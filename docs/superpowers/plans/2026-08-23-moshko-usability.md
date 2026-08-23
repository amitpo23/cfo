# השמשת מושקו 23/08/2026 — UI + Backend + השלמת WhatsApp

**הנחיית בעלים:** "אני רוצה להשמיש את מושקו גם ב-UI וגם במערכת הבקאנד ולשפר
אותו כולל השלמת החיבור לוואטסאפ". מודל העבודה: פייבל מתכנן, סונט מבצע,
קודקס בודק ומאשר.

**בסיס:** דוח פערי מושקו/וואטסאפ 23/08 (חקירה מאומתת-קוד, 15 פערים
מתועדפים). ‏WhatsApp בשל בקוד; הפערים הכואבים: הצ'אט הצף שבור לפעולות
כתיבה, כישלונות Meta נבלעים, אין caching, אין ניהול שיחות.

## אילוצים גלובליים

1. TDD; סוויטה מלאה ירוקה בסוף כל משימה; טסטים לא פונים לרשת.
2. משמעת עלויות: אפס קריאות ספק חדשות; אסור לגעת בשערי המכסה או
   ב-test_sumit_rate_limit_hard_rule.py.
3. honest-null; בידוד ארגוני; שער האישור לפעולות write נשאר בדיוק כמו שהוא.
4. ‏Frontend: ‏build+lint ירוקים; עברית RTL; דפוסי הקומפוננטות הקיימים.
5. שימוש חוזר במנגנונים קיימים — אין מסלולים מקבילים (הצ'אט הצף מאמץ את
   דפוסי ChatAssistant, לא ממציא).
6. ‏commit פר-משימה על main; בלי push עד אישור קודקס.

## משימה 1 — הצ'אט הצף מפסיק להיות מבוי סתום

- `MoshkoSystemChat.tsx` מטפל ב-`pending_action` מהתשובה: כרטיס אישור
  (שם כלי, ארגומנטים, כפתורי אשר/דחה) שקורא `POST /ai/chat/confirm` —
  באותו דפוס בדיוק כמו `ChatAssistant.tsx:287-316`. כולל 5 מצבי
  `action_status` (גם `unknown`).
- טעינת היסטוריית ה-session מה-DB בפתיחה (ה-endpoint הקיים שמשרת את
  ChatAssistant; אם אין — להוסיף route קריאה ל-session), כך שרענון דף לא
  מוחק את השיחה. ה-invalidateQueries הקיים מפסיק להיות no-op.
- בורר פרסונה (אותן 3 פרסונות, אותו localStorage key כמו ChatAssistant).
- טסטים: ‏frontend build+lint; ‏backend — אם נוסף route, טסט org-isolation
  עליו.

## משימה 2 — WhatsApp: כישלונות מפסיקים להיבלע + UI קישור

- `whatsapp_gateway.py:_post_messages` — בדיקת סטטוס תשובה (`raise_for_status`
  או בדיקה מפורשת של status+body של Meta), חריגה ברורה, וטסט לנתיב הכישלון.
- `channel_notifier.py` — ‏`sent`/`last_push_at` מתעדכנים רק על שליחה
  שהצליחה באמת; כשל נספר ונרשם (המונים מפסיקים לשקר). טסט.
- `SettingsPage.tsx` — סקציית קישור WhatsApp לצד טלגרם: הסבר מסלול
  אימות-המייל, והצגת מספר הבוט מ-config כשמוגדר (וכשריק — הודעה כנה
  "הערוץ טרם הופעל על ידי המשרד").
- לא בתחום: טיפול ב-statuses (דילוג מכוון קיים), פעולות בעלים (env/Meta).

## משימה 3 — יעילות הליבה: caching, אורך תשובה, מודל קונפיגורבילי

- ‏prompt caching ב-`ai_chat_service.py`: ‏`cache_control` על בלוק הכלים
  ועל ה-system prompt (הם קבועים בתוך שיחה) — חיסכון העלות/לטנטיות הגדול
  במערכת (106 סכמות × עד 6 סיבובים). לאמת מול תיעוד Anthropic SDK הקיים
  בקוד (יש שימושים אחרים ב-SDK בפרויקט).
- ‏`max_tokens` מ-1024 ל-4096, ובנוסף: אם `stop_reason == "max_tokens"` —
  לא להציג תשובה קטומה כתקינה; להוסיף סימון גלוי ("התשובה נחתכה") או
  המשך אוטומטי אחד.
- בחירת מודל: ‏`ai_chat_model` נשאר ברירת המחדל, אך נוסף override
  אופציונלי פר-פרסונה ב-config (ריק = הגלובלי). **בלי לשנות את ברירת
  המחדל** — שדרוג המודל הוא הכרעת בעלים (עלות), מוצפת בדוח.
- טסטים: ‏cache_control נשלח (מבנה הבקשה), התנהגות חיתוך, בחירת מודל.

## משימה 4 — ניהול שיחות (multi-session)

- ‏endpoint ‏`GET /ai/chat/sessions` — רשימת ה-sessions של המשתמש בארגון
  הפעיל (מזהה, הודעה ראשונה/אחרונה כקיצור-כותרת, ‏updated, סינון
  `regression-%` ו-`sys-%` לפי הקשר) — org+user-scoped fail-closed.
- ‏`ChatAssistant.tsx`: רשימת שיחות (פתיחה/חזרה לשיחה, שיחה חדשה בלי
  למחוק את הישנה), תצוגת הארגון הפעיל בכותרת הצ'אט.
- טסטים: ‏route (בידוד! משתמש לא רואה sessions של אחר), ‏frontend build.

## משימה 5 — תקרת שימוש על הצ'אט

- אכיפה על מה שהיום רק נרשם: תקרת הודעות-ליום פר-ארגון על `/ai/chat`
  (ערך config, ברירת מחדל נדיבה למשל 200), נבדקת מול `LlmUsage` הקיים או
  מונה ייעודי; חריגה = תשובת 429 כנה עם הסבר, לא חסימה שקטה. ‏super-admin
  פטור. טסט.
- חיווט חיווי ב-UI כשמתקרבים לתקרה (באנר עדין).

## משימה 6 — חיבור endpoints יתומים

- ‏`ownership-review` (2 ‏endpoints ללא צרכן) — טאב/סקציה במסך
  ‏admin-moshko הקיים. אם בבדיקה יתברר שהיכולת לא רלוונטית עוד — להציע
  מחיקה בדוח במקום לחווט (הכרעת מבקר).

## פעולות בעלים (לא בתחום הקוד — מהרנבוק MOSHKO_ACTIVATION_RUNBOOK)

‏SMTP_* (חוסם קישור WhatsApp), ‏4 משתני WHATSAPP_* ב-Vercel + ‏Redeploy,
אישור תבנית push ב-Meta + ‏WHATSAPP_PUSH_TEMPLATE_NAME. ‏
`scripts/check_whatsapp_setup.py` מוכן לאבחון.

## קריטריון סיום

סוויטה ירוקה, ‏build+lint ירוקים, ‏commit פר-משימה, ביקורת קודקס על
הענף כולו לפני push, עדכון לוח הסטטוס.

## גל P0 — ממצאי ביקורת קודקס 23/08 (קודמים למשימות 3-6)

מקור: ‏.superpowers/codex-audit-2026-08-23.md (נשמר גם ב-git לאחר commit).
אלה אכיפות של דוקטרינות קיימות (משמעת עלויות, honest-null, אפס אוטונומיה
בבלתי-הפיך, הקשחת W6.7) — בתחום המנדט הקיים.

### P0-A — איחוד ledger המכסה (הפרצה הכספית)

- המונה החודשי המקומי מאותחל מ-`snapshot.used` ומוגבל ל-
  `min(provider_remaining, internal_remaining)` — מקור אמת אחד
  (‏sumit_quota.py:176,192 מול sumit_request_budget).
- מניפסט paid/free קנוני לכל endpoint בקונקטור, **ברירת מחדל paid** —
  סוגר את הנתיבים שנמלטו מה-allowlist הידני (יצירת לקוח, createbatch,
  ביטול מסמך, העברה לספרים — sumit_integration.py:882,1188,1282).
  טסט כיסוי: כל מתודת קונקטור חייבת סיווג מפורש.

### P0-B — חוזה המזומן (אמת ולא נכסים)

- `_live_cash_balance`: ‏Open Finance + BANK בלבד (כמו dashboard_service:109),
  דרישת טריות `balance_as_of`/`observed_at` — ישן/חסר ⇒ `null` + סיבה.
- `burn_rate`: ‏`null + reason` במקום 0/999 (הפרת honest-null מפורשת).
- ‏credit_line: השוואת מסגרות מול יתרת BANK בלבד.
- תחזית: "הוצאות חוזרות" ו"פיגור AR/AP בחודש הנוכחי" מסומנים כהנחות
  (`assumptions[]` ב-payload + הצגה ב-UI), לא כעובדות.

### P0-C — אטומיות אבטחה (השלמת W6.7)

- מונה כשלי login אטומי (UPDATE יחיד עם WHERE, לא read-modify-write) +
  ‏rate-limit לפי מקור שאינו רק נעילת-חשבון.
- חד-פעמיות reset אטומית (claim על used_at בתנאי).
- ‏`token_version` על User: שינוי/איפוס סיסמה מפקיע את כל ה-sessions.
- ‏reset URL מ-`settings.app_url`, לא מ-request.base_url.

### P0-D — ‏cron ללא כפל-עלות על retry

- שער "ניסיון" (attempt claim) + ‏cooldown אחרי כשל ל-sync-open-finance
  ולכל cron חיצוני — כשל+retry של Vercel לא שורף מכסה מחדש.
- ‏batch cap ל-collection-reminders; תקציב עמיד לדחיפות ערוצים.

### P0-E — הפרדת סמכויות בפעולה בלתי-הפיכה של מושקו

- פעולות בלתי-הפיכות (charge, ביטול/הנפקת מסמך, תיוק, writeback) מסווגות
  IRREVERSIBLE ב-policy_engine ודורשות מורשה-חתימה שאינו המציע
  (proposer≠approver), עם בדיקת policy בהצעה, באישור ובביצוע.
- מעטפת פעולה בלתי-משתנה: ‏hash של (כלי+ארגומנטים+גרסה) נחתם בהצעה
  ונבדק באישור — deploy באמצע לא משנה משמעות.
- ‏moshko_regression: מחיקת gap כפול מסוננת org+user, לא רק session_id.

### נדחה מודע (P1/P2 של קודקס — לתור הבא, לא בגל הזה)

CI על Postgres אמיתי; פירוק קבצי-ענק; jobs פר-ארגון עם lease; המרת
datetime.utcnow; ‏Decimal עד הקצה; ‏npm ci.
