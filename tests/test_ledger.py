from datetime import date, timedelta
from .conftest import auth

def row(key="tx-1", client="client-1", kind="deposit", amount=100.25, currency="USD", day=None):
    return {"client_ref": client, "transaction_type": kind, "amount": amount, "currency": currency,
            "effective_date": (day or date.today()).isoformat(), "idempotency_key": key}

def test_partial_import(client):
    response = client.post("/v1/transactions/import", json={"rows": [
        row(), row("tx-2", kind="withdrawal", amount=20), {**row("bad"), "amount": -1},
        row("future", day=date.today() + timedelta(days=1)),
    ]}, headers=auth()).get_json()
    assert response["accepted_count"] == 2 and response["rejected_count"] == 2

def test_duplicate_import_is_idempotent(client):
    payload = {"rows": [row()]}
    client.post("/v1/transactions/import", json=payload, headers=auth())
    result = client.post("/v1/transactions/import", json=payload, headers=auth()).get_json()
    balance = client.get("/v1/clients/client-1/balance", headers=auth()).get_json()
    assert result["accepted_count"] == 0
    assert balance["balance_minor"] == 10025

def test_tenant_isolation(client):
    client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth("key-a"))
    assert client.get("/v1/clients/client-1/balance", headers=auth("key-b")).status_code == 404

def test_read_only_key_cannot_write(client):
    response = client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth("key-read"))
    assert response.status_code == 403

def test_balance_and_monthly_summary(client):
    client.post("/v1/transactions/import", json={"rows": [row(), row("fee-1", kind="fee", amount=5)]}, headers=auth())
    balance = client.get("/v1/clients/client-1/balance", headers=auth()).get_json()
    summary = client.get(f"/v1/clients/client-1/monthly-summary?year={date.today().year}&month={date.today().month}", headers=auth()).get_json()
    assert balance["balance_minor"] == 9525
    assert summary["inflows_minor"] == 10025
    assert summary["outflows_minor"] == 500
    assert summary["fees_minor"] == 500

def test_correction_preserves_history(client):
    result = client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth()).get_json()
    original_id = result["accepted"][0]["transaction_id"]
    correction = client.post(f"/v1/transactions/{original_id}/correct", headers=auth(), json={
        "replacement_type": "deposit", "replacement_amount": 90, "replacement_currency": "USD",
        "effective_date": date.today().isoformat(), "idempotency_key": "correction-1", "reason": "Wrong source amount"})
    assert correction.status_code == 200
    assert correction.get_json()["history_preserved"] is True
    entries = client.get("/v1/clients/client-1/transactions", headers=auth()).get_json()
    balance = client.get("/v1/clients/client-1/balance", headers=auth()).get_json()
    assert len(entries) == 3 and balance["balance_minor"] == 9000

def test_unknown_key_rejected(client):
    assert client.get("/v1/audit", headers=auth("invalid")).status_code == 401

def test_second_correction_rejected(client):
    result = client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth()).get_json()
    entry_id = result["accepted"][0]["transaction_id"]
    body = {"replacement_type": "deposit", "replacement_amount": 90, "replacement_currency": "USD",
            "effective_date": date.today().isoformat(), "idempotency_key": "fix-1", "reason": "Fix original"}
    assert client.post(f"/v1/transactions/{entry_id}/correct", json=body, headers=auth()).status_code == 200
    body["idempotency_key"] = "fix-2"
    assert client.post(f"/v1/transactions/{entry_id}/correct", json=body, headers=auth()).status_code == 409

def test_client_reference_can_repeat_across_tenants(client):
    assert client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth("key-a")).get_json()["accepted_count"] == 1
    assert client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth("key-b")).get_json()["accepted_count"] == 1

def test_subcent_amount_rejected(client):
    result = client.post("/v1/transactions/import", json={"rows": [row(amount=1.001)]}, headers=auth()).get_json()
    assert result["rejected_count"] == 1

def test_audit_events_are_tenant_scoped(client):
    client.post("/v1/transactions/import", json={"rows": [row()]}, headers=auth("key-a"))
    assert len(client.get("/v1/audit", headers=auth("key-a")).get_json()) == 1
    assert len(client.get("/v1/audit", headers=auth("key-b")).get_json()) == 0
