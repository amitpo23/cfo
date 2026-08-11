"""תיוק הוצאה לכרטיס באינדקס החשבונות של הארגון.

זו החוליה שהופכת אינדקס מיובא לשמיש: ל-org5 יש 1,004 כרטיסי חשבשבת
ב-`accounts` ו-15,060 פקודות יומן היסטוריות, אבל `expenses` החזיק רק
`category` כמחרוזת חופשית — בלי שום דרך להצביע לכרטיס.

הבהרת בעלים (10/08/2026): הוצאה שנכנסת דרך מודול העסק צריכה להיות
ניתנת לתיוק **לתוך האינדקס המיובא**, כך שאפשר יהיה להפיק דוחות מול
אותם כרטיסים שההנה"ח הקודמת עבדה מולם.

הבידוד הארגוני נאכף בכל פעולה: תיוק לכרטיס של תיק אחר הוא ערבוב ספרים
של שני לקוחות, ולכן נחסם ולא מתוקן בשקט.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session


class ExpenseFilingError(RuntimeError):
    """התיוק נעצר לפני שינוי כלשהו."""


# מילות רעש בשמות עסקים ישראליים ובשמות כרטיסים. הן מופיעות בעשרות
# רשומות ולכן אינן מזהות דבר.
#
# "ספק" נוסף אחרי שנתפס בהרצה על נתוני org5: "ספק מספוא" הוצע לכרטיס
# "אלון תבור-ספק" על סמך המילה הזו בלבד. התאמה חלשה גרועה מאין התאמה —
# היא נראית מכוונת, ומי שמאשר אותה מתייק לכרטיס של ספק אחר לגמרי.
_NOISE = {
    "בעמ", 'בע"מ', "בעm", "ltd", "בע", "ושות", "חברה", "עסק",
    "ספק", "ספקים", "לקוח", "לקוחות", "כללי", "שונים", "אחר", "sumit",
}

# מילה בודדת מתחת לאורך הזה אינה מזהה מספיק כדי להצדיק הצעה. מילה
# ייחודית ארוכה ("גלבוע") כן; חפיפה של שתי מילים ומעלה תמיד מספיקה.
_MIN_SINGLE_TOKEN_LENGTH = 4


def _normalize(text: str | None) -> str:
    """מנרמל שם לצורך השוואה: בלי ניקוד, גרשיים ורווחים כפולים."""
    cleaned = re.sub(r"[\"'`׳״.,\-_()]+", " ", (text or ""))
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _tokens(text: str | None) -> set[str]:
    return {t for t in _normalize(text).split() if len(t) > 1 and t not in _NOISE}


def file_expense_to_account(
    db: Session,
    organization_id: int,
    expense_id: int,
    account_id: int,
) -> dict[str, Any]:
    """מקשר הוצאה לכרטיס ומסמן אותה כמתויקת.

    תיוק חוזר מותר ומעביר לכרטיס החדש — תיקון תיוק שגוי הוא פעולה
    יומיומית של מנהל חשבונות, לא חריג שדורש מסלול מיוחד.
    """
    from ..models import Account, Expense

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.organization_id == organization_id)
        .first()
    )
    if expense is None:
        raise ExpenseFilingError(
            f"הוצאה {expense_id} אינה קיימת בארגון {organization_id}"
        )

    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None:
        raise ExpenseFilingError(f"כרטיס {account_id} אינו קיים")
    if account.organization_id != organization_id:
        raise ExpenseFilingError(
            f"כרטיס {account_id} שייך לארגון {account.organization_id} ולא "
            f"ל-{organization_id} — תיוק חוצה-ארגונים מערבב ספרים של שני לקוחות"
        )

    expense.account_id = account.id
    expense.status = "filed"
    db.commit()

    return {
        "expense_id": expense.id,
        "account_id": account.id,
        "source_account_code": account.source_account_code,
        "account_name": account.name,
        "status": expense.status,
    }


def suggest_accounts_for_expense(
    db: Session,
    organization_id: int,
    expense_id: int,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """כרטיסים מועמדים לתיוק ההוצאה, מדורגים.

    מנהל חשבונות אינו זוכר 1,004 קודים בעל-פה. ההתאמה נעשית על שם
    הספק מול שמות הכרטיסים באינדקס.

    honest-null: אין התאמה = רשימה ריקה. הצעה שרירותית גרועה מאין
    הצעה — היא מייצרת תיוק שגוי שנראה מכוון ואיש לא בודק אותו.
    """
    from ..models import Account, Expense

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.organization_id == organization_id)
        .first()
    )
    if expense is None:
        raise ExpenseFilingError(
            f"הוצאה {expense_id} אינה קיימת בארגון {organization_id}"
        )

    needle = _tokens(expense.supplier_name) | _tokens(expense.sumit_item_name)
    if not needle:
        return []

    scored: list[tuple[int, int, dict[str, Any]]] = []
    accounts = (
        db.query(Account)
        .filter(
            Account.organization_id == organization_id,
            Account.source_account_code.isnot(None),
        )
        .all()
    )
    for account in accounts:
        candidate = _tokens(account.name)
        overlap = needle & candidate
        if not overlap:
            continue
        # חפיפה של מילה בודדת מתקבלת רק כשהיא ייחודית מספיק. זה מה
        # שמפריד בין "גלבוע" (מזהה) לבין "ספק" (רעש).
        if len(overlap) == 1 and len(next(iter(overlap))) < _MIN_SINGLE_TOKEN_LENGTH:
            continue
        # דירוג: מספר המילים החופפות, ואז אורכן — "עדי דלקים" מנצח
        # התאמה על מילה קצרה ונפוצה אחת.
        scored.append(
            (
                len(overlap),
                sum(len(t) for t in overlap),
                {
                    "account_id": account.id,
                    "source_account_code": account.source_account_code,
                    "name": account.name,
                    "sort_code": account.sort_code,
                    "matched_on": sorted(overlap),
                },
            )
        )

    scored.sort(key=lambda row: (-row[0], -row[1], row[2]["source_account_code"]))
    return [row[2] for row in scored[:limit]]
