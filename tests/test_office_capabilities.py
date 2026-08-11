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
