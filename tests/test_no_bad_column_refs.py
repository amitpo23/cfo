"""
CI guard: ensure no code references non-existent model columns.

Runs scripts/colscan.py as a subprocess and asserts exit code 0.
"""
import subprocess
import sys
import pathlib


def test_no_bad_model_column_refs():
    root = pathlib.Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/colscan.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"colscan found bad refs:\n{result.stdout}\n{result.stderr}"
    )
