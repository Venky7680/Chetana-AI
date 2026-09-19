from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from ..core.normalize import alert_facets, envelope, normalize_alert, unwrap_items
from ..deps import GatewayDep, PrincipalDep, TenantDep

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cel: str | None = Query(default=None, description="Keep CEL filter expression"),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    payload = await gateway.execute(
        "alerts.list",
        principal=principal,
        tenant=tenant,
        query_params={"limit": limit, "offset": offset, "cel": cel},
    )
    items = [normalize_alert(a) for a in unwrap_items(payload)]

    # Client-side-ish filters the console offers on top of CEL, applied here so
    # the browser never pulls the full page just to hide rows.
    if severity:
        wanted = {s.strip().lower() for s in severity.split(",") if s.strip()}
        items = [a for a in items if a["severity"] in wanted]
    if status:
        wanted = {s.strip().lower() for s in status.split(",") if s.strip()}
        items = [a for a in items if a["status"] in wanted]

    items.sort(key=lambda a: (a["severity_rank"], a["last_received"] or ""), reverse=True)
    result = envelope(payload, items)
    result["facets"] = alert_facets(items)
    return result


@router.get("/{fingerprint}")
async def get_alert(
    fingerprint: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> dict[str, Any]:
    payload = await gateway.execute(
        "alerts.get", principal=principal, tenant=tenant, path_params={"fingerprint": fingerprint}
    )
    return normalize_alert(payload if isinstance(payload, dict) else {})


@router.get("/{fingerprint}/history")
async def alert_history(
    fingerprint: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> dict[str, Any]:
    payload = await gateway.execute(
        "alerts.history",
        principal=principal,
        tenant=tenant,
        path_params={"fingerprint": fingerprint},
    )
    items = [normalize_alert(a) for a in unwrap_items(payload)]
    items.sort(key=lambda a: a["last_received"] or "", reverse=True)
    return envelope(payload, items)


@router.get("/{fingerprint}/audit")
async def alert_audit(
    fingerprint: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    return await gateway.execute(
        "alerts.audit", principal=principal, tenant=tenant, path_params={"fingerprint": fingerprint}
    )


class EnrichRequest(BaseModel):
    fingerprint: str
    enrichments: dict[str, Any] = Field(default_factory=dict)


@router.post("/enrich")
async def enrich_alert(
    payload: EnrichRequest,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    body = payload.model_dump()
    # Stamp who did it, so enrichment carries provenance into Keep itself.
    body["enrichments"] = {**body["enrichments"], "chetana_enriched_by": principal.subject}
    return await gateway.execute("alerts.enrich", principal=principal, tenant=tenant, body=body)


@router.post("/{fingerprint}/assign/{last_received}")
async def assign_alert(
    fingerprint: str,
    last_received: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "alerts.assign",
        principal=principal,
        tenant=tenant,
        path_params={"fingerprint": fingerprint, "last_received": last_received},
    )


@router.post("/search")
async def search_alerts(
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    payload = await gateway.execute(
        "alerts.search", principal=principal, tenant=tenant, body=body
    )
    return envelope(payload, [normalize_alert(a) for a in unwrap_items(payload)])


@router.get("/quality/metrics")
async def alert_quality(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    return await gateway.execute("alerts.quality", principal=principal, tenant=tenant)


@router.get("/{fingerprint}/detail")
async def alert_detail(
    fingerprint: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """Everything the alert page needs, in one round trip.

    History and audit are best-effort: a provider that never wrote an audit
    trail should not blank out the page.
    """
    import asyncio

    alert, history, audit = await asyncio.gather(
        gateway.execute(
            "alerts.get", principal=principal, tenant=tenant, path_params={"fingerprint": fingerprint}
        ),
        gateway.execute(
            "alerts.history",
            principal=principal,
            tenant=tenant,
            path_params={"fingerprint": fingerprint},
        ),
        gateway.execute(
            "alerts.audit",
            principal=principal,
            tenant=tenant,
            path_params={"fingerprint": fingerprint},
        ),
        return_exceptions=True,
    )

    def _items(result: Any) -> list[dict[str, Any]]:
        return [] if isinstance(result, BaseException) else unwrap_items(result)

    occurrences = [normalize_alert(a) for a in _items(history)]
    occurrences.sort(key=lambda a: a["last_received"] or "", reverse=True)

    return {
        "alert": normalize_alert(alert if isinstance(alert, dict) else {}),
        "occurrences": occurrences,
        "audit": _items(audit),
        "degraded": [
            name
            for name, result in (("history", history), ("audit", audit))
            if isinstance(result, BaseException)
        ],
    }
