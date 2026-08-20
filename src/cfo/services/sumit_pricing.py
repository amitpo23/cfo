"""מנוע המחירון של SUMIT — הקאונטר יודע תמיד אם חורגים ומה העלות.

מקור אמת: מאמר 5507895 "איך עובד המחירון" (docs/sumit_help_kb/02):
- מודל דו-שכבתי: מסלול (מודולים + פעולות כלולות) + חיוב חריגה בפועל.
- קריאות API כלולות = **פי 5** ממכסת הפעולות של המסלול.
- חריגת קריאת API = **25% ממחיר פעולה**.
- חריגת אחסון = **5 ש"ח ל-GB לחודש**.
- פעולה משולבת (למשל מסמך+סליקה) נספרת כ-**2 פעולות**.

honest-null מחייב: מחיר הפעולה עצמו יושב בדף המחירון החיצוני פר-מסלול
ואינו בתיעוד העזרה. בלי `sumit_plan_action_price_ils` מוגדר — הקאונטר
מציג את החריגה בכמויות ואת הנוסחה, לעולם לא שקלים מומצאים.
"""
from __future__ import annotations

from typing import Any, Optional

# יחסי המחירון המתועדים (מאמר 5507895)
API_CALLS_PER_ACTION_RATIO = 5
API_OVERAGE_PRICE_RATIO = 0.25
STORAGE_OVERAGE_ILS_PER_GB = 5.0
COMBINED_ACTION_COUNT = 2

PRICING_MODEL_SUMMARY = {
    "source": "https://help.sumit.co.il/he/articles/5507895",
    "included_api_calls_rule": "קריאות API כלולות = פי 5 ממכסת הפעולות של המסלול",
    "api_overage_rule": "חריגת קריאת API = 25% ממחיר פעולה",
    "storage_overage_rule": f"חריגת אחסון = {STORAGE_OVERAGE_ILS_PER_GB:.0f} ש\"ח ל-GB לחודש",
    "combined_action_rule": "פעולה משולבת (מסמך+סליקה) נספרת כ-2 פעולות",
    "renewal_trap": "המנוי מתחדש אוטומטית — שנמוך מסלול חייב להיעשות לפני מועד החיוב",
}


def included_api_calls(*, included_actions: int) -> int:
    return int(included_actions) * API_CALLS_PER_ACTION_RATIO


def estimate_costs(
    *,
    actions_used: int,
    actions_included: int,
    api_calls_used: int = 0,
    action_price_ils: Optional[float] = None,
) -> dict[str, Any]:
    """אומדן עלות חריגה לפי מודל המחירון. אין מחיר מוגדר ⇒ כמויות בלבד."""
    actions_overage = max(0, int(actions_used) - int(actions_included))
    api_included = included_api_calls(included_actions=actions_included)
    api_overage = max(0, int(api_calls_used) - api_included)

    if action_price_ils is None:
        return {
            "actions_overage": actions_overage,
            "api_calls_included": api_included,
            "api_calls_overage": api_overage,
            "actions_overage_cost_ils": None,
            "api_calls_overage_cost_ils": None,
            "total_estimated_overage_ils": None,
            "priced": False,
            "reason": (
                "מחיר הפעולה של המסלול אינו מוגדר (SUMIT_PLAN_ACTION_PRICE_ILS) "
                "— המחיר נמצא בדף המחירון של המסלול, לא בתיעוד. הקאונטר מציג "
                "חריגה בכמויות בלבד; לא מציגים שקלים מומצאים."
            ),
        }

    price = float(action_price_ils)
    actions_cost = round(actions_overage * price, 2)
    api_cost = round(api_overage * price * API_OVERAGE_PRICE_RATIO, 2)
    return {
        "actions_overage": actions_overage,
        "api_calls_included": api_included,
        "api_calls_overage": api_overage,
        "actions_overage_cost_ils": actions_cost,
        "api_calls_overage_cost_ils": api_cost,
        "total_estimated_overage_ils": round(actions_cost + api_cost, 2),
        "priced": True,
        "action_price_ils": price,
    }
