"""W2.4 — גידור נתיב ה-webhook (הפער: עקף את שער ה-20 שעות לחלוטין).

ממצאי 20/08:
- debounce של 120ש' בזיכרון-תהליך — כמעט חסר-משמעות ב-serverless.
- webhook לא-מזוהה נפל ל-org 1 ושרף את התקציב שלו.
- אין תקרה יומית לריצות סנכרון מונעות-webhook.
"""
import asyncio

import pytest

import cfo.services.webhook_delta_sync as wds
from cfo.database import SessionLocal
from cfo.models import ProviderRequestBudget


@pytest.fixture(autouse=True)
def _clean(client):
    wds._last_handled.clear()
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        wds._last_handled.clear()
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


def _patch_targeted_sync(monkeypatch, calls):
    async def _fake(db, org_id, source, entity_types):
        calls.append((org_id, source, list(entity_types)))
        return {"sync_run_id": 1, "status": "completed", "counts": {}}
    monkeypatch.setattr(wds, "_run_targeted_sync", _fake)


def test_unattributable_sumit_webhook_is_rejected_not_routed_to_org1(monkeypatch):
    """payload בלי CompanyID — נדחה. הוא לא שורף את התקציב של org 1."""
    calls = []
    _patch_targeted_sync(monkeypatch, calls)

    db = SessionLocal()
    try:
        result = asyncio.run(wds.handle_sumit_trigger_event(db, {
            "TriggerType": "DocumentCreate", "DocumentID": 555,
        }))
    finally:
        db.close()

    assert result["handled"] is False
    assert result["reason"] == "unresolvable_org"
    assert calls == []


def test_webhook_budget_is_durable_and_capped_per_day(monkeypatch):
    """השער עמיד ב-DB: מחיקת מפת הזיכרון (כמו cold start) אינה מאפסת
    אותו, והתקרה היומית נאכפת."""
    monkeypatch.setattr(wds, "WEBHOOK_SYNCS_PER_DAY", 2)
    # כל תביעה בדלי-זמן משלה כדי לבודד את התקרה היומית מה-debounce.
    buckets = iter(range(100))
    monkeypatch.setattr(wds, "_debounce_bucket", lambda now: next(buckets))

    assert wds._claim_webhook_budget(41, "sumit") is None
    wds._last_handled.clear()  # cold start מדומה
    assert wds._claim_webhook_budget(41, "sumit") is None
    reason = wds._claim_webhook_budget(41, "sumit")
    assert reason is not None and "daily" in reason


def test_same_burst_is_debounced_durably(monkeypatch):
    """שתי מסירות באותו דלי 120ש' — השנייה נדחית גם אחרי cold start."""
    monkeypatch.setattr(wds, "_debounce_bucket", lambda now: 7)
    assert wds._claim_webhook_budget(42, "sumit") is None
    wds._last_handled.clear()
    reason = wds._claim_webhook_budget(42, "sumit")
    assert reason is not None and "debounce" in reason


def test_handler_consults_the_durable_gate(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_sumit_org", lambda db, payload: 3)
    monkeypatch.setattr(
        wds, "_claim_webhook_budget",
        lambda org_id, source: "daily_webhook_budget_exhausted",
    )

    result = asyncio.run(wds.handle_sumit_trigger_event(None, {
        "TriggerType": "DocumentCreate", "DocumentID": 1,
    }))
    assert result["handled"] is False
    assert result["reason"] == "daily_webhook_budget_exhausted"
    assert calls == []
