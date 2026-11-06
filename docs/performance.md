# Performance measurements and reproducible benchmarks

These are bounded local smoke results recorded on 5 November 2026, **not sustained capacity, a production SLO, or evidence of 1M TPM**. The implementation prioritizes correctness and recovery; added event/audit writes are not free.

## Recorded environment

- Windows host, AMD Ryzen 7 6800HS Creator Edition, 8 cores / 16 logical processors, approximately 13.7 GiB usable host RAM.
- PostgreSQL 16.11 in the existing local Docker container, 6.621 GiB container memory budget; `max_connections=100`, `shared_buffers=128MB`, `fsync=on`, `synchronous_commit=on`.
- Python 3.11.0; optional Locust 2.47.0; one Uvicorn API process and one separate PostgreSQL outbox worker for HTTP tests. Load generator and API share the host. No replica, proxy, TLS or network fault injection.
- HTTP dataset: 12 synthetic users, 24 owned accounts, default security rules/PIN hashing, three ledger-backed demo funding actions per user. No arbitrary balance assignment, production bypass flag or relaxed fraud policy.
- Benchmark fixtures use SQLAlchemy's test-engine pool (5 connections + 10 overflow); their separate worker uses 2 + 0. Production configuration defaults to 5 + 5. This fixture difference, shared-host execution and brief duration limit extrapolation.
- In-process comparison: 3 users/accounts, 2 client threads, 18 transfers at ₹1, real PostgreSQL and real Argon2 grants. No HTTP server/network; setup/funding are excluded from timing.

## Actual results

| Workload | New commits | Measured interval | New committed TPS | HTTP RPS | HTTP errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| ASGI baseline before reliability changes | 18 | 2.430 s | 7.406 | Not measured | 0 |
| Comparable ASGI smoke after changes | 18 | 2.621 s | 6.869 | Not measured | 0 |
| Final HTTP direct-transfer smoke, configured 10-TPS target | 48 | 5.272 s | 9.105 | 27.315 | 0 / 144 |
| HTTP mixed smoke | 40 | 7.164 s | 5.583 | 20.938 | 0 / 150 |

| Latency scope | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| ASGI baseline, grant + payment | 250.36 ms | 354.93 ms | 354.93 ms |
| ASGI after, grant + payment | 260.12 ms | 364.86 ms | 364.86 ms |
| Final HTTP direct, successful grant + payment intent | 873.32 ms | 1,789.00 ms | 2,019.27 ms |
| Final HTTP direct, all HTTP steps including replays | 370 ms | 1,000 ms | 1,100 ms |
| HTTP mixed, successful grant + payment intent | 280.99 ms | 442.36 ms | 749.68 ms |
| HTTP mixed, all HTTP steps | 120 ms | 280 ms | 480 ms |

ASGI percentiles use the lower order statistic `floor((n-1)*p)` with only 18 samples; HTTP intent percentiles use nearest rank and HTTP step percentiles use Locust's approximation. These small samples cannot establish stable tail latency. The ASGI after result is about 7% lower throughput in one run, not a statistically established regression or improvement. The measured index query improvement is not an end-to-end payment speedup.

The final direct run separately returned **48 idempotent replays**, all excluded from 48 new commits, and includes the final post-lock lease revalidation. An earlier direct smoke measured 7.193 TPS; variation between these tiny runs is not evidence that a code change increased capacity. The mixed run preceded that final lease hardening and exercised authentication, accounts, lookup, direct transfers, self-transfers, request payments, split contributions, recharge, bills and history; per-route counts are in the JSON artifact. The `target_financial_tps` field applies to financial mode pacing only; mixed mode uses deterministic seeded choices and think times. Configured CLI durations were six/eight seconds; the reported measurement windows use Locust test-start/test-stop boundaries, not an assumed duration.

Outbox backlog at final direct-run sampling was 18 pending and five processing, then all **84** events processed (48 transfers plus 36 funding events). Mixed ended with three pending, then all **76** processed. Neither had dead letters or failed financial records; ledger reconciliation passed at shutdown. Sampled lock waiters were zero and database deadlock counters zero; this does not prove absence of brief contention. Mixed resource sampling observed at most seven connections, container CPU samples from 0.15% to 46.66%, and memory samples approximately 799–825 MiB. Final direct sampling observed at most 13 connections, CPU samples 0.31–57.11%, and approximately 895–928 MiB memory. These are sparse Docker container observations, not PostgreSQL query CPU profiling or measured peaks.

Every benchmark used new schemas in isolated test databases. Development table hashes matched after shutdown. JSON artifacts are under [backend/benchmarks/results](../backend/benchmarks/results), including baseline/after, HTTP summaries, queue drain, resource samples, and full EXPLAIN plans.

## Query-plan experiment

An actor's 20,000 synthetic FAILED history records, ten recent, yielded a sequential scan at **4.319 ms** before `(actor_user_id,created_at)` and index-only scan at **0.101 ms** afterward. This justifies the additive index for owner/time predicates. It is a warm, synthetic count query, not representative financial load. The experiment commits its test inserts before index DDL to drain deferred triggers. It removes/rebuilds only the candidate index in its newly generated test schema; no development index or record is removed.

Other safe changes avoid rescanning daily history when a counter already exists, aggregate risk in SQL instead of loading ORM account graphs, and evaluate bill-list date once per page. No before/after capacity benefit is claimed for those individually. Existing account journal-sum triggers, PIN CPU, row serialization, WAL/index amplification and growing history remain bottlenecks.

## Reproducing safely

From `backend`, install optional benchmark tools (not required by the app):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmark.txt
$env:PAYFLOW_TEST_DATABASE = 'payflow_reliability_bench_tests'
.\.venv\Scripts\python.exe -B benchmarks/smoke.py --output benchmarks/results/local-asgi.json
.\.venv\Scripts\python.exe -B benchmarks/query_plans.py
```

The schema migration/fixture setup is outside measured timing. Schemas are retained; no reset/drop/truncate of financial data runs. The configured PostgreSQL role must be permitted to create the isolated database and schemas. Never configure `DATABASE_URL` itself to an existing benchmark/test database to evade the guard.

For HTTP, in terminal A set a random local fixture key and start the loopback server. Use the **same privately chosen key** in terminal B; the text below is a placeholder, not a secret to deploy:

```powershell
$env:PAYFLOW_BENCH_KEY = 'REPLACE_WITH_YOUR_RANDOM_32_PLUS_CHARACTER_TEST_KEY'
$env:PAYFLOW_TEST_DATABASE = 'payflow_reliability_bench_tests'
.\.venv\Scripts\python.exe -B benchmarks/isolated_server.py --worker
```

Terminal B, also from `backend`:

```powershell
$env:PAYFLOW_BENCH_KEY = 'REPLACE_WITH_THE_SAME_PRIVATE_TEST_KEY'
.\.venv\Scripts\python.exe -B benchmarks/run_smoke.py --mode mixed --duration 8 --users 12
```

Stop the fixture gracefully so worker drain/reconciliation/snapshots run:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:18017/__benchmark/stop' -Headers @{ 'X-Benchmark-Key' = $env:PAYFLOW_BENCH_KEY }
```

Each comparison needs a **fresh fixture**. A stopped schema remains retained. Fixture-only authenticated bootstrap/report/stop routes exist only in this script, bind to loopback port 18017 and are never mounted in production `main.py`. Bootstrap issues only synthetic credentials; do not log responses or publish its key. Locust rejects other hosts; this is not a general public-deployment load tool.

For the direct replay scenario, use a fresh fixture and set `$env:BENCH_REPLAY='1'` before `run_smoke.py --mode financial --duration 6 --users 12`. Clear it afterward for ordinary mixed tests. The runner bounds duration/users; the workload also stops at 20 seconds by default. Intent latency storage is capped at 10,000 samples. This is deliberate smoke tooling, not an uncapped distributed benchmark rig.

After explicit approval for a larger environment, Locust can be configured with `BENCH_TARGET_TPS` (e.g. 10/50/100), `BENCH_USERS` (fixture cap 100), `BENCH_HOT=1`, different actor counts and runtime. `BENCH_ALLOW_SUSTAINED=1` removes the default 20-second stop and must not be used without a reviewed resource budget. Pacing is closed-loop and can under-offer when saturated; offered target is not achieved TPS. Keep PIN/risk/daily policies enabled and use enough actors rather than silently bypassing them. Sustained high-rate workloads need a reviewed larger fixture/data lifecycle and an independent generator.

**50/100 TPS and all higher milestones were not run.** The 10-TPS-target smoke did not achieve 10 new committed TPS, so escalation would not substantiate capacity. No million-transaction stress, external deployment load, distributed/failover benchmark, sustained hot-settlement capacity test or storage/WAL profile was performed.

## Verification scope and next steps

The executed PostgreSQL suite passed **212 tests**, including 23 new reliability cases; React passed **185 tests**, including response interruption/timeout/cancellation cases. TypeScript, ESLint, production build and Alembic consistency passed. Failure boundaries are injected/simulated, not physical power loss. Current browser outcomes and development migration checks are recorded in the delivery report.

The four Chromium regression harnesses passed with real PIN-backed payments, PNG QR upload, request/split/self/recharge/bill flows, receipts and lost-response recovery at five responsive widths. Migration `0009_reliability_outbox` was applied after verification: whole-record hashes matched for every pre-existing development table, including security state. Existing counts at that check were 2 users, 2 accounts, 4 payments, 8 journal entries, 7 audit events, 1 configured PIN and 1 authorization. Both new event tables were empty; no historical posting was backfilled or modified. Readiness/liveness returned 200, metrics was disabled (404), and every reconciliation mismatch list was empty. No hardware-camera, physical-device, screen-reader, multi-region or power-loss verification is claimed.

Next evidence should isolate Argon2 CPU from database posting time, profile query/trigger/WAL costs with realistic accumulated history, measure account skew, and define latency/error/recovery SLOs. Establish controlled repeated runs and arrival-rate load with coordinated-omission analysis before provisioning for [16,667 TPS sustained / 50,000 TPS peak](scaling-to-1m-tpm.md).
