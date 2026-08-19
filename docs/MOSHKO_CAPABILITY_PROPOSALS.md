# מפת היכולות המוצעת למושקו — טיוטת עיצוב

**גרסה:** `0.1.0-draft`  
**תאריך:** 2026-08-17 (נמצא untracked בגיט, לא נבדק, עד 2026-08-19)  
**מקור:** טיוטת ייעוץ לסוכן פיתוח; לא מחליף את `MASTER_EXECUTION_PLAN.md` או `REZEF_OPERATING_SYSTEM.md`. תוקנו כאן שיבושי קידוד (תווים זרים/מילים חתוכות) שהיו בגרסה המקורית.  
**סטטוס:** `parking-lot` — ממתין להחלטת בעלים על שער פעיל רלוונטי.  
**הוראות שימוש:** מסמך זה עומד בזכויות הפרויקט הרציף; ניתן להפנות אליו, אך אין לבצע שינוי בקוד או בקטלוג היכולות ללא שער פעיל.

## עדכון סטטוס (19/08/2026)

המסמך נבדק לראשונה מול המצב בפועל. שלושה מהעשרה כבר קיימים או כוסו חלקית — לא לבנות מחדש:

- **#2 `bank_reconciliation_status`** — מיותר. `get_bank_reconciliation` ו-`get_ap_aging` (עם `bank_movement_seen` פר-חשבון) כבר עושים בדיוק את זה, כלי מושקו קיים.
- **#5 `budget_vs_actual`** — **בוצע היום.** `BudgetService.get_budget_vs_actual` היה בנוי (642 שורות) אבל קרא מ-`Transaction`, צינור קפוא שאין אליו כתיבה חיה מאז המעבר ל-SyncEngine (`LegacySyncRetiredError`) — תמיד היה מחזיר `{}` בשקט. תוקן לקרוא מ-`ledger_service.build_journal` (אותם ספרים נגזרים ש-Moshko כבר סומך עליהם), ונחשף ככלי `get_budget_vs_actual`. ר' `tests/test_budget_actuals_real.py`, `tests/test_budget_vs_actual_tool.py`.
- **#6 `list_open_exceptions`** / **#10 `integration_health`** — כוסו במידה רבה על-ידי `get_cfo_insights` (קורא `CfoInsight`, שכבר מאוחד על פני 4 סוגים: `bank_anomaly`, `credit_line_breach`, `parity_mismatch`, `sync_coverage`) ו-`get_daily_brief`, שניהם מוזנים ע"י `morning_cycle_service.run_morning_cycle` — אורקסטרטור יומי אחד שמריץ parity→bank_anomalies→reconcile→expense_queue→credit_line→daily_close→debtors בסדר תלות אחד, רשום ב-cron `/cron/bookkeeper-morning` (vercel.json). **לא אומת בסשן הזה שהוא רץ בפרוד בפועל בימים האחרונים** (honest-null — קוד קיים ≠ נמדד חי); לפני שקוראים לפער הזה סגור צריך למשוך זמינות/עדכניות `CfoInsight` מפרוד.
- שאר הפריטים (#1, #3, #4, #7, #8, #9) עדיין `parking-lot` כפי שהיו — לא נבנו.

## מטרה

להוסיף למושקו 10 כלי קריאה/כתיבה שמשרתים את העבודה היומית של המנהל/חשבון/בעלים, על בסיס הקוד הקיים ב-`src/cfo/services/ai_chat_tools.py`, `capability_tasks.py` ושירותי הליבה. הכלים החדשים לא יופעלו אוטומטית; כל כלי כתיבה עובר `confirm_action` ו-`policy_engine`.

---

## 1. שליחת בריף/דיווח במייל (`send_daily_brief_email`)

**טווח:** כתיבה מוגבלת  
**מקור:** `morning_brief_service.compose_brief` + `email_sender.send_email_smtp`  
**תיאור:** שולח את בריף הבוקר או סיכום תקופה בטקסט/PDF למייל מאושר.  
**פרמטרים:** `period`, `format`, `recipient_email`  
**בטיחות:** נמען נבדק מול `Contact` פעיל בארגון; alternately `user_supplied` אם המשתמש הזין כתובת במפורש. נדרש אישור מפורש לפני השליחה.

## 2. סטטוס התאמות בנק (`bank_reconciliation_status`)

**טווח:** קריאה  
**מקור:** `bank_reconciliation.py`, `manual_reconciliation.py`, `bank_expense_gap.py`  
**תיאור:** מחזיר unmatched transactions, סכומים מצטברים, וחריגי התאמה פתוחים.  
**פרמטרים:** `from_date`, `to_date`, `account_id`  
**בטיחות:** ארגון-scoped; לא חושף פרטי בנק מלאים.

## 3. חיפוש מסמכים (`search_documents`)

**טווח:** קריאה  
**מקור:** `expense_filing_service`, `document_issuance_service`, `sync_engine`  
**תיאור:** חיפוש טקסטורי על מסמכים/הוצאות/חשבוניות לפי סכום, ספק, תאריך, סטטוס.  
**פרמטרים:** `query`, `document_type`, `status`, `from_date`, `to_date`, `limit`  
**בטיחות:** org-scoped; מחזיר רק מטא-דאטה, לא קובץ מלא.

## 4. ניהול תזכורות גבייה (`send_collection_reminder`)

**טווח:** כתיבה  
**מקור:** `collection_case_service`, `ar_service`, `channel_notifier`  
**תיאור:** יוצר תזכורת חדשה או שולח תזכורת ספציפית מהצ'אט.  
**פרמטרים:** `case_id`, `channel`, `template`, `note`  
**בטיחות:** נדרש אישור מפורש; respects opt-in ו-`communication_opt_in`.

## 5. השוואת תקציב לביצוע (`budget_vs_actual`)

**טווח:** קריאה  
**מקור:** `forecasting_service`, `report_builder_service`  
**תיאור:** השוואת budget vs actual לקטגוריה/חודש/שנה, כולל variance ואחוז חריגה.  
**פרמטרים:** `year`, `month`, `category`, `compare_previous`  
**בטיחות:** honest-null: אם Budget חסר, מחזיר `null` עם סיבה.

## 6. רשימת חריגים פתוחים (`list_open_exceptions`)

**טווח:** קריאה  
**מקור:** `Alert`, `Task`, `SyncRun`, `morning_brief_service`  
**תיאור:** רשימת חריגים פתוחים עם אפשרות לטפל בהם: sync failures, policy blocks, bank anomalies.  
**פרמטרים:** `severity`, `status`, `older_than_hours`, `limit`  
**בטיחות:** SUPER_ADMIN רואה cross-org; מנהל ארגון רואה רק הארגון שלו.

## 7. שליחת בקשת תשלום ללקוח (`send_payment_link`)

**טווח:** כתיבה  
**מקור:** `payment_request_service`, `document_issuance_service`  
**תיאור:** יוצר payment link ושולח אותו למייל/SMS ללקוח מאושר.  
**פרמטרים:** `invoice_id`, `amount`, `channel`, `recipient_email`  
**בטיחות:** נדרש אישור מפורש; נמען נבדק מול Contact קיים.

## 8. סיכום חודשי אוטומטי (`monthly_summary`)

**טווח:** קריאה  
**מקור:** `financial_reports_service.generate_profit_loss`, `get_cashflow`, `get_ar_aging`, `get_ap_bills`  
**תיאור:** סיכום טקסטואלי של חודש מלא: הכנסות, הוצאות, גבייה, בנק, תזרים, חריגים.  
**פרמטרים:** `year`, `month`, `include_cashflow`, `include_ar_ap`  
**בטיחות:** משתנה `as_of` ו-`freshness` לכל מספר; לא מכניס למסקנות אלא מציג נתונים.

## 9. ניהול משימות מהצ'אט (`create_task` / `update_task_status`)

**טווח:** כתיבה  
**מקור:** `Task`, `cfo_tasks` routes, `moshko_tasks`  
**תיאור:** יצירת משימה חדשה או עדכון סטטוס קיים מהצ'אט.  
**פרמטרים:** `title`, `description`, `status`, `due_date`, `assignee_user_id`  
**בטיחות:** נדרש אישור מפורש; assignee נבדק מול חברות פעילה בארגון.

## 10. ניטור חיבורי ספקים (`integration_health`)

**טווח:** קריאה  
**מקור:** `roster_coverage.py`, `sync_engine`, `open_finance_connector`  
**תיאור:** מצב כל חיבורי SUMIT/Open Finance: last sync, errors, quota usage, obligo.  
**פרמטרים:** `source`, `org_id`, `include_quota`  
**בטיחות:** SUPER_ADMIN רואה cross-org; מנהל ארגון רואה רק מקורות פעילים בארגון שלו.

---

## קווי יסוד בטיחותיים לכל הכלים

1. **org-scoped** — כל כלי מוגבל לארגון המחובר לבקשת הצ'אט.
2. **honest-null** — אין מניפולציה של מספרים; תא חסר מחזיר `null` עם סיבה.
3. **policy/approval** — כל כלי כתיבה עובר `policy_engine` ו-`confirm_action`.
4. **redaction** — פרטי תשלום/סודות מוסתרים ב-`moshko_observability.redact_sensitive_text`.
5. **office-only** — כלים cross-org סומנים `office=True` ונגישים ל-`SUPER_ADMIN` בלבד.
6. **API discipline** — כלי חדש שלא צריך קריאת ספק חיה אינו פוגע בתקציב היומי.

---

## פעלות הבאות מוצעות

1. בחירת 2-3 כלים לשער הבא, לפי צורך העסקי.
2. הוספת טסטים אופליין לכל כלי (`tests/test_ai_chat_tools.py`/extend).
3. עדכון `capability_tasks.py` ו-`rezef_capabilities.json` רק אחרי prove.
4. הערכת השפעת תקציב API לכל כלי חדש שתלוי בספק חיצוני.
