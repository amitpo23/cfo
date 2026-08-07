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
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from ..models import Expense

logger = logging.getLogger(__name__)

# מע"מ ישראלי נכון ל-2025+ (ראה skill israeli-vat-reporting).
VAT_RATE = Decimal("0.18")

# כל המקורות שמקורם במסמך SUMIT ולכן ניתנים למשיכה ב-getpdf. אלה נוצרים
# בשני מסלולים שונים ואסור לסנן רק אחד מהם:
#   'sumit'             — סנכרון ה-API הרגיל (accounting/documents/list).
#   'sumit_fileexpense' — קליטה ממסך תיוק ההוצאות של הפורטל. אלה דווקא
#                         ההוצאות שיש להן סכומים אמיתיים, בעוד טיוטות ה-API
#                         חוזרות כמעטפות ריקות (total=0) עד תיוק.
SUMIT_SOURCES = ("sumit", "sumit_fileexpense")

# מזהים שנוצרו אצלנו ואינם קיימים ב-SUMIT. הקליטה הידנית של 07/2026
# (commit e69d654) הטביעה `sumit_file_<uuid>` על 41 שורות של org 5;
# getpdf עליהן הוא קריאת API מבוזבזת בוודאות.
#
# מכוון כשלילה של דפוס ידוע ולא כהיתר-מספרי: מזהי המסמך שנצפו בפרוד הם
# אמנם בני 10 ספרות, אבל היתר צר על סמך מדגם אחד היה פוסל מזהים תקינים
# בפורמט אחר. עדיף לפסול רק את מה שידוע בוודאות כמומצא.
_SYNTHETIC_ID_PREFIXES = ("sumit_file_",)


def _is_sumit_document_id(external_id: Optional[str]) -> bool:
    if not external_id:
        return False
    value = str(external_id).strip()
    return bool(value) and not value.startswith(_SYNTHETIC_ID_PREFIXES)


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
        # cache ברמת המופע (לא גלובלי חוצה-ארגונים) לכללים הנלמדים של הארגון
        # הזה — ר' _get_learned_rules. מופע אחד של הפייפליין מעבד את כל
        # process_pending, כך שהמפה נטענת פעם אחת לכל ריצה, לא פר-קבלה.
        self._learned_rules_cache: Optional[Dict[str, str]] = None

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

        # טיוטה בסכום 0 היא מעטפת ריקה: ה-getpdf מחזיר עבורה דף בלי תוכן,
        # וכל קריאה כזאת שורפת מכסת SUMIT + קריאת מודל ראייה על לא-כלום.
        # כש--limit מגביל את הריצה, התקציב הולך קודם לטיוטות שנושאות סכום.
        blank_last = case(
            (or_(Expense.total.is_(None), Expense.total == 0), 1), else_=0
        )
        pending = self.db.query(Expense).filter(
            Expense.organization_id == self.organization_id,
            Expense.source.in_(SUMIT_SOURCES),
            Expense.external_id.isnot(None),
            Expense.status != "filed",
        )
        if since:
            pending = pending.filter(Expense.expense_date >= since)

        # שורות עם מזהה סינתטי אינן ניתנות למשיכה, ולכן אינן נכנסות לתור
        # כלל — אחרת `--limit 50` היה מתבזבז על 41 קיצורי-דרך. הן נספרות
        # בנפרד כדי שלא ייעלמו מהדיווח (honest-null).
        synthetic = or_(*[
            Expense.external_id.like(f"{prefix}%")
            for prefix in _SYNTHETIC_ID_PREFIXES
        ])
        not_fetchable_total = pending.filter(synthetic).count()

        rows = pending.filter(~synthetic).order_by(blank_last, Expense.id).all()
        if limit:
            rows = rows[:limit]

        results: List[Dict[str, Any]] = []
        filed = flagged = errors = 0
        not_fetchable = not_fetchable_total
        for i, exp in enumerate(rows):
            try:
                res = await self._process_one(exp, connector, auto_file=auto_file)
            except Exception as exc:  # כשל לא-צפוי בקבלה בודדת — לא עוצרים את כולן
                if "403" in str(exc):  # rate limit — עוצרים בעדינות
                    logger.warning("SUMIT rate-limited at #%s; stopping", exp.id)
                    results.append({"expense_id": exp.id, "source": exp.source,
                                    "status": "rate_limited"})
                    break
                logger.exception("OCR pipeline failed for expense %s", exp.id)
                errors += 1
                res = {"expense_id": exp.id, "source": exp.source,
                       "status": "error", "error": str(exc)}
            results.append(res)
            status = res.get("status")
            if status == "filed":
                filed += 1
            elif status == "flagged":
                flagged += 1
            elif status == "not_fetchable":
                not_fetchable += 1
            # ההשהיה קיימת בשביל ה-rate-limit של SUMIT. שורה שקוצרה לפני
            # כל קריאה לא צריכה אותה — 41 שורות סינתטיות × delay=3 היו
            # שתי דקות שינה תמורת אפס קריאות.
            if delay and status != "not_fetchable" and i < len(rows) - 1:
                await asyncio.sleep(delay)

        return {
            "scanned": len(rows),
            "filed": filed,
            "flagged": flagged,
            "errors": errors,
            # honest-null: ריצה שקיצרה שורות לא רשאית להיראות כריצה נקייה.
            "not_fetchable": not_fetchable,
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

    def _get_learned_rules(self) -> Dict[str, str]:
        """כללים נלמדים לארגון הזה (ר' classifier_ml_training.
        ClassifierMLTrainingService.get_learned_rules_map) — נטענים פעם
        אחת ונשמרים ב-cache על המופע. process_pending משתמש באותו מופע
        לכל הטיוטות בריצה, כך שזו שאילתת DB אחת לריצה, לא פר-קבלה."""
        if self._learned_rules_cache is None:
            from .classifier_ml_training import ClassifierMLTrainingService

            self._learned_rules_cache = ClassifierMLTrainingService(
                self.db, self.organization_id
            ).get_learned_rules_map()
        return self._learned_rules_cache

    async def _process_one(
        self, exp: Expense, connector, auto_file: bool
    ) -> Dict[str, Any]:
        from .expense_classifier import classify_expense
        from .israeli_tax_rules import claimable_vat

        # 0. שער מזהה: רק מסמך שקיים ב-SUMIT ניתן למשיכה. שורות שנקלטו
        # בקליטה ידנית נושאות מזהה סינתטי (`sumit_file_<uuid>`) ולא מזהה
        # מסמך — getpdf עליהן הוא קריאת API מבוזבזת בוודאות. הן שייכות
        # למסלול התיוק, לא למסלול החילוץ.
        if not _is_sumit_document_id(exp.external_id):
            return {
                "expense_id": exp.id,
                "external_id": exp.external_id,
                "source": exp.source,
                "status": "not_fetchable",
                "reason": (
                    "מזהה סינתטי — אין מסמך למשוך מ-SUMIT; נדרש מסלול תיוק"
                ),
            }

        # 1. צילום הקבלה
        pdf = await connector.get_document_pdf(exp.external_id)

        # 2. חילוץ ראייה
        extract = await self._extract(pdf)

        # 2א. החלטת אמון אחת, מוקדמת, שחלה על כל השדות. מה שכבר רשום הוא
        # נתון מאומת עד שיוכח אחרת: 41 השורות של org 5 נושאות שם ספק אמיתי,
        # 29 מהן ח.פ, ו-₪211K סכומים — כולם מקליטה ידנית מדוקדקת. חילוץ
        # חלש רשאי **למלא חוסר**, לא לדרוס. `_review_reasons` חוסם *תיוק*
        # ולא *כתיבה*, ולכן השער חייב לשבת כאן.
        trustworthy = self._extract_is_trustworthy(extract)

        def may_write(existing) -> bool:
            return trustworthy or not existing

        # 3. אימות ח.פ מול רשם החברות (מתקן בועת OCR שגויה).
        # נקרא רק כשנשתמש בתוצאה — קריאה חיה ל-data.gov.il על ח.פ מומצא
        # מחילוץ חלש עלולה להחזיר חברה אמיתית ולהחליף שם מאומת בשם שגוי
        # אך משכנע, שממנו ה-ח.פ זורם ל-PCN874.
        registry_match = None
        ocr_tax_id = extract.get("supplier_tax_id")
        if ocr_tax_id and may_write(exp.supplier_tax_id):
            registry_match = await self._lookup_registry(ocr_tax_id)

        official_name = registry_match["name"] if registry_match else None
        ocr_supplier_name = official_name or extract.get("supplier_name")

        supplier_name = exp.supplier_name
        if ocr_supplier_name and may_write(exp.supplier_name):
            supplier_name = ocr_supplier_name

        tax_id = exp.supplier_tax_id
        if ocr_tax_id and may_write(exp.supplier_tax_id):
            tax_id = ocr_tax_id

        # סכומים: total כולל מע"מ, ממנו נגזרים net + vat
        total, net, vat = self._resolve_amounts(extract)
        # סכום 0 אינו נתון מאומת אלא מעטפת ריקה — אין מה להגן עליו.
        verified_total = exp.total if exp.total and float(exp.total) > 0 else None
        if total is not None and not may_write(verified_total):
            total, net, vat = None, None, None

        # 4. סיווג
        category = classify_expense(
            supplier_name,
            exp.description,
            extract.get("invoice_number") or exp.invoice_number,
            sumit_item_name=exp.sumit_item_name,
            learned_rules=self._get_learned_rules(),
        )

        # תאריך
        exp_date = self._parse_date(extract.get("expense_date")) or exp.expense_date

        # 5. עדכון ה-DB (תמיד שומרים את מה שחולץ, גם אם מסומן לבדיקה)
        if supplier_name:
            exp.supplier_name = supplier_name
        if tax_id:
            exp.supplier_tax_id = tax_id
        vat_claimable = None
        if total is not None:
            exp.total = Decimal(str(total))
            exp.amount = Decimal(str(net))
            exp.vat_amount = Decimal(str(vat))
            # 5א. שער-מסמך + ניכוי תשומות (israeli_tax_rules.claimable_vat) —
            # רק כשיש מע"מ-על-מסמך לחשב עבורו; None ("unknown") -> תור הכרעה.
            exp.doc_kind = self._resolve_doc_kind(extract)
            vehicle_business, vehicle_kind = (None, None)
            if category in ("vehicle", "vehicle_purchase"):
                vehicle_business, vehicle_kind = self._vehicle_profile_args()
            vat_claimable = claimable_vat(
                category=category, vat_on_doc=Decimal(str(vat)), doc_kind=exp.doc_kind,
                vehicle_primarily_business=vehicle_business, vehicle_kind=vehicle_kind,
            )
            exp.vat_claimable = vat_claimable
        if extract.get("invoice_number") and may_write(exp.invoice_number):
            exp.invoice_number = extract["invoice_number"]
        if exp_date and may_write(exp.expense_date):
            exp.expense_date = exp_date
        if may_write(exp.category):
            exp.category = category

        # החלטת תיוק: דורש קריאות, ביטחון מספק, ח.פ, ספק וסכום
        review_reasons = self._review_reasons(extract, tax_id, supplier_name, total)
        if total is not None and vat_claimable is None:
            # שער-המסמך/הקטגוריה לא הכריעו את ניכוי התשומות — תור הכרעה,
            # לא תיוק אוטומטי עם ניחוש (honest-null, KB02).
            review_reasons.append("נדרשת הכרעה: ניכוי תשומות")
        result: Dict[str, Any] = {
            "expense_id": exp.id,
            "external_id": exp.external_id,
            "source": exp.source,
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
            "doc_kind": exp.doc_kind,
            "vat_claimable": float(vat_claimable) if vat_claimable is not None else None,
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
        import inspect

        parameters = inspect.signature(extract_receipt).parameters.values()
        supports_context = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters) or (
            "db" in inspect.signature(extract_receipt).parameters
        )
        if supports_context:
            return await extract_receipt(
                content, db=self.db, organization_id=self.organization_id,
                purpose="ocr",
            )
        # Backward-compatible seam for injected offline extractors whose
        # historical contract was extract_receipt(content).
        return await extract_receipt(content)

    async def _lookup_registry(self, tax_id: str):
        if self._registry is not None:
            return await self._registry.lookup(tax_id)
        from .company_registry import CompanyRegistry

        if not hasattr(self, "_registry_instance"):
            self._registry_instance = CompanyRegistry()
        return await self._registry_instance.lookup(tax_id)

    def _extract_is_trustworthy(self, extract: Dict[str, Any]) -> bool:
        """האם החילוץ חזק מספיק כדי לגבור על נתון שכבר רשום.

        זו ההחלטה היחידה ששולטת בכל הכתיבות ב-`_process_one`. חילוץ שאינו
        עומד בה עדיין רשאי למלא שדות ריקים — הוא רק לא רשאי לדרוס.
        """
        if not extract.get("is_readable", True):
            return False
        return float(extract.get("confidence") or 0) >= self.min_confidence

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
    def _resolve_doc_kind(extract: Dict[str, Any]) -> str:
        """"tax_invoice" | "receipt" | "unknown", לפי document_type שהחזיר
        vision_extractor (invoice/invoice_receipt -> tax_invoice, receipt ->
        receipt). כשהחילוץ לא סיפק document_type ברור — שמרנית: מספר
        חשבונית קיים נחשב סימן ל-tax_invoice, אחרת unknown (הכרעה, לא ניחוש)."""
        doc_type = (extract.get("document_type") or "").strip().lower()
        if doc_type in ("invoice", "invoice_receipt"):
            return "tax_invoice"
        if doc_type == "receipt":
            return "receipt"
        if extract.get("invoice_number"):
            return "tax_invoice"
        return "unknown"

    def _vehicle_profile_args(self):
        from .expense_filing_service import _load_vehicle_profile_args

        return _load_vehicle_profile_args(self.db, self.organization_id)

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
