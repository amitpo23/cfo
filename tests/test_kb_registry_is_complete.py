"""כל קובץ במרכז הידע חייב להיות רשום — אחרת מושקו לא רואה אותו.

`kb_loader` מחזיק **רשימה מפורשת** של קבצים, לא glob. קובץ שנוסף
לתיקייה ולא נרשם ב-`kb_loader.py` **אינו קיים** מבחינת מושקו: הוא לא
יופיע באינדקס ולא יוחזר בחיפוש.

זה נכשל בפועל ב-16/08/2026: חמישה מסמכי תהליך (07–11) נכתבו ל-
`docs/bookkeeper_kb/`, `test_kb_loader.py` המשיך לעבור — כי הוא בודק
את הקבצים הרשומים — ומושקו לא ראה מהם דבר.

כתיבת ידע שאיש אינו קורא היא הצורה הגרועה ביותר של ידע חסר: היא
נראית כמו עבודה שהושלמה.
"""
from pathlib import Path

import pytest

from cfo.services.kb_loader import KB_CENTERS, kb_index, kb_search


REPO = Path(__file__).resolve().parents[1]


def _registered_filenames(dir_name: str) -> set[str]:
    for center in KB_CENTERS:
        if center.dir_name == dir_name:
            return {f.filename for f in center.files}
    raise AssertionError(f"מרכז ידע לא רשום: {dir_name!r}")


@pytest.mark.parametrize("dir_name", ["bookkeeper_kb", "sumit_help_kb"])
def test_every_markdown_file_on_disk_is_registered(dir_name):
    """הבדיקה המרכזית: אין קובץ בתיקייה שאינו ברשימה."""
    on_disk = {p.name for p in (REPO / "docs" / dir_name).glob("*.md")}
    registered = _registered_filenames(dir_name)

    missing = sorted(on_disk - registered)

    assert not missing, (
        f"קבצים בתיקייה שאינם רשומים ב-kb_loader — מושקו לא יראה אותם: {missing}"
    )


@pytest.mark.parametrize("dir_name", ["bookkeeper_kb", "sumit_help_kb"])
def test_no_registered_file_is_missing_from_disk(dir_name):
    """הכיוון ההפוך: רישום שמצביע לקובץ שאינו קיים מייצר honest-null
    שקט במקום תשובה."""
    on_disk = {p.name for p in (REPO / "docs" / dir_name).glob("*.md")}
    registered = _registered_filenames(dir_name)

    phantom = sorted(registered - on_disk)

    assert not phantom, f"רישום מצביע לקבצים שאינם קיימים: {phantom}"


# שאלות כפי שבעל עסק ישאל אותן בפועל — לא מילה בודדת. השער בודק
# **נוכחות** בתוצאות ולא מקום ראשון: תשובה שמצרפת גם את הנוהל הכללי
# וגם את המסמך הספציפי היא תשובה טובה, כל עוד הספציפי נמצא שם.
PROCESS_TOPICS = {
    "מנות פתוחות": "07-books-batches.md",
    "זיהוי כפילויות": "08-duplicate-detection.md",
    "מאזן בוחן": "09-sumit-operations-map.md",
    "סגירת חודש": "10-month-end-close.md",
    "createbatch": "11-updating-sumit.md",
    "תאריך העלאה": "11-updating-sumit.md",
}


@pytest.mark.parametrize("query,expected_file", sorted(PROCESS_TOPICS.items()))
def test_moshko_can_find_each_process_document(query, expected_file):
    """שער תוצאה, לא שער רישום: חיפוש בנושא חייב להחזיר את המסמך שלו.

    רישום לבדו אינו מספיק — אם הנוסח בקובץ אינו תואם לשאלה שבעל עסק
    ישאל, המסמך רשום ובלתי-נגיש."""
    results = kb_search(query).get("results", [])
    files = {r.get("file") for r in results}

    assert expected_file in files, (
        f'חיפוש "{query}" לא החזיר את {expected_file}. הוחזרו: {sorted(files)}'
    )


def test_the_index_lists_the_process_documents():
    index = str(kb_index())

    for filename in PROCESS_TOPICS.values():
        assert filename in index, f"{filename} אינו באינדקס שמושקו רואה"
