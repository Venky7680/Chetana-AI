"""payments-api — the front door, and the thing that actually breaks.

It holds a bounded pool of upstream connections to ledger-worker. When load
exceeds what the pool can carry, it sheds with a real 503 rather than queueing
forever — genuine backpressure. When ledger-worker is stopped, calls really do
fail. Every metric below is a measurement of that, so the Prometheus rules fire
on things that truly happened.

To see a hard outage end to end:  docker compose stop ledger-worker
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

LEDGER_URL = os.getenv("LEDGER_URL", "http://ledger-worker:8000")
POOL = int(os.getenv("UPSTREAM_POOL", "12"))
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "2.0"))

app = FastAPI(title="payments-api")

requests_total = Counter(
    "http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
request_duration = Histogram(
    "http_request_duration_seconds",
    "End-to-end request latency",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
upstream_errors = Counter(
    "payments_upstream_errors_total", "Failed calls to ledger-worker", ["kind"]
)
pool_inflight = Gauge("payments_pool_inflight", "Upstream calls in flight")
pool_size = Gauge("payments_pool_size", "Upstream connection pool size")
pool_size.set(POOL)

_pool = asyncio.Semaphore(POOL)
_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=LEDGER_URL,
        timeout=UPSTREAM_TIMEOUT,
        limits=httpx.Limits(max_connections=POOL),
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client is not None:
        await _client.aclose()


def _record(route: str, status: int, started: float) -> None:
    requests_total.labels(method="POST", route=route, status=str(status)).inc()
    request_duration.labels(route=route).observe(time.perf_counter() - started)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/pay")
async def pay(reference: str = "txn") -> Response:
    """Take a payment. Sheds load rather than queueing without bound."""
    started = time.perf_counter()
    route = "/pay"

    if _pool.locked():
        # Every slot is busy. Shedding is the honest answer, and 503 is a real
        # server error that the error-rate rule will see.
        _record(route, 503, started)
        upstream_errors.labels(kind="pool_exhausted").inc()
        return Response(status_code=503, content='{"detail":"upstream pool exhausted"}',
                        media_type="application/json")

    async with _pool:
        pool_inflight.inc()
        try:
            assert _client is not None
            response = await _client.post("/settle", params={"reference": reference})
            response.raise_for_status()
        except httpx.TimeoutException:
            upstream_errors.labels(kind="timeout").inc()
            _record(route, 504, started)
            return Response(status_code=504, content='{"detail":"ledger timeout"}',
                            media_type="application/json")
        except httpx.HTTPStatusError as exc:
            upstream_errors.labels(kind="upstream_status").inc()
            _record(route, 502, started)
            return Response(status_code=502,
                            content=f'{{"detail":"ledger returned {exc.response.status_code}"}}',
                            media_type="application/json")
        except httpx.HTTPError:
            # ledger-worker is down or unreachable — a real outage.
            upstream_errors.labels(kind="unreachable").inc()
            _record(route, 502, started)
            return Response(status_code=502, content='{"detail":"ledger unreachable"}',
                            media_type="application/json")
        finally:
            pool_inflight.dec()

    _record(route, 200, started)
    return Response(status_code=200, content=response.text, media_type="application/json")


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
