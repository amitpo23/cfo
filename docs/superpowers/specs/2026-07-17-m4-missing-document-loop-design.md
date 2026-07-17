# M4 — לולאת החוסרים האוטומטית: מסמך עיצוב

**תאריך:** 2026-07-17 | **סטטוס:** מאושר ע"י הבעלים (גישה A) | **היקף:** ארגון 1 בפיילוט
**עיקרון מנחה:** רצף היא הכלי — שיקול הדעת של מנהל חשבונות מעולה מקודד בחוקים שלהלן. כל החלטה אוטומטית חייבת להיות כזו שרו"ח היה חותם עליה; כל ספק מקצועי עוצר לבדיקה, לא מומצא.

## 1. מטרה

לסגור אוטומטית את הלולאה: תנועת בנק יוצאת ללא מסמך → תיק טיפול → העלאת מסמך → OCR → אימות → תיוק ב-SUMIT → סנכרון חוזר → התאמה נסגרת. מבוסס כולו על רכיבים קיימים (טקסונומיית החוסרים, צינור ה-OCR, תיוק ההוצאות, delta-sync, reconciliation) — החדש: מודל תיק, job יומי, מסך אחד, ושער אימות לתיוק אוטומטי.

## 2. מודל נתונים

`MissingDocumentCase` (טבלה חדשה + מיגרציה):
- `id`, `organization_id` (FK, org-scoped בכל שאילתה)
- `bank_transaction_id` (FK, unique — תיק אחד לתנועה)
- `status`: `open | doc_uploaded | ocr_processing | verified | filed | closed | dismissed | needs_review`
- `merchant_hint`, `amount`, `transaction_date`, `channel` (BANK/CARD) — snapshot לתצוגה
- `uploaded_file_path`, `ocr_result` (JSON), `verification_result` (JSON — הפירוט המלא של כל בדיקה)
- `filed_document_id` (SUMIT doc id), `matched_expense_id`
- `dismiss_reason`: `personal | duplicate_exists | no_doc_required | other` + `dismiss_note`
- `created_at`, `updated_at`, `closed_at`

## 3. זרימה

### 3.1 פתיחת תיקים (job יומי)
אחרי סנכרון ה-cron היומי: `classify_missing_documents` (קיים ב-bank_query_service) על ארגון 1 → לכל מועמד `missing_document` שאין לו תיק — יצירת תיק `open`. אידמפוטנטי לפי `bank_transaction_id`. תנועות מוחרגות (סליקה/העברות/מזומן/הו"ק/מסים/עמלות) לעולם לא הופכות תיק.

### 3.2 העלאה ואימות
1. משתמש מעלה קובץ במסך החוסרים (route חדש, multipart) → `doc_uploaded` → `ocr_processing`.
2. צינור ה-OCR הקיים (`expense_ocr_pipeline`) מחלץ: ספק, ח.פ, סכום, תאריך, מע"מ.
3. **שער האימות (שיקול הדעת החשבונאי):** התיוק אוטומטי רק אם כולם עוברים:
   - סכום המסמך = |סכום התנועה| בטולרנס 2% (או הפרש ≤ ₪1).
   - תאריך המסמך בחלון ±14 יום מתאריך התנועה.
   - שם הספק תואם את תיאור התנועה (token overlap) **או** ח.פ מזוהה.
   - **כלל 6 החודשים:** תאריך המסמך לא ישן מ-6 חודשים — ישן יותר → `needs_review` (דיווח מאוחר דורש החלטת רו"ח).
   - **שער כפילויות:** אין ב-Rezef הוצאה/חשבונית-ספק קיימת עם אותו ספק+סכום±2%+תאריך±7י — יש → `needs_review` עם הפניה לרשומה הקיימת (לא מתייקים פעמיים!).
   - **חיוב חו"ל** (מטבע מקור זר / ספק זר מזוהה): מתויק כהוצאת חו"ל עם מע"מ 0 — לא ממציאים מע"מ ישראלי על Microsoft/Vercel.
   - מע"מ במסמך חייב להתפצל תקין (vat_utils) — סתירה בין מע"מ מוצהר למחושב מעל ₪1 → `needs_review`.
4. עבר הכול → `verified`; נכשל משהו → `needs_review` עם פירוט הבדיקות ב-`verification_result` (המשתמש רואה בדיוק מה לא הסתדר ויכול לאשר ידנית).

### 3.3 תיוק וסגירה
1. `verified` → תיוק ב-SUMIT דרך שירות התיוק הקיים (`addexpense`) → `filed` + `filed_document_id`.
2. Delta-sync ממוקד (`run_full_sync(["bills","payments"])` או trigger webhook כשיירשם) מושך את המסמך חזרה.
3. Reconciliation רץ על התנועה → נוצרת התאמה יציבה → `closed` + `closed_at`.
4. תיוק נכשל (403/חריגה) — התיק נשאר `verified` וינוסה שוב ב-job הבא; ללא retry מיידי (משמעת עלויות).

### 3.4 Dismiss
פעולת דחייה עם סיבה חובה. `personal` מלמד את הטקסונומיה (הספק נכנס לרשימת דילוג עתידית — נתון נשמר, החוק ייושם בגרסה הבאה).

## 4. ממשקים
- Routes (org-scoped): `GET /missing-documents/cases` (+פילטר סטטוס), `POST /cases/{id}/upload`, `POST /cases/{id}/dismiss`, `POST /cases/{id}/approve` (אישור ידני מ-needs_review → ממשיך לתיוק), `POST /missing-documents/scan` (הרצת job ידנית, cooldown).
- כלי בוט: הרחבת `get_missing_documents` להחזיר גם תיקים פתוחים לפי סטטוס; כלי write חדש `dismiss_missing_document_case` (מאחורי שער האישור).
- UI: מסך אחד — טבלת תיקים לפי סטטוס, העלאה, dismiss, תצוגת verification_result. בלי דשבורד חדש מעבר לזה.

## 5. טיפול בשגיאות
- OCR נכשל/קובץ לא קריא → `needs_review` עם השגיאה.
- SUMIT חסום → נשאר `verified`, מונה ניסיונות, התראה אחרי 3 ימים.
- אותו קובץ הועלה לשני תיקים → hash הקובץ נבדק; כפילות → חסימה עם הודעה.
- כל מעבר סטטוס נרשם (audit trail בתוך JSON events בתיק).

## 6. בדיקות (TDD)
- Job: יצירה אידמפוטנטית, החרגות לא נפתחות, org isolation.
- שער האימות: כל חוק בנפרד (טולרנס, 6 חודשים, כפילות, חו"ל, סתירת מע"מ) — RED→GREEN.
- זרימה מלאה עם fakes: upload→OCR(fake)→verified→filed(fake SUMIT)→sync(fake)→closed.
- needs_review→approve ידני. Dismiss עם סיבה. כישלון תיוק לא מאבד את התיק.
- כלי הבוט org-scoped.

## 7. מה במפורש לא בהיקף
מייל/וואטסאפ כערוץ קליטה (שלב הבא), הרחבה לארגונים 2/5 (אחרי שבוע נקי), התראות דחיפה (תלוי SMTP), למידת ספקים אישיים אוטומטית (הנתון נאסף, החוק בהמשך).
