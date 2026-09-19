"""Runtime configuration for the Chetana BFF.

Everything is environment-driven so the same image runs in every environment.
Tenants are supplied as a JSON document (inline, or a path to a file) so an MSP
can add a client without a rebuild.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TenantConfig(BaseModel):
    """One managed client environment, backed by its own Keep instance/tenant."""

    id: str
    name: str
    keep_base_url: str
    keep_api_key: str
    # Highest autonomy tier this tenant has signed off on. Actions above it are
    # never executed automatically, regardless of who clicks the button.
    max_autonomy_tier: int = Field(default=1, ge=0, le=3)
    # Optional free-text region/cloud tags, surfaced in the console.
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    # This client's metric store, read through the evidence gateway during an
    # investigation. Left unset, the PromQL evidence tools are simply not
    # offered for this tenant rather than failing mid-investigation.
    prometheus_base_url: str | None = None
    # Whether AI investigation is switched on for this client at all. Some will
    # sign a managed-services contract long before they sign off on an LLM
    # reading their estate, and that is a per-tenant decision.
    investigations_enabled: bool = True

    @field_validator("keep_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("prometheus_base_url")
    @classmethod
    def _strip_optional_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else None


class UserConfig(BaseModel):
    """A console user. Replaced by OIDC in production; kept for local/dev and
    for air-gapped deployments where no IdP is available."""

    email: str
    # bcrypt hash. Generate with: python -m app.cli hash-password
    password_hash: str
    # "viewer" | "operator" | "approver" | "admin"
    role: str = "viewer"
    # Tenant ids this user may see. ["*"] means all.
    tenants: list[str] = Field(default_factory=lambda: ["*"])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CHETANA_", extra="ignore")

    app_name: str = "Chetana AI BFF"
    environment: str = "local"
    debug: bool = False

    # --- HTTP ---
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    request_timeout_seconds: float = 30.0
    keep_max_connections: int = 50

    # --- Auth ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 12 * 60

    # --- Tenants / users: JSON blob or path to a JSON file ---
    tenants_json: str = "[]"
    users_json: str = "[]"

    # --- Behaviour ---
    # Global ceiling. A tenant can be stricter, never looser.
    global_max_autonomy_tier: int = Field(default=1, ge=0, le=3)
    audit_log_path: str = "./data/audit.log"
    cache_ttl_seconds: int = 15

    # --- Persistence ---
    # SQLite by default so a single node needs nothing extra. Point this at
    # postgresql+asyncpg://... for multi-replica; no other code changes.
    database_url: str = "sqlite+aiosqlite:///./data/chetana.db"

    # --- Investigation (HolmesGPT) ---
    # Empty base url disables investigation entirely; the console then hides the
    # panel rather than offering a button that 502s.
    holmes_base_url: str = ""
    holmes_api_key: str = ""
    holmes_model: str = "bedrock/anthropic.claude-sonnet-4-20250514-v1:0"
    holmes_chat_path: str = "/api/chat"
    holmes_timeout_seconds: float = 180.0
    # How Holmes reaches us to call the evidence gateway back. Inside compose
    # this is the service name, not localhost.
    evidence_callback_url: str = "http://bff:8080"
    # The scoped token outlives a slow investigation but little else.
    evidence_token_ttl_seconds: int = 900
    # Hard stop on a model that decides to poll the estate forever.
    evidence_budget_per_investigation: int = Field(default=40, ge=1, le=500)
    # Cost ceiling. Investigations are LLM calls; an alert storm without this is
    # an uncapped bill.
    investigations_per_tenant_per_hour: int = Field(default=20, ge=1, le=1000)
    # A corpus of past ticket resolutions, built offline by ops/precedents. When
    # the file is absent the precedent tool is simply not granted, which is the
    # normal state until an MSP has exported its own tickets — better than
    # granting a tool that answers nothing.
    # An admin is the highest authority in the platform, so by default nothing
    # is parked for them — an admin with no one more senior to ask would
    # otherwise be stuck rather than safe. Overrides are still audited as
    # overrides. Set false where a contract requires two people on every
    # irreversible action regardless of rank.
    admin_bypasses_autonomy_ceiling: bool = True
    precedent_corpus_path: str = ""
    # Where uploaded, per-client corpora are written. Must be on a writable
    # volume that survives a container restart — a corpus is derived from an
    # export the client may not send twice.
    precedent_corpus_dir: str = "/srv/data/precedents"
    # An upload is parsed entirely in memory before anything is written, so this
    # bounds memory as well as disk. 40MB is roughly 200k tickets.
    max_upload_bytes: int = Field(default=40 * 1024 * 1024, ge=1024)

    @staticmethod
    def _load_json(raw: str) -> list[dict[str, Any]]:
        # Strip any BOM first, so the inline-vs-path test below sees real content.
        raw = (raw or "").lstrip("﻿").strip()
        if not raw:
            return []
        # Allow either an inline JSON array or a path to a JSON file.
        source = "inline value"
        if not raw.startswith("["):
            path = Path(raw)
            if not path.exists():
                raise ValueError(f"config file not found: {raw}")
            source = str(path)
            # utf-8-sig, not utf-8: Windows PowerShell's Set-Content and Notepad
            # both write a UTF-8 BOM, and json.loads rejects it outright. utf-8-sig
            # strips a BOM when present and behaves exactly like utf-8 when absent.
            raw = path.read_text(encoding="utf-8-sig").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Startup dies here otherwise, with a traceback that never names the file.
            raise ValueError(f"{source} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{source}: expected a JSON array")
        return parsed

    def tenants(self) -> list[TenantConfig]:
        return [TenantConfig(**t) for t in self._load_json(self.tenants_json)]

    def users(self) -> list[UserConfig]:
        return [UserConfig(**u) for u in self._load_json(self.users_json)]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests after mutating the environment."""
    get_settings.cache_clear()
    os.environ.setdefault("CHETANA_ENVIRONMENT", "local")
