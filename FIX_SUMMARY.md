# PR #103 — תיקונים אחרי REJECT 03.11.2026

מיפוי 21 הפריטים ברשימת התיקונים ל-CTO. טסטים: `tests/test_bank_match.py` (25 עוברים) ו-`frontend/src/components/bankMatchModel.test.ts` (7 עוברים, vitest).
סבב 2 (03.11): סוויטה מלאה, הענף 3,579 / 46 מול baseline `450bed1` 3,569 / 45. הכשל החדש היחיד (`test_the_migration_adds_it_on_top_of_the_single_head`) תוקן. התוצאות העדכניות נמצאות בסעיף (c) למטה.

## סבב 3 (04.11.2026): פערי האימות

### (c) CI למטה, ולכן הכול הורץ מקומית (04.11.2026)

CI של GitHub לא רץ בכלל: החשבון נעול בגלל בעיית חיוב. כל הראיות כאן הן מהרצות מקומיות (macOS, Python 3.12 מה-venv של ה-checkout הראשי, SQLite זמני לכל ריצה).

| בדיקה | תוצאה |
|---|---|
| `pytest tests/` על הענף (סבב 3, לפני commit) | `45 failed, 3590 passed, 8 skipped in 1126.42s` |
| `pytest tests/` על baseline `3db71c5` (ה-head הקודם, worktree נקי) | `45 failed, 3578 passed, 10 skipped in 1112.53s` |
| השוואת כשלים לפי שם (`comm` על שורות `FAILED`) | **זהות. 0 כשלים חדשים, 0 שתוקנו.** 45 הכשלים קיימים כבר ב-baseline |
| הפרש של 12+ עוברים | 10 טסטים חדשים ב-`tests/test_bank_match_consumers.py`, ועוד 2 טסטי node (`test_dashboard_eliav_ui_r2.py:43`, `test_dashboard_eliav_ui_fixes.py:125`) שדולגו ב-baseline רק כי ב-worktree שלו אין `frontend/node_modules` |
| טסטים ממוקדים: `test_bank_match_consumers.py` + `test_bank_match.py` + `test_sumit_rate_limit_hard_rule.py` | `40 passed` |
| red check (הורץ שוב בסבב הזה): ה-helper והקובץ החדש על הצרכנים של `3db71c5` | `6 failed, 4 passed`. נכשלים: open_payables, AR aging, כרטסת, פער, גבייה, route ה-503 |
| `cd frontend && npx tsc --noEmit` (TypeScript 5.9.3, node 22.22.0) | exit 0, בלי פלט |
| `cd frontend && npm run build` | `✓ built in 12.41s`, exit 0 |

`frontend/node_modules` ב-worktree הזה הוא symlink ל-checkout הראשי. `package-lock.json` זהה בשניהם (`diff -q` נקי), ולכן ה-build רץ על אותן תלויות.

### (a) התאמה מרובה או לפי קטגוריה נחשבת מותאמת בכל הקוראים

helper ציבורי אחד: `src/cfo/services/bank_match_settlements.py`.
- `bank_match_settlements(db, org_id, entity_types, entity_ids)` מחזיר לכל מסמך בהחלטה חיה את סכום השורה שלו. החלטה חיה פירושה ששורת הבנק `is_reconciled`, לא superseded, ועדיין מחזיקה `('bank_match', decision.id)`, וההחלטה `approved`. זה אותו כלל שמסך ההתאמה משתמש בו.
- `is_bank_match(txn)`: השורה מוסברת בהחלטת בעלים, במסמכים או בקטגוריה.
- `match_tables_ready(db)`: בודק אם ה-migration הוחל. קורא רק את ה-catalog, ולכן לא מפיל טרנזקציה ב-Postgres.

הכלל: **כל מסמך מכוסה בסכום השורה שלו, לא בסכום שורת הבנק.** חיוב כרטיס אחד מול 5 חשבונות ספק מכסה כל חשבון לפי הסכום שלו. ההשוואה היא לשוויון מול התאמת 1:1 של היום, בלי סמנטיקה חדשה.

| קורא | שינוי | טסט (`tests/test_bank_match_consumers.py`) |
|---|---|---|
| `open_payables.confirmed_cover` | שורת החלטה נכנסת ל-`bank_direct` לפי `abs(line.amount)`. ה-AP הפתוח בדשבורד ו-`get_ap_aging` עוברים דרכו | `test_open_payables_cover_each_bill_by_its_own_line_not_the_whole_charge` |
| `dashboard_service.get_ar_aging` / `get_ap_aging` | `bank_movement_seen` כולל גם מסמכים מהחלטה. ב-AR, כמו ב-1:1 היום, זה דגל + `bank_movement_seen_total` ולא הורדה מהיתרה | `test_ar_aging_flags_invoices_matched_one_to_many` |
| `ledger_service.contact_card` | תנועת `bank_settlement` לכל שורה של מסמכי איש הקשר, לפי סכום השורה. dedupe מול `Payment` נשמר | `test_the_contact_card_settles_each_invoice_by_its_line` |
| `bank_expense_gap` | שורת `bank_match` מוסברת בצד היציאות (`_find_document_match`) ובצד הכניסות (`_find_invoice_match`). ב-`gap_report` שורה שאושרה מול מסמכים נספרת "מתועדת", ושורה שאושרה לפי קטגוריה נכנסת ל-`excluded_by_class["bank_match_category"]` | `test_the_gap_report_counts_matched_rows_as_explained` |
| `collection_service._bank_payment_detected` (נוסף) | חשבונית ששולמה בתקבול 1:N לא מקבלת תזכורת גבייה. שורת זיכוי (שלילית) אינה תשלום חוב | `test_no_collection_reminder_for_an_invoice_matched_one_to_many`, `test_a_matched_credit_note_does_not_stop_reminders_for_another_invoice` |
| ה-helper עצמו | שורות לפי מסמך, סינון, reopen, ושורת בנק שכבר לא מחזיקה את ההחלטה | `test_the_helper_lists_each_matched_document_with_its_own_amount`, `test_a_bank_row_that_no_longer_holds_the_decision_settles_nothing` |

כל טסט בונה התאמה 1:N אמיתית דרך `decide()` (שתי חשבוניות + עמלה, שני חשבונות ספק, שורת שכר לפי קטגוריה), עם סכומים ושמות מומצאים. **red check:** כשהצרכנים מוחזרים לגרסת `3db71c5`, 6 מטסטי הצרכנים וה-route נכשלים. עם התיקון כל ה-10 עוברים.

ידוע ולא שונה (זהה ל-1:1): חשבון ספק ששולם חלקית מכוסה בסכום הפתוח שלו בזמן האישור. `remaining_of` לוקח `max(paid, cover)`, ולכן עלול להשאיר יתרה. זה אותו פער שקיים היום בהתאמת 1:1 של `bank_direct`.

### (b) לפני ה-migration: הודעה ברורה, לא 500

- שלושת ה-routes של הטאב (GET, POST, וה-GET הציבורי `/api/public/d/{slug}/bank-match`) בודקים `match_tables_ready` לפני כל שאילתה. אם הטבלאות חסרות, הם מחזירים **503** `migration_pending` עם הודעה בעברית: "מסך התאמת בנק עדיין לא הופעל בשרת הזה…". ה-frontend מציג את `message_he` כמו שהוא. אין שינוי ב-UI.
- הקוראים מ-(a) לא נוגעים בטבלאות החדשות כל עוד אין שורת בנק `bank_match`. לפני ה-migration אין שורה כזו, וגם `match_tables_ready` נבדק. שאר המסכים ממשיכים לעבוד על התאמות 1:1.
- הטסטים מוחקים את שתי הטבלאות ב-DB של הטסט ומשחזרים אותן: `test_the_match_screen_says_the_migration_is_pending_instead_of_a_500` ו-`test_without_the_match_tables_readers_keep_their_one_to_one_matches`.
- ה-migration עצמו לא שונה. הוא תוספתי: שתי טבלאות חדשות, בלי שינוי בעמודה קיימת.

## ⚠️ לפני פריסה: migration (תוספתי). דורש GO של עמית. לא הורץ דבר מול פרוד

`alembic/versions/m50b2c3d4e5f_bank_match_decisions.py` (down: `k40a1b2c3d4e`) מוסיף שתי טבלאות חדשות, `bank_match_decisions` ו-`bank_match_documents`. אין שינוי בעמודה קיימת. ה-migration **לא הוחל בפרוד**. `k40a1b2c3d4e` (`available_limit`) עדיין ממתין בעצמו, ולכן שניהם יעלו יחד.

צעדים, לפי `docs/GATE0_DEPLOYMENT_RUNBOOK.md`:
1. **גיבוי קודם:** נקודת שחזור `pg_dump` של מסד Neon של פרוד. לשמור את הנתיב ואת ה-hash.
2. **GO מפורש של עמית** לפני החלת ה-migration.
3. החלה: `POST /api/admin/db/migrate`, שמעלה את `k40a1b2c3d4e` ואחריו את `m50b2c3d4e5f`.
4. אימות: ש-`alembic_version` = `m50b2c3d4e5f`, שהטבלאות קיימות, ושהטאב מחזיר 200 במקום 503. סקריפט DDL חלקי אינו הוכחת `head`.

ב-Vercel `auto_create_db=False`, ולכן `create_all` לא רץ בעלייה והטבלאות לא נוצרות מעצמן. **מאז סבב 3, מיזוג לפני ה-migration כבר לא מחזיר 500.** הטאב מציג "לא הופעל" (503), ושאר המסכים לא מושפעים. אבל הטאב לא שמיש עד שה-migration יוחל.

## P0 — PR #103

| # | פריט | מצב | טסט |
|---|------|------|------|
| 1 | התאמה 1:N + עמלה | ✅ שורת בנק אחת מול כמה מסמכים. התנאי: \|בנק − (Σ מסמכים חתומים − עמלה)\| ≤ ₪1. ב-UI: «כמה מסמכים» עם הפרש רץ | `test_one_max_settlement_against_many_invoices_with_a_fee`, `test_one_card_charge_against_many_expenses_and_a_refund`, vitest `1:N match` |
| 2 | אישור לפי קטגוריה בלי מסמך | ✅ `approve_category`: חו״ז בעלים, שכר, הלוואה, ניכיון, סליקה. כרטיס יעד חובה, והבעלים מזין אותו. אין מספר כרטיס ברירת מחדל בקוד. השורה נספרת כמאוזנת | `test_approve_by_category_without_a_document` |
| 3 | "מאוזן" רק כשאין ממתין ואין חסר מסמך | ✅ `balanced` = כל השורות הוסברו. שורה בבדיקה או חסרת מסמך = "הוכרע, לא מאוזן — חסרים N מסמכים ₪X". הבדיקה האריתמטית הישנה נקראת עכשיו `coverage_ok` | `test_balanced_only_when_every_row_is_explained`, `test_owner_approves_flags_and_reopens` |
| 4 | לא להציע מסמך שכבר מותאם או חשבונית ששולמה | ✅ "תפוס" נבדק בכל הארגון: שורות `is_reconciled`, שורות התאמה, הקצאות קבלה פעילות. חשבונית או חשבון ספק בסטטוס paid/void/cancelled לא מוצעים. ההתאמה האוטומטית של השורה עצמה עדיין מוצעת עליה. אינדקס ייחודי ב-DB: מסמך אחד מסביר שורה אחת. **סבב 3:** מסמך שהותאם 1:N או עם עמלה כבר לא מופיע כחוב פתוח ב-AP, בכרטסת, בפער ובגבייה | `test_a_document_taken_anywhere_in_the_org_is_not_offered`, `test_a_document_matched_to_another_row_cannot_be_approved_again`, `test_paid_invoices_are_not_open_but_credit_notes_are` |
| 5 | החלטה + עדכון DB בטרנזקציה אחת, בלי JSON ב-plan | ✅ ההחלטה עברה לטבלאות. ה-route מבצע commit אחד, וכל כשל מגלגל אחורה. PUT של plan עם `bankMatchDecisions` נדחה (422) לכל תפקיד | `test_a_failure_rolls_back_the_decision_and_the_bank_columns`, `test_the_plan_never_carries_match_decisions` |
| 6 | API ציבורי במקום `_assert_not_allocated/_load_entity` | ✅ ב-`ManualReconciliationService` יש עכשיו `assert_not_allocated`, `assert_matchable`, `get_document`, `mark_reconciled`, `clear_reconciled`. אף אחת מהן לא מבצעת commit. `_assert_not_allocated` הוסרה | `test_bank_match_uses_only_the_public_reconciliation_api` (AST), `test_public_reconciliation_building_blocks_do_not_commit` |
| 7 | זיכויים והחזרים | ✅ השפעה חתומה על הבנק: חשבונית +, זיכוי מכירה −, חשבון ספק/הוצאה −, זיכוי ספק/החזר +. זיכוי מסונכרן (status=paid, total<0) נשאר פתוח. מסמך ששולם חלקית מותאם לפי ה-balance | `test_credit_notes_and_refunds_are_offered_in_their_bank_direction`, `test_paid_invoices_are_not_open_but_credit_notes_are`, `test_one_card_charge_against_many_expenses_and_a_refund` |

נוסף גם ממצא אבטחה מהבדיקה האוטומטית: רשימת המסמכים לבחירה (`documents`) לא נשלחת לקישור הציבורי ולמשתמש בצפייה בלבד, וחלון ההתאמה מוגבל ל-92 יום. נבדק ב-`test_public_link_reads_but_does_not_write` וב-`test_an_accountant_cannot_record_a_match_decision`.

## P0 — כלי 3: P&L + תזרים

| # | פריט | מצב | טסט / מה נותר |
|---|------|------|------|
| 8 | P&L אחד בכל המסכים | ⏳ נותר. #102 מאחד את ה-period payload, ויש טסטים: `test_cashflow_period_and_dashboard_routes_share_one_payload`, `test_budget_vs_actual_reads_the_same_dashboard_as_the_period_payload`. **חסר** טסט שמשווה את 4 המסכים (/daily-reports, /budget, /pnl, דשבורד) ואימות לאוקטובר בפרוד |
| 9 | יתרה + מסגרת + ניצול + פנוי + חריגה | ⏳ חלקי (#99): `credit_overrun` ב-liquidity, נבדק ב-`test_overrun_uses_the_booked_balance_not_the_friendlier_number`. **חסר**: פירוט לכל חשבון בנפרד, אותה יתרה בכל מסך, באדג׳ אדום בכל מסך, ואימות בפרוד |
| 10 | תחזית: כרטיסים, החזרי הלוואה, שכר, מע״מ | ⏳ נותר. התחזית ל-13 שבועות יודעת פריטים מתוארכים, פירעון הלוואה ופריטי בעלים (`test_cash_forecast_13w.py`). **חסר**: חיוב כרטיסים מ-interimBooked של OF, פריט שכר קבוע ב-10 לחודש, מע״מ, והבאג "/forecasting מציג יציאה 0" (לא אובחן) |
| 11 | הלוואות/ניכיון = מימון; אזהרת צ׳ק חוזר | ✅ חלקי. מימון: #99 (`test_discount_repayment_is_not_recurring_principal_and_the_fee_is_not_income`). כאן אפשר גם לאשר שורה בקטגוריית הלוואה/ניכיון. **חדש**: שורת צ׳ק חוזר במסך ההתאמה מציגה אזהרת הכנסה כפולה ומציינת חשבונית באותו סכום (`test_a_returned_cheque_warns_of_double_income_and_names_the_same_amount_invoice`). **חסר**: אימות #99 בפרוד, והאזהרה במסכי התזרים וה-P&L |
| 12 | פילטר יום/שבוע/חודש/טווח + עמודות בנק/סאמיט/תקציב | ⏳ לא נבדק בסשן הזה. #92 הוסיף טווחים והשוואה משלושה מקורות (`PeriodCompare.tsx`). לא אימתתי שזה מופיע בכל מסכי הכסף |
| 13 | placeholder של 10M | ✅ בקוד: `test_placeholder_income_is_excluded_from_the_total_and_the_displayed_amount` (#99, ירוק). ⏳ אימות בפרוד נותר |

## P1

| # | פריט | מצב |
|---|------|------|
| 14 | חסימת כפילות לפני תיוק/ייבוא | ⏳ נותר. מחוץ ל-scope של PR #103 |
| 15 | /documents לכל ארגון + סטטוסים | ⏳ נותר |
| 16 | מיפוי ספק→כרטיס שמור | ⏳ נותר |
| 17 | סנכרון OF לילי | ⛔ לא נגעתי. ההנחיה: לא להפוך את `OPEN_FINANCE_SCHEDULED_SYNC_ENABLED`. נדרשת הכרעת בעלים |
| 18 | באנר "בנק עד X · ספרים עד Y" | ✅ חלקי: מופיע במסך ההתאמה (`partial_banner`) ובמסכי הכסף מ-#99 (`test_partial_banner_names_bank_and_books_dates`). לא אימתתי שהוא מופיע בכל מסך |
| 19 | מיפוי ארגון עמית פורת ל-OF | ⛔ ממתין לאישור עמית |
| 20 | ניטור מכסת Neon | ⏳ נותר |
| 21 | `SUMIT_ENV_CREDENTIAL_ORG_IDS` | ⛔ ממתין ל-GO של עמית. לא בוצע |

## הערות

- **מסמך אחד ↔ שורת בנק אחת** (אינדקס ייחודי). מסמך שמשולם בכמה העברות בנק עדיין לא נתמך: הבעלים מסמן "בדיקה".
- **דוחות Z** ב-plan הם סיכומים חודשיים, ולכן אינם מסמכים להתאמה. סליקת מקס מותאמת מול שורות Invoice (מסמכי Z/חשבוניות מסונכרנים).
- **התאמה מרובה או לפי קטגוריה** כותבת `matched_entity_type='bank_match'` (כמו התקדים `settlement_allocation`). מאז סבב 3 כל הקוראים מזהים אותה דרך `bank_match_settlements` (ראו (a) למעלה). התאמה 1:1 בלי עמלה כותבת את העמודות הישנות כמו קודם.
- **אין שליחה ל-SUMIT.** `mark_reconciled` מסמן `reconciliation_dispatch_status='not_sent'`, ו-`reconciliation_dispatch` עשוי לאסוף שורות `bank_match`. אבל הוא אף פעם לא שולח: הוא מסמן רק `failed`/`unsupported`/`approval_required`, כי אין adapter מאושר.
- **לא נבדק בדפדפן.** נבדקו רק tsc, eslint ו-vitest למודל.
