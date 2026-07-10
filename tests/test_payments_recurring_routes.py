"""Wave 2 Step 8 (8.3, scoped to managing existing recurring items — SUMIT
has no mandate-CREATE endpoint, only list/cancel/update of an existing
RecurringCustomerItemID).

Found while auditing 8.3: POST /api/payments/recurring/{id}/charge routed
directly to SumitIntegration.charge_recurring(), a documented "Not-Supported
Stub" that always raises a bare Exception (SUMIT's /billing/recurring/charge/
creates a NEW recurring charge, not a one-off charge of an existing item —
SUMIT bills active recurring items automatically). The bare Exception isn't
a SumitAPIError, so it wasn't caught by any handler — any call would leak an
unhandled 500 in production. Removed the route entirely (matches every other
"Not-Supported Stub" — kept as a documented client method, never routed)."""


def test_charge_recurring_route_removed(client, fresh_org):
    iso = fresh_org()
    r = client.post("/api/payments/recurring/123/charge", headers=iso["headers"])
    assert r.status_code == 404
