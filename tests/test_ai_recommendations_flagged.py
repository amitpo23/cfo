"""היסטוריה: פאזה 2 סימנה את ההמלצות הקשיחות כ-illustrative; 20/08/2026
הבעלים הנחה "אפס פיברוק" — ההמלצות-להמחשה הוסרו כליל והוחלפו בסירוב
honest-null (ראה test_no_fabricated_analytics.py). הטסט הזה מקבע שהן
לא יחזרו.
"""
import pytest

from cfo.services.ai_analytics_service import (
    AdvancedAIService,
    AIAnalyticsNotConfiguredError,
)


def test_illustrative_recommendations_are_gone_for_good(client, owner):
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=owner["user"]["organization_id"])
        with pytest.raises(AIAnalyticsNotConfiguredError):
            svc.get_ai_recommendations()
    finally:
        db.close()
