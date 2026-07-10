# מרכז ידע — Open Finance API

**מקור:** [help.open-finance.ai/he](https://help.open-finance.ai/he/) (מרכז העזרה הרשמי, 25 מאמרים, 4 קטגוריות)
**נאסף:** 2026-07-10
**הקשר בפרויקט:** תומך ב-Workstream A/C ב-[REZEF_SUMIT_OPEN_FINANCE_COMPLETION_PLAN.md](REZEF_SUMIT_OPEN_FINANCE_COMPLETION_PLAN.md) ו-`OpenFinanceClient` ב-[src/cfo/services/open_finance_client.py](../src/cfo/services/open_finance_client.py).
**דוקומנטציה מלאה (interactive):** `docs.open-finance.ai`

---

## 0. ממצא קריטי — פותר את חסימת RSF-005

> "אם החשבון חובר דרך Financy, ה-`userId` שווה לכתובת המייל של ההרשמה."

זה פותר ישירות את החסימה שתועדה ב-[REZEF_SUMIT_OPEN_FINANCE_TODO.md](REZEF_SUMIT_OPEN_FINANCE_TODO.md) (RSF-005) וב-[open-finance-integration-state](../../../.claude/projects/-Users-mymac-coding-cfo/memory/open-finance-integration-state.md): חסר `OPEN_FINANCE_USER_ID` בפרודקשן. אם חיבור בנק הפועלים בפיילוט חובר בפועל דרך Financy (כפי שתועד), אזי `OPEN_FINANCE_USER_ID` הוא **כתובת המייל שאיתה נרשם המשתמש ל-Financy** — לא מזהה שרירותי שצריך "לקבל" מהספק. יש לאמת זאת מול המייל בפועל ולהגדיר כ-secret ב-Vercel לפני כל ניסיון API.

---

## 1. אימות מול ה-API (Access Tokens)

- מודל: **טוקן פר-משתמש**. כל טוקן משויך ל-`userId` ספציפי ומעניק גישה רק לנתונים שלו.
- **Endpoint:** `POST https://api.open-finance.ai/oauth/token`
- **Headers:** `Content-Type: application/json`
- **Body:**
  - `clientId` — מזהה הארגון מה-dashboard
  - `clientSecret` — **סודי, לעולם לא בצד לקוח**
  - `userId` — מזהה המשתמש במערכת שלכם (= מייל ההרשמה אם החיבור נוצר דרך Financy)
- שימוש: `Authorization: Bearer <token>`
- הטוקן הוא JWT עם תפוגה — ליצור מחדש כשפג.
- **אילוץ קריטי:** הטוקן חייב להתאים לאותו `userId` שאיתו נוצר חיבור הבנק. טוקן עם `userId` אחר לא ייתן גישה לנתוני החיבור המחובר.
- תיעוד מלא: `docs.open-finance.ai/docs/access-tokens`

## 2. יצירת חיבור בנק דרך ה-API

- **Endpoint:** `POST /v2/connections` (דורש scope `create:connections`)
- **Body (כל השדות אופציונליים):**
  ```json
  {
    "psuId": "123456789",
    "startDate": "2026-01-01",
    "providerIds": ["leumi"],
    "iframe": true,
    "redirectUrl": "https://your-app.com/return"
  }
  ```
  - `psuId` — ת.ז./דרכון המשתמש
  - `startDate` — ברירת מחדל שנה אחורה; לא יכול לחרוג משנה אחורה
  - `expiryDate` — ברירת מחדל 3 שנים קדימה; מקסימום מתחת ל-3 שנים
  - `providerIds` — סינון לבנק/ים ספציפיים; השמטה = מסך בחירת בנק
  - `iframe` — הטמעה עם postMessage
  - `psuCorporateId` — ח.פ. לחשבון עסקי
  - נוספים: `language` (`he`/`en`), `allowBusiness`, `access`, `callbackInformation` (webhooks)
- **תגובה (201):** `id` (מזהה חיבור), `connectUrl` (קישור למסע ההסכמה)
- **מסע המשתמש:** בחירת בנק (אם `providerIds` לא צוין) → התחברות בבנק → אישור שיתוף מידע → חיבור פעיל, נתונים זורמים
- **גילוי ספקים:** `GET /v2/providers` — לכל ספק יש וריאנט `-sandbox` לבדיקות.

## 3. שליפת חשבונות ותנועות

- **חשבונות:** `GET /v2/data/accounts` (scope `read:accounts`)
  - פרמטרים: `connectionId`, `accountType`, `limit` (מקס' 500), `nextPage`, `sort` (`1`/`-1`), `includeDuplicates` (`0`/`1`)
- **תנועות:** `GET /v2/data/transactions` (scope `read:transactions`)
  - פרמטרים: `dateFrom`/`dateTo` (`YYYY-MM-DD`), `accountId`, `connectionId`, `providerId`, `type` (`BANK`/`CARD`), `limit` (ברירת מחדל 500, מקס' 2000), `sort`, `includeDuplicates`
- **Pagination:** טוקן `nextPage` בתגובה כשיש עוד תוצאות; תקף רק לאותה בקשה/משתמש.
- נתונים מתעדכנים במחזורי סנכרון של הבנק — לא בזמן אמת ("we don't 'sit' on your bank account in real time").

### 3.1 סוגי יתרה (`balanceType`)

| ערך | משמעות |
|---|---|
| `closingBooked` | היתרה בספרים המעודכנת ביותר — עסקאות סופיות בלבד. חובה בחשבונות עו"ש |
| `expected` | עסקאות רשומות + פריטים ידועים ממתינים; מקרין יתרת סוף יום |
| `interimAvailable` | יתרה זמינה מחושבת תוך יום עסקים, כפופה לשינוי |
| `interimBooked` | יתרה ביניים לפי עסקאות שכבר נרשמו בספרים |
| `forwardAvailable` | יתרה זמינה לתאריך עתידי מסוים |
| `openingBooked` | יתרת פתיחה מהתקופה הקודמת — **לא נתמך בשוק הישראלי** |

- **עו"ש (CHECKING):** כל 6 הסוגים; `closingBooked` חובה.
- **כרטיסי אשראי/דביט (CARD):** בעיקר `closingBooked`, `interimBooked`, `interimAvailable` — המשמעות משתנה לפי סוג כרטיס (אשראי/דביט/נטען).
- **חיסכון (SAVINGS):** רק `closingBooked` ו-`expected`.
- **הלוואות/משכנתא (LOAN):** `closingBooked` = יתרה נותרת; `interimAvailable`/`interimBooked` = מסגרת זמינה/יתרת ביניים.

## 4. ייזום תשלום

שתי שיטות, שתיהן דורשות טוקן וחולקות מבנה `paymentInformation` זהה:

### שיטה A — UI מתארח של Open Finance
- **Endpoint:** `POST /v2/payments`
- Open Finance מנהל את כל המסכים (בחירת בנק, הרשאה, אישור). תומך בהטמעת iframe.
- **Body:** `psuId`, `providerIds` (אופציונלי — השמטה = מסך בחירת בנק), `paymentInformation` (סכום, מטבע, תיאור, חשבון/סוג/שם נמען)
- **תגובה:** `payUrl` — הפניה למסך התשלום המתארח.

### שיטה B — הפניה ישירה לבנק
- **Endpoint:** `POST /v2/pay/open-banking-init`
- אתם מנהלים את ה-UI, מפנים ישירות למסך ההרשאה בבנק. `providerId` **חובה** בשיטה זו.
- **תגובה:** `paymentId`, `scaOAuth` (קישור הרשאה ישיר לבנק).

**חשוב:** אין להסתמך רק על חזרת ה-redirect — יש לאמת סטטוס סופי דרך endpoint הסטטוס הייעודי.

### 4.1 תשלום מרובה (Bulk Payment)
- Endpoints: `POST /v2/pay/open-banking-init` (ישיר) או `/v2/payments` (UI)
- `bulkPaymentInformation`: פרטי חשבון חייב (מספר+סוג iban/bban), מערך תשלומים (סכום/מטבע/תיאור), פרטי נושה (חשבון/סוג/שם) **או** `merchantId`
- אופציונלי: `batchBookingPreferred`, `paymentInformationId` (עד 35 תווים), `requestedExecutionDate`/`requestedExecutionTime`
- **מגבלות:** מינימום תשלום 1 ב-API ישיר, אך 2 ב-UI; מטבע ILS בלבד; חשבון מקור≠יעד; `providerId` חובה בקריאה ישירה; כל הסכומים > 0.

### 4.2 תשלום תקופתי (Standing Order)
- **Endpoint:** `POST /v2/pay/open-banking-init`
- אובייקט `periodicPaymentInformation` במקום `paymentInformation`
- **שדות חובה:** `amount`, `currency`, `description`, `startDate` (ISO), `frequency`, `debtorAccountNumber`+`debtorAccountType`
- **`frequency`:** `Daily`, `Weekly`, `EveryTwoWeeks`, `Monthly`, `EveryTwoMonths`, `Quarterly`, `SemiAnnual`, `Annual`, `MonthlyVariable`
- אופציונלי: `endDate` (ISO, בד"כ חובה בהעברה ישירה לבנק), `dayOfExecution` (1-31), `executionRule` (`following`/`preceding` — טיפול בימים לא עסקיים), `monthsOfExecution` (מערך, רק ל-`MonthlyVariable`)
- נוספים: `providerId`, `psuId`, `redirectUrl`

### 4.3 סטטוסי תשלום
- **Endpoint:** `GET /v2/payments/{paymentId}/status` — poll עד סטטוס סופי.

| קטגוריה | קוד | משמעות |
|---|---|---|
| **כסף התקבל** | `ACCC` | הסליקה הושלמה בחשבון הנמען |
| | `ACSC` | הסליקה הושלמה בחשבון המשלם |
| **אושר טכנית** | `ACTC` | אימות טכני הצליח |
| | `ACSP` | התקבל, בתהליך סליקה |
| | `ACWC` | התקבל אך ייעשו שינויים |
| | `ACFC` | אושר טכנית עם בדיקת כיסוי |
| | `ACCP` | התקבל ופרטי הלקוח אומתו |
| **בתהליך** | `INIT` | נוצר, טרם הושלם ע"י המשתמש |
| | `RCVD` | הבקשה התקבלה בבנק |
| | `PATC` | ממתין לחתימות מרובות |
| | `PENDING` | ממתין לאישורים נוספים |
| | `PART` | התקבל חלקית (batch) |
| **נכשל/הסתיים** | `RJCT` | נדחה או שהקישור פג |
| | `CANC` | בוטל (מתוזמן/תקופתי) |
| | `ERROR` | שגיאת תהליך |

**סיבות דחייה נפוצות:** אין כיסוי, חריגה ממסגרת העברה, אי-התאמת פרטי זיהוי, קישור תשלום שפג.

**סיבות כשל תשלום נפוצות (מנקודת מבט משתמש):**
1. אי-התאמת פרטי זיהוי — בחשבון משותף, יש להתחבר עם ת.ז. אישית, לא זו של שותף.
2. שגיאת הקלדה בפרטי חשבון (ספרה חסרה/קוד סניף שגוי).
3. אין מספיק יתרה או חריגה ממגבלת העברה דיגיטלית.

## 5. הטמעת iframe

- הוסיפו `iframe=true` ל-query string בעת יצירת קישור החיבור/תשלום.
- אתחול: `openFinance.init({ onApprove, onAbort, onFailed })`, ואז הפעלת פונקציית start עם ה-URL.
- **אירועים (postMessage):** `success` (חיבור הושלם), `fail` (שגיאה), `close` (יציאה באמצע), `redirectToBank` (הפניה לאתר הבנק). כל אירוע כולל מטא-דאטה: user ID, connection ID, סטטוס, פרטי שגיאה, שלב בתהליך.
- מומלץ להציג את ה-iframe כ-modal מלא-מסך, ללא border, רקע שקוף.
- תיעוד מלא: `docs.open-finance.ai/docs/iframe-support`

## 6. שגיאות API נפוצות

| קוד | משמעות | טיפול מומלץ |
|---|---|---|
| `401` | access token חסר/שגוי/פג תוקף | לוודא header נכון; ליצור טוקן חדש |
| `403` | לטוקן תקף אין הרשאה לפעולה/נתון המבוקש | לוודא שהטוקן הונפק לאותו `userId`; לא לנסות לגשת לנתוני משתמש אחר |
| `404` | המשאב לא קיים (חיבור/חשבון/תשלום שגוי) | לוודא מזהה נכון ושייך למשתמש המאומת; לבדוק שלא נמחק |
| `400` | פרמטרים חסרים/שגויים | דוגמאות: `psuId` לא מספרי; שילוב date filters עם `limit`; `providerId` לא נתמך |

לפניות תמיכה: לצרף endpoint, request ID, קוד שגיאה ותיאור.

## 7. חיבור לבנקאות פתוחה — חשבון עסקי

- הרפורמה מאפשרת לחברות בע"מ להתחבר לחשבון הבנק שלהן.
- דרוש: ת.ז. בעל החשבון + מספר תאגיד.
- **בשונה מחשבונות פרטיים — יש להקים הרשאה מראש בבנק לפני מתן הסכמה** (לא ניתן לדלג).
- מדריכים ספציפיים לכל בנק: מזרחי טפחות, דיסקונט, קבוצת הבינלאומי, לאומי, הפועלים, ישראכרט.
- עוסק פטור/מורשה (עצמאי) בד"כ לא צריך את שלב ההרשאה המוקדמת, אך יש לוודא שלמשתמש המחובר יש הרשאות פעולה על החשבון.

## 8. תוקף הסכמה וחידוש

- ההסכמה לשיתוף מידע בנקאי תקפה לפרק זמן מוגבל (רגולציה + מדיניות הבנק הספציפי) — אחיד לכל ספקי הבנקאות הפתוחה.
- **בפקיעת ההסכמה:** זרימת המידע נעצרת, הנתונים הקיימים "קופאים" (ללא עדכון נוסף), החיבור עובר לסטטוס לא-פעיל/שגיאה. **זו התנהגות צפויה, לא תקלה טכנית.**
- **חידוש:** דורש חיבור מחדש ומתן הסכמה טרייה — כמו החיבור הראשוני. מומלץ לחדש **לפני** הפקיעה כדי למנוע פערי נתונים.

## 9. תקלות חיבור נפוצות ופתרונות

- **חיבור נכשל/שגיאה:** לרוב עקב אי-התאמת ת.ז., פרטי התחברות שגויים בחשבון משותף, סיסמת בנק שהשתנתה, או הסכמה שפגה. אם עבד קודם ועכשיו שגיאה → כנראה רק צריך להתחבר מחדש. תקלה נפוצה: אפליקציית הבנק נפתחת למסך בית במקום למסך הסכמה — לסגור לגמרי את האפליקציה ולהתחיל מחדש.
- **`PARTIALLY_AUTHORIZED`:** בחשבון משותף, בעל חשבון אחד אישר אך שאר בעלי החשבון חייבים לאשר גם לפני הפעלה.
- **חשבונות עסקיים:** דורשים הקמת הרשאה בבנק מראש (ר' סעיף 7).
- **חשבונות חסרים:** משתמש עם חשבון פרטי+עסקי רואה רק סוג אחד → לוודא מול הבנק שלמשתמש המחובר יש הרשאות פעולה על כל החשבונות.
- **נתונים/יתרות לא מעודכנים:** התחברות מחדש מכריחה משיכת נתונים טרייה; פערים מתמשכים דורשים פנייה לתמיכה עם תיעוד.
- **ביטול חיבור:** לנהל דרך הפלטפורמה שבה בוצע החיבור המקורי, או לפנות לתמיכה.
- **התהליך נתקע אחרי הפניה לבנק:**
  - מסך נטען ותקוע → להמתין עד דקה, להתחיל מחדש, להימנע מכרטיסיות מרובות במקביל.
  - מסך לא-נכון → session ישן של אפליקציית הבנק ברקע; לסגור לגמרי ולא רק למזער.
  - Pop-up blocker חוסם את מסך הבנק לגמרי → לבדוק חוסמי פרסומות/תוספים, לנסות דפדפן אחר.
  - חיבור נשאר לא-פעיל גם אחרי אישור → יכול לקחת כמה דקות; אם `PARTIALLY_AUTHORIZED` — צריך אישור שאר בעלי החשבון.
- **תנועות חסרות:** בנקאות פתוחה מספקת היסטוריה מוגבלת אחורה (בד"כ עד כמה חודשים); תנועות חדשות ממתינות למחזור הסנכרון הבא; תנועות ממתינות (pending) לא מוצגות עד לסיום סופי בבנק.
- **תנועות כפולות:** ייתכן שמדובר באותה תנועה בסטטוסים שונים — לבדוק אם שני הרשומות חולקות אותו transaction ID; לחלופין, חיבור אותו חשבון כמה פעמים יכול לגרום לכפילות.
- **טווח תאריכים חלקי:** לוודא שהטווח המבוקש בתוך החלון המותר של הבנק; חיבורים ראשוניים עשויים למשוך היסטוריה מלאה בהדרגה על פני כמה מחזורי סנכרון.

## 10. דיווח תקלה לתמיכה

**למשתמשי dashboard:**
1. כניסה ל-`https://dashboard.open-finance.ai`
2. לחיצה על בועת הצ'אט הצפה בתחתית העמוד
3. "Create a Request" → בחירה בין "Bug" 🐞 או "Feature Request" 😇
4. לצרף: מיקום מדויק, פעולה שבוצעה, מכשיר/דפדפן, האם התקלה חוזרת על עצמה

**ללא גישה ל-dashboard:** מייל לכתובת הייעודית של Open Finance, עם נושא: "פתיחת דיווח תקלה/בקשת בדיקה עבור ארגון {שם לקוח}", ובגוף המייל: שם מלא, שם ארגון, קטגוריית בקשה ופרטים, מזהה הסכם/עסקה/בקשת אשראי, ת.ז. לאימות, תיאור מפורט, דרך יצירת קשר.

מעקב אחר פניות: אזור "Requests" ב-dashboard, או פורטל הטיקטים הייעודי.

## 11. תיעוד API מלא (docs.open-finance.ai) — נאסף 2026-07-10

- **אינדקס machine-readable:** `https://docs.open-finance.ai/llms.txt` — כל העמודים כ-Markdown + OpenAPI. כל עמוד reference זמין כ-`<url>.md` גולמי.
- **עותקים מקומיים (OpenAPI מלא):** [docs/open_finance_api_reference/](open_finance_api_reference/) — 15 endpoints + 8 מדריכים שנשמרו בריפו לעיון offline.

### 11.1 Base URLs
- אימות: `https://api.open-finance.ai/oauth/token`
- API: `https://api.open-finance.ai/v2` (server template: `https://{API_PREFIX}.open-finance.ai/v2`, ברירת מחדל `api`)

### 11.2 טוקן — סכמה מדויקת
- `POST /oauth/token` — body: `{userId, clientId, clientSecret}` (כולם חובה)
- תגובה 200: `{accessToken, tokenType, expiresIn}` — **`expiresIn` במילישניות**

### 11.3 אובייקט Connection — סטטוסים מלאים (enum מה-OpenAPI)
`ACTIVE`, `CONNECTED`, `FETCHING`, `ERROR`, `FETCHING_ERROR`, `INACTIVE`, `COMPLETED`, `CREDENTIALS_ERROR`, `REJECTED`, `PARTIALLY_AUTHORIZED`, `UNKNOWN`, `TERMINATED_BY_USER`, `EXPIRED`, `REVOKED`, `REPLACED`, `SUSPENDED_BY_PROVIDER`

משמעויות עיקריות: `ACTIVE` = חיבור מתמשך עם משיכה יומית; `COMPLETED` = חיבור חד-פעמי שסיים למשוך; `PARTIALLY_AUTHORIZED` = ממתין לחתימת שותפים (5 ימים → `EXPIRED`); `REPLACED` = חיבור חדש עם אותו psuId+provider הפך ACTIVE.

שדות חשובים על connection: `id`, `userId`, `psuId`, `psuCorporateId`, `providerId`, `status`, `mode` (PSD2/PLAID), `expiryDate`, מונים (`accounts`, `cards`, `savings`, `loans`, `securities`, `transactions`), `lastFetchedDataDate`, `startDate`, `error`, `refreshSettings`.

### 11.4 אובייקט Account — שדות עיקריים
`id`, `accountNumber`, `parsedAccount` (`{bank, branch, number}`), `accountType`, `currency`, `ownerInfo` (`{nationalId, fullName}`), `accountName`, `balances[]` (עם `balanceType` — ר' סעיף 3.1), `creditLimit`, `cardDueDate`, `creditStatus` (`deleted`/`enabled`/`disabled`), `usage`, `transactions` (מונה), `securityPositions[]`, `interst[]` (כך במקור — typo של הספק), `relatedDates`.

### 11.5 אובייקט Transaction — שדות עיקריים
- זיהוי: `id`, `SK` (מזהה לעדכון — `PATCH /data/transactions/{sk}`), `connectionId`, `accountId`, `providerId`, `transactionProviderIdentifier`, `entryReference`, `endToEndId`
- סכום: `amount.originalAmount{amount,currency}` + `amount.chargedAmount{amount,currency}` (חיוב מט"ח: שניהם רלוונטיים), `markupFee`
- תיאור: `description{description, additionalInfo}`, `merchantName`, `merchantAddress`, `details`
- סיווג: `category{main,sub}` + `changedCategory` (אחרי עדכון ידני), `classification{type,source}`, `labels[]`, `categoryCode`
- תאריכים: `date{valueDate, bookingDate, transactionDate}`
- מצב: `status`, `type` (BANK/CARD), `isDuplicate`, `installments{number,total}`, `balancePerEndDay`, `isInvoiced`
- צדדים: `creditorAccount` / `debtorAccount` (`{iban, bban, maskedPan, ...}`)
- ני"ע: `securityDetails` (ISIN, מחירים, עמלות — לחשבונות השקעה)

### 11.6 Endpoints מרכזיים (מלא ב-llms.txt; עותקים ב-open_finance_api_reference/)
| Endpoint | הערות |
|---|---|
| `POST /oauth/token` | טוקן פר-user |
| `POST /v2/connections` / `GET /v2/connections` | יצירה/רשימה |
| `GET/DELETE /v2/connections/{connectionId}` | פרטים/מחיקה |
| `GET /v2/connections/{userId}/refresh` | **רענון כל החיבורים של user — קריאה יזומה לבנק, צורכת קרדיטים** |
| `GET /v2/connections/refresh/{connectionId}` | רענון חיבור בודד |
| `GET /v2/data/accounts` / `GET /v2/data/accounts/{accountId}` | חשבונות |
| `GET /v2/data/transactions` / `GET /v2/data/transactions/{sk}` | תנועות |
| `PATCH /v2/data/transactions/{sk}` | עדכון תנועה (קטגוריה וכו') |
| `GET /v2/data/transaction-categories` | טקסונומיית קטגוריות (scope `read:categories`) |
| `GET /v2/data/monthly-report/{userId}` | דוח בנקאות פתוחה חודשי |
| `GET /v2/data/extended-securities` | פוזיציות ני"ע |
| `GET /v2/providers`, `GET /v2/bank-branches` | מטא-דאטה |
| `POST /v2/account-number-verification` | בדיקת חשבון מוגבל |
| תשלומים: `POST /v2/payments`, `GET /v2/payments/{id}/status`, `DELETE /v2/payments/{id}` (ביטול), `POST /v2/payments/{id}/refund`, mandates (`/v2/mandates`) | ר' סעיף 4 |
| Decision/Financial-report/Private-scoring | `POST /v2/financial-report/{customerId}` → poll `GET /v2/financial-report/{jobId}`; דומה ל-decision ו-private-scoring |

### 11.7 קטגוריות תנועה (טקסונומיה דו-רמתית)
- מבנה: `category: {main, sub}`; טקסונומיות נפרדות להוצאות והכנסות.
- **הוצאות (9 ראשיות):** `HOUSEHOLD_&_SERVICES`, `HOME_IMPROVEMENTS`, `FOOD_&_DRINKS`, `TRANSPORT`, `SHOPPING`, `LEISURE`, `HEALTH_&_BEAUTY`, `OTHER` (כולל `CASH_WITHDRAWALS`, `BUSINESS_EXPENSES`), `FINANCE` (כולל `INTEREST_RATES`, `FEES`, `LOANS`, `SAVINGS`, `CAPITAL_MARKET`)
- **הכנסות (6 ראשיות):** `SALARY`, `PENSION`, `REIMBURSEMENTS`, `BENEFITS`, `FINANCE`, `OTHER`
- שליפה: `GET /v2/data/transaction-categories`

### 11.8 Webhooks
- הגדרה ב-dashboard (client settings → update mode → webhook URLs להצלחה/כשל); נשלחים כ-HTTPS POST.
- **סוגי אירועים:** (1) Connection status change — payload עם connectionId/status/userId/orgId/bank/expiry/accounts/error; ברגע `COMPLETED`/`ACTIVE` אפשר לקרוא accounts. (2) Payment status change. (3) Session data update.
- **חשוב ל-Workstream B:** webhooks על שינוי סטטוס connection מייתרים polling תדיר.

### 11.9 Sandbox
- ספקים: `open-finance-sandbox` (העשיר ביותר, 12+ חשבונות), `mizrahi-sandbox`, `leumi-sandbox`, `beinleumi-sandbox` (כולל מולטי-מטבע), `discount-sandbox` (חלקי), `yahav-sandbox`.
- הפעלה: `includeFakeProviders: true` ביצירת connection (להסיר בפרודקשן!).
- PSU IDs לתרחישים: `043510023` (ACTIVE), `050299338` (REJECTED), `316159011` (ERROR); mizrahi: psu `245938880`, user `102718538`, pass `1`, OTP `1`.
- `PATCH /v2/payments/sandbox/{paymentId}` — שינוי סטטוס תשלום sandbox ידני.
- **שימוש מומלץ ל-Rezef:** בדיקות connector ו-E2E בלי לגעת בחשבון האמיתי ובלי לצרוך קרדיטים של הפיילוט.

## 11.10 תצפיות חיות מהחשבון האמיתי (2026-07-10, read-only, ללא persistence)

- **WAF:** קריאות `urllib` (Python-urllib UA) נחסמות ב-403 עוד לפני האימות; `httpx` (הקליינט של Rezef) עובר. לזכור בכל סקריפט בדיקה.
- **חיבורים:** 5 סה"כ — 1 ACTIVE (hapoalim, נמשך היום, תוקף עד 2029-07-09, 1,884 תנועות) + **4** EXPIRED (התכנית העריכה 2).
- **חשבונות (6):** CHECKING (274 תנועות), CARD מסטרקארד קורפורייט זהב (1,610 תנועות), SAVINGS פר"י (status=blocked), 3 שורות LOAN (כולל מסגרת חח"ד — מסגרת אשראי מיוצגת כ-LOAN).
- **איכות נתונים:** ה-CHECKING חוזר עם `currency: "ILY"` (typo של הספק/בנק) — לנרמל ל-ILS בצד Rezef.
- **כיוון סכומים אומת:** `chargedAmount.amount` חיובי = זיכוי/כניסה, שלילי = חיוב/יציאה.
- **`type` בתנועות בפועל:** `CHECKING` / `CARD` (מרכז העזרה תיאר `BANK`/`CARD` — הערך בפועל שונה!).
- **סליקת כרטיס ניתנת לזיהוי:** חיוב ישראכרט בעו"ש מגיע עם `category: INCOMES_EXPENSES / CREDIT_CARD_CHECKING` — עוגן מרכזי למניעת כפל-ספירה (RSF-086/087).
- **`status` תנועה:** `BOOKED` / `PENDING` (חיוב הישראכרט העתידי הופיע כ-PENDING).

## 12. השלכות על Rezef

- **RSF-005 (חסום):** `OPEN_FINANCE_USER_ID` הוא כתובת המייל שאיתה נרשם המשתמש ל-Financy — לאמת ולהגדיר לפני כל ניסיון קריאה.
- **RSF-045 (חלון פיילוט 7 ימים):** תואם למגבלות ה-API (`dateFrom`/`dateTo`, `limit` עד 2000 לתנועות).
- **RSF-046 (סימן חיוב/זיכוי):** יש לאמת מול `balanceType` המתאים לסוג החשבון (סעיף 3.1) — לא כל סוגי היתרה רלוונטיים לכל סוג חשבון.
- **RSF-086/087 (הפרדת עסקת כרטיס מסליקת כרטיס):** ל-CARD יש `interimBooked`/`interimAvailable` נפרדים מ-`closingBooked` של העו"ש — יש לתכנן את שרשור התאמת הבנק סביב זה.
- **הגנת נפח קריאות (Workstream B):** אין endpoint ל-webhooks push מתועד במאמרים אלו מעבר ל-`callbackInformation` ביצירת חיבור — כדאי לבדוק את `docs.open-finance.ai` לפרטי webhook לפני מימוש polling תדיר.
- **תוקף הסכמה (סעיף 8):** יש לתכנן תזכורת חידוש הסכמה לפני פקיעה, כדי למנוע "הקפאת" נתונים ללא אזהרה ברורה למשתמש.
- כל התיעוד המלא והאינטראקטיבי נמצא ב-`docs.open-finance.ai` (docs.open-finance.ai/docs/access-tokens, /docs/iframe-support, /docs/bulk-payment-initialization, /docs/periodic-payment-initialization) — לא נסרק במלואו כאן; מומלץ לבדוק שם prior למימוש בפועל.
