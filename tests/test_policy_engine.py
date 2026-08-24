"""Classification contract for Rezef policy-catalog actions."""
from cfo.models import UserRole
from cfo.services import policy_engine


def test_every_policy_action_has_one_documented_classification():
    classified = (
        policy_engine.READ_ACTIONS
        | policy_engine.WRITE_ACTIONS
        | policy_engine.IRREVERSIBLE_ACTIONS
        | policy_engine.SIGNING_ACTIONS
    )

    assert classified == policy_engine.KNOWN_ACTIONS
    assert set(policy_engine.ACTION_CLASSIFICATION_RATIONALE) == classified
    assert sum(map(len, (
        policy_engine.READ_ACTIONS,
        policy_engine.WRITE_ACTIONS,
        policy_engine.IRREVERSIBLE_ACTIONS,
        policy_engine.SIGNING_ACTIONS,
    ))) == len(classified)


def test_money_documents_and_books_are_irreversible():
    assert policy_engine.IRREVERSIBLE_ACTIONS == frozenset({
        "invoices.issue",
        "invoices.credit",
        "expenses.file",
        "recurring.create",
        "recurring.update",
        "recurring_cancel.propose",
        "documents.cancel",
        "billing.charge",
        "accounting.writeback.propose",
    })


def test_irreversible_role_preset_only_allows_proposal_not_self_approval():
    decision = policy_engine.evaluate(
        grants=[],
        organization_id=7,
        user_id=11,
        role=UserRole.ADMIN,
        action="billing.charge",
    )

    assert decision.allowed is True
    assert decision.requires_signing_authority is True
    assert decision.separation_of_duties is True


def test_regular_write_keeps_existing_single_confirm_flow():
    decision = policy_engine.evaluate(
        grants=[],
        organization_id=7,
        user_id=11,
        role=UserRole.ADMIN,
        action="expenses.manage_categories",
    )

    assert decision.allowed is True
    assert decision.requires_signing_authority is False
    assert decision.separation_of_duties is False
