"""Balance, limit, used, available and overrun of each checking account.

An overdraft above its limit shows as an overrun even when the bank balance
is older than two days: the last booked balance stays, with its date. Made-up
accounts and amounts only.
"""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType
from cfo.services.dashboard_service import DashboardService
from cfo.services.dashboards.liquidity import checking_snapshot

TODAY = date(2026, 11, 4)


def _checking(org_id: int, name: str, balance, limit, as_of: datetime, external_id: str) -> None:
    with SessionLocal() as db:
        db.add(Account(
            organization_id=org_id, name=name, account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id=external_id,
            balance=None if balance is None else Decimal(balance),
            credit_limit=None if limit is None else Decimal(limit),
            balance_as_of=as_of, currency="ILS",
        ))
        db.commit()


def test_stale_overdraft_above_its_limit_is_an_overrun_with_its_date(fresh_org):
    owner = fresh_org()
    _checking(owner["org_id"], "עו״ש בדיקה", "-30000", "12000", datetime(2026, 10, 26), f"t-cl-{owner['org_id']}")
    with SessionLocal() as db:
        snap = checking_snapshot(db, owner["org_id"], today=TODAY)
    # Today's balance is not claimed from a 9-day-old snapshot.
    assert snap["balance"] is None
    [line] = snap["credit_lines"]["accounts"]
    assert line["balance"] == -30000
    assert line["as_of"] == "2026-10-26"
    assert line["stale"] is True
    assert line["limit"] == 12000
    assert line["used"] == 30000
    assert line["available"] == -18000
    assert line["overrun"] == 18000
    assert line["status"] == "overrun"
    assert "26.10" in line["label_he"]
    assert snap["credit_lines"]["any_overrun"] is True


def test_missing_limit_is_missing_not_zero(fresh_org):
    owner = fresh_org()
    _checking(owner["org_id"], "עו״ש בלי מסגרת", "-500", None, datetime(2026, 11, 4), f"t-cl-{owner['org_id']}")
    with SessionLocal() as db:
        snap = checking_snapshot(db, owner["org_id"], today=TODAY)
    [line] = snap["credit_lines"]["accounts"]
    assert line["balance"] == -500
    assert line["stale"] is False
    assert line["limit"] is None
    assert line["available"] is None
    assert line["overrun"] is None
    assert line["status"] == "unknown"
    assert snap["credit_lines"]["any_overrun"] is False


def test_within_limit_and_the_overview_shows_the_same_lines(fresh_org):
    owner = fresh_org()
    _checking(owner["org_id"], "עו״ש תקין", "-4000", "10000", datetime(2026, 11, 4), f"t-cl-a-{owner['org_id']}")
    _checking(owner["org_id"], "עו״ש בחריגה", "-25000", "20000", datetime(2026, 11, 3), f"t-cl-b-{owner['org_id']}")
    with SessionLocal() as db:
        snap = checking_snapshot(db, owner["org_id"], today=TODAY)
        by_name = {line["name"]: line for line in snap["credit_lines"]["accounts"]}
        assert by_name["עו״ש תקין"]["status"] == "within"
        assert by_name["עו״ש תקין"]["available"] == 6000
        assert by_name["עו״ש תקין"]["overrun"] == 0
        assert by_name["עו״ש בחריגה"]["overrun"] == 5000
        overview = DashboardService(db, owner["org_id"]).get_overview(today=TODAY)
    assert overview["credit_lines"] == snap["credit_lines"]


def test_liquidity_today_reports_the_overrun_on_the_last_booked_balance():
    from cfo.services.dashboards.liquidity_today import build_liquidity_today

    liquidity = {
        "position": {"balance": None, "as_of": None, "limit": 12000},
        "stale_balances": [{"observed_balance": -30000, "as_of": "2026-10-26"}],
    }
    today = build_liquidity_today(liquidity, {}, today=TODAY)
    assert today["checking"]["balance"] is None
    facility = today["facility"]
    assert facility["overrun"] == 18000
    assert facility["overrun_status"] == "overrun"
    assert facility["basis"] == "last_booked"
    assert facility["as_of"] == "2026-10-26"
