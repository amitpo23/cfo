"""אינדקס ה-KB ב-DB — ושהוא באמת זה שמושקו שואל.

**ההנחיה (17/08/2026).** "בבסיס נתונים שלנו תכניס אינדוקס ו-RAG לצרכי
תצוגה ולמושקו".

**מה נבנה ומה לא.** האחזור לקסיקלי: `tsvector(simple)` + `pg_trgm`. **לא**
pgvector, אף ש-Neon מציעה אותו — ל-Anthropic אין API של embeddings, ספק
embeddings נוסף הוא עלות שלא אושרה, ועמודת embedding ריקה בלי כותב נקראת
כיכולת קיימת בזמן שאינה. אם ייבחר ספק — זו revision נפרדת.

PostgreSQL אינו מכיל תצורת חיפוש-טקסט לעברית (אומת מול פרוד: 0 תצורות),
ולכן `simple` + טריגרמים ולא stemmer.

**הכשל שהטסטים כאן נועדו למנוע.** פעמיים היום נמצא שער שנכתב, נבדק, עבר
— ולא היה על המסלול: `getpdf` היה בלתי-מגודר בזמן ש-`getdetails` גודר,
ומסמכי KB 07–11 נכתבו ולא נרשמו בזמן ש-`test_kb_loader.py` המשיך לעבור.
אינדקס שאינו זה שמושקו שואל הוא בדיוק אותו כשל, ולכן טסט החיווט נכתב
**ראשון**.

**מקור אמת יחיד.** האינדקס נזרע מ-`KB_CENTERS` ולא מרישום שני. שער
דו-כיווני: כל קובץ רשום מיוצג באינדקס, ואין באינדקס מה שאינו רשום.
"""
import pytest

from cfo.database import SessionLocal
from cfo.services import kb_loader


# ==================================================================== #
# החיווט — הראשון שנכתב
# ==================================================================== #
@pytest.mark.asyncio
async def test_moshko_lookup_reaches_the_index(client, monkeypatch):
    """`_kb_lookup` הוא מה שמושקו קורא. אם האינדקס אינו על המסלול הזה,
    בנינו מערכת חיפוש שנייה שאיש אינו משתמש בה."""
    from cfo.services import ai_chat_tools, kb_index

    called = {}

    def _spy(query, **kwargs):
        called["query"] = query
        return {"available": True, "results": [], "source": "index"}

    monkeypatch.setattr(kb_index, "search", _spy)

    await ai_chat_tools._kb_lookup(None, 1, query="ניכוי תשומות")

    assert called.get("query") == "ניכוי תשומות", (
        "חיפוש הידע של מושקו אינו מגיע לאינדקס"
    )


# ==================================================================== #
# השער הדו-כיווני מול הרישום
# ==================================================================== #
def test_every_registered_kb_file_is_represented_in_the_index(client):
    """כיוון א': קובץ רשום שלא נזרע הוא ידע בלתי-נראה — בדיוק מה שקרה
    למסמכים 07–11."""
    from cfo.services import kb_index

    db = SessionLocal()
    kb_index.reindex(db)

    indexed = kb_index.indexed_files(db)
    registered = {
        (c.key, f.filename) for c in kb_loader.KB_CENTERS for f in c.files
    }

    missing = registered - indexed
    assert not missing, f"קבצים רשומים שאינם באינדקס: {sorted(missing)}"


def test_the_index_holds_nothing_that_is_not_registered(client):
    """כיוון ב': שורה יתומה מבטיחה ידע שאיש אינו מתחזק. קורה כשקובץ
    יוצא מהרישום והאינדקס לא נוקה."""
    from cfo.services import kb_index

    db = SessionLocal()
    kb_index.reindex(db)

    indexed = kb_index.indexed_files(db)
    registered = {
        (c.key, f.filename) for c in kb_loader.KB_CENTERS for f in c.files
    }

    assert not (indexed - registered), f"שורות יתומות: {sorted(indexed - registered)}"


def test_reindexing_twice_does_not_duplicate(client):
    """הזריעה רצה מחדש בכל פריסה. בלי upsert האינדקס היה גדל בכל דיפלוי
    וכל חיפוש היה מחזיר את אותה פסקה N פעמים."""
    from cfo.services import kb_index

    db = SessionLocal()
    first = kb_index.reindex(db)["chunks"]
    second = kb_index.reindex(db)["chunks"]

    assert first == second, f"מספר הקטעים השתנה: {first} → {second}"


# ==================================================================== #
# האחזור עצמו
# ==================================================================== #
def test_a_hebrew_query_finds_its_section(client):
    """עברית היא המבחן האמיתי: אין ל-PostgreSQL stemmer עברי, ולכן
    האחזור נשען על טריגרמים והתאמת תחילית-מילה."""
    from cfo.services import kb_index

    db = SessionLocal()
    kb_index.reindex(db)

    res = kb_index.search("מאזן בוחן", db=db)

    assert res["available"] is True
    assert res["results"], "שאילתה עברית בסיסית לא החזירה דבר"


def test_a_query_with_no_match_is_honest_rather_than_noisy(client):
    """honest-null: אין התאמה ⇒ רשימה ריקה, לא הקטע הכי פחות גרוע.
    תוצאה לא-רלוונטית שמוצגת כידע גרועה מ'לא נמצא'."""
    from cfo.services import kb_index

    db = SessionLocal()
    kb_index.reindex(db)

    res = kb_index.search("זזזקוואלופין תרנגולת קוונטית", db=db)

    assert res["results"] == []


def test_search_falls_back_when_the_index_is_empty(client):
    """הזריעה עשויה לא לרוץ עדיין בסביבה חדשה. אחזור שמחזיר ריק במקום
    ליפול חזרה לקבצים היה מכבה את הידע של מושקו בשקט."""
    from cfo.services import kb_index

    db = SessionLocal()
    kb_index.clear(db)

    res = kb_index.search("מאזן בוחן", db=db)

    assert res["results"], "אין fallback לקבצים כשהאינדקס ריק"
    assert res.get("source") == "files"
