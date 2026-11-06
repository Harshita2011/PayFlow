#!/bin/sh
set -eu
# Only the new Compose volume runs this script. Do not enable shell tracing.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=owner_password="$PAYFLOW_OWNER_PASSWORD" --set=app_password="$PAYFLOW_APP_PASSWORD" \
  --set=worker_password="$PAYFLOW_WORKER_PASSWORD" <<'SQL'
CREATE ROLE payflow_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'owner_password';
CREATE ROLE payflow_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE ROLE payflow_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'worker_password';
ALTER DATABASE payflow_demo OWNER TO payflow_owner;
ALTER SCHEMA public OWNER TO payflow_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
