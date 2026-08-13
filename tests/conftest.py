import os
import socket
import sys
import tempfile

# Must run before the app (and its settings) are imported.
_db_path = os.path.join(tempfile.mkdtemp(prefix="cfo_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ.pop("REGISTRATION_SECRET", None)
# מפתח מזויף. תפקידו היחיד: לגרום ל-"האם SUMIT מוגדר?" להחזיר True
# עבור ארגון 1, כדי שטסטי הבידוד יוכלו להוכיח ששאר הארגונים **אינם**
# נופלים על קרדנשלים מהסביבה. הוא לא נועד להישלח לשום מקום —
# ראו חומת הרשת מיד למטה, שהיא מה שהופך את הכוונה הזו לאכיפה.
os.environ["SUMIT_API_KEY"] = "test-env-sumit-key"
os.environ["CRON_SECRET"] = "test-cron-secret"

# --------------------------------------------------------------------- #
# חומת רשת — אירוע 13/08/2026
# --------------------------------------------------------------------- #
# מדידה עם sentinel גילתה **116 ניסיונות חיבור ל-`api.sumit.co.il` בכל
# ריצת סוויטה מלאה**, עם המפתח המזויף שלמעלה. בריצות חוזרות באותו יום —
# מעל אלף ניסיונות אימות כושלים מאותה כתובת IP, כלומר בדיוק הדפוס
# ש-SUMIT חוסמת עליו ("Repeated incorrect credentials attempts detected").
# החסימה חלה על ה-IP, ולכן היא פוגעת גם בעבודה האמיתית של הבעלים.
#
# למה זה היה בלתי-נראה: הטסטים עוברים בין אם הקריאה הצליחה ובין אם
# נכשלה — הם בודקים את טיפול השגיאה. סוויטה ירוקה מעולם לא העידה שאין
# תעבורה יוצאת.
#
# החסימה ב-DNS ולא ב-`connect` במכוון: היא תופסת גם ספריות שמנהלות
# connection pool משלהן. הודעת השגיאה נושאת את שם הטסט האשם, כדי
# שהוספה עתידית של קריאה יוצאת תאותר מיד ולא תחייב חיפוש ב-1,967 טסטים.

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver", ""}
_real_getaddrinfo = socket.getaddrinfo
_real_create_connection = socket.create_connection
_current_test = {"name": "<import/collection>"}


def _host_str(host) -> str:
    return host.decode() if isinstance(host, (bytes, bytearray)) else str(host)


def _blocked(host) -> RuntimeError:
    return RuntimeError(
        f"provider network is blocked in tests: {host} "
        f"(attempted by {_current_test['name']}). "
        "Use a fake connector/client instead of a real request — a live call "
        "with the placeholder key gets the owner's IP blocked by the provider."
    )


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    name = _host_str(host)
    if name not in _LOCAL_HOSTS:
        raise _blocked(name)
    return _real_getaddrinfo(host, port, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    name = _host_str(address[0]) if address else ""
    if name not in _LOCAL_HOSTS:
        raise _blocked(name)
    return _real_create_connection(address, *args, **kwargs)


socket.getaddrinfo = _guarded_getaddrinfo
socket.create_connection = _guarded_create_connection

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from fastapi.testclient import TestClient

from cfo.api import app


def pytest_runtest_setup(item):
    """מחזיק את שם הטסט הנוכחי כדי שחומת הרשת תוכל להצביע על האשם."""
    _current_test["name"] = item.name


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def owner(client):
    """First registered user — admin of the default organization."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "owner@example.com",
        "password": "secret123",
        "full_name": "Owner",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}, "user": data["user"]}


_iso_counter = {"n": 0}


@pytest.fixture
def fresh_org(client, owner):
    """Factory for an isolated organization (its own user) per test.

    Use when a test asserts exact aggregate amounts derived across ALL of an org's
    documents (ledger trial balance, cumulative P&L, annual reports) — the
    session-scoped `owner` org is shared across files and would pollute such totals.

    Depends on `owner` so the default org (first registered user) is always claimed
    by owner@example.com before any isolated org is created, regardless of test order.
    """
    def _make():
        _iso_counter["n"] += 1
        email = f"iso{_iso_counter['n']}@example.com"
        resp = client.post("/api/admin/auth/register", json={
            "email": email, "password": "secret123", "full_name": "Iso",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        return {"headers": {"Authorization": f"Bearer {data['access_token']}"},
                "org_id": data["user"]["organization_id"]}
    return _make


@pytest.fixture(scope="session")
def tenant(client, owner):
    """Second self-registered user — gets an organization of their own."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "tenant@example.com",
        "password": "secret123",
        "full_name": "Tenant",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}, "user": data["user"]}


@pytest.fixture(scope="session")
def mdb_dir():
    """ייצוא ה-MDB של חשבשבת (עומר ועודד, org5). מדלג כשאינו זמין —
    הקבצים מכילים נתוני לקוח ואינם ב-git."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "reports/omer_porat/hashavshevet_to_sumit/mdb_extract"
    if not (path / "JurnalTrans.csv").is_file():
        pytest.skip("ייצוא ה-MDB אינו זמין בסביבה הזו")
    return path
