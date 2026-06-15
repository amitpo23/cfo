"""
אימות ח.פ מול רשם החברות (data.gov.il CKAN).

מחזיר את השם הרשמי של החברה לפי מספר ח.פ — משמש את ה-OCR pipeline כדי לוודא
שהספק שחולץ מצילום הקבלה תואם לרשומה הרשמית (ולתקן שם/ח.פ שגויים שבועת ה-OCR
לפעמים מציעה). ראה [[expense-filing-6month-rule]].

ה-API ציבורי (CKAN datastore_search). אם המשאב לא זמין / החיפוש נכשל —
מחזירים None כדי שהקורא יוכל לדלג בעדינות בלי להפיל את כל ה-pipeline.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# שמות עמודות אפשריים בקובץ רשם החברות (השתנו לאורך השנים).
_NAME_FIELDS = ("שם חברה", "Company_Name", "CompanyName", "שם החברה")
_TAXID_FIELDS = ("מספר חברה", "Company_Number", "CompanyNumber", "מס' חברה")
_STATUS_FIELDS = ("סטטוס חברה", "Company_Status", "CompanyStatus")


def normalize_tax_id(tax_id: Optional[str]) -> str:
    """מנקה ח.פ לספרות בלבד (מסיר רווחים/מקפים)."""
    if not tax_id:
        return ""
    return re.sub(r"\D", "", str(tax_id))


def _extract(record: Dict[str, Any], fields) -> str:
    for f in fields:
        val = record.get(f)
        if val not in (None, ""):
            return str(val).strip()
    return ""


class CompanyRegistry:
    """חיפוש חברה לפי ח.פ ברשם החברות (data.gov.il)."""

    def __init__(
        self,
        resource_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.resource_id = resource_id or settings.companies_registry_resource_id
        self.base_url = base_url or settings.companies_registry_base_url
        self.timeout = timeout
        # מטמון בתוך-תהליכי כדי לא לחזור על אותה קריאה.
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}

    async def lookup(self, tax_id: str) -> Optional[Dict[str, Any]]:
        """מחזיר {'tax_id','name','status','raw'} לפי ח.פ, או None אם לא נמצא."""
        norm = normalize_tax_id(tax_id)
        if not norm:
            return None
        if norm in self._cache:
            return self._cache[norm]

        params = {
            "resource_id": self.resource_id,
            "q": norm,
            "limit": 5,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.base_url, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # רשת/שירות לא זמין — לא מפילים את ה-pipeline
            logger.warning("רשם החברות: חיפוש %s נכשל: %s", norm, exc)
            return None

        result = self._parse_records(norm, payload)
        self._cache[norm] = result
        return result

    @staticmethod
    def _parse_records(norm: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """בוחר את הרשומה שה-ח.פ שלה תואם בדיוק (q הוא חיפוש חופשי)."""
        records = ((payload or {}).get("result") or {}).get("records") or []
        for rec in records:
            rec_taxid = normalize_tax_id(_extract(rec, _TAXID_FIELDS))
            if rec_taxid == norm:
                name = _extract(rec, _NAME_FIELDS)
                if not name:
                    continue
                return {
                    "tax_id": norm,
                    "name": name,
                    "status": _extract(rec, _STATUS_FIELDS) or None,
                    "raw": rec,
                }
        return None
