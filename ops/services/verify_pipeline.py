"""Prove the alert rules reference metrics that actually exist.

A typo in a metric name does not fail anything loudly — Prometheus just
evaluates the rule to an empty vector forever and the alert silently never
fires. That is the worst possible failure for a demo, so this runs the real
services, drives real traffic through them, scrapes their real /metrics, and
checks every series name the rules depend on is present.

    python ops/services/verify_pipeline.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
RULES = HERE.parents[1] / "ops" / "prometheus" / "rules" / "chetana.yml"

LEDGER_PORT, API_PORT = 18002, 18001

# Series Prometheus itself synthesises, not something a service exports.
PROMETHEUS_BUILTINS = {"up"}


def metric_names_in_rules() -> set[str]:
    text = RULES.read_text(encoding="utf-8")
    exprs = re.findall(r"expr:\s*(?:\|[^\n]*\n)?((?:.*\n)*?)\s*for:", text)
    names: set[str] = set()
    for expr in exprs:
        # Strip label selectors first so label names are not mistaken for series.
        stripped = re.sub(r"\{[^}]*\}", "", expr)
        for token in re.findall(r"\b[a-z_][a-z0-9_]*\b", stripped):
            names.add(token)
    # Drop PromQL keywords and functions.
    noise = {
        "sum", "by", "rate", "clamp_min", "histogram_quantile", "le", "service",
        "environment", "team", "status", "kind", "e6", "and", "or", "unless", "on",
        "ignoring", "group_left", "group_right", "avg", "max", "min", "count", "increase",
        "absent", "delta", "idelta", "irate", "round", "floor", "ceil", "abs", "topk",
        "bottomk", "quantile", "stddev", "without", "offset", "bool", "label_replace",
        "time", "vector", "scalar", "clamp_max", "predict_linear", "deriv", "changes",
        "m", "s", "h", "d", "w", "y", "e",
    }
    return {n for n in names if n not in noise and not n.isdigit()}


def scrape(port: int) -> set[str]:
    raw = urlopen(f"http://127.0.0.1:{port}/metrics", timeout=10).read().decode()
    found: set[str] = set()
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        found.add(line.split("{")[0].split(" ")[0])
    # A histogram named X exposes X_bucket / X_sum / X_count.
    return found


def wait(port: int, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
            return True
        except (URLError, OSError):
            time.sleep(0.5)
    return False


def main() -> int:
    env = {**os.environ, "WORKER_SLOTS": "4", "WORKER_ROUNDS": "6000"}
    ledger = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ledger_worker:app", "--port", str(LEDGER_PORT),
         "--log-level", "warning"],
        cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "payments_api:app", "--port", str(API_PORT),
         "--log-level", "warning"],
        cwd=HERE,
        env={**env, "LEDGER_URL": f"http://127.0.0.1:{LEDGER_PORT}", "UPSTREAM_POOL": "3"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    failures: list[str] = []
    try:
        if not (wait(LEDGER_PORT) and wait(API_PORT)):
            print("services did not start")
            return 1

        # Real traffic, enough concurrency to genuinely exhaust the pool of 3.
        import concurrent.futures
        import urllib.request

        def call(i: int) -> int:
            request = urllib.request.Request(
                f"http://127.0.0.1:{API_PORT}/pay?reference=v{i}", method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.status
            except Exception as exc:  # 503 arrives as HTTPError
                return getattr(exc, "code", 0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            statuses = list(pool.map(call, range(200)))

        ok = sum(1 for s in statuses if s == 200)
        shed = sum(1 for s in statuses if s == 503)
        print(f"  traffic: {ok} settled, {shed} shed with 503, {len(statuses)} total")
        if ok == 0:
            failures.append("no request succeeded — the service chain is broken")
        if shed == 0:
            print("  note: nothing was shed; raise concurrency to exercise the 503 path")

        exported = scrape(API_PORT) | scrape(LEDGER_PORT)
        required = metric_names_in_rules() - PROMETHEUS_BUILTINS

        print(f"  rules reference {len(required)} series; services export {len(exported)}")
        for name in sorted(required):
            if name in exported:
                print(f"  PASS  {name}")
            else:
                print(f"  FAIL  {name} — referenced by a rule, exported by nothing")
                failures.append(name)
    finally:
        for process in (api, ledger):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()

    print()
    if failures:
        print(f"{len(failures)} problem(s): {', '.join(failures)}")
        return 1
    print("Every series the alert rules depend on is really being exported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
