"""Package G (2026-07-27b moshko-memory-and-whatsapp plan): email-based
channel verification. SUMIT exposes no API for a company's authorized phone
numbers/users (verified: zero endpoints), so an unknown phone is verified
against rezef's own User table via a 6-digit code sent to the REGISTERED
email — control of the phone plus control of the mailbox.

No real SMTP/network anywhere in this file: send_email_smtp is always
monkeypatched on cfo.services.channel_link_service (the name it's imported
under there), never allowed to touch smtplib.

Async calls use `asyncio.run(...)` inside plain sync test functions
(matching tests/test_of_snapshot_cache.py's convention) since
pytest-asyncio isn't configured in strict/auto mode in this repo.
"""
import asyncio
import re
from datetime import datetime, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import ChannelIdentity, ChannelLinkCode, User, UserRole
from cfo.services import channel_link_service as svc
from cfo.services.channel_link_service import (
    ChannelLinkError,
    complete_email_verification,
    start_email_verification,
)

_CODE_RE = re.compile(r"\b(\d{6})\b")


@pytest.fixture(autouse=True)
def _no_timing_pad(monkeypatch):
    """The 2s anti-timing-oracle floor is real behaviour, but paying it in
    every test would add minutes to the suite. Zeroed by default; the one
    test that actually asserts on it restores it explicitly."""
    monkeypatch.setattr(svc, "_MIN_START_RESPONSE_SECONDS", 0.0)


@pytest.fixture
def fake_smtp(monkeypatch):
    """Records every call instead of hitting real SMTP. `outcome["sent"]`
    controls the return value (defaults True); tests that want a failure
    flip it to False before calling start_email_verification."""
    calls = []
    outcome = {"sent": True}

    async def _fake_send(to, subject, body, settings, *, attachments=None):
        calls.append({"to": to, "subject": subject, "body": body})
        return outcome["sent"]

    monkeypatch.setattr(svc, "send_email_smtp", _fake_send)
    return calls, outcome


def _extract_code(body: str) -> str:
    m = _CODE_RE.search(body)
    assert m, f"no 6-digit code found in email body: {body!r}"
    return m.group(1)


def _email_for_org(org_id: int) -> str:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.organization_id == org_id).first().email
    finally:
        db.close()


def _start(db, *, provider="telegram", external_id="chat-1", email):
    return asyncio.run(
        start_email_verification(db, provider=provider, external_id=external_id, email=email)
    )


def test_unknown_and_known_email_return_identical_response(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        unknown_result = _start(db, external_id="chat-unknown", email="nobody-here@example.com")
        known_result = _start(db, external_id="chat-known", email=known_email)
    finally:
        db.close()

    assert unknown_result == known_result
    assert unknown_result["status"] == "code_sent"
    # But an email only actually went out for the known address.
    assert len(calls) == 1
    assert calls[0]["to"] == known_email.strip().lower()


def test_email_case_and_whitespace_are_normalized(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        result = _start(db, external_id="chat-norm", email=f"  {known_email.upper()}  ")
    finally:
        db.close()

    assert result["status"] == "code_sent"
    assert len(calls) == 1


def test_valid_code_links_identity_to_the_registered_user(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        _start(db, external_id="chat-valid", email=known_email)
        code = _extract_code(calls[-1]["body"])

        identity = complete_email_verification(
            db, provider="telegram", external_id="chat-valid", code=code,
        )
        assert identity.verified_at is not None
        assert identity.revoked_at is None
        assert identity.organization_id == iso["org_id"]

        db_user = db.query(User).filter(User.email == known_email).first()
        assert identity.user_id == db_user.id
    finally:
        db.close()


def test_valid_code_backfills_empty_user_phone(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == known_email).first()
        assert not user.phone  # fresh_org-registered users have no phone set

        _start(db, provider="whatsapp", external_id="9725550001", email=known_email)
        code = _extract_code(calls[-1]["body"])
        complete_email_verification(db, provider="whatsapp", external_id="9725550001", code=code)

        db.refresh(user)
        assert user.phone == "9725550001"
    finally:
        db.close()


def test_telegram_link_does_not_backfill_phone_with_chat_id(fresh_org, fake_smtp):
    """external_id is only a real phone number for provider="whatsapp" — a
    telegram chat_id must never be written into User.phone, even when phone
    was empty beforehand (see the deviation note in complete_email_verification)."""
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == known_email).first()
        assert not user.phone

        _start(db, provider="telegram", external_id="chat-no-phone-backfill", email=known_email)
        code = _extract_code(calls[-1]["body"])
        complete_email_verification(db, provider="telegram", external_id="chat-no-phone-backfill", code=code)

        db.refresh(user)
        assert user.phone is None
    finally:
        db.close()


def test_wrong_code_fails_with_distinct_message(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        _start(db, external_id="chat-wrong", email=known_email)
        with pytest.raises(ChannelLinkError) as exc:
            complete_email_verification(db, provider="telegram", external_id="chat-wrong", code="000000")
        assert "שגוי" in str(exc.value)
    finally:
        db.close()


def test_used_code_fails_with_distinct_message(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        _start(db, external_id="chat-used", email=known_email)
        code = _extract_code(calls[-1]["body"])
        complete_email_verification(db, provider="telegram", external_id="chat-used", code=code)

        with pytest.raises(ChannelLinkError) as exc:
            complete_email_verification(db, provider="telegram", external_id="chat-used", code=code)
        assert "נוצל" in str(exc.value)
    finally:
        db.close()


def test_expired_code_fails_with_distinct_message(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        _start(db, external_id="chat-expired", email=known_email)
        row = db.query(ChannelLinkCode).order_by(ChannelLinkCode.id.desc()).first()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        code = _extract_code(calls[-1]["body"])
        with pytest.raises(ChannelLinkError) as exc:
            complete_email_verification(db, provider="telegram", external_id="chat-expired", code=code)
        assert "פג" in str(exc.value)
    finally:
        db.close()


def test_code_sent_to_one_external_id_cannot_be_redeemed_from_another(fresh_org, fake_smtp):
    """The single most important test in this file: a code sent while
    talking to the bot from chat A must not be usable by pasting it in from
    chat B, even with the exact right digits and provider."""
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        _start(db, external_id="chat-A", email=known_email)
        code = _extract_code(calls[-1]["body"])

        with pytest.raises(ChannelLinkError):
            complete_email_verification(db, provider="telegram", external_id="chat-B", code=code)

        # The rightful owner (chat-A) can still redeem it — proves the
        # failure above was really about external_id, not a broken code.
        identity = complete_email_verification(db, provider="telegram", external_id="chat-A", code=code)
        assert identity.external_id == "chat-A"
    finally:
        db.close()


def test_blocked_after_five_failed_attempts(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        _start(db, external_id="chat-brute", email=known_email)
        real_code = _extract_code(calls[-1]["body"])

        for _ in range(5):
            with pytest.raises(ChannelLinkError):
                complete_email_verification(db, provider="telegram", external_id="chat-brute", code="111111")

        # 6th attempt is blocked even with the CORRECT code.
        with pytest.raises(ChannelLinkError) as exc:
            complete_email_verification(db, provider="telegram", external_id="chat-brute", code=real_code)
        assert "ניסיונות" in str(exc.value)
    finally:
        db.close()


def test_smtp_failure_returns_email_unavailable_and_burns_the_code(fresh_org, fake_smtp):
    calls, outcome = fake_smtp
    outcome["sent"] = False
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        result = _start(db, external_id="chat-nosmtp", email=known_email)
        assert result["status"] == "email_unavailable"

        # The code was generated (to build the email) but never delivered —
        # confirm it can't be redeemed even by someone who somehow guessed it.
        code = _extract_code(calls[-1]["body"])
        with pytest.raises(ChannelLinkError):
            complete_email_verification(db, provider="telegram", external_id="chat-nosmtp", code=code)
    finally:
        db.close()


def test_super_admin_with_null_org_cannot_be_linked(fake_smtp):
    calls, _ = fake_smtp
    db = SessionLocal()
    try:
        admin_email = "super-admin-pkg-g@example.com"
        existing = db.query(User).filter(User.email == admin_email).first()
        if existing is None:
            admin = User(
                email=admin_email, password_hash="x", full_name="Super Admin",
                organization_id=None, is_active=True,
            )
            db.add(admin)
            db.commit()

        result = _start(db, external_id="chat-superadmin", email=admin_email)
        assert result["status"] == "code_sent"  # same enumeration-safe response
        assert len(calls) == 0  # but nothing was actually sent
    finally:
        db.close()


def test_inactive_user_cannot_be_linked(fresh_org, fake_smtp):
    calls, _ = fake_smtp
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == known_email).first()
        user.is_active = False
        db.commit()

        result = _start(db, external_id="chat-inactive", email=known_email)
        assert result["status"] == "code_sent"
        assert len(calls) == 0
    finally:
        db.close()


def test_email_verification_never_guesses_an_org_for_multi_org_user(
    fresh_org, fake_smtp,
):
    calls, _ = fake_smtp
    primary = fresh_org()
    secondary = fresh_org()
    email = _email_for_org(primary["org_id"])
    db = SessionLocal()
    try:
        from cfo.models import OrganizationMembership
        user = db.query(User).filter(User.email == email).one()
        db.add(OrganizationMembership(
            organization_id=secondary["org_id"],
            user_id=user.id,
            role=UserRole.VIEWER,
            status="active",
            invited_by_user_id=user.id,
            verified_at=datetime.utcnow(),
        ))
        db.commit()

        result = _start(
            db, provider="whatsapp", external_id="972500009999", email=email,
        )

        assert result["status"] == "code_sent"
        assert len(calls) == 1
        assert _CODE_RE.search(calls[0]["body"]) is None
        assert "לאפליקציה" in calls[0]["body"]
        assert db.query(ChannelLinkCode).filter(
            ChannelLinkCode.user_id == user.id,
            ChannelLinkCode.used_at.is_(None),
        ).count() == 0
    finally:
        db.close()


# --- הקשחות שנוספו בביקורת האורקסטרייטור (2026-07-27) --- #

def test_requesting_a_code_is_rate_limited_per_device(fake_smtp, fresh_org):
    """בלי תקרה על *בקשת* קוד, start_email_verification הוא אורקל בלתי מוגבל:
    אפשר לסרוק כתובות כדי ללמוד מי לקוח של רצף, ואפשר להפציץ תיבת מייל של
    לקוח אמיתי בקודים. תקרת הניחושים הכושלים לא מכסה את זה."""
    calls, _ = fake_smtp
    iso = fresh_org()
    email = _email_for_org(iso["org_id"])

    results = []
    for _ in range(svc.MAX_REQUESTS_PER_EXTERNAL_ID + 1):
        db = SessionLocal()
        try:
            results.append(asyncio.run(start_email_verification(
                db, provider="whatsapp", external_id="972500000001", email=email,
            )))
        finally:
            db.close()

    assert results[-1]["status"] == "rate_limited"
    assert all(r["status"] != "rate_limited" for r in results[:-1])
    # לא נשלחו מיילים מעבר לתקרה
    assert len(calls) == svc.MAX_REQUESTS_PER_EXTERNAL_ID


def test_rate_limit_counts_unknown_emails_too(fake_smtp, fresh_org):
    calls, _ = fake_smtp
    """התקרה נספרת לפני החיפוש ולכל בקשה — אחרת היא עצמה הופכת לאורקל:
    'נחסמתי' היה מסגיר שהכתובות שניסיתי קיימות."""
    for _ in range(svc.MAX_REQUESTS_PER_EXTERNAL_ID):
        db = SessionLocal()
        try:
            asyncio.run(start_email_verification(
                db, provider="whatsapp", external_id="972500000002",
                email="nobody-here@example.com",
            ))
        finally:
            db.close()

    db = SessionLocal()
    try:
        blocked = asyncio.run(start_email_verification(
            db, provider="whatsapp", external_id="972500000002",
            email="nobody-here@example.com",
        ))
    finally:
        db.close()

    assert blocked["status"] == "rate_limited"
    assert calls == []


def test_unknown_email_response_is_padded_to_the_same_floor(fake_smtp, monkeypatch):
    """התשובה הזהה מילולית שווה כלום אם היא חוזרת מיידית: המסלול של מייל
    קיים ממתין ל-SMTP, ולכן מהירות התשובה עצמה מסגירה אילו כתובות רשומות."""
    monkeypatch.setattr(svc, "_MIN_START_RESPONSE_SECONDS", 0.4)
    import time as _time

    db = SessionLocal()
    try:
        started = _time.monotonic()
        asyncio.run(start_email_verification(
            db, provider="whatsapp", external_id="972500000003",
            email="definitely-not-registered@example.com",
        ))
        elapsed = _time.monotonic() - started
    finally:
        db.close()

    assert elapsed >= 0.4
