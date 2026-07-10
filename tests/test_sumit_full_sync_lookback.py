"""_list_documents_all's own docstring claims a full sync (updated_since=None)
"reaches back years, not just 365 days, so earlier-in-the-year history is not
silently dropped" -- but the code capped from_date at exactly
date.today() - timedelta(days=365), directly contradicting its own documented
intent. Found live (2026-07-04 data-parity check): a real customer whose only
invoices are dated 2024 (issue dates > 365 days before today, 2026-07-04)
could never be (re)discovered by a fresh full customer sync, even after
fixing fetch_customers() to derive customers from real documents -- the
365-day window silently excluded those documents before fetch_customers()
ever saw them."""
import asyncio
from datetime import date


class _CapturingClient:
    def __init__(self):
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_documents(self, request):
        self.requests.append(request)
        return []  # empty page -> loop exits immediately


def test_full_sync_lookback_reaches_back_years_not_365_days():
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _CapturingClient()

    asyncio.run(connector._list_documents_all(client, "0", updated_since=None))

    assert len(client.requests) == 1
    from_date = client.requests[0].from_date
    days_back = (date.today() - from_date).days
    # "years, not 365 days" -- assert comfortably more than a year.
    assert days_back > 730, f"only looked back {days_back} days, expected years"
