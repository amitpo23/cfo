"""PostgreSQL-offline contract for the pre-release security migrations."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _postgres_sql() -> str:
    result = subprocess.run(
        [
            sys.executable, "-m", "alembic", "upgrade",
            "d2e3f4a5b6c7:04b5c6d7e8f9", "--sql",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "DATABASE_URL": "postgresql://offline:offline@localhost:1/offline",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return result.stdout


def test_security_migrations_emit_complete_postgres_ddl_without_enum_recreation():
    sql = _postgres_sql()

    assert re.search(r"CREATE TABLE policy_grants", sql, re.I)
    assert re.search(r"CREATE TABLE provider_request_budgets", sql, re.I)
    assert re.search(r"CREATE TABLE moshko_feedback", sql, re.I)
    assert "ck_policy_grant_single_subject" in sql
    assert "ck_provider_budget_used_nonnegative" in sql
    assert "ck_moshko_feedback_category" in sql
    assert not re.search(r"CREATE TYPE\s+\S*userrole", sql, re.I)


def test_security_migrations_retain_org_and_evidence_foreign_keys():
    sql = _postgres_sql()

    assert "FOREIGN KEY(organization_id) REFERENCES organizations (id)" in sql
    assert "FOREIGN KEY(message_id) REFERENCES ai_chat_messages (id)" in sql
    assert "FOREIGN KEY(promoted_memory_id) REFERENCES moshko_memory (id)" in sql
