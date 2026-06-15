"""
Configuration management for CFO system
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    model_config = SettingsConfigDict(
        # Keep .env for standard setups and allow .env.local overrides for
        # local development secrets that should not be committed.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignore unknown env vars (e.g. VERCEL_*, system vars, vercel env pull
        # output) instead of crashing the app on boot.
        extra="ignore",
    )
    
    # Application
    app_name: str = "CFO Management System"
    app_url: str = "https://cfo-2.vercel.app" if os.getenv("VERCEL") else "http://localhost:8000"
    debug: bool = False
    log_level: str = "INFO"
    
    # Database
    database_url: str = "sqlite:////tmp/cfo.db" if os.getenv("VERCEL") else "sqlite:///./cfo.db"
    
    # Security
    jwt_secret_key: str = "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    # When set, /auth/register requires this code — keeps open registration
    # closed on public deployments.
    registration_secret: Optional[str] = None
    # Fernet key material for integration credentials at rest (falls back to
    # jwt_secret_key when unset).
    credentials_encryption_key: Optional[str] = None
    # Shared secret for the scheduled-sync endpoint; Vercel Cron sends it as
    # "Authorization: Bearer <CRON_SECRET>".
    cron_secret: Optional[str] = None
    
    # Accounting Systems
    quickbooks_client_id: Optional[str] = None
    quickbooks_client_secret: Optional[str] = None
    quickbooks_realm_id: Optional[str] = None
    
    xero_client_id: Optional[str] = None
    xero_client_secret: Optional[str] = None
    
    # SUMIT API
    sumit_api_key: Optional[str] = None
    sumit_company_id: Optional[str] = None

    # Open Finance API
    open_finance_client_id: Optional[str] = None
    open_finance_client_secret: Optional[str] = None
    open_finance_user_id: Optional[str] = None
    open_finance_api_base_url: str = "https://api.open-finance.ai/v2"
    open_finance_oauth_url: str = "https://api.open-finance.ai/oauth/token"
    
    # OpenAI
    openai_api_key: Optional[str] = None

    # LLM vision OCR (expense receipt extraction pipeline)
    # Anthropic is preferred (native PDF support); OpenAI is a fallback.
    anthropic_api_key: Optional[str] = None
    # Vision model used to read receipt scans. Claude reads PDFs natively.
    ocr_vision_model: str = "claude-opus-4-8"
    ocr_vision_model_openai: str = "gpt-4o"
    # Companies-registry (רשם החברות) lookup over data.gov.il CKAN.
    companies_registry_resource_id: str = "f004176c-b85f-4542-8901-7b3176f9a054"
    companies_registry_base_url: str = "https://data.gov.il/api/3/action/datastore_search"

    # Reports
    reports_output_dir: str = "./reports"
    timezone: str = "Asia/Jerusalem"


settings = Settings()
