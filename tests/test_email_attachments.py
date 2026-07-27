"""תמיכת צרופות ב-send_email_smtp (תכנית מושקו 2026-07-27, חבילה C).

הבדיקות אינן פותחות SMTP אמיתי: הן מזריקות smtplib.SMTP מזויף ובודקות את
ההודעה שנבנתה בפועל.
"""
import asyncio

import pytest

from cfo.services import email_sender
from cfo.services.email_sender import MAX_TOTAL_ATTACHMENT_BYTES, send_email_smtp


class _Settings:
    smtp_host = "smtp.example.com"
    smtp_port = 587
    smtp_user = None
    smtp_password = None
    smtp_from = "rezef@example.com"


class _FakeSMTP:
    """מחליף את smtplib.SMTP ושומר את ההודעה האחרונה שנשלחה."""

    sent = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        type(self).sent.append(msg)


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(email_sender.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


def test_plain_email_without_attachments_stays_single_part(_fake_smtp):
    """שלושת הקוראים הקיימים לא מעבירים attachments — ההודעה חייבת להישאר
    בדיוק כפי שהייתה, לא multipart."""
    assert asyncio.run(send_email_smtp("a@b.com", "נושא", "גוף", _Settings())) is True

    msg = _fake_smtp.sent[0]
    assert msg.is_multipart() is False
    assert msg.get_content_type() == "text/plain"
    assert "גוף" in msg.get_payload(decode=True).decode("utf-8")


def test_attachment_is_delivered_with_filename(_fake_smtp):
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ok = asyncio.run(
        send_email_smtp(
            "bank@example.com", "רווח והפסד", "מצורף הדוח", _Settings(),
            attachments=[("pnl.xlsx", b"PK\x03\x04fake", xlsx.split("/")[-1])],
        )
    )
    assert ok is True

    msg = _fake_smtp.sent[0]
    assert msg.is_multipart() is True
    parts = msg.get_payload()
    assert parts[0].get_payload(decode=True).decode("utf-8") == "מצורף הדוח"
    assert parts[1].get_filename() == "pnl.xlsx"
    assert parts[1].get_payload(decode=True) == b"PK\x03\x04fake"


def test_oversized_attachment_is_refused_not_silently_sent(_fake_smtp):
    """ספק SMTP עלול לדחות/לחתוך מייל גדול — עדיף False מפורש מאשר
    לדווח 'נשלח' על מייל שלא הגיע."""
    huge = b"x" * (MAX_TOTAL_ATTACHMENT_BYTES + 1)
    ok = asyncio.run(
        send_email_smtp(
            "a@b.com", "s", "b", _Settings(), attachments=[("big.xlsx", huge, "octet-stream")],
        )
    )
    assert ok is False
    assert _fake_smtp.sent == []


def test_unconfigured_smtp_refuses_even_with_attachment(_fake_smtp):
    class _NoSMTP(_Settings):
        smtp_host = None

    ok = asyncio.run(
        send_email_smtp(
            "a@b.com", "s", "b", _NoSMTP(), attachments=[("x.xlsx", b"data", "octet-stream")],
        )
    )
    assert ok is False
    assert _fake_smtp.sent == []
