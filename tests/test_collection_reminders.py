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
        org = db.get(Organization, org_id)
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


def test_plan_reminders_overdue_daily_message_with_days_count(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=20)
        from cfo.services.collection_service import CollectionService
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        assert len(planned) == 1
        assert planned[0].reminder_type == "overdue"
        assert planned[0].total_amount == 1000.0
        assert planned[0].phone == "0501234567"
        assert "20 ימים" in planned[0].message
        assert "בהתאם להסכם ותנאי התשלום" in planned[0].message
    finally:
        db.close()


def test_plan_reminders_overdue_one_day_singular(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=1)
        from cfo.services.collection_service import CollectionService
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        assert len(planned) == 1
        assert planned[0].reminder_type == "overdue"
        assert "ביום אחד" in planned[0].message
    finally:
        db.close()


def test_plan_reminders_pre_due_day_before(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=-1)  # due tomorrow
        from cfo.services.collection_service import CollectionService
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        assert len(planned) == 1
        assert planned[0].reminder_type == "pre_due"
        assert "מחר" in planned[0].message
    finally:
        db.close()


def test_plan_reminders_daily_cadence_cooldown(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cid = _overdue_invoice(db, org_id, days_overdue=5)
        # sent one hour ago → today's run must skip
        db.add(CollectionReminder(
            organization_id=org_id, contact_id=cid, reminder_type="overdue",
            channel="sms", status="sent",
            sent_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
        from cfo.services.collection_service import CollectionService
        assert CollectionService(db, org_id).plan_reminders(date.today()) == []
        # sent 25 hours ago → today's run must plan again (daily escalation)
        db.query(CollectionReminder).filter_by(organization_id=org_id).update(
            {"sent_at": datetime.now(timezone.utc) - timedelta(hours=25)})
        db.commit()
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        assert len(planned) == 1 and planned[0].reminder_type == "overdue"
    finally:
        db.close()


def test_plan_reminders_stops_on_bank_detected_payment(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import BankTransaction
        _overdue_invoice(db, org_id, days_overdue=5)
        inv = db.query(Invoice).filter_by(organization_id=org_id).one()
        db.add(BankTransaction(
            organization_id=org_id, external_id="tx-paid-1", source="open_finance",
            transaction_date=date.today(), description="העברה מהלקוח",
            amount=Decimal("1000"), currency="ILS",
            matched_entity_type="invoice", matched_entity_id=inv.id))
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


def test_cron_collection_requires_secret(client):
    r = client.get("/api/cron/collection-reminders")
    assert r.status_code in (401, 403)


def test_cron_collection_runs_for_enabled_orgs(client, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)
    r = client.get("/api/cron/collection-reminders",
                   headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200
    assert "summary" in r.json()


def test_collection_due_preview(client, owner):
    r = client.get("/api/financial/collection/due", headers=owner["headers"])
    assert r.status_code == 200
    assert "due" in r.json()


def test_collection_run_blocked_when_org_disabled(client, owner):
    # owner is admin of the default org, which has collection_reminders_enabled=False by default
    r = client.post("/api/financial/collection/run", headers=owner["headers"])
    assert r.status_code == 403
