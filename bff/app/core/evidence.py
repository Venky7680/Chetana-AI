"""The evidence gateway: the only way HolmesGPT is allowed to see the estate.

Out of the box, HolmesGPT investigates by calling the estate directly — kubectl,
Prometheus, cloud APIs — using credentials mounted into its container. That is
fine for a single team debugging its own cluster. It is not fine for an MSP:
the operation allowlist would govern Chetana -> Keep while an LLM ran
unsupervised queries against a client's production estate with standing
credentials, and no amount of "it's read-only by default" survives a bank's
security review.

So Holmes gets no estate credentials at all. Instead:

  1. Starting an investigation mints a token scoped to *that investigation* —
     one tenant, a fixed set of read-only tools, a short expiry.
  2. The token is passed to Holmes as an HTTP header on the request. Holmes'
     header propagation makes it available to toolsets as
     `request_context.headers`, so each curl carries it back to us.
  3. Every call lands here: token verified, tenant resolved, tool matched to an
     allowlisted R0 operation, budget decremented, result recorded.

Note the header name. Holmes strips `Authorization`, `Cookie` and `Set-Cookie`
from propagation by default, so the token must travel under a name of its own.

Three properties fall out of this, and they are the reason for the design:

  * Holmes cannot reach anything the allowlist does not already permit.
  * Every read is attributed to an investigation, a tenant and a user.
  * The console's evidence chain is built from what the gateway *served*, not
    from what the model *said* it did. A hallucinated tool call has no row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping

import jwt

EVIDENCE_ISSUER = "chetana-evidence"
EVIDENCE_HEADER = "X-Chetana-Evidence-Token"


class EvidenceTokenError(Exception):
    pass


@dataclass(frozen=True)
class EvidenceParam:
    name: str
    description: str
    required: bool = False
    default: str | None = None


@dataclass(frozen=True)
class EvidenceTool:
    """One read Holmes may perform, and how it maps onto something allowlisted.

    `operation_id` must name an R0 entry in the operation allowlist — this is
    asserted at import time below, so a future edit cannot quietly widen what an
    LLM can reach.
    """

    name: str
    description: str
    # "precedent" reaches no client system at all — see core/precedents.
    kind: Literal["keep", "prometheus", "precedent"]
    params: tuple[EvidenceParam, ...] = field(default_factory=tuple)
    operation_id: str | None = None
    # Which params become path params on the Keep operation.
    path_params: tuple[str, ...] = field(default_factory=tuple)
    # Fixed query params merged into every call.
    fixed_query: Mapping[str, Any] = field(default_factory=dict)
    # Param -> Keep query param name.
    query_map: Mapping[str, str] = field(default_factory=dict)
    prometheus_path: str | None = None


_TOOLS: tuple[EvidenceTool, ...] = (
    EvidenceTool(
        name="get_incident",
        description=(
            "Get one incident: its name, summary, severity, status, affected "
            "services, and when it started. Use this first to understand what "
            "you are investigating."
        ),
        kind="keep",
        operation_id="incidents.get",
        params=(EvidenceParam("incident_id", "The incident id", required=True),),
        path_params=("incident_id",),
    ),
    EvidenceTool(
        name="get_incident_alerts",
        description=(
            "List the alerts that were correlated into an incident, with their "
            "labels, severity, source and firing times. This is the primary "
            "evidence for what actually happened."
        ),
        kind="keep",
        operation_id="incidents.alerts",
        params=(
            EvidenceParam("incident_id", "The incident id", required=True),
            EvidenceParam("limit", "Maximum alerts to return", default="50"),
        ),
        path_params=("incident_id",),
        query_map={"limit": "limit"},
    ),
    EvidenceTool(
        name="get_incident_workflow_runs",
        description=(
            "List automation that already ran against this incident, and whether "
            "it succeeded. Check this before recommending an action — it may "
            "already have been attempted."
        ),
        kind="keep",
        operation_id="incidents.workflows",
        params=(EvidenceParam("incident_id", "The incident id", required=True),),
        path_params=("incident_id",),
    ),
    EvidenceTool(
        name="search_alerts",
        description=(
            "Search alerts across the estate with a CEL filter, for example "
            "service == 'payments-api' or severity == 'critical'. Use it to find "
            "related activity outside this incident, or to check whether the same "
            "symptom appeared before."
        ),
        kind="keep",
        operation_id="alerts.list",
        params=(
            EvidenceParam("cel", "CEL filter expression", required=True),
            EvidenceParam("limit", "Maximum alerts to return", default="50"),
        ),
        query_map={"cel": "cel", "limit": "limit"},
    ),
    EvidenceTool(
        name="get_topology",
        description=(
            "Get the service topology: which services exist and which depend on "
            "which. Use it to work out whether a failing service is a cause or a "
            "victim of something upstream."
        ),
        kind="keep",
        operation_id="topology.get",
    ),
    EvidenceTool(
        name="prometheus_instant_query",
        description=(
            "Run an instant PromQL query against this tenant's Prometheus and "
            "return the current value. Use it to check a metric right now, for "
            "example rate(http_requests_total{status=~'5..'}[5m])."
        ),
        kind="prometheus",
        prometheus_path="/api/v1/query",
        params=(EvidenceParam("query", "PromQL expression", required=True),),
        query_map={"query": "query"},
    ),
    EvidenceTool(
        name="prometheus_range_query",
        description=(
            "Run a PromQL query over a time window ending now and return the "
            "series. Use it to see whether a metric changed before the incident "
            "started, which is usually what separates cause from symptom. "
            "'minutes' is how far back to look. The response carries a "
            "'data_horizon' block giving the window you asked for and the window "
            "actually returned: metric storage has finite retention, so a long "
            "window can come back silently truncated. Always check data_horizon "
            "before claiming anything about what happened before a given time — "
            "the oldest sample may simply be the edge of retention."
        ),
        kind="prometheus",
        prometheus_path="/api/v1/query_range",
        params=(
            EvidenceParam("query", "PromQL expression", required=True),
            EvidenceParam("minutes", "How many minutes back to look", default="60"),
            EvidenceParam("step", "Resolution, e.g. 60s", default="60s"),
        ),
        query_map={"query": "query", "step": "step"},
    ),
    # The only tool that reaches no client system at all. It searches a corpus
    # of past ticket resolutions built offline, so there is nothing to scope and
    # nothing to leak — and correspondingly no allowlist operation behind it.
    EvidenceTool(
        name="search_resolution_precedents",
        description=(
            "Search past service-desk tickets for symptoms like this one and see "
            "how they were resolved. Use it early to get a hypothesis quickly, "
            "then confirm or reject it with metrics and topology — a precedent "
            "is a lead, never a conclusion. Every result says whether the ticket "
            "history is real or synthetic, and you must repeat that in your "
            "finding if you rely on it."
        ),
        kind="precedent",
        params=(
            EvidenceParam(
                "symptom",
                "What is going wrong, in plain words: 'certificate expired', "
                "'disk near capacity', 'pods crashlooping'",
                required=True,
            ),
            EvidenceParam(
                "ci_class",
                "Optional component class to weight the search towards, such as "
                "AzureVM, Printer, VPN-tunnel or K8s-node",
            ),
            EvidenceParam("limit", "Maximum precedents to return", default="5"),
        ),
    ),
)

TOOLS: Mapping[str, EvidenceTool] = {t.name: t for t in _TOOLS}
ALL_TOOL_NAMES: tuple[str, ...] = tuple(TOOLS)


def get_tool(name: str) -> EvidenceTool:
    try:
        return TOOLS[name]
    except KeyError as exc:
        raise KeyError(f"'{name}' is not an evidence tool") from exc


def _assert_read_only() -> None:
    """Fail at import if an evidence tool ever points at a write operation.

    Cheap insurance: the whole safety argument rests on these being R0, and a
    one-word typo in the allowlist would otherwise hand an LLM a write.
    """
    from .allowlist import Tier, get_operation

    for tool in _TOOLS:
        if tool.operation_id is None:
            continue
        operation = get_operation(tool.operation_id)
        if operation.tier != Tier.READ_ONLY or operation.is_write:
            raise RuntimeError(
                f"evidence tool '{tool.name}' points at non-read operation "
                f"'{tool.operation_id}' (tier R{int(operation.tier)})"
            )


_assert_read_only()


# ------------------------------------------------------------------- tokens
@dataclass(frozen=True)
class EvidenceGrant:
    investigation_id: str
    tenant_id: str
    tools: tuple[str, ...]

    def permits(self, tool_name: str) -> bool:
        return tool_name in self.tools


def mint_token(
    *,
    secret: str,
    algorithm: str,
    investigation_id: str,
    tenant_id: str,
    tools: tuple[str, ...],
    ttl_seconds: int,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": EVIDENCE_ISSUER,
        "sub": investigation_id,
        "tenant": tenant_id,
        "tools": list(tools),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def verify_token(*, secret: str, algorithm: str, token: str) -> EvidenceGrant:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[algorithm], issuer=EVIDENCE_ISSUER
        )
    except jwt.ExpiredSignatureError as exc:
        raise EvidenceTokenError("evidence token has expired") from exc
    except jwt.InvalidTokenError as exc:
        # A console session token lands here too: different issuer, so it is
        # rejected. The two token families are deliberately not interchangeable.
        raise EvidenceTokenError("invalid evidence token") from exc

    tenant = str(payload.get("tenant") or "").strip()
    subject = str(payload.get("sub") or "").strip()
    if not tenant or not subject:
        raise EvidenceTokenError("evidence token is missing its scope")

    return EvidenceGrant(
        investigation_id=subject,
        tenant_id=tenant,
        tools=tuple(payload.get("tools") or ()),
    )


def describe_tools() -> list[dict[str, Any]]:
    """What the console shows under Governance, so the tools an LLM may call are
    as inspectable as the operation allowlist itself."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "kind": tool.kind,
            "operation_id": tool.operation_id,
            "parameters": [
                {
                    "name": p.name,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in tool.params
            ],
        }
        for tool in _TOOLS
    ]
