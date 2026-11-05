---
name: daily-file
description: Morning step 1 of Rezef's daily loop — file today's SUMIT expense intake queue (books/fileexpenses) by running the approved sumit-file-expenses runbook, and report what is left. Hebrew triggers "תיוק יומי", "תייק את תור המס", "תיוק בוקר", "מה נשאר לתיוק"; English triggers "daily filing", "file today's expense queue", "morning filing run". Thin entry skill — the OCR/VAT loop lives in sumit-file-expenses.
---

# daily-file — תיוק בוקר של תור ההוצאות

צעד ראשון בלולאה היומית: `daily-file` → `daily-bank-match` → (`of-accounts-sync`) →
`daily-pnl-cash`. מתייקים **רק** את תור הקליטה של סאמית (`books/fileexpenses`).
לא נוגעים כאן בבנק, בהתאמות או בדוחות.

הסקיל הזה דק בכוונה. הלולאה עצמה — תיקון שנת ה-OCR, מע"מ לפי תאריך המסמך,
שערי `MULTIPAGE`/`ALREADY_FILED`/`NO_AMOUNT`, מחיקת כפילויות — מוגדרת
ב-`sumit-file-expenses` (`.claude/skills/sumit-file-expenses/SKILL.md`). לא לשכפל אותה.

## מתי

- כל בוקר, לפני `daily-bank-match`. תיוק קודם, כי התאמת בנק מחפשת מסמך מתויק.
- רק בכרום המחובר של עמית (runbook בפורטל, `AGENTS.md` → "runbooks מאושרים מראש").

## צעדים

1. **הכנה.** טען את `docs/bookkeeper_kb/03-classification-bridge.md` ואת
   `docs/SUMIT_KNOWLEDGE_BASE.md` (verify-first).
2. **ספירה אמיתית של התור.** עמודת "קבצים לקליטה" ברשימת התיקים
   (`app.sumit.co.il/books/`). המונה בכותרת מסך התיוק אינו מספר התור (מוגבל ל-200+).
   רשום: מספר, ארגון, שעה. אם אי אפשר לקרוא — `חסר (תור התיוק, <תאריך>)`, לא 0.
3. **GO.** הצג לעמית: כמה מסמכים, איזה ארגון, מה עומד להישמר. כל "שמירה כמסמך סופי"
   היא בלתי-הפיכה ודורשת **GO מפורש של עמית לריצה הזו**. GO מאתמול, GO לריצה אחרת
   או אישור כללי לסקיל — אינם GO.
4. **הרצה.** הפעל את `sumit-file-expenses` כמו שהוא, מסמך אחרי מסמך. ספק = תור הכרעה
   עם נימוק (honest-null), לא ניחוש.
5. **ספירה חוזרת** באותה עמודה, אחרי רענון.

## תנאי עצירה

- **הצלחה:** תור ≤ 20, ואין חריג בן יותר מ-48 שעות (צעד 3 ב-`00-role-and-daily-order.md`).
- **עצירה מיידית:** אין GO; שער `MULTIPAGE` (פיצול קובץ דורש אישור בעלים); הדפדפן
  לא מחובר; ספק אם המסמך עסקי או על שם העוסק.
- תור שלא התרוקן אינו "נקי" — לומר זאת במפורש.

## דיווח

```
תיוק <ארגון> · as-of <YYYY-MM-DD HH:MM>
תור לפני: <N> · נשמרו: <N> (תנועות <מ>–<עד>) · נמחקו ככפילות: <N>
תור הכרעה: <N> (נימוק לכל אחד) · נשארו: <N>
```

כל מספר שלא נמדד מופיע כ-`חסר` עם התאריך. חסר אינו 0.

## אסור

- להריץ את `scripts/sumit_daily_file_expenses.js`. הוא **חסום** ב-`AGENTS.md`;
  ההיתר הוא ל-runbook שסוכן מבצע עם GO, לא לסקריפט אוטומטי.
- קריאות SUMIT API "בדרך" (getpdf, getdetails וכו'). runbook בדפדפן אינו היתר לעקוף
  את תקרת 50 הקריאות בחודש לכל החשבון.
- להמציא סכום, תאריך או ח.פ. לא לסגור מנה (זה `cfo:close-batch`, עם GO נפרד).
- להמציא פרטי חיבור לארגון שאינו מחובר (למשל org 6 — ממתין להכרעה D).
- merge, מיגרציה לפרוד, או הפעלת cron.
