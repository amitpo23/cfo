#!/usr/bin/env python3
"""Set a new password and promote an existing user to SUPER_ADMIN.

You type the password (hidden, never printed). Role becomes super_admin so you
can see every organization (cross-org "all clients" view).

Usage:
    DATABASE_URL=postgresql+psycopg://... python scripts/bootstrap_superadmin.py <email>
"""
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _load_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    candidates = [str(Path(__file__).resolve().parent.parent / ".env.local")]
    for path in candidates:
        try:
            for line in open(path):
                line = line.strip()
                if line.startswith("DATABASE_URL=") and line.split("=", 1)[1].strip():
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    raise SystemExit("DATABASE_URL not found in environment or .env.local")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/bootstrap_superadmin.py <email>")
    email = sys.argv[1].strip()

    url = _load_database_url()
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    from sqlalchemy import create_engine, text
    from cfo.auth import get_password_hash

    pw1 = getpass.getpass("New password (min 8 chars): ")
    if len(pw1) < 8:
        raise SystemExit("Password must be at least 8 characters")
    if pw1 != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")

    hashed = get_password_hash(pw1)
    engine = create_engine(url)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE users SET password_hash = :h, role = 'SUPER_ADMIN', is_active = true "
                "WHERE email = :e"
            ),
            {"h": hashed, "e": email},
        )
        if result.rowcount == 0:
            raise SystemExit(f"No user found with email {email}")
    print(f"{email} is now SUPER_ADMIN with a new password ({result.rowcount} row). You can log in.")


if __name__ == "__main__":
    main()
