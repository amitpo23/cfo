"""Cron and registration secrets compare in constant time.

AUTH_BYPASS_ENABLED is already refused on Vercel by
Settings.validate_production_settings. tests/test_registration_boundary.py
covers that refusal; this file locks the remaining string compares.
"""
import ast
from pathlib import Path

from cfo.services.secret_compare import constant_time_equal

ROOT = Path(__file__).resolve().parents[1]


def test_constant_time_equal_matches_full_secret_only():
    secret = "cron-secret-value"
    assert constant_time_equal(f"Bearer {secret}", f"Bearer {secret}")
    assert not constant_time_equal(f"Bearer {secret[:-1]}", f"Bearer {secret}")
    assert not constant_time_equal(None, f"Bearer {secret}")
    assert not constant_time_equal("", f"Bearer {secret}")
    assert not constant_time_equal(secret, f"Bearer {secret}")
    assert not constant_time_equal("", "")
    assert not constant_time_equal(None, None)
    assert not constant_time_equal(None, "")
    assert not constant_time_equal("anything", "")
    assert not constant_time_equal("anything", None)


def test_cron_route_rejects_a_missing_or_partial_bearer(client):
    missing = client.get("/api/cron/daily-close")
    assert missing.status_code == 401
    partial = client.get(
        "/api/cron/daily-close",
        headers={"Authorization": "Bearer test-cron-secre"},
    )
    assert partial.status_code == 401
    ok = client.get(
        "/api/cron/daily-close",
        headers={"Authorization": "Bearer test-cron-secret"},
    )
    assert ok.status_code == 200


def test_cron_and_registration_do_not_compare_secrets_with_equality():
    cron_source = (ROOT / "src/cfo/api/routes/cron.py").read_text()
    cron_tree = ast.parse(cron_source)
    compared = []
    for node in ast.walk(cron_tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops
        ):
            compared.append(ast.get_source_segment(cron_source, node) or "")
    assert compared == [] or all("cron_secret" not in item and "Bearer" not in item for item in compared)
    assert "constant_time_equal" in cron_source

    admin_source = (ROOT / "src/cfo/api/routes/admin.py").read_text()
    assert "registration_code != settings.registration_secret" not in admin_source
    assert "constant_time_equal" in admin_source


def test_vercel_startup_still_refuses_auth_bypass():
    """The production validator on this branch already blocks the flag.

    Keep the guard named so a later edit cannot drop it quietly.
    """
    source = (ROOT / "src/cfo/config.py").read_text()
    assert "AUTH_BYPASS_ENABLED must be false on public deployments" in source
    assert 'os.getenv("VERCEL")' in source
