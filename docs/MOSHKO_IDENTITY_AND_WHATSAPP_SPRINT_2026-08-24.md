# תוכנית ספרינט — מושקו: זהות + פיילוט WhatsApp ל-5 ארגונים

**תאריך:** 24-25/08/2026. **מקור:** ייעוץ Fable, לפי הנחיית הבעלים. **סטטוס:** S9/S5/S6/S7/S8/S4 בוצעו ונפרסו — S1-S3 (WhatsApp תפעולי) ממתינים לבעלים.

## התקדמות

- ✅ **S9 (מדד המיקוד)** — `c96acae`. `GET /api/admin/moshko/focus-metrics`. בייסליין org2: 8 תורים, 0% giveup, 1 gap (12.5/100 תורים).
- ✅ **S5 (חלקי, במכוון)** — `38f08b7`. שער נגד-דריפט בין BASE_SYSTEM_PROMPT ל-TOOLS, מוכח-תופס. שכתוב פסקת-היכולות המלאה נדחה — סיכון לפרומפט מכוונן, לא בוצע.
- ✅ **S6 (פרוטוקול-תור)** — `556d94a`. `TURN_PROTOCOL` (זהה כוונה→כובע→הצלב-בנק→תבנית תשובה), תוסף לא שכתוב, אפס אובדן-תוכן מאומת בטסט.
- ✅ **S7+S8 (Reflector+Curator)** — `0a4d323`. פורטט מ-`amitpo23/medici-travel-os` (`reflector.ts`+`lessons.ts`). קידום = MoshkoMemory עם `approved_at=None` (תור-אישור קיים, אפס אוטונומיה — שונה מהרפרנס שמפעיל אוטומטית).
- ✅ **S4 (לוח פיילוט)** — `9b1d164`. `GET /api/admin/moshko/pilot-summary`, אותה קונבנציית `wa-`/`tg-` prefix.
- ⏳ **S1-S3 (WhatsApp תפעולי)** — לא בוצע. SMTP+Meta Business Manager+whitelist 5 בודקים דורשים גישת הבעלים; לא ניתן לביצוע מקוד.

**מדידה אחרי S5-S8 (25/08, org2):** זהה לבייסליין (8 תורים, 0%, 1 gap) — אין עוד שיחות חדשות מאז המדידה הראשונה, כצפוי. המדד מוכן למדוד את סבב הבדיקות הבא של הבעלים.

---

## חלק 1 — ממצאי מחקר (מאומתים, לא מנוחשים)

### 1.1 WhatsApp — מה המצב בפועל

**בקוד (נבדק, לא מהזיכרון):** תשתית WhatsApp הרשמית (Meta Cloud API) **כבר בנויה במלואה ובדוקה אופליין**:
- `src/cfo/services/whatsapp_gateway.py` (235 שורות) — שליחת טקסט, כפתורי אישור/ביטול, תבניות, הורדת מדיה, טיפול שגיאות מפורש.
- `src/cfo/api/routes/whatsapp_webhook.py` (457 שורות) — handshake של Meta, אימות חתימה HMAC-SHA256, דדופ wamid עם commit לפני LLM (מגן מכפל עלות Anthropic), אפס LLM לזהות לא-מאומתת.
- `src/cfo/services/channel_link_service.py` — קישור זהות דו-שלבי (טלפון + קוד למייל הרשום).
- טסטים קיימים: `tests/test_whatsapp_gateway.py`, `tests/test_whatsapp_webhook.py`.
- **runbook מוכן**: `docs/MOSHKO_ACTIVATION_RUNBOOK.md` שלב 5א — כולל `scripts/check_whatsapp_setup.py`.

חסר רק **תפעול**: משתני SMTP (תנאי-קדם קשיח לקישור זהות), 4 משתני WhatsApp ב-Vercel, הגדרת webhook ב-Meta.

**מהמאמר ששלח הבעלים** (theailazyleader.com, נקרא): שלושה מסלולים — רשמי (Meta Cloud API/Twilio/360dialog), ענן לא-רשמי מבוסס-QR (~$10–29/חודש, Baileys, סיכון השעיה), self-hosted (חינם, אותו סיכון). כלל: לא-רשמי רק לבוטים פנימיים.

**הממצא המכריע:** מספר-בדיקה חינמי של Meta Cloud API, בלי אימות עסקי, עם whitelist של **עד 5 מספרי נמענים בדיוק** (מאומתים ב-OTP) — התאמה מושלמת ל"5 ארגונים": חינם, רשמי, **אפס סיכון חסימה** (פיצ'ר מתועד, לא עקיפה).

**עלות שוטפת:** מאז 07/2025 חיוב פר-הודעת-תבנית; שיחות שיוזם הלקוח **חינמיות לגמרי**, כולל תשובות free-form בחלון 24 שעות. דפוס מושקו (משתמש פונה → עונה) = עלות ~0 כל עוד אין דחיפה יזומה בתבניות.

**המלצה: מסלול 5א — מספר הבדיקה הרשמי של Meta.** לא Twilio sandbox, לא unofficial (הזיכרון מ-21/07: "WhatsApp halted — API ToS" — הקוד נבנה מחדש על ה-API הרשמי בגלל זה בדיוק).

### 1.2 "זהות" — מקורות ההשראה

- **"Hodini" של יובל אבידני — זוהה.** = `hoodini`, ה-GitHub handle של יובל אבידני (YUV.AI, GitHub Star). ריפו רלוונטי: [`hoodini/ai-agents-skills`](https://github.com/hoodini/ai-agents-skills) — ידע ארוז כ-skills (SKILL.md). יש skill "Honest Agent" (נגד חנפנות) אבל **אין מערכת זיכרון/זהות שלמה** — התרומה היא הדפוס: ידע ארוז כמודולים ניתנים-לגילוי, לא prompt ענק.
- **`amitpo23/medici-travel-os` — המכרה האמיתי.** לולאת למידה ACE מלאה בסגנון Reflector/Curator (`src/core/learning/`): תמליל+outcome ← Reflector (LLM אחד מחלץ עד 3 לקחים, קטגוריות מוגבלות) ← Curator (מיזוג כמעט-זהים, קידום רק אחרי ≥3 הופעות בלתי-תלויות + policy קשיח שחוסם לקחים על כסף/הזמנות/אישורים + תקרת playbook 12). בדיוק מה שחסר למושקו.
- **"גל חבקין" — לא נמצא.** חיפוש עברית+אנגלית ריק; אין אזכור ב-`~/.claude/`. מה שכן הוטמע היום (24/08, 10:41–13:57): skill `engineering-framework` (`~/.codex/skills` + symlink ל-`~/.claude/skills`) — ללא attribution לחבקין. **שאלה פתוחה לבעלים** (לא ניחוש): האם זו הכוונה?

### 1.3 מה כבר קיים אצל מושקו — הרבה יותר משנדמה

| רכיב | קובץ | סטטוס |
|---|---|---|
| זהות-בסיס + 3 כובעים + honest-null | `ai_chat_personas.py` | קיים, מונוליט ~850 מילים |
| זיכרון לומד דו-scope (Hermes-style) | `moshko_memory.py` | קיים ועובד (W1.4) |
| תור כישלונות | `moshko_gaps` + `moshko_observability.py` | קיים (W1.1, 20/08) |
| קידום תשובה→זיכרון + regression | `admin.py` + `moshko_regression.py` | קיים — **ידני לחלוטין** |
| פידבק 4 קטגוריות | `moshko_feedback_service.py` | קיים |
| קטלוג 216 יכולות ספק | `capability_catalog.py` | קיים |
| ידע (rezef_kb + bookkeeper_kb) | `moshko_knowledge.py`, `kb_loader.py` | קיים |

**מה באמת חסר (שורש ה"מתפזר"):**
1. **אין לולאת למידה סגורה** — הפער בין `moshko_gaps` לפרומפט נסגר רק בעבודת-יד, פער-פער. אין Reflector/Curator אוטומטיים.
2. **BASE_SYSTEM_PROMPT מונוליט נסחף** — מונה יכולות בפרוזה, כפול מול `TOOLS` (~50 כלים, 3,933 שורות). כל כלי חדש = עדכון כפול, אין טסט שתופס drift.
3. **אין פרוטוקול-תור אחיד** — הפרומפט אומר *מה* מושקו יודע, לא *באיזה סדר* לעבוד.
4. **אין מדד פיזור** — אי אפשר לדעת אם זה משתפר בלי מספר.

---

## חלק 2 — ארכיטקטורת "זהות מושקו" (עיקרון: לא בונים מחדש, סוגרים לולאה שכבר 80% קיימת)

```
שכבה 1 — חוקה:    MOSHKO_IDENTITY — דוקטרינות + תהליך-תור סדור (מקור-אמת יחיד, עליו טסטים)
שכבה 2 — יכולות:  פסקת-הכלים בפרומפט מיוצרת מ-TOOLS, לא כתובה ביד
שכבה 3 — זיכרון:  moshko_memory (קיים) — עובדות מאושרות, הזרקה קפואה
שכבה 4 — למידה:   ACE loop בנוסח medici-travel-os —
                   moshko_gaps/feedback → Reflector (ידני) → לקחים-מועמדים
                   → Curator (≥3 הופעות + policy gate) → תור-אישור-בעלים (קיים)
                   → regression runner (קיים) → מדד
```

התאמות לדוקטרינות רצף: Reflector **ידני בלבד** (משמעת עלויות, כמו regression); קידום ל-active **לעולם לא אוטונומי** — דרך תור-האישור הקיים; policy gate חוסם כל לקח שנוגע למספרים פיננסיים/פעולות בלתי-הפיכות (honest-null + אפס אוטונומיה).

---

## חלק 3 — תוכנית WhatsApp ל-5 ארגונים

**מסלול: Meta test number. עלות: ₪0. סיכון חסימה: אפס.**

1. SMTP ב-Vercel (5 משתנים) + Redeploy — תנאי-קדם קשיח.
2. Meta Business App ← WhatsApp Set up ← מספר בדיקה + **טוקן System User קבוע** (לא זמני-24h).
3. Whitelist 5 מספרי בודקים (OTP לכל אחד).
4. Webhook: `https://cfo-2.vercel.app/api/whatsapp/webhook` + verify token + app secret.
5. אימות: `python scripts/check_whatsapp_setup.py --send-to <מספר>` (קיים).
6. Onboarding: כל בודק שולח למספר-הבדיקה את המייל הרשום שלו ← קוד ← מחובר.

מגבלות מקובלות לפיילוט: מספר לא-ממותג, דחיפה-יזומה מוגבלת לתבניות (לא רלוונטי — פיילוט inbound-driven). מעבר למספר אמיתי = מחוץ לספרינט.

---

## חלק 4 — הספרינט

### עדיפות א' — פיילוט WhatsApp חי

| # | משימה | TDD | תלות | מאמץ | קריטריון הצלחה |
|---|---|---|---|---|---|
| S1 | SMTP בפרוד + Redeploy | לא (ops) | — | S | קוד מגיע בפועל למייל בקישור-זהות |
| S2 | Meta test number + webhook | לא (ops) | S1 | S | `check_whatsapp_setup.py --send-to` מצליח |
| S3 | גיוס+קישור 5 בודקים | לא (תלוי-אנשים) | S2 | S | 5 `ChannelIdentity` מאומתות, שיחה דו-כיוונית |
| S4 | לוח פיילוט read-only | כן | S3 (לנתונים) | M | שאילתה אחת: "כמה עלה השבוע, מה נשבר" |

### עדיפות ב' — זהות מושקו

| # | משימה | TDD | תלות | מאמץ | קריטריון הצלחה |
|---|---|---|---|---|---|
| S5 | MOSHKO_IDENTITY כמקור-אמת, פרומפט-יכולות נגזר מ-TOOLS | כן | — | M | כלי חדש מעדכן פרומפט אוטומטית; טסט אדום על drift |
| S6 | פרוטוקול-תור סדור (כוונה→כובע→כלי→הצלבת-בנק→תבנית) | חלקית | S5 | S | כל הנחיות-הבעלים ממופות למקטע אחד, אפס אובדן |
| S7 | Reflector — חילוץ לקחים מ-gaps (פורט מ-medici-travel-os) | כן | — | M | 10 gaps אמיתיים → מועמדים שמורים עם source_gap_ids |
| S8 | Curator + policy gate (חוסם לקחים פיננסיים) | כן | S7 | M | אף לקח פיננסי לא עובר בטסט; לקח מאושר מוזרק |
| S9 | מדד מיקוד (%ויתור, gaps/100 תורים, %regression-pass) | כן | — | S | baseline לפני S5–S8, מדידה אחרי |

**סדר מומלץ:** S1→S2→S3 במקביל ל-S5→S6→S9 (baseline קודם!); אחר כך S7→S8. אם מקצצים: S4+S8 לספרינט הבא; **S9 לא מקצצים** — בלעדיו אין דרך לדעת אם זה עבד.

---

## חלק 5 — מה לא לעשות עכשיו

1. **לא unofficial WhatsApp** — יש 5 מספרים חינם ורשמית.
2. **לא מספר עסקי אמיתי + אימות עסקי** — שלב production, אחרי שהפיילוט מוכיח ערך.
3. **לא vector DB/RAG לזיכרון** — ההזרקה הקפואה עם תקרות היא החלטה מודעת שעובדת.
4. **לא Reflector אוטומטי ב-cron** — עולה טוקנים; ידני, כמו regression.
5. **לא כובע רביעי, לא ערוץ קול, לא ניתוב-חתימות יזום** — כבר מסומנים כ-follow-up ב-`rezef_capabilities.json`.
6. **לא "מערכת skills" בהשראת hoodini** — rezef_kb+kb_lookup כבר ממלאים את התפקיד; העיקרון (ידע ארוז ונגזר) כבר מיושם ב-S5.

**שאלה פתוחה אחת לבעלים:** "גל חבקין" = ה-skill `engineering-framework` שהוטמע היום? לא נמצא זכר אחר.

---

## מקורות
[theailazyleader — מדריך WhatsApp](https://theailazyleader.com/he/blog/whatsapp-automation-ai-guide-hebrew) · [Meta Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/) · [WANotifier — Test Number Limitations](https://help.wanotifier.com/en/article/test-phone-number-limitations-in-direct-setup-kt0ly2/) · [Meta WhatsApp Pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing) · [Blueticks — WhatsApp API Pricing 2026](https://blueticks.co/blog/whatsapp-business-api-pricing-2026) · [hoodini GitHub](https://github.com/hoodini) · [hoodini/ai-agents-skills](https://github.com/hoodini/ai-agents-skills) · [YUV.AI](https://yuv.ai/)

### קבצים קריטיים ליישום
`src/cfo/services/ai_chat_personas.py` (S5/S6) · `src/cfo/services/ai_chat_service.py` (הרכבת פרומפט/תור) · `src/cfo/services/moshko_observability.py` + `moshko_regression.py` (S7–S9) · `docs/MOSHKO_ACTIVATION_RUNBOOK.md` (S1–S3) · `src/cfo/api/routes/admin.py` (תור gaps/קידום, Curator + לוח פיילוט)
