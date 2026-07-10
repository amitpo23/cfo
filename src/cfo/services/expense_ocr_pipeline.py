"""
Pipeline אוטומטי לעיבוד טיוטות הוצאה סרוקות ב-SUMIT — ללא דפדפן, דרך ה-API בלבד.

הזרימה לכל טיוטה:
  1. משיכת צילום הקבלה        getpdf  -> bytes
  2. חילוץ נתונים במודל ראייה  vision  -> ספק/ח.פ/סכום/מע"מ/תאריך
  3. אימות ח.פ מול רשם החברות  registry -> שם רשמי (מתקן בועת OCR שגויה)
  4. סיווג לקטגוריה            classifier
  5. עדכון בסיס הנתונים        Expense
  6. (אופציונלי) תיוק ל-SUMIT  addexpense -> SUMIT מייצר פקודות יומן

עקרון מנחה (הנחיית המשתמש): מתייקים אוטומטית רק כאשר ח.פ + שם ספק + סכום
חולצו בביטחון. מה שלא קריא / חסר — מסומן לבדיקה ולא מתויק. ראה
[[expense-filing-6month-rule]], [[sumit-may2026-vat-state]], [[sumit-api-rate-limit]].
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Expense

logger = logging.getLogger(__name__)

# מע"מ ישראלי נכון ל-2025+ (ראה skill israeli-vat-reporting).
VAT_RATE = Decimal("0.18")


class ExpenseOCRPipeline:
    def __init__(
        self,
        db: Session,
        organization_id: int = 1,
        min_confidence: float = 0.6,
        registry=None,
        extractor=None,
    ):
        self.db = db
        self.organization_id = organization_id
        self.min_confidence = min_confidence
        # ניתנים להזרקה לצורך בדיקות; ברירת המחדל היא הממשים האמיתיים.
        self._registry = registry
        self._extractor = extractor

    # ---------- public API ----------

    async def process_pending(
        self,
        limit: Optional[int] = None,
        auto_file: bool = False,
        delay: float = 1.0,
        since: Optional[date] = None,
    ) -> Dict[str, Any]:
        """מעבד טיוטות הוצאה ממתינות (source=sumit, לא מתויקות) דרך ה-pipeline.

        delay: השהיה בין קבלות (rate-limit של SUMIT). since: לעבד רק מתאריך
        זה ואילך (חלון 6 החודשים).
        """
        connector = self._get_connector()

        q = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.source == "sumit",
                Expense.external_id.isnot(None),
                Expense.status != "filed",
            )
            .order_by(Expense.id)
        )
        if since:
            q = q.filter(Expense.expense_date >= since)
        rows = q.all()
        if limit:
            rows = rows[:limit]

        results: List[Dict[str, Any]] = []
        filed = flagged = errors = 0
        for i, exp in enumerate(rows):
            try:
                res = await self._process_one(exp, connector, auto_file=auto_file)
            except Exception as exc:  # כשל לא-צפוי בקבלה בודדת — לא עוצרים את כולן
                if "403" in str(exc):  # rate limit — עוצרים בעדינות
                    logger.warning("SUMIT rate-limited at #%s; stopping", exp.id)
                    results.append({"expense_id": exp.id, "status": "rate_limited"})
                    break
                logger.exception("OCR pipeline failed for expense %s", exp.id)
                errors += 1
                res = {"expense_id": exp.id, "status": "error", "error": str(exc)}
            results.append(res)
            if res.get("status") == "filed":
                filed += 1
            elif res.get("status") == "flagged":
                flagged += 1
            if delay and i < len(rows) - 1:
                await asyncio.sleep(delay)

        return {
            "scanned": len(rows),
            "filed": filed,
            "flagged": flagged,
            "errors": errors,
            "results": results,
        }

    async def process_expense(
        self, expense_id: int, auto_file: bool = False
    ) -> Dict[str, Any]:
        """מעבד הוצאה בודדת לפי מזהה."""
        exp = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.id == expense_id,
            )
            .first()
        )
        if not exp:
            raise ValueError(f"הוצאה {expense_id} לא נמצאה")
        if not exp.external_id:
            raise ValueError(f"להוצאה {expense_id} אין מסמך SUMIT (external_id)")
        connector = self._get_connector()
        return await self._process_one(exp, connector, auto_file=auto_file)

    # ---------- core ----------

    async def _process_one(
        self, exp: Expense, connector, auto_file: bool
    ) -> Dict[str, Any]:
        from .expense_classifier import classify_expense

        # 1. צילום הקבלה
        pdf = await connector.get_document_pdf(exp.external_id)

        # 2. חילוץ ראייה
        extract = await self._extract(pdf)

        # 3. אימות ח.פ מול רשם החברות (מתקן בועת OCR שגויה)
        registry_match = None
        if extract.get("supplier_tax_id"):
            registry_match = await self._lookup_registry(extract["supplier_tax_id"])

        official_name = registry_match["name"] if registry_match else None
        supplier_name = official_name or extract.get("supplier_name") or exp.supplier_name
        tax_id = extract.get("supplier_tax_id")

        # סכומים: total כולל מע"מ, ממנו נגזרים net + vat
        total, net, vat = self._resolve_amounts(extract)

        # 4. סיווג
        category = classify_expense(
            supplier_name,
            exp.description,
            extract.get("invoice_number") or exp.invoice_number,
            sumit_item_name=exp.sumit_item_name,
        )

        # תאריך
        exp_date = self._parse_date(extract.get("expense_date")) or exp.expense_date

        # 5. עדכון ה-DB (תמיד שומרים את מה שחולץ, גם אם מסומן לבדיקה)
        if supplier_name:
            exp.supplier_name = supplier_name
        if tax_id:
            exp.supplier_tax_id = tax_id
        if total is not None:
            exp.total = Decimal(str(total))
            exp.amount = Decimal(str(net))
            exp.vat_amount = Decimal(str(vat))
        if extract.get("invoice_number"):
            exp.invoice_number = extract["invoice_number"]
        if exp_date:
            exp.expense_date = exp_date
        exp.category = category

        # החלטת תיוק: דורש קריאות, ביטחון מספק, ח.פ, ספק וסכום
        review_reasons = self._review_reasons(extract, tax_id, supplier_name, total)
        result: Dict[str, Any] = {
            "expense_id": exp.id,
            "external_id": exp.external_id,
            "supplier_name": supplier_name,
            "supplier_tax_id": tax_id,
            "registry_confirmed": bool(registry_match),
            "ocr_supplier_name": extract.get("supplier_name"),
            "amount": net,
            "vat_amount": vat,
            "total": total,
            "category": category,
            "confidence": extract.get("confidence"),
            "expense_date": exp_date.isoformat() if exp_date else None,
        }

        if review_reasons:
            exp.status = "pending"
            exp.filing_error = "לבדיקה ידנית: " + "; ".join(review_reasons)
            self.db.commit()
            result["status"] = "flagged"
            result["review_reasons"] = review_reasons
            return result

        # מאומת — מנקים סימון בדיקה קודם
        exp.filing_error = None
        self.db.commit()

        if auto_file:
            from .expense_filing_service import ExpenseFilingService

            filing = ExpenseFilingService(self.db, organization_id=self.organization_id)
            filed = await filing.file_to_sumit(exp.id)
            result["status"] = "filed"
            result["sumit_expense_id"] = filed.get("sumit_expense_id")
        else:
            result["status"] = "ready"
        return result

    # ---------- helpers ----------

    def _get_connector(self):
        from .sync_engine import get_connector_for_org

        connector, _cid, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit" or not hasattr(connector, "get_document_pdf"):
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")
        return connector

    async def _extract(self, content: bytes) -> Dict[str, Any]:
        if self._extractor is not None:
            return await self._extractor(content)
        from .vision_extractor import extract_receipt

        return await extract_receipt(content)

    async def _lookup_registry(self, tax_id: str):
        if self._registry is not None:
            return await self._registry.lookup(tax_id)
        from .company_registry import CompanyRegistry

        if not hasattr(self, "_registry_instance"):
            self._registry_instance = CompanyRegistry()
        return await self._registry_instance.lookup(tax_id)

    @staticmethod
    def _resolve_amounts(extract: Dict[str, Any]):
        """מחזיר (total, net, vat) מתוך מה שחולץ. כל ערך כ-float או None ל-total."""
        total = extract.get("amount_total")
        vat = extract.get("vat_amount")
        net = extract.get("net_amount")
        if total is None:
            if net is not None and vat is not None:
                total = net + vat
            elif net is not None:
                total = net * float(1 + VAT_RATE)
            else:
                return None, None, None
        total_d = Decimal(str(total))
        if vat is None and net is not None:
            vat_d = total_d - Decimal(str(net))
        elif vat is None:
            # אומדן מע"מ מתוך הסכום הכולל (18%): vat = total - total/1.18
            vat_d = total_d - (total_d / (Decimal("1") + VAT_RATE))
            vat_d = vat_d.quantize(Decimal("0.01"))
        else:
            vat_d = Decimal(str(vat))
        net_d = total_d - vat_d
        return float(total_d), float(net_d), float(vat_d)

    def _review_reasons(
        self, extract: Dict[str, Any], tax_id, supplier_name, total
    ) -> List[str]:
        reasons = []
        if not extract.get("is_readable", True):
            reasons.append("המסמך לא קריא")
        conf = extract.get("confidence") or 0.0
        if conf < self.min_confidence:
            reasons.append(f"ביטחון נמוך ({conf:.2f})")
        if not tax_id:
            reasons.append("חסר ח.פ")
        if not supplier_name:
            reasons.append("חסר שם ספק")
        if total is None:
            reasons.append("חסר סכום")
        return reasons

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return None
