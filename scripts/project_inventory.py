#!/usr/bin/env python3
"""Print a reproducible source inventory without importing the app or reading secrets."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def count(folder, extensions):
    files = sorted(path for path in (ROOT / folder).rglob('*') if path.suffix in extensions and path.is_file())
    return {'files':len(files), 'lines':sum(len(path.read_text().splitlines()) for path in files)}


if __name__ == '__main__':
    print(json.dumps({
        'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'backend':count('src/cfo',{'.py'}),
        'frontend':count('frontend/src',{'.ts','.tsx'}),
        'test_sources':count('tests',{'.py'}),
        'alembic_migrations':count('alembic/versions',{'.py'}),
        'note':'Source inventory is not a count of collected tests or proof of operational capability.',
    },indent=2))
