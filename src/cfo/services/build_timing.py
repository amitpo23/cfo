"""Time and query count of one dashboard build, for ``Server-Timing`` and one log line.

The count is read from the session's own connection, so concurrent requests in
the same process do not mix. Nothing here carries a user id or an amount.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from time import perf_counter

from sqlalchemy import event
from sqlalchemy.engine import Engine

_KEY = "rezef_query_count"


@event.listens_for(Engine, "before_cursor_execute")
def _count_query(conn, *_args):
    conn.info[_KEY] = conn.info.get(_KEY, 0) + 1


@contextmanager
def measured(db):
    """Yields a dict that holds ``ms`` and ``queries`` once the block ends."""
    connection = db.connection()
    before = connection.info.get(_KEY, 0)
    started = perf_counter()
    out: dict = {}
    try:
        yield out
    finally:
        out["ms"] = round((perf_counter() - started) * 1000, 1)
        out["queries"] = connection.info.get(_KEY, 0) - before


def server_timing(measure: dict) -> str:
    return f'build;dur={measure["ms"]}, db;desc="queries={measure["queries"]}"'


def log_build(logger: logging.Logger, route: str, dashboard_id: int, entities: int, measure: dict) -> None:
    logger.info("dashboard_view %s", json.dumps({
        "route": route, "dashboard_id": dashboard_id, "entities": entities,
        "ms": measure["ms"], "queries": measure["queries"],
    }, sort_keys=True))
