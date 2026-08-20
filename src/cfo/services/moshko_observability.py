"""Best-effort, tenant-scoped observability primitives for Moshko.

No provider calls live here.  Logging uses a nested transaction so a missing
table or malformed observation rolls back only the observation, never the
conversation/tool transaction that produced it.
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import LLMUsage, MoshkoToolCall

logger = logging.getLogger(__name__)

_SENSITIVE_KEY = re.compile(
    r"(?:password|passphrase|secret|token|api[_-]?key|authorization|credential|"
    r"cvv|cvc|card[_-]?(?:number|no)|iban|bank[_-]?(?:account|number)|"
    r"account[_-]?number|routing[_-]?number|branch[_-]?number)",
    re.IGNORECASE,
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_BEARER_OR_KEY = re.compile(
    r"(?i)\b(?:bearer|api[_-]?key|access[_-]?token|secret)\s*[:=]?\s*[A-Za-z0-9._~+/=-]{6,}"
)
_REDACTED = "[REDACTED]"


def redact_sensitive_text(value: str) -> str:
    text = _IBAN.sub(_REDACTED, value)
    text = _CARD.sub(_REDACTED, text)
    return _BEARER_OR_KEY.sub(_REDACTED, text)


def redact_tool_arguments(value: Any, *, _key: str | None = None) -> Any:
    """Recursively preserve argument shape while removing sensitive values."""
    if _key and _SENSITIVE_KEY.search(_key):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): redact_tool_arguments(v, _key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_tool_arguments(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _usage_value(usage: Any, name: str, default: int = 0) -> int:
    if usage is None:
        return default
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def usage_tokens(usage: Any, provider: str) -> dict[str, int | None]:
    """Normalize Anthropic and OpenAI usage objects without SDK coupling."""
    if provider == "openai":
        input_tokens = _usage_value(usage, "prompt_tokens")
        output_tokens = _usage_value(usage, "completion_tokens")
        details = usage.get("prompt_tokens_details") if isinstance(usage, dict) else getattr(
            usage, "prompt_tokens_details", None
        )
        cached = _usage_value(details, "cached_tokens") if details is not None else 0
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cached or None,
            "cache_creation_input_tokens": None,
        }
    return {
        "input_tokens": _usage_value(usage, "input_tokens"),
        "output_tokens": _usage_value(usage, "output_tokens"),
        "cache_read_input_tokens": _usage_value(usage, "cache_read_input_tokens") or None,
        "cache_creation_input_tokens": _usage_value(usage, "cache_creation_input_tokens") or None,
    }


def _pricing_for(model: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(settings.llm_pricing_json or "{}")
    except (TypeError, json.JSONDecodeError):
        logger.warning("LLM pricing config is invalid JSON; cost will be NULL")
        return None
    row = parsed.get(model) if isinstance(parsed, dict) else None
    return row if isinstance(row, dict) else None


def calculate_cost_usd(model: str, tokens: dict[str, int | None]) -> Decimal | None:
    pricing = _pricing_for(model)
    if pricing is None:
        return None
    required = ("input_per_million_usd", "output_per_million_usd")
    if any(key not in pricing for key in required):
        return None
    cache_read = int(tokens.get("cache_read_input_tokens") or 0)
    cache_create = int(tokens.get("cache_creation_input_tokens") or 0)
    if cache_read and "cache_read_per_million_usd" not in pricing:
        return None
    if cache_create and "cache_creation_per_million_usd" not in pricing:
        return None
    try:
        total = (
            Decimal(int(tokens.get("input_tokens") or 0)) * Decimal(str(pricing[required[0]]))
            + Decimal(int(tokens.get("output_tokens") or 0)) * Decimal(str(pricing[required[1]]))
            + Decimal(cache_read) * Decimal(str(pricing.get("cache_read_per_million_usd", 0)))
            + Decimal(cache_create) * Decimal(str(pricing.get("cache_creation_per_million_usd", 0)))
        ) / Decimal(1_000_000)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return total.quantize(Decimal("0.00000001"))


def record_llm_usage_best_effort(
    db: Session,
    *,
    organization_id: int | None,
    user_id: int | None,
    session_id: str | None,
    provider: str,
    model: str,
    usage: Any,
    purpose: str,
) -> LLMUsage | None:
    try:
        tokens = usage_tokens(usage, provider)
        with db.begin_nested():
            row = LLMUsage(
                organization_id=organization_id,
                user_id=user_id,
                session_id=session_id,
                provider=provider,
                model=model,
                purpose=purpose,
                cost_usd=calculate_cost_usd(model, tokens),
                **tokens,
            )
            db.add(row)
            db.flush()
        return row
    except Exception:  # logging must never become a product outage
        logger.exception("Failed to record LLM usage (best effort)")
        return None


def result_size_bytes(result: Any) -> int | None:
    try:
        return len(json.dumps(result, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return None


def record_tool_call_best_effort(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    session_id: str,
    message_id: int | None,
    tool_name: str,
    target_system: str,
    arguments: dict[str, Any],
    succeeded: bool,
    error: str | None,
    duration_ms: int,
    result: Any = None,
) -> MoshkoToolCall | None:
    try:
        with db.begin_nested():
            row = MoshkoToolCall(
                organization_id=organization_id,
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                tool_name=tool_name,
                target_system=target_system,
                arguments=redact_tool_arguments(arguments),
                succeeded=succeeded,
                error=redact_sensitive_text(error) if error else None,
                duration_ms=max(int(duration_ms), 0),
                result_size_bytes=result_size_bytes(result) if succeeded else None,
            )
            db.add(row)
            db.flush()
        return row
    except Exception:
        logger.exception("Failed to record Moshko tool call (best effort)")
        return None


def record_gap_best_effort(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    session_id: str,
    message_id: int | None,
    gap_kind: str,
    question: str | None = None,
    answer: str | None = None,
    tool_name: str | None = None,
    error: str | None = None,
):
    """W1.1 — רישום שורת פער בתור הניתוח. best-effort: כישלון תיעוד לעולם
    לא מפיל את השיחה, בדיוק כמו רישום קריאות הכלים."""
    from ..models import MoshkoGap

    try:
        if question is None and message_id is not None:
            from ..models import ChatMessage

            src = db.query(ChatMessage).filter(
                ChatMessage.id == message_id,
                ChatMessage.organization_id == organization_id,
            ).first()
            if src is not None:
                question = src.content
        with db.begin_nested():
            row = MoshkoGap(
                organization_id=organization_id,
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                question=redact_sensitive_text(question) if question else None,
                answer=redact_sensitive_text(answer) if answer else None,
                gap_kind=gap_kind,
                tool_name=tool_name,
                error=redact_sensitive_text(error) if error else None,
            )
            db.add(row)
            db.flush()
        return row
    except Exception:
        logger.exception("Failed to record Moshko gap (best effort)")
        return None
