"""כשל upstream (SUMIT וכו') חייב להחזיר 503 כן — לא 500 גולמי."""
import httpx


def test_httpx_error_returns_503_not_500(client, owner, monkeypatch):
    """מפילים את קריאת ה-upstream ובודקים שהתשובה 503 עם detail ברור."""
    from cfo.integrations.sumit_integration import SumitIntegration

    async def _boom(self, *a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(SumitIntegration, "list_documents", _boom)
    resp = client.get("/api/accounting/documents", headers=owner["headers"])
    assert resp.status_code == 503
    assert "upstream" in resp.json()["detail"].lower()
