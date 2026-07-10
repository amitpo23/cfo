"""Wave 2 Step 10 — qa_gate.py orchestrates all QA checks and reports
PASS/FAIL/SKIP. Tested with an injected fake subprocess runner — no real
pytest/tsc/build subprocesses spawned (that would recursively re-run the
whole suite from inside itself)."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "qa_gate", Path(__file__).parent.parent / "scripts" / "qa_gate.py"
)
qa_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa_gate)


_BASELINE_STDOUT = f"סהכ: 232 | תקין(200): 168 | אזהרה(4xx): 25 | כשל(5xx/EXC): {qa_gate.ROUTE_AUDIT_BASELINE_FAILURES}"


def _ok(code=0, stdout=_BASELINE_STDOUT):
    return SimpleNamespace(returncode=code, stdout=stdout)


def _cmd_contains(cmd, needle):
    return any(needle in part for part in cmd)


def test_all_checks_pass_reports_overall_pass():
    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        return _ok(0)

    results = qa_gate.run_gate(run=fake_run)
    assert all(v in (True, None) for v in results.values())
    assert qa_gate.print_summary(results) is True
    # local schema drift always runs; frontend runs unless skipped
    assert any(_cmd_contains(c, "pytest") for c in calls)
    assert any(_cmd_contains(c, "audit_routes.py") for c in calls)
    assert any(_cmd_contains(c, "colscan.py") for c in calls)


def test_a_single_failure_fails_the_whole_gate():
    def fake_run(cmd, cwd=None):
        if _cmd_contains(cmd, "colscan.py"):
            return _ok(1)
        return _ok(0)

    results = qa_gate.run_gate(run=fake_run)
    assert results["5. Colscan (phantom column references)"] is False
    assert qa_gate.print_summary(results) is False


def test_route_audit_uses_documented_baseline_not_raw_exit_code():
    """audit_routes.py always exits 1 when ANY route returns non-200/401/
    403/404/422 — including the 39 documented, verified-correct env-gated
    400s (SUMIT/Open Finance not configured). qa_gate must not treat that
    baseline as a failure just because the script's own exit code is 1."""
    def fake_run(cmd, cwd=None):
        if _cmd_contains(cmd, "audit_routes.py"):
            return _ok(code=1, stdout=_BASELINE_STDOUT)  # script's own exit code IS 1
        return _ok(0)

    results = qa_gate.run_gate(run=fake_run)
    assert results["2. Route audit"] is True
    assert qa_gate.print_summary(results) is True


def test_route_audit_fails_when_failure_count_exceeds_baseline():
    def fake_run(cmd, cwd=None):
        if _cmd_contains(cmd, "audit_routes.py"):
            return _ok(code=1, stdout="סהכ: 240 | תקין(200): 170 | אזהרה(4xx): 25 | כשל(5xx/EXC): 45")
        return _ok(0)

    results = qa_gate.run_gate(run=fake_run)
    assert results["2. Route audit"] is False
    assert qa_gate.print_summary(results) is False


def test_route_audit_fails_safe_on_unparseable_output():
    def fake_run(cmd, cwd=None):
        if _cmd_contains(cmd, "audit_routes.py"):
            return _ok(code=0, stdout="")
        return _ok(0)

    results = qa_gate.run_gate(run=fake_run)
    assert results["2. Route audit"] is False


def test_no_env_file_skips_remote_drift_check_without_failing():
    results = qa_gate.run_gate(run=lambda cmd, cwd=None: _ok(0))
    assert results["3b. Schema drift (Neon)"] is None
    assert qa_gate.print_summary(results) is True


def test_env_file_runs_remote_drift_check():
    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        return _ok(0)

    results = qa_gate.run_gate(env_file="/tmp/fake.env", run=fake_run)
    assert results["3b. Schema drift (Neon)"] is True
    assert any("--env-file" in c and "/tmp/fake.env" in c for c in calls)


def test_skip_frontend_skips_tsc_and_build():
    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        return _ok(0)

    results = qa_gate.run_gate(skip_frontend=True, run=fake_run)
    assert results["4a. Frontend tsc"] is None
    assert results["4b. Frontend build"] is None
    assert not any("tsc" in c for c in calls)
    assert qa_gate.print_summary(results) is True


def test_frontend_build_failure_fails_the_gate():
    def fake_run(cmd, cwd=None):
        if "build" in cmd:
            return _ok(1)
        return _ok(0)

    results = qa_gate.run_gate(run=fake_run)
    assert results["4b. Frontend build"] is False
    assert qa_gate.print_summary(results) is False
