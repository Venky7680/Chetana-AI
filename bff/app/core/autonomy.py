"""Reversibility-based autonomy gating.

The rule Chetana enforces: *how much autonomy an action gets is decided by how
hard it is to undo, never by how urgent the alert is.* A P1 does not make a
`DELETE` safe.

Three ceilings apply to every write, and the strictest one wins:

  1. the global ceiling (deployment-wide, ops-owned)
  2. the tenant ceiling (what the client has signed off on)
  3. the caller's role

Anything above the effective ceiling is not refused outright — it is parked as
an *approval request*, which a second principal can release. Tier 3 requires
that the approver is a different person from the requester.

**Admins are exempt, by default and by choice.** An admin is the highest
authority in the platform, and an admin who hits an approval wall with nobody
more senior to ask is stuck rather than safe. So `admin_bypass` lets the admin
role execute at any tier without parking.

What that does *not* do is make the action quiet. A bypassed action is recorded
with `override: admin` and a reason that names the ceiling it exceeded, so the
audit trail distinguishes "this was within what the client signed off on" from
"an admin went past it". That distinction is the one a client asks about, and
it survives the bypass.

The switch exists because the ceiling is not really about trusting the operator.
One of the three ceilings is the client's own sign-off, and a deployment whose
contracts say an irreversible action always takes two people can turn the bypass
off without touching code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal

from .allowlist import Operation, Role, Tier

Decision = Literal["execute", "approval_required", "denied"]

APPROVAL_TTL = timedelta(minutes=30)


@dataclass
class GateResult:
    decision: Decision
    reason: str
    tier: Tier
    effective_ceiling: Tier
    approval_id: str | None = None
    # Number of distinct approvers still needed.
    approvals_needed: int = 0
    # True when an admin executed something the ceiling would have parked. It
    # reaches the audit trail so an override never reads like a normal action.
    overridden: bool = False


@dataclass
class ApprovalRequest:
    id: str
    tenant_id: str
    operation_id: str
    requested_by: str
    created_at: datetime
    expires_at: datetime
    tier: Tier
    approvals_needed: int
    path_params: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    approvals: list[str] = field(default_factory=list)
    consumed: bool = False
    note: str = ""

    @property
    def satisfied(self) -> bool:
        return len(self.approvals) >= self.approvals_needed

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "operation_id": self.operation_id,
            "requested_by": self.requested_by,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "tier": int(self.tier),
            "approvals_needed": self.approvals_needed,
            "approvals": list(self.approvals),
            "satisfied": self.satisfied,
            "expired": self.expired,
            "consumed": self.consumed,
            "note": self.note,
            "target": {
                "path_params": self.path_params,
                "query_params": self.query_params,
            },
        }


def approvals_required_for(tier: Tier) -> int:
    """Tier 2 needs one approver; tier 3 needs two distinct principals."""
    if tier <= Tier.AUTO_REVERSIBLE:
        return 0
    if tier == Tier.EFFORT_REVERSIBLE:
        return 1
    return 2


def effective_ceiling(global_max: int, tenant_max: int) -> Tier:
    return Tier(min(int(global_max), int(tenant_max)))


def evaluate(
    *,
    operation: Operation,
    role: Role,
    global_max: int,
    tenant_max: int,
    admin_bypass: bool = False,
) -> GateResult:
    """Decide what happens to a request, before any call reaches Keep."""

    ceiling = effective_ceiling(global_max, tenant_max)

    if role < operation.min_role:
        return GateResult(
            decision="denied",
            reason=(
                f"'{operation.id}' requires role '{operation.min_role.name.lower()}'; "
                f"caller is '{role.name.lower()}'"
            ),
            tier=operation.tier,
            effective_ceiling=ceiling,
        )

    if not operation.is_write or operation.tier == Tier.READ_ONLY:
        return GateResult(
            decision="execute",
            reason="read-only operation",
            tier=operation.tier,
            effective_ceiling=ceiling,
        )

    if operation.tier <= ceiling:
        return GateResult(
            decision="execute",
            reason=f"tier {int(operation.tier)} is within the autonomy ceiling {int(ceiling)}",
            tier=operation.tier,
            effective_ceiling=ceiling,
        )

    # Above the ceiling — but an admin is not asked to find a second signature.
    # The action still records that it went past the ceiling, and by how much,
    # because "an admin overrode this" is exactly what a client will ask about
    # later and it must not read the same as an ordinary approved action.
    if admin_bypass and role >= Role.ADMIN:
        return GateResult(
            decision="execute",
            reason=(
                f"admin override: tier {int(operation.tier)} exceeds the autonomy "
                f"ceiling {int(ceiling)}"
            ),
            tier=operation.tier,
            effective_ceiling=ceiling,
            overridden=True,
        )

    needed = approvals_required_for(operation.tier)
    return GateResult(
        decision="approval_required",
        reason=(
            f"tier {int(operation.tier)} ({operation.tier.name.lower()}) exceeds the "
            f"autonomy ceiling {int(ceiling)}; {needed} approval(s) required"
        ),
        tier=operation.tier,
        effective_ceiling=ceiling,
        approvals_needed=needed,
    )


class ApprovalStore:
    """In-memory approval ledger.

    Deliberately small and swappable: point it at Redis or Postgres when the BFF
    runs more than one replica. The interface is what the routers depend on.
    """

    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        tenant_id: str,
        operation: Operation,
        requested_by: str,
        approvals_needed: int,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, Any] | None = None,
        body: Any = None,
        note: str = "",
    ) -> ApprovalRequest:
        now = datetime.now(timezone.utc)
        req = ApprovalRequest(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            operation_id=operation.id,
            requested_by=requested_by,
            created_at=now,
            expires_at=now + APPROVAL_TTL,
            tier=operation.tier,
            approvals_needed=approvals_needed,
            path_params=path_params or {},
            query_params=query_params or {},
            body=body,
            note=note,
        )
        with self._lock:
            self._items[req.id] = req
        return req

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._items.get(approval_id)

    def list(self, tenant_id: str | None = None, *, include_done: bool = False) -> list[ApprovalRequest]:
        items = list(self._items.values())
        if tenant_id:
            items = [i for i in items if i.tenant_id == tenant_id]
        if not include_done:
            items = [i for i in items if not i.consumed and not i.expired]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def approve(self, approval_id: str, approver: str) -> tuple[ApprovalRequest | None, str | None]:
        """Record an approval. Returns (request, error)."""
        with self._lock:
            req = self._items.get(approval_id)
            if req is None:
                return None, "approval request not found"
            if req.consumed:
                return req, "approval request has already been used"
            if req.expired:
                return req, "approval request has expired"
            if approver == req.requested_by:
                # Four-eyes: the requester never counts as an approver.
                return req, "an action cannot be approved by the principal that requested it"
            if approver in req.approvals:
                return req, "this principal has already approved"
            req.approvals.append(approver)
            return req, None

    def consume(self, approval_id: str) -> None:
        with self._lock:
            req = self._items.get(approval_id)
            if req is not None:
                req.consumed = True

    def purge_expired(self) -> int:
        with self._lock:
            expired = [k for k, v in self._items.items() if v.expired and not v.consumed]
            for k in expired:
                del self._items[k]
        return len(expired)
