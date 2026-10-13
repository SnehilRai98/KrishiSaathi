"""SQLAlchemy models and connection management.

SQLite is the zero-setup default; set DATABASE_URL to a MySQL URL for a server database.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("krishisaathi.database")

DEFAULT_DATABASE_URL = f"sqlite:///{(Path(__file__).parent / 'krishisaathi.db').as_posix()}"


def utcnow() -> datetime:
    """Naive UTC timestamp (the DB columns are timezone-less)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class CropAnalysis(Base):
    __tablename__ = "crop_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_filename = Column(String(255), nullable=False)
    # Nullable because an image-quality-only record must never masquerade as a diagnosis.
    predicted_disease = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(40), default="diagnosis_unavailable", nullable=False)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    quality_feedback = Column(Text, nullable=True)
    # JSON list of {"label", "confidence"} for the closest matches (history details view).
    top_predictions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class FertilizerPlan(Base):
    """A saved fertiliser plan: what the farmer entered and the plan that was calculated from it."""

    __tablename__ = "fertilizer_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(120), nullable=False, default="")
    area_value = Column(Float, nullable=False)
    area_unit = Column(String(20), nullable=False)
    request_json = Column(Text, nullable=False)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None
_database_initialized = False
_database_error: str | None = None


def configure_database(url: str | None = None) -> None:
    """Configure the application database.

    ``url=None`` reads DATABASE_URL and falls back to the bundled SQLite file; an explicit
    empty string leaves the database unconfigured (used by tests).
    """
    global DATABASE_URL, engine, SessionLocal, _database_initialized, _database_error
    if engine is not None:
        engine.dispose()

    DATABASE_URL = (os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL) if url is None else url
    _database_initialized = False
    _database_error = None
    engine = None
    SessionLocal = None
    if not DATABASE_URL:
        return

    options = {"pool_pre_ping": True}
    if DATABASE_URL.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool

    engine = create_engine(DATABASE_URL, **options)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def database_status() -> tuple[bool, str | None]:
    """Perform a live database check; configuration alone is not readiness."""
    if engine is None:
        return False, "DATABASE_URL is not configured. Remove it from backend/.env to use the built-in SQLite database, or set a valid database URL."
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False, "Cannot connect to the configured database. If you use MySQL, check that it is running and that DATABASE_URL is correct."
    if not _database_initialized:
        return False, _database_error or "Database tables have not initialized successfully."
    return True, None


def init_db() -> None:
    global _database_initialized, _database_error
    if engine is None or SessionLocal is None:
        _database_initialized = False
        _database_error = "DATABASE_URL is not configured."
        raise RuntimeError(_database_error)

    try:
        Base.metadata.create_all(engine)
        # Additive migration for databases created by earlier rebuilt versions.
        with engine.begin() as connection:
            tables = set(sa_inspect(engine).get_table_names())
            additions = {
                "crop_analyses": {
                    "status": "VARCHAR(40) NOT NULL DEFAULT 'diagnosis_unavailable'",
                    "image_width": "INTEGER NULL",
                    "image_height": "INTEGER NULL",
                    "quality_feedback": "TEXT NULL",
                    "top_predictions": "TEXT NULL",
                },
            }
            for table, columns in additions.items():
                if table not in tables:
                    continue
                present = {item["name"] for item in sa_inspect(engine).get_columns(table)}
                for name, declaration in columns.items():
                    if name not in present:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"))
            if engine.dialect.name == "mysql" and "crop_analyses" in tables:
                connection.execute(text("ALTER TABLE crop_analyses MODIFY predicted_disease VARCHAR(255) NULL"))
        _database_initialized = True
        _database_error = None
    except Exception as exc:
        _database_initialized = False
        _database_error = "Database initialization failed. Check the database connection and permissions."
        raise RuntimeError(_database_error) from exc


def get_session():
    """FastAPI dependency with clear 503 responses for unavailable database operations."""
    from fastapi import HTTPException

    ready, message = database_status()
    if not ready or SessionLocal is None:
        raise HTTPException(status_code=503, detail=message or "Database is unavailable.")

    session = SessionLocal()
    try:
        yield session
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="A database operation failed. Check the database connection and schema initialization.",
        ) from exc
    finally:
        session.close()


configure_database()
