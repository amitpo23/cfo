# סריקת באגים מאומתת — שירותי פאזה 13 (2026-06-25)

נוצר לאחר שה-audit הרב-סוכני התגלה כלא-אמין: הוא קבע ש"ליבת פאזה 13 תקינה",
בעוד `analytics_reporting` היה שבור לחלוטין (16 הפניות לעמודות לא-קיימות).
סריקה זו דטרמיניסטית — שמות העמודות הוצלבו מול הסכמה דרך SQLAlchemy, וכל crash אומת בריצה.

## A. הפניות לעמודות שלא קיימות בסכמה

### תוקן כבר (#1+#2)
- `analytics_reporting.py` — 16× `total_amount`/`remaining_balance` → `total`/`balance`. ✅ תוקן + 4 stubs.
- `forecasting_advanced.py` — ערכים קשיחים → delegation אמיתי. ✅ תוקן.

### פתוח — rename פשוט (`total_amount` → `total`, `vendor_id`→`supplier_id`)
| קובץ | הפניה שגויה | מקבילה נכונה | אומת קורס |
|------|-------------|--------------|-----------|
| `revenue_analytics.py` | `Invoice.total_amount` (8×, +instance) | `Invoice.total` | ✅ `get_revenue_summary` |
| `expense_analytics.py` | `Expense.total_amount` (5×, +instance) | `Expense.total` | ✅ `get_expense_summary` |
| `expense_analytics.py` | `Expense.vendor_id` (2×) | `Expense.supplier_id` | ✅ |
| `invoice_service.py:596` | `i.total_amount` | `i.total` | חשוד |
| `revenue_analytics.py:61` | `Invoice.customer_id` | `Invoice.contact_id` | ✅ |

### פתוח — עמוק מ-rename (אין עמודה תואמת בסכמה כלל)
| קובץ | הפניה | בעיה |
|------|-------|------|
| `revenue_analytics.py` | `Invoice.category` | ל-Invoice אין `category`; revenue-by-category לא נתמך ע"י הסכמה |
| `revenue_analytics.py` | `Contact.country`, `Contact.state_province` | ל-Contact אין שדות גאוגרפיים; `analyze_revenue_by_region` חסר תשתית נתונים |

> משמעות: `analyze_revenue_by_category` ו-`analyze_revenue_by_region` אינם תיקון-rename —
> צריך או להוסיף עמודות לסכמה (migration) או להסיר/לסמן את היכולות כלא-נתמכות.

## B. Stubs / ערכים מומצאים (לא crash, אך נתון לא-אמין)
| קובץ:שורה | מה | חומרה |
|-----------|-----|-------|
| `dashboard_service.py:380` | `cogs = expenses * 0.3` — אומדן COGS שרירותי שמזין gross_profit/opex בדשבורד | בינוני-גבוה |
| `ai_intelligence_agent.py:262` | fallback מחזיר `"[Analysis would be provided here]"` | בינוני |
| `cash_flow_service.py:408,427` | TODO — תזרים חשבוניות/הוצאות מ-SUMIT לא ממומש | בינוני |
| `dashboard_service.py:46` | `month_net_profit = month_gross_profit` (COGS לא מופרד) | נמוך |
| `revenue_analytics.py:219` | profitability ללא הקצאת עלויות | נמוך |
| `ml_models.py:468` | placeholder בתחזית | נמוך |
| `analytics_reporting.py:449` | net profit = operating profit "for now" | נמוך |

## C. תשתית טסטים
הטסטים הריקים (`assert status_code in [200,401,403]`) אפשרו לקוד השבור הזה לעבור CI —
endpoint שמחזיר 500 עובר את ה-assertion. זה שורש העובדה שה-audit פספס.

## False positives שאומתו (לא לתקן)
- `invoice_service.py:596` `i.total_amount` — `i` הוא dataclass `ReceivedInvoice` עם שדה `total_amount`. תקין.
- `financial_management.py:270` `schedule.total_amount` — `schedule` הוא dataclass `PaymentSchedule` עם `total_amount`. תקין.
- `models.py:307` `Payment.status` — הערה בהגדרת העמודה, לא הפניה. תקין.

## פתרון (2026-06-25)
**קבוצה A (קריסות) — נסגרה:**
- `revenue_analytics.py` — `total_amount`→`total`, `customer_id`→`contact_id`; `analyze_revenue_by_category` ו-`analyze_revenue_by_region` מחזירים `{"status":"unsupported"}` (אין עמודה בסכמה); `identify_investment_opportunities` השמיט את הסעיפים התלויים בהם.
- `expense_analytics.py` — `total_amount`→`total`, `vendor_id`→`supplier_id`, `exp.vendor`→`exp.supplier`.
- סורק העמודות הדטרמיניסטי חוזר נקי (היחיד שנותר הוא ה-FP בהערה).
- טסטי derivation אמיתיים: `test_phase13_analytics_real.py` (8), `test_analytics_reporting_real.py` (4), `test_forecasting_advanced_real.py` (4). סה"כ 373 טסטים עוברים.

**נותר פתוח (קבוצה B — נדחתה ע"י המשתמש לסבב נפרד):** `dashboard_service:380` COGS=expenses×0.3, `ai_intelligence_agent:262` fallback מזויף, `cash_flow_service:408/427` TODO.

## הערכה
ה-audit הרב-סוכני אינו אמין לקביעות "תקין/solid". כל ממצא כאן אומת ידנית או דטרמיניסטית.
