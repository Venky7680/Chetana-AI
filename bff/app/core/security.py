"""Console authentication, roles, and tenant entitlement.

Local users + JWT today; the `Principal` abstraction is what the rest of the BFF
depends on, so swapping in OIDC later touches only this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from .allowlist import ROLE_BY_NAME, Role
from .config import Settings, UserConfig


@dataclass(frozen=True)
class Principal:
    subject: str
    role: Role
    tenants: tuple[str, ...]

    def may_access(self, tenant_id: str) -> bool:
        return "*" in self.tenants or tenant_id in self.tenants

    def visible_tenants(self, all_ids: list[str]) -> list[str]:
        if "*" in self.tenants:
            return list(all_ids)
        return [t for t in all_ids if t in self.tenants]


class AuthError(Exception):
    pass


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def parse_role(name: str) -> Role:
    try:
        return ROLE_BY_NAME[name.strip().lower()]
    except KeyError as exc:
        raise AuthError(f"unknown role '{name}'") from exc


def authenticate(settings: Settings, email: str, password: str) -> UserConfig:
    email_norm = email.strip().lower()
    for user in settings.users():
        if user.email.strip().lower() == email_norm and verify_password(password, user.password_hash):
            return user
    raise AuthError("invalid email or password")


def issue_token(settings: Settings, user: UserConfig) -> tuple[str, int]:
    expires_in = settings.access_token_ttl_minutes * 60
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user.email,
        "role": user.role,
        "tenants": user.tenants,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iss": "chetana-bff",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def principal_from_token(settings: Settings, token: str) -> Principal:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="chetana-bff",
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("session expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid session token") from exc

    return Principal(
        subject=str(payload["sub"]),
        role=parse_role(str(payload.get("role", "viewer"))),
        tenants=tuple(payload.get("tenants") or ["*"]),
    )
