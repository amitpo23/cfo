## פסיקה כללית: בעיות מהותיות

הטווח אכן כולל 14 commits: ‏75 קבצים, ‎7,281+‎/‎1,458-‎. `git diff --check` נקי. השינויים משפרים משמעותית fail-closed, בידוד ארגוני ו־exactly-once, אך נמצאו פערי P0 בשערי העלות, בחישובי המזומן ובאישור פעולות מושקו.

לא בוצעו שינויים או קריאות חיות. הטסטים הממוקדים לא התחילו משום שסביבת הביקורת read-only ואינה מאפשרת יצירת temp/SQLite; לכן אין כאן אישור runtime חדש מעבר לבסיס המתועד.

## ממצאים לפי תחום

### 1. שערי עלות — בעיות מהותיות

- המונים האטומיים עצמם בנויים היטב: `UPSERT ... WHERE used < limit` מונע race בין instances, וכל חלונות הבקשה נתבעים באותה טרנזקציה ([sumit_request_budget.py:154](/Users/mymac/coding/cfo/src/cfo/services/sumit_request_budget.py:154), [sumit_request_budget.py:238](/Users/mymac/coding/cfo/src/cfo/services/sumit_request_budget.py:238)).

- קיים נתק מסוכן בין מדידת הספק למונה המקומי. מדידה טרייה עם `49/50` עוברת בכל קריאה כי `remaining > 0`, ואז נתבע מונה חודשי נפרד שמתחיל ב־0 ומאפשר עד 90 פעולות. המונה אינו מאותחל מ־`snapshot.used` ואינו מוגבל ל־`snapshot.remaining` ([sumit_quota.py:176](/Users/mymac/coding/cfo/src/cfo/services/sumit_quota.py:176), [sumit_quota.py:192](/Users/mymac/coding/cfo/src/cfo/services/sumit_quota.py:192), [config.py:80](/Users/mymac/coding/cfo/src/cfo/config.py:80)). זה אינו race ב־DB, אלא פרצה לוגית בין שני מקורות אמת.

- שער הפעולות בתשלום הוא allowlist ידני ([sumit_integration.py:102](/Users/mymac/coding/cfo/src/cfo/integrations/sumit_integration.py:102), [sumit_integration.py:308](/Users/mymac/coding/cfo/src/cfo/integrations/sumit_integration.py:308)). נתיבים כגון יצירת לקוח, יצירת batch, ביטול מסמך והעברתו לספרים אינם ברשימה ([sumit_integration.py:882](/Users/mymac/coding/cfo/src/cfo/integrations/sumit_integration.py:882), [sumit_integration.py:1188](/Users/mymac/coding/cfo/src/cfo/integrations/sumit_integration.py:1188), [sumit_integration.py:1282](/Users/mymac/coding/cfo/src/cfo/integrations/sumit_integration.py:1282)). זאת בסתירה לחוזה המקומי שלפיו כל קריאת API צורכת פעולה ([SUMIT_KNOWLEDGE_BASE.md:53](/Users/mymac/coding/cfo/docs/SUMIT_KNOWLEDGE_BASE.md:53)). נתיבים אלה כפופים רק לתקרת 2,000 הבקשות הכללית, לא ליתרת הפעולות שנמדדה.

### 2. אבטחה — תקין עם הסתייגויות מהותיות

- החלקים החיוביים: טוקן האיפוס אקראי ונשמר רק כ־SHA-256; לכל JWT חדש יש `jti`; וה־denylist נבדק בכל בקשה ([models.py:202](/Users/mymac/coding/cfo/src/cfo/models.py:202), [auth.py:44](/Users/mymac/coding/cfo/src/cfo/auth.py:44), [dependencies.py:83](/Users/mymac/coding/cfo/src/cfo/api/dependencies.py:83)).

- מונה כשלי login הוא read-modify-write רגיל. בקשות מקבילות יכולות לקרוא אותו ערך ולדרוס זו את זו, ולכן לעקוף בפועל את סף חמשת הניסיונות ([admin.py:602](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:602), [admin.py:617](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:617)). אין גם מגבלת IP/מכשיר, והנעילה החשבונית מאפשרת DoS על כתובת ידועה.

- החד־פעמיות של reset אינה אטומית: שתי בקשות עם אותו token יכולות לעבור את בדיקת `used_at` לפני שאחת מהן עושה commit ([admin.py:794](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:794), [admin.py:806](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:806)).

- שינוי או איפוס סיסמה אינם מבטלים JWT קיימים, התקפים עד 24 שעות ([auth.py:17](/Users/mymac/coding/cfo/src/cfo/auth.py:17), [admin.py:704](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:704), [admin.py:778](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:778)). במקרה של השתלטות חשבון, איפוס סיסמה אינו מוציא את התוקף.

- קישור האיפוס נבנה מ־`request.base_url` ולא מ־`settings.app_url`; ללא נרמול Host בשכבת Vercel זה מאפשר reset-link poisoning ([admin.py:759](/Users/mymac/coding/cfo/src/cfo/api/routes/admin.py:759), [config.py:24](/Users/mymac/coding/cfo/src/cfo/config.py:24)).

### 3. שירותים חיים — בעיות מהותיות

- `_live_cash_balance` מחבר כל `BANK` וגם כל `ASSET`, ללא סינון `source` או טריות ([live_cash_flow_service.py:341](/Users/mymac/coding/cfo/src/cfo/services/live_cash_flow_service.py:341)). לכן חסכונות, נכסים ידניים ואף חשבון שסווג כברירת־מחדל כ־ASSET עלולים להיחשב מזומן. הדשבורד החדש כבר משתמש בהגדרה הנכונה — Open Finance ו־BANK בלבד ([dashboard_service.py:109](/Users/mymac/coding/cfo/src/cfo/services/dashboard_service.py:109)).

- שדות `balance_as_of`, `observed_at` ו־`synced_at` קיימים אך אינם נבדקים ([models.py:562](/Users/mymac/coding/cfo/src/cfo/models.py:562)). יתרה ישנה או ברירת־מחדל 0 מוצגת כבסיס חי.

- `burn_rate` מחזיר `current_balance=0` ו־`runway_months=999` כשאין יתרה או שאין burn חיובי, במקום `null + reason` ([live_cash_flow_service.py:175](/Users/mymac/coding/cfo/src/cfo/services/live_cash_flow_service.py:175), [live_cash_flow_service.py:182](/Users/mymac/coding/cfo/src/cfo/services/live_cash_flow_service.py:182)). זו הפרת honest-null מפורשת.

- “הוצאות חוזרות” הן למעשה כל ההוצאות התקינות ב־90 הימים האחרונים, כולל חד־פעמיות, והממוצע מחולק רק בחודשים שבהם נמצאו נתונים ([live_forecast_service.py:264](/Users/mymac/coding/cfo/src/cfo/services/live_forecast_service.py:264), [live_forecast_service.py:293](/Users/mymac/coding/cfo/src/cfo/services/live_forecast_service.py:293)). בנוסף, 100% מה־AR/AP שבפיגור משובץ לחודש הנוכחי כהנחת בסיס ([live_forecast_service.py:198](/Users/mymac/coding/cfo/src/cfo/services/live_forecast_service.py:198)). שתיהן הנחות תחזית שלא מסומנות כתרחיש.

- בדיקת מסגרת האשראי משווה מסגרות של חשבונות BANK ליתרה ארגונית הכוללת ASSET; בעקבות זאת `ok/warning/breach` עלולים להיות שגויים ([credit_line_service.py:60](/Users/mymac/coding/cfo/src/cfo/services/credit_line_service.py:60), [credit_line_service.py:88](/Users/mymac/coding/cfo/src/cfo/services/credit_line_service.py:88)).

### 4. מושקו — בעיות מהותיות

- בידוד השיחות לפי org+user תקין; write אינו מבוצע מתוך קריאת המודל; ובאישור יש compare-and-set אטומי לפני side effect, כולל מצב `unknown` במקום retry מסוכן ([ai_chat_service.py:465](/Users/mymac/coding/cfo/src/cfo/services/ai_chat_service.py:465), [ai_chat_service.py:623](/Users/mymac/coding/cfo/src/cfo/services/ai_chat_service.py:623)).

- חוזה רצף דורש שלוש בדיקות מדיניות וסמכות חתימה נפרדת לפעולה בלתי־הפיכה ([REZEF_OPERATING_SYSTEM.md:123](/Users/mymac/coding/cfo/docs/REZEF_OPERATING_SYSTEM.md:123)). בפועל קיימת בדיקה בהצעה וב־confirm בלבד, ופעולות כמו `billing.charge`, הנפקת/ביטול מסמך ותיוק הוצאה מוגדרות כ־WRITE רגיל ומוענקות כברירת־מחדל ל־ADMIN/ACCOUNTANT ([policy_engine.py:22](/Users/mymac/coding/cfo/src/cfo/services/policy_engine.py:22), [policy_engine.py:33](/Users/mymac/coding/cfo/src/cfo/services/policy_engine.py:33), [policy_engine.py:59](/Users/mymac/coding/cfo/src/cfo/services/policy_engine.py:59)). אישור עצמי יחיד יכול אפוא להפעיל פעולה בלתי־הפיכה ללא מורשה חתימה נפרד.

- ההצעה שומרת שם כלי וקלט, אך לא גרסת מימוש או hash. deploy בין הצעה לאישור עשוי לשנות את משמעות הפעולה שתבוצע ([ai_chat_service.py:492](/Users/mymac/coding/cfo/src/cfo/services/ai_chat_service.py:492), [ai_chat_service.py:606](/Users/mymac/coding/cfo/src/cfo/services/ai_chat_service.py:606)).

- רגרסיית מושקו בודקת רק שהזיכרון הוזרק ושהתשובה אינה “מוותרת”; תשובה שגויה או הזויה יכולה לעבור ([moshko_regression.py:62](/Users/mymac/coding/cfo/src/cfo/services/moshko_regression.py:62), [moshko_regression.py:83](/Users/mymac/coding/cfo/src/cfo/services/moshko_regression.py:83)). מחיקת gap כפול מסוננת לפי `session_id` בלבד, בלי org/user ([moshko_regression.py:78](/Users/mymac/coding/cfo/src/cfo/services/moshko_regression.py:78)).

### 5. Crons — תקין חלקית; לא כולם מגודרי עלות

- כל שמונת ה־crons שב־Vercel מוגנים ב־`CRON_SECRET`, ו־SUMIT משתמש ב־claim אטומי פר מפתח ובשער הרשת המרכזי ([vercel.json:56](/Users/mymac/coding/cfo/vercel.json:56), [cron.py:57](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:57), [cron.py:212](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:212)).

- Open Finance מוגדר כ“סנכרון מוצלח אחד” ולא “ניסיון אחד”: השער קורא רק `last_success_at` ([cron.py:238](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:238), [cron.py:505](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:505)). כשל ולאחריו retry של Vercel יכול לבצע שוב קריאות ספק. ה־advisory lock מונע חפיפה, אך לא ניסיון נוסף אחרי שהריצה הכושלת הסתיימה.

- `collection-reminders` שולח את כל ה־planned ללא batch cap או claim להרצה; SMS עובר דרך SUMIT, אך חשוף לפרצת המכסה מתחום 1, ומייל אינו מוגבל ([cron.py:699](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:699), [cron.py:727](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:727)). גם דחיפות WhatsApp/Telegram ב־channel-alerts/roster-health אינן תחת תקציב עמיד ([cron.py:854](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:854), [cron.py:951](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:951)).

## המלצות שיפור מתועדפות

### P0 — לפני הכול

- לאחד את snapshot המכסה והמונה המקומי ל־ledger אטומי אחד, המאותחל מ־`used` ומוגבל ל־`min(provider_remaining, internal_remaining)`. לסווג כל endpoint כ־paid/free במניפסט קנוני, עם ברירת־מחדל paid. מחיר אי־ביצוע: חיובי SUMIT וחסימת לקוח למרות “שער ירוק”.

- לתקן את חוזה המזומן: Open Finance + BANK בלבד, דרישת `balance_as_of` טרי, ו־`null` במקום 0/999. מחיר אי־ביצוע: החלטות מסגרת, runway ותחזית על בסיס נכסים שאינם מזומן או יתרות ישנות.

- להפריד במושקו בין proposer, approver ומורשה חתימה; לבצע policy check בשלושת השלבים ולחתום על מעטפת פעולה בלתי־משתנה. מחיר אי־ביצוע: חיוב, ביטול מסמך או writeback בלתי־הפיך באישור עצמי יחיד.

- להפוך login/reset לאטומיים, להוסיף rate limit שאינו נעילת־חשבון בלבד, ולבטל את כל ה־sessions בעת שינוי/איפוס סיסמה באמצעות `token_version`/security stamp. לבנות reset URL מ־`settings.app_url`. מחיר אי־ביצוע: עקיפת lockout, שימוש כפול בטוקן והמשך גישה של session גנוב.

- להוסיף ל־Open Finance ולכל cron חיצוני claim של “ניסיון”, cooldown אחרי כשל ו־batch ceiling. מחיר אי־ביצוע: retries שורפים מכסה ועלות גם בלי sync מוצלח.

### P1 — קרוב

- להוסיף CI מול Postgres אמיתי לטסטי concurrency של budgets, login, reset ו־Moshko CAS. ה־SQLite היחיד משותף לכל הסוויטה וה־fixtures המרכזיים הם session-scoped ([conftest.py:7](/Users/mymac/coding/cfo/tests/conftest.py:7), [conftest.py:120](/Users/mymac/coding/cfo/tests/conftest.py:120)). מחיר אי־ביצוע: races ותלויות־סדר שאינן נחשפות לפני פרוד.

- להעביר crons מריצת HTTP סדרתית על כל הארגונים לעבודות עמידות פר־ארגון עם lease, checkpoint ו־resume. כיום הלולאה סדרתית ומוגבלת ל־300 שניות ([cron.py:96](/Users/mymac/coding/cfo/src/cfo/api/routes/cron.py:96), [vercel.json:7](/Users/mymac/coding/cfo/vercel.json:7)). מחיר אי־ביצוע: timeout חלקי וסקייל שאינו ליניארי במספר הלקוחות.

- לפרק bounded contexts גדולים: כיום 146 קבצי שירות, `ai_chat_tools.py` ‏3,933 שורות, `sumit_integration.py` ‏3,219, `admin.py` ‏3,052 ו־`models.py` ‏2,550. מחיר אי־ביצוע: ביקורות חלקיות, coupling גבוה ורגרסיות בשינויים מקומיים.

- לחזק את רגרסיית מושקו בבדיקת עובדות/ציפייה מובנית, scope מלא ומגבלת טוקנים. מחיר אי־ביצוע: dashboard ירוק שאינו מעיד על תשובה נכונה.

### P2 — כשנוח

- להמיר את 114 שימושי `datetime.utcnow()` ב־41 קבצים, מודול־אחר־מודול ובהתאם לחוזה timezone של העמודות. מחיר אי־ביצוע: אזהרות מצטברות ושבירה עתידית; המרה גורפת מסוכנת בגלל ערבוב naive/aware.

- לשמור `Decimal` עד גבול ה־API ולהציג במפורש הנחות ותרחישים בתחזית. מחיר אי־ביצוע: שגיאות עיגול והצגת הנחות כעובדות.

- להשתמש ב־`npm ci` בפריסת Vercel במקום `npm install`. מחיר אי־ביצוע: builds שאינם משתחזרים במדויק מה־lockfile.

Codex session ID: 01a02db9-549e-7283-8ee8-21efb1282cf7
Resume in Codex: codex resume 01a02db9-549e-7283-8ee8-21efb1282cf7
