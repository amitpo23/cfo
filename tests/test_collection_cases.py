"""Wave 2 item 7.3: manual collection-case workflow (open -> promised/paid/escalated).

Separate from the automated SMS/email reminders in collection_service.py — this
tracks a human collector's attempts (calls, emails) and outcomes per contact.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services import collection_case_service as svc


def _overdue_invoice(db, org_id, days_overdue, total="1000", contact=None):
    if contact is None:
        contact = Contact(organization_id=org_id, name="לקוח חייב", contact_type=ContactType.CUSTOMER,
                          email="c@example.com", phone="0501234567")
        db.add(contact)
        db.flush()
    today = date.today()
    inv = Invoice(organization_id=org_id, contact_id=contact.id, invoice_number=f"INV-{days_overdue}",
                 total=Decimal(total), balance=Decimal(total), status=InvoiceStatus.SENT,
                 issue_date=today - timedelta(days=days_overdue + 30),
                 due_date=today - timedelta(days=days_overdue))
    db.add(inv)
    db.commit()
    return contact, inv


def test_open_cases_for_overdue_creates_one_case_per_contact(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        opened = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)
        assert len(opened) == 1
        assert opened[0].status == "open"
        assert opened[0].attempts == []
    finally:
        db.close()


def test_open_cases_is_idempotent(fresh_org):
    """Calling it twice (e.g. daily job) must not open a second case for the
    same contact while one is still open/promised."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)
        second_run = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)
        assert second_run == []
        all_cases = svc.list_cases(db, org_id)
        assert len(all_cases) == 1
    finally:
        db.close()


def test_open_cases_ignores_invoices_under_threshold(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=5)  # under 30-day threshold
        opened = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)
        assert opened == []
    finally:
        db.close()


def test_log_attempt_promised_advances_status_and_sets_promise_date(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        promise = date.today() + timedelta(days=7)

        updated = svc.log_attempt(db, org_id, case.id, channel="phone", outcome="promised",
                                  notes="הבטיח לשלם בשבוע הבא", promise_date=promise)

        assert updated.status == "promised"
        assert updated.promise_date == promise
        assert len(updated.attempts) == 1
        assert updated.attempts[0]["channel"] == "phone"
        assert updated.attempts[0]["outcome"] == "promised"
    finally:
        db.close()


def test_log_attempt_no_answer_leaves_status_unchanged(fresh_org):
    """An ambiguous outcome (no_answer) must not silently advance the case —
    only a real signal (promised/paid/escalate) changes status."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]

        updated = svc.log_attempt(db, org_id, case.id, channel="phone", outcome="no_answer")

        assert updated.status == "open"
        assert len(updated.attempts) == 1
    finally:
        db.close()


def test_log_attempt_paid_closes_case(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        updated = svc.log_attempt(db, org_id, case.id, channel="email", outcome="paid")
        assert updated.status == "paid"
    finally:
        db.close()


def test_log_attempt_unknown_case_raises(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            svc.log_attempt(db, org_id, 999999, channel="phone", outcome="promised")
    finally:
        db.close()


def test_set_status_direct_override(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        updated = svc.set_status(db, org_id, case.id, "escalated")
        assert updated.status == "escalated"
    finally:
        db.close()


def test_set_status_rejects_invalid_value(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        with pytest.raises(ValueError):
            svc.set_status(db, org_id, case.id, "not_a_real_status")
    finally:
        db.close()


def test_list_cases_filters_by_status(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        svc.set_status(db, org_id, case.id, "escalated")
        assert len(svc.list_cases(db, org_id, status="escalated")) == 1
        assert len(svc.list_cases(db, org_id, status="open")) == 0
    finally:
        db.close()


def test_case_isolated_across_orgs(fresh_org):
    """A collection case in org A must be invisible/untouchable from org B."""
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_a, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_a, date.today(), days_threshold=30)[0]

        assert svc.list_cases(db, org_b) == []
        with pytest.raises(ValueError):
            svc.log_attempt(db, org_b, case.id, channel="phone", outcome="promised")
        with pytest.raises(ValueError):
            svc.set_status(db, org_b, case.id, "paid")
    finally:
        db.close()


def test_routes_require_auth(client):
    assert client.get("/api/collections/cases").status_code == 403
    assert client.post("/api/collections/cases/1/attempt", json={}).status_code == 403
    assert client.post("/api/collections/cases/1/status", json={}).status_code == 403


def test_alert_engine_flags_broken_promise(fresh_org):
    """Wave 2 item 7.3's alert_engine connection: a promised case whose
    promise_date has passed without being marked paid must be flagged."""
    from cfo.services.alert_engine import AlertEngine

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        svc.log_attempt(db, org_id, case.id, channel="phone", outcome="promised",
                        promise_date=date.today() - timedelta(days=1))  # already broken

        alerts = AlertEngine(db, org_id).evaluate_all()
        stale = [a for a in alerts if a.alert_type == "stale_collection_case"]
        assert len(stale) == 1
        assert stale[0].entity_id == case.id
    finally:
        db.close()


def test_alert_engine_does_not_flag_fresh_case(fresh_org):
    """A case opened just now (no attempts yet) must NOT be immediately
    flagged as stale — only after stale_days with no activity."""
    from cfo.services.alert_engine import AlertEngine

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)

        alerts = AlertEngine(db, org_id).evaluate_all()
        stale = [a for a in alerts if a.alert_type == "stale_collection_case"]
        assert stale == []
    finally:
        db.close()


def test_alert_engine_does_not_flag_paid_case(fresh_org):
    from cfo.services.alert_engine import AlertEngine

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
        case = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=30)[0]
        svc.log_attempt(db, org_id, case.id, channel="phone", outcome="paid")

        alerts = AlertEngine(db, org_id).evaluate_all()
        stale = [a for a in alerts if a.alert_type == "stale_collection_case"]
        assert stale == []
    finally:
        db.close()


def test_list_cases_route_enriches_with_contact_name(client, fresh_org):
    """The UI needs a human-readable contact name (and a way to reach them) —
    a bare contact_id is not usable in a collections worklist."""
    iso = fresh_org()
    org_id, headers = iso["org_id"], iso["headers"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45, total="2500")
    finally:
        db.close()

    client.post("/api/collections/open", headers=headers)
    r = client.get("/api/collections/cases", headers=headers)
    assert r.status_code == 200
    case = r.json()["cases"][0]
    assert case["contact_name"] == "לקוח חייב"
    assert case["contact_phone"] == "0501234567"
    assert case["total_balance"] == 2500.0


def test_route_lifecycle(client, fresh_org):
    iso = fresh_org()
    org_id, headers = iso["org_id"], iso["headers"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=45)
    finally:
        db.close()

    r = client.post("/api/collections/open", headers=headers)
    assert r.status_code == 200
    assert r.json()["opened"] == 1

    r = client.get("/api/collections/cases", headers=headers)
    assert r.status_code == 200
    cases = r.json()["cases"]
    assert len(cases) == 1
    case_id = cases[0]["id"]

    r = client.post(f"/api/collections/cases/{case_id}/attempt", headers=headers,
                    json={"channel": "phone", "outcome": "promised", "notes": "x"})
    assert r.status_code == 200
    assert r.json()["status"] == "promised"

    r = client.post(f"/api/collections/cases/{case_id}/status", headers=headers,
                    json={"status": "paid"})
    assert r.status_code == 200
    assert r.json()["status"] == "paid"
