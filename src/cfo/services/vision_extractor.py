"""
חילוץ נתוני קבלה מצילום/סריקה באמצעות מודל ראייה (LLM vision).

מקבל את ה-PDF/תמונה של הקבלה (כפי ש-SUMIT getpdf מחזיר) ומחזיר dict מובנה:
ספק, ח.פ, סכום כולל, מע"מ, תאריך, מספר חשבונית, מטבע ורמת ביטחון.

ספק ברירת מחדל: Anthropic (Claude) — קורא PDF באופן טבעי. אם מוגדר רק
openai_api_key — fallback ל-OpenAI (דורש רסטור של ה-PDF לתמונה).

חשוב: אין כאן הזנת מפתחות. המפתח נקרא מהקונפיג (settings) שהמשתמש מגדיר
ב-.env.local. ללא מפתח — נזרקת שגיאה ברורה ולא מתבצעת קריאה.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Dict, Optional

from ..config import settings

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """אתה מחלץ נתונים מצילום/סריקה של חשבונית או קבלה ישראלית.
החזר אך ורק אובייקט JSON תקין (ללא טקסט נוסף, ללא ```), עם השדות הבאים:

{
  "supplier_name": "שם העסק/הספק כפי שמופיע על הקבלה",
  "supplier_tax_id": "ח.פ / מספר עוסק מורשה (ספרות בלבד) או null",
  "amount_total": מספר — הסכום הכולל לתשלום כולל מע"מ,
  "vat_amount": מספר — סכום המע"מ בלבד, או null אם לא מצוין,
  "net_amount": מספר — הסכום לפני מע"מ, או null,
  "invoice_number": "מספר החשבונית/קבלה או null",
  "expense_date": "תאריך המסמך בפורמט YYYY-MM-DD או null",
  "currency": "ILS לרוב, או קוד מטבע אחר",
  "document_type": "invoice / receipt / invoice_receipt / unknown",
  "confidence": מספר בין 0 ל-1 — עד כמה אתה בטוח בקריאה,
  "is_readable": true/false — האם המסמך קריא מספיק לחילוץ,
  "notes": "הערות חריגות (למשל: מסמך דהוי, חסר ח.פ) או null"
}

כללים:
- ח.פ ישראלי הוא 9 ספרות לרוב. החזר ספרות בלבד.
- אל תמציא ערכים. אם שדה לא קריא — החזר null ו-confidence נמוך.
- אם מע"מ לא מופיע במפורש אך יש סכום כולל וסכום לפני מע"מ — חשב את ההפרש.
- אם המסמך לא קריא בכלל — is_readable=false."""


class VisionExtractionError(Exception):
    """שגיאה בחילוץ הראייה (אין מפתח/SDK, או כשל קריאה)."""


def _decode_json(text: str) -> Dict[str, Any]:
    """מחלץ JSON מטקסט שהמודל החזיר (גם אם עטוף ב-```json)."""
    text = (text or "").strip()
    # הסרת code fences אם קיימים
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """מנרמל את פלט המודל למבנה אחיד עם טיפוסים נכונים."""
    def num(v):
        if v in (None, "", "null"):
            return None
        try:
            return float(str(v).replace(",", "").replace("₪", "").strip())
        except (TypeError, ValueError):
            return None

    tax_id = raw.get("supplier_tax_id")
    tax_id = re.sub(r"\D", "", str(tax_id)) if tax_id not in (None, "", "null") else None

    return {
        "supplier_name": (raw.get("supplier_name") or "").strip() or None,
        "supplier_tax_id": tax_id or None,
        "amount_total": num(raw.get("amount_total")),
        "vat_amount": num(raw.get("vat_amount")),
        "net_amount": num(raw.get("net_amount")),
        "invoice_number": (str(raw.get("invoice_number")).strip()
                           if raw.get("invoice_number") not in (None, "", "null") else None),
        "expense_date": (str(raw.get("expense_date")).strip()
                         if raw.get("expense_date") not in (None, "", "null") else None),
        "currency": (raw.get("currency") or "ILS").strip() or "ILS",
        "document_type": (raw.get("document_type") or "unknown").strip(),
        "confidence": num(raw.get("confidence")) or 0.0,
        "is_readable": bool(raw.get("is_readable", True)),
        "notes": (str(raw.get("notes")).strip()
                  if raw.get("notes") not in (None, "", "null") else None),
    }


def _looks_like_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


async def extract_receipt(
    content: bytes,
    media_type: Optional[str] = None,
) -> Dict[str, Any]:
    """מחלץ נתוני קבלה מבייטים של קובץ (PDF או תמונה).

    בוחר ספק לפי המפתחות המוגדרים: Anthropic מועדף, OpenAI fallback.
    זורק VisionExtractionError אם אין מפתח/SDK או אם הקריאה נכשלה.
    """
    if not content:
        raise VisionExtractionError("קובץ ריק — אין מה לחלץ")
    if not settings.ocr_llm_enabled:
        # החלטת משתמש (2026-07-06): מפתח ה-Anthropic משרת את הצ'אטבוט בלבד.
        # OCR בראייה ממוחשבת מופעל רק בהסכמה מפורשת (OCR_LLM_ENABLED=true).
        raise VisionExtractionError(
            "חילוץ OCR מבוסס-LLM כבוי — מפתח ה-API מוקצה לעוזר ה-AI בלבד. "
            "להפעלה: OCR_LLM_ENABLED=true"
        )
    if media_type is None:
        media_type = "application/pdf" if _looks_like_pdf(content) else "image/png"

    if settings.anthropic_api_key:
        raw = await _extract_anthropic(content, media_type)
    elif settings.openai_api_key:
        raw = await _extract_openai(content, media_type)
    else:
        raise VisionExtractionError(
            "לא מוגדר מפתח LLM. הגדר ANTHROPIC_API_KEY (מומלץ) או OPENAI_API_KEY "
            "ב-.env.local כדי להפעיל את חילוץ הראייה."
        )
    return _normalize(raw)


async def _extract_anthropic(content: bytes, media_type: str) -> Dict[str, Any]:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise VisionExtractionError(
            "חבילת anthropic אינה מותקנת. הרץ: pip install anthropic"
        ) from exc

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    b64 = base64.standard_b64encode(content).decode("ascii")
    # PDF נשלח כ-document block; תמונה כ-image block.
    if media_type == "application/pdf":
        media_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        media_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    try:
        message = await client.messages.create(
            model=settings.ocr_vision_model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [media_block, {"type": "text", "text": EXTRACTION_PROMPT}],
            }],
        )
    except Exception as exc:
        raise VisionExtractionError(f"קריאת Anthropic נכשלה: {exc}") from exc
    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    try:
        return _decode_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise VisionExtractionError(f"פלט Anthropic אינו JSON תקין: {text[:200]}") from exc


async def _extract_openai(content: bytes, media_type: str) -> Dict[str, Any]:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise VisionExtractionError(
            "חבילת openai אינה מותקנת. הרץ: pip install openai"
        ) from exc

    # OpenAI vision (chat completions) מקבל תמונות בלבד — נרסטר PDF לתמונה.
    if media_type == "application/pdf":
        content, media_type = _pdf_to_image(content)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    b64 = base64.standard_b64encode(content).decode("ascii")
    data_url = f"data:{media_type};base64,{b64}"
    try:
        resp = await client.chat.completions.create(
            model=settings.ocr_vision_model_openai,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        )
    except Exception as exc:
        raise VisionExtractionError(f"קריאת OpenAI נכשלה: {exc}") from exc
    text = resp.choices[0].message.content or ""
    try:
        return _decode_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise VisionExtractionError(f"פלט OpenAI אינו JSON תקין: {text[:200]}") from exc


def _pdf_to_image(content: bytes):
    """רסטור עמוד ראשון של PDF ל-PNG (נדרש למסלול OpenAI)."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise VisionExtractionError(
            "מסלול OpenAI דורש רסטור PDF לתמונה. התקן pypdfium2 (pip install "
            "pypdfium2), או השתמש ב-Anthropic שקורא PDF באופן טבעי."
        ) from exc
    import io

    pdf = pdfium.PdfDocument(content)
    page = pdf[0]
    bitmap = page.render(scale=2.0)
    pil_image = bitmap.to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue(), "image/png"
