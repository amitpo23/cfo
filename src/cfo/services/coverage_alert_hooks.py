"""Recompute the coverage alert when a reviewed local import is written or removed.

Cash-flow reads stay read-only. A new local row, an ORM delete, or a bulk
delete of ``reviewed_local_import`` transactions refreshes the alert in the
same transaction. ``refresh_coverage_alert`` flushes, so a depth flag stops
that flush from re-entering these hooks.
"""
from __future__ import annotations

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ..models import BankTransaction

# Same value as bank_coverage.LOCAL_SOURCE. Imported lazily below so this
# module can be installed from bank_coverage without a cycle.
LOCAL_IMPORT_SOURCE = "reviewed_local_import"

_INSTALLED = False


def _local_import_orgs(objects) -> set[int]:
    orgs = set()
    for obj in objects:
        if isinstance(obj, BankTransaction) and obj.source == LOCAL_IMPORT_SOURCE and obj.organization_id:
            orgs.add(int(obj.organization_id))
    return orgs


def _before_commit(session) -> None:
    """Refresh after the local rows are written and before the commit finishes.

    ``before_commit`` runs before the commit's own flush. Flushing here writes
    the import first; the alert update then happens outside ``after_flush``,
    so SQLAlchemy does not discard it.
    """
    if session.info.get("coverage_alert_depth"):
        return
    orgs = _local_import_orgs(list(session.new) + list(session.deleted))
    if not orgs:
        return
    session.info["coverage_alert_depth"] = True
    try:
        session.flush()
        for org_id in orgs:
            from .bank_coverage import refresh_coverage_alert
            refresh_coverage_alert(session, org_id)
    finally:
        session.info["coverage_alert_depth"] = False


def _is_bank_transaction_delete(state) -> bool:
    if not state.is_delete or getattr(state.session, "_flushing", False):
        return False
    mapper = state.bind_mapper
    if mapper is not None and getattr(mapper, "class_", None) is BankTransaction:
        return True
    table = getattr(state.statement, "table", None)
    return getattr(table, "name", None) == BankTransaction.__tablename__


def _orgs_in_delete(session, statement) -> set[int]:
    where = getattr(statement, "whereclause", None)
    query = select(BankTransaction.organization_id).where(
        BankTransaction.source == LOCAL_IMPORT_SOURCE
    ).distinct()
    if where is not None:
        query = query.where(where)
    return {int(org_id) for org_id in session.scalars(query).all() if org_id is not None}


def _capture_bulk_delete(state):
    if state.session.info.get("coverage_alert_depth") or not _is_bank_transaction_delete(state):
        return None
    try:
        orgs = _orgs_in_delete(state.session, state.statement)
    except Exception:
        return None
    if orgs:
        state.session.info.setdefault("coverage_alert_bulk_orgs", set()).update(orgs)
    return None


def _after_bulk_delete(context) -> None:
    session = context.query.session
    orgs = session.info.pop("coverage_alert_bulk_orgs", None)
    if not orgs or session.info.get("coverage_alert_depth"):
        return
    _refresh_orgs(session, orgs)


def _refresh_orgs(session, orgs: set[int]) -> None:
    from .bank_coverage import refresh_coverage_alert

    session.info["coverage_alert_depth"] = True
    try:
        for org_id in orgs:
            refresh_coverage_alert(session, org_id)
    finally:
        session.info["coverage_alert_depth"] = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    event.listen(Session, "before_commit", _before_commit)
    event.listen(Session, "do_orm_execute", _capture_bulk_delete)
    event.listen(Session, "after_bulk_delete", _after_bulk_delete)
