"""loadgen — real HTTP traffic against payments-api.

Concurrency follows a slow cycle, so the estate genuinely moves between healthy
and overloaded over a period of minutes. Nothing about the alerts is scripted:
the load is real, the saturation is real, and the alerts fire because the system
actually degraded.

Tune with LOAD_MIN / LOAD_MAX / LOAD_PERIOD_SECONDS.
"""

from __future__ import annotations

import asyncio
import math
import os
import time

import httpx

TARGET = os.getenv("TARGET_URL", "http://payments-api:8000")
LOAD_MIN = int(os.getenv("LOAD_MIN", "2"))
LOAD_MAX = int(os.getenv("LOAD_MAX", "26"))
PERIOD = float(os.getenv("LOAD_PERIOD_SECONDS", "420"))


def concurrency_now(started: float) -> int:
    """A slow sine between LOAD_MIN and LOAD_MAX — a plausible daily curve,
    compressed into minutes so a demo does not take a day."""
    phase = ((time.time() - started) % PERIOD) / PERIOD
    wave = (math.sin(phase * 2 * math.pi - math.pi / 2) + 1) / 2
    return int(LOAD_MIN + wave * (LOAD_MAX - LOAD_MIN))


async def worker(client: httpx.AsyncClient, index: int, stop: asyncio.Event) -> None:
    counter = 0
    while not stop.is_set():
        counter += 1
        try:
            await client.post("/pay", params={"reference": f"w{index}-{counter}"})
        except httpx.HTTPError:
            # The API being unreachable is itself a real condition; Prometheus
            # sees it as up == 0. Nothing to do but keep trying.
            await asyncio.sleep(0.5)
        await asyncio.sleep(0.05)


async def main() -> None:
    started = time.time()
    stop = asyncio.Event()
    running: list[asyncio.Task] = []

    async with httpx.AsyncClient(base_url=TARGET, timeout=10.0) as client:
        # Wait for the target to exist before generating load.
        for _ in range(60):
            try:
                await client.get("/healthz")
                break
            except httpx.HTTPError:
                await asyncio.sleep(2)

        while True:
            want = concurrency_now(started)
            while len(running) < want:
                running.append(asyncio.create_task(worker(client, len(running), stop)))
            while len(running) > want:
                task = running.pop()
                task.cancel()
            print(f"loadgen: {len(running)} concurrent callers", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
