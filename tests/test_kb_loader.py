"""Package 2 (conversational channels/personas plan) — KB loader.

Covers docs/superpowers/plans/2026-07-26-conversational-channels-personas.md
package 2: kb_index/kb_search over docs/bookkeeper_kb + docs/sumit_help_kb,
honest-null when the KB directory tree isn't present at runtime, and the
kb_lookup chat tool actually wired to real content."""
from pathlib import Path

from cfo.services import kb_loader


def _clear_caches():
    kb_loader._index_for.cache_clear()
    kb_loader._read_file.cache_clear()


def setup_function(_fn):
    _clear_caches()


def teardown_function(_fn):
    _clear_caches()


def test_kb_index_lists_the_files_actually_present_on_disk():
    idx = kb_loader.kb_index()
    assert idx["available"] is True
    centers = {c["key"]: c for c in idx["centers"]}
    assert "bookkeeper_kb" in centers
    assert "sumit_help_kb" in centers
    assert "procedures" in centers

    bookkeeper_files = {f["filename"] for f in centers["bookkeeper_kb"]["files"]}
    for expected in (
        "README.md",
        "00-role-and-daily-order.md",
        "01-income-tax-recognition.md",
        "02-vat-input-deductibility.md",
        "03-classification-bridge.md",
    ):
        assert expected in bookkeeper_files

    sumit_files = {f["filename"] for f in centers["sumit_help_kb"]["files"]}
    assert "03-income-customers-expenses.md" in sumit_files

    procedures_files = {f["filename"] for f in centers["procedures"]["files"]}
    for expected in (
        "BOOKKEEPER_ARMY_OPERATING_MODEL.md",
        "REZEF_OPERATING_SYSTEM.md",
        "SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md",
    ):
        assert expected in procedures_files

    # Every listed file must actually exist and every listed file must carry
    # a hand-written (non-empty) Hebrew title + summary.
    for center in idx["centers"]:
        for f in center["files"]:
            assert f["title"].strip()
            assert f["summary"].strip()

    # Sum generically over whatever centers are actually present, rather
    # than a hardcoded total — a fourth center added later shouldn't need
    # this assertion rewritten too.
    assert idx["file_count"] == sum(len(c["files"]) for c in idx["centers"])


def test_kb_index_reports_exactly_three_centers():
    idx = kb_loader.kb_index()
    assert len(idx["centers"]) == 3
    assert {c["key"] for c in idx["centers"]} == {
        "bookkeeper_kb",
        "sumit_help_kb",
        "procedures",
    }


def test_kb_search_procedural_term_hits_the_new_procedures_center():
    """'224א' (the personal-liability clause the operating model repeats
    throughout its SOPs) appears only in BOOKKEEPER_ARMY_OPERATING_MODEL.md
    — verified with grep before writing this assertion — so a hit here can
    only come from the new procedures center, with a real source string."""
    result = kb_loader.kb_search("224א")
    assert result["results"], "expected at least one matching section"
    assert all(r["center"] == "פרוצדורות ונהלי עבודה" for r in result["results"])
    assert all(r["file"] == "BOOKKEEPER_ARMY_OPERATING_MODEL.md" for r in result["results"])
    for r in result["results"]:
        assert r["source"].startswith("פרוצדורות ונהלי עבודה — BOOKKEEPER_ARMY_OPERATING_MODEL.md")


def test_kb_search_known_term_returns_sections_with_source():
    result = kb_loader.kb_search("תשומות")
    assert result["results"], "expected at least one matching section"
    for r in result["results"]:
        assert r["text"]
        assert r["source"]
        assert r["file"]
        assert r["heading"]


def test_kb_search_hospitality_term_hits_vat_file():
    result = kb_loader.kb_search("אירוח")
    assert result["results"]
    assert any(r["file"] == "02-vat-input-deductibility.md" for r in result["results"])


def test_kb_search_gibberish_returns_honest_no_results_note():
    result = kb_loader.kb_search("xzqwqzxnonsenseterm12345")
    assert result["results"] == []
    assert "לא נמצאו תוצאות" in result["note"]
    assert "xzqwqzxnonsenseterm12345" in result["note"]


def test_kb_search_enforces_max_chars_ceiling():
    result = kb_loader.kb_search("מס", max_chars=500)
    total = sum(len(r["text"]) for r in result["results"])
    assert total <= 500
    assert result["results"]


def test_kb_search_max_chars_smaller_than_default_yields_fewer_or_shorter_results():
    small = kb_loader.kb_search("מע\"מ", max_chars=300)
    large = kb_loader.kb_search("מע\"מ", max_chars=4000)
    small_total = sum(len(r["text"]) for r in small["results"])
    large_total = sum(len(r["text"]) for r in large["results"])
    assert small_total <= 300
    assert large_total >= small_total


def test_kb_search_max_chars_ceiling_holds_across_all_three_centers():
    """'סנכרון' (sync) is present in files in all three centers (verified
    with grep across bookkeeper_kb/sumit_help_kb/procedures). With
    max_chars=4000 the top hits are all sumit_help_kb, so a small budget
    alone doesn't prove the three-center case — raise it until results
    actually span all three centers, then check the ceiling holds for that
    combined, cross-center total (not just per-center)."""
    result = kb_loader.kb_search("סנכרון", max_chars=12000)
    total = sum(len(r["text"]) for r in result["results"])
    assert total <= 12000
    assert result["results"]
    centers_hit = {r["center"] for r in result["results"]}
    assert centers_hit == {
        "מרכז ידע מנהל החשבונות",
        "מרכז ידע SUMIT (מרכז העזרה)",
        "פרוצדורות ונהלי עבודה",
    }


def test_kb_index_missing_file_in_new_center_does_not_break_the_index(monkeypatch):
    """honest-null at file granularity: a file listed in KB_CENTERS but
    absent on disk (e.g. renamed/deleted procedures doc) must be silently
    dropped from the index — same pattern the two existing centers already
    rely on — never a crash or a poisoned 'available: False' for the whole
    index."""
    original = kb_loader.KB_CENTERS
    procedures = next(c for c in original if c.key == "procedures")
    bogus_file = kb_loader.KBFile("DOES-NOT-EXIST.md", "כותרת", "תקציר")
    patched_procedures = kb_loader.KBCenter(
        key=procedures.key,
        title_he=procedures.title_he,
        dir_name=procedures.dir_name,
        heading_re=procedures.heading_re,
        files=procedures.files + (bogus_file,),
    )
    patched = tuple(
        patched_procedures if c.key == "procedures" else c for c in original
    )
    monkeypatch.setattr(kb_loader, "KB_CENTERS", patched)
    _clear_caches()

    idx = kb_loader.kb_index()
    assert idx["available"] is True
    procedures_out = next(c for c in idx["centers"] if c["key"] == "procedures")
    filenames = {f["filename"] for f in procedures_out["files"]}
    assert "DOES-NOT-EXIST.md" not in filenames
    assert "BOOKKEEPER_ARMY_OPERATING_MODEL.md" in filenames


def test_kb_index_honest_null_when_docs_root_missing(monkeypatch, tmp_path):
    """A missing KB directory tree at runtime (e.g. not packaged into the
    Vercel function) must never surface as a silent empty index/search —
    it must say so explicitly."""
    missing_root = tmp_path / "no-docs-here"
    monkeypatch.setattr(kb_loader, "DOCS_ROOT", missing_root)

    idx = kb_loader.kb_index()
    assert idx == {"available": False, "reason": kb_loader.NOT_AVAILABLE_REASON}

    search = kb_loader.kb_search("תשומות")
    assert search == {"available": False, "reason": kb_loader.NOT_AVAILABLE_REASON}


def test_kb_index_cache_is_keyed_by_root_not_global(monkeypatch, tmp_path):
    """Regression guard: the cache must be keyed on the resolved docs root,
    not memoized with no arguments — otherwise a test (or a monkeypatch
    anywhere else in the process) that points DOCS_ROOT at a missing path
    would poison kb_index()/kb_search() for every other caller afterwards."""
    real = kb_loader.kb_index()
    assert real["available"] is True

    missing_root = tmp_path / "still-missing"
    monkeypatch.setattr(kb_loader, "DOCS_ROOT", missing_root)
    assert kb_loader.kb_index()["available"] is False

    monkeypatch.undo()
    assert kb_loader.kb_index()["available"] is True


def test_kb_lookup_tool_returns_real_content_and_index_without_query(fresh_org):
    import asyncio

    from cfo.database import SessionLocal
    from cfo.services.ai_chat_tools import TOOLS

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        with_query = asyncio.run(TOOLS["kb_lookup"].fn(db, org_id, query="תשומות"))
        assert with_query["results"]

        no_query = asyncio.run(TOOLS["kb_lookup"].fn(db, org_id, query=""))
        assert no_query["available"] is True
        assert no_query["centers"]
    finally:
        db.close()


def test_engine_status_tool_reports_kb_files_available_count(fresh_org):
    import asyncio

    from cfo.database import SessionLocal
    from cfo.services.ai_chat_tools import TOOLS

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_engine_status"].fn(db, org_id))
        assert result["kb_files_available"] == kb_loader.kb_index()["file_count"]
    finally:
        db.close()
