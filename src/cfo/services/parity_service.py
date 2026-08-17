"""התאמה משולשת יומית-קלה (Open Finance ↔ Rezef DB ↔ SUMIT) — PR3 של תוכנית
מחזור-הבוקר של מנהל החשבונות (docs/bookkeeper_kb/00-role-and-daily-order.md,
צעד 1: "לא נוגעים במספר לפני שיודעים שהוא טרי ואמין").

ארבע בדיקות, בסדר-תלות (טריות קודמת לכול):

1. freshness — checkpoints של SUMIT ו-Open Finance בני ≤26 שעות (אותו שער
   בדיוק כמו filing_verification, מקודם לכאן ומפורמט ל-source כללי).
   אם מקור כלשהו לא-טרי — סטטוס כולל "stale" לכל היותר, וכל הבדיקות הבאות
   מסומנות authoritative=False (הן עדיין רצות ומדווחות, אבל לא נחשבות
   מכריעות — honest-null: לא משתיקים, מסמנים).
2. of_balance_walk — יתרת המזומן בפועל (Account.balance, חשבונות Open
   Finance) מול "הליכת-יתרה" עצמאית: snapshot יומי אחרון + סכום תנועות הבנק
   מאז. שערי-הגנה נגד אזעקות-שווא על בעיית-תזמון (לא על פער אמיתי).
3. internal_double_computation — רו"ה מצטבר-יומי (daily_reports_service.
   cumulative_pl) מול חישוב-ישיר עצמאי (_direct_pl_totals כאן) על אותה בדיוק
   אוכלוסיית מסמכים — "שתי דרכי חישוב לאותו מספר" (מודל מכונן, צעד 1 בטבלה).
4. sumit_crosscheck — אם קיימת רשומת FilingCrosscheck לתקופה הנוכחית, משווים
   מולה (אותה נוסחה כמו filing_verification.verify_filing בדיקה 3); אחרת —
   skipped, לא כשל (אין הצלבה מוקלטת עדיין).

תוצאה כוללת: "ok" | "mismatch" | "stale". mismatch גובר תמיד; stale רק אם
שום בדיקה סמכותית לא נכשלה בפועל; אחרת ok.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Sequence

# שער טריות סנכרון (זהה ל-filing_verification.STALE_SYNC_HOURS — מקור אמת יחיד
# כאן; filing_verification עוטף ומייבא).
STALE_SYNC_HOURS = 26

# סובלנות בדיקת הליכת-היתרה (of_balance_walk): קבוע הניתן לכיוונון (עיגולי-
# בנק, ריבוי תנועות), אך לעולם לא מתחת לרצפה המוחלטת של ₪1.
OF_BALANCE_WALK_TOLERANCE = 1.0

# סובלנות ה"רו"ה בשתי דרכי חישוב" — פער מעבר לזה מעיד על אי-עקביות פנימית
# אמיתית (לא עיגול), כי שתי הדרכים אמורות לצבור בדיוק אותה אוכלוסיית מסמכים.
INTERNAL_DOUBLE_COMPUTATION_TOLERANCE = 1.0

# סובלנות ההצלבה מול ספרי SUMIT — זהה לזו שבשימוש בבדיקה 3 של
# filing_verification.verify_filing (שם: פער ≤ ₪1 = התאמה).
SUMIT_CROSSCHECK_TOLERANCE = 1.0

INSIGHT_TYPE = "parity_mismatch"

# ==================================================================== #
# רישום הבדיקות — מקור אמת יחיד לריצה היומית **ולצ'ק-ליסט של מושקו**
# ==================================================================== #
# `run_daily_parity` מריצה מכאן, ו-`render_parity_checklist_he` מייצרת
# מכאן את docs/bookkeeper_kb/14-parity-check.md. שני כיוונים נאכפים ב-
# tests/test_parity_checklist_generated.py, כדי שלא יחזור הכשל של
# kb_loader: מסמכים שנכתבו, לא נרשמו, והטסטים המשיכו לעבור בזמן שמושקו
# לא ראה אותם.
#
# `compares` הוא השדה שעונה על השאלה "איזו צלע של המשולש נבדקה" — הוא מה
# שחשף ששתי צלעות מדלגות בשקט בזמן שההכרעה ירוקה.
PARITY_CHECKS: tuple[dict[str, str], ...] = (
    {
        "key": "freshness",
        "title_he": "טריות הסנכרון",
        "compares": "חותמות סנכרון SUMIT ו-Open Finance מול השעון",
        "blocks_he": (
            f"מקור שלא סונכרן מעל {STALE_SYNC_HOURS} שעות. אז כל הבדיקות "
            "הבאות מסומנות לא-סמכותיות — הן מדווחות אך אינן מכריעות."
        ),
    },
    {
        "key": "of_balance_walk",
        "title_he": "הילוך יתרות הבנק",
        "compares": "יתרת החשבון בפועל (Open Finance) מול snapshot אחרון + תנועות מאז",
        "blocks_he": "אין חשבונות Open Finance מחוברים, או אין snapshot קודם → skipped.",
    },
    {
        "key": "internal_double_computation",
        "title_he": "רו״ה בשתי דרכי חישוב",
        "compares": "רצף מול רצף — מצטבר-יומי מול חישוב ישיר על אותה אוכלוסייה",
        "blocks_he": (
            "ארבעה אפסים בשני הצדדים → unknown, לא ok. אין נתונים אינו "
            "התאמה."
        ),
    },
    {
        "key": "sumit_crosscheck",
        "title_he": "הצלבה מול ספרי SUMIT",
        "compares": "מע״מ תשומות/עסקאות ברצף מול ערכי SUMIT שהוקלדו (FilingCrosscheck)",
        "blocks_he": (
            "אין רשומת FilingCrosscheck לתקופה → skipped. זו הצלע שדורשת "
            "הקלדה ידנית מהפורטל, ולכן היא הצלע שנוטה להיעדר."
        ),
    },
)


def render_parity_checklist_he() -> str:
    """מייצר את גוף הצ'ק-ליסט. נכתב לדיסק ע"י scripts/render_bookkeeper_kb.py."""
    lines = [
        "| # | בדיקה | מה מושווה מול מה | מה חוסם / מה מדלג |",
        "|---|-------|------------------|--------------------|",
    ]
    for idx, c in enumerate(PARITY_CHECKS, start=1):
        lines.append(
            f"| {idx} | **{c['title_he']}** | {c['compares']} | {c['blocks_he']} |"
        )
    return "\n".join(lines)


def sync_freshness(
    db,
    org_id: int,
    *,
    source: str = "sumit",
    entity_types: Sequence[str] = ("invoices", "bills"),
    source_label_he: str = "SUMIT",
) -> dict[str, Any]:
    """מועד המשיכה המוצלחת האחרונה של מקור נתונים (SUMIT או Open Finance)
    לארגון. מקודם מ-filing_verification._sync_freshness (PR3 — daily-cycle
    parity) כדי שגם parity_service וגם filing_verification ישתמשו באותו
    מקור-אמת יחיד, בלי שכפול-קוד. הפרמטרים source/entity_types/source_label_he
    מברירת-המחדל משחזרים בדיוק את ההתנהגות המקורית (SUMIT, invoices+bills) —
    filing_verification._sync_freshness הפך ל-wrapper דק שקורא לכאן בלי
    ארגומנטים, כך שהתנהגותו (כולל נוסח ההודעות) נשארת זהה-ביט וטסטיו לא זזים.

    מקור האמת: SyncCheckpoint.last_success_at פר-ישות — לא SyncRun. ריצה
    שעתית נרשמת COMPLETED גם כשה-circuit breaker דילג על כל הישויות (אומת
    חי 13/07: org 1 עם ריצות "COMPLETED" בזמן שה-checkpoints שלו ללא הצלחה
    ובמעגל פתוח בגלל חסימת ה-obligo) — כך שסינון לפי ריצות מפספס בדיוק את
    המצב שהשער נועד לתפוס. fallback ל-SyncRun רק כשאין checkpoints (ארגון
    מלפני M1)."""
    from ..models import SyncRun, SyncStatus

    circuit_until = None
    last_success = None
    try:
        from ..models import SyncCheckpoint

        cps = db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == source,
            SyncCheckpoint.entity_type.in_(list(entity_types)),
        ).all()
        if cps:
            successes = [cp.last_success_at for cp in cps if cp.last_success_at]
            last_success = max(successes) if successes else None
            opens = [cp.circuit_open_until for cp in cps
                     if cp.circuit_open_until and cp.circuit_open_until > datetime.utcnow()]
            circuit_until = max(opens) if opens else None
            if last_success is None:
                msg = (f"⚠️ אזהרה חמורה: משיכת המסמכים מ-{source_label_he} מעולם לא הצליחה "
                       "לארגון זה (checkpoints ללא הצלחה)")
                if circuit_until:
                    msg += f"; הסנכרון מושהה עד {circuit_until.isoformat()} בגלל חסימת API"
                return {"stale": True, "last_sync_at": None, "hours_since": None,
                        "circuit_open_until": circuit_until.isoformat() if circuit_until else None,
                        "message": msg + " — אין להגיש בלי רענון."}
    except Exception:  # טבלת checkpoints לא קיימת (סביבה ישנה) — fallback לריצות
        pass

    if last_success is None:
        succeeded = [SyncStatus.COMPLETED, SyncStatus.PARTIAL]
        last_run = db.query(SyncRun).filter(
            SyncRun.organization_id == org_id,
            SyncRun.source == source,
            SyncRun.status.in_(succeeded),
            SyncRun.finished_at.isnot(None),
        ).order_by(SyncRun.finished_at.desc()).first()
        if not last_run or not last_run.finished_at:
            return {
                "stale": True, "last_sync_at": None, "hours_since": None,
                "message": (
                    f"⚠️ אזהרה חמורה: מעולם לא בוצע סנכרון {source_label_he} מוצלח לארגון זה — "
                    "אין להגיש דיווח על בסיס נתונים שלא סונכרנו מעולם."
                ),
            }
        last_success = last_run.finished_at

    hours = (datetime.utcnow() - last_success).total_seconds() / 3600.0
    last_sync_iso = last_success.isoformat()
    if hours <= STALE_SYNC_HOURS:
        return {"stale": False, "last_sync_at": last_sync_iso,
                "hours_since": round(hours, 1), "message": None}

    age = f"{hours / 24:.1f} ימים" if hours >= 48 else f"{hours:.1f} שעות"
    return {
        "stale": True, "last_sync_at": last_sync_iso, "hours_since": round(hours, 1),
        "message": (
            f"⚠️ הנתונים בני {age} — משיכת מסמכי {source_label_he} אחרונה: "
            f"{last_success.date().isoformat()}; אין להגיש בלי רענון."
        ),
    }


def _check_freshness(db, org_id: int) -> tuple[dict[str, Any], bool]:
    """בדיקה 1: טריות SUMIT + Open Finance. מחזיר (check, authoritative) —
    authoritative חל על *הבדיקות הבאות* (לא על הבדיקה הזו עצמה, שהיא מטא-מידע
    על מצב הטריות ותמיד "סמכותית" באשר להערכתה את עצמה)."""
    sumit_fresh = sync_freshness(db, org_id)
    of_fresh = sync_freshness(
        db, org_id, source="open_finance",
        entity_types=("accounts", "bank_transactions"),
        source_label_he="Open Finance",
    )
    stale_sources = []
    if sumit_fresh["stale"]:
        stale_sources.append("SUMIT")
    if of_fresh["stale"]:
        stale_sources.append("Open Finance")

    if stale_sources:
        details_he = (
            "מקורות לא-טריים (מעל 26 שעות מאז סנכרון מוצלח): " + ", ".join(stale_sources)
            + " — כל הבדיקות הבאות מסומנות כלא-סמכותיות עד לרענון."
        )
    else:
        details_he = "SUMIT ו-Open Finance טריים (סנכרון מוצלח ב-26 השעות האחרונות)."

    check = {
        "name": "freshness",
        "status": "stale" if stale_sources else "ok",
        "authoritative": True,
        "details_he": details_he,
        "sumit": sumit_fresh,
        "open_finance": of_fresh,
    }
    return check, (not stale_sources)


def _check_of_balance_walk(db, org_id: int, as_of: date) -> dict[str, Any]:
    """בדיקה 2 (ברמת ארגון): יתרת המזומן בפועל (Σ Account.balance, חשבונות
    Open Finance) מול "הליכת-יתרה" עצמאית — ה-snapshot היומי האחרון *לפני*
    as_of (cash_balance לא-ריק) + סכום תנועות הבנק (Open Finance) שקרו מאז.

    שני שערי-הגנה נגד אזעקת-שווא (לא נגד פער אמיתי): נתוני Open Finance אינם
    בזמן-אמת (תנועות ממתינות/pending אינן גלויות עד שהן "נבקעות" — booked),
    כך ש-Σ(תנועות שנקלטו) יכול לפגר אחרי היתרה בפועל. אם יתרת חשבון-כלשהו
    ישנה מהתנועה האחרונה הידועה, או מאוחרת מ-as_of עצמו — משווים תפוחים
    לתפוזים; מסמנים "skipped" עם הסיבה, לא "mismatch"."""
    from ..models import Account, AccountType, BankTransaction, DailySnapshot

    snapshot = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.organization_id == org_id,
            DailySnapshot.snapshot_date < as_of,
            DailySnapshot.cash_balance.isnot(None),
        )
        .order_by(DailySnapshot.snapshot_date.desc())
        .first()
    )
    if snapshot is None:
        return {
            "name": "of_balance_walk", "status": "skipped",
            "details_he": "אין תמונת-מצב יומית (DailySnapshot) קודמת לתאריך זה — ריצה ראשונה, אין בסיס להשוואה.",
        }

    # אותה בדיוק אוכלוסייה כמו dashboard_service._get_of_cash_summary, שממנה
    # נכתב DailySnapshot.cash_balance ע"י cron/daily-close: רק חשבונות Open
    # Finance מסוג CHECKING (AccountType.BANK) — לא חסכונות/הלוואות/כרטיסי-
    # אשראי. השוואת כל חשבונות ה-OF (כולל LIABILITY/ASSET) מול cash_balance
    # הייתה מייצרת פער-שווא קבוע בגובה הרכיבים הלא-שייכים.
    of_accounts = db.query(Account).filter(
        Account.organization_id == org_id, Account.source == "open_finance",
        Account.account_type == AccountType.BANK,
    ).all()
    if not of_accounts:
        return {
            "name": "of_balance_walk", "status": "skipped",
            "details_he": "אין חשבונות Open Finance מקושרים לארגון — אין מה להשוות.",
        }

    # התנועות שנספרות חייבות לכסות בדיוק את אותם חשבונות שמניבים את actual —
    # אחרת (למשל תנועת כרטיס-אשראי Open Finance, שגם היא source="open_finance"
    # אך על חשבון LIABILITY לא-CHECKING) התנועה הייתה מתווספת ל-expected בלי
    # מקבילה ב-actual, ומייצרת פער-שווא קבוע בכל יום עם פעילות כרטיס.
    checking_ids = [a.id for a in of_accounts]
    txns = db.query(BankTransaction).filter(
        BankTransaction.organization_id == org_id,
        BankTransaction.account_id.in_(checking_ids),
        BankTransaction.transaction_date > snapshot.snapshot_date,
        BankTransaction.transaction_date <= as_of,
    ).all()

    latest_txn_date = max((t.transaction_date for t in txns), default=snapshot.snapshot_date)

    missing_as_of = [a for a in of_accounts if a.balance_as_of is None]
    if missing_as_of:
        return {
            "name": "of_balance_walk", "status": "skipped",
            "details_he": (
                f"{len(missing_as_of)} חשבונות Open Finance ללא חותמת balance_as_of — "
                "לא ניתן לקבוע טריות היתרה, מדלגים על ההשוואה."
            ),
        }
    stale_accounts = [a for a in of_accounts if a.balance_as_of.date() < latest_txn_date]
    if stale_accounts:
        return {
            "name": "of_balance_walk", "status": "skipped",
            "details_he": (
                f"יתרת {len(stale_accounts)} חשבון/ות Open Finance ישנה מהתנועה האחרונה "
                f"הידועה ({latest_txn_date.isoformat()}) — פער-תזמון, לא פער אמיתי."
            ),
        }
    future_accounts = [a for a in of_accounts if a.balance_as_of.date() > as_of]
    if future_accounts:
        return {
            "name": "of_balance_walk", "status": "skipped",
            "details_he": (
                f"יתרת {len(future_accounts)} חשבון/ות Open Finance מאוחרת מתאריך "
                f"הבדיקה ({as_of.isoformat()}) — משקפת מצב עתידי, לא ניתן להשוואה נכונה."
            ),
        }

    txn_sum = sum(float(t.amount or 0) for t in txns)
    expected = float(snapshot.cash_balance) + txn_sum
    actual = sum(float(a.balance or 0) for a in of_accounts)
    diff = abs(expected - actual)
    tolerance = max(1.0, OF_BALANCE_WALK_TOLERANCE)
    status = "ok" if diff <= tolerance else "mismatch"
    details_he = (
        f"יתרה צפויה ₪{expected:.2f} (snapshot {snapshot.snapshot_date.isoformat()} = "
        f"₪{float(snapshot.cash_balance):.2f} + {len(txns)} תנועות = ₪{txn_sum:.2f}) מול "
        f"יתרה בפועל ₪{actual:.2f}"
        + ("" if status == "ok" else f" — פער ₪{diff:.2f} מעבר לסובלנות ₪{tolerance:.2f}.")
    )
    return {
        "name": "of_balance_walk", "status": status, "details_he": details_he,
        "expected": round(expected, 2), "actual": round(actual, 2), "diff": round(diff, 2),
        "tolerance": tolerance, "snapshot_date": snapshot.snapshot_date.isoformat(),
    }


def _direct_pl_totals(db, org_id: int, year: int, month: int) -> dict[str, float]:
    """חישוב-שני עצמאי לרווח/הפסד המצטבר של החודש: *בדיוק* אותה אוכלוסיית
    מסמכים ואותם שדות כמו daily_reports_service.cumulative_pl (Invoice.subtotal
    לא-draft/void/cancelled; Bill.subtotal לא-draft/void; Expense.amount לא-
    'error'; לפי תאריך מסמך) — אבל בנתיב-קוד נפרד: סכימה שטוחה במקום צבירה
    יומית-מצטברת. אם השניים לא מתאימים, יש חוסר-עקביות פנימית אמיתית (באג
    בלולאת היום-אחר-יום או בסינון), לא שוני-מדיניות.

    למה לא filing_verification._independent_sums: הפונקציה ההיא מחזירה מע"מ
    בלבד (output_vat/input_vat, שדה tax/vat_amount) על אוכלוסייה *מצומצמת
    יותר* מכוונת (רק expenses "filed" דרך expense_counts, דה-דופ מול bills
    לפי external_id, החרגת קבלות מהעסקאות) — סוג-כמות אחר (מע"מ, לא קרן) וגם
    אוכלוסייה שונה במתכוון (זו הבדיקה הרגולטורית של תיוק-מע"מ, לא רו"ה
    ניהולי). השוואת net/gross (subtotal/amount) מול VAT הייתה משווה תפוחים
    לתפוזים ומייצרת פערי-שווא שיטתיים בכל בוקר (למשל: כל הוצאה "pending"
    שטרם תויקה הייתה מפילה את הבדיקה) — בדיוק מה שהעיקרון honest-null אוסר:
    מתריעים על אי-עקביות אמיתית, לא על מצב ידוע ומתועד כבר (טיוטות ממתינות,
    ר' filing_verification._pending_drafts)."""
    from calendar import monthrange

    from ..models import Bill, BillStatus, Expense, Invoice, InvoiceStatus

    start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    skip_inv = {InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED}
    skip_bill = {BillStatus.DRAFT, BillStatus.VOID}

    def _doc_date(r):
        return getattr(r, "issue_date", None) or getattr(r, "due_date", None)

    revenue = 0.0
    for inv in db.query(Invoice).filter(Invoice.organization_id == org_id).all():
        if inv.status in skip_inv:
            continue
        d = _doc_date(inv)
        if d and start <= d <= end:
            revenue += float(inv.subtotal or 0)

    expense = 0.0
    for bill in db.query(Bill).filter(Bill.organization_id == org_id).all():
        if bill.status in skip_bill:
            continue
        d = _doc_date(bill)
        if d and start <= d <= end:
            expense += float(bill.subtotal or 0)

    for exp in db.query(Expense).filter(Expense.organization_id == org_id).all():
        if str(getattr(exp, "status", "") or "").lower() == "error":
            continue
        d = getattr(exp, "expense_date", None)
        if d and start <= d <= end:
            expense += float(exp.amount or 0)

    return {"revenue": round(revenue, 2), "expense": round(expense, 2)}


def _check_internal_double_computation(db, org_id: int, as_of: date) -> dict[str, Any]:
    """בדיקה 3: רו"ה מצטבר-יומי (cumulative_pl) מול חישוב-ישיר עצמאי
    (_direct_pl_totals) לאותו חודש — "רו"ה פנימי בשתי דרכי חישוב זהות"
    (docs/bookkeeper_kb/00-role-and-daily-order.md, צעד 1)."""
    from . import daily_reports_service

    year, month = as_of.year, as_of.month
    cp = daily_reports_service.cumulative_pl(db, org_id, year, month)
    direct = _direct_pl_totals(db, org_id, year, month)

    cp_revenue = float(cp["totals"]["revenue"])
    cp_expense = float(cp["totals"]["expense"])
    diff_rev = abs(cp_revenue - direct["revenue"])
    diff_exp = abs(cp_expense - direct["expense"])
    tolerance = INTERNAL_DOUBLE_COMPUTATION_TOLERANCE
    ok = diff_rev <= tolerance and diff_exp <= tolerance

    # honest-null: ארבעה אפסים אינם הוכחת עקביות אלא היעדר נתון. בלי השער
    # הזה הבדיקה מחזירה "ok" על ארגון ריק — ומדווחת הצלחה על כך שלא בדקה
    # דבר. זה קרה בפועל: org1/org2 מסתנכרנים כל יום (ולכן הטריות ירוקה)
    # אך אין להם פקודות יומן, ולכן הריצה של 03:45 הכריזה "ok" בזמן ששתי
    # הצלעות האחרות "skipped". אותה תבנית fail-open כמו spent_today=None.
    no_data = (
        cp_revenue == 0.0 and cp_expense == 0.0
        and direct["revenue"] == 0.0 and direct["expense"] == 0.0
    )
    if no_data:
        status = "unknown"
    else:
        status = "ok" if ok else "mismatch"

    if no_data:
        details_he = (
            "אין נתונים להשוואה בחודש זה — שתי דרכי החישוב החזירו אפס בהכנסות "
            "ובהוצאות. זו אינה התאמה אלא היעדר בסיס לבדיקה."
        )
    elif ok:
        details_he = "שתי דרכי החישוב (מצטבר-יומי מול ישיר) תואמות על הכנסות והוצאות החודש."
    else:
        parts = []
        if diff_rev > tolerance:
            parts.append(
                f"הכנסות: מצטבר-יומי ₪{cp_revenue:.2f} מול חישוב-ישיר ₪{direct['revenue']:.2f} "
                f"(פער ₪{diff_rev:.2f})"
            )
        if diff_exp > tolerance:
            parts.append(
                f"הוצאות: מצטבר-יומי ₪{cp_expense:.2f} מול חישוב-ישיר ₪{direct['expense']:.2f} "
                f"(פער ₪{diff_exp:.2f})"
            )
        details_he = "אי-עקביות פנימית בין שתי דרכי החישוב: " + "; ".join(parts)

    return {
        "name": "internal_double_computation", "status": status, "details_he": details_he,
        "cumulative_pl_revenue": round(cp_revenue, 2), "cumulative_pl_expense": round(cp_expense, 2),
        "direct_revenue": direct["revenue"], "direct_expense": direct["expense"],
        "diff_revenue": round(diff_rev, 2), "diff_expense": round(diff_exp, 2),
        "tolerance": tolerance,
    }


def _check_sumit_crosscheck(db, org_id: int, as_of: date) -> dict[str, Any]:
    """בדיקה 4: אם קיימת רשומת FilingCrosscheck (הקלדה ידנית של ערכי המע"מ
    מספרי SUMIT) לתקופה הנוכחית — משווים מולה, באותה נוסחה בדיוק כמו הבדיקה
    השלישית ב-filing_verification.verify_filing (פער ≤ ₪1 = התאמה). אם אין
    רשומה — "skipped", לא כשל (אין הצלבה מוקלטת עדיין, לא שגיאה)."""
    from . import daily_reports_service, financial_synthesis
    from .filing_verification import _find_crosscheck

    year, month = as_of.year, as_of.month
    basis = "document"
    period = financial_synthesis.period_label(year, month, 1)
    crosscheck = _find_crosscheck(db, org_id, period, basis)
    if crosscheck is None:
        return {
            "name": "sumit_crosscheck", "status": "skipped",
            "details_he": "אין הצלבה מוקלטת לתקופה (FilingCrosscheck) — הנחיה ידנית בלבד.",
            "period": period,
        }

    report = daily_reports_service.vat_report_period(db, org_id, year, month, months=1, basis=basis)
    diff_in = abs(float(crosscheck.books_input_vat) - float(report["input_vat"]))
    diff_out = None
    if crosscheck.books_output_vat is not None:
        diff_out = abs(float(crosscheck.books_output_vat) - float(report["output_vat"]))
    max_diff = diff_in if diff_out is None else max(diff_in, diff_out)
    tolerance = SUMIT_CROSSCHECK_TOLERANCE
    status = "ok" if max_diff <= tolerance else "mismatch"

    if status == "ok":
        details_he = f"הוצלב מול ספרי SUMIT לתקופה {period} — התאמה (פער ≤ ₪{tolerance:.2f})."
    else:
        gap_parts = [f"תשומות ₪{diff_in:.2f}"]
        if diff_out is not None:
            gap_parts.append(f"עסקאות ₪{diff_out:.2f}")
        details_he = f"⚠️ פער מול ספרי SUMIT לתקופה {period}: " + "; ".join(gap_parts)

    return {
        "name": "sumit_crosscheck", "status": status, "details_he": details_he,
        "diff_input_vat": round(diff_in, 2),
        "diff_output_vat": round(diff_out, 2) if diff_out is not None else None,
        "period": period,
    }


def run_daily_parity(db, organization_id: int, as_of: date) -> dict[str, Any]:
    """מריץ את ארבע בדיקות ההתאמה המשולשת היומית-הקלה ומחזיר תוצאה מפורטת +
    סטטוס כולל. status: "mismatch" גובר על "stale" (אם בדיקה סמכותית נכשלה,
    זה חמור יותר מסתם נתונים ישנים); "stale" רק כשהטריות נכשלה ושום בדיקה
    סמכותית לא נכשלה בפועל; "ok" אחרת."""
    freshness_check, authoritative = _check_freshness(db, organization_id)
    checks: list[dict[str, Any]] = [freshness_check]

    # נגזר מ-PARITY_CHECKS ולא מ-tuple מקודד-קשיח: כך בדיקה חמישית שתתווסף
    # לרישום תרוץ בפועל, ובדיקה שתרוץ בלי להיות ברישום תיתפס בטסט.
    # `freshness` כבר רץ למעלה (הוא מכתיב authoritative לשאר).
    for spec in PARITY_CHECKS:
        if spec["key"] == "freshness":
            continue
        c = globals()[f"_check_{spec['key']}"](db, organization_id, as_of)
        c["authoritative"] = authoritative
        c["title_he"] = spec["title_he"]
        c["compares"] = spec["compares"]
        checks.append(c)

    mismatched = any(c["status"] == "mismatch" and c.get("authoritative", True) for c in checks)

    # honest-null בהכרעה הכוללת: "ok" מחייב שלפחות בדיקה מהותית אחת
    # **באמת השוותה** משהו. הטריות אינה כזו — היא מוכיחה שסנכרון רץ, לא
    # שהמספרים תואמים.
    #
    # בלי השער הזה התקבל בפועל:
    #   freshness=ok · of_balance_walk=skipped ·
    #   internal_double_computation=ok(0 מול 0) · sumit_crosscheck=skipped
    #   → status="ok"
    # שתי צלעות דילגו, השלישית השוותה אפס לאפס, וההכרעה ירוקה. דוח כזה
    # גרוע מהיעדר דוח: הוא סוגר התראות (check_and_alert עושה resolve על
    # "ok") על בסיס שתיקה, ומאמן את הקורא להתעלם.
    substantive = [c for c in checks if c["name"] != "freshness"]
    proved_something = any(
        c["status"] == "ok" and c.get("authoritative", True) for c in substantive
    )

    if mismatched:
        status = "mismatch"
    elif freshness_check["status"] == "stale":
        status = "stale"
    elif not proved_something:
        status = "unknown"
    else:
        status = "ok"

    return {
        "status": status, "checks": checks,
        "organization_id": organization_id, "as_of": as_of.isoformat(),
    }


def check_and_alert(db, organization_id: int, as_of: date) -> dict[str, Any]:
    """מריץ run_daily_parity ו-upsert-ת CfoInsight (fingerprint פר-בדיקה+חודש)
    לכל בדיקה שנכשלה (mismatch); ומאפסת (resolve) התראות parity פעילות
    לבדיקה שחזרה ל-ok. אותה תבנית מצומצמת בדיוק כמו credit_line_service.
    check_and_alert — upsert לפי fingerprint, החייאה אם הייתה resolved,
    resolve כשהמצב חזר ל-ok. בדיקות "stale"/"skipped" לא נוגעות בהתראות
    (לא מספיק ודאיות כדי להתריע *או* לסגור — honest-null: לא מנחשים).

    שער authoritative (קריטי): כשהטריות נכשלה, run_daily_parity מסמן את כל
    הבדיקות הבאות authoritative=False — ואינו סופר mismatch כזה לסטטוס
    הכולל. אם check_and_alert היה פועל על c["status"] בלבד (בלי לבדוק
    authoritative), שני כיוונים שגויים: (1) mismatch לא-סמכותי היה יוצר
    התראה "high" בזמן שה-run עצמו מדווח status="stale" — סתירה; (2) "ok"
    לא-סמכותי (מספרים שאולי לא נכונים כי הנתונים ישנים) היה *סוגר* התראה
    אמיתית וקיימת על בסיס נתונים לא-אמינים — בדיוק מה ש-honest-null אוסר.
    לכן: authoritative=False -> no-op גמור (לא מתריעים, לא סוגרים), מקביל
    ל"unknown -> no-op" ב-credit_line_service.check_and_alert."""
    from ..models import CfoInsight

    result = run_daily_parity(db, organization_id, as_of)
    period_key = as_of.strftime("%Y-%m")
    now = datetime.utcnow()
    alerted: list[dict[str, Any]] = []
    resolved_ids: list[int] = []

    for c in result["checks"]:
        if not c.get("authoritative", True):
            continue  # נתונים לא-טריים — לא מתריעים ולא סוגרים על בסיסם

        name = c["name"]
        fingerprint = f"parity:{name}:{period_key}"

        if c["status"] == "mismatch":
            title = f"אי-התאמת התאמה משולשת יומית — {name} ({period_key})"
            message = c.get("details_he", "")
            evidence = {k: v for k, v in c.items() if k not in ("name", "status", "details_he")}

            existing = db.query(CfoInsight).filter(
                CfoInsight.organization_id == organization_id,
                CfoInsight.fingerprint == fingerprint,
            ).first()
            if existing:
                existing.insight_type = INSIGHT_TYPE
                existing.severity = "high"
                existing.title = title
                existing.message = message
                existing.evidence = evidence
                if existing.status == "resolved":
                    existing.status = "active"
                    existing.resolved_at = None
                existing.updated_at = now
                insight_id = existing.id
            else:
                insight = CfoInsight(
                    organization_id=organization_id,
                    fingerprint=fingerprint,
                    insight_type=INSIGHT_TYPE,
                    severity="high",
                    title=title,
                    message=message,
                    evidence=evidence,
                    status="active",
                )
                db.add(insight)
                db.flush()
                insight_id = insight.id
            alerted.append({"check": name, "insight_id": insight_id, "fingerprint": fingerprint})

        elif c["status"] == "ok":
            active = db.query(CfoInsight).filter(
                CfoInsight.organization_id == organization_id,
                CfoInsight.insight_type == INSIGHT_TYPE,
                CfoInsight.fingerprint == fingerprint,
                CfoInsight.status == "active",
            ).all()
            for ins in active:
                ins.status = "resolved"
                ins.resolved_at = now
                ins.updated_at = now
                resolved_ids.append(ins.id)

    if alerted or resolved_ids:
        db.commit()

    return {**result, "alerted": alerted, "resolved_insight_ids": resolved_ids}
