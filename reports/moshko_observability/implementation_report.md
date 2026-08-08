# דוח יישום — observability למושקו ודחיפה יזומה ל־WhatsApp

תאריך: 2026-08-01  
מצב: הושלם ונבדק אופליין; לא נפרס ולא בוצעה אף קריאת רשת/ספק/פרוד.

## מה נבנה

### שימוש LLM ועלות

- נוספה טבלת `llm_usage` עם tenant/user/session, ספק, מודל, input/output tokens,
  cache-read/cache-creation tokens, purpose (`chat`/`vision`/`ocr`), עלות וזמן.
- כל קריאת Anthropic בלולאת הצ׳אט נרשמת, לרבות turns ביניים שמפעילים כלים.
- נתיבי הראייה של Anthropic ו־OpenAI רושמים usage כאשר ה־SDK מחזיר אותו; מסלול
  OCR רקע מסומן `ocr`, וקליטת קבלה בשיחה מסומנת `vision`.
- התמחור נקרא רק מ־`LLM_PRICING_JSON`. ברירת המחדל היא `{}`; מודל לא מוכר,
  JSON לא תקין או מחיר cache חסר כאשר היו cache tokens מחזירים `cost_usd=NULL`.
- הרישום משתמש ב־nested transaction ונלכד בשתי שכבות best-effort. כשל בטבלת
  הטלמטריה אינו מפיל או מבטל שיחה.

מבנה הקונפיג הצפוי (דוגמה צורנית בלבד, ללא מחירים מומצאים):

```json
{
  "exact-model-id": {
    "input_per_million_usd": "<owner-verified-price>",
    "output_per_million_usd": "<owner-verified-price>",
    "cache_read_per_million_usd": "<owner-verified-price>",
    "cache_creation_per_million_usd": "<owner-verified-price>"
  }
}
```

### קריאות כלים ופרטיות

- נוספה טבלת `moshko_tool_calls` לכל כלי קריאה שבוצע אוטומטית ולכל כלי כתיבה
  שבוצע רק לאחר אישור מפורש.
- נשמרים: org/user/session/message, שם כלי, יעד, ארגומנטים מחוטאים, הצלחה,
  שגיאה, משך במילישניות וגודל תוצאה בבייטים — לא תוכן התוצאה.
- המיפוי ל־`sumit` / `open_finance` / `rezef_db` / `local` נבדק מול wrappers
  בפועל. בפרט, `query_bank_transactions` הוא `rezef_db`; `connect_bank_account`
  הוא `open_finance`; ו־`run_client_sync` משתמש ב־source שבחר ה־connector.
- החיטוי רקורסיבי וממסך סיסמאות, tokens, API keys, authorization, IBAN,
  מספרי חשבון/בנק/סניף, CVV ומספרי כרטיס — גם בתוך טקסט חופשי.
- כשל כלי נרשם ומוחזר למודל כתוצאת שגיאה במקום להעלים את האירוע; כשל ברישום
  הלוג עצמו נשאר best-effort ואינו מפיל את השיחה.

### API ומסך אדמין

- נוספו ראוטים תחת `/api/admin/moshko/`, כולם עם `get_super_admin`:
  - `GET /conversations`
  - `GET /conversations/{session_id}`
  - `GET /tool-calls`
  - `GET /usage`
- קיימים pagination וסינון לפי תאריכים, org, user וערוץ; tool calls מסוננים גם
  לפי יעד והצלחה; usage מקובץ לפי יום/ארגון/מודל.
- אגרגציית עלות נשארת `NULL` אם אפילו קריאה אחת בקבוצה אינה מתומחרת, כדי לא
  להציג סכום חלקי כאילו הוא מלא.
- session זהה ביותר מ־tenant/user אחד מחזיר 409 עד שהאדמין מספק scope מפורש,
  ולכן תמלולים משני ארגונים אינם מתערבבים.
- נוסף מסך RTL `ניטור מושקו`: סיכומים, טוקנים/עלות יומית, רשימת שיחות ותמלול,
  קריאות כלים וארגומנטים מחוטאים. הקוד טוען את שלושת מקורות הנתונים במקביל.

### דחיפה יזומה ל־WhatsApp

- `channel_notifier` מנתב לפי `ChannelIdentity.provider` ומוודא קונפיג נפרד
  ל־Telegram ול־WhatsApp. ברירת המחדל דוחפת לכל הזהויות הזכאיות בארגון.
- `push_enabled=False`, זהות לא מאומתת או מבוטלת ממשיכים להיחסם.
- נוסף `ChannelIdentity.last_inbound_at`, שמתעד כל inbound מאומת ב־WhatsApp,
  גם media, interactive וסוג תוכן שהמערכת אינה מעבדת.
- בתוך 24 שעות נשלח free-form דרך `WhatsAppGateway.send_text`.
- מחוץ לחלון: אם `WHATSAPP_PUSH_TEMPLATE_NAME` לא מוגדר מוחזר
  `status=outside_service_window` ולא מתבצע ניסיון שליחה. אם הוא מוגדר,
  נשלחת תבנית בשפה `WHATSAPP_PUSH_TEMPLATE_LANGUAGE` עם הטקסט כמשתנה body יחיד.
- cron ההתראות הישן הפסיק לסנן Telegram בלבד, ולכן ארגון WhatsApp־בלבד מגיע
  כעת בפועל ל־notifier הרב־ערוצי.

### סכימה וחוזי מערכת

- מיגרציה additive/idempotent: `d6e7f8a9b0c1_add_moshko_observability.py`.
- היא מוסיפה שתי טבלאות ואת `channel_identities.last_inbound_at`; אין backfill,
  אין DML עסקי ואין קריאת ספק.
- `docs/rezef_capabilities.json` עודכן, אך היכולת נשארה `gated`: אין הוכחת
  deploy, ספק חי או תבנית Meta מאושרת.
- במהלך הריצה המלאה נחשף באג קיים ביום הראשון בחודש: השוואת `DateTime <= date`
  השמיטה את יום הסיום ב־SQLite. שלושת מקורות הדוחות הרלוונטיים תוקנו לטווח
  חצי־פתוח (`< end_date + 1 day`) ונבדקו ממוקד.

## בדיקות

- TDD אדום ראשון: collection נכשל לפני קיום `LLMUsage`/`MoshkoToolCall`.
- בדיקות ממוקדות לפני suite: 70 עברו.
- build frontend: עבר (`tsc && vite build`, ‏2,430 modules transformed).
- suite מלאה יחידה: 1,677 נאספו; 1,661 עברו ו־16 נכשלו.
- לאחר תיקון 16 הכשלים, כל הטסטים שנכשלו עברו בריצות ממוקדות. לא בוצעה suite
  מלאה שנייה, בהתאם להוראה להריץ אותה פעם אחת בלבד.
- אזהרות build לא חוסמות: browserslist מיושן ו־chunks קיימים מעל 500KB.
- אזהרות pytest הן בעיקר `datetime.utcnow()`/Pydantic קיימות; לא בוצע sweep
  timezone גורף בהתאם למדיניות הריפו.

## שאלות פתוחות לבעלים

1. לספק מחירים מאומתים לכל model id פעיל ול־cache ב־`LLM_PRICING_JSON`.
   עד אז העלות מוצגת `NULL` בכנות.
2. האם קיימת תבנית Meta מאושרת עם משתנה body יחיד? אם כן, להגדיר את שמה ושפתה.
   עד אז pushes מחוץ ל־24 שעות יחזרו `outside_service_window`.
3. לקבוע מדיניות retention לתמלולים, usage ו־tool-call logs. לא נוספה מחיקה
   אוטומטית ללא החלטת בעלים.
4. לאשר בנפרד deploy ומיגרציה לפי `docs/GATE0_DEPLOYMENT_RUNBOOK.md`; לא בוצעה
   שום פעולה על פרוד במשימה זו.
5. לאחר deploy מאושר: לבצע smoke חי מבוקר לכל ערוץ ולוודא שהתבנית המאושרת
   תואמת בדיוק למספר המשתנים שמוגדר בקוד.
