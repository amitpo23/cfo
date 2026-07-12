# מיפוי כיסוי יכולות — SUMIT ו-Open Finance (2026-07-12, אמפירי)

**מחליף** את חלק א' (מפת כיסוי) של [REZEF_MASTER_ORCHESTRATION_PLAN.md](REZEF_MASTER_ORCHESTRATION_PLAN.md)
(שנכתב 07/07/26 ומאז התיישן). נבנה ע"י שני סוכני חקירה עצמאיים שעברו על **כל**
84 ה-endpoints של SUMIT ו-**כל** 83 המתודות של Open Finance ואימתו שימוש בפועל
בקוד (לא רק "עטוף") — grep שיטתי מול `services/`, `api/routes/`, `ai_chat_tools.py`, `cron.py`.

## שיטת הסיווג (זהה לשתי המערכות)
- **L0** — לא עטוף כלל, אין מתודת client.
- **L0\*** — עטוף **ונקרא בפועל** מ-route/service חי, אבל גוף המתודה `raise` תמיד
  במכוון (SUMIT לא תומך סמנטית) — מתועד בקוד, לא רגרסיה.
- **L1** — עטוף, אפס קריאות מחוץ לקובץ ה-client (route קיים לפעמים, אבל dead).
- **L2** — נצרך בשירות, אבל אין route/cron/בוט חי שמפעיל את השירות. **לא נמצא אף מקרה** בשתי המערכות — כל מה שנצרך בשירות, בסופו של דבר נחשף.
- **L3** — חי בפועל, שרשרת route→service→client מוכחת.

## SUMIT — 84/84 endpoints

| רמה | כמות | פירוט |
|---|---|---|
| L0 (לא עטוף) | 4 | `books/transactions/createbatch`, `creditguy/vault/tokenizesingleuse`, `deals/adddeal`, `deals/createremark` |
| L0\* (מקושר, נכשל תמיד במכוון) | 4 | `creditguy/billing/load`, `crm/data/getentitieshtml`, `billing/generalbilling/openupayterminal`, `billing/recurring/charge` |
| L1 (עטוף, אפס קריאות) | 3 | `creditguy/gateway/getreferencenumbers`, `billing/payments/multivendorcharge`, `billing/recurring/updatesettings` |
| L2 | 0 | — |
| **L3 (חי בפועל)** | **73** | **87%** |

**זהה במספר (8/84) לרשימה הישנה, אך מדויק יותר בקטגוריה** — 4 מהשמונה הן L0 טהור,
4 הן "כן נקראות בקוד, כושלות תמיד במכוון" (docstrings מסבירים שה-endpoint לא
תואם סמנטית). לא רגרסיה — התנהגות מתועדת.

### ממצא תפעולי חדש (לא היה במסמך הישן)
**`creditguy/billing/load` (L0\*)** נקראת בכל ריצת `/cron/sync-sumit` (שעתי, לכל
org מחובר) כחלק מ-`fetch_bank_transactions` — וכושלת בשקט בכל פעם (נלכדת,
מוחזרת כ-`error`). מיותר מאז ש-Open Finance מכסה בפועל את תחום תנועות הבנק —
מומלץ להסיר `bank_transactions` מרשימת יעדי source="sumit" בסנכרון (ניקוי, לא דחוף).

### פערי ערך שנותרו
1. **`books/transactions/createbatch`** (L0, אין מתודה) — עדיין החסם למהלך M5
   (פקודות יומן אוטומטיות). `fetch_journal_entries` הקיים מחזיר תמיד ריק — sync
   חד-כיווני מ-SUMIT בלבד, אין push.
2. **`triggers/subscribe`/`unsubscribe`** — L3 חי, אבל **ערך נמוך בפועל**: SUMIT
   תומך ב-triggers רק על ישויות CRM, לא על אירועי הנה"ח כמו "מסמך חדש" —
   מגבלת ה-API עצמו, לא באג ברצף.

## Open Finance — 83/83 מתודות

| רמה | כמות | |
|---|---|---|
| L1 (עטוף, אפס קריאות) | 13 | 15.7% |
| L2 | 0 | — |
| **L3 (route חשוף)** | **70** | **84.3%** |

**אזהרת פרשנות:** L3 כאן הוא קריטריון נדיב — "route חשוף" בלבד. מתוך 70,
כ-60 הן **thin pass-through בלי שום שירות שמעבד את הנתון**. שימוש עסקי אמיתי
(route + שירות שמפעיל לוגיקה, cron מתוזמן, או כלי בוט רשום) מאומת רק ל-**8-9
מתודות "עמוקות"**: `list_accounts`, `list_transactions`, `list_connections`,
`create_connection`, `get_connection`, `get_monthly_report`, `get_extended_securities`,
`create_payment` (היחידה עם כלי בוט רשום).

### פערי ערך שנבדקו ספציפית
| יכולת | סטטוס בפועל |
|---|---|
| קטגוריזציה (`category.main/sub`) | ✅ **בשימוש** — `bank_expense_gap.classify_transaction` (T3, נבנה היום) |
| יתרות `closingBooked` | ✅ בשימוש — `open_finance_connector._BALANCE_TYPE_PRIORITY` |
| `cardDueDate` (חיוב כרטיס קרוב) | ❌ אפס שימוש — פער אמיתי לתזרים |
| Mandates (הוראת קבע) | ❌ 4/4 מתודות חשופות, אפס שימוש עסקי |
| `PATCH transactions` (כתיבת סיווג חזרה) | ❌ route חי, אף שירות לא כותב אליו |
| Webhooks (קליטה) | ✅ מקבל+מעבד חי (`webhook_delta_sync`); ⚠️ לא ניתן לאמת מהקוד שהספק *שולח* לשם (רישום דרך dashboard חיצוני), ו-`callbackInformation` הפר-חיבור לעולם לא מועבר ב-`create_connection` |

### דריפט תיעוד
`docs/OPEN_FINANCE_API_REFERENCE.md` (907 שורות) תואם ~1:1 לקוד, ללא דריפט.
`docs/open_finance_api_reference/*.md` (15 קבצים) מכסה רק תת-קבוצה
(connections/accounts/transactions/branches/providers/monthly-report/securities) —
לא דריפט, כיסוי חלקי מתועד היטב.

## 🔴 ממצא קריטי חדש — נמצא ותוקן היום: דליפת מידע חוצת-לקוחות

**הבעיה:** `get_monthly_report`/`get_extended_securities` **אין להן פרמטר
connectionId בכלל** (מאומת מול ה-OpenAPI spec של הספק) — הן מוחזרות **מצטברות
לפי `userId` בלבד**, בניגוד ל-`list_accounts`/`list_transactions` שכן תומכות
ב-`connectionId` (וקיבלו scoping פר-org היום, ב-commit `72b0baf`).

**המצב החי שנמצא:** org 1 (עמית פורת) ו-org 2 (שף אליהב) **מחוברים תחת אותו
userId אמיתי של Financy** (`amitporat1981@gmail.com`) — כי שני חיבורי הבנק
נוצרו דרך אותו חשבון Financy אישי, לא דרך הקצאת userId נפרד פר-לקוח. קריאה ל-
`GET /monthly-report` או `/securities` עבור org 1 הייתה מחזירה **את הסכומים
המצטברים של שני הלקוחות יחד** — אין שדה לסנן לפיו (הצבירה קורית בשרת הספק).

**התיקון (בוצע, נפרס):** `_has_shared_of_identity()` ב-`open_finance.py` בודקת
אם ל-org אחר פעיל יש אותו userId אפקטיבי; אם כן — `/monthly-report` ו-`/securities`
מחזירים 409 עם הסבר בעברית, וה-enrichment האוטומטי ב-`insights/generate`
מדלג בכנות (במקום להחזיר `null` סתמי או למזג בטעות). 5 טסטים חדשים
(`test_open_finance_shared_identity.py`), suite מלא ירוק.

**פתרון-שורש (לא בוצע — דורש החלטת מוצר):** userId נפרד פר-לקוח ב-Financy
(רישום/הקצאה נפרדת), לא רק הזרקת ערך שונה לקוד — הקוד כבר תומך ב-`ensure_of_identity`
(`open_finance_onboarding.py`) שמקצה `rezef-org-<id>` אוטומטית לכל org מלבד
org 1, אבל זה לא משנה למי ה*חיבור הבנקאי עצמו* שייך ב-Financy אם הוא כבר נוצר
דרך אותו login אישי.

## סיכום מנהלים
- **SUMIT: 87% חי בפועל.** הפערים הנותרים (createbatch, triggers ל-CRM בלבד)
  ידועים ומתועדים; אין דחיפות.
- **Open Finance: כיסוי-routes רחב (84%) אך רק ~9 מתודות "עמוקות" באמת מייצרות
  ערך.** זה תואם את עקרון-העל של [REZEF_OPERATING_MODEL.md](REZEF_OPERATING_MODEL.md) —
  השכבה הטכנית כמעט שלמה, הפער האמיתי הוא שכבת הערך.
- **תוקן היום ממצא אבטחה אמיתי** (לא תיאורטי — חי על נתוני שני לקוחות אמיתיים)
  באותה משפחה בדיוק כמו תיקון ה-connection_id scoping מוקדם יותר היום.
