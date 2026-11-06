# Backup and recovery runbook

Backups contain private account records, password/PIN hashes, authorization digests and audit history even when money is fictional. Do not commit them, publish artifacts or paste contents into support logs. `backups/` is ignored by Git/build contexts; local tools create new files and refuse overwrite. Encrypt off-host copies and restrict access before adopting any retention schedule.

## Verified local restore exercise

This command supports **only** the verified new `payflow-demo` Compose project. It cannot target `payflow-postgres-5436` or a public database. Its safety gates check Compose labels, fixed source database, generated restore-name pattern, target nonexistence, file exclusivity and checksum. No reset, clean or overwrite option exists.

After the local smoke workflow, quiesce only the owned worker so notification state remains stable for whole-record comparison:

```powershell
docker compose --env-file .env.compose stop worker
python tools/compose_backup.py exercise --output backups/local-verification.dump
docker compose --env-file .env.compose up -d worker
```

Use a new output filename for another exercise. The tool:

1. Computes a read-only snapshot of every source table without printing records.
2. Uses PostgreSQL 16 `pg_dump --format=custom` inside the verified isolated container, capturing binary output directly in Python. This avoids PowerShell text-redirection corruption.
3. Records/verifies SHA-256 and refuses a changed source during the comparison exercise.
4. Creates a new uniquely named `payflow_restore_<uuid>_tests` database; existing targets are never reused.
5. Restores using `pg_restore --no-owner --exit-on-error`, compares every table's records and reconciles the restored ledger.
6. Preserves the source, backup and isolated restore database. It never cuts application traffic over or deletes test-owned data implicitly.

The executed exercise passed checksum verification, complete record equality and restored reconciliation. This demonstrates a local logical restore, not managed-provider failover, power-loss recovery or a measured RPO/RTO guarantee.

## Managed PostgreSQL release backup

Before an approved cloud migration, verify provider backup/PITR status and create a logical backup with a compatible PostgreSQL client. Use `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE` and a private `PGPASSFILE`/provider secret mechanism rather than putting passwords in command arguments. Prefer verified TLS certificates. Do not paste connection strings into logs. Check free disk space, client/server major compatibility and backup encryption/access controls.

`pg_dump` takes a consistent database snapshot; record source environment, schema revision, backup timestamp and checksum separately. Capture binary output to a file through a binary-safe client interface. On older Windows PowerShell, do not pipe binary archives through text redirection. A live dump's table counts may differ from later live reads; that alone does not prove corruption. Validate through an isolated restore and reconciliation.

Proposed retention starting point: encrypted daily copies for seven days and weekly copies for four weeks, adjusted for privacy requirements and cost. Provider PITR/logical-backup retention depends on the purchased plan and must be verified in the account. No cloud backup scheduler, storage bucket or retention deletion job was created.

## Disaster recovery and rollback

1. Freeze risky release activity, preserve original logs/events, and assess whether there is an outage, uncertain commit or accounting mismatch. Do not manually edit ledger/balances.
2. Identify a known backup plus its migration revision and checksum. Confirm the current database is not the intended restore target.
3. Provision a **new isolated database/instance** only after approval of resources and restore scope. Never restore over the current development/production database without explicit separate approval.
4. Restore, validate roles/ownership/TLS and compare schema revision with compatible application code. Apply only reviewed forward migrations under the deployment lock.
5. Run complete reconciliation, sample participant-only receipts/history, inspect request/split/service links and outbox state. Already delivered events may replay; retain stable IDs and consumer deduplication.
6. Determine which commits occurred after the backup and whether acknowledged payments would be lost. Prefer provider PITR/WAL recovery when available; do not announce successful recovery without accounting for that gap.
7. Approve a controlled connection-string cutover. Keep the original database intact for investigation and an explicitly planned reversal. Protect against two writable primaries/split brain.
8. Verify live/ready probes, PIN/authentication, a disposable simulated payment, idempotency, worker progress and reconciliation. Record observed recovery time and data-loss window.

**Proposed demo objectives:** RPO at most 24 hours with daily backups, RTO four hours after an approved restore decision. These are planning objectives, not measured guarantees; a public release needs a provider-specific drill and cost/retention decisions. Preserve signing secrets appropriately—restoring data while silently rotating the JWT secret changes session behavior. Never assign default passwords or PINs during recovery.
