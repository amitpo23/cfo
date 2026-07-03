"""
Configuration management for CFO system
"""
import os
from pydantic import field_validator, model_validator
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
    auto_create_db: bool = False if os.getenv("VERCEL") else True
    # Development/QA only. When enabled, API requests without a Bearer token are
    # treated as a super-admin session. Do not enable on public production.
    auth_bypass_enabled: bool = False
    cors_allowed_origins: str = (
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173"
        if not os.getenv("VERCEL")
        else "https://cfo-2.vercel.app"
    )
    
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
    open_finance_webhook_secret: Optional[str] = None

    # Google Sign-In
    google_client_id: Optional[str] = None

    # SaaS billing / checkout. Stripe Checkout enables Apple Pay and Google Pay
    # when the Stripe account, domain, and payment methods are configured.
    stripe_secret_key: Optional[str] = None
    stripe_price_company_up_to_2_5m: Optional[str] = None
    stripe_price_company_above_2_5m: Optional[str] = None
    stripe_price_office: Optional[str] = None
    
    # OpenAI
    openai_api_key: Optional[str] = None

    # LLM vision OCR (expense receipt extraction pipeline)
    # Anthropic is preferred (native PDF support); OpenAI is a fallback.
    anthropic_api_key: Optional[str] = None
    # Vision model used to read receipt scans. Claude reads PDFs natively.
    ocr_vision_model: str = "claude-opus-4-8"
    ocr_vision_model_openai: str = "gpt-4o"
    # AI chat assistant (Wave 2 Step 9) — same anthropic_api_key as OCR above.
    ai_chat_model: str = "claude-sonnet-5"
    # Companies-registry (רשם החברות) lookup over data.gov.il CKAN.
    companies_registry_resource_id: str = "f004176c-b85f-4542-8901-7b3176f9a054"
    companies_registry_base_url: str = "https://data.gov.il/api/3/action/datastore_search"

    # Reports
    reports_output_dir: str = "./reports"
    timezone: str = "Asia/Jerusalem"

    # SMTP Email
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None

    @field_validator("database_url", mode="before")
    @classmethod
    def default_empty_database_url(cls, value):
        if value == "":
            return "sqlite:////tmp/cfo.db" if os.getenv("VERCEL") else "sqlite:///./cfo.db"
        if isinstance(value, str) and value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def default_empty_jwt_secret(cls, value):
        if value == "":
            return "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING"
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def validate_production_settings(self):
        if not os.getenv("VERCEL"):
            return self

        errors = []
        if not self.database_url or self.database_url.startswith("sqlite:"):
            errors.append("DATABASE_URL must point to a persistent production database")
        if (
            not self.jwt_secret_key
            or self.jwt_secret_key == "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING"
            or len(self.jwt_secret_key) < 32
        ):
            errors.append("JWT_SECRET_KEY must be a long random production secret")
        if not self.credentials_encryption_key or len(self.credentials_encryption_key) < 32:
            errors.append("CREDENTIALS_ENCRYPTION_KEY must be a separate long random secret")
        if not self.cron_secret:
            errors.append("CRON_SECRET must be configured for scheduled jobs")
        if not self.open_finance_webhook_secret:
            errors.append("OPEN_FINANCE_WEBHOOK_SECRET must be configured")

        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))
        return self


settings = Settings()
