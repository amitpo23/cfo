"""Rezef in-app chatbot knowledge base — src/cfo/services/rezef_kb.py.

Two concerns tested here:
1. The topic-lookup contract (`get_topic`/`topic_index`) the `rezef_help`
   chat tool relies on (see test_ai_chat_tools.py for the tool wrapper
   itself).
2. A sanity test that keeps the KB honest as the app evolves: every
   backing API path cited in the overview section (SCREENS) must actually
   exist in the live FastAPI route table — this is what stops the KB from
   silently rotting into fiction after a route is renamed/removed.
"""
import pytest

from cfo.api import app
from cfo.services import rezef_kb
from cfo.services.rezef_kb import SCREENS, TOPIC_SUMMARIES, TOPICS, get_topic, topic_index


def test_topic_index_lists_every_topic_with_a_one_line_summary():
    index = topic_index()
    for key in TOPICS:
        assert f"`{key}`" in index
        assert TOPIC_SUMMARIES[key] in index


def test_no_topic_returns_the_index_without_a_not_found_note():
    result = get_topic(None)
    assert result == topic_index()
    assert "לא נמצא" not in result


def test_empty_string_topic_returns_the_index():
    assert get_topic("") == topic_index()
    assert get_topic("   ") == topic_index()


@pytest.mark.parametrize("key", list(TOPICS.keys()))
def test_known_topic_returns_its_own_section(key):
    result = get_topic(key)
    assert result == TOPICS[key]
    # Every section should at least mention its own topic key elsewhere in
    # the KB's cross-references, or stand as a distinct, non-empty section.
    assert len(result) > 40


def test_known_topic_lookup_is_case_and_whitespace_insensitive():
    assert get_topic(" Expenses ") == TOPICS["expenses"]
    assert get_topic("VAT") == TOPICS["vat"]


def test_unknown_topic_returns_index_plus_not_found():
    result = get_topic("שיווק דיגיטלי")
    assert "לא נמצא" in result
    assert "שיווק דיגיטלי" in result
    # Still carries the full index so the caller can recover in one turn.
    for key in TOPICS:
        assert f"`{key}`" in result


def test_alias_resolves_to_canonical_topic():
    assert get_topic("מע\"מ") == TOPICS["vat"]
    assert get_topic("משרד") == TOPICS["office"]


def test_screens_cover_all_frontend_nav_routes():
    """Locks in screen count so a future App.tsx route addition/removal is
    a deliberate KB edit, not silent drift."""
    assert len(SCREENS) == 40
    paths = [s.path for s in SCREENS]
    assert len(paths) == len(set(paths))  # no duplicates


@pytest.mark.parametrize(
    "screen", [s for s in SCREENS if s.api_path is not None], ids=lambda s: s.path,
)
def test_screen_api_path_exists_in_live_route_table(screen):
    """Every /api/... path cited in the KB overview must be a real,
    currently-registered FastAPI route — keeps the KB from rotting into
    fiction as routes get renamed or removed."""
    live_paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert screen.api_path in live_paths, (
        f"KB screen {screen.path!r} cites {screen.api_path!r}, which is not "
        f"a registered FastAPI route"
    )


def test_screens_without_api_path_are_deliberately_flagged_in_their_summary():
    """A screen with api_path=None must say so honestly in its one-liner —
    never silently omitted."""
    honesty_markers = ("לא מחובר", "לא טוען", "לא קורא", "בלי", "מסך הזנה")
    for s in SCREENS:
        if s.api_path is None:
            assert any(marker in s.summary for marker in honesty_markers), s.path


def test_rezef_kb_module_has_no_placeholder_content():
    """Guards against accidentally shipping stub/lorem content instead of
    the real KB sections."""
    for key, text in TOPICS.items():
        assert text.strip(), key
        assert "TODO" not in text
        assert "lorem" not in text.lower()


def test_topics_dict_matches_summaries_keys_exactly():
    assert set(TOPICS.keys()) == set(TOPIC_SUMMARIES.keys())
