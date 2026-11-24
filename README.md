# Tenant Ledger API — Flask + PostgreSQL

Multi-tenant money-movement backend built with Python 3.11+, Flask, SQLAlchemy 2, PostgreSQL and pytest.

## Run locally

```bash
docker compose up -d db
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg://ledger:ledger@localhost:5432/tenant_ledger"
python create_demo.py
python run.py
```

API base URL: `http://127.0.0.1:5000`. Use `X-API-Key: demo-write-key` for writes, `demo-read-key` for read-only access, and `demo-admin-key` for admin access. Demo keys are local-development credentials only.

## Endpoints

- `POST /v1/transactions/import` — 1-1000 rows; valid rows accepted independently; invalid rows returned with row-level errors.
- `GET /v1/clients/{client_ref}/transactions` — tenant-scoped history with date filters and stable pagination.
- `GET /v1/clients/{client_ref}/balance?as_of=YYYY-MM-DD&currency=USD` — point-in-time balance in integer minor units.
- `GET /v1/clients/{client_ref}/monthly-summary?year=2026&month=11&currency=USD` — SQL-aggregated inflows, outflows, fees and net change.
- `POST /v1/transactions/{id}/correct` — append reversal and replacement; never updates/deletes original row.
- `GET /v1/audit` — tenant-scoped audit events.
- `GET /health` — health check.

## Design and security

- API keys are stored as SHA-256 digests and each key belongs to one tenant.
- Every tenant-owned query is scoped by `tenant_id`; client references are opaque and unique per tenant.
- Amounts use integer minor units; currencies are not silently converted.
- Database uniqueness on `(tenant_id, idempotency_key)` protects against duplicate posting.
- Savepoints isolate bad import rows.
- Corrections append a reversal at the original effective date and a replacement at the requested date.
- Transfers are represented as outgoing movements for this single-client ledger. A paired debit/credit transfer endpoint is a production extension.

## Production follow-ups

Use Alembic migrations rather than `create_all`, key rotation/revocation, per-tenant rate limits, structured logging, backups/PITR, PostgreSQL row-level security and concurrency/load tests. Do not use demo keys in production.
