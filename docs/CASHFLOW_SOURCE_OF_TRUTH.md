# מקור אמת אחד לתזרים — מצב מול 18 הפערים

תאריך: 28.10.2026. המפרט: שרשרת תקציב → תחזית 13 שבועות → ביצוע → התרעות, לכל ארגון, בלי ערכים של עסק מסוים.

האובייקט הקנוני הוא `view.cashflow_source`, נבנה ב־`src/cfo/services/dashboards/cashflow_truth.py` מנתונים שכבר נקראו לדשבורד. אין קריאת SUMIT או Open Finance, ואין מיגרציה: ברירות המחדל ודריסות הארגון יושבות ב־`plan.cashflowSettings`.

ברירות מחדל לכל ארגון: שבוע ראשון–שישי; מזומן שחל בשבת עובר ליום ראשון הבא ונמנה פעם אחת; שכר ב־10 (ואם ה־10 בשבת — בראשון שאחריו); ספקים = הגדרה מפורשת `supplierTermsMode` לכל ארגון. ברירת המחדל, עד שהבעלים יאשר, היא `eom_plus_30_days` (ספטמבר → 30.10). המצב השני `end_of_next_month` נותן 31.10, וכי 31.10.2026 הוא שבת המזומן עובר ליום ראשון 1.11. שני המצבים מזיזים שבת לראשון. יתרת פתיחה = עו״ש בלבד; מסגרת אשראי בשורה נפרדת, וראש פנוי = יתרה + מסגרת; חסר אינו 0 (`missing` / `assumption` / `confirmed`); הוצאות משותפות בשורה «משותף — לא מוקצה» בלי הקצאה; צ׳ק מנוכה = יתרת הלוואה קצרה שנשארת פתוחה עד יום הפדיון של אותו צ׳ק ואז נסגרת (רק פירעון, בלי תקבול מקזז באותו יום, לא הכנסה תפעולית). הלוואת גישור עדיין נסגרת מול תקבול באותו יום; כפל בנק↔ספרים חוסם פרסום.

שני מצבי תאריך ספק קיימים ב־`supplierTermsMode`. ברירת המחדל נשארת `eom_plus_30_days` (ספטמבר → 30.10) עד שהבעלים יאשר איזה מצב התכוון. `end_of_next_month` ממומש ונבדק (ספטמבר → 31.10 → ראשון 1.11) אבל אינו ברירת המחדל.

לשונית «תזרים חזוי» עדיין קוראת את `cash_forecast` (ודאות `certain` / `scheduled` / `estimate`). `cashflow_source` הוא המקור עם `layer` ו־`certainty` ∈ {מאושר, סביר, מסוכן, הערכה}.

## 18 הפערים

| # | פער | מצב | איפה |
|---|---|---|---|
| 1 | תחזית שבועית 13 שבועות עם יתרת פתיחה | מכוסה ב־#85, והפיגום הקנוני חוזר על אותם שבועות | `cash_forecast.week_windows`, `cashflow_truth.week_windows`. טסט: `tests/test_forecast_rules_and_liquidity.py`, `tests/test_cash_forecast_13w.py` |
| 2 | שלוש שכבות + `layer` + `certainty` | מכוסה באובייקט הקנוני. לשונית התזרים הישנה לא נושאת את השדות | `cashflow_truth.scaffold`. טסט: `test_an_empty_organization_gets_a_full_scaffold_of_unknowns` |
| 3 | בדיקת כפל בנק↔ספרים | מכוסה. מפתח `(supplier_id, doc_ref, gross)`, מועמד אינו אישור, תשלום חלקי מקטין הפרשה, אשראי לא נספר פעמיים, הפרשת שכבה 2 לא עוברת את יתרת הספקים. כשל חוסם פרסום | `detect_duplicates`. טסטים: `test_duplicate_check_blocks_…`, `test_a_card_charge_…`, `test_layer2_supplier_forecast_…`, `test_internal_transfer_…` |
| 4 | יתרת פתיחה חסרה נשארת «לא ידוע» | מכוסה ב־#85 (`opening` הוא `None`, לא 0). אין במקור החדש מספר של עסק | `cash_forecast._walk`, `liquidity_position`. טסט: `test_an_unknown_opening_does_not_become_zero` |
| 5 | עו״ש בלבד, מסגרת בנפרד, ראש פנוי נגזר | מכוסה ב־#85 ומחוזק במקור | `liquidity.build_liquidity` (יתרה מחשבונות checking), `liquidity_position`. טסט: `test_opening_balance_is_checking_only_and_the_facility_is_separate`, `test_opening_is_checking_only_and_the_facility_is_headroom` |
| 6 | ניכיון צ׳ק = הלוואה קצרה שנסגרת בפדיון | מכוסה ב־#85 (`forecast_rules.discounted_cheque_items`) ובמקור. הסכומים אינם בקוד — רק בראיית הבעלים | טסט: `test_each_discounted_cheque_is_a_short_loan_on_its_own_date`, `test_saturday_cash_moves_to_the_next_sunday_once` |
| 7 | תנאי ספק: שני מצבים מפורשים, שבת→ראשון בשניהם | מכוסה כהגדרה `supplierTermsMode`. ברירת המחדל `eom_plus_30_days` (ספטמבר → 30.10) עד אישור בעלים. `end_of_next_month` (ספטמבר → 1.11) קיים ונבדק ואינו ברירת המחדל | `supplier_due`. טסט: `test_supplier_terms_mode_defaults_to_eom_plus_30_and_both_modes_leave_saturday`, `test_default_supplier_mode_pays_september_on_30_october`, `test_end_of_next_month_moves_september_off_saturday_to_1_november` |
| 8 | שכר ב־10 מדרייבר (כמות × תעריף × תוספת מעסיק) | חלקי. יום ה־10 (ודריסת יום לארגון) מחובר לתחזית הקיימת. הדרייבר עצמו במקור; תוספת ריקה אינה 0. התחזית הישנה עדיין קוראת סכום חודשי מ־`plan.payroll` או משורות התקציב, לא את הדרייבר | `payroll_date`, `evaluate_driver`. טסט: `test_payroll_uses_the_org_day_…`, `test_drivers_stay_missing_…`, `test_payroll_comes_from_the_budget_definition_on_the_first` |
| 9 | דרייברי תקציב (כמות×מחיר, רכב, ימי אשראי) | מכוסה כמנוע. סיכום רק כשכל הרכיבים מספריים; שורה «לסיווג» חוסמת סיכום. #84 כבר שמר כמות×תעריף על `budgetLines` | `evaluate_drivers`. טסט: `test_drivers_stay_missing_…`. שורות #84: `tests/test_books_pnl_and_budget_lines.py` |
| 10 | חסר ≠ 0, והשלמה ידנית רק עם סכום+מקור+תאריך | מכוסה. אפס ידני רק עם `verified_by`. #85 כבר שמר `None` במקום 0 בתחזית | `accept_manual`, וכל שורת `missing`. טסט: `test_a_manual_completion_needs_amount_source_and_date`, `test_missing_inputs_stay_null_and_are_labelled` |
| 11 | פירוק כמות/מחיר, YTD מול YTD, סימן favorable | מכוסה כמנוע. מחיר = סכום/כמות, לא ממוצע פשוט. «נותר ליעד שנתי» נפרד מהחריגה. תקציב־מול־ביצוע הישן (`budget.py`) עדיין סכום בלבד, בלי כמות | `variance_line`, `variance_set`. טסט: `test_variance_splits_quantity_and_price_…` |
| 12 | צורך מימון = שפל מצטבר, ובנפרד סכום שבועות שליליים | מכוסה כשכל הסגירות ידועות. בלי יתרה — חסר, לא 0. תקבול מסוכן הוא שורה נפרדת (`scenario: full`) ולא נכנס לבסיס | `funding_need`. טסט: `test_funding_need_is_the_trough_…` |
| 13 | שורת «לא מסווג» + כיסוי (סכום הדליים = סך התנועות) | מכוסה. שורה בלי סכום, או תנועה שנכנסה פעמיים, חוסמות פרסום. בתצוגה, נפילה ל־`suppliers_direct` / `other_in` נספרת כלא־מסווגת ולא נבלעת בספקים | `coverage`, `view_model._bank_rows`. טסט: `test_coverage_keeps_an_unclassified_row_…` |
| 14 | הוצאות משותפות בלי הקצאה | מכוסה ב־#84 (`books_pnl`, מפתח רק כשהוגדר) ובמקור (השורה לא מחולקת; מפתח ב־`cashflowSettings` נדחה) | `books_pnl._allocate_shared`, `evaluate_driver` מסוג `shared_cost`. טסט: `test_shared_costs_stay_on_their_own_row`, טסטי #84 ב־`tests/test_books_pnl_and_budget_lines.py` |
| 15 | צ׳ק שמועדו עבר = «מועד שחלף ומצב לא ידוע», לא «פתוח» | מכוסה. `state` הישן (`cleared` / `future` / `no_coverage` / `not_found`) נשאר; נוסף `verification` | `cheque_verification`, `liquidity.match_checks`. טסט: `test_a_past_cheque_is_not_open`. המצבים הישנים: `test_liquidity_reads_accounts_daily_balances_checks_and_debt_service` |
| 16 | נזילות יומית: סף 90%, ראש פנוי 2,000, גיל יתרה 2 ימים | חלקי. החישוב וההתרעות במקור, על היתרה השמורה. שער 20 השעות של Open Finance כבר קיים ב־cron ולא שונה כאן. אין רענון ספק חדש | `liquidity_position`. טסט: `test_opening_is_checking_only_…` (כולל «יתרה ישנה» ו«קרוב למסגרת») |
| 17 | כרטיס אשראי מחוץ לעו״ש, כולל יתרת ביניים | מכוסה ב־#80 / נזילות #85 (`present_cards`, `available_limit`). הפיגום מחזיק שורת כרטיסים נפרדת, לא מקוזזת מהעו״ש | `liquidity.present_cards`. טסט: `test_card_available_uses_the_stored_figure_…` |
| 18 | תקרת הפסד ומקור מימון, אופציונליים לכל עסק | מכוסה כשדות. ברירת המחדל `null` (לא הוגדר), לא 0. דוח השוואה בסגירת חודש לא נבנה | `CashflowSettings.loss_cap`, `funding_source`. טסט: `test_defaults_are_the_owner_rules_…` |

ארגון חדש בלי נתונים: `scaffold` וגם `build_view` מחזירים 13 שבועות של ראשון–שישי, כל שורת הפיגום `missing` ובלי סכום, ויתרת פתיחה לא ידועה. טסט: `test_an_empty_organization_gets_a_full_scaffold_of_unknowns`, `test_the_live_view_of_a_new_org_carries_that_scaffold`.

## קשיחות שנשארו בקוד (לא במקור התזרים החדש)

אלה לא נכנסים לחישוב של ארגון ריק. הם עדיין שמות או מספרים של עסק אחד, במסלול התיוק והתקציב הישן:

| מקום | מה קשיח |
|---|---|
| `filing.py` | `CHEF_ORG, CHEF_ACCOUNT, FOOD_GROUP_ORG = 2, 35, 6`. קיצור בין־חברתי רץ רק על הזוג הזה |
| `filing.py` | כינויי «פוד גרופ» / «אליאב כהן» (סדר מילים לא משנה), ותווית «העברות בין השף לפוד גרופ» |
| `filing.py` | ביטוי `food_group` להתאמת צד נגדי |
| `budget_fill.py` | `DECLARED_PAYROLL_MONTHLY = 49700` — סכום שורות השכר שכבר מולאו בזרע של #84, להשוואת «האם הסכום המוצהר מתמלא». לא נכנס לתחזית |
| `plan_budget.py` | `external_id` מהצורה `eliav:group:{category}` כשמוצאים קטגוריה קיימת |
| `books_pnl.py` | כינוי חלוקה `food_group` → `shared` (מילת סיווג, לא סכום) |
| הערות ב־`cash_forecast.py`, `cash_statement.py`, `service.py`, `source_journal.py` | אזכור פוד גרופ / אליאב בהסבר, בלי מספר |

61,000 ו־41,000 אינם בקוד הייצור. הם מופיעים בטסטים כראיית בעלים שמוזנת לתוכנית.

## מה עדיין פתוח

- לשונית התזרים והתחזית החודשית לא עברו לקרוא מ־`cashflow_source`, ולכן עלולות להופיע זו לצד זו שתי ודאויות.
- דרייבר השכר לא מחליף עדיין את `plan.payroll` בתוך 13 השבועות.
- פירוק הכמות/המחיר לא מחובר לטבלת תקציב־מול־ביצוע הקיימת, כי לביצוע אין כמות.
- מסמכי ספקים מהספרים לא נטענים אוטומטית לבדיקת הכפל (אין טבלה חדשה). בלי מסמכים הבדיקה היא `missing`, לא «אין כפל».
- דוח השוואת תקציב בסגירת חודש (פער 18) לא נכתב.
- הקצאת הוצאות משותפות ממתינה למפתח מהבעלים. עד אז אין חלוקה.
