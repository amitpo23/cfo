"""
Configuration management for CFO system
"""
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
    debug: bool = False
    log_level: str = "INFO"
    
    # Database
    database_url: str = "sqlite:///./cfo.db"
    
    # Security
    jwt_secret_key: str = "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    
    # Accounting Systems
    quickbooks_client_id: Optional[str] = None
    quickbooks_client_secret: Optional[str] = None
    quickbooks_realm_id: Optional[str] = None
    
    xero_client_id: Optional[str] = None
    xero_client_secret: Optional[str] = None
    
    # SUMIT API
    sumit_api_key: Optional[str] = None
    sumit_company_id: Optional[str] = None
    
    # OpenAI
    openai_api_key: Optional[str] = None
    
    # Reports
    reports_output_dir: str = "./reports"
    timezone: str = "Asia/Jerusalem"


settings = Settings()
