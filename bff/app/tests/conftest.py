from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402

TENANTS = [
    {
        "id": "almasraf",
        "name": "Almasraf Bank",
        "keep_base_url": "http://keep.test",
        "keep_api_key": "stub-key",
        "max_autonomy_tier": 1,
        "tags": ["uae", "banking"],
    },
    {
        "id": "das",
        "name": "DAS Holding",
        "keep_base_url": "http://keep.test",
        "keep_api_key": "stub-key",
        "max_autonomy_tier": 2,
        "tags": ["uae"],
        # Only this tenant has a metric store, so the evidence grant differs
        # between the two — which is the behaviour worth testing.
        "prometheus_base_url": "http://prom.test",
    },
]

PASSWORD = "chetana-test-pw"


def _users() -> list[dict]:
    pw = hash_password(PASSWORD)
    return [
        {"email": "viewer@intertecsys.com", "password_hash": pw, "role": "viewer", "tenants": ["almasraf"]},
        {"email": "operator@intertecsys.com", "password_hash": pw, "role": "operator", "tenants": ["*"]},
        {"email": "approver@intertecsys.com", "password_hash": pw, "role": "approver", "tenants": ["*"]},
        {"email": "admin@intertecsys.com", "password_hash": pw, "role": "admin", "tenants": ["*"]},
    ]


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory) -> None:
    audit = tmp_path_factory.mktemp("audit") / "audit.log"
    database = tmp_path_factory.mktemp("db") / "chetana-test.db"
    os.environ.update(
        {
            "CHETANA_ENVIRONMENT": "test",
            "CHETANA_JWT_SECRET": "test-secret",
            "CHETANA_TENANTS_JSON": json.dumps(TENANTS),
            "CHETANA_USERS_JSON": json.dumps(_users()),
            "CHETANA_GLOBAL_MAX_AUTONOMY_TIER": "1",
            "CHETANA_AUDIT_LOG_PATH": str(audit),
            # Never let a test run touch the real database file.
            "CHETANA_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
            # Investigation is off unless a test switches it on, so the suite
            # never tries to reach a HolmesGPT container.
            "CHETANA_HOLMES_BASE_URL": "",
        }
    )
    get_settings.cache_clear()


@pytest.fixture
def stub_keep_transport() -> httpx.ASGITransport:
    from tools.fake_keep import create_app

    return httpx.ASGITransport(app=create_app(seed=11))


@pytest.fixture
async def client(stub_keep_transport):
    """An httpx client bound to the BFF, with Keep replaced by the stub."""
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bff.test") as http:
        async with app.router.lifespan_context(app):
            app.state.gateway.clients.transport = stub_keep_transport
            yield http


async def login(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token: str, tenant: str = "almasraf") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Chetana-Tenant": tenant}
