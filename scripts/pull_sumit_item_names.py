#!/usr/bin/env python3
"""
משיכת שם פריט ההוצאה מ-SUMIT לכל הוצאה (getdetails) ושמירתו ב-sumit_item_name.
שם הפריט (למשל "הוצאות נסיעה") הוא אות הסיווג האמין — שם הספק כמעט תמיד "ספק כללי".

resumable: מדלג על הוצאות שכבר יש בהן sumit_item_name; commit כל 10 רשומות;
backoff מתגבר על 403 (rate limit) כדי לא להיחסם.

שימוש:
    DATABASE_URL="sqlite:///./cfo.db" python scripts/pull_sumit_item_names.py --org 1
"""
import argparse
import asyncio
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cfo.database import SessionLocal  # noqa: E402
from cfo.models import Expense  # noqa: E402
from cfo.services.sync_engine import get_connector_for_org  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cooldown", type=float, default=90.0,
                        help="שניות המתנה אחרי חסימת 403 לפני round חוזר")
    parser.add_argument("--max-rounds", type=int, default=20, dest="max_rounds")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = (
            db.query(Expense)
            .filter(
                Expense.organization_id == args.org,
                Expense.source == "sumit",
                Expense.external_id.isnot(None),
                Expense.sumit_item_name.is_(None),
            )
            .order_by(Expense.id)
        )
        rows = q.all()
        if args.limit:
            rows = rows[: args.limit]
        total = len(rows)
        print(f"to pull: {total}", flush=True)

        connector, _cid, source = get_connector_for_org(db, args.org, preferred_source="sumit")
        if source != "sumit":
            raise SystemExit("SUMIT not connected for org")

        names = collections.Counter()
        total_done = 0

        async def one_pass(pass_rows):
            """פאס יחיד מעל רשומות. מחזיר ('done', n) או ('blocked', n) אם
            נעצר עקב 403 רצופים."""
            nonlocal total_done
            client = await connector._get_client()
            done = 0
            backoff = args.delay
            consecutive_403 = 0
            async with client:
                for e in pass_rows:
                    try:
                        d = await client.get_document_supplier_details(e.external_id)
                        consecutive_403 = 0
                        backoff = args.delay
                    except Exception as exc:
                        if "403" in str(exc):
                            consecutive_403 += 1
                            if consecutive_403 >= 8:
                                db.commit()
                                return "blocked", done
                            backoff = min(backoff * 2, 30.0)
                            print(f"  rate-limited ({consecutive_403}), backoff -> "
                                  f"{backoff:.1f}s", flush=True)
                            await asyncio.sleep(backoff)
                            continue
                        print(f"  err #{e.id}: {str(exc)[:60]}", flush=True)
                        await asyncio.sleep(args.delay)
                        continue
                    item_name = (d.get("item_name") or "").strip()
                    tax_id = (d.get("tax_id") or "").strip()
                    name = (d.get("name") or "").strip()
                    # "" (לא None) מסמן "נבדק ואין פריט" כדי לא לחזור עליו
                    e.sumit_item_name = item_name or ""
                    names[item_name or "(none)"] += 1
                    if tax_id and not e.supplier_tax_id:
                        e.supplier_tax_id = tax_id
                    if d.get("vat") and not float(e.vat_amount or 0):
                        e.vat_amount = d["vat"]
                    cur = (e.supplier_name or "").strip()
                    if name and name not in ("ספק כללי", "ספק SUMIT") and (
                        cur.isdigit() or cur in ("", "ספק SUMIT", "ספק כללי", "ספק")
                    ):
                        e.supplier_name = name
                    done += 1
                    total_done += 1
                    if done % 10 == 0:
                        db.commit()
                        print(f"  {total_done}/{total}", flush=True)
                    await asyncio.sleep(backoff)
            db.commit()
            return "done", done

        # לולאת rounds חיצונית: עוקפת חסימת cooldown של SUMIT ע"י המתנה
        # והרצה חוזרת רק על הרשומות שעדיין חסרות שם-פריט.
        cooldown = args.cooldown
        for rnd in range(1, args.max_rounds + 1):
            remaining = [e for e in rows if e.sumit_item_name is None]
            if not remaining:
                break
            print(f"--- round {rnd}: {len(remaining)} remaining ---", flush=True)
            status, n = await one_pass(remaining)
            db.expire_all()  # רענון מצב הרשומות ל-round הבא
            if status == "done":
                break
            print(f"  blocked after {n} this round; cooldown {cooldown}s then retry",
                  flush=True)
            await asyncio.sleep(cooldown)
            cooldown = min(cooldown * 1.5, 600)

        print(f"\ndone: {total_done} pulled this run", flush=True)
        print("=== distinct item names ===", flush=True)
        for k, v in names.most_common():
            print(f"  {k!r} x{v}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
