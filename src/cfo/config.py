"""
Configuration management for CFO system
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
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
    
    # Reports
    reports_output_dir: str = "./reports"
    timezone: str = "Asia/Jerusalem"


settings = Settings()
