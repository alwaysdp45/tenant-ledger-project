1. Chosen scope: row-level bulk import, idempotency, tenant isolation, point-in-time balances, monthly summaries, append-only corrections and audit events.
2. PostgreSQL is the runtime database; tenant-scoped unique constraints and composite indexes support correctness and common access patterns.
3. Money uses integer minor units and currencies remain separate; unsupported currencies, future dates and sub-cent amounts are rejected.
4. Corrections append a reversal at the original effective date plus a replacement at the requested date; original rows are never edited or deleted.
5. Transfers are represented as outgoing movements in this single-client ledger; paired double-entry transfers, FX, exports, anomaly detection and rate limiting were deferred to keep the one-hour implementation focused.
6. At 100x load, consider batch inserts, bounded background imports, PgBouncer/pool tuning, date partitioning and PostgreSQL row-level security; benchmark before adopting.
