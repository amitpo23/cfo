"""יכולות ברמת חברת המשרד — מה שנפתח עם מפתח ה-office.

עד 11/08/2026 היו רק הרשאות פר-תיק. מפתח חברת המשרד (CompanyID
844329067) פותח פעולות שאין להן משמעות ברמת תיק בודד: מכסות החשבון,
פרטי חברות בפורטל, ורשימת מסמכים חוצת-תיקים.

הכלל: פעולה ברמת משרד בלי מפתח משרד **נכשלת בגלוי** ואינה נופלת חזרה
למפתח של תיק בודד — נפילה כזו הייתה שולחת קריאה עם הרשאה שגויה, או
מחזירה נתונים של תיק אחד כאילו הם של המשרד כולו.
"""
import pytest

from cfo.services.office_capabilities import (
    OFFICE_TASKS,
    OfficeCredentialsMissing,
    office_credentials,
    office_tasks_status,
)


def test_office_tasks_cover_what_the_key_actually_unlocks():
    for task in ("account_quotas", "company_details", "office_documents"):
        assert task in OFFICE_TASKS


def test_every_office_task_declares_its_endpoint_and_write_status():
    for name, task in OFFICE_TASKS.items():
        assert task["capability"], name
        assert isinstance(task["writes"], bool), name
        assert task["description_he"], name


def test_credentials_resolve_when_configured(monkeypatch):
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_office_api_key", "office-key", raising=False)
    monkeypatch.setattr(settings, "sumit_office_company_id", "844329067", raising=False)

    creds = office_credentials()

    assert creds["company_id"] == "844329067"
    assert creds["api_key"] == "office-key"


def test_missing_office_key_fails_loudly_instead_of_using_the_org_key(monkeypatch):
    """זו הבדיקה המרכזית: אסור שהיעדר מפתח משרד ייפול חזרה ל-
    `sumit_api_key`, שהוא מפתח של תיק לקוח בודד."""
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_office_api_key", None, raising=False)
    monkeypatch.setattr(settings, "sumit_office_company_id", None, raising=False)
    monkeypatch.setattr(settings, "sumit_api_key", "org-level-key", raising=False)

    with pytest.raises(OfficeCredentialsMissing):
        office_credentials()


def test_partial_configuration_is_also_a_failure(monkeypatch):
    """מפתח בלי CompanyID אינו שימושי — עדיף להיכשל מאשר לשלוח קריאה
    חלקית שתיכשל אצל הספק בהודעה עמומה."""
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_office_api_key", "office-key", raising=False)
    monkeypatch.setattr(settings, "sumit_office_company_id", None, raising=False)

    with pytest.raises(OfficeCredentialsMissing):
        office_credentials()


def test_status_reports_availability_without_leaking_the_key(monkeypatch):
    """הסטטוס מגיע למסכי אדמין וללוגים — הוא מדווח זמינות, לא סוד."""
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_office_api_key", "office-key", raising=False)
    monkeypatch.setattr(settings, "sumit_office_company_id", "844329067", raising=False)

    status = office_tasks_status()

    assert status["configured"] is True
    assert status["company_id"] == "844329067"
    assert "office-key" not in str(status)
    assert all(t["executable"] for t in status["tasks"])


def test_status_marks_everything_blocked_when_not_configured(monkeypatch):
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_office_api_key", None, raising=False)
    monkeypatch.setattr(settings, "sumit_office_company_id", None, raising=False)

    status = office_tasks_status()

    assert status["configured"] is False
    assert not any(t["executable"] for t in status["tasks"])
    assert all(t["blocked_by"] for t in status["tasks"])


# ---------------------------------------------------------------------- #
# כיסוי מלא — נמצא חסר בסקירה 11/08/2026
# ---------------------------------------------------------------------- #
def test_map_covers_every_office_level_endpoint_the_client_implements():
    """הגרסה הראשונה מיפתה 3 יכולות מתוך 9 שהקליינט כבר מממש.
    השער הזה מונע חזרה על כך: כל endpoint ברמת המשרד חייב להיות במפה,
    אחרת מושקו יענה "אין לי יכולת" על משהו שקיים."""
    expected = {
        "account_quotas", "company_details", "office_documents",
        "create_client_company", "update_client_company", "install_applications",
        "grant_permission", "revoke_permission", "create_user", "login_redirect",
    }
    assert set(OFFICE_TASKS) == expected


def test_write_operations_are_marked_and_require_approval():
    """יצירת ארגון, הענקת הרשאה ויצירת משתמש הן פעולות בלתי-הפיכות
    אצל הספק — אסור שיסווגו כקריאה."""
    for name in ("create_client_company", "grant_permission", "revoke_permission",
                 "create_user", "install_applications", "update_client_company"):
        assert OFFICE_TASKS[name]["writes"] is True, name


def test_replacing_an_accounting_office_requires_removing_the_old_one_first():
    """כלל מרכז הידע: 'לא ניתן להעניק הרשאה לשני משרדי רו"ח בו-זמנית —
    חובה להסיר את הישן לפני הוספת החדש.' מי שיקרא את המפה חייב לדעת."""
    grant = OFFICE_TASKS["grant_permission"]
    assert "warning_he" in grant
    assert "להסיר" in grant["warning_he"]
