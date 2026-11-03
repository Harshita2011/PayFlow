# PayFlow — Phase 2 authentication

PayFlow is a local UPI payment **simulation** for learning. Phase 2 implements
registration → login → JWT access token → protected profile → client-side logout.
It does not process real money.

## Run locally (PowerShell)

Backend, in one terminal:

```powershell
cd D:\PayFLow\backend
docker start payflow-postgres-5436
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001
```

Keep your existing `backend/.env` database connection. Local JWT settings were
added without replacing that connection or an existing signing key. The signing
key is random and is never printed by application code.

For a fresh checkout, use `backend/.env.example` as a template and supply your
own database credentials. Generate a key directly into the local `.env` without
printing it (run this **only when configuring a new signing key**):

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import secrets; p=Path('.env'); f=p.open('a', encoding='utf-8'); f.write('\nJWT_SECRET_KEY='+secrets.token_urlsafe(48)+'\nACCESS_TOKEN_EXPIRE_MINUTES=15\n'); f.close()"
```

Never commit `.env`. Changing a signing key invalidates tokens signed with the
previous key. `ACCESS_TOKEN_EXPIRE_MINUTES` accepts integers from 1 to 60 and
defaults to 15. A missing/short signing key prevents startup instead of silently
using a public default. No table creation, schema changes, data deletion, or
database resets happen at application startup. This project expects the existing
`users` table.

Frontend, in another terminal:

```powershell
cd D:\PayFLow\frontend
npm install
npm run dev -- --port 5173 --strictPort
```

Open http://localhost:5173. The default API address is http://localhost:8001.
To change it, copy `frontend/.env.example` to `frontend/.env.local`, edit
`VITE_API_BASE_URL`, then restart Vite. `VITE_` settings are public browser
configuration: never put a signing key or database credentials there.

Use Ctrl+C in each terminal to stop its server. If an older server is already
running, stop that server and restart it to load the new dependencies/settings.

## Files and important code

| File | Role and changes |
| --- | --- |
| `backend/main.py` | Preserves registration and health checks. Adds JSON `POST /login`, protected `GET /me`, safe database error responses, and `Cache-Control: no-store` on authentication responses. CORS still permits only the two local Vite origins, now including POST and the Authorization header. |
| `backend/schemas.py` | `LoginRequest` shares email normalization with `RegisterRequest`. Registration keeps its 8–128-character password and trimmed 1–100-character name requirements. Login accepts 1–128 characters so wrong passwords can receive generic credential errors. `TokenResponse` describes the login response. `UserResponse` permits only public profile fields. Extra request fields are rejected. |
| `backend/security.py` | Owns Argon2id hashing, a random dummy hash for unknown-email checks, JWT creation, and the `get_current_user` dependency. `HTTPBearer(auto_error=False)` lets the app return a consistent 401 for missing or invalid authorization. |
| `backend/config.py` | Loads `.env` beside the module, validates the signing key and configured expiry, and keeps the existing DATABASE_URL setting. |
| `backend/requirements.txt` | Adds maintained PyJWT 2.x for JWT signing and verification. |
| `backend/.env.example` | Safe configuration template; has placeholders and no signing secret. |
| `backend/.env` (local only) | Adds a generated key and expiry when absent; keeps the existing database configuration. Ignored by Git. |
| `backend/tests/test_register.py` | Keeps registration coverage, shares its isolated database fixture with auth tests, and checks safe 503 responses for other database constraints. |
| `backend/tests/test_auth.py` | Covers login, generic errors, token issuance, claims, expired/tampered/malformed tokens, missing authorization, profile privacy, nonexistent users, CORS, and safe database failures. |
| `frontend/src/api.ts` | One API base URL and fetch helper. Defines response types, sends JSON/Bearer headers, disables caching, times out requests after 10 seconds, and turns network/API failures into readable messages. |
| `frontend/src/useAuth.ts` | Small React hook holding the token, public user, and expiry **in memory**. Loads `/me` after login, clears sessions on expiry/401, and ignores profile responses from a logged-out session. |
| `frontend/src/App.tsx` | Registration/login forms, confirmation checks, required fields, loading/disabled states, feedback, profile refresh, logout, and the existing backend check. Passwords are read from the form rather than stored in persistent browser storage. |
| `frontend/src/App.css`, `src/index.css` | Responsive interface, shared field/button styling, visible keyboard focus, feedback, and mobile layout. |
| `frontend/index.html` | PayFlow page title and description. |
| `frontend/.env.example` | Public API-address template. |
| `frontend/package.json`, `package-lock.json` | Add the test script and development-only Vitest, Testing Library, and jsdom dependencies. No frontend runtime library was added. |
| `frontend/vitest.config.ts`, `src/test-setup.ts` | DOM test environment and cleanup of rendered components, fetch mocks, spies, and timers between tests. |
| `frontend/src/App.test.tsx` | Exercises registration/login/profile/logout, confirmation, duplicate-email and credential errors, network failure, disabled forms, expiry, rejected tokens, late requests, and losing authentication on page remount. |
| `.gitignore` | Keeps local secrets, virtual environments, caches, dependencies, and generated builds out of source control. Allows `.env.example` templates. |
| `README.md` | This runbook, request-flow explanation, manual checks, test instructions, and limitations. |

`models.py` and `database.py` are reused without changes; no migration is needed.

## How requests work

### Registration

1. React checks confirmation, required fields, email syntax, and length limits.
   Browser checks improve usability; backend validation is authoritative.
2. `registerUser()` sends JSON to `POST /register`.
3. Pydantic validates fields, trims the name, and lowercases the normalized email.
4. `Depends(get_db)` supplies a SQLAlchemy session. A parameterized `SELECT`
   checks the normalized email. An existing email returns 409.
5. Argon2id generates a salted password hash. Only that hash is assigned to the
   existing `User.password_hash` column.
6. `db.add()` stages the insert; `db.commit()` writes it to PostgreSQL through
   SQLAlchemy and psycopg. `db.refresh()` loads the generated ID/timestamp.
7. `response_model=UserResponse` filters out the password hash. React displays
   success and switches to login; registration does not sign in automatically.

Two requests may both pass the initial email lookup. The existing database unique
constraint remains the final safeguard. A PostgreSQL uniqueness error triggers
`db.rollback()` and a 409. Other SQLAlchemy failures become a generic 503 rather
than returning SQL, connection strings, or exception details. Validation errors
omit submitted values, including passwords and malformed JSON bodies.

### Login and password verification

1. React sends `{ "email": "...", "password": "..." }` to `POST /login`.
2. The backend normalizes the email and reads the corresponding `User`.
3. `password_hasher.verify()` checks the submitted password against the stored
   Argon2id hash. It does not decrypt the stored value. For an unknown email, a
   dummy verification reduces timing differences.
4. Unknown emails and incorrect passwords both return 401 with
   `Invalid email or password`. No password/hash is returned.
5. A valid login returns `access_token`, `token_type: "bearer"`, and
   `expires_in` in seconds. This login response necessarily contains the token;
   it must not be logged, copied into URLs, or displayed in the application UI.

### JWT creation and protected profile

The server signs with HS256 and `JWT_SECRET_KEY`. Tokens contain the stable user
ID as string `sub`, issue time `iat`, expiry `exp`, issuer `iss`, audience `aud`,
and `token_use: "access"`. They contain no name, email, or password. A JWT is
signed, not encrypted: anyone holding it can read its claims.

After login, React calls `GET /me` using `Authorization: Bearer <access_token>`.
`get_current_user()` verifies the signature with a fixed algorithm allowlist,
expiry, required claims, issuer, audience, token purpose, and valid database ID.
It then reads that user from PostgreSQL and returns public fields. Missing,
expired, tampered, malformed, or unknown-user tokens return 401 with a Bearer
challenge. The dependency checks the database on every profile request rather
than trusting token claims as current user data.

### Authentication state and logout

`useAuth()` stores the token only in React memory. The UI shows a profile only
after `/me` succeeds. Refreshing or closing the page loses authentication. There
is no localStorage, sessionStorage, token cookie, or token in the URL.

The Log out button clears local session state and user details. A late profile
request cannot restore a logged-out session. A timer signs out at the configured
expiry; a 401 from `/me` also clears authentication.

**Client-side logout does not revoke the JWT on the server.** A previously copied
token remains usable until it expires. There is deliberately no misleading
server logout endpoint, refresh token, or production session system in Phase 2.
Memory storage reduces persistence after navigation but does not prevent active
XSS from accessing a running application's credentials.

## Test each endpoint through FastAPI /docs

Open http://localhost:8001/docs with the backend and database running.

1. Expand `GET /health` → **Try it out** → **Execute**: expect 200/healthy.
2. Execute `GET /db-health`: expect 200/connected.
3. Expand `POST /register` and submit a fresh email:

   ```json
   {
     "full_name": "Harsh Kumar",
     "email": "harsh@example.com",
     "password": "Learning-PayFlow-2026!"
   }
   ```

   Expect **201** and only `id`, `full_name`, `email`, `created_at`.
   Repeat it (including a differently capitalized email): expect **409**.
   Try a blank name, bad email, or password shorter than 8: expect **422**.
4. Expand `POST /login` and submit the same email/password, without full_name:

   ```json
   { "email": "harsh@example.com", "password": "Learning-PayFlow-2026!" }
   ```

   Expect **200** and a Bearer access token. A wrong password/unknown email
   returns **401** with the same generic message.
5. Before authorizing, execute `GET /me`: expect **401**.
6. Click **Authorize** in the docs. Paste only the access-token value into the
   HTTPBearer field (the docs add `Bearer`), then authorize and close the dialog.
   Execute `GET /me`: expect **200** and the public profile.
7. Replace the token with `invalid-token`: expect **401**. For expiry, temporarily
   configure `ACCESS_TOKEN_EXPIRE_MINUTES=1`, restart the backend, log in again,
   wait over a minute, and call `/me`: expect **401**. Restore 15 afterward.
8. Use the docs' **Authorize → Logout** action to clear its saved authorization.
   This changes only the docs browser state and does not revoke the token.

Successful manual registrations create real local user rows. These instructions
do not delete them. Swagger's token display is a developer tool; treat it as
sensitive and avoid sharing screenshots of login responses.

## Test the frontend manually

1. Open http://localhost:5173 and choose **Create account**.
2. Submit mismatched passwords: an error appears without making a registration
   request. Correct them and use a fresh email: success switches to sign in.
3. Try a wrong password: a generic error appears. Sign in correctly: the profile
   shows name, email, ID, and membership date.
4. Click **Refresh profile**: a protected `/me` request appears in the browser's
   Network panel with its Bearer header. Do not share that header.
5. Click **Log out**: the profile disappears. Reload while logged in: the login
   form returns because tokens are in memory only.
6. Check the layout at phone width. Use the keyboard to navigate form fields.
7. Stop the backend and submit a form: readable feedback appears and the form
   becomes available again. Restart the backend to continue.
8. **Check Backend** still calls `/health` and shows backend connectivity.

## Automated tests

From `D:\PayFLow\backend`:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

The default suite creates isolated in-memory SQLite databases. The one test
specific to PostgreSQL uniqueness errors is skipped in this mode.

To run the full suite against the configured PostgreSQL database:

```powershell
$env:REGISTER_TEST_POSTGRES = '1'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
Remove-Item Env:REGISTER_TEST_POSTGRES
```

Each PostgreSQL test owns an outer transaction and uses session savepoints. Test
inserts/updates are rolled back; no existing users are deleted, reset, or committed
over. PostgreSQL sequences can still advance during rolled-back inserts, so gaps
in user IDs are normal. No tables/containers/volumes are dropped.

From `D:\PayFLow\frontend`:

```powershell
npm test
npm run build
npm run lint
```

React tests mock fetch and exercise real forms/state; they never access your
database. `npm run build` runs TypeScript checks before creating the production
bundle. No test prints live credentials or tokens.

Executed during implementation: **23 PostgreSQL backend tests passed**,
**10 frontend tests passed**, production build/type checks passed, ESLint passed.
The PostgreSQL saved-user count was unchanged before/after the suite.

A real Chromium browser also completed registration → invalid login → valid
login → protected profile → refresh → logout → reload against a temporary API
using an outer PostgreSQL transaction. Confirmation validation, memory-only
storage, mobile overflow, and the backend-check button passed with no page errors.
The temporary API and frontend servers were stopped afterward; test user rows
were not saved. Desktop and phone layouts were visually inspected.

## Local-development security limits

- Use HTTPS in production; localhost HTTP is acceptable only for local work.
- CORS remains restricted to `http://localhost:5173` and
  `http://127.0.0.1:5173`. CORS is a browser policy, not authentication.
- Short-lived tokens limit exposure, but there is no revocation list, refresh
  token, multi-device session management, or server-side logout.
- There is no login throttling, abuse protection, email verification, recovery,
  or MFA. Add those before any public deployment. Registration's explicit 409
  also reveals whether an email is registered, as requested for this exercise.
- Never log passwords, hashes, Authorization headers, or login responses.
  Production monitoring must redact them, including database error parameters.
- The local `.env` is ignored, but environment files still require appropriate
  filesystem access controls. Use a managed secret store for deployment.
- The existing ESLint dependency chain reports 12 moderate development-only
  audit warnings. The production dependency audit reports 0 vulnerabilities.
  No forced/breaking dependency downgrade was applied. Starlette currently emits
  an httpx TestClient deprecation warning; the tests still pass.
- Future work includes deliberate migration management, rate limits, verified
  email, and a reviewed session strategy. No payments or banking features were
  added in this phase.

References: [FastAPI password hashing and JWT tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
and [PyJWT claim verification](https://pyjwt.readthedocs.io/en/stable/usage.html).
