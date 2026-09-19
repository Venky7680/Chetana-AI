"""The single chokepoint between the console and Keep.

Every request follows exactly one path:

    operation id -> allowlist lookup -> autonomy gate -> audit -> Keep

There is no bypass, and no router talks to `KeepClient` directly.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import HTTPException, status

from .core import autonomy
from .core.allowlist import Operation, OperationNotAllowed, Role, Tier, get_operation
from .core.audit import AuditLog
from .core.autonomy import ApprovalStore, GateResult
from .core.config import Settings, TenantConfig
from .core.keep_client import KeepClientRegistry, KeepError
from .core.security import Principal

logger = logging.getLogger("chetana.gateway")


class Gateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tenants = {t.id: t for t in settings.tenants()}
        self.clients = KeepClientRegistry(
            timeout=settings.request_timeout_seconds,
            max_connections=settings.keep_max_connections,
        )
        self.approvals = ApprovalStore()
        self.audit = AuditLog(settings.audit_log_path)

    # ------------------------------------------------------------------ tenants
    def tenant(self, tenant_id: str) -> TenantConfig | None:
        return self._tenants.get(tenant_id)

    def all_tenants(self) -> list[TenantConfig]:
        return [t for t in self._tenants.values() if t.enabled]

    def tenants_for(self, principal: Principal) -> list[TenantConfig]:
        return [t for t in self.all_tenants() if principal.may_access(t.id)]

    # -------------------------------------------------------------------- gate
    def gate(self, operation: Operation, principal: Principal, tenant: TenantConfig) -> GateResult:
        return autonomy.evaluate(
            operation=operation,
            role=principal.role,
            global_max=self.settings.global_max_autonomy_tier,
            tenant_max=tenant.max_autonomy_tier,
            admin_bypass=self.settings.admin_bypasses_autonomy_ceiling,
        )

    def describe_gate(self, op_id: str, principal: Principal, tenant: TenantConfig) -> dict[str, Any]:
        """Let the console grey out or badge a control *before* the user clicks."""
        operation = self._operation(op_id)
        result = self.gate(operation, principal, tenant)
        return {
            "operation_id": operation.id,
            "summary": operation.summary,
            "tier": int(operation.tier),
            "tier_name": operation.tier.name.lower(),
            "min_role": operation.min_role.name.lower(),
            "decision": result.decision,
            "reason": result.reason,
            "approvals_needed": result.approvals_needed,
            "effective_ceiling": int(result.effective_ceiling),
        }

    # ----------------------------------------------------------------- execute
    async def execute(
        self,
        op_id: str,
        *,
        principal: Principal,
        tenant: TenantConfig,
        path_params: Mapping[str, Any] | None = None,
        query_params: Mapping[str, Any] | None = None,
        body: Any = None,
        approval_id: str | None = None,
        note: str = "",
        audit_detail: Mapping[str, Any] | None = None,
    ) -> Any:
        """`audit_detail` attaches caller-supplied context to the trail entry.

        It exists so a router can make a tier *true* rather than merely
        asserted: deleting a dashboard is classed reversible because the router
        snapshots the layout here first, and without somewhere to put that
        snapshot the classification would be a promise nothing keeps.

        It cannot overwrite the keys the gateway sets, and it is dropped
        entirely for an operation carrying credentials, so it can never become
        a side door into the trail for a secret.
        """
        operation = self._operation(op_id)
        result = self.gate(operation, principal, tenant)

        if result.decision == "denied":
            self.audit.record(
                actor=principal.subject,
                tenant_id=tenant.id,
                operation_id=operation.id,
                decision="denied",
                reason=result.reason,
                tier=int(operation.tier),
                status="refused",
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, result.reason)

        if result.decision == "approval_required":
            if approval_id:
                self._consume_approval(approval_id, operation, tenant, principal)
            else:
                request = self.approvals.create(
                    tenant_id=tenant.id,
                    operation=operation,
                    requested_by=principal.subject,
                    approvals_needed=result.approvals_needed,
                    path_params={k: str(v) for k, v in (path_params or {}).items()},
                    query_params=dict(query_params or {}),
                    # A parked action is replayed by its requester, who supplies
                    # the body again with the approval id — the stored copy is
                    # never what executes. So for an operation carrying a
                    # client's credentials there is nothing to gain by keeping
                    # them in the ledger for half an hour, and something to lose.
                    body=None if operation.secret_body else body,
                    note=note,
                )
                self.audit.record(
                    actor=principal.subject,
                    tenant_id=tenant.id,
                    operation_id=operation.id,
                    decision="approval_required",
                    reason=result.reason,
                    tier=int(operation.tier),
                    status="parked",
                    detail={"approval_id": request.id},
                )
                raise HTTPException(
                    status.HTTP_202_ACCEPTED,
                    detail={
                        "code": "approval_required",
                        "message": result.reason,
                        "approval": request.as_dict(),
                    },
                )

        client = await self.clients.get(tenant)
        try:
            payload = await client.call(
                operation,
                path_params=path_params,
                query_params=query_params,
                body=body,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except KeepError as exc:
            self.audit.record(
                actor=principal.subject,
                tenant_id=tenant.id,
                operation_id=operation.id,
                decision=result.decision,
                reason=result.reason,
                tier=int(operation.tier),
                status="keep_error",
                detail={"status_code": exc.status_code, "message": exc.message},
            )
            raise HTTPException(exc.status_code, exc.message) from exc

        if operation.is_write:
            detail: dict[str, Any] = {
                "path_params": {k: str(v) for k, v in (path_params or {}).items()},
                "approval_id": approval_id,
            }
            if result.overridden:
                detail["override"] = "admin"
            # The trail answers "who installed what, and who let them" — never
            # "with which credential". Said explicitly so the answer is visible
            # to an auditor reading the trail, rather than merely absent.
            if operation.secret_body:
                detail["body"] = "<redacted: credentials>"
            elif audit_detail:
                for key, value in audit_detail.items():
                    detail.setdefault(key, value)
            self.audit.record(
                actor=principal.subject,
                tenant_id=tenant.id,
                operation_id=operation.id,
                decision="executed",
                reason=result.reason,
                tier=int(operation.tier),
                detail=detail,
            )
        return payload

    # ----------------------------------------------------------------- helpers
    def _operation(self, op_id: str) -> Operation:
        try:
            return get_operation(op_id)
        except OperationNotAllowed as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"operation '{op_id}' is not allowlisted"
            ) from exc

    def _consume_approval(
        self,
        approval_id: str,
        operation: Operation,
        tenant: TenantConfig,
        principal: Principal,
    ) -> None:
        request = self.approvals.get(approval_id)
        if request is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "approval request not found")
        if request.consumed:
            raise HTTPException(status.HTTP_409_CONFLICT, "approval request has already been used")
        if request.expired:
            raise HTTPException(status.HTTP_410_GONE, "approval request has expired")
        if request.tenant_id != tenant.id or request.operation_id != operation.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "approval request does not match this operation"
            )
        if not request.satisfied:
            missing = request.approvals_needed - len(request.approvals)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"approval incomplete: {missing} more approval(s) required"
            )
        self.approvals.consume(approval_id)
        self.audit.record(
            actor=principal.subject,
            tenant_id=tenant.id,
            operation_id=operation.id,
            decision="approval_consumed",
            reason=f"released by {', '.join(request.approvals)}",
            tier=int(operation.tier),
            detail={"approval_id": approval_id, "approvers": request.approvals},
        )

    async def aclose(self) -> None:
        await self.clients.aclose()


__all__ = ["Gateway", "Role", "Tier"]
