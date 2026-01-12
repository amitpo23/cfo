"""
Payments API routes
Handles payments, recurring payments, credit card transactions, and billing
"""
from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from datetime import date
from decimal import Decimal

from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    ChargeRequest, PaymentResponse, PaymentMethodResponse,
    TransactionRequest, TransactionResponse,
    RecurringPaymentRequest, RecurringPaymentResponse,
    BillingTransactionRequest, BillingTransaction,
    TokenizeCardRequest, TokenResponse
)
from ..dependencies import get_current_user, get_sumit_integration

router = APIRouter()


# ==================== Standard Payments ====================

@router.post("/charge", response_model=PaymentResponse)
async def charge_customer(
    charge: ChargeRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Charge customer"""
    async with sumit:
        return await sumit.charge_customer(charge)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get payment details"""
    async with sumit:
        return await sumit.get_payment(payment_id)


@router.get("/", response_model=List[PaymentResponse])
async def list_payments(
    customer_id: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List payments with filters"""
    async with sumit:
        return await sumit.list_payments(
            customer_id=customer_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset
        )


# ==================== Payment Methods ====================

@router.get("/methods/{customer_id}", response_model=List[PaymentMethodResponse])
async def get_payment_methods(
    customer_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get customer payment methods"""
    async with sumit:
        return await sumit.get_payment_methods(customer_id)


@router.post("/methods/set")
async def set_payment_method(
    customer_id: str = Query(...),
    payment_method_id: str = Query(...),
    is_default: bool = Query(False),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Set customer payment method"""
    async with sumit:
        return await sumit.set_payment_methods(customer_id, payment_method_id, is_default)


@router.post("/methods/remove")
async def remove_payment_method(
    customer_id: str = Query(...),
    payment_method_id: str = Query(...),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Remove customer payment method"""
    async with sumit:
        return await sumit.remove_payment_method(customer_id, payment_method_id)


# ==================== Redirect Flow ====================

@router.post("/redirect/begin")
async def begin_payment_redirect(
    amount: Decimal = Query(...),
    description: str = Query(...),
    return_url: str = Query(...),
    customer_id: Optional[str] = Query(None),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Begin payment redirect flow"""
    async with sumit:
        redirect_url = await sumit.begin_payment_redirect(
            amount=amount,
            description=description,
            return_url=return_url,
            customer_id=customer_id
        )
        return {"redirect_url": redirect_url}


# ==================== Recurring Payments ====================

@router.get("/recurring/customer/{customer_id}", response_model=List[RecurringPaymentResponse])
async def list_customer_recurring(
    customer_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List customer recurring payments"""
    async with sumit:
        return await sumit.list_customer_recurring(customer_id)


@router.post("/recurring/{recurring_id}/cancel")
async def cancel_recurring(
    recurring_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Cancel recurring payment"""
    async with sumit:
        return await sumit.cancel_recurring(recurring_id)


@router.post("/recurring/{recurring_id}/charge", response_model=PaymentResponse)
async def charge_recurring(
    recurring_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Manually charge recurring payment"""
    async with sumit:
        return await sumit.charge_recurring(recurring_id)


@router.put("/recurring/{recurring_id}", response_model=RecurringPaymentResponse)
async def update_recurring(
    recurring_id: str,
    updates: RecurringPaymentRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Update recurring payment details"""
    async with sumit:
        return await sumit.update_recurring(recurring_id, updates)


# ==================== Credit Card Terminal - Transactions ====================

@router.post("/terminal/transaction", response_model=TransactionResponse)
async def create_card_transaction(
    transaction: TransactionRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Create credit card transaction"""
    async with sumit:
        return await sumit.create_card_transaction(transaction)


@router.get("/terminal/transaction/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get transaction details"""
    async with sumit:
        return await sumit.get_transaction(transaction_id)


@router.post("/terminal/redirect")
async def begin_transaction_redirect(
    transaction_id: str = Query(...),
    return_url: str = Query(...),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Begin redirect flow for transaction"""
    async with sumit:
        redirect_url = await sumit.begin_redirect(transaction_id, return_url)
        return {"redirect_url": redirect_url}


# ==================== Credit Card Terminal - Billing ====================

@router.post("/terminal/billing/load", response_model=List[BillingTransaction])
async def load_billing_transactions(
    request: BillingTransactionRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Load billing transactions from credit card terminal"""
    async with sumit:
        return await sumit.load_billing_transactions(request)


@router.post("/terminal/billing/process")
async def process_billing_transactions(
    transaction_ids: List[str],
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Process billing transactions"""
    async with sumit:
        return await sumit.process_billing_transactions(transaction_ids)


@router.get("/terminal/billing/{transaction_id}/status")
async def get_billing_status(
    transaction_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get billing transaction status"""
    async with sumit:
        return await sumit.get_billing_status(transaction_id)


# ==================== Credit Card Vault ====================

@router.post("/vault/tokenize", response_model=TokenResponse)
async def tokenize_card(
    request: TokenizeCardRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Tokenize credit card for future use"""
    async with sumit:
        return await sumit.tokenize_card(request)


@router.post("/vault/tokenize-single-use", response_model=TokenResponse)
async def tokenize_single_use(
    request: TokenizeCardRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Tokenize card for single use"""
    async with sumit:
        return await sumit.tokenize_single_use(request)


# ==================== Upay ====================

@router.post("/upay/open-terminal")
async def open_upay_terminal(
    amount: Decimal = Query(...),
    description: str = Query(...),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Open Upay terminal for payment"""
    async with sumit:
        return await sumit.open_upay_terminal(amount, description)
