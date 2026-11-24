from datetime import date
import hashlib
import json

from flask import Blueprint, current_app, request, jsonify
from sqlalchemy import select, func, case
from sqlalchemy.exc import IntegrityError

from .models import ApiKey, Client, LedgerEntry, AuditEvent
from .schemas import parse_import_row, parse_correction, InputError

api = Blueprint("api", __name__)


def get_session():
    return current_app.extensions["ledger_session_factory"]()


def hash_key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate():
    raw_key = request.headers.get("X-API-Key", "")
    if not raw_key:
        return None, (jsonify(error="X-API-Key header is required"), 401)
    db = get_session()
    try:
        key_record = db.scalar(select(ApiKey).where(
            ApiKey.key_hash == hash_key(raw_key),
            ApiKey.active.is_(True),
        ))
        if not key_record:
            return None, (jsonify(error="Invalid API key"), 401)
        return {"tenant_id": key_record.tenant_id, "role": key_record.role}, None
    finally:
        db.close()


def require_principal(write=False):
    principal, error = authenticate()
    if error:
        return None, error
    if write and principal["role"] not in ("write", "admin"):
        return None, (jsonify(error="Write access required"), 403)
    return principal, None


def signed_amount(kind, amount_minor):
    return amount_minor if kind == "deposit" else -amount_minor


def audit(db, principal, action, entity_type, entity_id, details):
    db.add(AuditEvent(
        tenant_id=principal["tenant_id"],
        actor_role=principal["role"],
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=json.dumps(details, sort_keys=True),
    ))


def find_client(db, tenant_id, client_ref):
    return db.scalar(select(Client).where(
        Client.tenant_id == tenant_id,
        Client.client_ref == client_ref,
    ))


def get_or_create_client(db, tenant_id, client_ref):
    client = find_client(db, tenant_id, client_ref)
    if client:
        return client
    client = Client(tenant_id=tenant_id, client_ref=client_ref)
    db.add(client)
    db.flush()
    return client


def entry_json(entry):
    return {
        "id": entry.id,
        "client_id": entry.client_id,
        "transaction_type": entry.transaction_type,
        "amount_minor": entry.amount_minor,
        "signed_amount_minor": entry.signed_amount_minor,
        "currency": entry.currency,
        "effective_date": entry.effective_date.isoformat(),
        "is_reversal": entry.is_reversal,
        "reverses_entry_id": entry.reverses_entry_id,
        "corrects_entry_id": entry.corrects_entry_id,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@api.post("/v1/transactions/import")
def import_transactions():
    principal, error = require_principal(write=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        return jsonify(error="rows must be an array containing 1-1000 items"), 422

    db = get_session()
    accepted, rejected = [], []
    try:
        for index, raw in enumerate(rows):
            try:
                row = parse_import_row(raw)
                duplicate = db.scalar(select(LedgerEntry.id).where(
                    LedgerEntry.tenant_id == principal["tenant_id"],
                    LedgerEntry.idempotency_key == row["idempotency_key"],
                ))
                if duplicate:
                    rejected.append({"row": index, "idempotency_key": row["idempotency_key"], "error": "Duplicate transaction"})
                    continue

                # Savepoint isolates a bad row without losing earlier successful rows.
                with db.begin_nested():
                    client = get_or_create_client(db, principal["tenant_id"], row["client_ref"])
                    entry = LedgerEntry(
                        tenant_id=principal["tenant_id"],
                        client_id=client.id,
                        transaction_type=row["transaction_type"],
                        amount_minor=row["amount_minor"],
                        signed_amount_minor=signed_amount(row["transaction_type"], row["amount_minor"]),
                        currency=row["currency"],
                        effective_date=row["effective_date"],
                        idempotency_key=row["idempotency_key"],
                        external_ref=row["external_ref"],
                        created_by_role=principal["role"],
                    )
                    db.add(entry)
                    db.flush()
                    audit(db, principal, "transaction.imported", "ledger_entry", entry.id, {
                        "client_ref": row["client_ref"],
                        "amount_minor": row["amount_minor"],
                        "currency": row["currency"],
                    })
                accepted.append({"row": index, "transaction_id": entry.id})
            except (InputError, IntegrityError, ValueError) as exc:
                rejected.append({"row": index, "error": str(exc) or "Invalid row"})
        db.commit()
        return jsonify(accepted_count=len(accepted), rejected_count=len(rejected),
                       accepted=accepted, rejected=rejected)
    except Exception:
        db.rollback()
        current_app.logger.exception("Bulk import failed")
        return jsonify(error="Bulk import failed"), 500
    finally:
        db.close()


@api.get("/v1/clients/<string:client_ref>/transactions")
def client_transactions(client_ref):
    principal, error = require_principal()
    if error:
        return error
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        start_date = date.fromisoformat(request.args["start_date"]) if request.args.get("start_date") else None
        end_date = date.fromisoformat(request.args["end_date"]) if request.args.get("end_date") else None
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError()
        if start_date and end_date and start_date > end_date:
            return jsonify(error="start_date must be on or before end_date"), 422
    except ValueError:
        return jsonify(error="Invalid pagination or date parameter"), 422

    db = get_session()
    try:
        client = find_client(db, principal["tenant_id"], client_ref)
        if not client:
            return jsonify(error="Client not found"), 404
        stmt = select(LedgerEntry).where(
            LedgerEntry.tenant_id == principal["tenant_id"],
            LedgerEntry.client_id == client.id,
        )
        if start_date:
            stmt = stmt.where(LedgerEntry.effective_date >= start_date)
        if end_date:
            stmt = stmt.where(LedgerEntry.effective_date <= end_date)
        entries = db.scalars(stmt.order_by(LedgerEntry.effective_date, LedgerEntry.id).limit(limit).offset(offset)).all()
        return jsonify([entry_json(entry) for entry in entries])
    finally:
        db.close()


@api.get("/v1/clients/<string:client_ref>/balance")
def client_balance(client_ref):
    principal, error = require_principal()
    if error:
        return error
    try:
        as_of = date.fromisoformat(request.args.get("as_of", date.today().isoformat()))
    except ValueError:
        return jsonify(error="Invalid as_of date"), 422
    currency = request.args.get("currency", "USD").upper()
    if len(currency) != 3 or not currency.isalpha():
        return jsonify(error="currency must be a three-letter code"), 422

    db = get_session()
    try:
        client = find_client(db, principal["tenant_id"], client_ref)
        if not client:
            return jsonify(error="Client not found"), 404
        total = db.scalar(select(func.coalesce(func.sum(LedgerEntry.signed_amount_minor), 0)).where(
            LedgerEntry.tenant_id == principal["tenant_id"],
            LedgerEntry.client_id == client.id,
            LedgerEntry.currency == currency,
            LedgerEntry.effective_date <= as_of,
        )) or 0
        return jsonify(client_ref=client_ref, currency=currency, as_of=as_of.isoformat(), balance_minor=int(total))
    finally:
        db.close()


@api.get("/v1/clients/<string:client_ref>/monthly-summary")
def monthly_summary(client_ref):
    principal, error = require_principal()
    if error:
        return error
    try:
        year, month = int(request.args["year"]), int(request.args["month"])
        month_start = date(year, month, 1)
        next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    except (KeyError, ValueError):
        return jsonify(error="Provide valid year and month"), 422
    currency = request.args.get("currency", "USD").upper()
    if len(currency) != 3 or not currency.isalpha():
        return jsonify(error="currency must be a three-letter code"), 422

    db = get_session()
    try:
        client = find_client(db, principal["tenant_id"], client_ref)
        if not client:
            return jsonify(error="Client not found"), 404
        totals = db.execute(select(
            func.coalesce(func.sum(case((LedgerEntry.signed_amount_minor > 0, LedgerEntry.signed_amount_minor), else_=0)), 0).label("inflows"),
            func.coalesce(func.sum(case((LedgerEntry.signed_amount_minor < 0, -LedgerEntry.signed_amount_minor), else_=0)), 0).label("outflows"),
            func.coalesce(func.sum(case((LedgerEntry.transaction_type == "fee", -LedgerEntry.signed_amount_minor), else_=0)), 0).label("fees"),
            func.count(LedgerEntry.id).label("entry_count"),
        ).where(
            LedgerEntry.tenant_id == principal["tenant_id"],
            LedgerEntry.client_id == client.id,
            LedgerEntry.currency == currency,
            LedgerEntry.effective_date >= month_start,
            LedgerEntry.effective_date < next_month,
        )).one()
        inflows, outflows = int(totals.inflows or 0), int(totals.outflows or 0)
        return jsonify(
            client_ref=client_ref, year=year, month=month, currency=currency,
            inflows_minor=inflows, outflows_minor=outflows,
            fees_minor=int(totals.fees or 0), net_change_minor=inflows - outflows,
            entry_count=int(totals.entry_count or 0),
        )
    finally:
        db.close()


@api.post("/v1/transactions/<int:entry_id>/correct")
def correct_transaction(entry_id):
    principal, error = require_principal(write=True)
    if error:
        return error
    try:
        kind, amount_minor, currency, effective_date, idempotency_key, reason = parse_correction(request.get_json(silent=True))
    except InputError as exc:
        return jsonify(error=str(exc)), 422

    db = get_session()
    try:
        original = db.scalar(select(LedgerEntry).where(
            LedgerEntry.id == entry_id,
            LedgerEntry.tenant_id == principal["tenant_id"],
        ))
        if not original:
            return jsonify(error="Transaction not found"), 404
        if original.is_reversal:
            return jsonify(error="A reversal cannot be corrected"), 409
        already_corrected = db.scalar(select(LedgerEntry.id).where(
            LedgerEntry.tenant_id == principal["tenant_id"],
            LedgerEntry.reverses_entry_id == original.id,
        ))
        if already_corrected:
            return jsonify(error="Transaction has already been corrected"), 409

        with db.begin_nested():
            reversal = LedgerEntry(
                tenant_id=principal["tenant_id"], client_id=original.client_id,
                transaction_type=original.transaction_type, amount_minor=original.amount_minor,
                signed_amount_minor=-original.signed_amount_minor, currency=original.currency,
                effective_date=original.effective_date,
                idempotency_key=f"reversal:{original.id}:{idempotency_key}",
                is_reversal=True, reverses_entry_id=original.id, created_by_role=principal["role"],
            )
            replacement = LedgerEntry(
                tenant_id=principal["tenant_id"], client_id=original.client_id,
                transaction_type=kind, amount_minor=amount_minor,
                signed_amount_minor=signed_amount(kind, amount_minor), currency=currency,
                effective_date=effective_date, idempotency_key=idempotency_key,
                corrects_entry_id=original.id, created_by_role=principal["role"],
            )
            db.add_all([reversal, replacement])
            db.flush()
            audit(db, principal, "transaction.corrected", "ledger_entry", original.id, {
                "reversal_id": reversal.id, "replacement_id": replacement.id, "reason": reason,
            })
        db.commit()
        return jsonify(original_transaction_id=original.id, reversal_transaction_id=reversal.id,
                       replacement_transaction_id=replacement.id, history_preserved=True)
    except IntegrityError:
        db.rollback()
        return jsonify(error="Duplicate correction request"), 409
    except Exception:
        db.rollback()
        current_app.logger.exception("Correction failed")
        return jsonify(error="Correction failed"), 500
    finally:
        db.close()


@api.get("/v1/audit")
def audit_log():
    principal, error = require_principal()
    if error:
        return error
    try:
        limit = int(request.args.get("limit", 100))
        entity_id = int(request.args["entity_id"]) if request.args.get("entity_id") else None
        if not 1 <= limit <= 500:
            raise ValueError()
    except ValueError:
        return jsonify(error="Invalid audit query parameters"), 422

    db = get_session()
    try:
        stmt = select(AuditEvent).where(AuditEvent.tenant_id == principal["tenant_id"])
        if entity_id is not None:
            stmt = stmt.where(AuditEvent.entity_id == entity_id)
        events = db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit)).all()
        return jsonify([{
            "id": event.id, "actor_role": event.actor_role, "action": event.action,
            "entity_type": event.entity_type, "entity_id": event.entity_id,
            "details": json.loads(event.details), "created_at": event.created_at.isoformat(),
        } for event in events])
    finally:
        db.close()
