#!/usr/bin/env python3
"""Read-only CSV of Open Finance duplicate pairs per organization, account, and month.

Auto-excluded PENDING/BOOKED pairs are included with disposition ``excluded``.
Unconfirmed lookalikes are ``warning`` and are not removed by this report.
Confirmed ``dedupePairs`` from the organization's dashboard plans are ``confirmed``.

The script refuses any non-sqlite database URL, opens sqlite in query_only mode,
and does not import a SUMIT or Open Finance client.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from cfo.config import settings  # noqa: E402
from cfo.services.dashboards.activity_quality import duplicate_pairs  # noqa: E402

COLUMNS = (
    "organization_id",
    "account_id",
    "month",
    "left_id",
    "right_id",
    "amount",
    "left_date",
    "right_date",
    "left_status",
    "right_status",
    "left_description",
    "right_description",
    "entry_reference",
    "rule",
    "disposition",
)


def assert_local_sqlite(url: str) -> None:
    lowered = (url or "").strip().lower()
    if lowered.startswith("sqlite:") and "postgres" not in lowered and "neon.tech" not in lowered:
        return
    raise SystemExit("eliav_dq_report reads only a local sqlite database and refuses this URL")


def open_readonly_session(url: str):
    assert_local_sqlite(url)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    db = sessionmaker(bind=engine)()
    db.execute(text("PRAGMA query_only = ON"))
    return db, engine


def close_readonly_session(db, engine) -> None:
    db.rollback()
    db.close()
    engine.dispose()


def write_csv(pairs: list[dict], destination) -> None:
    writer = csv.DictWriter(destination, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in pairs:
        writer.writerow({column: row.get(column) for column in COLUMNS})


def main(argv: list[str] | None = None, *, url: str | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only CSV of suspected duplicate bank pairs")
    parser.add_argument("--organization-id", type=int, default=None)
    parser.add_argument("--output", default=None, help="CSV path. Defaults to stdout.")
    args = parser.parse_args(argv)
    database_url = url if url is not None else settings.database_url
    db, engine = open_readonly_session(database_url)
    try:
        pairs = duplicate_pairs(db, args.organization_id)
        if args.output:
            with open(args.output, "w", encoding="utf-8", newline="") as handle:
                write_csv(pairs, handle)
        else:
            write_csv(pairs, sys.stdout)
    finally:
        close_readonly_session(db, engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
