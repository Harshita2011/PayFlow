# A measured path toward 1 million transactions per minute

**Design target, not achieved capacity:** 1,000,000 / 60 = 16,666.67 successful new financial postings/second sustained; a hypothetical 3× peak is 50,000 TPS. Replayed receipts, HTTP reads, rejected requests and PIN checks are not new financial transactions. Implemented and measured behavior is documented separately in [reliability](reliability.md) and [performance](performance.md).

## Current boundary and write amplification

The implementation uses one authoritative PostgreSQL transaction with deterministic owner/account locks, exact amounts, deferred ledger/cache/link constraints, durable scoped retries, one-time grants and same-transaction outbox events. There is no broker-driven debit, Redis balance or cross-database transfer.

A typical successful transfer writes at least a payment, two journal entries, two cached balances, an idempotency result, consumed grant, daily counter, risk decision, audit record, submission-rate row and outbox row: roughly 13 logical row writes, before grant issuance, index/WAL/full-page amplification, triggers, replicas or asynchronous participant notifications. Funding, requests, splits and services differ. At 16,667 TPS that illustrative lower-order estimate is about 217,000 logical row writes/sec; at 50,000 TPS about 650,000. This is a planning calculation, not measured disk I/O. A sustained target is 1.44 billion postings/day and at least 2.88 billion journal rows/day, making retention, indexes, backups and reconciliation first-class design problems.

## API and database scaling

Start with stateless independently scraped API processes behind a load balancer, bounded per-instance pools, shared database-backed security/idempotency, and reserved database/admin connections. Scale application concurrency only while database lock/CPU/WAL/storage headroom remains. Argon2 is intentionally expensive; PIN authorization CPU and memory require separate capacity tests. Reusing an already consumed grant for a different payment is not an acceptable performance shortcut.

Use representative storage with fsync and synchronous commit enabled, sufficient RAM, measured NVMe/WAL throughput and explicit replica durability/RPO policy. Hardware sizing cannot be inferred from laptop smoke results. A low-latency multi-AZ quorum has different commit costs from localhost Docker. Document every test's CPU, RAM, storage, version, pool count, workers, security settings, replication and dataset. Read replicas may serve explicitly stale activity/history, never authoritative spend checks, grant consumption or idempotent result recovery.

Prioritize profiles of statement count, lock hold times, WAL bytes/payment, trigger scans, account fan-in, security writes and query plans. Existing deferred cached-bank-balance aggregates need measured redesign before very large account histories; funding/settlement also concentrates writes in shared journal indexes, without a mutable internal bank-balance row. Do not disable accounting checks to advertise TPS. Proposed incremental invariants would need formal accounting rules, migration/backfill validation and independent reconciliation tests first.

## Hot accounts and internal settlement

User fan-in still serializes cached recipient balance updates; many requests from one sender serialize source/owner policy. Recharge and bills use internal ledger-only settlement accounts with no public user/cached bank balance, but shared journal indexes and aggregate checks can still contend and grow expensive. Current tests cover two concurrent purchases, not a safe 50,000-TPS settlement model.

Proposed settlement lanes would use deterministic routing (e.g. hash of immutable payment ID to K fixed internal ledger identities), require each purchase to debit one owned source and credit exactly one validated lane, and reconcile per-lane and aggregate merchant totals. No periodic aggregation may create/destroy money or conceal duplicate payment IDs. Lane selection and lane count/version must be immutable per posting. Existing historical settlement identities must remain queryable. This schema/routing change is **not implemented**; evidence, invariants, migration strategy and approval precede it.

## Partitioning tradeoffs

Time partitioning journal/history can bound scans and index maintenance, but PostgreSQL partitioned unique keys generally need the partition key. Existing globally unique payment IDs, `(user_id,key)` retry scope, ledger/payment FKs and grant/request/receipt links must retain their meaning. Merely partitioning by timestamp can weaken global deduplication or break references.

The [PostgreSQL 16 partitioning limitations](https://www.postgresql.org/docs/16/ddl-partitioning.html) explain the partition-key requirement for unique/primary-key constraints; design a globally unique identity contract before changing this schema.

Possible design: a small global identity/idempotency registry plus time-routed immutable posting partitions, with explicit identity-to-partition mapping. Its registry can become a new hotspot. Late events, UTC boundaries, foreign keys, index build lock time, archival queries, backup restores and per-partition/global reconciliation need tests. Retention cannot drop financial partitions while obligations or regulatory/audit requirements still reference them. No existing table is repartitioned or dropped by this implementation.

## Account-based sharding: proposal only

Co-locating an account's balance and journal on an owner shard preserves local serializability. A transfer spanning shards is **not automatically atomic**; two independent commits are unsafe. A production design would need an explicitly specified distributed settlement protocol, not a new HTTP endpoint that debits then hopes to credit.

One research option is durable escrow/reservation with a globally unique transfer/coordinator record:

1. `INITIATED`: persist immutable parties, amount, shard versions and request fingerprint.
2. `RESERVED`: source shard atomically reserves available funds in a ledger-backed escrow and records the transfer ID. A reservation is not a final recipient credit.
3. `DESTINATION_PREPARED`: destination durably records readiness and a unique incoming settlement ID, without spendable duplicate credit.
4. A durable coordinator decides `COMMIT` or `ABORT` exactly once, using consensus-backed recovery/ownership epochs.
5. Each shard idempotently applies that durable decision with matching inter-shard clearing entries. `SETTLED` requires both acknowledgments and reconciliation.
6. `RECOVERY_REQUIRED` means the decision is unknown/unacknowledged. Query/recover the coordinator; never guess failure from a timeout and independently release escrow after a commit decision.

An abort before a durable commit releases the reservation through an auditable compensating accounting entry; it does not erase history. After commit, refund/reversal is a separate authorized posting. Test coordinator loss, duplicate messages, reordered acknowledgments, shard failover, epoch fencing, split brain, partial partitions and offline reconciliation. Define spendability, exactly which balances are authoritative, liveness under partitions and customer-visible pending states formally. This is substantially more complex than the current single-database atomic contract, and is **not implemented or approved as a money model**.

## Recovery and event streaming

Current recovery is scoped request-key replay after PostgreSQL rollback/commit; outbox workers use expiring fenced leases and idempotent notification inserts. Future streaming should publish committed outbox IDs after commit, preserve ordering only where explicitly required, use consumer deduplication/inbox state, backpressure and dead-letter tooling. A broker must never independently authorize/debit accounts. Broker offsets alone do not create end-to-end exactly-once financial effects.

Recovery objectives require measured backup/restore/PITR drills, WAL retention and replica promotion fencing. Before declaring high availability, test acknowledged-commit survival against the chosen replication mode, failover split-brain prevention and consistency of retry/grant records with the ledger.

## Capacity milestones and acceptance gates

| Milestone | Evidence required before advancing |
| --- | --- |
| Bounded 10 TPS target | Real mixed financial traffic, PIN/security enabled, new commits counted from database, no ledger mismatch, disclosed short duration and errors. |
| 50 / 100 TPS | Explicit resource budget/approval, multiple actors/accounts, realistic hot/cold distribution, bounded latency/error SLOs and outbox lag; avoid per-user demo caps being mistaken for DB capacity. |
| 500 / 1,000 TPS | Dedicated load generator and production-like durable storage, multi-instance evidence, stable pool/WAL/lock metrics, representative accumulated history. |
| 5,000 / 10,000 TPS | Distributed load generators, failover/recovery tests under load, schema/trigger cost validated, representative skew and security write amplification. |
| 16,667 sustained / 50,000 peak | Explicit test duration and SLO, sustained resource/replication headroom, realistic failure/peak recovery and queue drain, reproducible end-to-end reconciliation. A momentary sampled peak is insufficient. |

No milestone beyond the recorded bounded smoke measurements is claimed. Define an SLO before capacity testing (for example, agreed p95/p99 and non-policy error budgets); do not present an illustrative SLO as an achieved result. Saturated closed-loop clients understate offered load; use arrival-rate workloads and coordinated-omission-aware latency analysis at later gates. Load generators must not share the API host for serious capacity results. Never send stress traffic to a public deployment without authorization.

## Monitoring, assumptions and risks

Correlate API tail latency/error/replay rates with pool saturation, database CPU/IO/WAL, lock waits/deadlocks, replication lag, trigger cost, grant/rate denials and oldest outbox age. Sample committed TPS independently from receipts; deduplicate replay traffic. Monitor hot-account concentration, not only global averages. Include incident runbooks for uncertain commits, unavailable security state, dead letters and stale leases.

Current limitations include one primary database, small demo budgets, no database-role provisioning, no distributed tracing collector, no production alerting/failover/backup orchestration, local per-process request metrics, and a single-threaded local delivery loop per worker. These are explicit future engineering tasks, not capabilities supplied by adding Kafka/Redis or increasing API workers.
