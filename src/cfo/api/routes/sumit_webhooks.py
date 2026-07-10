"""
SUMIT webhook receiver + subscription management (M1b — bidirectional webhooks).

POST /sumit/webhooks is the push endpoint SUMIT's triggers/triggers/subscribe
API calls when a document is created/updated. It's protected by a shared
secret (X-Webhook-Secret header), not user auth — mirrors the Open Finance
webhook receiver in api/routes/open_finance.py.

POST /sumit/webhooks/subscribe is a normal authenticated, org-scoped admin
route that registers the deployed webhook URL with SUMIT via
SumitIntegration.subscribe_trigger.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ...config import settings
from ...database import get_db_session
from ..dependencies import get_current_org_id, sumit_for_org
from ...services.webhook_delta_sync import handle_sumit_trigger_event

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks")
async def sumit_webhook(
    request: Request,
    x_webhook_secret: str = Header(None),
    db: Session = Depends(get_db_session),
):
    """Receive SUMIT trigger events (document created/updated) and run a
    targeted delta sync. No signature scheme beyond the shared secret."""
    if settings.sumit_webhook_secret and not secrets.compare_digest(
        x_webhook_secret or "", settings.sumit_webhook_secret,
    ):
        raise HTTPException(401, "invalid webhook credentials")

    try:
        event = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid JSON")

    result = await handle_sumit_trigger_event(db, event)
    logger.info("SUMIT webhook received: keys=%s", list(event.keys()) if isinstance(event, dict) else type(event))
    return {"received": True, "delta_sync": result}


@router.post("/webhooks/subscribe")
async def sumit_webhook_subscribe(
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Register the deployed webhook URL with SUMIT's triggers API for this
    org's SUMIT integration. Body: {"target_url": "...", "trigger_type": "..."}
    (trigger_type defaults to CreateOrUpdate — document create or update)."""
    target_url = body.get("target_url")
    if not target_url:
        raise HTTPException(422, "target_url is required")
    trigger_type = body.get("trigger_type", "CreateOrUpdate")

    sumit = sumit_for_org(db, org_id)
    if sumit is None:
        raise HTTPException(400, "SUMIT API key not configured for this organization")

    async with sumit:
        result = await sumit.subscribe_trigger(trigger_type=trigger_type, webhook_url=target_url)
    return {"subscribed": True, "target_url": target_url, "trigger_type": trigger_type, "result": result}
