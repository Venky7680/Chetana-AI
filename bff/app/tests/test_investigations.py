"""Tests for Layer 5: the investigation lifecycle and the evidence gateway.

The gateway is the part that matters. It is the one endpoint in the BFF that is
called by a language model rather than by a person, so its refusals are load
bearing: if the token scoping is wrong, an LLM reads another client's estate.
"""

from __future__ import annotations


import pytest

from app.core import evidence as ev

from .conftest import auth_headers, login

pytestmark = pytest.mark.asyncio

SECRET = "test-secret"


def _token(
    *,
    investigation_id: str,
    tenant_id: str = "almasraf",
    tools: tuple[str, ...] | None = None,
    ttl: int = 300,
) -> str:
    return ev.mint_token(
        secret=SECRET,
        algorithm="HS256",
        investigation_id=investigation_id,
        tenant_id=tenant_id,
        tools=tools if tools is not None else ev.ALL_TOOL_NAMES,
        ttl_seconds=ttl,
    )


def _evidence_headers(token: str) -> dict[str, str]:
    return {ev.EVIDENCE_HEADER: token}


# --------------------------------------------------------------- the gateway
async def test_evidence_tools_are_publicly_describable(client):
    response = await client.get("/api/v1/evidence/tools")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()["tools"]}
    assert "get_incident" in names
    # No tenant data leaks through this endpoint.
    assert "keep_api_key" not in response.text


async def test_evidence_requires_a_token(client):
    response = await client.get("/api/v1/evidence/get_topology")
    assert response.status_code == 401


async def test_evidence_rejects_a_forged_token(client):
    forged = ev.mint_token(
        secret="not-the-secret",
        algorithm="HS256",
        investigation_id="inv_x",
        tenant_id="almasraf",
        tools=ev.ALL_TOOL_NAMES,
        ttl_seconds=300,
    )
    response = await client.get(
        "/api/v1/evidence/get_topology", headers=_evidence_headers(forged)
    )
    assert response.status_code == 401


async def test_evidence_refuses_a_tool_outside_the_grant(client):
    """A grant is a fixed list. Holmes asking for something not on it is a 403
    even though the tool exists and the token is otherwise valid."""
    record = await _new_investigation(client)
    token = _token(investigation_id=record, tools=("get_incident",))
    response = await client.get(
        "/api/v1/evidence/get_topology", headers=_evidence_headers(token)
    )
    assert response.status_code == 403
    assert "not granted" in response.text


async def test_evidence_serves_a_granted_read(client):
    record = await _new_investigation(client)
    token = _token(investigation_id=record)
    response = await client.get(
        "/api/v1/evidence/get_topology", headers=_evidence_headers(token)
    )
    assert response.status_code == 200


async def test_evidence_budget_is_enforced(client):
    """The runaway-loop stop. A model that keeps reading runs out of budget
    rather than out of the client's goodwill."""
    record = await _new_investigation(client, budget=2)
    token = _token(investigation_id=record)
    codes = []
    for _ in range(3):
        response = await client.get(
            "/api/v1/evidence/get_topology", headers=_evidence_headers(token)
        )
        codes.append(response.status_code)
    assert codes[:2] == [200, 200]
    assert codes[2] == 429


async def test_evidence_for_an_unknown_tenant_is_404(client):
    record = await _new_investigation(client)
    token = _token(investigation_id=record, tenant_id="does-not-exist")
    response = await client.get(
        "/api/v1/evidence/get_topology", headers=_evidence_headers(token)
    )
    assert response.status_code == 404


async def test_a_refused_read_still_lands_in_the_evidence_chain(client):
    """What the AI *tried* to look at is as interesting to an auditor as what it
    succeeded in reading."""
    record = await _new_investigation(client)
    token = _token(investigation_id=record, tools=("get_incident",))
    await client.get("/api/v1/evidence/get_topology", headers=_evidence_headers(token))

    store = client._transport.app.state.store  # type: ignore[attr-defined]
    stored = await store.get_investigation(record, with_calls=True)
    assert [c.status for c in stored.calls] == ["refused"]
    assert stored.calls[0].tool == "get_topology"


# ----------------------------------------------------------- the lifecycle
async def test_capabilities_reports_not_configured(client):
    token = await login(client, "operator@intertecsys.com")
    response = await client.get(
        "/api/v1/investigations/capabilities", headers=auth_headers(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["may_investigate"] is True


async def test_prometheus_tools_are_only_granted_where_there_is_a_prometheus(client):
    token = await login(client, "operator@intertecsys.com")

    almasraf = await client.get(
        "/api/v1/investigations/capabilities", headers=auth_headers(token, tenant="almasraf")
    )
    das = await client.get(
        "/api/v1/investigations/capabilities", headers=auth_headers(token, tenant="das")
    )
    assert "prometheus_instant_query" not in almasraf.json()["tools"]
    assert "prometheus_instant_query" in das.json()["tools"]


async def test_viewer_cannot_start_an_investigation(client):
    token = await login(client, "viewer@intertecsys.com")
    response = await client.post(
        "/api/v1/investigations",
        headers=auth_headers(token),
        json={"incident_id": "abc"},
    )
    # 403 on role, or 503 when the engine is unconfigured — either way, a viewer
    # never gets to spend money.
    assert response.status_code in (403, 503)


async def test_starting_without_an_engine_is_503_not_500(client):
    token = await login(client, "operator@intertecsys.com")
    response = await client.post(
        "/api/v1/investigations",
        headers=auth_headers(token),
        json={"incident_id": "abc"},
    )
    assert response.status_code == 503
    assert "CHETANA_HOLMES_BASE_URL" in response.text


async def test_investigations_are_tenant_scoped(client):
    """An investigation id from one client must not resolve under another."""
    record = await _new_investigation(client, tenant_id="das")
    token = await login(client, "admin@intertecsys.com")
    response = await client.get(
        f"/api/v1/investigations/{record}", headers=auth_headers(token, tenant="almasraf")
    )
    assert response.status_code == 404


# --------------------------------------------------------------------- helper
async def _new_investigation(
    client,
    *,
    tenant_id: str = "almasraf",
    budget: int = 40,
) -> str:
    """Create an investigation row directly.

    Going through the API would need a live HolmesGPT; the gateway behaviour
    under test starts once the row exists.
    """
    store = client._transport.app.state.store  # type: ignore[attr-defined]
    record = await store.create_investigation(
        tenant_id=tenant_id,
        incident_id="incident-under-test",
        requested_by="operator@intertecsys.com",
        question="why",
        model="test-model",
        evidence_budget=budget,
    )
    return record.id
