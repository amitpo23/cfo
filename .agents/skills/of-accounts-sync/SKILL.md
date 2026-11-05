---
name: of-accounts-sync
description: Optional slot in Rezef's daily loop, right before the P&L/cash report — pull Open Finance accounts and bank transactions into Rezef for one organization, only on Amit's explicit instruction for this run, and only if the last Open Finance sync is at least 20 hours old. Hebrew triggers "סנכרון בנק לפני דוח", "תמשוך תנועות מאופן פיננס", "רענון חשבונות בנק"; English triggers "sync Open Finance accounts", "pull bank transactions before the report". Admin only. Costs provider budget; never scheduled.
---

# of-accounts-sync — משיכת חשבונות ותנועות מ-Open Finance לפני דוח

משבצת אופציונלית: `daily-file` → `daily-bank-match` → **`of-accounts-sync`** →
`daily-pnl-cash`. זה הסקיל היחיד בלולאה היומית שעולה כסף (תקציב קריאות Open Finance).

## מתי — ורק אז

- עמית ביקש במפורש סנכרון **לריצה הזו**, לארגון מסוים. בקשה מאתמול או "תריץ את כל
  הבוקר" אינן בקשה לסנכרון.
- המשתמש המריץ הוא admin/SUPER_ADMIN. **ב-main הנתיב `POST /api/sync/run` דורש רק
  משתמש מחובר**, כלומר השער הזה קיים בסקיל ולא בקוד. לא מריצים בשם משתמש רגיל.
- לארגון יש חיבור Open Finance פעיל: `GET /api/integration/status` → `open_finance: true`.
- הסנכרון הליילי כבוי בהכרעת עמית. הסקיל הזה **לא** מתזמן, לא מוסיף cron ולא משנה
  את `OPEN_FINANCE_SCHEDULED_SYNC_*`.

## שער 20 השעות — בודקים לפני, כי הנתיב לא בודק

ב-main, `POST /api/sync/run` אוכף רק cooldown של 15 דקות. שער 20 השעות
(`of_sync_min_interval_hours`) נאכף ב-cron וב-`connections/refresh-all`, לא כאן.

1. `GET /api/sync/runs?limit=100` → הריצה האחרונה עם `source == "open_finance"`,
   **בכל סטטוס**, כולל `failed`. ריצה שנכשלה כבר צרכה קריאות. אם ב-100 הריצות האחרונות
   אין אף ריצת `open_finance`, כותבים זאת ולא מסיקים "מעולם לא רץ".
2. `started_at` של הריצה הזו לפני פחות מ-20 שעות → **עצירה**. מדווחים "ניסיון אחרון
   ב-<started_at>, הבא מותר אחרי <started_at + 20h>", וממשיכים ל-`daily-pnl-cash` עם
   הנתונים הקיימים.
3. אם יש הרשאת SUPER_ADMIN: `GET /api/admin/cost-protection-status` →
   `open_finance.sync_min_interval_hours`. אם הערך גבוה מ-20, עובדים לפיו.

## הריצה

```
POST /api/sync/run?source=open_finance
```

- **בלי `entity_types`.** ריצה עם `entity_types` לא מעדכנת את ה-checkpoint
  (`__source__`) שה-cron בודק (`sync_engine.run_full_sync`). אז ה-cron של הארגונים
  שברשימה עלול לסנכרן שוב בתוך פחות מ-20 שעות. ריצה מלאה ל-Open Finance עולה אותו
  דבר: שאר הישויות (לקוחות, חשבוניות וכו') מוחזרות ריקות בלי קריאת רשת
  (`open_finance_connector.py`). בפועל נמשכים `accounts` ו-`bank_transactions`.
- ריצה אחת. 429 (cooldown) או כישלון → עצירה ודיווח. **אין ניסיון חוזר** באותו יום.
- אחרי הריצה: `GET /api/sync/runs?limit=5` → `status`, `counts`, `error_summary`.

## אחרי — חובה

- `counts` מראה תנועות בנק חדשות → **חוזרים ל-`daily-bank-match`** לפני
  `daily-pnl-cash`. דוח שכולל תנועות שלא עברו התאמה סותר את דוח ההתאמה.
- `partial` או `error_summary` לא ריק → הנתונים חלקיים. הדוח הבא מסומן כך, וכל
  ערך שלא נמשך מופיע כ-`חסר (Open Finance, <תאריך>)`, לא 0.

## פעולה נפרדת: refresh-all

`POST /api/open-finance/connections/refresh-all` מבקש מהספק לרענן את החיבור מול הבנק.
עלותו 20 קרדיטים, והוא דורש מחרוזת אישור מדויקת. **זו לא חלק מהסקיל.** עושים את זה
רק ב-GO נפרד ומפורש של עמית, ורק אם הוא ביקש את הפעולה הזו בשמה.

## דיווח

```
OF sync <ארגון> · as-of <YYYY-MM-DD HH:MM>
ריצה אחרונה קודמת: <finished_at> · הוחלט: הורץ | נחסם (20h) | נחסם (אין בקשה/אין חיבור)
תוצאה: <status> · חשבונות: <N> · תנועות חדשות: <N> · שגיאות: <error_summary | אין>
הבא: daily-bank-match (תנועות חדשות) | daily-pnl-cash
```

## אסור

- לסנכרן SUMIT מכאן, או להריץ `/api/admin/control/clients/<org_id>/sync`. הוא מסנכרן
  את כל המקורות הפעילים, כולל SUMIT.
- לעקוף את שער 20 השעות, לנסות שוב אחרי 429, או לשנות env/דגלים.
- להירשם לשירות בתשלום, ליצור חיבור/consent חדש, או להמציא credentials (למשל org 6).
- להפוך משיכה שנכשלה ל-0 או ל"אין תנועות".
- merge, מיגרציה לפרוד, או שינוי ב-`vercel.json`.
