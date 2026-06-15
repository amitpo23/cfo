"""
דוח עמלות — עמלות בנק, כרטיסי אשראי/סליקה, וריבית הלוואות
Fees report: detects bank charges, card/clearing fees, and loan interest from
real expense transactions, classified by source.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Transaction, TransactionType


# מילות מפתח לזיהוי סוג עמלה (קטגוריה או תיאור), עברית + אנגלית
FEE_KEYWORDS = {
    "credit_card": [
        "סליקה", "אשראי", "כרטיס", "credit", "card", "clearing", "sumit", "tranzila", "cardcom",
    ],
    "bank": [
        "עמלת", "עמלה", "עמלות", "בנק", "bank", "fee", "charge", "wire", "swift", "עו\"ש",
    ],
    "loan": [
        "ריבית", "הלוואה", "אשראי בנקאי", "interest", "loan", "mortgage", "משכנתא",
    ],
}

FEE_TYPE_LABELS = {
    "credit_card": "עמלות סליקה / כרטיסי אשראי",
    "bank": "עמלות בנק",
    "loan": "ריבית והלוואות",
    "other": "עמלות אחרות",
}


class FeesService:
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id

    def _classify(self, category: Optional[str], description: Optional[str]) -> Optional[str]:
        text = f"{category or ''} {description or ''}".lower()
        for fee_type, keywords in FEE_KEYWORDS.items():
            if any(kw.lower() in text for kw in keywords):
                return fee_type
        return None

    def _expense_total(self, start_date: date, end_date: date) -> float:
        return float(
            self.db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(
                Transaction.organization_id == self.organization_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            ).scalar() or 0
        )

    def get_fees_report(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict:
        """דוח עמלות מפורט לפי סוג, עם אחוז מההוצאות ופירוט פריטים."""
        today = end_date or date.today()
        start = start_date or today.replace(month=1, day=1)

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.organization_id == self.organization_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= today,
            )
            .all()
        )

        by_type = {"credit_card": 0.0, "bank": 0.0, "loan": 0.0, "other": 0.0}
        items: List[Dict] = []
        for t in rows:
            fee_type = self._classify(t.category, t.description)
            if fee_type is None:
                continue
            amount = float(t.amount or 0)
            by_type[fee_type] += amount
            items.append({
                "date": t.transaction_date.isoformat() if t.transaction_date else None,
                "description": t.description or t.category or "עמלה",
                "category": t.category,
                "type": fee_type,
                "type_label": FEE_TYPE_LABELS[fee_type],
                "amount": amount,
            })

        total_fees = sum(by_type.values())
        total_expenses = self._expense_total(start, today)
        items.sort(key=lambda x: x["amount"], reverse=True)

        return {
            "period": {"start": start.isoformat(), "end": today.isoformat()},
            "total_fees": round(total_fees, 2),
            "total_expenses": round(total_expenses, 2),
            "fees_pct_of_expenses": round(total_fees / total_expenses * 100, 2) if total_expenses else 0,
            "by_type": [
                {"type": k, "label": FEE_TYPE_LABELS[k], "amount": round(v, 2)}
                for k, v in by_type.items() if v > 0
            ],
            "items": items[:100],
        }
