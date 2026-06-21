"""
Deterministic calculators API — fields in, a number out. No language model, no auth,
no org data. Pure formulas (see services/calculators.py).
"""
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from ...services import calculators

router = APIRouter()


@router.get("/calculators")
async def list_calculators():
    """Catalog of available calculators with their input fields (for rendering cards)."""
    return {"calculators": calculators.list_calculators()}


@router.post("/calculators/{calculator_id}")
async def run_calculator(calculator_id: str, inputs: dict[str, Any] = Body(default={})):
    """Run a calculator deterministically. Returns {result, unit, breakdown, note}."""
    try:
        return calculators.run(calculator_id, inputs or {})
    except KeyError:
        raise HTTPException(404, f"Unknown calculator: {calculator_id}")
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid inputs: {e}")
