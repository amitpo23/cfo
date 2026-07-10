# רצף כמתכלל — מפת יכולות מלאה ותוכנית מימוש v2

**נבנה:** 2026-07-10, אחרי מיפוי שיטתי של כל יכולות SUMIT (swagger חי, 84 endpoints + מרכז עזרה) ו-Open Finance (llms.txt מלא + מרכז עזרה) מול המימוש בפועל ב-Rezef.
**עיקרון:** רצף אינה "עוד חיבור" — היא המוח שמתכלל שלוש מערכות: **Open Finance** (אמת פיננסית גולמית — בנק/כרטיס/יתרות/תשלומים), **SUMIT צד-עסק** (מסמכים חוקיים, סליקה, CRM, SMS), ו-**SUMIT הנהלת חשבונות** (ספרים רשמיים, פקודות יומן, פורטל רו"ח). הערך של רצף = מה שאף אחת מהן לא עושה לבד.

## חלק א' — מפת כיסוי (עובדות, נכון להיום)

### שכבת client (עטיפת API) — כמעט מלאה
- **SUMIT:** 76/84 endpoints עטופים ב-`sumit_integration`/services. שמונת הלא-עטופים: `books/transactions/createbatch` (פקודות יומן — **התגלית המרכזית**), `billing/recurring/charge`, `creditguy/billing/load`, `creditguy/vault/tokenizesingleuse`, `crm/data/getentitieshtml`, `deals/adddeal`, `deals/createremark`, `billing/generalbilling/openupayterminal`.
- **Open Finance:** ~90 מתודות ב-`OpenFinanceClient` — מכסות הכול: connections, accounts, transactions (+PATCH), payments (רגיל/bulk/תקופתי/refund/cancel/ATM), mandates (הוראות קבע בנקאיות!), merchants, monthly-report, extended-securities, financial-report, decision, private-scoring, aggregations, credit sessions, OSH, WhatsApp-link.

### שכבת הערך (services/bot/UI) — כאן הפער
| יכולת זמינה | מי חושף אותה | האם רצף מפיקה ממנה ערך היום |
|---|---|---|
| קטגוריזציה מובנית על כל תנועת בנק (`category.main/sub`) | OF | ❌ נשמר ב-raw_data, לא מנוצל לסיווג הוצאות/תובנות |
| יתרות בזמן-אמת (`closingBooked`/`expected`) + `cardDueDate` | OF | ❌ תזרים לא ניזון מהן |
| `monthly-report`, `extended-securities` | OF | ❌ route קיים, אף שירות לא צורך |
| webhooks על שינוי סטטוס connection/payment | OF | ⚠️ receiver קיים, לא רשום ב-dashboard, לא מפעיל delta-sync |
| `verify_account_number` (חשבון מוגבל) | OF | ❌ לא נבדק לפני בקשות תשלום |
| mandates — הוראת קבע בנקאית לגבייה חוזרת | OF | ❌ לא בשימוש |
| bulk/standing-order payments | OF | ❌ לא בשימוש |
| `PATCH /data/transactions/{sk}` (עדכון קטגוריה חזרה ל-OF) | OF | ❌ |
| `books/transactions/createbatch` — פקודות יומן לספרים | SUMIT | ❌ לא עטוף ולא בשימוש — **המפתח להחלפת הנה"ח הידנית** |
| `triggers/subscribe` — webhook מ-SUMIT על אירועי מסמכים | SUMIT | ❌ עטוף, לא בשימוש — מייתר polling שעתי ופותר את מגבלת ה-403 |
| `billing/recurring/charge` — חיוב מחזורי (ריטיינרים) | SUMIT | ❌ |
| `scheduleddocuments` — חשבוניות מחזוריות | SUMIT | ⚠️ עטוף, לא מחובר לזרימת ריטיינרים |
| `sms/send` + מיילינג | SUMIT | ✅ בשימוש בגבייה (SMS מוכן; מייל חסום על SMTP) |
| מודול בנק של SUMIT (feed+התאמות במסך, Growth+) | SUMIT UI | ✅ קיים אצל המשתמש במסך; אין לו API — רצף לא תלויה בו |
| התאמות בנק, דוח חוסרים, OCR, תזרים, בוט | רצף | ✅ הליבה עובדת (הוכח היום), אך חד-פעמית — לא מתוזמנת |

### תשתית — פערים חוסמים
1. **אין סנכרון OF מתוזמן** (אין `IntegrationConnection`), וה-cron השעתי עושה full-sync בלי watermark — יישרוף קרדיטים (500/חודש) אם נחבר כמו-שהוא. SUMIT נחבט ב-403 בלי circuit-breaker.
2. **VAT לא מפוצל** במסמכים מסונכרנים → כל פלט מע"מ שגוי (VAT=0).
3. **SMTP חסר** → מיילים (תזכורות/התראות/דוחות) לא יוצאים.
4. `is_provisional` לא מתהפך — אין flow אימות-בעלים.
5. הבוט עיוור לבנק — אין כלי שאילתות על 1,884 התנועות שנקלטו.

## חלק ב' — עשרת מהלכי הערך של המתכלל

מסודרים לפי (תלות ← ערך). כל מהלך = יכולת ששתי המערכות לא נותנות לבד:

**M1. עצבים במקום דופק (תשתית אירועים):** SUMIT `triggers/subscribe` → webhook לרצף על מסמך חדש; OF webhooks רשומים ב-dashboard → delta-sync ממוקד. + פיצול cron, watermarks, circuit-breaker, תקציב קריאות יומי. *פותר בבת-אחת: 403, קרדיטים, ריענון איטי.*

**M2. ספר-אמת בנקאי חי:** חיבור `IntegrationConnection` ל-OF (אחרי M1), ריענון יומי, יתרות `closingBooked` נשמרות כ-snapshot, אימות-בעלים שמהפך `is_provisional`.

**M3. סיווג חכם כפול:** קטגוריית OF (`TRANSPORT/CAR_&_FUEL`...) ממופה לקטגוריות המס של רצף כברירת-מחדל לסיווג הוצאות; תיקוני משתמש נדחפים חזרה ב-`PATCH transactions` — לולאת למידה. מזין את expense_classifier הקיים.

**M4. לולאת החוסרים אוטומטית:** דוח היום ← כמנוע רץ: תנועה יוצאת ללא מסמך → insight/משימה → צילום/מייל → OCR (קיים) → `addexpense` ל-SUMIT → trigger חוזר (M1) → delta-sync → ההתאמה נסגרת. *הערך העסקי המוחשי ביותר.*

**M5. פקודות יומן אוטומטיות:** עטיפת `books/transactions/createbatch` + מיפוי אינדקס חשבונות + dry-run; התאמות מאושרות ← batch יומי לספרי SUMIT. *ההשלמה של "להחליף את מנהל החשבונות".* דורש: אימות שמודול Books פעיל על CompanyID של העוסק (המשתמש רואה מסך התאמות — כנראה כן), מיפוי קודים, אישור פר-batch בהתחלה.

**M6. גבייה תלת-ערוצית:** תזכורת (SMS של SUMIT / מייל אחרי SMTP) + שלוש דרכי תשלום מהבוט: קישור סליקה SUMIT (קיים) / העברה בנקאית OF payUrl (נוסף היום) / **mandate בנקאי** לריטיינרים. סטטוס תשלום ב-webhook → קבלה אוטומטית ב-SUMIT → נסגר בהתאמה כשמגיעה תנועת הבנק. + `verify_account_number` לפני כל בקשה.

**M7. תזרים אמת:** התחזית ניזונה מיתרות חיות + `cardDueDate` (החיוב הקרוב של הכרטיס ידוע!) + הוראות קבע שזוהו + מסמכים פתוחים. התראות runway דרך alert_engine (קיים) → ערוצי M6.

**M8. בוט רואה הכול:** כלים חדשים — `query_bank_transactions` (כולל "כמה הוצאתי על X"), `get_bank_position`, `get_missing_documents`, `approve_reconciliation`. הבוט הופך לממשק ההפעלה של M4-M7.

**M9. תיקון VAT ודוחות רשמיים:** פיצול מע"מ במסמכים המסונכרנים (הבאג הידוע), ואז דוח מע"מ/מקדמות מרצף מוצלב מול SUMIT — כפול-אימות שאף מערכת לא נותנת.

**M10. שכבת דוחות מנהלים:** דוח חודשי משולב (בנק+ספרים+תזרים+חוסרים) שנשלח אוטומטית במייל/וואטסאפ — הצפת ערך יזומה, לא רק בשאילתא.

## חלק ג' — סדר ביצוע

| שלב | מהלכים | תלות |
|---|---|---|
| 1 | M1 (אירועים+הגנת קריאות) | — חוסם הכול |
| 2 | M2 (ספר-אמת חי) + M8 (כלי בוט לבנק) | M1 |
| 3 | M4 (לולאת חוסרים) + M9 (VAT) | M2 |
| 4 | M5 (פקודות יומן) — אחרי אימות Books+מיפוי+אישור | M2, שחרור 403 |
| 5 | M6 (גבייה) + SMTP + M7 (תזרים) | M1-M2 |
| 6 | M3 (סיווג לומד) + M10 (דוחות יזומים) | M2-M4 |

## עדכוני עובדות למסמכים קודמים
- RSF-151 עודכן: יש API לפקודות יומן (`createbatch`).
- הדרישה "התאמה תשב גם ב-SUMIT" ממומשת דרך M5 (פקודות יומן) — לא דרך API התאמות שאינו קיים.
- עותק swagger: `docs/sumit_swagger_v1_2026-07-10.json`; מרכז ידע OF: `docs/OPEN_FINANCE_KNOWLEDGE_BASE.md` + `docs/open_finance_api_reference/`.
