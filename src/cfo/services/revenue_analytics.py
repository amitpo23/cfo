"""
Phase 13A: Sales & Revenue Analytics Service
Analyzes revenue sources and sales segments
"""
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal
from statistics import mean
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, case

from ..models import Organization, Invoice, Contact, BankTransaction, Payment


class RevenueAnalyticsService:
    """Analyze revenue and sales segments"""

    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id

    def get_revenue_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get revenue summary for period"""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        invoices = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= start_date,
            Invoice.status.in_(["sent", "paid", "partially_paid"])
        ).all()

        total_invoiced = sum(inv.total for inv in invoices) or Decimal(0)
        total_paid = sum(inv.paid_amount for inv in invoices) or Decimal(0)
        total_pending = total_invoiced - total_paid

        return {
            "period_days": days,
            "total_invoiced": float(total_invoiced),
            "total_paid": float(total_paid),
            "total_pending": float(total_pending),
            "invoice_count": len(invoices),
            "average_invoice": float(total_invoiced / len(invoices)) if invoices else 0,
            "collection_rate_percent": float((total_paid / total_invoiced * 100)) if total_invoiced > 0 else 0,
        }

    def analyze_revenue_by_customer(self, days: int = 90, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Analyze revenue by customer
        Returns: top customers with revenue metrics
        """
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        customer_revenue = self.db.query(
            Contact.id,
            Contact.name,
            func.sum(Invoice.total).label("total_revenue"),
            func.count(Invoice.id).label("invoice_count"),
            func.avg(Invoice.total).label("average_invoice"),
            func.sum(Invoice.paid_amount).label("amount_paid")
        ).join(
            Invoice, Invoice.contact_id == Contact.id
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= start_date,
            Invoice.status.in_(["sent", "paid", "partially_paid"]),
            Contact.organization_id == self.org_id
        ).group_by(
            Contact.id, Contact.name
        ).order_by(
            func.sum(Invoice.total).desc()
        ).limit(limit).all()

        total_revenue = sum(c.total_revenue for c in customer_revenue) or Decimal(1)

        return [
            {
                "customer_id": c.id,
                "customer_name": c.name,
                "total_revenue": float(c.total_revenue),
                "invoice_count": c.invoice_count,
                "average_invoice": float(c.average_invoice) if c.average_invoice else 0,
                "amount_paid": float(c.amount_paid) if c.amount_paid else 0,
                "amount_pending": float(c.total_revenue - (c.amount_paid or Decimal(0))),
                "percentage_of_total_revenue": float((c.total_revenue / total_revenue * 100) if total_revenue > 0 else 0),
            }
            for c in customer_revenue
        ]

    def analyze_revenue_by_category(self, days: int = 90) -> Dict[str, Any]:
        """לא נתמך: למודל Invoice אין שדה category בסכמה.

        מוחזר סטטוס 'unsupported' מפורש במקום נתון מומצא או קריסה. לתמיכה
        אמיתית נדרש לגזור קטגוריה מ-``Invoice.line_items`` או להוסיף עמודה.
        """
        return {
            "status": "unsupported",
            "reason": "Invoice records have no category field in the current schema",
            "data": [],
        }

    def analyze_revenue_by_region(self, days: int = 90) -> Dict[str, Any]:
        """לא נתמך: למודל Contact אין שדות גאוגרפיים (country/state) בסכמה.

        מוחזר סטטוס 'unsupported' מפורש במקום נתון מומצא או קריסה.
        """
        return {
            "status": "unsupported",
            "reason": "Contact records have no geographic fields in the current schema",
            "data": [],
        }

    def analyze_revenue_concentration(self, days: int = 90) -> Dict[str, Any]:
        """
        Analyze revenue concentration
        Identifies if revenue is concentrated in few customers or distributed
        """
        customers = self.analyze_revenue_by_customer(days=days, limit=100)

        if not customers:
            return {
                "concentration_ratio": 0,
                "herfindahl_index": 0,
                "top_10_percent_revenue": 0,
                "customer_count": 0,
                "risk_level": "no_data",
            }

        total_revenue = sum(c["total_revenue"] for c in customers)
        
        # Top 10% of customers
        top_10_pct = customers[:max(1, len(customers) // 10)]
        top_10_revenue = sum(c["total_revenue"] for c in top_10_pct)

        # Herfindahl-Hirschman Index (HHI) - measure of concentration
        # Ranges from 0 (perfect competition) to 10000 (monopoly)
        hhi = sum(
            ((c["total_revenue"] / total_revenue * 100) ** 2)
            for c in customers
        ) if total_revenue > 0 else 0

        # Risk level based on HHI
        if hhi > 5000:
            risk_level = "critical"
        elif hhi > 3000:
            risk_level = "high"
        elif hhi > 1500:
            risk_level = "moderate"
        else:
            risk_level = "low"

        return {
            "total_customers": len(customers),
            "total_revenue": total_revenue,
            "concentration_ratio": float(top_10_revenue / total_revenue * 100) if total_revenue > 0 else 0,
            "herfindahl_index": round(hhi, 2),
            "top_10_percent_customer_count": len(top_10_pct),
            "top_10_percent_revenue": float(top_10_revenue),
            "risk_level": risk_level,
            "recommendation": self._concentration_recommendation(hhi),
        }

    def get_customer_profitability(self, days: int = 90) -> List[Dict[str, Any]]:
        """
        Analyze customer profitability
        Compares revenue from customer vs costs associated with them
        """
        customers = self.analyze_revenue_by_customer(days=days, limit=50)

        # gross_profit_estimate is not available: no cost data in the current schema.
        # Return None rather than a fabricated 70% margin estimate.
        return [
            {
                "customer_id": c["customer_id"],
                "customer_name": c["customer_name"],
                "revenue": c["total_revenue"],
                "gross_profit_estimate": None,
                "gross_profit_available": False,
                "profitability_score": c["amount_paid"] / c["total_revenue"] if c["total_revenue"] > 0 else 0,
                "payment_reliability": "good" if c["amount_paid"] / c["total_revenue"] > 0.9 else "fair" if c["amount_paid"] / c["total_revenue"] > 0.7 else "poor",
            }
            for c in customers
        ]

    def identify_investment_opportunities(self, days: int = 90) -> List[Dict[str, Any]]:
        """
        Identify high-potential investment opportunities
        - Growing customer segments
        - High-margin categories
        - Underexploited regions
        """
        opportunities = []

        # הזדמנויות לפי קטגוריה/אזור הושמטו: הסכמה אינה כוללת קטגוריית חשבונית
        # או שדות גאוגרפיים (ראו analyze_revenue_by_category/region). לא ממציאים נתון.

        # Growing customers — מבוסס על נתון אמיתי (revenue לפי לקוח).
        # אין נתון-מגמה אמיתי (revenue של תקופה קודמת) כדי לחשב אחוז-צמיחה אמיתי,
        # ולכן אין שדה "estimated_growth"/"growth_potential" מומצא — רק שדות
        # שנשלפו בפועל מהשאילתה.
        customers = self.analyze_revenue_by_customer(days=days, limit=50)
        for cust in customers:
            if cust["invoice_count"] >= 4 and cust["percentage_of_total_revenue"] < 15:
                opportunities.append({
                    "type": "growing_customer",
                    "customer_id": cust["customer_id"],
                    "customer_name": cust["customer_name"],
                    "current_revenue": cust["total_revenue"],
                    "invoice_count": cust["invoice_count"],
                    "recommendation": f"Develop strategic relationship with {cust['customer_name']}",
                })

        # הזדמנויות לפי אזור הושמטו — אין שדות גאוגרפיים בסכמה.

        return sorted(
            opportunities,
            key=lambda x: x.get("current_revenue", 0),
            reverse=True
        )

    def analyze_revenue_trends(self, days: int = 180) -> Dict[str, Any]:
        """
        Analyze revenue trends over time
        """
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        daily_revenue = {}
        invoices = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= start_date,
            Invoice.status.in_(["sent", "paid", "partially_paid"])
        ).all()

        for inv in invoices:
            date_key = inv.created_at.date().isoformat()
            if date_key not in daily_revenue:
                daily_revenue[date_key] = Decimal(0)
            daily_revenue[date_key] += inv.total

        if not daily_revenue:
            return {"status": "no_data", "period_days": days}

        sorted_dates = sorted(daily_revenue.keys())
        total = sum(daily_revenue.values()) or Decimal(0)
        mid_point = len(sorted_dates) // 2

        if mid_point > 0:
            first_half_avg = mean([float(daily_revenue[d]) for d in sorted_dates[:mid_point]])
            second_half_avg = mean([float(daily_revenue[d]) for d in sorted_dates[mid_point:]])
            trend_percent = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
            trend = "increasing" if trend_percent > 5 else "decreasing" if trend_percent < -5 else "stable"
        else:
            trend = "insufficient_data"

        return {
            "period_days": days,
            "total_revenue": float(total),
            "daily_average": float(total / len(daily_revenue)) if daily_revenue else 0,
            "days_with_revenue": len(daily_revenue),
            "trend": trend,
            "trend_percent": float(trend_percent) if mid_point > 0 else None,
        }

    def _average_days_to_payment(self) -> Optional[float]:
        """Compute mean days between invoice.issue_date and payment.payment_date.

        Fetches all Payment rows for this org that have a linked invoice with an
        issue_date.  Skips rows where either date is missing.  Returns None when
        there are no qualifying payments.
        """
        payments = (
            self.db.query(Payment)
            .filter(Payment.organization_id == self.org_id)
            .all()
        )
        deltas = []
        for pmt in payments:
            if pmt.payment_date is None:
                continue
            if pmt.invoice is None or pmt.invoice.issue_date is None:
                continue
            delta = (pmt.payment_date - pmt.invoice.issue_date).days
            deltas.append(delta)
        if not deltas:
            return None
        return round(sum(deltas) / len(deltas), 1)

    def get_sales_pipeline_health(self) -> Dict[str, Any]:
        """
        Get health of sales pipeline
        - Active customers
        - Expected revenue
        - Conversion metrics
        """
        # Get invoices from last 90 days
        start_date = datetime.now(timezone.utc) - timedelta(days=90)

        invoices = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= start_date
        ).all()

        draft_invoices = [i for i in invoices if i.status == "draft"]
        sent_invoices = [i for i in invoices if i.status == "sent"]
        paid_invoices = [i for i in invoices if i.status == "paid"]

        draft_value = sum(i.total for i in draft_invoices) or Decimal(0)
        sent_value = sum(i.total for i in sent_invoices) or Decimal(0)
        paid_value = sum(i.total for i in paid_invoices) or Decimal(0)

        return {
            "draft_invoices": len(draft_invoices),
            "draft_value": float(draft_value),
            "sent_invoices": len(sent_invoices),
            "sent_value": float(sent_value),
            "paid_invoices": len(paid_invoices),
            "paid_value": float(paid_value),
            "conversion_rate": float((len(paid_invoices) / len(invoices) * 100)) if invoices else 0,
            "average_days_to_payment": self._average_days_to_payment(),
        }

    def _concentration_recommendation(self, hhi: float) -> str:
        """Get recommendation based on HHI"""
        if hhi > 5000:
            return "CRITICAL: Diversify customer base immediately to reduce risk"
        elif hhi > 3000:
            return "HIGH: Actively work to diversify revenue sources"
        elif hhi > 1500:
            return "MODERATE: Consider expanding to new customer segments"
        else:
            return "GOOD: Healthy revenue distribution across customers"
