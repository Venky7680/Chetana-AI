"""Client for the HolmesGPT server.

Holmes exposes `POST /api/chat` (`ask` in, `analysis` + `tool_calls` out). We
call it with two headers that matter:

  * `X-Chetana-Evidence-Token` — the per-investigation grant. Holmes' header
    propagation makes this available to the `chetana` toolset, which forwards it
    back to our evidence gateway on every read. Holmes blocks `Authorization`
    from propagation, hence the custom name.
  * `X-Chetana-Tenant` — carried for defence in depth only. The tenant that
    actually governs a read is the one inside the signed token; a header cannot
    widen it.

The model is a Bedrock model id (`bedrock/...`), so the credentials live on the
Holmes container and never pass through here.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("chetana.holmes")


class HolmesError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class HolmesResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.raw = payload

    @property
    def analysis(self) -> str:
        value = self.raw.get("analysis")
        if isinstance(value, str) and value.strip():
            return value.strip()
        # Older builds and some deployments answer under a different key; fall
        # back rather than reporting an empty finding for a run that cost money.
        for key in ("result", "response", "answer", "text"):
            candidate = self.raw.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

    @property
    def tool_calls(self) -> list[Any]:
        calls = self.raw.get("tool_calls")
        return calls if isinstance(calls, list) else []


class HolmesClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model: str = "",
        chat_path: str = "/api/chat",
        timeout_seconds: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.chat_path = chat_path if chat_path.startswith("/") else f"/{chat_path}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def healthy(self) -> bool:
        try:
            response = await self._client.get("/healthz", timeout=5.0)
            return response.status_code < 400
        except httpx.HTTPError:
            return False

    async def ask(
        self,
        *,
        question: str,
        evidence_token: str,
        tenant_id: str,
        system_prompt: str | None = None,
    ) -> HolmesResult:
        headers = {
            "X-Chetana-Evidence-Token": evidence_token,
            "X-Chetana-Tenant": tenant_id,
            "content-type": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        body: dict[str, Any] = {"ask": question, "stream": False}
        if self.model:
            body["model"] = self.model
        if system_prompt:
            body["additional_system_prompt"] = system_prompt

        try:
            response = await self._client.post(self.chat_path, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise HolmesError("the investigation timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise HolmesError(f"could not reach HolmesGPT: {exc}", 502) from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            # Surface Holmes' own words. A 401 here almost always means
            # HOLMES_API_KEY is set on the container but not in the BFF config,
            # and a generic "investigation failed" would hide that for an hour.
            raise HolmesError(
                f"HolmesGPT returned {response.status_code}: {detail}",
                response.status_code if response.status_code < 500 else 502,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise HolmesError("HolmesGPT returned a non-JSON response", 502) from exc

        if not isinstance(payload, dict):
            raise HolmesError("HolmesGPT returned an unexpected response shape", 502)

        return HolmesResult(payload)
