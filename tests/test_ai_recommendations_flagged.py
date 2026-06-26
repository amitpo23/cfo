"""פאזה 2 — המלצות ה-AI הקשיחות מסומנות ביושר כ-illustrative (לא data-derived),
כדי שלא יוצגו כאילו נותחו מנתוני העסק. מימוש אמיתי → פאזה 11 (תכנון/ייעוץ).
"""
from cfo.services.ai_analytics_service import AdvancedAIService


def test_recommendations_are_flagged_illustrative(client, owner):
    from cfo.database import SessionLocal
    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=owner["user"]["organization_id"])
        recs = svc.get_ai_recommendations()
        assert recs, "expected example recommendations"
        assert all(getattr(r, "is_illustrative", False) for r in recs)
    finally:
        db.close()
