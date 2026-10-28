"""Print the stored checking balance of each organization.

Read-only. Does not call SUMIT or Open Finance and does not write.
Uses the database this process is already configured with. Do not pass a
production env file from an unattended run.
"""
from __future__ import annotations

import json

from cfo.database import SessionLocal
from cfo.services.dashboards.balance_diagnostic import diagnose_all


def main() -> None:
    with SessionLocal() as db:
        report = diagnose_all(db)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
