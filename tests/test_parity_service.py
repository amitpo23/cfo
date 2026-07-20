"""PR3 של תוכנית מחזור-הבוקר — התאמה משולשת יומית-קלה (Open Finance ↔ Rezef DB
↔ SUMIT). כל בדיקה בודדת: freshness, of_balance_walk, internal_double_computation,
sumit_crosscheck. ר' docs/bookkeeper_kb/00-role-and-daily-order.md, צעד 1."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, BankTransaction, Bill, BillStatus, CfoInsight,
    DailySnapshot, Expense, FilingCrosscheck, Invoice, InvoiceStatus,
    SyncCheckpoint,
)
from cfo.services import parity_service as ps


AS_OF = date(2026, 5, 20)


def _mk_checkpoint(db, org_id, *, source, entity_type, hours_ago=1):
    db.add(SyncCheckpoint(
        organization_id=org_id, source=source, entity_type=entity_type,
        last_success_at=datetime.utcnow() - timedelta(hours=hours_ago),
    ))


def _seed_fresh_checkpoints(db, org_id):
    _mk_checkpoint(db, org_id, source="sumit", entity_type="invoices")
    _mk_checkpoint(db, org_id, source="sumit", entity_type="bills")
    _mk_checkpoint(db, org_id, source="open_finance", entity_type="accounts")
    _mk_checkpoint(db, org_id, source="open_finance", entity_type="bank_transactions")


def _mk_of_account(db, org_id, *, balance, balance_as_of, name="עו\"ש ראשי"):
    acc = Account(
        organization_id=org_id, name=name, account_type=AccountType.BANK,
        balance=Decimal(str(balance)), currency="ILS", source="open_finance",
        balance_as_of=balance_as_of,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_bank_txn(db, org_id, *, amount, txn_date, account_id=None):
    t = BankTransaction(
        organization_id=org_id, source="open_finance",
        transaction_date=txn_date, amount=Decimal(str(amount)),
        description="test", account_id=account_id,
    )
    db.add(t)
    return t


def _mk_snapshot(db, org_id, *, snapshot_date, cash_balance):
    db.add(DailySnapshot(organization_id=org_id, snapshot_date=snapshot_date,
                         cash_balance=Decimal(str(cash_balance))))


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

def test_freshness_ok_when_both_sources_synced_recently(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        freshness = result["checks"][0]
        assert freshness["name"] == "freshness"
        assert freshness["status"] == "ok"
        assert freshness["sumit"]["stale"] is False
        assert freshness["open_finance"]["stale"] is False
        for c in result["checks"][1:]:
            assert c["authoritative"] is True
    finally:
        db.close()


def test_freshness_stale_when_sumit_checkpoint_old(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_checkpoint(db, org_id, source="sumit", entity_type="invoices", hours_ago=48)
        _mk_checkpoint(db, org_id, source="sumit", entity_type="bills", hours_ago=48)
        _mk_checkpoint(db, org_id, source="open_finance", entity_type="accounts")
        _mk_checkpoint(db, org_id, source="open_finance", entity_type="bank_transactions")
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        freshness = result["checks"][0]
        assert freshness["status"] == "stale"
        assert freshness["sumit"]["stale"] is True
        assert freshness["open_finance"]["stale"] is False
        assert "SUMIT" in freshness["details_he"]
        assert result["status"] == "stale"
        for c in result["checks"][1:]:
            assert c["authoritative"] is False
    finally:
        db.close()


def test_freshness_stale_when_of_checkpoint_old(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_checkpoint(db, org_id, source="sumit", entity_type="invoices")
        _mk_checkpoint(db, org_id, source="sumit", entity_type="bills")
        _mk_checkpoint(db, org_id, source="open_finance", entity_type="accounts", hours_ago=48)
        _mk_checkpoint(db, org_id, source="open_finance", entity_type="bank_transactions", hours_ago=48)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        freshness = result["checks"][0]
        assert freshness["status"] == "stale"
        assert freshness["sumit"]["stale"] is False
        assert freshness["open_finance"]["stale"] is True
        assert "Open Finance" in freshness["details_he"]
    finally:
        db.close()


def test_filing_verification_sync_freshness_still_sumit_only_and_unparameterized_call():
    """sync_freshness בברירת-מחדל (בלי ארגומנטים) חייב להישאר מזוהה עם ההתנהגות
    שה-wrapper הישן ב-filing_verification._sync_freshness חשף — לא רק שה-import
    עובד, גם שהחתימה שומרת על ברירות המחדל (source='sumit', invoices+bills)."""
    import inspect
    sig = inspect.signature(ps.sync_freshness)
    assert sig.parameters["source"].default == "sumit"
    assert tuple(sig.parameters["entity_types"].default) == ("invoices", "bills")


# ---------------------------------------------------------------------------
# of_balance_walk
# ---------------------------------------------------------------------------

def test_balance_walk_ok_within_tolerance(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1050,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "ok"
        assert walk["expected"] == 1050.0
        assert walk["actual"] == 1050.0
    finally:
        db.close()


def test_balance_walk_mismatch_beyond_tolerance(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1200,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "mismatch"
        assert walk["diff"] == 150.0
        assert result["status"] == "mismatch"
    finally:
        db.close()


def test_balance_walk_skipped_when_no_prior_snapshot(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_of_account(db, org_id, balance=1000,
                       balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "skipped"
        assert "snapshot" in walk["details_he"] or "תמונת-מצב" in walk["details_he"]
    finally:
        db.close()


def test_balance_walk_skipped_when_no_of_accounts(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "skipped"
    finally:
        db.close()


def test_balance_walk_skipped_on_stale_balance_as_of_timing_guard(fresh_org):
    """יתרת חשבון ישנה מהתנועה האחרונה הידועה — פער-תזמון, לא פער אמיתי. אסור
    לסמן mismatch כשהסיבה האמיתית היא ש-Open Finance לא בזמן-אמת (תנועות
    pending לא גלויות עד שהן נבקעות)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        snap_date = AS_OF - timedelta(days=1)
        _mk_snapshot(db, org_id, snapshot_date=snap_date, cash_balance=1000)
        # balance_as_of ישן משמעותית מהתנועה שנקלטה ב-AS_OF
        acc = _mk_of_account(db, org_id, balance=1050,
                             balance_as_of=datetime.combine(snap_date, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "skipped"
        assert "תזמון" in walk["details_he"] or "ישנה" in walk["details_he"]
    finally:
        db.close()


def test_balance_walk_skipped_when_balance_as_of_newer_than_as_of(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        _mk_of_account(db, org_id, balance=1000,
                       balance_as_of=datetime.combine(AS_OF + timedelta(days=2), datetime.min.time()))
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "skipped"
        assert "עתיד" in walk["details_he"] or "מאוחרת" in walk["details_he"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# internal_double_computation
# ---------------------------------------------------------------------------

def _seed_pl_data(db, org_id):
    db.add(Invoice(organization_id=org_id, source="manual", invoice_number="I1",
                   issue_date=AS_OF, status=InvoiceStatus.SENT,
                   subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180")))
    db.add(Bill(organization_id=org_id, source="manual", bill_number="B1",
               issue_date=AS_OF, status=BillStatus.APPROVED,
               subtotal=Decimal("400"), tax=Decimal("72"), total=Decimal("472")))
    db.add(Expense(organization_id=org_id, source="manual", supplier_name="ספק",
                   amount=Decimal("200"), vat_amount=Decimal("36"), total=Decimal("236"),
                   expense_date=AS_OF, status="filed"))


def test_internal_double_computation_ok_on_clean_data(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _seed_pl_data(db, org_id)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        dc = next(c for c in result["checks"] if c["name"] == "internal_double_computation")
        assert dc["status"] == "ok"
        assert dc["diff_revenue"] == 0
        assert dc["diff_expense"] == 0
    finally:
        db.close()


def test_internal_double_computation_mismatch_when_forced_divergence(fresh_org, monkeypatch):
    """שתי דרכי החישוב אמורות תמיד להתאים על אותה אוכלוסיית מסמכים בפועל —
    כדי לבדוק שגלאי-האי-עקביות עצמו עובד נכון (מזהה פער, מחשב אותו נכון,
    ומסמן mismatch), מדמים באג בדרך אחת (cumulative_pl) דרך monkeypatch,
    ומוודאים שההשוואה תופסת את זה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _seed_pl_data(db, org_id)
        db.commit()

        from cfo.services import daily_reports_service

        real_cumulative_pl = daily_reports_service.cumulative_pl

        def _broken(db_, org_id_, year, month):
            out = real_cumulative_pl(db_, org_id_, year, month)
            out["totals"]["revenue"] = out["totals"]["revenue"] + 500
            return out

        monkeypatch.setattr(daily_reports_service, "cumulative_pl", _broken)

        result = ps.run_daily_parity(db, org_id, AS_OF)
        dc = next(c for c in result["checks"] if c["name"] == "internal_double_computation")
        assert dc["status"] == "mismatch"
        assert dc["diff_revenue"] == 500.0
        assert result["status"] == "mismatch"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# sumit_crosscheck
# ---------------------------------------------------------------------------

def test_crosscheck_absent_is_skipped(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        cc = next(c for c in result["checks"] if c["name"] == "sumit_crosscheck")
        assert cc["status"] == "skipped"
        assert "הצלבה" in cc["details_he"]
    finally:
        db.close()


def test_crosscheck_present_match(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _seed_pl_data(db, org_id)
        db.add(FilingCrosscheck(organization_id=org_id, period="2026-05", basis="document",
                                books_input_vat=Decimal("108.00"), books_output_vat=Decimal("180.00")))
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        cc = next(c for c in result["checks"] if c["name"] == "sumit_crosscheck")
        assert cc["status"] == "ok"
    finally:
        db.close()


def test_crosscheck_present_mismatch(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _seed_pl_data(db, org_id)
        db.add(FilingCrosscheck(organization_id=org_id, period="2026-05", basis="document",
                                books_input_vat=Decimal("999.00"), books_output_vat=Decimal("180.00")))
        db.commit()
        result = ps.run_daily_parity(db, org_id, AS_OF)
        cc = next(c for c in result["checks"] if c["name"] == "sumit_crosscheck")
        assert cc["status"] == "mismatch"
        assert cc["diff_input_vat"] > 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# check_and_alert: fingerprint dedup + auto-resolve
# ---------------------------------------------------------------------------

def test_check_and_alert_creates_insight_for_mismatching_check(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1200,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()

        result = ps.check_and_alert(db, org_id, AS_OF)
        assert result["status"] == "mismatch"
        assert len(result["alerted"]) >= 1

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == "parity:of_balance_walk:2026-05",
        ).first()
        assert insight is not None
        assert insight.insight_type == "parity_mismatch"
        assert insight.severity == "high"
        assert insight.status == "active"
        assert any("֐" <= ch <= "׿" for ch in (insight.message or ""))
    finally:
        db.close()


def test_check_and_alert_dedups_on_fingerprint_across_double_run(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1200,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()

        ps.check_and_alert(db, org_id, AS_OF)
        ps.check_and_alert(db, org_id, AS_OF)

        rows = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == "parity:of_balance_walk:2026-05",
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_check_and_alert_resolves_when_back_to_ok(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1200,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()

        ps.check_and_alert(db, org_id, AS_OF)
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == "parity:of_balance_walk:2026-05",
        ).first()
        assert insight.status == "active"

        # מתקנים את הפער — היתרה בפועל חוזרת להתאים.
        acc.balance = Decimal("1050")
        db.commit()

        result = ps.check_and_alert(db, org_id, AS_OF)
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "ok"

        db.refresh(insight)
        assert insight.status == "resolved"
        assert insight.resolved_at is not None
    finally:
        db.close()


def test_check_and_alert_does_not_create_insight_for_nonauthoritative_mismatch(fresh_org):
    """כשהטריות נכשלה (SUMIT ישן), of_balance_walk הופך ל-authoritative=False
    — גם אם המספרים מראים "mismatch", אסור להתריע high על נתונים שכבר
    הוכרזו לא-אמינים (run_daily_parity עצמו מדווח status='stale', לא
    'mismatch'; check_and_alert חייב להסכים)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_checkpoint(db, org_id, source="sumit", entity_type="invoices", hours_ago=48)
        _mk_checkpoint(db, org_id, source="sumit", entity_type="bills", hours_ago=48)
        _mk_checkpoint(db, org_id, source="open_finance", entity_type="accounts")
        _mk_checkpoint(db, org_id, source="open_finance", entity_type="bank_transactions")
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1200,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()

        result = ps.check_and_alert(db, org_id, AS_OF)
        assert result["status"] == "stale"
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "mismatch"
        assert walk["authoritative"] is False
        assert result["alerted"] == []

        rows = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == "parity:of_balance_walk:2026-05",
        ).all()
        assert len(rows) == 0
    finally:
        db.close()


def test_check_and_alert_does_not_resolve_active_insight_on_nonauthoritative_ok(fresh_org):
    """התראה אמיתית שכבר נפתחה (מ-mismatch סמכותי) לא נסגרת ע"י check_and_alert
    כשהריצה הבאה מחזירה 'ok' אבל על בסיס נתונים לא-טריים — סגירה כזו הייתה
    משתיקה אזעקה אמיתית על בסיס נתונים שאי-אפשר לסמוך עליהם."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_fresh_checkpoints(db, org_id)
        _mk_snapshot(db, org_id, snapshot_date=AS_OF - timedelta(days=1), cash_balance=1000)
        acc = _mk_of_account(db, org_id, balance=1200,
                             balance_as_of=datetime.combine(AS_OF, datetime.min.time()))
        _mk_bank_txn(db, org_id, amount=50, txn_date=AS_OF, account_id=acc.id)
        db.commit()

        ps.check_and_alert(db, org_id, AS_OF)
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == "parity:of_balance_walk:2026-05",
        ).first()
        assert insight.status == "active"

        # התיקון בפועל: היתרה מתאימה עכשיו — אבל הסנכרון האחרון של SUMIT ישן
        # (48 שעות), כך שהבדיקה הופכת ל-authoritative=False.
        acc.balance = Decimal("1050")
        db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id, SyncCheckpoint.source == "sumit",
        ).update({"last_success_at": datetime.utcnow() - timedelta(hours=48)})
        db.commit()

        result = ps.check_and_alert(db, org_id, AS_OF)
        assert result["status"] == "stale"
        walk = next(c for c in result["checks"] if c["name"] == "of_balance_walk")
        assert walk["status"] == "ok"
        assert walk["authoritative"] is False
        assert result["resolved_insight_ids"] == []

        db.refresh(insight)
        assert insight.status == "active"
    finally:
        db.close()


def test_sumit_only_org_never_synced_of_suppresses_all_downstream_checks(fresh_org, monkeypatch):
    """מגבלה ידועה (לא באג): ארגון שעדיין לא השלים את מסע ה-consent של Open
    Finance (יש כאלה בפרודקשן — ר' Open Finance integration state) לעולם לא
    יקבל checkpoint ל-source='open_finance', כך שהבדיקה הכוללת נשארת "stale"
    לצמיתות וכל הבדיקות הבאות מסומנות authoritative=False — כולל
    internal_double_computation ו-sumit_crosscheck, ששתיהן כלל לא תלויות
    ב-Open Finance. זו התנהגות מכוונת לפי המפרט ("אם מקור כלשהו לא-טרי, כל
    ההמשך לא-סמכותי") ולא עיוות בקוד — אבל המשמעות התפעולית היא ש-check_and_alert
    לא יתריע על אי-עקביות רו"ה/הצלבת-SUMIT אמיתית לארגונים כאלה עד שיושלם
    onboarding ל-Open Finance. הבדיקה כאן נועדה לנעול (pin) את ההתנהגות
    הזו במפורש כדי שמישהו לא "יתקן" אותה בעתיד לידי אזעקות-שווא."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_checkpoint(db, org_id, source="sumit", entity_type="invoices")
        _mk_checkpoint(db, org_id, source="sumit", entity_type="bills")
        # אין checkpoints ל-open_finance כלל — ארגון SUMIT-בלבד.
        _seed_pl_data(db, org_id)
        db.commit()

        from cfo.services import daily_reports_service

        real_cumulative_pl = daily_reports_service.cumulative_pl

        def _broken(db_, org_id_, year, month):
            out = real_cumulative_pl(db_, org_id_, year, month)
            out["totals"]["revenue"] = out["totals"]["revenue"] + 500
            return out

        monkeypatch.setattr(daily_reports_service, "cumulative_pl", _broken)

        result = ps.check_and_alert(db, org_id, AS_OF)
        assert result["status"] == "stale"
        dc = next(c for c in result["checks"] if c["name"] == "internal_double_computation")
        assert dc["status"] == "mismatch"  # המספרים כן מגלים אי-עקביות אמיתית...
        assert dc["authoritative"] is False  # ...אבל מסומנת לא-סמכותית בגלל OF
        assert result["alerted"] == []  # ...ולכן check_and_alert לא מתריע עליה
    finally:
        db.close()
