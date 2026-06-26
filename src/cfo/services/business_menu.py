"""Per-business capability menu / syllabus (תפריט יכולות לכל עסק).

One catalog of everything the platform does, rendered per organization with a LIVE
status for each capability: is it ready to use for *this* business right now, and on
what data basis (real SUMIT data / derived by us / blocked on a missing connection).

This is the "menu" an accounting-office manager opens per client file to see, at a
glance, the full surface and what's actionable today vs. what needs a connection or
data first. Status is computed from the org's real counts + connection health, so it
never overstates readiness.
"""
from __future__ import annotations

from typing import Any

# Capability natures (matches the engine's state vocabulary).
REAL, DERIVED, PARTIAL, BLOCKED = "real", "derived", "partial", "blocked"

# The full catalog. Each capability lists its route and how readiness is judged.
# `needs` keys: "docs" (any invoices/bills/expenses), "invoices", "bills",
# "employees", "bank" (validated bank data), "sumit" (SUMIT connected).
CATALOG: list[dict[str, Any]] = [
    {"key": "bookkeeping", "title": "הנהלת חשבונות כפולה", "icon": "BookOpen", "nature": DERIVED,
     "capabilities": [
        {"name": "מאזן בוחן", "route": "/api/ledger/trial-balance", "needs": "docs"},
        {"name": "פקודות יומן", "route": "/api/ledger/journal", "needs": "docs"},
        {"name": "כרטסת חשבון", "route": "/api/ledger/account/{code}", "needs": "docs"},
        {"name": "מאזן (נכסים/התחייבויות/הון)", "route": "/api/ledger/balance-sheet", "needs": "docs"},
     ]},
    {"key": "receivables", "title": "חייבים (AR) — מי חייב לנו", "icon": "TrendingUp", "nature": REAL,
     "capabilities": [
        {"name": "גיול חובות לקוחות", "route": "/api/daily-reports/ar-aging", "needs": "invoices"},
        {"name": "מי חייב לנו (כרטסת לקוח)", "route": "/api/ar/aging", "needs": "invoices"},
     ]},
    {"key": "payables", "title": "זכאים (AP) — מה אנחנו חייבים", "icon": "CreditCard", "nature": REAL,
     "capabilities": [
        {"name": "גיול התחייבויות לספקים", "route": "/api/daily-reports/ap-aging", "needs": "bills"},
        {"name": "פירוק ספקים", "route": "/api/daily-reports/suppliers", "needs": "bills"},
     ]},
    {"key": "reports", "title": "דוחות (יומי + תקופתי)", "icon": "FileSpreadsheet", "nature": DERIVED,
     "capabilities": [
        {"name": "רווח/הפסד מצטבר יומי", "route": "/api/daily-reports/cumulative-pl", "needs": "docs"},
        {"name": "דוח מע\"מ תקופתי", "route": "/api/daily-reports/vat", "needs": "docs"},
        {"name": "מאזן + רווח/הפסד + תזרים", "route": "/api/reports/profit-loss", "needs": "docs"},
     ]},
    {"key": "annual", "title": "דוחות שנתיים (טיוטה)", "icon": "FileWarning", "nature": DERIVED,
     "capabilities": [
        {"name": "טיוטת 1301 (יחיד)", "route": "/api/annual-reports/1301", "needs": "docs"},
        {"name": "טיוטת 1214 (חברה)", "route": "/api/annual-reports/1214", "needs": "docs"},
     ]},
    {"key": "payroll", "title": "שכר (Payroll)", "icon": "Users", "nature": REAL,
     "capabilities": [
        {"name": "עובדים ותלושים", "route": "/api/payroll/payslips", "needs": "employees"},
        {"name": "דוח 102", "route": "/api/payroll/reports/102", "needs": "employees"},
        {"name": "דוח 126 שנתי", "route": "/api/payroll/reports/126", "needs": "employees"},
     ]},
    {"key": "tax", "title": "מיסוי וחישובים", "icon": "Calculator", "nature": PARTIAL,
     "capabilities": [
        {"name": "16 מחשבונים דטרמיניסטיים", "route": "/api/calculators", "needs": None},
        {"name": "עמדת מע\"מ (עסקאות/תשומות)", "route": "/api/daily-reports/vat", "needs": "docs"},
     ]},
    {"key": "bank", "title": "בנק והתאמות (Open Finance)", "icon": "Landmark", "nature": BLOCKED,
     "capabilities": [
        {"name": "תובנות מדפי הבנק", "route": "/api/open-finance/insights", "needs": "bank"},
        {"name": "התאמות בנק", "route": "/api/open-finance/reconcile", "needs": "bank"},
     ]},
    {"key": "payments", "title": "תשלומים (מס\"ב)", "icon": "Banknote", "nature": REAL,
     "capabilities": [
        {"name": "קובץ מס\"ב", "route": "/api/masav/generate", "needs": "sumit"},
     ]},
    {"key": "anomalies", "title": "בקרת איכות — מסמכים חריגים", "icon": "AlertTriangle", "nature": REAL,
     "capabilities": [
        {"name": "זיהוי חריגות", "route": "/api/engine/anomalies", "needs": "docs"},
     ]},
    {"key": "engine", "title": "המנוע המאחד", "icon": "Cpu", "nature": DERIVED,
     "capabilities": [
        {"name": "סטטוס + ריצת pipeline", "route": "/api/engine/run", "needs": "docs"},
     ]},
]


def build_menu(db, organization_id: int) -> dict[str, Any]:
    from . import engine_service
    from ..models import Organization

    st = engine_service.status(db, organization_id)
    counts = st["counts"]
    have = {
        "docs": (counts["invoices"] + counts["bills"] + counts["expenses"]) > 0,
        "invoices": counts["invoices"] > 0,
        "bills": counts["bills"] > 0,
        "employees": counts["employees"] > 0,
        "bank": st["connections"]["open_finance"] and st["bank_data_validated"],
        "sumit": st["connections"]["sumit"],
    }

    def _status(need) -> tuple[str, str]:
        if need is None:
            return REAL, "זמין תמיד"
        if need == "bank" and not st["connections"]["open_finance"]:
            return BLOCKED, "דורש חיבור Open Finance"
        if need == "bank" and not st["bank_data_validated"]:
            return BLOCKED, "דורש מסע consent ואימות נתון בנק חי"
        if have.get(need):
            return "ready", "פעיל — יש נתונים"
        labels = {"docs": "אין מסמכים מסונכרנים", "invoices": "אין חשבוניות",
                  "bills": "אין חשבונות ספק", "employees": "לא הוזנו עובדים",
                  "sumit": "SUMIT לא מחובר"}
        return "needs_data", labels.get(need, "דורש נתונים")

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    sections = []
    total = ready = blocked = 0
    for section in CATALOG:
        caps = []
        for cap in section["capabilities"]:
            state, note = _status(cap.get("needs"))
            caps.append({"name": cap["name"], "route": cap["route"],
                         "state": state, "note": note})
            total += 1
            if state == "ready" or (state == REAL and cap.get("needs") is None):
                ready += 1
            elif state == BLOCKED:
                blocked += 1
        sections.append({
            "key": section["key"], "title": section["title"], "icon": section["icon"],
            "nature": section["nature"], "capabilities": caps,
        })

    return {
        "organization_id": organization_id,
        "business_name": org.name if org else f"Org {organization_id}",
        "connections": st["connections"],
        "bank_data_validated": st["bank_data_validated"],
        "sections": sections,
        "summary": {"total": total, "ready": ready, "blocked": blocked},
    }
