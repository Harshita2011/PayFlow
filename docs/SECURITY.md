# Security architecture and threat model

PayFlow uses fictional funds. These controls are educational safeguards, not financial certification or a claim of production readiness.

## Scope and audit findings

The audited implementation already used Argon2id passwords, restricted HS256 JWT validation with issuer/audience/expiry checks, object-level ownership, exact decimal amounts, deterministic account locks, an immutable balanced ledger, deferred database checks, and user-scoped idempotency results. Those mechanisms are retained.

Identified gaps were JWT-only payment approval, unthrottled login/registration, no payment PIN or short-lived approval, no daily outgoing allowance, limited abuse signals, and no structured security-event store. Registration still exposes duplicate-email status as a compatibility limitation; logout remains client-side without JWT revocation.

| Threat | Implemented response | Residual limitation |
| --- | --- | --- |
| Credential guessing/stuffing | Socket-peer and HMAC-identity login throttles, registration throttles, generic login failure, common-password rejection for new registrations | No MFA, verified email, breached-password service, or distributed edge bot protection |
| Stolen JWT / privilege escalation | Source ownership and participant checks plus separate PIN grants; initial PIN setup also reauthenticates the account password | Active XSS can access live browser state; stealing both credentials defeats this demo factor |
| Unauthorized account access | Backend owner filters, generic 404, actor-only access-denial events | Identifiers are not themselves secrets or authorization |
| Duplicate/replayed payment | Existing scoped UUID key/fingerprint replay; grant additionally binds key, terms, source, user, PIN version and expiry | Lost frontend session storage requires inspecting server history; no cross-device recovery UI |
| Request spam/enumeration | Exact UPI lookup only, DB lookup budget, hourly/outstanding and UTC-day request caps, creation-velocity blocking | Registration duplicate status remains an oracle; per-user limits are not full Sybil protection |
| Fraudulent payment patterns | Explainable amount/velocity/distinct-recipient/insufficient-funds/service/new-contact/PIN-failure rules | Rules are demo heuristics; false positives are possible and no ML accuracy is claimed |
| Concurrent spending/races | Existing lock order plus owner-scoped daily counter and atomic authorization consumption | Lock waits/deadlocks can fail; clients must retry the original key |
| Secret and personal-data leakage | SecretStr PIN/password inputs, safe errors, digest-only grants, HMAC rate subjects, allowlisted audit metadata, no PIN/token logging | Deployment logging, TLS, role privileges and browser hardening need operational review |

## PIN lifecycle

`POST /security/pin` requires the current account password and a strong six-digit ASCII PIN. Argon2id stores only a salted hash. Repeated/low-diversity PINs, obvious ascending/descending sequences, and simple repeated patterns are rejected. Existing users have no default PIN and existing credentials/history are never rewritten.

`POST /security/pin/change` verifies the existing PIN, then increments its version. Every outstanding grant from the previous version becomes invalid. Failed PIN attempts are serialized using the same owner-configuration advisory lock as payments; five failures lock the credential for 900 seconds by default. Verification after expiry resets the failed-attempt window. The independent per-user PIN rate limit also covers setup/change/authorization calls.

There is **no forgotten-PIN reset endpoint**. Neither an active JWT nor the login password alone can replace a configured PIN. A genuine independent recovery mechanism must be designed before recovery can be offered.

## One-payment authorization

1. Review the payment and generate its intended idempotency UUID.
2. Submit `POST /security/payment-authorizations` with that key, the PIN, an operation and its original payload. REQUEST/BILL_PAYMENT include `reference_id`; request amounts/destinations and bill/plan prices are loaded by the server.
3. The server verifies ownership and the PIN and issues a random 256-bit bearer token, valid for 120 seconds by default. Only SHA-256 of that high-entropy token is stored.
4. Send it in `Payment-Authorization` alongside the existing Bearer token and `Idempotency-Key` to the original payment endpoint.
5. After lifecycle/configuration/account locks, the shared engine compares user, key, fingerprint, source, operation, destination digest, exact amount, credential version, expiry and unconsumed state. It evaluates limits and risk under the same protected transaction.
6. Consumption, daily usage, payment, ledger, lifecycle/fulfillment and allowed risk/audit records commit together. Deferred database checks require newly inserted successful non-funding payments to have a matching consumed grant and idempotency record.

Direct/QR transfers, request and split payments, self-transfers, recharge and bills share this policy. Demo funding has an explicit central exemption from PIN/daily outgoing spending: the unchanged three-action lifetime allowance, owned-account checks, shared submission rate and audit/risk recording still apply.

Successful same-key retries return their original result before requiring another grant, even after grant expiry or PIN change. A supplied key alone cannot authorize a new posting. Authorization/risk failures roll back the reservation and do not burn the grant. Known financial failures retain their existing idempotent failure response, but consume neither grant nor daily allowance. Injected/transaction failures roll everything back and allow the original grant to retry until expiry; an expired grant can be replaced under the **same intended key**.

React never puts the PIN, JWT or raw grant in browser storage. It clears PIN input before awaiting verification and keeps a raw grant only in component memory. A committed-response retry uses that same key; after refresh, a headerless retry can recover a committed response, or a proven authorization-required response asks for a fresh grant under the same key. A server-authoritative amount/source mismatch requires review rather than silently approving changed details.

### Trying an authorization in FastAPI /docs

Authenticate using **Authorize**, then configure your own PIN with `/security/pin` and your account password. Choose one UUID for the intended payment and put it in `Idempotency-Key` on both authorization and transfer requests. For example, send this shape to `/security/payment-authorizations` (replace the PIN and identifiers with your own fictional account details):

```json
{
  "pin": "YOUR_SIX_DIGIT_PIN",
  "operation": "TRANSFER",
  "payload": {
    "upi_id": "recipient-example@payflow",
    "source_account_id": 1,
    "amount": "12.50",
    "note": "Demo payment"
  }
}
```

The PIN placeholder deliberately is not a usable PIN. Copy the returned `authorization_token` into the `Payment-Authorization` header of `/payments/transfer`, and submit exactly the nested `payload` above as its body. Keep the original key and payload when retrying. Do not publish tokens, grant responses or credentials in screenshots or logs.

## Limits and deterministic risk rules

Outgoing daily usage includes successful direct/QR/request/split/self/recharge/bill payments across all owned accounts. Self-transfers count despite conserving total funds, preventing rapid account cycling. Funding and failures do not count. Defaults are ₹100,000 per payment, ₹200,000 and 50 postings per UTC day, and 20 created contribution/money requests per UTC day. Existing schema maximums still apply if configuration is higher.

The payment lock order is retry key → submission-rate window → applicable split/request or bill/catalog → owner configuration → ascending bank IDs → bound grant/daily counter. PIN issuance/change takes its owner lock before credential updates; no code takes a financial account lock before the sender's configuration lock.

The engine holds owner lock 709, seeds a missing daily counter from already committed historical payments for that UTC date, and updates it only with successful postings. The posting-decision timestamp is sampled after account locks and defines the UTC day. Same-key replays do not update usage. Request creation uses sorted capacity locks 707; splits/renewals share that budget. There is no counter-reset cron: a new UTC date selects a new row.

| Signal | Default behavior |
| --- | --- |
| At least 8 prior successful outgoing payments in 60 seconds | HIGH / BLOCK |
| Amount at least ₹75,000 | HIGH / BLOCK |
| Amount at least ₹10,000 below the block threshold | MEDIUM / ALLOW and record |
| A new destination after 5 distinct transfer-account destinations in 10 minutes | HIGH / BLOCK |
| At least 5 insufficient-funds failures in 10 minutes | HIGH / BLOCK |
| At least 8 successful service purchases in 10 minutes | HIGH / BLOCK for another service purchase |
| At least 3 recent PIN failures in 10 minutes | MEDIUM / ALLOW and record; PIN lockout still independently applies |
| At least 3 prior transfers in 10 minutes to a contact saved in the past day | MEDIUM / ALLOW and record |
| More than 10 requested contributions created within 60 seconds | HIGH / BLOCK request creation |

LOW means no listed rule fired. MEDIUM is observable, not a pretend additional-verification mechanism. HIGH returns a safe blocked response with rule names and no success receipt. Windows use committed database state; blocked outcomes are also audited. Rules do not use protected personal characteristics.

## Rate limiting and audit

PostgreSQL upserts implement fixed-window counters. Login defaults: 30 requests/socket-peer/minute and 10/normalized-email/15 minutes. Registration: 10/socket-peer/hour and 3/email/hour. PIN: 10/user/minute; new payment submissions: 30/user/minute. Existing lookup/service/request limits remain in force. Identity/IP subjects are HMAC digests, not raw addresses or emails. Both committed replays and concurrent duplicates bypass new-submission throttling after reserving the scoped retry key; only the winning new reservation charges a slot. Successful and known-result slots commit with the request. After a blocked rollback, a security-only transaction retains the attempt/denial. Interrupted attempts are recorded best effort after rollback, without double-charging an already committed request. A 429 includes Retry-After. Counter-store failure denies the operation; there is no in-memory fail-open fallback.

Run Uvicorn with **`--no-proxy-headers`** for the direct local setup. FastAPI uses `request.client.host`, never reads forwarding headers itself, and the QA server disables proxy headers. If a reverse proxy is introduced, explicitly configure trusted proxy addresses and deployment boundaries; an upstream server that rewrites ASGI client addresses changes the trust model.

Security events contain an ID, actor ID when known, UTC timestamp, operation UUID, outcome and allowlisted codes/rule names. They never contain submitted passwords/PINs, bearer tokens, email/mobile/reference values, or arbitrary exception/request bodies. PIN failures and lockouts commit in PIN-only transactions; successful payment events commit with the ledger. Blocked payment events are written in a separate security-only transaction **after** financial rollback. An unavailable audit store returns a safe 503; it never allows a payment to proceed.

`GET /security/events` provides paginated events for the current actor only and the configured recent-retention window. No normal-user endpoint exposes global logs, PIN hashes, grant digests or rate subjects. Audit/risk records reject updates. Application credentials are not a substitute for a separate least-privilege runtime role and audited migration/operator role.

## Retention and operation

`SECURITY_RETENTION_DAYS` defaults to 90. The operator CLI `python -m security_retention` is a **read-only preview** of eligible counts. Only an explicit, reviewed `--apply` prunes old audit events, unlinked blocked risk decisions, long-expired unused grants, and rate windows older than two days. Consumed grants, linked risk decisions, credentials, daily counters, and all financial/business history are preserved. There is no scheduled purge or implicit startup cleanup. Review archival/access requirements before running a maintenance command; no cleanup is run as part of implementation verification.

Settings are validated in `backend/security_settings.py` and documented in the root README and safe environment template. Browser controls use the existing design and are subordinate to backend enforcement. Existing authentication sessions are not rotated or revoked by this migration. No real provider integration or production-security certification is implied.

## Implementation map

| Files | Responsibility |
| --- | --- |
| `backend/security_models.py`, `migrations/versions/0008_payment_security.py`, `migrations/env.py` | Add credentials, grants, daily counters, rate windows, audit and risk state; register metadata; protect new successful postings with a deferred constraint trigger. |
| `backend/pin_schemas.py`, `pin_security.py` | Validate secret inputs; implement PIN setup/change, bound grant issuance, own status and paginated events. |
| `backend/payment_policy.py`, `security_events.py`, `security_settings.py` | Central financial policy, concurrency-safe counters, explainable risk rules, redacted events and validated configuration. |
| `backend/payments.py`, `social.py`, `commerce.py` | Pass grants through every financial entry point and consume them in the existing posting transaction. |
| `backend/main.py`, `schemas.py`, `accounts.py`, `request_limits.py` | Authentication throttles/common-password checks, security routing/CORS, access/primary-change events and shared request-abuse limits. |
| `backend/reconcile.py`, `security_retention.py`, `.env.example` | Verify security/financial linkage; preview explicitly operated retention; document safe configuration defaults. |
| `backend/tests/test_security.py`, `payment_support.py`, `test_register.py`, `test_migrations.py` | Dedicated policy/concurrency tests, real-grant regression fixtures and migration/data-isolation checks. |
| `frontend/src/SecurityPanel.tsx`, `securityApi.ts`, `PaymentPinDialog.tsx` | Security settings/activity, typed API calls and masked, cleared PIN confirmation with lockout countdown. |
| `frontend/src/PaymentPanel.tsx`, `api.ts`, `socialApi.ts`, `commerceApi.ts` | Bind approval to the reviewed intent, send the grant in a header and preserve original-key uncertain-outcome recovery. |
| `frontend/src/App.tsx`, `navigation.ts`, `DashboardShell.tsx`, `ConfirmDialog.tsx`, `App.css` | Add settings navigation, focused accessible PIN dialogs and responsive security styling. |
| `frontend/src/Security.test.tsx`, `pinTestHelpers.ts`, existing payment/social/commerce/QR/experience tests | Exercise security UX and adapt existing payment regressions to explicit PIN approval. |
| `frontend/qa/security-browser.mjs`, `security-helpers.mjs`, `isolated_backend.py`, existing browser harnesses | Real PIN-backed Chromium verification with isolated PostgreSQL records and development-data comparisons. |
| `README.md`, `docs/SECURITY.md` | Cohesive setup, architecture, threat model, API instructions and operational limitations. |

## Executed verification — 5 November 2026

| Check | Observed result |
| --- | --- |
| Full PostgreSQL backend suite | **189 passed**, no failures or skips; includes 42 dedicated security tests and 4 migration tests. |
| React suite | **182 passed**. |
| TypeScript, production bundle and ESLint | Passed; `npm run build` invokes `tsc -b` before Vite. |
| Alembic consistency | No new upgrade operations detected at `0008_payment_security`. |
| Reconciliation | Balanced; every reported mismatch/link/invariant list empty in development and isolated browser schemas. |
| Chromium regression harnesses | Authentication/accounts, direct and PNG-upload QR payments, contacts/requests, splits, multiple accounts/self-transfers, recharge/bills, receipts and committed-response retries passed with real PIN grants. |
| Chromium security harness | PIN setup/change, five failures/lockout/recovery, risk/daily blocks, lost-response/re-login recovery, both balances, private events, keyboard dialog containment, logout and five widths (320–1440 px) passed. Uses the explicit QA-only thresholds described in README. |
| README diagrams | All three Mermaid diagrams parsed and rendered in Chromium. |
| Dependency checks | `pip check` passed; `npm audit --omit=dev` reported zero production dependency advisories at execution time. No Python vulnerability-advisory scan was performed. |

Migration upgraded the development database from `0007_bills_recharge` to `0008_payment_security`. Whole-record hashes of **every pre-existing table** matched before/after. The existing 2 users, 2 bank accounts, 3 payments and 6 ledger entries were preserved. All six new security tables were empty afterward: no default PIN, test payment or audit seed was inserted. Retention was previewed only; no pruning ran. Test schemas are separate and retained.

Hardware-camera access, physical-device behavior, screen-reader compatibility, penetration testing and production deployment were not verified. Headless responsive/keyboard checks and real PNG QR upload do not establish those guarantees.
