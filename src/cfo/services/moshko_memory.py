"""ליבת הזיכרון הלומד של מושקו (חבילה E,
docs/superpowers/plans/2026-07-27b-moshko-memory-and-whatsapp.md).

הפניית העיצוב: Hermes Agent (Nous Research) — שני scope בדיוק (עסק/משתמש),
הזרקה קפואה לפרומפט (לא retrieval, אין vector DB), תקרת-תווים שכופה אוצרות.
אנחנו מאמצים את הצורה אבל מאחסנים ב-Postgres (טבלת MoshkoMemory) כי רצף
רצה serverless ורב-דיירת — לא קבצים על דיסק מתמיד כמו הרמס.

honest-null חל גם כאן: הזיכרון שומר עובדות הצהרתיות, העדפות, ומוסכמות —
לעולם לא מספרים פיננסיים (יתרות, סכומים, נתונים משתנים). כל מספר עדיין
מגיע מקריאת כלי טרייה בתור הנוכחי (ראו ההנחיה שנוספה ל-BASE_SYSTEM_PROMPT
ב-ai_chat_personas.py).

כל הפעולות org-scoped; זיכרון אישי מסונן לפי user_id — משתמש אחד לעולם
אינו רואה את הזיכרון האישי של משתמש אחר באותו ארגון.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import MoshkoMemory

# בקנה מידה של הרמס (ראו התכנית) — תקרת תווים פר-scope שכופה על מושקו
# לאחד/למחוק רשומות ישנות במקום להתנפח בלי גבול.
# W1.4 (20/08/2026): 2000 חנק את לולאת האימון — תיקון admin מתקבל עד
# 8000 תווים אבל קידומו נחסם על התקרה. 6000 מכיל תיקון מלא + זיכרונות.
ORG_MEMORY_CHAR_CAP = 6000
USER_MEMORY_CHAR_CAP = 1500

# מעל 80% מהתקרה — עדיין כותב, אבל מצרף אזהרה לאחד רשומות (בדיוק כמו
# ברמס: כתיבה תמיד מצליחה אם יש מקום, האזהרה היא רמז מוקדם, לא חסימה).
CONSOLIDATION_THRESHOLD = 0.8

_VALID_CATEGORIES = {"preference", "business_fact", "correction", "convention"}
_VALID_SOURCES = {"conversation", "admin", "inferred"}


def _normalize(content: str) -> str:
    return (content or "").strip()


def _dedup_key(content: str) -> str:
    return _normalize(content).casefold()


def _scope_rows(db: Session, organization_id: int, target_user_id: Optional[int]) -> list[MoshkoMemory]:
    """שורות בדיוק בתוך scope אחד: org (target_user_id=None, user_id IS
    NULL בטבלה) או משתמש ספציפי (target_user_id=X, user_id == X בטבלה).
    לעולם לא מערבב את שני ה-scope-ים — כל פעולת כתיבה/עדכון/מחיקה פועלת
    בתוך scope בודד."""
    query = db.query(MoshkoMemory).filter(MoshkoMemory.organization_id == organization_id)
    if target_user_id is None:
        query = query.filter(MoshkoMemory.user_id.is_(None))
    else:
        query = query.filter(MoshkoMemory.user_id == target_user_id)
    return query.order_by(MoshkoMemory.id.asc()).all()


def _chars_used(rows: list[MoshkoMemory]) -> int:
    return sum(len(r.content) for r in rows)


def _usage_for(rows: list[MoshkoMemory], cap: int) -> dict[str, Any]:
    chars = _chars_used(rows)
    return {
        "chars": chars,
        "cap": cap,
        "pct": round(chars / cap, 4) if cap else 0.0,
    }


def remember(
    db: Session, organization_id: int, *,
    content: str, scope: str = "org", user_id: Optional[int] = None,
    category: str = "business_fact", source: str = "conversation",
) -> dict[str, Any]:
    """כותב עובדה הצהרתית אחת. אוכף תקרת-תווים פר-scope (לא כותב אם
    חורג), מדדף תוכן זהה (case-fold, ללא כפילויות), ומזהיר בחצייה של
    CONSOLIDATION_THRESHOLD."""
    if scope not in ("org", "user"):
        raise ValueError("scope חייב להיות 'org' או 'user'")
    if scope == "user" and user_id is None:
        raise ValueError("scope='user' דורש user_id")
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"category לא תקין: {category}")
    if source not in _VALID_SOURCES:
        raise ValueError(f"source לא תקין: {source}")

    normalized = _normalize(content)
    if not normalized:
        raise ValueError("תוכן זיכרון ריק")

    target_user_id = user_id if scope == "user" else None
    cap = USER_MEMORY_CHAR_CAP if scope == "user" else ORG_MEMORY_CHAR_CAP

    rows = _scope_rows(db, organization_id, target_user_id)

    # דדופ: תוכן זהה (normalized) באותו scope — לא כפילות, רק מרענן
    # updated_at ומחזיר already_known.
    dedup_key = _dedup_key(normalized)
    for row in rows:
        if _dedup_key(row.content) == dedup_key:
            row.updated_at = datetime.utcnow()
            db.commit()
            return {
                "status": "already_known",
                "id": row.id,
                "content": row.content,
                "usage": _usage_for(rows, cap),
            }

    current_chars = _chars_used(rows)
    projected = current_chars + len(normalized)
    if projected > cap:
        return {
            "status": "cap_reached",
            "message": "הגעת לתקרת התווים של הזיכרון — יש לאחד או למחוק זיכרונות קודמים לפני הוספת עובדה חדשה.",
            "usage": {"chars": current_chars, "cap": cap, "pct": round(current_chars / cap, 4) if cap else 0.0},
        }

    row = MoshkoMemory(
        organization_id=organization_id, user_id=target_user_id,
        content=normalized, category=category, source=source,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        # W1.4: "תזכור ש..." הוא הוראה מפורשת של המשתמש — זה האישור.
        # בלעדי זה, אכיפת approved_at בהזרקה הייתה משתיקה את כלי הזיכרון.
        approved_at=datetime.utcnow(),
        approved_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    result: dict[str, Any] = {
        "status": "ok",
        "id": row.id,
        "content": row.content,
        "usage": {"chars": projected, "cap": cap, "pct": round(projected / cap, 4) if cap else 0.0},
    }
    if projected > cap * CONSOLIDATION_THRESHOLD:
        result["warning"] = "מתקרב לתקרת הזיכרון — שקול לאחד רשומות."
    return result


def _find_by_match(rows: list[MoshkoMemory], match: str) -> list[MoshkoMemory]:
    needle = _normalize(match).casefold()
    return [r for r in rows if needle in r.content.casefold()]


def update_memory(
    db: Session, organization_id: int, *,
    match: str, content: str, user_id: Optional[int] = None,
) -> dict[str, Any]:
    """מעדכן זיכרון קיים בהתאמת תת-מחרוזת (case-insensitive), בתוך scope
    בודד: user_id=None = זיכרון עסק, user_id=X = הזיכרון האישי של X בלבד.
    התאמה מרובה — לא מבצע, מחזיר מועמדים ומבקש ניסוח מדויק יותר (בטיחות:
    'תעדכן X' לא ישנה כמה זיכרונות בטעות)."""
    rows = _scope_rows(db, organization_id, user_id)
    matches = _find_by_match(rows, match)

    if not matches:
        return {"status": "not_found", "message": f"לא נמצא זיכרון התואם ל-'{match}'"}
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "message": "נמצאו כמה זיכרונות תואמים — נסח התאמה מדויקת יותר לפני עדכון.",
            "candidates": [{"id": r.id, "content": r.content} for r in matches],
        }

    normalized = _normalize(content)
    if not normalized:
        raise ValueError("תוכן זיכרון ריק")

    row = matches[0]
    # אכיפת תקרה גם כאן — לא רק ב-remember. בלי זה, מודל שנחסם ע"י
    # cap_reached ב-add יכול לעקוף את התקרה דרך update על שורה קצרה עם
    # content ארוך בהרבה: התקרה היא "המנגנון היחיד שמונע התנפחות" של
    # הבלוק המוזרק לכל תור (ראו התכנית) — היא חייבת לחול על כל כתיבה,
    # לא רק על add.
    cap = USER_MEMORY_CHAR_CAP if user_id is not None else ORG_MEMORY_CHAR_CAP
    current_chars = _chars_used(rows)
    projected = current_chars - len(row.content) + len(normalized)
    if projected > cap:
        return {
            "status": "cap_reached",
            "message": "העדכון חורג מתקרת התווים של הזיכרון — יש לקצר את התוכן או למחוק זיכרונות אחרים תחילה.",
            "usage": {"chars": current_chars, "cap": cap, "pct": round(current_chars / cap, 4) if cap else 0.0},
        }

    row.content = normalized
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "id": row.id, "content": row.content}


def forget(
    db: Session, organization_id: int, *,
    match: str, user_id: Optional[int] = None,
) -> dict[str, Any]:
    """מוחק זיכרון קיים בהתאמת תת-מחרוזת (case-insensitive), בתוך scope
    בודד. התאמה מרובה — לא מוחק, מחזיר מועמדים."""
    rows = _scope_rows(db, organization_id, user_id)
    matches = _find_by_match(rows, match)

    if not matches:
        return {"status": "not_found", "message": f"לא נמצא זיכרון התואם ל-'{match}'"}
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "message": "נמצאו כמה זיכרונות תואמים — נסח התאמה מדויקת יותר לפני מחיקה.",
            "candidates": [{"id": r.id, "content": r.content} for r in matches],
        }

    row = matches[0]
    deleted_content = row.content
    db.delete(row)
    db.commit()
    return {"status": "ok", "deleted_content": deleted_content}


def list_memories(db: Session, organization_id: int, *, user_id: Optional[int] = None) -> list[dict[str, Any]]:
    """כל הזיכרונות הנראים למשתמש הנתון: עובדות העסק (user_id=None
    בטבלה) בתוספת הזיכרון האישי שלו, אם ניתן user_id. בלי user_id —
    רק עובדות העסק."""
    rows = list(_scope_rows(db, organization_id, None))
    if user_id is not None:
        rows += _scope_rows(db, organization_id, user_id)
    return [
        {
            "id": r.id,
            "scope": "org" if r.user_id is None else "user",
            "content": r.content,
            "category": r.category,
            "source": r.source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def usage(db: Session, organization_id: int, user_id: Optional[int] = None) -> dict[str, Any]:
    org_rows = _scope_rows(db, organization_id, None)
    result: dict[str, Any] = {"org": _usage_for(org_rows, ORG_MEMORY_CHAR_CAP)}
    if user_id is not None:
        user_rows = _scope_rows(db, organization_id, user_id)
        result["user"] = _usage_for(user_rows, USER_MEMORY_CHAR_CAP)
    return result


def render_memory_block(db: Session, organization_id: int, user_id: Optional[int]) -> str:
    """מחזיר את שני בלוקי הזיכרון (עסק/משתמש) בעברית להזרקה קפואה
    לפרומפט. מחרוזת ריקה אם אין זיכרונות בכלל — לעולם לא כותרות ריקות.

    W1.4 (20/08/2026): רק זיכרונות **מאושרים** מוזרקים — עד עכשיו
    `approved_at` היה דקורטיבי וכפתור "ביטול אישור" לא שינה דבר.
    כל זיכרון שהוזרק נחתם `last_used_at` (בלי commit — התור השולח
    מבצע commit), כדי שאפשר יהיה למדוד מה באמת משפיע.
    """
    now = datetime.utcnow()

    def _approved(rows: list[MoshkoMemory]) -> list[MoshkoMemory]:
        return [r for r in rows if r.approved_at is not None]

    org_rows = _approved(_scope_rows(db, organization_id, None))
    user_rows = (
        _approved(_scope_rows(db, organization_id, user_id))
        if user_id is not None else []
    )

    blocks: list[str] = []
    if org_rows:
        lines = "\n".join(f"- {r.content}" for r in org_rows)
        blocks.append(f"## מה אני יודע על העסק\n{lines}")
    if user_rows:
        lines = "\n".join(f"- {r.content}" for r in user_rows)
        blocks.append(f"## מה אני יודע עליך\n{lines}")

    for row in (*org_rows, *user_rows):
        row.last_used_at = now

    return "\n\n".join(blocks)
