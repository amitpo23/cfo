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


# ---------------------------------------------------------------------- #
# org_categories — כרטיסים מותאמים אישית לארגון. מילות המפתח שלהם גוברות
# על מילות המפתח המובנות (CATEGORY_KEYWORDS).
# ---------------------------------------------------------------------- #

def test_org_category_keyword_wins_over_built_in_on_the_same_keyword():
    """הבוחן המכריע: 'ביטוח' הוא גם מילת מפתח מובנית (-> 'insurance') וגם
    מילת מפתח של כרטיס מותאם אישית. אם הכרטיס המותאם אינו נבדק ראשון, הבדיקה
    הזו הייתה עוברת גם בטעות (למשל אם רק ה-built-in נבדק) — לכן מילת המפתח
    זהה בשני המקורות, לא ייחודית לכרטיס המותאם."""
    org_categories = [{"key": "vehicle_insurance_card", "keywords": ["ביטוח"]}]
    result = classify_expense("חברת ביטוח ישיר", org_categories=org_categories)
    assert result == "vehicle_insurance_card"
    # ובלי org_categories אותה מחרוזת מסווגת ל-built-in הרגיל
    assert classify_expense("חברת ביטוח ישיר") == "insurance"


def test_org_category_falls_back_to_built_in_when_no_org_keyword_matches():
    org_categories = [{"key": "custom_card", "keywords": ["מילה-שלא-מופיעה-בטקסט"]}]
    assert classify_expense("תחנת דלק פז", org_categories=org_categories) == "travel"


def test_sumit_item_name_still_beats_org_category_keywords():
    # שם פריט SUMIT הוא האות האמין ביותר — גובר גם על כרטיסים מותאמים אישית.
    org_categories = [{"key": "custom_travel", "keywords": ["נסיעה"]}]
    result = classify_expense(
        "ספק כללי", sumit_item_name="הוצאות נסיעה", org_categories=org_categories,
    )
    assert result == "travel"


def test_org_categories_with_no_keywords_are_safely_ignored():
    org_categories = [{"key": "no_keywords_card", "keywords": None}]
    assert classify_expense("תחנת דלק פז", org_categories=org_categories) == "travel"


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
