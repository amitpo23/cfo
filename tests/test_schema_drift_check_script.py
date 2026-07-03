"""Found while wiring qa_gate.py (Wave 2 Step 10): schema_drift_check.py
required the raw DATABASE_URL env var to be explicitly set, even though
cfo.config.Settings.database_url already has a usable default
(sqlite:///./cfo.db) — so running the script with no env var at all (the
documented "local" usage, no --env-file) failed with exit 2 instead of
actually checking the local db."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "schema_drift_check.py"


def test_runs_without_database_url_env_var_using_settings_default():
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True,
    )
    assert result.returncode in (0, 1), (
        f"expected a real drift check (0=clean, 1=drift), got exit "
        f"{result.returncode}: {result.stdout}{result.stderr}"
    )
    assert "לא מוגדר" not in result.stdout + result.stderr
