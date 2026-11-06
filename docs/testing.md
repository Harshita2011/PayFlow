# Test and CI workflow

The repository uses Python unittest + real PostgreSQL, Vitest/React Testing Library and Playwright Chromium. Existing suites cover authentication/accounts, ownership, exact money, concurrent/idempotent payments, QR, requests, splits, service fulfillment, PIN/limits/risk/audit, outbox delivery and recovery. Deployment tests add configuration, exact CORS/headers, role separation, migration-runner serialization and database-target guards. Tests never reset development tables.

## Reproducible dependencies

Install Python 3.11 runtime/test dependencies from `backend/requirements.lock` / `requirements-dev.lock` with `pip install --require-hashes -r ...`. The patched installer has its own `requirements-build.lock`; optional security tooling is pinned in `requirements-ci.lock`. Exact transitive versions come from the tested environment; published PyPI artifact digests are recorded by `tools/lock_python.py`. Regenerate only after installing/reviewing intended inputs and rerun all checks. Linux image builds verified these locks; they are not a universal Python-version lock.

Run `npm ci` in `frontend`. Playwright is exact-pinned in the lock and needs its matching browser: `npx playwright install chromium` (Linux CI also installs OS dependencies). A narrow `minimatch` 11.0.1 override addresses the current glob-amplification advisory in lint dependencies; lint/build/tests validate compatibility. No audit findings were suppressed or lint rules disabled to obtain a pass.

## PostgreSQL isolation

The default payment target is `payflow_phase4_tests`; an alternative name must match `payflow_*_tests` and differ from `DATABASE_URL`'s database. `PAYFLOW_ENV=demo` refuses test setup. There is no database-reset command.

For separate test credentials, provision a new isolated database and set `PAYFLOW_TEST_DATABASE_URL` to its dedicated role plus the exact declared name. This branch requires no CREATEDB privilege. The test role must own that test database and be able to create its own schemas, functions and tables. Without an explicit URL, local fixtures create the verified separate database once using the developer connection; this preserves the existing local workflow but requires CREATEDB. A remote explicit test database still requires deliberate operator provisioning—never reuse production credentials or a production URL.

Automatic derivation is restricted to loopback or the local `postgres` service hostname. A remote connection must provide an explicit isolated test URL; the helper will not silently create a test database on a remote application server.

`backend/.env.test.example` describes an independent test environment; actual `.env.test` is ignored and is not implicitly loaded over a real `.env`. Export its settings deliberately in a separate test terminal. Authentication/migration fixtures use outer rollback transactions; committed payment tests use fresh named schemas retained in their separate database. Legacy regression fixtures obtain real PIN grants and explicitly relax demo risk thresholds in that fixture process; security tests and default browser tests enforce real defaults.

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
$env:REGISTER_TEST_POSTGRES='1'
$env:PAYFLOW_TEST_DATABASE='payflow_ci_local_tests'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m migrate
.\.venv\Scripts\python.exe -m reconcile
```

The last two commands check the explicitly configured application database read-only; they do not restore/reset it. Unset test environment variables before returning to normal development.

## Frontend and E2E

```powershell
Set-Location frontend
npm ci
npm test
npm run build
npm run lint
npx playwright install chromium
$env:PAYFLOW_TEST_DATABASE='payflow_ci_e2e_local_tests'
npm run test:e2e
```

The orchestrator starts only owned processes on dedicated loopback ports **5180 and 18016**, refuses occupied ports, creates fresh test schemas and runs a separate real outbox worker. Four regression scripts cover all principal flows and responsive widths; a fifth security script uses a fresh fixture with explicit test-only short lockout/daily/risk thresholds. The worker must drain, each ledger must reconcile, and application-database fingerprints must remain unchanged before shutdown. The original localhost:8001 API and developer Vite port 5173 are not targets.

The managed browser runner generates an independent ephemeral JWT key, so its synthetic-user tokens cannot authenticate against the development API. For the same protection in local backend runs, launch from the repository root with `.\backend\.venv\Scripts\python.exe tools/run_backend_tests.py`; it selects test mode, keeps database safety guards and never overwrites a dotenv file or prints its signing key. CI already generates job-specific keys independently.

`PAYFLOW_PYTHON` selects the interpreter (default local backend venv; CI uses `python`). No fixture administrative route is mounted in production `main.py`. QA stop/check endpoints exist only in the isolated script and require a per-run random key. No public deployment or development database receives test payments.

Diagnostic artifacts are ignored under `test-artifacts/e2e`. Failure capture masks form inputs. The trace is a **redacted JSON route/status timeline**, not a raw Playwright network archive: raw traces can contain bearer tokens, PIN bodies and session state and are intentionally not uploaded. CI uploads only screenshots from synthetic contexts and redacted timelines on failure, with three-day retention; never publish server logs, cookies, storage state, backups or environment dumps.

## GitHub Actions

`.github/workflows/ci.yml` triggers pushes to main/master/codex branches, pull requests and manual validation. Jobs run backend PostgreSQL tests/migrations/reconciliation; frontend tests/build/lint; dependency/secret/static/workflow checks; isolated E2E; and Docker startup/smoke/restore. All actions use verified commit SHAs, checkout does not persist credentials, workflow permission is contents-read, and no cloud/deployment secrets are available to fork pull requests. Jobs have bounded timeouts and dependency caching.

The service PostgreSQL password in CI is explicitly ephemeral and job-local, not a deployment secret. A new JWT key is generated per job without printing it; tests use a dedicated non-superuser role/database. The workflow does not push commits/images, deploy services or grant production credentials.

**Local workflow validation is not a GitHub execution.** `tools/validate_ci.py` uses PyYAML plus checksum-pinned actionlint. It validates syntax/pinning locally; the workflow still needs to run on GitHub after the user reviews and pushes changes. Provider configuration is prepared only.

## Security checks

```powershell
Set-Location D:\PayFLow
.\backend\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements-ci.lock
.\backend\.venv\Scripts\python.exe -m pip_audit --require-hashes -r backend/requirements.lock
.\backend\.venv\Scripts\python.exe tools/static_analysis.py
.\backend\.venv\Scripts\python.exe tools/secret_scan.py
.\backend\.venv\Scripts\python.exe tools/validate_ci.py
.\backend\.venv\Scripts\python.exe tools/validate_deployment.py
npm audit --prefix frontend --audit-level=moderate
```

Bandit gates medium/high severity application-source findings, excluding generated artifacts, virtual environments and test fixtures. Its one explicit B104 annotation documents the intentional container listener; network exposure is controlled by ingress/Compose. Gitleaks scans Git-visible current working files in a staging directory, redacts findings and refuses tracked private dotenv files. It does not scan ignored local secrets or rewrite Git history. One false-positive random idempotency UUID fixture was replaced with an obvious deterministic valid UUID; no broad scanner allowlist was added.

Audit results are point-in-time, not certification. Container OS scanning, full Git-history secret scanning, penetration testing, physical camera/screen-reader tests and actual cloud verification remain additional release-review work. See [deployment](deployment.md) and [backup/recovery](backup-recovery.md).
