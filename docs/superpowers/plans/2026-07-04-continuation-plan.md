# תכנית המשך — רצף (Rezef), אחרי איטרציה 13 של לולאת השיפור המתמדת

> **לסוכן המבצע:** זהו מסמך תכנית (לא handoff באמצע ביצוע). כל הממצאים כאן נבדקו ישירות מול הקוד הנוכחי (HEAD `4f50d47`, 2026-07-04) — לא הועתקו מהתדרוך בלי אימות. קרא את `docs/superpowers/plans/2026-07-04-continuation-briefing.md` לרקע המלא, ואת `.superpowers/sdd/progress.md` לפני שאתה מתחיל (אל תשכפל עבודה). עבוד מ-`/Users/mymac/coding/cfo`, branch `feat/sumit-ar-ap-documents-ocr`. תיעוד ותקשורת בעברית. TDD מלא לכל פריט: טסט אדום → מימוש → ירוק → `qa_gate.py` → deploy → אימות חי → עדכון ledger.

> ## ⚡ עדכון ביצוע (2026-07-04, אחרי כתיבת התכנית) — **כל 5 הפריטים הושלמו**
>
> תכנית זו בוצעה **במלואה** — ר' סעיף 7 למטה לדוח-ביצוע מלא (מה הצליח, קומיטים, אימות חי), סעיף 8 להרחבות שבוצעו מעבר לתכנית המקורית, וסעיף 9 למידע מרוכז לסוכן הממונה (מה עוד פתוח, מה נדרש ממנו/מהמשתמש). Suite כרגע: **606 עוברים** (עלה מ-566). `ANTHROPIC_API_KEY` **עדיין לא נוסף** ב-Vercel (נבדק שוב הרגע). כל השאר בסעיף 0 למטה — היסטורי, לא לשכפל.

## 0. מצב מאומת ברגע כתיבת תכנית זו

- Suite: **566 עוברים** (הרצתי מחדש עכשיו — `python -m pytest tests/ -q --tb=short -p no:warnings` — תואם בדיוק את מה שהתדרוך טען).
- `vercel env ls production | grep -i anthropic` — **ריק** (הרצתי מחדש עכשיו). `ANTHROPIC_API_KEY` עדיין לא נוסף.
- `git status --short` — נקי.
- כל 8 השאלות הפתוחות בתדרוך נבדקו ברמת קוד (ר' פירוט תחת כל פריט/בסעיף 4). **שני ממצאים חדשים, שלא היו בתדרוך, עלו תוך כדי המחקר** ומשנים את סדר העדיפויות:
  1. **הבעיה שסעיף 3.7 של התדרוך הזהיר ממנה לגבי הצ'אטבוט — כבר קורית היום, לא רק תיאורטית, דרך ה-UI החי.** `DocumentManager.tsx` (שכבר אומת חי בפרוד ב"BROWSER VERIFICATION" באיטרציה הקודמת) שולח `customer_id: customerName` — שם חופשי שהמשתמש הקליד — ישירות ל-SUMIT, בלי לבדוק אם קיים `Contact` תואם. `document_issuance_service.create_document` (שורה 142) מעביר את זה כמו שהוא ל-`DocumentRequest.customer_id`, ולעולם לא שומר בחזרה את ה-`customer_id` שה-SUMIT-response מחזיר (`DocumentResponse.customer_id` קיים במודל, `sumit_models.py:105`, אך לא נקרא בפועל). אין אף endpoint אחד בכל הריפו שמחפש/מציג `Contact` קיים (`grep` מלא — אפס תוצאות). זה שורש-הבעיה הסביר להיווצרות שריד-הלקוח "2095660683" שכבר תועד — וזה קורה **בכל הפקת מסמך אמיתית היום דרך ה-UI**, לא רק בתרחיש-צ'אטבוט עתידי. זו עדיפות א' (נכונות נתונים) אמיתית, לא ד'.
  2. **`Expense.deduction_percent` הוא "פיצ'ר מת" מקצה-לקצה.** השדה קיים (`models.py:738`), `annual_report_service.py` (שורות 65–113) כבר מכבד אותו בחישוב 1301 — אבל `ExpenseUpdateRequest` (`api/routes/expenses.py`) **לא כולל את השדה בכלל**, ו-`ExpenseFilingService.update_expense` (`expense_filing_service.py:62-87`) לא מאפשר אותו גם ברמת השירות. כלומר: מאז שהשדה נוסף (7.7), **אף משתמש אמיתי לא יכול היה להגדיר אותו** — לא ב-API, לא ב-UI. שלושת מחשבוני-הניכוי הקיימים (`calculators.py:392-433`) עומדים מנותקים לגמרי מכל רשומת הוצאה.

## 1. כללים מחייבים (ללא שינוי מהתכניות הקודמות)

1. TDD לכל שינוי: `python -m pytest tests/ -q --tb=short -p no:warnings` ירוק לפני כל commit.
2. פרוד: סכמה additive בלבד; אין מיגרציות חדשות נדרשות לאף אחד מ-5 הפריטים למטה (כל הטבלאות/עמודות כבר קיימות).
3. סודות רק ב-scratchpad/.env.local. לעולם לא בקומיט.
4. SUMIT חי: backoff על 403; לעולם לא להשאיר מסמך אמיתי לא-מבוטל; להימנע מיצירת שרידי-בדיקה חדשים (המוסכמה שכבר נקבעה בשלב 8: אימות דרך mock + payload-inspection איפה שאפשר, לא כתיבה חיה נוספת).
5. אחרי כל 1–2 פריטים: `python scripts/qa_gate.py` מלא, ואז deploy+migrate+smoke+drift.
6. עדכן `.superpowers/sdd/progress.md` אחרי כל פריט.

---

## 2. פריטים לביצוע (בסדר עדיפות לפי הנחיית-המטרה: נכונות-נתונים › יכולת-חוסמת › חוויית-משתמש › צ'אטבוט › ליטוש)

### פריט 1 (עדיפות א — נכונות נתונים, חי בפרוד היום) — פתרון resolve-or-create ל-customer_id, מניעת לקוחות-רפאים כפולים ב-SUMIT

**✅ בוצע — commit `bb8d190` (+`123d6e3` ledger).** 10 טסטים חדשים (576→586 בשלב זה). נפרס, אומת חי: `GET /api/contacts?query=Unknown` מול org 1 החזיר Contact-ים אמיתיים (id 6/7, external_id אמיתיים). **ממצא-צד לא-מתוכנן**: אלה שני Contact-ים אמיתיים ששמם המסונכרן הוא פשוט "Unknown" — בעיית איכות-נתונים בצנרת הסנכרון (contact_external_id לא תמיד נפתר), תועד ב-progress.md, לא תוקן (מחוץ לתחום הפריט הזה).

**רקע/ממצא** (מפורט בסעיף 0 לעיל): אין שום מנגנון חיפוש/שיוך לקוח קיים בכל הריפו לפני שליחת מסמך ל-SUMIT.

**קבצים:** חדש: `src/cfo/services/contact_service.py`, `src/cfo/api/routes/contacts.py`. שינוי: `src/cfo/services/document_issuance_service.py` (`create_document`), `frontend/src/components/DocumentManager.tsx`, `src/cfo/api/__init__.py` (רישום router).

**TDD:**
1. `tests/test_contact_service.py` (חדש) — אדום:
   - `test_search_contacts_matches_partial_name_case_insensitive`
   - `test_search_contacts_is_org_scoped`
   - `test_resolve_or_create_contact_reuses_existing_by_exact_name_match`
   - `test_resolve_or_create_contact_creates_new_when_no_match`
   מימוש: `search_contacts(db, org_id, query, contact_type=None, limit=20)`, `resolve_or_create_contact(db, org_id, *, name, email=None, phone=None, contact_type=ContactType.CUSTOMER)`.
2. `tests/test_contacts_routes.py` (חדש) — אדום: `GET /api/contacts?query=...` מחזיר התאמות; בידוד org (שאילתה על ארגון אחר → ריק, לא 200 עם דלף); 401 ללא אימות. מימוש: route + רישום ב-`api/__init__.py`.
3. הרחבת `tests/test_document_issuance.py` — אדום:
   - `test_create_document_reuses_existing_contact_by_name` — זרע `Contact` עם `external_id="sumit-123"`, קרא ל-`create_document` עם `customer_name` תואם, ודא ש-`invoice.contact_id` מצביע לרשומה הקיימת וש-`DocumentRequest.customer_id` שנשלח בפועל (נלכד ב-fake transport הקיים) הוא `"sumit-123"`, **לא** השם החופשי.
   - `test_create_document_persists_sumit_customer_id_onto_new_contact` — mock תגובת SUMIT עם `customer_id` חדש; ודא שנוצר `Contact` חדש עם `external_id` = הערך שחזר; קריאה שנייה עם אותו `customer_name` — ודא ש**היא** משתמשת ב-`external_id` השמור, לא יוצרת `Contact` שלישי.
   מימוש: לפני בניית ה-request, לקרוא ל-`resolve_or_create_contact`; להשתמש ב-`contact.external_id or contact.name`; אחרי תגובה מוצלחת בלי `external_id` קודם — לשמור את `response.customer_id` על ה-`Contact` ולעשות commit; להצמיד `invoice.contact_id` תמיד (גם כש-`send_to_sumit=False`).
4. Frontend: `DocumentManager.tsx` — שדה הלקוח הופך ל-autocomplete מול `GET /api/contacts` (typeahead), עם נפילה חופשית ללקוח חדש. `tsc --noEmit` + `npm run build` נקיים; בדיקה ידנית מקומית (לקוח חוזר → אותו contact_id בפעם השנייה).
5. Suite מלא, `qa_gate.py`, deploy, ואז אימות חי זהיר: יצירת מסמך טיוטה ל-org 1 עם שם לקוח שכבר קיים לו `Contact.external_id` שמור, ווידוא (מהתשובה/מהלוג, בלי ליצור שרידים חדשים מיותרים) שה-payload השתמש ב-`external_id` הקיים.

זהו הפריט בעל המינוף הגבוה ביותר שנמצא הסבב הזה: הוא תיקון-אמת חי (לא היפותטי), הוא תשתית לפריט 4 ולפריט 5 למטה (`search_contacts`), והוא סוגר ישירות את האזהרה בסעיף 3.7 של התדרוך (ברגע שהצ'אטבוט יקבל גישה ל-`issue_document`/`create_payment_link`, הוא יעבור דרך אותו שירות מתוקן).

### פריט 2 (עדיפות ב — יכולת חסרה, "פיצ'ר מת" מקצה-לקצה) — נתיב כתיבה ל-`deduction_percent`

**✅ בוצע — commit `30df417`.** 3 טסטים חדשים (576→579). **הוחלט במודע לא לבנות** את `apply_deduction_calculator`/route ה-calculator (סעיף 2 בתת-הרשימה למטה) — `calculators.py` מחזיר row-list ל-UI ישיר, לא אחוז נקי; מיפוי calculator_id→kwargs נשפט כמעבר-לתחום התיקון הזה. נפרס, 16/16 smoke.

**קבצים:** `src/cfo/api/routes/expenses.py`, `src/cfo/services/expense_filing_service.py`.

**TDD:**
1. הרחבת `tests/test_expense_filing.py` — אדום:
   - `test_update_expense_sets_deduction_percent`
   - `test_update_expense_rejects_out_of_range_deduction_percent` (מחוץ ל-0–100)
   - `test_update_expense_deduction_percent_omitted_stays_null` (רגרסיה — התנהגות קיימת נשארת זהה-ביט כשלא מסופק)
   מימוש: הוספת `deduction_percent: Optional[float]` ל-`ExpenseUpdateRequest`; הוספה לרשימת השדות המותרים ב-`ExpenseFilingService.update_expense` עם guard טווח (שגיאת ValueError → 400, כמו שאר הוולידציות באותו route).
2. `tests/test_expense_filing.py` — אדום: `test_apply_deduction_calculator_sets_percent_from_vehicle_calculator` — קורא ל-`ExpenseFilingService.apply_deduction_calculator(expense_id, calculator_id, inputs)` שמריץ `calculators.run()` הקיים (שימוש חוזר, לא שכפול מתמטיקה) ושומר את האחוז שחזר. Route חדש: `POST /api/expenses/{id}/deduction`.
3. Frontend (אופציונלי לסבב זה, לפי התקדים של 7.3/7.9 — backend עצמאי ובר-פריסה גם בלי): כפתור "חשב ניכוי" בתצוגת הוצאה בודדת.
4. Suite מלא, `qa_gate.py`, deploy; אימות חי חיובי בלבד (אין הוצאה חד-פעמית זמינה לבדיקה הרסנית — לתעד זאת ולא לדלג בשקט).

### פריט 3 (עדיפות ב — סיכון תפעולי אמיתי, מאמץ נמוך) — ולידציית קוד-בנק/מספר-זיהוי אמיתיים במס"ב

**✅ בוצע — commits `d0f6e05` + `a70c50f` (תיקון-באג בהמשך).** `is_valid_bank_code()` נבנה מול רשימת 43 קודים שנשלפה טרייה מ-masav.co.il (לא הומצאה). `is_valid_israeli_id()` אומת מול דוגמה חיצונית מאומתת. **advisor תפס באג אמיתי** אחרי שדיווחתי "הכול נסגר": הפונקציה דחתה ת.ז תקינה שאיבדה 0 מוביל (נפוץ אחרי ייבוא Excel) — תוקן ב-`zfill(9)`, טסט-רגרסיה נוסף. **שני סיכוני-החלטה אמיתיים לא נפתרו וסומנו בכנות** ב-`docs/superpowers/plans/2026-07-04-continuation-plan-open-items.md` (ר' סעיף 9 למטה) — אל תניח שזה "סגור לגמרי".

**רקע/ממצא:** `_gather()` ב-`src/cfo/api/routes/masav.py` (שורות 59–105) בודק רק שהשדות **לא ריקים** (`_digits`), לא שקוד-הבנק תקף מול רשימת בנק ישראל האמיתית ולא שהת.ז./ח.פ. עומד בביקורת-הספרה. ספק עם קוד-בנק שגוי מקודד היום לקובץ מס"ב "תקין למראה" שהבנק ידחה בפועל.

**קבצים:** `src/cfo/services/masav_service.py`, `src/cfo/api/routes/masav.py`.

**TDD:**
1. הרחבת `tests/test_masav.py` — אדום: `test_is_valid_bank_code_accepts_known_codes`, `test_is_valid_bank_code_rejects_unknown_code`, `test_is_valid_israeli_id_checkdigit_accepts_valid`, `test_is_valid_israeli_id_checkdigit_rejects_invalid`. מימוש ב-`masav_service.py`: קבוע `BANK_OF_ISRAEL_CODES` (רשימה מתועדת-מקור), `is_valid_bank_code()`, `is_valid_israeli_id()` (אלגוריתם ביקורת-ספרה סטנדרטי — נוסחה ציבורית ומכנית, **לא** שאלת-פרשנות משפטית כמו סעיף 3.6, מותר לממש).
2. הרחבת `tests/test_financial_real_data.py` (שם כבר קיימים טסטי-route למס"ב) — אדום: `test_masav_gather_skips_vendor_with_invalid_bank_code`, `test_masav_gather_skips_vendor_with_bad_id_checkdigit`. מימוש: הוספת שני הבדיקות לרשימת ה-`missing`/skip הקיימת ב-`_gather()`.
3. Suite מלא, `qa_gate.py`, deploy; אימות חי: `GET /api/masav/preview` מול חשבונות-ספק פתוחים אמיתיים ב-org 1 — לוודא שאין רגרסיה (כל ספק שהיה תקין נשאר תקין).

### פריט 4 (עדיפות ב/ג — יכולת חסרה + מאפשר-צ'אטבוט) — כרטסת לקוח/ספק (`contact_card`)

**✅ בוצע — commit `776c63c`.** 7 טסטים חדשים (585→591). אומת חי מול contact_id אמיתי (org 1, id 6) — יתרה רצה נכונה. **פער-סיכון לא-פתור** (זוהה ע"י advisor, לא על ידי): `contact_card` מצרף Payment לפי `Payment.contact_id`, שה-sync ממלא **רק** כש-`contact_external_id` נפתר — תשלום לא-משוייך "נעלם" מהכרטסת, עלול לנפח יתרת-חוב. תועד ב-open-items file (סעיף 9).

**רקע/ממצא:** יעד-הסיום המדיד #4 בהנחיית-המטרה מזכיר "כרטסת" במפורש כתרחיש-משתמש נדרש לצ'אטבוט. `ledger_service.py` כבר מכיל פונקציה אנלוגית לפי קוד-חשבון (`general_ledger(account_code)`, שורה 462) — אבל אין שום דבר per-contact בכל עץ ה-services (grep מלא, אפס תוצאות ל-"customer_card"/"contact_card"/"statement").

**קבצים:** `src/cfo/services/ledger_service.py`, `src/cfo/api/routes/ledger.py`.

**TDD:**
1. הרחבת `tests/test_ledger_service.py` (הקובץ הקיים כבר מערבב טסטי-שירות וטסטי-route — לפי המוסכמה שכבר נהוגה בפרויקט) — אדום: `test_contact_card_lists_invoices_bills_payments_chronologically_with_running_balance`, `test_contact_card_is_org_scoped`, `test_contact_card_empty_for_contact_with_no_activity`. מימוש: `ledger_service.contact_card(db, organization_id, contact_id)` — אוסף `Invoice` (`contact_id`), `Bill` (`vendor_id`), `Payment` (`contact_id`), ממוין כרונולוגית, יתרה רצה (מוסכמת-סימן זהה ל-`general_ledger` הקיים).
2. אותו קובץ — אדום: `test_contact_card_route_org_scoped` — `GET /api/ledger/contact/{contact_id}/card`: 200 עם נתוני הארגון הנכון; 404 (לא 200 עם דליפה) על contact שאינו שייך לארגון המבקש.
3. Suite מלא, `qa_gate.py`, deploy; אימות חי מול contact_id אמיתי ב-org 1.

### פריט 5 (עדיפות ד — צ'אטבוט; אימות חי תלוי בסעיף 3.1) — השלמת שכבת הכלים ל-9.1 המקורי

**✅ בוצע — commit `8bdd064`.** כל 7 הכלים (לא 6 — כלל גם `search_contacts` בנוסף למה שתוכנן) נוספו: 6 קריאה + `create_payment_link` ככלי-כתיבה עם שער-אישור מלא (נבדק turn 2 גם כן, לא רק turn 1). 9 טסטים חדשים (591→600). **אימות חי של הלולאה עצמה עדיין חסום** — `ANTHROPIC_API_KEY` עדיין ריק (נבדק שוב הרגע). מה שכן אומת חי בלי המפתח: כל שירותי-הבסיס עצמם (get_engine_status/get_vat_position/get_ledger_card/search_contacts) דרך ה-routes הרגילים שלהם.

**רקע/ממצא:** `ai_chat_tools.py` בפועל מכיל **6** כלים (`get_ar_aging`, `get_ap_bills`, `get_pnl`, `get_collection_cases`, `issue_document`, `log_collection_attempt`) לעומת ~12 בתכנון המקורי (9.1). כל השירותים הדרושים לכלים החסרים כבר קיימים (חלקם נבנו זה עתה בפריטים 1/4):
- `search_contacts` ← `contact_service.search_contacts` (פריט 1)
- `get_ledger_card` ← `ledger_service.contact_card` (פריט 4)
- `get_vat_position` ← `financial_synthesis.compute_vat_position` (כבר קיים, `financial_synthesis.py:219`)
- `get_cashflow` ← `dashboard_service.get_cashflow_projection` (כבר קיים, שורה 435)
- `list_invoices` ← `document_issuance_service.list_documents` (כבר קיים, שורה 45)
- `get_engine_status` ← `engine_service.status` (כבר קיים, שורה 25)
- `create_payment_link` ← `document_issuance_service.create_payment_link` (**כבר נבנה ונפרס באיטרציה 7 — היום לא חשוף לצ'אטבוט בכלל**)

**קבצים:** `src/cfo/services/ai_chat_tools.py`, `src/cfo/services/ai_chat_service.py`.

**TDD:**
1. הרחבת `tests/test_ai_chat_tools.py` — אדום: טסט בידוד-org אחד לכל כלי חדש (6 כלים: 5 קריאה + `create_payment_link`); `category="write"` עבור `create_payment_link`.
2. מימוש: פונקציות-עטיפה דקות + רשומות `ChatTool` חדשות ב-`ai_chat_tools.py`, בדיוק לפי התבנית הקיימת (`org_id` מוזרק, לעולם לא פרמטר-מודל).
3. הרחבת `tests/test_ai_chat_service.py` — אדום: הרחבת טסט שער-האישור הקיים כך שיכלול גם `create_payment_link` — לוודא שהשער עומד גם כאן (כיבוי מלאכותי → כישלון, בדיוק כמו מתודולוגיית 9.3 המקורית — בדיקת turn 2, לא רק turn 1).
4. Suite מלא, `qa_gate.py`, deploy. **אימות חי של הלולאה עצמה נשאר חסום על `ANTHROPIC_API_KEY` (ר' סעיף 3, "ממתין למשתמש") — לשלוח עם mock בלבד, בדיוק כפי ש-9.1–9.4 נשלחו, ולא לטעון "אומת חי" לפני שה-runbook שם רץ בפועל.**

---

## 3. ממתין למשתמש (לא לנחש, לא להחליט לבד)

### 3.1 — ANTHROPIC_API_KEY
עדיין חסר (אומת שוב הרגע: `vercel env ls production | grep -i anthropic` → ריק). **Runbook מוכן לרגע שיתווסף** (לא TDD — רצף פעולות בלבד):
1. `vercel --prod --yes` (redeploy — משתני-סביבה לא נכנסים לתוקף בלי דיפלוי חדש).
2. בדיקה חיה #1: הודעת מידע-בלבד ("מה מצב גיול החובות?") — מאמתת לראשונה אי-פעם את מנגנון ה-tool-use מול תשובת Claude אמיתית.
3. בדיקה חיה #2: פעולת-כתיבה עם אישור (למשל `log_collection_attempt` על case אמיתי, או `issue_document`/`create_payment_link` בדפוס הצעת-מחיר+ביטול המקובל בפרויקט לבדיקות SUMIT חיות).
4. **לשים לב במפורש**: אם פריט 1 לעיל כבר נחת עד אז — לוודא בבדיקה החיה שהמודל אכן עובר דרך `search_contacts`/`resolve_or_create_contact` ולא ממציא `customer_id` חופשי (schema הכלי עדיין חושף שדה `customer_id` חופשי לצורך תאימות-לאחור — זו נקודת-הבדיקה הקריטית).
5. עדכון `PRODUCTION_READINESS.md` + `SUMIT_MODULE_COVERAGE.md` + ledger, ודיווח למשתמש. זה סוגר את גל 2 רשמית.

### 3.2 — Account/Transaction: repair / retire / להשאיר
ללא שינוי מאז איטרציה 13 (נבדק שוב ב-grep הסבב הזה — אותם 8 שירותים תלויים בפועל: `ai_analytics_service`, `ai_intelligence_agent`, `balance_snapshot` [+`kpi_service` גם בעקיפין וגם ישירות], `budget_service`, `cost_analysis_service`, `fees_service`, `forecasting_service`, `tax_service` דרך `FinancialReportsService`). שום מידע חדש ברמת-קוד משנה את שיקול-הדעת כאן — זו החלטת ארכיטקטורה/מוצר טהורה. **ממתין לבחירת המשתמש בין תיקון/הצנעה/השארה כפי שמפורט בתדרוך**, לפני שניתן לגעת באחד מ-8 השירותים הללו.

### 3.3 — ניקוי שרידי SUMIT
שני פריטים שונים, טיפול שונה:
- **מסמך 1001** (הצעת מחיר, ₪1): אושר סופית — אין נתיב ביטול/מחיקה בכל 84 הנתיבים של ה-spec לסוג-מסמך זה. ידני-בלבד ב-`app.sumit.co.il`.
- **לקוח "2095660683"**: חד יותר ממה שהתדרוך תיאר — קיים כבר route פעיל ופרוס `DELETE /api/crm/entities/{id}` (`src/cfo/api/routes/crm.py:78`, מחובר ל-`sumit_integration.delete_entity`, `sumit_integration.py:1563`), שמעולם לא הופעל על הרשומה הספציפית הזו. זו קריאה בודדת, מוכנה, שסוכן **יכול** לבצע טכנית — אך היא הרסנית ובלתי-הפיכה על מערכת צד-שלישי חיה, ולכן עדיין דורשת אישור מפורש וחד-פעמי מהמשתמש (כלל-עצירה א'), לא "המשך" גורף. מסומן בנפרד ממסמך 1001 בכוונה — זה קל-יישום יותר ברגע שיינתן אישור.

### 3.4 — מבנה אחיד (8 סוגי-רשומה, spec אמיתי בידיים)
שום מחקר חדש לא משנה את ההערכה — עדיין פרויקט-יישום נפרד וגדול הראוי לתכנון TDD ייעודי משלו. **שאלה למשתמש כפי שהתדרוך מנסח**: האם זה בעדיפות לסבב הבא? לא נכלל בתכנית הזו בכל מקרה (גדול מדי לסבב משותף עם פריטים אחרים) — אך התשובה קובעת אם סבב-התכנון הבא ייפתח בו.

### 3.5 — PCN874 (spec byte-level)
עדיין לא אותר במקור קריא-מכונה אחרי שתי איטרציות מחקר (9 ו-10) שמיצו את כל הכלים הזמינים לסביבה הזו (WebFetch, WebSearch, רינדור PDF דרך poppler, מעקב-ציטוטים). הצעד הבא דורש פנייה ישירה לרשות המסים או מקור מסחרי/ספק מורשה — מחוץ ליכולת סוכן לפתור. **אין לממש פורמט מנוחש.**

### 3.6 — ריבית חוק מוסר תשלומים
עדיין רק פער מתועד (Prime+2% טענה מקורית מול Prime+6.5% שנמצא), לא נפתר — שאלת-פרשנות-טקסט-חוק אמיתית שמחוץ לסמכות-סוכן בטוחה (שיעור-ריבית שגוי הוא טעות משפטית/כספית ממשית שנגבית מלקוח אמיתי). **דורש אימות מהמשתמש או מעו"ד/רו"ח מול נוסח החוק המלא**, לא חיפוש-רשת נוסף.

### 3.7 — קישור תשלום, השלמת אימות חי
הצד הקוד-י של הסיכון שהסעיף הזה מזהיר ממנו מטופל ישירות ע"י פריט 1 לעיל ברגע שיינחת. מה שנשאר תלוי במשתמש בפועל: חשבון SUMIT עם מודול Upay/סליקת-אשראי מופעל בפועל, כדי לראות תגובת-הצלחה אמיתית (לא רק דחייה עסקית נכונה). **אין לסוכן גישה לחשבון כזה** — דורש או השלמת onboarding של Upay בחשבון הקיים, או ארגון-בדיקה אחר עם המודול כבר מופעל.

### הערה על 3.8 (פערים קטנים שנבדקו ולא נבחרו לסבב הזה)
- שני endpoints כפולים ל-AR aging (`/api/ar/aging` ב-`cfo_dashboard.py`, `/api/financial/ar/aging` ב-`financial_management.py`) — אומת שוב, עדיין קיים, P2 טהור (איחוד עתידי, לא דחוף).
- `form_102`/`form_126` ל-XML רשמי — עדיין gap גדול יותר מאשר מה שנבחר לסבב הזה.
- ולידציית Masav ואת פערי-הניכוי בהוצאות — **אלה כן נבחרו** (פריטים 2+3 לעיל).
- מסך Open Finance — כבר תוקן (איטרציה 8, אומת קיים בקוד).

---

## 4. הגדרת סיום לסבב הזה

- [x] פריט 1 (contact resolution, מניעת לקוחות-רפאים) — TDD מלא, deploy, אימות חי — `bb8d190`
- [x] פריט 2 (`deduction_percent` write path) — TDD מלא, deploy — `30df417`
- [x] פריט 3 (ולידציית מס"ב) — TDD מלא, deploy, אימות חי — `d0f6e05`+`a70c50f`
- [x] פריט 4 (כרטסת לקוח/ספק) — TDD מלא, deploy, אימות חי — `776c63c`
- [x] פריט 5 (השלמת כלי צ'אטבוט, mocked) — TDD מלא, deploy — `8bdd064`; אימות חי עדיין חסום (3.1)
- [x] `qa_gate.py` ירוק אחרי כל פריט; `prod_smoke.py` 16/16; `schema_drift_check` OK בכל דיפלוי — כל פעם, לא רק בסוף
- [x] `.superpowers/sdd/progress.md` מעודכן אחרי כל פריט (כולל תיקון-כנות אחרי advisor)
- [ ] `PRODUCT_AUDIT_AND_ROADMAP.md` — **לא עודכן** בסבב הזה (פריטים 1+2 לא סומנו ✅ בגריד עצמו — פער-תיעוד קטן שנשאר)
- [x] דיווח סיכום קצר בעברית למשתמש — בוצע כמה פעמים תוך כדי (סוף כל איטרציה)

**כל 8 תיבות-הסימון שרלוונטיות ל-TDD/deploy סומנו. שתי תיבות פתוחות**: עדכון `PRODUCT_AUDIT_AND_ROADMAP.md` עצמו (לא קריטי — progress.md מתעד הכול), וכמובן כל סעיף 3 (ממתין למשתמש) — ר' סעיף 9 למטה לתמונה מעודכנת.

---

## 7. דוח ביצוע מלא (התווסף 2026-07-04, אחרי סיום כל 5 הפריטים)

**סטטיסטיקה**: Suite עלה מ-566 (בכתיבת התכנית) ל-**606** טסטים (+40, כולל שלוש הרחבות מעבר לתכנית — ר' סעיף 8). כל commit עבר qa_gate מלא + דיפלוי + smoke 16/16 + אימות חי נפרד (כולל דפדפן, לא רק curl, לשינויי UI).

**סדר קומיטים (features, לא docs)**: `bb8d190` → `30df417` → `d0f6e05` → `776c63c` → `8bdd064` → `a70c50f` (תיקון) → `31d0ee6` (הרחבה) → `23c8552` (הרחבה) → `6be2647` (הרחבה).

**מה שהתגלה בדרך ולא היה בתכנית המקורית**:
- פריט 1: ממצא-צד "Unknown" contacts בנתוני sync — לא תוקן, מחוץ לתחום.
- פריט 3: מעבר קוד-בנק בנק-ישראל מ-2 ל-3 ספרות (ל-2027, לא רלוונטי היום) — נחקר עם fork ייעודי, לא ניחוש.
- פריט 3 (אחרי advisor): באג zfill אמיתי בת.ז — תוקן. שני סיכוני-החלטה (bank-code snapshot, contact_card null-payment) — לא תוקנו, סומנו בכנות.
- **לקח מתודולוגי חשוב**: קראתי ל-advisor אחרי שכבר דיווחתי "5/5 הושלמו, אין דבר לדחות" — הוא תפס באג אמיתי ופער-ניסוח. **מסקנה לסוכן הבא: תזמן advisor *לפני* דיווח-סיום, לא רק *אחרי*.**

## 8. הרחבות מעבר לתכנית המקורית (לולאת שיפור, ללא הנחיה נוספת מהמשתמש — יזומות מתוך גריפ יזום)

לאחר שסגרתי את 5 הפריטים, המשכתי בלולאת השיפור המתמדת (הנחיית-המטרה `2026-07-03-rezef-goal-directive.md`) ומצאתי + תיקנתי 3 פערים נוספים, לא מתוכננים:

1. **הפעלת ארנק Upay** (`31d0ee6`) — `SUMIT_MODULE_COVERAGE.md` תיעד שתי מתודות SUMIT קיימות בקוד (`setup_upay_credentials`, `open_upay_terminal`) ללא route נגיש כלל, ועם route-בודד שהיה קיים (`open_upay_terminal`) שקרס תמיד ב-500 (SUMIT-endpoint שם מבצע onboarding-מוסד-סליקה-חדש, לא "פתיחת תשלום" כפי שהשם רמז). נוספו `POST /api/payments/upay/setup` + `GET /upay/status`, תוקן ה-500→400. 5 טסטים.
2. **תיקון `/settings` — עמוד מוקאפ מלא** (`23c8552`) — נמצא בזמן חיפוש-עבודה שיטתי, לא בגריפ פערים-מומצאים הרגיל: כל העמוד היה סטטי לגמרי (0 קריאות API, "Save" בלי onClick, "Connected"/"2 min ago" קבועים תמיד). נבנה מחדש עם נתונים אמיתיים; אומת בדפדפן פעמיים (dev מקומי + פרוד חי, מחובר כמשתמש אמיתי) — לא רק curl.
3. **סריקה שיטתית + UI ל-Upay** (`6be2647`) — לפי בקשת המשתמש, נסרקו כל 40 קומפוננטות ה-frontend המנותבות לאותו דפוס בדיוק (regex תוקן פעמיים עד שהיה מדויק) — לא נמצא מקרה שני. נוסף כרטיס Upay אמיתי ל-`/sync`, אומת בדפדפן (הזרקת שורת-DB מקומית-בלבד לבדיקת הענף המותנה, לא credential אמיתי).

## 9. מידע מרוכז לסוכן הממונה — מה עדיין פתוח ומה נדרש כדי להמשיך

**מצב כללי**: תכנית זו סגורה. הצ'אטבוט (יעד-סיום #4), P0 החשבונאות הכפולה (יעד #1), ו-Open Finance (יעד #7) הם שלושת החסמים הגדולים שנותרו מתוך 7 יעדי-הסיום בהנחיית-המטרה — כולם דורשים קלט מהמשתמש, לא רק עוד קוד.

### מה שרק המשתמש יכול לפתור (לא לנחש, לא להחליט לבד)
1. **`ANTHROPIC_API_KEY`** — עדיין לא נוסף. Runbook מוכן (סעיף 3.1 למעלה, ללא שינוי).
2. **Account/Transaction: repair/retire/השאר** — P0 עדיין פתוח ב-`PRODUCT_AUDIT_AND_ROADMAP.md`. שום מידע חדש לא שינה את שיקול-הדעת (סעיף 3.2 למעלה, ללא שינוי) — 8-9 יכולות (כולל KPI dashboard) עדיין תלויות בנתונים שבורים/קפואים.
3. **ניקוי שרידי SUMIT** (מסמך 1001 + לקוח 2095660683) — ללא שינוי (סעיף 3.3). ה-route למחיקת הלקוח קיים ומוכן טכנית, אבל דורש אישור חד-פעמי מפורש.
4. **מבנה אחיד / PCN874 / ריבית חוק מוסר תשלומים** — ללא שינוי (סעיפים 3.4-3.6). לא נחקרו מחדש בסבב הזה.
5. **אימות תאימות-נתונים מול מסכי SUMIT החיים** (יעד-סיום #3 בהנחיית-המטרה) — **לא בוצע בכלל בכל הסבב הזה**, ולא רק כי לא הגעתי אליו: זה דורש כניסה בפועל ל-`app.sumit.co.il` עם התחברות אמיתית, וזו פעולה שאסור לי לבצע בעצמי (הזנת סיסמה לאימות היא פעולה אסורה לפי כללי הבטיחות שלי, גם עם משתמש-בדיקה). **דרוש אחד משניים**: (א) המשתמש עצמו נכנס ומספק צילומי-מסך/מספרים להשוואה, או (ב) לוותר על ההשוואה מול ה-UI ולהסתפק בהשוואה מול ה-API/swagger בלבד (חלקי יותר, אבל בר-ביצוע על ידי סוכן).
6. **Open Finance consent** — `OPEN_FINANCE_USER_ID` עדיין חסר; מסך ההפעלה מוכן מצד הקוד, אבל מסע ה-consent הבנקאי בפועל הוא פעולת-משתמש בלעדית.

### שני סיכוני-החלטה חדשים (לא היו בתדרוך המקורי — עלו תוך כדי ביצוע פריט 3+4)
ר' `docs/superpowers/plans/2026-07-04-continuation-plan-open-items.md` לפירוט מלא:
- **א. רשימת קודי-הבנק במס"ב היא צילום קפוא** (43 קודים, 2026-07-04) המשמש כחסימה קשיחה — לא רענון-חי. סיכון: ספק חדש-לגיטימי לא-ברשימה ידולג בשקט מקובץ תשלום אמיתי.
- **ב. `contact_card` מפספס תשלומים לא-משוייכים** — Payment עם `contact_id=NULL` (מסנכרון-לא-נפתר) פשוט לא מופיע, עלול לנפח יתרת-חוב מוצגת.

### אפיקים מתוך "5 האפיקים" שטרם התחילו כלל
- **אפיק 2** (סופר-אדמין + UI פר-לקוח מלא) — לא התחיל כאפיק ייעודי.
- **אפיק 3** (Open Finance חי) — תשתית מלאה, חסום ב-consent (ר' לעיל).
- **אפיק 5** (רגולטוריה — PCN874/מבנה-אחיד/הגשות-סרוקות) — לא התחיל; דורש סקריפט-דפדפן, לא קוד backend רגיל, כי אין API ב-SUMIT לאלה כלל.

### המלצה לסוכן הממונה
אם נדרשת תכנית-המשך נוספת: הפריטים הכי בטוחים-ליישום-מיידי (לא דורשים החלטת-משתמש) הם עוד סיבובי "grep שיטתי + תיקון" כמו סעיף 8 למעלה (יש עוד מקום לחפש רכיבי-backend, לא רק frontend, עם דפוסי mock/hardcode/placeholder). כל דבר אחר בסעיף הזה דורש תשובה מהמשתמש לפני שניתן לתכנן TDD סביבו.

---

### Critical Files for Implementation
- /Users/mymac/coding/cfo/src/cfo/services/document_issuance_service.py
- /Users/mymac/coding/cfo/src/cfo/services/contact_service.py (new)
- /Users/mymac/coding/cfo/src/cfo/api/routes/expenses.py
- /Users/mymac/coding/cfo/src/cfo/services/masav_service.py
- /Users/mymac/coding/cfo/src/cfo/services/ledger_service.py
- /Users/mymac/coding/cfo/src/cfo/services/ai_chat_tools.py
- /Users/mymac/coding/cfo/src/cfo/api/routes/payments.py (הרחבת Upay, סעיף 8)
- /Users/mymac/coding/cfo/frontend/src/components/SettingsPage.tsx (חדש, סעיף 8)
- /Users/mymac/coding/cfo/frontend/src/components/CFOSyncDashboard.tsx (כרטיס Upay, סעיף 8)
