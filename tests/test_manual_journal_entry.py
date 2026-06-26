"""פאזה 6 — פקודת יומן ידנית (התאמות רו"ח): נשמרת, חייבת להיות מאוזנת,
ונכללת ב-journal/trial_balance כמו פקודות נגזרות.
"""
from datetime import date

import pytest

from cfo.services import ledger_service


def test_add_manual_entry_persists_and_appears_in_trial_balance(fresh_org):
    from cfo.database import SessionLocal

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        ledger_service.add_manual_entry(
            db, org_id, entry_date=date(2026, 3, 1), memo="התאמת רו\"ח",
            lines=[
                {"account": "5000", "debit": 100, "credit": 0, "description": "הוצאה"},
                {"account": "1200", "debit": 0, "credit": 100, "description": "בנק"},
            ],
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        tb = ledger_service.trial_balance(db, org_id, start=date(2026, 3, 1), end=date(2026, 3, 31))
        rows = {r["account"]: r for r in tb["accounts"]}
        assert rows["5000"]["debit"] == 100.0
        assert rows["1200"]["credit"] == 100.0
        assert tb["balanced"] is True
    finally:
        db.close()


def test_manual_entry_route_creates_and_rejects(client, owner):
    h = owner["headers"]
    ok = client.post("/api/ledger/entries", headers=h, json={
        "entry_date": "2026-03-02", "memo": "התאמה",
        "lines": [{"account": "5000", "debit": 50, "credit": 0},
                  {"account": "1200", "debit": 0, "credit": 50}],
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "created"
    bad = client.post("/api/ledger/entries", headers=h, json={
        "entry_date": "2026-03-02", "memo": "לא מאוזן",
        "lines": [{"account": "5000", "debit": 50, "credit": 0},
                  {"account": "1200", "debit": 0, "credit": 40}],
    })
    assert bad.status_code == 400


def test_add_manual_entry_rejects_unbalanced(fresh_org):
    from cfo.database import SessionLocal

    org = fresh_org()
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            ledger_service.add_manual_entry(
                db, org["org_id"], entry_date=date(2026, 3, 1), memo="לא מאוזן",
                lines=[
                    {"account": "5000", "debit": 100, "credit": 0},
                    {"account": "1200", "debit": 0, "credit": 90},
                ],
            )
    finally:
        db.close()
