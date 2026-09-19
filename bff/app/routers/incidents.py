from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..core.normalize import (
    envelope,
    incident_facets,
    normalize_alert,
    normalize_incident,
    unwrap_items,
)
from ..deps import GatewayDep, PrincipalDep, TenantDep

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    candidate: bool | None = Query(default=None, description="Only AI-suggested incidents"),
    cel: str | None = Query(default=None),
    open_only: bool = Query(default=False),
) -> dict[str, Any]:
    payload = await gateway.execute(
        "incidents.list",
        principal=principal,
        tenant=tenant,
        query_params={"limit": limit, "offset": offset, "candidate": candidate, "cel": cel},
    )
    items = [normalize_incident(i) for i in unwrap_items(payload)]
    # Facets are computed over everything Keep returned, before the open_only
    # filter — otherwise the counts change as you filter, which is disorienting.
    facets = incident_facets(items)
    if open_only:
        items = [i for i in items if i["is_open"]]
    items.sort(key=lambda i: (i["severity_rank"], i["last_seen_at"] or ""), reverse=True)
    result = envelope(payload, items)
    result["facets"] = facets
    return result


@router.get("/meta")
async def incidents_meta(gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep) -> Any:
    return await gateway.execute("incidents.meta", principal=principal, tenant=tenant)


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> dict[str, Any]:
    payload = await gateway.execute(
        "incidents.get", principal=principal, tenant=tenant, path_params={"incident_id": incident_id}
    )
    return normalize_incident(payload if isinstance(payload, dict) else {})


@router.get("/{incident_id}/detail")
async def incident_detail(
    incident_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """One round trip for the whole incident page.

    This is the reason a BFF exists: the browser asks one question and the
    fan-out to Keep happens next to Keep, not across the internet.
    """
    incident, alerts, workflows = await asyncio.gather(
        gateway.execute(
            "incidents.get",
            principal=principal,
            tenant=tenant,
            path_params={"incident_id": incident_id},
        ),
        gateway.execute(
            "incidents.alerts",
            principal=principal,
            tenant=tenant,
            path_params={"incident_id": incident_id},
            query_params={"limit": 200},
        ),
        gateway.execute(
            "incidents.workflows",
            principal=principal,
            tenant=tenant,
            path_params={"incident_id": incident_id},
            query_params={"limit": 50},
        ),
        return_exceptions=True,
    )

    def _safe_items(result: Any) -> list[dict[str, Any]]:
        return [] if isinstance(result, BaseException) else unwrap_items(result)

    normalized_alerts = [normalize_alert(a) for a in _safe_items(alerts)]
    normalized_alerts.sort(key=lambda a: (a["severity_rank"], a["last_received"] or ""), reverse=True)

    return {
        "incident": normalize_incident(incident if isinstance(incident, dict) else {}),
        "alerts": normalized_alerts,
        "workflow_executions": _safe_items(workflows),
        "degraded": [
            name
            for name, result in (("alerts", alerts), ("workflows", workflows))
            if isinstance(result, BaseException)
        ],
    }


class StatusChange(BaseModel):
    status: str
    comment: str | None = None


@router.post("/{incident_id}/status")
async def change_status(
    incident_id: str,
    payload: StatusChange,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "incidents.status",
        principal=principal,
        tenant=tenant,
        path_params={"incident_id": incident_id},
        body=payload.model_dump(exclude_none=True),
    )


class Comment(BaseModel):
    comment: str = Field(min_length=1)


@router.post("/{incident_id}/comment")
async def add_comment(
    incident_id: str,
    payload: Comment,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "incidents.comment",
        principal=principal,
        tenant=tenant,
        path_params={"incident_id": incident_id},
        body={"status": "comment", "comment": payload.comment},
    )


@router.post("/{incident_id}/confirm")
async def confirm_incident(
    incident_id: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    return await gateway.execute(
        "incidents.confirm",
        principal=principal,
        tenant=tenant,
        path_params={"incident_id": incident_id},
    )


class MergeRequest(BaseModel):
    source_incident_ids: list[str]
    destination_incident_id: str
    approval_id: str | None = None


@router.post("/merge")
async def merge_incidents(
    payload: MergeRequest,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    body = payload.model_dump(exclude={"approval_id"})
    return await gateway.execute(
        "incidents.merge",
        principal=principal,
        tenant=tenant,
        body=body,
        approval_id=payload.approval_id,
        note=f"merge {len(payload.source_incident_ids)} incident(s)",
    )


class BulkIds(BaseModel):
    incident_ids: list[str]
    approval_id: str | None = None


@router.post("/bulk/delete")
async def bulk_delete(
    payload: BulkIds,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """Delete several incidents. Tier 3 per incident, so the gate runs once per
    id and a partial failure is reported rather than hidden."""
    deleted: list[str] = []
    failed: list[dict[str, Any]] = []
    for incident_id in payload.incident_ids:
        try:
            await gateway.execute(
                "incidents.delete",
                principal=principal,
                tenant=tenant,
                path_params={"incident_id": incident_id},
                approval_id=payload.approval_id,
                note=f"bulk delete of {len(payload.incident_ids)} incident(s)",
            )
            deleted.append(incident_id)
        except Exception as exc:  # surfaced to the caller, never swallowed
            failed.append({"incident_id": incident_id, "error": str(getattr(exc, "detail", exc))})
    return {"deleted": deleted, "failed": failed}
