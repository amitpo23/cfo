# PR #103 — תיקונים אחרי REJECT 03.11.2026

מיפוי 21 הפריטים ברשימת התיקונים ל-CTO. טסטים: `tests/test_bank_match.py` (25 עוברים) ו-`frontend/src/components/bankMatchModel.test.ts` (7 עוברים, vitest).
`npx tsc --noEmit` נקי. במודולים השכנים (reconcil/dashboard/plan/eliav/payable/money/cashflow/period: 536 טסטים) נכשלים 10. אותם 10 בדיוק נכשלים גם ב-HEAD לפני התיקונים, בלי קשר לשינוי הזה.

## ⚠️ לפני פריסה: migration (תוספתי)

`alembic/versions/m50b2c3d4e5f_bank_match_decisions.py` (down: `k40a1b2c3d4e`) מוסיף שתי טבלאות חדשות, `bank_match_decisions` ו-`bank_match_documents`. אין שינוי בעמודה קיימת. ה-migration **לא הוחל בפרוד**. מחילים לפי `docs/GATE0_DEPLOYMENT_RUNBOOK.md`: נקודת שחזור pg_dump, GO של עמית, ואז `POST /api/admin/db/migrate`. `k40a1b2c3d4e` עדיין ממתין בעצמו, ולכן שניהם יעלו יחד.

## P0 — PR #103

| # | פריט | מצב | טסט |
|---|------|------|------|
| 1 | התאמה 1:N + עמלה | ✅ שורת בנק אחת מול כמה מסמכים. התנאי: \|בנק − (Σ מסמכים חתומים − עמלה)\| ≤ ₪1. ב-UI: «כמה מסמכים» עם הפרש רץ | `test_one_max_settlement_against_many_invoices_with_a_fee`, `test_one_card_charge_against_many_expenses_and_a_refund`, vitest `1:N match` |
| 2 | אישור לפי קטגוריה בלי מסמך | ✅ `approve_category`: חו״ז בעלים, שכר, הלוואה, ניכיון, סליקה. כרטיס יעד חובה, והבעלים מזין אותו. אין מספר כרטיס ברירת מחדל בקוד. השורה נספרת כמאוזנת | `test_approve_by_category_without_a_document` |
| 3 | "מאוזן" רק כשאין ממתין ואין חסר מסמך | ✅ `balanced` = כל השורות הוסברו. שורה בבדיקה או חסרת מסמך = "הוכרע, לא מאוזן — חסרים N מסמכים ₪X". הבדיקה האריתמטית הישנה נקראת עכשיו `coverage_ok` | `test_balanced_only_when_every_row_is_explained`, `test_owner_approves_flags_and_reopens` |
| 4 | לא להציע מסמך שכבר מותאם או חשבונית ששולמה | ✅ "תפוס" נבדק בכל הארגון: שורות `is_reconciled`, שורות התאמה, הקצאות קבלה פעילות. חשבונית או חשבון ספק בסטטוס paid/void/cancelled לא מוצעים. ההתאמה האוטומטית של השורה עצמה עדיין מוצעת עליה. אינדקס ייחודי ב-DB: מסמך אחד מסביר שורה אחת | `test_a_document_taken_anywhere_in_the_org_is_not_offered`, `test_a_document_matched_to_another_row_cannot_be_approved_again`, `test_paid_invoices_are_not_open_but_credit_notes_are` |
| 5 | החלטה + עדכון DB בטרנזקציה אחת, בלי JSON ב-plan | ✅ ההחלטה עברה לטבלאות. ה-route מבצע commit אחד, וכל כשל מגלגל אחורה. PUT של plan עם `bankMatchDecisions` נדחה (422) לכל תפקיד | `test_a_failure_rolls_back_the_decision_and_the_bank_columns`, `test_the_plan_never_carries_match_decisions` |
| 6 | API ציבורי במקום `_assert_not_allocated/_load_entity` | ✅ ב-`ManualReconciliationService` יש עכשיו `assert_not_allocated`, `assert_matchable`, `get_document`, `mark_reconciled`, `clear_reconciled`. אף אחת מהן לא מבצעת commit. `_assert_not_allocated` הוסרה | `test_bank_match_uses_only_the_public_reconciliation_api` (AST), `test_public_reconciliation_building_blocks_do_not_commit` |
| 7 | זיכויים והחזרים | ✅ השפעה חתומה על הבנק: חשבונית +, זיכוי מכירה −, חשבון ספק/הוצאה −, זיכוי ספק/החזר +. זיכוי מסונכרן (status=paid, total<0) נשאר פתוח. מסמך ששולם חלקית מותאם לפי ה-balance | `test_credit_notes_and_refunds_are_offered_in_their_bank_direction`, `test_paid_invoices_are_not_open_but_credit_notes_are`, `test_one_card_charge_against_many_expenses_and_a_refund` |

נוסף גם ממצא אבטחה מהבדיקה האוטומטית: רשימת המסמכים לבחירה (`documents`) לא נשלחת לקישור הציבורי ולמשתמש בצפייה בלבד, וחלון ההתאמה מוגבל ל-92 יום. נבדק ב-`test_public_link_reads_but_does_not_write` וב-`test_an_accountant_cannot_record_a_match_decision`.

## P0 — כלי 3: P&L + תזרים

| # | פריט | מצב | טסט / מה נותר |
|---|------|------|------|
| 8 | P&L אחד בכל המסכים | ⏳ נותר. #102 מאחד את ה-period payload, ויש טסטים: `test_cashflow_period_and_dashboard_routes_share_one_payload`, `test_budget_vs_actual_reads_the_same_dashboard_as_the_period_payload`. **חסר** טסט שמשווה את 4 המסכים (/daily-reports, /budget, /pnl, דשבורד) ואימות לאוקטובר בפרוד |
| 9 | יתרה + מסגרת + ניצול + פנוי + חריגה | ⏳ חלקי (#99): `credit_overrun` ב-liquidity, נבדק ב-`test_overrun_uses_the_booked_balance_not_the_friendlier_number`. **חסר**: פירוט לכל חשבון (FG/שף בנפרד), אותה יתרה בכל מסך, באדג׳ אדום בכל מסך, ואימות בפרוד |
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
- **התאמה מרובה או לפי קטגוריה** כותבת `matched_entity_type='bank_match'` (כמו התקדים `settlement_allocation`). קוראים שבודקים `=='bill'/'invoice'` (`bank_expense_gap`, `open_payables`, `ledger_service`, `dashboard_service`) לא מזהים אותה עדיין כמסמך. זה נותר להמשך. התאמה 1:1 בלי עמלה כותבת את העמודות הישנות כמו קודם.
- **לא נבדק בדפדפן.** נבדקו רק tsc, eslint ו-vitest למודל.
