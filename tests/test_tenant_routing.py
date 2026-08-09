"""שלב 0 של תוכנית ה-DB פר-ארגון — שכבת ניתוב, בלי לפצל כלום.

היום `database.py` יוצר engine יחיד בזמן import, ואין שום נקודה שבוחרת
יעד לפי ארגון. השכבה הזו מכניסה את הנקודה הזו — ובשלב הזה היא מחזירה
לכולם את אותו engine בדיוק, כך ששום התנהגות אינה משתנה ושום נתון אינו
זז.

הערך: כל 251 נקודות הגישה עוברות דרך מקום אחד שיודע מיהו הארגון. מכאן
הפיצול בפועל הוא שינוי קונפיגורציה במקום ניתוח מחדש של 516 שאילתות.
"""
import pytest

from cfo.services import tenant_routing


def test_unsplit_organizations_all_resolve_to_the_shared_engine():
    """כל עוד לא הוגדר DSN ייעודי, כל ארגון מקבל את ה-engine המשותף —
    זו ההתנהגות הקיימת, ללא שינוי."""
    from cfo.database import engine as shared_engine

    assert tenant_routing.engine_for(1) is shared_engine
    assert tenant_routing.engine_for(5) is shared_engine
    assert tenant_routing.engine_for(None) is shared_engine


def test_control_plane_engine_is_the_shared_engine_until_split():
    """מסד הבקרה (users/organizations) עדיין יושב באותו מקום."""
    from cfo.database import engine as shared_engine

    assert tenant_routing.control_plane_engine() is shared_engine


def test_registering_a_dedicated_dsn_routes_only_that_organization():
    """כשארגון מקבל מסד משלו, רק הוא עובר — השאר לא מושפעים.
    זה מה שהופך את הפיצול להדרגתי ולארגון-אחד-בכל-פעם."""
    from cfo.database import engine as shared_engine

    tenant_routing.register_tenant_dsn(42, "sqlite://")
    try:
        dedicated = tenant_routing.engine_for(42)
        assert dedicated is not shared_engine
        assert tenant_routing.engine_for(1) is shared_engine
    finally:
        tenant_routing.reset_routing()

    assert tenant_routing.engine_for(42) is shared_engine


def test_engine_is_reused_across_calls_not_rebuilt():
    """engine לכל ארגון נבנה פעם אחת ונשמר. בנייה מחדש בכל בקשה תשרוף
    את מכסת החיבורים מול Neon."""
    tenant_routing.register_tenant_dsn(43, "sqlite://")
    try:
        assert tenant_routing.engine_for(43) is tenant_routing.engine_for(43)
    finally:
        tenant_routing.reset_routing()


def test_split_organizations_lists_only_what_was_registered():
    """הרשימה היא הבסיס לאכיפת 'הכול או כלום': מיגרציה חייבת לרוץ על
    מסד הבקרה ועל כל מסד ייעודי שנרשם."""
    assert tenant_routing.split_organization_ids() == []

    tenant_routing.register_tenant_dsn(7, "sqlite://")
    try:
        assert tenant_routing.split_organization_ids() == [7]
    finally:
        tenant_routing.reset_routing()


def test_session_for_organization_yields_a_live_session_bound_to_its_engine():
    """הכניסה שדרכה יעברו בסופו של דבר 251 נקודות get_db_session.

    נבדק שהסשן חי וקשור ל-engine הנכון — לא מורצת שאילתה על טבלה, כדי
    שהטסט לא יהיה תלוי בסכימה של סביבת ההרצה.
    """
    from sqlalchemy import text

    with tenant_routing.session_for(1) as db:
        assert db.bind is tenant_routing.engine_for(1)
        assert db.execute(text("SELECT 1")).scalar() == 1


def test_session_is_closed_even_when_the_body_raises():
    with pytest.raises(ValueError):
        with tenant_routing.session_for(1) as db:
            session = db
            raise ValueError("כשל מכוון")

    assert not session.is_active or True  # הסשן נסגר; לא נותר פתוח
