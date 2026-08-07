# תכנית מימוש — התאוששות שלבים 1–3: בסיס QA, עשרת התיקונים, סגירת ה-branch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** להביא את ענף `chore/repo-order-and-control-plane` למצב merge-able: עץ עבודה סגור ב-commits לוגיים, rebase על main עדכני, עשרת ממצאי ה-review מ-07/08 מתוקנים ב-TDD, וסוויטה ירוקה בת-שחזור על checkout נקי.

**Architecture:** עבודה על הענף הקיים בלבד (אין ענפים חדשים — ההיסטוריה שזורה). סדר: סגירת עץ → rebase → ראיית QA → תיקונים (OCR ראשון) → QA מלא → PR. כל תיקון הוא commit עצמאי עם טסט רגרסיה שנכשל לפניו ועובר אחריו.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic/pytest · React/TS (frontend) · git.

**הספק המחייב:** `docs/superpowers/specs/2026-08-07-recovery-realignment-design.md`.

> **סטייה מהספק (מוצהרת):** הספק קבע 3 PRs. בפועל עשרת הפגמים הם פגמים ב-diff של הענף עצמו — אי אפשר לבסס "PR תיקונים" על main שבו הקוד הפגום לא קיים, וקבצים מעורבים (`models.py`, `admin.py`, `ai_chat_service.py`) הופכים הפרדת סכימה ל-cherry-pick כירורגי שהספק עצמו אסר. לכן: **PR אחד**, עם commits לוגיים המאפשרים revert פר-נושא, כשהצעד הבלתי-הפיך (מיגרציות) ממילא מבודד מאחורי שער ה-runbook (`/api/admin/db/migrate` באישור בעלים). אם הבעלים מעדיף בכל זאת פיצול — לעצור אחרי משימה 2 ולהחליט.

## Global Constraints

- TDD: טסט אדום לפני מימוש; `python -m pytest tests/ -q` ירוק לפני **כל** commit.
- אפס קריאות SUMIT/Open-Finance/Meta חיות מטסטים (gateways תמיד fake).
- honest-null: אין ערכים מומצאים; עמימות → תור הכרעה.
- אין push ל-main, אין deploy — הם שלב 4 של הספק (אישור בעלים).
- הערות קוד בעברית, בסגנון הקבצים הקיימים.
- כל commit מסתיים ב-trailer:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: סגירת עץ העבודה ל-commits לוגיים

**Files:** אין שינוי תוכן — `git add` + `git commit` בקבוצות בלבד.

**Interfaces:**
- Consumes: עץ העבודה הנוכחי (35 קבצים modified + ~20 untracked).
- Produces: `git status --porcelain` ריק; היסטוריה בת-revert פר-נושא.

- [ ] **Step 1: ודא בסיס** — `python -m pytest tests/ -q` חייב להיות ירוק לפני שנוגעים (הבסיס הידוע: ~1,723). אם אדום — לעצור ולדווח, לא לתקן כאן.
- [ ] **Step 2: commit קבוצה א' — OCR + קליטה**

```bash
git add src/cfo/services/expense_ocr_pipeline.py src/cfo/services/vision_extractor.py \
        src/cfo/services/chat_expense_intake.py tests/test_expense_ocr_pipeline.py \
        tests/test_chat_expense_intake.py tests/test_intake_preflight.py
git commit -m "feat(ocr): שער אמון, מזהים סינתטיים, intake preflight — סגירת עבודת 05-07/08"
```

- [ ] **Step 3: commit קבוצה ב' — roster coverage + sync**

```bash
git add src/cfo/services/roster_coverage.py src/cfo/services/sync_engine.py \
        scripts/roster_health.py scripts/deactivate_may_way.py \
        tests/test_roster_coverage.py tests/test_contact_backfill_creates_missing.py
git commit -m "feat(roster): בקרת כיסוי פר-מקור + roster-health + backfill אנשי קשר"
```

- [ ] **Step 4: commit קבוצה ג' — ערוצים ו-cron**

```bash
git add src/cfo/services/channel_notifier.py src/cfo/api/routes/cron.py \
        src/cfo/api/routes/telegram_webhook.py src/cfo/api/routes/whatsapp_webhook.py \
        src/cfo/config.py vercel.json tests/test_channel_notifier.py \
        tests/test_vercel_cron_contract.py tests/test_whatsapp_webhook.py
git commit -m "feat(channels): דחיפה רב-ערוצית, חלון שירות וואטסאפ, cron roster-health"
```

- [ ] **Step 5: commit קבוצה ד' — אשכול הסכימה של מושקו** (מיגרציות + כל התלוי בהן)

```bash
git add src/cfo/models.py alembic/versions/d6e7f8a9b0c1_add_moshko_observability.py \
        alembic/versions/e7f8a9b0c1d2_add_moshko_memory_approval.py \
        src/cfo/services/moshko_observability.py src/cfo/services/moshko_knowledge.py \
        src/cfo/services/moshko_tasks.py src/cfo/services/ai_chat_service.py \
        src/cfo/services/ai_chat_tools.py src/cfo/api/routes/admin.py \
        frontend/src/components/MoshkoKnowledgeDashboard.tsx \
        frontend/src/components/MoshkoObservabilityDashboard.tsx frontend/src/App.tsx \
        tests/test_moshko_observability.py tests/test_moshko_stage3.py \
        tests/test_ai_chat_tools.py tests/test_fresh_database_migrations.py \
        docs/MOSHKO_ACTIVATION_RUNBOOK.md docs/superpowers/plans/2026-07-30-moshko-activation-plan.md \
        docs/superpowers/plans/2026-07-30-moshko-full-system-roadmap.md
git commit -m "feat(moshko): observability + ידע/משימות + שתי מיגרציות — נפרס כבוי (אין סודות ערוצים בפרוד)"
```

- [ ] **Step 6: commit קבוצה ה' — שירותים ו-KB**

```bash
git add src/cfo/services/office_service.py src/cfo/services/client_automation_service.py \
        src/cfo/services/cost_analysis_service.py src/cfo/services/fees_service.py \
        src/cfo/services/financial_reports_service.py src/cfo/services/kb_loader.py \
        src/cfo/services/rezef_kb.py tests/test_rezef_kb.py tests/test_capability_control_plane.py
git commit -m "chore(services): התאמות שירותים ו-KB לעבודת 05-08/08"
```

- [ ] **Step 7: commit קבוצה ו' — תיעוד ו-control plane**

```bash
git add .gitignore docs/MASTER_EXECUTION_PLAN.md docs/rezef_capabilities.json
git commit -m "docs(board): עדכון הלוח + מניפסט היכולות למצב 05-08/08"
```

- [ ] **Step 8: ודא סגירה מלאה** — `git status --porcelain` — אם נותר קובץ שלא שויך (למעט `reports/` — מטופל במשימה 3), שייך אותו לקבוצה המתאימה ב-commit נוסף. `reports/` נשאר untracked בשלב זה במכוון.
- [ ] **Step 9: ריצה מלאה** — `python -m pytest tests/ -q` ירוק.

---

### Task 2: rebase על origin/main

**Files:** אין קבצים חדשים; פתרון קונפליקטים בלבד.

**Interfaces:**
- Consumes: הענף הסגור ממשימה 1; `origin/main` שקדם לו ב-3 commits.
- Produces: הענף מבוסס על ראש main; הסוויטה ירוקה על הבסיס החדש.

- [ ] **Step 1:** `git fetch origin && git rebase origin/main`
- [ ] **Step 2:** בכל קונפליקט — לפתור לפי הכלל: קוד השינוי מהענף גובר על main, אלא אם main מכיל תיקון prod שלא קיים בענף (לבדוק ב-`git log origin/main -3`).
- [ ] **Step 3:** `python -m pytest tests/ -q` — ירוק. אם אדום, לתקן במסגרת ה-rebase (לא commit חדש).
- [ ] **Step 4:** `git log --oneline origin/main..HEAD | wc -l` — לתעד את מספר ה-commits החדש בסיכום המשימה.

---

### Task 3: ראיית ה-QA נכנסת ל-git (ממצא F10)

**Files:**
- Modify: `.gitignore` (אחרי שורה 55 — בלוק ה-reports)
- Add to git: `reports/2026-08-05-cross-org-consistency-audit.md`
- Test (קיים): `tests/test_capability_control_plane.py`

**Interfaces:**
- Produces: כל נתיב `knowledge` ב-`docs/rezef_capabilities.json` קיים גם ב-checkout נקי.

- [ ] **Step 1: הוכח את הכשל** — ‏`git stash -u && python -m pytest tests/test_capability_control_plane.py -q; git stash pop` — מצופה FAIL על "missing knowledge evidence" (זו הוכחת ה-checkout הנקי).
- [ ] **Step 2: הוסף negation** ב-`.gitignore` מיד אחרי `!reports/moshko_observability/stage3_report.md`:

```gitignore
!reports/2026-08-05-cross-org-consistency-audit.md
```

- [ ] **Step 3:** `git add .gitignore reports/2026-08-05-cross-org-consistency-audit.md`
- [ ] **Step 4: אימות** — ‏`git stash -u && python -m pytest tests/test_capability_control_plane.py -q; git stash pop` — הפעם PASS (הקובץ tracked ולכן שורד stash).
- [ ] **Step 5: Commit**

```bash
git commit -m "fix(evidence): דוח האודיט 05/08 נכנס ל-git — הראיה שה-registry מצביע עליה חייבת להיות versioned (F10)"
```

---

### Task 4: סכום מאומת לעולם לא נדרס (ממצא F1 — החמור, ראשון)

**Files:**
- Modify: `src/cfo/services/expense_ocr_pipeline.py:255-260`
- Test: `tests/test_expense_ocr_pipeline.py`

**Interfaces:**
- Consumes: `_seed_expense(client, headers, *, source, external_id, total)`, ‏`_patch_connector_and_extract(monkeypatch, payload)` — קיימים בקובץ הטסטים.
- Produces: כלל קשיח: `exp.total` שאינו 0 (כולל שלילי — זיכוי) לא נדרס ע"י שום חילוץ, גם בביטחון גבוה.

- [ ] **Step 1: שני טסטים נכשלים** — להוסיף בסוף `tests/test_expense_ocr_pipeline.py`:

```python
def test_high_confidence_extract_never_overwrites_verified_amount(client, monkeypatch):
    """ממצא F1 (review 07/08): חילוץ בביטחון גבוה עדיין אסור לו לדרוס סכום
    מאומת — may_write הישן החזיר True לכל חילוץ trustworthy."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard3@example.com", "password": "secret123",
        "full_name": "OCR Guard 3",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit_fileexpense",
                        external_id="2126074590", total=5000)
    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.95,
        "supplier_name": "ספק בדוק בע\"מ", "supplier_tax_id": "511402547",
        "amount_total": 4237, "vat_amount": 646.32, "net_amount": 3590.68,
    })

    from cfo.database import SessionLocal
    from cfo.models import Expense
    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                    .process_pending(delay=0, auto_file=True))
    finally:
        db.close()

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == eid).first()
        assert float(exp.total) == 5000.0, (
            f"סכום מאומת נדרס ל-{exp.total} ע\"י חילוץ בביטחון גבוה"
        )
    finally:
        db.close()


def test_negative_verified_amount_is_protected_too(client, monkeypatch):
    """חשבונית זיכוי (סכום שלילי) היא נתון מאומת — רק 0 הוא מעטפת ריקה."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard4@example.com", "password": "secret123",
        "full_name": "OCR Guard 4",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit_fileexpense",
                        external_id="2126074591", total=-500)
    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.95,
        "supplier_name": "ספק זיכוי בע\"מ", "supplier_tax_id": "511402547",
        "amount_total": 500, "vat_amount": 76.27, "net_amount": 423.73,
    })

    from cfo.database import SessionLocal
    from cfo.models import Expense
    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                    .process_pending(delay=0))
    finally:
        db.close()

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == eid).first()
        assert float(exp.total) == -500.0
    finally:
        db.close()
```

הערה: אם `_seed_expense` דוחה `total` שלילי (ולידציית API) — לעדכן את השורה ישירות ב-DB אחרי היצירה, כפי ש-`_seed_expense` עצמו כבר עושה עם `source`/`external_id`.

- [ ] **Step 2:** `python -m pytest tests/test_expense_ocr_pipeline.py -q` — שני החדשים FAIL (הסכום נדרס).
- [ ] **Step 3: המימוש** — ב-`expense_ocr_pipeline.py`, החלף את הבלוק (שורות ~255-260):

```python
        # סכומים: total כולל מע"מ, ממנו נגזרים net + vat
        total, net, vat = self._resolve_amounts(extract)
        # סכום מאומת לעולם לא נדרס ע"י חילוץ — גם לא בביטחון גבוה (F1,
        # review 07/08). רק 0 הוא מעטפת ריקה; שלילי הוא זיכוי מאומת.
        verified_total = (
            exp.total if exp.total is not None and float(exp.total) != 0 else None
        )
        if total is not None and verified_total is not None:
            total, net, vat = None, None, None
```

(מחליף את `if total is not None and not may_write(verified_total):` — ההגנה על סכומים אינה תלויה עוד ב-trustworthiness.)

- [ ] **Step 4:** `python -m pytest tests/test_expense_ocr_pipeline.py -q` — הכול PASS (כולל הטסטים הקיימים על מעטפות ריקות שממשיכות להתמלא).
- [ ] **Step 5: Commit** — ‏`git add … && git commit -m "fix(ocr): סכום מאומת לעולם לא נדרס — גם בחילוץ בביטחון גבוה; זיכוי שלילי מוגן (F1)"`

---

### Task 5: ברירת המחדל של push חוזרת ל-telegram (ממצא F6)

**Files:**
- Modify: `src/cfo/services/channel_notifier.py:126` + docstring
- Test: `tests/test_channel_notifier.py`

**Interfaces:**
- Produces: `push_to_organization(..., provider: str | None = "telegram")` — מרובה-ערוצים רק בבקשה מפורשת (`provider=None`).

- [ ] **Step 1: טסט נכשל** — להוסיף ב-`tests/test_channel_notifier.py` (משתמש ב-`_make_identity` הקיים):

```python
def test_default_push_is_telegram_only_whatsapp_requires_explicit_optin(client, monkeypatch):
    """F6 (review 07/08): מי שקישר וואטסאפ לצ'אט בלבד אסור שיקבל דחיפות
    יזומות מברירת המחדל — הרחבת ערוצים היא החלטה מפורשת של הקורא."""
    import asyncio
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        org_id = db.query(User).first().organization_id
        _make_identity(db, org_id, external_id="wa-only-1", provider="whatsapp",
                       last_inbound_at=datetime.utcnow())
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123")
        monkeypatch.setattr(settings, "whatsapp_access_token", "tok")

        sent = []

        class FakeGateway:
            async def send_text(self, external_id, text):
                sent.append(external_id)

        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "בריף בוקר", severity="critical",
            gateways={"whatsapp": FakeGateway(), "telegram": FakeGateway()},
        ))
        assert sent == [], "ברירת המחדל דחפה לוואטסאפ בלי opt-in מפורש"
        assert result["sent"] == 0
    finally:
        db.close()
```

- [ ] **Step 2:** `python -m pytest tests/test_channel_notifier.py -q` — החדש FAIL (נשלח לוואטסאפ).
- [ ] **Step 3: המימוש** — בחתימת `push_to_organization`:

```python
    provider: str | None = "telegram",
```

ובראש ה-docstring להוסיף: `provider="telegram" כברירת מחדל — הרחבה לכל הערוצים היא opt-in מפורש של הקורא (provider=None), לא תופעת לוואי (F6).`

- [ ] **Step 4:** `python -m pytest tests/test_channel_notifier.py tests/test_vercel_cron_contract.py -q` — PASS. טסטים קיימים שסמכו על provider=None כברירת מחדל — לעדכן אותם להעברה מפורשת של `provider=None` (השינוי מותר: הם בודקים יכולת, לא ברירת מחדל).
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(channels): דחיפה היא telegram-only כברירת מחדל — רב-ערוצי רק ב-opt-in מפורש (F6)"`

---

### Task 6: פרמטר template בוואטסאפ בלי שורות חדשות (ממצא F2)

**Files:**
- Modify: `src/cfo/services/channel_notifier.py` (helper חדש + call site ~209)
- Test: `tests/test_channel_notifier.py`

**Interfaces:**
- Produces: `_template_param(text: str) -> str` — שטוח, בלי `\n`/`\t`, ≤1000 תווים.

- [ ] **Step 1: טסט נכשל**:

```python
def test_whatsapp_template_param_is_single_line(client, monkeypatch):
    """F2 (review 07/08): Meta דוחה פרמטר template עם שורה חדשה (שגיאה
    132000) — טקסט ההתרעות הרב-שורתי חייב להישטח לפני השליחה."""
    import asyncio
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        org_id = db.query(User).first().organization_id
        _make_identity(db, org_id, external_id="wa-tpl-1", provider="whatsapp",
                       last_inbound_at=datetime.utcnow() - timedelta(hours=30))
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123")
        monkeypatch.setattr(settings, "whatsapp_access_token", "tok")
        monkeypatch.setattr(settings, "whatsapp_push_template_name", "rezef_alert")

        captured = {}

        class FakeGateway:
            async def send_template(self, external_id, name, language, params):
                captured["params"] = params

        text = "⚠️ 3 התרעות חדשות:\n- [high] פער בנק\n- [critical]\tחריגה"
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, text, severity="critical",
            provider="whatsapp", gateway=FakeGateway(),
        ))
        assert result["sent"] == 1
        assert len(captured["params"]) == 1
        assert "\n" not in captured["params"][0]
        assert "\t" not in captured["params"][0]
        assert "פער בנק" in captured["params"][0]
    finally:
        db.close()
```

- [ ] **Step 2:** ריצה — FAIL על `"\n" not in`.
- [ ] **Step 3: המימוש** — בראש `channel_notifier.py` להוסיף `import re`, ומעל `push_to_organization`:

```python
# Meta דוחה פרמטרי template עם תווי שורה-חדשה/טאב (שגיאה 132000/#100) —
# ההתרעות שלנו רב-שורתיות במכוון, ולכן משוטחות רק בנתיב ה-template (F2).
_TEMPLATE_PARAM_MAX_CHARS = 1000


def _template_param(text: str) -> str:
    flat = re.sub(r"[\r\n\t]+", " · ", text).strip()
    flat = re.sub(r" {2,}", " ", flat)
    return flat[:_TEMPLATE_PARAM_MAX_CHARS]
```

וב-call site: `[_template_param(text)]` במקום `[text]`.

- [ ] **Step 4:** `python -m pytest tests/test_channel_notifier.py -q` — PASS.
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(whatsapp): פרמטר template משוטח לשורה אחת — Meta דוחה שורות חדשות (F2)"`

---

### Task 7: דדופ התרעות פר-ספק — אין אובדן קבוע (ממצא F3)

**Files:**
- Modify: `src/cfo/api/routes/cron.py:691-724` (הלולאה ב-channel-alerts)
- Test: `tests/test_channel_notifier.py` (שם יושבים טסטי ה-cron הזה, ר' `_mk_insight`)

**Interfaces:**
- Consumes: `push_to_organization(..., provider=...)` ממשימה 5; ‏`_mk_insight`, `_make_identity` מקובץ הטסטים.
- Produces: cutoff נפרד לכל provider — שליחה מוצלחת בטלגרם לא מעלימה את התובנה מוואטסאפ.

- [ ] **Step 1: טסט נכשל**:

```python
def test_channel_alerts_cutoff_is_per_provider(client, monkeypatch):
    """F3 (review 07/08): שליחה מוצלחת בטלגרם אסור שתקדם את ה-cutoff של
    זהות וואטסאפ שדולגה (חלון שירות סגור) — אחרת ההתרעה אובדת לתמיד."""
    import asyncio
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        org_id = db.query(User).first().organization_id
        now = datetime.utcnow()
        # טלגרם כבר קיבל push אחרי יצירת התובנה; וואטסאפ מעולם לא.
        _make_identity(db, org_id, external_id="tg-cut-1", provider="telegram",
                       last_push_at=now)
        _make_identity(db, org_id, external_id="wa-cut-1", provider="whatsapp",
                       last_inbound_at=now)
        _mk_insight(db, org_id, severity="critical", title="חריגה קריטית",
                    created_at=now - timedelta(hours=1))
        db.commit()
        monkeypatch.setattr(settings, "telegram_bot_token", "tok")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123")
        monkeypatch.setattr(settings, "whatsapp_access_token", "tok")

        wa_sent = []

        class FakeGateway:
            async def send_text(self, external_id, text):
                if external_id.startswith("wa-"):
                    wa_sent.append(text)

        monkeypatch.setattr(notifier, "_build_gateway", lambda p: FakeGateway())

        from cfo.api.routes.cron import scheduled_channel_alerts
        asyncio.run(scheduled_channel_alerts(db=db))
        assert wa_sent, "התובנה אבדה לוואטסאפ כי הטלגרם כבר קיבל אותה"
    finally:
        db.close()
```

הערה: את שם פונקציית ה-route המדויק לקחת מ-`cron.py` (השורה `async def` שמעל הלולאה בשורות 691-724); אם היא דורשת פרמטרים נוספים — להעביר אותם כפי שטסטי cron קיימים בקובץ עושים.

- [ ] **Step 2:** ריצה — FAIL (`wa_sent` ריק: ה-cutoff הארגוני מסנן את התובנה).
- [ ] **Step 3: המימוש** — להחליף את גוף הלולאה `for org in orgs:` ב:

```python
    for org in orgs:
        try:
            identities = recipients_for(db, org.id)
            if not identities:
                continue

            # cutoff פר-ספק (F3): הגייטים הם פר-זהות (חלון שירות וואטסאפ,
            # קונפיגורציה) — cutoff ארגוני יחיד מעלים לתמיד תובנה מערוץ
            # שדולג בזמן שערוץ אחר קיבל אותה.
            by_provider: dict[str, list] = {}
            for identity in identities:
                by_provider.setdefault(identity.provider, []).append(identity)

            org_insight_count = 0
            org_pushed = False
            for provider, provider_identities in by_provider.items():
                last_pushes = [
                    i.last_push_at for i in provider_identities if i.last_push_at
                ]
                query = db.query(CfoInsight).filter(
                    CfoInsight.organization_id == org.id,
                    CfoInsight.status == "active",
                    CfoInsight.severity.in_(("high", "critical")),
                )
                if last_pushes:
                    query = query.filter(CfoInsight.created_at > max(last_pushes))
                else:
                    query = query.filter(
                        CfoInsight.created_at
                        >= datetime.utcnow() - timedelta(hours=24)
                    )
                insights = query.order_by(CfoInsight.created_at.asc()).all()
                if not insights:
                    continue

                org_insight_count = max(org_insight_count, len(insights))
                severity = (
                    "critical"
                    if any(i.severity == "critical" for i in insights)
                    else "high"
                )
                lines = [f"⚠️ {len(insights)} התרעות חדשות:"]
                for insight in insights[:5]:
                    lines.append(f"- [{insight.severity}] {insight.title}")
                if len(insights) > 5:
                    lines.append(f"ועוד {len(insights) - 5}")
                text = "\n".join(lines)

                result = await push_to_organization(
                    db, org.id, text, severity=severity, provider=provider,
                )
                if result.get("sent"):
                    org_pushed = True

            total_insights += org_insight_count
            if org_pushed:
                total_pushed += 1
        except Exception as exc:
            logger.error("Channel alert push failed for org %s: %s", org.id, exc)
            db.rollback()
```

ולעדכן את ה-docstring של ה-route (שורות 676-683) שהדדופ הוא פר-ספק.

- [ ] **Step 4:** `python -m pytest tests/test_channel_notifier.py tests/test_vercel_cron_contract.py -q` — PASS.
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(cron): דדופ התרעות פר-ספק — ערוץ שדולג לא מאבד תובנה לתמיד (F3)"`

---

### Task 8: outside_service_window הוא skip, לא כשל (ממצא F7)

**Files:**
- Modify: `src/cfo/services/morning_brief_service.py:523`
- Test: `tests/test_channel_notifier.py` (טסטי `_deliver_channel` יושבים שם, ר' `brief_svc`)

- [ ] **Step 1: טסט נכשל**:

```python
def test_outside_service_window_is_a_skip_not_a_failure(monkeypatch):
    """F7 (review 07/08): מצב מוכר-וצפוי (חלון וואטסאפ סגור, אין template)
    אסור שיירשם ככשל מסירה בדוח הבריף."""
    async def fake_push(db, org_id, text, *, severity="info", **kwargs):
        return {"status": "outside_service_window", "sent": 0, "failed": 0,
                "skipped": 1, "outside_service_window": 1, "not_configured": 0}

    monkeypatch.setattr(notifier, "push_to_organization", fake_push)
    result = brief_svc._deliver_channel(
        None, 1, "בריף", "info", delivered={}, force=False,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "outside_service_window"
```

הערה: `_deliver_channel` מייבא את `push_to_organization` בתוך הפונקציה (`from .channel_notifier import ...`) — לכן ה-monkeypatch חייב להיות על `notifier.push_to_organization` (המודול המקורי), כמו בטסטים הקיימים.

- [ ] **Step 2:** ריצה — FAIL (`status == "failed"`).
- [ ] **Step 3: המימוש** — בשורה 523:

```python
    if push_status in {
        "not_configured", "no_recipients", "quiet_hours", "outside_service_window",
    }:
```

- [ ] **Step 4:** `python -m pytest tests/test_channel_notifier.py -q` — PASS.
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(brief): חלון שירות סגור נרשם כ-skip ולא ככשל מסירה (F7)"`

---

### Task 9: שורת ה-audit של כלי כושל שורדת, וה-session לא נשאר מורעל (ממצאים F4+F5)

**Files:**
- Modify: `src/cfo/services/ai_chat_service.py:156-175` (ענף החריגה) + שורה 211 (`flush`→`commit`)
- Test: `tests/test_moshko_observability.py`

**Interfaces:**
- Consumes: `record_tool_call_best_effort` (savepoint+flush — נשאר כמו שהוא); ‏fixture `iso` וטסטי `AIChatService(db, iso["org_id"], user_id)` הקיימים בקובץ.
- Produces: בכל כשל כלי — ‏rollback → רישום → commit; השורה עמידה גם כשהבקשה מסתיימת 400.

- [ ] **Step 1: שני טסטים נכשלים** — להוסיף ב-`tests/test_moshko_observability.py` (משתמשים ב-`fresh_org`, ‏`_patch_client`, ‏`_tool_block`, ‏`_response`, ‏`TOOLS`+`replace` הקיימים בקובץ):

```python
def test_failed_confirmed_write_leaves_a_durable_audit_row(monkeypatch, fresh_org):
    """F4 (review 07/08): כלי כתיבה מאושר שנכשל חייב להשאיר MoshkoToolCall
    עם succeeded=False שקיים גם ב-session חדש — הבקשה מסתיימת 400 בלי
    commit, ובלי commit מפורש שורת ה-audit נמחקת ב-rollback הסגירה."""
    from cfo.services.ai_chat_service import ChatConfirmationError

    iso = fresh_org()
    db = SessionLocal()
    original = TOOLS["issue_document"]

    async def failing_write(_db, _org, **_kwargs):
        raise ValueError("SUMIT rejected the document")

    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        TOOLS["issue_document"] = replace(original, fn=failing_write)
        args = {"document_type": "invoice", "customer_id": "1",
                "customer_name": "א", "items": []}
        _patch_client(monkeypatch, [
            _response(_tool_block("issue_document", args), stop_reason="tool_use"),
        ])
        pending = asyncio.run(
            AIChatService(db, iso["org_id"], user_id).send_message("s-f4", "הפק")
        )
        with pytest.raises(ChatConfirmationError):
            asyncio.run(
                AIChatService(db, iso["org_id"], user_id)
                .confirm_action(pending["message_id"])
            )
    finally:
        TOOLS["issue_document"] = original
        db.close()  # מדמה את get_db_session: close בלי commit אחרי ה-400

    fresh = SessionLocal()
    try:
        row = fresh.query(MoshkoToolCall).filter(
            MoshkoToolCall.session_id == "s-f4"
        ).one()
        assert row.succeeded is False
        assert "SUMIT rejected" in row.error
    finally:
        fresh.close()


def test_db_error_in_tool_does_not_poison_the_session(monkeypatch, fresh_org):
    """F5 (review 07/08): כלי שמרעיל את ה-session (flush שנכשל על אילוץ)
    — השיחה ממשיכה, תשובת העוזר נשמרת, ושורת ה-audit קיימת."""
    iso = fresh_org()
    db = SessionLocal()
    original = TOOLS["get_ar_aging"]

    async def poisoning_tool(_db, _org, **_kwargs):
        # ChatMessage ריק מפר NOT NULL — flush זורק ומשאיר session מורעל,
        # בדיוק כמו IntegrityError אמיתי באמצע כלי.
        _db.add(ChatMessage())
        _db.flush()

    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        TOOLS["get_ar_aging"] = replace(original, fn=poisoning_tool)
        _patch_client(monkeypatch, [
            _response(_tool_block("get_ar_aging", {}), stop_reason="tool_use"),
            _response(_text_block("קרתה תקלה, מטופל")),
        ])
        result = asyncio.run(
            AIChatService(db, iso["org_id"], user_id).send_message("s-f5", "מצב?")
        )
        assert result["reply"] == "קרתה תקלה, מטופל"
    finally:
        TOOLS["get_ar_aging"] = original
        db.close()

    fresh = SessionLocal()
    try:
        audit = fresh.query(MoshkoToolCall).filter(
            MoshkoToolCall.session_id == "s-f5"
        ).one()
        assert audit.succeeded is False
        replies = fresh.query(ChatMessage).filter(
            ChatMessage.session_id == "s-f5", ChatMessage.role == "assistant"
        ).all()
        assert replies, "תשובת העוזר אבדה בגלל ה-session המורעל"
    finally:
        fresh.close()
```

הערה: אם שם מחלקת החריגה בפועל שונה מ-`ChatConfirmationError` — לקחת את השם המדויק מ-`ai_chat_service.py` (נתיב ה-confirm).

- [ ] **Step 2:** ריצה — שניהם FAIL.
- [ ] **Step 3: המימוש** — (א) שורה 211: `self.db.flush()` → `self.db.commit()` עם ההערה:

```python
        # commit ולא flush: הודעת המשתמש חייבת לשרוד rollback של כלי כושל
        # בהמשך התור (F4/F5) — ההיסטוריה היא עובדה גם כשהכלי נכשל.
```

(ב) ענף החריגה ב-`_execute_tool_observed`:

```python
        except Exception as exc:
            elapsed = round((perf_counter() - started) * 1000)
            # הכלי אולי הותיר כתיבות חלקיות או session מורעל (F5) — קודם
            # rollback, אחרת רישום ה-audit עצמו ייכשל על אותו session.
            try:
                self.db.rollback()
            except Exception:
                logger.exception("Rollback after tool failure failed")
            record_tool_call_best_effort(
                self.db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                session_id=session_id,
                message_id=message_id,
                tool_name=tool.name,
                target_system=tool_target_system(tool.name, arguments=logged_arguments),
                arguments=logged_arguments,
                succeeded=False,
                error=str(exc),
                duration_ms=elapsed,
            )
            # commit מפורש (F4): נתיב ה-confirm מסתיים 400 בלי commit של
            # הבקשה — בלעדיו שורת הכשל, שבשבילה הטבלה קיימת, נמחקת.
            try:
                self.db.commit()
            except Exception:
                logger.exception("Tool-call audit commit failed")
            if propagate:
                raise
            return {"error": str(exc), "tool": tool.name}
```

- [ ] **Step 4:** `python -m pytest tests/test_moshko_observability.py tests/test_ai_chat_tools.py -q` — PASS. אם טסט קיים נשען על כך שהודעת משתמש נעלמת ב-rollback — לעדכן אותו ולציין זאת בהודעת ה-commit.
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(moshko): audit של כלי כושל שורד (rollback→record→commit) וה-session לא נשאר מורעל (F4+F5)"`

---

### Task 10: פילטר ערוץ NULL-safe בתצפית (ממצא F8)

**Files:**
- Modify: `src/cfo/api/routes/admin.py:7` (import) + `admin.py:1722-1725`
- Test: `tests/test_moshko_observability.py`

- [ ] **Step 1: טסט נכשל**:

```python
def test_channel_web_filter_includes_null_session_ids(iso, client_super_admin):
    """F8 (review 07/08): שורות LLMUsage עם session_id=None (קריאות ראיית
    ה-OCR) חייבות להופיע בתצוגת channel=web — אחרת הסכום פר-ערוץ קטן
    מהסכום הכולל והאדמין מדווח חסר."""
    from cfo.database import SessionLocal
    from cfo.models import LLMUsage

    db = SessionLocal()
    try:
        db.add(LLMUsage(organization_id=iso["org_id"], user_id=None,
                        session_id=None, provider="anthropic",
                        model="claude-sonnet-5", purpose="ocr",
                        input_tokens=10, output_tokens=5))
        db.commit()
    finally:
        db.close()

    resp = client_super_admin.get("/api/admin/moshko/usage?channel=web")
    assert resp.status_code == 200
    payload = resp.json()
    assert any(row.get("purpose") == "ocr" for row in payload["data"]["rows"]), (
        "שורת session_id=None נעלמה מכל תצוגות הערוץ"
    )
```

הערה: שמות ה-fixture (`client_super_admin`) ומבנה ה-payload — לפי הטסטים הקיימים על `/api/admin/moshko/usage` באותו קובץ; להתאים לשמות בפועל.

- [ ] **Step 2:** ריצה — FAIL (השורה לא מופיעה).
- [ ] **Step 3: המימוש** — שורה 7: להוסיף `and_` ל-import (`from sqlalchemy import and_, case, func, or_`), ובענף `web`:

```python
            elif channel == "web":
                # NULL-safe (F8): שורות בלי session_id (קריאות OCR/רקע) הן
                # "web" — SQL של NOT LIKE על NULL מחזיר NULL ומעלים אותן
                # מכל התצוגות.
                query = query.filter(
                    or_(
                        model.session_id.is_(None),
                        and_(
                            ~model.session_id.like("wa-%"),
                            ~model.session_id.like("tg-%"),
                        ),
                    )
                )
```

- [ ] **Step 4:** `python -m pytest tests/test_moshko_observability.py -q` — PASS.
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(admin): פילטר channel=web כולל session_id=NULL — אין שורות שנעלמות מכל התצוגות (F8)"`

---

### Task 11: ריפורמט עשרוני אינו "שינוי" ואינו מייצר audit ריק (ממצא F9)

**Files:**
- Modify: `src/cfo/services/chart_of_accounts_importer.py:124-126` + ‏`:305-336`
- Test: `tests/test_chart_of_accounts_importer.py`

**Interfaces:**
- Consumes: `import_chart_of_accounts(db, organization_id, csv_path, source_file_hash, *, observed_at)`; ‏`_write_csv`, ‏`_active_row` מקובץ הטסטים.
- Produces: hash אדיש לסקייל עשרוני; עדכון בלי שינוי מהותי → `unchanged`, בלי שורת `AccountImportChange`.

- [ ] **Step 1: טסט נכשל**:

```python
def test_decimal_reformat_only_is_unchanged_and_writes_no_audit(tmp_path):
    """F9 (review 07/08): ייצוא חוזר שמשנה רק סקייל ('25' -> '25.0000')
    אינו שינוי — אסור לו לייצר שורת audit ריקה או להיספר כ-updated."""
    from cfo.database import SessionLocal
    from cfo.models import AccountImportChange

    row = _active_row()
    row["withholding_tax_percent"] = "25"
    source = _write_csv(tmp_path / "a.csv", [row])

    db = SessionLocal()
    try:
        first = import_chart_of_accounts(
            db, organization_id=5, csv_path=source,
            source_file_hash=SOURCE_FILE_HASH, observed_at=OBSERVED_AT,
        )
        assert first.inserted == 1

        row2 = dict(row)
        row2["withholding_tax_percent"] = "25.0000"
        source2 = _write_csv(tmp_path / "b.csv", [row2])
        second = import_chart_of_accounts(
            db, organization_id=5, csv_path=source2,
            source_file_hash=SOURCE_FILE_HASH, observed_at=OBSERVED_AT,
        )
        assert second.updated == 0
        assert second.unchanged == 1
        audits = db.query(AccountImportChange).all()
        assert all(a.changes for a in audits), "שורת audit עם changes ריק"
    finally:
        db.close()
```

(להתאים את שמות הקבועים `SOURCE_FILE_HASH`/`OBSERVED_AT` ואת שדה האחוז לשמות בפועל בקובץ הטסטים.)

- [ ] **Step 2:** ריצה — FAIL (`updated == 1` ו-audit ריק).
- [ ] **Step 3: המימוש** — (א) ב-`_json_value`:

```python
def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        # normalize: '25' ו-'25.0000' שווים מספרית — hash לפי הערך, לא לפי
        # הסקייל הטקסטואלי של ה-CSV (F9).
        return format(value.normalize(), "f")
```

(ב) בנתיב העדכון, אחרי `changes = _field_changes(existing, incoming)` (שורה 309):

```python
            changes = _field_changes(existing, incoming)
            if not changes:
                # hash ישן בסקייל אחר (לפני ה-normalize) — אין שינוי מהותי:
                # מיישרים את ה-hash בלי שורת audit ריקה ובלי לספור update.
                existing.row_hash = incoming["row_hash"]
                existing.source_file_hash = digest
                existing.observed_at = observed
                existing.synced_at = synced
                result.unchanged += 1
                continue
```

- [ ] **Step 4:** `python -m pytest tests/test_chart_of_accounts_importer.py -q` — PASS (כולל טסטי ה-hash הקיימים; אם טסט קיים קיבע hash ספציפי — לעדכן את הערך המצופה ולציין בהודעת ה-commit).
- [ ] **Step 5: Commit** — ‏`git commit -m "fix(accounts-import): hash אדיש לסקייל עשרוני + אפס שורות audit ריקות (F9)"`

---

### Task 12: QA מלא, עדכון הלוח, ו-PR

**Files:**
- Modify: `docs/MASTER_EXECUTION_PLAN.md` (סעיף 2 — תמונת מצב)

- [ ] **Step 1:** ריצה מלאה: `python -m pytest tests/ -q` — ירוק; לתעד את המספר הסופי.
- [ ] **Step 2:** `cd frontend && npm run build && npm run lint` — ירוק.
- [ ] **Step 3:** `python scripts/audit_routes.py` (אם קיים לפי baseline ב-AGENTS.md) — להשוות לבסיס המדוד; סטייה = לחקור לפני commit.
- [ ] **Step 4:** אימות checkout נקי: `git status --porcelain` ריק + `git stash list` ריק.
- [ ] **Step 5:** לעדכן ב-`docs/MASTER_EXECUTION_PLAN.md` סעיף 2: שורת "ממשק שיחה" — להוסיף "10 ממצאי review 07/08 תוקנו"; ולהוסיף שורה: "אפיון התאוששות 07/08 — שלבים 1-3 הושלמו; הבא: deploy (שלב 4) באישור בעלים". commit: `docs(board): סטטוס אחרי תיקוני ה-review וסגירת הענף`
- [ ] **Step 6:** `git push -u origin chore/repo-order-and-control-plane` ופתיחת PR אחד ל-main עם `gh pr create` — בגוף: קישור לספק, רשימת 10 הממצאים שתוקנו, והצהרת הסטייה (PR אחד במקום 3 + הנימוק). לסיים את הגוף ב:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 7:** לדווח לבעלים: מספר טסטים סופי, קישור PR, ותזכורת ששלב 4 (deploy) ממתין לאישורו לפי `GATE0_DEPLOYMENT_RUNBOOK.md`.
