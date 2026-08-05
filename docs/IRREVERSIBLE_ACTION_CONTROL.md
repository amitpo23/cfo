# בקרת פעולות בלתי־הפיכות

מסמך זה הוא חוזה הבטיחות לתשלום, החזר, יצירת מנדט, הפקת/ביטול מסמך, שידור
לרשות וסגירת תקופה. הוא משלים את `REZEF_OPERATING_SYSTEM.md`; הוא אינו הוכחת
מוכנות לפרוד.

## העיקרון

פעולת ספק חיצוני אינה מתחילה מ־route ישיר. הזרימה הנדרשת היא:

`proposed → approved → executing → executed → verified`

- `proposed`: נשמרים הארגון, סוג הפעולה, ה־payload המדויק, hash ומפתח
  idempotency.
- `approved`: `OrganizationSigningAuthority` פעיל ומורשה לסוג הפעולה אישר
  את אותו payload שנשמר. שינוי payload מחייב הצעה חדשה.
- `executing`: worker אחד בלבד תפס את הפעולה ב־UPDATE אטומי.
- `executed`: הספק החזיר מזהה/אישור קבלה. מצב זה עדיין אינו הוכחת השלמה.
- `verified`: בוצע readback עצמאי ונשמרה ראיה.
- `rejected`: ההצעה נדחתה ולא ניתנת לביצוע.

המימוש המקומי נמצא ב־`IrreversibleActionRequest`,
`IrreversibleActionService` וב־`/api/approvals`. API האישור חושף הצעה, רשימה,
צפייה, אישור ודחייה בלבד. אין endpoint גנרי לביצוע ספק.

## מה מוכח מקומית

- בידוד לפי `organization_id` גם בקריאה וגם במעברי מצב.
- `(organization_id, idempotency_key)` ייחודי.
- שימוש חוזר באותו מפתח עם payload שונה נחסם.
- אישור דורש הרשאת חתימה ארגונית פעילה וב־scope המתאים. נשמרים user, role,
  authority id וסוג ההרשאה בזמן האישור.
- `super_admin` אינו עוקף את מדיניות הבעלים העסקית.
- claim לביצוע מותנה ב־`status=approved`, ולכן רק worker אחד יכול לזכות.
- `executed` ו־`verified` נפרדים; אימות דורש evidence לא ריק.
- `tests/test_irreversible_action_workflow.py` מכסה את החוזה ללא רשת.

## בעלים ומורשי חתימה

בעלות עסקית נשמרת בנפרד מ־`UserRole`:

- משתמש ראשון בארגון self-registered חדש מקבל authority מסוג `owner` לכל
  הפעולות.
- רק owner פעיל יכול להעניק או לבטל authority.
- מורשה יכול להיות מוגבל, לדוגמה `["payment"]`; הוא אינו יכול לאשר
  `period_close`.
- אי־אפשר לבטל owner אחרון, להשבית מורשה פעיל או להפוך אותו ל־viewer לפני
  ביטול ההרשאה.
- ארגון שהיה קיים לפני המודל אינו מקבל owner בניחוש. Admin ארגוני מבצע פעם
  אחת bootstrap מפורש עם `I_AM_AUTHORIZED_OWNER`; הפעולה נרשמת ב־AuditLog.

## Inventory ראשוני של נקודות ביצוע

| משפחה | מצב נוכחי | מותר חי? |
|---|---|---|
| `/api/advanced/payments/execute` | נכשל 501; אינו ממציא reference או אפס | לא |
| `/api/payments/*` פעולות כתיבה | דורשות Admin; עדיין אינן צורכות approval עמיד | לא |
| `POST /api/open-finance/payments` | צורך approval מסוג `payment`, נועל payload, מבצע פעם אחת ושומר readback | רק לאחר פריסה, bootstrap וקונפיגורציה; לא נבדק חי |
| ביטול/החזר/`init`/מנדטים ב־Open Finance | דורשים Admin; עדיין אינם צורכים approval עמיד | לא |
| `/api/accounting/documents*` | pass-through ל־SUMIT; טרם חובר לחוזה | לא |
| `/api/financial/documents*` והפקה/ביטול חשבונית | מסלולי שירות נוספים; טרם חוברו לחוזה | לא |
| `/api/open-finance/reconcile/sumit-dispatch` | writeback חיצוני (הערת לקוח ב-SUMIT); מחובר לחוזה `sumit_writeback` — proposed/approved per-row, ללא verified (SUMIT חסר readback עצמאי להערות) | רק לאחר פריסה וקונפיגורציה; לא נבדק חי |
| יצוא/בדיקות דיווח | draft/verification בלבד; אינם שידור לרשות | כן, כטיוטה בלבד |
| סגירת תקופה/מנה | אין executor מאומת | לא |

ה־inventory הוא נקודת פתיחה ולא טענה שכל נקודות הכתיבה אותרו. עד השלמת
סריקה route-by-route, ברירת המחדל לכל endpoint חיצוני שאינו מופיע כאן היא
“לא מאושר לביצוע חי”.

## חוזה החיבור לספק

adapter עתידי חייב:

1. לקבל `request_id` בלבד, לטעון את הרשומה בארגון ולוודא `action_type`.
2. להשתמש ב־payload השמור; אסור לקבל payload חלופי מהבקשה המבצעת.
3. לבצע `claim_for_execution` לפני הקריאה.
4. למסור לספק מפתח idempotency אם הפרוטוקול תומך בו.
5. לשמור provider reference ותשובת קבלה ב־`mark_executed`.
6. לבצע readback בלתי־תלוי ולשמור evidence ב־`mark_verified`.
7. בכשל או תוצאה עמומה לא לסמן verified ולא להחזיר “בוצע”.

`POST /api/open-finance/payments` הוא adapter הייחוס הראשון: `X-Rezef-Approval-Id`
חובה; client לא נבנה לפני בדיקת האישור וה־payload; התשלום נוצר מה־payload
השמור בלבד; replay נחסם; ו־`get_payment` נשמר כראיית readback. הטסט משתמש
בלקוח מזויף בלבד — התנהגות חיה מול הספק **לא נבדקה**.

`services/reconciliation_dispatch.dispatch_reconciliation_to_sumit` הוא adapter
שני, לסוג `sumit_writeback` — עם סטייה מכוונת אחת מהחוזה הכללי: הוא מציע
(`propose`) ומטפל ב־claim/execute **בפנימיות השירות עצמו**, לא דרך header
`X-Rezef-Approval-Id` בבקשת ביצוע נפרדת, כי dispatch מטפל במנה של תנועות בנק
בבת אחת (per-row idempotency key `sumit-writeback:{org_id}:banktxn:{txn_id}`),
לא בפעולה בודדת כמו תשלום. אישור עדיין קורה אך ורק דרך
`POST /api/approvals/{id}/approve` הקיים — השירות לא מדלג על approve, רק
מאחד claim+execute עם ה-dispatch run הבא אחרי האישור. סטייה שנייה, מתועדת:
ל-SUMIT אין endpoint readback עצמאי להערת לקוח (`createremark`), אז ה-adapter
הזה **אינו קורא ל-`mark_verified`** — הפעולה נשארת ב-`executed` (לא `verified`)
לצמיתות; זו מגבלה כנה של הספק, לא פרצה בקוד. `tests/test_sumit_reconciliation_writeback.py`
מכסה propose→pending_approval, approve→confirmed (executed) עם connector מזויף,
reject→unsupported, וכשל ספק→failed — ללא רשת אמיתית.
