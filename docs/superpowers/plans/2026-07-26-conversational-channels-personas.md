# תכנית מאושרת — ממשק שיחה Telegram/WhatsApp עם 3 פרסונות (מועצה 2026-07-26)

**סטטוס**: מאושר לביצוע. הוכרע ע"י Fable 5 על בסיס תכנית Opus 5 (אומתה מול הקוד).
GPT 5.6 Sol נשר (2×timeout); GPT 5.5 מבצע QA אחרי כל חבילה.

## הכרעות מחייבות

1. **סוכן יחיד + שכבת פרסונה.** פרסונה (`bookkeeper` | `cfo` | `accountant`) היא ציר
   פרומפט/טון/foreground בלבד — **לא שער הרשאה**. `office`/role נשארים שער האבטחה
   היחיד, ללא שינוי בשלושת נקודות האכיפה. כל 23 ה-read-tools זמינים לכל פרסונה;
   write נשאר מאחורי confirm flow הקיים. ברירת מחדל: `cfo`. שאלה חוצת-תחום נענית
   ע"י אותו סוכן עם הצהרת "כובע" בתוך התשובה.
2. **P&L אחד.** גוף `_get_pnl` בכלי הצ'אט עובר ל-`financial_reports_service.generate_profit_loss`
   (ledger חי); שם הכלי נשמר. אין כלי P&L שני.
3. **כלים חדשים (read, כל הפרסונות)**: `get_credit_line_status`, `get_ar_health` (DSO/score),
   `get_cfo_insights`, `get_daily_brief`, `get_tax_estimate` (**חובה** שדות `method`+`caveat`
   בפלט — הנוסחה מפושטת), `verify_filing`, `kb_lookup`. **נדחה**: `get_cash_runway`
   (Transaction מיושנת — עד מיגרציית ledger).
4. **פרומפטים**: מודול `ai_chat_personas.py` — BASE משותף (honest-null, חובת מקור-כלי,
   איסור הנחת-אישור) + בלוק פרסונה (טון + עוגני ידע + foreground tools + אסקלציה).
   מנה"ח=תפעולי־רשימות; CFO=מגמה+מספר+השלכה; רו"ח=זהיר, מפריד ודאי/הערכה,
   מפנה ל-verify_filing לפני כל שידור.
5. **ידע**: loader קל (keyword) מעל `docs/bookkeeper_kb/` + `docs/sumit_help_kb/`. אין RAG.
   חובה `includeFiles` ב-vercel.json + בדיקת נוכחות ב-runtime שמחזירה honest-null
   ("מרכז הידע אינו זמין") — לא רשימה ריקה.
6. **זהות ערוץ**: `ChannelIdentity(provider, external_id, user_id, organization_id,
   default_persona, verified_at, revoked_at)`, unique(provider, external_id) +
   `ChannelLinkCode(user_id, organization_id, code_hash, expires_at, used_at)`.
   קישור: משתמש מאומת JWT מנפיק קוד חד-פעמי באפליקציה (TTL 15 דק', hash ב-DB,
   single-use) → שולח `/start <קוד>` בטלגרם. אין זיהוי לפי טלפון, אפס סיסמאות בצ'אט.
7. **Telegram קודם** (webhook-native, serverless-friendly): route חדש
   `telegram_webhook.py` — אימות `X-Telegram-Bot-Api-Secret-Token` ב-compare_digest,
   **dedupe על update_id בשלב א'** (retry כפול = עלות LLM כפולה), אישור write דרך
   inline keyboard שה-callback שלו נושא message_id בלבד (tool+input נקראים מה-DB).
   WhatsApp = adapter עתידי מעל interface ערוץ אחיד.
8. **דחיות מפורשות**: WhatsApp adapter, דחיפה יזומה (בריף→טלגרם), קול, קבוצות,
   RAG, get_cash_runway, פרסונה רביעית "מתכללת", כלי write חדשים.

## חבילות עבודה (TDD — טסט אדום קודם)

- **חבילה 1 — פרסונות + P&L + כלים חדשים** (בלי ערוץ): `ai_chat_personas.py`,
  עדכון `ai_chat_service.py` (פרמטר persona), תיקון `_get_pnl`, 7 כלים חדשים
  (kb_lookup כ-stub שמחזיר honest-null עד חבילה 2). טסטים: בחירת פרסונה, טון-עוגנים
  ב-prompt, שאלה מעורבת, פרסונה לא מרחיבה הרשאה (super_admin office), caveat במס.
- **חבילה 2 — KB loader**: `kb_loader.py` + חיבור `kb_lookup` + `includeFiles` +
  השלמת `.env.example`/`.env.template` (כולל ANTHROPIC_API_KEY החסר). טסטים:
  חיפוש, קובץ חסר → honest-null, תקרת גודל תשובה.
- **חבילה 3 — זהות + Telegram**: מודלים + מיגרציית alembic, endpoints קוד-קישור,
  `channel_gateway.py`, `telegram_webhook.py`, config (telegram_bot_token,
  telegram_webhook_secret). טסטים: קוד פג/משומש/זר, secret שגוי → 403, dedupe,
  זרימת הודעה→תשובה עם anthropic+httpx מדומים, callback אישור write.
- **חבילה 4 — QA מועצה**: GPT 5.5 על ה-diff המלא, Opus 5 פישוט, pytest ירוק (בסיס 1,401).

## סיכונים (מיטיגציה בטסטים)

1. פרסונה→הרשאה בטעות: טסט שמשתמש רגיל בכל פרסונה לא רואה/מריץ office tool.
2. שני מקורות P&L: כלי יחיד ledger-based.
3. מספר מס מומצא: caveat כשדה + טסט.
4. עלות כפולה מ-retry: dedupe update_id בשלב א'.
5. KB שקט בפרוד: includeFiles + honest-null + מונה ב-engine_status.
