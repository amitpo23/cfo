"""
מצב מאזני נוכחי — מקור אמת יחיד
Single source of truth for the current balance position, derived from the
sub-ledgers the business actually maintains: account balances (cash),
open invoices (AR), open bills (AP), and inventory valuation.

Used by both KPIService and BankReportService so the two screens agree.
"""
from typing import Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Account, Invoice, Bill, InventoryItem


def compute_balance_snapshot(db: Session, organization_id: int) -> Dict:
    cash = float(
        db.query(func.coalesce(func.sum(Account.balance), 0))
        .filter(Account.organization_id == organization_id)
        .scalar() or 0
    )
    receivables = float(
        db.query(func.coalesce(func.sum(Invoice.balance), 0))
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.balance > 0,
        ).scalar() or 0
    )
    payables = float(
        db.query(func.coalesce(func.sum(Bill.balance), 0))
        .filter(
            Bill.organization_id == organization_id,
            Bill.balance > 0,
        ).scalar() or 0
    )
    inventory = float(
        db.query(
            func.coalesce(func.sum(InventoryItem.quantity * InventoryItem.unit_cost), 0)
        ).filter(
            InventoryItem.organization_id == organization_id,
            InventoryItem.is_active == True,  # noqa: E712
        ).scalar() or 0
    )
    current_assets = cash + receivables + inventory
    current_liabilities = payables
    return {
        "cash": cash,
        "receivables": receivables,
        "payables": payables,
        "inventory": inventory,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "total_assets": current_assets,  # אין רישום נכסים קבועים נפרד
        "total_liabilities": current_liabilities,
        "equity": current_assets - current_liabilities,
        "total_debt": current_liabilities,
        "current_ratio": (current_assets / current_liabilities) if current_liabilities else 0,
    }
