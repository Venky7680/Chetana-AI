"""Shape Keep payloads into the contract the console codes against.

Keep's alert objects are intentionally open-ended — providers push whatever they
have. The console should not be re-learning ten provider dialects, so the BFF
normalises the fields the UI depends on and keeps everything else under `raw`.

Normalisation is tolerant by design: a missing field becomes `None`, never an
exception, because one malformed alert must not take a client's console down.
"""

from __future__ import annotations

from typing import Any, Iterable

SEVERITY_ORDER = {
    "critical": 5,
    "high": 4,
    "warning": 3,
    "medium": 3,
    "low": 2,
    "info": 1,
    "informational": 1,
}

OPEN_INCIDENT_STATUSES = {"firing", "acknowledged", "open", "in_progress"}


def _first(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = payload.get(name)
        if value not in (None, "", []):
            return value
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def severity_rank(severity: Any) -> int:
    return SEVERITY_ORDER.get(str(severity or "").strip().lower(), 0)


def normalize_alert(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"raw": payload}
    severity = _first(payload, "severity")
    return {
        "fingerprint": _first(payload, "fingerprint", "id"),
        "name": _first(payload, "name", "title", "alertname") or "(unnamed alert)",
        "description": _first(payload, "description", "message", "summary"),
        "status": str(_first(payload, "status") or "unknown").lower(),
        "severity": str(severity or "unknown").lower(),
        "severity_rank": severity_rank(severity),
        "source": _as_list(_first(payload, "source", "providerType")),
        "service": _first(payload, "service"),
        "environment": _first(payload, "environment"),
        "last_received": _first(payload, "lastReceived", "last_received", "timestamp"),
        "first_received": _first(payload, "firstTimestamp", "first_received"),
        "assignee": _first(payload, "assignee"),
        "url": _first(payload, "url", "generatorURL"),
        "incident_ids": _as_list(_first(payload, "incident", "incident_id", "incidents")),
        "labels": _first(payload, "labels") or {},
        "enriched_fields": _first(payload, "enriched_fields") or [],
        "raw": payload,
    }


def normalize_incident(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"raw": payload}
    severity = _first(payload, "severity", "user_severity")
    status = str(_first(payload, "status") or "unknown").lower()
    return {
        "id": _first(payload, "id", "incident_id"),
        "name": _first(payload, "user_generated_name", "ai_generated_name", "name")
        or "(untitled incident)",
        "summary": _first(payload, "user_summary", "generated_summary", "summary"),
        "status": status,
        "is_open": status in OPEN_INCIDENT_STATUSES,
        "severity": str(severity or "unknown").lower(),
        "severity_rank": severity_rank(severity),
        "alerts_count": _first(payload, "alerts_count", "number_of_alerts") or 0,
        "services": _as_list(_first(payload, "services", "affected_services")),
        "sources": _as_list(_first(payload, "alert_sources", "sources")),
        "assignee": _first(payload, "assignee"),
        "created_at": _first(payload, "creation_time", "created_at"),
        "started_at": _first(payload, "start_time", "started_at"),
        "last_seen_at": _first(payload, "last_seen_time", "end_time"),
        "is_candidate": bool(_first(payload, "is_candidate") or False),
        "is_predicted": bool(_first(payload, "is_predicted") or False),
        "rule_id": _first(payload, "rule_id"),
        "raw": payload,
    }


def normalize_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"raw": payload}
    return {
        "id": _first(payload, "id", "workflow_id"),
        "name": _first(payload, "name") or "(unnamed workflow)",
        "description": _first(payload, "description"),
        "disabled": bool(_first(payload, "disabled") or False),
        "revision": _first(payload, "revision"),
        "created_by": _first(payload, "created_by"),
        "interval": _first(payload, "interval"),
        "triggers": _as_list(_first(payload, "triggers")),
        "providers": _as_list(_first(payload, "providers")),
        "last_execution_time": _first(payload, "last_execution_time"),
        "last_execution_status": _first(payload, "last_execution_status"),
        "executions_count": _first(payload, "workflow_raw_id", "executions_count") or 0,
        "raw": payload,
    }


def unwrap_items(payload: Any) -> list[dict[str, Any]]:
    """Keep returns either a bare list or a paginated envelope. Handle both."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "alerts", "incidents", "workflows", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [p for p in value if isinstance(p, dict)]
    return []


def envelope(payload: Any, items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Preserve Keep's paging metadata alongside the normalised items."""
    items = list(items)
    meta = {"count": len(items), "limit": None, "offset": None, "total": len(items)}
    if isinstance(payload, dict):
        meta["limit"] = payload.get("limit")
        meta["offset"] = payload.get("offset")
        meta["total"] = payload.get("count", payload.get("total", len(items)))
    return {"items": items, "meta": meta}


def summarize(alerts: list[dict[str, Any]], incidents: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts the overview page needs, computed once in the BFF rather than
    five times in the browser."""
    by_severity: dict[str, int] = {}
    for alert in alerts:
        by_severity[alert["severity"]] = by_severity.get(alert["severity"], 0) + 1

    firing = [a for a in alerts if a["status"] in {"firing", "alerting", "open"}]
    open_incidents = [i for i in incidents if i["is_open"]]
    correlated = sum(int(i["alerts_count"] or 0) for i in incidents)

    # Noise reduction: how many raw alerts collapsed into how many incidents.
    reduction = 0.0
    if correlated:
        reduction = round((1 - (len(incidents) / correlated)) * 100, 1)

    return {
        "alerts_total": len(alerts),
        "alerts_firing": len(firing),
        "alerts_by_severity": by_severity,
        "incidents_total": len(incidents),
        "incidents_open": len(open_incidents),
        "alerts_correlated": correlated,
        "noise_reduction_pct": reduction,
        "unassigned_incidents": len([i for i in open_incidents if not i["assignee"]]),
        "critical_open": len([i for i in open_incidents if i["severity_rank"] >= 5]),
    }


# ---------------------------------------------------------------------- facets

def _bucket(values: Iterable[Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value) if value not in (None, "", []) else "None"
        counts[key] = counts.get(key, 0) + 1
    return sorted(
        ({"value": k, "count": v} for k, v in counts.items()),
        key=lambda o: (o["value"] == "None", -o["count"], o["value"]),
    )


def incident_facets(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Facet counts over the incidents actually loaded.

    Computed here rather than in the browser so every client — and any future
    mobile or CLI surface — sees the same numbers, and so a page of 500 rows
    does not have to be counted five times in JavaScript.
    """
    return [
        {"key": "status", "label": "Status", "options": _bucket(i["status"] for i in incidents)},
        {"key": "severity", "label": "Severity", "options": _bucket(i["severity"] for i in incidents)},
        {
            "key": "assignee",
            "label": "Assignee",
            "options": _bucket(i["assignee"] for i in incidents),
        },
        {
            "key": "source",
            "label": "Source",
            "options": _bucket(s for i in incidents for s in (i["sources"] or [None])),
        },
        {
            "key": "service",
            "label": "Service",
            "options": _bucket(s for i in incidents for s in (i["services"] or [None])),
        },
        {
            "key": "linked",
            "label": "Linked incident",
            "options": _bucket("Yes" if i["rule_id"] else "No" for i in incidents),
        },
    ]


def alert_facets(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"key": "status", "label": "Status", "options": _bucket(a["status"] for a in alerts)},
        {"key": "severity", "label": "Severity", "options": _bucket(a["severity"] for a in alerts)},
        {
            "key": "source",
            "label": "Source",
            "options": _bucket(s for a in alerts for s in (a["source"] or [None])),
        },
        {"key": "service", "label": "Service", "options": _bucket(a["service"] for a in alerts)},
        {
            "key": "environment",
            "label": "Environment",
            "options": _bucket(a["environment"] for a in alerts),
        },
        {"key": "assignee", "label": "Assignee", "options": _bucket(a["assignee"] for a in alerts)},
    ]
