#!/usr/bin/env python3
"""Import a verified Hashavshevet account-index CSV into a local SQLite DB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cfo.models import Organization  # noqa: E402
from cfo.services.chart_of_accounts_importer import (  # noqa: E402
    import_chart_of_accounts,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--organization-id", required=True, type=int)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--source-file-hash", required=True)
    parser.add_argument("--create-organization-name")
    parser.add_argument("--create-organization-tax-id")
    args = parser.parse_args()

    if not args.database_url.startswith("sqlite:///"):
        parser.error("offline importer accepts only an explicit sqlite:/// URL")

    engine = create_engine(
        args.database_url, connect_args={"check_same_thread": False}
    )
    db = sessionmaker(bind=engine)()
    try:
        organization = db.query(Organization).filter(
            Organization.id == args.organization_id
        ).first()
        if organization is None:
            if not args.create_organization_name:
                parser.error(
                    f"organization_id={args.organization_id} is missing; "
                    "--create-organization-name is required to create it locally"
                )
            organization = Organization(
                id=args.organization_id,
                name=args.create_organization_name,
                tax_id=args.create_organization_tax_id,
                is_active=True,
            )
            db.add(organization)
            db.commit()

        result = import_chart_of_accounts(
            db,
            organization_id=args.organization_id,
            csv_path=args.csv,
            source_file_hash=args.source_file_hash,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

