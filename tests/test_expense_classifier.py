"""בדיקות מסווג הוצאות + סיווג גורף + תיוק גורף."""
from datetime import date
import pytest
from cfo.services.expense_classifier import classify_expense


@pytest.mark.parametrize("supplier,desc,expected", [
    ("עו\"ד כהן", None, "professional"),
    ("תחנת דלק פז", None, "travel"),
    ("חברת חשמל", None, "utilities"),
    ("Google Ads", None, "marketing"),
    ("השכרת משרד", "דמי שכירות חודשי", "rent"),
    ("ביטוח ישיר", None, "insurance"),
    ("ספק חומרי גלם", None, "materials"),
    ("משהו אקראי לגמרי", None, "other"),
])
def test_classify_rules(supplier, desc, expected):
    assert classify_expense(supplier, desc) == expected


@pytest.mark.parametrize("item_name,expected", [
    ("הוצאות נסיעה", "travel"),
    ("אנרגיה", "utilities"),
    ("ציוד משרדי", "equipment"),
    ("הוצאות משרד", "office"),
    ("קופה קטנה", "petty_cash"),
    ("הוצאות כלליות", "other"),
])
def test_classify_by_sumit_item_name(item_name, expected):
    # שם הפריט של SUMIT הוא אות הסיווג האמין כשהספק גנרי
    assert classify_expense("ספק כללי", sumit_item_name=item_name) == expected


def test_sumit_item_name_takes_priority_over_supplier():
    # גם אם שם הספק מטעה, פריט SUMIT גובר
    assert classify_expense("ספק כללי", sumit_item_name="הוצאות נסיעה") == "travel"


def test_unknown_item_name_falls_back_to_supplier_keywords():
    # פריט לא מוכר -> נופלים חזרה לסיווג לפי שם ספק/תיאור
    assert classify_expense("תחנת דלק פז", sumit_item_name="פריט לא מוכר") == "travel"


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "clsowner@example.com", "password": "secret123", "full_name": "Cls Owner",
    })
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"}}


def test_auto_classify_on_create(client, acc):
    r = client.post("/api/expenses", json={
        "supplier_name": "תחנת דלק", "amount": 300, "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["data"]["category"] == "travel"  # סווג אוטומטית


def test_bulk_classify_endpoint(client, acc):
    # הוצאה עם קטגוריה ריקה מפורשת -> other -> תסווג מחדש
    client.post("/api/expenses", json={
        "supplier_name": "רואה חשבון לוי", "amount": 500,
        "expense_date": date.today().isoformat(), "category": "other",
    }, headers=acc["headers"])
    r = client.post("/api/expenses/classify", headers=acc["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["data"]["classified"] >= 1
    filed = client.get("/api/expenses", headers=acc["headers"]).json()["data"]
    accountant = [e for e in filed if e["supplier_name"] == "רואה חשבון לוי"]
    assert accountant and accountant[0]["category"] == "professional"


def test_file_all_without_sumit(client, acc):
    # אין חיבור SUMIT -> כל ניסיון נכשל נקי, מדווח failed (לא קריסה)
    r = client.post("/api/expenses/file-all", headers=acc["headers"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["filed"] == 0 and d["failed"] >= 1
