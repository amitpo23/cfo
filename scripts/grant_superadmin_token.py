#!/usr/bin/env python3
"""Promote a user to SUPER_ADMIN and mint a short-lived access token.

Use only as a break-glass local operator tool. The token is printed to stdout;
do not paste it into chat or commit command output.

Usage:
    DATABASE_URL=postgresql+psycopg://... JWT_SECRET_KEY=... python scripts/grant_superadmin_token.py <email>
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _load_env() -> None:
    """Load local env file before importing settings."""
    candidates = [str(ROOT / ".env.local")]
    for path in candidates:
        try:
            for line in open(path):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v and k not in os.environ:
                    os.environ[k] = v
        except FileNotFoundError:
            continue


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/grant_superadmin_token.py <email>")
    email = sys.argv[1].strip()

    _load_env()
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL not found (environment / .env.local)")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    from sqlalchemy import create_engine, text
    from cfo.auth import create_access_token

    engine = create_engine(url)
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, organization_id FROM users WHERE email = :e"), {"e": email}
        ).first()
        if not row:
            raise SystemExit(f"No user found with email {email}")
        user_id, org_id = row[0], row[1]
        conn.execute(
            text("UPDATE users SET role = 'SUPER_ADMIN', is_active = true WHERE id = :id"),
            {"id": user_id},
        )

    token = create_access_token(
        data={"sub": user_id, "role": "super_admin", "org_id": org_id},
        expires_delta=timedelta(days=7),
    )

    print("\n" + email + " is now SUPER_ADMIN. Token (valid 7 days):\n")
    print(token)
    print("\n--- To log in instantly (no password) ---")
    print("1. Open https://cfo-2.vercel.app")
    print("2. Open DevTools console:  Cmd+Option+J")
    print("3. Paste and run:")
    print(f"   localStorage.setItem('auth_token','{token}'); location.reload()")
    print("\nYou will be logged in as super admin.\n")


if __name__ == "__main__":
    main()
