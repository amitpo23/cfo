"""Database-backed hard ceilings for every outbound SUMIT API request.

The daily sync checkpoint limits jobs, not requests.  This guard sits at the
network boundary and uses atomic upserts, so concurrent Vercel instances share
the same burst and paid-action budget instead of each keeping a local counter.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..database import SessionLocal
from ..models import ProviderRequestBudget


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
    now = datetime.now(timezone.utc)
    _, day_start, _ = _utc_windows(now)
    db = SessionLocal()
    try:
        with db.begin():
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
    ) -> bool:
        if limit_value <= 0:
            return False
        table = ProviderRequestBudget.__table__
        values = {
            "provider": "sumit",
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

    def claim(self, endpoint: str) -> None:
        """Consume both slots before the HTTP client is allowed to run.

        `endpoint` is accepted for call-site diagnostics but deliberately not
        persisted; request bodies and credentials never enter this table.
        """
        del endpoint
        now = datetime.now(timezone.utc)
        minute_start, day_start, month_start = _utc_windows(now)
        db = SessionLocal()
        try:
            with db.begin():
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
                day_ok = self._claim_window(
                    db,
                    scope_key=f"org:{self.organization_id}",
                    organization_id=self.organization_id,
                    window_kind="day",
                    window_start=day_start,
                    limit_value=self.daily_limit,
                    now=now,
                )
                if not day_ok:
                    raise SumitRequestBudgetExceeded(
                        "SUMIT organization daily request budget exceeded",
                    )
                if settings.sumit_environment == "test":
                    # פר-ארגון (הכרעת בעלים 19/08): מכסת מסלול הבדיקות של
                    # SUMIT היא ~400 לכל עסק, ולכן 200 לכל ארגון הם שולי
                    # ביטחון של 50% — לא תקציב משותף שגוזל ארגון מארגון.
                    month_ok = self._claim_window(
                        db,
                        scope_key=f"org:{self.organization_id}",
                        organization_id=self.organization_id,
                        window_kind="month",
                        window_start=month_start,
                        limit_value=settings.sumit_test_monthly_request_limit,
                        now=now,
                    )
                    if not month_ok:
                        raise SumitRequestBudgetExceeded(
                            "SUMIT test monthly request budget exceeded",
                        )
        except SumitRequestBudgetExceeded:
            raise
        except SQLAlchemyError as exc:
            raise SumitRequestBudgetUnavailable(
                "SUMIT request budget could not be persisted; request refused",
            ) from exc
        finally:
            db.close()
