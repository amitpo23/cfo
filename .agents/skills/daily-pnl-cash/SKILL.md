---
name: daily-pnl-cash
description: Final step of Rezef's daily loop — print the day's and the month-to-date P&L and cash (books, BOOKED bank, budget) from one /api/cashflow/period payload, every figure with its source and as-of, unknown values shown as חסר and never 0. Hebrew triggers "רווח והפסד יומי", "תזרים היום", "דוח בוקר רו"ה ותזרים", "מצטבר חודש"; English triggers "daily P&L and cash", "month-to-date P&L", "today's cash report". Reads local Rezef data only, zero provider calls.
---

# daily-pnl-cash — רו"ה ותזרים: היום ומצטבר החודש

צעד אחרון: `daily-file` → `daily-bank-match` → (`of-accounts-sync`) → **`daily-pnl-cash`**.
קורא **payload אחד** — אותו מקור של `/pnl`, `/budget` ו-`/cashflow` (#102). אין
סכימה ידנית, אין קריאה שנייה, אין שילוב של כמה grain-ים.

## מתי

- אחרי `daily-bank-match`. אם הוא נגמר ב"חסום", מריצים בכל זאת, וכותבים בראש הדוח
  "התאמה חסומה: <N> שורות" — מספרים לפני התאמה מלאה אינם סופיים.
- אם `of-accounts-sync` הכניס תנועות חדשות ולא הייתה אחריו התאמה — חוזרים קודם
  ל-`daily-bank-match`.

## הקריאה — אחת

```
GET /api/cashflow/period?grain=day&start=<YYYY-MM-01>&end=<YYYY-MM-DD היום>
```

- `provider_calls` חייב להיות `0`. אחרת — עצירה ודיווח.
- **היום** = `periods[-1]` (הדלי שבו `start == end == היום`).
- **מצטבר חודש (MTD)** = `totals`. לא לסכם את `periods` ידנית.
- **מזומן** = `totals.cash` (תנועות BOOKED; לא מוסתר גם כשטענת רווח חסומה).
- בכל דלי: `books` (`revenue`/`costs`/`net`), `bank` (`in`/`out`/`net`),
  `budget` (`revenue`/`costs`/`net`), `variance`.

## כל מספר — סכום, מקור, as-of

כל ערך ב-payload הוא `{amount, source, as_of, missing_label}`. מדפיסים בדיוק כך:

- `amount` לא ריק → `<amount> · <source> · as-of <as_of>`
- `amount` ריק → `חסר · <missing_label> · as-of <as_of>`. **לא 0, לא "—", לא דילוג.**

## מה בודקים לפני שמדפיסים

1. `partial_banner` לא ריק → מדפיסים אותו בראש הדוח.
2. `profit_claim.allowed == false` → לא מדפיסים נטו כרווח. מדפיסים את
   `profit_claim.reason_he` ואת `unclassified_outflows.label_he` (עם `count`/`amount`).
   הכנסות, הוצאות ותזרים BOOKED עדיין מודפסים.
3. ימים שקטים: ב-grain יומי, יום בלי תנועת BOOKED או בלי מסמך נחשב חסר (#102,
   `gap_is_missing`). לכן ה-MTD ב-`totals` יוצא לרוב `חסר בחלק מהטווח`. **מדווחים את זה
   כך.** לא מוסיפים קריאת `grain=month` כדי "למלא" — שני grain-ים בדוח אחד הם בדיוק
   המספרים הסותרים שהדוח הזה אמור למנוע. ההכרעה על יום שקט פתוחה אצל עמית (E, #106).
4. `as_of` של ה-payload הוא היום. ספרים ובנק נושאים `as_of` משלהם — ההבדל ביניהם הוא
   טריות הנתונים, ומדפיסים את שניהם.

## הדוח

```
רו"ה + תזרים <ארגון> · <YYYY-MM-DD> · as-of <payload.as_of> · provider_calls 0
[partial_banner, אם יש] [התאמה חסומה: N, אם יש] [טענת רווח חסומה: reason_he, אם יש]

                 היום (periods[-1])            מצטבר חודש (totals)
ספרים הכנסות    <figure>                       <figure>
ספרים הוצאות    <figure>                       <figure>
ספרים נטו       <figure>                       <figure>
בנק נכנס        <figure>                       <figure>
בנק יוצא        <figure>                       <figure>
בנק נטו         <figure>                       <figure>
תקציב נטו       <figure>                       <figure>
מזומן (BOOKED)                                  <totals.cash.net>
```

`<figure>` = סכום · מקור · as-of, או `חסר · missing_label · as-of`.
מסך המוצר לאותם מספרים: `/pnl` (לשנות את הטווח שם משנה את כל המספרים, כי זה אותו payload).

## אסור

- להמציא 0, ממוצע, תחזית או "בערך" במקום חסר.
- לחבר ספרים ובנק לעמודה אחת, או לסכם דליים ידנית.
- לקרוא ל-`/api/cashflow/monthly`, `/api/cashflow/daily` או כל מקור נוסף לאותו דוח.
- לסנכרן ספק, לשנות קוד בצד השרת (חישוב יום שקט = החלטת בעלים), או לממש את UI של #106.
- להמציא נתונים לארגון שאינו מחובר (org 6).
