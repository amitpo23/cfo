"""Block local customer artifacts from Vercel source uploads."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_ignores_local_customer_artifacts():
    patterns = {
        line.strip()
        for line in (ROOT / ".vercelignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "*.sql",
        "tmp",
        "outputs",
        "sites",
        "reports",
        ".kilo",
        ".superpowers",
        ".cursor",
        "docs/audits",
    } <= patterns
