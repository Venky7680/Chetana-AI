"""A small stand-in for Keep.

Two jobs:
  * the BFF test suite runs against it over an ASGI transport, so tests never
    need Docker;
  * `tasks.ps1 demo` runs it for real, so the console can be shown to a client
    before their Keep instance and providers exist.

It implements only the endpoints the allowlist actually uses, with the same
response shapes Keep returns. It is not a Keep reimplementation and must never
be deployed as one.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query

SERVICES = [
    ("core-banking-api", "prod-uae"),
    ("payments-gateway", "prod-uae"),
    ("customer-portal", "prod-ksa"),
    ("etl-nightly", "prod-uae"),
    ("identity-provider", "shared"),
    ("oci-object-store", "prod-ksa"),
    ("huawei-cce-cluster", "prod-ksa"),
    ("azure-sql-mi", "prod-uae"),
]
SOURCES = ["prometheus", "azuremonitor", "oraclecloud", "huaweicloud", "zabbix", "servicenow"]
SEVERITIES = ["critical", "high", "warning", "low", "info"]
TEMPLATES = [
    "High CPU on {service}",
    "{service} p99 latency above SLO",
    "Disk usage above 85% on {service}",
    "{service} health probe failing",
    "Replication lag on {service}",
    "Certificate expiring in 7 days for {service}",
    "Backup job failed for {service}",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def build_dataset(seed: int = 7) -> dict[str, Any]:
    rng = random.Random(seed)
    alerts: list[dict[str, Any]] = []
    for i in range(140):
        service, environment = rng.choice(SERVICES)
        name = rng.choice(TEMPLATES).format(service=service)
        severity = rng.choices(SEVERITIES, weights=[6, 14, 40, 25, 15])[0]
        received = _now() - timedelta(minutes=rng.randint(1, 60 * 30))
        alerts.append(
            {
                "id": f"alert-{i}",
                "fingerprint": _fingerprint(name, service, str(i)),
                "name": name,
                "description": f"{name} — detected by {rng.choice(SOURCES)}",
                "severity": severity,
                "status": rng.choices(
                    ["firing", "resolved", "acknowledged", "suppressed"],
                    weights=[55, 30, 10, 5],
                )[0],
                "source": [rng.choice(SOURCES)],
                "service": service,
                "environment": environment,
                "lastReceived": received.isoformat(),
                "assignee": rng.choice([None, None, None, "noc@intertecsys.com"]),
                "labels": {"cluster": environment, "team": "cloud-ops"},
                "enriched_fields": [],
            }
        )

    incidents: list[dict[str, Any]] = []
    pool = [a for a in alerts if a["status"] == "firing"]
    rng.shuffle(pool)
    cursor = 0
    for i in range(12):
        size = rng.randint(3, 14)
        members = pool[cursor : cursor + size]
        cursor += size
        if not members:
            break
        worst = max(members, key=lambda a: SEVERITIES.index(a["severity"]) * -1)
        started = min(a["lastReceived"] for a in members)
        incidents.append(
            {
                "id": f"inc-{i:03d}",
                "ai_generated_name": f"{worst['service']} degradation",
                "user_generated_name": None,
                "generated_summary": (
                    f"{len(members)} correlated alerts across {worst['service']}. "
                    "Probable cause ranked by PyRCA; investigation available."
                ),
                "status": rng.choices(
                    ["firing", "acknowledged", "resolved"], weights=[55, 25, 20]
                )[0],
                "severity": worst["severity"],
                "alerts_count": len(members),
                "services": sorted({a["service"] for a in members}),
                "alert_sources": sorted({s for a in members for s in a["source"]}),
                "assignee": rng.choice([None, "noc@intertecsys.com"]),
                "creation_time": started,
                "start_time": started,
                "last_seen_time": max(a["lastReceived"] for a in members),
                "is_candidate": rng.random() < 0.25,
                "is_predicted": rng.random() < 0.2,
                "rule_id": f"rule-{rng.randint(1, 4)}",
                "_alert_fingerprints": [a["fingerprint"] for a in members],
            }
        )

    workflows = [
        {
            "id": "wf-restart-pod",
            "name": "Restart unhealthy pod",
            "description": "Rolls the deployment behind a failing health probe.",
            "disabled": False,
            "revision": 4,
            "created_by": "rajagopal@intertecsys.com",
            "triggers": [{"type": "alert", "filters": [{"key": "name", "value": "health probe"}]}],
            "providers": [{"type": "kubernetes", "name": "prod-uae"}],
            "last_execution_time": (_now() - timedelta(hours=3)).isoformat(),
            "last_execution_status": "success",
        },
        {
            "id": "wf-scale-nodepool",
            "name": "Scale node pool +2",
            "description": "Adds two nodes to the affected node pool.",
            "disabled": False,
            "revision": 2,
            "created_by": "abhinav@intertecsys.com",
            "triggers": [{"type": "manual"}],
            "providers": [{"type": "huaweicloud", "name": "prod-ksa"}],
            "last_execution_time": (_now() - timedelta(days=2)).isoformat(),
            "last_execution_status": "success",
        },
        {
            "id": "wf-open-servicenow",
            "name": "Raise ServiceNow incident",
            "description": "Creates a P2 incident and attaches the RCA summary.",
            "disabled": False,
            "revision": 9,
            "created_by": "noc@intertecsys.com",
            "triggers": [{"type": "incident"}],
            "providers": [{"type": "servicenow", "name": "itsm"}],
            "last_execution_time": (_now() - timedelta(minutes=40)).isoformat(),
            "last_execution_status": "success",
        },
        {
            "id": "wf-purge-cache",
            "name": "Purge CDN cache",
            "description": "Invalidates the edge cache for the affected origin.",
            "disabled": True,
            "revision": 1,
            "created_by": "abhinav@intertecsys.com",
            "triggers": [{"type": "manual"}],
            "providers": [{"type": "cloudflare", "name": "edge"}],
            "last_execution_time": None,
            "last_execution_status": None,
        },
    ]

    return {
        "alerts": alerts,
        "incidents": incidents,
        "workflows": workflows,
        "runs": [],
        "maintenance": [],
        "mapping": [
            {
                "id": "map-1",
                "name": "Service owner lookup",
                "description": "Adds owning team and support tier from the CMDB extract",
                "matchers": [["service"]],
                "disabled": False,
                "priority": 10,
            }
        ],
        "extraction": [
            {
                "id": "ext-1",
                "name": "Pull instance from description",
                "attribute": "description",
                "regex": r"instance=(?P<instance>[\w\.\-]+)",
                "disabled": False,
                "pre": True,
                "priority": 10,
            }
        ],
        "rules": [
            {
                "id": "rule-1",
                "name": "Same service within 15m",
                "definition_cel": 'service == "core-banking-api"',
                "timeframe": 900,
                "grouping_criteria": ["service"],
                "created_by": "abhinav@intertecsys.com",
            }
        ],
    }


def create_app(seed: int = 7) -> FastAPI:
    app = FastAPI(title="Stub Keep", version="0.0.0-stub")
    data = build_dataset(seed)

    def _incident(incident_id: str) -> dict[str, Any]:
        for inc in data["incidents"]:
            if inc["id"] == incident_id:
                return inc
        raise HTTPException(404, "incident not found")

    @app.get("/status")
    def status() -> dict[str, Any]:
        return {"status": "ok", "stub": True}

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        """The image's HEALTHCHECK probes this; without it the stub reports
        unhealthy forever even though it is serving fine."""
        return {"status": "ok", "stub": True}

    @app.get("/whoami")
    def whoami() -> dict[str, Any]:
        return {"tenantId": "keep-stub"}

    @app.get("/alerts")
    def list_alerts(limit: int = Query(50), offset: int = Query(0)) -> dict[str, Any]:
        window = data["alerts"][offset : offset + limit]
        return {"limit": limit, "offset": offset, "count": len(data["alerts"]), "items": window}

    @app.get("/alerts/quality/metrics")
    def quality() -> dict[str, Any]:
        return {"alert_quality": {"prometheus": {"total": 40, "with_service": 38}}}

    @app.get("/alerts/{fingerprint}")
    def get_alert(fingerprint: str) -> dict[str, Any]:
        for alert in data["alerts"]:
            if alert["fingerprint"] == fingerprint:
                return alert
        raise HTTPException(404, "alert not found")

    @app.get("/alerts/{fingerprint}/history")
    def alert_history(fingerprint: str) -> list[dict[str, Any]]:
        return [a for a in data["alerts"] if a["fingerprint"] == fingerprint]

    @app.get("/alerts/{fingerprint}/audit")
    def alert_audit(fingerprint: str) -> list[dict[str, Any]]:
        return [{"fingerprint": fingerprint, "action": "created", "user_id": "keep"}]

    @app.post("/alerts/enrich")
    def enrich(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        for alert in data["alerts"]:
            if alert["fingerprint"] == body.get("fingerprint"):
                alert["labels"].update(body.get("enrichments") or {})
                alert["enriched_fields"] = sorted(body.get("enrichments", {}))
                return {"status": "ok"}
        raise HTTPException(404, "alert not found")

    @app.post("/alerts/search")
    def search(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        needle = str(body.get("query", {}).get("cel", "")).lower()
        items = [a for a in data["alerts"] if needle in a["name"].lower()] if needle else data["alerts"]
        return {"count": len(items), "items": items[:100]}

    @app.get("/incidents")
    def list_incidents(limit: int = Query(25), offset: int = Query(0)) -> dict[str, Any]:
        window = data["incidents"][offset : offset + limit]
        return {"limit": limit, "offset": offset, "count": len(data["incidents"]), "items": window}

    @app.get("/incidents/meta")
    def incidents_meta() -> dict[str, Any]:
        return {
            "statuses": ["firing", "acknowledged", "resolved"],
            "severities": SEVERITIES,
            "services": sorted({s for s, _ in SERVICES}),
        }

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict[str, Any]:
        return _incident(incident_id)

    @app.get("/incidents/{incident_id}/alerts")
    def incident_alerts(incident_id: str, limit: int = Query(200)) -> dict[str, Any]:
        inc = _incident(incident_id)
        members = [a for a in data["alerts"] if a["fingerprint"] in inc["_alert_fingerprints"]]
        return {"count": len(members), "items": members[:limit]}

    @app.get("/incidents/{incident_id}/workflows")
    def incident_workflows(incident_id: str, limit: int = Query(50)) -> dict[str, Any]:
        runs = [r for r in data["runs"] if r.get("incident_id") == incident_id]
        return {"count": len(runs), "items": runs[:limit]}

    @app.post("/incidents/{incident_id}/status")
    def change_status(incident_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        inc = _incident(incident_id)
        inc["status"] = body.get("status", inc["status"])
        return inc

    @app.post("/incidents/{incident_id}/comment")
    def comment(incident_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _incident(incident_id)
        return {"status": "ok", "comment": body.get("comment")}

    @app.post("/incidents/{incident_id}/confirm")
    def confirm(incident_id: str) -> dict[str, Any]:
        inc = _incident(incident_id)
        inc["is_candidate"] = False
        return inc

    @app.post("/incidents/merge")
    def merge(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return {"merged": body.get("source_incident_ids", []), "into": body.get("destination_incident_id")}

    @app.delete("/incidents/{incident_id}")
    def delete_incident(incident_id: str) -> dict[str, Any]:
        inc = _incident(incident_id)
        data["incidents"].remove(inc)
        return {"deleted": incident_id}

    @app.get("/workflows")
    def list_workflows() -> list[dict[str, Any]]:
        return data["workflows"]

    @app.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        for wf in data["workflows"]:
            if wf["id"] == workflow_id:
                return wf
        raise HTTPException(404, "workflow not found")

    @app.get("/workflows/{workflow_id}/raw")
    def raw_workflow(workflow_id: str) -> dict[str, Any]:
        get_workflow(workflow_id)
        return {"workflow_raw": f"workflow:\n  id: {workflow_id}\n  steps: []\n"}

    @app.get("/workflows/{workflow_id}/runs")
    def workflow_runs(workflow_id: str, limit: int = Query(25)) -> dict[str, Any]:
        runs = [r for r in data["runs"] if r["workflow_id"] == workflow_id]
        return {"count": len(runs), "items": runs[:limit]}

    @app.post("/workflows/{workflow_id}/run")
    def run_workflow(workflow_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        get_workflow(workflow_id)
        run = {
            "workflow_id": workflow_id,
            "workflow_execution_id": _fingerprint(workflow_id, _now().isoformat()),
            "status": "success",
            "started": _now().isoformat(),
            "incident_id": body.get("incident_id"),
            "requested_by": body.get("chetana_requested_by"),
        }
        data["runs"].append(run)
        return run

    @app.get("/providers")
    def providers() -> dict[str, Any]:
        return {
            "installed_providers": [
                {"id": "p1", "type": "prometheus", "details": {"name": "prod-uae"}},
                {"id": "p2", "type": "azuremonitor", "details": {"name": "azure-uae"}},
                {"id": "p3", "type": "oraclecloud", "details": {"name": "oci-ksa"}},
                {"id": "p4", "type": "servicenow", "details": {"name": "itsm"}},
            ],
            "providers": [
                {"type": "huaweicloud", "categories": ["Cloud Infrastructure"]},
                {"type": "kubernetes", "categories": ["Orchestration"]},
                {"type": "zabbix", "categories": ["Monitoring"]},
            ],
        }

    @app.get("/rules")
    def rules() -> list[dict[str, Any]]:
        return data["rules"]

    @app.get("/deduplications")
    def deduplications() -> list[dict[str, Any]]:
        return [
            {
                "id": "dedup-1",
                "name": "prometheus default",
                "provider_type": "prometheus",
                "ingested": 4120,
                "dedup_ratio": 71.4,
                "fingerprint_fields": ["labels.alertname", "labels.instance"],
            }
        ]

    @app.get("/maintenance")
    def maintenance() -> list[dict[str, Any]]:
        return data["maintenance"]

    @app.get("/topology")
    def topology() -> list[dict[str, Any]]:
        return [
            {"id": 1, "service": s, "display_name": s, "environment": e, "dependencies": []}
            for s, e in SERVICES
        ]

    @app.get("/deduplications/fields")
    def dedup_fields() -> dict[str, Any]:
        return {"prometheus": ["labels.alertname", "labels.instance", "labels.service"]}

    @app.post("/rules")
    def create_rule(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        rule = {
            "id": _fingerprint("rule", str(body)),
            "name": body.get("ruleName", "unnamed"),
            "definition_cel": body.get("celQuery", ""),
            "timeframe": body.get("timeframeInSeconds", 900),
            "grouping_criteria": body.get("groupingCriteria", []),
            "created_by": "seed",
        }
        data["rules"].append(rule)
        return rule

    @app.delete("/rules/{rule_id}")
    def delete_rule(rule_id: str) -> dict[str, Any]:
        return {"deleted": rule_id}

    @app.post("/maintenance")
    def create_maintenance(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        window = {"id": _fingerprint("mw", str(body)), "enabled": True, **body}
        data["maintenance"].append(window)
        return window

    @app.delete("/maintenance/{rule_id}")
    def delete_maintenance(rule_id: str) -> dict[str, Any]:
        data["maintenance"] = [m for m in data["maintenance"] if m["id"] != rule_id]
        return {"deleted": rule_id}

    @app.get("/topology/applications")
    def topology_applications() -> list[dict[str, Any]]:
        return [
            {
                "id": "app-1",
                "name": "Retail banking",
                "description": "Customer-facing banking journey",
                "services": [{"id": "1", "name": "core-banking-api"},
                             {"id": "2", "name": "payments-gateway"}],
            }
        ]

    @app.get("/mapping")
    def mapping_rules() -> list[dict[str, Any]]:
        return data["mapping"]

    @app.post("/mapping")
    def create_mapping(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        rule = {"id": _fingerprint("map", str(body.get("name"))), **body}
        data["mapping"].append(rule)
        return rule

    @app.get("/extraction")
    def extraction_rules() -> list[dict[str, Any]]:
        return data["extraction"]

    @app.post("/extraction")
    def create_extraction(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        rule = {"id": _fingerprint("ext", str(body.get("name"))), **body}
        data["extraction"].append(rule)
        return rule

    @app.get("/preset")
    def presets() -> list[dict[str, Any]]:
        return [
            {"id": "preset-1", "name": "feed", "options": [], "is_private": False},
            {"id": "preset-2", "name": "critical", "options": [], "is_private": False},
        ]

    return app


app = create_app()
