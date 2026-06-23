#!/usr/bin/env python3
"""Copy the local CFO SQLite database into a Postgres/Supabase database.

Default mode is a dry-run. Use --execute to write. Use --truncate-target only
when the target database is known to be disposable or already backed up.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, create_engine, delete, func, select, text


SKIP_TABLES = {"sqlite_sequence"}


def engine_for(url: str):
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite:"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql+psycopg"):
        kwargs["connect_args"] = {"prepare_threshold": None}
    return create_engine(url, **kwargs)


def normalize_target_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def table_order(metadata: MetaData) -> list[Table]:
    return [
        table for table in metadata.sorted_tables
        if table.name not in SKIP_TABLES
    ]


def reset_postgres_sequences(conn, tables: list[Table]) -> None:
    dialect = conn.engine.dialect.name
    if dialect != "postgresql":
        return

    for table in tables:
        for column in table.primary_key.columns:
            try:
                is_integer_pk = column.type.python_type is int
            except NotImplementedError:
                is_integer_pk = False
            if not is_integer_pk:
                continue
            sequence_name = conn.execute(
                text("select pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            ).scalar()
            if not sequence_name:
                continue
            max_id = conn.execute(
                text(f'select coalesce(max("{column.name}"), 0) from "{table.name}"')
            ).scalar_one()
            if max_id:
                conn.execute(
                    text("select setval(:sequence_name, :next_value, true)"),
                    {"sequence_name": sequence_name, "next_value": max_id},
                )
            else:
                conn.execute(
                    text("select setval(:sequence_name, 1, false)"),
                    {"sequence_name": sequence_name},
                )
            print(f"sequence {sequence_name} -> {max_id}")


def copy_rows(source_url: str, target_url: str, *, execute: bool, truncate_target: bool) -> int:
    source = engine_for(source_url)
    target = engine_for(normalize_target_url(target_url))

    source_meta = MetaData()
    source_meta.reflect(bind=source)
    target_meta = MetaData()
    target_meta.reflect(bind=target)

    missing = sorted(set(source_meta.tables) - set(target_meta.tables) - SKIP_TABLES)
    if missing:
        raise RuntimeError("Target is missing tables: " + ", ".join(missing))

    total = 0
    with source.connect() as source_conn:
        with target.begin() as target_conn:
            ordered = table_order(source_meta)
            if truncate_target:
                for source_table in reversed(ordered):
                    target_table = target_meta.tables[source_table.name]
                    count = target_conn.execute(select(func.count()).select_from(target_table)).scalar_one()
                    print(f"target_existing {source_table.name}={count}")
                    if execute:
                        target_conn.execute(delete(target_table))

            for source_table in ordered:
                rows = [dict(row._mapping) for row in source_conn.execute(select(source_table)).all()]
                total += len(rows)
                print(f"copy {source_table.name}: {len(rows)} rows")
                if execute and rows:
                    target_table = target_meta.tables[source_table.name]
                    target_conn.execute(target_table.insert(), rows)

            if execute:
                reset_postgres_sequences(target_conn, [target_meta.tables[t.name] for t in ordered])

    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate CFO SQLite data to Postgres")
    parser.add_argument("--sqlite-url", default="sqlite:///./cfo.db")
    parser.add_argument("--target-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--execute", action="store_true", help="write to target; otherwise dry-run")
    parser.add_argument("--truncate-target", action="store_true", help="delete target table rows before copying")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=False)
    target_url = args.target_url or os.getenv("DATABASE_URL", "")

    if not target_url:
        print("Target DATABASE_URL is required", file=sys.stderr)
        return 2
    if target_url.startswith("sqlite:"):
        print("Target must be Postgres/Supabase, not SQLite", file=sys.stderr)
        return 2

    print("mode=" + ("execute" if args.execute else "dry-run"))
    print("source=" + args.sqlite_url)
    print("target=" + engine_for(normalize_target_url(target_url)).url.render_as_string(hide_password=True))
    total = copy_rows(
        args.sqlite_url,
        target_url,
        execute=args.execute,
        truncate_target=args.truncate_target,
    )
    print(f"total_rows={total}")
    if not args.execute:
        print("No data written. Re-run with --execute to migrate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
