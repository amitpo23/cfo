"""חומת רשת: הסוויטה לא יוצאת לספק חיצוני. לעולם.

**האירוע שהוליד את הקובץ הזה (13/08/2026).** `conftest.py` מגדיר
`SUMIT_API_KEY="test-env-sumit-key"` — מפתח מזויף שנועד רק לגרום ל-
"האם SUMIT מוגדר?" להחזיר True. אלא ששום דבר לא מנע מהקוד להשתמש בו
**מול השרת האמיתי**.

מדידה עם sentinel: **116 ניסיונות חיבור ל-`api.sumit.co.il` בכל ריצת
סוויטה מלאה.** בריצות חוזרות באותו יום מדובר באלף ומעלה ניסיונות אימות
כושלים מאותה כתובת IP — בדיוק הדפוס ש-SUMIT חוסמת עליו
("Repeated incorrect credentials attempts detected").

**למה זה היה בלתי-נראה:** הטסטים עוברים בין אם הקריאה הצליחה ובין אם
נכשלה — הם בודקים את טיפול השגיאה. סוויטה ירוקה מעולם לא העידה שאין
תעבורה יוצאת. רק אינסטרומנטציה חשפה זאת.

הכלל מעכשיו: כל ניסיון חיבור לכתובת שאינה מקומית **נכשל בקול** ומצביע
על הטסט האשם. טסט שצריך התנהגות ספק — משתמש ב-fake, לא ברשת.
"""
import socket

import pytest


EXTERNAL_HOSTS = ["api.sumit.co.il", "data.gov.il", "example.com"]


@pytest.mark.parametrize("host", EXTERNAL_HOSTS)
def test_outbound_dns_to_an_external_host_is_blocked(host):
    """הבדיקה המרכזית: אי-אפשר אפילו לפתור שם של מארח חיצוני.

    חסימה ב-DNS ולא ב-connect היא מכוונת — היא תופסת גם ספריות שמנהלות
    connection pool משלהן ולא עוברות ב-`socket.create_connection`."""
    with pytest.raises(RuntimeError) as err:
        socket.getaddrinfo(host, 443)

    assert "provider network" in str(err.value).lower()
    assert host in str(err.value)


def test_the_error_names_the_test_so_the_culprit_is_obvious(request):
    """מי שיוסיף מחר קריאה יוצאת יראה מיד איזה טסט אשם — במקום לחפש
    בין 1,967 טסטים."""
    with pytest.raises(RuntimeError) as err:
        socket.getaddrinfo("api.sumit.co.il", 443)

    assert request.node.name in str(err.value)


def test_localhost_still_resolves():
    """שער נגדי: חומה שחוסמת גם localhost הייתה מפילה את TestClient
    ואת ה-SQLite המקומי, וכל הסוויטה הייתה אדומה מסיבה לא קשורה."""
    assert socket.getaddrinfo("127.0.0.1", 0)
    assert socket.getaddrinfo("localhost", 0)


def test_creating_a_connection_to_an_external_host_is_blocked():
    with pytest.raises(RuntimeError):
        socket.create_connection(("api.sumit.co.il", 443), timeout=1)


def test_raw_socket_connect_is_guarded_without_touching_the_network():
    """ספרייה יכולה לעקוף DNS ו-create_connection עם כתובת IP מוכנה."""
    assert socket.socket.__name__ == "_GuardedSocket"


def test_raw_socket_connect_ex_is_guarded_without_touching_the_network():
    assert "connect_ex" in socket.socket.__dict__
