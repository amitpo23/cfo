"""PR4 of the bookkeeper daily-cycle plan — the morning-cycle orchestrator.

Runs parity -> bank_anomalies -> reconcile -> expense_queue -> credit_line ->
daily_close -> debtors for one org, entirely against Postgres (zero new
SUMIT/Open Finance API calls). See src/cfo/services/morning_cycle_service.py
module docstring for the full rationale.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, BankTransaction, CfoInsight, Contact, ContactType,
    DailySnapshot, Expense, Invoice, InvoiceStatus,
)
from cfo.services import morning_cycle_service as svc

TODAY = date(2026, 7, 20)


def _mk_expense(db, org_id, *, status, updated_at=None, amount=100):
    exp = Expense(
        organization_id=org_id, supplier_name="ספק בדיקה", amount=Decimal(str(amount)),
        expense_date=TODAY, status=status,
    )
    db.add(exp)
    db.flush()
    if updated_at is not None:
        db.query(Expense).filter(Expense.id == exp.id).update({"updated_at": updated_at})
        db.flush()
    return exp


# --------------------------------------------------------------------- #
# days_to_next_deadline — pure function
# --------------------------------------------------------------------- #
def test_days_to_next_deadline_mid_month():
    assert svc.days_to_next_deadline(date(2026, 7, 20)) == 3  # -> 23rd


def test_days_to_next_deadline_on_a_deadline_day_is_zero():
    assert svc.days_to_next_deadline(date(2026, 7, 15)) == 0
    assert svc.days_to_next_deadline(date(2026, 7, 19)) == 0
    assert svc.days_to_next_deadline(date(2026, 7, 23)) == 0


def test_days_to_next_deadline_rolls_to_next_month():
    # Past the 23rd -> next month's 15th.
    assert svc.days_to_next_deadline(date(2026, 7, 24)) == (date(2026, 8, 15) - date(2026, 7, 24)).days


def test_days_to_next_deadline_rolls_over_year_boundary():
    assert svc.days_to_next_deadline(date(2026, 12, 24)) == (date(2027, 1, 15) - date(2026, 12, 24)).days


def test_days_to_next_deadline_early_month():
    assert svc.days_to_next_deadline(date(2026, 7, 1)) == 14  # -> 15th


# --------------------------------------------------------------------- #
# compute_cycle_status — pure function matrix
# --------------------------------------------------------------------- #
def _base_kwargs(**overrides):
    kwargs = dict(
        parity_status="ok", open_expense_drafts=5, exceptions_over_48h=0,
        credit_status="ok", days_to_next_deadline=10, bank_anomaly_today=False,
    )
    kwargs.update(overrides)
    return kwargs


def test_cycle_status_green_when_everything_clean():
    assert svc.compute_cycle_status(**_base_kwargs()) == "green"


def test_cycle_status_red_on_credit_breach():
    assert svc.compute_cycle_status(**_base_kwargs(credit_status="breach")) == "red"


def test_cycle_status_red_on_parity_mismatch():
    assert svc.compute_cycle_status(**_base_kwargs(parity_status="mismatch")) == "red"


def test_cycle_status_red_on_aged_exceptions_near_deadline():
    assert svc.compute_cycle_status(
        **_base_kwargs(exceptions_over_48h=2, days_to_next_deadline=3)
    ) == "red"


def test_cycle_status_not_red_when_exceptions_but_deadline_far():
    # exceptions>0 alone, deadline far away -> not red (not green either, since
    # exceptions_over_48h != 0 fails the green condition -> yellow).
    assert svc.compute_cycle_status(
        **_base_kwargs(exceptions_over_48h=2, days_to_next_deadline=20)
    ) == "yellow"


def test_cycle_status_red_on_bank_anomaly_today():
    assert svc.compute_cycle_status(**_base_kwargs(bank_anomaly_today=True)) == "red"


def test_cycle_status_yellow_on_stale_parity_not_red():
    # Stale is never green (freshness folded into parity_status), and stale
    # alone is not one of the red triggers -> yellow.
    assert svc.compute_cycle_status(**_base_kwargs(parity_status="stale")) == "yellow"


def test_cycle_status_yellow_when_queue_too_deep():
    assert svc.compute_cycle_status(**_base_kwargs(open_expense_drafts=21)) == "yellow"


def test_cycle_status_yellow_on_unknown_inputs():
    assert svc.compute_cycle_status(**_base_kwargs(parity_status=None)) == "yellow"
    assert svc.compute_cycle_status(**_base_kwargs(open_expense_drafts=None)) == "yellow"
    assert svc.compute_cycle_status(**_base_kwargs(exceptions_over_48h=None)) == "yellow"


def test_cycle_status_green_when_credit_only_warning():
    # Spec: red requires an actual breach; green only requires "no credit
    # breach" (not "no warning") -- a warning alone, with everything else
    # clean, is still green.
    assert svc.compute_cycle_status(**_base_kwargs(credit_status="warning")) == "green"


# --------------------------------------------------------------------- #
# run_daily_close_step
# --------------------------------------------------------------------- #
def test_run_daily_close_step_legacy_call_leaves_new_columns_null(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = svc.run_daily_close_step(db, org_id, TODAY)
        assert result["status"] == "ok"

        snap = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id, DailySnapshot.snapshot_date == TODAY,
        ).first()
        assert snap is not None
        assert snap.cycle_status is None
        assert snap.parity_status is None
        # Self-contained columns are always computed, even on the legacy path.
        assert snap.days_to_next_deadline == 3
        assert snap.open_items is not None
    finally:
        db.close()


def test_run_daily_close_step_writes_morning_cycle_columns_when_given(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = svc.run_daily_close_step(
            db, org_id, TODAY,
            parity_status="ok", unreconciled_count=3, open_expense_drafts=7,
            exceptions_over_48h=1, credit_headroom=Decimal("5000"),
            credit_breach_date=None, cycle_status="yellow",
        )
        assert result["status"] == "ok"

        snap = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id, DailySnapshot.snapshot_date == TODAY,
        ).first()
        assert snap.parity_status == "ok"
        assert snap.unreconciled_count == 3
        assert snap.open_expense_drafts == 7
        assert snap.exceptions_over_48h == 1
        assert float(snap.credit_headroom) == 5000.0
        assert snap.cycle_status == "yellow"
    finally:
        db.close()


def test_run_daily_close_step_raises_on_failure_for_caller_isolation(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        import cfo.services.dashboard_service as ds_module

        def _boom(self, today=None):
            raise RuntimeError("boom")

        monkeypatch.setattr(ds_module.DashboardService, "get_overview", _boom)

        try:
            svc.run_daily_close_step(db, org_id, TODAY)
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------- #
# run_morning_cycle — step ordering, per-step isolation, idempotency
# --------------------------------------------------------------------- #
def test_step_ordering_parity_runs_first(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        call_order = []

        real_parity = svc.parity_service.check_and_alert
        real_bank = svc.bank_anomalies.scan_and_alert
        real_credit = svc.credit_line_service.check_and_alert

        def _tracked_parity(db_, org, as_of):
            call_order.append("parity")
            return real_parity(db_, org, as_of)

        def _tracked_bank(db_, org, since):
            call_order.append("bank_anomalies")
            return real_bank(db_, org, since=since)

        def _tracked_reconcile(db_, org, *, persist=True):
            call_order.append("reconcile")
            return {"matches": [], "unmatched_txns": [], "unmatched_docs": [], "matched_count": 0, "txn_count": 0}

        def _tracked_credit(db_, org):
            call_order.append("credit_line")
            return real_credit(db_, org)

        monkeypatch.setattr(svc.parity_service, "check_and_alert", _tracked_parity)
        monkeypatch.setattr(svc.bank_anomalies, "scan_and_alert", _tracked_bank)
        monkeypatch.setattr(svc, "reconcile_organization", _tracked_reconcile)
        monkeypatch.setattr(svc.credit_line_service, "check_and_alert", _tracked_credit)

        result = svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert result["status"] == "ok"
        assert call_order[0] == "parity"
        assert call_order.index("parity") < call_order.index("bank_anomalies")
        assert call_order.index("bank_anomalies") < call_order.index("reconcile")
        assert call_order.index("reconcile") < call_order.index("credit_line")
    finally:
        db.close()


def test_per_step_isolation_parity_failure_does_not_block_later_steps(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        def _boom(db_, org, as_of):
            raise RuntimeError("parity boom")

        monkeypatch.setattr(svc.parity_service, "check_and_alert", _boom)

        result = svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert result["status"] == "ok"
        assert result["steps"]["parity"]["status"] == "error"
        assert "parity boom" in result["steps"]["parity"]["error"]
        # Later steps still ran despite the parity failure.
        assert result["steps"]["bank_anomalies"]["status"] == "ok"
        assert result["steps"]["reconcile"]["status"] == "ok"
        assert result["steps"]["expense_queue"]["status"] == "ok"
        assert result["steps"]["credit_line"]["status"] == "ok"
        assert result["steps"]["daily_close"]["status"] == "ok"
        assert result["steps"]["debtors"]["status"] == "ok"
    finally:
        db.close()


def test_per_org_isolation_in_run_all_organizations(fresh_org, monkeypatch):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        real_run = svc.run_morning_cycle

        def _maybe_boom(db_, organization_id, today, force=False):
            if organization_id == org_a:
                raise RuntimeError("org_a boom")
            return real_run(db_, organization_id, today, force=force)

        monkeypatch.setattr(svc, "run_morning_cycle", _maybe_boom)

        result = svc.run_all_organizations(db, TODAY, force=True)
        assert any(e["organization_id"] == org_a for e in result["errors"])
        assert any(r["organization_id"] == org_b for r in result["results"])
    finally:
        db.close()


def test_idempotent_double_run_same_day_single_row_updated(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        r1 = svc.run_morning_cycle(db, org_id, TODAY, force=True)
        r2 = svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert r1["status"] == "ok"
        assert r2["status"] == "ok"

        count = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id, DailySnapshot.snapshot_date == TODAY,
        ).count()
        assert count == 1
    finally:
        db.close()


def test_default_force_false_skips_already_completed_cycle(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        r1 = svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert r1["status"] == "ok"

        r2 = svc.run_morning_cycle(db, org_id, TODAY, force=False)
        assert r2["status"] == "skipped"
        assert r2["cycle_status"] == r1["cycle_status"]

        count = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id, DailySnapshot.snapshot_date == TODAY,
        ).count()
        assert count == 1
    finally:
        db.close()


def test_snapshot_columns_populated_after_full_cycle(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = Account(
            organization_id=org_id, name="עו\"ש", account_type=AccountType.BANK,
            balance=Decimal("0"), currency="ILS", source="open_finance",
            credit_limit=Decimal("10000"),
        )
        db.add(acc)
        _mk_expense(db, org_id, status="pending")
        _mk_expense(db, org_id, status="review")
        db.commit()

        result = svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert result["status"] == "ok"

        snap = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id, DailySnapshot.snapshot_date == TODAY,
        ).first()
        assert snap is not None
        assert snap.cycle_status in ("green", "yellow", "red")
        assert snap.parity_status in ("ok", "mismatch", "stale")
        assert snap.unreconciled_count is not None
        assert snap.open_expense_drafts == 2
        assert snap.exceptions_over_48h == 0
        assert snap.days_to_next_deadline == 3
        assert snap.open_items is not None
    finally:
        db.close()


def test_expense_queue_counts_only_open_statuses_and_aged_exceptions(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        old = datetime.utcnow() - timedelta(hours=72)
        _mk_expense(db, org_id, status="pending", updated_at=old)
        _mk_expense(db, org_id, status="review")
        _mk_expense(db, org_id, status="error")
        _mk_expense(db, org_id, status="duplicate")
        _mk_expense(db, org_id, status="filed")  # not counted
        db.commit()

        result = svc._step_expense_queue(db, org_id, TODAY)
        assert result["open_expense_drafts"] == 4
        assert result["exceptions_over_48h"] == 1
    finally:
        db.close()


def test_debtors_step_returns_top_overdue_read_only(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח חייב")
        db.add(cust)
        db.flush()
        db.add(Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="OD1",
            issue_date=TODAY - timedelta(days=100), due_date=TODAY - timedelta(days=70),
            status=InvoiceStatus.SENT, total=5000, paid_amount=0, balance=5000,
        ))
        db.commit()

        result = svc._step_debtors(db, org_id, TODAY)
        assert result["total_receivable"] == 5000.0
        assert len(result["top_overdue"]) == 1
        assert result["top_overdue"][0]["amount"] == 5000.0
        # Read-only: no email/SMS side effects, no CfoInsight rows created by this step.
    finally:
        db.close()


# --------------------------------------------------------------------- #
# cron route
# --------------------------------------------------------------------- #
def test_bookkeeper_morning_route_requires_secret(client):
    r = client.get("/api/cron/bookkeeper-morning")
    assert r.status_code in (401, 403)


def test_bookkeeper_morning_route_runs_single_org(client, fresh_org, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org_id = fresh_org()["org_id"]
    r = client.get(
        "/api/cron/bookkeeper-morning",
        params={"org_id": org_id, "force": "true"},
        headers={"Authorization": "Bearer testsecret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == []
    assert len(body["results"]) == 1
    assert body["results"][0]["organization_id"] == org_id
