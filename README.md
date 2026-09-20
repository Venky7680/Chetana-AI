# Chetana AI — console + BFF over Keep

The console and backend-for-frontend for the Chetana AI AIOps platform. **Keep is the
backend of record** for alert ingestion, deduplication, correlation and workflow
execution. This repo is everything in front of it: a FastAPI BFF that is the only thing
allowed to talk to Keep, and a Next.js console for the NOC.

```
browser ── Next.js console ──► FastAPI BFF ──► Keep ──► client estate
                                   │
                                   ├── operation allowlist   (what may be called at all)
                                   ├── autonomy gate         (what may run unattended)
                                   ├── tenant registry       (whose Keep, whose ceiling)
                                   └── audit trail           (what was attempted, by whom)
```

## Why a BFF and not a direct call to Keep

Three things the browser cannot be trusted to do, and that Keep does not do for an MSP:

**1. The operation allowlist.** The console never names a Keep URL. It names an
*operation id* — `incidents.status`, `workflows.run` — and `bff/app/core/allowlist.py`
maps that to exactly one method, one path template, a declared set of query parameters,
a minimum role and a reversibility tier. An undeclared query parameter is dropped; an
unlisted operation is a 400. Adding a Keep capability to the product is a reviewable
one-line change, not an emergent property of a pass-through proxy.

**2. Reversibility-based autonomy.** Autonomy is gated on how hard an action is to undo,
never on how urgent the alert is. A P1 does not make a `DELETE` safe.

| Tier | Meaning | Example | Gate |
|------|---------|---------|------|
| R0 | Read | list alerts, fetch an incident | always allowed |
| R1 | Auto-reversible | acknowledge, comment, enrich, assign | runs unattended |
| R2 | Reversible with effort | run a remediation workflow, merge incidents | one approval |
| R3 | Irreversible | delete an incident, uninstall a provider | two distinct approvers |

Three ceilings apply and the strictest wins: the deployment ceiling, the tenant's own
ceiling (what that client signed off on), and the caller's role. Anything above the
effective ceiling is not refused — it is **parked** as an approval request that a second
principal releases. A requester can never approve their own request, and an approval is
single-use.

**3. Tenancy.** One BFF, many clients, one Keep instance (and API key) per client. Every
request carries `X-Chetana-Tenant`; entitlement is checked before anything reaches Keep,
and a tenant the caller is not entitled to returns 404 rather than 403, so the console
never confirms that a client exists to someone who should not know.

Everything a write attempts — executed, denied, or parked — lands in an append-only
NDJSON audit trail, visible in the console under **Governance**.

## Run it

### The real thing

```powershell
.\scripts\tasks.ps1 init     # one-time: .env, tenants.json, users.json
.\scripts\tasks.ps1 real     # real Keep + a real alert pipeline + BFF + console
```

This stands up an actual failure chain. Nothing in it is simulated:

```
loadgen ──HTTP──► payments-api ──HTTP──► ledger-worker
                       │                      │
                       └──── /metrics ────────┘
                                 │
                            Prometheus   scrapes, evaluates 10 alert rules
                                 │
                           Alertmanager  groups, inhibits, routes
                                 │
                                Keep      dedup, correlate, workflows
                                 │
                                BFF       allowlist, autonomy gate, audit
                                 │
                              console
```

`loadgen` makes real HTTP calls. `payments-api` holds a bounded pool of upstream
connections and sheds with a genuine 503 once it is full — real backpressure, not a
coin flip. `ledger-worker` does real CPU work (iterated hashing) behind a real
concurrency limit, so latency climbs because work is actually queueing. Prometheus
scrapes what really happened, and the alerts fire because the system really degraded.

| Where | URL |
|---|---|
| Chetana console | <http://localhost:3100> |
| Keep's own UI | <http://localhost:3000> |
| Prometheus (alert state) | <http://localhost:9090/alerts> |
| Alertmanager | <http://localhost:9093> |
| payments-api metrics | <http://localhost:8001/metrics> |
| Chetana BFF | <http://localhost:8090> |

**Give it 3–6 minutes.** The load generator ramps on a seven-minute cycle, rules need
one to three minutes of sustained breach, then Alertmanager groups and posts to Keep.
Watch `/alerts` on Prometheus go green → yellow (pending) → red (firing) first; alerts
appear in the console a few seconds after that.

To force a hard outage immediately rather than waiting for the load curve:

```powershell
docker compose stop ledger-worker    # TargetDown + LedgerUnreachable within ~60s
docker compose start ledger-worker   # recovery, and resolved events flow through too
```

### Stub Keep, for a demo with no dependencies

```powershell
.\scripts\tasks.ps1 demo
```

Serves plausible Middle East estate data from `bff/tools/fake_keep.py`. Useful on a
plane; not something to show as if it were live.

### Against a Keep you already run

```powershell
.\scripts\tasks.ps1 up
```

Set each tenant's `keep_base_url` in `config/tenants.json` first.

### Without Docker

```bash
cd bff
pip install -r requirements-dev.txt
export CHETANA_JWT_SECRET=dev CHETANA_TENANTS_JSON=../config/tenants.json CHETANA_USERS_JSON=../config/users.json
uvicorn app.main:app --port 8090 --reload

cd web && npm install
NEXT_PUBLIC_BFF_URL=http://localhost:8090 npm run dev -- -p 3100
```

## What fires, and why

Ten rules in `ops/prometheus/rules/chetana.yml`, each over a genuinely observed series:

| Alert | Fires when | Severity |
|---|---|---|
| `TargetDown` | Prometheus cannot scrape a service for 1m | critical |
| `LedgerUnreachable` | payments-api's upstream calls are failing outright | critical |
| `HighErrorRate` | over 5% of requests returning 5xx for 2m | critical |
| `HighLatencyP99` | p99 above the 1.5s objective for 3m | warning |
| `ElevatedLatencyP95` | p95 above 750ms for 3m | warning |
| `UpstreamPoolSaturated` | connection pool over 90% utilised for 2m | warning |
| `LedgerSlotsSaturated` | every settlement slot occupied for 2m | warning |
| `LedgerQueueBacklog` | more than eight callers queueing for a slot | high |
| `HighMemoryUsage` | resident memory above 220MB for 5m | warning |
| `FileDescriptorPressure` | over 70% of the fd limit in use for 5m | warning |

An inhibit rule stops latency warnings paging while the service is already down — the
same thing Keep's correlation then does one layer up.

## Configuration

`.\scripts\tasks.ps1 init` writes all three files for you. To change things afterwards,
edit them directly — or to add a user, generate a hash and add an entry:

```powershell
cd bff; python -m app.cli hash-password 'the-real-password'
```

Pass the password non-interactively with `.\scripts\tasks.ps1 init -Password 'x'`.

`config/tenants.json` — one entry per managed client:

| Field | Meaning |
|-------|---------|
| `id` | used in the `X-Chetana-Tenant` header |
| `keep_base_url` / `keep_api_key` | that client's Keep instance |
| `max_autonomy_tier` | what this client has signed off on (0–3) |
| `tags` | shown in the console; useful for region/vertical |

`config/users.json` — console users. Roles, in order: `viewer` → `operator` →
`approver` → `admin`. `tenants: ["*"]` means every client. This is a local-users
fallback; `bff/app/core/security.py` is the one file to change to put OIDC in front
(the rest of the BFF depends only on the `Principal` abstraction).

## Tests

```powershell
.\scripts\tasks.ps1 setup
.\scripts\tasks.ps1 test     # 58 unit + API tests, Keep stubbed over ASGI
.\scripts\tasks.ps1 smoke    # 22 end-to-end checks over real HTTP
.\scripts\tasks.ps1 lint     # ruff + tsc
.\scripts\tasks.ps1 build    # production build of the console
```

Also worth running after any change to the alert rules:

```powershell
promtool check rules ops\prometheus\rules\chetana.yml
amtool check-config ops\alertmanager\alertmanager.yml
python ops\services\verify_pipeline.py
```

`verify_pipeline.py` starts the real services, drives real traffic through them, scrapes
their real `/metrics`, and asserts that every series the alert rules reference is
actually exported. A typo in a metric name does not fail loudly — Prometheus just
evaluates the rule to an empty vector forever and the alert silently never fires.

`tools/smoke_test.py` boots the stub Keep and the BFF as real processes and walks the
full four-eyes path: park → self-approval refused → approver releases → action executes →
replay refused. Run it after any change to the gateway.

## AI investigation (Layer 5)

HolmesGPT answers "why is this incident happening". The interesting part is not that
it is wired in, but **how**.

Out of the box Holmes investigates by calling the estate directly — kubectl, Prometheus,
cloud APIs — with credentials mounted into its container. That is fine for one team
debugging its own cluster. For an MSP it is not: the operation allowlist would govern
Chetana to Keep, while a language model ran unsupervised queries against a client's
production estate with standing credentials.

So **Holmes is given no credentials for the client estate at all**. Instead:

1. Starting an investigation mints a token scoped to *that investigation* — one tenant,
   a fixed list of read-only tools, a short expiry.
2. The BFF passes it to Holmes as a request header. Holmes' header propagation exposes
   it to the toolset, so each `curl` carries it back to us. It travels as
   `X-Chetana-Evidence-Token`, not a bearer token: Holmes strips `Authorization` from
   propagation by default.
3. Every call lands on the evidence gateway: token verified, tenant resolved, tool
   mapped to an allowlisted **R0** operation, budget decremented, result recorded.

```
console ──► BFF ──► HolmesGPT ──► Bedrock (the model)
              ▲          │
              └──────────┘
          evidence gateway
      allowlisted · tenant-scoped
        time-boxed · audited
```

Three properties fall out of it:

- Holmes cannot reach anything the allowlist does not already permit. A unit test
  asserts every evidence tool points at an R0 operation, so a typo cannot widen it.
- Every read is attributed to an investigation, a tenant and the person who asked.
- **The evidence chain in the console is built from what the gateway served, not from
  what the model said it did.** When the two disagree the panel says so. A hallucinated
  tool call has no row.

Cost is capped twice: a per-investigation read budget (the runaway-loop stop) and a
per-tenant hourly ceiling — because the natural trigger for an investigation is an alert
storm, which is exactly when you least want an unbounded number of them.

Investigation is per-tenant opt-in (`investigations_enabled`). A client can have managed
services without having agreed that a language model may read their estate.

```powershell
# .env — these reach the MODEL only, never the estate.
# A Bedrock API key is a bearer token; that plus the region is the whole setup.
AWS_BEARER_TOKEN_BEDROCK=...
AWS_REGION_NAME=us-east-1
CHETANA_HOLMES_MODEL=bedrock/us.anthropic.claude-sonnet-5

# Bring the whole profile up. Do NOT name services here: naming one starts
# only it and its dependencies, so keep-backend stays down and every page
# reports Keep unreachable.
docker compose --profile real up -d --build
```

Add `prometheus_base_url` to a tenant in `config\tenants.json` to give its
investigations the two PromQL tools; without it they are simply not granted, rather than
failing mid-investigation. The toolset itself is `ops\holmes\toolsets.yaml`, and the
console lists it under **Governance → AI evidence tools**, so a client's security
reviewer can read exactly what the model may see.

## What the console shows

| Page | What it is for |
|------|----------------|
| **Overview** | One call, whole picture: open incidents, firing alerts, noise reduction, noisiest services |
| **Estate** | Every client you are entitled to on one screen, worst first |
| **Incidents** | Correlated incidents; detail fans out to alerts + workflow runs in one round trip |
| **Alerts** | Everything ingested, with server-side CEL filtering and a per-alert detail page |
| **Alert detail** | Source labels, every occurrence, Keep's own audit trail, and enrichment |
| **Workflows** | Keep automation; detail page shows the YAML and run history |
| **Approvals** | Parked actions, who asked, how many approvals are still needed |
| **Correlation** | Correlation rules (create one from a CEL predicate) and deduplication ratios |
| **Topology** | Service dependencies, and what breaks if a given service breaks |
| **Maintenance** | Suppression windows — open one before a planned change |
| **Providers** | Connect and disconnect telemetry sources, and the Keep catalogue |
| **Governance** | The allowlist, the AI evidence toolset, and the audit trail |

## Layout

```
bff/
  app/core/allowlist.py    every Keep operation the product can perform
  app/core/autonomy.py     reversibility tiers, ceilings, approval ledger
  app/core/keep_client.py  per-tenant HTTP client; cannot be given a raw path
  app/core/normalize.py    provider-dialect smoothing + derived stats
  app/core/security.py     auth, roles, entitlement  ← swap for OIDC here
  app/core/evidence.py     the read-only toolset an LLM may use, and its scoped tokens
  app/core/holmes_client.py  HolmesGPT over HTTP
  app/core/store.py        investigations + the evidence chain (SQLite → Postgres)
  app/routers/evidence.py  the gateway HolmesGPT calls back into
  app/gateway.py           the single chokepoint: allowlist → gate → audit → Keep
  app/routers/             thin HTTP surface; no router touches Keep directly
  tools/fake_keep.py       stub Keep for tests and offline demos
  tools/smoke_test.py      end-to-end checks
ops/
  services/                payments-api, ledger-worker, loadgen — the estate being watched
  services/verify_pipeline.py  proves the rules reference series that exist
  holmes/toolsets.yaml     the only toolset Holmes gets: curls into the evidence gateway
  prometheus/              scrape config + 10 alert rules
  alertmanager/            grouping, inhibition, and the webhook into Keep
scripts/tasks.ps1          init / real / demo / up / test / smoke / lint on Windows
web/
  app/(console)/           console pages
  components/ui.tsx        severity/tier badges, gated action button
  lib/session.tsx          session, tenant switching, server-supplied capabilities
```

## Next

- **PyRCA** for causal ranking, feeding a ranked candidate list into the Holmes prompt
  as a prior. Gated on data rather than effort: a causal graph needs weeks of real
  telemetry before it is worth trusting.
- **Auto-remediation** — StackStorm or Keep workflows behind the R2 gate. The approval
  ledger is the integration point; it is in-memory today and wants Redis or Postgres
  before the BFF runs more than one replica. (Investigations already persist —
  `CHETANA_DATABASE_URL`, SQLite by default, Postgres by changing one string.)
- **Investigation feedback** — a thumbs up/down per finding, the only way to show RCA
  accuracy improving over time.
- **OIDC** in `security.py`, so console identity comes from the client's IdP.
- **Approval notifications** — the ledger has everything a Teams or ServiceNow hook needs.
