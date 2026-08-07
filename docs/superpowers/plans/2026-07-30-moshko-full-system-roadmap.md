# מפת דרכים — מושקו כמערכת מלאה לפיילוט לקוח

**נכתב:** 2026-07-30 · **מבוסס על בדיקת קוד וסביבת פרוד חיה**
**היעד:** לקוח אמיתי משתמש במושקו בוואטסאפ, מנצל את מלוא יכולות רצף, ואנחנו רואים בזמן אמת מה נשאל, מה בוצע, מה עלה, ומה מושקו למד.

---

## 1. מה כבר קיים (נבדק, לא הערכה)

### 1.1 יכולות רצף בשיחה — **46 כלים, כיסוי רחב מאוד**
`src/cfo/services/ai_chat_tools.py` — מושקו כבר יודע לעשות:

| תחום | כלים |
|---|---|
| **גבייה ולקוחות** | `get_ar_aging`, `get_collection_cases`, `log_collection_attempt`, `get_ar_health`, `create_payment_link`, `search_contacts` |
| **ספקים והוצאות** | `get_ap_bills`, `list_expenses`, `classify_pending_expenses`, `file_expense`, `set_expense_category`, `create_expense_category`, `get_learned_rules`, `get_expense_intake_status`, `get_suppliers_missing_invoices` |
| **בנק ותזרים** | `query_bank_transactions`, `get_bank_position`, `get_cashflow`, `connect_bank_account`, `create_bank_payment_request`, `get_credit_line_status`, `get_bank_expense_gap_alerts` |
| **הנה"ח ודיווח** | `get_pnl`, `get_ledger_card`, `get_vat_position`, `get_tax_estimate`, `verify_filing`, `propose_vat_filing_approval`, `list_pending_approvals`, `get_missing_documents`, `issue_document`, `list_invoices` |
| **ניהול משרד (רו"ח)** | `list_office_clients`, `get_office_rollup`, `get_client_overview`, `run_client_sync`, `register_office_client` |
| **ידע ותובנות** | `kb_lookup`, `rezef_help`, `get_cfo_insights`, `get_daily_brief`, `get_engine_status`, `email_report` |
| **זיכרון** | `memory`, `search_history` |

**מסקנה: אין פער יכולות משמעותי.** מושקו כבר נוגע ב-SUMIT, ב-Open Finance, ובמנוע ההנה"ח.

### 1.2 מערכת ניהול ידע — **קיימת בשלוש שכבות, אך ללא ממשק ניהול**
1. **ידע מקצועי סטטי** — `docs/bookkeeper_kb/` (7 מסמכים: הכרה בהוצאות, ניכוי תשומות, גשר סיווג, מסמכים וראיות) + `docs/sumit_help_kb/` (609 מאמרים) — נגיש דרך `kb_lookup`.
2. **ידע על רצף** — `services/rezef_kb.py` — "מה רצף יודעת לעשות", נגיש דרך `rezef_help`.
3. **זיכרון לומד** — `MoshkoMemory` ([models.py:1642](src/cfo/models.py:1642)) בשני scope (עסק/משתמש), עם קטגוריות `preference | business_fact | correction | convention`. נכתב **רק ע"י המודל עצמו** דרך כלי `memory`.

**הפער:** אין דרך לבן-אדם לראות, לערוך, לאשר או למחוק מה שמושקו למד. אם הוא למד משהו שגוי — זה נשאר.

### 1.3 מעקב משימות — **טבלה קיימת, לא מחוברת לבוט**
`Task` ([models.py:1323](src/cfo/models.py:1323)) עם `status`, `due_date`, `entity_type/id`, `alert_id`. **אבל אין כלי `create_task` ברשימת 46 הכלים** — מושקו לא יכול לפתוח משימה, ומה שהמשתמש מבקש ממנו לא הופך למשימה מעקב.

### 1.4 תשתית ערוץ — מוכנה
ארבעת ערכי WhatsApp בפרוד ✅ · ראוט webhook חי (403 בלי חתימה) ✅ · אימות מייל מוקשח (3 בקשות/שעה, 5 ניחושים, ריפוד זמן) ✅ · שעות שקט 22:00–07:00 ✅ · opt-in פר-משתמש ✅

---

## 2. הפערים — מה חוסם פיילוט לקוח

| # | פער | חומרה | סטטוס |
|---|---|---|---|
| G1 | **SMTP לא מוגדר** — אף לקוח לא יכול להתחבר בוואטסאפ | 🔴 חוסם מוחלט | הבעלים |
| G2 | **אין observability** — אין מדידת טוקנים/עלות, אין לוג קריאות כלים, אין מסך אדמין | 🔴 חוסם פיילוט | **Codex — בביצוע** |
| G3 | **דחיפה יזומה לא עובדת בוואטסאפ** | 🟡 | **Codex — בביצוע** |
| G4 | **אין ממשק לניהול הידע הלומד** — אי אפשר לראות/לתקן מה מושקו למד | 🟡 | לא התחיל |
| G5 | **מושקו לא פותח משימות** — אין `create_task`/`list_tasks`; בקשות לא הופכות למעקב | 🟡 | לא התחיל |
| G6 | **טלגרם כבוי** (`TELEGRAM_BOT_TOKEN` חסר) — אין ערוץ גיבוי ואין דחיפות ללא מגבלת 24ש' | 🟢 | הבעלים, 2 דקות |
| G7 | **אין מסך "ידע מקצועי"** — ה-KB נגיש רק לבוט, לא לאדם | 🟢 | לא התחיל |

---

## 3. שלבי ההשלמה

### שלב 1 — פתיחת החסימה (הבעלים, ~15 דקות) 🔴
**1א. SMTP** — חמישה משתנים ל-Vercel Production. Gmail עם App Password הוא המהיר ביותר:
`SMTP_HOST=smtp.gmail.com` · `SMTP_PORT=587` · `SMTP_USER` · `SMTP_PASSWORD` (app-password!) · `SMTP_FROM`

**1ב. אימות Meta** — Callback URL `https://cfo-2.vercel.app/api/whatsapp/webhook`, subscribe ל-`messages`, המספר ברשימת הנמענים (עד 5).

**1ג. הרצת אימות** — `python scripts/check_whatsapp_setup.py --send-to 972...` — **הבעלים בלבד** (רשת חיה).

**1ד. (מומלץ) טלגרם** — טוקן מ-BotFather + `TELEGRAM_WEBHOOK_SECRET`. נותן ערוץ גיבוי בלי תלות ב-SMTP ובלי מגבלת חלון 24 שעות.

**תוצאה:** מושקו חי ואתה מדבר איתו.

### שלב 2 — observability (Codex, בביצוע) 🔴
טבלת שימוש בטוקנים ועלות (קריאת `response.usage` שנזרקת היום; תמחור בקונפיג — `llm_pricing_json` כבר נוסף), לוג כל 46 קריאות הכלים עם סיווג יעד (SUMIT/OF/רצף), ראוטים `/api/admin/moshko/{conversations,tool-calls,usage}` ל-SUPER_ADMIN, מסך frontend, וחיטוי ערכים רגישים. במקביל: הכללת הדחיפה היזומה לוואטסאפ עם טיפול כן בחלון 24 השעות (`whatsapp_push_template_name` כבר נוסף לקונפיג).

**תוצאה:** אתה רואה מה נשאל, מה רץ, וכמה זה עלה.

### שלב 3 — ניהול ידע ומשימות (Codex, אחרי שלב 2) 🟡
**3א. מסך ניהול הזיכרון הלומד** — לראות כל רשומת `MoshkoMemory` פר-ארגון ופר-משתמש, לערוך, למחוק, ולסמן "מאושר". להוסיף `source='admin'` לרשומות שבן-אדם הזין. **קריטי:** זיכרון שגוי מזהם כל תשובה עתידית.

**3ב. חיבור מושקו למשימות** — כלים חדשים `create_task` / `list_tasks` / `update_task` על טבלת `Task` הקיימת. כשלקוח אומר "תזכיר לי לשלם לספק ב-15" — זו משימה, לא הודעה שנעלמת. חיבור ל-`Alert` הקיים.

**3ג. מסך ידע מקצועי** — הנגשת `bookkeeper_kb` ו-`rezef_kb` בממשק לאדם, לא רק לבוט.

**תוצאה:** הידע מנוהל ומתוקן; המשימות במעקב.

### שלב 4 — deploy ופיילוט מבוקר 🔴
מיזוג PR + מיגרציות בפרוד לפי [GATE0](../../GATE0_DEPLOYMENT_RUNBOOK.md). ⚠️ **שים לב: גם מיגרציית אינדקס חשבשבת (`c5d6e7f8a9b0`) ממתינה** — הכול ייכנס יחד.

**פיילוט:** להתחיל **בעצמך בלבד** לשבוע. לקרוא כל שיחה ב-observability, לתקן זיכרונות שגויים, למדוד עלות ממוצעת לשיחה. רק אז לקוח ראשון — עדיף עומר ועודד (org5), שהתיק שלו כבר קלוט ומאומת.

### שלב 5 — הידוק לפני פתיחה רחבה 🟢
תקרת עלות פר-ארגון (אחרי שיש מדידה — לא לפני), מספר WhatsApp קבוע (מצריך אימות עסקי ב-Meta; החלפת 4 ערכים, אפס קוד), ותבניות מאושרות לדחיפות מחוץ לחלון.

---

## 4. סדר עדיפויות

```
היום:        שלב 1 (SMTP + Meta)  ←  אתה. פותח את החסימה.
במקביל:      שלב 2 (observability) ←  Codex. רץ עכשיו.
אחר כך:      שלב 3 (ידע + משימות) ←  Codex.
ואז:         שלב 4 (deploy + פיילוט עצמי שבוע)
לבסוף:       שלב 5 (לקוח ראשון)
```

## 5. הכלל שלא כדאי לשבור
**אין פיילוט לקוח לפני ששלב 2 בפרוד.** בלי מדידת עלות אין תקרה, ובלי לוג כלים אין ראיה למה שנעשה בשם הלקוח — וזו מערכת שנוגעת בספרים ובדיווחים לרשויות.
