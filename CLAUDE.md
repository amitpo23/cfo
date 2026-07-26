# רצף (Rezef) — CFO Operating System

FastAPI backend ב-`src/cfo/`, React frontend ב-`frontend/`, פרוד ב-cfo-2.vercel.app (Vercel + Neon). אינטגרציות: SUMIT (הנה"ח ישראלית) + Open Finance (בנקאות פתוחה).

## לפני עבודה חשבונאית/מיסויית — חובה

**טען את `docs/bookkeeper_kb/README.md`** — מרכז הידע של מנהל החשבונות: דיני הכרה בהוצאות, ניכוי תשומות (תקנה 14/18, אירוח, שער-מסמך), סדר היום, ומשמעת הטעינה. הגשר התפעולי לתיוק: `docs/bookkeeper_kb/03-classification-bridge.md` (מיוצר מ-`src/cfo/services/israeli_tax_rules.py` — לערוך בקוד בלבד).

## דוקטרינות מחייבות

- **verify-first**: בדיקה מול מרכז ידע SUMIT (`docs/SUMIT_KNOWLEDGE_BASE.md`) לפני כל פעולה בפורטל/API.
- **אימות משולש**: כל פלט דיווח לרשויות ≥3 בדיקות בלתי-תלויות (`filing_verification`).
- **honest-null**: אין מספרים מומצאים; עמימות = תור הכרעה, לא ניחוש.
- **אפס אוטונומיה בבלתי-הפיך**: סגירת מנה/שידור/תשלום — רק באישור בעלים.
- **משמעת עלויות API**: קריאות SUMIT/OF רק כשחייבים; שערי sync יומיים קשיחים (20h) — לא לעקוף.

## תפעול

- טסטים: `python -m pytest tests/ -q` (חובה ירוק לפני commit). TDD.
- חוזה המערכת: `docs/REZEF_OPERATING_SYSTEM.md`; סטטוס יכולת וראיות:
  `docs/rezef_capabilities.json`; לוח הסטטוס היחיד: `docs/MASTER_EXECUTION_PLAN.md`.
- המודל המכונן: `docs/BOOKKEEPER_ARMY_OPERATING_MODEL.md` (workflow + 12 SOP).
- סכימת פרוד: `create_all` לא מוסיף עמודות. לפעול רק לפי
  `docs/GATE0_DEPLOYMENT_RUNBOOK.md`; סקריפט DDL חלקי אינו הוכחת Alembic
  `head` ואינו רשאי לסמן אותו.
