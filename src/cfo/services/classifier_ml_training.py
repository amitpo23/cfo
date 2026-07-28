"""
ML classifier training — use feedback loop to retrain and improve categorization.

Reads classifier_feedback from Expense records and trains a lightweight
classifier (using regex + word frequency instead of heavy ML frameworks).

Future: can integrate sklearn/spacy for more sophisticated models.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Expense
from .expense_classifier import normalize_supplier_key

logger = logging.getLogger(__name__)

# סף התיקונים לאותו ספק+קטגוריה-חדשה שמעליו כלל נלמד נחשב "בטוח מספיק"
# להיכנס לשימוש בסיווג בפועל (ר' get_learned_rules / חבילה I, 2026-07-27).
MIN_CORRECTIONS_FOR_RULE = 3


class ClassifierMLTrainingService:
    """Learn from user feedback to improve expense classification."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def _feedback_expenses(self) -> list[Expense]:
        """הוצאות הארגון שיש להן לפחות רשומת classifier_feedback אחת —
        שאילתת הבסיס המשותפת לכל מתודות המודול (org-scoped תמיד)."""
        return (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.classifier_feedback.isnot(None),
            )
            .all()
        )

    def analyze_feedback(self) -> dict[str, Any]:
        """Analyze all classifier feedback to identify patterns."""
        expenses = self._feedback_expenses()

        patterns = defaultdict(lambda: {"correct": [], "incorrect": []})
        total_feedback = 0

        for exp in expenses:
            feedback_list = exp.classifier_feedback or []
            for feedback in feedback_list:
                if not isinstance(feedback, dict):
                    continue
                total_feedback += 1

                old_cat = feedback.get("old_category")
                new_cat = feedback.get("new_category")
                # feedback_text/supplier may be present with an explicit
                # None value (record_classifier_feedback's default), not
                # just absent — `.get(key, "")` only covers the "missing
                # key" case, so a stored None still reaches `.lower()` and
                # raises. `or ""` covers both.
                supplier = (feedback.get("supplier") or "").lower()
                text = (feedback.get("feedback_text") or "").lower()

                # Track: supplier + old_cat → new_cat (user corrected us)
                if old_cat != new_cat:
                    patterns[new_cat]["incorrect"].append({
                        "supplier": supplier,
                        "was_predicted": old_cat,
                        "text": text,
                    })

        # Identify high-confidence corrections
        high_confidence_updates = {}
        for category, corrections in patterns.items():
            incorrect = corrections["incorrect"]
            if len(incorrect) >= 3:  # At least 3 corrections
                # Extract common supplier names for this category
                suppliers = Counter(c["supplier"] for c in incorrect if c["supplier"])
                if suppliers.most_common(1):
                    most_common_supplier = suppliers.most_common(1)[0][0]
                    high_confidence_updates[most_common_supplier] = category

        return {
            "total_feedback_records": total_feedback,
            "patterns_discovered": len(patterns),
            "high_confidence_updates": high_confidence_updates,
            "patterns": dict(patterns),
        }

    def generate_updated_keywords(self) -> dict[str, Any]:
        """Generate updated keyword mappings from feedback."""
        analysis = self.analyze_feedback()
        high_conf = analysis.get("high_confidence_updates", {})

        # These would be merged into CATEGORY_KEYWORDS in expense_classifier.py
        updated_keywords = {}
        for supplier, category in high_conf.items():
            if category not in updated_keywords:
                updated_keywords[category] = []
            updated_keywords[category].append(supplier)

        return {
            "updated_keywords": updated_keywords,
            "confidence_threshold": "3+ user corrections",
            "note": "Merge these into CATEGORY_KEYWORDS in expense_classifier.py",
        }

    def export_training_data(self, output_path: Optional[str] = None) -> dict[str, Any]:
        """Export feedback as training data for external ML model."""
        expenses = self._feedback_expenses()

        training_data = {
            "metadata": {
                "organization_id": self.organization_id,
                "total_samples": 0,
            },
            "samples": [],
        }

        for exp in expenses:
            feedback_list = exp.classifier_feedback or []
            for feedback in feedback_list:
                if not isinstance(feedback, dict):
                    continue

                sample = {
                    "supplier": exp.supplier_name or "Unknown",
                    "description": exp.description or "",
                    "true_category": feedback.get("new_category"),
                    "predicted_category": feedback.get("old_category"),
                    "user_feedback": feedback.get("feedback_text", ""),
                }
                training_data["samples"].append(sample)

        training_data["metadata"]["total_samples"] = len(training_data["samples"])

        if output_path:
            with open(output_path, "w") as f:
                json.dump(training_data, f, indent=2, ensure_ascii=False)
            logger.info("Exported %d training samples to %s", len(training_data["samples"]), output_path)

        return training_data

    def recommend_classifier_update(self) -> dict[str, Any]:
        """Recommend when to retrain classifier."""
        expenses = self._feedback_expenses()

        total_expenses = self.db.query(Expense).filter(
            Expense.organization_id == self.organization_id,
        ).count()

        total_feedback = sum(len(e.classifier_feedback or []) for e in expenses)
        feedback_ratio = total_feedback / total_expenses if total_expenses > 0 else 0

        recommendation = {
            "total_expenses": total_expenses,
            "with_feedback": len(expenses),
            "feedback_records": total_feedback,
            "feedback_ratio": round(feedback_ratio, 4),
            "should_retrain": feedback_ratio >= 0.1,  # Retrain if 10%+ have feedback
            "reason": None,
        }

        if feedback_ratio >= 0.1:
            recommendation["reason"] = "Significant user corrections detected — classifier should be retrained"
        elif feedback_ratio >= 0.05:
            recommendation["reason"] = "Moderate corrections — monitor before retraining"
        else:
            recommendation["reason"] = "Insufficient feedback data for meaningful retraining"

        return recommendation

    # ---------- learned rules (חבילה I, 2026-07-27: סגירת לולאת הלמידה) ----------
    #
    # NOTE: analyze_feedback's own `high_confidence_updates` is NOT reused here
    # on purpose — it counts corrections per *new_category* across ALL
    # suppliers (`len(incorrect) >= 3`) and then arbitrarily keeps
    # `most_common(1)` supplier, so 3 corrections spread across 3 different
    # suppliers wrongly mint a rule backed by a single correction each, and a
    # second supplier that legitimately hit 3 corrections on its own gets
    # silently dropped. get_learned_rules below counts strictly per
    # (normalized supplier, new_category) instead, which is what "3
    # corrections for the same supplier" actually means.

    def get_learned_rules(self) -> dict[str, Any]:
        """כללים נלמדים לפי ספק, מתוך תיקוני משתמש (classifier_feedback) של
        הארגון הזה בלבד (הבידוד: כל שאילתה כאן ממילא מסוננת ב-
        organization_id דרך _feedback_expenses — ר' __init__).

        לכל ספק (מנורמל: normalize_supplier_key — strip+lower) סופרים כמה
        פעמים תוקן ל-כל קטגוריה-חדשה (מתעלמים מ-old_category==new_category,
        שאינו תיקון אמיתי). קטגוריה הופכת לכלל נלמד בפועל רק כשהיא הגיעה
        ל-MIN_CORRECTIONS_FOR_RULE (3) תיקונים. אם לספק יש כמה קטגוריות
        מתחרות שכולן חצו את הסף — המנצחת: הכי הרבה תיקונים; שוויון נשבר לפי
        התיקון האחרון (timestamp מאוחר יותר).

        מחזיר גם 'below_threshold': לכל ספק שהקטגוריה המובילה שלו עוד לא
        הגיעה לסף — כמה תיקונים חסרים לה, כדי שהמשתמש יראה גם מה עוד לא הפך
        לכלל (שקיפות — ר' כלי הצ'אט get_learned_rules ב-ai_chat_tools.py).
        """
        # supplier_key -> new_category -> {"count": int, "last_ts": str}
        counts: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"count": 0, "last_ts": ""})
        )
        for exp in self._feedback_expenses():
            for feedback in exp.classifier_feedback or []:
                if not isinstance(feedback, dict):
                    continue
                old_cat = feedback.get("old_category")
                new_cat = feedback.get("new_category")
                if not new_cat or old_cat == new_cat:
                    continue  # לא תיקון אמיתי — אין ממנו מה ללמוד
                supplier_key = normalize_supplier_key(feedback.get("supplier"))
                if not supplier_key:
                    continue  # ספק None/ריק — אין לפי מה להתאים בעתיד
                ts = feedback.get("timestamp") or ""
                bucket = counts[supplier_key][new_cat]
                bucket["count"] += 1
                if ts >= bucket["last_ts"]:
                    bucket["last_ts"] = ts

        rules: dict[str, dict[str, Any]] = {}
        below_threshold: list[dict[str, Any]] = []
        for supplier_key, cat_counts in counts.items():
            best_cat, best = max(
                cat_counts.items(), key=lambda kv: (kv[1]["count"], kv[1]["last_ts"])
            )
            if best["count"] >= MIN_CORRECTIONS_FOR_RULE:
                rules[supplier_key] = {
                    "category": best_cat,
                    "correction_count": best["count"],
                }
            else:
                below_threshold.append({
                    "supplier": supplier_key,
                    "category": best_cat,
                    "correction_count": best["count"],
                    "corrections_needed": MIN_CORRECTIONS_FOR_RULE - best["count"],
                })

        return {
            "rules": rules,
            "below_threshold": below_threshold,
            "min_corrections": MIN_CORRECTIONS_FOR_RULE,
        }

    def get_learned_rules_map(self) -> dict[str, str]:
        """מפה פשוטה supplier_key -> category, מוכנה לצריכה ישירה ע"י
        expense_classifier.classify_expense(learned_rules=...). נועדה
        להיטען פעם אחת בתחילת ריצת סיווג גורפת (למשל
        ExpenseFilingService.classify_pending), לא פר-הוצאה בתוך הלולאה —
        analyze_feedback/get_learned_rules סורקים את כל ה-Expense-ים עם
        feedback של הארגון, ואין טעם לחזור על זה בכל איטרציה."""
        return {
            supplier_key: info["category"]
            for supplier_key, info in self.get_learned_rules()["rules"].items()
        }
