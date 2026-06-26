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


from cfo.services.email_sender import send_email_smtp


def test_email_sender_disabled_when_unconfigured():
    import asyncio
    class S:  # minimal settings stub, no SMTP host
        smtp_host = None
        smtp_port = 587
        smtp_user = None
        smtp_password = None
        smtp_from = None
    assert asyncio.run(send_email_smtp("a@b.com", "s", "body", S())) is False


import asyncio
from cfo.services.collection_service import CollectionService, dispatch_reminders


def test_dispatch_sends_sms_and_records(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=5)
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        sent = []
        async def fake_sms(phone, message): sent.append((phone, message)); return True
        async def fake_email(to, subject, body): return True
        summary = asyncio.run(dispatch_reminders(
            db, org_id, planned, sms_sender=fake_sms, email_sender=fake_email))
        from cfo.models import CollectionReminder
        rows = db.query(CollectionReminder).filter_by(organization_id=org_id).all()
        assert summary["sms_sent"] == 1
        assert sent and sent[0][0] == "0501234567"
        assert any(r.channel == "sms" and r.status == "sent" for r in rows)
    finally:
        db.close()


def test_dispatch_records_failure_without_crashing(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=5)
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        async def boom_sms(phone, message): raise RuntimeError("sumit 403")
        async def fake_email(to, subject, body): return True
        summary = asyncio.run(dispatch_reminders(db, org_id, planned, boom_sms, fake_email))
        assert summary["failed"] >= 1
    finally:
        db.close()
