# PayFlow

**A full-stack, Google Pay-inspired digital payments simulator built around transaction safety, double-entry accounting, and a responsive React interface.**

![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)

PayFlow demonstrates relational data modeling, authentication and authorization, atomic payments, idempotent retries, and concurrent balance updates through one application. Users manage fictional accounts, send simulated INR, share QR identities, request contributions, split expenses, and pay fictional service providers.

> **Simulation only.** All funds, bank accounts, recharge plans, and bills are fictional. PayFlow does not connect to real banks, UPI networks, NPCI, BBPS, telecom operators, or payment gateways. No real money moves and no real service is activated.

## Contents

- [Project overview](#project-overview)
- [Key features](#key-features)
- [Technology stack](#technology-stack)
- [System architecture](#system-architecture)
- [Payment processing architecture](#payment-processing-architecture)
- [Database design](#database-design)
- [Security and reliability](#security-and-reliability)
- [Reliable delivery and operations](#reliable-delivery-and-operations)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Environment variables](#environment-variables)
- [Running the application](#running-the-application)
- [Containers and deployment](#containers-and-deployment)
- [Testing and verification](#testing-and-verification)
- [API overview](#api-overview)
- [Demo workflow](#demo-workflow)
- [Screenshots](#screenshots)
- [Design decisions and tradeoffs](#design-decisions-and-tradeoffs)
- [Limitations](#limitations)
- [Future improvements](#future-improvements)
- [License and acknowledgments](#license-and-acknowledgments)

## Project overview

PayFlow is an educational and portfolio project exploring the engineering behind a payment application. Its central problem is keeping balances, payment records, ledger entries, and related business state consistent when requests overlap, fail, or lose their responses.

One payment service powers person-to-person transfers, self-transfers, money requests, split contributions, and fictional purchases. PostgreSQL enforces accounting and ownership invariants alongside application validation. A read-only reconciliation command checks whether stored balances and business records agree with the journal.

The interface exposes these systems through recipient verification, explicit confirmation, recoverable payment intents, receipts, and account-scoped history. It is a local simulator, not a production financial service.

## Key features

| Area | Implemented functionality |
| --- | --- |
| Authentication | Registration, Argon2id password hashing, throttled JWT Bearer login, protected profile, client-side logout, and session-expiry handling |
| Payment security | Separate six-digit PIN, password-authenticated setup, PIN change/temporary lockout, one-payment grants, UTC daily limits, explainable risk rules, and private security activity |
| Reliability | Atomic payment outbox, separately leased notification worker, crash/retry recovery, live/ready probes, structured correlation logs and opt-in metrics |
| Bank accounts and UPI IDs | Up to four fictional accounts per user, primary selection, generated account numbers and unique `@payflow` IDs, masked displays, and exact decimal balances |
| Payments | Exact-ID recipient lookup, owned source selection, incoming/outgoing transfers, self-transfers, receipts, cursor-paginated history, and retry recovery |
| Demo funding | ₹1,000 per action, limited to three successful funding actions per user across all their accounts |
| QR payments | QR generation, PNG download, UPI ID copying, supported-camera scanning, local image decoding, backend recipient verification, and explicit confirmation |
| Contacts and requests | Personal saved contacts, favorites, derived recent counterparties, incoming/outgoing requests, confirmed payment, decline/cancel actions, expiry, and receipts |
| Expense splitting | Equal/custom shares, optional creator share, up to ten participants including the creator, contribution requests, progress, renewal, settlement status, and receipts |
| Recharge and bills | Fictional operators/plans; electricity, water, gas, and broadband bills; saved billers; source selection; review, payment, and service history |
| Interface | Responsive sidebar/mobile navigation, focused feature screens, loading/empty/error states, keyboard-accessible controls, and reduced-motion styling |

Important product semantics:

- **UPI IDs belong to accounts.** Changing primary changes the default source, not the destination of an existing UPI ID or QR code.
- **Contacts are a private address book**, not mutual friendships. Finding users requires an exact UPI ID; there is no public directory.
- **Requests are obligations, not debits.** They expire after seven days; only an explicitly confirmed successful payment marks one paid.
- **Splits record externally paid expenses**, not verified PayFlow purchases. Creator shares generate no self-payment. Equal allocation uses integer paise: ₹100 across three people becomes ₹33.34, ₹33.33, and ₹33.33. Custom shares must sum exactly to the total.
- **Services are synthetic.** Operators include PayFlow Mobile, NovaTel Demo, and BlueWave Telecom Demo, with ₹99/₹199/₹299/₹599 plans. Utility references use `DEMO` followed by six digits. A user/biller/reference has one stable bill per database calendar month; repeated lookup preserves its identity, amount, and paid state.

## Technology stack

| Layer | Technologies | Role |
| --- | --- | --- |
| Frontend | React 19, TypeScript 5, Vite 8 | Component UI, typed clients, and development/production builds |
| Styling | CSS custom properties, CSS, SVG icons | Shared design tokens and responsive layouts without a large UI framework |
| API | Python, FastAPI, Pydantic 2, Uvicorn | Routing, dependency injection, validation, typed responses, and OpenAPI |
| Persistence | PostgreSQL 16, SQLAlchemy, psycopg 3 | Relational storage, ORM access, transactions, locks, and constraints |
| Schema management | Alembic | Versioned forward migrations and model/schema comparison |
| Authentication | pwdlib with Argon2, PyJWT | Argon2id password verification and signed HS256 access tokens |
| QR | `qrcode`, `@zxing/browser`, `@zxing/library` | Browser-side PNG generation and camera/image decoding |
| Tests | Python `unittest`, FastAPI TestClient/httpx, Vitest, React Testing Library, jsdom | Backend integration and frontend behavior tests |
| Infrastructure and QA | Docker Compose, GitHub Actions, Playwright, Bandit, Gitleaks | Separate local demo stack, isolated browser tests and CI validation |

Dependency inputs are declared in [requirements.txt](backend/requirements.txt), [requirements-dev.txt](backend/requirements-dev.txt), and [package.json](frontend/package.json). Reproducible installs use the hash-checked Python `requirements*.lock` files and the frontend npm lockfile.

## System architecture

```mermaid
flowchart TD
    UI["React dashboard and feature components"] --> HTTP["Typed API helpers / fetch"]
    HTTP --> API["FastAPI routes and Pydantic validation"]
    API --> Auth["JWT validation and current-user dependency"]
    API --> Features["Accounts, contacts, requests, splits, and commerce"]
    Features --> Engine["Shared execute_payment service"]
    Engine --> Policy["Bound grants, UTC limits, and risk rules"]
    Policy --> ORM["SQLAlchemy session / psycopg"]
    Engine --> ORM
    Features --> ORM
    Auth --> ORM
    ORM --> PG[("PostgreSQL")]
    PG --- Journal["Payments, ledger, constraints, and triggers"]
    Audit["Read-only reconciliation CLI"] --> PG
```

- **React** owns presentation, memory-only authentication, local navigation, form review, and pending-intent recovery. API helpers attach Bearer tokens and normalize errors; the browser does not write balances.
- **FastAPI** authenticates callers, validates input, authorizes object access, and returns public schemas. Feature modules implement lifecycle rules and delegate money movement to `payments.py`.
- **SQLAlchemy and psycopg** translate model operations and explicit SQL into PostgreSQL queries within a session/transaction. PostgreSQL stores authoritative records and validates deferred accounting checks at commit.
- **Alembic** manages schema changes explicitly. Application startup does not create tables or run migrations.

These modules form one backend application, not independently deployed microservices. Frontend navigation uses React state rather than URL-based routing.

## Payment processing architecture

### Posting a payment

1. The user verifies a recipient or selects an owned destination/service, reviews the amount and source, and confirms.
2. The backend validates the JWT and payload. Client-supplied ownership, balances, settlement IDs, and purchase prices are not accepted.
3. `execute_payment` reserves a UUID idempotency key scoped to the authenticated user and compares a request fingerprint. A matching completed result is replayed before another posting is attempted.
4. The engine resolves the UPI destination, owned self-transfer destination, or private settlement ledger. Request/bill terms come from stored records; recharge prices come from active server-side plans.
5. It locks applicable lifecycle records, obtains the sender's account-configuration advisory lock, and locks affected bank accounts with `SELECT FOR UPDATE` in ascending ID order. Under those locks it verifies the bound PIN grant, UTC spending allowance, deterministic risk rules, and available funds.
6. A successful operation consumes its one-payment grant, increments daily usage, updates cached bank balances, writes the payment/two matching ledger entries, and persists linked obligations, fulfillment, and security decisions in the same PostgreSQL transaction.
7. Deferred constraints validate the posting. The engine stores its response in the idempotency record and commits once; only then is the receipt returned. Transaction failures roll back the operation.

```mermaid
sequenceDiagram
    actor User
    participant UI as React
    participant API as FastAPI
    participant Engine as Payment service
    participant DB as PostgreSQL
    User->>UI: Review, confirm, and enter payment PIN
    UI->>API: Request bound short-lived PIN authorization
    API-->>UI: One-payment bearer grant
    UI->>API: JWT, payload, key, and Payment-Authorization
    API->>Engine: Validated request and authenticated user
    Engine->>DB: Reserve scoped key and compare fingerprint
    alt Matching completed request
        DB-->>Engine: Stored result
        Engine-->>UI: Original receipt or error
    else New request
        Engine->>DB: Lock lifecycle records and ordered accounts
        Engine->>DB: Validate grant, limits, risk, ownership, and funds
        Engine->>DB: Consume grant and write usage, ledger, payment, state, audit, and result
        Engine->>DB: Check constraints and commit together
        DB-->>Engine: Commit succeeds
        Engine-->>UI: Confirmed receipt
    end
```

### Shared infrastructure

| Flow | Posting and business-state behavior |
| --- | --- |
| Direct or QR transfer | Debit the selected sender account and credit the exact UPI destination. QR selection uses the same transfer endpoint. |
| Request or split contribution | Lock the linked split/request, pay the pinned requester account, and mark the same underlying request paid atomically. Both screens reference one obligation. |
| Self-transfer | Move funds between different accounts owned by the caller, conserving combined user funds. |
| Demo funding | Debit `demo-funding` and credit the selected owned bank account, subject to the user-wide allowance. |
| Mobile recharge | Debit the owned source, credit `settlement-recharge`, and commit completed fictional fulfillment with the payment. |
| Utility bill | Lock the owned bill, debit its stored amount, credit `settlement-bills`, and mark it paid in the same transaction. |

Successful postings have two entries totaling zero. Failed payment records have no ledger postings. Types distinguish transfers, self-transfers, funding, recharges, and bills; new QR/request transfers also carry channel metadata.

### Retry and concurrency behavior

- Matching key/payload returns the stored HTTP status/body; changed parameters under the same key return **409**. Database uniqueness coordinates concurrent duplicates across API workers.
- Different keys cannot pay a paid bill twice: the authorized caller receives the original receipt. Paid money requests similarly recover their existing receipt.
- Lock order is retry key → submission-rate window → applicable split/request or bill/catalog locks → sender configuration → ascending bank-account IDs. Lifecycle actions use the same relevant record locks to coordinate pay/cancel/decline races.
- Deadlocks, lock timeouts, and uncertain commit failures return a safe **503** directing the client to retry the **same key and body**. Known business failures retain their results; correcting one requires a freshly reviewed intent.
- React saves unresolved intent metadata in account-scoped `sessionStorage` before submission, without the JWT. Same-tab retries after re-login preserve source, payload, and key. Recovery is not cross-device.

## Database design

| Entities | Responsibility |
| --- | --- |
| `users`, `bank_accounts` | Credentials/profiles and owned accounts with unique numbers/UPI IDs, exact balances, and primary selection |
| `payments` | Immutable payment snapshots, actor, bank/settlement references, type/channel, status, amount, and timestamp |
| `ledger_accounts`, `ledger_entries` | Bank-backed/internal ledgers and signed entries unique by payment/ledger pair |
| `payment_requests` | Engine idempotency records: user/key, fingerprint, payment link, HTTP status, and stored response |
| `contacts` | Unique owner/contact pairs and favorites; no self-contacts |
| `money_requests`, `money_request_destinations` | Requester/payer obligations, expiry, receipt, and pinned receiving account |
| `expense_splits`, `expense_split_participants`, `split_request_links` | External expense totals, shares, current contribution requests, and renewal history |
| `demo_operators`, `demo_recharge_plans`, `mobile_recharges` | Fictional catalogs and immutable completed recharges with masked numbers and unique payment links |
| `demo_billers`, `utility_bills`, `saved_billers` | Providers, owned monthly bills, payment links, and saved synthetic references |
| `recipient_lookup_limits`, `request_creation_limits`, `security_rate_windows` | Shared database-backed request and API throttles |
| `payment_pin_credentials`, `payment_authorizations` | Argon2id PIN hashes/version/lockout and digest-only, bound, expiring one-payment grants |
| `payment_limit_counters`, `fraud_risk_decisions`, `security_audit_events` | UTC usage, explainable risk decisions, and restricted structured security activity |

**Naming distinction:** `payment_requests` stores idempotency results; `money_requests` stores requests between people. The simplified diagram omits secondary role-specific foreign keys and catalog details.

```mermaid
erDiagram
    users ||--o{ bank_accounts : owns
    users ||--o{ contacts : saves
    users ||--o{ money_requests : requests_or_pays
    users ||--o{ payment_requests : scopes_keys
    bank_accounts ||--o{ payments : participates_in
    bank_accounts o|--|| ledger_accounts : backs
    payments ||--o{ ledger_entries : posts
    ledger_accounts ||--o{ ledger_entries : receives_entries
    payments o|--o| money_requests : settles
    users ||--o{ expense_splits : creates
    expense_splits ||--|{ expense_split_participants : allocates
    expense_split_participants ||--o{ split_request_links : tracks_attempts
    money_requests ||--o| split_request_links : links
    users ||--o{ mobile_recharges : purchases
    payments ||--o| mobile_recharges : fulfills
    users ||--o{ utility_bills : owns
    payments o|--o| utility_bills : settles
    users ||--o{ saved_billers : saves
```

Money uses PostgreSQL `NUMERIC(18,2)`, Python `Decimal`, and decimal-string JSON. The immutable ledger is the accounting source of truth; bank balances are cached values reconciled against it. Foreign keys restrict financial-record deletion. Unique/check constraints and deferred triggers enforce account limits, one primary per owner, nonnegative balances, balanced postings, cached-balance agreement, immutable financial records, and request/split/fulfillment linkage.

Splits are `OPEN`, `SETTLED`, or `CANCELLED`; settlement requires every owed contribution to be paid, and cancellation is prohibited after a contribution has been paid. Terminal unpaid contribution requests can be renewed with their audit links retained. Bills store `UNPAID`/`PAID`; `OVERDUE` is derived for display. Recharges persist completed synchronous fulfillment; financial failures appear in main payment history.

Internal funding/settlement accounts are ledger entities, not artificial users or bank accounts. They have no public credentials and cannot appear as selectable funding/self-transfer accounts.

The [migration chain](backend/migrations/versions) has repository head `0009_reliability_outbox`. Upgrades preserve history; downgrades are intentionally refused. Normal operation uses migrations, not `Base.metadata.create_all`.

## Security and reliability

| Protection | Implementation |
| --- | --- |
| Passwords | Salted Argon2id through pwdlib, hashes excluded from public schemas, and dummy verification for unknown logins |
| Authentication | HS256 JWT signature, expiry, issuer, audience, required-claim/purpose checks, and current-user database lookup |
| Authorization | Backend account ownership, request participant/payer checks, split visibility/creator checks, and user-owned bill/contact access |
| Money integrity | Strict decimal strings, authoritative purchase amounts, locked funds checks, atomic postings, constraints, and idempotency |
| Privacy and validation | Minimal recipient responses, masked identifiers, unexpected input fields rejected, safe database errors, and validation errors omitting submitted values |
| Browser behavior | Memory-only JWTs, explicit confirmation, no-store API responses, restricted localhost CORS, and pending-intent recovery |
| QR input | Strict versioned payload, length/UPI validation, no external navigation or credentials, backend recipient resolution, and camera-track cleanup |
| Auditing | Read-only checks of ledger totals, balances, posting structure, self-transfer conservation, and request/split/service links |

### Payment PIN and one-time authorization

Sensitive payments require a separate six-digit PIN. Initial setup also verifies the account password; changing it requires the current PIN. Obvious sequences/repetitions are rejected, hashes use Argon2id, and five wrong attempts cause a temporary 15-minute lockout by default. Existing users receive no default PIN. There is no forgotten-PIN reset endpoint because independent recovery is unavailable.

After review, React exchanges the PIN for a 120-second random bearer grant through `POST /security/payment-authorizations`. Only its digest is stored. The grant binds the user, source, operation, destination/bill/plan, exact amount, request fingerprint, idempotency key, expiry and PIN version. The original payment endpoint receives it in `Payment-Authorization`; consumption commits with the ledger, not before it. PIN changes invalidate older unconsumed grants. Neither PINs nor grants enter browser storage.

Successful committed retries replay their original result without requiring a fresh grant. A new posting always requires a matching unconsumed grant. After an uncommitted/expired retry, the frontend can obtain a fresh grant under the **same intended key**. Controlled demo funding is an explicit central PIN/daily-spending exemption with its unchanged user-wide allowance and shared rate/audit checks.

### Limits, fraud rules and audit

Defaults are ₹100,000 per payment, ₹200,000/50 outgoing postings per UTC day, and 20 created money/contribution requests per UTC day. Self-transfers count toward outgoing limits; demo funding, failures and idempotent replays do not. Owner locks protect a daily counter initialized from existing committed history. Days reset at **00:00 UTC**, with the posting-decision timestamp sampled after locks.

Rules use committed database state: payment velocity, large amounts, many recipient accounts, repeated insufficient funds, service-purchase velocity, recent PIN failures, new-contact repetition, and request-creation velocity. LOW/MEDIUM may ALLOW; sufficiently high risk BLOCKS with a safe rule explanation and no success receipt. There is no pretend additional-verification challenge or machine learning.

PostgreSQL fixed-window counters protect login, registration, PIN calls and new payment submissions alongside existing lookup/request limits. Socket-peer IP and normalized-identity subjects are HMAC digests. Direct local Uvicorn must use `--no-proxy-headers`; adding a reverse proxy requires an explicit trusted-proxy policy. Counter-store failure denies the action rather than failing open.

Structured events cover login, PIN lifecycle/failure/lockout, blocked/allowed payments, rules, primary changes and access/rate denials. They contain actor/operation IDs and allowlisted codes, never raw credentials, tokens, emails, mobile numbers or customer references. Successful financial decisions audit atomically; blocked decisions audit after financial rollback. Users can read only their own recent events in Security Settings.

See [Security architecture and threat model](docs/SECURITY.md) for rule thresholds, lock ordering, failure semantics, safe retention and residual risks. `security_retention` previews eligible security-only rows; its explicit operator `--apply` mode is never an automatic startup task and preserves financial history and consumed grants.

Logout clears React state but **does not revoke an issued JWT**; it remains valid until expiry. Refresh requires signing in again. Database owners can alter triggers, so production operation would need separate runtime/migration privileges and the additional controls under [Limitations](#limitations).

## Reliable delivery and operations

Every new successful payment creates a versioned, minimal outbox event in the **same PostgreSQL transaction** as its ledger. A separate `python -m outbox_worker` process claims bounded batches with `FOR UPDATE SKIP LOCKED`, expiring fenced leases, exponential retry and dead-letter state. It creates owner-scoped in-app notification records with unique event/user deduplication. Notifications are at least once and may be delayed; they never determine financial success or change balances. The dashboard receipt remains authoritative for the committed result.

```mermaid
flowchart LR
  API[FastAPI posting transaction] --> DB[(Payment + ledger + outbox)]
  DB --> Receipt[Committed receipt]
  DB --> Worker[Separate leased worker]
  Worker --> Activity[Idempotent participant notifications]
```

Run workers in separate terminals; do not attach financial background jobs to the API:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m outbox_worker
```

`GET /health/live` is database-independent; `GET /health/ready` checks PostgreSQL and the expected migration. `/metrics` is disabled unless a separate `PAYFLOW_OPS_TOKEN` is configured and supplied in `X-Ops-Token`. It exports low-cardinality HTTP durations/counts, payment/replay/error counters, pool utilization, outbox depth/lag/attempts, and database connection/lock/deadlock gauges. Logs use validated request/correlation UUIDs and route templates without bodies, raw query strings or credentials.

API and worker processes share correctness-critical PostgreSQL state. For local multi-worker use, run `python -m uvicorn main:app --port 8001 --workers 2 --no-proxy-headers --no-access-log`. Each process has its own bounded pool; default maximum is 10 connections/process, so account for all API/worker processes and reserve database headroom. Per-process metrics require independently scraped instances; a shared multi-worker port does not aggregate counters.

See [Reliability and operations](docs/reliability.md) for leases, failure recovery, metrics and configuration, [measured performance](docs/performance.md) for bounded benchmark results and commands, and [scaling toward 1M TPM](docs/scaling-to-1m-tpm.md) for a **proposed, unachieved** architecture target. Redis, Kafka, financial sharding, settlement lanes and production failover are not implemented. Authoritative balances remain strongly coordinated in PostgreSQL.

## Project structure

```text
PayFlow/
├── backend/
│   ├── main.py, config.py, database.py, security.py
│   ├── models.py, schemas.py
│   ├── accounts.py, account_schemas.py
│   ├── payments.py, payment_models.py, payment_schemas.py
│   ├── social.py, social_models.py, social_schemas.py, request_limits.py
│   ├── splits.py, split_models.py, split_schemas.py, split_service.py
│   ├── commerce.py, commerce_models.py, commerce_schemas.py
│   ├── commerce_service.py, commerce_seed.py, reconcile.py
│   ├── pin_security.py, pin_schemas.py, payment_policy.py
│   ├── security_models.py, security_events.py, security_settings.py
│   ├── security_retention.py
│   ├── outbox.py, outbox_models.py, outbox_worker.py
│   ├── operations.py, observability.py, reliability_config.py
│   ├── migrate.py, migration_lock.py, serve.py, worker_health.py
│   ├── migrations/versions/
│   ├── tests/
│   ├── benchmarks/                  # Isolated workloads and measured results
│   ├── alembic.ini, requirements.txt, requirements-dev.txt
│   ├── requirements*.lock, Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx, useAuth.ts, DashboardShell.tsx, navigation.ts
│   │   ├── AccountPanel.tsx, PaymentPanel.tsx, PaymentHistory.tsx
│   │   ├── SocialPanel.tsx, SplitPanel.tsx, SelfTransferPanel.tsx
│   │   ├── CommercePanel.tsx, MyQrCode.tsx, QrScanner.tsx
│   │   ├── SecurityPanel.tsx, PaymentPinDialog.tsx, securityApi.ts
│   │   ├── api.ts, socialApi.ts, splitApi.ts, commerceApi.ts
│   │   ├── qrPayload.ts, qrMedia.ts, moneyInput.ts, splitMath.ts
│   │   └── *.test.ts, *.test.tsx, App.css, index.css, assets/
│   ├── public/
│   ├── qa/                         # Isolated backend and browser harnesses
│   ├── package.json, package-lock.json
│   ├── Dockerfile, nginx.conf, vercel.json
│   └── .env.example
├── docs/
│   ├── SECURITY.md, reliability.md, performance.md
│   ├── deployment.md, testing.md, backup-recovery.md
│   ├── deployment-smoke.md, verification.md
│   └── scaling-to-1m-tpm.md
├── .github/workflows/ci.yml
├── tools/                          # Guarded CI, smoke and restore utilities
├── deploy/postgres-init.sh
├── docker-compose.yml, render.yaml
└── README.md
```

## Getting started

### Prerequisites

- Python 3.11, the version used by the local backend environment.
- Node.js 22.12+ and npm; the checked-in Vite dependency also permits Node 20.19+.
- Git and Docker Desktop with Linux containers, or an existing PostgreSQL server. The local container uses PostgreSQL 16.
- PowerShell. These commands do not require virtual-environment activation.

Clone the configured repository:

```powershell
git clone https://github.com/Harshita2011/PayFlow.git
Set-Location PayFlow
```

### Backend dependencies and configuration

From the repository root:

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `backend/.env` with your local PostgreSQL connection. Keep existing connection settings and signing keys if already configured. The [environment table](#environment-variables) explains each setting.

For the **blank JWT slot in a new environment**, this generates a key without printing it and leaves a nonempty signing key unchanged:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import secrets; p=Path('.env'); s=p.read_text(encoding='utf-8'); p.write_text(s.replace('JWT_SECRET_KEY=\n','JWT_SECRET_KEY='+secrets.token_urlsafe(48)+'\n',1),encoding='utf-8')"
```

### PostgreSQL

If `payflow-postgres-5436` already exists, reuse it with `docker start payflow-postgres-5436`. Do not recreate its container or volume.

For a **new installation only**, this example creates PostgreSQL 16 with persistent storage. It is a setup example, not a checked-in Compose configuration:

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

Use that user/database/password in `DATABASE_URL`; URL-encode special characters in credentials. Wait for PostgreSQL to be ready, then apply migrations from `backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Migrations insert the fictional operator, plan, and biller catalogs automatically. Optional `commerce_seed` execution through the same virtual environment inserts missing catalog entries without replacing existing ones:

```powershell
.\.venv\Scripts\python.exe -m commerce_seed
```

### Frontend dependencies

In another terminal, from the repository root:

```powershell
Set-Location frontend
npm ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

The frontend defaults to `http://localhost:8001`. No credentials belong in its environment file.

## Environment variables

| Variable | Location | Required | Purpose and safe example |
| --- | --- | --- | --- |
| `DATABASE_URL` | Backend environment or `backend/.env` | Yes | SQLAlchemy/psycopg URL: `postgresql+psycopg://payflow:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5436/payflow` |
| `PAYFLOW_ENV` | Backend/worker | No | `development` (default), `test`, or `demo`; demo requires HTTPS CORS and database TLS |
| `CORS_ALLOWED_ORIGINS` | Backend | No | Exact comma-separated origins; defaults to localhost/127.0.0.1:5173, no wildcards |
| `PAYFLOW_EXPOSE_DOCS`, `LOG_LEVEL` | Backend | No | Docs default off in demo; INFO/WARNING/ERROR logging |
| `JWT_SECRET_KEY` | Backend environment or `backend/.env` | Yes | Random signing key of at least 32 bytes; generate locally rather than copying a sample secret |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Backend | No | Access-token lifetime, integer 1–60; default `15` |
| `PAYFLOW_DEMO_MOBILE_PREFIXES` | Backend | No | One to ten ASCII digits allowed as the first digit of a ten-digit demo mobile number; default `6789` |
| `VITE_API_BASE_URL` | `frontend/.env` or frontend process environment | No | Public backend URL; default `http://localhost:8001` |
| `PAYMENT_SINGLE_LIMIT`, `PAYMENT_DAILY_LIMIT`, `PAYMENT_DAILY_COUNT` | Backend | No | Exact decimal amounts `100000.00` / `200000.00`, daily count `50` |
| `REQUEST_DAILY_COUNT` | Backend | No | UTC-day request/contribution creation cap; default `20` |
| `PIN_MAX_ATTEMPTS`, `PIN_LOCK_SECONDS`, `PAYMENT_AUTH_SECONDS` | Backend | No | Defaults `5`, `900`, `120`; grant TTL is bounded to 300 seconds |
| `LOGIN_IP_LIMIT`, `LOGIN_IDENTITY_LIMIT`, `REGISTER_IP_LIMIT` | Backend | No | Defaults `30` per minute/IP, `10` per 15 minutes/identity, `10` per hour/IP |
| `PIN_RATE_LIMIT`, `PAYMENT_RATE_LIMIT` | Backend | No | Defaults `10` PIN calls and `30` new submissions per user/minute |
| `RISK_*` | Backend | No | Exact rule settings/defaults are enumerated in `.env.example` and [SECURITY.md](docs/SECURITY.md) |
| `SECURITY_RETENTION_DAYS` | Backend | No | Recent event visibility/operator retention cutoff; default `90`, no scheduled purge |
| `REGISTER_TEST_POSTGRES` | Backend test process only | No | Set to `1` for PostgreSQL integration tests; leave unset for the limited SQLite suite |
| `PAYFLOW_TEST_DATABASE` | Test/benchmark process only | No | Validated isolated `payflow_*_tests` database; default `payflow_phase4_tests`; never the development database |
| `PAYFLOW_TEST_DATABASE_URL` | Test process only | No | Optional separate credentials for a pre-provisioned test database; must match the declared test name |
| `PORT`, `WEB_CONCURRENCY`, `PAYFLOW_MAX_CONCURRENCY` | Container/cloud entry point | No | Defaults 8001/1/16; budget memory and database connections per process |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS` | Backend/worker | No | Per-process defaults `5`, `5`, `5`, `1800` |
| `DB_CONNECT_TIMEOUT_SECONDS`, `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS` | Backend/worker | No | Bounded waits; defaults `5`, `15000`, `5000` |
| `OUTBOX_BATCH_SIZE`, `OUTBOX_LEASE_SECONDS`, `OUTBOX_MAX_ATTEMPTS`, `OUTBOX_POLL_SECONDS` | Worker | No | Defaults `10`, `30`, `5`, `1` |
| `PAYFLOW_OPS_TOKEN` | Backend operator environment | No | Empty disables metrics; otherwise a separately generated random 32+ byte token, never a frontend value |

Safe templates exist at [backend/.env.example](backend/.env.example) and [frontend/.env.example](frontend/.env.example). Local environment files are ignored by Git. Backend configuration reads its adjacent `.env`; frontend `VITE_` values become public build configuration. Restart the relevant server after changes and rebuild the frontend for changed production values.

Ports are local conventions, not protocol requirements. A different PostgreSQL port requires a matching server/container mapping and `DATABASE_URL`. A different API port requires updating `VITE_API_BASE_URL`. Changing the frontend origin also requires updating `backend/main.py`'s CORS allowlist, currently localhost/127.0.0.1 on port 5173.

## Running the application

Run each block from the repository root in a separate PowerShell terminal.

**Backend:**

```powershell
docker start payflow-postgres-5436
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001 --no-proxy-headers --no-access-log
```

**Frontend:**

```powershell
Set-Location frontend
npm run dev -- --port 5173 --strictPort
```

- Application: [http://localhost:5173](http://localhost:5173)
- Interactive API documentation: [http://localhost:8001/docs](http://localhost:8001/docs)
- OpenAPI schema: [http://localhost:8001/openapi.json](http://localhost:8001/openapi.json)
- Health checks: `/health` for the process and `/db-health` for database connectivity.

`--strictPort` prevents Vite moving silently outside the CORS allowlist. These commands start development servers; the repository does not provide production deployment configuration.

## Containers and deployment

An optional, separate local stack packages the frontend, API, durable worker, migration runner and persistent PostgreSQL. It does **not** use or replace the existing `payflow-postgres-5436` container. From the repository root:

```powershell
python tools/init_compose.py
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose up -d --build --wait
```

The initializer refuses to overwrite an existing private environment file. Open [the local simulated demo](http://localhost:18080). Only its frontend proxy is published to loopback; API/worker run non-root with separate restricted database roles. Data persists in `payflow_demo_pgdata`. Stop with `docker compose --env-file .env.compose stop`; do not remove volumes.

```powershell
python tools/deployment_smoke.py
docker compose --env-file .env.compose exec api python -m reconcile
```

GitHub Actions defines backend/PostgreSQL, frontend, security, isolated E2E and container/restore jobs with read-only permissions, immutable action SHAs and no deployment credentials. Local workflow syntax was validated; **the workflow has not run on GitHub**. No commit, push, public deployment or billable resource creation was performed.

Cloud configuration is prepared for a Vercel static frontend plus a Render API/worker and separately provisioned persistent managed PostgreSQL. Automatic deployment is disabled; owner migrations and public release require explicit review/approval. No hosted URL exists. See [deployment instructions](docs/deployment.md), [test/CI workflow](docs/testing.md), [backup/recovery](docs/backup-recovery.md), the [post-deployment checklist](docs/deployment-smoke.md), and [executed verification](docs/verification.md) for configuration, current provider assumptions, safety gates and exact commands.

## Testing and verification

Latest executed checks: **225 PostgreSQL backend tests** and **190 frontend tests** passed; TypeScript, ESLint, production build, Alembic consistency and ledger reconciliation passed. The managed runner passed five Chromium scenarios with worker drain and data-preservation checks. The separate Compose stack and its backup/restore exercise passed locally. These are verification results, not cloud-deployment or load-capacity claims; [performance.md](docs/performance.md) records the separately measured bounded workloads and limitations.

### Backend

From `backend`, the default suite uses in-memory SQLite for authentication/account tests and skips PostgreSQL-specific cases:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

For the full suite, configure PostgreSQL and migrate the application database, then run:

```powershell
$env:REGISTER_TEST_POSTGRES = '1'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
Remove-Item Env:REGISTER_TEST_POSTGRES
```

Tests cover PIN setup/lockout/change, grant binding/expiry/consumption, UTC counters, limits/risk/rate failures, audit privacy, authorization, exact amounts, ledger balance, rollback injection, retry/concurrency and request/split/service regressions. Security fixtures do not reset the development database.

**Integration-test isolation:** payment tests create fresh schemas in a separate database (default `payflow_phase4_tests`, or a validated `PAYFLOW_TEST_DATABASE`), with independent sessions and real commits. The PostgreSQL role needs permission to create that database once and create schemas there. Authentication/account and migration tests also use the dedicated test database, with outer rollback transactions and isolated schemas. Dedicated committed test schemas are deliberately retained. Legacy payment regression helpers obtain real PIN grants and explicitly relax configured risk thresholds in their fixture process; dedicated security tests and default browser QA enforce the actual defaults. PostgreSQL tests are therefore not read-only operations even though they preserve development records.

### Frontend

From `frontend`:

```powershell
npm test
npx tsc -b
npm run lint
npm run build
```

Vitest/jsdom tests exercise PIN setup/entry/lockout, blocked-payment warnings, forms, confirmation, QR handling, retry recovery, receipts, contacts, requests, splits, and purchases with mocked HTTP calls. `npm run build` also runs `tsc -b` before generating the Vite bundle in `frontend/dist`.

### Schema and ledger checks

From `backend`, with the database already migrated:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m reconcile
.\.venv\Scripts\python.exe -m security_retention
```

`alembic check` compares SQLAlchemy metadata with the schema; integration tests cover trigger behavior. Reconciliation uses a consistent read-only snapshot and exits unsuccessfully when an invariant fails. It never repairs balances or rewrites history. The retention command above only previews eligible security-row counts; it does not prune them.

### Optional browser verification

[frontend/qa](frontend/qa) contains a repository-pinned Playwright runner, `isolated_backend.py`, real-worker integration, lost-response recovery and responsive scenarios. From `frontend`, run `npx playwright install chromium`, then `npm run test:e2e`. The managed runner uses dedicated loopback ports 5180/18016, fresh test schemas and masked/redacted failure diagnostics; it never targets the development API. See [testing.md](docs/testing.md).

Use the isolated backend on `127.0.0.1:18016` and a separate Vite process with `VITE_API_BASE_URL=http://127.0.0.1:18016`. Harnesses block writes outside that backend. Shutdown checks reconcile its ledger and compare development-record snapshots. These scripts create isolated test records and run test-schema migrations; do not point them at ordinary development payment endpoints. Headless checks do not establish physical-camera or assistive-technology compatibility.

The `qa/security-browser.mjs` harness additionally tests PIN lockout/recovery, PIN change, risk/daily blocks, private events and original-key recovery after a lost committed response and re-login. Use a **fresh isolated QA backend only**, with explicit test-process overrides `PIN_LOCK_SECONDS=5`, `PIN_RATE_LIMIT=30`, `PAYMENT_DAILY_LIMIT=25.00`, and `RISK_BLOCK_AMOUNT=20.00`. These overrides do not modify `backend/.env`; restart the QA server to restore defaults.

## API overview

User-specific routes require a Bearer token. New sensitive payments additionally require a bound `Payment-Authorization` grant; demo funding retains its controlled exemption. `Idempotency-Key: <UUID>` is required for money-changing requests, creating money requests/splits, and renewing split contributions. Payloads and responses are documented in [FastAPI /docs](http://localhost:8001/docs); this table highlights the main routes.

| Group | Method and route | Purpose |
| --- | --- | --- |
| Security | `GET /security/status`, `GET /security/events` | Own PIN/limit status and paginated security activity |
| Reliability | `GET /health/live`, `GET /health/ready` | Process liveness and database/schema readiness |
| Activity | `GET /activity/notifications` | JWT-protected, owner-only asynchronous payment references |
| Security | `POST /security/pin`, `POST /security/pin/change` | Password-authenticated initial setup and current-PIN-authenticated change; no reset endpoint |
| Security | `POST /security/payment-authorizations` | Verify PIN and issue a short-lived grant bound to an intended payment/key |
| Authentication | `POST /register`, `POST /login`, `GET /me` | Create a user, obtain a token, and retrieve the authenticated profile |
| Accounts | `GET /accounts/banks`, `GET /accounts`, `POST /accounts` | List demo banks and create/list owned accounts |
| Accounts | `PATCH /accounts/{account_id}/primary` | Change the owned default account atomically |
| Payments | `POST /payments/resolve`, `POST /payments/transfer` | Resolve an exact recipient and send a confirmed payment |
| Payments | `POST /payments/self-transfer`, `POST /demo/fund` | Move funds between owned accounts or add controlled demo funds |
| Payments | `GET /payments/history`, `GET /payments/{transaction_id}` | Participant-only paginated history and receipts |
| QR | Uses `/payments/resolve` and `/payments/transfer` | Client-side generation/decoding; no separate QR payment endpoint |
| Contacts | `GET /contacts`, `POST /contacts`, `DELETE /contacts/{contact_id}` | Personal saved-contact management |
| Contacts | `PATCH /contacts/{contact_id}/favorite`, `GET /contacts/recent` | Favorites and recent counterparties |
| Money requests | `POST /payment-requests`, `GET /payment-requests/incoming`, `GET /payment-requests/outgoing` | Create and list participant-scoped obligations |
| Money requests | `POST /payment-requests/{request_id}/pay` | Explicitly pay an eligible request or recover its receipt |
| Money requests | `POST /payment-requests/{request_id}/decline`, `POST /payment-requests/{request_id}/cancel` | Close an eligible incoming/outgoing request |
| Splits | `POST /splits`, `GET /splits`, `GET /splits/{split_id}` | Create an expense and view accessible splits/progress |
| Splits | `POST /splits/{split_id}/cancel`, `POST /splits/{split_id}/participants/{participant_id}/renew` | Safely cancel an unpaid split or renew a contribution request |
| Recharge | `GET /recharge/operators`, `GET /recharge/plans`, `POST /recharge` | Discover fictional plans and purchase at the server price |
| Recharge | `GET /recharge/history`, `GET /recharge/{recharge_id}` | Owned recharge records and receipts |
| Bills | `GET /billers`, `POST /bills/lookup`, `POST /bills/{bill_id}/pay` | Find a stable synthetic bill and pay its stored amount |
| Bills | `GET /bills`, `GET /bills/{bill_id}`, `GET /bills/history` | Owned bill details/history; lists support `paid_only=true` |
| Saved billers | `GET /saved-billers`, `POST /saved-billers`, `DELETE /saved-billers/{saved_id}` | Save/remove owned biller-reference shortcuts |
| Saved billers | `POST /saved-billers/{saved_id}/lookup` | Fetch a current bill without returning the full saved reference |

Example transfer JSON, using an owned source ID and another account's verified UPI ID:

```json
{
  "upi_id": "recipient-example@payflow",
  "source_account_id": 1,
  "amount": "125.50",
  "note": "Shared demo lunch"
}
```

These identifiers are examples, not seeded users. Monetary inputs must be positive decimal strings with at most two decimal places; transfer/request/split inputs are capped at ₹100,000.00. In `/docs`, log in and paste the access token into **Authorize**; Swagger supplies the Bearer prefix.

QR payloads use `payflow://pay?v=1&upi=recipient-example%40payflow`. Only a public recipient identifier is encoded: no amount, account number, balance, or token. Unsupported versions, external URLs, malformed payloads, and oversized contents are rejected. Camera access needs a supported secure context such as localhost/HTTPS. PNG/JPG/WebP decoding runs locally with 5 MB and 4096 × 4096 pixel limits. Scanning alone never sends money.

## Demo workflow

Use fictional identities in two browser profiles, Alice and Bob. Manual operations intentionally persist demo records; use the isolated QA environment for disposable experiments.

1. Register and sign in as both users. Open **Security Settings**, re-enter the account password, and set a strong payment PIN. Create an account for each and copy Bob's generated UPI ID.
2. Alice adds ₹1,000 of demo funds, verifies Bob, reviews a ₹125.50 transfer, confirms, and enters her payment PIN. Refresh both users' balances/history and open the same receipt.
3. Bob displays/downloads his QR. Alice scans or uploads it, checks the backend-verified recipient, and explicitly confirms a new payment.
4. Save Bob as a contact/favorite. Create a money request; as its designated payer, review and pay it or decline it. Creating a request moves no money.
5. Create an external expense split with an optional creator share and equal/custom allocations. Pay Bob's linked contribution through Requests or My Splits; both represent the same obligation.
6. Add Alice's second account and explicitly confirm a self-transfer. Combined funds stay unchanged. Changing primary does not reroute her existing UPI IDs.
7. Open **Bills & Recharge**, choose PayFlow Mobile's ₹99 Demo Starter plan, enter a ten-digit demo number starting with 6–9 under the default configuration, select a funded source, review, and confirm.
8. Select a utility biller and enter `DEMO000001`. Fetch twice to verify stable bill details. Save the biller, review/pay the bill, and fetch it again to see `PAID` and its receipt.
9. Inspect main/service history and run reconciliation. If a response is lost, retry the original saved intent rather than generating a new payment key.

Use amounts within available funds. New accounts do not reset the three-action funding allowance. Repeat recharge preselects operator/plan but requires number re-entry and a new review because full numbers are not retained in recharge records.

## Screenshots

No application screenshots are currently committed. The image under `frontend/src/assets` is a UI asset, not a documented application screenshot; no placeholder or external stock images are used here.

## Design decisions and tradeoffs

| Decision | Reason and tradeoff |
| --- | --- |
| One PostgreSQL transaction per posting | Balances, journal, receipt linkage, and fulfillment succeed or roll back together, keeping consistency within one database rather than distributed settlement. |
| Double-entry journal plus cached balance | The journal explains every movement; cached balances simplify account reads. Deferred aggregate checks add database work and are not a throughput claim. |
| Decimal strings and integer paise | Avoid binary floating-point rounding in inputs, storage, and allocation; clients must preserve string amounts. |
| Database-coordinated retries/locking | Unique scoped keys and deterministic locks coordinate API workers. Lock waits/failures still require same-key recovery. |
| Shared request/split obligations | Paying a contribution from either screen settles the same request. Renewal links retain earlier attempts instead of creating a competing payment system. |
| Account-scoped UPI routing | Existing identities and QRs keep their receiving account when defaults change; primary selection is not an incoming-payment redirect. |
| Private internal ledgers | Funding and fictional purchases remain balanced without public system users or selectable settlement bank accounts. |
| Memory-only authentication | Tokens do not persist across reload, at the cost of signing in again. Pending operation metadata is stored separately for retry recovery. |

## Limitations

- Fictional INR only: no real banking/UPI/BBPS integration, telecom activation, utility settlement, refunds, reversals, recurring payments, or multi-currency support.
- Not a production-ready financial service. No refresh-token/revocation system, MFA, verified email, password recovery, or independent forgotten-PIN recovery. Both login and registration are rate-limited. Registration explicitly reports duplicate emails.
- Six-digit PINs have limited entropy; hashing and online lockout do not eliminate offline guessing after database compromise. PIN knowledge is not claimed as independent MFA. Risk rules are demo heuristics and may block legitimate behavior.
- Localhost HTTP, basic per-user limits, and database triggers do not replace TLS, edge abuse protection, monitoring, or least-privilege database roles. Administrators can alter accounting protections.
- Fulfillment is synchronous and fictional. Synthetic bill references are stored in plain text. Recharge records retain only masked numbers; unresolved browser intents temporarily retain the original number for exact retry.
- Deliberately small demo limits: four accounts, three user-wide funding actions, ten split participants, 100 generated bills, and 20 saved billers per user. No automated funding reset or idempotency-record expiry exists. Security retention requires an explicit operator action.
- Retry metadata is tab/session scoped. Clearing it or switching devices loses the frontend recovery context; inspect history before starting a replacement payment.
- Compose, CI and provider configuration are present, but no public deployment or GitHub-hosted CI execution has been verified. Browser harnesses do not prove physical-device/camera or screen-reader compatibility.

## Future improvements

- Harden session management, account recovery, and abuse prevention.
- Extend observability with operational alerts, distributed tracing and stronger fraud/rate-limit analysis.
- Verify the prepared CI on GitHub and the approved cloud release, then add provider alerts, image OS scanning and repeated restore drills.
- Review database privileges, secret management, backups, recovery procedures, and accounting-query scaling before public deployment.
- Extend accessibility and physical-device testing; add committed product screenshots.
- Explore durable asynchronous fulfillment/recovery only if the simulator's scope requires it.

## License and acknowledgments

No `LICENSE` file is currently included, so the repository does not declare an open-source license.

PayFlow is an independent educational and portfolio project inspired by modern digital payment interfaces. It is not affiliated with or endorsed by Google Pay, Google, NPCI, banks, utility providers, or telecom operators.
