"""Documents settled by an owner's bank-match decision.

A 1:1 match without a fee writes the document on the bank row
(``matched_entity_type='invoice'|'bill'|'expense'``) and readers see it
there. A 1:N match, one with a fee, or a category approval writes
``matched_entity_type='bank_match'`` with the decision id, and its
documents live in ``bank_match_documents``. This module is the one place
readers learn about those documents.

A line counts only while its bank row is reconciled, not superseded, and
still holds ``('bank_match', decision.id)``, the same rule the match
screen uses. Each document settles its own line amount, never the whole
bank row: one card charge for five bills covers each bill by its own total.

Before migration m50b2c3d4e5f the tables do not exist. No bank row can
hold ``'bank_match'`` then, so nothing is read from them and readers keep
their 1:1 matches.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

MULTI_MATCH = "bank_match"
DOCUMENT_TYPES = ("invoice", "bill", "expense")
TABLES = ("bank_match_decisions", "bank_match_documents")


@dataclass(frozen=True)
class Settlement:
    entity_type: str
    entity_id: int
    amount: float  # the document's signed effect on the bank: invoice +, credit note −, bill −, supplier credit +
    bank_transaction_id: int
    bank_date: Optional[date]
    bank_external_id: Optional[str]


def match_tables_ready(db) -> bool:
    """Whether migration m50b2c3d4e5f is applied. Reads the catalog only, so a False never aborts the transaction."""
    from sqlalchemy import inspect
    inspector = inspect(db.get_bind())
    return all(inspector.has_table(name) for name in TABLES)


def is_bank_match(txn) -> bool:
    """The bank row is explained by an owner's decision: documents or a category."""
    return bool(getattr(txn, "is_reconciled", False)) and getattr(txn, "matched_entity_type", None) == MULTI_MATCH


def bank_match_settlements(db, organization_id: int, entity_types: Iterable[str] = DOCUMENT_TYPES,
                           entity_ids: Optional[Iterable[int]] = None) -> list[Settlement]:
    """Every document a live bank-match decision settles in the organization. No provider call."""
    from ..models import BankMatchDecision, BankMatchDocument, BankTransaction

    entity_types = tuple(entity_types)
    if entity_ids is not None:
        entity_ids = list(entity_ids)
        if not entity_ids:
            return []
    live = (
        BankTransaction.organization_id == organization_id,
        BankTransaction.is_reconciled.is_(True),
        BankTransaction.matched_entity_type == MULTI_MATCH,
        BankTransaction.matched_entity_id.isnot(None),
        BankTransaction.superseded_by_id.is_(None),
    )
    if db.query(BankTransaction.id).filter(*live).first() is None or not match_tables_ready(db):
        return []
    query = (
        db.query(BankMatchDocument, BankTransaction)
        .join(BankTransaction, BankTransaction.id == BankMatchDocument.bank_transaction_id)
        .join(BankMatchDecision, BankMatchDecision.id == BankMatchDocument.decision_id)
        .filter(
            *live,
            BankTransaction.matched_entity_id == BankMatchDocument.decision_id,
            BankMatchDocument.organization_id == organization_id,
            BankMatchDecision.organization_id == organization_id,
            BankMatchDecision.status == "approved",
            BankMatchDocument.entity_type.in_(entity_types),
        )
    )
    if entity_ids is not None:
        query = query.filter(BankMatchDocument.entity_id.in_(entity_ids))
    return [
        Settlement(line.entity_type, line.entity_id, float(line.amount), bank.id,
                   bank.transaction_date, bank.external_id)
        for line, bank in query.order_by(BankMatchDocument.id)
    ]


def settled_document_keys(db, organization_id: int) -> set[tuple[str, int]]:
    """(entity_type, entity_id) of every document a live decision settles. Suggesters skip these."""
    return {(line.entity_type, line.entity_id) for line in bank_match_settlements(db, organization_id)}


def assert_not_decided(txn) -> None:
    """The older match paths may not clear or overwrite a decision. The match screen reopens it."""
    if is_bank_match(txn):
        raise ValueError("התנועה הוכרעה במסך התאמת בנק. שינוי או ביטול נעשים שם (פתיחה מחדש)")


def assert_document_free(db, organization_id: int, entity_type: str, entity_id: int) -> None:
    """A document a live decision settles cannot explain a second bank row."""
    if entity_type in DOCUMENT_TYPES and bank_match_settlements(db, organization_id, (entity_type,), [entity_id]):
        raise ValueError(f"המסמך {entity_type} #{entity_id} כבר מותאם לתנועת בנק במסך התאמת בנק")
