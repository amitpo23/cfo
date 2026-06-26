"""T1.3 — Honest fallback message instead of placeholder string."""
from cfo.services.ai_intelligence_agent import AIIntelligenceAgent
from cfo.database import SessionLocal


def test_synthesize_answer_honest_fallback():
    """Verify that unknown question types return honest message, not placeholder."""
    db = SessionLocal()
    try:
        # Create agent with a dummy org_id (1)
        agent = AIIntelligenceAgent(db, org_id=1)

        # Call with unknown question type to trigger the else branch
        result = agent._synthesize_answer("unknown_type", "some question", {})

        # Assert: should NOT contain the placeholder text
        assert "[Analysis would be provided here]" not in result, \
            "Placeholder string should be removed"

        # Assert: should contain the honest message
        assert "don't have enough information" in result, \
            "Should return honest message about lacking information"

    finally:
        db.close()


def test_placeholder_removed_from_source():
    """Verify the literal placeholder no longer exists in the source code."""
    with open("src/cfo/services/ai_intelligence_agent.py") as f:
        source = f.read()

    assert "[Analysis would be provided here]" not in source, \
        "Placeholder string should be removed from source"
