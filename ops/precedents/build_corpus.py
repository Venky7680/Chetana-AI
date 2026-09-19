"""Build a precedent corpus from a ticket export, without the console.

The console can do this now — Runbook candidates → Ticket history takes a drag
and drop, and it is the right route for anything belonging to a client. This
script remains for the cases a browser is wrong for: seeding a deployment before
anyone has logged in, a corpus built in CI, or a file too large to upload.

It is deliberately a thin wrapper. The parsing, redaction and tiering all live
in the BFF's `app/core/corpus_builder`, because two implementations would drift
and the one that drifted would be the one deciding what a language model reads.

    python build_corpus.py tickets.csv corpus.json --kind historical \\
        --name "Client X service desk"

A corpus written here is the *shared fallback*, used only by clients that have
uploaded nothing of their own. Per-client corpora live on the BFF's writable
volume and are only ever written through the console, so that a file on an
engineer's laptop cannot become one client's history in another's investigation.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# The builder is the BFF's, imported directly rather than copied.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bff"))

from app.core.corpus_builder import build  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="ticket export, CSV")
    parser.add_argument("target", type=Path, help="corpus to write")
    parser.add_argument(
        "--kind",
        choices=("synthetic", "historical"),
        default="synthetic",
        help=(
            "Whether these tickets really happened. Travels with every search "
            "result, so a model citing generated history has to say so."
        ),
    )
    parser.add_argument("--name", default="Ticket export")
    args = parser.parse_args()

    with args.source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    corpus = build(rows, kind=args.kind, name=args.name)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(
        json.dumps(corpus, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    info = corpus["source"]
    ingest = corpus["ingest"]
    print(
        f"{args.target}: {info['patterns']} patterns from {info['tickets']} tickets, "
        f"{info['distinct_resolutions']} distinct resolutions, kind={info['kind']}"
    )
    print(
        f"  runbook candidates: {len(corpus['runbook_candidates'])} · "
        f"mapping rows: {len(corpus['mapping_rows'])} ready, "
        f"{len(corpus['mapping_needs_review'])} need review"
    )
    if ingest["redacted"]:
        removed = ", ".join(f"{n} {k}" for k, n in sorted(ingest["redacted"].items()))
        print(f"  redacted: {removed}")
    if ingest["rows_skipped"]:
        print(
            f"  skipped {ingest['rows_skipped']} rows with no short description "
            f"or resolution notes"
        )


if __name__ == "__main__":
    main()
