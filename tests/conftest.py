import hashlib
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import create_app
from app.database import Base
from app.models import Tenant, ApiKey

@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        for tenant_name, key, role in [("Tenant A", "key-a", "admin"), ("Tenant B", "key-b", "admin"), ("Read", "key-read", "read")]:
            tenant = Tenant(name=tenant_name)
            db.add(tenant)
            db.flush()
            db.add(ApiKey(tenant_id=tenant.id, key_hash=hashlib.sha256(key.encode()).hexdigest(), role=role))
    app = create_app({"TESTING": True, "DATABASE_URL": "sqlite://", "DB_POOL_SIZE": 1, "DB_MAX_OVERFLOW": 0})
    app.extensions["ledger_engine"].dispose()
    app.extensions["ledger_engine"] = engine
    app.extensions["ledger_session_factory"] = Session
    with app.test_client() as test_client:
        yield test_client
    engine.dispose()

def auth(key="key-a"):
    return {"X-API-Key": key}
