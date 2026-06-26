"""
colscan.py — CI guard against non-existent model-column references.

Introspects SQLAlchemy models and flags any code that references
<Model>.<attr> where attr is not a real attribute on that model.

Exit 0 = clean.  Exit 1 = bad references found (printed to stdout).
"""
import re
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cfo import models  # noqa: E402

valid = {}
for name in dir(models):
    obj = getattr(models, name)
    if isinstance(obj, type) and hasattr(obj, "__mapper__"):
        valid[name] = set(dir(obj))

names = sorted(valid, key=len, reverse=True)
pat = re.compile(r"\b(" + "|".join(names) + r")\.([a-z_][a-z0-9_]*)\b")
SKIP = {"query", "metadata", "registry", "c", "classes", "prepare"}

hits = {}
for f in (ROOT / "src" / "cfo").rglob("*.py"):
    for i, line in enumerate(f.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]            # strip inline comments
        if not code.strip():
            continue
        for mo in pat.finditer(code):
            model, attr = mo.group(1), mo.group(2)
            if attr in valid[model] or attr in SKIP:
                continue
            hits.setdefault(f"{model}.{attr}", []).append(f"{f.relative_to(ROOT)}:{i}")

if hits:
    print("BAD MODEL-COLUMN REFERENCES FOUND:")
    for k in sorted(hits):
        print(f"  {k}  ({len(hits[k])}x)  e.g. {hits[k][0]}")
    sys.exit(1)
print("colscan: clean — no bad model-column references")
sys.exit(0)
