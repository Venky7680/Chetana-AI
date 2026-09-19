"""Ticket history: upload, inspect, remove.

An MSP's closed tickets are the cheapest source of two things this platform
otherwise has to guess at — what a symptom usually turns out to be, and which
fixes recur often enough to be worth automating. Until now the only way in was a
command-line script and a read-only mount, which meant the person who has the
export could not be the person who loads it.

Three properties this router is responsible for:

  * **The corpus belongs to one client.** It is written under that client's id
    and the evidence gateway resolves it by the tenant on the investigation's
    own token. There is no path from one client's tickets to another's finding.
  * **The raw export never lands on disk.** The upload is parsed in memory,
    redacted, reduced to patterns, and the bytes are dropped. What persists is
    derived and de-identified, so "we do not store your ticket data" is a
    statement that survives inspection.
  * **Uploads accumulate.** Each export merges into what the client already has,
    which is the point of loading several years of them: counts grow and a fix
    seen across three exports outranks one seen in a single odd month.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from ..core.allowlist import Role
from ..core.corpus_builder import build, merge
from ..core.precedents import CorpusStore
from ..deps import GatewayDep, PrincipalDep, SettingsDep, TenantDep

router = APIRouter(prefix="/precedents", tags=["precedents"])

# Uploading changes what a language model may cite during an investigation of
# this client's estate. That is closer to changing a policy than to filing a
# document, so it sits with the roles that can already change how the platform
# behaves rather than with everyone who can read an alert.
MIN_ROLE = Role.APPROVER


def _store(request: Request) -> CorpusStore:
    store: CorpusStore | None = getattr(request.app.state, "corpora", None)
    if store is None:  # pragma: no cover - only if startup failed
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "corpus store not ready"
        )
    return store


def _summary(store: CorpusStore, tenant_id: str) -> dict[str, Any]:
    own = store.corpus(tenant_id)
    index = store.index(tenant_id)
    sidecars = store.sidecars(tenant_id)
    return {
        # `owned` is the difference between "this client's own history" and
        # "the shared demo corpus". The console must be able to say which,
        # because one is evidence and the other is an illustration.
        "owned": own is not None,
        "corpus": (
            {**index.describe(), "patterns_loaded": len(index)} if index else None
        ),
        "uploads": store.uploads(tenant_id),
        "counts": {name: len(rows) for name, rows in sidecars.items()},
    }


@router.get("")
async def describe(
    request: Request, principal: PrincipalDep, tenant: TenantDep
) -> dict[str, Any]:
    """What this client's investigations can cite, and where it came from."""
    return _summary(_store(request), tenant.id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    principal: PrincipalDep,
    tenant: TenantDep,
    gateway: GatewayDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if principal.role < MIN_ROLE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"uploading ticket history requires the {MIN_ROLE.name.lower()} role",
        )

    filename = (file.filename or "upload.csv").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only .csv exports are accepted. Export the ticket list as CSV first.",
        )

    raw = await file.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{filename} is {len(raw) // (1024 * 1024)}MB; the limit is "
            f"{settings.max_upload_bytes // (1024 * 1024)}MB. Split it by year.",
        )
    if not raw.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{filename} is empty")

    # utf-8-sig strips the BOM Excel adds, which otherwise becomes part of the
    # first column's name and makes every lookup of that column miss.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes anything
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Could not read the file as text"
        )

    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not parse {filename}: {exc}"
        ) from exc

    incoming = build(rows, kind="historical", name=filename)
    ingest = incoming.get("ingest", {})
    if not incoming.get("entries"):
        # Almost always a column-name mismatch, so say which columns were needed
        # rather than reporting an empty result as success.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"No usable tickets in {filename}. Each row needs a short description "
            f"and resolution notes — {ingest.get('rows_skipped', 0)} of "
            f"{len(rows)} rows had neither. Accepted column names include "
            f"'Short Description'/'short_description' and "
            f"'Resolution Notes'/'close_notes'.",
        )

    store = _store(request)
    merged = merge(store.corpus(tenant.id), incoming)

    record = {
        "file": filename,
        "rows": ingest.get("rows_read", 0),
        "skipped": ingest.get("rows_skipped", 0),
        "redacted": ingest.get("redacted", {}),
        "by": principal.subject,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    store.save(tenant.id, merged, upload=record)

    # The trail records who loaded what, and how much was redacted — never the
    # ticket text itself, which no longer exists by this point.
    gateway.audit.record(
        actor=principal.subject,
        tenant_id=tenant.id,
        operation_id="precedents.upload",
        decision="executed",
        reason=f"ingested {filename}",
        tier=1,
        detail=record,
    )

    return {"ingested": record, **_summary(store, tenant.id)}


@router.delete("")
async def clear(
    request: Request,
    principal: PrincipalDep,
    tenant: TenantDep,
    gateway: GatewayDep,
) -> dict[str, Any]:
    """Remove this client's corpus entirely.

    Everything derived goes with it: precedent search falls back to the shared
    corpus if one exists, and the runbook candidates and mapping suggestions on
    this client empty out. There is no undo, because the exports the corpus was
    built from were never kept — re-upload them to rebuild.
    """
    if principal.role < Role.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "removing ticket history requires the admin role"
        )

    store = _store(request)
    removed = store.clear(tenant.id)
    if removed:
        gateway.audit.record(
            actor=principal.subject,
            tenant_id=tenant.id,
            operation_id="precedents.clear",
            decision="executed",
            reason="removed all ingested ticket history",
            tier=3,
        )
    return {"removed": removed, **_summary(store, tenant.id)}
