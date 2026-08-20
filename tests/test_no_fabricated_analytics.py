"""הסרת פיברוקים (חקירת 20/08, "מיידי"): אפס מספרים מומצאים בטאבים.

שני המקורות שנמצאו:
1. `get_ai_recommendations` — 5 המלצות קשיחות עם שקלים מומצאים
   (₪25,000 / ₪30,000 / roi=9999) שהמסך רינדר כאילו חושבו מהתיק.
2. `compare_to_industry` — "ממוצע ענף" שהוא קבוע קשיח בקוד; הפרמטר
   `industry` כלל לא בשימוש. אין שום נתוני ענף מאחורי המספר.

honest-null: עדיף "לא מוגדר" מפורש ממספר שנשמע אמיתי.
"""
import pytest

from cfo.services.ai_analytics_service import (
    AdvancedAIService,
    AIAnalyticsNotConfiguredError,
)
from cfo.services.kpi_service import KPIService


def test_ai_recommendations_refuse_instead_of_fabricating(client, owner):
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=owner["user"]["organization_id"])
        with pytest.raises(AIAnalyticsNotConfiguredError):
            svc.get_ai_recommendations()
    finally:
        db.close()


def test_industry_comparison_is_honest_about_missing_source(client, owner):
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        svc = KPIService(db, organization_id=owner["user"]["organization_id"])
        result = svc.compare_to_industry()
        assert result["available"] is False
        assert "reason" in result
        assert "comparison" not in result or result["comparison"] == []
    finally:
        db.close()
