"""ההצלבה מול ספרי SUMIT חייבת לכסות גם את צד העסקאות.

**הממצא (18/08/2026).** ה-API של `FilingCrosscheck` תומך ב-
`books_output_vat` מיומו הראשון, ו-`parity_service._check_sumit_crosscheck`
משווה את שני הצדדים — אבל **מסך המע"מ שלח רק `books_input_vat`**.

התוצאה: `diff_output_vat` היה תמיד `None`, כלומר צד העסקאות לא נבדק
מעולם. חצי מההצלבה היה קיים בקוד ובלתי-אפשרי להזנה.

(תיקון לאודיט שלי: כתבתי שם ש"צריך לבנות מסך הקלדה". המסך קיים ואף
מקושר בניווט תחת `/vat-report`. הפער היה שדה אחד.)

**honest-null בשדה עצמו:** ריק ≠ אפס. אפס הוא הצהרה שאין עסקאות
בתקופה; ריק הוא "לא נבדק". השרת מבחין ביניהם, ולכן ה-UI אינו שולח 0
כברירת מחדל.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import FilingCrosscheck


def test_the_api_stores_the_output_side(client, owner):
    """השרת תמך בזה תמיד — הטסט מקבע את ההתנהגות שה-UI עכשיו מנצל."""
    resp = client.post(
        "/api/daily-reports/vat/crosscheck",
        headers=owner["headers"],
        json={"year": 2026, "month": 5, "months": 1, "basis": "document",
              "books_input_vat": 1234.5, "books_output_vat": 9876.5},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["books_output_vat"] == 9876.5


def test_an_omitted_output_stays_null_not_zero(client, owner):
    """**הלב.** אפס הוא הצהרה שאין עסקאות; חסר הוא 'לא נבדק'. אם השרת
    היה כותב 0, ה-parity היה משווה מול אפס ומדווח פער מלא — כשל שגוי
    שמאמן להתעלם."""
    resp = client.post(
        "/api/daily-reports/vat/crosscheck",
        headers=owner["headers"],
        json={"year": 2026, "month": 6, "months": 1, "basis": "document",
              "books_input_vat": 500.0},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["books_output_vat"] is None


def test_parity_compares_both_sides_when_both_are_present(client, fresh_org):
    """הערך של השדה החדש: ברגע שהוקלד, ה-parity משווה אותו."""
    from datetime import date

    from cfo.services import parity_service

    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    db.add(FilingCrosscheck(
        organization_id=org_id, period="2026-05", basis="document",
        books_input_vat=100.0, books_output_vat=250.0, source="manual",
    ))
    db.commit()

    check = parity_service._check_sumit_crosscheck(db, org_id, date(2026, 5, 31))

    assert check["status"] != "skipped", "ההצלבה דולגה למרות שיש רשומה"
    assert check["diff_output_vat"] is not None, (
        "צד העסקאות לא הושווה — זה בדיוק מה שהיה שבור"
    )


def test_the_ui_sends_the_output_field():
    """שער חיווט: תמיכת שרת בלי שדה ב-UI היא יכולת שאי-אפשר להשתמש בה.
    זהו הכשל שחזר בסשן הזה — נבנה, נבדק, ולא היה על המסלול."""
    import pathlib

    src = pathlib.Path("frontend/src/components/VatReportScreen.tsx").read_text()

    assert "books_output_vat" in src, "המסך אינו שולח את צד העסקאות"
    assert "crosscheckOutput" in src
