from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from cfo.database import SessionLocal
from cfo.models import CollectionReminder, Contact, ContactType, Invoice, InvoiceStatus, Organization


def test_collection_reminder_roundtrip(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(CollectionReminder(
            organization_id=org_id, contact_id=None, invoice_numbers="INV-1",
            reminder_type="first", channel="sms", amount=Decimal("100"),
            days_overdue=5, status="sent", sent_at=datetime.now(timezone.utc),
        ))
        db.commit()
        row = db.query(CollectionReminder).filter_by(organization_id=org_id).one()
        assert row.reminder_type == "first" and row.channel == "sms"
    finally:
        db.close()


def test_org_collection_defaults(fresh_org):
    from cfo.models import Organization
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.query(Organization).get(org_id)
        assert org.collection_reminders_enabled is False
        assert org.collection_sms_sender is None
    finally:
        db.close()


def _overdue_invoice(db, org_id, days_overdue, total="1000"):
    c = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER,
                email="c@example.com", phone="0501234567")
    db.add(c); db.flush()
    today = date.today()
    db.add(Invoice(organization_id=org_id, contact_id=c.id, invoice_number="INV-9",
                   total=Decimal(total), balance=Decimal(total), status=InvoiceStatus.SENT,
                   issue_date=today - timedelta(days=days_overdue + 30),
                   due_date=today - timedelta(days=days_overdue)))
    db.commit()
    return c.id


def test_plan_reminders_assigns_type_by_days_overdue(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=20)  # → "second"
        from cfo.services.collection_service import CollectionService
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        assert len(planned) == 1
        assert planned[0].reminder_type == "second"
        assert planned[0].total_amount == 1000.0
        assert planned[0].phone == "0501234567"
    finally:
        db.close()


def test_plan_reminders_respects_cooldown(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cid = _overdue_invoice(db, org_id, days_overdue=5)  # "first"
        db.add(CollectionReminder(
            organization_id=org_id, contact_id=cid, reminder_type="first",
            channel="sms", status="sent", sent_at=datetime.now(timezone.utc)))
        db.commit()
        from cfo.services.collection_service import CollectionService
        assert CollectionService(db, org_id).plan_reminders(date.today()) == []
    finally:
        db.close()
