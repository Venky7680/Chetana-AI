"""The evidence gateway — the endpoints HolmesGPT calls back into.

This router is deliberately unlike every other one in the BFF: it does not
authenticate a console user. Its caller is an LLM running inside the Holmes
container, and its only credential is the per-investigation token minted when
the investigation started.

Every call is reduced to an allowlisted R0 operation and executed through the
same gateway as everything else, under a synthetic VIEWER principal named after
the investigation. So an evidence read appears in the audit trail as
`holmes:inv_ab12...` — attributable to an investigation, a tenant and the person
who asked for it, and structurally incapable of doing anything a viewer could
not do by hand.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status

from ..core import evidence as ev
from ..core.allowlist import Role
from ..core.config import TenantConfig
from ..core.security import Principal
from ..core.store import Store
from ..deps import GatewayDep, SettingsDep
from ..gateway import Gateway

logger = logging.getLogger("chetana.evidence")

router = APIRouter(prefix="/evidence", tags=["evidence"])


def _store(request: Request) -> Store:
    store: Store | None = getattr(request.app.state, "store", None)
    if store is None:  # pragma: no cover - only if startup failed
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store not ready")
    return store


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """What an investigation is permitted to look at.

    Unauthenticated on purpose: it is a description of the contract, contains no
    tenant data, and being able to point a client's security reviewer at it
    without issuing them a login is the whole point.

    Which corpus a given client's investigations may search is deliberately NOT
    here — that is tenant data, and it lives behind auth on /precedents.
    """
    return {"tools": ev.describe_tools()}


@router.get("/{tool_name}")
async def serve_evidence(
    tool_name: str,
    request: Request,
    gateway: GatewayDep,
    settings: SettingsDep,
    x_chetana_evidence_token: str | None = Header(default=None),
) -> Any:
    started = time.perf_counter()
    store = _store(request)

    if not x_chetana_evidence_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"missing {ev.EVIDENCE_HEADER} header"
        )

    try:
        grant = ev.verify_token(
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            token=x_chetana_evidence_token.strip(),
        )
    except ev.EvidenceTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        tool = ev.get_tool(tool_name)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    params = {k: v for k, v in request.query_params.items() if v not in (None, "")}

    async def refuse(code: int, detail: str) -> None:
        await store.record_evidence_call(
            investigation_id=grant.investigation_id,
            tool=tool_name,
            params=params,
            status="refused",
            status_code=code,
            detail=detail,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if not grant.permits(tool_name):
        await refuse(403, "tool not in this investigation's grant")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"'{tool_name}' is not granted to this investigation",
        )

    tenant = gateway.tenant(grant.tenant_id)
    if tenant is None or not tenant.enabled:
        await refuse(404, "tenant unavailable")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")

    # Budget is claimed before the work, so a refusal still costs a slot and a
    # model cannot probe the gateway for free.
    allowed, reason = await store.claim_evidence_slot(grant.investigation_id)
    if not allowed:
        await refuse(429, reason)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, reason)

    for spec in tool.params:
        if spec.required and not params.get(spec.name):
            await refuse(400, f"missing required parameter '{spec.name}'")
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{spec.name}' is required for {tool_name}",
            )
        if not spec.required and spec.default and not params.get(spec.name):
            params[spec.name] = spec.default

    try:
        if tool.kind == "prometheus":
            payload = await _serve_prometheus(
                tool, tenant, params, settings.request_timeout_seconds
            )
        elif tool.kind == "precedent":
            payload = _serve_precedents(request, tenant.id, params)
        else:
            payload = await _serve_keep(tool, gateway, tenant, grant, params)
    except HTTPException as exc:
        await store.record_evidence_call(
            investigation_id=grant.investigation_id,
            tool=tool_name,
            params=params,
            status="error",
            status_code=exc.status_code,
            detail=str(exc.detail)[:500],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        raise

    elapsed = int((time.perf_counter() - started) * 1000)
    await store.record_evidence_call(
        investigation_id=grant.investigation_id,
        tool=tool_name,
        params=params,
        status="ok",
        status_code=200,
        result_bytes=len(str(payload)),
        duration_ms=elapsed,
    )
    gateway.audit.record(
        actor=f"holmes:{grant.investigation_id}",
        tenant_id=tenant.id,
        operation_id=tool.operation_id or f"{tool.kind}.{tool.name}",
        decision="evidence",
        reason=f"investigation {grant.investigation_id}",
        tier=0,
        detail={"tool": tool_name, "params": params, "duration_ms": elapsed},
    )
    return payload


def _serve_precedents(
    request: Request, tenant_id: str, params: dict[str, str]
) -> dict[str, Any]:
    """Search the offline ticket corpus.

    The `source` block is returned alongside every result rather than only at
    load time, because it is the model's only way to know whether it is being
    shown real history. A corpus built from generated tickets says so here, in
    the same payload as the matches, where it cannot be separated from them.
    """
    store = getattr(request.app.state, "corpora", None)
    index = store.index(tenant_id) if store else None
    if index is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "no precedent corpus is loaded for this deployment",
        )

    try:
        limit = int(params.get("limit") or 5)
    except ValueError:
        limit = 5

    matches = index.search(
        params.get("symptom", ""),
        ci_class=params.get("ci_class", "") or "",
        limit=limit,
    )
    return {"source": index.describe(), "matches": matches}


async def _serve_keep(
    tool: ev.EvidenceTool,
    gateway: Gateway,
    tenant: TenantConfig,
    grant: ev.EvidenceGrant,
    params: dict[str, str],
) -> Any:
    assert tool.operation_id is not None

    path_params = {name: params[name] for name in tool.path_params if name in params}
    query_params: dict[str, Any] = dict(tool.fixed_query)
    for param_name, keep_name in tool.query_map.items():
        if param_name in params:
            query_params[keep_name] = params[param_name]

    # A viewer principal scoped to exactly one tenant. The gate, the allowlist
    # and the audit trail all apply unchanged — this is not a side door into
    # Keep, it is the front door with a narrower identity.
    principal = Principal(
        subject=f"holmes:{grant.investigation_id}",
        role=Role.VIEWER,
        tenants=(tenant.id,),
    )
    return await gateway.execute(
        tool.operation_id,
        principal=principal,
        tenant=tenant,
        path_params=path_params or None,
        query_params=query_params or None,
    )


async def _serve_prometheus(
    tool: ev.EvidenceTool,
    tenant: TenantConfig,
    params: dict[str, str],
    timeout: float,
) -> Any:
    if not tenant.prometheus_base_url:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no Prometheus is configured for tenant '{tenant.id}'",
        )

    query: dict[str, Any] = {}
    for param_name, prom_name in tool.query_map.items():
        if param_name in params:
            query[prom_name] = params[param_name]

    is_range = tool.prometheus_path == "/api/v1/query_range"
    requested_start = requested_end = 0.0
    if is_range:
        try:
            minutes = max(1, min(int(params.get("minutes", "60")), 60 * 24 * 90))
        except ValueError:
            minutes = 60
        requested_end = time.time()
        requested_start = requested_end - minutes * 60
        query["start"] = f"{requested_start:.3f}"
        query["end"] = f"{requested_end:.3f}"
        query.setdefault("step", "60s")

    url = f"{tenant.prometheus_base_url}{tool.prometheus_path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=query)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"could not reach Prometheus: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Prometheus returned {response.status_code}: {response.text[:300]}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Prometheus returned a non-JSON response"
        ) from exc

    if not is_range:
        return payload
    return _with_data_horizon(payload, requested_start, requested_end)


def _series_extent(payload: Any) -> tuple[float | None, float | None]:
    """Earliest and latest sample timestamps across every series returned."""
    earliest = latest = None
    result = (payload or {}).get("data", {}).get("result")
    if not isinstance(result, list):
        return None, None
    for series in result:
        values = series.get("values") if isinstance(series, dict) else None
        if not values:
            continue
        try:
            first, last = float(values[0][0]), float(values[-1][0])
        except (TypeError, ValueError, IndexError):
            continue
        earliest = first if earliest is None else min(earliest, first)
        latest = last if latest is None else max(latest, last)
    return earliest, latest


def _with_data_horizon(payload: Any, start: float, end: float) -> Any:
    """Tell the model how far back the data ACTUALLY goes.

    A range query that runs past the retention window comes back silently
    truncated: Prometheus returns 200 with the samples it has. To a reader —
    human or model — the oldest returned sample looks like the beginning of
    history, so "the metric was fine before the incident" and "we have no data
    from before the incident" become indistinguishable. That is not a
    hypothetical: an investigation cited a data point at the edge of retention
    as evidence that saturation *preceded* an alert that had fired nineteen
    hours earlier, which the store could not possibly have covered.

    So every range result carries the window that was asked for, the window
    actually returned, and a plain warning when the two disagree.
    """
    earliest, latest = _series_extent(payload)
    horizon: dict[str, Any] = {
        "requested_from": _iso(start),
        "requested_to": _iso(end),
        "data_from": _iso(earliest),
        "data_to": _iso(latest),
    }

    if earliest is None:
        horizon["warning"] = (
            "No samples were returned for this window. Either the query matches "
            "no series, or the whole window predates this Prometheus's retention. "
            "Do not read an empty result as evidence that the metric was healthy."
        )
    # A minute of slack: the first scrape rarely lands exactly on the boundary.
    elif earliest - start > 60:
        missing = (earliest - start) / 3600
        horizon["truncated"] = True
        horizon["warning"] = (
            f"Data begins at {_iso(earliest)}, about {missing:.1f}h after the start "
            f"of the window you asked for — the earlier part is outside this "
            f"Prometheus's retention. The oldest sample here is the limit of what "
            f"is stored, NOT the moment the behaviour began. Do not claim a metric "
            f"changed before a timestamp that falls outside this range; say the "
            f"data does not reach that far instead."
        )
    else:
        horizon["truncated"] = False

    return {"data_horizon": horizon, "result": payload}


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
