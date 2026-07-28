"""חבילה I (2026-07-27) — סגירת לולאת הלמידה בסיווג הוצאות.

הפער שאומת: expenses.classifier_feedback נכתב (manual_reconciliation.
record_classifier_feedback) ונותח (classifier_ml_training.analyze_feedback),
אבל expense_classifier.classify_expense מעולם לא צרך את התוצר — היה פידבק,
לא הייתה למידה. הקובץ הזה בודק שהלולאה נסגרה: כלל נלמד (>=3 תיקונים לאותו
ספק) משפיע בפועל על סיווג עתידי, בלי לעקוף כלל מפורש של המשתמש ובלי לדלוף
בין ארגונים.
"""
import asyncio
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import Expense
from cfo.services.ai_chat_tools import TOOLS
from cfo.services.classifier_ml_training import (
    MIN_CORRECTIONS_FOR_RULE,
    ClassifierMLTrainingService,
)
from cfo.services.expense_classifier import classify_expense, classify_expense_detailed
from cfo.services.manual_reconciliation import ManualReconciliationService


def _make_expense(db, org_id, supplier, category, **extra):
    exp = Expense(
        organization_id=org_id,
        supplier_name=supplier,
        amount=100,
        vat_amount=18,
        total=118,
        expense_date=date(2026, 6, 1),
        category=category,
        **extra,
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def _correct(db, org_id, expense, new_category, feedback_text=None):
    """מדמה תיקון משתמש דרך הזרימה האמיתית (לא מזריק classifier_feedback
    ידנית) — כדי שהבדיקות יעברו דרך אותה שכבה שבאמת רושמת פידבק."""
    service = ManualReconciliationService(db, organization_id=org_id)
    return service.record_classifier_feedback(
        expense.id, "expense", new_category, feedback_text=feedback_text,
    )


# ---------------------------------------------------------------------- #
# סף הלמידה: 2 תיקונים -> אין כלל, 3 -> יש כלל
# ---------------------------------------------------------------------- #

def test_two_corrections_are_below_threshold_no_learned_rule(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for _ in range(2):
            exp = _make_expense(db, org_id, "ספק מבחן א", "office")
            _correct(db, org_id, exp, "professional")

        rules_map = ClassifierMLTrainingService(db, org_id).get_learned_rules_map()
        assert "ספק מבחן א" not in rules_map

        result = ClassifierMLTrainingService(db, org_id).get_learned_rules()
        assert result["rules"] == {}
        below = {b["supplier"]: b for b in result["below_threshold"]}
        assert below["ספק מבחן א"]["correction_count"] == 2
        assert below["ספק מבחן א"]["corrections_needed"] == 1
    finally:
        db.close()


def test_three_corrections_create_a_learned_rule(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for _ in range(MIN_CORRECTIONS_FOR_RULE):
            exp = _make_expense(db, org_id, "ספק מבחן ב", "office")
            _correct(db, org_id, exp, "professional")

        result = ClassifierMLTrainingService(db, org_id).get_learned_rules()
        assert result["rules"]["ספק מבחן ב"] == {
            "category": "professional",
            "correction_count": 3,
        }
        assert result["min_corrections"] == MIN_CORRECTIONS_FOR_RULE
    finally:
        db.close()


def test_repeated_corrections_on_the_same_expense_all_persist(fresh_org):
    """שומר-רגרסיה ל-manual_reconciliation.record_classifier_feedback:
    classifier_feedback הוא עמודת JSON רגילה (לא MutableList.as_mutable),
    כך שלפני התיקון .append() במקום לא סימן את העמודה כ'מלוכלכת' ורק
    התיקון *הראשון* נשמר בפועל (הוא היחיד שכלל גם assignment של `= []`).
    כאן מתקנים את *אותה* הוצאה שוב ושוב — זו הדרך היחידה לתפוס את הבאג,
    בניגוד לבדיקות אחרות בקובץ שיוצרות הוצאה חדשה לכל תיקון."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _make_expense(db, org_id, "ספק חוזר", "office")
        _correct(db, org_id, exp, "professional")
        _correct(db, org_id, exp, "travel")
        _correct(db, org_id, exp, "professional")

        db.refresh(exp)  # קורא מחדש מה-DB, לא מה-identity map
        assert len(exp.classifier_feedback) == 3
        new_cats = [f["new_category"] for f in exp.classifier_feedback]
        assert new_cats == ["professional", "travel", "professional"]

        # ושכל התיקונים האלה נספרים (לא רק האחרון): get_learned_rules עוקב
        # לפי (ספק, קטגוריה-חדשה) ומציג את הקטגוריה המובילה של הספק —
        # "professional" (2 תיקונים) מובילה על "travel" (תיקון אחד).
        result = ClassifierMLTrainingService(db, org_id).get_learned_rules()
        below = [b for b in result["below_threshold"] if b["supplier"] == "ספק חוזר"]
        assert len(below) == 1
        assert below[0]["category"] == "professional"
        assert below[0]["correction_count"] == 2
        assert below[0]["corrections_needed"] == 1
    finally:
        db.close()


def test_learned_rule_tie_break_is_by_correction_count_not_dict_order(fresh_org):
    """ספק עם 3 תיקונים ל-travel ו-4 תיקונים ל-vehicle -> vehicle מנצח
    (הכי הרבה תיקונים), לא בגלל סדר איטרציה על dict."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        supplier = "ספק דו-משמעי"
        for _ in range(3):
            exp = _make_expense(db, org_id, supplier, "office")
            _correct(db, org_id, exp, "travel")
        for _ in range(4):
            exp = _make_expense(db, org_id, supplier, "office")
            _correct(db, org_id, exp, "vehicle")

        result = ClassifierMLTrainingService(db, org_id).get_learned_rules()
        assert result["rules"][supplier] == {"category": "vehicle", "correction_count": 4}
        # travel לא מופיע כלל נלמד נפרד — רק vehicle (המנצחת) נכנסת ל-rules
        assert supplier not in [b["supplier"] for b in result["below_threshold"]]
    finally:
        db.close()


def test_sumit_item_name_still_beats_learned_rule():
    """שם פריט SUMIT הוא האות האמין ביותר — נשאר בעדיפות עליונה גם מול
    כלל נלמד לאותו ספק (לא רק מול כרטיס מותאם אישית/מילות מפתח)."""
    learned_rules = {"ספק כללי": "professional"}
    result = classify_expense_detailed(
        "ספק כללי", None, None,
        sumit_item_name="הוצאות נסיעה", learned_rules=learned_rules,
    )
    assert result["category"] == "travel"
    assert result["classification_source"] == "sumit_item"


# ---------------------------------------------------------------------- #
# הוצאה חדשה מאותו ספק מסווגת לפי הכלל הנלמד, ומסומנת כ-learned
# ---------------------------------------------------------------------- #

def test_new_expense_from_same_supplier_uses_learned_rule(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # שם ספק בלי שום מילת מפתח מובנית — כך שרק כלל נלמד (לא CATEGORY_
        # KEYWORDS) יכול להוביל לתשובה הנכונה.
        supplier_no_keywords = "אקמה השקעות בע\"מ"
        exp2 = _make_expense(db, org_id, supplier_no_keywords, "office")
        _correct(db, org_id, exp2, "professional")
        exp3 = _make_expense(db, org_id, supplier_no_keywords, "office")
        _correct(db, org_id, exp3, "professional")
        exp4 = _make_expense(db, org_id, supplier_no_keywords, "office")
        _correct(db, org_id, exp4, "professional")

        learned_rules = ClassifierMLTrainingService(db, org_id).get_learned_rules_map()
        assert learned_rules[supplier_no_keywords.strip().lower()] == "professional"

        detailed = classify_expense_detailed(
            supplier_no_keywords, None, None, learned_rules=learned_rules,
        )
        assert detailed["category"] == "professional"
        assert detailed["classification_source"] == "learned"

        # classify_expense (המחרוזת, נקודת הכניסה הרגילה) עקבית עם זה
        assert classify_expense(
            supplier_no_keywords, None, None, learned_rules=learned_rules,
        ) == "professional"
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# רגרסיה קריטית: כלל מפורש של המשתמש (כרטיס מותאם אישית) גובר על כלל נלמד
# ---------------------------------------------------------------------- #

def test_explicit_org_category_wins_over_learned_rule(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        supplier = "ספק עם כלל מפורש"
        for _ in range(MIN_CORRECTIONS_FOR_RULE):
            exp = _make_expense(db, org_id, supplier, "office")
            _correct(db, org_id, exp, "professional")

        learned_rules = ClassifierMLTrainingService(db, org_id).get_learned_rules_map()
        assert learned_rules[supplier.strip().lower()] == "professional"

        # כרטיס מותאם אישית של המשתמש שמצביע על קטגוריה אחרת לגמרי
        org_categories = [{"key": "vip_supplier_card", "keywords": [supplier]}]

        result = classify_expense_detailed(
            supplier, None, None,
            org_categories=org_categories, learned_rules=learned_rules,
        )
        assert result["category"] == "vip_supplier_card"
        assert result["classification_source"] == "org_category"
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# בידוד ארגונים — הבדיקה החשובה ביותר
# ---------------------------------------------------------------------- #

def test_learned_rule_does_not_leak_across_organizations(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        supplier = "ספק משותף בין ארגונים"
        for _ in range(MIN_CORRECTIONS_FOR_RULE):
            exp = _make_expense(db, org_a, supplier, "office")
            _correct(db, org_a, exp, "professional")

        rules_a = ClassifierMLTrainingService(db, org_a).get_learned_rules_map()
        rules_b = ClassifierMLTrainingService(db, org_b).get_learned_rules_map()

        assert rules_a[supplier.strip().lower()] == "professional"
        assert rules_b == {}  # ארגון ב' לא רואה כלום מארגון א'

        # וגם בפועל: סיווג באותו שם ספק עם המפה של ארגון ב' לא משתמש בכלל
        result = classify_expense_detailed(supplier, None, None, learned_rules=rules_b)
        assert result["classification_source"] != "learned"
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# set_expense_category (מושקו) רושם classifier_feedback
# ---------------------------------------------------------------------- #

def test_set_expense_category_tool_records_classifier_feedback(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _make_expense(db, org_id, "ספק דרך מושקו", "office")

        result = asyncio.run(
            TOOLS["set_expense_category"].fn(
                db, org_id, expense_id=exp.id, category="professional",
            )
        )
        assert result["category"] == "professional"

        db.refresh(exp)
        assert exp.category == "professional"
        assert exp.classifier_feedback is not None
        assert len(exp.classifier_feedback) == 1
        assert exp.classifier_feedback[0]["old_category"] == "office"
        assert exp.classifier_feedback[0]["new_category"] == "professional"
    finally:
        db.close()


def test_set_expense_category_tool_rejects_unknown_category(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _make_expense(db, org_id, "ספק דרך מושקו 2", "office")
        with pytest.raises(ValueError):
            asyncio.run(
                TOOLS["set_expense_category"].fn(
                    db, org_id, expense_id=exp.id, category="לא-קיים-בכלל",
                )
            )
        db.refresh(exp)
        # קטגוריה לא השתנתה ולא נרשם פידבק על קטגוריה לא-תקפה
        assert exp.category == "office"
        assert not exp.classifier_feedback
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# get_learned_rules (כלי צ'אט) — כללים + ספירות מתחת לסף
# ---------------------------------------------------------------------- #

def test_get_learned_rules_tool_reports_rules_and_below_threshold(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for _ in range(MIN_CORRECTIONS_FOR_RULE):
            exp = _make_expense(db, org_id, "ספק עם כלל", "office")
            _correct(db, org_id, exp, "professional")
        for _ in range(1):
            exp = _make_expense(db, org_id, "ספק בלי כלל עדיין", "office")
            _correct(db, org_id, exp, "marketing")

        result = asyncio.run(TOOLS["get_learned_rules"].fn(db, org_id))

        assert result["min_corrections_required"] == MIN_CORRECTIONS_FOR_RULE
        rules_by_supplier = {r["supplier"]: r for r in result["learned_rules"]}
        assert rules_by_supplier["ספק עם כלל"]["category"] == "professional"
        assert rules_by_supplier["ספק עם כלל"]["correction_count"] == 3

        below_by_supplier = {b["supplier"]: b for b in result["below_threshold"]}
        assert below_by_supplier["ספק בלי כלל עדיין"]["correction_count"] == 1
        assert below_by_supplier["ספק בלי כלל עדיין"]["corrections_needed"] == 2
    finally:
        db.close()


def test_get_learned_rules_tool_is_read_category():
    assert TOOLS["get_learned_rules"].category == "read"


# ---------------------------------------------------------------------- #
# עמידות: ספק None/ריק לא מפיל כלום
# ---------------------------------------------------------------------- #

def test_none_or_blank_supplier_does_not_crash_learning_or_classification(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # Expense.supplier_name הוא NOT NULL ב-DB, אז ה"ריק" האמיתי שנבדק
        # כאן הוא מחרוזת ריקה/רווחים — אבל record_classifier_feedback עצמו
        # קורא ל-exp.supplier_name (יכול להיות None בעקרון בכל מודל אחר),
        # ולכן חשוב שגם normalize_supplier_key(None) לא יקרוס (ר' למטה).
        exp_blank = _make_expense(db, org_id, "   ", "office")
        _correct(db, org_id, exp_blank, "professional")
        from cfo.services.expense_classifier import normalize_supplier_key
        assert normalize_supplier_key(None) == ""

        result = ClassifierMLTrainingService(db, org_id).get_learned_rules()
        # אף כלל וגם אף ערך "מתחת-לסף" לא נבנה משם ספק ריק/None
        assert "" not in result["rules"]
        assert all(b["supplier"] for b in result["below_threshold"])

        # וגם classify_expense עם ספק None לא קורס, גם כשיש learned_rules
        learned_rules = ClassifierMLTrainingService(db, org_id).get_learned_rules_map()
        assert classify_expense(None, None, None, learned_rules=learned_rules) == "other"
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# אין רגרסיה: הוצאה בלי היסטוריית תיקונים מסווגת בדיוק כמו קודם
# ---------------------------------------------------------------------- #

@pytest.mark.parametrize("supplier,desc,expected", [
    ("עו\"ד כהן", None, "professional"),
    ("תחנת דלק פז", None, "vehicle"),
    ("חברת חשמל", None, "utilities"),
    ("Google Ads", None, "marketing"),
    ("משהו אקראי לגמרי", None, "other"),
])
def test_no_regression_without_feedback_history(supplier, desc, expected):
    # קריאה בלי learned_rules בכלל — ההתנהגות הקיימת (str) חייבת להישאר זהה.
    assert classify_expense(supplier, desc) == expected
    # וגם עם learned_rules ריק/None מפורש — אותה תוצאה בדיוק.
    assert classify_expense(supplier, desc, learned_rules={}) == expected
    assert classify_expense(supplier, desc, learned_rules=None) == expected


def test_no_regression_empty_learned_rules_does_not_change_source():
    detailed_without = classify_expense_detailed("תחנת דלק פז", None, None)
    detailed_with_empty = classify_expense_detailed(
        "תחנת דלק פז", None, None, learned_rules={},
    )
    assert detailed_without == detailed_with_empty
    assert detailed_without["classification_source"] == "keyword"
