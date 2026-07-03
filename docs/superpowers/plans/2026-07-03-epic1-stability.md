# Epic 1 — יציבות ותשתית: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** בסיס אמין לכל האפיקים — suite ירוק, אפס 500 לא מוסברים, אפס schema drift מול Neon prod (כולל מנגנון מניעה קבוע), ואימות SUMIT write-back חי.

**Architecture:** אודיט-קודם: כל תיקון מבוסס על פגם מאומת בריצה. שלושה שערי אימות רב-פעמיים: pytest suite, `scripts/audit_routes.py` (מקומי), `scripts/prod_smoke.py` (חדש, HTTP מול הפרוד). מנגנון schema-sync additive משותף לסקריפט אבחון ול-endpoint המיגרציה.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pytest, httpx, Vercel CLI, Neon Postgres (prod), SQLite (מקומי/טסטים).

## Global Constraints

- הספק (spec): `docs/superpowers/specs/2026-07-03-epic1-stability-design.md`.
- שינויי סכמה בפרוד: **additive בלבד** (ADD COLUMN / CREATE TABLE). מחיקות — אסורות.
- כל קריאה חיה ל-SUMIT: עם backoff (403 קשיח אחרי ~250 קריאות מהירות; המתנה 30s ונסיון חוזר, עד 3 פעמים).
- קבצי env של פרוד נשמרים **רק** ב-scratchpad: `/private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/` — לעולם לא בתוך הרפו.
- טסטים רצים על SQLite; קוד DDL חייב לעבוד גם על SQLite וגם על Postgres (ל-SQLite אין `ADD COLUMN IF NOT EXISTS` — בודקים קיום לפני).
- שפת תקשורת ותיעוד: עברית; מזהי קוד באנגלית.
- הרצת suite מלא: `python -m pytest tests/ -q --tb=short` מ-`/Users/mymac/coding/cfo`. Baseline: 442 passed, 1 failed.

---

### Task 1: תיקון באג חציית-חודש ב-`_prorated_budget`

הטסט `test_weekly_budget_report_reads_real_budget` נכשל (`budget=0.0`) כי
`_prorated_budget` (analytics_reporting.py:227) שולף תקציב לפי
`start_date.year, start_date.month` בלבד. שבוע 29/6–5/7/2026 מתחיל ביוני,
אז תקציב שהוגדר ליולי לא נמצא. התיקון: שקלול פר-יום על פני כל החודשים
שהתקופה חוצה.

**Files:**
- Modify: `src/cfo/services/analytics_reporting.py:227-240` (הפונקציה `_prorated_budget`)
- Test: `tests/test_analytics_reporting_real.py` (הוספת טסט רגרסיה דטרמיניסטי)

**Interfaces:**
- Consumes: `BudgetService(db, org_id).get_budget_vs_actual(year, month)` → אובייקט עם `total_budget: float` ו-`categories` (לכל אחת `category_name`, `category_id`, `budget_amount: float`).
- Produces: אותה חתימה קיימת — `_prorated_budget(start_date, end_date) -> tuple[float, Dict[str, float]]`. אין שינוי צרכנים.

- [ ] **Step 1: כתיבת טסט רגרסיה דטרמיניסטי (תאריכים קבועים, לא date.today)**

להוסיף בסוף `tests/test_analytics_reporting_real.py`:

```python
def test_prorated_budget_spans_month_boundary(fresh_org):
    """שבוע שחוצה חודשים חייב לשקלל תקציב משני החודשים — לא רק מחודש ההתחלה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Budget(organization_id=org_id, category_name="rent",
                      year=2026, month=6, budgeted_amount=Decimal("3000")))
        db.add(Budget(organization_id=org_id, category_name="rent",
                      year=2026, month=7, budgeted_amount=Decimal("3100")))
        db.commit()
        svc = AnalyticsReportingService(db, org_id)
        # שבוע 2026-06-29 (שני) עד 2026-07-05 (ראשון): 2 ימי יוני + 5 ימי יולי
        total, by_cat = svc._prorated_budget(date(2026, 6, 29), date(2026, 7, 5))
    finally:
        db.close()

    expected = 3000 * (2 / 30) + 3100 * (5 / 31)  # 200 + 500 = 700
    assert abs(total - expected) < 0.01
    assert abs(by_cat["rent"] - expected) < 0.01
```

- [ ] **Step 2: הרצת שני הטסטים לוודא כישלון**

Run: `python -m pytest tests/test_analytics_reporting_real.py::test_prorated_budget_spans_month_boundary tests/test_analytics_reporting_real.py::test_weekly_budget_report_reads_real_budget -v -p no:warnings`
Expected: שניהם FAIL — החדש על `total==200 != 700` (רק יוני נספר), הקיים על `budget=0.0`.

- [ ] **Step 3: החלפת מימוש `_prorated_budget`**

להחליף את הפונקציה כולה ב-`src/cfo/services/analytics_reporting.py`:

```python
    def _prorated_budget(self, start_date: date, end_date: date) -> tuple[float, Dict[str, float]]:
        """תקציב התקופה: תקציב חודשי אמיתי מ-BudgetService, משוקלל פר-יום.

        תקופה שחוצה חודשים (למשל שבוע 29/6–5/7) נצברת מכל חודש לפי חלקו היחסי.
        """
        total = 0.0
        by_category: Dict[str, float] = {}
        seg_start = start_date
        while seg_start <= end_date:
            days_in_month = calendar.monthrange(seg_start.year, seg_start.month)[1]
            month_end = seg_start.replace(day=days_in_month)
            seg_end = min(end_date, month_end)
            factor = ((seg_end - seg_start).days + 1) / days_in_month
            summary = BudgetService(self.db, self.org_id).get_budget_vs_actual(
                seg_start.year, seg_start.month
            )
            total += summary.total_budget * factor
            for c in summary.categories:
                key = c.category_name or str(c.category_id)
                by_category[key] = by_category.get(key, 0.0) + c.budget_amount * factor
            seg_start = seg_end + timedelta(days=1)
        return total, by_category
```

- [ ] **Step 4: הרצת קובץ הטסטים המלא**

Run: `python -m pytest tests/test_analytics_reporting_real.py -v -p no:warnings`
Expected: כל הטסטים PASS (כולל שני הנכשלים מ-Step 2).

- [ ] **Step 5: הרצת suite מלא**

Run: `python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -5`
Expected: `443 passed` (442 קודמים + הרגרסיה החדשה), 0 failed.

- [ ] **Step 6: Commit**

```bash
git add src/cfo/services/analytics_reporting.py tests/test_analytics_reporting_real.py
git commit -m "fix(analytics): prorate weekly budget across month boundaries"
```

---

### Task 2: מודול schema-sync + סקריפט בדיקת drift גנרי

היום אין דרך גנרית לגלות drift (הסקריפט הקיים `fix_prod_schema_drift.py`
מכיל DDL קשיח של drift ספציפי מהעבר). בונים מודול השוואה גנרי:
מודלים (`Base.metadata`) מול הסכמה החיה (`inspect(engine)`).

**Files:**
- Create: `src/cfo/services/schema_sync.py`
- Create: `scripts/schema_drift_check.py`
- Test: `tests/test_schema_sync.py`

**Interfaces:**
- Consumes: `cfo.database.Base` (metadata של כל המודלים).
- Produces (ל-Task 3 ול-Task 7):
  - `compute_missing(engine) -> dict` בצורה `{"tables": [str], "columns": {table: [col_name]}}` — מה חסר בסכמה החיה יחסית למודלים.
  - `apply_additive(engine) -> dict` — מבצע את ההשלמות (טבלאות חסרות + עמודות חסרות), מחזיר את מה שבוצע באותה צורה. (המימוש ב-Task 3; כאן stub שזורק `NotImplementedError`.)

- [ ] **Step 1: כתיבת טסטים ל-compute_missing**

ליצור `tests/test_schema_sync.py`:

```python
"""schema_sync — גילוי גנרי של drift בין המודלים לסכמה החיה."""
import sqlalchemy as sa

from cfo.database import Base
from cfo.services.schema_sync import compute_missing


def _fresh_engine(tmp_path):
    return sa.create_engine(f"sqlite:///{tmp_path}/drift.db")


def test_no_drift_on_full_schema(tmp_path):
    """אחרי create_all מלא — אין שום דבר חסר."""
    engine = _fresh_engine(tmp_path)
    Base.metadata.create_all(engine)
    missing = compute_missing(engine)
    assert missing["tables"] == []
    assert missing["columns"] == {}


def test_detects_missing_table_and_column(tmp_path):
    """טבלה שלא נוצרה ועמודה שהוסרה — שתיהן מתגלות."""
    engine = _fresh_engine(tmp_path)
    tables = dict(Base.metadata.tables)
    victim_table = "collection_reminders"
    assert victim_table in tables, "מודל הייחוס לבדיקה לא קיים עוד — עדכן את הטסט"
    Base.metadata.create_all(
        engine,
        tables=[t for name, t in tables.items() if name != victim_table],
    )
    # מסירים עמודה מטבלה קיימת כדי לדמות drift של עמודה
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))

    missing = compute_missing(engine)
    assert victim_table in missing["tables"]
    assert "collection_sms_sender" in missing["columns"]["organizations"]
```

- [ ] **Step 2: הרצה לוודא כישלון**

Run: `python -m pytest tests/test_schema_sync.py -v -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'cfo.services.schema_sync'`.

- [ ] **Step 3: מימוש compute_missing**

ליצור `src/cfo/services/schema_sync.py`:

```python
"""השוואת המודלים (Base.metadata) מול הסכמה החיה — וגישור additive.

משמש גם את scripts/schema_drift_check.py (קריאה בלבד) וגם את
POST /api/admin/db/migrate (תיקון). additive בלבד: לעולם לא מוחק.
"""
from typing import Dict, List

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from ..database import Base


def compute_missing(engine: Engine) -> Dict:
    """מה חסר בסכמה החיה יחסית למודלים: טבלאות שלמות ועמודות בטבלאות קיימות."""
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())

    missing_tables: List[str] = []
    missing_columns: Dict[str, List[str]] = {}

    for name, table in Base.metadata.tables.items():
        if name not in live_tables:
            missing_tables.append(name)
            continue
        live_cols = {c["name"] for c in inspector.get_columns(name)}
        gap = [c.name for c in table.columns if c.name not in live_cols]
        if gap:
            missing_columns[name] = gap

    return {"tables": sorted(missing_tables), "columns": missing_columns}


def apply_additive(engine: Engine) -> Dict:
    raise NotImplementedError  # Task 3
```

- [ ] **Step 4: הרצת הטסטים**

Run: `python -m pytest tests/test_schema_sync.py -v -p no:warnings`
Expected: 2 PASS.

- [ ] **Step 5: סקריפט CLI לבדיקה מול כל DB**

ליצור `scripts/schema_drift_check.py`:

```python
#!/usr/bin/env python3
"""בדיקת schema drift — קריאה בלבד. exit 1 אם יש drift.

הרצה:  DATABASE_URL=postgresql+psycopg://... python scripts/schema_drift_check.py
או:    python scripts/schema_drift_check.py --env-file /path/to/.env.prod
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="קובץ env לטעינת DATABASE_URL ממנו")
    args = parser.parse_args()

    if args.env_file:
        for line in open(args.env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL לא מוגדר", file=sys.stderr)
        return 2

    from cfo.database import engine
    from cfo.services.schema_sync import compute_missing

    missing = compute_missing(engine)
    if not missing["tables"] and not missing["columns"]:
        print("OK — אין drift: הסכמה החיה תואמת את המודלים")
        return 0

    print("DRIFT נמצא:")
    for t in missing["tables"]:
        print(f"  טבלה חסרה: {t}")
    for t, cols in missing["columns"].items():
        print(f"  עמודות חסרות ב-{t}: {', '.join(cols)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: הרצה מקומית (sanity)**

Run: `DATABASE_URL=sqlite:///cfo.db python scripts/schema_drift_check.py`
Expected: מדפיס או `OK` או רשימת drift מקומית (cfo.db מנוהל ב-create_all — ייתכן drift מקומי; זה ממצא, לא כשל).

- [ ] **Step 7: Commit**

```bash
git add src/cfo/services/schema_sync.py scripts/schema_drift_check.py tests/test_schema_sync.py
git commit -m "feat(schema): generic model-vs-live drift detection + CLI check"
```

---

### Task 3: apply_additive + חיווט ל-`/api/admin/db/migrate`

הפיכת ה-endpoint לעמיד: אחרי alembic הוא משלים additive כל עמודה/טבלה
חסרה, כך שפריסה לעולם לא תשאיר את הפרוד עם "column does not exist".

**Files:**
- Modify: `src/cfo/services/schema_sync.py` (מימוש `apply_additive`)
- Modify: `src/cfo/api/routes/admin.py:560-594` (הפונקציה `run_db_migrations`)
- Test: `tests/test_schema_sync.py` (הרחבה), `tests/test_admin_migrate.py` (חדש)

**Interfaces:**
- Consumes: `compute_missing(engine)` מ-Task 2.
- Produces: `apply_additive(engine) -> {"tables": [...], "columns": {...}}` (מה בוצע); תשובת ה-endpoint מקבלת שדה חדש `schema_sync` עם אותה צורה + `alembic` (action קיים).

- [ ] **Step 1: טסט ל-apply_additive**

להוסיף ל-`tests/test_schema_sync.py`:

```python
from cfo.services.schema_sync import apply_additive


def test_apply_additive_closes_the_gap(tmp_path):
    """אחרי apply_additive — compute_missing חוזר ריק, והנתונים הקיימים שורדים."""
    engine = _fresh_engine(tmp_path)
    tables = dict(Base.metadata.tables)
    Base.metadata.create_all(
        engine,
        tables=[t for name, t in tables.items() if name != "collection_reminders"],
    )
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))
        conn.execute(sa.text(
            "INSERT INTO organizations (name) VALUES ('שרידות-נתונים')"
        ))

    applied = apply_additive(engine)
    assert "collection_reminders" in applied["tables"]
    assert "collection_sms_sender" in applied["columns"]["organizations"]

    assert compute_missing(engine) == {"tables": [], "columns": {}}
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(sa.text("SELECT name FROM organizations"))]
    assert "שרידות-נתונים" in names
```

הערה למממש: אם ל-`organizations.name` יש אילוץ NOT NULL נוסף שמפיל את
ה-INSERT, להוסיף לערכי החובה בהתאם למודל `Organization` — הכוונה היא רק
להוכיח שאין איבוד נתונים.

- [ ] **Step 2: הרצה לוודא כישלון**

Run: `python -m pytest tests/test_schema_sync.py::test_apply_additive_closes_the_gap -v -p no:warnings`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: מימוש apply_additive**

להחליף את ה-stub ב-`src/cfo/services/schema_sync.py`:

```python
def apply_additive(engine: Engine) -> Dict:
    """משלים את הסכמה החיה למודלים — additive בלבד (יצירת טבלאות/עמודות חסרות).

    לעולם לא מוחק ולא משנה עמודות קיימות. בטוח להרצה חוזרת (idempotent).
    """
    from sqlalchemy.schema import CreateColumn

    missing = compute_missing(engine)

    if missing["tables"]:
        Base.metadata.create_all(
            engine,
            tables=[Base.metadata.tables[t] for t in missing["tables"]],
        )

    for table_name, col_names in missing["columns"].items():
        table = Base.metadata.tables[table_name]
        with engine.begin() as conn:
            for col_name in col_names:
                col = table.columns[col_name]
                ddl_col = CreateColumn(col).compile(dialect=engine.dialect)
                stmt = f'ALTER TABLE {table_name} ADD COLUMN {ddl_col}'
                if col.nullable is False and col.default is None and col.server_default is None:
                    # עמודת NOT NULL בלי default תיכשל על טבלה מאוכלסת —
                    # מוסיפים כ-nullable; אכיפת NOT NULL נשארת למיגרציית alembic מסודרת.
                    stmt = stmt.replace(" NOT NULL", "")
                conn.execute(sa_text(stmt))

    return missing
```

ולהוסיף ל-imports בראש הקובץ:

```python
from sqlalchemy import text as sa_text
```

- [ ] **Step 4: הרצת טסטי schema_sync**

Run: `python -m pytest tests/test_schema_sync.py -v -p no:warnings`
Expected: 3 PASS.

- [ ] **Step 5: טסט ל-endpoint המשודרג**

ליצור `tests/test_admin_migrate.py`:

```python
"""POST /api/admin/db/migrate חייב להשלים גם עמודות חסרות (drift), לא רק alembic."""
import sqlalchemy as sa

from cfo.database import engine


def test_migrate_endpoint_reports_and_fixes_drift(client, owner):
    """מדמים drift של עמודה ואז מוודאים שה-endpoint סוגר אותו ומדווח."""
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))

    resp = client.post("/api/admin/db/migrate", headers=owner["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert "schema_sync" in body
    assert "collection_sms_sender" in body["schema_sync"]["columns"].get("organizations", [])

    insp = sa.inspect(engine)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert "collection_sms_sender" in cols
```

הערה: `owner` (conftest.py) הוא המשתמש הראשון — admin של ארגון ברירת
המחדל, עם `headers` מוכנים. `require_admin` יכבד אותו.

- [ ] **Step 6: הרצה לוודא כישלון**

Run: `python -m pytest tests/test_admin_migrate.py -v -p no:warnings`
Expected: FAIL — בתשובה אין `schema_sync` (או שהעמודה לא שוחזרה).

- [ ] **Step 7: חיווט ה-endpoint**

ב-`src/cfo/api/routes/admin.py`, בתוך `run_db_migrations`, אחרי בלוק
ה-alembic (stamped/upgraded) ולפני שליפת ה-revision, להוסיף:

```python
    from ...services.schema_sync import apply_additive

    try:
        if "users" in tables and "alembic_version" not in tables:
            alembic_command.stamp(cfg, "head")
            action = "stamped"
        else:
            alembic_command.upgrade(cfg, "head")
            action = "upgraded"
    except Exception as exc:  # create_all↔alembic: "already exists" וכדומה
        if "already exists" not in str(exc).lower():
            raise
        alembic_command.stamp(cfg, "head")
        action = f"stamped_after_conflict ({type(exc).__name__})"

    schema_sync_report = apply_additive(engine)
```

(הבלוק `try` עוטף את שני הענפים הקיימים — להחליף את הקוד הקיים, לא להוסיף
עותק.) ולעדכן את ה-return:

```python
    return {"action": action, "current_revision": revision, "schema_sync": schema_sync_report}
```

- [ ] **Step 8: הרצת הטסט + suite מלא**

Run: `python -m pytest tests/test_admin_migrate.py tests/test_schema_sync.py -v -p no:warnings && python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -3`
Expected: הכל PASS, suite מלא ירוק.

- [ ] **Step 9: Commit**

```bash
git add src/cfo/services/schema_sync.py src/cfo/api/routes/admin.py tests/test_schema_sync.py tests/test_admin_migrate.py
git commit -m "feat(admin): db/migrate now self-heals additive schema drift"
```

---

### Task 4: אודיט routes מלא + סגירת מחלקת ה-500 של אינטגרציות

מריצים את האודיט, מתעדים ממצאים, וסוגרים את המחלקה הידועה: כשל upstream
(SUMIT/OF לא זמין, שגיאת רשת) חייב להחזיר 503 כן — לא 500 גולמי.

**Files:**
- Create: `docs/audits/2026-07-03-route-audit.md` (תוצאות גולמיות + סיווג)
- Modify: `src/cfo/api/__init__.py` (exception handler גלובלי ל-httpx)
- Test: `tests/test_upstream_error_handling.py`

**Interfaces:**
- Consumes: `scripts/audit_routes.py` (קיים; הרצה: `python scripts/audit_routes.py`).
- Produces: handler שממפה `httpx.HTTPError` → HTTP 503 `{"detail": "..."}` לכל ה-app; מסמך אודיט מסווג שממנו ייגזרו משימות המשך.

- [ ] **Step 1: הרצת האודיט המלא ושמירת פלט**

Run: `python scripts/audit_routes.py > /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/route_audit_raw.txt 2>&1; tail -30 /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/route_audit_raw.txt`
Expected: טבלת סטטוס פר-route. לשמור את הקובץ — הוא הבסיס לסיווג.

- [ ] **Step 2: סיווג הממצאים למסמך**

ליצור `docs/audits/2026-07-03-route-audit.md` עם שלוש קטגוריות, כל route
שאינו 200 מסווג לאחת מהן על סמך קריאת ה-traceback בפלט:
1. **env-gated** — דורש SUMIT/OF חי (מקומית אין) → לא באג; לוודא שהוא מחזיר 400/503 ולא 500.
2. **באג אמיתי** — traceback בקוד שלנו → נרשם עם ציטוט השגיאה; אם התיקון בקוד קטן (שורה-שתיים במחלקות הידועות: NaN/inf, current_user.get, envelope) מתקנים כאן ב-TDD; אחרת נפתחת משימה חדשה בתכנית (להוסיף בסוף הקובץ הזה כ-Task 4.N עם אותו פורמט).
3. **artifact מקומי** — `date_trunc` על SQLite וכד' → מתועד, לא מתוקן.

- [ ] **Step 3: טסט ל-handler הגלובלי**

ליצור `tests/test_upstream_error_handling.py`:

```python
"""כשל upstream (SUMIT וכו') חייב להחזיר 503 כן — לא 500 גולמי."""
import httpx


def test_httpx_error_returns_503_not_500(client, owner, monkeypatch):
    """מפילים את קריאת ה-upstream ובודקים שהתשובה 503 עם detail ברור."""
    from cfo.integrations.sumit_integration import SumitIntegration

    async def _boom(self, *a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(SumitIntegration, "list_documents", _boom)
    resp = client.get("/api/accounting/documents", headers=owner["headers"])
    assert resp.status_code == 503
    assert "upstream" in resp.json()["detail"].lower()
```

הערות: `owner` הוא org 1 — מקבל SUMIT credentials מה-env (conftest מגדיר
`SUMIT_API_KEY=test-env-sumit-key`), כך שה-dependency עוברת וה-route מגיע
לקריאה המפוצצת. לאמת את שם המתודה שה-route קורא בפועל (list_documents)
מול `src/cfo/api/routes/accounting.py:107` ולעדכן את ה-monkeypatch אם שונה.

- [ ] **Step 4: הרצה לוודא כישלון**

Run: `python -m pytest tests/test_upstream_error_handling.py -v -p no:warnings`
Expected: FAIL — סטטוס 500 במקום 503.

- [ ] **Step 5: מימוש ה-handler**

ב-`src/cfo/api/__init__.py`, אחרי יצירת ה-`app` (לאתר את
`app = FastAPI(...)`), להוסיף:

```python
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(httpx.HTTPError)
async def upstream_error_handler(request: Request, exc: httpx.HTTPError):
    """כשל תקשורת מול שירות חיצוני (SUMIT/Open Finance) — 503 כן, לא 500."""
    return JSONResponse(
        status_code=503,
        content={"detail": f"upstream integration unavailable: {type(exc).__name__}"},
    )
```

- [ ] **Step 6: הרצת הטסט + suite**

Run: `python -m pytest tests/test_upstream_error_handling.py -v -p no:warnings && python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -3`
Expected: PASS + suite ירוק.

- [ ] **Step 7: תיקוני מיני-באגים מהסיווג (אם נמצאו בקטגוריה 2)**

לכל באג קטן: טסט אדום → תיקון → ירוק, באותו קובץ טסט רלוונטי קיים.
באגים גדולים: להוסיף Task 4.N לתכנית זו ולעצור לאישור בין-משימות רגיל.

- [ ] **Step 8: Commit**

```bash
git add docs/audits/2026-07-03-route-audit.md src/cfo/api/__init__.py tests/test_upstream_error_handling.py
git commit -m "feat(api): honest 503 on upstream failures + full route audit doc"
```

---

### Task 5: `scripts/prod_smoke.py` — סריקה חיה של הפרוד

סקריפט HTTP רב-פעמי מול הפרוד (או preview): login → נתיבים קריטיים →
טבלת סטטוס. הופך לשער האימות של כל פריסה מעתה.

**Files:**
- Create: `scripts/prod_smoke.py`
- Test: `tests/test_prod_smoke.py` (הסקריפט נבדק מול ה-TestClient המקומי)

**Interfaces:**
- Consumes: משתני env: `SMOKE_BASE_URL` (ברירת מחדל `https://cfo-2.vercel.app`), `SMOKE_EMAIL`, `SMOKE_PASSWORD`.
- Produces: פונקציה `run_smoke(base_url, email, password, client=None) -> list[dict]` שכל פריט בה `{"path": str, "status": int, "ok": bool, "note": str}`; exit code 0 כשהכל ok/skip, 1 אחרת.

- [ ] **Step 1: טסט מול ה-TestClient המקומי**

ליצור `tests/test_prod_smoke.py`:

```python
"""prod_smoke חייב לרוץ end-to-end מול האפליקציה ולדווח סטטוס לכל נתיב."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "prod_smoke", Path(__file__).parent.parent / "scripts" / "prod_smoke.py"
)
prod_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prod_smoke)


def test_smoke_runs_against_local_app(client, owner):
    """מריצים את הסקריפט עצמו מול ה-TestClient — login אמיתי + סריקה מלאה."""
    results = prod_smoke.run_smoke(
        base_url="", email="owner@example.com", password="secret123", client=client
    )
    paths = {r["path"] for r in results}
    assert "/api/health" in paths
    assert any(r["path"].startswith("/api/dashboard") for r in results)
    login = next(r for r in results if r["path"] == "/api/admin/auth/login")
    assert login["ok"], "login מקומי חייב להצליח — owner קיים מה-conftest"
    # אף תוצאה לא מתפוצצת בלי סטטוס; כשלים מדווחים, לא נזרקים
    assert all(isinstance(r["status"], int) for r in results)
```

הערה: `TestClient` של starlette יורש מ-`httpx.Client`, ולכן `run_smoke`
עובד עליו כמו על client אמיתי. ה-fixture `owner` מבטיח שהמשתמש
owner@example.com/secret123 קיים לפני הריצה. `run_smoke` לא נוגע
ב-`client.headers` (משותף בין טסטים) — רק headers פר-בקשה.

- [ ] **Step 2: הרצה לוודא כישלון**

Run: `python -m pytest tests/test_prod_smoke.py -v -p no:warnings`
Expected: FAIL — הקובץ `scripts/prod_smoke.py` לא קיים.

- [ ] **Step 3: מימוש הסקריפט**

ליצור `scripts/prod_smoke.py`:

```python
#!/usr/bin/env python3
"""סריקה חיה של הפרוד — login + GET לנתיבים קריטיים, טבלת סטטוס, exit code.

הרצה:
    SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py
    SMOKE_BASE_URL=https://<preview>.vercel.app SMOKE_EMAIL=... python scripts/prod_smoke.py
"""
import os
import sys

import httpx

# נתיבים קריטיים: (path, note). env_gated=נכשל בחן אם האינטגרציה לא מוגדרת.
CRITICAL_PATHS = [
    ("/api/health", "בריאות בסיסית"),
    ("/api/dashboard/executive", "דשבורד מנהלים"),
    ("/api/financial/reports/profit-loss", "רווח והפסד"),
    ("/api/ledger/balance-sheet", "מאזן"),
    ("/api/ledger/trial-balance", "מאזן בוחן"),
    ("/api/ar/aging", "גיול לקוחות"),
    ("/api/ap/aging", "גיול ספקים"),
    ("/api/daily-reports/vat", "דוח מעמ"),
    ("/api/engine/status", "סטטוס מנוע"),
    ("/api/business/menu", "תפריט יכולות"),
    ("/api/office/clients", "תיקי משרד"),
    ("/api/admin/organizations", "ארגונים (אדמין)"),
    ("/api/admin/control/clients", "מרכז שליטה סופר-אדמין"),
]

SKIP_STATUSES = {400, 503}  # env-gated: אינטגרציה לא מוגדרת = דיווח כן, לא כשל


def run_smoke(base_url, email, password, client=None):
    """מריץ את הסריקה. client מוזרק בטסטים (TestClient); אחרת httpx אמיתי."""
    own_client = client is None
    if own_client:
        client = httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True)

    results = []
    headers = {}  # לא נוגעים ב-client.headers — הוא עלול להיות משותף (TestClient בטסטים)
    try:
        if email and password:
            resp = client.post(
                "/api/admin/auth/login",
                json={"email": email, "password": password},
            )
            if resp.status_code != 200:
                results.append({"path": "/api/admin/auth/login",
                                "status": resp.status_code, "ok": False,
                                "note": "login נכשל — שאר הבדיקות ירוצו לא-מחוברות"})
            else:
                token = resp.json()["access_token"]
                headers["Authorization"] = f"Bearer {token}"
                results.append({"path": "/api/admin/auth/login",
                                "status": 200, "ok": True, "note": "login"})

        for path, note in CRITICAL_PATHS:
            try:
                r = client.get(path, headers=headers)
                ok = r.status_code == 200 or r.status_code in SKIP_STATUSES
                suffix = " (env-gated)" if r.status_code in SKIP_STATUSES else ""
                results.append({"path": path, "status": r.status_code,
                                "ok": ok, "note": note + suffix})
            except httpx.HTTPError as exc:
                results.append({"path": path, "status": -1, "ok": False,
                                "note": f"{note} — {type(exc).__name__}"})
    finally:
        if own_client:
            client.close()
    return results


def main() -> int:
    base_url = os.environ.get("SMOKE_BASE_URL", "https://cfo-2.vercel.app")
    email = os.environ.get("SMOKE_EMAIL")
    password = os.environ.get("SMOKE_PASSWORD")
    if not email or not password:
        print("אזהרה: SMOKE_EMAIL/SMOKE_PASSWORD לא הוגדרו — רץ לא-מחובר (רק /api/health משמעותי)")

    results = run_smoke(base_url, email, password)
    width = max(len(r["path"]) for r in results)
    failures = 0
    for r in results:
        mark = "OK " if r["ok"] else "FAIL"
        if not r["ok"]:
            failures += 1
        print(f"{mark} {r['status']:>4} {r['path']:<{width}} {r['note']}")
    print(f"\n{len(results) - failures}/{len(results)} תקינים מול {base_url}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: הרצת הטסט**

Run: `python -m pytest tests/test_prod_smoke.py -v -p no:warnings`
Expected: PASS.

- [ ] **Step 5: הרצה חיה מול הפרוד**

Run: `SMOKE_EMAIL=<אימייל-אדמין> SMOKE_PASSWORD=<סיסמה> python scripts/prod_smoke.py`
(את פרטי ההתחברות לפרוד לספק מה-env או מהמשתמש; אם אינם ידועים — לעצור
ולשאול את המשתמש לפני ההרצה.)
Expected: טבלה מלאה. כל FAIL שאינו env-gated נרשם ב-`docs/audits/2026-07-03-route-audit.md` בקטגוריה 2 ומטופל לפי אותו כלל (קטן=כאן, גדול=Task חדש).

- [ ] **Step 6: Commit**

```bash
git add scripts/prod_smoke.py tests/test_prod_smoke.py docs/audits/2026-07-03-route-audit.md
git commit -m "feat(ops): reusable prod smoke gate + live prod findings"
```

---

### Task 6: אימות SUMIT write-back חי (הצעת מחיר + ביטול)

מאמתים את שרשרת ההנפקה מקצה לקצה מול SUMIT האמיתי, במסמך שאושר ע"י
המשתמש: הצעת מחיר (ללא משמעות מס) על סכום סמלי, ואז ביטול מיידי.

**Files:**
- Create: `scripts/verify_sumit_writeback.py`
- Modify: `docs/PRODUCTION_READINESS.md` (רישום תוצאת האימות)

**Interfaces:**
- Consumes: `SumitIntegration(api_key, company_id)` — המתודות שהאודיט ב-Task 4 אישר לנתיבי documents (create/getpdf/cancel); credentials מ-env: `SUMIT_API_KEY`, `SUMIT_COMPANY_ID`.
- Produces: עדות מתועדת (מזהה מסמך, גודל PDF, סטטוס ביטול) ב-PRODUCTION_READINESS.md.

- [ ] **Step 1: כתיבת הסקריפט**

ליצור `scripts/verify_sumit_writeback.py`:

```python
#!/usr/bin/env python3
"""אימות write-back חי מול SUMIT: הצעת מחיר סמלית → PDF → ביטול → וידוא.

מאושר ע"י המשתמש (2026-07-03): הצעת מחיר בלבד, סכום סמלי, ביטול מיידי.
הרצה:  SUMIT_API_KEY=... SUMIT_COMPANY_ID=... python scripts/verify_sumit_writeback.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

BACKOFF_SECONDS = 30
MAX_ATTEMPTS = 3


async def _with_backoff(coro_factory, label):
    """403 של SUMIT = rate limit — המתנה ונסיון חוזר, עד MAX_ATTEMPTS."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            if "403" not in str(exc) or attempt == MAX_ATTEMPTS:
                raise
            print(f"  {label}: 403 (rate limit) — המתנה {BACKOFF_SECONDS}s, נסיון {attempt}/{MAX_ATTEMPTS}")
            await asyncio.sleep(BACKOFF_SECONDS)


async def main() -> int:
    api_key = os.environ.get("SUMIT_API_KEY")
    company_id = os.environ.get("SUMIT_COMPANY_ID")
    if not api_key:
        print("SUMIT_API_KEY לא מוגדר", file=sys.stderr)
        return 2

    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.integrations.sumit_models import DocumentRequest

    sumit = SumitIntegration(api_key=api_key, company_id=company_id)

    print("1) יוצר הצעת מחיר סמלית...")
    request = DocumentRequest(
        document_type="quote",
        customer_name="בדיקת מערכת רצף — למחיקה",
        items=[{"description": "אימות write-back אוטומטי", "quantity": 1, "unit_price": 1.0}],
    )
    doc = await _with_backoff(lambda: sumit.create_document(request), "create")
    doc_id = getattr(doc, "document_id", None) or (doc.get("document_id") if isinstance(doc, dict) else None)
    print(f"   נוצר מסמך: {doc_id}")
    if not doc_id:
        print(f"   תשובה לא צפויה: {doc}", file=sys.stderr)
        return 1

    print("2) מוריד PDF...")
    pdf = await _with_backoff(lambda: sumit.get_document_pdf(doc_id), "getpdf")
    pdf_bytes = pdf if isinstance(pdf, (bytes, bytearray)) else getattr(pdf, "content", b"")
    print(f"   PDF: {len(pdf_bytes)} bytes")

    print("3) מבטל את המסמך...")
    cancel = await _with_backoff(lambda: sumit.cancel_document(doc_id), "cancel")
    print(f"   תשובת ביטול: {cancel}")

    print("4) מוודא סטטוס...")
    details = await _with_backoff(lambda: sumit.get_document(doc_id), "getdetails")
    print(f"   פרטי מסמך אחרי ביטול: {details}")

    print("\nאימות write-back הושלם — תעד את המזהה והסטטוס ב-PRODUCTION_READINESS.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

הערות למממש: לפני ההרצה לקרוא את החתימות האמיתיות ב-
`src/cfo/integrations/sumit_integration.py` (create_document /
get_document_pdf / cancel_document / get_document) ולהתאים שמות/פרמטרים
ואת בניית `DocumentRequest` לשדות האמיתיים ב-`sumit_models.py` (כולל
מיפוי `quote`→PriceQuotation שכבר קיים). זהו סקריפט תפעולי חד-ייעודי —
אין לו unit test; האימות הוא הריצה החיה עצמה.

- [ ] **Step 2: משיכת credentials (אם חסרים ב-.env.local)**

Run: `grep -c "SUMIT_API_KEY=." /Users/mymac/coding/cfo/.env.local || vercel env pull /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/.env.prod --environment production --yes`
Expected: מפתח זמין מאחד המקורות. קובץ ה-prod נשאר ב-scratchpad בלבד.

- [ ] **Step 3: הרצה חיה**

Run: `set -a && source <קובץ-env-עם-המפתח> && set +a && python scripts/verify_sumit_writeback.py`
Expected: 4 שלבים ירוקים — נוצר, הורד PDF (גודל > 0), בוטל, סטטוס מאומת.
אם נכשל: לתקן לפי השגיאה (חתימות/שדות) ולהריץ שוב; לא להשאיר מסמך לא-מבוטל
ב-SUMIT — אם create הצליח ו-cancel נכשל, לבטל ידנית דרך ה-UI ולדווח.

- [ ] **Step 4: תיעוד התוצאה**

להוסיף ל-`docs/PRODUCTION_READINESS.md` תחת "Current Readiness Snapshot":

```markdown
- SUMIT write-back verified live (2026-07-03): quote document created,
  PDF downloaded, canceled successfully (doc id recorded in audit doc)
```

ואת מזהה המסמך + הפלט המלא ב-`docs/audits/2026-07-03-route-audit.md`.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_sumit_writeback.py docs/PRODUCTION_READINESS.md docs/audits/2026-07-03-route-audit.md
git commit -m "feat(ops): live SUMIT write-back verification (quote+cancel)"
```

---

### Task 7: בדיקת drift מול Neon prod + תיקון

**Files:**
- Modify: `docs/audits/2026-07-03-route-audit.md` (רישום תוצאה)

**Interfaces:**
- Consumes: `scripts/schema_drift_check.py` (Task 2), `.env.prod` שנמשך ב-Task 6 Step 2 (או למשוך עכשיו באותה פקודת `vercel env pull`).

- [ ] **Step 1: משיכת env פרוד אם עוד לא נמשך**

Run: `ls /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/.env.prod || vercel env pull /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/.env.prod --environment production --yes`

- [ ] **Step 2: בדיקת drift קריאה-בלבד**

Run: `python scripts/schema_drift_check.py --env-file /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/.env.prod`
Expected: `OK` או רשימת drift.

- [ ] **Step 3: אם יש drift — תיקון דרך ה-endpoint המשודרג**

Run (מקבל token אדמין דרך login):
`SMOKE_EMAIL=... SMOKE_PASSWORD=... python - <<'EOF'` עם גוף שקורא
`POST https://cfo-2.vercel.app/api/admin/db/migrate` עם ה-token ומדפיס
את `schema_sync` מהתשובה. (אם הפריסה של Task 8 עוד לא בוצעה — ה-endpoint
בפרוד עדיין ישן; במקרה כזה לדחות את הצעד לאחרי הפריסה, ולתקן בינתיים
ישירות: `python scripts/fix_prod_schema_drift.py --apply` רק אם ה-drift
שנמצא זהה ל-DDL הקשיח שבסקריפט, אחרת להמתין ל-Task 8.)

- [ ] **Step 4: אימות חוזר**

Run: אותה פקודת בדיקה מ-Step 2.
Expected: `OK — אין drift`.

- [ ] **Step 5: תיעוד ב-audit doc + commit**

```bash
git add docs/audits/2026-07-03-route-audit.md
git commit -m "docs(audit): prod schema drift check results"
```

---

### Task 8: פריסה, אימות סופי, ועדכון תיעוד

**Files:**
- Modify: `docs/PRODUCTION_READINESS.md`

**Interfaces:**
- Consumes: `scripts/prod_smoke.py` (Task 5), Vercel CLI (הפרויקט מקושר: cfo-2).

- [ ] **Step 1: suite מלא אחרון לפני פריסה**

Run: `python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -3`
Expected: הכל ירוק (443+ passed).

- [ ] **Step 2: פריסת preview**

Run: `vercel deploy 2>&1 | tail -3`
Expected: URL של preview. לשמור אותו.

- [ ] **Step 3: smoke מול ה-preview**

Run: `SMOKE_BASE_URL=<preview-url> SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py`
Expected: exit 0. אם לא — לתקן לפני production.

- [ ] **Step 4: פריסת production**

Run: `vercel deploy --prod 2>&1 | tail -3`
Expected: פריסה ל-cfo-2.vercel.app.

- [ ] **Step 5: הפעלת migrate בפרוד (סוגר drift אם נותר) + smoke סופי**

Run: קריאת `POST /api/admin/db/migrate` עם token אדמין (כמו Task 7 Step 3),
ואז: `SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py`
Expected: migrate מחזיר `schema_sync` ריק או עם ההשלמות שבוצעו; smoke exit 0.

- [ ] **Step 6: עדכון PRODUCTION_READINESS.md**

לעדכן את סעיף "Current Readiness Snapshot" למצב אמת: תאריך אימות, תוצאות
smoke, מנגנון migrate המשודרג, ומה שנותר פתוח (OPEN_FINANCE_USER_ID —
אפיק 3; Google OAuth — לא חוסם).

- [ ] **Step 7: Commit + push**

```bash
git add docs/PRODUCTION_READINESS.md
git commit -m "docs(readiness): epic 1 stability verified live"
git push origin feat/sumit-ar-ap-documents-ocr
```

---

## הגדרת סיום (מול ה-spec)

- [ ] suite מלא ירוק (443+) — Tasks 1-5.
- [ ] audit_routes: 0 כשלים לא-מתועדים — Task 4.
- [ ] prod_smoke ירוק מול production — Task 8.
- [ ] אפס schema drift מול Neon + מנגנון קבע — Tasks 3, 7, 8.
- [ ] SUMIT write-back אומת חי — Task 6.
- [ ] PRODUCTION_READINESS.md מעודכן — Task 8.
