"""fetch_bank_transactions לא קורא ל-SUMIT — creditguy/billing/load כושל
תמיד ובכוונה (מגבלת ה-API עצמו, לא באג), ולפני התיקון הריצה קריאת רשת
הרוסה-מראש בכל sync שעתי, לכל org מחובר, לנצח. הבנק מגיע מ-Open Finance."""
import asyncio


def test_fetch_bank_transactions_never_calls_client(monkeypatch):
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")

    async def _boom(self):
        raise AssertionError("fetch_bank_transactions must not open a SUMIT client")

    monkeypatch.setattr(SumitConnector, "_get_client", _boom)

    result = asyncio.run(connector.fetch_bank_transactions())
    assert result.items == []
    assert result.has_more is False
    assert result.error is None
