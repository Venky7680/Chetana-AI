"""Turning a ticket export into a precedent corpus, runbooks and routing rules.

This is the single implementation. The console's upload endpoint calls it, and
so does the offline CLI in ops/precedents — a second copy would drift, and the
copy that drifted would be the one deciding what an LLM gets to read.

Three things happen here that are worth stating plainly, because each one is a
decision rather than a detail.

**Redaction runs before anything is stored.** Ticket text names people: the user
who called, the engineer who closed it, a mailbox, a desk extension. A precedent
corpus is searched *by a language model*, so whatever survives ingest ends up in
model context on every search. Names, emails, phone numbers and ticket ids are
stripped here, once, at the only point where the raw text exists.

**Instance identifiers are generalised away.** `Cert-4637` becomes `Cert`.
Without this, forty identical certificate cases become forty patterns seen once
each, and the ranking buries the common cause under its own instances.

**Resolution times are dropped entirely.** They are the field most likely to be
generated rather than measured, and an MTTR nobody measured is worse than no
MTTR at all. Nothing downstream can cite one because nothing carries one.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------- columns
COLUMNS = {
    "symptom": (
        "Short Description",
        "short_description",
        "summary",
        "title",
        "subject",
    ),
    "ci": ("CI / Affected Resource", "cmdb_ci", "ci", "configuration_item", "asset"),
    "priority": ("Priority", "priority", "urgency", "severity"),
    "group": ("Assignment Group", "assignment_group", "team", "queue"),
    "resolution": (
        "Resolution Notes",
        "close_notes",
        "resolution",
        "resolution_notes",
        "solution",
    ),
    "opened": ("Opened", "opened_at", "created", "created_at", "reported"),
}

# --------------------------------------------------------------------- shapes
INSTANCE_SUFFIX = re.compile(r"[-_]?\d+$")
INLINE_INSTANCE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z][A-Za-z0-9]*)*)[-_]\d{2,}\b"
)

# --------------------------------------------------------------------- privacy
#
# Ordered most specific first: an email must be caught before the name inside it
# is, or "firstname.lastname@corp.ae" leaves a redacted name glued to a domain.
REDACTIONS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
    ("ticket", re.compile(r"\b(?:INC|REQ|CHG|TASK|RITM|SR)\d{4,}\b", re.I), "[ticket]"),
    # Before phone, or a dotted quad is eaten by the digit-run pattern and an
    # address is reported as a telephone number.
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    # Long digit runs with optional separators: extensions, mobiles, employee ids.
    ("phone", re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w.])"), "[phone]"),
    # "for John Smith", "user Jane Doe", "reported by Ana Lopez" — the shapes a
    # person's name actually takes in ticket prose. A bare capitalised pair is
    # deliberately NOT matched: "Print Spooler" and "Active Directory" are not
    # people, and over-redacting destroys the fix pattern the corpus is for.
    (
        "name",
        re.compile(
            # The cue word is case-insensitive — it often starts the sentence
            # ("Called Jane Doe...") — but the name itself is not, because
            # dropping the capitals here would make the pattern match any two
            # ordinary words and redact the fix along with the person.
            r"\b(?i:for|by|with|user|employee|contacted|called|spoke to|assisted"
            r"|guided|reported by|on behalf of)\s+"
            r"(?:(?i:mr|ms|mrs|dr)\.?\s+)?"
            r"([A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,15})\b"
        ),
        None,  # replacement is computed, see redact()
    ),
)


def redact(text: str) -> tuple[str, Counter[str]]:
    """Strip personal identifiers, and report what was found.

    Returns the cleaned text and a count per category, so the console can show
    what redaction actually caught rather than asserting that it worked.

    This is a filter, not a guarantee. It removes the identifiers that appear in
    ticket prose in predictable shapes; it cannot catch a name written bare in
    the middle of a sentence. Anything that must not leave a client's estate
    should not be uploaded in the first place.
    """
    found: Counter[str] = Counter()
    cleaned = text
    for label, pattern, replacement in REDACTIONS:
        if replacement is None:
            # Keep the preposition, drop the person: "for John Smith" -> "for [name]".
            def _sub(match: re.Match[str]) -> str:
                found[label] += 1
                return match.group(0).replace(match.group(1), "[name]")

            cleaned = pattern.sub(_sub, cleaned)
        else:
            cleaned, n = pattern.subn(replacement, cleaned)
            if n:
                found[label] += n
    return cleaned, found


def generalise(text: str) -> str:
    """Drop instance identifiers so a symptom describes a class of failure."""
    return INLINE_INSTANCE.sub(r"\1", text).strip()


def ci_class(value: str) -> str:
    return INSTANCE_SUFFIX.sub("", value).strip("-_") if value else ""


def pick(row: Mapping[str, Any], names: tuple[str, ...]) -> str:
    """Read a column by any of its known spellings, case-insensitively."""
    lowered = {str(k).strip().lower(): v for k, v in row.items() if k}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


# ------------------------------------------------------------------ runbooks
PHYSICAL = re.compile(
    r"replac|cable|dock|hardware|on-?site|shipped|swapped|battery|screen", re.I
)

# Order matters: the costly and irreversible patterns are tested first, so a
# note containing both "unlocked" and "reset password" is tiered on the reset.
TIER_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "R2",
        re.compile(r"reset (the )?password|password reset", re.I),
        "a password reset cannot be undone — the old secret is gone",
    ),
    (
        "R2",
        re.compile(r"renew|rotat|re-?issue|purchase|licen[cs]e", re.I),
        "spends money or issues a new credential someone must trust",
    ),
    (
        "R2",
        re.compile(r"resiz|expand|scal(e|ed)|next tier", re.I),
        "changes capacity, and costs money until it is changed back",
    ),
    (
        "R2",
        re.compile(r"rolled back|rollback|failover|redeploy", re.I),
        "visible version change; reversible but people will notice",
    ),
    (
        "R1",
        re.compile(r"restart|reboot|re-?ran|rerun|re-?sync", re.I),
        "self-reversing — the service returns to the same state",
    ),
    (
        "R1",
        re.compile(r"clear(ed)?|flush|purge|deleted temp|log files", re.I),
        "removes only regenerable data (cache, temp, rotated logs)",
    ),
    ("R1", re.compile(r"unlock", re.I), "reversible — the account can be locked again"),
)

TIER_BY_PRIORITY = {
    "1": "platinum",
    "2": "gold",
    "3": "silver",
    "4": "bronze",
}


def _tier(note: str) -> tuple[str | None, str | None]:
    if PHYSICAL.search(note):
        return None, None
    for tier, pattern, why in TIER_RULES:
        if pattern.search(note):
            return tier, why
    return None, None


def _support_tier(priority: str) -> str:
    head = priority.strip()[:1]
    return TIER_BY_PRIORITY.get(head, "silver")


# ---------------------------------------------------------------------- build
def build(
    rows: Iterable[Mapping[str, Any]],
    *,
    kind: str = "historical",
    name: str = "Ticket export",
) -> dict[str, Any]:
    """Derive everything from one export.

    Returns the corpus and its three sidecars in a single structure, so a caller
    persists one consistent set rather than four files that could disagree.
    """
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "ci": Counter(), "group": Counter(), "priority": Counter()}
    )
    by_ci: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "group": Counter(), "priority": Counter()}
    )
    redacted: Counter[str] = Counter()
    opened: list[datetime] = []
    read = 0
    skipped = 0

    for row in rows:
        symptom_raw = pick(row, COLUMNS["symptom"])
        resolution_raw = pick(row, COLUMNS["resolution"])
        if not symptom_raw or not resolution_raw:
            skipped += 1
            continue
        read += 1

        symptom_clean, hits = redact(symptom_raw)
        redacted.update(hits)
        resolution_clean, hits = redact(resolution_raw)
        redacted.update(hits)

        symptom = generalise(symptom_clean)
        resolution = generalise(resolution_clean)

        klass = ci_class(pick(row, COLUMNS["ci"]))
        group = pick(row, COLUMNS["group"])
        priority = pick(row, COLUMNS["priority"])

        bucket = buckets[(symptom, resolution)]
        bucket["n"] += 1
        if klass:
            bucket["ci"][klass] += 1
        if group:
            bucket["group"][group] += 1
        if priority:
            bucket["priority"][priority] += 1

        if klass:
            entry = by_ci[klass]
            entry["n"] += 1
            if group:
                entry["group"][group] += 1
            if priority:
                entry["priority"][priority] += 1

        raw = pick(row, COLUMNS["opened"])
        if raw:
            try:
                opened.append(datetime.fromisoformat(raw))
            except ValueError:
                pass

    entries = [
        {
            "symptom": symptom,
            "resolution": resolution,
            "ci_classes": [c for c, _ in bucket["ci"].most_common(3)],
            "groups": [g for g, _ in bucket["group"].most_common(2)],
            "priority": (bucket["priority"].most_common(1) or [("", 0)])[0][0],
            "n": bucket["n"],
        }
        for (symptom, resolution), bucket in buckets.items()
    ]
    entries.sort(key=lambda e: (-e["n"], e["symptom"]))

    # --- runbook candidates ---
    per_resolution: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "ci": Counter(), "group": Counter()}
    )
    for entry in entries:
        item = per_resolution[entry["resolution"]]
        item["n"] += entry["n"]
        for klass in entry["ci_classes"]:
            item["ci"][klass] += entry["n"]
        for group in entry["groups"]:
            item["group"][group] += entry["n"]

    candidates = []
    for resolution, item in per_resolution.items():
        tier, why = _tier(resolution)
        if not tier:
            continue
        candidates.append(
            {
                "tickets": item["n"],
                "tier": tier,
                "rationale": why,
                "ci_class": (item["ci"].most_common(1) or [("unknown", 0)])[0][0],
                "owning_team": (item["group"].most_common(1) or [("unknown", 0)])[0][0],
                "resolution": resolution,
            }
        )
    candidates.sort(key=lambda c: (c["tier"], -c["tickets"]))

    # --- mapping rules ---
    ready, review = [], []
    for klass, entry in sorted(by_ci.items(), key=lambda kv: -kv[1]["n"]):
        if not entry["group"]:
            continue
        group, count = entry["group"].most_common(1)[0]
        confidence = count / entry["n"]
        priority = (entry["priority"].most_common(1) or [("", 0)])[0][0]
        row = {
            "ci_class": klass,
            "owning_team": group,
            "support_tier": _support_tier(priority),
        }
        if confidence >= 0.7:
            ready.append(row)
        else:
            # Below this line the component does not determine the owner — the
            # symptom does — so a rule would mis-route roughly half of them,
            # always towards whichever team was more common in the export.
            review.append(
                {
                    **row,
                    "confidence": round(confidence, 2),
                    "also": [g for g, _ in entry["group"].most_common(3)[1:]],
                }
            )

    window = ""
    if opened:
        window = f"{min(opened).date().isoformat()} to {max(opened).date().isoformat()}"

    return {
        "source": {
            "name": name,
            "kind": kind,
            "tickets": read,
            "patterns": len(entries),
            "distinct_resolutions": len({e["resolution"] for e in entries}),
            "window": window,
            "caveat": (
                "Synthetic data. The symptom-to-resolution patterns are plausible but "
                "invented, and no timing information is carried. Treat a match as a "
                "hypothesis worth checking, never as evidence that this estate has seen "
                "the problem before."
                if kind == "synthetic"
                else "Historical ticket data from this client. Personal identifiers were "
                "removed at ingest, and no resolution times are carried."
            ),
        },
        "entries": entries,
        "runbook_candidates": candidates,
        "mapping_rows": ready,
        "mapping_needs_review": review,
        "ingest": {
            "rows_read": read,
            "rows_skipped": skipped,
            "redacted": dict(redacted),
        },
    }


def merge(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Add a new export to what a client already has.

    Counts accumulate, so a fix seen in three exports outranks one seen in a
    single unusual month — which is the whole reason for uploading more than one
    dump. Everything derived is recomputed from the merged patterns rather than
    concatenated, so the runbook tiers and routing confidence reflect the full
    history instead of whichever file arrived last.
    """
    if not existing or not existing.get("entries"):
        return incoming

    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in [*existing.get("entries", []), *incoming.get("entries", [])]:
        key = (entry.get("symptom", ""), entry.get("resolution", ""))
        if not key[0] or not key[1]:
            continue
        current = combined.get(key)
        if current is None:
            combined[key] = dict(entry)
            continue
        current["n"] = int(current.get("n", 0)) + int(entry.get("n", 0))
        current["ci_classes"] = list(
            dict.fromkeys(
                [*current.get("ci_classes", []), *entry.get("ci_classes", [])]
            )
        )[:3]
        current["groups"] = list(
            dict.fromkeys([*current.get("groups", []), *entry.get("groups", [])])
        )[:2]

    entries = sorted(combined.values(), key=lambda e: (-e["n"], e["symptom"]))
    rebuilt = _rederive(entries)

    old_source = existing.get("source") or {}
    new_source = incoming.get("source") or {}
    # A merged corpus is only "historical" if everything in it is. One synthetic
    # export makes the whole thing synthetic, because a search result cannot say
    # which upload a given pattern came from.
    kind = (
        "historical"
        if old_source.get("kind") == "historical"
        and new_source.get("kind") == "historical"
        else "synthetic"
    )

    return {
        "source": {
            **new_source,
            "kind": kind,
            "name": new_source.get("name") or old_source.get("name"),
            "tickets": int(old_source.get("tickets", 0))
            + int(new_source.get("tickets", 0)),
            "patterns": len(entries),
            "distinct_resolutions": len({e["resolution"] for e in entries}),
            "window": _widen(old_source.get("window"), new_source.get("window")),
        },
        "entries": entries,
        **rebuilt,
        "ingest": incoming.get("ingest", {}),
    }


def _rederive(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the sidecars from merged patterns."""
    per_resolution: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "ci": Counter(), "group": Counter()}
    )
    by_ci: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "group": Counter()})

    for entry in entries:
        item = per_resolution[entry["resolution"]]
        item["n"] += entry["n"]
        for klass in entry.get("ci_classes", []):
            item["ci"][klass] += entry["n"]
            by_ci[klass]["n"] += entry["n"]
            for group in entry.get("groups", []):
                by_ci[klass]["group"][group] += entry["n"]
        for group in entry.get("groups", []):
            item["group"][group] += entry["n"]

    candidates = []
    for resolution, item in per_resolution.items():
        tier, why = _tier(resolution)
        if not tier:
            continue
        candidates.append(
            {
                "tickets": item["n"],
                "tier": tier,
                "rationale": why,
                "ci_class": (item["ci"].most_common(1) or [("unknown", 0)])[0][0],
                "owning_team": (item["group"].most_common(1) or [("unknown", 0)])[0][0],
                "resolution": resolution,
            }
        )
    candidates.sort(key=lambda c: (c["tier"], -c["tickets"]))

    ready, review = [], []
    for klass, entry in sorted(by_ci.items(), key=lambda kv: -kv[1]["n"]):
        if not entry["group"]:
            continue
        group, count = entry["group"].most_common(1)[0]
        confidence = count / max(sum(entry["group"].values()), 1)
        row = {"ci_class": klass, "owning_team": group, "support_tier": "silver"}
        if confidence >= 0.7:
            ready.append(row)
        else:
            review.append(
                {
                    **row,
                    "confidence": round(confidence, 2),
                    "also": [g for g, _ in entry["group"].most_common(3)[1:]],
                }
            )

    return {
        "runbook_candidates": candidates,
        "mapping_rows": ready,
        "mapping_needs_review": review,
    }


def _widen(a: str | None, b: str | None) -> str:
    dates = []
    for window in (a, b):
        if window:
            dates.extend(re.findall(r"\d{4}-\d{2}-\d{2}", window))
    if not dates:
        return ""
    return f"{min(dates)} to {max(dates)}"
