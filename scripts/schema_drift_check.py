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
    from cfo.services.schema_sync import compute_schema_drift, has_schema_drift

    drift = compute_schema_drift(engine)
    if not has_schema_drift(drift):
        print("OK — אין drift מבני: הסכמה החיה תואמת את המודלים")
        for table_name, exemptions in drift["dialect_exemptions"].items():
            print(f"WARN — חריגת dialect מתועדת ב-{table_name}: {exemptions}")
        return 0

    print("DRIFT נמצא:")
    for t in drift["tables"]:
        print(f"  טבלה חסרה: {t}")
    for t, cols in drift["columns"].items():
        print(f"  עמודות חסרות ב-{t}: {', '.join(cols)}")
    labels = {
        "types": "אי-התאמות טיפוס",
        "nullability": "אי-התאמות nullability",
        "primary_keys": "מפתחות ראשיים חסרים/שונים",
        "foreign_keys": "מפתחות זרים חסרים",
        "unique_constraints": "אילוצי unique חסרים",
        "indexes": "אינדקסים חסרים",
    }
    for key, label in labels.items():
        for table_name, details in drift[key].items():
            print(f"  {label} ב-{table_name}: {details}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
