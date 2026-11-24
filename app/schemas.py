from datetime import date
from decimal import Decimal, InvalidOperation


TRANSACTION_TYPES = {"deposit", "withdrawal", "fee", "transfer"}
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "CHF"}


class InputError(ValueError):
    pass


def parse_import_row(raw):
    if not isinstance(raw, dict):
        raise InputError("Each row must be a JSON object")
    required = ("client_ref", "transaction_type", "amount", "currency", "effective_date", "idempotency_key")
    missing = [field for field in required if field not in raw]
    if missing:
        raise InputError(f"Missing fields: {', '.join(missing)}")

    client_ref = str(raw["client_ref"]).strip()
    idempotency_key = str(raw["idempotency_key"]).strip()
    kind = str(raw["transaction_type"]).strip().lower()
    currency = str(raw["currency"]).strip().upper()
    if not client_ref or len(client_ref) > 100:
        raise InputError("client_ref must contain 1-100 characters")
    if not idempotency_key or len(idempotency_key) > 128:
        raise InputError("idempotency_key must contain 1-128 characters")
    if kind not in TRANSACTION_TYPES:
        raise InputError("Invalid transaction_type")
    if currency not in SUPPORTED_CURRENCIES:
        raise InputError(f"Unsupported currency: {currency}")

    try:
        amount = Decimal(str(raw["amount"]))
        effective_date = date.fromisoformat(str(raw["effective_date"]))
    except (InvalidOperation, ValueError, TypeError):
        raise InputError("Invalid amount or effective_date")
    if not amount.is_finite() or amount <= 0 or amount > Decimal("100000000"):
        raise InputError("amount must be greater than 0 and at most 100000000")
    if amount * 100 != (amount * 100).to_integral_value():
        raise InputError("Amount supports at most two decimal places")
    if effective_date > date.today():
        raise InputError("Future transaction dates are not allowed")

    external_ref = raw.get("external_ref")
    if external_ref is not None and len(str(external_ref)) > 128:
        raise InputError("external_ref must be at most 128 characters")

    return {
        "client_ref": client_ref,
        "transaction_type": kind,
        "amount_minor": int(amount * 100),
        "currency": currency,
        "effective_date": effective_date,
        "idempotency_key": idempotency_key,
        "external_ref": str(external_ref) if external_ref is not None else None,
    }


def parse_correction(raw):
    if not isinstance(raw, dict):
        raise InputError("Request body must be a JSON object")
    required = ("replacement_type", "replacement_amount", "replacement_currency", "effective_date", "idempotency_key", "reason")
    missing = [field for field in required if field not in raw]
    if missing:
        raise InputError(f"Missing fields: {', '.join(missing)}")
    kind = str(raw["replacement_type"]).strip().lower()
    currency = str(raw["replacement_currency"]).strip().upper()
    if kind not in TRANSACTION_TYPES:
        raise InputError("Invalid replacement_type")
    if currency not in SUPPORTED_CURRENCIES:
        raise InputError(f"Unsupported currency: {currency}")
    try:
        amount = Decimal(str(raw["replacement_amount"]))
        effective_date = date.fromisoformat(str(raw["effective_date"]))
    except (InvalidOperation, ValueError, TypeError):
        raise InputError("Invalid replacement_amount or effective_date")
    if not amount.is_finite() or amount <= 0 or amount > Decimal("100000000"):
        raise InputError("replacement_amount must be greater than 0 and at most 100000000")
    if amount * 100 != (amount * 100).to_integral_value():
        raise InputError("Amount supports at most two decimal places")
    if effective_date > date.today():
        raise InputError("Future transaction dates are not allowed")
    key = str(raw["idempotency_key"]).strip()
    reason = str(raw["reason"]).strip()
    if not key or len(key) > 128:
        raise InputError("idempotency_key must contain 1-128 characters")
    if len(reason) < 3 or len(reason) > 500:
        raise InputError("reason must contain 3-500 characters")
    return kind, int(amount * 100), currency, effective_date, key, reason
