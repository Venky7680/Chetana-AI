"""End-to-end smoke test over real HTTP.

Boots the stub Keep and the BFF as separate processes, exercises the paths that
matter (sign-in, overview, the autonomy gate, four-eyes approval, estate), then
shuts both down. Run it after any change to the gateway:

    python tools/smoke_test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.security import hash_password  # noqa: E402

KEEP_PORT = 8099
BFF_PORT = 8088
BFF = f"http://127.0.0.1:{BFF_PORT}"
PASSWORD = "Demo!2345"

ok = 0
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label} — {detail}")
        print(f"  FAIL  {label} — {detail}")


def call(path: str, *, token: str | None = None, tenant: str | None = "demo", body=None, method="GET"):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if tenant:
        headers["X-Chetana-Tenant"] = tenant
    data = json.dumps(body).encode() if body is not None else None
    request = Request(f"{BFF}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload) if payload else None
    except HTTPError as exc:
        payload = exc.read().decode()
        return exc.code, json.loads(payload) if payload else None


def wait_for(url: str, attempts: int = 40) -> bool:
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    config = Path("/tmp/chetana-smoke")
    config.mkdir(exist_ok=True)
    pw = hash_password(PASSWORD)
    (config / "tenants.json").write_text(
        json.dumps(
            [
                {
                    "id": "demo",
                    "name": "Demo Client",
                    "keep_base_url": f"http://127.0.0.1:{KEEP_PORT}",
                    "keep_api_key": "stub",
                    "max_autonomy_tier": 1,
                    "tags": ["uae"],
                }
            ]
        )
    )
    (config / "users.json").write_text(
        json.dumps(
            [
                {"email": "operator@intertecsys.com", "password_hash": pw, "role": "operator", "tenants": ["*"]},
                {"email": "approver@intertecsys.com", "password_hash": pw, "role": "approver", "tenants": ["*"]},
            ]
        )
    )

    env = {
        **os.environ,
        "CHETANA_TENANTS_JSON": str(config / "tenants.json"),
        "CHETANA_USERS_JSON": str(config / "users.json"),
        "CHETANA_JWT_SECRET": "smoke-secret",
        "CHETANA_AUDIT_LOG_PATH": str(config / "audit.log"),
        "CHETANA_DATABASE_URL": f"sqlite+aiosqlite:///{config / 'smoke.db'}",
        # No HolmesGPT in the smoke stack: the checks below are about the
        # gateway's refusals, which must hold whether or not an engine exists.
        "CHETANA_HOLMES_BASE_URL": "",
    }

    keep = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tools.fake_keep:app", "--port", str(KEEP_PORT), "--log-level", "warning"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    bff = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(BFF_PORT), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if not wait_for(f"{BFF}/healthz"):
            print("BFF did not start")
            return 1

        status, ready = call("/readyz", tenant=None)
        check("readyz reaches Keep", ready and ready["status"] == "ok", str(ready))

        status, session = call(
            "/api/v1/auth/login",
            tenant=None,
            method="POST",
            body={"email": "operator@intertecsys.com", "password": PASSWORD},
        )
        check("operator signs in", status == 200, str(status))
        operator = session["access_token"]

        status, _ = call(
            "/api/v1/auth/login",
            tenant=None,
            method="POST",
            body={"email": "operator@intertecsys.com", "password": "wrong"},
        )
        check("bad password is rejected", status == 401, str(status))

        status, overview = call("/api/v1/overview", token=operator)
        check("overview returns stats", status == 200 and overview["stats"]["alerts_total"] > 0, str(status))
        check(
            "noise reduction is computed",
            overview["stats"]["noise_reduction_pct"] > 0,
            str(overview["stats"]),
        )

        status, alerts = call("/api/v1/alerts?limit=20", token=operator)
        check("alerts are normalised", status == 200 and "severity_rank" in alerts["items"][0], str(status))
        fingerprint = alerts["items"][0]["fingerprint"]

        status, _ = call(
            "/api/v1/alerts/enrich",
            token=operator,
            method="POST",
            body={"fingerprint": fingerprint, "enrichments": {"runbook": "RB-014"}},
        )
        check("tier 1 write executes", status == 200, str(status))

        status, parked = call(
            "/api/v1/workflows/wf-restart-pod/run",
            token=operator,
            method="POST",
            body={"reason": "smoke test"},
        )
        check("tier 2 write is parked", status == 202, str(status))
        approval_id = parked["detail"]["approval"]["id"]

        status, _ = call(
            f"/api/v1/approvals/{approval_id}/approve", token=operator, method="POST", body={"note": "self"}
        )
        check("requester cannot self-approve", status in (403, 409), str(status))

        _, session = call(
            "/api/v1/auth/login",
            tenant=None,
            method="POST",
            body={"email": "approver@intertecsys.com", "password": PASSWORD},
        )
        approver = session["access_token"]
        status, granted = call(
            f"/api/v1/approvals/{approval_id}/approve", token=approver, method="POST", body={"note": "ok"}
        )
        check("approver releases the action", status == 200 and granted["satisfied"], str(status))

        status, run = call(
            "/api/v1/workflows/wf-restart-pod/run",
            token=operator,
            method="POST",
            body={"reason": "smoke test", "approval_id": approval_id},
        )
        check("approved action executes", status == 200, str(status))

        status, _ = call(
            "/api/v1/workflows/wf-restart-pod/run",
            token=operator,
            method="POST",
            body={"approval_id": approval_id},
        )
        check("approval is single-use", status == 409, str(status))

        status, estate = call("/api/v1/estate", token=operator, tenant=None)
        check("estate view works", status == 200 and estate["totals"]["tenants"] == 1, str(status))

        status, audit = call("/api/v1/audit", token=operator)
        check(
            "audit captured the executed run",
            any(e["operation_id"] == "workflows.run" and e["decision"] == "executed" for e in audit),
            "not found in audit",
        )

        incident_id = overview["top_incidents"][0]["id"]
        status, detail = call(f"/api/v1/incidents/{incident_id}/detail", token=operator)
        check("incident detail fans out", status == 200 and len(detail["alerts"]) > 0, str(status))

        status, _ = call("/api/v1/alerts", token=operator, tenant="does-not-exist")
        check("unknown tenant is 404", status == 404, str(status))

        # --- Layer 5: the evidence gateway ---------------------------------
        # These refusals are the whole safety argument for letting an LLM near a
        # client estate, so they are smoke-tested over real HTTP, not just in
        # unit tests against an ASGI transport.
        status, tools = call("/api/v1/evidence/tools", tenant=None)
        check(
            "evidence toolset is publicly describable",
            status == 200 and any(t["name"] == "get_incident" for t in tools["tools"]),
            str(status),
        )
        check(
            "every evidence tool is read-only",
            all(t["operation_id"] is None or "delete" not in t["operation_id"] for t in tools["tools"]),
            "a non-read operation is exposed to the model",
        )

        status, _ = call("/api/v1/evidence/get_topology", tenant=None)
        check("evidence read without a token is 401", status == 401, str(status))

        status, _ = call(
            "/api/v1/evidence/get_topology", token=operator, tenant=None
        )
        check(
            "a console session token is not an evidence token",
            status == 401,
            str(status),
        )

        status, caps = call("/api/v1/investigations/capabilities", token=operator)
        check(
            "investigation capabilities report an unconfigured engine",
            status == 200 and caps["configured"] is False,
            str(status),
        )

        status, _ = call(
            "/api/v1/investigations",
            token=operator,
            method="POST",
            body={"incident_id": incident_id},
        )
        check("investigation without an engine is 503", status == 503, str(status))

    finally:
        for process in (bff, keep):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()

    print(f"\n{ok} checks passed, {len(failures)} failed")
    for failure in failures:
        print(f"  - {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
