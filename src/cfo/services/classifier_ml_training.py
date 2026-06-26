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

logger = logging.getLogger(__name__)


class ClassifierMLTrainingService:
    """Learn from user feedback to improve expense classification."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def analyze_feedback(self) -> dict[str, Any]:
        """Analyze all classifier feedback to identify patterns."""
        expenses = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.classifier_feedback.isnot(None),
            )
            .all()
        )

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
                supplier = feedback.get("supplier", "").lower()
                text = feedback.get("feedback_text", "").lower()

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
        expenses = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.classifier_feedback.isnot(None),
            )
            .all()
        )

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
        expenses = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.classifier_feedback.isnot(None),
            )
            .all()
        )

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
