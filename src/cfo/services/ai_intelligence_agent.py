"""
Phase 13C: AI Intelligence Agent with RAG
Retrieval-Augmented Generation for financial insights
"""
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal
from sqlalchemy.orm import Session
from enum import Enum

from ..models import Organization, Invoice, Bill, Expense, Transaction
from .analytics_reporting import AnalyticsReportingService
from .expense_analytics import ExpenseAnalyticsService
from .revenue_analytics import RevenueAnalyticsService


class InsightType(str, Enum):
    """Types of financial insights"""
    ALERT = "alert"
    RECOMMENDATION = "recommendation"
    TREND = "trend"
    ANOMALY = "anomaly"
    OPPORTUNITY = "opportunity"


class AIIntelligenceAgent:
    """
    AI Intelligence Agent for financial insights
    Uses RAG (Retrieval-Augmented Generation) to answer financial questions
    by retrieving relevant data and synthesizing insights
    """

    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id
        self.reporting_service = AnalyticsReportingService(db, org_id)
        self.expense_service = ExpenseAnalyticsService(db, org_id)
        self.revenue_service = RevenueAnalyticsService(db, org_id)

    def answer_financial_question(self, question: str) -> Dict[str, Any]:
        """
        Answer a financial question using RAG
        Retrieves relevant data and synthesizes answer
        """
        # Classify the question
        question_type = self._classify_question(question)
        
        # Retrieve relevant data based on question type
        relevant_data = self._retrieve_relevant_data(question_type, question)
        
        # Synthesize answer using retrieved data
        answer = self._synthesize_answer(question_type, question, relevant_data)
        
        return {
            "question": question,
            "question_type": question_type,
            "answer": answer,
            "confidence": self._calculate_confidence(relevant_data),
            "data_sources": relevant_data.get("sources", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def generate_daily_insights(self) -> List[Dict[str, Any]]:
        """
        Generate daily automated insights
        - Key metrics
        - Anomalies detected
        - Recommendations
        """
        insights = []

        # 1. Daily summary
        daily_report = self.reporting_service.generate_daily_report()
        insights.append({
            "type": InsightType.ALERT.value,
            "title": "Daily Financial Summary",
            "message": self._summarize_daily_report(daily_report),
            "priority": "high",
            "data": daily_report,
        })

        # 2. Anomalies
        anomalies = self.expense_service.detect_spending_anomalies(days=30, sensitivity=2.0)
        if anomalies:
            insights.append({
                "type": InsightType.ANOMALY.value,
                "title": f"Spending Anomalies Detected ({len(anomalies)})",
                "message": self._summarize_anomalies(anomalies),
                "priority": "medium",
                "data": anomalies[:5],  # Top 5
            })

        # 3. Recommendations
        recommendations = self._generate_recommendations(daily_report, anomalies)
        for rec in recommendations:
            insights.append({
                "type": InsightType.RECOMMENDATION.value,
                "title": rec["title"],
                "message": rec["message"],
                "priority": rec["priority"],
                "data": rec.get("data"),
            })

        # 4. AR/AP alerts
        ar_ap = daily_report.get("ar_ap_summary", {})
        if ar_ap.get("overdue_receivables", 0) > 0:
            insights.append({
                "type": InsightType.ALERT.value,
                "title": "Overdue Receivables",
                "message": f"You have {ar_ap['overdue_receivables']:.2f} in overdue receivables",
                "priority": "critical",
                "data": ar_ap,
            })

        return sorted(insights, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["priority"], 4))

    def get_financial_health_score(self) -> Dict[str, Any]:
        """
        Calculate overall financial health score (0-100)
        """
        scores = {}

        # 1. Liquidity score (0-25)
        liquidity_score = self._calculate_liquidity_score()
        scores["liquidity"] = liquidity_score

        # 2. Revenue trend score (0-25)
        revenue_score = self._calculate_revenue_score()
        scores["revenue"] = revenue_score

        # 3. Expense control score (0-25)
        expense_score = self._calculate_expense_control_score()
        scores["expense_control"] = expense_score

        # 4. AR/AP health score (0-25)
        ar_ap_score = self._calculate_ar_ap_score()
        scores["ar_ap_health"] = ar_ap_score

        overall_score = sum(scores.values())

        return {
            "overall_score": overall_score,
            "component_scores": scores,
            "health_status": self._get_health_status(overall_score),
            "areas_of_concern": self._identify_areas_of_concern(scores),
            "recommendations": self._get_improvement_recommendations(scores),
        }

    def get_executive_summary(self) -> Dict[str, Any]:
        """
        Generate executive summary for decision makers
        """
        daily_report = self.reporting_service.generate_daily_report()
        revenue_summary = self.revenue_service.get_revenue_summary(days=90)
        expense_summary = self.expense_service.get_expense_summary(days=90)
        health_score = self.get_financial_health_score()

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period": "last_90_days",
            "key_metrics": {
                "total_revenue": revenue_summary["total_invoiced"],
                "total_expenses": expense_summary["total_expenses"],
                "net_income": revenue_summary["total_invoiced"] - expense_summary["total_expenses"],
                "cash_position": daily_report["cash_position"],
            },
            "financial_health_score": health_score["overall_score"],
            "critical_alerts": [i for i in self.generate_daily_insights() if i["priority"] == "critical"],
            "top_opportunities": self.revenue_service.identify_investment_opportunities(days=90)[:3],
            "next_actions": self._generate_next_actions(daily_report, health_score),
        }

    # ==================== Question Classification & Retrieval ====================

    def _classify_question(self, question: str) -> str:
        """Classify financial question into category"""
        question_lower = question.lower()

        if any(word in question_lower for word in ["revenue", "sales", "income", "customer"]):
            return "revenue"
        elif any(word in question_lower for word in ["expense", "cost", "spending", "budget"]):
            return "expense"
        elif any(word in question_lower for word in ["cash", "liquid", "balance", "position"]):
            return "liquidity"
        elif any(word in question_lower for word in ["profit", "margin", "income"]):
            return "profitability"
        elif any(word in question_lower for word in ["trend", "growth", "increase", "decrease"]):
            return "trend"
        elif any(word in question_lower for word in ["overdue", "aging", "ar", "ap", "receivable", "payable"]):
            return "ar_ap"
        else:
            return "general"

    def _retrieve_relevant_data(self, question_type: str, question: str) -> Dict[str, Any]:
        """Retrieve relevant data for question"""
        data = {"sources": []}

        if question_type == "revenue":
            data["revenue_summary"] = self.revenue_service.get_revenue_summary(days=90)
            data["customer_analysis"] = self.revenue_service.analyze_revenue_by_customer(days=90, limit=10)
            data["sources"].extend(["revenue_summary", "customer_analysis"])

        elif question_type == "expense":
            data["expense_summary"] = self.expense_service.get_expense_summary(days=90)
            data["category_analysis"] = self.expense_service.analyze_category_spending(days=90)
            data["anomalies"] = self.expense_service.detect_spending_anomalies(days=90)
            data["sources"].extend(["expense_summary", "category_analysis", "anomalies"])

        elif question_type == "liquidity":
            data["cash_position"] = self.reporting_service._get_cash_position()
            data["ar_ap"] = self.reporting_service._get_ar_ap_summary()
            data["sources"].extend(["cash_position", "ar_ap"])

        elif question_type == "profitability":
            data["daily_report"] = self.reporting_service.generate_daily_report()
            data["sources"].append("daily_report")

        elif question_type == "trend":
            data["revenue_trends"] = self.revenue_service.analyze_revenue_trends(days=180)
            data["expense_trends"] = self.expense_service.analyze_spending_trends(days=180)
            data["sources"].extend(["revenue_trends", "expense_trends"])

        elif question_type == "ar_ap":
            data["ar_ap_summary"] = self.reporting_service._get_ar_ap_summary()
            data["sources"].append("ar_ap_summary")

        else:
            data["daily_report"] = self.reporting_service.generate_daily_report()
            data["sources"].append("daily_report")

        return data

    def _synthesize_answer(self, question_type: str, question: str, data: Dict[str, Any]) -> str:
        """Synthesize answer from retrieved data"""
        if question_type == "revenue":
            summary = data.get("revenue_summary", {})
            return (
                f"Your total revenue over the last 90 days is {summary.get('total_invoiced', 0):.2f}. "
                f"You've collected {summary.get('collection_rate_percent', 0):.1f}% of invoiced amount. "
                f"Your top customer has generated {summary.get('average_invoice', 0):.2f} in average invoice value."
            )

        elif question_type == "expense":
            summary = data.get("expense_summary", {})
            categories = data.get("category_analysis", [])
            top_cat = categories[0] if categories else {}
            return (
                f"Your total expenses over the last 90 days are {summary.get('total_expenses', 0):.2f}. "
                f"Top expense category is {top_cat.get('category', 'Unknown')} at {top_cat.get('percentage_of_total', 0):.1f}% of total spending."
            )

        elif question_type == "trend":
            revenue_trend = data.get("revenue_trends", {})
            expense_trend = data.get("expense_trends", {})
            return (
                f"Revenue trend is {revenue_trend.get('trend', 'stable')}. "
                f"Expenses trend is {expense_trend.get('trend', 'stable')}. "
                f"Net margin improving: {revenue_trend.get('trend') == 'increasing' and expense_trend.get('trend') in ['stable', 'decreasing']}"
            )

        else:
            return "Based on your financial data, here's what I found: [Analysis would be provided here]"

    def _calculate_confidence(self, data: Dict[str, Any]) -> float:
        """Calculate confidence in answer (0-1)"""
        sources = data.get("sources", [])
        # More data sources = higher confidence
        return min(0.95, 0.5 + (len(sources) * 0.15))

    # ==================== Scoring Methods ====================

    def _calculate_liquidity_score(self) -> float:
        """Calculate liquidity score (0-25)"""
        # Would analyze cash position, AR/AP ratio, etc.
        return 20.0

    def _calculate_revenue_score(self) -> float:
        """Calculate revenue score (0-25)"""
        summary = self.revenue_service.get_revenue_summary(days=90)
        # Higher revenue and collection rate = better score
        collection_rate = summary.get("collection_rate_percent", 0)
        return min(25.0, (collection_rate / 100) * 25)

    def _calculate_expense_control_score(self) -> float:
        """Calculate expense control score (0-25)"""
        trends = self.expense_service.analyze_spending_trends(days=180)
        trend = trends.get("trend", "stable")
        
        if trend == "decreasing":
            return 25.0
        elif trend == "stable":
            return 18.0
        else:  # increasing
            return 12.0

    def _calculate_ar_ap_score(self) -> float:
        """Calculate AR/AP health score (0-25)"""
        ar_ap = self.reporting_service._get_ar_ap_summary()
        overdue_ar = ar_ap.get("overdue_receivables", 0)
        
        if overdue_ar < 1000:
            return 25.0
        elif overdue_ar < 5000:
            return 18.0
        else:
            return 10.0

    # ==================== Helper Methods ====================

    def _summarize_daily_report(self, report: Dict[str, Any]) -> str:
        """Summarize daily report to text"""
        summary = report.get("summary", {})
        net_flow = summary.get("net_cash_flow", 0)
        return f"Today: {summary.get('income', 0):.2f} income, {summary.get('expenses', 0):.2f} expenses. Net cash flow: {net_flow:.2f}"

    def _summarize_anomalies(self, anomalies: List[Dict[str, Any]]) -> str:
        """Summarize anomalies to text"""
        if not anomalies:
            return "No spending anomalies detected."
        high = sum(1 for a in anomalies if a.get("anomaly_type") == "unusually_high")
        low = sum(1 for a in anomalies if a.get("anomaly_type") == "unusually_low")
        return f"Detected {high} unusually high expenses and {low} unusually low expenses."

    def _generate_recommendations(
        self,
        daily_report: Dict[str, Any],
        anomalies: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations"""
        recommendations = []

        if anomalies:
            recommendations.append({
                "title": "Review Unusual Expenses",
                "message": f"Found {len(anomalies)} unusual expenses. Review and investigate.",
                "priority": "high",
            })

        ar_ap = daily_report.get("ar_ap_summary", {})
        if ar_ap.get("overdue_receivables", 0) > 5000:
            recommendations.append({
                "title": "Follow Up on Overdue Invoices",
                "message": f"You have {ar_ap['overdue_receivables']:.2f} in overdue receivables. Send payment reminders.",
                "priority": "critical",
            })

        return recommendations

    def _get_health_status(self, score: float) -> str:
        """Get health status based on score"""
        if score >= 90:
            return "Excellent"
        elif score >= 75:
            return "Good"
        elif score >= 60:
            return "Fair"
        else:
            return "Poor"

    def _identify_areas_of_concern(self, scores: Dict[str, float]) -> List[str]:
        """Identify areas needing attention"""
        concerns = []
        for area, score in scores.items():
            if score < 15:
                concerns.append(area)
        return concerns

    def _get_improvement_recommendations(self, scores: Dict[str, float]) -> List[str]:
        """Get recommendations for improvement"""
        recommendations = []
        for area, score in scores.items():
            if score < 15:
                recommendations.append(f"Improve {area} - current score {score:.0f}/25")
        return recommendations

    def _generate_next_actions(
        self,
        daily_report: Dict[str, Any],
        health_score: Dict[str, Any]
    ) -> List[str]:
        """Generate next actions for decision makers"""
        actions = []

        if health_score.get("overall_score", 0) < 60:
            actions.append("Schedule financial review meeting")

        ar_ap = daily_report.get("ar_ap_summary", {})
        if ar_ap.get("overdue_receivables", 0) > 0:
            actions.append("Follow up on overdue receivables")

        return actions
