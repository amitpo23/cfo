# תכנית — מושקו כמנהל כספי רב-ארגוני מאובטח

**2026-08-11 · תכנית עבודה, לא לוח סטטוס.** לוח הסטטוס היחיד נשאר
[`MASTER_EXECUTION_PLAN.md`](MASTER_EXECUTION_PLAN.md).
ADR נלווה: [`adr/0001-control-plane-vs-tenant-tables.md`](adr/0001-control-plane-vs-tenant-tables.md).

## 0. סתירה שיש להצהיר עליה לפני הכול

**השער הפעיל הוא שער 0** (פריסה + פתיחת תיק פיילוט). לפי §3.5 בתכנית
הראשית, *"עבודה שאינה בשער הפעיל — נרשמת בחניון ולא מתבצעת."*

רוב התכנית הזו — מנוע גבייה מלא (H), מרכז איכות (I), מסכי ניהול (J) —
**אינה עבודת שער 0.** אינני מרחיב את השער בשקט.

ההפרדה שאני מבצע בפועל:

| קטגוריה | מה נכלל | נימוק |
|---|---|---|
| **תשתית אבטחה הכרחית — מבוצע** | הסרת ברירת המחדל org 1 · חברות רב-ארגונית · מנוע הרשאות · מטא-דאטה של הרשאה לכלי מושקו | אלה **תיקוני חשיפה**, לא הרחבת מוצר. ברירת מחדל שקטה לארגון 1 ומנוע ללא תקרות הם פערים שקיימים כבר עכשיו בקוד שנפרס |
| **תכנון בלבד — לא מבוצע** | חיווט 446 ה-routes (D) · פעולות כספיות (G) · גבייה (H) · מרכז איכות (I) · מסכים (J) | היקף של שבועות; פתיחתם החלקית מייצרת שכבות חצי-בנויות במקום הוכחות |

## 1. מצב קיים — מה שנבדק בקוד (audit)

| # | ממצא | מיקום | חומרה |
|---|---|---|---|
| 1 | `User.organization_id` הוא FK יחיד — אדם שייך לארגון אחד | [models.py:175](../src/cfo/models.py#L175) | **חסר** |
| 2 | SUPER_ADMIN בלי כותרת נופל שקט ל-org 1 | [dependencies.py:219](../src/cfo/api/dependencies.py#L219) | **מסוכן** |
| 3 | ניתוב ה-tenant מחובר ל-3 שירותי קריאה; 446 תלויות route על ה-session המשותף, אפס cron/webhook | `tenant_routing.py` מול `api/routes/*` | **חלקי** |
| 4 | `ChatTool` נושא רק `category`/`office`/`needs_user` — אין הרשאה, סיכון, סמכות חתימה או ערוץ | [ai_chat_tools.py:19](../src/cfo/services/ai_chat_tools.py#L19) | **חסר** |
| 5 | `ChannelIdentity` ייחודי ב-(provider, external_id) → ארגון אחד לכל מספר | [models.py:1636](../src/cfo/models.py#L1636) | **חלקי** |
| 6 | `CollectionCase`: 4 סטטוסים, בלי owner, בלי סכום הבטחה, בלי stop rules | [models.py:979](../src/cfo/models.py#L979) | **חלקי** |
| 7 | `_resolve_super_admin_active_org` פותח `SessionLocal()` משלו בתוך ה-dependency | [dependencies.py:160](../src/cfo/api/dependencies.py#L160) | **מסוכן** |

**קיים ותקין — לא לגעת:** זרימת `propose→approve→execute once→verify`
(`IrreversibleActionRequest`); הפרדת `OrganizationSigningAuthority` מ-RBAC;
קישור ערוץ בקוד חד-פעמי עם hash בלבד (לא לפי טלפון); שער `viewer`
מרכזי; מתג הכיבוי לפעולות SUMIT בתשלום.

### threat model — מה שהממצאים מאפשרים בפועל

| איום | מתאפשר על ידי | מצב |
|---|---|---|
| סופר-אדמין כותב לארגון הלא-נכון בלי כוונה | ממצא 2 — הכותרת נשלחת מ-`localStorage`; ריק ⇒ org 1 | **פתוח** |
| אדם עם שני עסקים לא יכול להפריד ביניהם | ממצא 1+5 | **פתוח** |
| מושקו מציג ל-LLM כלי שהמשתמש אינו רשאי להציע | ממצא 4 | **פתוח** |
| הורדת הרשאה בין הצעה לאישור אינה נתפסת | ממצא 4 | **פתוח** |
| חריגת סכום עוברת דרך confirmation רגיל | אין תקרות בשום מקום | **פתוח** |
| זליגת נתונים בין ארגונים ב-DB | ממצא 3 | מוקטן ע"י `organization_id` בשאילתות; **בידוד פיזי לא מחווט** |

## 2. סדר תלותי

```
ADR (הושלם)
  └─> שלב 1: הסרת ברירת המחדל org 1          ← קטן, בשער 0, מפחית חשיפה
        └─> שלב 2: OrganizationMembership     ← כל השאר תלוי בזהות רב-ארגונית
              └─> שלב 3: מנוע הרשאות          ← לוגיקה טהורה, הוכחה מלאה אופליין
                    └─> שלב 4: מטא-דאטה לכלים ובדיקה חוזרת באישור
                          └─> [חניון] שלבים 5+: D, G, H, I, J
```

## 3. מיגרציות נדרשות

| שלב | מיגרציה | הפיכות |
|---|---|---|
| 1 | אין | — |
| 2 | `organization_memberships` (טבלה חדשה) | drop table; `users.organization_id` **נשאר** ואינו נמחק |
| 3 | `organization_policies` + `policy_grants` | drop tables; בהיעדרן המערכת נופלת חזרה ל-RBAC הקיים בלבד |
| 4 | אין (מטא-דאטה בקוד) | — |

**אף מיגרציה אינה מוחקת עמודה או טבלה קיימת.** `users.organization_id`
משמש כמקור ה-backfill ונשאר כ-fallback לקריאה עד שכל הקוראים יעברו.

## 4. אסטרטגיית rollback

- **שלב 1:** החזרת שלוש שורות. אין נתונים.
- **שלב 2:** `alembic downgrade` מוריד את הטבלה; `users.organization_id`
  שלם ולא נגוע ⇒ המערכת חוזרת להתנהגות הקודמת בדיוק.
- **שלב 3:** בהיעדר טבלאות המדיניות, `policy_engine` מחזיר
  "אין מדיניות" ⇒ **fail closed** לפעולות בסיכון, ו-RBAC הקיים ממשיך
  לשלוט בשאר. מצב זה נבדק בטסט.
- **שלב 4:** מטא-דאטה בקוד; revert של הקומיט.

## 5. מטריצת הרשאות (presets)

`owner` **אינו** ערך ב-`UserRole` — הוא סמכות עסקית ב-
`OrganizationSigningAuthority`. הטבלה למטה היא **תפקיד אפליקטיבי**, וסמכות
החתימה נדרשת **בנוסף** לכל פעולה בלתי-הפיכה.

| פעולה | organization_admin | accountant | finance_manager | collections_agent | employee | viewer |
|---|---|---|---|---|---|---|
| `financial.read` · `reports.read` · `bank.read` | ✔ | ✔ | ✔ | — | — | ✔ |
| `invoices.draft` | ✔ | ✔ | ✔ | — | — | — |
| `invoices.issue` · `invoices.credit` | ✔ | ✔ | — | — | — | — |
| `expenses.review` | ✔ | ✔ | ✔ | — | ✔ | — |
| `expenses.file` | ✔ | ✔ | — | — | — | — |
| `reconciliation.propose` | ✔ | ✔ | ✔ | — | — | — |
| `reconciliation.approve` | ✔ | ✔ | — | — | — | — |
| `collections.read` | ✔ | ✔ | ✔ | ✔ | — | ✔ |
| `collections.contact` | ✔ | — | ✔ | ✔ | — | — |
| `collections.escalate` | ✔ | — | — | — | — | — |
| `payment_link.create` | ✔ | ✔ | ✔ | ✔ | — | — |
| `bank_payment.propose` | ✔ | ✔ | ✔ | — | — | — |
| `bank_payment.approve` · `bank_payment.execute` | — | — | — | — | — | — |
| `mandate.read` | ✔ | ✔ | ✔ | — | — | ✔ |
| `mandate.create` · `mandate.cancel` · `recurring.charge` | — | — | — | — | — | — |
| `refund.propose` | ✔ | ✔ | — | — | — | — |
| `refund.approve` | — | — | — | — | — | — |
| `filing.prepare` | ✔ | ✔ | — | — | — | — |
| `filing.approve` · `period_close.approve` | — | — | — | — | — | — |
| `users.manage` · `policies.manage` | ✔ | — | — | — | — | — |

**השורות הריקות הן העיקר.** `bank_payment.approve/execute`,
`mandate.*`, `recurring.charge`, `refund.approve`, `filing.approve`,
`period_close.approve` — **אף תפקיד אפליקטיבי אינו מקבל אותן.** הן
דורשות `OrganizationSigningAuthority` פעיל וב-scope, ותו לא.
`SUPER_ADMIN` אינו מופיע בטבלה כלל: הוא מפעיל מערכת, לא מורשה עסקי.

## 6. תנאי השלמה לכל שלב

| שלב | תנאי השלמה (אופליין) |
|---|---|
| 1 | SUPER_ADMIN בלי `organization_id` ובלי כותרת מקבל שגיאה מפורשת עם רשימת ארגונים; אף מסלול אינו מחזיר org 1 בשקט; החזית מציגה בורר במקום להיכשל |
| 2 | אדם אחד, שני ארגונים, תפקידים שונים; לא-חבר ⇒ 403 בלי דליפת שם; מושעה/פג-תוקף נחסם מיד; מיגרציה שומרת קיימים בלי לנחש בעלות |
| 3 | מטריצה מלאה role×action; תקרה, מגבלה יומית, חשבון אסור, לקוח אסור, תוקף שפג; deny גובר על allow; מדיניות חסרה ⇒ fail closed; self-approval חסום; שינוי תפקיד בין הצעה לאישור פוסל |
| 4 | ה-LLM מקבל רק סכימות מותרות; שם כלי מומצא נדחה בשרת; בדיקה חוזרת באישור; שינוי payload ⇒ הצעה חדשה; אישור חוצה-ארגון נדחה |

## 6ב. סבב הביקורת — 2026-08-11 (ערב)

### מבנה הענפים

הקומיט המעורב `18fe4c0` (48 קבצים) פוצל; הענף המקורי
`chore/repo-order-and-control-plane` **לא שוכתב ולא נמחק**.

| ענף | תוכן | בסיס |
|---|---|---|
| `fix/explicit-active-org` | הסרת ברירת המחדל org 1 + טסט AUTH_BYPASS | `origin/chore/…` |
| `split/prior-uncommitted-work` | 6 קומיטים: chat action-state · SUMIT BooksBatch · schema drift · frontend · תיעוד · שער drift | `origin/chore/…` |
| `security/org-access-context` | ההקשר, מחזור החיים, תיקוני המיגרציה | `fix/explicit-active-org` |

**שקילות הפיצול אומתה:** ההפרש היחיד בין ענף הפיצול ל-`18fe4c0` הוא
תוכן `48f4831`, שיושב נכון בענף העצמאי.

**מיגרציית החברות נותקה מ-`c1d2e3f4a5b6`** ומשורשרת ל-`b0c1d2e3f4a5`
(ה-head שעל origin). שער אבטחה שתלוי בקוד לא-מסוקר אינו שער.

### ששת הפערים שנסגרו

| # | פער | חומרה |
|---|---|---|
| 1 | מיגרציה הנפיקה `CREATE TYPE userrole` → `DuplicateObject` בפרוד **אחרי** ש-CREATE TABLE בוצע | **P0** — בלתי-נראה ב-SQLite |
| 2 | משתמש מושבת דולג ב-backfill → הפעלה מחדש החזירה גישה בשקט | **P0** |
| 3 | רשומת חברות לא-פעילה נחשבה "אין חברות" ונפלה ל-`users.organization_id` — מה שהותיר את #2 חסר משמעות | **P0** |
| 4 | כותרת מפורשת הוחלפה בשקט בארגון של המשתמש | **P0** |
| 5 | `User.role` שימש כהרשאה ארגונית ב-`require_admin` (44 מסלולים), `get_organization_admin` (11) ו-`require_role` | **P0** |
| 6 | הרשמה יצרה ארגון בלי חברות → כל משתמש חדש נכנס דרך מסלול התאימות | **P1** |

### מדידות

| שער | תוצאה |
|---|---|
| `pytest tests/ -q` | **1,926 עוברים**, 0 נכשלים |
| `audit_routes.py` | 260 · 177 · 45 · **36** · **2** — **זהה לבסיס הענף** |
| `schema_drift_check.py` | PASS |
| frontend lint · tsc · build | PASS |

> **על `audit_routes`:** הבסיס ב-AGENTS.md (37 · 1) נמדד על עץ שכלל את
> תיקון הסיווג מקבוצה ג'. תיקון זה יושב על `split/prior-uncommitted-work`
> ואינו בענף האבטחה, ולכן `qa_gate` מדווח FAIL על שער 2 כאן. אומת
> ב-worktree נפרד: `fix/explicit-active-org` נותן 36 · 2 בדיוק, ו-
> `split/prior-uncommitted-work` נותן 37 · 1. **אפס רגרסיה מעבודת
> האבטחה** — הפער הוא תוצאה ישירה של הפיצול שנדרש.

### לא בוצע

שלב 4 (חיווט מורשי חתימה ופעולות בלתי-הפיכות ל-`OrganizationAccessContext`) ·
שלב 5 (persistence ואכיפת policy בשלוש נקודות + מטא-דאטה ל-ChatTool) ·
שלב 6 (UI: בורר לכל משתמש רב-ארגוני, ניקוי cache, חסימת תצוגה לפני
הכרעת context).

**נותר מחובר ל-`User.role`:** 13 קריאות ישירות במסלולים בודדים,
ו-`get_super_admin` (תפקיד פלטפורמה — נכון שיישאר גלובלי).
`policy_engine` נשאר בלי persistence ובלי קוראים.

## 7. אסור לבצע אוטונומית

- פריסה, כתיבה לפרוד, מיגרציה בפרוד.
- קריאה חיה ל-SUMIT או ל-Open Finance.
- מחיקה או שינוי של `users.organization_id` בנתונים קיימים.
- הענקת `OrganizationSigningAuthority` לארגון קיים — bootstrap מפורש בלבד.
- שיוך אדם לארגון לפי התאמת מייל, דומיין או נתון מ-SUMIT.
- שינוי סטטוס יכולת ב-`rezef_capabilities.json` ל-`implemented`.
- שליחת הודעת גבייה כלשהי.
