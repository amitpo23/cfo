"""שער המפתח חייב לקרוא את אותם אישורים שהסנכרון באמת משתמש בהם.

**הרגרסיה (נמדדה בפרוד 18/08/2026).** `_per_key_daily_gate` נפרס ב-17/08.
למחרת בבוקר:

    org 1 · sumit · סונכרן 18/08 01:30   ← רץ
    org 2 · sumit · סונכרן 17/08 01:31   ← דולג
    org 5 · sumit · סונכרן 17/08 01:31   ← דולג

הסיבה: `_resolve_sumit_key` קרא `organizations.api_credentials`, שהוא
`null` בפרוד לכל הארגונים. אישורי SUMIT האמיתיים יושבים מוצפנים ב-
`integration_connections.credentials_encrypted` — וזה מה ש-
`get_connector_for_org` (הנתיב שהסנכרון באמת עובר בו) קורא.

לכן השער החזיר `None`, נכשל-סגור כמתוכנן, ודילג על **כל ארגון שאינו
org1** — שרק לו יש נפילה לאישורי סביבה.

**הלקח:** שער שפותר מפתח ממקור שונה מזה שהריצה משתמשת בו אינו מגן —
הוא או חוסם את הכול או חוסם כלום. הטסטים כאן אוכפים שהמקורות זהים.
"""
import inspect

from cfo.api.routes import cron
from cfo.services import sync_engine


def test_the_gate_reads_the_encrypted_connection_credentials():
    """המקור היחיד הנכון. `organizations.api_credentials` הוא `null`
    בפרוד, ולכן קריאה ממנו שקולה ל'אין מפתח' לכל הארגונים."""
    src = inspect.getsource(cron._resolve_sumit_key)

    assert "credentials_encrypted" in src or "decrypt_credentials" in src, (
        "השער אינו קורא את האישורים המוצפנים — יחזיר None לכל ארגון "
        "שאינו org1 וידלג עליו בשקט"
    )


def test_the_gate_and_the_sync_share_the_same_source():
    """שני המסלולים חייבים לקרוא מאותה טבלה. אם הם מתפצלים, השער תובע
    חלון על מפתח אחד בזמן שהריצה שולחת באחר."""
    gate = inspect.getsource(cron._resolve_sumit_key)
    runner = inspect.getsource(sync_engine.get_connector_for_org)

    for marker in ("IntegrationConnection", "decrypt_credentials"):
        assert marker in gate, f"{marker} חסר בשער"
        assert marker in runner, f"{marker} חסר בנתיב הסנכרון"


def test_the_env_fallback_stays_restricted_to_org_one():
    """אישורי סביבה שייכים לארגון 1 בלבד. נפילה רחבה יותר הייתה שולחת
    קריאות של תיק אחד בשם תיק אחר."""
    src = inspect.getsource(cron._resolve_sumit_key)

    assert "org_id == 1" in src or "organization_id == 1" in src


def test_a_configured_org_resolves_a_key(client, monkeypatch):
    """שער התנהגותי: ארגון עם חיבור פעיל ואישורים מוצפנים חייב לקבל
    מפתח — אחרת הוא ידולג כל בוקר בלי שאיש ישים לב."""
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    db = SessionLocal()
    org_id = 4242
    db.add(IntegrationConnection(
        organization_id=org_id, source="sumit", status="active",
        credentials_encrypted=encrypt_credentials(
            {"api_key": "org-own-key-abc123", "company_id": "999"}
        ),
    ))
    db.commit()

    resolved = cron._resolve_sumit_key(db, org_id)

    assert resolved == "org-own-key-abc123"


def test_an_org_without_any_connection_resolves_nothing(client):
    """שער נגדי: ארגון בלי חיבור אינו מקבל מפתח שאול. fail-closed נשאר."""
    from cfo.database import SessionLocal

    db = SessionLocal()

    assert cron._resolve_sumit_key(db, 987654) is None
