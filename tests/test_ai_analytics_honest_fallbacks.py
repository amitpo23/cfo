"""AdvancedAIService had two live, reachable routes silently fabricating data:

- get_ai_analysis(): with no OPENAI_API_KEY, returned a canned generic Hebrew
  "reassurance" paragraph (identical for every org/question) instead of an
  honest "not configured" response. Worse: even WITH a key configured, if the
  caller passed no explicit context (which is exactly what the real frontend,
  AIAnalyticsDashboard.tsx, does today), it silently fed GPT-4 a hardcoded
  fake financial context (_prepare_financial_context: revenue_mtd=450000 etc,
  identical for every organization) and presented the response as real advice.
- predict_metric(): computed a "forecast" entirely from random.randint/
  random.uniform noise (_get_metric_history/_get_seasonality_factor), dressed
  up with trend/confidence-interval/scenario math that looks computed but
  inputs pure noise.

Neither is reachable without a real financial data pipeline that doesn't
exist yet, so both now raise AIAnalyticsNotConfiguredError -- mirroring the
AIChatNotConfiguredError pattern already established for the Anthropic chat
this session -- instead of fabricating a plausible-looking answer.

get_ai_recommendations() is intentionally NOT touched here: it already
returns is_illustrative=True (see test_ai_recommendations_flagged.py, a
prior, deliberate "Phase 2" decision) -- that's an honest label already, just
never surfaced in the frontend (fixed separately in AIAnalyticsDashboard.tsx).
"""
import pytest

from cfo.database import SessionLocal
from cfo.services.ai_analytics_service import AdvancedAIService, AIAnalyticsNotConfiguredError


def test_get_ai_analysis_raises_when_openai_not_configured(fresh_org, monkeypatch):
    import cfo.config as config_module
    monkeypatch.setattr(config_module.settings, "openai_api_key", None)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org_id)
        with pytest.raises(AIAnalyticsNotConfiguredError):
            import asyncio
            asyncio.run(svc.get_ai_analysis("מה מצב התזרים שלי?"))
    finally:
        db.close()


def test_get_ai_analysis_never_falls_back_to_fake_context(fresh_org, monkeypatch):
    """Even with a key configured, no explicit context = raise, never fabricate."""
    import asyncio
    import cfo.config as config_module
    monkeypatch.setattr(config_module.settings, "openai_api_key", "fake-key-should-not-be-used")

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org_id)

        import openai

        def _fail_if_constructed(*_a, **_kw):
            raise AssertionError("must not build a real OpenAI client without real context")

        monkeypatch.setattr(openai, "OpenAI", _fail_if_constructed)

        with pytest.raises(AIAnalyticsNotConfiguredError):
            asyncio.run(svc.get_ai_analysis("מה מצב התזרים שלי?", context=None))
    finally:
        db.close()


def test_get_ai_analysis_uses_real_context_when_provided(fresh_org, monkeypatch):
    """The legitimate path still works: real context + real key -> real call."""
    import asyncio
    import cfo.config as config_module
    monkeypatch.setattr(config_module.settings, "openai_api_key", "fake-key")

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org_id)

        seen_context = {}

        class _FakeMessage:
            content = "ניתוח אמיתי"

        class _FakeChoice:
            message = _FakeMessage()

        class _FakeResponse:
            choices = [_FakeChoice()]

        class _FakeCompletions:
            def create(self, model, messages, **kwargs):
                seen_context["prompt"] = messages[0]["content"]
                return _FakeResponse()

        class _FakeChat:
            completions = _FakeCompletions()

        class _FakeOpenAI:
            def __init__(self, api_key):
                self.chat = _FakeChat()

        import openai
        monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

        real_context = {"revenue_mtd": 12345.0}
        result = asyncio.run(svc.get_ai_analysis("מה מצב התזרים שלי?", context=real_context))

        assert result == "ניתוח אמיתי"
        assert "12345" in seen_context["prompt"]
    finally:
        db.close()


def test_predict_metric_raises_instead_of_returning_random_noise(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org_id)
        with pytest.raises(AIAnalyticsNotConfiguredError):
            svc.predict_metric("revenue", horizon_months=6)
    finally:
        db.close()


def test_route_predict_metric_returns_clean_400_not_fake_200(client, owner):
    r = client.get("/api/financial/ai/predict/revenue", headers=owner["headers"])
    assert r.status_code == 400, r.text
    assert "היסטוריית נתונים אמיתית" in r.json()["detail"]


def test_route_analyze_returns_clean_400_not_canned_text(client, owner, monkeypatch):
    # Isolated from whatever OPENAI_API_KEY happens to be set in the shell
    # running the tests -- this test asserts the no-key path specifically.
    import cfo.config as config_module
    monkeypatch.setattr(config_module.settings, "openai_api_key", None)

    r = client.post(
        "/api/financial/ai/analyze",
        json={"question": "מה מצב התזרים שלי?"},
        headers=owner["headers"],
    )
    assert r.status_code == 400, r.text
    assert "OPENAI_API_KEY" in r.json()["detail"]
