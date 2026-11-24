import hashlib
from sqlalchemy import select
from app import create_app
from app.database import Base
from app.models import Tenant, ApiKey

app = create_app()
engine = app.extensions["ledger_engine"]
Session = app.extensions["ledger_session_factory"]
Base.metadata.create_all(engine)

with Session.begin() as db:
    tenant = db.scalar(select(Tenant).where(Tenant.name == "Northbridge Advisory"))
    if tenant is None:
        tenant = Tenant(name="Northbridge Advisory")
        db.add(tenant)
        db.flush()
    for raw_key, role in [("demo-write-key", "write"), ("demo-read-key", "read"), ("demo-admin-key", "admin")]:
        digest = hashlib.sha256(raw_key.encode()).hexdigest()
        if not db.scalar(select(ApiKey).where(ApiKey.key_hash == digest)):
            db.add(ApiKey(tenant_id=tenant.id, key_hash=digest, role=role, active=True))

print("Database initialized. Local-only keys: demo-write-key, demo-read-key, demo-admin-key")
