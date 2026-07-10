#!/usr/bin/env python3
"""Production readiness checks for the CFO platform.

The script is intentionally read-only. It validates configuration, database
connectivity/schema, core data counts, and optional integration pings.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


REQUIRED_ENV = [
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "CREDENTIALS_ENCRYPTION_KEY",
    "REGISTRATION_SECRET",
    "CRON_SECRET",
    "CORS_ALLOWED_ORIGINS",
    "SUMIT_API_KEY",
    "SUMIT_COMPANY_ID",
]

OPTIONAL_ENV = [
    "OPEN_FINANCE_CLIENT_ID",
    "OPEN_FINANCE_CLIENT_SECRET",
    "OPEN_FINANCE_USER_ID",
    "OPEN_FINANCE_WEBHOOK_SECRET",
    "GOOGLE_CLIENT_ID",
    "VITE_GOOGLE_CLIENT_ID",
]

CORE_TABLES = [
    "organizations",
    "users",
    "integration_connections",
    "accounts",
    "contacts",
    "invoices",
    "bills",
    "expenses",
    "payments",
    "transactions",
    "bank_connections",
    "bank_transactions",
    "sync_runs",
    "alembic_version",
]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def status(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def check_env(require_postgres: bool) -> list[Check]:
    checks: list[Check] = []
    for key in REQUIRED_ENV:
        value = env_value(key)
        checks.append(Check(f"env:{key}", bool(value), f"len={len(value)}"))

    for key in OPTIONAL_ENV:
        value = env_value(key)
        checks.append(Check(f"env_optional:{key}", bool(value), f"len={len(value)}"))

    db_url = env_value("DATABASE_URL")
    checks.append(Check("database:not_sqlite", not db_url.startswith("sqlite:"), "required for Vercel production"))
    if require_postgres:
        checks.append(Check("database:postgres", db_url.startswith(("postgresql://", "postgresql+psycopg://")), "expected managed Postgres"))
    return checks


def check_database() -> tuple[list[Check], dict[str, Any]]:
    url = env_value("DATABASE_URL")
    if not url:
        return [Check("database:connect", False, "DATABASE_URL is empty")], {}
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite:"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql+psycopg"):
        kwargs["connect_args"] = {"prepare_threshold": None}

    engine = create_engine(url, **kwargs)
    checks: list[Check] = []
    summary: dict[str, Any] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1")).scalar_one()
            checks.append(Check("database:connect", True, engine.url.render_as_string(hide_password=True)))
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            summary["table_count"] = len(tables)
            for table in CORE_TABLES:
                checks.append(Check(f"table:{table}", table in tables))
            for table in sorted(tables & set(CORE_TABLES)):
                try:
                    count = conn.execute(text(f'select count(*) from "{table}"')).scalar_one()
                    summary[f"count:{table}"] = count
                except Exception as exc:  # noqa: BLE001
                    summary[f"count:{table}"] = f"error:{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("database:connect", False, f"{type(exc).__name__}: {exc}"))
    return checks, summary


async def check_integrations() -> list[Check]:
    checks: list[Check] = []

    if env_value("SUMIT_API_KEY") and env_value("SUMIT_COMPANY_ID"):
        from src.cfo.integrations.sumit_integration import SumitIntegration

        try:
            async with SumitIntegration(
                api_key=env_value("SUMIT_API_KEY"),
                company_id=env_value("SUMIT_COMPANY_ID"),
            ) as client:
                checks.append(Check("sumit:ping", bool(await client.test_connection())))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("sumit:ping", False, f"{type(exc).__name__}: {exc}"))
    else:
        checks.append(Check("sumit:ping", False, "SUMIT credentials missing"))

    of_keys = ["OPEN_FINANCE_CLIENT_ID", "OPEN_FINANCE_CLIENT_SECRET", "OPEN_FINANCE_USER_ID"]
    if all(env_value(k) for k in of_keys):
        from src.cfo.services.open_finance_client import OpenFinanceClient

        client = OpenFinanceClient(
            client_id=env_value("OPEN_FINANCE_CLIENT_ID"),
            client_secret=env_value("OPEN_FINANCE_CLIENT_SECRET"),
            user_id=env_value("OPEN_FINANCE_USER_ID"),
        )
        try:
            checks.append(Check("open_finance:ping", bool(await client.ping())))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("open_finance:ping", False, f"{type(exc).__name__}: {exc}"))
        finally:
            await client.close()
    else:
        missing = [k for k in of_keys if not env_value(k)]
        checks.append(Check("open_finance:ping", False, "missing=" + ",".join(missing)))

    return checks


def print_checks(checks: list[Check]) -> None:
    for check in checks:
        detail = f" - {check.detail}" if check.detail else ""
        print(f"[{status(check.ok)}] {check.name}{detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only CFO production readiness check")
    parser.add_argument("--env-file", default=".env.local", help="dotenv file to load first")
    parser.add_argument("--require-postgres", action="store_true", help="fail if DATABASE_URL is not Postgres")
    parser.add_argument("--skip-integrations", action="store_true", help="skip live SUMIT/Open Finance pings")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=True)

    checks = check_env(require_postgres=args.require_postgres)
    db_checks, summary = check_database()
    checks.extend(db_checks)
    if not args.skip_integrations:
        checks.extend(asyncio.run(check_integrations()))

    print_checks(checks)
    if summary:
        print("\nSummary:")
        for key, value in sorted(summary.items()):
            print(f"{key}={value}")

    required_failures = [
        check for check in checks
        if not check.ok and not check.name.startswith("env_optional:")
    ]
    return 1 if required_failures else 0


if __name__ == "__main__":
    sys.exit(main())
