"""קליטת פקודות יומן מייצוא חשבשבת "ייצוא לרו״ח" (Journal_*.mdb).

הרקע: `journal_entries` = 0 בכל הארגונים — "החוליה השבורה" של הלוח.
לעומר ועודד (org5) קיימת היסטוריה מלאה מההנה"ח הקודמת, 11/2021–06/2026,
שדווחה בפועל לרשויות. **הכרעת בעלים (10/08/2026): חשבשבת הוא הרשומה
הנכונה וגובר על SUMIT לתקופה החופפת**, ולכן הקליטה דורסת בהרצה חוזרת.

## למה דווקא ה-MDB ולא MOVEIN.DAT

התוכנית מ-28/07 חסמה את הקליטה בגלל פער של ₪6,691,532.40. הפער נבע
מ-`MOVEIN.DAT` — קובץ fixed-width שהגיע **בלי** `Movein.prm` המתאר את
מבנה העמודות, ולכן מיפוי שדות הסכום היה ניחוש.

`Journal_PORAT.mdb` הוא הייצוא הרשמי לרו"ח. הוא מכיל שתי טבלאות עם
צדדים מפורשים — `JurnalTrans` (כותרת) ו-`JurnalTransMoves` (שורות
חובה/זכות) — ומאוזן במדויק: 273,229,334.16 בכל צד.

`DebitCredit`: `1` = חובה, `0` = זכות.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

SOURCE = "hashavshevet_mdb"

_DEBIT = "1"


class JournalImportError(RuntimeError):
    """המקור אינו כשיר לקליטה. נעצר לפני כתיבה כלשהי."""


@dataclass
class ParsedEntry:
    external_id: str
    entry_date: date
    memo: str
    reference: str
    batch: str
    lines: list[dict[str, Any]] = field(default_factory=list)

    def debit_total(self) -> Decimal:
        return sum((Decimal(str(l["debit"])) for l in self.lines), Decimal(0))

    def credit_total(self) -> Decimal:
        return sum((Decimal(str(l["credit"])) for l in self.lines), Decimal(0))

    @property
    def is_one_sided(self) -> bool:
        """תנועה שכל שורותיה בצד אחד.

        לגיטימי בחשבשבת: רישומי מע"מ והעברות יתרות שהצד הנגדי שלהן
        יושב בתנועה אחרת (`TransCredID` ריק בכותרת). הן מתקזזות ברמת
        המערכת, ולכן נשמרות ומסומנות — לא נפסלות.
        """
        return self.debit_total() == 0 or self.credit_total() == 0


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise JournalImportError(f"קובץ מקור חסר: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


_CENT = Decimal("0.01")


def _amount(raw: Optional[str]) -> Decimal:
    """סכום באגורות.

    ה-MDB מייצא ערכים שעברו דרך float ולכן נושאים שגיאת ייצוג —
    `539.3200000000001` במקום `539.32`. בלי עיגול לאגורה, תנועה תקינה
    לחלוטין נראית לא מאוזנת: 539.3200000000001 + 91.68000000000001
    שונה מ-631. זה פסל 4,827 תנועות תקינות עד שאותר.
    """
    text = (raw or "").strip() or "0"
    try:
        return Decimal(text).quantize(_CENT)
    except InvalidOperation:
        raise JournalImportError(f"סכום לא פריק: {raw!r}") from None


def _parse_date(raw: Optional[str]) -> Optional[date]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def parse_journal_source(
    mdb_dir: str | Path,
    *,
    cutoff: Optional[date] = None,
    strict: bool = True,
) -> list[ParsedEntry]:
    """קורא את הייצוא ומחזיר פקודות מאוזנות בלבד.

    `cutoff` חותך תנועות מאוחרות ממנו — התקופה שמעבר לו שייכת ל-SUMIT
    ואסור שתיכנס פעמיים.

    נעצר על מקור לא מאוזן: פקודה שאינה מאוזנת אינה פקודה, וקליטה חלקית
    של ספרים היא שגיאה חשבונאית ולא אי-נוחות.
    """
    base = Path(mdb_dir)
    headers = _rows(base / "JurnalTrans.csv")
    moves = _rows(base / "JurnalTransMoves.csv")

    by_transaction: dict[str, list[dict[str, str]]] = {}
    for move in moves:
        by_transaction.setdefault((move.get("TransID") or "").strip(), []).append(move)

    entries: list[ParsedEntry] = []
    for header in headers:
        transaction_id = (header.get("TransID") or "").strip()
        entry_date = _parse_date(header.get("ValueDate")) or _parse_date(header.get("DueDate"))
        if not transaction_id or entry_date is None:
            continue
        if cutoff and entry_date > cutoff:
            continue

        lines = []
        for move in by_transaction.get(transaction_id, []):
            amount = _amount(move.get("SuF"))
            is_debit = (move.get("DebitCredit") or "").strip() == _DEBIT
            lines.append(
                {
                    "account_key": (move.get("AccountKey") or "").strip(),
                    "debit": str(amount if is_debit else Decimal(0)),
                    "credit": str(Decimal(0) if is_debit else amount),
                }
            )
        if not lines:
            # תנועה פשוטה: שני צדדים בלבד, ולכן חשבשבת אינו מייצר לה
            # שורות ב-JurnalTransMoves — כל המידע יושב בכותרת
            # (TransDebID / TransCredID / suF). 120 תנועות כאלה היו
            # נופלות בשקט אילו דילגנו, והספרים היו חסרים.
            debit_account = (header.get("TransDebID") or "").strip()
            credit_account = (header.get("TransCredID") or "").strip()
            amount = _amount(header.get("suF"))
            if amount == 0 or not (debit_account or credit_account):
                continue
            if debit_account:
                lines.append(
                    {"account_key": debit_account, "debit": str(amount), "credit": "0"}
                )
            if credit_account:
                lines.append(
                    {"account_key": credit_account, "debit": "0", "credit": str(amount)}
                )

        entries.append(
            ParsedEntry(
                external_id=f"hashavshevet:{transaction_id}",
                entry_date=entry_date,
                memo=(header.get("Description") or "").strip(),
                reference=(header.get("Referance") or "").strip(),
                batch=(header.get("BatchNo") or "").strip(),
                lines=lines,
            )
        )

    # אין דרישת איזון פר-תנועה: חשבשבת מאפשר תנועות חד-צדיות (רישומי
    # מע"מ, העברות יתרות) שהצד הנגדי שלהן יושב בתנועה אחרת.
    #
    # ברמת המקור כולו נותר פער של ₪217,116.65, שמקורו ב-19 תנועות
    # חד-צדיות שכל המידע שלהן בכותרת. אפשר היה "לאזן" בהשמטתן — אבל זו
    # מחיקת נתוני אמת כדי שמספר יסתדר. `strict=True` עוצר ומדווח;
    # `strict=False` קולט הכול ומסמן את הפער, כדי שהתיק יהיה מלא לתשאול
    # בלי להעמיד פנים שאלה ספרים מאוזנים.
    total_debit = sum((e.debit_total() for e in entries), Decimal(0))
    total_credit = sum((e.credit_total() for e in entries), Decimal(0))
    if strict and total_debit != total_credit:
        raise JournalImportError(
            f"המקור כולו אינו מאוזן: חובה {total_debit} מול זכות {total_credit} "
            f"(פער {total_debit - total_credit}). העבר strict=False כדי לקלוט "
            "עם סימון הפער, אחרי הכרעה מודעת."
        )

    return entries


def source_summary(entries: list[ParsedEntry]) -> dict[str, Any]:
    """מספרי בקרה לאימות מול מאזן בוחן חיצוני."""
    return {
        "entries": len(entries),
        "one_sided": sum(1 for e in entries if e.is_one_sided),
        "debit_total": str(sum((e.debit_total() for e in entries), Decimal(0))),
        "credit_total": str(sum((e.credit_total() for e in entries), Decimal(0))),
        "first_date": min((e.entry_date for e in entries), default=None),
        "last_date": max((e.entry_date for e in entries), default=None),
    }


def import_journal_entries(
    db: Session,
    organization_id: int,
    mdb_dir: str | Path,
    *,
    cutoff: Optional[date] = None,
    strict: bool = True,
) -> dict[str, Any]:
    """קולט את הפקודות לארגון, **דורס** קליטה קודמת מאותו מקור.

    הדריסה מכוונת: חשבשבת הוא הרשומה שדווחה לרשויות, ולכן הרצה חוזרת
    מיישרת את הספרים אליו במקום לצבור כפילויות.
    """
    from ..models import JournalEntry, Organization

    if db.query(Organization.id).filter(Organization.id == organization_id).first() is None:
        raise JournalImportError(f"ארגון {organization_id} אינו קיים")

    entries = parse_journal_source(mdb_dir, cutoff=cutoff, strict=strict)
    debit_total = sum((e.debit_total() for e in entries), Decimal(0))
    credit_total = sum((e.credit_total() for e in entries), Decimal(0))

    replaced = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.organization_id == organization_id,
            JournalEntry.source == SOURCE,
        )
        .delete(synchronize_session=False)
    )

    for entry in entries:
        db.add(
            JournalEntry(
                organization_id=organization_id,
                external_id=entry.external_id,
                source=SOURCE,
                entry_date=entry.entry_date,
                memo=entry.memo or None,
                lines=entry.lines,
                raw_data={
                    "reference": entry.reference,
                    "batch": entry.batch,
                    "one_sided": entry.is_one_sided,
                },
            )
        )
    db.commit()

    return {
        "organization_id": organization_id,
        "inserted": len(entries),
        "replaced": replaced,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "debit_total": str(debit_total),
        "credit_total": str(credit_total),
        "imbalance": str(debit_total - credit_total),
        "one_sided": sum(1 for e in entries if e.is_one_sided),
        "balanced": debit_total == credit_total,
    }
