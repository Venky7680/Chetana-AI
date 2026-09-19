"""ledger-worker — a real service that does real work.

Nothing here simulates a metric. It runs an actual CPU-bound settlement
computation under an actual concurrency limit, and the metrics are measurements
of what really happened. When the API sends it more work than `WORKER_SLOTS`
allows, requests really do queue, latency really does climb, and Prometheus sees
it because it happened — not because a script decided it should.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SLOTS = int(os.getenv("WORKER_SLOTS", "8"))
# How much real CPU one settlement costs. Tuned so a single request is a few ms.
ROUNDS = int(os.getenv("WORKER_ROUNDS", "18000"))

app = FastAPI(title="ledger-worker")

settlements = Counter("ledger_settlements_total", "Settlements processed", ["outcome"])
duration = Histogram(
    "ledger_settlement_duration_seconds",
    "Wall-clock time to settle, including time spent waiting for a slot",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
inflight = Gauge("ledger_inflight", "Settlements executing right now")
queued = Gauge("ledger_queued", "Callers waiting for a free slot")
capacity = Gauge("ledger_slots", "Concurrency limit")
capacity.set(SLOTS)

_semaphore = asyncio.Semaphore(SLOTS)


def _settle(reference: str) -> str:
    """Genuine CPU work: iterated hashing. Blocks the thread, as real work does."""
    digest = reference.encode()
    for _ in range(ROUNDS):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()[:16]


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {"status": "ok", "slots": SLOTS, "inflight": inflight._value.get()}


@app.post("/settle")
async def settle(reference: str = "txn") -> dict[str, object]:
    started = time.perf_counter()
    queued.inc()
    try:
        async with _semaphore:
            queued.dec()
            inflight.inc()
            try:
                # Real work, off the event loop so the service stays responsive.
                token = await asyncio.to_thread(_settle, reference)
            finally:
                inflight.dec()
    except Exception:
        settlements.labels(outcome="error").inc()
        raise
    elapsed = time.perf_counter() - started
    duration.observe(elapsed)
    settlements.labels(outcome="ok").inc()
    return {"reference": reference, "token": token, "seconds": round(elapsed, 4)}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
