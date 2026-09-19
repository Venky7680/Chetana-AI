"""Tenants, the allowlist itself, approvals and the audit trail.

These endpoints exist so the console can render an honest picture of what the
platform is permitted to do — the allowlist is a product surface, not a secret.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..core.allowlist import OPERATIONS
from ..deps import GatewayDep, PrincipalDep, TenantDep

router = APIRouter(tags=["governance"])


@router.get("/tenants")
def list_tenants(gateway: GatewayDep, principal: PrincipalDep) -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "tags": t.tags,
            "max_autonomy_tier": t.max_autonomy_tier,
            "effective_ceiling": min(t.max_autonomy_tier, gateway.settings.global_max_autonomy_tier),
        }
        for t in gateway.tenants_for(principal)
    ]


@router.get("/capabilities")
def capabilities(gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep) -> dict:
    """Every allowlisted operation with this caller's decision for this tenant.

    The console uses it to decide which buttons are live, which need approval,
    and which are not available at all.
    """
    return {
        "tenant": {"id": tenant.id, "name": tenant.name},
        "role": principal.role.name.lower(),
        "effective_ceiling": min(
            tenant.max_autonomy_tier, gateway.settings.global_max_autonomy_tier
        ),
        "operations": [
            gateway.describe_gate(op_id, principal, tenant) for op_id in sorted(OPERATIONS)
        ],
    }


@router.get("/approvals")
def list_approvals(
    gateway: GatewayDep,
    tenant: TenantDep,
    principal: PrincipalDep,
    include_done: bool = Query(default=False),
) -> list[dict]:
    return [r.as_dict() for r in gateway.approvals.list(tenant.id, include_done=include_done)]


class ApproveRequest(BaseModel):
    note: str = ""


@router.post("/approvals/{approval_id}/approve")
def approve(
    approval_id: str,
    payload: ApproveRequest,
    gateway: GatewayDep,
    tenant: TenantDep,
    principal: PrincipalDep,
) -> dict:
    from ..core.allowlist import Role

    if principal.role < Role.APPROVER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "approver role required")

    request, error = gateway.approvals.approve(approval_id, principal.subject)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, error or "not found")
    if request.tenant_id != tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval request not found")
    if error:
        raise HTTPException(status.HTTP_409_CONFLICT, error)

    gateway.audit.record(
        actor=principal.subject,
        tenant_id=tenant.id,
        operation_id=request.operation_id,
        decision="approval_granted",
        reason=payload.note or "approved in console",
        tier=int(request.tier),
        detail={"approval_id": approval_id},
    )
    return request.as_dict()


@router.get("/audit")
def audit(
    gateway: GatewayDep,
    tenant: TenantDep,
    principal: PrincipalDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return gateway.audit.recent(tenant.id, limit=limit)
