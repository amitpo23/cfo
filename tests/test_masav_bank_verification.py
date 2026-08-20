"""חוק 17 — מס"ב אינה מדווחת כשל על פרטי בנק שגויים.

הפער (סריקת KB ‏20/08): `verify_bank_account` של SUMIT (בדיקה מול מאגר
בנק ישראל) עטוף ולא מחובר למסלול מס"ב — הוולידציה הקיימת היא מבנית
בלבד (קוד בנק/סניף/חשבון חוקיים בצורתם), וחשבון סגור/מוגבל עובר בשקט.

הפתרון: (א) route מפורש `POST /api/masav/verify-accounts` שמאמת את
חשבונות המוטבים מול SUMIT (קריאות API — באישור מפורש, לא אוטומטי);
(ב) ה-preview מציג אזהרת חוק 17 כשהחשבונות לא אומתו.
"""
import pytest

from cfo.database import SessionLocal


def test_preview_carries_rule17_warning(client, fresh_org):
    iso = fresh_org()
    saved = client.post(
        "/api/masav/settings",
        json={"institution_code": "12345678", "sending_institution": "12345",
              "institution_name": "בדיקה"},
        headers=iso["headers"],
    )
    assert saved.status_code == 200, saved.text
    r = client.post(
        "/api/masav/preview",
        json={"payment_date": "2026-09-01"},
        headers=iso["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "bank_verification_notice" in body
    assert "מס\"ב" in body["bank_verification_notice"]


def test_verify_accounts_route_calls_sumit_per_distinct_account(client, fresh_org, monkeypatch):
    iso = fresh_org()
    calls = []

    async def fake_verify(db, org_id, accounts):
        calls.append(list(accounts))
        return [
            {"bank_code": a["bank_code"], "branch": a["branch"],
             "account_number": a["account_number"],
             "valid": True, "valid_branch": True, "is_limited_account": False}
            for a in accounts
        ]

    import cfo.api.routes.masav as masav_module
    monkeypatch.setattr(masav_module, "_verify_accounts_against_sumit", fake_verify)
    monkeypatch.setattr(
        masav_module, "_gather",
        lambda db, org_id, bill_ids: (
            [type("P", (), {
                "beneficiary_name": "ספק", "bank_code": "12", "branch": "345",
                "account_number": "123456", "amount": 100, "reference": "r1",
            })(),
             type("P", (), {
                "beneficiary_name": "ספק", "bank_code": "12", "branch": "345",
                "account_number": "123456", "amount": 200, "reference": "r2",
             })()],
            [],
        ),
    )

    r = client.post(
        "/api/masav/verify-accounts",
        json={"payment_date": "2026-09-01"},
        headers=iso["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # שני תשלומים לאותו חשבון — אימות SUMIT אחד בלבד (דדופ, חיסכון בקריאות).
    assert len(calls) == 1 and len(calls[0]) == 1
    assert body["accounts"][0]["valid"] is True
    assert body["verified_count"] == 1
