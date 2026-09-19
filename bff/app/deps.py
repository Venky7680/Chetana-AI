"""FastAPI dependencies: settings, principal, tenant, gateway."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from .core.config import Settings, TenantConfig, get_settings
from .core.security import AuthError, Principal, principal_from_token
from .gateway import Gateway

TENANT_HEADER = "X-Chetana-Tenant"


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def gateway_dep(request: Request) -> Gateway:
    gateway: Gateway | None = getattr(request.app.state, "gateway", None)
    if gateway is None:  # pragma: no cover - only if startup failed
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "gateway not ready")
    return gateway


GatewayDep = Annotated[Gateway, Depends(gateway_dep)]


def principal_dep(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        return principal_from_token(settings, token)
    except AuthError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc


PrincipalDep = Annotated[Principal, Depends(principal_dep)]


def tenant_dep(
    gateway: GatewayDep,
    principal: PrincipalDep,
    x_chetana_tenant: Annotated[str | None, Header()] = None,
) -> TenantConfig:
    """Resolve the tenant for this request and check the caller is entitled.

    Every downstream call is scoped by this object; there is no code path that
    reaches Keep without one.
    """
    tenant_id = (x_chetana_tenant or "").strip()
    if not tenant_id:
        visible = gateway.tenants_for(principal)
        if len(visible) == 1:
            return visible[0]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{TENANT_HEADER} header is required when more than one tenant is accessible",
        )

    tenant = gateway.tenant(tenant_id)
    if tenant is None or not tenant.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown tenant '{tenant_id}'")
    if not principal.may_access(tenant.id):
        # Deliberately 404, not 403: don't confirm the tenant exists to someone
        # who is not entitled to it.
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown tenant '{tenant_id}'")
    return tenant


TenantDep = Annotated[TenantConfig, Depends(tenant_dep)]
