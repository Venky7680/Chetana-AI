"""A transport failure must tell an operator what to do about it.

This exists because of a real incident: the console showed

    Keep unreachable for tenant 'live': [Errno -2] Name or service not known

which is accurate and unactionable. The cause was that Keep's container was
never started — `docker compose --profile real up -d --build web` names a
service, and naming one starts only it and its dependencies, so a profile's
other services stay down. Nothing in that message points there.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import TenantConfig
from app.core.allowlist import get_operation
from app.core.keep_client import (
    _CONNECT_RETRIES,
    KeepClient,
    KeepUnavailable,
    explain_connect_failure,
)


def _tenant(url: str = "http://keep-backend:8080") -> TenantConfig:
    return TenantConfig(
        id="live",
        name="Live estate",
        keep_base_url=url,
        keep_api_key="k",
        max_autonomy_tier=1,
    )


def test_dns_failure_names_the_host_and_the_fix() -> None:
    """The exact error from the incident, and what the operator needs from it."""
    exc = httpx.ConnectError("[Errno -2] Name or service not known")
    message = explain_connect_failure(_tenant(), exc)

    # The host, so it is obvious which name failed to resolve.
    assert "keep-backend" in message
    # The fix, not the symptom.
    assert "docker compose --profile real up -d" in message
    assert "config/tenants.json" in message
    # The raw errno is noise once the cause is named.
    assert "Errno -2" not in message


@pytest.mark.parametrize(
    "raw",
    [
        "[Errno -2] Name or service not known",
        "[Errno 8] nodename nor servname provided, or not known",
        "[Errno -3] Temporary failure in name resolution",
        "getaddrinfo failed",
    ],
)
def test_every_platforms_dns_wording_is_recognised(raw: str) -> None:
    """glibc, macOS and Windows each word this differently."""
    message = explain_connect_failure(_tenant(), httpx.ConnectError(raw))
    assert "could not be resolved" in message


@pytest.mark.parametrize(
    "raw",
    [
        "[Errno 111] Connection refused",
        # The one that actually reached the console. httpx tries every address
        # a name resolves to and reports only the aggregate when they all fail,
        # so ECONNREFUSED never appears in the string. The first version of the
        # classifier matched "connection refused" alone and missed this.
        "All connection attempts failed",
        "[WinError 10061] No connection could be made because the target machine actively refused it",
        "Network is unreachable",
    ],
)
def test_refused_is_a_different_diagnosis(raw: str) -> None:
    """Resolved but refused means it is starting, or on another port — not absent."""
    message = explain_connect_failure(_tenant(), httpx.ConnectError(raw))

    assert "container is running" in message
    assert "migration" in message
    # Must not send someone to `up -d` for a container that is already up.
    assert "up -d" not in message
    # It must say how to check, since "wait a bit" is not a diagnosis.
    assert "docker compose logs keep-backend" in message


def test_unclassified_errors_keep_their_detail() -> None:
    """Anything unrecognised must pass the original text through, not swallow it."""
    message = explain_connect_failure(_tenant(), httpx.ConnectError("TLS handshake blew up"))
    assert "TLS handshake blew up" in message
    assert "live" in message


def test_a_bare_hostname_url_still_reports_a_host() -> None:
    """urlsplit returns no hostname for a scheme-less URL; don't print 'None'."""
    message = explain_connect_failure(
        _tenant("keep-backend:8080"), httpx.ConnectError("Name or service not known")
    )
    assert "None" not in message
    assert "keep-backend" in message


# --------------------------------------------------------------------- retries
#
# The startup race this exists for: `docker compose up -d` starts the BFF and
# Keep together, Keep needs a few seconds to bind its port, and the BFF has no
# depends_on ordering it behind that. One refused connection used to leave the
# console showing "Keep is not fully reachable" until a human pressed Retry,
# even though Keep was healthy seconds later.


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Refuses the first `failures` connections, then answers normally."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise httpx.ConnectError("All connection attempts failed", request=request)
        return httpx.Response(200, json=[{"id": "abc"}], request=request)


class _SentThenBrokenTransport(httpx.AsyncBaseTransport):
    """Fails *after* the request went out — the case a retry must not paper over."""

    def __init__(self) -> None:
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        raise httpx.ReadError("connection reset mid-response", request=request)


def _client(transport: httpx.AsyncBaseTransport) -> KeepClient:
    return KeepClient(_tenant(), timeout=5, max_connections=4, transport=transport)


@pytest.mark.asyncio
async def test_a_startup_race_recovers_without_a_human() -> None:
    """Keep binding its port a second late must not surface as an outage."""
    transport = _FlakyTransport(failures=1)
    client = _client(transport)
    try:
        result = await client.call(get_operation("incidents.list"))
    finally:
        await client.aclose()

    assert result == [{"id": "abc"}]
    assert transport.attempts == 2, "should have retried exactly once"


@pytest.mark.asyncio
async def test_retries_are_bounded_and_then_explain_themselves() -> None:
    """A real outage must still fail, with the actionable message, not hang."""
    transport = _FlakyTransport(failures=99)
    client = _client(transport)
    try:
        with pytest.raises(KeepUnavailable) as caught:
            await client.call(get_operation("incidents.list"))
    finally:
        await client.aclose()

    # One original attempt plus _CONNECT_RETRIES.
    assert transport.attempts == 1 + _CONNECT_RETRIES
    assert "container is running" in caught.value.message


@pytest.mark.asyncio
async def test_a_failure_after_the_request_was_sent_is_never_retried() -> None:
    """The safety boundary: replaying this could acknowledge an incident twice."""
    transport = _SentThenBrokenTransport()
    client = _client(transport)
    try:
        with pytest.raises(KeepUnavailable):
            # A write, deliberately: this is the operation a bad retry would
            # duplicate — the same comment posted twice on one incident.
            await client.call(
                get_operation("incidents.comment"),
                path_params={"incident_id": "c7b1e424"},
                body={"comment": "acknowledged"},
            )
    finally:
        await client.aclose()

    assert transport.attempts == 1, "a sent request must not be replayed"
