from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..core.security import AuthError, authenticate, issue_token, parse_role
from ..deps import GatewayDep, PrincipalDep, SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    email: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, settings: SettingsDep) -> LoginResponse:
    try:
        user = authenticate(settings, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    token, expires_in = issue_token(settings, user)
    return LoginResponse(
        access_token=token, expires_in=expires_in, role=user.role, email=user.email
    )


@router.get("/me")
def me(principal: PrincipalDep, gateway: GatewayDep) -> dict:
    tenants = gateway.tenants_for(principal)
    return {
        "email": principal.subject,
        "role": principal.role.name.lower(),
        "role_level": int(principal.role),
        "tenants": [
            {
                "id": t.id,
                "name": t.name,
                "tags": t.tags,
                "max_autonomy_tier": t.max_autonomy_tier,
            }
            for t in tenants
        ],
        "global_max_autonomy_tier": gateway.settings.global_max_autonomy_tier,
    }


@router.get("/roles")
def roles() -> list[dict]:
    from ..core.allowlist import ROLE_BY_NAME

    return [{"name": name, "level": int(role)} for name, role in ROLE_BY_NAME.items()]


__all__ = ["router", "parse_role"]
