"""
שירות תיוק הוצאות — DB-backed, רב-ארגוני, מתייק ל-SUMIT עם credentials של הארגון
Expense filing service: persists expenses, files them to SUMIT using the
organization's own credentials, and can pull expense documents from SUMIT.
"""
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Expense


class ExpenseFilingService:
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id

    # ---------- CRUD ----------

    def list_expenses(self, status: Optional[str] = None) -> List[Dict]:
        q = self.db.query(Expense).filter(Expense.organization_id == self.organization_id)
        if status:
            q = q.filter(Expense.status == status)
        rows = q.order_by(Expense.expense_date.desc()).all()
        return [self._serialize(e) for e in rows]

    def create_expense(self, data: Dict) -> Dict:
        from .expense_classifier import classify_expense

        amount = Decimal(str(data.get("amount", 0)))
        vat = Decimal(str(data.get("vat_amount", 0) or 0))
        total = data.get("total")
        total = Decimal(str(total)) if total is not None else amount + vat
        # סיווג אוטומטי אם לא סופקה קטגוריה
        category = data.get("category")
        if not category:
            category = classify_expense(
                data.get("supplier_name"), data.get("description"), data.get("invoice_number")
            )
        exp = Expense(
            organization_id=self.organization_id,
            source=data.get("source", "manual"),
            supplier_id=data.get("supplier_id"),
            supplier_name=data.get("supplier_name") or "ספק",
            amount=amount,
            vat_amount=vat,
            total=total,
            expense_date=data.get("expense_date") or date.today(),
            category=category,
            description=data.get("description"),
            invoice_number=data.get("invoice_number"),
            receipt_file=data.get("receipt_file"),
            status="pending",
        )
        self.db.add(exp)
        self.db.commit()
        self.db.refresh(exp)
        return self._serialize(exp)

    def update_expense(self, expense_id: int, data: Dict) -> Dict:
        """עדכון הוצאה (אישור/תיקון סכום, מע"מ, פריט/קטגוריה, ספק) לפני תיוק."""
        exp = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.id == expense_id,
            ).first()
        )
        if not exp:
            raise ValueError(f"הוצאה {expense_id} לא נמצאה")
        for field in ("supplier_name", "category", "description", "invoice_number"):
            if data.get(field) is not None:
                setattr(exp, field, data[field])
        if data.get("amount") is not None:
            exp.amount = Decimal(str(data["amount"]))
        if data.get("vat_amount") is not None:
            exp.vat_amount = Decimal(str(data["vat_amount"]))
        if data.get("deduction_percent") is not None:
            exp.deduction_percent = Decimal(str(data["deduction_percent"]))
        # שמירת total עקבי אם לא סופק מפורשות
        if data.get("total") is not None:
            exp.total = Decimal(str(data["total"]))
        elif data.get("amount") is not None or data.get("vat_amount") is not None:
            exp.total = Decimal(str(exp.amount or 0)) + Decimal(str(exp.vat_amount or 0))
        self.db.commit()
        self.db.refresh(exp)
        return self._serialize(exp)

    def classify_uncategorized(self, reclassify_all: bool = False) -> Dict:
        """סיווג אוטומטי של הוצאות. ברירת מחדל: רק ללא קטגוריה / 'other'."""
        from .expense_classifier import classify_expense

        q = self.db.query(Expense).filter(Expense.organization_id == self.organization_id)
        if not reclassify_all:
            q = q.filter((Expense.category.is_(None)) | (Expense.category == "") | (Expense.category == "other"))
        updated = 0
        for exp in q.all():
            new_cat = classify_expense(
                exp.supplier_name, exp.description, exp.invoice_number,
                sumit_item_name=exp.sumit_item_name,
            )
            if new_cat != exp.category:
                exp.category = new_cat
                updated += 1
        self.db.commit()
        return {"classified": updated}

    # ---------- SUMIT filing ----------

    async def resolve_supplier_names(
        self, limit: Optional[int] = None, delay: float = 0.4
    ) -> Dict:
        """פתרון שמות ספקים להוצאות שמקורן SUMIT (שם מגיע כ-ID) דרך getdetails,
        ואז סיווג מחדש לפי השם האמיתי.

        delay: השהיה בין קריאות (שניות) כדי לא לחרוג מ-rate limit של SUMIT
        (קריאות מהירות מדי מחזירות 403). commit מתבצע כל 25 רשומות כדי
        לשמור התקדמות גם אם נעצרים באמצע.
        """
        import asyncio

        from .sync_engine import get_connector_for_org
        from .expense_classifier import classify_expense

        connector, _conn_id, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit" or not hasattr(connector, "get_document_supplier_details"):
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")

        # הוצאות SUMIT שעדיין חסר בהן שם ספק אמיתי או ח.פ
        q = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.source == "sumit",
                Expense.external_id.isnot(None),
            )
        )
        rows = [
            e for e in q.all()
            if (e.supplier_name or "").strip().isdigit()
            or e.supplier_name in ("", "ספק SUMIT")
            or not e.supplier_tax_id
        ]
        if limit:
            rows = rows[:limit]

        resolved = 0
        reclassified = 0
        tax_ids = 0
        rate_limited = False
        for i, e in enumerate(rows):
            try:
                d = await connector.get_document_supplier_details(e.external_id)
            except Exception as exc:
                if "403" in str(exc):  # rate limit — לעצור בעדינות ולשמור התקדמות
                    rate_limited = True
                    break
                continue
            name = d.get("name")
            tax_id = d.get("tax_id")
            if tax_id and not e.supplier_tax_id:
                e.supplier_tax_id = tax_id
                tax_ids += 1
            if d.get("vat") and not e.vat_amount:
                e.vat_amount = d["vat"]
            # שם פריט SUMIT — אות הסיווג האמין
            item_name = d.get("item_name")
            if item_name and not e.sumit_item_name:
                e.sumit_item_name = item_name
            if name:
                e.supplier_name = name
                resolved += 1
            new_cat = classify_expense(
                e.supplier_name, e.description, e.invoice_number,
                sumit_item_name=e.sumit_item_name,
            )
            if new_cat != e.category:
                e.category = new_cat
                reclassified += 1
            if i % 25 == 0:
                self.db.commit()  # שמירת התקדמות
            if delay:
                await asyncio.sleep(delay)
        self.db.commit()
        return {
            "resolved": resolved,
            "tax_ids": tax_ids,
            "reclassified": reclassified,
            "scanned": len(rows),
            "rate_limited": rate_limited,
        }

    def pcn874_readiness(self) -> Dict:
        """בדיקת מוכנות PCN874: אילו הוצאות מתויקות חסרות ח.פ/מע"מ, וסיכום סכומים."""
        filed = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.status == "filed",
            ).all()
        )
        pending = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.status != "filed",
            ).count()
        )
        ready = 0
        missing_tax_id = []
        missing_vat = 0
        total_amount = 0.0
        total_vat = 0.0
        for e in filed:
            has_tax = bool((e.supplier_tax_id or "").strip())
            has_vat = float(e.vat_amount or 0) > 0
            total_amount += float(e.total or 0)
            total_vat += float(e.vat_amount or 0)
            if not has_tax:
                missing_tax_id.append({"id": e.id, "supplier": e.supplier_name, "amount": float(e.total or 0)})
            if not has_vat:
                missing_vat += 1
            if has_tax and has_vat:
                ready += 1
        return {
            "filed_total": len(filed),
            "pcn_ready": ready,
            "missing_tax_id_count": len(missing_tax_id),
            "missing_vat_count": missing_vat,
            "not_in_books_count": pending,  # טיוטות שלא ייכנסו ל-PCN874 עד שיתויקו
            "totals": {"amount": round(total_amount, 2), "vat": round(total_vat, 2)},
            "missing_tax_id_sample": missing_tax_id[:20],
        }

    async def file_all_pending(self) -> Dict:
        """תיוק גורף של כל ההוצאות הממתינות ב-SUMIT."""
        pending = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.status != "filed",
            ).all()
        )
        filed, failed = 0, 0
        errors = []
        for exp in pending:
            try:
                await self.file_to_sumit(exp.id)
                filed += 1
            except ValueError as e:
                failed += 1
                errors.append({"expense_id": exp.id, "error": str(e)})
        return {"filed": filed, "failed": failed, "errors": errors[:20]}


    async def file_to_sumit(self, expense_id: int) -> Dict:
        """תיוק הוצאה ב-SUMIT עם ה-credentials של הארגון."""
        from .sync_engine import get_connector_for_org
        from ..integrations.sumit_models import ExpenseRequest

        exp = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.id == expense_id,
            ).first()
        )
        if not exp:
            raise ValueError(f"הוצאה {expense_id} לא נמצאה")
        if exp.status == "filed":
            return self._serialize(exp)

        connector, _conn_id, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit":
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")

        if not hasattr(connector, "add_expense"):
            raise ValueError("הקונקטור אינו תומך ביצירת הוצאה")

        # יוצרים תמיד מסמך הוצאה עם הקטגוריה שלנו — כך הסיווג נכנס ל-SUMIT
        # (ל-SUMIT אין API לעדכון קטגוריה של טיוטה קיימת).
        request = ExpenseRequest(
            supplier_name=exp.supplier_name,
            amount=Decimal(str(exp.amount or 0)),
            vat_amount=Decimal(str(exp.vat_amount or 0)),
            expense_date=exp.expense_date,
            category=exp.category,
            notes=exp.description or (
                f"חשבונית: {exp.invoice_number}" if exp.invoice_number else None
            ),
            receipt_file=exp.receipt_file,
        )
        try:
            response = await connector.add_expense(request)
            new_id = response.get("expense_id")
            # אם ההוצאה הגיעה מטיוטה סרוקה ב-SUMIT — מבטלים את המקור כדי שלא תהיה כפילות.
            if exp.source == "sumit" and exp.external_id and hasattr(connector, "cancel_document"):
                await connector.cancel_document(exp.external_id)
            exp.sumit_expense_id = new_id
            exp.status = "filed"
            exp.filing_error = None
        except Exception as e:  # נשמר המצב כדי לאפשר ניסיון חוזר
            exp.status = "error"
            exp.filing_error = str(e)
            self.db.commit()
            raise ValueError(f"תיוק ל-SUMIT נכשל: {e}")

        self.db.commit()
        self.db.refresh(exp)
        return self._serialize(exp)

    async def sync_pending_from_sumit(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> Dict:
        """משיכת הוצאות ממתינות (טיוטות) מ-SUMIT אל טבלת ההוצאות, מסווגות אוטומטית.

        מיובאות בסטטוס 'pending' (ממתינות לאישור), לא 'filed' — האישור נעשה
        בנפרד דרך movetobooks כדי לא לתייק בטעות.
        """
        from .sync_engine import get_connector_for_org
        from .expense_classifier import classify_expense
        from ..integrations.sumit_models import DocumentListRequest

        connector, _conn_id, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit" or not hasattr(connector, "list_documents"):
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")

        # הטיוטות הממתינות (עמוד fileexpenses) הן status="draft" — לא מסוננות
        # נכון ע"י document_type="expense" (הן סוג 15, לא 16). מושכים הכל ומסננים
        # טיוטות בצד הלקוח.
        # פילטר סוג-מסמך ב-API מחזיר רק הוצאות סופיות (16), לא את הטיוטות הסרוקות (15).
        # לכן מושכים רחב ומסננים בצד הלקוח לפי קודי ההוצאה של SUMIT:
        # 15 = ExpenseReceipt (סריקות ממתינות), 16 = ExpenseInvoice (הוצאות מתויקות).
        EXPENSE_TYPE_CODES = {"15", "16"}
        request = DocumentListRequest(
            from_date=from_date,
            to_date=to_date,
            limit=1000,
        )
        docs = await connector.list_documents(request)
        created = 0
        drafts = 0
        filed = 0
        for d in docs:
            ext = str(getattr(d, "document_id", "") or getattr(d, "id", "") or "")
            if not ext:
                continue
            status_val = str(getattr(d, "status", "") or "").lower()
            is_draft = "draft" in status_val or getattr(d, "is_draft", False)
            doc_type = str(getattr(d, "document_type", "") or "")
            # רק מסמכי הוצאה (לא חשבוניות מכירה / קבלות הכנסה)
            if doc_type not in EXPENSE_TYPE_CODES:
                continue
            existing = (
                self.db.query(Expense)
                .filter(
                    Expense.organization_id == self.organization_id,
                    Expense.external_id == ext,
                    Expense.source == "sumit",
                ).first()
            )
            if existing:
                continue
            total = abs(Decimal(str(getattr(d, "total_amount", 0) or 0)))
            vat = abs(Decimal(str(getattr(d, "vat_amount", 0) or 0)))
            supplier = str(getattr(d, "customer_id", "") or "").strip() or "ספק SUMIT"
            invoice_no = getattr(d, "document_number", None)
            exp = Expense(
                organization_id=self.organization_id,
                external_id=ext,
                source="sumit",
                supplier_name=supplier,
                amount=total - vat,
                vat_amount=vat,
                total=total,
                expense_date=getattr(d, "issue_date", None) or date.today(),
                invoice_number=invoice_no,
                category=classify_expense(supplier, None, invoice_no),
                # טיוטה = ממתינה לאישור; מסמך סופי = כבר מתויק ב-SUMIT
                status="pending" if is_draft else "filed",
                sumit_expense_id=None if is_draft else ext,
            )
            self.db.add(exp)
            created += 1
            if is_draft:
                drafts += 1
            else:
                filed += 1
        self.db.commit()
        return {
            "imported": created,
            "pending_drafts": drafts,
            "already_filed": filed,
            "total_expense_docs_from_sumit": len(docs),
        }

    # ---------- helpers ----------

    @staticmethod
    def _serialize(e: Expense) -> Dict:
        return {
            "id": e.id,
            "supplier_name": e.supplier_name,
            "amount": float(e.amount or 0),
            "vat_amount": float(e.vat_amount or 0),
            "total": float(e.total or 0),
            "expense_date": e.expense_date.isoformat() if e.expense_date else None,
            "category": e.category,
            "description": e.description,
            "invoice_number": e.invoice_number,
            "status": e.status,
            "sumit_expense_id": e.sumit_expense_id,
            "filing_error": e.filing_error,
            "source": e.source,
            "deduction_percent": float(e.deduction_percent) if e.deduction_percent is not None else None,
        }
