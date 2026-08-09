"""תמונת ארגון — לתשאל ולבדוק תיק אחד, בלי לחכות לפיצול המסדים.

הנתונים כבר org-scoped, ולכן אפשר לשאול "מה מצב התיק הזה" כבר היום.
כשארגון יעבור למסד ייעודי, אותה פונקציה תעבוד בלי שינוי — היא ניגשת
דרך `tenant_routing.session_for`, שיודע לאן לפנות.
"""
from cfo.services.org_snapshot import list_organizations, org_snapshot


def test_snapshot_reports_the_org_identity_and_where_its_data_lives(fresh_org):
    org_id = fresh_org()["org_id"]

    snap = org_snapshot(org_id)

    assert snap["organization_id"] == org_id
    assert snap["name"]
    # `shared` כל עוד הארגון לא פוצל; `dedicated` אחרי — כך רואים מיד
    # מאיפה המספרים הגיעו.
    assert snap["database"] in {"shared", "dedicated"}


def test_snapshot_counts_the_business_data(fresh_org):
    org_id = fresh_org()["org_id"]

    snap = org_snapshot(org_id)

    for key in ("expenses", "invoices", "bills", "bank_transactions", "contacts"):
        assert key in snap["data"]
        assert isinstance(snap["data"][key], int)


def test_snapshot_reports_provider_connections_with_staleness(fresh_org):
    """לכל ספק: האם מחובר, באיזה סטטוס, ולפני כמה זמן סונכרן.
    זמן הוא העיקר — חיבור `active` שלא סונכרן שבועיים אינו תואם."""
    org_id = fresh_org()["org_id"]

    snap = org_snapshot(org_id)

    assert "providers" in snap
    for provider in ("sumit", "open_finance"):
        assert provider in snap["providers"]
        entry = snap["providers"][provider]
        assert "connected" in entry
        assert "status" in entry
        assert "hours_since_sync" in entry


def test_unconnected_provider_is_honest_null_not_zero(fresh_org):
    """ספק שאינו מחובר מדווח None ולא 0 שעות. 0 היה נקרא
    כ"סונכרן ממש עכשיו" — היפוך מוחלט של המשמעות."""
    org_id = fresh_org()["org_id"]

    snap = org_snapshot(org_id)

    sumit = snap["providers"]["sumit"]
    assert sumit["connected"] is False
    assert sumit["hours_since_sync"] is None
    assert sumit["status"] is None


def test_snapshot_flags_a_stale_or_missing_provider(fresh_org):
    """הדגלים הם התשובה ל"האם התיק תואם" — לא צריך לפרש מספרים."""
    org_id = fresh_org()["org_id"]

    snap = org_snapshot(org_id)

    assert isinstance(snap["issues"], list)
    assert any("sumit" in issue.lower() for issue in snap["issues"])


def test_missing_organization_returns_none_rather_than_an_empty_shell(fresh_org):
    assert org_snapshot(999_999) is None


def test_list_organizations_returns_every_org_with_its_headline_numbers(fresh_org):
    org_id = fresh_org()["org_id"]

    rows = list_organizations()

    assert any(row["organization_id"] == org_id for row in rows)
    for row in rows:
        assert "name" in row and "issues" in row


def test_snapshot_flags_zero_sum_drafts_as_a_parity_gap(fresh_org):
    """טיוטה בסכום 0 היא חוסר-התאמה מול SUMIT במובן המדויק: המסמך קיים
    בספק, נמשך לרצף, אבל הסכום לא הגיע. כל דוח שנשען על expenses.total
    מדווח חסר. זה חייב להופיע כדגל ולא להיבלע בספירה הכוללת."""
    org_id = fresh_org()["org_id"]

    snap = org_snapshot(org_id)

    assert "zero_sum_expenses" in snap["data"]
    assert isinstance(snap["data"]["zero_sum_expenses"], int)


def test_snapshot_counts_supplier_bills(fresh_org):
    """1,296 חשבוניות ספק בפרוד. תיק ש"תואם ל-SUMIT" ומשמיט אותן
    אינו תואם."""
    org_id = fresh_org()["org_id"]

    assert "bills" in org_snapshot(org_id)["data"]
