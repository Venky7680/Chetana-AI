"""Per-tenant HTTP client for the Keep backend.

The client can only be driven through an allowlisted `Operation`. It never
accepts a raw path from a caller, and it never forwards a query parameter the
operation did not declare.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping
from urllib.parse import quote

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

        try:
            response = await self._client.request(
                operation.method,
                path,
                params=params or None,
                json=json_body,
                content=raw_body,
                headers={"content-type": "application/yaml"} if raw_body is not None else None,
            )
        except httpx.TimeoutException as exc:
            raise KeepUnavailable(f"Keep timed out for tenant '{self.tenant.id}'") from exc
        except httpx.HTTPError as exc:
            raise KeepUnavailable(f"Keep unreachable for tenant '{self.tenant.id}': {exc}") from exc

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
