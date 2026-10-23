"""The /d/ view reads each entity's bank rows, card accounts and coverage once per
request (``read_memo``). The memo must not change a single number, must not outlive
the build, and keeps the query count of a two-entity view under a ratchet."""
import contextlib
from datetime import date

from sqlalchemy import event

from cfo.database import SessionLocal, engine
from cfo.models import ClientDashboard
from cfo.services import bank_coverage, read_memo
from cfo.services.dashboards import multi_entity, view_model
from tests.test_dashboard_eliav_ui_fixes import _account, _bank, _consolidated

# Two entities, a reviewed local import on one of them. 132 queries before the memo.
QUERY_CEILING = 90


def _two_entity_dashboard(client, platform_admin, fresh_org, slug):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, slug)
    with SessionLocal() as db:
        chef_main = _account(db, chef["org_id"], "עו״ש 8954", 0).id
        food_main = _account(db, food["org_id"], "Imported bank 1662", None, source="reviewed_local_import").id
        _bank(db, chef["org_id"], date(2026, 6, 10), 11800, "הפקדת מזומן", account_id=chef_main)
        _bank(db, chef["org_id"], date(2026, 8, 3), 2360, "הפקדת מזומן", account_id=chef_main)
        _bank(db, chef["org_id"], date(2026, 9, 2), 5000, "העברה מבנק הפועלים", account_id=chef_main)
        _bank(db, food["org_id"], date(2026, 8, 30), -5000, "העברה לשף", account_id=food_main)
        _bank(db, food["org_id"], date(2026, 8, 5), -500, "בזק", account_id=food_main)
        db.commit()
    return dashboard_id


def _build(dashboard_id):
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, dashboard_id)
        return multi_entity.build_dashboard_view(
            db, dashboard, date(2026, 6, 1), date(2026, 9, 30), plan=view_model.plan_payload(db, dashboard_id),
        )


def test_the_memo_changes_no_number_of_the_view(client, fresh_org, platform_admin, monkeypatch):
    dashboard_id = _two_entity_dashboard(client, platform_admin, fresh_org, "memo-same-view")
    with_memo = _build(dashboard_id)
    monkeypatch.setattr(multi_entity, "read_memo", lambda db: contextlib.nullcontext())
    without_memo = _build(dashboard_id)
    assert with_memo == without_memo
    assert with_memo["combined"]["intercompany_removed"]["pairs"] == 1


def test_the_memo_ends_with_the_build_and_a_later_row_is_seen(client, fresh_org, platform_admin):
    dashboard_id = _two_entity_dashboard(client, platform_admin, fresh_org, "memo-ends")
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, dashboard_id)
        org_id = dashboard.primary_organization_id
        multi_entity.build_dashboard_view(db, dashboard, date(2026, 6, 1), date(2026, 9, 30))
        assert read_memo._KEY not in db.info
        before = len(bank_coverage.window_rows(db, org_id, date(2026, 6, 1), date(2026, 9, 30)))
        _bank(db, org_id, date(2026, 9, 3), 100, "הפקדת מזומן")
        assert len(bank_coverage.window_rows(db, org_id, date(2026, 6, 1), date(2026, 9, 30))) == before + 1


def test_inside_the_memo_a_reader_gets_a_copy(fresh_org):
    org = fresh_org()
    with SessionLocal() as db, read_memo.read_memo(db):
        first = bank_coverage.window_rows(db, org["org_id"], date(2026, 1, 1), date(2026, 1, 31))
        first.append("not a row")
        assert bank_coverage.window_rows(db, org["org_id"], date(2026, 1, 1), date(2026, 1, 31)) == []


def test_query_count_of_a_two_entity_view_stays_under_the_ratchet(client, fresh_org, platform_admin):
    dashboard_id = _two_entity_dashboard(client, platform_admin, fresh_org, "memo-ratchet")
    _build(dashboard_id)  # warm the imports
    count = {"n": 0}

    def _count(*_args):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        _build(dashboard_id)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert count["n"] <= QUERY_CEILING, count["n"]
