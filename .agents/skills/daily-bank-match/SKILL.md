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

- טריות: `GET /api/sync/runs?limit=100`. ריצת `open_finance` אחרונה ב-`completed`
  לפני יותר מ-26 שעות = הבנק לא טרי. ממשיכים, אבל כל שורה מסומנת `bank_stale` והדוח
  "לא-סמכותי" (צעד 1 ב-`00-role-and-daily-order.md`). **לא** מסנכרנים מכאן.
- טווח: מה-1 בחודש עד היום (`as_of` = היום).

## צעדים

1. **מה פתוח.** `GET /api/reconcile-manual/unmatched?limit=1000`, ואז סינון לטווח החודש.
   אין עימוד בנתיב. אם חזרו בדיוק 1000 שורות — לכתוב
   "מוצגות 1000 מתוך ≥1000", לא "הכול". חיתוך שקט אסור.
2. **פער מסמכים.** `GET /api/daily-reports/bank-expense-gap?year=<YYYY>&month=<M>`.
   לכל יציאה: `has_document`, `matched_hint`. בסיכום: `excluded_by_class` (יציאות
   שלא נדרש להן מסמך) ו-`inflows.undocumented_count` (כניסות בלי חשבונית).
3. **הצעות.** לכל שורה פתוחה: `GET /api/reconcile-manual/match-suggestions/<bank_txn_id>`.
   משתמשים רק בהצעות של הנתיב הזה, כי אותו שירות כותב את ההתאמה בצעד 4.
4. **הצעה, ואחריה אישור.** ב-main, `POST /api/reconcile-manual/match` לא בודק אם המסמך
   כבר מותאם לתנועת בנק אחרת (#103 מוסיף `assert_document_free`). לכן עד מיזוג #103:
   - מציגים לעמית רשימת התאמות מוצעות. בכל אחת מועמד יחיד, סכום זהה, ספק זהה ותאריך סביר.
   - **רק אחרי אישורו** כותבים כל אחת ב-`POST /api/reconcile-manual/match` עם
     `bank_txn_id`, `entity_type` (`invoice`/`bill`/`expense`) ו-`entity_id`.
   ההתאמה מקומית והפיכה (`POST /api/reconcile-manual/unmatch`). כל השאר עובר לרשימת החסומים.
5. **ספירה חוזרת** של צעדים 1–2.

## מאוזן — ההגדרה המדויקת

החודש **מאוזן** כששלושת התנאים מתקיימים:

- `totals.undocumented_count == 0` ב-`/api/daily-reports/bank-expense-gap` (יציאות), **וגם**
- `inflows.undocumented_count == 0` באותו דוח (כניסות בלי חשבונית), **וגם**
- כל שורה בטווח ב-`/api/reconcile-manual/unmatched` (מקור: `is_reconciled=false`) הותאמה
  היום, או קיבלה סיבה מהטבלה למטה.

שורה עם `no_document_expected:<class>` **לא** מונעת איזון. היא מדווחת בשורה נפרדת,
עם הספירה והסכום מ-`excluded_by_class`. כל סיבה אחרת = החודש חסום.

לכתוב ליד כל מונה את מקורו. דוח הפער מסנן לפי `transaction_date` בלי סינון BOOKED,
ואילו `/api/cashflow/period` סופר BOOKED בלבד. לכן המונים עשויים להיות שונים
בתנועות ממתינות. זה אינו סתירה, אבל צריך לכתוב את זה.

## רשימת חסומים — סיבה לכל שורה

כל שורה שלא הותאמה מקבלת אחת הסיבות האלה. אין דילוג שקט.

| סיבה | מתי | חוסם איזון |
|---|---|---|
| `no_document_expected:<class>` | לא נדרש מסמך. `<class>` היא אחת המחלקות של `classify_transaction`: `self_transfer`, `salary`, `tax_payment`, `loan_or_finance`, `bank_fee`, `card_settlement`, `other_excluded`. משתמשים בה רק כשהתיאור מתאים למחלקה ויש לה ספירה ב-`excluded_by_class` | לא |
| `no_document` | אין מסמך מתויק כנגד היציאה או הכניסה. חוזר ל-`daily-file`, או לבקשת חשבונית מהספק | כן |
| `multiple_candidates` | יותר ממועמד אחד, או ציונים דומים | כן |
| `amount_mismatch` | מועמד יחיד בסכום שונה (עמלה, תשלום חלקי) | כן |
| `split_payment_1_to_n` | תשלום אחד מול כמה חשבוניות. ב-main אין עדיין התאמה 1:N. אחרי מיזוג #103 — דרך מסך ההתאמה | כן |
| `card_rule_pending_105` | זיכוי Max או חיוב כרטיס שהמחלקה שלו ב-main שגויה או לא ברורה. הכלל מחכה ל-#105. עד אז לא מנחשים | כן |
| `owner_decision` | משיכת בעלים, הוצאה פרטית, צד שלישי. נכנס לתור הכרעה | כן |
| `unclassified` | לא ברור לאיזו מחלקה השורה שייכת. לא מנחשים | כן |
| `bank_stale` | הבנק לא טרי (ראה "לפני שמתחילים") | כן |

```
התאמת בנק <ארגון> · <YYYY-MM-01>–<YYYY-MM-DD> · as-of <YYYY-MM-DD HH:MM>
הותאמו היום: <N> · לא מותאמות (unmatched, is_reconciled): <N>
ללא מסמך — יציאות (gap): <N> · כניסות (gap.inflows): <N>
לא נדרש מסמך (excluded_by_class): <class> <N> / <סכום> · ...
סטטוס: מאוזן | חסום
חסומים:
  <תאריך> · <תיאור> · <סכום> · <סיבה> · <מה צריך כדי לשחרר>
```

סכום לא ידוע מופיע כ-`חסר` עם התאריך, לא 0.

## אסור

- להתאים כשיש ספק "כדי שהמונה ירד". מונה נמוך עם התאמות שגויות גרוע ממונה גבוה.
- לכתוב התאמה בלי אישור, כל עוד #103 לא מוזג.
- לסנכרן SUMIT או Open Finance מתוך הסקיל (זה `of-accounts-sync`, באישור).
- לסגור מנה, לרשום תשלום ב-SUMIT, או לשנות ספרים רשמיים.
- לממש כאן את הקוד של #103 או #105, לעשות merge לענפים, או להריץ מיגרציה בפרוד.
- להמציא פרטי חיבור לארגון שאינו מחובר (org 6).
