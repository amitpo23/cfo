"""כרטיסי הוצאה מותאמים אישית לארגון (ExpenseCategory) — CRUD, מוצג לצד
הקטגוריות המובנות (VALID_CATEGORIES ב-expense_classifier.py) בממשק אחד.

מודול פונקציות (לא class), כמו contact_service.py / collection_case_service.py —
נצרך גם מ-routes/expenses.py וגם מ-ai_chat_tools.py.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from ..models import Expense, ExpenseCategory
from .expense_classifier import CATEGORY_NAMES_HE, VALID_CATEGORIES


class CategoryInUseError(ValueError):
    """נזרקת כש-DELETE מבוקש על קטגוריה שהוצאות עדיין משתמשות בה. נושאת את
    המונה כדי שה-route יוכל להחזיר 409 עם הכמות (לא רק הודעת טקסט)."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(f"לא ניתן למחוק — הקטגוריה בשימוש ב-{count} הוצאות")


def _serialize(c: ExpenseCategory) -> Dict:
    return {
        "id": c.id,
        "key": c.key,
        "name_he": c.name_he,
        "keywords": c.keywords or [],
        "built_in": False,
    }


def list_categories(db: Session, organization_id: int) -> List[Dict]:
    """כרטיסים מובנים (built_in=True, id=None) + כרטיסים מותאמים אישית של
    הארגון (built_in=False), ממוינים: מובנים קודם, לפי מפתח; אחר כך מותאמים
    לפי סדר יצירה."""
    built_in = [
        {"id": None, "key": key, "name_he": CATEGORY_NAMES_HE.get(key, key),
         "keywords": None, "built_in": True}
        for key in sorted(VALID_CATEGORIES)
    ]
    custom = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.organization_id == organization_id)
        .order_by(ExpenseCategory.created_at.asc(), ExpenseCategory.id.asc())
        .all()
    )
    return built_in + [_serialize(c) for c in custom]


def org_category_keys(db: Session, organization_id: int) -> Set[str]:
    """כל מפתחות הכרטיסים המותאמים אישית של הארגון — לאימות PATCH category."""
    rows = (
        db.query(ExpenseCategory.key)
        .filter(ExpenseCategory.organization_id == organization_id)
        .all()
    )
    return {r[0] for r in rows}


def get_classifier_categories(db: Session, organization_id: int) -> List[Dict]:
    """כרטיסי הארגון שיש להם keywords — לשימוש ב-classify_expense(org_categories=...).
    כרטיסים בלי keywords אינם משתתפים בסיווג האוטומטי (הם עדיין תקפים לשיוך ידני)."""
    rows = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.organization_id == organization_id)
        .order_by(ExpenseCategory.created_at.asc(), ExpenseCategory.id.asc())
        .all()
    )
    return [{"key": r.key, "keywords": r.keywords} for r in rows if r.keywords]


def create_category(
    db: Session, organization_id: int, *, key: str, name_he: str,
    keywords: Optional[List[str]] = None,
) -> Dict:
    key = (key or "").strip()
    name_he = (name_he or "").strip()
    if not key:
        raise ValueError("חובה לספק מפתח (key) לכרטיס")
    if not name_he:
        raise ValueError("חובה לספק שם תצוגה (name_he) לכרטיס")
    if key in VALID_CATEGORIES:
        raise ValueError(f"'{key}' הוא מפתח קטגוריה מובנית של המערכת — בחר מפתח אחר")
    existing = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.organization_id == organization_id, ExpenseCategory.key == key)
        .first()
    )
    if existing:
        raise ValueError(f"כרטיס עם המפתח '{key}' כבר קיים בארגון זה")

    category = ExpenseCategory(
        organization_id=organization_id, key=key, name_he=name_he,
        keywords=list(keywords) if keywords else None,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return _serialize(category)


def delete_category(db: Session, organization_id: int, category_id: int) -> None:
    category = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.organization_id == organization_id, ExpenseCategory.id == category_id)
        .first()
    )
    if not category:
        raise ValueError(f"כרטיס {category_id} לא נמצא")

    in_use = (
        db.query(Expense)
        .filter(Expense.organization_id == organization_id, Expense.category == category.key)
        .count()
    )
    if in_use:
        raise CategoryInUseError(in_use)

    db.delete(category)
    db.commit()
