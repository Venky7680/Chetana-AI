from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from ..core.allowlist import OPERATIONS, get_operation
from ..core.keep_client import KeepError
from ..deps import GatewayDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(settings: SettingsDep) -> dict[str, Any]:
    """Liveness. Never touches Keep — a Keep outage must not restart the BFF."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "operations": len(OPERATIONS),
    }


@router.get("/readyz")
async def readyz(gateway: GatewayDep) -> dict[str, Any]:
    """Readiness. Checks every configured Keep backend in parallel."""
    tenants = gateway.all_tenants()
    op = get_operation("keep.status")

    async def probe(tenant) -> dict[str, Any]:
        try:
            client = await gateway.clients.get(tenant)
            await client.call(op)
            return {"tenant": tenant.id, "keep": "reachable"}
        except KeepError as exc:
            return {"tenant": tenant.id, "keep": "unreachable", "detail": exc.message}
        except Exception as exc:  # pragma: no cover - defensive
            return {"tenant": tenant.id, "keep": "unreachable", "detail": str(exc)}

    results = await asyncio.gather(*(probe(t) for t in tenants)) if tenants else []
    degraded = [r for r in results if r["keep"] != "reachable"]
    return {
        "status": "degraded" if degraded else "ok",
        "tenants": results,
    }
