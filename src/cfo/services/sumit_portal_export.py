"""SUMIT portal file import: profit and loss, balance sheet, ledger cards.

The CFO exports the file from the SUMIT portal in the browser (CSV or xlsx).
This module never builds a SUMIT or Open Finance client. Rows are stored on
``JournalEntry`` with ``source='sumit_portal_export'`` and an empty ``lines``
list, so they stay out of the derived ledger and out of OPENFRMT B100.
Re-import of the same kind and report date updates that snapshot in place.

Expected columns (Hebrew headers as exported from the portal grid, or the
English aliases). A title row above the header is ignored.

* Account code: מפתח, מפתח חשבון, מספר חשבון, קוד חשבון, קוד, account_code
* Account name: שם חשבון, שם הכרטיס, שם, account_name
* Section: סעיף, קבוצה, סיווג, סוג, section
  נכסים / התחייבויות / הון / הכנסות / הוצאות
* Amount: יתרה or סכום (a blank cell stays unknown, it is not zero)
* Ledger card movements also use תאריך, אסמכתא, פרטים, חובה, זכות

A section banner row (a single cell "נכסים") applies to the rows under it.
A totals row (סה״כ) is not an account. Debit and credit are used only when
the file has no amount column: assets and expenses are debit minus credit,
liabilities, equity and revenue are credit minus debit. Without a section
that sign is not guessed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError

from ..models import Account, AccountType, AuditLog, JournalEntry

SOURCE = "sumit_portal_export"
SOURCE_LABEL = "ייצוא פורטל SUMIT"
KINDS = ("balance_sheet", "profit_loss", "ledger_cards")
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
_CODE = re.compile(r"[\w./-]{1,60}", re.UNICODE)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_LOCAL_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")

_SECTIONS = (
    ("asset", ("נכסים", "נכס", "רכוש שוטף", "רכוש קבוע", "asset", "assets")),
    ("liability", ("התחייבויות", "התחייבות", "התחייבויות שוטפות", "liability", "liabilities")),
    ("equity", ("הון עצמי", "הון ויתרות", "הון ועודפים", "הון", "equity")),
    ("revenue", ("הכנסות", "הכנסה", "revenue", "income")),
    ("expense", ("הוצאות", "הוצאה", "expense", "expenses")),
)
_PLACED = {
    "balance_sheet": {"asset", "liability", "equity"},
    "profit_loss": {"revenue", "expense"},
}
_ACCOUNT_SECTION = {
    AccountType.ASSET: "asset",
    AccountType.BANK: "asset",
    AccountType.ACCOUNTS_RECEIVABLE: "asset",
    AccountType.LIABILITY: "liability",
    AccountType.ACCOUNTS_PAYABLE: "liability",
    AccountType.EQUITY: "equity",
    AccountType.REVENUE: "revenue",
    AccountType.EXPENSE: "expense",
}
_HEADER_FIELDS = (
    ("code", ("מפתח חשבון", "מספר חשבון", "קוד חשבון", "מפתח", "קוד", "כרטיס", "account_code", "code")),
    ("name", ("שם חשבון", "שם הכרטיס", "שם", "account_name", "name")),
    ("section", ("סעיף מאזן", "סעיף", "קבוצה", "סיווג", "סוג", "section")),
    ("amount", ("יתרה בש\"ח", "יתרה", "סכום", "amount", "balance")),
    ("debit", ("חובה", "debit")),
    ("credit", ("זכות", "credit")),
    ("date", ("תאריך אסמכתא", "תאריך", "date")),
    ("reference", ("אסמכתא", "אסמכתה", "מספר מסמך", "reference")),
    ("detail", ("פרטים", "תיאור תנועה", "הערה", "description")),
    ("as_of", ("תאריך מאזן", "עד תאריך", "ליום", "as_of")),
)
_KIND_ALIASES = {
    "balance_sheet": "balance_sheet",
    "balance": "balance_sheet",
    "מאזן": "balance_sheet",
    "profit_loss": "profit_loss",
    "pnl": "profit_loss",
    "רווח והפסד": "profit_loss",
    "ledger_cards": "ledger_cards",
    "cards": "ledger_cards",
    "כרטיסים": "ledger_cards",
    "כרטיסי הנהח": "ledger_cards",
    "כרטסת": "ledger_cards",
}


class PortalImportError(ValueError):
    """The file is not a usable SUMIT portal export. Nothing was stored."""


def norm_text(value) -> str:
    text = str(value or "")
    text = text.replace("\ufeff", "").replace("\u200f", "").replace("\u200e", "")
    text = text.replace("״", "\"").replace("׳", "'")
    text = " ".join(text.strip().strip(":").split())
    return text.casefold()


def _header_field(value) -> str | None:
    text = norm_text(value)
    if not text:
        return None
    for field, names in _HEADER_FIELDS:
        if text in {norm_text(name) for name in names}:
            return field
    return None


def _section_name(value) -> str | None:
    text = norm_text(value)
    if not text:
        return None
    for section, words in _SECTIONS:
        for word in sorted(words, key=len, reverse=True):
            token = norm_text(word)
            if text == token or text.startswith(token + " "):
                return section
    return None


def _is_total(name: str) -> bool:
    text = norm_text(name).replace("\"", "")
    return text in {"סהכ", "סך הכל", "total"} or text.startswith("סהכ") or text.startswith("סך הכל") or text.startswith("total")


def _quantize(number: Decimal) -> Decimal:
    if not number.is_finite() or abs(number) >= Decimal("1000000000"):
        raise ValueError("out of range")
    return number.quantize(Decimal("0.01"))


def parse_amount(value):
    """A blank amount is unknown. An explicit 0 stays 0."""
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            raise ValueError("bool")
        return None
    if isinstance(value, Decimal):
        return _quantize(value)
    if isinstance(value, int):
        return _quantize(Decimal(value))
    if isinstance(value, float):
        return _quantize(Decimal(str(value)))
    text = str(value).strip().replace("\u00a0", " ")
    if text in {"", "-", "—"}:
        return None
    negative = False
    text = text.replace("₪", "").replace("NIS", "").replace("ש\"ח", "").strip()
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    if text.endswith("-"):
        negative = True
        text = text[:-1].strip()
    text = text.replace(" ", "")
    if text.startswith("-"):
        negative = True
        text = text[1:]
    if text == "":
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            text = parts[0] + "." + parts[1]
        else:
            text = text.replace(",", "")
    number = _quantize(Decimal(text))
    return -number if negative else number


def money_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(_quantize(value), "f")


def amount_out(value) -> float | None:
    if value is None or value == "":
        return None
    return float(Decimal(str(value)))


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    iso = _ISO_DATE.fullmatch(text[:10])
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    local = _LOCAL_DATE.search(text)
    if local:
        return date(int(local.group(3)), int(local.group(2)), int(local.group(1)))
    raise ValueError(text)


def _check_as_of(day: date, today: date) -> date:
    if day < date(1990, 1, 1) or day > today + timedelta(days=1):
        raise PortalImportError("תאריך הדוח מחוץ לטווח")
    return day


def _kind_alias(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    token = norm_text(value).replace("\"", "").replace("'", "")
    kind = _KIND_ALIASES.get(token) or _KIND_ALIASES.get(norm_text(value))
    if kind is None:
        raise PortalImportError("סוג דוח לא מוכר. בחרו מאזן, רווח והפסד או כרטיסי הנה״ח.")
    return kind


def _code(value, row_number: int) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        text = str(value)
    else:
        text = str(value).strip()
    if text == "":
        return None
    if not _CODE.fullmatch(text):
        raise PortalImportError(f"שורה {row_number}: מפתח חשבון לא תקין")
    return text


def _cell(row, columns, field):
    index = columns.get(field)
    if index is None or index >= len(row):
        return None
    return row[index]


def _read_table(content: bytes, filename: str) -> list[list]:
    name = (filename or "").lower()
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        raise PortalImportError("קבצי xls ישנים אינם נתמכים. ייצאו CSV או xlsx.")
    if name.endswith(".xlsx") or content[:2] == b"PK":
        import openpyxl
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        except Exception as exc:
            raise PortalImportError("קובץ ה-Excel לא נקרא. ייצאו xlsx או CSV.") from exc
        try:
            sheet = workbook.worksheets[0]
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1255"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise PortalImportError("הקובץ אינו UTF-8 או Windows-1255")
    sample = "\n".join(text.splitlines()[:20])
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _find_header(rows: list[list]) -> tuple[int, dict]:
    for index, row in enumerate(rows[:30]):
        columns = {}
        for cell_index, cell in enumerate(row[:40]):
            field = _header_field(cell)
            if field and field not in columns:
                columns[field] = cell_index
        if "code" in columns and columns.keys() & {"name", "amount", "debit", "credit", "section"}:
            return index, columns
    raise PortalImportError("לא נמצאה שורת כותרות. צריך מפתח חשבון ועמודה של שם, סעיף, יתרה או חובה/זכות.")


def _signed_amount(kind: str, section: str | None, explicit, debit, credit):
    if explicit is not None or kind == "ledger_cards":
        return explicit
    if debit is None and credit is None:
        return None
    debit = debit or Decimal("0")
    credit = credit or Decimal("0")
    if kind == "balance_sheet" and section == "asset":
        return _quantize(debit - credit)
    if kind == "balance_sheet" and section in {"liability", "equity"}:
        return _quantize(credit - debit)
    if kind == "profit_loss" and section == "revenue":
        return _quantize(credit - debit)
    if kind == "profit_loss" and section == "expense":
        return _quantize(debit - credit)
    return None


def _detect_kind(columns, lines, filename: str) -> str:
    if "date" in columns and ({"debit", "credit"} & columns.keys()):
        return "ledger_cards"
    found = set()
    for line in lines:
        if line["section"] in {"asset", "liability", "equity"}:
            found.add("balance_sheet")
        elif line["section"] in {"revenue", "expense"}:
            found.add("profit_loss")
    if found == {"balance_sheet"}:
        return "balance_sheet"
    if found == {"profit_loss"}:
        return "profit_loss"
    name = filename or ""
    folded = name.casefold()
    if "כרטיס" in name or "כרטס" in name:
        return "ledger_cards"
    if "רווח" in name or "profit" in folded:
        return "profit_loss"
    if "מאזן" in name or "balance" in folded:
        return "balance_sheet"
    if len(found) > 1:
        raise PortalImportError("הקובץ מערבב מאזן ורווח והפסד. בחרו את סוג הדוח.")
    raise PortalImportError("לא זוהה סוג הדוח. בחרו מאזן, רווח והפסד או כרטיסי הנה״ח.")


def _collect_dates(values) -> list[date]:
    found = []
    for value in values:
        if value is None or value == "":
            continue
        try:
            day = parse_date(value)
        except ValueError:
            continue
        if day is not None:
            found.append(day)
    return found


def parse_portal_export(content: bytes, *, filename: str, kind: str | None, as_of: str | None,
                        today: date | None = None) -> dict:
    if not content:
        raise PortalImportError("הקובץ ריק")
    if len(content) > MAX_BYTES:
        raise PortalImportError("הקובץ גדול מ-5MB")
    today = today or datetime.now(timezone.utc).date()
    rows = _read_table(content, filename)
    header_at, columns = _find_header(rows)
    errors = []
    current_section = None
    draft = []
    column_dates = []
    for offset, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        if not any(cell not in (None, "") for cell in row):
            continue
        row_number = offset
        try:
            code = _code(_cell(row, columns, "code"), row_number)
            name = str(_cell(row, columns, "name") or "").strip()
            section = _section_name(_cell(row, columns, "section")) or current_section
            explicit = parse_amount(_cell(row, columns, "amount"))
            debit = parse_amount(_cell(row, columns, "debit"))
            credit = parse_amount(_cell(row, columns, "credit"))
            movement_date = parse_date(_cell(row, columns, "date"))
            if "as_of" in columns:
                column_dates.extend(_collect_dates([_cell(row, columns, "as_of")]))
        except (PortalImportError, ValueError, InvalidOperation) as exc:
            if isinstance(exc, PortalImportError):
                errors.append(str(exc))
            else:
                errors.append(f"שורה {row_number}: סכום או תאריך לא תקין")
            continue
        if code is None and not name and explicit is None and debit is None and credit is None:
            banner = None
            for cell in row[:8]:
                banner = _section_name(cell) or banner
            if banner:
                current_section = banner
            continue
        if code is None and _is_total(name):
            continue
        if not name and code is None:
            errors.append(f"שורה {row_number}: חסר מפתח או שם חשבון")
            continue
        draft.append({
            "row_number": row_number,
            "code": code,
            "name": name or code,
            "section": section,
            "explicit": explicit,
            "debit": debit,
            "credit": credit,
            "movement_date": movement_date,
            "reference": str(_cell(row, columns, "reference") or "").strip()[:80],
            "detail": str(_cell(row, columns, "detail") or "").strip()[:200],
        })
        if len(draft) > MAX_ROWS:
            raise PortalImportError("יותר מ-5,000 שורות. פצלו את הייצוא.")
    if errors:
        raise PortalImportError(" · ".join(errors[:8]))
    if not draft:
        raise PortalImportError("אין שורות לייבוא")
    requested = _kind_alias(kind)
    detected = _detect_kind(columns, draft, filename)
    resolved_kind = requested or detected
    lines = []
    for line in draft:
        amount = _signed_amount(resolved_kind, line["section"], line["explicit"], line["debit"], line["credit"])
        movement = None
        if resolved_kind == "ledger_cards":
            movement = {
                "date": line["movement_date"].isoformat() if line["movement_date"] else None,
                "reference": line["reference"],
                "detail": line["detail"],
                "debit": money_str(line["debit"]),
                "credit": money_str(line["credit"]),
            }
            if movement["date"] is None and not movement["reference"] and not movement["detail"] and movement["debit"] is None and movement["credit"] is None:
                movement = None
        lines.append({
            "code": line["code"],
            "name": line["name"][:255],
            "section": line["section"],
            "amount": amount,
            "movement": movement,
            "row_number": line["row_number"],
        })
    form_day = None
    if as_of:
        try:
            form_day = parse_date(as_of)
        except ValueError as exc:
            raise PortalImportError("תאריך הדוח אינו YYYY-MM-DD") from exc
        if form_day is None:
            raise PortalImportError("תאריך הדוח אינו YYYY-MM-DD")
    if form_day is not None:
        report_day, as_of_source = form_day, "form"
    elif column_dates:
        unique = set(column_dates)
        if len(unique) > 1:
            raise PortalImportError("תאריך הדוח אינו אחיד בקובץ")
        report_day, as_of_source = column_dates[0], "file"
    else:
        preamble = _collect_dates(cell for row in rows[:header_at] for cell in row[:8])
        if preamble:
            report_day, as_of_source = preamble[0], "file"
        else:
            report_day, as_of_source = today, "import_date"
    report_day = _check_as_of(report_day, today)
    seen = set()
    for line in lines:
        line["external_id"] = _identity(resolved_kind, report_day, line)
        if line["external_id"] in seen:
            raise PortalImportError(f"שורה {line['row_number']}: מפתח {line['code'] or line['name']} מופיע פעמיים")
        seen.add(line["external_id"])
    return {
        "kind": resolved_kind,
        "as_of": report_day,
        "as_of_source": as_of_source,
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "lines": lines,
    }


def _identity(kind: str, as_of: date, line: dict) -> str:
    code = line["code"] or ("name:" + hashlib.sha256(line["name"].encode()).hexdigest()[:16])
    base = f"{kind}:{as_of.isoformat()}:{code}"
    if line["movement"]:
        digest = hashlib.sha256(
            json.dumps(line["movement"], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:20]
        base = f"{base}:{digest}"
    if len(base) > 255:
        raise PortalImportError("מזהה שורה ארוך מדי")
    return base


def _account_section(account) -> str | None:
    raw = account.account_type
    if isinstance(raw, AccountType):
        return _ACCOUNT_SECTION.get(raw)
    try:
        return _ACCOUNT_SECTION.get(AccountType(str(getattr(raw, "value", raw))))
    except ValueError:
        return None


def _index_accounts(db, organization_id: int):
    by_code: dict[str, list] = {}
    by_name: dict[str, list] = {}
    for account in db.query(Account).filter(Account.organization_id == organization_id).all():
        for key in (account.source_account_code, account.sumit_account_code, account.external_id):
            if key:
                by_code.setdefault(str(key).strip(), []).append(account)
        if account.name and str(account.name).strip():
            by_name.setdefault(norm_text(account.name), []).append(account)
    return by_code, by_name


def _unique(accounts: list) -> list:
    seen = set()
    out = []
    for account in accounts:
        if account.id in seen:
            continue
        seen.add(account.id)
        out.append(account)
    return out


def _applies(kind: str, section: str | None) -> bool:
    if kind == "ledger_cards":
        return True
    return section in _PLACED[kind]


def _map_line(kind: str, line: dict, by_code, by_name) -> dict:
    section = line["section"]
    if line["code"]:
        matches = _unique(by_code.get(line["code"], []))
        missing = "אין חשבון ברצף עם המפתח הזה"
        ambiguous = "יותר מחשבון אחד ברצף תואם למפתח"
    else:
        matches = _unique(by_name.get(norm_text(line["name"]), []))
        missing = "אין חשבון ברצף עם השם הזה"
        ambiguous = "יותר מחשבון אחד ברצף תואם לשם"
    account_id = None
    if len(matches) > 1:
        mapped, reason = False, ambiguous
    elif len(matches) == 1:
        mapped, reason = True, None
        account_id = matches[0].id
        if section is None:
            section = _account_section(matches[0])
    else:
        mapped, reason = False, missing
    if not _applies(kind, section):
        reason = reason or "השורה אינה בסעיף של הדוח שנבחר"
    canonical = {
        "code": line["code"],
        "name": line["name"],
        "section": section,
        "amount": money_str(line["amount"]),
        "mapped": mapped,
        "reason": reason,
        "applies": _applies(kind, section),
        "rezef_account_id": account_id,
        "movement": line["movement"],
    }
    return {
        "external_id": line["external_id"],
        "canonical": canonical,
        "payload_hash": hashlib.sha256(
            json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }


def import_portal_export(db, organization_id: int, content: bytes, *, filename: str,
                         kind: str | None = None, as_of: str | None = None, actor_id: int | None = None) -> dict:
    parsed = parse_portal_export(content, filename=filename or "", kind=kind, as_of=as_of)
    by_code, by_name = _index_accounts(db, organization_id)
    mapped_lines = [_map_line(parsed["kind"], line, by_code, by_name) for line in parsed["lines"]]
    now = datetime.now(timezone.utc).isoformat()
    prefix = f"{parsed['kind']}:{parsed['as_of'].isoformat()}:"
    try:
        existing = {
            row.external_id: row
            for row in db.query(JournalEntry).filter(
                JournalEntry.organization_id == organization_id,
                JournalEntry.source == SOURCE,
                JournalEntry.external_id.startswith(prefix),
            ).all()
        }
        inserted = updated = unchanged = 0
        seen = set()
        for line in mapped_lines:
            seen.add(line["external_id"])
            raw = {
                "kind": parsed["kind"],
                "as_of": parsed["as_of"].isoformat(),
                "as_of_source": parsed["as_of_source"],
                "imported_at": now,
                "filename": (filename or "")[:255],
                "file_sha256": parsed["file_sha256"],
                "provider_calls": 0,
                "official_posting": False,
                "line": line["canonical"],
            }
            current = existing.get(line["external_id"])
            if current is None:
                db.add(JournalEntry(
                    organization_id=organization_id,
                    source=SOURCE,
                    external_id=line["external_id"],
                    entry_date=parsed["as_of"],
                    memo=(line["canonical"]["name"] or "")[:500],
                    lines=[],
                    raw_data=raw,
                    payload_hash=line["payload_hash"],
                ))
                inserted += 1
            elif current.payload_hash == line["payload_hash"]:
                unchanged += 1
            else:
                current.entry_date = parsed["as_of"]
                current.memo = (line["canonical"]["name"] or "")[:500]
                current.lines = []
                current.raw_data = raw
                current.payload_hash = line["payload_hash"]
                updated += 1
        removed = 0
        for external_id, row in existing.items():
            if external_id not in seen:
                db.delete(row)
                removed += 1
        unmapped = [
            line["canonical"] for line in mapped_lines
            if not line["canonical"]["mapped"] or not line["canonical"]["applies"]
        ]
        db.add(AuditLog(
            user_id=actor_id,
            organization_id=organization_id,
            action="IMPORT_SUMIT_PORTAL_EXPORT",
            entity_type="JournalEntry",
            entity_id=None,
            details={
                "kind": parsed["kind"],
                "as_of": parsed["as_of"].isoformat(),
                "filename": (filename or "")[:255],
                "file_sha256": parsed["file_sha256"],
                "inserted": inserted,
                "updated": updated,
                "unchanged": unchanged,
                "removed": removed,
                "unmapped": len(unmapped),
                "provider_calls": 0,
            },
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PortalImportError("ייבוא מקביל של אותו קובץ. נסו שוב.") from exc
    except Exception:
        db.rollback()
        raise
    stored_sync = _snapshot_sync(db, organization_id, parsed["kind"], parsed["as_of"].isoformat()) or now
    return {
        "kind": parsed["kind"],
        "as_of": parsed["as_of"].isoformat(),
        "as_of_source": parsed["as_of_source"],
        "imported_at": stored_sync,
        "filename": filename or "",
        "file_sha256": parsed["file_sha256"],
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
        "mapped_count": sum(1 for line in mapped_lines if line["canonical"]["mapped"] and line["canonical"]["applies"]),
        "unmapped_count": len(unmapped),
        "unmapped": [_public_unmapped(line) for line in unmapped[:100]],
        "provider_calls": 0,
    }


def _snapshot_sync(db, organization_id: int, kind: str, as_of: str) -> str | None:
    prefix = f"{kind}:{as_of}:"
    stamps = []
    for row in db.query(JournalEntry).filter(
        JournalEntry.organization_id == organization_id,
        JournalEntry.source == SOURCE,
        JournalEntry.external_id.startswith(prefix),
    ).all():
        stamp = (row.raw_data or {}).get("imported_at")
        if stamp:
            stamps.append(stamp)
    return max(stamps) if stamps else None


def _public_unmapped(canonical: dict) -> dict:
    return {
        "code": canonical.get("code"),
        "name": canonical.get("name"),
        "reason": canonical.get("reason"),
        "amount": amount_out(canonical.get("amount")),
    }


def _public_snapshot_line(row: JournalEntry) -> dict | None:
    raw = row.raw_data or {}
    line = raw.get("line") if isinstance(raw.get("line"), dict) else None
    if line is None:
        return None
    movement = line.get("movement") if isinstance(line.get("movement"), dict) else None
    return {
        "code": line.get("code"),
        "name": line.get("name") or "",
        "section": line.get("section"),
        "amount": amount_out(line.get("amount")),
        "mapped": bool(line.get("mapped")),
        "reason": line.get("reason"),
        "applies": bool(line.get("applies")),
        "movement_date": (movement or {}).get("date"),
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
        "synced_at": raw.get("imported_at"),
    }


def load_snapshots(db, organization_id: int) -> dict:
    """The latest stored export of each kind. Missing kinds are absent."""
    rows = db.query(JournalEntry).filter(
        JournalEntry.organization_id == organization_id,
        JournalEntry.source == SOURCE,
    ).all()
    groups: dict[tuple, list] = {}
    for row in rows:
        raw = row.raw_data or {}
        kind = raw.get("kind")
        if kind not in KINDS:
            continue
        groups.setdefault((kind, raw.get("as_of") or ""), []).append(row)
    latest: dict[str, list] = {}
    ranks: dict[str, tuple] = {}
    for (kind, as_of), items in groups.items():
        stamp = max(((item.raw_data or {}).get("imported_at") or "") for item in items)
        rank = (stamp, as_of)
        if kind not in latest or rank > ranks[kind]:
            latest[kind] = items
            ranks[kind] = rank
    out = {}
    for kind, items in latest.items():
        raws = [item.raw_data or {} for item in items]
        stamp = max((raw.get("imported_at") or "") for raw in raws)
        carrier = next((raw for raw in raws if raw.get("imported_at") == stamp), raws[0])
        lines = [line for item in items if (line := _public_snapshot_line(item)) is not None]
        lines.sort(key=lambda line: (line["code"] or "", line["movement_date"] or "", line["name"]))
        out[kind] = {
            "kind": kind,
            "as_of": carrier.get("as_of"),
            "as_of_source": carrier.get("as_of_source"),
            "imported_at": stamp or None,
            "filename": carrier.get("filename"),
            "lines": lines,
            "source": SOURCE,
            "source_label": SOURCE_LABEL,
        }
    return out


def summarize_snapshots(db, organization_id: int) -> dict:
    snapshots = load_snapshots(db, organization_id)
    body = {"provider_calls": 0}
    for kind in KINDS:
        snapshot = snapshots.get(kind)
        if snapshot is None:
            body[kind] = None
            continue
        unmapped = [line for line in snapshot["lines"] if not line["mapped"] or not line["applies"]]
        body[kind] = {
            "kind": kind,
            "as_of": snapshot["as_of"],
            "as_of_source": snapshot["as_of_source"],
            "imported_at": snapshot["imported_at"],
            "filename": snapshot["filename"],
            "line_count": len(snapshot["lines"]),
            "mapped_count": sum(1 for line in snapshot["lines"] if line["mapped"] and line["applies"]),
            "unmapped_count": len(unmapped),
            "unmapped": [
                {"code": line["code"], "name": line["name"], "reason": line["reason"], "amount": line["amount"]}
                for line in unmapped[:50]
            ],
            "provider_calls": 0,
        }
    return body
