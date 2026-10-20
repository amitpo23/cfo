"""Constant-time secret comparison.

Hashing both sides first keeps the compared byte strings the same length, so a
short or missing header cannot exit early on length alone.
"""
from __future__ import annotations

import hashlib
import hmac


def constant_time_equal(provided: object, expected: object) -> bool:
    left = "" if provided is None else str(provided)
    right = "" if expected is None else str(expected)
    return hmac.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )
