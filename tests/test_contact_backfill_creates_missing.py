"""שלמות נתונים: חשבונית לא נשארת יתומה כשהיא עצמה נושאת את זהות הלקוח.

הרקע (אודיט פרוד 05/08/2026): ל-org 5 יש 8 חשבוניות מתוך 23 בלי `contact_id`.
כולן נושאות ב-`raw_data` גם `customer_id` וגם `customer_name` — כלומר כל מה
שנדרש כדי לזהות את הלקוח. הן נשארו יתומות כי `backfill_invoice_contacts` רק
**מקשר** לאיש קשר קיים; אם ה-Contact מעולם לא נוצר, הלולאה מדלגת והדוח מחזיר
`invoices_fixed: 0` — לנצח.

חשבונית בלי לקוח שוברת גיול חייבים, גבייה וכל דוח AR.
"""
import pytest

from cfo.models import Contact, Invoice, Organization


ORG_ID = 301


@pytest.fixture
def db(client):
    from cfo.database import SessionLocal

    session = SessionLocal()

    def purge():
        session.query(Invoice).filter(
            Invoice.organization_id == ORG_ID).delete(synchronize_session=False)
        session.query(Contact).filter(
            Contact.organization_id == ORG_ID).delete(synchronize_session=False)
        session.query(Organization).filter(
            Organization.id == ORG_ID).delete(synchronize_session=False)
        session.commit()

    purge()
    session.add(Organization(id=ORG_ID, name="תיק יתום", is_active=True))
    session.commit()
    yield session
    purge()
    session.close()


def _engine(session):
    """התיקון הוא מקומי לחלוטין ואינו נוגע בספק — connector=None מספיק."""
    from cfo.services.sync_engine import SyncEngine

    return SyncEngine(session, None, organization_id=ORG_ID, source="sumit")


def _orphan(session, *, number, customer_id, customer_name, total=1000):
    from datetime import date

    session.add(Invoice(
        organization_id=ORG_ID, source="sumit", external_id=f"EXT-{number}",
        invoice_number=number, total=total, issue_date=date.today(),
        contact_id=None,
        raw_data={"customer_id": customer_id, "customer_name": customer_name},
    ))
    session.commit()


def test_backfill_creates_the_missing_contact_from_the_invoice_payload(db):
    """הכשל של org 5: הלקוח קיים בחשבונית אבל לא בטבלת אנשי הקשר."""
    _orphan(db, number="10000", customer_id="2004988528",
            customer_name='דודק חקלאות בע"מ')

    result = _engine(db).backfill_invoice_contacts()

    assert result["invoices_fixed"] == 1
    assert result["contacts_created"] == 1

    inv = db.query(Invoice).filter(Invoice.invoice_number == "10000").first()
    assert inv.contact_id is not None
    contact = db.query(Contact).filter(Contact.id == inv.contact_id).first()
    assert contact.name == 'דודק חקלאות בע"מ'
    assert contact.external_id == "2004988528"
    assert contact.source == "sumit"
    assert contact.organization_id == ORG_ID


def test_an_existing_contact_is_linked_not_duplicated(db):
    """ההתנהגות הקיימת נשמרת: אם איש הקשר קיים, מקשרים אליו."""
    db.add(Contact(organization_id=ORG_ID, source="sumit",
                   external_id="2005019629", name='אלון תבור שיווק בע"מ',
                   contact_type="CUSTOMER"))
    db.commit()

    _orphan(db, number="20001", customer_id="2005019629",
            customer_name="שם אחר מה-OCR")

    result = _engine(db).backfill_invoice_contacts()

    assert result["invoices_fixed"] == 1
    assert result["contacts_created"] == 0
    assert db.query(Contact).filter(
        Contact.organization_id == ORG_ID).count() == 1


def test_several_invoices_of_one_customer_share_a_single_contact(db):
    """בפרוד ל-'אבו דיבה אדהם' יש 4 חשבוניות יתומות — צריך איש קשר אחד."""
    for n in ("10005", "10006", "10008", "10009"):
        _orphan(db, number=n, customer_id="2042114617",
                customer_name="אבו דיבה אדהם")

    result = _engine(db).backfill_invoice_contacts()

    assert result["invoices_fixed"] == 4
    assert result["contacts_created"] == 1
    assert db.query(Contact).filter(
        Contact.organization_id == ORG_ID).count() == 1


def test_an_invoice_without_identity_is_left_alone(db):
    """honest-null: בלי מזהה או שם לא ממציאים לקוח."""
    from datetime import date

    db.add(Invoice(
        organization_id=ORG_ID, source="sumit", external_id="EXT-NOID",
        invoice_number="99999", total=500, issue_date=date.today(),
        contact_id=None, raw_data={},
    ))
    db.commit()

    result = _engine(db).backfill_invoice_contacts()

    assert result["invoices_fixed"] == 0
    assert result["contacts_created"] == 0
    inv = db.query(Invoice).filter(Invoice.invoice_number == "99999").first()
    assert inv.contact_id is None


def test_a_customer_id_without_a_name_is_not_invented(db):
    """מזהה בלי שם אינו מספיק כדי ליצור איש קשר."""
    _orphan(db, number="88888", customer_id="2050590137", customer_name=None)

    result = _engine(db).backfill_invoice_contacts()

    assert result["contacts_created"] == 0
    assert result["invoices_fixed"] == 0


def test_repair_is_idempotent(db):
    _orphan(db, number="10007", customer_id="2050590137",
            customer_name="משק בן שאול")

    first = _engine(db).backfill_invoice_contacts()
    second = _engine(db).backfill_invoice_contacts()

    assert first["invoices_fixed"] == 1
    assert second["invoices_fixed"] == 0
    assert second["contacts_created"] == 0
    assert db.query(Contact).filter(
        Contact.organization_id == ORG_ID).count() == 1
