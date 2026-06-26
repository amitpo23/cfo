# Automated Collection Reminders (SMS/Email) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically remind customers who haven't paid by their invoice due date, via SMS (SUMIT) and email (SMTP), with escalation (first/second/final) and anti-spam state tracking.

**Architecture:** A new `CollectionService` (sync) plans which reminders are due from real overdue invoices and records what was sent in a new `CollectionReminder` table (state → escalation + cooldown). An async `dispatch_reminders` orchestrator sends through injected channel callables (SMS = SUMIT `send_sms`, email = SMTP). A daily cron iterates orgs that opted in. Reuses the existing Hebrew reminder templates in `ar_service`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SUMIT integration (`send_sms`), Python `smtplib`, pytest.

## Global Constraints
- "No fake data": only real overdue invoices trigger reminders; no fabricated amounts.
- Overdue source of truth: `Invoice.due_date` (encodes the customer's payment terms). Overdue = `due_date < today` AND `status in (sent, partially_paid, overdue)` AND `balance > 0`.
- Anti-spam: never send the same `reminder_type` to the same contact within a 7-day cooldown.
- Opt-in: cron only acts on orgs with `Organization.collection_reminders_enabled == True` (regulatory: no unsolicited SMS).
- All work TDD; run `python -m pytest tests/ -q` green before each commit. Branch: `feat/sumit-ar-ap-documents-ocr`.
- Alembic note: the repo has **multiple migration heads** and `cfo.db` is managed by `create_all`. Model changes are picked up by SQLite tests automatically. Each new migration sets `down_revision` to a current head; if `alembic upgrade head` complains about multiple heads, run `alembic merge heads` first (prod only).

---

### Task 1: `CollectionReminder` model

**Files:**
- Modify: `src/cfo/models.py` (add model near `Invoice`/`Contact`)
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Produces: `CollectionReminder(organization_id:int, contact_id:int|None, invoice_numbers:str, reminder_type:str, channel:str, amount:Decimal, days_overdue:int, status:str, error:str|None, sent_at:datetime)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collection_reminders.py
from datetime import datetime, timezone
from decimal import Decimal
from cfo.database import SessionLocal
from cfo.models import CollectionReminder


def test_collection_reminder_roundtrip(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(CollectionReminder(
            organization_id=org_id, contact_id=None, invoice_numbers="INV-1",
            reminder_type="first", channel="sms", amount=Decimal("100"),
            days_overdue=5, status="sent", sent_at=datetime.now(timezone.utc),
        ))
        db.commit()
        row = db.query(CollectionReminder).filter_by(organization_id=org_id).one()
        assert row.reminder_type == "first" and row.channel == "sms"
    finally:
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py::test_collection_reminder_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'CollectionReminder'`

- [ ] **Step 3: Add the model**

```python
# src/cfo/models.py  (add after the Invoice/Bill section)
class CollectionReminder(Base):
    """תיעוד תזכורת גבייה שנשלחה — מצב להסלמה ומניעת ספאם."""
    __tablename__ = "collection_reminders"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    invoice_numbers = Column(String(500), nullable=True)
    reminder_type = Column(String(20), nullable=False)   # first | second | final
    channel = Column(String(20), nullable=False)         # sms | email
    amount = Column(Numeric(precision=12, scale=2), default=0)
    days_overdue = Column(Integer, default=0)
    status = Column(String(20), default="sent")          # sent | failed
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_collreminder_org_contact", "organization_id", "contact_id"),
    )
```

Ensure `timezone` is imported at the top of `models.py` (it uses `datetime` already; add `from datetime import datetime, timezone` if `timezone` is missing).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cfo/models.py tests/test_collection_reminders.py
git commit -m "feat(collections): add CollectionReminder state model"
```

---

### Task 2: Organization opt-in fields + migration

**Files:**
- Modify: `src/cfo/models.py` (`Organization`)
- Create: `alembic/versions/<rev>_add_collection_reminders.py`
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Produces: `Organization.collection_reminders_enabled: bool` (default False), `Organization.collection_sms_sender: str|None`

- [ ] **Step 1: Write the failing test**

```python
def test_org_collection_defaults(fresh_org):
    from cfo.models import Organization
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.query(Organization).get(org_id)
        assert org.collection_reminders_enabled is False
        assert org.collection_sms_sender is None
    finally:
        db.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py::test_org_collection_defaults -v`
Expected: FAIL — `AttributeError: ... has no attribute 'collection_reminders_enabled'`

- [ ] **Step 3: Add fields + migration**

```python
# src/cfo/models.py — inside class Organization
    collection_reminders_enabled = Column(Boolean, default=False, nullable=False)
    collection_sms_sender = Column(String(20), nullable=True)
```

```python
# alembic/versions/<rev>_add_collection_reminders.py
"""add collection reminders + org opt-in"""
from alembic import op
import sqlalchemy as sa

revision = "c0ffee010203"
down_revision = "5f6a7b8c9d0e"  # a current head; run `alembic merge heads` if needed
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "collection_reminders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("invoice_numbers", sa.String(500), nullable=True),
        sa.Column("reminder_type", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("days_overdue", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(20), server_default="sent"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_collreminder_org_contact", "collection_reminders",
                    ["organization_id", "contact_id"])
    op.add_column("organizations", sa.Column(
        "collection_reminders_enabled", sa.Boolean, server_default=sa.false(), nullable=False))
    op.add_column("organizations", sa.Column("collection_sms_sender", sa.String(20), nullable=True))

def downgrade():
    op.drop_column("organizations", "collection_sms_sender")
    op.drop_column("organizations", "collection_reminders_enabled")
    op.drop_index("ix_collreminder_org_contact", table_name="collection_reminders")
    op.drop_table("collection_reminders")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py -v`
Expected: PASS (SQLite picks up the model via create_all)

- [ ] **Step 5: Commit**

```bash
git add src/cfo/models.py alembic/versions/c0ffee010203_add_collection_reminders.py tests/test_collection_reminders.py
git commit -m "feat(collections): org opt-in fields + migration"
```

---

### Task 3: `CollectionService.plan_reminders`

**Files:**
- Create: `src/cfo/services/collection_service.py`
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Consumes: `Invoice`, `Contact`, `CollectionReminder` models; `ar_service` templates.
- Produces:
  - `@dataclass PlannedReminder(contact_id:int, contact_name:str, email:str|None, phone:str|None, invoice_numbers:list[str], total_amount:float, days_overdue:int, reminder_type:str, message:str)`
  - `CollectionService(db, org_id).plan_reminders(today: date, cooldown_days:int=7) -> list[PlannedReminder]`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, timedelta
from decimal import Decimal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services.collection_service import CollectionService


def _overdue_invoice(db, org_id, days_overdue, total="1000"):
    c = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER,
                email="c@example.com", phone="0501234567")
    db.add(c); db.flush()
    today = date.today()
    db.add(Invoice(organization_id=org_id, contact_id=c.id, invoice_number="INV-9",
                   total=Decimal(total), balance=Decimal(total), status=InvoiceStatus.SENT,
                   issue_date=today - timedelta(days=days_overdue + 30),
                   due_date=today - timedelta(days=days_overdue)))
    db.commit()
    return c.id


def test_plan_reminders_assigns_type_by_days_overdue(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=20)  # → "second"
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        assert len(planned) == 1
        assert planned[0].reminder_type == "second"
        assert planned[0].total_amount == 1000.0
        assert planned[0].phone == "0501234567"
    finally:
        db.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py::test_plan_reminders_assigns_type_by_days_overdue -v`
Expected: FAIL — `ModuleNotFoundError: cfo.services.collection_service`

- [ ] **Step 3: Implement the service**

```python
# src/cfo/services/collection_service.py
"""תכנון תזכורות גבייה מחשבוניות באיחור אמיתיות (ללא שליחה — ראו dispatch)."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import Contact, Invoice, CollectionReminder
from .ar_service import AccountsReceivableService

OVERDUE_STATUSES = ["sent", "partially_paid", "overdue"]


@dataclass
class PlannedReminder:
    contact_id: int
    contact_name: str
    email: Optional[str]
    phone: Optional[str]
    invoice_numbers: List[str]
    total_amount: float
    days_overdue: int
    reminder_type: str
    message: str


def _reminder_type(days_overdue: int) -> str:
    if days_overdue >= 30:
        return "final"
    if days_overdue >= 14:
        return "second"
    return "first"


class CollectionService:
    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id
        self._templates = AccountsReceivableService(db, org_id).reminder_templates

    def plan_reminders(self, today: date, cooldown_days: int = 7) -> List[PlannedReminder]:
        rows = self.db.query(Invoice, Contact).join(
            Contact, Invoice.contact_id == Contact.id
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.due_date.isnot(None),
            Invoice.due_date < today,
            Invoice.status.in_(OVERDUE_STATUSES),
            Invoice.balance > 0,
        ).all()

        # group by contact
        by_contact: dict = {}
        for inv, contact in rows:
            g = by_contact.setdefault(contact.id, {"contact": contact, "invoices": []})
            g["invoices"].append(inv)

        planned: List[PlannedReminder] = []
        for cid, g in by_contact.items():
            contact = g["contact"]
            invoices = g["invoices"]
            oldest_days = max((today - inv.due_date).days for inv in invoices)
            rtype = _reminder_type(oldest_days)
            if self._recently_sent(cid, rtype, today, cooldown_days):
                continue
            total = float(sum(inv.balance or 0 for inv in invoices))
            numbers = [inv.invoice_number or f"#{inv.id}" for inv in invoices]
            message = self._render(rtype, contact.name, numbers, total, oldest_days)
            planned.append(PlannedReminder(
                contact_id=cid, contact_name=contact.name, email=contact.email,
                phone=contact.phone, invoice_numbers=numbers, total_amount=total,
                days_overdue=oldest_days, reminder_type=rtype, message=message,
            ))
        return planned

    def _recently_sent(self, contact_id: int, rtype: str, today: date, cooldown_days: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        return self.db.query(CollectionReminder).filter(
            CollectionReminder.organization_id == self.org_id,
            CollectionReminder.contact_id == contact_id,
            CollectionReminder.reminder_type == rtype,
            CollectionReminder.sent_at >= cutoff,
            CollectionReminder.status == "sent",
        ).first() is not None

    def _render(self, rtype, name, numbers, amount, days_overdue) -> str:
        tmpl = self._templates.get(rtype, self._templates["first"])
        return tmpl.format(
            customer_name=name, invoice_numbers=", ".join(numbers),
            amount=amount, days_overdue=days_overdue,
            due_date="", company_name=self._company_name(),
        )

    def _company_name(self) -> str:
        from ..models import Organization
        org = self.db.query(Organization).get(self.org_id)
        return org.name if org else ""
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py -v`
Expected: PASS

- [ ] **Step 5: Add cooldown + no-contact-info tests**

```python
def test_plan_reminders_respects_cooldown(fresh_org):
    from datetime import datetime, timezone
    from cfo.models import CollectionReminder
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cid = _overdue_invoice(db, org_id, days_overdue=5)  # "first"
        db.add(CollectionReminder(
            organization_id=org_id, contact_id=cid, reminder_type="first",
            channel="sms", status="sent", sent_at=datetime.now(timezone.utc)))
        db.commit()
        assert CollectionService(db, org_id).plan_reminders(date.today()) == []
    finally:
        db.close()
```

- [ ] **Step 6: Run + commit**

Run: `python -m pytest tests/test_collection_reminders.py -v` → PASS

```bash
git add src/cfo/services/collection_service.py tests/test_collection_reminders.py
git commit -m "feat(collections): plan_reminders from overdue invoices with escalation+cooldown"
```

---

### Task 4: `dispatch_reminders` orchestrator (channel injection)

**Files:**
- Modify: `src/cfo/services/collection_service.py`
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Consumes: `PlannedReminder`, `CollectionReminder`.
- Produces: `async dispatch_reminders(db, org_id, planned, sms_sender, email_sender, sms_sender_name=None) -> dict` where `sms_sender(phone:str, message:str) -> Awaitable[bool]` and `email_sender(to:str, subject:str, body:str) -> Awaitable[bool]`. Records one `CollectionReminder` per channel sent. Returns `{"sms_sent":int, "email_sent":int, "failed":int}`.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from cfo.services.collection_service import CollectionService, dispatch_reminders


def test_dispatch_sends_sms_and_records(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=5)
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        sent = []
        async def fake_sms(phone, message): sent.append((phone, message)); return True
        async def fake_email(to, subject, body): return True
        summary = asyncio.run(dispatch_reminders(
            db, org_id, planned, sms_sender=fake_sms, email_sender=fake_email))
        from cfo.models import CollectionReminder
        rows = db.query(CollectionReminder).filter_by(organization_id=org_id).all()
        assert summary["sms_sent"] == 1
        assert sent and sent[0][0] == "0501234567"
        assert any(r.channel == "sms" and r.status == "sent" for r in rows)
    finally:
        db.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py::test_dispatch_sends_sms_and_records -v`
Expected: FAIL — `ImportError: cannot import name 'dispatch_reminders'`

- [ ] **Step 3: Implement dispatch**

```python
# append to src/cfo/services/collection_service.py
async def dispatch_reminders(db, org_id, planned, sms_sender, email_sender,
                             sms_sender_name=None) -> dict:
    from decimal import Decimal
    summary = {"sms_sent": 0, "email_sent": 0, "failed": 0}
    for p in planned:
        for channel, target, send in (
            ("sms", p.phone, sms_sender),
            ("email", p.email, email_sender),
        ):
            if not target:
                continue
            try:
                if channel == "sms":
                    ok = await send(target, p.message)
                else:
                    ok = await send(target, "תזכורת תשלום", p.message)
            except Exception as exc:  # record failure, never crash the batch
                _record(db, org_id, p, channel, "failed", str(exc))
                summary["failed"] += 1
                continue
            if ok:
                _record(db, org_id, p, channel, "sent", None)
                summary["sms_sent" if channel == "sms" else "email_sent"] += 1
            else:
                _record(db, org_id, p, channel, "failed", "sender returned False")
                summary["failed"] += 1
    db.commit()
    return summary


def _record(db, org_id, p, channel, status, error):
    from decimal import Decimal
    db.add(CollectionReminder(
        organization_id=org_id, contact_id=p.contact_id,
        invoice_numbers=", ".join(p.invoice_numbers), reminder_type=p.reminder_type,
        channel=channel, amount=Decimal(str(p.total_amount)), days_overdue=p.days_overdue,
        status=status, error=error, sent_at=datetime.now(timezone.utc),
    ))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py::test_dispatch_sends_sms_and_records -v`
Expected: PASS

- [ ] **Step 5: Add failure-handling test + commit**

```python
def test_dispatch_records_failure_without_crashing(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _overdue_invoice(db, org_id, days_overdue=5)
        planned = CollectionService(db, org_id).plan_reminders(date.today())
        async def boom_sms(phone, message): raise RuntimeError("sumit 403")
        async def fake_email(to, subject, body): return True
        summary = asyncio.run(dispatch_reminders(db, org_id, planned, boom_sms, fake_email))
        assert summary["failed"] >= 1
    finally:
        db.close()
```

Run: `python -m pytest tests/test_collection_reminders.py -v` → PASS

```bash
git add src/cfo/services/collection_service.py tests/test_collection_reminders.py
git commit -m "feat(collections): async dispatch with channel injection + failure recording"
```

---

### Task 5: SMTP email sender + config

**Files:**
- Modify: `src/cfo/config.py` (add SMTP settings)
- Create: `src/cfo/services/email_sender.py`
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Produces: `async send_email_smtp(to:str, subject:str, body:str, settings) -> bool` — returns False (no send) when SMTP not configured; True after a successful send.

- [ ] **Step 1: Write the failing test**

```python
from cfo.services.email_sender import send_email_smtp


def test_email_sender_disabled_when_unconfigured():
    import asyncio
    class S:  # minimal settings stub, no SMTP host
        smtp_host = None
        smtp_port = 587
        smtp_user = None
        smtp_password = None
        smtp_from = None
    assert asyncio.run(send_email_smtp("a@b.com", "s", "body", S())) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py::test_email_sender_disabled_when_unconfigured -v`
Expected: FAIL — `ModuleNotFoundError: cfo.services.email_sender`

- [ ] **Step 3: Implement sender + config**

```python
# src/cfo/config.py — add to the Settings class
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
```

```python
# src/cfo/services/email_sender.py
"""שליחת מייל דרך SMTP. מושבת בשקט (False) כשאין קונפיג — לא ממציא הצלחה."""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


async def send_email_smtp(to: str, subject: str, body: str, settings) -> bool:
    if not (settings.smtp_host and settings.smtp_from):
        logger.warning("SMTP not configured; skipping email to %s", to)
        return False

    def _send() -> bool:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True

    try:
        return await asyncio.to_thread(_send)
    except Exception:
        logger.exception("SMTP send failed for %s", to)
        return False
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py::test_email_sender_disabled_when_unconfigured -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cfo/config.py src/cfo/services/email_sender.py tests/test_collection_reminders.py
git commit -m "feat(collections): SMTP email sender (disabled cleanly when unconfigured)"
```

---

### Task 6: Cron endpoint `/api/cron/collection-reminders`

**Files:**
- Modify: `src/cfo/api/routes/cron.py`
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Consumes: `CollectionService`, `dispatch_reminders`, `send_email_smtp`, SUMIT `send_sms`.
- Produces: `GET /api/cron/collection-reminders` (behind `_verify_cron_secret`) → `{"status":"ok","orgs":int,"summary":{...}}`. Acts only on orgs with `collection_reminders_enabled`.

- [ ] **Step 1: Write the failing test**

```python
def test_cron_collection_requires_secret(client):
    r = client.get("/api/cron/collection-reminders")
    assert r.status_code in (401, 403)


def test_cron_collection_runs_for_enabled_orgs(client, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)
    r = client.get("/api/cron/collection-reminders",
                   headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200
    assert "summary" in r.json()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py -k cron -v`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3a: Add an org-scoped SUMIT builder (no request context)**

The request dependency `get_sumit_integration` (in `src/cfo/api/dependencies.py`)
needs `get_current_org_id` — unavailable in cron. Factor its credential logic
into a plain function reused by cron. Add to `src/cfo/api/dependencies.py`:

```python
def sumit_for_org(db: Session, org_id: int):
    """בונה SumitIntegration לארגון נתון מחוץ ל-request (ל-cron). None אם אין מפתח."""
    from ..integrations.sumit_integration import SumitIntegration
    from ..models import IntegrationConnection
    from ..services.credentials_vault import decrypt_credentials

    conn = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == org_id,
        IntegrationConnection.source == "sumit",
        IntegrationConnection.status == "active",
    ).order_by(IntegrationConnection.id).first()
    creds = decrypt_credentials(conn.credentials_encrypted) if conn else {}

    env_allowed = org_id == 1
    api_key = creds.get("api_key") or (settings.sumit_api_key if env_allowed else None)
    company_id = creds.get("company_id") or (settings.sumit_company_id if env_allowed else None)
    if not api_key:
        return None
    return SumitIntegration(api_key=api_key, company_id=company_id)
```

- [ ] **Step 3b: Implement the cron route**

```python
# src/cfo/api/routes/cron.py — add a new route (mirror existing cron handlers)
from ...services.collection_service import CollectionService, dispatch_reminders
from ...services.email_sender import send_email_smtp
from ..dependencies import sumit_for_org
from ...config import settings
from ...models import Organization
from ...integrations.sumit_models import SMSRequest
from datetime import date

@router.get("/cron/collection-reminders", dependencies=[Depends(_verify_cron_secret)])
async def run_collection_reminders(db: Session = Depends(get_db)):
    orgs = db.query(Organization).filter(
        Organization.collection_reminders_enabled.is_(True)
    ).all()

    totals = {"sms_sent": 0, "email_sent": 0, "failed": 0, "skipped_no_sumit": 0}
    for org in orgs:
        planned = CollectionService(db, org.id).plan_reminders(date.today())
        if not planned:
            continue
        sumit = sumit_for_org(db, org.id)

        async def email_sender(to, subject, body):
            return await send_email_smtp(to, subject, body, settings)

        if sumit is None:
            # אין SUMIT לארגון — מייל בלבד (SMS ידלג כי אין שולח)
            async def sms_sender(phone, message):
                return False
            totals["skipped_no_sumit"] += 1
        else:
            async def sms_sender(phone, message, _s=org.collection_sms_sender, _c=sumit):
                return bool(await _c.send_sms(SMSRequest(
                    phone_number=phone, message=message, sender_name=_s)))

        summary = await dispatch_reminders(
            db, org.id, planned, sms_sender, email_sender,
            sms_sender_name=org.collection_sms_sender)
        for k in ("sms_sent", "email_sent", "failed"):
            totals[k] += summary.get(k, 0)

    return {"status": "ok", "orgs": len(orgs), "summary": totals}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py -k cron -v`
Expected: PASS (no enabled orgs → empty summary, 200)

- [ ] **Step 5: Commit**

```bash
git add src/cfo/api/routes/cron.py tests/test_collection_reminders.py
git commit -m "feat(collections): daily cron endpoint for enabled orgs"
```

---

### Task 7: Manual preview + run routes (RBAC)

**Files:**
- Modify: `src/cfo/api/routes/financial_management.py` (or the AR router)
- Test: `tests/test_collection_reminders.py`

**Interfaces:**
- Produces:
  - `GET /api/financial/collection/due` → `{"due":[{contact_name, total_amount, days_overdue, reminder_type, channels:[...]}]}` (preview; no send).
  - `POST /api/financial/collection/run` → dispatches now for the caller's org; same summary shape as cron.

- [ ] **Step 1: Write the failing test**

```python
def test_collection_due_preview(client, owner):
    # `owner` fixture provides an authenticated org; seed an overdue invoice for it
    # (reuse helper pattern; owner["org_id"], owner["headers"])
    r = client.get("/api/financial/collection/due", headers=owner["headers"])
    assert r.status_code == 200
    assert "due" in r.json()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_collection_reminders.py -k preview -v`
Expected: FAIL — 404

- [ ] **Step 3: Implement routes**

```python
# src/cfo/api/routes/financial_management.py
from datetime import date
from ..dependencies import get_sumit_integration, require_admin
from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import SMSRequest
from ...services.collection_service import CollectionService, dispatch_reminders
from ...services.email_sender import send_email_smtp
from ...config import settings

@router.get("/collection/due")
async def collection_due(db: Session = Depends(get_db),
                         org_id: int = Depends(get_current_org_id)):
    planned = CollectionService(db, org_id).plan_reminders(date.today())
    return {"due": [
        {"contact_name": p.contact_name, "total_amount": p.total_amount,
         "days_overdue": p.days_overdue, "reminder_type": p.reminder_type,
         "channels": [c for c in (("sms" if p.phone else None),
                                  ("email" if p.email else None)) if c]}
        for p in planned
    ]}

@router.post("/collection/run", dependencies=[Depends(require_admin)])
async def collection_run(db: Session = Depends(get_db),
                         org_id: int = Depends(get_current_org_id),
                         sumit: SumitIntegration = Depends(get_sumit_integration)):
    planned = CollectionService(db, org_id).plan_reminders(date.today())
    async def sms_sender(phone, message):
        return bool(await sumit.send_sms(SMSRequest(phone_number=phone, message=message)))
    async def email_sender(to, subject, body):
        return await send_email_smtp(to, subject, body, settings)
    summary = await dispatch_reminders(db, org_id, planned, sms_sender, email_sender)
    return {"status": "ok", "summary": summary}
```

> Note: `get_sumit_integration` raises 400 if the org has no SUMIT key. That is
> acceptable for a manual admin-triggered run. `require_admin` + `get_current_org_id`
> + `get_db` all come from `src/cfo/api/dependencies.py` (verified present).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_collection_reminders.py -k "preview or run" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cfo/api/routes/financial_management.py tests/test_collection_reminders.py
git commit -m "feat(collections): manual preview + run routes"
```

---

### Task 8: Register the cron in Vercel

**Files:**
- Modify: `vercel.json` (or `vercel.ts`)

- [ ] **Step 1: Add the cron entry**

```json
{ "crons": [ { "path": "/api/cron/collection-reminders", "schedule": "0 7 * * *" } ] }
```

Merge into the existing `crons` array (do not drop existing entries: sync, enrich-expenses, process-ocr).

- [ ] **Step 2: Verify full suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add vercel.json
git commit -m "feat(collections): register daily collection-reminders cron"
```

---

## Self-Review notes
- **Coverage:** overdue detection (Task 3), escalation+cooldown (Task 3), SMS send (Task 4), email send (Task 5), automation (Task 6), manual control (Task 7), schedule (Task 8). ✓
- **Integration facts (verified 2026-06-26 against real code):**
  1. SUMIT request client = `get_sumit_integration` dependency → `SumitIntegration` (raises 400 if no key). Cron uses the new `sumit_for_org(db, org_id)` helper (Task 6, Step 3a).
  2. RBAC guard = `require_admin` (in `dependencies.py`); applied to `POST /collection/run`.
  3. `get_current_org_id`, `get_db`, `require_admin`, `get_sumit_integration` all in `src/cfo/api/dependencies.py`.
- **Out of scope (separate plan):** physical-letter escalation (`send_letter_by_click`), small-claims, late-payment interest (Prime+2%) — see roadmap P2.
