from flask import Flask
from flasgger import Swagger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .database import Base
from .routes import api


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL="postgresql+psycopg://ledger:ledger@localhost:5432/tenant_ledger",
        DB_POOL_SIZE=5,
        DB_MAX_OVERFLOW=10,
    )
    if test_config:
        app.config.update(test_config)

    engine_options = {"pool_pre_ping": True}
    if not app.config["DATABASE_URL"].startswith("sqlite"):
        engine_options.update(
            pool_size=app.config["DB_POOL_SIZE"],
            max_overflow=app.config["DB_MAX_OVERFLOW"],
        )
    engine = create_engine(app.config["DATABASE_URL"], **engine_options)
    app.extensions["ledger_engine"] = engine
    app.extensions["ledger_session_factory"] = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    app.register_blueprint(api)
    swagger = Swagger(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
