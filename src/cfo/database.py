"""
Database connection and session management
"""
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
from typing import Generator

from .config import settings
from .models import Base, IntegrationType, Organization


def _json_default(o):
    """JSON encoder fallback for values SUMIT/normalized data carry in JSON
    columns (raw_data/line_items): Decimal and date/datetime are not
    JSON-serializable by default and would abort the whole sync commit."""
    if isinstance(o, Decimal):
        # ערך מספרי — שומרים כ-float כדי לשמר חישוביות
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def _json_serializer(obj):
    return json.dumps(obj, default=_json_default, ensure_ascii=False)


def _engine_kwargs():
    kwargs = {"echo": settings.debug, "json_serializer": _json_serializer}
    if "sqlite" in settings.database_url:
        kwargs["connect_args"] = {"check_same_thread": False}
    elif "postgresql+psycopg" in settings.database_url:
        kwargs["connect_args"] = {"prepare_threshold": None}
        kwargs["poolclass"] = NullPool
    return kwargs


# Create engine
engine = create_engine(settings.database_url, **_engine_kwargs())

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """אתחול מסד הנתונים"""
    Base.metadata.create_all(bind=engine)
    ensure_default_organization()


def ensure_default_organization():
    """Create a minimal default tenant for demo/serverless environments."""
    db = SessionLocal()
    try:
        # Seed only into an empty table, without an explicit id: an explicit
        # id=1 insert would leave the PostgreSQL identity sequence at 1 and
        # break the next auto-id organization insert with a duplicate key.
        if db.query(Organization).first():
            return

        db.add(Organization(
            name="Demo Organization",
            business_type="financial_management",
            integration_type=IntegrationType.MANUAL,
            settings={"seeded": True},
            is_active=True,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session():
    """Get database session for FastAPI dependency injection"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
