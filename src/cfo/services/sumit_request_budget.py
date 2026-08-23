"""Database-backed hard ceilings for every outbound SUMIT API request.

The daily sync checkpoint limits jobs, not requests.  This guard sits at the
network boundary and uses atomic upserts, so concurrent Vercel instances share
the same burst and paid-action budget instead of each keeping a local counter.
"""
from __future__ import annotations

import hashlib
from calendar import monthrange
from datetime import datetime, timezone

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..database import SessionLocal
from ..models import ProviderRequestBudget


def _db_now(db) -> datetime:
    """P0-A תיקון 2 (סקירת קודקס 23/08/2026) — זמן קנוני מה-DB, לא
    משעון-התהליך. שני instances של Vercel עם שעוני-מערכת שונים
    (לדוגמה סביב תפנית חודש) שהיו נגזרים כל אחד משעון-התהליך שלו יכלו
    לתבוע `window_start` שונה לאותו רגע אמיתי — כל אחד מקבל תקציב
    חודשי נפרד משלו. ה-DB (Postgres/Neon אחד משותף לכל ה-instances)
    הוא מקור-זמן יחיד; שאילתה עליו סוגרת את הפער.

    **לא** בולעת שגיאה: אם השאילתה נכשלת, `SQLAlchemyError` עולה
    למעלה כרגיל ונתפסת ע"י ה-`except SQLAlchemyError` הקיים בכל קורא —
    fail-closed, לא נפילה חזרה לשעון-תהליך בשקט.
    """
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        value = db.execute(text("SELECT now()")).scalar()
    elif dialect == "sqlite":
        value = db.execute(text("SELECT CURRENT_TIMESTAMP")).scalar()
    else:  # pragma: no cover - production/test dialects are explicit
        raise SumitRequestBudgetUnavailable(
            f"unsupported dialect for canonical time: {dialect}",
        )
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


class SumitRequestBudgetError(RuntimeError):
    """Base class for fail-closed SUMIT budget errors."""


class SumitRequestBudgetExceeded(SumitRequestBudgetError):
    """The current shared minute or organization-day window is full."""


class SumitRequestBudgetUnavailable(SumitRequestBudgetError):
    """The durable counter could not be proven/updated."""


# ריצת סנכרון אחת ביום לכל מפתח (הנחיית הבעלים, 17/08/2026). המספר עצמו
# הוא ההנחיה — לא ערך ניתן-לכיוונון שנשחק בהדרגה, ולכן הוא קבוע ולא Setting.
DAILY_SYNC_RUNS_PER_KEY = 1


def key_fingerprint(api_key: str | None) -> str:
    """טביעת-אצבע חד-כיוונית של מפתח API, לשימוש כ-`scope_key`.

    למה hash ולא המפתח: `scope_key` נכתב ל-DB ומופיע בלוגים ובהודעות
    שגיאה. מפתח שנשמר שם הוא מפתח שדלף.

    למה יציב בין תהליכים: כל instance של Vercel תובע את אותו חלון. hash
    לא-דטרמיניסטי (כמו `hash()` של פייתון, שמשתנה בין תהליכים) היה נותן
    לכל instance חלון משלו — כלומר מגבלה שאינה קיימת.
    """
    if not isinstance(api_key, str) or not api_key.strip():
        # fail-closed ובקול: מפתח ריק היה ממפה את כל הארגונים לאותו חלון,
        # כך שארגון בלי מפתח היה חוסם את כל השאר.
        raise SumitRequestBudgetUnavailable(
            "לא ניתן לתבוע חלון סנכרון יומי בלי מפתח SUMIT תקף",
        )
    digest = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()
    return f"key:{digest[:16]}"


def claim_daily_sync_run(api_key: str | None, *, organization_id: int) -> None:
    """תובע את חלון הסנכרון היומי **של המפתח**. נקרא פעם אחת בתחילת ריצה.

    זו אינה מגבלת בקשות-HTTP: ריצה אחת מוציאה עשרות בקשות (עימוד, ריבוי
    ישויות), ומגבלה מילולית של בקשה אחת הייתה שוברת את הסנכרון. המגבלה
    היא על **הריצה**.

    למה פר-מפתח ולא פר-ארגון: `SumitRequestLimiter.claim` תובע לפי
    `org:{id}`, אבל `SUMIT_OFFICE_API_KEY` הוא הגדרה גלובלית אחת המשרתת
    את כל הארגונים. עם scope לפי ארגון, N ארגונים שורפים כל אחד מכסה
    מלאה על אותו מפתח — והמכסה בתשלום היא 50.
    """
    scope_key = key_fingerprint(api_key)
    db = SessionLocal()
    try:
        with db.begin():
            # P0-A תיקון 2: זמן קנוני מה-DB, לא משעון-התהליך — ראו _db_now.
            now = _db_now(db)
            _, day_start, _ = _utc_windows(now)
            claimed = SumitRequestLimiter._claim_window(
                db,
                scope_key=scope_key,
                organization_id=organization_id,
                window_kind="day",
                window_start=day_start,
                limit_value=DAILY_SYNC_RUNS_PER_KEY,
                now=now,
            )
        if not claimed:
            raise SumitRequestBudgetExceeded(
                f"מפתח SUMIT זה כבר ביצע את ריצת הסנכרון היומית שלו "
                f"({DAILY_SYNC_RUNS_PER_KEY}/יום). הריצה נדחתה — לא נשלחה "
                "שום בקשה. הנתונים ברצף הם המראה של המשיכה האחרונה."
            )
    except SumitRequestBudgetError:
        raise
    except SQLAlchemyError as exc:
        raise SumitRequestBudgetUnavailable(
            "חלון הסנכרון היומי לא ניתן לתביעה; הריצה נדחתה",
        ) from exc
    finally:
        db.close()


def _utc_windows(now: datetime) -> tuple[datetime, datetime, datetime]:
    minute = now.replace(second=0, microsecond=0)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return minute, day, month


def paced_daily_limit(
    *, configured_daily: int, monthly_limit: int, month_used: int,
    day_used: int = 0, days_left: int, provider_remaining: int | None = None,
) -> int:
    """W2.3 — התקרה היומית האפקטיבית נגזרת מהיתרה החודשית.

    בלי זה, 20/יום × 30 ימים = 600 מול 200/חודש: המכסה נשרפת עד יום ~10
    ואז המערכת חסומה עד סוף החודש. הקצב מפזר את היתרה על הימים שנותרו:
    `min(היומי המוגדר, ceil((יתרה + שימוש-היום) / ימים שנותרו))`.

    שימוש-היום מוחזר לחישוב כדי שההקצבה תישאר יציבה לאורך היום: בלעדיו
    כל תביעה מקטינה את היתרה החודשית ולכן מכווצת את ההקצבה תוך-כדי-יום,
    וסדרת תביעות לגיטימית נחסמת באמצע למרות שההקצבה של הבוקר טרם נוצלה.

    `provider_remaining` — P0-A תיקון 5 (סקירת קודקס 23/08): כשניתן,
    נגזרת ממנו תקרת-ספק יומית נפרדת. בניגוד ליתרה הפנימית, אין מוסיפים
    לה `day_used`: המדידה מהספק קבועה עד הרענון הבא, והוספת claims של
    היום הייתה מגדילה את התקרה תוך-יום (2 לשני ימים: 1 בבוקר, 2 אחרי
    claim אחד). לכן ה-provider pace נשאר קבוע/מצטמצם עד מדידה חדשה.
    """
    days = max(1, days_left)
    internal_remaining = max(0, monthly_limit - month_used)
    internal_daily = -(
        -(internal_remaining + max(0, day_used)) // days
    )
    limits = [configured_daily, internal_daily]
    if provider_remaining is not None:
        provider_daily = -(-max(0, provider_remaining) // days)
        limits.append(provider_daily)
    return min(limits)


class SumitRequestLimiter:
    """Claim one global-minute slot and one per-org UTC-day slot atomically."""

    def __init__(
        self,
        organization_id: int,
        *,
        per_minute_limit: int | None = None,
        daily_limit: int | None = None,
    ):
        if organization_id <= 0:
            raise ValueError("a positive organization_id is required for SUMIT")
        self.organization_id = organization_id
        # Callers may lower a ceiling (tests and emergency controls), never
        # raise it above the code-owned maximum in Settings.
        self.per_minute_limit = min(
            settings.sumit_global_requests_per_minute,
            per_minute_limit if per_minute_limit is not None
            else settings.sumit_global_requests_per_minute,
        )
        self.daily_limit = min(
            settings.sumit_org_daily_request_limit,
            daily_limit if daily_limit is not None
            else settings.sumit_org_daily_request_limit,
        )

    @staticmethod
    def _claim_window(
        db,
        *,
        scope_key: str,
        organization_id: int | None,
        window_kind: str,
        window_start: datetime,
        limit_value: int,
        now: datetime,
        provider: str = "sumit",
    ) -> bool:
        if limit_value <= 0:
            return False
        table = ProviderRequestBudget.__table__
        values = {
            "provider": provider,
            "scope_key": scope_key,
            "organization_id": organization_id,
            "window_kind": window_kind,
            "window_start": window_start,
            "used": 1,
            "limit_value": limit_value,
            "updated_at": now,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(table).values(**values)
        elif dialect == "sqlite":
            statement = sqlite_insert(table).values(**values)
        else:  # pragma: no cover - production/test dialects are explicit
            raise SumitRequestBudgetUnavailable(
                f"unsupported request-budget dialect: {dialect}",
            )
        statement = statement.on_conflict_do_update(
            index_elements=[
                table.c.provider,
                table.c.scope_key,
                table.c.window_kind,
                table.c.window_start,
            ],
            set_={
                "used": table.c.used + 1,
                "limit_value": limit_value,
                "updated_at": now,
            },
            where=table.c.used < limit_value,
        ).returning(table.c.used)
        return db.execute(statement).scalar_one_or_none() is not None

    @staticmethod
    def _lock_window(
        db,
        *,
        scope_key: str,
        organization_id: int | None,
        window_kind: str,
        window_start: datetime,
        now: datetime,
        provider: str = "sumit",
    ) -> None:
        """Ensure a durable coordination row exists and lock it to commit.

        The insert closes the absent-row race; ``SELECT ... FOR UPDATE`` then
        serializes every transaction using the same logical window. SQLite
        ignores the row-lock clause but still exercises the ordering/guards in
        offline tests; PostgreSQL/Neon provides the production lock semantics.
        """
        table = ProviderRequestBudget.__table__
        values = {
            "provider": provider,
            "scope_key": scope_key,
            "organization_id": organization_id,
            "window_kind": window_kind,
            "window_start": window_start,
            "used": 0,
            "limit_value": 0,
            "updated_at": now,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(table).values(**values)
        elif dialect == "sqlite":
            statement = sqlite_insert(table).values(**values)
        else:  # pragma: no cover - production/test dialects are explicit
            raise SumitRequestBudgetUnavailable(
                f"unsupported request-budget dialect: {dialect}",
            )
        db.execute(statement.on_conflict_do_nothing(
            index_elements=[
                table.c.provider,
                table.c.scope_key,
                table.c.window_kind,
                table.c.window_start,
            ],
        ))
        (
            db.query(ProviderRequestBudget.id)
            .filter(
                ProviderRequestBudget.provider == provider,
                ProviderRequestBudget.scope_key == scope_key,
                ProviderRequestBudget.window_kind == window_kind,
                ProviderRequestBudget.window_start == window_start,
            )
            .with_for_update()
            .one()
        )

    @staticmethod
    def _window_used(
        db, *, scope_key: str, window_kind: str, window_start: datetime,
    ) -> int:
        """קריאת מונה חלון קיים (0 אם אין) — לצורך חישוב הקצב היומי."""
        row = (
            db.query(ProviderRequestBudget.used)
            .filter(
                ProviderRequestBudget.provider == "sumit",
                ProviderRequestBudget.scope_key == scope_key,
                ProviderRequestBudget.window_kind == window_kind,
                ProviderRequestBudget.window_start == window_start,
            )
            .first()
        )
        return int(row[0]) if row else 0

    @staticmethod
    def _seed_window_floor(
        db, *, scope_key: str, organization_id: int | None, window_kind: str,
        window_start: datetime, used: int, limit_value: int, now: datetime,
        provider: str = "sumit",
    ) -> None:
        """P0-A תיקון 1 — קובע רצפת-`used` ראשונית לחלון (לא +1 כמו
        `_claim_window`). משמש למרוץ-הדורות של `since_snapshot`: 'שריון'
        תביעות מהדור הקודם שעדיין לא הוכח שנספגו במדידת הספק, לתוך חלון
        הדור החדש — לפני שהוא נפתח לתביעות אמיתיות.

        `GREATEST`/`MAX` בעדכון: לעולם לא **מוריד** used קיים (אם חלון
        כבר נתבע בפועל בינתיים), רק מבטיח רצפה.
        """
        if used <= 0:
            return
        table = ProviderRequestBudget.__table__
        seeded = min(used, max(0, limit_value))
        values = {
            "provider": provider, "scope_key": scope_key,
            "organization_id": organization_id, "window_kind": window_kind,
            "window_start": window_start, "used": seeded,
            "limit_value": max(0, limit_value), "updated_at": now,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(table).values(**values)
            greatest = func.greatest(table.c.used, statement.excluded.used)
        elif dialect == "sqlite":
            statement = sqlite_insert(table).values(**values)
            greatest = func.max(table.c.used, statement.excluded.used)
        else:  # pragma: no cover - production/test dialects are explicit
            raise SumitRequestBudgetUnavailable(
                f"unsupported request-budget dialect: {dialect}",
            )
        statement = statement.on_conflict_do_update(
            index_elements=[
                table.c.provider, table.c.scope_key,
                table.c.window_kind, table.c.window_start,
            ],
            set_={
                "used": greatest,
                "limit_value": max(0, limit_value),
                "updated_at": now,
            },
        )
        db.execute(statement)

    def claim(self, endpoint: str) -> None:
        """Consume both slots before the HTTP client is allowed to run.

        `endpoint` is accepted for call-site diagnostics but deliberately not
        persisted; request bodies and credentials never enter this table.
        """
        del endpoint
        # פר-ארגון (הכרעת בעלים 19/08): מכסת מסלול הבדיקות של SUMIT היא
        # ~400 לכל עסק, ולכן 200 לכל ארגון הם שולי ביטחון של 50% — לא
        # תקציב משותף שגוזל ארגון מארגון. W2.2 (20/08): גם ל-live יש
        # בלם חודשי — בלעדיו התקרה האפקטיבית הייתה 300/יום ללא סוף חודש.
        if settings.sumit_environment == "test":
            monthly_limit = settings.sumit_test_monthly_request_limit
        else:
            monthly_limit = settings.sumit_live_monthly_request_limit
        db = SessionLocal()
        try:
            with db.begin():
                # P0-A תיקון 2: זמן קנוני מה-DB, לא משעון-התהליך.
                now = _db_now(db)
                minute_start, day_start, month_start = _utc_windows(now)
                minute_ok = self._claim_window(
                    db,
                    scope_key="global",
                    organization_id=None,
                    window_kind="minute",
                    window_start=minute_start,
                    limit_value=self.per_minute_limit,
                    now=now,
                )
                if not minute_ok:
                    raise SumitRequestBudgetExceeded(
                        "SUMIT global minute request budget exceeded",
                    )
                # W2.3 — קצב: היתרה החודשית מתפזרת על הימים שנותרו במקום
                # להישרף בתחילת החודש ולחסום את סופו. החודש נתבע לפני
                # היום כדי שמיצוי חודשי ידווח "monthly" ולא "daily";
                # כישלון יומי מגלגל את התביעה החודשית אחורה (אותה טרנזקציה).
                month_used = self._window_used(
                    db,
                    scope_key=f"org:{self.organization_id}",
                    window_kind="month",
                    window_start=month_start,
                )
                day_used = self._window_used(
                    db,
                    scope_key=f"org:{self.organization_id}",
                    window_kind="day",
                    window_start=day_start,
                )
                days_in_month = monthrange(now.year, now.month)[1]
                effective_daily = paced_daily_limit(
                    configured_daily=self.daily_limit,
                    monthly_limit=monthly_limit,
                    month_used=month_used,
                    day_used=day_used,
                    days_left=days_in_month - now.day + 1,
                )
                month_ok = self._claim_window(
                    db,
                    scope_key=f"org:{self.organization_id}",
                    organization_id=self.organization_id,
                    window_kind="month",
                    window_start=month_start,
                    limit_value=monthly_limit,
                    now=now,
                )
                if not month_ok:
                    raise SumitRequestBudgetExceeded(
                        "SUMIT monthly request budget exceeded"
                        if settings.sumit_environment == "live"
                        else "SUMIT test monthly request budget exceeded",
                    )
                day_ok = self._claim_window(
                    db,
                    scope_key=f"org:{self.organization_id}",
                    organization_id=self.organization_id,
                    window_kind="day",
                    window_start=day_start,
                    limit_value=effective_daily,
                    now=now,
                )
                if not day_ok:
                    raise SumitRequestBudgetExceeded(
                        "SUMIT organization daily request budget exceeded",
                    )
        except SumitRequestBudgetExceeded:
            raise
        except SQLAlchemyError as exc:
            raise SumitRequestBudgetUnavailable(
                "SUMIT request budget could not be persisted; request refused",
            ) from exc
        finally:
            db.close()
