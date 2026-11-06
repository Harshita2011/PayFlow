# Executed verification and deployment status

Recorded 6 November 2026. These results are local executions, not fabricated GitHub/cloud outcomes. The existing payment/security/reliability implementation was inspected before adding infrastructure. No real bank, telecom or payment integration was introduced.

| Check | Observed result |
| --- | --- |
| Complete PostgreSQL backend suite | **225 passed**, no failures or skips; final independent-signing-key run completed in 422.935 seconds. Includes 13 deployment/configuration/isolation cases plus existing financial/security/concurrency/outbox regressions. |
| Frontend tests | **190 passed** across 14 test files; five new cases validate hosted API configuration. |
| TypeScript / Vite production build / ESLint | Passed, including the final repository-pinned browser helpers. |
| Managed Playwright runner | All five scenarios passed twice locally, including final configuration: registration/login/PIN, funding, direct/PNG QR payments, contacts/requests, split settlement, multiple accounts/self-transfers, recharge/bills, receipts/history, lost-response original-key recovery, lockout/risk/limits, logout and five responsive widths. |
| Worker integration in E2E | Separate real worker processes drained both test-stage queues; all ledgers reconciled and development-record fingerprints matched before/after. |
| Docker images / Compose | Backend/worker and frontend images built; final PostgreSQL/API/worker/frontend healthy, one-shot migration exited 0. Only loopback frontend port 18080 published. |
| Built Compose frontend in Chromium | Registration/login/PIN/account/funding, QR generation, same-origin proxy, CSP/security headers, five widths and logout passed with no browser errors. |
| Local Compose API smoke | Verified principal financial workflows, ownership/PIN enforcement, same-key replay, balances/receipts/history, notifications, non-root processes, restricted worker and reconciliation. |
| Backup / restore | Custom-format dump/checksum, restoration into a NEW uniquely named isolated database, whole-table equality and restored reconciliation passed. Original source preserved; backup/restore database retained. |
| Alembic checks | Existing head `0009_reliability_outbox`; no new schema upgrade needed. Metadata comparison passed; migration-runner lock/expected-revision controls tested. |
| Application, build and CI Python lock audits | No known advisories at execution after patching the old installer; container installer is pip 26.3. |
| npm audit | Zero vulnerabilities after compatible updates and the tested minimatch 11.0.1 override. |
| Bandit | Medium/high application-source gate passed; intentional container binding has a narrowly documented B104 annotation. |
| Gitleaks | Current Git-visible source passed with redacted reporting; private ignored environment files/backups/artifacts are not staged. No broad scanner allowlist. |
| CI/provider files | Workflow YAML and immutable action pinning validated with actionlint; local provider safety checks and YAML/JSON parsing passed. **No GitHub Actions job ran on GitHub.** |
| Original development data | E2E hash comparisons passed; final read-only check found 2 users, 2 accounts, 4 payments, 8 ledger entries, 7 security events and 1 configured PIN. Every reconciliation mismatch list was empty. No development container/volume reset or test payment there. |

The local container runtime was Python 3.11.18 with a separately pinned patched pip installer. PostgreSQL/Node/Nginx/Python base images use recorded SHA-256 digests. Existing local Python development behavior remains supported. GitHub-hosted Linux jobs are prepared but still need actual remote execution after user review/push; local containers do not establish that those jobs passed remotely.

Managed backend and browser launchers generate independent signing keys without modifying development environment files. Synthetic test-user tokens therefore cannot authenticate against the development API.

## Changes and their purpose

| Files | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Read-only, SHA-pinned backend/frontend/security/E2E/container validation; no deployment credentials or publishing. |
| `backend/Dockerfile`, `frontend/Dockerfile`, `.dockerignore` files, `frontend/nginx.conf`, `docker-compose.yml`, `deploy/postgres-init.sh` | Separate persistent local stack, non-root images, private networking, readiness ordering and dedicated DB roles. |
| `backend/requirements*.lock`, `requirements-ci.txt`, `requirements-build.txt`, `tools/lock_python.py` | Exact/hash-checked application, test, installer and CI dependencies. |
| `backend/config.py`, `main.py`, `serve.py`, environment examples | Validated deployment mode/TLS/CORS, secure headers, docs exposure, bounded container entry point and no secrets baked into images. |
| `backend/migrate.py`, `migration_lock.py`, `provision_roles.py`, `migrations/env.py` | Explicit expected-revision migrations, session lock and local role grants; runtime never upgrades schemas. |
| `backend/outbox.py`, `outbox_worker.py`, `worker_health.py` | Minimal worker column reads and bounded heartbeat/progress checks without financial writes. |
| `backend/test_database.py`, `tests/payment_support.py`, `tests/test_deployment.py` | Separate credential support, target guards and deployment regressions. |
| `frontend/qa/*`, `package.json`, `package-lock.json` | Pinned Playwright, managed isolated fixtures/workers, redacted diagnostic traces and built-container UI smoke. |
| `frontend/src/apiConfiguration.ts`, `Deployment.test.ts`, `vite.config.ts`, one deterministic UUID test fixture | Build-time public URL validation, regression coverage and removal of a non-secret scanner false positive. |
| `render.yaml`, `frontend/vercel.json` | Prepared manual-only provider deployment with no database automatically provisioned. |
| `tools/ci_*`, `static_analysis.py`, `secret_scan.py`, `validate_*`, `compose_*`, `deployment_smoke.py`, `init_compose.py` | Guarded local/CI validation, private environment creation, safe smoke and restore exercise. |
| `README.md`, `docs/deployment.md`, `testing.md`, `backup-recovery.md`, `deployment-smoke.md` | Cohesive documentation, runbooks, approval gates and known limits. |

Pre-existing uncommitted reliability work was retained; no unrelated feature reset, commit or push was performed.

## Prepared only / not verified

- Public deployment, real hosted URLs, cloud billing/resource creation, provider-account validation and actual GitHub Actions executions.
- Production failover, PITR/cutover, RPO/RTO guarantees, operating-system/container vulnerability scanning, full Git-history scanning, penetration certification, physical camera/device/screen-reader compatibility.
- Resource capacity beyond previously documented bounded smoke measurements. No million-TPM claim or new sustained stress test.

The local demo is reachable at `http://localhost:18080`; that is **not** a public deployment URL. Hosting requires the explicit user/provider/region/budget decisions and secret/role/network setup in [deployment.md](deployment.md). Proposed recovery objectives are planning goals, not achieved guarantees.
