"""Per-organization SUMIT credentials.

Environment ``SUMIT_API_KEY`` is used only for organizations listed in
``SUMIT_ENV_CREDENTIAL_ORG_IDS``. An organization with its own
``IntegrationConnection`` (or ``organizations.api_credentials``) is served
from that row alone. Another organization's key is never substituted.
"""
from __future__ import annotations

MISSING_HE = "אין אישורי SUMIT לארגון הזה. לא נעשה שימוש באישורים של ארגון אחר."
_BLOCKED = {"inactive", "revoked", "disabled"}


def resolve_sumit_credentials(db, organization_id: int) -> dict | None:
    """``{"api_key", "company_id"}`` for this org, or None."""
    from ..config import settings
    from ..models import IntegrationConnection, Organization
    from .credentials_vault import decrypt_credentials

    conn = (
        db.query(IntegrationConnection)
        .filter(
            IntegrationConnection.organization_id == organization_id,
            IntegrationConnection.source == "sumit",
        )
        .order_by(IntegrationConnection.id)
        .first()
    )
    if conn is not None and (conn.status or "").lower() in _BLOCKED:
        return None

    creds: dict = {}
    if conn is not None and conn.credentials_encrypted:
        try:
            creds = decrypt_credentials(conn.credentials_encrypted) or {}
        except Exception:
            creds = {}

    api_key = creds.get("api_key")
    company_id = creds.get("company_id")
    if not api_key:
        org = db.get(Organization, organization_id)
        stored = (org.api_credentials if org is not None and org.api_credentials else None) or {}
        api_key = stored.get("api_key")
        company_id = company_id or stored.get("company_id")
    if api_key:
        return {"api_key": api_key, "company_id": company_id}

    if settings.env_sumit_allowed(organization_id) and settings.sumit_api_key:
        return {
            "api_key": settings.sumit_api_key,
            "company_id": settings.sumit_company_id,
        }
    return None
