"""
Automatic OCR scheduling — runs pending expense OCR on a schedule or trigger.

Integrates with the cron system to automatically process SUMIT draft expenses
on a schedule, updating the pipeline without manual API calls.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Expense
from .expense_ocr_pipeline import ExpenseOCRPipeline

logger = logging.getLogger(__name__)


class ExpenseOCRScheduler:
    """Manages scheduled OCR runs for organizations."""

    def __init__(self, db: Session):
        self.db = db

    async def run_scheduled_ocr(
        self,
        organization_id: int,
        limit: int = 50,
        auto_file: bool = True,
        min_confidence: float = 0.7,
        since: Optional[date] = None,
    ) -> dict[str, Any]:
        """Run OCR on pending expenses for a single organization.

        Args:
            organization_id: Target org
            limit: Max expenses to process
            auto_file: Automatically file high-confidence results
            min_confidence: Minimum confidence to auto-file (default 0.7)
            since: Only process expenses from this date onward (6-month rule)

        Returns:
            Summary of run: {scanned, processed, filed, flagged, errors}
        """
        if since is None:
            # Default: 6-month lookback (expense filing rule)
            since = date.today() - timedelta(days=180)

        pipeline = ExpenseOCRPipeline(
            self.db,
            organization_id=organization_id,
            min_confidence=min_confidence,
        )

        result = await pipeline.process_pending(
            limit=limit,
            auto_file=auto_file,
            since=since,
        )

        logger.info(
            "Scheduled OCR for org %s: scanned=%s, filed=%s, flagged=%s, errors=%s",
            organization_id,
            result.get("scanned", 0),
            result.get("filed", 0),
            result.get("flagged", 0),
            result.get("errors", 0),
        )

        return result

    async def run_all_organizations(
        self,
        limit: int = 50,
        auto_file: bool = True,
    ) -> dict[str, Any]:
        """Run OCR for all organizations with active SUMIT connections.

        Returns:
            {orgs_processed, total_scanned, total_filed, total_flagged, total_errors, results}
        """
        from ..models import IntegrationConnection

        # Find orgs with active SUMIT
        targets = {
            conn.organization_id
            for conn in self.db.query(IntegrationConnection).filter(
                IntegrationConnection.status == "active",
                IntegrationConnection.source == "sumit",
            ).all()
        }

        results = []
        totals = {"scanned": 0, "filed": 0, "flagged": 0, "errors": 0}

        for org_id in sorted(targets):
            try:
                org_result = await self.run_scheduled_ocr(
                    org_id,
                    limit=limit,
                    auto_file=auto_file,
                )
                org_result["organization_id"] = org_id
                results.append(org_result)
                for key in ("scanned", "filed", "flagged", "errors"):
                    totals[key] += org_result.get(key, 0)
            except Exception as exc:
                logger.error("Scheduled OCR failed for org %s: %s", org_id, exc)
                results.append({"organization_id": org_id, "error": str(exc)})

        return {
            "orgs_processed": len(targets),
            "total_scanned": totals["scanned"],
            "total_filed": totals["filed"],
            "total_flagged": totals["flagged"],
            "total_errors": totals["errors"],
            "results": results,
        }
