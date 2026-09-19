"""The explicit Keep operation allowlist.

This is the architectural heart of the BFF. The console never names a Keep URL;
it names an *operation id*. Only operations declared here can reach Keep, and
each one carries the metadata the rest of the BFF needs:

  * the exact HTTP method and Keep path template
  * whether it mutates state
  * the minimum console role required
  * its reversibility tier (see core/autonomy.py)

Adding a Keep capability to the product is therefore a deliberate, reviewable
one-line change here rather than an emergent property of a pass-through proxy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Mapping


class Role(IntEnum):
    """Console roles, ordered by privilege."""

    VIEWER = 10
    OPERATOR = 20
    APPROVER = 30
    ADMIN = 40


ROLE_BY_NAME: Mapping[str, Role] = {
    "viewer": Role.VIEWER,
    "operator": Role.OPERATOR,
    "approver": Role.APPROVER,
    "admin": Role.ADMIN,
}


class Tier(IntEnum):
    """Reversibility tiers.

    Autonomy is gated on how hard an action is to undo, not on how urgent the
    alert was. A P1 incident does not make a destructive action safe.
    """

    # R0: reads nothing changes. Always allowed.
    READ_ONLY = 0
    # R1: self-reversing or trivially undone (acknowledge, comment, assign,
    # enrich, re-open). Allowed to execute without human approval.
    AUTO_REVERSIBLE = 1
    # R2: reversible with effort or with a side effect someone will notice
    # (run a remediation workflow, merge incidents, install a provider).
    # Requires an explicit approval step.
    EFFORT_REVERSIBLE = 2
    # R3: irreversible or destructive (delete alert/incident/rule/provider).
    # Requires approval from a second principal.
    IRREVERSIBLE = 3


@dataclass(frozen=True)
class Operation:
    id: str
    method: str
    path: str  # Keep path template, e.g. "/incidents/{incident_id}"
    tier: Tier
    min_role: Role
    summary: str
    # Path params that must be supplied by the caller.
    path_params: tuple[str, ...] = field(default_factory=tuple)
    # Query params the caller may pass through. Anything else is dropped.
    query_params: tuple[str, ...] = field(default_factory=tuple)
    # Whether a JSON body is forwarded.
    body: bool = False
    # Post the body as raw text rather than JSON. Keep's workflow endpoints
    # yaml.safe_load the request body, so JSON-encoding it would yield a string.
    raw_body: bool = False
    # The request body carries a client's credentials. Nothing may log it, echo
    # it back, or put it in the audit trail — the trail records WHO installed
    # WHAT, never the secret itself.
    secret_body: bool = False
    # A DELETE that only ends a reversible *state* rather than destroying a
    # durable record — closing a maintenance window is re-openable in one click.
    # Set deliberately, and only with a note, so it stays a reviewed exemption
    # from the "DELETE means tier 2 or higher" rule.
    restorable: bool = False

    @property
    def is_write(self) -> bool:
        return self.method.upper() not in {"GET", "HEAD"}


def _op(
    id: str,
    method: str,
    path: str,
    tier: Tier,
    min_role: Role,
    summary: str,
    *,
    path_params: tuple[str, ...] = (),
    query_params: tuple[str, ...] = (),
    body: bool = False,
    raw_body: bool = False,
    secret_body: bool = False,
    restorable: bool = False,
) -> Operation:
    return Operation(
        id=id,
        method=method,
        path=path,
        tier=tier,
        min_role=min_role,
        summary=summary,
        path_params=path_params,
        query_params=query_params,
        body=body,
        raw_body=raw_body,
        secret_body=secret_body,
        restorable=restorable,
    )


PAGING = ("limit", "offset")
ALERT_QUERY = PAGING + ("sort_by", "sort_dir", "cel")
INCIDENT_QUERY = PAGING + (
    "sorting",
    "candidate",
    "predicted",
    "cel",
    "status",
    "severity",
)

OPERATIONS: dict[str, Operation] = {
    op.id: op
    for op in [
        # ---------------------------------------------------------------- meta
        _op("keep.whoami", "GET", "/whoami", Tier.READ_ONLY, Role.VIEWER, "Resolve the Keep tenant id"),
        _op("keep.status", "GET", "/status", Tier.READ_ONLY, Role.VIEWER, "Keep readiness"),
        _op("keep.metrics", "GET", "/metrics", Tier.READ_ONLY, Role.VIEWER, "Prometheus metrics"),
        # -------------------------------------------------------------- alerts
        _op("alerts.list", "GET", "/alerts", Tier.READ_ONLY, Role.VIEWER, "List alerts", query_params=ALERT_QUERY),
        _op(
            "alerts.get",
            "GET",
            "/alerts/{fingerprint}",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Get one alert",
            path_params=("fingerprint",),
        ),
        _op(
            "alerts.history",
            "GET",
            "/alerts/{fingerprint}/history",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Alert history",
            path_params=("fingerprint",),
        ),
        _op(
            "alerts.audit",
            "GET",
            "/alerts/{fingerprint}/audit",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Alert audit trail",
            path_params=("fingerprint",),
        ),
        _op(
            "alerts.search",
            "POST",
            "/alerts/search",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Search alerts (CEL)",
            body=True,
        ),
        _op(
            "alerts.quality",
            "GET",
            "/alerts/quality/metrics",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Alert quality metrics",
            query_params=("fields",),
        ),
        _op(
            "alerts.enrich",
            "POST",
            "/alerts/enrich",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Attach enrichment to an alert",
            body=True,
        ),
        _op(
            "alerts.unenrich",
            "POST",
            "/alerts/unenrich",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Remove enrichment from an alert",
            body=True,
        ),
        _op(
            "alerts.assign",
            "POST",
            "/alerts/{fingerprint}/assign/{last_received}",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Assign an alert to the caller",
            path_params=("fingerprint", "last_received"),
        ),
        # ----------------------------------------------------------- incidents
        _op(
            "incidents.list",
            "GET",
            "/incidents",
            Tier.READ_ONLY,
            Role.VIEWER,
            "List incidents",
            query_params=INCIDENT_QUERY,
        ),
        _op("incidents.meta", "GET", "/incidents/meta", Tier.READ_ONLY, Role.VIEWER, "Incident facets"),
        _op(
            "incidents.get",
            "GET",
            "/incidents/{incident_id}",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Get one incident",
            path_params=("incident_id",),
        ),
        _op(
            "incidents.alerts",
            "GET",
            "/incidents/{incident_id}/alerts",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Alerts correlated into an incident",
            path_params=("incident_id",),
            query_params=PAGING,
        ),
        _op(
            "incidents.workflows",
            "GET",
            "/incidents/{incident_id}/workflows",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Workflow executions for an incident",
            path_params=("incident_id",),
            query_params=PAGING,
        ),
        _op(
            "incidents.create",
            "POST",
            "/incidents",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Create an incident",
            body=True,
        ),
        _op(
            "incidents.comment",
            "POST",
            "/incidents/{incident_id}/comment",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Comment on an incident",
            path_params=("incident_id",),
            body=True,
        ),
        _op(
            "incidents.status",
            "POST",
            "/incidents/{incident_id}/status",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Change incident status",
            path_params=("incident_id",),
            body=True,
        ),
        _op(
            "incidents.update",
            "PUT",
            "/incidents/{incident_id}",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Update incident fields",
            path_params=("incident_id",),
            body=True,
        ),
        _op(
            "incidents.confirm",
            "POST",
            "/incidents/{incident_id}/confirm",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Confirm a predicted incident",
            path_params=("incident_id",),
        ),
        _op(
            "incidents.add_alerts",
            "POST",
            "/incidents/{incident_id}/alerts",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Add alerts to an incident",
            path_params=("incident_id",),
            body=True,
        ),
        _op(
            "incidents.merge",
            "POST",
            "/incidents/merge",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Merge incidents",
            body=True,
        ),
        _op(
            "incidents.delete",
            "DELETE",
            "/incidents/{incident_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete an incident",
            path_params=("incident_id",),
        ),
        # ----------------------------------------------------------- workflows
        _op(
            "workflows.list",
            "GET",
            "/workflows",
            Tier.READ_ONLY,
            Role.VIEWER,
            "List workflows",
            query_params=("is_v2",),
        ),
        _op(
            "workflows.get",
            "GET",
            "/workflows/{workflow_id}",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Get a workflow",
            path_params=("workflow_id",),
        ),
        _op(
            "workflows.raw",
            "GET",
            "/workflows/{workflow_id}/raw",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Workflow YAML",
            path_params=("workflow_id",),
        ),
        _op(
            "workflows.runs",
            "GET",
            "/workflows/{workflow_id}/runs",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Workflow run history",
            path_params=("workflow_id",),
            query_params=PAGING + ("status",),
        ),
        _op(
            "workflows.run_status",
            "GET",
            "/workflows/{workflow_id}/runs/{workflow_execution_id}",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Single workflow run",
            path_params=("workflow_id", "workflow_execution_id"),
        ),
        _op(
            "workflows.executions",
            "GET",
            "/workflows/executions",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Executions by alert fingerprint",
            query_params=PAGING + ("alert_fingerprint",),
        ),
        # Running a workflow reaches into a customer estate: R2, approver-gated.
        _op(
            "workflows.run",
            "POST",
            "/workflows/{workflow_id}/run",
            Tier.EFFORT_REVERSIBLE,
            Role.OPERATOR,
            "Execute a workflow",
            path_params=("workflow_id",),
            body=True,
        ),
        # Authoring, so the console is not a read-only viewer onto Keep.
        _op(
            "workflows.create",
            "POST",
            "/workflows/json",
            Tier.EFFORT_REVERSIBLE,
            Role.OPERATOR,
            "Create a workflow from YAML",
            body=True,
            raw_body=True,
        ),
        _op(
            "workflows.update",
            "PUT",
            "/workflows/{workflow_id}",
            Tier.EFFORT_REVERSIBLE,
            Role.OPERATOR,
            "Replace a workflow's definition",
            path_params=("workflow_id",),
            body=True,
            raw_body=True,
        ),
        _op(
            "workflows.delete",
            "DELETE",
            "/workflows/{workflow_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete a workflow",
            path_params=("workflow_id",),
        ),
        # ----------------------------------------------------------- providers
        _op("providers.list", "GET", "/providers", Tier.READ_ONLY, Role.VIEWER, "Installed + available providers"),
        _op(
            "providers.logs",
            "GET",
            "/providers/{provider_type}/{provider_id}/logs",
            Tier.READ_ONLY,
            Role.OPERATOR,
            "Provider logs",
            path_params=("provider_type", "provider_id"),
        ),
        _op(
            "providers.test",
            "POST",
            "/providers/test",
            Tier.READ_ONLY,
            Role.OPERATOR,
            "Test provider credentials",
            body=True,
            secret_body=True,
        ),
        _op(
            "providers.webhook",
            "GET",
            "/providers/{provider_type}/webhook",
            Tier.READ_ONLY,
            Role.OPERATOR,
            "How to push alerts from this source into Keep",
            path_params=("provider_type",),
            query_params=("provider_id",),
        ),
        _op(
            "providers.install",
            "POST",
            "/providers/install",
            Tier.EFFORT_REVERSIBLE,
            Role.ADMIN,
            "Install a provider",
            body=True,
            secret_body=True,
        ),
        _op(
            "providers.delete",
            "DELETE",
            "/providers/{provider_type}/{provider_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Uninstall a provider",
            path_params=("provider_type", "provider_id"),
        ),
        # ------------------------------------------------------------------ AI
        _op("ai.stats", "GET", "/ai/stats", Tier.READ_ONLY, Role.VIEWER, "AI layer stats and model configs"),
        _op(
            "ai.settings",
            "PUT",
            "/ai/{algorithm_id}/settings",
            Tier.EFFORT_REVERSIBLE,
            Role.OPERATOR,
            "Tune or enable an AI correlation model",
            path_params=("algorithm_id",),
            body=True,
        ),
        # ------------------------------------------------------------- presets
        _op("presets.list", "GET", "/preset", Tier.READ_ONLY, Role.VIEWER, "List presets"),
        _op(
            "presets.alerts",
            "GET",
            "/preset/{preset_name}/alerts",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Alerts for a preset",
            path_params=("preset_name",),
            query_params=PAGING,
        ),
        # A preset is a saved alert filter. It routes nothing, suppresses
        # nothing and fires nothing — it decides what a person is looking at —
        # so it sits at tier 1 alongside the dashboards that display it.
        _op(
            "presets.create",
            "POST",
            "/preset",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Create a saved alert view",
            body=True,
        ),
        _op(
            "presets.update",
            "PUT",
            "/preset/{preset_id}",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Update a saved alert view",
            path_params=("preset_id",),
            body=True,
        ),
        # Deleting one is gated a step higher than creating it because dashboard
        # widgets reference a preset by name: removing it silently empties every
        # tile built on it, in dashboards the deleter may never look at.
        _op(
            "presets.delete",
            "DELETE",
            "/preset/{preset_id}",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Delete a saved alert view",
            path_params=("preset_id",),
        ),
        # ------------------------------------------- correlation & suppression
        _op("rules.list", "GET", "/rules", Tier.READ_ONLY, Role.VIEWER, "Correlation rules"),
        _op(
            "rules.create",
            "POST",
            "/rules",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Create a correlation rule",
            body=True,
        ),
        _op(
            "rules.update",
            "PUT",
            "/rules/{rule_id}",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Update a correlation rule",
            path_params=("rule_id",),
            body=True,
        ),
        _op(
            "rules.delete",
            "DELETE",
            "/rules/{rule_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete a correlation rule",
            path_params=("rule_id",),
        ),
        _op("dedup.list", "GET", "/deduplications", Tier.READ_ONLY, Role.VIEWER, "Deduplication rules + stats"),
        _op("dedup.fields", "GET", "/deduplications/fields", Tier.READ_ONLY, Role.VIEWER, "Deduplication fields"),
        _op(
            "dedup.create",
            "POST",
            "/deduplications",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Create a deduplication rule",
            body=True,
        ),
        _op(
            "dedup.delete",
            "DELETE",
            "/deduplications/{rule_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete a deduplication rule",
            path_params=("rule_id",),
        ),
        _op("maintenance.list", "GET", "/maintenance", Tier.READ_ONLY, Role.VIEWER, "Maintenance windows"),
        _op(
            "maintenance.create",
            "POST",
            "/maintenance",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Open a maintenance window",
            body=True,
        ),
        _op(
            "maintenance.delete",
            "DELETE",
            "/maintenance/{rule_id}",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Close a maintenance window",
            path_params=("rule_id",),
            restorable=True,
        ),
        # ------------------------------------------------------------ topology
        _op("topology.get", "GET", "/topology", Tier.READ_ONLY, Role.VIEWER, "Service topology", query_params=("provider_ids", "services", "environment")),
        _op("topology.applications", "GET", "/topology/applications", Tier.READ_ONLY, Role.VIEWER, "Topology applications"),
        # Topology writes are R2 rather than R1 even though a service or edge is
        # trivially deleted again. The reason is not how hard they are to undo
        # but what they feed: the dependency graph is what the investigation
        # engine uses to tell a cause from a victim, so a wrong edge produces a
        # confidently wrong root cause — and that reaches a client as an
        # incident report, which is not reversible at all.
        _op(
            "topology.create_service",
            "POST",
            "/topology/service",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Declare a service in the topology",
            body=True,
        ),
        _op(
            "topology.create_dependency",
            "POST",
            "/topology/dependency",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Declare that one service depends on another",
            body=True,
        ),
        _op(
            "topology.delete_services",
            "DELETE",
            "/topology/services",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete services from the topology",
            body=True,
        ),
        # ------------------------------------------------------------ dashboards
        _op("dashboards.list", "GET", "/dashboard", Tier.READ_ONLY, Role.VIEWER, "Saved dashboards"),
        _op(
            "dashboards.widgets",
            "GET",
            "/dashboard/metric-widgets",
            Tier.READ_ONLY,
            Role.VIEWER,
            "Metric widgets available to dashboards",
        ),
        # Saving a dashboard touches nothing in the estate: it changes no alert
        # routing, runs no remediation, and is undone by editing it back. That
        # is tier 1 on the reversibility test, and gating it any higher would
        # mean an approval round-trip per drag, which is how a builder becomes
        # a thing nobody uses.
        _op(
            "dashboards.create",
            "POST",
            "/dashboard",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Create a dashboard",
            body=True,
        ),
        _op(
            "dashboards.update",
            "PUT",
            "/dashboard/{dashboard_id}",
            Tier.AUTO_REVERSIBLE,
            Role.OPERATOR,
            "Update a dashboard",
            path_params=("dashboard_id",),
            body=True,
        ),
        # Deleting one destroys a layout somebody built, and Keep has no undo.
        # It sits at tier 2 rather than 3 because the BFF snapshots the config
        # into the audit record before the call, so the layout is genuinely
        # recoverable — the tier is earned by that snapshot, not assumed.
        _op(
            "dashboards.delete",
            "DELETE",
            "/dashboard/{dashboard_id}",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Delete a dashboard",
            path_params=("dashboard_id",),
        ),
        # ------------------------------------------------------------------ tags
        _op("tags.list", "GET", "/tags", Tier.READ_ONLY, Role.VIEWER, "Alert tags"),
        # -------------------------------------------------------------- mapping
        _op("mapping.list", "GET", "/mapping", Tier.READ_ONLY, Role.VIEWER, "Enrichment mapping rules"),
        _op(
            "mapping.create",
            "POST",
            "/mapping",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Create a mapping rule",
            body=True,
        ),
        _op(
            "mapping.delete",
            "DELETE",
            "/mapping/{rule_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete a mapping rule",
            path_params=("rule_id",),
        ),
        _op("extraction.list", "GET", "/extraction", Tier.READ_ONLY, Role.VIEWER, "Extraction rules"),
        _op(
            "extraction.create",
            "POST",
            "/extraction",
            Tier.EFFORT_REVERSIBLE,
            Role.APPROVER,
            "Create an extraction rule",
            body=True,
        ),
        _op(
            "extraction.delete",
            "DELETE",
            "/extraction/{rule_id}",
            Tier.IRREVERSIBLE,
            Role.ADMIN,
            "Delete an extraction rule",
            path_params=("rule_id",),
        ),
    ]
}


class OperationNotAllowed(KeyError):
    """Raised when an operation id is not in the allowlist."""


def get_operation(op_id: str) -> Operation:
    try:
        return OPERATIONS[op_id]
    except KeyError as exc:  # pragma: no cover - trivial
        raise OperationNotAllowed(op_id) from exc


def operations_for_role(role: Role) -> list[Operation]:
    return [op for op in OPERATIONS.values() if op.min_role <= role]
