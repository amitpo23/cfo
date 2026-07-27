# Runbook — הפעלת ערוץ הטלגרם בפרודקשיין

מיועד לבעלים. כל השלבים כאן דורשים סודות או פעולה חיצונית ולכן **אינם מבוצעים ע"י
סוכן** (ראו `AGENTS.md` — "אסור להריץ"). הקוד עצמו כבר בענף ועובר טסטים; מה שלהלן
הוא רק ההפעלה.

הפניה: התכנית המלאה ב-`docs/superpowers/plans/2026-07-26-conversational-channels-personas.md`.
סדר הפריסה הכללי כפוף ל-`docs/GATE0_DEPLOYMENT_RUNBOOK.md`.

## 0. מה כבר קיים בקוד

| רכיב | קובץ |
| --- | --- |
| קבלת עדכונים מטלגרם | `src/cfo/api/routes/telegram_webhook.py` (`POST /api/telegram/webhook`) |
| הנפקת קוד קישור | `src/cfo/api/routes/channels.py` (`POST /api/channels/link-code`) |
| קישור זהות ואימות | `src/cfo/services/channel_link_service.py` |
| שליחה יוצאת | `src/cfo/services/channel_gateway.py` |
| טבלאות | מיגרציה `f2a3b4c5d6e7_add_channel_identity.py` |
| UI הנפקת קוד | `frontend/src/components/SettingsPage.tsx` — כרטיס "ערוצי שיחה" |

## 1. יצירת הבוט (BotFather)

1. בטלגרם: שיחה עם `@BotFather` → `/newbot` → שם ושם-משתמש לבוט.
2. שמור את ה-token שהתקבל. **הוא סוד** — לא ל-git, לא לצ'אט, לא ל-`.env` שנדחף.
3. מומלץ: `/setprivacy` → `Enable` (הבוט לא יקרא הודעות קבוצה; ממילא הקוד מתעלם
   מכל צ'אט שאינו `private`).
4. אופציונלי: `/setcommands` עם:
   ```
   cfo - מנהל כספים: תזרים, גבייה, רווחיות
   bookkeeper - מנהלת חשבונות: הוצאות, מסמכים, מע"מ
   accountant - רואה חשבון: מס, אימות דיווח
   ```

## 2. סוד ה-webhook

ייצר מחרוזת אקראית חזקה (זהו ערך שאתה בוחר, לא משהו שטלגרם נותן):

```bash
openssl rand -hex 32
```

## 3. משתני סביבה ב-Vercel

הוסף לפרויקט `cfo-2`, ל-**Production** (ול-Preview אם רוצים לבדוק שם):

| משתנה | ערך |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | ה-token מ-BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | הפלט של שלב 2 |

ודא ש-`ANTHROPIC_API_KEY` כבר מוגדר — בלעדיו הצ'אט מחזיר 503 מפורש.

**עד שהמשתנים מוגדרים, ה-endpoint מחזיר 503 "ערוץ טלגרם לא מוגדר"** — הוא לעולם
לא פתוח ללא אימות.

## 4. מיגרציית מסד הנתונים

שלוש הטבלאות (`channel_identities`, `channel_link_codes`,
`channel_processed_updates`) נוצרות רק ע"י Alembic. `create_all` לא יוסיף אותן.
פעל לפי `docs/GATE0_DEPLOYMENT_RUNBOOK.md` להרצת המיגרציה `f2a3b4c5d6e7` מול Neon.

## 5. רישום ה-webhook מול טלגרם

אחרי שהפריסה עלתה עם המשתנים:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" -H "Content-Type: application/json" -d '{"url":"https://cfo-2.vercel.app/api/telegram/webhook","secret_token":"<WEBHOOK_SECRET>","allowed_updates":["message","callback_query"]}'
```

אימות:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

`pending_update_count` גבוה או `last_error_message` = בעיה בפריסה, לא בטלגרם.

## 6. קישור המשתמש הראשון

1. באפליקציה: הגדרות → ערוצי שיחה → **הנפק קוד קישור**.
2. בטלגרם, לבוט: `/start <קוד>` — תוך 15 דקות.
3. תשובת ברוך-הבא מציינת את שלוש הפרסונות ואת ברירת המחדל (מנהל כספים).

הקוד חד-פעמי, נשמר כ-hash בלבד, ומבוטל ברגע שמנפיקים חדש. **אין זיהוי לפי מספר
טלפון ואין סיסמאות בצ'אט** — הקוד הוא שרשרת האמון היחידה מהאפליקציה המאומתת אל
הערוץ.

## 7. אימות אחרי ההפעלה

| בדיקה | ציפייה |
| --- | --- |
| הודעה מחשבון **לא** מקושר | הסבר קישור בלבד. **אפס קריאות LLM** — לא נצרך תקציב |
| "מה התזרים שלי?" מחשבון מקושר | מספרים מהשירותים, לא מהמודל |
| "כמה מס אשלם?" | האומדן **חייב** להופיע עם הסתייגות (`caveat`) |
| שאלה על נוהל/דין | הבוט משתמש ב-`kb_lookup` |
| `kb_files_available` (שאל את הבוט על engine status) | ‏> 0. אם 0 — `includeFiles` ב-`vercel.json` לא עבד ומרכזי הידע לא נארזו |
| פעולת כתיבה | כפתורי "אשר / בטל" — לעולם לא ביצוע אוטומטי |

## 8. כיבוי / ניתוק

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

לניתוק משתמש בודד: לסמן `revoked_at` בשורת ה-`ChannelIdentity` שלו. `resolve_identity`
מתייחס לזהות מבוטלת בדיוק כמו לזהות שלא קיימת.
