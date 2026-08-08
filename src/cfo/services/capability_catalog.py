"""קטלוג היכולות — מה SUMIT ו-Open Finance יודעים לעשות, במקום אחד.

הרקע: 116 מתודות נבנו ב-`SumitIntegration` ו-100 ב-`OpenFinanceClient`,
אבל למושקו נגישים 50 כלים בלבד (`ai_chat_tools.TOOLS`). היכולת קיימת ואינה
ניתנת לקריאה לפי משימה — אין מקום אחד לשאול "מה משרת את המשימה הזו".

הקטלוג נגזר מהקוד ב-introspection ולא נכתב ביד, כדי שלא יתיישן ברגע
שמישהו מוסיף מתודה. מה שנגזר הוא **מבנה** בלבד (שם, פרמטרים, docstring);
אין כאן שום קריאת רשת ושום גישה לספק.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable


def _summarize(func: Callable) -> str:
    """השורה המשמעותית הראשונה ב-docstring, או מחרוזת ריקה.

    honest-null: מתודה בלי תיעוד מקבלת summary ריק ולא תיאור מנוחש משמה.
    """
    doc = inspect.getdoc(func) or ""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parameters(func: Callable) -> list[str]:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return []
    return [name for name in signature.parameters if name != "self"]


# פעלים שמעידים על כיוון בוודאות. הרשימות סגורות בכוונה: שם שאינו כאן
# מסווג `unknown` ולא מנוחש. ניחוש לכיוון `read` הוא המסוכן שבשניים — הוא
# מתיר קריאה אוטומטית לכלי שבפועל כותב לספק.
_READ_PREFIXES = (
    "get", "list", "fetch", "search", "read", "find", "query", "check", "test",
    "download", "export", "lookup", "validate", "verify", "preview", "calculate",
)
_WRITE_PREFIXES = (
    "create", "add", "update", "set", "delete", "remove", "send", "post", "put",
    "patch", "cancel", "issue", "close", "open", "archive", "upload", "import",
    "assign", "register", "approve", "reject", "refund", "charge", "pay", "submit",
    "sync", "link", "unlink", "enable", "disable", "start", "stop", "trigger",
)


def classify_kind(name: str, summary: str = "") -> str:
    """`read` / `write` / `unknown` עבור יכולת אחת.

    ה-HTTP verb ב-docstring גובר כשהוא קיים — הוא עדות ישירה מהספק, בעוד
    השם הוא רק מוסכמה. `GET` הוא קריאה; `POST`/`PUT`/`PATCH`/`DELETE`
    משנים מצב אצל הספק ולכן כתיבה.
    """
    upper = summary.upper()
    if "GET /" in upper:
        return "read"
    if any(f"{verb} /" in upper for verb in ("POST", "PUT", "PATCH", "DELETE")):
        return "write"

    head = name.split("_", 1)[0].lower()
    if head in _READ_PREFIXES:
        return "read"
    if head in _WRITE_PREFIXES:
        return "write"
    return "unknown"


def _describe(owner: type, system: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, member in inspect.getmembers(owner):
        if name.startswith("_"):
            continue
        if not (inspect.isfunction(member) or inspect.iscoroutinefunction(member)):
            continue
        summary = _summarize(member)
        kind = classify_kind(name, summary)
        entries.append(
            {
                "system": system,
                "name": name,
                "is_async": inspect.iscoroutinefunction(member),
                "parameters": _parameters(member),
                "summary": summary,
                "kind": kind,
                # `unknown` נחשב טעון-אישור בדיוק כמו `write`: כשאין ודאות
                # שהיכולת קוראת בלבד, ברירת המחדל הבטוחה היא לעצור לאישור.
                "requires_approval": kind != "read",
            }
        )
    return sorted(entries, key=lambda entry: entry["name"])


def build_catalog() -> dict[str, list[dict[str, Any]]]:
    """קטלוג מלא, פר-מערכת, נגזר מהקוד החי."""
    from ..integrations.sumit_integration import SumitIntegration
    from .open_finance_client import OpenFinanceClient

    return {
        "sumit": _describe(SumitIntegration, "sumit"),
        "open_finance": _describe(OpenFinanceClient, "open_finance"),
    }


def find_capabilities(
    task: str,
    *,
    reads_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """היכולות שמשרתות משימה נתונה, מדורגות, מכל המערכות יחד.

    זה מה שמאפשר "יכולות מקבילות": משימה אחת מחזירה גם את הכלי של SUMIT
    וגם את זה של Open Finance כשלשניהם יש מה לתרום, במקום שהקורא יצטרך
    לדעת מראש באיזו מערכת להסתכל.

    `reads_only` מצמצם ליכולות קוראות בלבד — המצב הנכון לחקירה, כי הוא
    לא יכול להפעיל פעולה בלתי-הפיכה אצל הספק.
    """
    needle = (task or "").strip().lower()
    if not needle:
        return []

    scored: list[tuple[int, str, dict[str, Any]]] = []
    for entries in build_catalog().values():
        for entry in entries:
            if reads_only and entry["kind"] != "read":
                continue
            # התאמה בשם גוברת על אזכור ב-docstring: השם הוא מה שהמתודה
            # *היא*, ה-docstring הוא רק מה שנכתב עליה.
            if needle in entry["name"].lower():
                scored.append((0, entry["name"], entry))
            elif needle in entry["summary"].lower():
                scored.append((1, entry["name"], entry))

    scored.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, _, entry in scored[:limit]]
