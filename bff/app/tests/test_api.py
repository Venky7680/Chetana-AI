from __future__ import annotations

import pytest

from .conftest import auth_headers, login

pytestmark = pytest.mark.asyncio


async def test_health_does_not_require_auth(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_unauthenticated_requests_are_rejected(client):
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 401


async def test_viewer_can_list_alerts_normalised(client):
    token = await login(client, "viewer@intertecsys.com")
    response = await client.get("/api/v1/alerts", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["items"], "expected alerts from the stub"
    first = body["items"][0]
    assert {"fingerprint", "name", "severity", "severity_rank", "status"} <= set(first)
    # Sorted worst-first.
    ranks = [a["severity_rank"] for a in body["items"]]
    assert ranks == sorted(ranks, reverse=True)


async def test_tenant_entitlement_is_enforced(client):
    token = await login(client, "viewer@intertecsys.com")  # only entitled to almasraf
    response = await client.get("/api/v1/alerts", headers=auth_headers(token, tenant="das"))
    assert response.status_code == 404


async def test_unknown_tenant_is_404(client):
    token = await login(client, "admin@intertecsys.com")
    response = await client.get("/api/v1/alerts", headers=auth_headers(token, tenant="nope"))
    assert response.status_code == 404


async def test_viewer_cannot_write(client):
    token = await login(client, "viewer@intertecsys.com")
    response = await client.post(
        "/api/v1/alerts/enrich",
        headers=auth_headers(token),
        json={"fingerprint": "x", "enrichments": {"note": "hi"}},
    )
    assert response.status_code == 403


async def test_incident_detail_is_one_round_trip(client):
    token = await login(client, "operator@intertecsys.com")
    listing = await client.get("/api/v1/incidents", headers=auth_headers(token))
    incident_id = listing.json()["items"][0]["id"]

    response = await client.get(
        f"/api/v1/incidents/{incident_id}/detail", headers=auth_headers(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["incident"]["id"] == incident_id
    assert body["alerts"]
    assert body["degraded"] == []


async def test_tier_one_write_executes_within_ceiling(client):
    token = await login(client, "operator@intertecsys.com")
    alerts = await client.get("/api/v1/alerts", headers=auth_headers(token))
    fingerprint = alerts.json()["items"][0]["fingerprint"]

    response = await client.post(
        "/api/v1/alerts/enrich",
        headers=auth_headers(token),
        json={"fingerprint": fingerprint, "enrichments": {"runbook": "RB-014"}},
    )
    assert response.status_code == 200


async def test_workflow_run_is_parked_for_approval(client):
    """Tier 2 above the tenant ceiling: 202 with an approval request, no Keep call."""
    token = await login(client, "operator@intertecsys.com")
    response = await client.post(
        "/api/v1/workflows/wf-restart-pod/run",
        headers=auth_headers(token),
        json={"reason": "pod stuck in CrashLoopBackOff"},
    )
    assert response.status_code == 202
    detail = response.json()["detail"]
    assert detail["code"] == "approval_required"
    assert detail["approval"]["approvals_needed"] == 1


async def test_requester_cannot_approve_their_own_request(client):
    approver_token = await login(client, "approver@intertecsys.com")
    parked = await client.post(
        "/api/v1/workflows/wf-restart-pod/run",
        headers=auth_headers(approver_token),
        json={"reason": "self-approval attempt"},
    )
    approval_id = parked.json()["detail"]["approval"]["id"]

    response = await client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers=auth_headers(approver_token),
        json={"note": "me"},
    )
    assert response.status_code == 409
    assert "cannot be approved by the principal that requested it" in response.text


async def test_four_eyes_flow_releases_the_action(client):
    operator = await login(client, "operator@intertecsys.com")
    approver = await login(client, "approver@intertecsys.com")

    parked = await client.post(
        "/api/v1/workflows/wf-restart-pod/run",
        headers=auth_headers(operator),
        json={"reason": "health probe failing"},
    )
    approval_id = parked.json()["detail"]["approval"]["id"]

    granted = await client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers=auth_headers(approver),
        json={"note": "confirmed with client"},
    )
    assert granted.status_code == 200
    assert granted.json()["satisfied"] is True

    executed = await client.post(
        "/api/v1/workflows/wf-restart-pod/run",
        headers=auth_headers(operator),
        json={"reason": "health probe failing", "approval_id": approval_id},
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "success"

    # An approval is single-use.
    replay = await client.post(
        "/api/v1/workflows/wf-restart-pod/run",
        headers=auth_headers(operator),
        json={"approval_id": approval_id},
    )
    assert replay.status_code == 409


async def test_capabilities_tells_the_console_what_is_live(client):
    token = await login(client, "operator@intertecsys.com")
    response = await client.get("/api/v1/capabilities", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    decisions = {op["operation_id"]: op["decision"] for op in body["operations"]}
    assert decisions["alerts.list"] == "execute"
    assert decisions["workflows.run"] == "approval_required"
    assert decisions["incidents.delete"] == "denied"


async def test_overview_aggregates_and_computes_noise_reduction(client):
    token = await login(client, "operator@intertecsys.com")
    response = await client.get("/api/v1/overview", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["alerts_total"] > 0
    assert body["stats"]["noise_reduction_pct"] > 0
    assert body["autonomy"]["effective_ceiling"] == 1


async def test_estate_view_spans_entitled_tenants(client):
    token = await login(client, "admin@intertecsys.com")
    response = await client.get(
        "/api/v1/estate", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["tenants"] == 2


async def test_writes_are_audited(client):
    operator = await login(client, "operator@intertecsys.com")
    alerts = await client.get("/api/v1/alerts", headers=auth_headers(operator))
    fingerprint = alerts.json()["items"][0]["fingerprint"]
    await client.post(
        "/api/v1/alerts/enrich",
        headers=auth_headers(operator),
        json={"fingerprint": fingerprint, "enrichments": {"note": "audited"}},
    )

    response = await client.get("/api/v1/audit", headers=auth_headers(operator))
    assert response.status_code == 200
    entries = response.json()
    assert any(e["operation_id"] == "alerts.enrich" and e["decision"] == "executed" for e in entries)
