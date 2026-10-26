"""מוכנות מושקו לעבודה חיה — בדיקה offline שמחזירה בוליאנים בלבד.

עונה על "מה חסר כדי שמושקו יענה בוואטסאפ/טלגרם וישלח דוחות", מתוך ההגדרות
שה-runtime טוען בפועל. אין כאן קריאת רשת (לא Meta, לא Telegram, לא
Anthropic), ואף ערך סודי לא מוחזר או נרשם ללוג: רק "מוגדר / לא מוגדר".
האם הטוקן עצמו תקף — זה נבדק רק בשיחה אמיתית, לא כאן.
"""
from __future__ import annotations

from ..config import settings


def _present(value) -> bool:
    return bool(value and str(value).strip())


def moshko_readiness() -> dict:
    llm_key = _present(settings.anthropic_api_key)
    whatsapp = {
        "access_token": _present(settings.whatsapp_access_token),
        "phone_number_id": _present(settings.whatsapp_phone_number_id),
        "app_secret": _present(settings.whatsapp_app_secret),
        "verify_token": _present(settings.whatsapp_verify_token),
    }
    whatsapp["ready"] = all(whatsapp.values())
    telegram = {
        "bot_token": _present(settings.telegram_bot_token),
        "webhook_secret": _present(settings.telegram_webhook_secret),
    }
    telegram["ready"] = all(telegram.values())

    from .cash_position_pdf import hebrew_font_paths

    return {
        "llm": {"api_key_configured": llm_key},
        "whatsapp": whatsapp,
        "telegram": telegram,
        # Proactive WhatsApp pushes (owner decision 2026-10-23: off by default).
        # A reply inside a conversation the user opened — including a report
        # PDF — is not a push and does not depend on this flag.
        "push": {"whatsapp_push_enabled": bool(settings.whatsapp_push_enabled)},
        "report_pdf": {"hebrew_font_available": hebrew_font_paths() is not None},
        "ready_to_chat": llm_key and (whatsapp["ready"] or telegram["ready"]),
    }
