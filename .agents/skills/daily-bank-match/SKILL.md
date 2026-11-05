---
name: daily-bank-match
description: Morning step 2 of Rezef's daily loop — after filing, classify and match the month's bank transactions to filed documents until the month is balanced or every open row sits on an explicit blocked list with a reason. Hebrew triggers "התאמת בנק יומית", "תתאים את הבנק", "מה לא מותאם", "רשימת חסומים"; English triggers "daily bank match", "reconcile today's bank rows", "what is still unmatched". Local Rezef data only, zero provider calls.
---

# daily-bank-match — סיווג והתאמה עד מאוזן או רשימת חסומים

צעד שני: `daily-file` → **`daily-bank-match`** → (`of-accounts-sync`) → `daily-pnl-cash`.
עובד רק על נתוני רצף המקומיים. אפס קריאות SUMIT/Open Finance.

## מתי

- אחרי `daily-file`, כי התאמה מחפשת מסמך שכבר תויק.
- **שוב**, אם `of-accounts-sync` הכניס תנועות בנק חדשות. לא מריצים את
  `daily-pnl-cash` על תנועות שלא עברו התאמה.

## לפני שמתחילים

- טריות: `GET /api/sync/runs?limit=20`. ריצת `open_finance` אחרונה ב-`completed` מעל
  26 שעות = הבנק לא טרי. ממשיכים, אבל כל שורה מסומנת `bank_stale` והדוח הוא
  "לא-סמכותי" (צעד 1 ב-`00-role-and-daily-order.md`). **לא** מסנכרנים מכאן.
- טווח: מה-1 בחודש עד היום (`as_of` = היום).

## צעדים

1. **מה פתוח.** `GET /api/reconcile-manual/unmatched?limit=1000`, ואז סינון לטווח החודש.
   אין עימוד בנתיב. אם חזרו בדיוק 1000 שורות — לכתוב
   "מוצגות 1000 מתוך ≥1000", לא "הכול". חיתוך שקט אסור.
2. **פער מסמכים.** `GET /api/daily-reports/bank-expense-gap?year=<YYYY>&month=<M>`.
   לכל יציאה: `has_document`, `matched_hint`, ו-`excluded_by_class` (העברות, שכר,
   מס, כרטיס אשראי וכו' — לא הוצאה שדורשת חשבונית).
3. **הצעות.** לכל שורה פתוחה: `GET /api/reconcile-manual/match-suggestions/<bank_txn_id>`
   (או `GET /api/control/reconciliation/suggestions?start_date=…&end_date=…` לקבוצה).
4. **החלה — רק כשאין ספק.** מועמד יחיד, סכום זהה, ספק זהה, תאריך סביר:
   `POST /api/reconcile-manual/match` עם `bank_txn_id`, `entity_type`, `entity_id`.
   ההתאמה מקומית והפיכה (`POST /api/reconcile-manual/unmatch`). כל השאר → רשימת חסומים.
5. **ספירה חוזרת** של צעדים 1–2.

## מאוזן — ההגדרה המדויקת

החודש **מאוזן** רק כששני התנאים מתקיימים:

- אפס שורות בטווח ב-`/api/reconcile-manual/unmatched` (מקור: `is_reconciled=false`), **וגם**
- `totals.undocumented_count == 0` ב-`/api/daily-reports/bank-expense-gap`.

לכתוב ליד כל מונה את מקורו. דוח הפער מסנן לפי `transaction_date` בלי סינון BOOKED,
ואילו `/api/cashflow/period` סופר BOOKED בלבד. לכן המונים עשויים להיות שונים
בתנועות ממתינות. זה אינו סתירה, אבל צריך לכתוב את זה.

## רשימת חסומים — סיבה לכל שורה

כל שורה שלא הותאמה נכנסת לרשימה עם אחת הסיבות האלה. אין דילוג שקט.

| סיבה | מתי |
|---|---|
| `no_document` | אין מסמך מתויק כנגד היציאה. חוזר ל-`daily-file` או לבקשת חשבונית מהספק |
| `multiple_candidates` | יותר ממועמד אחד, או ציון דומה |
| `amount_mismatch` | מועמד יחיד, סכום שונה (עמלה, תשלום חלקי) |
| `split_payment_1_to_n` | תשלום אחד מול כמה חשבוניות. ב-main אין עדיין התאמה 1:N; אחרי מיזוג #103 — דרך מסך ההתאמה |
| `card_settlement` | חיוב/זיכוי כרטיס (Max, ישראכרט וכו'). הכלל מחכה ל-#105; עד אז לא מנחשים |
| `owner_decision` | משיכת בעלים, הוצאה פרטית, צד שלישי — תור הכרעה |
| `bank_stale` | הבנק לא טרי (ראה "לפני שמתחילים") |

```
התאמת בנק <ארגון> · <YYYY-MM-01>–<YYYY-MM-DD> · as-of <YYYY-MM-DD HH:MM>
הותאמו היום: <N> · לא מותאמות (unmatched, is_reconciled): <N> · ללא מסמך (gap): <N>
סטטוס: מאוזן | חסום
חסומים:
  <תאריך> · <תיאור> · <סכום> · <סיבה> · <מה צריך כדי לשחרר>
```

סכום שלא ידוע מופיע כ-`חסר` עם התאריך, לא 0.

## אסור

- להתאים כשיש ספק, "כדי שהמונה ירד". מונה נמוך עם התאמות שגויות גרוע ממונה גבוה.
- לסנכרן SUMIT או Open Finance מתוך הסקיל (זה `of-accounts-sync`, באישור).
- לסגור מנה, לרשום תשלום ב-SUMIT, או לשנות ספרים רשמיים.
- לממש כאן את הקוד של #103 או #105, למזג ענפים, או להריץ מיגרציה בפרוד.
- להמציא פרטי חיבור לארגון שאינו מחובר (org 6).
