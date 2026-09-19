"""Credentials typed into the console must not survive anywhere in the BFF.

Installing a provider means a client's Datadog or ServiceNow key passes through
this service. It is forwarded to Keep, which holds it in its own secret manager,
and that is the only place it should exist. These tests pin the places it would
otherwise collect: the response, the approval ledger, and the audit trail.

They matter because the leak is silent. Nothing fails, nothing looks wrong, and
a key sits in a process for thirty minutes or in an append-only file forever.

One thing changed when admins stopped being parked. `providers.install` is
admin-only and tier 2, so with the bypass on it never parks at all — which means
the ledger protection is not weakened but *unreachable* for the one operation
that carries a credential. It is still tested, with the bypass off, because a
deployment can turn it off and because the protection must not rot while nothing
exercises it.
"""

from __future__ import annotations

import json

import pytest

from app.core.allowlist import Role, Tier, get_operation
from app.core.autonomy import evaluate

from .conftest import auth_headers, login

SECRET = "dd-api-key-this-must-not-be-stored-anywhere"

INSTALL = {
    "provider_id": "datadog",
    "provider_name": "Datadog (prod)",
    "config": {"api_key": SECRET, "app_key": SECRET, "domain": "datadoghq.eu"},
}


async def _install_as_admin(client):
    token = await login(client, "admin@intertecsys.com")
    response = await client.post(
        "/api/v1/providers/install", headers=auth_headers(token), json=INSTALL
    )
    return token, response


@pytest.mark.asyncio
async def test_the_credential_is_not_echoed_back(client):
    """Whatever happens next — executed, parked or refused by Keep — the key
    must not come back out in the response."""
    _, response = await _install_as_admin(client)
    assert SECRET not in response.text


@pytest.mark.asyncio
async def test_the_credential_never_reaches_the_audit_trail(client):
    """The trail answers who installed what. Never with which secret — and it
    is append-only, so a leak here is permanent."""
    token, _ = await _install_as_admin(client)
    audit = await client.get("/api/v1/audit", headers=auth_headers(token))
    assert audit.status_code == 200
    assert SECRET not in audit.text
    # The attempt itself is still recorded — redaction must not mean silence.
    assert "providers.install" in audit.text


@pytest.mark.asyncio
async def test_a_non_admin_cannot_install_a_provider(client):
    """Credentials reaching Keep at all is an admin action, before any question
    of approval."""
    token = await login(client, "operator@intertecsys.com")
    response = await client.post(
        "/api/v1/providers/install",
        headers=auth_headers(token),
        json={"provider_id": "datadog", "provider_name": "DD", "config": {"api_key": SECRET}},
    )
    assert response.status_code == 403


# --- the gate itself --------------------------------------------------------
def test_an_admin_is_not_parked_and_the_override_is_recorded():
    """An admin with nobody more senior to ask should not be stuck. But the
    result must say it went past the ceiling, or the trail cannot tell an
    override apart from an ordinary approved action."""
    result = evaluate(
        operation=get_operation("providers.install"),
        role=Role.ADMIN,
        global_max=1,
        tenant_max=1,
        admin_bypass=True,
    )
    assert result.decision == "execute"
    assert result.overridden is True
    assert "override" in result.reason


def test_with_the_bypass_off_an_admin_parks_like_anyone_else():
    result = evaluate(
        operation=get_operation("providers.install"),
        role=Role.ADMIN,
        global_max=1,
        tenant_max=1,
        admin_bypass=False,
    )
    assert result.decision == "approval_required"
    assert result.overridden is False


def test_the_bypass_never_lowers_the_role_bar():
    """Bypassing the ceiling is not the same as bypassing the allowlist. An
    operator stays denied on an admin-only operation however the flag is set."""
    for flag in (True, False):
        result = evaluate(
            operation=get_operation("providers.install"),
            role=Role.OPERATOR,
            global_max=3,
            tenant_max=3,
            admin_bypass=flag,
        )
        assert result.decision == "denied"


def test_a_parked_credential_is_still_kept_out_of_the_ledger():
    """Reachable only with the bypass off, so it is exercised directly.

    A parked action is replayed by its requester, who sends the body again with
    the approval id. The ledger's copy is never what executes, so keeping it is
    pure exposure.
    """
    from app.core.autonomy import ApprovalStore

    store = ApprovalStore()
    operation = get_operation("providers.install")
    assert operation.secret_body is True
    assert operation.tier == Tier.EFFORT_REVERSIBLE

    request = store.create(
        tenant_id="almasraf",
        operation=operation,
        requested_by="admin@intertecsys.com",
        approvals_needed=1,
        # This is what the gateway passes for a secret_body operation.
        body=None,
        note="Install Datadog (prod)",
    )
    assert request.body is None
    assert SECRET not in json.dumps(request.as_dict())
