"""A memo for one read-only request.

A dashboard view reads the same bank rows, card accounts and coverage of each
organization from several services (cash flow, P&L, liquidity, intercompany),
and every read is a round trip to Neon. Inside ``read_memo(db)`` those reads are
made once and shared. Outside it, ``remember`` just computes, so code that
writes between two reads (tests, sync) is unchanged.

The memo lives in ``Session.info`` and ends with the block, so nothing outlives
the request: there is no staleness to budget for. Callers that hand out a
mutable value return a copy.
"""
from __future__ import annotations

from contextlib import contextmanager

_KEY = "rezef_read_memo"


@contextmanager
def read_memo(db):
    info = getattr(db, "info", None)
    if not isinstance(info, dict) or _KEY in info:
        # Not a session, or already inside a memo: the outer block owns it.
        yield
        return
    info[_KEY] = {}
    try:
        yield
    finally:
        info.pop(_KEY, None)


def remember(db, key: tuple, compute):
    info = getattr(db, "info", None)
    memo = info.get(_KEY) if isinstance(info, dict) else None
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]
