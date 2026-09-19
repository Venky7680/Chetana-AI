from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..core.normalize import envelope, normalize_workflow, unwrap_items
from ..deps import GatewayDep, PrincipalDep, TenantDep

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("")
async def list_workflows(
    gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> dict[str, Any]:
    payload = await gateway.execute("workflows.list", principal=principal, tenant=tenant)
    items = [normalize_workflow(w) for w in unwrap_items(payload)]
    items.sort(key=lambda w: (w["disabled"], w["name"].lower()))
    return envelope(payload, items)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> dict[str, Any]:
    payload = await gateway.execute(
        "workflows.get", principal=principal, tenant=tenant, path_params={"workflow_id": workflow_id}
    )
    return normalize_workflow(payload if isinstance(payload, dict) else {})


@router.get("/{workflow_id}/raw")
async def get_workflow_raw(
    workflow_id: str, gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep
) -> Any:
    return await gateway.execute(
        "workflows.raw", principal=principal, tenant=tenant, path_params={"workflow_id": workflow_id}
    )


@router.get("/{workflow_id}/runs")
async def list_runs(
    workflow_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await gateway.execute(
        "workflows.runs",
        principal=principal,
        tenant=tenant,
        path_params={"workflow_id": workflow_id},
        query_params={"limit": limit, "offset": offset},
    )


@router.get("/{workflow_id}/runs/{execution_id}")
async def run_status(
    workflow_id: str,
    execution_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "workflows.run_status",
        principal=principal,
        tenant=tenant,
        path_params={"workflow_id": workflow_id, "workflow_execution_id": execution_id},
    )


class RunRequest(BaseModel):
    """Workflow execution is tier 2 — it reaches into a client estate.

    Either it is inside the tenant's autonomy ceiling and runs, or the BFF
    returns 202 with an approval request that a second principal releases.
    """

    inputs: dict[str, Any] = Field(default_factory=dict)
    incident_id: str | None = None
    alert_fingerprint: str | None = None
    approval_id: str | None = None
    reason: str = ""


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    payload: RunRequest,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    body: dict[str, Any] = dict(payload.inputs)
    if payload.incident_id:
        body["incident_id"] = payload.incident_id
    if payload.alert_fingerprint:
        body["fingerprint"] = payload.alert_fingerprint
    body["chetana_requested_by"] = principal.subject

    return await gateway.execute(
        "workflows.run",
        principal=principal,
        tenant=tenant,
        path_params={"workflow_id": workflow_id},
        body=body,
        approval_id=payload.approval_id,
        note=payload.reason or f"run workflow {workflow_id}",
    )


@router.get("/{workflow_id}/detail")
async def workflow_detail(
    workflow_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """Workflow, its YAML definition and its recent runs, in one call."""
    import asyncio

    workflow, raw, runs = await asyncio.gather(
        gateway.execute(
            "workflows.get",
            principal=principal,
            tenant=tenant,
            path_params={"workflow_id": workflow_id},
        ),
        gateway.execute(
            "workflows.raw",
            principal=principal,
            tenant=tenant,
            path_params={"workflow_id": workflow_id},
        ),
        gateway.execute(
            "workflows.runs",
            principal=principal,
            tenant=tenant,
            path_params={"workflow_id": workflow_id},
            query_params={"limit": 25},
        ),
        return_exceptions=True,
    )

    definition = ""
    if isinstance(raw, dict):
        definition = str(raw.get("workflow_raw") or raw.get("raw") or "")
    elif isinstance(raw, str):
        definition = raw

    return {
        "workflow": normalize_workflow(workflow if isinstance(workflow, dict) else {}),
        "definition": definition,
        "runs": [] if isinstance(runs, BaseException) else unwrap_items(runs),
        "degraded": [
            name
            for name, result in (("definition", raw), ("runs", runs))
            if isinstance(result, BaseException)
        ],
    }


class WorkflowSource(BaseModel):
    """A workflow authored in the console, as YAML.

    Keep parses the request body with yaml.safe_load, so the text is forwarded
    verbatim — comments and formatting survive the round trip, which matters
    when the YAML is the thing an engineer maintains.
    """

    yaml: str = Field(min_length=1)
    approval_id: str | None = None
    reason: str = ""


@router.post("")
async def create_workflow(
    payload: WorkflowSource,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "workflows.create",
        principal=principal,
        tenant=tenant,
        body=payload.yaml,
        approval_id=payload.approval_id,
        note=payload.reason or "create workflow from console",
    )


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    payload: WorkflowSource,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> Any:
    return await gateway.execute(
        "workflows.update",
        principal=principal,
        tenant=tenant,
        path_params={"workflow_id": workflow_id},
        body=payload.yaml,
        approval_id=payload.approval_id,
        note=payload.reason or f"update workflow {workflow_id}",
    )


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
    approval_id: str | None = None,
) -> Any:
    return await gateway.execute(
        "workflows.delete",
        principal=principal,
        tenant=tenant,
        path_params={"workflow_id": workflow_id},
        approval_id=approval_id,
        note=f"delete workflow {workflow_id}",
    )
