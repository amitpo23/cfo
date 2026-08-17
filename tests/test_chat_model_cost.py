"""ברירת המחדל של מודל הצ'אט חייבת להיות הזולה ביותר.

הבעלים ביקש ב-17/08/2026 שמושקו ירוץ על המודל הזול ביותר. באותו רגע
יתרת החשבון הייתה **$1.92** — סכום שמספיק לעשרות הודעות ב-Haiku
ולמעט מאוד ב-Opus.

זה אינו רק חיסכון: חשבון שנגמר באמצע יום עבודה משבית את מושקו לגמרי,
בלי אזהרה ובלי דרך לדעת מראש. ברירת מחדל יקרה היא סיכון זמינות.

ההגדרה נשארת משתנה סביבה — אפשר להעלות מודל למשימה שדורשת זאת, אבל
**ברירת המחדל בקוד** היא הזולה.
"""
from cfo.config import Settings


CHEAPEST_MODEL = "claude-haiku-4-5-20251001"

# מדורג מהיקר לזול. כל אחד מאלה כברירת מחדל הוא רגרסיית עלות.
MORE_EXPENSIVE = ("claude-opus-5", "claude-opus-4-8", "claude-sonnet-5",
                  "claude-fable-5")


def test_the_default_chat_model_is_the_cheapest():
    assert Settings().ai_chat_model == CHEAPEST_MODEL


def test_no_expensive_model_is_the_default():
    """שער מפורש: אם מישהו יחזיר את sonnet/opus כברירת מחדל, זה ייתפס."""
    assert Settings().ai_chat_model not in MORE_EXPENSIVE


def test_the_model_stays_configurable(monkeypatch):
    """הזול הוא ברירת מחדל, לא כלא. משימה שדורשת מודל חזק יכולה
    להעלות אותו דרך הסביבה."""
    monkeypatch.setenv("AI_CHAT_MODEL", "claude-sonnet-5")

    assert Settings().ai_chat_model == "claude-sonnet-5"


def test_the_service_reads_the_setting_and_does_not_hardcode():
    """מודל קשיח בקוד היה עוקף את ההגדרה בשקט."""
    import inspect

    from cfo.services import ai_chat_service

    source = inspect.getsource(ai_chat_service)
    hardcoded = [
        line.strip() for line in source.splitlines()
        if "model=" in line and "claude-" in line
    ]

    assert not hardcoded, f"מודל קשיח בקוד: {hardcoded}"
