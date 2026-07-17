# תוכנית שלמות נתונים — "מספר על המסך = אמת מאומתת עם מקור"

**נכתב:** 2026-07-12, אחרי אבחון חי של מרכז השליטה (org 1). העיקרון: כל מדד
מוצג חייב (א) נוסחה מוגדרת, (ב) מקור אמת מוגדר, (ג) בדיקת שפיות אוטומטית,
(ד) חותמת טריות. אין נתונים ≠ אפס — מציגים "אין נתונים" בכנות.

## א. ממצאי האבחון (שורש, מאומת מול פרוד)

| # | סימפטום במסך | שורש |
|---|---|---|
| 1 | יתרת מזומן ₪0 | `_account_balance` לא מפענח את המבנה האמיתי: `balances[] = {balanceType: closingBooked/expected, balanceAmount: {amount: "28459.68" (מחרוזת!), currency}, referenceDate}` → נשמר 0 לכל החשבונות |
| 2 | אין הפרדת נכס/התחייבות | כל חשבונות ה-OF נשמרים `account_type=BANK` — כולל LOAN ומסגרות. מזומן חייב = CHECKING בלבד |
| 3 | ספקים לתשלום ‎-947,035 | (א) SUMIT מחזיר מסמכי הוצאה (15/16) עם total **שלילי** — 730/730 שליליים, נשמר כמו-שהוא; (ב) status תמיד RECEIVED ו-balance=total — קבלה-על-הוצאה (type 15) שולמה מעצם טבעה ואינה "לתשלום" |
| 4 | רווח נקי חודש ₪0 | מציג את החודש הקלנדרי הנוכחי (יולי) שאין לו ספרים עדיין — אפס מוצג כעובדה במקום "אין נתונים"/חודש סגור אחרון |
| 5 | runway 0 | נגזרת של מזומן-0; גם הנוסחה לא מוגדרת (צריך burn ממוצע מהבנק) |
| 6 | currency "ILY" | פגם ידוע של הספק בעו"ש — לא מנורמל ל-ILS |
| 7 | "עדיין אין נתוני סנכרון" | last_sync=null ב-overview למרות שסנכרונים רצים — ה-endpoint לא קורא את ה-SyncRun האחרון |
| 8 | אין "הוצאות ללא חשבונית" במרכז | המסך החדש קיים אך לא מקושר מהמרכז ואין אריח |

## ב. ספר הנוסחאות — מקור אמת פר מדד

| מדד | נוסחה | מקור אמת | בדיקת שפיות |
|---|---|---|---|
| יתרת מזומן | Σ balance של חשבונות OF מסוג CHECKING (עסקיים) | OF `balances[]`: העדפה closingBooked, referenceDate המאוחר; string→Decimal | טריות ≤48h; השוואה יומית מול משיכה חיה |
| פיקדונות/חסכונות | Σ SAVINGS | OF | מוצג בנפרד, לא במזומן |
| הלוואות ומסגרות | Σ LOAN (התחייבות) | OF | לעולם לא במזומן |
| חוב כרטיס פתוח | Σ CARD | OF | מוצג כהתחייבות קרובה |
| AR / חובות באיחור | Σ balance של Invoice בסטטוס sent/partially_paid/overdue (+due<today לבאיחור) | SUMIT sync | invariant: אין PAID עם balance>0 |
| AP / ספקים לתשלום | Σ balance של Bill **פתוח בלבד**, אחרי נרמול סימן | SUMIT: type 16 פתוח עד תשלום; **type 15 = שולם** (balance 0) | invariant: total≥0 לכל bill; AP≥0 |
| הכנסות/הוצאות/רווח חודש | Σ invoices.total − Σ (bills+expenses) לחודש המוצג | ספרים | אם אין נתונים לחודש הנוכחי → מציגים חודש סגור אחרון עם תווית; לעולם לא "0" מומצא |
| רווח תפעולי מהבנק (ציר מקביל) | Σ תקבולים − Σ יציאות-הוצאה (אחרי מנוע הסיווג) | בנק | מוצג לצד הספרים + פער מוסבר |
| runway | מזומן ÷ ממוצע burn חודשי נטו מהבנק (3 חודשים סגורים) | בנק | null כשאין 3 חודשים/מזומן |
| הוצאות ללא חשבונית | מנוע הפער (קיים) | בנק×ספרים | כבר חי |
| מע"מ תקופתי | daily-reports/vat | ספרים | **רגרסיה קשיחה: מאי 2026 org1 = ₪1,817.32 בדיוק גם אחרי נרמול הסימן** |

## ג. תהליכי אימות שוטפים
1. **שירות data_quality** — ריצת invariants פר-org: bills.total≥0; אין PAID-עם-יתרה; balance=total−paid; מטבע ∈ {ILS,USD,EUR}; טריות יתרות ≤48h; אין external_id כפול; ספירת טיוטות-ריקות (אינפורמטיבי). תוצאה נשמרת + נחשפת ב-`GET /api/data-quality` וכ-badge ב-overview.
2. **cron סגירה יומית** `/api/cron/daily-close` (06:30, אחרי sync+gap-scan): מריץ data_quality, שומר snapshot יומי (מזומן, AR, AP, P&L חודשי-מצטבר, פער-בנק) — הבסיס למגמות ולדשבורד; כשל-פר-org מבודד.
3. **חוזה כנות ב-UI:** לכל אריח — tooltip מקור+טריות; null → "אין נתונים עדיין"; נתון עם בדיקת-שפיות כושלת → מסומן ⚠️.

## ד. חוזה ה-API המעודכן (dashboard/overview)
```
cash_balance: number|null, cash_as_of: iso|null,
savings_balance, loans_total, card_outstanding,
pnl_month: "YYYY-MM", pnl_is_current_month: bool,
month_revenue/month_expenses/month_net_profit: number|null,
bank_month_inflow/bank_month_outflow/bank_month_net: number,
runway_months: number|null,
ar_total, ar_overdue,
ap_total(≥0), ap_due_7_days, ap_due_30_days,
undocumented_expenses: {count,total,potential_vat},   // חודש נוכחי, מהמנוע
data_quality: {status, issues_count, last_check_at},
last_sync: {sumit: iso|null, open_finance: iso|null}
```

## ה. חלוקת ביצוע
- **סוכן Backend:** נרמול bills (סימן+סטטוס) + סקריפט תיקון דאטה, פרסור יתרות+סיווג חשבונות+ILY, נוסחאות overview לפי החוזה, data_quality, daily-close. TDD; רגרסיית מע"מ קשיחה.
- **סוכן Frontend:** מרכז שליטה מחודש לפי החוזה — כנות (null≠0), טריות, אריח "הוצאות ללא חשבונית" עם קישור למסך הספקים, ניראות ניווט למסך החדש, תיקון תצוגת AP.
- **בקרה (Fable):** review לשני הסוכנים, ריצת סקריפט התיקון בפרוד, אימות חי מול המספרים הידועים (מזומן, AP, מע"מ מאי), deploy, smoke.
