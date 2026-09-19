"""Configure a fresh Keep instance so the console has something to show.

A newly installed Keep has alerts and nothing else: no correlation rules, no
mapping, no extraction, no maintenance windows, no dashboards. Every one of
those pages is therefore honestly empty — which is correct, and also useless
for a demo.

This does what an implementer would do on day one: writes real configuration
into Keep through Keep's own REST API, matched to the lab estate that the
Prometheus pipeline is watching. Nothing here is faked into the console; it is
genuine Keep configuration that Keep then applies to genuine alerts.

    python ops/seed_keep.py                      # against http://localhost:8080
    python ops/seed_keep.py --url http://host:8080 --api-key KEY

Every request prints Keep's actual status code and, on failure, Keep's own
error body — so a schema that has drifted between Keep versions is visible
immediately rather than silently doing nothing.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

created = 0
skipped = 0
failed = 0


def call(base: str, key: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "x-api-key": key, "accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            text = response.read().decode()
            return response.status, json.loads(text) if text else None
    except HTTPError as exc:
        text = exc.read().decode()
        try:
            return exc.code, json.loads(text)
        except ValueError:
            return exc.code, text[:500]
    except URLError as exc:
        return 0, str(exc)


def post(base: str, key: str, label: str, path: str, body: Any) -> None:
    """POST one object, and say exactly what Keep made of it."""
    global created, skipped, failed
    status, payload = call(base, key, "POST", path, body)
    if 200 <= status < 300:
        created += 1
        print(f"  created  {label}")
    elif status in (409, 422) and _already_exists(payload):
        skipped += 1
        print(f"  exists   {label}")
    else:
        failed += 1
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        print(f"  FAILED   {label}  [HTTP {status}] {str(detail)[:220]}")


def _already_exists(payload: Any) -> bool:
    text = json.dumps(payload).lower() if payload is not None else ""
    return "already exist" in text or "duplicate" in text or "unique" in text


def existing_names(base: str, key: str, path: str, field: str = "name") -> set[str]:
    status, payload = call(base, key, "GET", path)
    if not (200 <= status < 300) or not isinstance(payload, list):
        return set()
    return {str(item.get(field)) for item in payload if isinstance(item, dict)}


# --------------------------------------------------------------------- content
#
# Everything below is scoped to the lab estate the Prometheus pipeline watches:
# payments-api and ledger-worker in prod-uae. Point it at a different estate by
# editing these, not by editing the console.

# Keep validates that sqlQuery.sql is non-empty and sqlQuery.params is a dict,
# then stores both and never executes the SQL — rulesengine.py matches purely on
# definition_cel. The SQL below is therefore a faithful, parameterised mirror of
# the CEL rather than a dummy: anyone reading the rule in Keep's database sees
# the same intent, and it cannot cause a wrong match.
CORRELATION_RULES = [
    {
        "ruleName": "Payments path degradation",
        "sqlQuery": {
            "sql": "((service like :service_1) or (service like :service_2))",
            "params": {"service_1": "payments-api", "service_2": "ledger-worker"},
        },
        "celQuery": '(service == "payments-api" || service == "ledger-worker")',
        "timeframeInSeconds": 900,
        "timeUnit": "seconds",
        "groupingCriteria": ["environment"],
        "groupDescription": "Payments and the ledger it depends on, degrading together",
        "requireApprove": False,
        "resolveOn": "never",
        "createOn": "any",
        "incidentNameTemplate": "Payments path degraded",
        "threshold": 1,
    },
    {
        "ruleName": "Saturation cluster",
        "sqlQuery": {
            "sql": "((name like :name_1) or (name like :name_2))",
            "params": {"name_1": "%Saturated%", "name_2": "%Backlog%"},
        },
        "celQuery": 'name.contains("Saturated") || name.contains("Backlog")',
        "timeframeInSeconds": 600,
        "timeUnit": "seconds",
        "groupingCriteria": ["service"],
        "groupDescription": "Pool and queue pressure on one service",
        "requireApprove": False,
        "resolveOn": "never",
        "createOn": "any",
        "incidentNameTemplate": "Saturation on {{ service }}",
        "threshold": 2,
    },
    {
        "ruleName": "Hard outage",
        "sqlQuery": {
            "sql": "(severity like :severity_1)",
            "params": {"severity_1": "critical"},
        },
        "celQuery": 'severity == "critical"',
        "timeframeInSeconds": 300,
        "timeUnit": "seconds",
        "groupingCriteria": ["service"],
        "groupDescription": "Anything critical on a single service, grouped tightly",
        "requireApprove": False,
        "resolveOn": "never",
        "createOn": "any",
        "incidentNameTemplate": "{{ service }} outage",
        "threshold": 1,
    },
]

MAPPING_RULES = [
    {
        "name": "Service ownership",
        "description": "Adds owning team, support tier, CMDB id and runbook from the service name",
        "type": "csv",
        "priority": 10,
        "disabled": False,
        "override": True,
        "matchers": [["service"]],
        "rows": [
            {
                "service": "payments-api",
                "owning_team": "Payments Engineering",
                "support_tier": "gold",
                "cmdb_id": "CI-00412",
                "runbook": "RB-003",
                "escalation": "payments-oncall@intertecsys.com",
            },
            {
                "service": "ledger-worker",
                "owning_team": "Core Banking",
                "support_tier": "gold",
                "cmdb_id": "CI-00417",
                "runbook": "RB-006",
                "escalation": "core-oncall@intertecsys.com",
            },
            {
                "service": "prometheus",
                "owning_team": "Cloud Operations",
                "support_tier": "silver",
                "cmdb_id": "CI-00901",
                "runbook": "RB-100",
                "escalation": "noc@intertecsys.com",
            },
        ],
    },
    {
        "name": "Environment criticality",
        "description": "Marks which environments page out of hours",
        "type": "csv",
        "priority": 20,
        "disabled": False,
        "override": False,
        "matchers": [["environment"]],
        "rows": [
            {"environment": "prod-uae", "business_impact": "customer-facing", "out_of_hours": "page"},
            {"environment": "prod-ksa", "business_impact": "customer-facing", "out_of_hours": "page"},
            {"environment": "shared", "business_impact": "internal", "out_of_hours": "ticket"},
        ],
    },
]

EXTRACTION_RULES = [
    {
        "name": "Instance from description",
        "description": "Promotes the host buried in the alert description to a real field",
        "priority": 10,
        "attribute": "description",
        "regex": r"instance=(?P<instance>[\w\.\-:]+)",
        "disabled": False,
        "pre": True,
    },
    {
        "name": "Runbook reference",
        "description": "Lifts the RB-xxx reference our rules annotate alerts with",
        "priority": 20,
        "attribute": "description",
        "regex": r"(?P<runbook_ref>RB-\d{3})",
        "disabled": False,
        "pre": False,
    },
    {
        "name": "Percentage threshold",
        "description": "Extracts the breached percentage so it can be filtered on",
        "priority": 30,
        "attribute": "description",
        "regex": r"above (?P<threshold_pct>\d+(?:\.\d+)?)%",
        "disabled": False,
        "pre": False,
    },
]


def maintenance_windows() -> list[dict[str, Any]]:
    """A window that has already expired, and one scheduled ahead.

    Both are real: Keep applies the future one when its time comes.
    """
    now = datetime.now(timezone.utc)
    return [
        {
            "name": "Ledger patching (scheduled)",
            "description": "Monthly patch window for the settlement workers",
            "cel_query": 'service == "ledger-worker"',
            "start_time": (now + timedelta(days=3)).isoformat(),
            "duration_seconds": 3 * 3600,
            "enabled": True,
            "suppress": True,
        },
        {
            "name": "Prometheus upgrade (completed)",
            "description": "Kept for the audit trail — shows a closed window",
            "cel_query": 'service == "prometheus"',
            "start_time": (now - timedelta(days=2)).isoformat(),
            "duration_seconds": 2 * 3600,
            "enabled": False,
            "suppress": True,
        },
    ]


# The dependency graph of the lab estate, in call order:
#
#     loadgen ──► payments-api ──► ledger-worker
#
# Direction is "caller depends on callee". Getting it backwards makes the
# investigation engine blame the victim, so it is worth reading twice.
TOPOLOGY_SERVICES: list[dict[str, Any]] = [
    {
        "service": "loadgen",
        "display_name": "Load generator (synthetic callers)",
        "environment": "prod-uae",
        "description": (
            "Stands in for customer traffic against the payments path. Real HTTP, "
            "sine-wave concurrency — not a mock."
        ),
        "team": "Platform Engineering",
        "category": "client",
    },
    {
        "service": "payments-api",
        "display_name": "Payments API",
        "environment": "prod-uae",
        "description": (
            "Customer-facing payments endpoint. Holds a bounded connection pool to "
            "ledger-worker and sheds load as 503 when that pool saturates."
        ),
        "team": "Payments Engineering",
        "category": "api",
    },
    {
        "service": "ledger-worker",
        "display_name": "Ledger Worker",
        "environment": "prod-uae",
        "description": (
            "Performs ledger settlement behind a bounded worker pool. Contention "
            "here is what shows up downstream as payments-api latency and 5xx."
        ),
        "team": "Core Banking",
        "category": "worker",
    },
]

TOPOLOGY_DEPENDENCIES: list[tuple[str, str, str]] = [
    ("loadgen", "payments-api", "HTTP"),
    ("payments-api", "ledger-worker", "HTTP"),
]


def topology(base: str, key: str) -> None:
    """Declare the service graph so cause and victim are distinguishable.

    Keep normally discovers topology from a provider that exposes a service map;
    a Prometheus webhook does not. But Keep also accepts services and edges
    declared by hand, and an MSP generally knows the graph anyway. Without it the
    investigation engine can only infer direction from alert wording, which is
    exactly the kind of evidence that produces a confident wrong answer.
    """
    global created, skipped, failed

    status, existing = call(base, key, "GET", "/topology")
    by_name: dict[str, int] = {}
    edges: set[tuple[int, int]] = set()
    if 200 <= status < 300 and isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            name, sid = item.get("service"), item.get("id")
            if name is not None and sid is not None:
                by_name[str(name)] = int(sid)
            for dep in item.get("dependencies") or []:
                if isinstance(dep, dict) and dep.get("serviceId") is not None:
                    edges.add((int(sid), int(dep["serviceId"])))

    print("\nService topology")
    for service in TOPOLOGY_SERVICES:
        name = service["service"]
        if name in by_name:
            print(f"  exists   {name}")
            skipped += 1
            continue
        code, payload = call(base, key, "POST", "/topology/service", service)
        if 200 <= code < 300 and isinstance(payload, dict) and payload.get("id") is not None:
            by_name[name] = int(payload["id"])
            created += 1
            print(f"  created  {name}")
        else:
            failed += 1
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            print(f"  FAILED   {name}  [HTTP {code}] {str(detail)[:220]}")

    for caller, callee, protocol in TOPOLOGY_DEPENDENCIES:
        label = f"{caller} -> {callee}"
        if caller not in by_name or callee not in by_name:
            print(f"  skipped  {label}  (a service is missing)")
            skipped += 1
            continue
        pair = (by_name[caller], by_name[callee])
        if pair in edges:
            print(f"  exists   {label}")
            skipped += 1
            continue
        post(
            base,
            key,
            label,
            "/topology/dependency",
            {
                "service_id": pair[0],
                "depends_on_service_id": pair[1],
                "protocol": protocol,
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080", help="Keep API base URL")
    parser.add_argument("--api-key", default="chetana-local-dev-key")
    args = parser.parse_args()

    base, key = args.url, args.api_key

    status, _ = call(base, key, "GET", "/status")
    if not (200 <= status < 300):
        print(f"Keep is not answering at {base} (HTTP {status}).")
        print("Start it first:  docker compose --profile real up -d keep-backend")
        return 1
    print(f"Keep reachable at {base}\n")

    print("Correlation rules")
    have = existing_names(base, key, "/rules")
    for rule in CORRELATION_RULES:
        if rule["ruleName"] in have:
            print(f"  exists   {rule['ruleName']}")
        else:
            post(base, key, rule["ruleName"], "/rules", rule)

    print("\nMapping rules")
    have = existing_names(base, key, "/mapping")
    for rule in MAPPING_RULES:
        if rule["name"] in have:
            print(f"  exists   {rule['name']}")
        else:
            post(base, key, rule["name"], "/mapping", rule)

    print("\nExtraction rules")
    have = existing_names(base, key, "/extraction")
    for rule in EXTRACTION_RULES:
        if rule["name"] in have:
            print(f"  exists   {rule['name']}")
        else:
            post(base, key, rule["name"], "/extraction", rule)

    print("\nMaintenance windows")
    have = existing_names(base, key, "/maintenance")
    for window in maintenance_windows():
        if window["name"] in have:
            print(f"  exists   {window['name']}")
        else:
            post(base, key, window["name"], "/maintenance", window)

    topology(base, key)

    print(f"\n{created} created, {skipped} already present, {failed} rejected by Keep")
    if failed:
        print(
            "\nA rejection above is Keep telling us its schema differs from what this\n"
            "script sends — the status code and Keep's own message are printed with it.\n"
            "Nothing was faked into the console as a result."
        )
    print(
        "\nNot seeded, deliberately:\n"
        "  Dashboards       — a dashboard is a layout you arrange in Keep's own UI.\n"
        "  AI Plugins       — no REST endpoint in this Keep version.\n"
        "\nService topology IS seeded above. Keep discovers topology from providers\n"
        "that expose a service map, which a Prometheus webhook does not — but it also\n"
        "accepts services and edges declared by hand, and the graph is what lets the\n"
        "investigation engine tell a cause from a victim instead of guessing from\n"
        "alert wording."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
