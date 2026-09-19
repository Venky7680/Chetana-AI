"""Searching past ticket resolutions, for the investigation engine.

The RCA engine reasons from metrics and topology — what is true right now. It
has no memory of what this class of symptom turned out to be the last twenty
times. A service desk has exactly that memory, in its closed tickets, and it is
usually the fastest route to a hypothesis.

Two things make this safe to hand to a model.

**It cannot reach anything.** Unlike every other evidence tool, this one touches
no client system: the corpus is a file built offline by ops/precedents. There is
no query language, no tenant data, no credential.

**It never pretends.** Every result carries the corpus's `kind`. A corpus built
from generated tickets says `synthetic`, and the caveat travels with the payload
into the model's context, so a finding resting on invented precedent has to say
so. This is the same discipline as the data-horizon guard on range queries: the
failure mode worth designing against is not a wrong answer, it is a confident
one built on something that was never measured.

Scoring is TF-IDF cosine over word stems. No dependency, no model, no network —
a thousand-odd short strings do not justify any of those, and a search the
gateway can run in a millisecond is one that cannot time out mid-investigation.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")

# Words that appear in most tickets and separate nothing. Kept deliberately
# short: an aggressive stop list throws away the domain terms that matter.
_STOP = frozenset(
    """
    a an and are as at be been by can cannot could did do does for from had has have
    in into is it its no not of on or over that the their then there these this to
    unable user users was were when which will with without
    issue issues problem problems request requests ticket
    """.split()
)

# A symptom search is about the failure, not the pleasantries around it.
_SYNONYMS = {
    "down": "outage",
    "offline": "outage",
    "unavailable": "outage",
    "slow": "latency",
    "sluggish": "latency",
    "degraded": "latency",
    "timeout": "timing out",
    "expired": "expiry",
    "expiring": "expiry",
    "restarted": "restart",
    "rebooted": "restart",
    "locked": "lockout",
    "failing": "failure",
    "failed": "failure",
}


def _tokens(text: str) -> list[str]:
    out = []
    for word in _WORD.findall(text.lower()):
        if word in _STOP or len(word) < 2:
            continue
        out.extend(_SYNONYMS.get(word, word).split())
    return out


@dataclass(frozen=True)
class Precedent:
    symptom: str
    resolution: str
    ci_classes: tuple[str, ...]
    groups: tuple[str, ...]
    priority: str
    occurrences: int


class PrecedentIndex:
    """An in-memory TF-IDF index over symptom + resolution text."""

    def __init__(self, corpus: dict[str, Any]) -> None:
        self.source: dict[str, Any] = dict(corpus.get("source") or {})
        self.entries: list[Precedent] = []
        self._vectors: list[dict[str, float]] = []

        raw = corpus.get("entries") or []
        documents: list[list[str]] = []
        for item in raw:
            symptom = str(item.get("symptom") or "").strip()
            resolution = str(item.get("resolution") or "").strip()
            if not symptom or not resolution:
                continue
            self.entries.append(
                Precedent(
                    symptom=symptom,
                    resolution=resolution,
                    ci_classes=tuple(item.get("ci_classes") or ()),
                    groups=tuple(item.get("groups") or ()),
                    priority=str(item.get("priority") or ""),
                    occurrences=int(item.get("n") or 1),
                )
            )
            # The CI class is part of the searchable text: "printer" matches a
            # Printer-class precedent even when the symptom wording differs.
            documents.append(
                _tokens(
                    f"{symptom} {resolution} {' '.join(item.get('ci_classes') or ())}"
                )
            )

        total = len(documents) or 1
        appearances: Counter[str] = Counter()
        for doc in documents:
            appearances.update(set(doc))
        self._idf = {
            term: math.log(total / (1 + count)) + 1.0
            for term, count in appearances.items()
        }

        for doc in documents:
            self._vectors.append(self._vectorise(doc))

    def _vectorise(self, tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        vector = {
            term: (1 + math.log(n)) * self._idf.get(term, 1.0)
            for term, n in counts.items()
        }
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        return {term: v / norm for term, v in vector.items()}

    def __len__(self) -> int:
        return len(self.entries)

    def search(
        self, query: str, *, ci_class: str = "", limit: int = 5
    ) -> list[dict[str, Any]]:
        query_vector = self._vectorise(_tokens(query))
        if not query_vector:
            return []

        wanted = ci_class.strip().lower()
        scored: list[tuple[float, int]] = []
        for index, vector in enumerate(self._vectors):
            # Iterate the shorter side; a query is a handful of terms.
            score = sum(
                weight * vector.get(term, 0.0) for term, weight in query_vector.items()
            )
            if score <= 0:
                continue
            if wanted:
                classes = [c.lower() for c in self.entries[index].ci_classes]
                # A stated CI class is a strong hint, not a filter: excluding
                # everything else would hide the precedent that names the
                # upstream component rather than the one that is shouting.
                if any(wanted in c or c in wanted for c in classes):
                    score *= 1.6
            scored.append((score, index))

        scored.sort(key=lambda pair: (-pair[0], -self.entries[pair[1]].occurrences))
        results = []
        for score, index in scored[: max(1, min(limit, 20))]:
            entry = self.entries[index]
            results.append(
                {
                    "symptom": entry.symptom,
                    "resolution": entry.resolution,
                    "ci_classes": list(entry.ci_classes),
                    "handled_by": list(entry.groups),
                    "typical_priority": entry.priority,
                    "times_seen": entry.occurrences,
                    "match": round(score, 3),
                }
            )
        return results

    def describe(self) -> dict[str, Any]:
        return dict(self.source)


# ---------------------------------------------------------------- the store
class CorpusStore:
    """Per-client precedent corpora on disk, with their indices cached.

    Isolation is the whole point of this class. Before it, one corpus was
    loaded at startup and every investigation searched it — fine for a single
    bundled demo file, and a data leak the moment real client exports are
    uploaded, because a precedent from one bank would be citable in another
    bank's investigation. The evidence gateway now resolves a corpus by the
    tenant on the investigation's own token, so there is no path from one
    client's tickets to another's finding.

    A shared fallback corpus is still supported for the demo stack, and is used
    only by tenants that have uploaded nothing. It carries its own `kind`, so a
    synthetic fallback announces itself in every result rather than passing for
    the client's own history.
    """

    FILENAME = "corpus.json"
    HISTORY = "uploads.json"

    def __init__(self, root: str | Path, fallback: str | Path | None = None) -> None:
        self.root = Path(root)
        self.fallback_path = Path(fallback) if fallback else None
        self._cache: dict[str, PrecedentIndex | None] = {}
        self._fallback: PrecedentIndex | None = None
        self._fallback_loaded = False

    # --- paths ---
    def _dir(self, tenant_id: str) -> Path:
        # Tenant ids come from config, not from a request, but a path is a path:
        # anything that is not a plain identifier is refused rather than
        # sanitised, because a silently rewritten tenant id would read another
        # client's corpus.
        if not tenant_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tenant_id):
            raise ValueError(f"unusable tenant id for storage: {tenant_id!r}")
        return self.root / tenant_id

    def path_for(self, tenant_id: str) -> Path:
        return self._dir(tenant_id) / self.FILENAME

    # --- reads ---
    def _read(self, file: Path) -> dict[str, Any] | None:
        if not file.is_file():
            return None
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def corpus(self, tenant_id: str) -> dict[str, Any] | None:
        """The raw corpus document for a client, without touching the fallback."""
        try:
            return self._read(self.path_for(tenant_id))
        except ValueError:
            return None

    def index(self, tenant_id: str) -> PrecedentIndex | None:
        """The searchable index for a client, falling back to the shared one."""
        if tenant_id not in self._cache:
            payload = self.corpus(tenant_id)
            built = PrecedentIndex(payload) if payload else None
            self._cache[tenant_id] = built if built and len(built) else None

        own = self._cache[tenant_id]
        return own if own is not None else self._shared()

    def _shared(self) -> PrecedentIndex | None:
        if not self._fallback_loaded:
            self._fallback_loaded = True
            payload = self._read(self.fallback_path) if self.fallback_path else None
            built = PrecedentIndex(payload) if payload else None
            self._fallback = built if built and len(built) else None
        return self._fallback

    def sidecars(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        """Runbook candidates and mapping rules for the console.

        These are derived from the same corpus, so they are stored inside it
        rather than in files beside it — four files that can disagree is a bug
        waiting for the day one write fails.
        """
        names = ("mapping_rows", "mapping_needs_review", "runbook_candidates")
        payload = self.corpus(tenant_id)
        if payload is None:
            fallback = self._read(self.fallback_path) if self.fallback_path else None
            payload = fallback or {}
        return {
            name: [row for row in (payload.get(name) or []) if isinstance(row, dict)]
            for name in names
        }

    def uploads(self, tenant_id: str) -> list[dict[str, Any]]:
        """What has been ingested for this client, newest first."""
        try:
            payload = self._read(self._dir(tenant_id) / self.HISTORY)
        except ValueError:
            return []
        rows = (payload or {}).get("uploads") or []
        return [row for row in rows if isinstance(row, dict)]

    # --- writes ---
    def save(
        self, tenant_id: str, corpus: dict[str, Any], *, upload: dict[str, Any]
    ) -> None:
        """Replace a client's corpus and append to its upload history.

        Written to a temporary file and moved into place, so an interrupted
        write cannot leave a client with a half-written corpus that then fails
        to parse and silently disables their precedent search.
        """
        directory = self._dir(tenant_id)
        directory.mkdir(parents=True, exist_ok=True)

        self._atomic(directory / self.FILENAME, corpus)

        history = self.uploads(tenant_id)
        history.insert(0, upload)
        self._atomic(directory / self.HISTORY, {"uploads": history[:50]})

        self._cache.pop(tenant_id, None)

    def clear(self, tenant_id: str) -> bool:
        """Remove a client's corpus and its history."""
        try:
            directory = self._dir(tenant_id)
        except ValueError:
            return False
        removed = False
        for name in (self.FILENAME, self.HISTORY):
            file = directory / name
            if file.is_file():
                file.unlink()
                removed = True
        self._cache.pop(tenant_id, None)
        return removed

    @staticmethod
    def _atomic(target: Path, payload: Any) -> None:
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(target)
