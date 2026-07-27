"""Package 3 (2026-07-26 conversational-channels plan), decision 6: channel
link-code issuance/redemption. Covers channel_link_service.py directly and
the authenticated POST /api/channels/link-code route."""
from datetime import datetime, timedelta, timezone

import pytest

from cfo.database import SessionLocal
from cfo.models import ChannelIdentity, ChannelLinkCode, User
from cfo.services.channel_link_service import (
    ChannelLinkError,
    issue_link_code,
    redeem_link_code,
    resolve_identity,
)


def _user_id_for(email: str) -> int:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).first().id
    finally:
        db.close()


def test_link_code_route_requires_auth(client):
    r = client.post("/api/channels/link-code")
    assert r.status_code == 403


def test_link_code_route_issues_code_with_instructions(client, fresh_org):
    iso = fresh_org()
    r = client.post("/api/channels/link-code", headers=iso["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"]
    assert "expires_at" in body
    assert body["code"] in body["instructions"]


def test_link_code_expiry_is_timezone_explicit_and_in_the_future(client, fresh_org):
    """A naive ISO timestamp is read as LOCAL time by browsers — in Israel
    (UTC+3) that would make a brand-new code look already-expired to the
    countdown in SettingsPage.tsx. The wire format must carry the offset."""
    iso = fresh_org()
    r = client.post("/api/channels/link-code", headers=iso["headers"])
    expires_at = datetime.fromisoformat(r.json()["expires_at"])

    assert expires_at.tzinfo is not None, "expires_at must state its timezone"
    remaining = expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=10) < remaining <= timedelta(minutes=15)


def test_issued_code_is_stored_only_as_hash(fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        result = issue_link_code(db, iso["org_id"], _row_user_id(db, iso["org_id"]))
        row = db.query(ChannelLinkCode).order_by(ChannelLinkCode.id.desc()).first()
        assert row.code_hash != result["code"]
        assert len(row.code_hash) == 64  # sha256 hex digest length
    finally:
        db.close()


def _row_user_id(db, org_id: int) -> int:
    return db.query(User).filter(User.organization_id == org_id).first().id


def test_redeem_valid_code_creates_verified_identity(fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = _row_user_id(db, iso["org_id"])
        result = issue_link_code(db, iso["org_id"], user_id)

        identity = redeem_link_code(
            db, result["code"], provider="telegram", external_id="chat-1",
            display_name="Test User",
        )
        assert identity.verified_at is not None
        assert identity.revoked_at is None
        assert identity.organization_id == iso["org_id"]
        assert identity.user_id == user_id
        assert identity.default_persona == "cfo"
    finally:
        db.close()


def test_redeem_unknown_code_fails(fresh_org):
    db = SessionLocal()
    try:
        with pytest.raises(ChannelLinkError):
            redeem_link_code(db, "doesnotexist", provider="telegram", external_id="chat-x")
    finally:
        db.close()


def test_redeem_already_used_code_fails(fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = _row_user_id(db, iso["org_id"])
        result = issue_link_code(db, iso["org_id"], user_id)
        redeem_link_code(db, result["code"], provider="telegram", external_id="chat-used-1")

        with pytest.raises(ChannelLinkError):
            redeem_link_code(db, result["code"], provider="telegram", external_id="chat-used-2")
    finally:
        db.close()


def test_redeem_expired_code_fails(fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = _row_user_id(db, iso["org_id"])
        result = issue_link_code(db, iso["org_id"], user_id)
        row = db.query(ChannelLinkCode).order_by(ChannelLinkCode.id.desc()).first()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        with pytest.raises(ChannelLinkError):
            redeem_link_code(db, result["code"], provider="telegram", external_id="chat-expired")
    finally:
        db.close()


def test_redeem_error_messages_are_distinct(fresh_org):
    """Spec requires expired/used/unknown codes to fail with SEPARATE
    messages, not just "fail" — otherwise a bug that collapses all three
    into one generic error would pass silently."""
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = _row_user_id(db, iso["org_id"])

        with pytest.raises(ChannelLinkError) as exc_unknown:
            redeem_link_code(db, "totally-unknown-code", provider="telegram", external_id="c-unknown")

        used_result = issue_link_code(db, iso["org_id"], user_id)
        redeem_link_code(db, used_result["code"], provider="telegram", external_id="c-used-once")
        with pytest.raises(ChannelLinkError) as exc_used:
            redeem_link_code(db, used_result["code"], provider="telegram", external_id="c-used-twice")

        expired_result = issue_link_code(db, iso["org_id"], user_id)
        row = db.query(ChannelLinkCode).order_by(ChannelLinkCode.id.desc()).first()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(ChannelLinkError) as exc_expired:
            redeem_link_code(db, expired_result["code"], provider="telegram", external_id="c-expired")

        messages = {str(exc_unknown.value), str(exc_used.value), str(exc_expired.value)}
        assert len(messages) == 3, messages
    finally:
        db.close()


def test_resolve_identity_filters_revoked(fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = _row_user_id(db, iso["org_id"])
        result = issue_link_code(db, iso["org_id"], user_id)
        identity = redeem_link_code(db, result["code"], provider="telegram", external_id="chat-revoke")

        found = resolve_identity(db, "telegram", "chat-revoke")
        assert found is not None
        assert found.id == identity.id

        identity.revoked_at = datetime.utcnow()
        db.commit()

        assert resolve_identity(db, "telegram", "chat-revoke") is None
    finally:
        db.close()


def test_resolve_identity_returns_none_for_unknown_external_id():
    db = SessionLocal()
    try:
        assert resolve_identity(db, "telegram", "no-such-chat-id") is None
    finally:
        db.close()
