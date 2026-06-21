# SUMIT + Open Finance Coverage & Multi-Tenant Buildout Plan

> תאריך: 2026-06-21 · מבוסס על מיפוי רב-סוכני (5 סוכנים) + אימות-קוד ידני.
> מלווה את [PRODUCT_AUDIT_AND_ROADMAP.md](PRODUCT_AUDIT_AND_ROADMAP.md).

## תשובות לשאלות-המפתח (מאומתות)
- **כיסוי SUMIT:** רחב ותקין end-to-end (מסמכים/הוצאות/חוב/סליקה/vault/CRM/SMS/הגדרות/שערים). מה שחסר — ספקים, כרטסת, תרשים חשבונות, **התאמת בנק** — חסר כי **SUMIT API לא חושף אותם**. אין התאמת-בנק נייטיב ב-SUMIT; הנתיב היחיד הוא התאמת OF/נגזר מול מסמכי+תקבולי SUMIT (קיים ב-`bank_reconciliation.py`).
- **חיוב → חשבונית מס:** `charge_customer` מנפיק מסמך (חשבונית-מס/קבלה) אוטומטית. עובד.
- **הוראת קבע:** מודל קיים אך **בזיכרון בלבד** (אין persistence, אין scheduler). SUMIT מציעה הוראת-קבע נייטיב (מחייבת בצד שלה).
- **Scheduling:** תשתית Vercel Cron קיימת, אך רק 2 jobs (`/cron/sync`, `/cron/enrich-expenses`). אין job להוצאת חשבוניות/הרצת הוראות-קבע.
- **Insights ל-OF:** מנוע 8-גלאים אמיתי על תנועות, אך משטח OF המלא (Decision/Scoring, Payments lifecycle, Mandates, Aggregations, Extended-Securities, דוחות-שרת) **לא נצרך**.

## ✅ גל 1 — שכבת P0 בידוד/אבטחה (הושלם 2026-06-21)
- **P0-a** org-scope ל-PATCH tasks/alerts + GET sync-run (cross-tenant נסגר). commit `8dd5b65`.
- **P0-b** דחיית NULL org במקום ברירת-מחדל org 1. commit `2976f36`.
- **P0-c** SUMIT direct routes דרך ה-vault הפר-org (env רק ל-org 1). commit `60ba348`.
- **P0-d** אומת שה-dual-key מיותר (routes הם pass-through טהור, 0 כתיבה מקומית) + הקשחת auth ברמת mount. commit `63c9d32`.
- כל הגל עם טסטי cross-tenant, 228 טסטים עוברים. **המערכת מוכנה לדייר שני מבחינת בידוד.**

## גל 2 — Open Finance (lane A)
- **OF Payments lifecycle (P1/M):** מודל `Payment` org-scoped, status-polling, עיבוד webhook `paymentId` (כיום נזרק). חיבור ל-AR/reconciliation. קבצים: `models.py`, `routes/open_finance.py`, `bank_reconciliation.py`.
- **העשרת insights (P1/M):** לצרוך `openBankingReportBalances` aggregates, `/aggregations`, `extended-securities`, ודוחות-שרת — מעבר ל-8 הגלאים על תנועות גולמיות. קבצים: `bank_insights.py`, `routes/open_finance.py`, `BankInsightsDashboard.tsx`.

## גל 3 — SUMIT (lane B)
- **Write-back verification (P1/M):** אחרי create/cancel/move-to-books לאמת `get_document_details`/`get_payment` שהפעולה נקלטה — מונע השחתה שקטה של היומן הנגזר. קבצים: `sumit_connector.py`, `routes/accounting.py`.
- **Vendor master (P1/M):** לגזור רשומות `Vendor` מ-supplier details של מסמכי הוצאה (SUMIT אין endpoint ייעודי). קבצים: `sumit_connector.py`, `sync_engine.py`.

## גל 4 — Recurring billing & scheduling (lane C — מהשאלה של המשתמש)
- **Persistence להוראות-קבע (P1/M):** מודל `StandingOrder` org-scoped + migration (כיום dict בזיכרון). קבצים: `models.py`, `payment_request_service.py`.
- **Scheduler (P1/M):** `/cron/recurring-charges` שמריץ הוראות-קבע שהגיע `next_charge_date` → `charge_customer` (מנפיק חשבונית מס) → רישום היסטוריה. קבצים: `routes/cron.py`, `payment_request_service.py`.
- **UI לו"ז (P2/M):** הגדרת הוצאת-חשבונית/חיוב תקופתי בדשבורד. קבצים: `PaymentsDashboard.tsx`/חדש.
- שיקול: להעדיף הוראת-קבע **נייטיב של SUMIT** (היא מחייבת+מנפיקה) לעומת מנוע-חיוב עצמאי; להחליט פר-use-case.

## גל 5 — P2 / הרחבות
- חיתום אשראי (OF decision scoring + loans) — **ב-scope, לבנות בהמשך** (החלטת משתמש): `DecisionResult` model + workflow + UI.
- הרחבת סוגי-מסמכים מסונכרנים (proforma/order/delivery_note) ל-lifecycle רכש.
- חשיפת `multivendor_charge` (קיים, ללא route).
- ניתוק מפתח-הצפנה מ-JWT_SECRET (`credentials_vault.py`).
- ניקוי routes של NotImplemented (recurring-charge ידני, fax/postal stubs).

## הערות
- כל גל מבוצע TDD + אימות (טסטים/ריצה) + commit מבודד, כפי שנעשה בגל 1.
- "מקביל" בין lane A/B = גלים עוקבים עם checkpoint, לא בו-זמנית.
