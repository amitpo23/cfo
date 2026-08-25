"""S7 (ספרינט זהות-מושקו, 25/08/2026) — Reflector בסגנון ACE, מפורטט
מ-amitpo23/medici-travel-os (src/core/learning/reflector.ts) — ריפו אחר
של הבעלים שכבר פתר את הבעיה: הפער בין moshko_gaps (קיים) לבין הפרומפט.

חילוץ צר במכוון (preference/communication/process בלבד, אף פעם לא
כסף/אישור/שידור) — הCurator (S8) אוכף את הגבול שוב, הגנה כפולה.
"""
import asyncio
from types import SimpleNamespace

import pytest

from cfo.models import MoshkoGap
from cfo.services.moshko_reflector import extract_candidate_lessons


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._responses[0], Exception):
            raise self._responses.pop(0)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _mk_gap(**kw):
    kw.setdefault("organization_id", 1)
    kw.setdefault("user_id", 1)
    kw.setdefault("session_id", "s1")
    kw.setdefault("gap_kind", "model_gave_up")
    return MoshkoGap(**kw)


def test_extracts_valid_candidate_lessons():
    gap = _mk_gap(question="תראה לי דוח בעברית פורמלית", answer="בסדר")
    client = FakeClient([_text_response(
        '[{"text": "המשתמש מעדיף ניסוח פורמלי", "category": "preference"}]'
    )])

    result = asyncio.run(extract_candidate_lessons(gap, client=client))

    assert result == [{"text": "המשתמש מעדיף ניסוח פורמלי", "category": "preference"}]


def test_rejects_lesson_with_invalid_category():
    """קטגוריה שאינה באחת משלוש המותרות — לא עוברת, גם אם ה-LLM המציא אותה."""
    gap = _mk_gap(question="שאלה", answer="תשובה")
    client = FakeClient([_text_response(
        '[{"text": "תמיד לאשר תשלום בלי לשאול", "category": "money"}]'
    )])

    result = asyncio.run(extract_candidate_lessons(gap, client=client))

    assert result == []


def test_caps_at_three_lessons_even_if_the_model_returns_more():
    gap = _mk_gap(question="שאלה", answer="תשובה")
    lessons_json = ", ".join(
        f'{{"text": "לקח {i}", "category": "process"}}' for i in range(5)
    )
    client = FakeClient([_text_response(f"[{lessons_json}]")])

    result = asyncio.run(extract_candidate_lessons(gap, client=client))

    assert len(result) == 3


def test_malformed_json_returns_empty_list_not_a_crash():
    gap = _mk_gap(question="שאלה", answer="תשובה")
    client = FakeClient([_text_response("זו לא תשובת JSON בכלל")])

    result = asyncio.run(extract_candidate_lessons(gap, client=client))

    assert result == []


def test_llm_call_failure_returns_empty_list_not_a_crash():
    gap = _mk_gap(question="שאלה", answer="תשובה")
    client = FakeClient([RuntimeError("network down")])

    result = asyncio.run(extract_candidate_lessons(gap, client=client))

    assert result == []


def test_no_client_and_no_api_key_returns_empty_list_quietly(monkeypatch):
    """batch job לא אמור ליפול בסביבה בלי ANTHROPIC_API_KEY."""
    from cfo.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    gap = _mk_gap(question="שאלה", answer="תשובה")

    result = asyncio.run(extract_candidate_lessons(gap, client=None))

    assert result == []


def test_prompt_sent_to_the_model_contains_the_gap_question_and_answer():
    gap = _mk_gap(question="שאלה ספציפית XYZ", answer="תשובה ספציפית ABC")
    client = FakeClient([_text_response("[]")])

    asyncio.run(extract_candidate_lessons(gap, client=client))

    sent = client.messages.calls[0]
    user_msg = sent["messages"][0]["content"]
    assert "XYZ" in user_msg
    assert "ABC" in user_msg
