"""The operations overview — one call, whole picture.

Also serves the cross-tenant "estate" view an MSP NOC needs: every client on one
screen, worst first.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request

from ..core.normalize import normalize_alert, normalize_incident, summarize, unwrap_items
from ..deps import GatewayDep, PrincipalDep, TenantDep

router = APIRouter(tags=["overview"])


async def _tenant_snapshot(gateway, principal, tenant) -> dict[str, Any]:
    alerts_payload, incidents_payload = await asyncio.gather(
        gateway.execute(
            "alerts.list", principal=principal, tenant=tenant, query_params={"limit": 500}
        ),
        gateway.execute(
            "incidents.list", principal=principal, tenant=tenant, query_params={"limit": 200}
        ),
        return_exceptions=True,
    )

    problems: list[str] = []
    alerts: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []

    if isinstance(alerts_payload, BaseException):
        problems.append(f"alerts: {alerts_payload}")
    else:
        alerts = [normalize_alert(a) for a in unwrap_items(alerts_payload)]

    if isinstance(incidents_payload, BaseException):
        problems.append(f"incidents: {incidents_payload}")
    else:
        incidents = [normalize_incident(i) for i in unwrap_items(incidents_payload)]

    stats = summarize(alerts, incidents)
    return {
        "tenant": {"id": tenant.id, "name": tenant.name, "tags": tenant.tags},
        "stats": stats,
        "reachable": not problems,
        "problems": problems,
        "alerts": alerts,
        "incidents": incidents,
    }


@router.get("/overview")
async def overview(gateway: GatewayDep, principal: PrincipalDep, tenant: TenantDep) -> dict[str, Any]:
    snapshot = await _tenant_snapshot(gateway, principal, tenant)

    top_incidents = sorted(
        [i for i in snapshot["incidents"] if i["is_open"]],
        key=lambda i: (i["severity_rank"], int(i["alerts_count"] or 0)),
        reverse=True,
    )[:8]

    recent_alerts = sorted(
        snapshot["alerts"], key=lambda a: a["last_received"] or "", reverse=True
    )[:12]

    by_service: dict[str, int] = {}
    for alert in snapshot["alerts"]:
        key = alert["service"] or alert["environment"] or "unattributed"
        by_service[str(key)] = by_service.get(str(key), 0) + 1
    noisiest = sorted(by_service.items(), key=lambda kv: kv[1], reverse=True)[:8]

    return {
        "tenant": snapshot["tenant"],
        "stats": snapshot["stats"],
        "reachable": snapshot["reachable"],
        "problems": snapshot["problems"],
        "top_incidents": top_incidents,
        "recent_alerts": recent_alerts,
        "noisiest_services": [{"name": k, "alerts": v} for k, v in noisiest],
        "autonomy": {
            "tenant_ceiling": tenant.max_autonomy_tier,
            "global_ceiling": gateway.settings.global_max_autonomy_tier,
            "effective_ceiling": min(
                tenant.max_autonomy_tier, gateway.settings.global_max_autonomy_tier
            ),
            "pending_approvals": len(gateway.approvals.list(tenant.id)),
        },
    }


@router.get("/estate")
async def estate(gateway: GatewayDep, principal: PrincipalDep) -> dict[str, Any]:
    """Every tenant this principal can see, worst first. The MSP NOC wall."""
    tenants = gateway.tenants_for(principal)
    snapshots = await asyncio.gather(
        *(_tenant_snapshot(gateway, principal, t) for t in tenants),
        return_exceptions=True,
    )

    rows: list[dict[str, Any]] = []
    for tenant, snapshot in zip(tenants, snapshots):
        if isinstance(snapshot, BaseException):
            rows.append(
                {
                    "tenant": {"id": tenant.id, "name": tenant.name, "tags": tenant.tags},
                    "reachable": False,
                    "problems": [str(snapshot)],
                    "stats": {},
                }
            )
            continue
        rows.append(
            {
                "tenant": snapshot["tenant"],
                "reachable": snapshot["reachable"],
                "problems": snapshot["problems"],
                "stats": snapshot["stats"],
                "pending_approvals": len(gateway.approvals.list(tenant.id)),
            }
        )

    rows.sort(
        key=lambda r: (
            r["reachable"],
            -(r["stats"].get("critical_open", 0)),
            -(r["stats"].get("incidents_open", 0)),
        )
    )

    totals = {
        "tenants": len(rows),
        "unreachable": len([r for r in rows if not r["reachable"]]),
        "incidents_open": sum(r["stats"].get("incidents_open", 0) for r in rows),
        "alerts_firing": sum(r["stats"].get("alerts_firing", 0) for r in rows),
        "critical_open": sum(r["stats"].get("critical_open", 0) for r in rows),
    }
    return {"totals": totals, "tenants": rows}


# --------------------------------------------------------------------- analytics
@router.get("/analytics")
async def analytics(
    request: Request,
    gateway: GatewayDep,
    principal: PrincipalDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """The numbers an MSP actually reports on, computed here rather than five
    times in the browser.

    This replaced a page that listed dashboards built in Keep's own canvas. That
    page was honest and useless: nobody had built one, so it was permanently
    empty, and building one meant leaving Chetana. Everything below is derived
    from data the platform already holds.
    """
    snapshot = await _tenant_snapshot(gateway, principal, tenant)
    alerts = snapshot["alerts"]
    incidents = snapshot["incidents"]

    # --- alert volume over time -------------------------------------------
    # Bucketed hourly from the alerts Keep returned. The window is whatever
    # those alerts span, and it is stated in the response rather than implied,
    # because a chart whose axis silently means "the last 500 alerts" invites
    # exactly the kind of wrong conclusion the investigation engine now guards
    # against.
    stamps: list[datetime] = []
    for alert in alerts:
        parsed = _parse(alert.get("last_received"))
        if parsed:
            stamps.append(parsed)

    volume: list[dict[str, Any]] = []
    window_from = window_to = None
    if stamps:
        window_from, window_to = min(stamps), max(stamps)
        span_hours = max(1, int((window_to - window_from).total_seconds() // 3600) + 1)
        # Keep the bar count readable: widen the bucket rather than render 300 bars.
        bucket_hours = 1 if span_hours <= 36 else max(1, span_hours // 36)
        buckets: dict[datetime, int] = {}
        for stamp in stamps:
            offset = int((stamp - window_from).total_seconds() // 3600) // bucket_hours
            key = window_from + timedelta(hours=offset * bucket_hours)
            buckets[key] = buckets.get(key, 0) + 1
        cursor = window_from.replace(minute=0, second=0, microsecond=0)
        while cursor <= window_to:
            volume.append({"at": cursor.isoformat(), "count": buckets.get(cursor, 0)})
            cursor += timedelta(hours=bucket_hours)

    # --- noisiest services -------------------------------------------------
    by_service: dict[str, int] = {}
    for alert in alerts:
        key = str(alert.get("service") or alert.get("environment") or "unattributed")
        by_service[key] = by_service.get(key, 0) + 1
    services = [
        {"name": name, "count": count}
        for name, count in sorted(by_service.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]

    # --- incidents ---------------------------------------------------------
    by_status: dict[str, int] = {}
    for incident in incidents:
        by_status[str(incident.get("status") or "unknown")] = (
            by_status.get(str(incident.get("status") or "unknown"), 0) + 1
        )

    # --- how the investigation engine is doing -----------------------------
    store = getattr(request.app.state, "store", None)
    investigations: dict[str, Any] = {"total": 0}
    if store is not None:
        records = await store.list_investigations(tenant_id=tenant.id, limit=200)
        complete = [r for r in records if r.status == "complete"]
        failed = [r for r in records if r.status == "failed"]
        durations = [r.duration_ms for r in complete if r.duration_ms]
        investigations = {
            "total": len(records),
            "complete": len(complete),
            "failed": len(failed),
            "evidence_reads": sum(r.evidence_used or 0 for r in records),
            "median_seconds": (
                round(sorted(durations)[len(durations) // 2] / 1000, 1) if durations else None
            ),
        }

    return {
        "tenant": snapshot["tenant"],
        "stats": snapshot["stats"],
        "problems": snapshot["problems"],
        "window": {
            "from": window_from.isoformat() if window_from else None,
            "to": window_to.isoformat() if window_to else None,
            "alerts_sampled": len(alerts),
        },
        "alert_volume": volume,
        "noisiest_services": services,
        "incidents_by_status": by_status,
        "investigations": investigations,
    }


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
