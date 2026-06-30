#!/usr/bin/env python3
"""Reset an existing user's password — interactive (you type it; it is never printed).

Usage:
    DATABASE_URL=postgresql+psycopg://... python scripts/reset_password.py <email>

DATABASE_URL is read from the environment, else from .env.local. The new
password is read with getpass (hidden), hashed with bcrypt, and written to
users.password_hash.
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
        raise SystemExit("Usage: python scripts/reset_password.py <email>")
    email = sys.argv[1].strip()

    url = _load_database_url()
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    from sqlalchemy import create_engine, text
    from cfo.auth import get_password_hash

    pw1 = getpass.getpass("New password (min 8 chars): ")
    if len(pw1) < 8:
        raise SystemExit("Password must be at least 8 characters")
    pw2 = getpass.getpass("Confirm password: ")
    if pw1 != pw2:
        raise SystemExit("Passwords do not match")

    hashed = get_password_hash(pw1)
    engine = create_engine(url)
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET password_hash = :h WHERE email = :e"),
            {"h": hashed, "e": email},
        )
        if result.rowcount == 0:
            raise SystemExit(f"No user found with email {email}")
    print(f"Password updated for {email} ({result.rowcount} row). You can now log in.")


if __name__ == "__main__":
    main()
