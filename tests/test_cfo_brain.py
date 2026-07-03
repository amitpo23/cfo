"""
Behavior / smoke tests for CFOBrainService.

We assert:
  1. run_analysis() returns a dict with the expected top-level keys.
  2. list_insights() returns a list.
  3. After run_analysis on a fresh org (which has no integrations configured),
     at least one insight is generated (connection-type insights are always
     emitted when SUMIT / Open Finance are absent — verified from source).
"""
from cfo.database import SessionLocal
from cfo.services.cfo_brain_service import CFOBrainService

# These are the actual top-level keys returned by CFOBrainService.run_analysis()
# (read directly from cfo_brain_service.py lines 100-107).
EXPECTED_RUN_ANALYSIS_KEYS = {
    "organization_id",
    "analyzed_at",
    "insights_generated",
    "tasks_created",
    "overview",
    "insights",
}


def test_run_analysis_shape(fresh_org):
    """run_analysis(create_tasks=False) returns a dict with all expected top-level keys."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)
        assert isinstance(result, dict), "Expected run_analysis() to return a dict"
        missing = EXPECTED_RUN_ANALYSIS_KEYS - result.keys()
        assert not missing, f"Missing keys in run_analysis result: {missing}"
    finally:
        db.close()


def test_list_insights_returns_list(fresh_org):
    """list_insights() returns a list (after run_analysis populates it)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brain = CFOBrainService(db, org_id)
        brain.run_analysis(create_tasks=False)
        result = brain.list_insights()
        assert isinstance(result, list), "Expected list_insights() to return a list"
    finally:
        db.close()


def test_connection_insights_generated_on_fresh_org(fresh_org):
    """
    A fresh org with no integrations always triggers connection-type insights
    (SUMIT and/or Open Finance missing). Verified from _connection_insights() source:
    it checks settings and active IntegrationConnection rows — a fresh org has neither.
    Since SUMIT_API_KEY is set in conftest (test-env-sumit-key), only the
    open_finance insight fires for sure; but either way insights_generated >= 1.
    """
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)
        # open_finance is always missing on a fresh test org → at least 1 insight
        assert result["insights_generated"] >= 1, (
            "Expected at least one insight for a fresh org with no integrations"
        )
        insights = CFOBrainService(db, org_id).list_insights()
        assert len(insights) >= 1, "list_insights() should be non-empty after run_analysis"
    finally:
        db.close()


def test_one_insight_generator_failing_does_not_abort_the_others(fresh_org, monkeypatch):
    """Unlike AlertEngine.evaluate_all() (which isolates each check via
    _run_check), run_analysis() calls each _*_insights() generator directly
    with no isolation — one exception anywhere currently aborts the entire
    analysis, silently dropping every other insight too (client_automation_
    service.run_post_sync_tasks wraps the whole run_analysis() call in a
    try/except that just logs and continues, so this failure mode is
    invisible in production). This must not be the case: a single generator
    failing should be caught, logged, and not block the others."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brain = CFOBrainService(db, org_id)
        monkeypatch.setattr(
            brain, "_cashflow_insights",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated failure")),
        )

        result = brain.run_analysis(create_tasks=False)

        # Connection insights (a different generator) still ran and produced output.
        assert result["insights_generated"] >= 1, (
            "A failing _cashflow_insights must not silently zero out every other insight"
        )
    finally:
        db.close()
