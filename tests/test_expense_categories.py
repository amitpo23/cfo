"""בדיקות: כרטיסי הוצאה מותאמים אישית לארגון (ExpenseCategory) — CRUD, בידוד
בין ארגונים, ומניעת מחיקה כשקטגוריה בשימוש."""
from datetime import date

import pytest


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "catowner@example.com", "password": "secret123", "full_name": "Cat Owner",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"}}


def test_list_categories_includes_built_ins_marked_as_such(client, acc):
    r = client.get("/api/expenses/categories", headers=acc["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    built_in = [c for c in data if c["built_in"]]
    assert any(c["key"] == "rent" for c in built_in)
    assert any(c["key"] == "travel" for c in built_in)
    # לכרטיסים המובנים אין id (הם לא שורות ב-DB)
    assert all(c["id"] is None for c in built_in)


def test_create_and_list_custom_category(client, acc):
    r = client.post("/api/expenses/categories", json={
        "key": "conference_travel", "name_he": "נסיעות לכנסים",
        "keywords": ["כנס", "conference"],
    }, headers=acc["headers"])
    assert r.status_code == 200, r.text
    created = r.json()["data"]
    assert created["key"] == "conference_travel"
    assert created["built_in"] is False
    assert created["id"] is not None

    lst = client.get("/api/expenses/categories", headers=acc["headers"]).json()["data"]
    custom = [c for c in lst if c["key"] == "conference_travel"]
    assert len(custom) == 1
    assert custom[0]["built_in"] is False
    assert custom[0]["name_he"] == "נסיעות לכנסים"
    assert custom[0]["keywords"] == ["כנס", "conference"]


def test_create_category_rejects_duplicate_key_in_same_org(client, acc):
    client.post("/api/expenses/categories", json={
        "key": "dup_card", "name_he": "כרטיס א",
    }, headers=acc["headers"])
    r = client.post("/api/expenses/categories", json={
        "key": "dup_card", "name_he": "כרטיס ב",
    }, headers=acc["headers"])
    assert r.status_code == 400, r.text


def test_create_category_rejects_built_in_key_collision(client, acc):
    r = client.post("/api/expenses/categories", json={
        "key": "rent", "name_he": "שכירות מחדש",
    }, headers=acc["headers"])
    assert r.status_code == 400, r.text


def test_custom_category_is_org_scoped(client, acc):
    reg2 = client.post("/api/admin/auth/register", json={
        "email": "catother@example.com", "password": "secret123", "full_name": "Cat Other",
    })
    other_headers = {"Authorization": f"Bearer {reg2.json()['access_token']}"}

    client.post("/api/expenses/categories", json={
        "key": "org_a_only_card", "name_he": "כרטיס רק לארגון א",
    }, headers=acc["headers"])

    other_list = client.get("/api/expenses/categories", headers=other_headers).json()["data"]
    assert not any(c["key"] == "org_a_only_card" for c in other_list)


def test_org_b_cannot_delete_org_a_category(client, acc):
    reg3 = client.post("/api/admin/auth/register", json={
        "email": "catother2@example.com", "password": "secret123", "full_name": "Cat Other 2",
    })
    other_headers = {"Authorization": f"Bearer {reg3.json()['access_token']}"}

    created = client.post("/api/expenses/categories", json={
        "key": "org_a_protected_card", "name_he": "כרטיס מוגן",
    }, headers=acc["headers"]).json()["data"]

    d = client.delete(f"/api/expenses/categories/{created['id']}", headers=other_headers)
    assert d.status_code == 404, d.text

    # עדיין קיים בארגון המקורי
    lst = client.get("/api/expenses/categories", headers=acc["headers"]).json()["data"]
    assert any(c["key"] == "org_a_protected_card" for c in lst)


def test_delete_unused_category_succeeds(client, acc):
    created = client.post("/api/expenses/categories", json={
        "key": "throwaway_card", "name_he": "כרטיס חד פעמי",
    }, headers=acc["headers"]).json()["data"]

    d = client.delete(f"/api/expenses/categories/{created['id']}", headers=acc["headers"])
    assert d.status_code == 200, d.text

    lst = client.get("/api/expenses/categories", headers=acc["headers"]).json()["data"]
    assert not any(c["key"] == "throwaway_card" for c in lst)


def test_delete_category_in_use_returns_409_with_count(client, acc):
    created = client.post("/api/expenses/categories", json={
        "key": "used_card", "name_he": "כרטיס בשימוש",
    }, headers=acc["headers"]).json()["data"]

    client.post("/api/expenses", json={
        "supplier_name": "ספק כלשהו", "amount": 100,
        "expense_date": date.today().isoformat(), "category": "used_card",
    }, headers=acc["headers"])

    d = client.delete(f"/api/expenses/categories/{created['id']}", headers=acc["headers"])
    assert d.status_code == 409, d.text
    assert d.json()["detail"]["count"] >= 1

    # עדיין קיים — לא נמחק
    lst = client.get("/api/expenses/categories", headers=acc["headers"]).json()["data"]
    assert any(c["key"] == "used_card" for c in lst)


def test_empty_keywords_are_stripped_on_create(fresh_org):
    """מילת-מפתח ריקה ("") תופסת כל טקסט וחוטפת את הסיווג — מסוננת ביצירה."""
    from cfo.database import SessionLocal
    from cfo.services.expense_category_service import create_category

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cat = create_category(
            db, org_id, key="hijack_test", name_he="בדיקת חטיפה",
            keywords=["", "  ", "דלק", " חניה "],
        )
    finally:
        db.close()
    assert cat["keywords"] == ["דלק", "חניה"]
