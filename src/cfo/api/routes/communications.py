"""
Communications API routes
Handles SMS, email, fax, and customer service
"""
from fastapi import APIRouter, Depends, Query
from typing import List, Optional

from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    SMSRequest, SMSResponse, EmailListRequest, FaxRequest,
    TicketRequest, TicketResponse
)
from ..dependencies import get_current_user, get_sumit_integration

router = APIRouter()


# ==================== SMS ====================

@router.post("/sms/send", response_model=SMSResponse)
async def send_sms(
    sms: SMSRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Send single SMS"""
    async with sumit:
        return await sumit.send_sms(sms)


@router.post("/sms/send-multiple", response_model=List[SMSResponse])
async def send_multiple_sms(
    messages: List[SMSRequest],
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Send multiple SMS messages"""
    async with sumit:
        return await sumit.send_multiple_sms(messages)


@router.get("/sms/senders")
async def list_sms_senders(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List available SMS sender names"""
    async with sumit:
        senders = await sumit.list_sms_senders()
        return {"senders": senders}


@router.get("/sms/mailing-lists")
async def list_sms_mailing_lists(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List SMS mailing lists"""
    async with sumit:
        return await sumit.list_sms_mailing_lists()


@router.post("/sms/mailing-lists/add")
async def add_to_sms_mailing_list(
    list_id: str = Query(...),
    phone_number: str = Query(...),
    name: Optional[str] = Query(None),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Add contact to SMS mailing list"""
    async with sumit:
        return await sumit.add_to_sms_mailing_list(list_id, phone_number, name)


# ==================== Email ====================

@router.get("/email/mailing-lists")
async def list_mailing_lists(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List all mailing lists"""
    async with sumit:
        return await sumit.list_mailing_lists()


@router.post("/email/mailing-lists/add")
async def add_to_mailing_list(
    request: EmailListRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Add contact to mailing list"""
    async with sumit:
        return await sumit.add_to_mailing_list(request)


# ==================== Fax ====================

@router.post("/fax/send")
async def send_fax(
    fax: FaxRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Send fax"""
    async with sumit:
        return await sumit.send_fax(fax)


# ==================== Mail ====================

@router.post("/mail/send-letter")
async def send_letter(
    recipient: dict = Query(...),
    content: str = Query(...),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Send letter via mail service"""
    async with sumit:
        return await sumit.send_letter_by_click(recipient, content)


@router.get("/mail/letters/{letter_id}/tracking")
async def get_letter_tracking(
    letter_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get letter tracking code"""
    async with sumit:
        tracking_code = await sumit.get_letter_tracking_code(letter_id)
        return {"letter_id": letter_id, "tracking_code": tracking_code}


# ==================== Customer Service ====================

@router.post("/tickets", response_model=TicketResponse)
async def create_ticket(
    ticket: TicketRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Create customer service ticket"""
    async with sumit:
        return await sumit.create_ticket(ticket)
