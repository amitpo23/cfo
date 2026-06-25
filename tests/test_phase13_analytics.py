"""
Phase 13: Analytics & Business Intelligence Tests
Using the existing test client infrastructure
"""
import pytest
from fastapi.testclient import TestClient

from cfo.api import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_analytics_daily_report_endpoint(client):
    """Test daily report API endpoint"""
    resp = client.get("/api/analytics/reports/daily")
    # Should return 401 if not authenticated, or 200 if there's test data
    assert resp.status_code in [200, 401, 403]


def test_analytics_weekly_budget_endpoint(client):
    """Test weekly budget report endpoint"""
    resp = client.get("/api/analytics/reports/weekly-budget")
    assert resp.status_code in [200, 401, 403]


def test_analytics_monthly_pl_endpoint(client):
    """Test monthly P&L report endpoint"""
    resp = client.get("/api/analytics/reports/monthly-pl")
    assert resp.status_code in [200, 401, 403]


def test_expense_summary_endpoint(client):
    """Test expense summary endpoint"""
    resp = client.get("/api/analytics/expenses/summary")
    assert resp.status_code in [200, 401, 403]


def test_expense_category_analysis_endpoint(client):
    """Test expense category analysis endpoint"""
    resp = client.get("/api/analytics/expenses/by-category")
    assert resp.status_code in [200, 401, 403]


def test_expense_vendor_analysis_endpoint(client):
    """Test expense vendor analysis endpoint"""
    resp = client.get("/api/analytics/expenses/by-vendor")
    assert resp.status_code in [200, 401, 403]


def test_anomaly_detection_endpoint(client):
    """Test anomaly detection endpoint"""
    resp = client.get("/api/analytics/expenses/anomalies")
    assert resp.status_code in [200, 401, 403]


def test_expense_trends_endpoint(client):
    """Test expense trends endpoint"""
    resp = client.get("/api/analytics/expenses/trends")
    assert resp.status_code in [200, 401, 403]


def test_cost_optimization_endpoint(client):
    """Test cost optimization opportunities endpoint"""
    resp = client.get("/api/analytics/expenses/optimization")
    assert resp.status_code in [200, 401, 403]


def test_revenue_summary_endpoint(client):
    """Test revenue summary endpoint"""
    resp = client.get("/api/analytics/revenue/summary")
    assert resp.status_code in [200, 401, 403]


def test_revenue_by_customer_endpoint(client):
    """Test revenue by customer endpoint"""
    resp = client.get("/api/analytics/revenue/by-customer")
    assert resp.status_code in [200, 401, 403]


def test_revenue_by_category_endpoint(client):
    """Test revenue by category endpoint"""
    resp = client.get("/api/analytics/revenue/by-category")
    assert resp.status_code in [200, 401, 403]


def test_revenue_by_region_endpoint(client):
    """Test revenue by region endpoint"""
    resp = client.get("/api/analytics/revenue/by-region")
    assert resp.status_code in [200, 401, 403]


def test_revenue_concentration_endpoint(client):
    """Test revenue concentration endpoint"""
    resp = client.get("/api/analytics/revenue/concentration")
    assert resp.status_code in [200, 401, 403]


def test_revenue_profitability_endpoint(client):
    """Test customer profitability endpoint"""
    resp = client.get("/api/analytics/revenue/profitability")
    assert resp.status_code in [200, 401, 403]


def test_revenue_opportunities_endpoint(client):
    """Test investment opportunities endpoint"""
    resp = client.get("/api/analytics/revenue/opportunities")
    assert resp.status_code in [200, 401, 403]


def test_revenue_trends_endpoint(client):
    """Test revenue trends endpoint"""
    resp = client.get("/api/analytics/revenue/trends")
    assert resp.status_code in [200, 401, 403]


def test_pipeline_health_endpoint(client):
    """Test sales pipeline health endpoint"""
    resp = client.get("/api/analytics/revenue/pipeline")
    assert resp.status_code in [200, 401, 403]


def test_ai_ask_question_endpoint(client):
    """Test AI ask question endpoint"""
    resp = client.post("/api/analytics/ai/ask", json={"question": "What is our revenue?"})
    assert resp.status_code in [200, 401, 403]


def test_ai_insights_endpoint(client):
    """Test AI daily insights endpoint"""
    resp = client.get("/api/analytics/ai/insights")
    assert resp.status_code in [200, 401, 403]


def test_ai_health_score_endpoint(client):
    """Test financial health score endpoint"""
    resp = client.get("/api/analytics/ai/health-score")
    assert resp.status_code in [200, 401, 403]


def test_ai_executive_summary_endpoint(client):
    """Test executive summary endpoint"""
    resp = client.get("/api/analytics/ai/executive-summary")
    assert resp.status_code in [200, 401, 403]
