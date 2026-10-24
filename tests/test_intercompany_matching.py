"""The indexed intercompany matcher must return the same settlement as the nested scan.

The reference below is the previous O(n*m) loop, copied so this file does not
call the production matcher twice. Hand cases pin the rule without that copy.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import Decimal

from cfo.services.dashboards.multi_entity import (
    IC_MAX_ITEMS,
    IC_RULE_HE,
    IC_TOLERANCE,
    _settle_intercompany,
)


class _Txn:
    def __init__(self, row_id: int, org_id: int, when: date, amount: Decimal):
        self.id = row_id
        self.organization_id = org_id
        self.transaction_date = when
        self.amount = amount
        self.description = ""


def _item(row_id: int, org_id: int, when: date, amount: Decimal, category: str = "intercompany"):
    value = Decimal(amount)
    return (_Txn(row_id, org_id, when, value), value, category)


def _reference_settle(rows: list, window_days: int, labels: dict | None = None) -> dict:
    """Previous nested scan. Outflows in (date, id) order; closest free inflow, then lowest id."""
    labels = labels or {}
    empty = {
        "summary": {
            "pairs": 0, "inflows": 0.0, "outflows": 0.0, "amount": 0.0,
            "window_days": window_days, "rule": IC_RULE_HE, "items": [],
            "by_month": {},
        },
        "by_month": {},
    }
    outs = sorted((item for item in rows if item[1] < 0), key=lambda item: (item[0].transaction_date, item[0].id))
    ins = [item for item in rows if item[1] > 0]
    used: set[int] = set()
    by_month: dict[str, dict] = {}
    items = []
    total = Decimal(0)
    for out_row, out_amount, _out_category in outs:
        best = None
        for in_row, in_amount, _in_category in ins:
            if in_row.id in used or in_row.organization_id == out_row.organization_id:
                continue
            if abs(abs(out_amount) - in_amount) > IC_TOLERANCE:
                continue
            gap = abs((in_row.transaction_date - out_row.transaction_date).days)
            if gap > window_days:
                continue
            key = (gap, in_row.id)
            if best is None or key < best[0]:
                best = (key, in_row, in_amount)
        if best is None:
            continue
        _, in_row, in_amount = best
        used.add(in_row.id)
        out_month = out_row.transaction_date.strftime("%Y-%m")
        in_month = in_row.transaction_date.strftime("%Y-%m")
        by_month.setdefault(in_month, {"inflows": 0.0, "outflows": 0.0})["inflows"] += float(in_amount)
        by_month.setdefault(out_month, {"inflows": 0.0, "outflows": 0.0})["outflows"] += float(-out_amount)
        total += in_amount
        if len(items) < IC_MAX_ITEMS:
            items.append({
                "from": labels.get(out_row.organization_id),
                "to": labels.get(in_row.organization_id),
                "out_date": out_row.transaction_date.isoformat(),
                "in_date": in_row.transaction_date.isoformat(),
                "amount": float(in_amount),
                "days_apart": abs((in_row.transaction_date - out_row.transaction_date).days),
            })
    for slot in by_month.values():
        slot["inflows"] = round(slot["inflows"], 2)
        slot["outflows"] = round(slot["outflows"], 2)
    summary = dict(empty["summary"])
    summary.update({
        "pairs": len(used),
        "inflows": round(float(total), 2),
        "outflows": round(float(total), 2),
        "amount": round(float(total), 2),
        "items": items,
        "by_month": {month: dict(by_month[month]) for month in sorted(by_month)},
    })
    return {"summary": summary, "by_month": by_month}


def _assert_same(rows, window, labels=None):
    produced = _settle_intercompany(rows, window, labels)
    reference = _reference_settle(rows, window, labels)
    # json keeps key order. dict equality would ignore a reshuffle of by_month.
    assert json.dumps(produced, ensure_ascii=False) == json.dumps(reference, ensure_ascii=False)


def test_lower_id_wins_when_the_date_gap_is_equal():
    # Both inflows are 2 days away, on opposite sides of the outflow.
    # id 3 is the later day. Lowest id wins, not the earlier date.
    rows = [
        _item(1, 1, date(2026, 2, 5), Decimal("-40.00")),
        _item(8, 2, date(2026, 2, 3), Decimal("40.00")),
        _item(3, 2, date(2026, 2, 7), Decimal("40.00")),
    ]
    settled = _settle_intercompany(rows, 4, {1: "א", 2: "ב"})
    assert settled["summary"]["pairs"] == 1
    assert settled["summary"]["items"] == [{
        "from": "א",
        "to": "ב",
        "out_date": "2026-02-05",
        "in_date": "2026-02-07",
        "amount": 40.0,
        "days_apart": 2,
    }]
    _assert_same(rows, 4, {1: "א", 2: "ב"})


def test_earlier_outflow_takes_the_closer_inflow():
    # A on Jan 1 is processed before B on Jan 2, so A takes the Jan 2 inflow (gap 1)
    # and B is left with Jan 5 (gap 3). Reversing that order would pair B with Jan 2.
    rows = [
        _item(1, 1, date(2026, 1, 1), Decimal("-100.00")),
        _item(2, 1, date(2026, 1, 2), Decimal("-100.00")),
        _item(10, 2, date(2026, 1, 2), Decimal("100.00")),
        _item(11, 2, date(2026, 1, 5), Decimal("100.00")),
    ]
    settled = _settle_intercompany(rows, 4, {1: "from", 2: "to"})
    assert [(item["out_date"], item["in_date"]) for item in settled["summary"]["items"]] == [
        ("2026-01-01", "2026-01-02"),
        ("2026-01-02", "2026-01-05"),
    ]
    _assert_same(rows, 4, {1: "from", 2: "to"})


def test_tolerance_and_window_are_inclusive_on_the_boundary():
    day = date(2026, 3, 1)
    within = [
        _item(1, 1, day, Decimal("-10.00")),
        _item(2, 2, day, Decimal("10.01")),  # exactly 0.01
    ]
    outside = [
        _item(1, 1, day, Decimal("-10.00")),
        _item(2, 2, day, Decimal("10.02")),  # 0.02
    ]
    on_window = [
        _item(1, 1, day, Decimal("-10.00")),
        _item(2, 2, day + timedelta(days=4), Decimal("10.00")),
    ]
    past_window = [
        _item(1, 1, day, Decimal("-10.00")),
        _item(2, 2, day + timedelta(days=5), Decimal("10.00")),
    ]
    assert _settle_intercompany(within, 4)["summary"]["pairs"] == 1
    assert _settle_intercompany(outside, 4)["summary"]["pairs"] == 0
    assert _settle_intercompany(on_window, 4)["summary"]["pairs"] == 1
    assert _settle_intercompany(past_window, 4)["summary"]["pairs"] == 0
    assert _settle_intercompany(on_window, 0)["summary"]["pairs"] == 0
    same_day = [
        _item(1, 1, day, Decimal("-10.00")),
        _item(2, 2, day, Decimal("10.00")),
    ]
    assert _settle_intercompany(same_day, 0)["summary"]["pairs"] == 1
    for case, window in ((within, 4), (outside, 4), (on_window, 4), (past_window, 4), (on_window, 0), (same_day, 0)):
        _assert_same(case, window)


def test_amount_bucket_boundary_still_matches():
    # 10.00 is bucket 1000 and 10.01 is bucket 1001. 10.005 vs 10.015 crosses a bucket too.
    day = date(2026, 4, 1)
    adjacent = [
        _item(1, 1, day, Decimal("-10.00")),
        _item(2, 2, day, Decimal("10.01")),
    ]
    three_places = [
        _item(1, 1, day, Decimal("-10.005")),
        _item(2, 2, day, Decimal("10.015")),
    ]
    other_side = [
        _item(1, 1, day, Decimal("-10.009")),
        _item(2, 2, day, Decimal("9.999")),
    ]
    for rows in (adjacent, three_places, other_side):
        assert _settle_intercompany(rows, 4)["summary"]["pairs"] == 1
        _assert_same(rows, 4)


def test_same_organization_and_zero_amount_are_not_pairs():
    day = date(2026, 5, 1)
    rows = [
        _item(1, 1, day, Decimal("-25.00")),
        _item(2, 1, day, Decimal("25.00")),
        _item(3, 2, day, Decimal("0")),
        _item(4, 1, day, Decimal("0")),
    ]
    settled = _settle_intercompany(rows, 4)
    assert settled["summary"]["pairs"] == 0
    assert settled["summary"]["items"] == []
    assert settled["by_month"] == {}
    _assert_same(rows, 4)


def test_each_side_is_removed_from_its_own_month():
    rows = [
        _item(1, 1, date(2026, 8, 31), Decimal("-50.00")),
        _item(2, 2, date(2026, 9, 2), Decimal("50.00")),
    ]
    settled = _settle_intercompany(rows, 4, {1: "שף", 2: "פוד"})
    assert settled["by_month"] == {
        "2026-09": {"inflows": 50.0, "outflows": 0.0},
        "2026-08": {"inflows": 0.0, "outflows": 50.0},
    }
    assert settled["summary"]["by_month"] == {
        "2026-08": {"inflows": 0.0, "outflows": 50.0},
        "2026-09": {"inflows": 50.0, "outflows": 0.0},
    }
    # 50 + 0 on the inflow side of September, and the outflow is the same 50.
    assert settled["summary"]["amount"] == 50.0
    assert settled["summary"]["pairs"] == 1
    _assert_same(rows, 4, {1: "שף", 2: "פוד"})


def test_one_inflow_is_used_once():
    day = date(2026, 6, 1)
    rows = [
        _item(1, 1, day, Decimal("-80")),
        _item(2, 1, day + timedelta(days=1), Decimal("-80")),
        _item(3, 2, day, Decimal("80")),
    ]
    settled = _settle_intercompany(rows, 4)
    assert settled["summary"]["pairs"] == 1
    assert settled["summary"]["items"][0]["out_date"] == "2026-06-01"
    _assert_same(rows, 4)


def test_item_list_stops_at_200_and_the_pair_count_does_not():
    rows = []
    day = date(2026, 7, 1)
    for i in range(1, IC_MAX_ITEMS + 2):
        rows.append(_item(i, 1, day, Decimal(-i)))
        rows.append(_item(10_000 + i, 2, day, Decimal(i)))
    settled = _settle_intercompany(rows, 4, {1: "a", 2: "b"})
    assert settled["summary"]["pairs"] == IC_MAX_ITEMS + 1
    assert len(settled["summary"]["items"]) == IC_MAX_ITEMS
    assert settled["summary"]["items"][0]["amount"] == 1.0
    assert settled["summary"]["items"][-1]["amount"] == float(IC_MAX_ITEMS)
    _assert_same(rows, 4, {1: "a", 2: "b"})


def _random_case(seed: int, *, n_pairs: int | None = None, amount_choices: int | None = None):
    rng = random.Random(seed)
    n_pairs = n_pairs if n_pairs is not None else rng.randint(15, 90)
    orgs = [10, 20, 30, 40][: rng.randint(2, 4)]
    window = rng.randint(0, 10)
    base = date(2025, 1, 1)
    slips = (
        Decimal("0"), Decimal("0.01"), Decimal("-0.01"),
        Decimal("0.02"), Decimal("0.005"), Decimal("-0.005"),
    )
    rows = []
    next_id = 1
    for _ in range(n_pairs):
        if amount_choices:
            cents = rng.randrange(1, amount_choices) * 100
        elif rng.random() < 0.7:
            # Repeated amounts, so several inflows compete for one outflow.
            cents = rng.randrange(1, 8) * 1000
        else:
            cents = rng.randrange(1, 200_000)
        amount = Decimal(cents) / Decimal(100)
        if rng.random() < 0.12:
            amount += Decimal("0.005")
        day = base + timedelta(days=rng.randrange(0, 320))
        org_a, org_b = rng.sample(orgs, 2)
        if rng.random() < 0.18:
            org_b = org_a
        gap = rng.randint(-window - 2, window + 2)
        in_amount = amount + rng.choice(slips)
        if in_amount <= 0:
            in_amount = Decimal("0.01")
        rows.append(_item(next_id, org_a, day, -amount, "transfers_out"))
        next_id += 1
        rows.append(_item(next_id, org_b, day + timedelta(days=gap), in_amount, "other_in"))
        next_id += 1
    for _ in range(4):
        rows.append(_item(next_id, orgs[0], base, Decimal("0")))
        next_id += 1
    rng.shuffle(rows)
    return rows, window, {org: f"e{org}" for org in orgs}


def test_indexed_match_matches_the_nested_scan_on_random_rows():
    for seed in range(40):
        rows, window, labels = _random_case(seed)
        try:
            _assert_same(rows, window, labels)
        except AssertionError as exc:
            raise AssertionError(f"seed {seed}") from exc


def test_indexed_match_matches_the_nested_scan_when_many_rows_share_an_amount():
    rows, window, labels = _random_case(12345, n_pairs=350, amount_choices=4)
    _assert_same(rows, window, labels)
