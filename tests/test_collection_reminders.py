from datetime import datetime, timezone
from decimal import Decimal
from cfo.database import SessionLocal
from cfo.models import CollectionReminder, Organization


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
