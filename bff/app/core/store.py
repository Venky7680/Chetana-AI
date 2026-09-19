"""Durable storage for investigations and the evidence they touched.

The BFF had no database until now: approvals live in memory and the audit trail
is an append-only file. Investigations force the issue — an investigation runs
for tens of seconds, costs real money, and its finding has to survive a restart
or the feature is a toy.

SQLite by default so a single-node deployment needs nothing extra; point
`CHETANA_DATABASE_URL` at Postgres and the only other change is adding asyncpg
to requirements. Nothing in this module assumes SQLite.

The evidence table is the point of the whole design. Holmes reports which tools
it called; this table records which calls *actually reached the estate*, written
by the gateway itself. When the two disagree, the gateway is right — which is
what makes the evidence chain in the console trustworthy rather than a
self-report from a language model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _ensure_sqlite_dir(url: str) -> None:
    """Create the directory a SQLite file lives in, if it is missing."""
    from pathlib import Path

    _, _, tail = url.partition("///")
    if not tail or tail.startswith(":memory:"):
        return
    path = Path(tail.split("?", 1)[0])
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)


class Base(DeclarativeBase):
    pass


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    requested_by: Mapped[str] = mapped_column(String(255))

    # queued -> running -> complete | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    question: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(128), default=None)

    finding: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # Holmes' own account of the tools it used, kept for comparison against the
    # evidence_calls rows the gateway wrote.
    reported_tool_calls: Mapped[Any | None] = mapped_column(JSON, default=None)

    evidence_budget: Mapped[int] = mapped_column(Integer, default=40)
    evidence_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    calls: Mapped[list["EvidenceCall"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="EvidenceCall.created_at",
    )

    @property
    def open(self) -> bool:
        return self.status in ("queued", "running")

    def as_dict(self, *, include_calls: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "incident_id": self.incident_id,
            "requested_by": self.requested_by,
            "status": self.status,
            "question": self.question,
            "model": self.model,
            "finding": self.finding,
            "error": self.error,
            "evidence_used": self.evidence_used,
            "evidence_budget": self.evidence_budget,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
        }
        if include_calls:
            payload["evidence"] = [c.as_dict() for c in self.calls]
            payload["reported_tool_calls"] = self.reported_tool_calls or []
        return payload


class EvidenceCall(Base):
    """One read that the gateway actually served to Holmes.

    Written by the evidence router on every call, successful or not. This is the
    audit answer to "what did the AI look at inside my estate".
    """

    __tablename__ = "evidence_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(64))
    params: Mapped[Any | None] = mapped_column(JSON, default=None)
    # ok | refused | error
    status: Mapped[str] = mapped_column(String(16), default="ok")
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    result_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    investigation: Mapped[Investigation] = relationship(back_populates="calls")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "params": self.params or {},
            "status": self.status,
            "status_code": self.status_code,
            "detail": self.detail,
            "result_bytes": self.result_bytes,
            "duration_ms": self.duration_ms,
            "at": self.created_at.isoformat() if self.created_at else None,
        }


class Store:
    """Owns the engine and session factory. One instance per process."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            # The BFF is async and FastAPI may touch the connection from more
            # than one task; SQLite's default same-thread check rejects that.
            connect_args["check_same_thread"] = False
            # SQLite will not create a missing parent directory — it just fails
            # with "unable to open database file", which says nothing about the
            # actual problem. Create it here so a fresh container or a new
            # volume mount does not need a manual mkdir.
            _ensure_sqlite_dir(url)
        self._engine = create_async_engine(url, echo=echo, future=True, connect_args=connect_args)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def session(self) -> AsyncSession:
        return self._sessions()

    async def aclose(self) -> None:
        await self._engine.dispose()

    # ------------------------------------------------------------- operations
    async def create_investigation(
        self,
        *,
        tenant_id: str,
        incident_id: str | None,
        requested_by: str,
        question: str,
        model: str | None,
        evidence_budget: int,
    ) -> Investigation:
        record = Investigation(
            id=new_id("inv"),
            tenant_id=tenant_id,
            incident_id=incident_id,
            requested_by=requested_by,
            question=question,
            model=model,
            status="running",
            evidence_budget=evidence_budget,
        )
        async with self.session() as session:
            session.add(record)
            await session.commit()
        return record

    async def get_investigation(
        self, investigation_id: str, *, with_calls: bool = False
    ) -> Investigation | None:
        from sqlalchemy.orm import selectinload

        stmt = select(Investigation).where(Investigation.id == investigation_id)
        if with_calls:
            stmt = stmt.options(selectinload(Investigation.calls))
        async with self.session() as session:
            return (await session.execute(stmt)).scalar_one_or_none()

    async def list_investigations(
        self, *, tenant_id: str, incident_id: str | None = None, limit: int = 50
    ) -> list[Investigation]:
        stmt = select(Investigation).where(Investigation.tenant_id == tenant_id)
        if incident_id:
            stmt = stmt.where(Investigation.incident_id == incident_id)
        stmt = stmt.order_by(Investigation.created_at.desc()).limit(limit)
        async with self.session() as session:
            return list((await session.execute(stmt)).scalars())

    async def finish_investigation(
        self,
        investigation_id: str,
        *,
        status: str,
        finding: str | None = None,
        error: str | None = None,
        reported_tool_calls: Any | None = None,
        duration_ms: int | None = None,
    ) -> None:
        async with self.session() as session:
            record = await session.get(Investigation, investigation_id)
            if record is None:  # pragma: no cover - defensive
                return
            record.status = status
            record.finding = finding
            record.error = error
            record.reported_tool_calls = reported_tool_calls
            record.duration_ms = duration_ms
            record.completed_at = _now()
            await session.commit()

    async def claim_evidence_slot(self, investigation_id: str) -> tuple[bool, str]:
        """Atomically take one unit of an investigation's evidence budget.

        Returns (allowed, reason). This is the runaway-loop stop: a model that
        decides to poll the estate forever runs out of budget rather than out of
        the client's goodwill.
        """
        async with self.session() as session:
            record = await session.get(Investigation, investigation_id)
            if record is None:
                return False, "investigation not found"
            if not record.open:
                return False, f"investigation is {record.status}"
            if record.evidence_used >= record.evidence_budget:
                return False, (
                    f"evidence budget exhausted ({record.evidence_budget} calls)"
                )
            record.evidence_used += 1
            await session.commit()
            return True, ""

    async def record_evidence_call(
        self,
        *,
        investigation_id: str,
        tool: str,
        params: dict[str, Any],
        status: str,
        status_code: int | None = None,
        detail: str | None = None,
        result_bytes: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        async with self.session() as session:
            session.add(
                EvidenceCall(
                    id=new_id("ev"),
                    investigation_id=investigation_id,
                    tool=tool,
                    params=params,
                    status=status,
                    status_code=status_code,
                    detail=detail,
                    result_bytes=result_bytes,
                    duration_ms=duration_ms,
                )
            )
            await session.commit()

    async def count_recent_investigations(self, tenant_id: str, *, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(Investigation)
            .where(Investigation.tenant_id == tenant_id, Investigation.created_at >= since)
        )
        async with self.session() as session:
            return int((await session.execute(stmt)).scalar_one())


async def session_scope(store: Store) -> AsyncIterator[AsyncSession]:  # pragma: no cover
    async with store.session() as session:
        yield session
