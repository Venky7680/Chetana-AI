"""Providers, correlation rules, deduplication, maintenance, topology, presets.

These are the parts of Keep that make it more than an alert list: how telemetry
gets in, how it collapses, and what gets suppressed. Every one goes through the
gateway, so the same tiers and audit apply.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from ..core.dashboards import DashboardConfig, to_keep_config
from ..deps import GatewayDep, PrincipalDep, TenantDep

router = APIRouter(tags=["platform"])


def _as_list(value: Any) -> list[Any]:
    """Guarantee a list to the console, whatever Keep returned.

    Several Keep endpoints return a bare list in one version and an envelope or
    a mapping in another. The browser then calls .map on a non-array, throws,
    and React unmounts the whole page — a blank screen caused by a shape, not a
    failure. Normalising here means a surprise degrades to an empty section.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "results", "data", "rules", "dashboards", "widgets"):
            inner = value.get(key)
            if isinstance(inner, list):
                return inner
        # A mapping of id -> object is still a collection of objects.
        if value and all(isinstance(v, dict) for v in value.values()):
            return list(value.values())
    return []


def _reason(exc: BaseException) -> str:
    """A failure a human can act on, rather than a stack trace or a silent [].

    Several of these endpoints fan out to two Keep calls. Previously a failure
    on either side became an empty list, so "Keep rejected this request" and
    "nothing is configured" rendered identically. They are very different
    problems and the console now says which one it is.
    """
    detail = getattr(exc, "detail", None)
    status = getattr(exc, "status_code", None)
    if detail and status:
        return f"{status}: {detail}"
    return str(detail or exc) or exc.__class__.__name__


# --------------------------------------------------------------------- providers
@router.get("/providers")
async def providers(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    payload = await gateway.execute(
        "providers.list", principal=principal, tenant=tenant
    )
    if not isinstance(payload, dict):
        return {"installed_providers": [], "available_count": 0, "categories": []}

    installed = payload.get("installed_providers") or []
    available = payload.get("providers") or []
    return {
        "installed_providers": installed,
        "available_count": len(available),
        # The full catalogue is ~100 entries; only send it when it is asked for.
        "categories": sorted(
            {
                c
                for p in available
                if isinstance(p, dict)
                for c in (p.get("categories") or [])
            }
        ),
    }


@router.get("/providers/catalogue")
async def provider_catalogue(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> list[dict[str, Any]]:
    payload = await gateway.execute(
        "providers.list", principal=principal, tenant=tenant
    )
    catalogue = payload.get("providers", []) if isinstance(payload, dict) else []
    # Keep already describes each provider completely: its fields and their
    # hints, the scopes the credential must carry, whether it can receive a
    # webhook, whether it can be polled. An earlier version of this projection
    # kept four booleans and dropped the rest, which is why the install form
    # here was so much poorer than Keep's own. Pass it through.
    return [
        {
            "type": p.get("type"),
            "display_name": p.get("display_name") or p.get("type"),
            "description": p.get("provider_description") or "",
            "categories": p.get("categories") or [],
            "tags": p.get("tags") or [],
            "can_setup_webhook": bool(p.get("can_setup_webhook")),
            "supports_webhook": bool(p.get("supports_webhook")),
            "webhook_required": bool(p.get("webhook_required")),
            "can_query": bool(p.get("can_query")),
            "can_notify": bool(p.get("can_notify")),
            "pulling_available": bool(p.get("pulling_available")),
            "coming_soon": bool(p.get("coming_soon")),
            # Field name -> {description, hint, required, sensitive, type, default}.
            "config": p.get("config") or {},
            # What the credential must be allowed to do. Showing this before the
            # form is filled in saves the round trip where someone pastes a
            # read-only token and finds out from a 412 ten minutes later.
            "scopes": _as_list(p.get("scopes")),
            "docs_slug": p.get("docs_slug"),
        }
        for p in catalogue
        if isinstance(p, dict)
    ]


@router.get("/providers/{provider_type}/webhook")
async def provider_webhook(
    provider_type: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    provider_id: str | None = None,
) -> Any:
    """The "push alerts from X into Keep" instructions, per provider.

    Many sources are connected by pointing them at a webhook rather than by
    giving Keep a credential. Keep renders per-provider instructions with the
    URL and key already substituted; this hands them to the console so the
    whole path — including "here is exactly what to paste into Graylog" —
    happens without anyone opening Keep.

    The response contains a Keep-issued webhook key. That key is the thing the
    user must copy into the source, so it is displayed on purpose. It is a GET,
    so nothing writes it to the audit trail.
    """
    payload = await gateway.execute(
        "providers.webhook",
        principal=principal,
        tenant=tenant,
        path_params={"provider_type": provider_type},
        query_params={"provider_id": provider_id} if provider_id else None,
    )
    if not isinstance(payload, dict):
        return {"markdown": None, "description": None, "template": None}
    return {
        "markdown": payload.get("webhookMarkdown"),
        "description": payload.get("webhookDescription"),
        "template": payload.get("webhookTemplate"),
    }


@router.post("/providers/test")
async def test_provider(
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    body: dict[str, Any] = Body(...),
) -> Any:
    return await gateway.execute(
        "providers.test", principal=principal, tenant=tenant, body=body
    )


class ProviderInstall(BaseModel):
    """Install a telemetry source for this client.

    The credential fields differ per provider (124 of them), so `config` is an
    open map validated by Keep rather than by us — Keep knows each provider's
    schema and returns 412 when a scope check fails, which is a better error
    than anything we could invent.

    The values here are a client's credentials. They are forwarded to Keep,
    which stores them in its own secret manager, and they are never logged,
    echoed back, written to the audit trail, or kept in the approval ledger.
    The operation is marked `secret_body` in the allowlist, which is what
    enforces all of that.
    """

    provider_id: str = Field(min_length=1, max_length=128)
    provider_name: str = Field(min_length=1, max_length=128)
    provider_type: str | None = None
    pulling_enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None
    reason: str = ""


@router.post("/providers/install")
async def install_provider(
    payload: ProviderInstall,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    # Keep's endpoint takes a flat object: the reserved keys plus the config
    # fields alongside them, not nested.
    body: dict[str, Any] = {
        "provider_id": payload.provider_id,
        "provider_name": payload.provider_name,
        "provider_type": payload.provider_type or payload.provider_id,
        "pulling_enabled": payload.pulling_enabled,
        **payload.config,
    }
    return await gateway.execute(
        "providers.install",
        principal=principal,
        tenant=tenant,
        body=body,
        approval_id=payload.approval_id,
        note=payload.reason or f"Install {payload.provider_name}",
    )


@router.delete("/providers/{provider_type}/{provider_id}")
async def uninstall_provider(
    provider_type: str,
    provider_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "providers.delete",
        principal=principal,
        tenant=tenant,
        path_params={"provider_type": provider_type, "provider_id": provider_id},
        approval_id=approval_id,
        note=f"Uninstall {provider_type}/{provider_id}",
    )


# --------------------------------------------------------------------------- AI
#
# Keep's AI layer is reachable over REST after all. The endpoints are marked
# include_in_schema=False, so they never appear in Keep's API docs — which is
# why an earlier version of this console said they did not exist and sent people
# to Keep's own UI. They are real, and verified against Keep's source.
@router.get("/ai")
async def ai_stats(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    payload = await gateway.execute("ai.stats", principal=principal, tenant=tenant)
    if not isinstance(payload, dict):
        return {"algorithm_configs": [], "alerts_count": 0, "incidents_count": 0}
    return {
        "alerts_count": payload.get("alerts_count") or 0,
        "incidents_count": payload.get("incidents_count") or 0,
        "first_alert_datetime": payload.get("first_alert_datetime"),
        "algorithm_configs": _as_list(payload.get("algorithm_configs")),
    }


class AiSettings(BaseModel):
    """Keep wants the whole config object back, not a patch.

    The console therefore reads the current object from /ai, changes the
    settings array, and sends the object back unchanged in every other respect.
    """

    config: dict[str, Any]
    approval_id: str | None = None
    reason: str = ""


@router.put("/ai/{algorithm_id}/settings")
async def update_ai_settings(
    algorithm_id: str,
    payload: AiSettings,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "ai.settings",
        principal=principal,
        tenant=tenant,
        path_params={"algorithm_id": algorithm_id},
        body=payload.config,
        approval_id=payload.approval_id,
        note=payload.reason or f"Tune AI model {algorithm_id}",
    )


# -------------------------------------------------------------- correlation rules
@router.get("/rules")
async def correlation_rules(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> list[Any]:
    return _as_list(
        await gateway.execute("rules.list", principal=principal, tenant=tenant)
    )


class CorrelationRule(BaseModel):
    """A Keep correlation rule: a CEL predicate plus a time window.

    Creating one changes how every future alert is grouped for this client, so
    it is tier 2 — approver-gated, or parked.
    """

    ruleName: str = Field(min_length=1, alias="name")
    # Keep requires sqlQuery.sql to be non-empty and sqlQuery.params to be a
    # dict, but rulesengine.py matches on definition_cel and never executes the
    # SQL. Left empty, Keep answers 400 "SQL is required"; with params as a list
    # it answers 400 "Params are required". Filled in below from the CEL.
    sqlQuery: dict[str, Any] | None = None
    celQuery: str = Field(min_length=1, alias="cel")
    timeframeInSeconds: int = Field(
        default=900, ge=60, le=86400, alias="timeframe_seconds"
    )
    timeUnit: str = Field(default="seconds", alias="time_unit")
    groupingCriteria: list[str] = Field(default_factory=list, alias="grouping")
    requireApprove: bool = Field(default=False, alias="require_approve")
    resolveOn: str = Field(default="never", alias="resolve_on")
    createOn: str = Field(default="any", alias="create_on")
    incidentNameTemplate: str = Field(default="", alias="incident_name_template")
    incidentPrefix: str = Field(default="", alias="incident_prefix")
    threshold: int = Field(default=1, ge=1)
    approval_id: str | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _mirror_cel_into_sql(self) -> "CorrelationRule":
        """Give Keep a stored SQL definition that says the same thing as the CEL.

        A dummy like "1=1" would pass validation, but anyone reading the rule in
        Keep's own UI would see a rule that appears to match everything. Carrying
        the CEL across as a single bound parameter keeps the record honest and
        cannot match anything by accident, because it is never executed.
        """
        if not self.sqlQuery or not self.sqlQuery.get("sql"):
            self.sqlQuery = {"sql": "(:cel)", "params": {"cel": self.celQuery}}
        params = self.sqlQuery.get("params")
        if not isinstance(params, dict):
            self.sqlQuery["params"] = {}
        return self


@router.post("/rules")
async def create_rule(
    payload: CorrelationRule,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    body = payload.model_dump(by_alias=True, exclude={"approval_id"}, exclude_none=True)
    return await gateway.execute(
        "rules.create",
        principal=principal,
        tenant=tenant,
        body=body,
        approval_id=payload.approval_id,
        note=f"create correlation rule '{payload.ruleName}'",
    )


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "rules.delete",
        principal=principal,
        tenant=tenant,
        path_params={"rule_id": rule_id},
        approval_id=approval_id,
        note=f"delete correlation rule {rule_id}",
    )


# ---------------------------------------------------------------- deduplication
@router.get("/deduplications")
async def deduplications(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    rules, fields = await asyncio.gather(
        gateway.execute("dedup.list", principal=principal, tenant=tenant),
        gateway.execute("dedup.fields", principal=principal, tenant=tenant),
        return_exceptions=True,
    )
    problems: list[str] = []
    if isinstance(rules, BaseException):
        problems.append(f"deduplication rules: {_reason(rules)}")
    if isinstance(fields, BaseException):
        problems.append(f"deduplication fields: {_reason(fields)}")
    return {
        "rules": [] if isinstance(rules, BaseException) else _as_list(rules),
        "fields": {} if isinstance(fields, BaseException) else fields,
        "problems": problems,
    }


# ------------------------------------------------------------------ maintenance
@router.get("/maintenance")
async def maintenance(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> list[Any]:
    return _as_list(
        await gateway.execute("maintenance.list", principal=principal, tenant=tenant)
    )


class MaintenanceWindow(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    cel_query: str = Field(min_length=1)
    start_time: str
    duration_seconds: int = Field(ge=60, le=60 * 60 * 24 * 30)
    enabled: bool = True
    suppress: bool = True


@router.post("/maintenance")
async def create_maintenance(
    payload: MaintenanceWindow,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "maintenance.create",
        principal=principal,
        tenant=tenant,
        body=payload.model_dump(exclude_none=True),
    )


@router.delete("/maintenance/{rule_id}")
async def close_maintenance(
    rule_id: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    return await gateway.execute(
        "maintenance.delete",
        principal=principal,
        tenant=tenant,
        path_params={"rule_id": rule_id},
    )


# --------------------------------------------------------------------- topology
@router.get("/topology")
async def topology(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    services, applications = await asyncio.gather(
        gateway.execute("topology.get", principal=principal, tenant=tenant),
        gateway.execute("topology.applications", principal=principal, tenant=tenant),
        return_exceptions=True,
    )
    problems: list[str] = []
    if isinstance(services, BaseException):
        problems.append(f"services: {_reason(services)}")
    if isinstance(applications, BaseException):
        problems.append(f"applications: {_reason(applications)}")
    return {
        "services": [] if isinstance(services, BaseException) else _as_list(services),
        "applications": []
        if isinstance(applications, BaseException)
        else _as_list(applications),
        "problems": problems,
    }


class TopologyServiceIn(BaseModel):
    """A service declared by hand.

    Keep normally discovers topology from a provider that exposes a service map.
    Plenty of estates have no such provider — and the MSP usually knows the
    dependency graph anyway, from the CMDB or from having built the thing. Keep
    marks manually created services so they stay distinguishable from
    discovered ones.
    """

    service: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    environment: str = "unknown"
    description: str | None = None
    team: str | None = None
    email: str | None = None
    slack: str | None = None
    category: str | None = None
    namespace: str | None = None
    tags: list[str] | None = None
    approval_id: str | None = None
    reason: str = ""


class TopologyDependencyIn(BaseModel):
    """`service_id` calls `depends_on_service_id`.

    Direction matters and is easy to invert. Read it as "the caller depends on
    the callee": payments-api depends on ledger-worker, so payments-api is
    service_id. Getting this backwards makes the investigation engine blame the
    victim.
    """

    service_id: int
    depends_on_service_id: int
    protocol: str = "unknown"
    approval_id: str | None = None
    reason: str = ""


@router.post("/topology/services")
async def create_topology_service(
    payload: TopologyServiceIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    body = payload.model_dump(exclude_none=True, exclude={"approval_id", "reason"})
    return await gateway.execute(
        "topology.create_service",
        principal=principal,
        tenant=tenant,
        body=body,
        approval_id=payload.approval_id,
        note=payload.reason,
    )


@router.post("/topology/dependencies")
async def create_topology_dependency(
    payload: TopologyDependencyIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    body = payload.model_dump(exclude={"approval_id", "reason"})
    return await gateway.execute(
        "topology.create_dependency",
        principal=principal,
        tenant=tenant,
        body=body,
        approval_id=payload.approval_id,
        note=payload.reason,
    )


@router.delete("/topology/services")
async def delete_topology_services(
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    ids: str,
    approval_id: str | None = None,
) -> Any:
    """`ids` is a comma-separated list, because a DELETE body is not portable.

    Keep takes a list of numeric service ids. Anything non-numeric is dropped
    rather than forwarded, so a malformed id cannot become part of a request
    that deletes something else.
    """
    parsed = [int(part) for part in ids.split(",") if part.strip().isdigit()]
    if not parsed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No valid service ids given")
    return await gateway.execute(
        "topology.delete_services",
        principal=principal,
        tenant=tenant,
        body=parsed,
        approval_id=approval_id,
        note=f"Delete {len(parsed)} topology service(s)",
    )


# ------------------------------------------------- derived from ticket history
#
# Both of these are read from files built offline by ops/precedents from an ITSM
# export. They are suggestions for a person to approve, never applied on their
# own — the point of generating them was to save someone an afternoon in a
# spreadsheet, not to let a CSV quietly configure a client's alert routing.
def _insights(request: Request, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
    store = getattr(request.app.state, "corpora", None)
    return store.sidecars(tenant_id) if store else {}


@router.get("/mapping/suggestions")
async def mapping_suggestions(
    request: Request, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    """Proposed CI-class routing, split by whether it is safe to apply blind.

    The split is the useful part. A CI class whose tickets route to one team
    almost every time is a rule; one that splits between two teams routes by
    *symptom* rather than by component, and a rule there would mis-route roughly
    half of them — quietly, and in the direction of whichever team was more
    common in the export.
    """
    data = _insights(request, tenant.id)
    return {
        "ready": data.get("mapping_rows", []),
        "needs_review": data.get("mapping_needs_review", []),
    }


@router.get("/runbooks/candidates")
async def runbook_candidates(
    request: Request, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    """Repeatable fixes found in closed tickets, with a proposed tier.

    Nothing here is wired to anything. It is the review surface auto-remediation
    needs before a line of it is written: what recurs often enough to be worth
    automating, and — the question that actually decides the tier — what could
    not be undone afterwards.
    """
    items = _insights(request, tenant.id).get("runbook_candidates", [])
    tiers: dict[str, dict[str, int]] = {}
    for item in items:
        tier = str(item.get("tier") or "?")
        bucket = tiers.setdefault(tier, {"runbooks": 0, "tickets": 0})
        bucket["runbooks"] += 1
        bucket["tickets"] += int(item.get("tickets") or 0)
    return {"items": items, "by_tier": tiers}


# ---------------------------------------------------------------------- presets
#
# A preset is Keep's saved alert view: a name plus a CEL expression. The console
# already filters the feed with CEL, so saving one is the natural end of that
# gesture — and it is the last thing a dashboard's preset widgets needed that
# could previously only be created in Keep's own UI.
class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cel: str = Field(default="", max_length=4000)
    is_private: bool = False
    counter_shows_firing_only: bool = True
    approval_id: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def _reserved_names(self) -> PresetIn:
        # Keep rejects these with a bare 400. Saying so here means the person
        # finds out while typing rather than after pressing save.
        if self.name.strip().lower() in {"feed", "deleted"}:
            raise ValueError(f"'{self.name}' is reserved by Keep for its own views")
        return self

    def to_keep(self) -> dict[str, Any]:
        # Keep matches the option label case-insensitively on "cel"; it writes
        # "CEL" itself, so this writes "CEL" too and the two stay indistinguishable.
        return {
            "name": self.name.strip(),
            "options": [{"label": "CEL", "value": self.cel}],
            "is_private": self.is_private,
            "is_noisy": False,
            "tags": [],
            "counter_shows_firing_only": self.counter_shows_firing_only,
        }


@router.post("/presets")
async def create_preset(
    payload: PresetIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "presets.create",
        principal=principal,
        tenant=tenant,
        body=payload.to_keep(),
        approval_id=payload.approval_id,
        note=payload.reason or f"Create view {payload.name}",
    )


@router.put("/presets/{preset_id}")
async def update_preset(
    preset_id: str,
    payload: PresetIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "presets.update",
        principal=principal,
        tenant=tenant,
        path_params={"preset_id": preset_id},
        body=payload.to_keep(),
        approval_id=payload.approval_id,
        note=payload.reason or f"Update view {payload.name}",
    )


@router.delete("/presets/{preset_id}")
async def delete_preset(
    preset_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "presets.delete",
        principal=principal,
        tenant=tenant,
        path_params={"preset_id": preset_id},
        approval_id=approval_id,
        note=f"Delete view {preset_id}",
    )


@router.get("/presets")
async def presets(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> list[Any]:
    return _as_list(
        await gateway.execute("presets.list", principal=principal, tenant=tenant)
    )


# ----------------------------------------------------------------- enrichment
@router.get("/enrichment")
async def enrichment(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    """Mapping and extraction rules — how Keep decorates alerts on the way in."""
    mapping, extraction = await asyncio.gather(
        gateway.execute("mapping.list", principal=principal, tenant=tenant),
        gateway.execute("extraction.list", principal=principal, tenant=tenant),
        return_exceptions=True,
    )
    problems: list[str] = []
    if isinstance(mapping, BaseException):
        problems.append(f"mapping: {_reason(mapping)}")
    if isinstance(extraction, BaseException):
        problems.append(f"extraction: {_reason(extraction)}")
    return {
        "mapping": [] if isinstance(mapping, BaseException) else _as_list(mapping),
        "extraction": []
        if isinstance(extraction, BaseException)
        else _as_list(extraction),
        "problems": problems,
    }


@router.get("/dashboards")
async def dashboards(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    """Saved dashboards, plus everything the builder's widget picker needs.

    Presets come back here rather than from a second round trip because the
    picker is useless without them: a preset widget references a preset by id
    and name, and those are the only legal values.
    """
    saved, widgets, presets = await asyncio.gather(
        gateway.execute("dashboards.list", principal=principal, tenant=tenant),
        gateway.execute("dashboards.widgets", principal=principal, tenant=tenant),
        gateway.execute("presets.list", principal=principal, tenant=tenant),
        return_exceptions=True,
    )
    problems: list[str] = []
    if isinstance(saved, BaseException):
        problems.append(f"dashboards: {_reason(saved)}")
    if isinstance(widgets, BaseException):
        problems.append(f"widgets: {_reason(widgets)}")
    if isinstance(presets, BaseException):
        problems.append(f"presets: {_reason(presets)}")
    return {
        "dashboards": [] if isinstance(saved, BaseException) else _as_list(saved),
        "widgets": [] if isinstance(widgets, BaseException) else _as_list(widgets),
        "presets": [] if isinstance(presets, BaseException) else _as_list(presets),
        "problems": problems,
    }


class DashboardIn(BaseModel):
    """What the console may save.

    The layout is validated against `core.dashboards` before it reaches Keep,
    which stores the column without looking at it.
    """

    dashboard_name: str = Field(min_length=1, max_length=120)
    dashboard_config: DashboardConfig
    approval_id: str | None = None
    reason: str = ""


@router.post("/dashboards")
async def create_dashboard(
    payload: DashboardIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "dashboards.create",
        principal=principal,
        tenant=tenant,
        body={
            "dashboard_name": payload.dashboard_name,
            "dashboard_config": to_keep_config(payload.dashboard_config),
        },
        approval_id=payload.approval_id,
        note=payload.reason or f"Create dashboard {payload.dashboard_name}",
    )


@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str,
    payload: DashboardIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "dashboards.update",
        principal=principal,
        tenant=tenant,
        path_params={"dashboard_id": dashboard_id},
        body={
            "dashboard_name": payload.dashboard_name,
            "dashboard_config": to_keep_config(payload.dashboard_config),
        },
        approval_id=payload.approval_id,
        note=payload.reason or f"Update dashboard {payload.dashboard_name}",
    )


@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    """Read the layout into the audit trail, then delete it.

    Keep has no undo for this, so the snapshot is what makes the operation's
    tier-2 classification true rather than a convenient assumption — the layout
    can be rebuilt from the trail. The read is best-effort: if it fails the
    delete still proceeds, but the trail says the snapshot is missing instead
    of quietly implying one was taken.
    """
    snapshot: dict[str, Any]
    try:
        existing = _as_list(
            await gateway.execute("dashboards.list", principal=principal, tenant=tenant)
        )
        match = next((d for d in existing if str(d.get("id")) == dashboard_id), None)
        snapshot = (
            {
                "deleted_dashboard": {
                    "dashboard_name": match.get("dashboard_name"),
                    "dashboard_config": match.get("dashboard_config"),
                }
            }
            if match
            else {"deleted_dashboard": "<not found before delete>"}
        )
    except Exception as exc:  # noqa: BLE001 - the delete is what the caller asked for
        snapshot = {"deleted_dashboard": f"<snapshot failed: {_reason(exc)}>"}

    return await gateway.execute(
        "dashboards.delete",
        principal=principal,
        tenant=tenant,
        path_params={"dashboard_id": dashboard_id},
        approval_id=approval_id,
        note=f"Delete dashboard {dashboard_id}",
        audit_detail=snapshot,
    )


@router.get("/dashboards/preset-alerts/{preset_name}")
async def preset_alerts(
    preset_name: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    limit: int = 20,
) -> Any:
    """The rows behind a preset table widget."""
    result = await gateway.execute(
        "presets.alerts",
        principal=principal,
        tenant=tenant,
        path_params={"preset_name": preset_name},
        query_params={"limit": max(1, min(limit, 100))},
    )
    return {"items": _as_list(result)}


@router.get("/tags")
async def tags(gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep) -> Any:
    return await gateway.execute("tags.list", principal=principal, tenant=tenant)


# ------------------------------------------------- authoring: mapping rules
class MappingRuleIn(BaseModel):
    """Matchers are a list of lists: the outer list is OR, the inner AND.

    So [["service"], ["environment","team"]] means "match on service, or on
    environment AND team together". Keep rejects a flat list.
    """

    name: str = Field(min_length=1)
    description: str | None = None
    type: str = "csv"
    priority: int = Field(default=0, ge=0)
    disabled: bool = False
    override: bool = True
    matchers: list[list[str]] = Field(min_length=1)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    approval_id: str | None = None


@router.post("/mapping")
async def create_mapping(
    payload: MappingRuleIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "mapping.create",
        principal=principal,
        tenant=tenant,
        body=payload.model_dump(exclude={"approval_id"}, exclude_none=True),
        approval_id=payload.approval_id,
        note=f"create mapping rule '{payload.name}'",
    )


@router.delete("/mapping/{rule_id}")
async def delete_mapping(
    rule_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "mapping.delete",
        principal=principal,
        tenant=tenant,
        path_params={"rule_id": rule_id},
        approval_id=approval_id,
        note=f"delete mapping rule {rule_id}",
    )


# ---------------------------------------------- authoring: extraction rules
class ExtractionRuleIn(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    priority: int = Field(default=0, ge=0)
    attribute: str = Field(min_length=1)
    regex: str = Field(min_length=1)
    condition: str | None = None
    disabled: bool = False
    # pre=True runs before enrichment, so later rules can match what it extracts.
    pre: bool = False
    approval_id: str | None = None


@router.post("/extraction")
async def create_extraction(
    payload: ExtractionRuleIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "extraction.create",
        principal=principal,
        tenant=tenant,
        body=payload.model_dump(exclude={"approval_id"}, exclude_none=True),
        approval_id=payload.approval_id,
        note=f"create extraction rule '{payload.name}'",
    )


@router.delete("/extraction/{rule_id}")
async def delete_extraction(
    rule_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "extraction.delete",
        principal=principal,
        tenant=tenant,
        path_params={"rule_id": rule_id},
        approval_id=approval_id,
        note=f"delete extraction rule {rule_id}",
    )


# ------------------------------------------- authoring: deduplication rules
class DeduplicationRuleIn(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    provider_type: str = Field(min_length=1)
    provider_id: str | None = None
    fingerprint_fields: list[str] = Field(min_length=1)
    full_deduplication: bool = False
    ignore_fields: list[str] | None = None
    approval_id: str | None = None


@router.post("/deduplications")
async def create_deduplication(
    payload: DeduplicationRuleIn,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "dedup.create",
        principal=principal,
        tenant=tenant,
        body=payload.model_dump(exclude={"approval_id"}, exclude_none=True),
        approval_id=payload.approval_id,
        note=f"create deduplication rule '{payload.name}'",
    )


@router.delete("/deduplications/{rule_id}")
async def delete_deduplication(
    rule_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "dedup.delete",
        principal=principal,
        tenant=tenant,
        path_params={"rule_id": rule_id},
        approval_id=approval_id,
        note=f"delete deduplication rule {rule_id}",
    )
