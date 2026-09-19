"""Investigation lifecycle — Layer 5, the reasoning plane.

An investigation takes tens of seconds, so starting one returns 202 with an id
and the console polls. Running it inside the request would mean a two-minute
HTTP call that any reverse proxy in front of this will eventually cut.

What this router is careful about:

  * **Cost.** Every investigation is an LLM call. A per-tenant hourly ceiling is
    enforced before anything is started, because the natural trigger for an
    investigation is an alert storm — exactly when you least want an unbounded
    number of them.
  * **Consent.** A tenant can have managed services without having agreed that a
    language model may read their estate. `investigations_enabled` is per tenant
    and defaults on only because the demo stack needs it; for a real client it
    is a contract question.
  * **Scope.** The token handed to Holmes grants only the tools that make sense
    for this tenant — no Prometheus tools if the tenant has no Prometheus, so a
    missing integration is a smaller toolset rather than a failed investigation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core import evidence as ev
from ..core.allowlist import Role
from ..core.config import TenantConfig
from ..core.holmes_client import HolmesClient, HolmesError
from ..core.security import Principal
from ..core.store import Store
from ..deps import GatewayDep, PrincipalDep, SettingsDep, TenantDep
from ..gateway import Gateway

logger = logging.getLogger("chetana.investigations")

router = APIRouter(prefix="/investigations", tags=["investigations"])

MIN_ROLE = Role.OPERATOR

SYSTEM_PROMPT = """\
You are the investigation engine inside Chetana AI, an AIOps platform operated \
by a managed service provider. You are investigating an incident in a client's \
production estate.

Read the evidence before concluding anything. Use the chetana tools: start with \
the incident and its alerts, then look at topology to tell a cause from a \
victim, then use PromQL to check whether a metric moved *before* the incident \
started. A symptom that appeared after the incident began is not the cause.

If a precedent search is available, it is worth an early call: it tells you how \
this class of symptom was resolved before, which is a fast route to a \
hypothesis. Treat what it returns as a lead to test against metrics and \
topology, never as a finding on its own — and if the source block says the \
ticket history is synthetic, say so wherever you rely on it.

Your answer must be structured exactly as:

ROOT CAUSE: one sentence. If the evidence does not support a conclusion, say \
"Undetermined" and say what is missing.
CONFIDENCE: high, medium or low.
EVIDENCE: the specific observations that led you there, each naming the tool and \
what it returned. Do not list evidence you did not actually retrieve.
IMPACT: which services and users are affected.
RECOMMENDED ACTION: what a human should do next. Recommend only; you cannot \
change anything, and any action will be executed by a human through an approval \
gate.

Never invent a metric, a service name or a log line. If a tool returns nothing, \
say so — an honest gap is more useful to an on-call engineer than a plausible \
guess.\
"""


class StartInvestigation(BaseModel):
    incident_id: str | None = None
    question: str | None = Field(default=None, max_length=2000)


def _store(request: Request) -> Store:
    store: Store | None = getattr(request.app.state, "store", None)
    if store is None:  # pragma: no cover - only if startup failed
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store not ready")
    return store


def _holmes(request: Request) -> HolmesClient:
    client: HolmesClient | None = getattr(request.app.state, "holmes", None)
    if client is None or not client.enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI investigation is not configured — set CHETANA_HOLMES_BASE_URL",
        )
    return client


def _has_precedents(request: Request, tenant: TenantConfig) -> bool:
    """Whether THIS client has a corpus to search — its own, or the shared one."""
    store = getattr(request.app.state, "corpora", None)
    return bool(store and store.index(tenant.id))


def _granted_tools(
    tenant: TenantConfig, *, has_precedents: bool = False
) -> tuple[str, ...]:
    """A tool nothing can answer is worse than a tool that is absent.

    The model discovers an absent tool instantly; a granted-but-empty one costs
    it a call from its evidence budget to find out, and invites it to read the
    silence as meaning nothing was ever seen before.
    """
    names = []
    for name, tool in ev.TOOLS.items():
        if tool.kind == "prometheus" and not tenant.prometheus_base_url:
            continue
        if tool.kind == "precedent" and not has_precedents:
            continue
        names.append(name)
    return tuple(names)


@router.get("/capabilities")
async def capabilities(
    request: Request,
    principal: PrincipalDep,
    tenant: TenantDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Let the console decide whether to render the panel at all."""
    client: HolmesClient | None = getattr(request.app.state, "holmes", None)
    configured = client is not None and client.enabled
    # Probe rather than assume: "configured but the container is down" and "not
    # configured" need different words in the console, and the difference is one
    # cheap call.
    reachable = bool(configured and client is not None and await client.healthy())
    return {
        "configured": configured,
        "reachable": reachable,
        "tenant_enabled": tenant.investigations_enabled,
        "may_investigate": principal.role >= MIN_ROLE,
        "min_role": MIN_ROLE.name.lower(),
        "model": settings.holmes_model if configured else None,
        "tools": _granted_tools(
            tenant,
            has_precedents=_has_precedents(request, tenant),
        ),
        "evidence_budget": settings.evidence_budget_per_investigation,
        "hourly_limit": settings.investigations_per_tenant_per_hour,
    }


@router.get("")
async def list_investigations(
    request: Request,
    principal: PrincipalDep,
    tenant: TenantDep,
    incident_id: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    store = _store(request)
    records = await store.list_investigations(
        tenant_id=tenant.id, incident_id=incident_id, limit=min(max(limit, 1), 100)
    )
    return {"items": [r.as_dict() for r in records], "count": len(records)}


@router.get("/{investigation_id}")
async def get_investigation(
    investigation_id: str,
    request: Request,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    store = _store(request)
    record = await store.get_investigation(investigation_id, with_calls=True)
    # 404 rather than 403 across tenants, same as everywhere else in the BFF.
    if record is None or record.tenant_id != tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "investigation not found")
    return record.as_dict(include_calls=True)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_investigation(
    payload: StartInvestigation,
    request: Request,
    principal: PrincipalDep,
    tenant: TenantDep,
    gateway: GatewayDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    store = _store(request)
    client = _holmes(request)

    if principal.role < MIN_ROLE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"starting an investigation requires the {MIN_ROLE.name.lower()} role",
        )
    if not tenant.investigations_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"AI investigation is not enabled for {tenant.name}",
        )

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = await store.count_recent_investigations(tenant.id, since=since)
    if recent >= settings.investigations_per_tenant_per_hour:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            (
                f"{tenant.name} has reached its limit of "
                f"{settings.investigations_per_tenant_per_hour} investigations per hour"
            ),
        )

    question = await _build_question(payload, gateway, principal, tenant)

    record = await store.create_investigation(
        tenant_id=tenant.id,
        incident_id=payload.incident_id,
        requested_by=principal.subject,
        question=question,
        model=settings.holmes_model,
        evidence_budget=settings.evidence_budget_per_investigation,
    )

    token = ev.mint_token(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        investigation_id=record.id,
        tenant_id=tenant.id,
        tools=_granted_tools(
            tenant,
            has_precedents=_has_precedents(request, tenant),
        ),
        ttl_seconds=settings.evidence_token_ttl_seconds,
    )

    task = asyncio.create_task(
        _run(
            store=store,
            client=client,
            investigation_id=record.id,
            tenant_id=tenant.id,
            question=question,
            token=token,
        )
    )
    # Hold a reference: asyncio only keeps a weak one, and a garbage-collected
    # task disappears mid-investigation with no error anywhere.
    tasks: set[asyncio.Task[None]] = request.app.state.investigation_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)

    gateway.audit.record(
        actor=principal.subject,
        tenant_id=tenant.id,
        operation_id="investigation.start",
        decision="executed",
        reason="AI investigation requested",
        tier=0,
        detail={"investigation_id": record.id, "incident_id": payload.incident_id},
    )

    return record.as_dict()


async def _build_question(
    payload: StartInvestigation,
    gateway: Gateway,
    principal: Principal,
    tenant: TenantConfig,
) -> str:
    """Give Holmes a concrete starting point rather than a bare incident id.

    Pulling the incident's own summary in costs one cheap read and measurably
    improves the first tool call the model chooses.
    """
    if payload.question and not payload.incident_id:
        return payload.question.strip()

    if not payload.incident_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "either incident_id or question is required"
        )

    headline = ""
    try:
        incident = await gateway.execute(
            "incidents.get",
            principal=principal,
            tenant=tenant,
            path_params={"incident_id": payload.incident_id},
        )
        if isinstance(incident, dict):
            name = (
                incident.get("user_generated_name")
                or incident.get("ai_generated_name")
                or ""
            )
            severity = incident.get("severity") or ""
            services = incident.get("services") or []
            bits = [b for b in (name, f"severity {severity}" if severity else "") if b]
            if services:
                bits.append("services: " + ", ".join(str(s) for s in services[:8]))
            headline = "; ".join(bits)
    except HTTPException:
        # Not fatal: Holmes can fetch the incident itself with get_incident. A
        # failed enrichment should not block the investigation.
        logger.info("could not pre-fetch incident %s for context", payload.incident_id)

    question = (
        f"Investigate incident {payload.incident_id} for the client "
        f"'{tenant.name}' (tenant id {tenant.id})."
    )
    if headline:
        question += f" What is known so far: {headline}."
    if payload.question:
        question += f" The operator also asks: {payload.question.strip()}"
    question += (
        " Determine the root cause using the chetana evidence tools and answer"
        " in the required structure."
    )
    return question


async def _run(
    *,
    store: Store,
    client: HolmesClient,
    investigation_id: str,
    tenant_id: str,
    question: str,
    token: str,
) -> None:
    started = time.perf_counter()
    try:
        result = await client.ask(
            question=question,
            evidence_token=token,
            tenant_id=tenant_id,
            system_prompt=SYSTEM_PROMPT,
        )
    except HolmesError as exc:
        await store.finish_investigation(
            investigation_id,
            status="failed",
            error=exc.message,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        logger.warning("investigation %s failed: %s", investigation_id, exc.message)
        return
    except Exception as exc:  # pragma: no cover - defensive
        await store.finish_investigation(
            investigation_id,
            status="failed",
            error=f"unexpected error: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        logger.exception("investigation %s crashed", investigation_id)
        return

    analysis = result.analysis
    await store.finish_investigation(
        investigation_id,
        status="complete" if analysis else "failed",
        finding=analysis or None,
        error=None if analysis else "HolmesGPT returned an empty analysis",
        reported_tool_calls=_summarise_tool_calls(result.tool_calls),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _summarise_tool_calls(calls: list[Any]) -> list[dict[str, Any]]:
    """Keep Holmes' self-reported calls small — the console compares them
    against our own evidence rows, it does not need the full payloads."""
    summary: list[dict[str, Any]] = []
    for call in calls[:60]:
        if not isinstance(call, dict):
            continue
        summary.append(
            {
                "tool": call.get("tool_name") or call.get("name") or "unknown",
                "description": str(call.get("description") or "")[:200],
            }
        )
    return summary
