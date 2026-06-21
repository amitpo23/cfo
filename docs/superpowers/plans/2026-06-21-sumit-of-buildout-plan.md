# SUMIT + Open Finance + Recurring Billing — Buildout Plan (workflow-executed)

> תאריך: 2026-06-21 · מבוצע ע"י dynamic workflows, **גל-אחר-גל עם אימות-בריצה ו-commit ידני של עמית-קלוד בין גלים**.
> עיקרון: ה-workflow מממש + כותב unit-tests + מחזיר diffs/status. **אין auto-commit.** אימות-בריצה + commit = ידני, אחרי כל גל.
> גל 1 (P0 בידוד) כבר הושלם ידנית. ראה [SUMIT_OF_TENANCY_PLAN.md](../../SUMIT_OF_TENANCY_PLAN.md).

## חוזה ארכיטקטורה (לכל פריט)
SUMIT=מקור-אמת (מסמכים, לא יומן); ה-ledger נגזר. OF=provisional. Multi-tenant org-scoped עם vault מוצפן פר-org. `from cfo...` בטסטים (src ב-path). הרצת טסטים: `source .venv/bin/activate && python -m pytest -q`. Decimal למע"מ/כסף, לא float.

## סיווג-אימות (קובע מה ה-workflow יכול "לסגור")
- **BE-TDD** — טסט התנהגותי אמיתי (failing-first) = gate. ה-workflow מסיים.
- **UI-scaffold** — tsc/build ≠ נכון; ה-workflow מסקפד, מחזיר "needs /verify". עמית-קלוד מאמת בדפדפן.
- **live-flagged** — דורש OF/SUMIT חי; unit-test ל-parsing/persistence, ה-live מסומן לא-מאומת.
- **migration-gate** — חייב קובץ Alembic תואם המודל; עמית-קלוד סוקר לפני הרצה מול DB.

---

## גל 2 — Open Finance

### 2.1 OF Payment persistence + webhook processing [BE-TDD + migration-gate + live-flagged]
- **Files:** modify `src/cfo/models.py` (add `Payment`-OF model — שם ייחודי, למשל `OpenFinancePayment`, כדי לא להתנגש ב-`Payment` הקיים), `src/cfo/api/routes/open_finance.py` (webhook handler ~808-824 שמטפל כיום רק ב-`connection_id`), `alembic/versions/` (migration חדש). Test: `tests/test_open_finance_payments.py`.
- **Pattern to mirror:** מודל org-scoped עם `organization_id` FK (ראה `BankTransaction` models.py); webhook קיים שמטפל ב-connection events.
- **Test (BE-TDD):** webhook payload עם `paymentId`+status → נוצרת/מתעדכנת רשומת `OpenFinancePayment` org-scoped עם status; payload כפול (אותו paymentId) → upsert (לא כפילות).
- **Acceptance:** events של paymentId כבר לא נזרקים; status ניתן לשאילתה; live polling מסומן TODO לא-מאומת.

### 2.2 Insights enrichment from OF server-side data [BE-TDD + UI-scaffold]
- **Files:** modify `src/cfo/services/bank_insights.py` (generate_insights ~169, risk-signals ~452), `src/cfo/api/routes/open_finance.py` (endpoints aggregations/extended-securities/financial-report ~255-322,747), `frontend/src/components/BankInsightsDashboard.tsx`. Test: `tests/test_bank_insights.py` (להרחיב).
- **Pattern to mirror:** הגלאים הקיימים מחזירים `_insight(...)` dicts; להוסיף גלאי/שדות מ-`openBankingReportBalances` aggregates + extended-securities.
- **Test (BE-TDD):** בהינתן sample aggregates/securities payload → נוצרות תובנות חדשות (נכסים/תיק/יתרות מצרפיות) מעבר ל-8 הגלאים על תנועות.
- **Acceptance:** ה-insights צורך שדות-שרת; UI מציג אותם (scaffold → /verify של עמית-קלוד).

---

## גל 3 — SUMIT

### 3.1 Write-back verification [BE-TDD + live-flagged]
- **Files:** modify `src/cfo/services/sumit_connector.py`, `src/cfo/api/routes/accounting.py` (create/cancel/move-to-books), `src/cfo/integrations/sumit_integration.py`. Test: `tests/test_sumit_writeback.py`.
- **Pattern:** אחרי create/cancel/move-to-books — קריאת `get_document_details(document_id)` לאימות שה-id נקלט/ה-state עבר; אם לא — שגיאה ברורה ולא הצלחה שקטה.
- **Test (BE-TDD):** עם SUMIT integration ממוקה — create→verify מחזיר אישור; כשל-verify → exception/סטטוס שגיאה. live מסומן.

### 3.2 Vendor master from expense supplier details [BE-TDD]
- **Files:** modify `src/cfo/services/sumit_connector.py` (fetch_vendors ~203, כיום ריק), `src/cfo/services/sync_engine.py`, שימוש ב-`get_document_supplier_details` (sumit_integration ~830). Test: `tests/test_vendor_sync.py`.
- **Pattern:** לגזור רשומות `Vendor` מ-supplier details של מסמכי הוצאה (ח.פ+שם), upsert org+external_id+source כמו `_upsert_*` הקיימים.
- **Test (BE-TDD):** מסמכי הוצאה עם ספקים → טבלת `Vendor` מתאוכלסת; אותו ספק פעמיים → רשומה אחת.

---

## גל 4 — Recurring billing & scheduling

### 4.1 StandingOrder persistence [BE-TDD + migration-gate]
- **Files:** modify `src/cfo/models.py` (StandingOrder model org-scoped — כיום dataclass בזיכרון ב-payment_request_service.py:96), `src/cfo/services/payment_request_service.py` (להחליף `self._standing_orders: Dict` ב-DB), `alembic/versions/`. Test: `tests/test_standing_orders.py`.
- **Pattern:** מודל org-scoped + `_upsert`; create/list/cancel נגד DB (כיום dict).
- **Test (BE-TDD):** create_standing_order → נשמר ב-DB ושורד "restart" (session חדש); list/cancel org-scoped.

### 4.2 Recurring-charges scheduler [BE-TDD + live-flagged]
- **Files:** modify `src/cfo/api/routes/cron.py` (הוסף `/cron/recurring-charges` עם `_verify_cron_secret`, כמו `/cron/sync`), `src/cfo/services/payment_request_service.py`. Test: `tests/test_recurring_scheduler.py`.
- **Pattern:** ה-job בוחר standing orders עם `next_charge_date <= today` ו-active → לכל אחד `charge_customer` (מנפיק חשבונית מס) → רישום ב-charges_history → קידום next_charge_date לפי frequency.
- **Test (BE-TDD):** לוגיקת בחירת-due ניתנת-לבדיקה (orders שהגיע זמנם נבחרים; עתידיים לא); החיוב עצמו (SUMIT) מסומן live.

### 4.3 Recurring-schedule UI [UI-scaffold]
- **Files:** modify `frontend/src/components/PaymentsDashboard.tsx` או חדש `RecurringBillingDashboard.tsx` + nav/route ב-App.tsx.
- **Pattern:** מסך להגדרת הוראת-קבע (לקוח/סכום/תדירות/next_date) מול endpoints של standing orders.
- **Acceptance:** scaffold + tsc/build; **needs /verify** של עמית-קלוד.

---

## גל 5 — P2 / הרחבות

### 5.1 Lending: decision/scoring persistence [BE-TDD + migration-gate + UI-scaffold + live-flagged]
- **Files:** `src/cfo/models.py` (DecisionResult org-scoped), `src/cfo/api/routes/open_finance.py` (~517-672 pass-throughs), migration, `OpenFinanceOpsDashboard.tsx`. Test: `tests/test_decision_results.py`.
- **Test (BE-TDD):** decision payload → DecisionResult נשמר org-scoped + parsing; live OF מסומן.

### 5.2 Expand synced SUMIT document types [BE-TDD]
- **Files:** `src/cfo/services/sumit_connector.py` (~230-234 type filters — כיום 5 מתוך 13). Test: להרחיב `tests/test_*sync*`.
- **Test:** proforma/order/delivery_note נכללים ב-fetch (mock).

### 5.3 Expose multivendor_charge route [BE-TDD]
- **Files:** `src/cfo/api/routes/payments.py` (POST /multivendor-charge → `sumit.multivendor_charge`, integration ~1947). Test: route קיים+auth+org-scope.

### 5.4 Decouple encryption key from JWT [BE-TDD]
- **Files:** `src/cfo/services/credentials_vault.py` (~14-21), `src/cfo/config.py`. Test: דורש `CREDENTIALS_ENCRYPTION_KEY` נפרד (אזהרה/שגיאה אם נופל ל-jwt_secret).

### 5.5 Cleanup NotImplemented routes [BE-TDD]
- **Files:** `payments.py` (recurring-charge ידני ~152), `communications.py` (fax/postal stubs). Test: routes מחזירים 501 ברור או מוסרים.

---

## פרוטוקול הרצה
לכל גל: (1) workflow מממש כל פריט ברצף (פריטים שנוגעים ב-models.py סדרתיים), מחזיר diffs+testResult+status; (2) עמית-קלוד מריץ את כל החבילה + build + אימות-בריצה (`/verify`) לפריטי UI/live; (3) סוקר migrations; (4) commit מבודד פר-פריט (staging של קבצי-הפריט בלבד — לא `git add -A`); (5) גל הבא.
