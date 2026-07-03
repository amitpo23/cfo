#!/usr/bin/env python3
"""בדיקת schema drift — קריאה בלבד. exit 1 אם יש drift.

הרצה:  DATABASE_URL=postgresql+psycopg://... python scripts/schema_drift_check.py
או:    python scripts/schema_drift_check.py --env-file /path/to/.env.prod
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="קובץ env לטעינת DATABASE_URL ממנו")
    args = parser.parse_args()

    if args.env_file:
        for line in open(args.env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

    # No explicit fallback needed here: cfo.config.Settings.database_url
    # already defaults to the local sqlite db when DATABASE_URL isn't set —
    # that's what makes "no --env-file" mean "check the local db".
    from cfo.database import engine
    from cfo.services.schema_sync import compute_missing

    missing = compute_missing(engine)
    if not missing["tables"] and not missing["columns"]:
        print("OK — אין drift: הסכמה החיה תואמת את המודלים")
        return 0

    print("DRIFT נמצא:")
    for t in missing["tables"]:
        print(f"  טבלה חסרה: {t}")
    for t, cols in missing["columns"].items():
        print(f"  עמודות חסרות ב-{t}: {', '.join(cols)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
