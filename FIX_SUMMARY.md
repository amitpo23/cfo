# FIX_SUMMARY — חשבונית מס: מע"מ נטו + ח.פ לקוח + מייל (2026-11-09)

- ענף: `fix/invoice-vat-taxid` (base `e961c65`)
- HEAD (קוד): `e66be42`
- PR: https://github.com/amitpo23/cfo/pull/108 — פתוח, לא מוזג
- Preview (Vercel, מה-PR, לא קודם): https://cfo-2-2z05ctgiq-guyofiror.vercel.app
  (גם https://cfo-financial-system-bkhio0hqx-guyofiror.vercel.app)
- CI ב-GitHub: לא רץ ("account is locked due to a billing issue"), כל הבדיקות רצו מקומית.

## מה תוקן
1. **מע"מ**: `VATIncluded` לוקח את ערכו מ-`prices_include_vat`, שברירת המחדל שלו היא false (נטו, כמו במסך). `VATRate` לא נשלח כי היחידה שלו לא מתועדת: SUMIT מחיל את שיעור החברה, ושיעור לא-חוקי נחסם לפני קריאה. שורה בלי `vat_rate` מקבלת את השיעור החוקי לתאריך (קודם 17).
2. **ח.פ**: שדה במסך עם ולידציה של 9 ספרות. נשלח כ-`Details.Customer.CompanyNumber` ונשמר על ה-Contact. אזהרה מוצגת מעל סף ההקצאה כשאין ח.פ.
3. **סוג מסמך**: `invoice` ממופה ל-`Invoice` (חשבונית מס). יש טסט.
4. **מייל**: נשלח רק כשמסמנים זאת, עם אפשרות לכתובת אחרת, דרך `Details.SendByEmail` בלי קריאת send נפרדת. גם `/financial/invoices` כבר לא שולח אוטומטית.

## בדיקות שרצו
- `tests/test_invoice_vat_taxid.py`: 21/21 עוברים (מקרים: 60,000 נטו → `VATIncluded:false` וסה"כ 70,800; מצב ברוטו; מיפוי; מייל; ח.פ; טסט route עם שער אישור).
- 54 קבצים קשורים: 837 עברו ו-4 נכשלו. אותם 4 נכשלים גם ב-base `e961c65`, אז זו לא רגרסיה.
- Frontend: `tsc --noEmit` ✓, lint ✓, `node --test` 26/26 ✓, `npm run build` ✓.
- לא בוצעה אף קריאה ל-SUMIT ולא הופק אף מסמך.

## לפני הפקה אמיתית היום (עמית)
- אם הלקוח **כבר קיים ב-SUMIT** (נבחר מההצעות עם "SUMIT <id>"), הוא נשלח לפי `ID` והח.פ **לא מתעדכן**. צריך לוודא בפורטל שיש לו ח.פ.
- השיעור שנשלח הוא ברירת המחדל של החברה ב-SUMIT. צריך לוודא שהיא 18%.
- מומלץ לבדוק את החשבונית הראשונה ב-preview (סה"כ 70,800 במסך האישור) לפני ההפקה בפרוד.

## Follow-ups (לא שונו)
- `VATIncluded: true` באתרים אחרים: `sumit_integration.py` (בערך בשורות 2573, 2615, 2675, 2776: charge, payment link וכו') ו-`recurring_billing_service.py:151`.
- עדכון ח.פ ללקוח קיים ב-SUMIT לפי `ID`.
- תמיכה בשיעור מע"מ שונה מהחוקי (0% וכד'): צריך לאמת את היחידה של `VATRate` או ליישם `VATPerItem`.
- `invoice_receipt` עם `Payments`: התקבולים חייבים להיות בסכום הברוטו.
- `document_anomalies.ALLOCATION_THRESHOLD` קבוע (5000, `>=`), לעומת `israeli_tax_rules` המתוארך (`>`).
- `/accounting/documents` (route גולמי) ו-`InvoiceService` הישן משתמשים עכשיו בברירת המחדל נטו.
