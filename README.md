# PayFlow

**A full-stack digital payments simulator built around secure transaction authorization, double-entry accounting, and reliable payment processing.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-configured-2088FF?logo=githubactions&logoColor=white)

PayFlow pairs a responsive React interface with a PostgreSQL-backed payment engine. Its engineering focus is keeping balances, journal entries, receipts, security decisions, and related business records consistent—even when requests race, fail, or lose their responses.

> **Fictional funds only.** This independent educational and portfolio project does not move real money, activate mobile services, or settle actual bills. It has no connection to banks, UPI/NPCI/BBPS networks, or payment gateways, and is not affiliated with Google Pay, Google, or UPI providers.

**Project status:** local Docker deployment verified; cloud deployment prepared only. GitHub Actions is configured and locally validated, but has not yet executed on GitHub. See the [dated verification record](docs/verification.md).

## Contents

- [Overview](#project-overview) · [Features](#key-features) · [Stack](#technology-stack)
- [Architecture](#system-architecture) · [Payment processing](#how-a-payment-works) · [Database](#database-design)
- [Security](#security-architecture) · [Reliability](#reliability-and-distributed-systems) · [Performance](#performance-and-scalability)
- [Structure](#project-structure) · [Getting started](#getting-started) · [Environment](#environment-variables)
- [Testing](#testing) · [CI/CD](#cicd) · [Deployment](#deployment) · [Operations and recovery](#observability-and-recovery)
- [API](#api-overview) · [Demo workflow](#demo-workflow) · [Screenshots](#screenshots)
- [Design decisions](#design-decisions) · [Limitations](#limitations) · [Future work](#future-improvements) · [License](#license-and-acknowledgments)

## Project overview

PayFlow explores the systems behind a payment product: relational modeling, authenticated ownership, exact monetary arithmetic, concurrent spending, durable retries, and recovery. Recipient verification, explicit review, payment PIN approval, and receipts make those mechanisms visible through one application.

A shared service handles person-to-person transfers, self-transfers, money requests, split contributions, and fictional purchases. PostgreSQL coordinates each financial posting; a separate worker handles non-financial activity notifications after commit. Tests exercise successful workflows and failures at transaction boundaries.

The project demonstrates payment correctness and operational tradeoffs for educational and portfolio use. It is not a production financial service or a claim of regulatory compliance.

## Key features

| Area | Implemented capabilities |
| --- | --- |
| **Payments and banking** | Up to four fictional bank accounts/user; primary source selection; account-scoped PayFlow identifiers; exact INR balances; direct and self-transfers; receipts and cursor-paginated history |
| **QR payments** | Generate/download QR images, copy an ID, supported-camera scanning or image upload, backend recipient verification, explicit confirmation |
| **Social payments** | Private saved contacts, favorites, recent counterparties, incoming/outgoing requests, seven-day expiry, pay/decline/cancel, linked receipts |
| **Expense splitting** | Equal/custom shares, optional creator share, up to ten participants including creator, contribution requests, progress, renewal, settlement tracking |
| **Recharge and bills** | Fictional operators/plans; electricity, water, gas and broadband bills; saved billers; server-authoritative prices; purchase history |
| **Security** | Registration/login, Argon2id passwords/PINs, JWT authentication, bound payment authorizations, lockout, database-backed rate limits, UTC limits, risk rules, private audit activity |
| **Reliability** | Atomic double-entry posting, durable idempotency, same-key recovery, transactional outbox, leased workers, idempotent notifications, reconciliation |
| **Engineering and operations** | PostgreSQL/React/browser tests, locked dependencies, Docker, CI configuration, health probes, structured logs, protected metrics, backup/restore tools |

Important product semantics:

- Demo funding adds **₹1,000/action**, with **three successful actions per user across all accounts**. Adding an account does not reset the allowance.
- Each generated **@payflow ID belongs to an account**. Primary changes affect the default source, not existing receiving IDs or QR codes.
- Contacts are a personal address book, not mutual friendships. Lookup requires an exact ID; there is no public directory.
- Requests and splits create obligations, not automatic debits. Splits record externally paid expenses, not verified PayFlow purchases. Both screens settle the same underlying contribution request.
- Creator shares generate no self-payment. Equal allocation uses integer paise: ₹100 across three participants becomes ₹33.34, ₹33.33, ₹33.33. Custom shares must sum exactly.
- Services are fictional. A user/biller/reference has a stable monthly bill; repeated lookup preserves identity, amount, and paid status.

## Technology stack

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Interface | React 19, TypeScript 5, Vite 8 | Typed components/clients and builds |
| Styling | CSS custom properties, CSS, SVG icons | Responsive layouts, design tokens, reduced motion |
| Backend | Python 3.11, FastAPI, Pydantic 2, Uvicorn | API, validation, dependency injection, public schemas |
| Persistence | PostgreSQL 16, SQLAlchemy, psycopg 3 | Transactions, relational data, locks, constraints |
| Migrations | Alembic | Versioned upgrades and schema comparison |
| Credentials | pwdlib/Argon2id, PyJWT | Password/PIN hashing and restricted HS256 tokens |
| QR processing | qrcode, @zxing/browser, @zxing/library | Browser generation and camera/image decoding |
| Backend tests | unittest, FastAPI TestClient/httpx | PostgreSQL integration, authorization, concurrency, failures |
| Frontend tests | Vitest, React Testing Library, jsdom | Component/client behavior |
| Browser QA | Playwright Chromium | Isolated workflows and responsive checks |
| Delivery/tooling | Docker, Docker Compose, GitHub Actions, Bandit, Gitleaks | Reproducible services and validation |
| Optional benchmarks | Locust and repository harnesses | Bounded isolated financial workloads |

Dependency sources: [Python runtime](backend/requirements.txt), [Python tests](backend/requirements-dev.txt), [frontend package](frontend/package.json). Reproducible installs use Python hash locks and [package-lock.json](frontend/package-lock.json). Redis, Kafka, Kubernetes, and hosted monitoring stacks are not runtime dependencies.

## System architecture

```mermaid
flowchart TD
    UI["React frontend"] --> Client["Typed fetch clients / Bearer JWT"]
    Client --> API["FastAPI routes and Pydantic schemas"]
    API --> Auth["Authentication and object authorization"]
    Auth --> Features["Accounts, contacts, requests, splits, commerce"]
    Features --> Engine["Shared payment engine and security policy"]
    Features --> ORM["SQLAlchemy / psycopg"]
    Engine --> ORM
    ORM --> DB[("PostgreSQL: accounts, payments, ledger, idempotency, security, outbox")]
    Worker["Separate outbox worker"] -->|"Claim events / write notifications"| DB
    Reconcile["Read-only reconciliation CLI"] --> DB
```

- **Frontend:** presentation, state-based navigation, review, memory-only JWTs, unresolved-payment recovery. It never writes balances.
- **API/services:** authenticate callers, enforce ownership/lifecycles, validate schemas, and delegate financial effects to `execute_payment` in [payments.py](backend/payments.py).
- **Database:** authoritative financial/security state. SQLAlchemy sessions and explicit SQL run through psycopg; PostgreSQL locks, uniqueness, checks, and deferred triggers enforce invariants.
- **Worker:** consumes committed events and creates participant-scoped notifications. It does not authorize payments or change balances.

This is one modular backend with a separate worker, not independently deployed business microservices. Alembic manages schema changes; API/worker startup does not create tables or run migrations.

## How a payment works

After review, React exchanges the payment PIN for a short-lived grant bound to the exact intent. It submits the existing payment endpoint with Bearer authentication, an `Idempotency-Key`, and `Payment-Authorization`.

1. Validate caller/payload; reserve a user-scoped key and compare its fingerprint. A matching completed request returns the stored result.
2. Resolve authoritative recipient, request, bill, or plan terms. Lock applicable lifecycle records before accounts.
3. Acquire the sender's configuration lock, resolve an owned source, and lock bank accounts in ascending ID order with `SELECT FOR UPDATE`.
4. Under those locks, revalidate ownership, state/expiry, funds, bound grant, UTC counters, and risk rules.
5. For success, update cached balances and write the payment plus matching signed debit/credit entries. Consume the grant, increment usage, update linked obligation/fulfillment state, and record security decisions.
6. Insert a minimal outbox event and store the idempotency response in the same transaction. Validate deferred accounting constraints and commit once.
7. Return the confirmed receipt. Activity may arrive later without affecting payment status.

The transaction is already active during reservation/validation; debit and credit are not separate commits. Deadlock, timeout, and uncertain-commit paths direct callers to recover with the original key.

```mermaid
sequenceDiagram
    actor User
    participant UI as React
    participant API as FastAPI
    participant Engine as Payment service
    participant DB as PostgreSQL
    participant Worker as Outbox worker
    User->>UI: Review, explicitly confirm, enter PIN
    UI->>API: Request authorization for exact terms
    API-->>UI: Short-lived one-payment grant
    UI->>API: Payload + JWT + idempotency key + grant
    API->>Engine: Validated caller and request
    Engine->>DB: Reserve key and compare fingerprint
    alt Completed matching key
        DB-->>Engine: Stored status and response
        Engine-->>API: Original result, no new posting
    else New intent
        Engine->>DB: Lock lifecycle records and ordered accounts
        Engine->>DB: Validate grant, limits, risk, funds
        Engine->>DB: Write balances, ledger, payment, state, audit, outbox, result
        Engine->>DB: Validate constraints and COMMIT
        DB-->>Engine: Commit confirmed
        Engine-->>API: Receipt
    end
    API-->>UI: Committed result
    Worker->>DB: Claim committed event with fenced lease
    Worker->>DB: Insert deduplicated participant notifications
```

| Flow | Atomic financial/business effect |
| --- | --- |
| Direct / QR | Debit source, credit exact UPI account; QR uses the transfer endpoint |
| Request / split contribution | Pay pinned requester account, mark the same obligation paid, settle split when owed contributions are paid |
| Self-transfer | Move funds between different owned accounts, conserving combined funds |
| Demo funding | Debit private demo-funding ledger, credit owned account under the user-wide allowance |
| Mobile recharge | Debit source, credit settlement-recharge, record completed fictional fulfillment |
| Utility bill | Lock owned bill, debit stored amount, credit settlement-bills, mark paid |

Transactions prevent partial posting. Ordered locks prevent concurrent overspending and reduce deadlock risk. Idempotency recovers lost responses without another debit. Double-entry records explain every movement. These are single-database guarantees, not globally distributed exactly-once delivery.

## Database design

| Entities | Purpose |
| --- | --- |
| `users`, `bank_accounts` | Credentials/profiles, owned accounts, unique numbers/IDs, primary selection, exact balances |
| `payments`, `ledger_accounts`, `ledger_entries` | Immutable financial snapshots and signed journal; internal ledgers have no login/public bank account |
| `payment_requests` | Engine idempotency: user/key, fingerprint, stored HTTP result, payment link |
| `contacts`, `money_requests`, `money_request_destinations` | Address book, authorized obligations, pinned receiving accounts |
| `expense_splits`, `expense_split_participants`, `split_request_links` | Expense shares, current requests, renewal history |
| `demo_operators`, `demo_recharge_plans`, `mobile_recharges` | Fictional catalogs, completed purchases, masked numbers, unique payment links |
| `demo_billers`, `utility_bills`, `saved_billers` | Providers, owned monthly bills, saved synthetic references |
| `payment_pin_credentials`, `payment_authorizations` | PIN hashes/version/lockout, digest-only grants |
| `payment_limit_counters`, `fraud_risk_decisions`, `security_audit_events` | UTC usage, explainable decisions, private activity |
| `recipient_lookup_limits`, `request_creation_limits`, `security_rate_windows` | Shared database throttles |
| `outbox_events`, `activity_notifications` | Leases/delivery state and unique event/user notifications |

**Naming distinction:** `payment_requests` means engine idempotency; `money_requests` means requests between people.

```mermaid
erDiagram
    users ||--o{ bank_accounts : owns
    users ||--o{ payment_requests : scopes_keys
    bank_accounts ||--|| ledger_accounts : backs
    bank_accounts ||--o{ payments : participates_in
    payments ||--o{ ledger_entries : posts
    ledger_accounts ||--o{ ledger_entries : records
    users ||--o{ money_requests : requests_or_pays
    users ||--o{ expense_splits : creates
    expense_splits ||--|{ expense_split_participants : allocates
    expense_split_participants ||--o{ split_request_links : tracks
    money_requests ||--o| split_request_links : links
    payments ||--o| mobile_recharges : fulfills
    payments o|--o| utility_bills : settles
    payments ||--o| outbox_events : emits
    outbox_events ||--o{ activity_notifications : delivers
```

This simplified domain view omits role-specific payment foreign keys, catalogs, security relationships, and the nullable bank link of internal ledgers.

Money uses PostgreSQL **`NUMERIC(18,2)`**, Python **`Decimal`**, and decimal-string JSON. The immutable journal is the accounting source of truth; cached bank balances are reconciled against it. Constraints/triggers enforce positive payments, nonnegative bank balances, balanced successful postings, primary-account rules, immutable financial records, and request/split/fulfillment linkage. Financial foreign keys restrict deletion.

Splits are OPEN, SETTLED, or CANCELLED; cancellation is refused after contributions have been paid. Bills store UNPAID/PAID, with overdue derived for display. Recharges persist synchronous completed fulfillment; financial failures appear in main history.

The [migration chain](backend/migrations/versions) has head **0009_reliability_outbox**. Normal operation uses migrations, not `Base.metadata.create_all`; destructive downgrades are intentionally refused.

## Security architecture

| Control | Implemented behavior |
| --- | --- |
| Passwords | Salted Argon2id via pwdlib; hashes excluded from public schemas; dummy verification for unknown logins |
| Tokens | HS256-only JWTs; expiry, issuer, audience, required claims/purpose and user lookup; 15-minute default lifetime |
| Ownership | Backend source ownership, request participant/payer checks, split visibility/management, owned bills/contacts |
| Payment PIN | Six digits with weak-pattern rejection; password-authenticated first setup; existing-PIN change; five failures lock for 15 minutes by default |
| Payment grants | Digest-only, default 120-second expiry; bound user/source/destination/operation/amount/fingerprint/key/PIN version; atomic consumption |
| Limits | Default ₹100,000/payment, ₹200,000 and 50 outgoing postings/UTC day, 20 money/contribution requests/day; locked counters |
| Risk rules | Amount, velocity, recipient diversity, insufficient-funds, service, PIN-failure and new-contact signals; HIGH blocks with an explanation |
| Abuse controls | Database-backed login/registration/PIN/payment throttles, exact lookup, request caps, HMAC-digested subjects, safe errors |
| Configuration | Ignored private environments, exact CORS, demo HTTPS/DB TLS validation, headers, protected metrics, separate local runtime/worker roles |

Self-transfers count toward outgoing limits. Demo funding is a central PIN/daily-spending exemption under its own allowance. Failures and replays do not consume spending allowance. Days reset at **00:00 UTC**; risk can block below nominal limits.

Allowed decisions audit in the posting transaction; blocked decisions persist after rollback without financial changes. Metadata excludes passwords, PINs, raw JWTs/grants, and full customer references. Users see only their own recent events; retention cleanup requires an explicit operator action.

JWTs, PINs and raw grants are not persisted in browser storage. Logout clears the frontend session but **does not revoke an issued JWT**. No refresh-token flow, independent MFA, verified-email/password recovery, or forgotten-PIN reset exists. A PIN is not claimed as independent MFA. Registration still reports duplicate emails. See the [security architecture and threat model](docs/SECURITY.md).

## Reliability and distributed systems

- **Durable retries:** matching key/payload recover stored status/body; changed terms under that key return 409. Database uniqueness coordinates duplicates across API processes.
- **Unknown outcomes:** transaction errors return 503 with same-key guidance. React saves unresolved intent metadata in account-scoped `sessionStorage`, excluding credentials. Committed results replay without a new grant; an uncommitted attempt can obtain a fresh grant under the same key.
- **Lifecycle coordination:** applicable split/request/bill records lock before accounts. Pay/cancel/decline/expiry races coordinate there. Paid obligations recover receipts instead of posting again.
- **Transactional outbox:** every new successful payment inserts a minimal `payment.posted.v1` event in its posting transaction. No broker publish precedes commit.
- **At-least-once processing:** bounded `SKIP LOCKED` claims, fenced expiring leases, exponential backoff, bounded retries, and `DEAD` state support recovery.
- **Idempotent consumer:** unique event/user notifications make redelivery safe after a crash between delivery and acknowledgment. Notification delays do not change payment success.
- **Reconciliation:** read-only checks compare balances, journal totals, posting structure, and business links. They report mismatches without automatically repairing money.

PostgreSQL remains authoritative. Workers cannot independently debit accounts or alter committed ledgers. Critical grant/idempotency/limit/rate state is shared in the database; every process still needs a connection/memory budget. This does not establish high availability or unlimited capacity. See [reliability and operations](docs/reliability.md).

## Performance and scalability

Current measures include owner/time history indexes, bounded pages, configurable pools, lock/statement timeouts, ordered locks, SQL risk aggregation, and separate notifications. Account contention, journal-check costs, Argon2 CPU, and write amplification remain measurement targets.

[Artifacts](backend/benchmarks/results) and the [performance report](docs/performance.md) document these **bounded local smoke results from 5 November 2026**:

| Workload | New commits | Measurement window | Committed TPS | Intent p95 / p99 |
| --- | ---: | ---: | ---: | ---: |
| HTTP direct, configured 10-TPS target | 48 | 5.272 s | 9.105 | 1,789.00 / 2,019.27 ms |
| HTTP mixed workflows | 40 | 7.164 s | 5.583 | 442.36 / 749.68 ms |

Intent latency includes PIN grant plus payment. Direct testing separately returned 48 replays, excluded from new commits. Mixed testing preceded final worker-lease hardening. Brief closed-loop runs shared the API/generator host; small-sample percentiles do not establish stable tail latency.

Environment: Windows, Ryzen 7 6800HS (8 cores/16 logical processors), approximately 13.7 GiB usable host RAM; PostgreSQL 16.11 in Docker, Python 3.11, one API process and one worker, 12 synthetic users/24 accounts with security enabled. The report details fixture pool differences, resource samples, and reproduction. **50/100 TPS and higher milestones were not run.** No sustained capacity or production SLO is claimed.

## Project structure

```text
PayFlow/
├── backend/
│   ├── main.py, config.py, database.py, security.py
│   ├── accounts.py, payments.py, payment_models.py
│   ├── social.py, splits.py, split_service.py
│   ├── commerce.py, commerce_service.py, commerce_seed.py
│   ├── pin_security.py, payment_policy.py, security_events.py
│   ├── outbox.py, outbox_models.py, outbox_worker.py
│   ├── operations.py, observability.py, reconcile.py
│   ├── migrate.py, migration_lock.py, serve.py, worker_health.py
│   ├── migrations/versions/
│   ├── tests/
│   ├── benchmarks/results/
│   ├── requirements*.lock, Dockerfile, .env.example
│   └── models.py, *_models.py, schemas.py, *_schemas.py
├── frontend/
│   ├── src/                    # Feature panels, clients, styles, tests
│   ├── qa/                     # Managed browser runner and isolated fixtures
│   ├── public/
│   ├── package.json, package-lock.json
│   └── Dockerfile, nginx.conf, vercel.json, .env.example
├── docs/                       # Architecture, testing, deployment and operations
├── tools/                      # Guarded CI, smoke and backup utilities
├── deploy/postgres-init.sh
├── .github/workflows/ci.yml
├── docker-compose.yml, .env.compose.example, render.yaml
└── README.md
```

## Getting started

### Prerequisites

- Git and Docker Desktop with Linux containers and Docker Compose.
- Python **3.11** for backend development/local tooling.
- Node.js **22.12+** and npm; CI/Docker use Node 22. Vite also permits Node 20.19+.
- PostgreSQL **16**, supplied by Compose or an existing local server.
- Windows PowerShell for these commands; virtual-environment activation is not required.

```powershell
git clone https://github.com/Harshita2011/PayFlow.git
Set-Location PayFlow
```

For the existing checkout, use `Set-Location D:\PayFLow` instead.

### Docker quick start

From the repository root:

```powershell
# First setup only; skip when .env.compose already exists.
python tools/init_compose.py
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose up -d --build --wait
```

Open **[http://localhost:18080](http://localhost:18080)**. The initializer creates random secrets without printing them, using keys in [.env.compose.example](.env.compose.example), and refuses overwrite. Never commit the private file or regenerate passwords for an existing volume without role rotation. Review Windows file permissions.

Project payflow-demo runs postgres, one-shot migrate, api, worker, and frontend. Data persists in **payflow_demo_pgdata**. Only Nginx is published to loopback; /api proxies to the private backend. The original payflow-postgres-5436 container remains separate. Local Compose uses development mode on its private network; hosted demo mode requires HTTPS and DB TLS.

```powershell
docker compose --env-file .env.compose ps -a
docker compose --env-file .env.compose stop
```

Stopping retains data. Do not remove volumes. Fully interpolated configuration contains credentials; use config --quiet rather than logging it.

### Manual development setup

**1. Start PostgreSQL.** Reuse the existing container when present:

```powershell
docker start payflow-postgres-5436
```

For a **new installation only**, create persistent PostgreSQL with a chosen password. Do not run against an existing container/name:

```powershell
$demoDbSecret = Read-Host 'Choose a local PostgreSQL password' -AsSecureString
$env:POSTGRES_PASSWORD = [System.Net.NetworkCredential]::new('', $demoDbSecret).Password
docker run --name payflow-postgres-5436 --detach `
  --publish 127.0.0.1:5436:5432 `
  --env POSTGRES_USER=payflow --env POSTGRES_DB=payflow --env POSTGRES_PASSWORD `
  --mount type=volume,source=payflow_pgdata,target=/var/lib/postgresql/data `
  postgres:16
Remove-Item Env:POSTGRES_PASSWORD
```

**2. Install backend dependencies.** From the repository root:

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build.lock -r requirements-dev.lock
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `backend/.env` with your PostgreSQL URL and a random `JWT_SECRET_KEY`; preserve existing settings. For a new environment, fill only the example's blank key slot without printing it:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import secrets; p=Path('.env'); s=p.read_text(encoding='utf-8'); p.write_text(s.replace('JWT_SECRET_KEY=\n','JWT_SECRET_KEY='+secrets.token_urlsafe(48)+'\n',1),encoding='utf-8')"
```

**3. Inspect and apply migrations deliberately.** Once PostgreSQL is ready, from `backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic current
# Use base ONLY for a verified new empty database.
.\.venv\Scripts\python.exe -m migrate --apply --expected-current base
.\.venv\Scripts\python.exe -m migrate
```

For an existing database below head, back it up and replace `base` with its verified current revision. Unexpected revisions are refused; already-current databases are not upgraded again. Migrations seed fictional catalogs without replacing records. See [controlled migrations](docs/deployment.md#controlled-migrations-and-rollback).

**4. Start API and worker in separate terminals**, each from `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001 --no-proxy-headers --no-access-log
```

```powershell
.\.venv\Scripts\python.exe -m outbox_worker
```

**5. Start React**, from the repository root in another terminal:

```powershell
Set-Location frontend
npm ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm run dev -- --port 5173 --strictPort
```

Development UI: [localhost:5173](http://localhost:5173). API docs: [localhost:8001/docs](http://localhost:8001/docs); schema: [localhost:8001/openapi.json](http://localhost:8001/openapi.json). Docs default off in hosted demo mode and are disabled in Compose.

Ports are conventions: update PostgreSQL mapping/URL, API port/VITE_API_BASE_URL, and exact CORS_ALLOWED_ORIGINS together. No source edit is needed for CORS. The server ignores forwarded headers; review trusted ingress before public operation.

## Environment variables

Backend configuration loads its adjacent .env; process variables take precedence. VITE_ values are public build configuration. Restart backend services after changes; rebuild for frontend changes.

| Variable | Scope / required | Purpose / safe example |
| --- | --- | --- |
| `DATABASE_URL` | Backend/worker; yes | postgresql+psycopg://YOUR_DB_USER:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5436/payflow; demo requires sslmode=require or certificate verification |
| `JWT_SECRET_KEY` | Backend/worker; yes | Random 32+ byte secret; API instances share a stable key, restricted workers use an independent configuration key |
| `PAYFLOW_ENV` | Backend; optional | development default, test, demo; demo validates HTTPS origins and DB TLS |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Backend; optional | 15 default, supported 1–60 |
| `CORS_ALLOWED_ORIGINS` | Backend; optional | Exact origins, e.g. http://localhost:5173,http://127.0.0.1:5173; no wildcards |
| `PAYFLOW_EXPOSE_DOCS`, `LOG_LEVEL` | Backend; optional | Docs 1 in dev/test, 0 in demo by default; log INFO, WARNING, ERROR |
| `VITE_API_BASE_URL` | Frontend; optional locally | Default http://localhost:8001; Compose /api; hosted builds require approved external HTTPS URL |
| `PORT`, `WEB_CONCURRENCY`, `PAYFLOW_MAX_CONCURRENCY` | Container entry point; optional | Defaults 8001, 1, 16; budget memory/connections per process |
| `PAYMENT_SINGLE_LIMIT`, `PAYMENT_DAILY_LIMIT`, `PAYMENT_DAILY_COUNT` | Backend; optional | Defaults 100000.00, 200000.00, 50 |
| `REQUEST_DAILY_COUNT` | Backend; optional | Default 20 requests/contributions per UTC day |
| `PIN_MAX_ATTEMPTS`, `PIN_LOCK_SECONDS`, `PAYMENT_AUTH_SECONDS` | Backend; optional | Defaults 5, 900, 120 |
| `LOGIN_IP_LIMIT`, `LOGIN_IDENTITY_LIMIT`, `REGISTER_IP_LIMIT` | Backend; optional | Defaults 30/minute, 10/15 minutes, 10/hour respectively |
| `PIN_RATE_LIMIT`, `PAYMENT_RATE_LIMIT` | Backend; optional | Defaults 10 PIN calls and 30 new submissions/user/minute |
| `RISK_*`, `SECURITY_RETENTION_DAYS` | Backend; optional | Rules in backend example/security guide; retention 90, no scheduled purge |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | Each process; optional | Defaults 5 + 5; Compose 3 + 2 |
| `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS` | Backend/worker; optional | Defaults 5, 1800 |
| `DB_CONNECT_TIMEOUT_SECONDS`, `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS` | Backend/worker; optional | Defaults 5, 15000, 5000 |
| `OUTBOX_BATCH_SIZE`, `OUTBOX_LEASE_SECONDS`, `OUTBOX_MAX_ATTEMPTS`, `OUTBOX_POLL_SECONDS` | Worker; optional | Defaults 10, 30, 5, 1 |
| `WORKER_HEARTBEAT_FILE` | Worker; optional | Compose /tmp/payflow-worker-heartbeat local probe |
| `PAYFLOW_OPS_TOKEN` | Operators; optional | Empty disables metrics; otherwise independent random 32+ byte token |
| `PAYFLOW_DEMO_MOBILE_PREFIXES` | Backend; optional | Default 6789, allowed first digits of ten-digit demo numbers |
| `PAYFLOW_TEST_DATABASE`, `PAYFLOW_TEST_DATABASE_URL` | Tests only; optional | Guarded isolated payflow_*_tests name and optional dedicated credentials |
| `REGISTER_TEST_POSTGRES` | Tests only | Managed launcher sets 1 to include PostgreSQL suites |

Templates: [backend](backend/.env.example), [frontend](frontend/.env.example), [tests](backend/.env.test.example), [Compose](.env.compose.example). Compose's role passwords, WORKER_CONFIG_KEY, HTTP port and expected revision are documented in its template. Never put secrets in frontend values, images, screenshots, logs, or source control.

## Testing

### Commands

From the repository root, with backend dependencies and PostgreSQL available:

```powershell
.\backend\.venv\Scripts\python.exe tools/run_backend_tests.py
```

The launcher selects test mode, an independent signing key, and default payflow_ci_local_tests. Fixtures enforce a separate target and fresh retained schemas/rollback transactions. Automatic local DB creation needs CREATEDB; alternatively provision a dedicated test database and export matching PAYFLOW_TEST_DATABASE/PAYFLOW_TEST_DATABASE_URL. Remote targets require an explicit isolated URL; demo mode is refused. See [test isolation](docs/testing.md).

Frontend and browser checks:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
npm run lint
npx playwright install chromium
npm run test:e2e
```

The build checks TypeScript before Vite. E2E starts owned services on **5180/18016**, uses isolated schemas and real workers, checks reconciliation/data fingerprints, and shuts down its services. It does not target development ports 5173/8001. Five scenarios cover principal flows, responsive widths, security, and lost-response recovery. Security-specific fixtures use documented test-only thresholds.

From the repository root with the separate Compose stack running:

```powershell
python tools/deployment_smoke.py
docker compose --env-file .env.compose exec api python -m reconcile
```

Smoke creates synthetic records only after verifying its isolated target; it cannot target public hosting. For manual-development schema/ledger checks without upgrades, run `python -m migrate` and `python -m reconcile` through the backend virtual environment from backend.

### Latest recorded local verification

These are **reported executions dated 6 November 2026**, corroborated by [verification.md](docs/verification.md) and available local logs—not permanent live status or tests rerun by a README edit.

| Check | Recorded result |
| --- | --- |
| PostgreSQL backend suite | **225 passed**, no failures/skips |
| React suite | **190 passed**, 14 files |
| Managed Chromium scenarios | **5 passed**, including workers, reconciliation and development-data checks |
| TypeScript / build / ESLint | Passed |
| Docker images / health / built UI smoke | Passed locally |
| Alembic revision and metadata | 0009_reliability_outbox, consistency passed |
| Ledger and restored-data reconciliation | Passed |
| Isolated backup/restore | Checksum and whole-table comparison passed |
| Dependency audits / source security checks | Passed at execution within the verification report's scope |

Physical cameras, cloud disaster recovery, and GitHub-hosted execution are not established by these results.

## CI/CD

[Validate PayFlow](.github/workflows/ci.yml) triggers on pull requests, selected branch pushes (main, master, codex/**), and manual dispatch.

| Job | Validation |
| --- | --- |
| Backend | PostgreSQL, isolated credentials, migrations, full tests, schema/reconciliation and dependency checks |
| Frontend | npm ci, tests, TypeScript/build, ESLint |
| Security | Python/npm audits, Bandit, redacted Gitleaks, workflow/provider configuration checks |
| E2E | Isolated API/database/worker and Playwright; restricted failure artifacts |
| Containers | Image builds, readiness, synthetic smoke, isolated restore |

Actions use immutable SHAs and read-only permissions. Checkout credentials are not persisted; no deployment secrets/publishing steps are included. Gitleaks checks current Git-visible source, not full history. These checks are not penetration testing or container OS scanning.

**Configured does not mean remotely passed:** syntax/action pins were locally validated; no GitHub Actions run is claimed. Releases remain manual and require approval. No passing-CI or coverage badge is displayed.

## Deployment

**Local Docker is verified. Public deployment is prepared, not completed; no public URL exists.**

Prepared hosting uses a **Vercel static frontend**, **Render container API**, **separate Render worker**, and **persistent managed PostgreSQL**. [render.yaml](render.yaml) and [vercel.json](frontend/vercel.json) disable automatic deployment. Database creation, secrets, HTTPS origins, role grants, approved migrations, and release verification remain operator tasks.

Do not use ephemeral SQLite or expiring databases for retained records. Free-tier eligibility, sleeping services, regional availability, limits, and backup retention require provider review. The [deployment guide](docs/deployment.md) records dated hosting assumptions and covers approval gates, migration ordering, roles, and rollback. No hosting cost or capacity is guaranteed.

## Observability and recovery

| Tool | Use and access |
| --- | --- |
| `GET /health/live` | Process responsiveness without DB dependency |
| `GET /health/ready` | PostgreSQL/revision readiness and safe failure status |
| Structured logs | Correlation/request UUIDs, route templates, status/duration; no bodies, raw query strings, credentials |
| `GET /metrics` | Low-cardinality HTTP/payment/replay/pool/outbox/DB metrics; disabled unless configured, requires X-Ops-Token; restrict network exposure |
| Worker heartbeat | Local Compose probe; separately monitor queue age/dead letters |
| `python -m outbox_worker --inspect-dead` | Bounded read-only inspection without payload dumps |
| `python -m reconcile` | Read-only accounting/business checks, never automatic balance repair |

Per-process metrics need per-instance collection; a multi-worker port does not aggregate them. Budget combined API/worker pool maxima and leave DB/operator headroom.

Backup tooling uses custom-format pg_dump, checksums, a **new uniquely named restore database**, whole-table comparison and restored reconciliation. The recorded local exercise passed. Backups contain sensitive hashes/history even with fictional funds; keep them private and encrypt off-host copies. Recovery objectives are planning targets, not measured guarantees. Never restore over development/production automatically.

Runbooks: [verification](docs/verification.md), [testing](docs/testing.md), [backup/recovery](docs/backup-recovery.md), [deployment smoke](docs/deployment-smoke.md), [reliability](docs/reliability.md). Notification delay never justifies a replacement payment; recover the original intent/receipt first.

## API overview

Except registration/login and health probes, these user APIs require JWT authentication. Financial submissions require idempotency and, except controlled funding, a matching payment authorization.

| Area | Representative routes | Purpose |
| --- | --- | --- |
| Authentication | `POST /register`, `POST /login`, `GET /me` | Setup, access token, profile |
| Accounts | `GET/POST /accounts`, `GET /accounts/banks`, `PATCH /accounts/{id}/primary` | Owned accounts, demo catalog, primary |
| Payments | `POST /demo/fund`, `POST /payments/resolve`, `POST /payments/transfer`, `POST /payments/self-transfer` | Funding, lookup, shared engine |
| Receipts/history | `GET /payments/history`, `GET /payments/{id}` | Participant-authorized results |
| QR | Browser generation/decoding → resolve/transfer | No separate QR posting endpoint |
| Contacts | `GET/POST /contacts`, `GET /contacts/recent`, `DELETE /contacts/{id}`, `PATCH /contacts/{id}/favorite` | Address book/recent counterparties |
| Requests | `POST /payment-requests`, `GET /payment-requests/incoming`, `GET /payment-requests/outgoing`, `POST /payment-requests/{id}/pay` | Create/list/pay; matching decline/cancel actions |
| Splits | `GET/POST /splits`, `GET /splits/{id}`, `POST /splits/{id}/cancel`, `POST /splits/{id}/participants/{participant_id}/renew` | Expenses/progress/cancellation/renewal |
| Recharge | `GET /recharge/operators`, `GET /recharge/plans`, `POST /recharge`, `GET /recharge/history` | Fictional purchases/history |
| Bills | `GET /billers`, `POST /bills/lookup`, `GET /bills`, `POST /bills/{id}/pay`, `GET /bills/history` | Stable owned bills/settlement |
| Saved billers | `GET/POST /saved-billers`, `DELETE /saved-billers/{id}`, `POST /saved-billers/{id}/lookup` | Saved references/lookup |
| Security | `POST /security/pin`, `POST /security/pin/change`, `POST /security/payment-authorizations`, `GET /security/status`, `GET /security/events` | PIN/grants/settings/private audit |
| Activity | `GET /activity/notifications` | Worker-generated activity |

See [interactive docs](http://localhost:8001/docs) for schemas. QR content follows `payflow://pay?v=1&upi=<normalized-id>%40payflow`; no token, amount, balance, or account number is encoded. External/malformed/unsupported content is rejected and never opened as a URL.

## Demo workflow

Use two fictional users in separate browser profiles. Manual actions persist demo records; use managed QA for disposable tests.

1. **Register and configure security.** Set a payment PIN using the account password; create an account for each user.
2. **Fund and send.** Add funds within the allowance. Verify the other user's ID, review ₹125.50, explicitly confirm, and approve with the PIN.
3. **Check results.** Inspect both balances/history and receipt ID. Recover a lost response with the original key.
4. **Try QR.** Display/download a QR; scan/upload it, verify backend identity, confirm a new payment.
5. **Request and split.** Save a contact, create/pay or decline a request, record an external expense split, and pay linked contributions.
6. **Move owned funds.** Add a second account, confirm a self-transfer, verify combined funds are conserved.
7. **Use fictional services.** Select a plan/ten-digit demo number starting with 6–9 by default. Fetch a bill with DEMO000001, select a funded source, review, confirm.
8. **Inspect and reconcile.** Review service/main history and run reconciliation.

Keep amounts within funds. Prices are server-authoritative. Repeat recharge requires fresh review and number entry because completed records retain only masked numbers.

## Screenshots

No product screenshots are currently committed. Frontend images are UI assets, not documented screenshots; no broken placeholders are included.

Capture dashboard, transfer review, QR, split progress, service receipts and security settings with disposable identities. Exclude credentials, PINs, tokens, private references and session state. Local QA captures are ignored and are not published here.

## Design decisions

| Decision | Benefit and tradeoff |
| --- | --- |
| PostgreSQL financial authority | One transaction coordinates money, usage and lifecycle; capacity remains constrained by DB/account contention |
| Double-entry journal plus cache | Explains movements and provides fast reads; reconciliation/deferred checks add work |
| Decimal strings/integer paise | Exact storage/allocation; clients preserve string money |
| Durable scoped idempotency | Recovers outcomes across instances; callers retain original intent/key |
| Shared engine/obligations | Features reuse posting guarantees instead of balance shortcuts |
| Transactional outbox | Survives API crashes; at-least-once delivery needs deduplication/leases/monitoring |
| Account-scoped routing | Primary changes preserve IDs/QRs; users select the receiving identity |
| Simulated providers, gradual scaling | Safe accounting experiments; real settlement/cross-shard protocols remain outside the contract |

## Limitations

- No real money, banking/UPI/BBPS connectivity, mobile activation, utility settlement, refunds/reversals, recurring payments, or multi-currency support.
- No public deployment or verified remote CI yet. Dated local health checks do not guarantee an always-on service.
- No production security certification, JWT revocation, refresh tokens, MFA, verified-email/password recovery, or independent PIN recovery. PIN entropy remains limited despite hashing/lockout.
- Risk rules are demo heuristics, not guaranteed fraud prevention. Duplicate-email responses remain an enumeration limitation; proxy-shared IP budgets need ingress review.
- Recovery metadata is tab/session scoped. Clearing storage or switching devices loses UI context; inspect history before replacing an uncertain payment.
- Deliberate caps: four accounts, three funding actions/user, ten split participants, 100 generated bills, 20 saved billers/user. No automated funding reset or idempotency expiry.
- Synthetic references are text; unresolved recharge intents retain the original number for exact retry. Do not use real personal data.
- Physical-camera/device and screen-reader compatibility is incomplete; upload scanning and responsive Chromium scenarios are tested.
- Cloud failover/restore/cutover, RPO/RTO, image OS scanning, full Git-history secret scanning, and production load are unverified. Administrators can alter database protections.

## Future improvements

- Execute prepared CI on GitHub and release an approved public demo with managed backups/alerts.
- Establish repeated financial benchmarks with realistic history/skew, independent generators, and latency/error objectives.
- Improve monitoring, tracing, fraud analysis, recovery controls, accessibility, and device/browser coverage.
- Explore partitioning, settlement contention and account sharding after measurement. [Scaling toward 1 million transactions/minute](docs/scaling-to-1m-tpm.md) is **future design research, not achieved capacity**: approximately 16,667 TPS sustained / 50,000 TPS hypothetical peak. Cross-shard transfers require a specified/tested settlement/recovery protocol; they are not automatically atomic.

## License and acknowledgments

No `LICENSE` file is currently included; the repository does not declare an open-source license.

PayFlow is an independent educational and portfolio project inspired by modern digital payment interfaces. It is not affiliated with or endorsed by Google Pay, Google, NPCI, UPI providers, banks, telecom operators, or utility providers.
