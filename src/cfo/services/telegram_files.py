"""הורדת קובץ טלגרם (getFile + הורדת בייטים) עבור מסלול קליטת-קבלה בשיחה
(חבילה A, תכנית מושקו). קובץ נפרד מ-channel_gateway.py (שייך לחבילה B) —
זהו עוזר הורדה צר המשמש רק את telegram_webhook.py לצילום/PDF שנשלח לצ'אט.
"""
from __future__ import annotations

from typing import Optional

import httpx

from ..config import settings

# מגבלת גודל הגיונית לצילום/PDF של קבלה — מונעת הורדה בלתי-מוגבלת.
TELEGRAM_FILE_MAX_BYTES = 20 * 1024 * 1024  # 20MB
_TIMEOUT = httpx.Timeout(20.0)


class TelegramFileError(Exception):
    """שגיאה בפתרון/הורדת קובץ טלגרם (getFile נכשל, קובץ גדול מדי וכו')."""


async def download_telegram_file(file_id: str, *, token: Optional[str] = None) -> bytes:
    """פותר file_id -> file_path דרך getFile, ואז מוריד את בייטי הקובץ
    מ-CDN הקבצים של טלגרם. אוכף מגבלת גודל, הן מה-file_size שמוחזר מ-
    getFile (כשיש) והן על הבייטים שהתקבלו בפועל."""
    bot_token = token if token is not None else settings.telegram_bot_token
    if not bot_token:
        raise TelegramFileError("טוקן טלגרם לא מוגדר")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": file_id},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramFileError(f"getFile נכשל: {exc}") from exc

        data = resp.json()
        if not data.get("ok"):
            raise TelegramFileError(f"getFile נכשל: {data.get('description', 'שגיאה לא ידועה')}")
        result = data.get("result") or {}
        file_path = result.get("file_path")
        if not file_path:
            raise TelegramFileError("getFile לא החזיר file_path")

        file_size = result.get("file_size")
        if file_size is not None and file_size > TELEGRAM_FILE_MAX_BYTES:
            raise TelegramFileError(
                f"הקובץ גדול מדי ({file_size} בייטים) — המגבלה {TELEGRAM_FILE_MAX_BYTES} בייטים"
            )

        try:
            download_resp = await client.get(
                f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
            )
            download_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramFileError(f"הורדת הקובץ נכשלה: {exc}") from exc

        content = download_resp.content
        if len(content) > TELEGRAM_FILE_MAX_BYTES:
            raise TelegramFileError(
                f"הקובץ שהתקבל גדול מדי ({len(content)} בייטים) — המגבלה {TELEGRAM_FILE_MAX_BYTES} בייטים"
            )
        return content
