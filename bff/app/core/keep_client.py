"""Per-tenant HTTP client for the Keep backend.

The client can only be driven through an allowlisted `Operation`. It never
accepts a raw path from a caller, and it never forwards a query parameter the
operation did not declare.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

import httpx

from .allowlist import Operation
from .config import TenantConfig

logger = logging.getLogger("chetana.keep")


class KeepError(Exception):
    """A non-2xx response from Keep, normalised for the console."""

    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.payload = payload


class KeepUnavailable(KeepError):
    def __init__(self, message: str) -> None:
        super().__init__(502, message)


# Substrings every resolver library uses for "that name does not exist". Kept as
# a tuple because httpx wraps the OS error and the wording differs by platform:
# glibc says "Name or service not known", macOS "nodename nor servname provided".
_DNS_FAILURE_MARKERS = (
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "getaddrinfo failed",
)

# "Refused" reaches us under several names. httpx tries every address a host
# resolves to — IPv6 then IPv4, typically — and when they all fail it reports
# the aggregate, "All connection attempts failed", with the underlying ECONNREFUSED
# nowhere in the string. Matching only on "connection refused" misses the most
# common phrasing of the most common failure, which is how the first version of
# this function fell through to the generic branch on a real outage.
_REFUSED_MARKERS = (
    "connection refused",
    "all connection attempts failed",
    "connect call failed",
    "actively refused",  # Windows, WinError 10061
    "network is unreachable",
)


# A refused connection during startup is not an outage, it is a race. Keep
# takes a few seconds to bind its port after its container starts, and the BFF
# has no depends_on ordering it behind that. One refusal used to leave the whole
# console showing "Keep is not fully reachable" until someone pressed Retry.
#
# Only ConnectError is retried, and that is the safety argument: httpx raises it
# while establishing the socket, before a single byte of the request goes out.
# Nothing reached Keep, so replaying it cannot duplicate a write. ReadError and
# RemoteProtocolError are NOT retried — those fire after the request was sent,
# where a retry could acknowledge an incident twice.
_CONNECT_RETRIES = 2
_CONNECT_BACKOFF_SECONDS = 0.75


def explain_connect_failure(tenant: TenantConfig, exc: Exception) -> str:
    """Turn a transport error into something an operator can act on.

    The raw text is accurate and useless: "[Errno -2] Name or service not known"
    tells someone staring at the console nothing about what to do next. The
    common causes each have a different fix, and which one applies is knowable
    from the error, so the message names it.
    """
    host = urlsplit(tenant.keep_base_url).hostname or tenant.keep_base_url
    raw = str(exc).strip() or exc.__class__.__name__
    lowered = raw.lower()

    if any(marker in lowered for marker in _DNS_FAILURE_MARKERS):
        return (
            f"Keep is not running, or is not on this network: the hostname "
            f"'{host}' could not be resolved. If Keep is a Compose service, "
            f"bring it up — `docker compose --profile real up -d` with no "
            f"service name, since naming one service starts only that service "
            f"and its dependencies. Otherwise correct keep_base_url for tenant "
            f"'{tenant.id}' in config/tenants.json."
        )

    if any(marker in lowered for marker in _REFUSED_MARKERS):
        return (
            f"Keep's container is running — '{host}' resolves — but nothing is "
            f"accepting connections on it yet. Keep runs a database migration "
            f"on first boot and can take a few minutes before it listens, so "
            f"give it a moment and press Retry. If it persists, "
            f"`docker compose logs keep-backend --tail 50` will say whether it "
            f"is still migrating or has crashed, and `docker compose ps` "
            f"whether it stayed up."
        )

    return f"Keep unreachable for tenant '{tenant.id}': {raw}"


def render_path(operation: Operation, path_params: Mapping[str, Any]) -> str:
    """Fill the operation's path template, URL-encoding every segment value.

    Missing params are an error rather than a silently malformed URL.
    """
    values: dict[str, str] = {}
    for name in operation.path_params:
        if name not in path_params or path_params[name] in (None, ""):
            raise ValueError(f"missing path parameter '{name}' for operation '{operation.id}'")
        values[name] = quote(str(path_params[name]), safe="")
    return operation.path.format(**values)


def filter_query(operation: Operation, query: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop anything the operation did not declare. No pass-through."""
    if not query:
        return {}
    allowed = set(operation.query_params)
    return {k: v for k, v in query.items() if k in allowed and v is not None and v != ""}


class KeepClient:
    def __init__(
        self,
        tenant: TenantConfig,
        *,
        timeout: float,
        max_connections: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tenant = tenant
        self._client = httpx.AsyncClient(
            base_url=tenant.keep_base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=max_connections),
            transport=transport,
            headers={
                "x-api-key": tenant.keep_api_key,
                "accept": "application/json",
                "user-agent": "chetana-bff/0.1",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        operation: Operation,
        *,
        path_params: Mapping[str, Any] | None = None,
        query_params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        path = render_path(operation, path_params or {})
        params = filter_query(operation, query_params)
        json_body = body if operation.body and not operation.raw_body else None
        # Keep's workflow endpoints read the request body and yaml.safe_load it.
        # Sending it JSON-encoded would parse back to a string, not a mapping,
        # so raw operations post the YAML text verbatim — which also preserves
        # the author's comments and formatting.
        raw_body = str(body) if operation.raw_body and body is not None else None

        logger.info(
            "keep call",
            extra={
                "tenant": self.tenant.id,
                "operation": operation.id,
                "method": operation.method,
                "path": path,
            },
        )

        attempt = 0
        while True:
            try:
                response = await self._client.request(
                    operation.method,
                    path,
                    params=params or None,
                    json=json_body,
                    content=raw_body,
                    headers=(
                        {"content-type": "application/yaml"} if raw_body is not None else None
                    ),
                )
                break
            except httpx.TimeoutException as exc:
                raise KeepUnavailable(f"Keep timed out for tenant '{self.tenant.id}'") from exc
            except httpx.ConnectError as exc:
                attempt += 1
                if attempt > _CONNECT_RETRIES:
                    raise KeepUnavailable(explain_connect_failure(self.tenant, exc)) from exc
                logger.info(
                    "keep connect failed, retrying",
                    extra={
                        "tenant": self.tenant.id,
                        "operation": operation.id,
                        "attempt": attempt,
                    },
                )
                await asyncio.sleep(_CONNECT_BACKOFF_SECONDS * attempt)
            except httpx.HTTPError as exc:
                raise KeepUnavailable(explain_connect_failure(self.tenant, exc)) from exc

        if response.status_code >= 400:
            payload: Any
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:2000]
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise KeepError(
                response.status_code,
                str(detail or f"Keep returned {response.status_code}"),
                payload,
            )

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}


class KeepClientRegistry:
    """One client per tenant, created lazily and reused."""

    def __init__(
        self,
        *,
        timeout: float,
        max_connections: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._clients: dict[str, KeepClient] = {}
        self._timeout = timeout
        self._max_connections = max_connections
        # Tests inject an ASGI transport here to run against a stub Keep.
        self.transport = transport
        self._lock = asyncio.Lock()

    async def get(self, tenant: TenantConfig) -> KeepClient:
        existing = self._clients.get(tenant.id)
        if existing is not None:
            return existing
        async with self._lock:
            existing = self._clients.get(tenant.id)
            if existing is None:
                existing = KeepClient(
                    tenant,
                    timeout=self._timeout,
                    max_connections=self._max_connections,
                    transport=self.transport,
                )
                self._clients[tenant.id] = existing
            return existing

    async def aclose(self) -> None:
        for client in list(self._clients.values()):
            await client.aclose()
        self._clients.clear()
