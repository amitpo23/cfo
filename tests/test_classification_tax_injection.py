"""משימה 5 (4.4): הזרקת israeli_tax_rules ללולאת הסיווג.

הבעיה: classify_uncategorized/classify_pending/resolve_supplier_names היו
משנים category בלי לחשב מחדש vat_claimable — תוצאה סווגה מחדש אבל נשארה
עם ניכוי-מע"מ ישן/שגוי מהקטגוריה הקודמת. sync_pending_from_sumit יצר הוצאה
חדשה בלי לגעת ב-israeli_tax_rules בכלל. הטסטים כאן מוכיחים שכל נקודות
הסיווג עוברות עכשיו דרך israeli_tax_rules.claimable_vat (ולא מנחשות),
כולל המנגנונים המיוחדים (רכב פר-פרופיל, אירוח, טלפון/תקשורת) ומקרה עמום
שנשאר honest-null (תור הכרעה).
"""
from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "taxinject@example.com", "password": "secret123", "full_name": "Tax Inject",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


def _create(client, acc, **overrides):
    payload = {
        "supplier_name": "ספק כלשהו",
        "amount": 100,
        "vat_amount": 18,
        "expense_date": date.today().isoformat(),
        "category": "office",
        "doc_kind": "tax_invoice",
    }
    payload.update(overrides)
    r = client.post("/api/expenses", json=payload, headers=acc["headers"])
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_classify_uncategorized_recomputes_vat_claimable_on_category_change(client, acc):
    """הוצאה שסווגה office (100% תשומות) -> מזוהה מחדש כ-hospitality (0%
    תמיד, תקנה 2(1)/15א) -> vat_claimable חייב להתעדכן ל-0, לא להישאר
    תקוע על 18 (הערך הישן מהקטגוריה הקודמת)."""
    from cfo.database import SessionLocal
    from cfo.models import Expense
    from cfo.services.expense_filing_service import ExpenseFilingService

    created = _create(client, acc, supplier_name="מסעדה של השף", category="office")
    assert created["vat_claimable"] == 18.0  # office = 100% תשומות, לפני הסיווג-מחדש

    db = SessionLocal()
    try:
        result = ExpenseFilingService(db, acc["org_id"]).classify_uncategorized(reclassify_all=True)
        assert result["classified"] >= 1

        row = db.query(Expense).filter(Expense.id == created["id"]).one()
        assert row.category == "hospitality"  # "מסעדה" הוא מילת-מפתח hospitality
        assert row.vat_claimable == Decimal("0.00")
    finally:
        db.close()


def test_classify_pending_vehicle_uses_per_profile_vat_fraction(client, acc):
    """רכב — פר-רכב (VehicleProfile), לא פר-עסק. עם פרופיל primarily_business=True
    ודוק-קיינד tax_invoice: 2/3 מהמע"מ נתבע (תקנה 18)."""
    from cfo.database import SessionLocal
    from cfo.models import Expense, VehicleProfile
    from cfo.services.expense_filing_service import ExpenseFilingService

    db = SessionLocal()
    try:
        db.add(VehicleProfile(
            organization_id=acc["org_id"], label="רכב יחיד לארגון",
            vehicle_kind="private", primarily_business=True,
        ))
        db.commit()
    finally:
        db.close()

    created = _create(
        client, acc, supplier_name="פז תדלוק", category="other",
        vat_amount=30, amount=100,
    )

    db = SessionLocal()
    try:
        # status="pending" כברירת מחדל ביצירה — classify_pending יתפוס אותה
        # כי category="other".
        result = ExpenseFilingService(db, acc["org_id"]).classify_pending()
        assert result["classified"] >= 1

        row = db.query(Expense).filter(Expense.id == created["id"]).one()
        assert row.category == "vehicle"
        assert row.vat_claimable == Decimal("20.00")  # 30 * 2/3
    finally:
        db.close()


def test_resolve_supplier_names_recomputes_vat_claimable_for_utilities_phone(client, acc, monkeypatch):
    """טלפון/תקשורת -> מסווג utilities (אין כרטיס ייעודי לטלפון בתרשים
    ברמת-קטגוריה) -> input_vat_fraction=FULL -> vat_claimable = כל המע"מ,
    כשsupplier מתגלה כ"בזק" (מילת-מפתח utilities) דרך resolve_supplier_names."""
    import asyncio

    from cfo.database import SessionLocal
    from cfo.models import Expense
    from cfo.services.expense_filing_service import ExpenseFilingService
    import cfo.services.sync_engine as sync_engine

    created = _create(
        client, acc, supplier_name="12345", category="other",
        vat_amount=18, amount=100, doc_kind="tax_invoice",
        invoice_number="EXP-PHONE-1",
    )
    # מדמים הוצאת SUMIT: שם ספק מספרי (ID) שטרם נפתר, כדי ש-resolve_supplier_names יתפוס אותה
    db = SessionLocal()
    try:
        row = db.query(Expense).filter(Expense.id == created["id"]).one()
        row.source = "sumit"
        row.external_id = "SUMIT-PHONE-1"
        db.commit()
    finally:
        db.close()

    class FakeConnector:
        async def get_document_supplier_details(self, external_id):
            return {"name": "בזק בינלאומי - טלפון", "tax_id": "512345678", "item_name": "טלפון"}

    monkeypatch.setattr(
        sync_engine, "get_connector_for_org",
        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"),
    )

    db = SessionLocal()
    try:
        result = asyncio.run(ExpenseFilingService(db, acc["org_id"]).resolve_supplier_names())
        assert result["reclassified"] >= 1

        row = db.query(Expense).filter(Expense.id == created["id"]).one()
        assert row.category == "utilities"
        assert row.vat_claimable == Decimal("18.00")  # FULL — 100% תשומות
    finally:
        db.close()


def test_sync_pending_from_sumit_calls_tax_engine_stays_honest_null_without_doc_kind(client, acc, monkeypatch):
    """sync_pending_from_sumit לא מקבל doc_kind מ-SUMIT (אין אות כזה במסמך
    הרשימה) -> israeli_tax_rules.claimable_vat עדיין נקרא (המנוע הוא
    המקור היחיד לקביעה), אבל התוצאה חייבת להישאר honest-null (תור הכרעה)
    ולא לנחש 100%/0% סתם כי היה נוח."""
    import asyncio
    from decimal import Decimal as D

    from cfo.database import SessionLocal
    from cfo.integrations.sumit_models import DocumentResponse
    from cfo.models import Expense
    from cfo.services.expense_filing_service import ExpenseFilingService
    import cfo.services.sync_engine as sync_engine

    class FakeConnector:
        async def list_documents(self, request):
            return [
                DocumentResponse(
                    document_id="SUMIT-SYNC-VATCHECK-1",
                    document_number="EXP-SYNC-VATCHECK-1",
                    document_type="15",
                    customer_id="99777",
                    customer_name="ספק סנכרון",
                    total_amount=D("118.00"),
                    vat_amount=D("18.00"),
                    status="draft",
                    issue_date=date(2026, 7, 25),
                )
            ]

    monkeypatch.setattr(
        sync_engine, "get_connector_for_org",
        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"),
    )

    db = SessionLocal()
    try:
        result = asyncio.run(ExpenseFilingService(db, acc["org_id"]).sync_pending_from_sumit())
        assert result["imported"] == 1

        row = db.query(Expense).filter(
            Expense.organization_id == acc["org_id"],
            Expense.external_id == "SUMIT-SYNC-VATCHECK-1",
        ).one()
        assert row.doc_kind is None
        assert row.vat_claimable is None  # תור הכרעה — לא ניחוש
    finally:
        db.close()


def test_ambiguous_category_stays_in_decision_queue_after_classification(client, acc):
    """כיבוד (refreshments) — israeli_tax_rules מסמן input_vat_fraction=None
    במפורש (עמדה שמרנית עד הכרעה, KB02): גם אחרי שהסיווג רץ ומצא את
    הקטגוריה בוודאות (מילת-מפתח "כיבוד"), vat_claimable נשאר None —
    honest-null, לא ניחוש — כלומר ההוצאה נשארת בתור-הכרעה."""
    from cfo.database import SessionLocal
    from cfo.models import Expense
    from cfo.services.expense_filing_service import ExpenseFilingService

    created = _create(
        client, acc, supplier_name='כיבוד למשרד בע"מ', category="other",
        vat_amount=18, amount=100, doc_kind="tax_invoice",
    )

    db = SessionLocal()
    try:
        ExpenseFilingService(db, acc["org_id"]).classify_pending()
        row = db.query(Expense).filter(Expense.id == created["id"]).one()
        assert row.category == "refreshments"
        assert row.vat_claimable is None  # תור הכרעה
    finally:
        db.close()
