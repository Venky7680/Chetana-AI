"""Append-only audit trail.

Every gated decision is recorded — including the ones that were denied or parked
for approval — because "what did the platform try to do in my estate, and who
let it" is the first question a Middle East enterprise security review asks.

Records are newline-delimited JSON so they can be tailed straight into Loki,
Sentinel or a SIEM without a parser.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

logger = logging.getLogger("chetana.audit")


class AuditLog:
    def __init__(self, path: str, *, memory_size: int = 500) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._recent: Deque[dict[str, Any]] = deque(maxlen=memory_size)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover - read-only volume
            logger.warning("audit log directory not writable: %s", self.path.parent)

    def record(
        self,
        *,
        actor: str,
        tenant_id: str,
        operation_id: str,
        decision: str,
        reason: str,
        tier: int,
        status: str = "ok",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "tenant_id": tenant_id,
            "operation_id": operation_id,
            "decision": decision,
            "reason": reason,
            "tier": tier,
            "status": status,
        }
        if detail:
            entry["detail"] = detail

        line = json.dumps(entry, separators=(",", ":"), default=str)
        with self._lock:
            self._recent.append(entry)
            try:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:  # pragma: no cover
                logger.warning("failed to write audit entry: %s", exc)
        logger.info("audit %s", line)
        return entry

    def recent(self, tenant_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        items = list(self._recent)[::-1]
        if tenant_id:
            items = [i for i in items if i.get("tenant_id") == tenant_id]
        return items[:limit]
