#!/usr/bin/env python3
"""שער QA מרוכז לפני הדיפלוי הסופי (Wave 2 שלב 10). מריץ את כל הבדיקות
ומדווח PASS/FAIL/SKIP מרוכז. exit 1 אם משהו נכשל. אין דיפלוי עם QA אדום.

הרצה:  python scripts/qa_gate.py
        python scripts/qa_gate.py --env-file /path/to/.env.prod   # גם בדיקת drift מול Neon
        python scripts/qa_gate.py --skip-frontend                 # דילוג על טסטי frontend (למשל בסביבה בלי node)

סעיף 7 (E2E ידני מול preview) אינו אוטומטי — נבדק ומתועד בנפרד.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent

RunFn = Callable[[list], "subprocess.CompletedProcess"]

# scripts/audit_routes.py marks any non-200/401/403/404/422 status as "FAIL"
# — including 400, which in this codebase is the correct, intentional
# response for "integration not configured" (SumitNotConfiguredError,
# AIChatNotConfiguredError, etc.), not a bug. docs/audits/2026-07-03-route-
# audit.md investigated 39 of these individually and confirmed they're
# expected env-gated 400s; a 40th was added deliberately (2026-07-04):
# /api/financial/ai/predict/{metric} used to return 200 with fabricated
# random-noise data when unconfigured — now raises AIAnalyticsNotConfiguredError
# for a clean 400 instead, trading a silently-wrong 200 for an honest failure.
# The real qa_gate criterion (per the Step 10 plan) is "zero NEW undocumented
# failures", not "script exit code == 0" — so we compare the reported count
# against this documented baseline instead.
ROUTE_AUDIT_BASELINE_FAILURES = 40


def _default_run(cmd: list, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result


def route_audit_within_baseline(stdout: str) -> bool:
    """True if the reported failure count is at or below the documented
    baseline (no NEW failures). False (fail-safe) if the summary line is
    missing/unparseable — an audit we can't verify isn't a pass."""
    match = re.search(r"כשל\(5xx/EXC\):\s*(\d+)", stdout)
    if not match:
        return False
    return int(match.group(1)) <= ROUTE_AUDIT_BASELINE_FAILURES


def run_gate(
    *,
    env_file: Optional[str] = None,
    skip_frontend: bool = False,
    run: RunFn = _default_run,
) -> dict:
    """Runs every qa_gate check and returns {name: True|False|None}
    (None = skipped). Injectable `run` for testing without real subprocesses."""
    results: dict[str, Optional[bool]] = {}

    def check(name: str, cmd: list, cwd: Optional[Path] = None) -> None:
        print(f"\n=== {name} ===")
        ok = run(cmd, cwd).returncode == 0
        print(f"{'PASS' if ok else 'FAIL'} — {name}")
        results[name] = ok

    def skip(name: str, reason: str) -> None:
        print(f"\n=== {name} === SKIPPED ({reason})")
        results[name] = None

    check("1. Full test suite", [sys.executable, "-m", "pytest", "tests/", "-q"])

    print("\n=== 2. Route audit ===")
    route_audit_result = run([sys.executable, "scripts/audit_routes.py"])
    ok = route_audit_within_baseline(getattr(route_audit_result, "stdout", "") or "")
    print(f"{'PASS' if ok else 'FAIL'} — 2. Route audit (baseline: {ROUTE_AUDIT_BASELINE_FAILURES} known env-gated 400s)")
    results["2. Route audit"] = ok
    check("3a. Schema drift (local)", [sys.executable, "scripts/schema_drift_check.py"])
    if env_file:
        check(
            "3b. Schema drift (Neon)",
            [sys.executable, "scripts/schema_drift_check.py", "--env-file", env_file],
        )
    else:
        skip("3b. Schema drift (Neon)", "no --env-file given")

    if skip_frontend:
        skip("4a. Frontend tsc", "--skip-frontend")
        skip("4b. Frontend build", "--skip-frontend")
    else:
        frontend_dir = ROOT / "frontend"
        check("4a. Frontend tsc", ["npx", "tsc", "--noEmit"], frontend_dir)
        check("4b. Frontend build", ["npm", "run", "build"], frontend_dir)

    check("5. Colscan (phantom column references)", [sys.executable, "scripts/colscan.py"])
    check(
        "6. Tenancy-focused tests",
        [sys.executable, "-m", "pytest", "tests/", "-q", "-k", "isolation or org_scope or tenancy"],
    )

    return results


def print_summary(results: dict) -> bool:
    print("\n" + "=" * 50)
    print("QA GATE SUMMARY")
    for name, ok in results.items():
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        print(f"  {status:5} {name}")

    failed = [name for name, ok in results.items() if ok is False]
    if failed:
        print(f"\nQA GATE FAILED: {', '.join(failed)}")
        return False
    print(
        "\nQA GATE PASSED (automated checks). Section 7 (manual E2E against "
        "a preview) is not automated — verify and document separately."
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="env file with a Neon DATABASE_URL, for the remote drift check")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args()

    results = run_gate(env_file=args.env_file, skip_frontend=args.skip_frontend)
    return 0 if print_summary(results) else 1


if __name__ == "__main__":
    sys.exit(main())
