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

## 7. אסור לבצע אוטונומית

- פריסה, כתיבה לפרוד, מיגרציה בפרוד.
- קריאה חיה ל-SUMIT או ל-Open Finance.
- מחיקה או שינוי של `users.organization_id` בנתונים קיימים.
- הענקת `OrganizationSigningAuthority` לארגון קיים — bootstrap מפורש בלבד.
- שיוך אדם לארגון לפי התאמת מייל, דומיין או נתון מ-SUMIT.
- שינוי סטטוס יכולת ב-`rezef_capabilities.json` ל-`implemented`.
- שליחת הודעת גבייה כלשהי.
