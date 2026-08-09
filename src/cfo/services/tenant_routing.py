"""ניתוב חיבורי מסד לפי ארגון — שלב 0 של תוכנית ה-DB פר-ארגון.

הבעיה שזה פותר: `database.py` יוצר engine יחיד בזמן import
(`engine = create_engine(settings.database_url)`), ואין שום נקודה שבה
נבחר יעד לפי ארגון. כל 251 נקודות ה-`get_db_session` מדברות עם אותו
מסד ואינן יודעות שקיימת בכלל שאלה כזו.

**בשלב הזה השכבה אינה מפצלת דבר.** כל ארגון שלא נרשם לו DSN ייעודי
מקבל את ה-engine המשותף — אותו אובייקט בדיוק. אפס שינוי התנהגות, אפס
נתון שזז. מה שכן קורה: הגישה מתרכזת בנקודה אחת שיודעת מיהו הארגון,
ומכאן הפיצול בפועל הוא שינוי קונפיגורציה ולא ניתוח מחדש של 516
שאילתות.

ראה `docs/superpowers/plans/2026-08-08-db-per-tenant-plan.md`.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# המצב כאן הוא process-local. בפריסה מרובת-workers כל worker מחזיק עותק
# משלו, ולכן **טעינת הניתוב חייבת לקרות באתחול כל worker** ולא רק פעם
# אחת גלובלית; אחרת worker אחד ינתב לפי מפה ישנה (Codex QA 09/08).
# הנעילה מגנה מפני מרוץ בתוך worker: שני threads שמבקשים אותו ארגון
# בו-זמנית עלולים לבנות שני engines ולשמור רק אחד, ולהדליף pool.
_LOCK = threading.RLock()

# ארגון → DSN ייעודי. ריק עד שארגון ראשון מפוצל בפועל.
_TENANT_DSN: dict[int, str] = {}

# ארגון → engine בנוי. engine מוחזק ולא נבנה מחדש בכל בקשה: בנייה חוזרת
# פותחת חיבורים חדשים מול Neon ושורפת את מכסת החיבורים.
_TENANT_ENGINES: dict[int, Engine] = {}
_TENANT_SESSION_FACTORIES: dict[int, sessionmaker] = {}


def _shared_engine() -> Engine:
    """ה-engine ההיסטורי מ-`database.py`.

    מיובא בתוך הפונקציה ולא ברמת המודול כדי לא ליצור תלות מעגלית
    (`database` מייבא את `models`, ששירותים מייבאים בחזרה).
    """
    from ..database import engine

    return engine


def control_plane_engine() -> Engine:
    """מסד הבקרה — `users`, `organizations` ומיפוי ארגון→DSN.

    עד הפיצול בפועל זהו המסד המשותף. כשמסד הבקרה יופרד, רק הפונקציה
    הזו משתנה.
    """
    return _shared_engine()


def engine_for(organization_id: int | None) -> Engine:
    """ה-engine שדרכו נגישים הנתונים של ארגון נתון.

    `None` = הקשר שאינו שייך לארגון (בקרה, בריאות, אתחול).
    ארגון בלי DSN ייעודי מקבל את ה-engine המשותף — ההתנהגות הקיימת.
    """
    if organization_id is None:
        return _shared_engine()

    with _LOCK:
        cached = _TENANT_ENGINES.get(organization_id)
        if cached is not None:
            return cached

        dsn = _TENANT_DSN.get(organization_id)
        if dsn is None:
            return _shared_engine()

        from ..database import _engine_kwargs

        engine = create_engine(dsn, **_engine_kwargs())
        _TENANT_ENGINES[organization_id] = engine
        return engine


def _session_factory(organization_id: int | None) -> sessionmaker:
    if organization_id is not None and organization_id in _TENANT_DSN:
        factory = _TENANT_SESSION_FACTORIES.get(organization_id)
        if factory is None:
            factory = sessionmaker(
                autocommit=False, autoflush=False, bind=engine_for(organization_id)
            )
            _TENANT_SESSION_FACTORIES[organization_id] = factory
        return factory

    from ..database import SessionLocal

    return SessionLocal


@contextmanager
def session_for(organization_id: int | None) -> Generator[Session, None, None]:
    """סשן המכוון למסד של הארגון. נסגר תמיד, גם כשהגוף זורק."""
    db = _session_factory(organization_id)()
    try:
        yield db
    finally:
        db.close()


def register_tenant_dsn(organization_id: int, dsn: str) -> None:
    """מפנה ארגון למסד ייעודי. רק הוא מושפע; שאר הארגונים ממשיכים
    למסד המשותף — כך הפיצול נעשה ארגון-אחד-בכל-פעם.

    ה-engine הקודם נסגר במפורש: pool נטוש מחזיק חיבורים פתוחים מול
    Neon עד סוף התהליך, ובמסלול החינמי המכסה קטנה (Codex QA 09/08).
    """
    with _LOCK:
        _TENANT_DSN[organization_id] = dsn
        stale = _TENANT_ENGINES.pop(organization_id, None)
        _TENANT_SESSION_FACTORIES.pop(organization_id, None)
    if stale is not None:
        stale.dispose()


def split_organization_ids() -> list[int]:
    """הארגונים שכבר יושבים על מסד ייעודי.

    זהו הבסיס לאכיפת "הכול או כלום": מיגרציה חייבת לרוץ על מסד הבקרה
    ועל כל מסד שברשימה הזו, ולהצליח על כולם.
    """
    return sorted(_TENANT_DSN)


def reset_routing() -> None:
    """מנקה ניתוב ומשליך engines. לשימוש טסטים ואתחול מחדש."""
    with _LOCK:
        engines = list(_TENANT_ENGINES.values())
        _TENANT_DSN.clear()
        _TENANT_ENGINES.clear()
        _TENANT_SESSION_FACTORIES.clear()
    for engine in engines:
        engine.dispose()
