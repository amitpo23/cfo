"""Shared execution boundary for legacy provider endpoints.

The operation name is part of the immutable intent, so an approval for one
endpoint cannot authorize another endpoint with an otherwise identical body.
Provider acknowledgement is deliberately not called independent verification.
"""
from typing import Awaitable, Callable, Any

from fastapi import HTTPException, Response
from pydantic import BaseModel

from ..services.irreversible_action_service import (
    IrreversibleActionService, ActionAuthorizationError, ActionValidationError,
    ActionConflictError, ActionStateError,
)


async def execute_approved_action(
    *, db, org_id: int, approval_id: int | None, response: Response,
    action_type: str, payload: dict, execute: Callable[[dict], Awaitable[Any]],
    reference: Callable[[Any], str | None],
):
    if approval_id is None:
        raise HTTPException(409, 'An approved X-Rezef-Approval-Id is required')
    service = IrreversibleActionService(db, org_id)
    try:
        action = service.claim_approved_for_execution(
            approval_id, action_type=action_type, submitted_payload=payload,
        )
    except ActionAuthorizationError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ActionConflictError, ActionStateError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ActionValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        result = await execute(action.payload)
        provider_reference = reference(result)
        if not provider_reference:
            raise ValueError('Provider acknowledgement omitted a reference')
        evidence = result.model_dump(mode='json') if isinstance(result, BaseModel) else result
        service.mark_executed(approval_id, provider_reference=provider_reference,
                              execution_result={'provider_response': evidence,
                                                'verification_required': True})
    except Exception as exc:
        db.rollback()  # Keep uncommitted business rows out of the failure record.
        service.mark_failed(approval_id, error=f'Provider outcome unknown: {type(exc).__name__}')
        raise HTTPException(502, 'Provider outcome is unverified; do not retry automatically') from exc
    response.headers['X-Rezef-Approval-Id'] = str(approval_id)
    response.headers['X-Rezef-Approval-Status'] = 'executed_unverified'
    return result


def require_durable_adapter():
    """Fail closed for a legacy route with no reviewed execution adapter."""
    raise HTTPException(409, 'This legacy action requires an approval-aware execution adapter; use the reviewed approval workflow')


def approved_provider_action(action_type: str, operation: str, *, target_key: str | None = None,
                             allow_local_draft: bool = False):
    """Adapt a typed legacy endpoint to the durable approval boundary.

    The intent includes every validated path/query/body argument. Dependency
    objects never enter storage. Execution reconstructs arguments from the
    persisted intent. Targets can identify cancellation acknowledgements;
    they never substitute for independent readback evidence.
    """
    import inspect
    from functools import wraps
    from typing import get_type_hints
    from fastapi import Depends, Header
    from fastapi.params import Depends as DependsParam
    from fastapi.encoders import jsonable_encoder
    from .dependencies import get_access_context, require_admin
    from ..database import get_db_session

    def decorate(endpoint):
        signature = inspect.signature(endpoint)
        hints = get_type_hints(endpoint)
        parameters = [p.replace(annotation=hints.get(p.name, p.annotation)) for p in signature.parameters.values()]
        inputs = [p.name for p in parameters if not isinstance(p.default, DependsParam)]

        @wraps(endpoint)
        async def wrapped(**kwargs):
            kwargs.pop('_approval_executor')
            fallback_db = kwargs.pop('_approval_db')
            db = kwargs.get('db', fallback_db)
            ctx = kwargs.pop('_approval_context')
            approval_id = kwargs.pop('_approval_header')
            response = kwargs.pop('_approval_response')
            arguments = {name: jsonable_encoder(kwargs[name]) for name in inputs if name in kwargs}
            if allow_local_draft and any(isinstance(value, dict) and value.get('send_to_sumit') is False for value in arguments.values()):
                return await endpoint(**kwargs)
            if approval_id is None:
                raise HTTPException(409, 'An approved X-Rezef-Approval-Id is required')
            payload = {'operation': operation, 'arguments': arguments}
            for value in arguments.values():
                if isinstance(value, dict) and 'amount' in value:
                    payload['amount'] = value['amount']
            def has_card(value):
                if isinstance(value, dict):
                    return any((key in {'card', 'card_details', 'card_number', 'cvv', 'cvv2'} and item)
                               or has_card(item) for key, item in value.items())
                return isinstance(value, list) and any(has_card(item) for item in value)
            if has_card(arguments):
                raise HTTPException(400, 'Use a stored payment method; raw card data cannot enter an approval')

            async def execute(persisted):
                from pydantic import TypeAdapter
                restored = dict(kwargs)
                for name, value in persisted['arguments'].items():
                    restored[name] = TypeAdapter(hints[name]).validate_python(value) if name in hints else value
                return await endpoint(**restored)

            def reference(result):
                data = jsonable_encoder(result)
                if target_key:
                    return str(arguments[target_key])
                if isinstance(data, dict):
                    data = data.get('data') or data
                    if isinstance(data, dict):
                        for key in ('provider_reference', 'document_id', 'payment_id', 'transaction_id', 'resource_id', 'sk', 'id'):
                            if data.get(key):
                                return str(data[key])
                return None

            return await execute_approved_action(
                db=db, org_id=ctx.organization_id, approval_id=approval_id, response=response,
                action_type=action_type, payload=payload, execute=execute, reference=reference)

        parameters.extend([
            inspect.Parameter('_approval_executor', inspect.Parameter.KEYWORD_ONLY, default=Depends(require_admin)),
            inspect.Parameter('_approval_response', inspect.Parameter.KEYWORD_ONLY, annotation=Response),
            inspect.Parameter('_approval_header', inspect.Parameter.KEYWORD_ONLY, annotation=int | None,
                              default=Header(None, alias='X-Rezef-Approval-Id')),
            inspect.Parameter('_approval_context', inspect.Parameter.KEYWORD_ONLY, default=Depends(get_access_context)),
            inspect.Parameter('_approval_db', inspect.Parameter.KEYWORD_ONLY, default=Depends(get_db_session)),
        ])
        wrapped.__signature__ = signature.replace(parameters=parameters, return_annotation=hints.get('return', signature.return_annotation))
        return wrapped
    return decorate
