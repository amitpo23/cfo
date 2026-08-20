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
    # Fail closed into the free SUMIT testing track.  A live environment must
    # be selected explicitly; misspellings must never enable live behavior.
    sumit_environment: str = "test"
    # 200 — הנחיית בעלים 19/08/2026: 200 קריאות בחודש **לכל ארגון**
    # ("מאחר וכרגע מותר 400 לכל ארגון זה מרווח ביטחון מתאים") — שולי
    # ביטחון של 50% מתחת למכסת מסלול הבדיקות של SUMIT.
    sumit_test_monthly_request_limit: int = 200
    sumit_test_monthly_paid_action_limit: int = 90
    sumit_test_org_daily_request_limit: int = 20
    sumit_test_requests_per_minute: int = 10
    # W2.2 (20/08/2026): ב-live לא היה בלם חודשי בכלל — 300/יום ≈ 9,000
    # בחודש. התקרות כאן הן תקציב עלות פנימי, לא מכסת ספק, ומוצמדות
    # לתקרה קשיחה בקוד (ראה enforce_cost_protection_floors).
    sumit_live_monthly_request_limit: int = 2000
    sumit_live_monthly_paid_action_limit: int = 90
    # פורטל ההנה"ח של המשרד (CompanyID 844329067) הוא ישות נפרדת מתיק
    # לקוח בודד: הוא מחזיק את כל התיקים, ורק מפתח שלו מורשה לפעולות
    # ברמת המשרד. `SUMIT_BOOKS_AMIT_PORAT.md` השאיר זאת כשאלה פתוחה —
    # "איזה API key מורשה ל-DatabaseID, של חברת ה-org או של המשרד?"
    #
    # השדות נפרדים במכוון ואינם נופלים חזרה ל-`sumit_api_key`. נפילה
    # כזו הייתה שולחת קריאה ברמת משרד עם מפתח של תיק בודד, או גרוע
    # מכך — דורסת את המפתח של org1 ומפנה את הסנכרון שלו לחברה אחרת.
    sumit_office_api_key: Optional[str] = None
    sumit_office_company_id: Optional[str] = None

    # Open Finance API
    open_finance_client_id: Optional[str] = None
    open_finance_client_secret: Optional[str] = None
    open_finance_user_id: Optional[str] = None
    open_finance_api_base_url: str = "https://api.open-finance.ai/v2"
    open_finance_oauth_url: str = "https://api.open-finance.ai/oauth/token"
    open_finance_webhook_secret: Optional[str] = None
    # Shared secret for the SUMIT triggers webhook receiver (see
    # api/routes/sumit_webhooks.py) — same pattern as the Open Finance one.
    sumit_webhook_secret: Optional[str] = None

    # Telegram conversational channel (plan 2026-07-26, package 3). Bot API
    # token from @BotFather; the webhook secret is a separate value you set
    # yourself and register with Telegram's setWebhook (secret_token param) —
    # api/routes/telegram_webhook.py compares it via secrets.compare_digest.
    # Unset secret => the webhook route answers 503 (channel not configured),
    # never silently open.
    telegram_bot_token: Optional[str] = None
    telegram_webhook_secret: Optional[str] = None

    # WhatsApp conversational channel (Meta Cloud API directly — no Twilio/
    # 360dialog), package F (plan 2026-07-27b) — /api/whatsapp/webhook.
    # phone_number_id + access_token identify the ONE shared business number
    # all customers message (SUMIT-bot pattern — routing is by sender
    # number, not by a per-customer number). verify_token is a value you
    # choose yourself and register in the Meta App dashboard's webhook
    # subscription (compared via secrets.compare_digest on the GET
    # handshake). app_secret authenticates every POST body via the
    # X-Hub-Signature-256 HMAC header. Any of these unset => the
    # corresponding webhook path answers 503 (channel not configured),
    # never silently open — same doctrine as the Telegram secret above.
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_access_token: Optional[str] = None
    whatsapp_verify_token: Optional[str] = None
    whatsapp_app_secret: Optional[str] = None
    whatsapp_api_version: str = "v21.0"
    # Approved Meta template used for proactive pushes outside the 24-hour
    # customer-service window.  Unset means fail honestly with
    # outside_service_window; free-form text is never attempted there.
    whatsapp_push_template_name: Optional[str] = None
    whatsapp_push_template_language: str = "he"

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
    # החלטת משתמש (2026-07-06): מפתח ה-API משרת את עוזר ה-AI בלבד.
    # OCR מבוסס-LLM נצרך מכסה ברקע (cron) — כבוי אלא אם הופעל במפורש.
    ocr_llm_enabled: bool = False
    # A scheduled OCR document consumes at least one SUMIT getpdf action and
    # one LLM call (and may later file/cancel). Explicit enablement is still
    # required; this is the additional per-org/day document cap.
    ocr_daily_document_limit: int = 10
    # Chat-initiated receipt intake (package A, moshko-full-bot plan
    # 2026-07-27): a user explicitly sending a photo/PDF straight to the chat
    # bot (e.g. Telegram) is a different cost/consent story than the
    # scheduled background OCR pipeline gated by ocr_llm_enabled above — see
    # vision_extractor.extract_receipt's user_initiated flag for why these
    # are two independent gates, not one shared flag.
    chat_receipt_intake_enabled: bool = True
    # Per-org/day cap on chat-initiated receipt intakes (mirrors
    # ocr_daily_document_limit's role for the background pipeline).
    chat_receipt_daily_limit: int = 20
    # AI chat assistant (Wave 2 Step 9) — same anthropic_api_key as OCR above.
    # Haiku 4.5 — המודל הזול ביותר. הכרעת בעלים 17/08/2026, כשיתרת
    # החשבון עמדה על $1.92. זה אינו רק חיסכון: חשבון שנגמר באמצע יום
    # עבודה משבית את מושקו לגמרי, בלי אזהרה. ברירת מחדל יקרה היא סיכון
    # זמינות, לא רק סיכון תקציב.
    #
    # נשאר משתנה סביבה (`AI_CHAT_MODEL`) — משימה שדורשת מודל חזק יותר
    # יכולה להעלות אותו נקודתית.
    ai_chat_model: str = "claude-haiku-4-5-20251001"
    # JSON object keyed by exact model id. Rates are USD per one million
    # tokens: input_per_million_usd, output_per_million_usd and, when cache
    # tokens occur, cache_read_per_million_usd/cache_creation_per_million_usd.
    # Deliberately empty by default: pricing changes and an unconfigured or
    # unknown model must produce cost=NULL, never a guessed amount.
    llm_pricing_json: str = "{}"
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

    # Sync call-protection (M1a — RSF-020..032). See services/sync_engine.py.
    # Overlap window subtracted from SyncCheckpoint.last_success_at to compute
    # the `updated_since` watermark passed to connectors (covers late-arriving
    # documents/clock skew without re-fetching full history every run).
    sync_overlap_days: int = 3
    # Hard page cap per entity type per run; stop with a PARTIAL result (and a
    # resumable cursor) instead of an unbounded loop against a live API.
    sync_max_pages_per_entity: int = 20
    # How long to skip an entity after a 401/403/quota/obligo/IP-block error
    # before trying again (circuit breaker).
    sync_circuit_open_hours: int = 6
    # Base delay (seconds) for the transient-5xx retry backoff. Kept small and
    # overridable so tests don't burn real wall-clock time.
    sync_retry_base_delay_seconds: float = 0.5
    # Open Finance has a limited monthly call budget (~500 calls) — scheduled
    # OF syncs are capped to at most one *successful full* sync per org per
    # this many hours (daily-ish, not hourly).
    of_sync_min_interval_hours: int = 20
    # SUMIT bills API overage to the CLIENT company's own payment method
    # (incident 2026-07-17: daily ILS 62.23 invoices to org 2's business).
    # Scheduled SUMIT syncs are therefore code-gated to one successful full
    # sync per org per this many hours — the cron schedule alone is not a
    # guarantee.
    sumit_sync_min_interval_hours: int = 20
    # Hard request-boundary ceilings shared through Postgres. SUMIT documents
    # a temporary block at roughly 100 requests/minute, so Rezef stays below
    # that with a non-configurably-higher maximum of 80. The daily value is an
    # internal paid-action safety budget per organization, not a provider quota.
    sumit_global_requests_per_minute: int = 80
    sumit_org_daily_request_limit: int = 300
    # /documents/getdetails is one paid SUMIT action per document. Supplier
    # enrichment is therefore capped independently from the once-daily job
    # cadence. This is an internal cost budget, not a claimed provider quota;
    # operators may lower it (including 0 to disable), never raise above 25.
    sumit_enrichment_daily_action_limit: int = 25
    # Minimum time between manually-triggered (POST /sync/run) syncs for the
    # same org/source, to stop a user/UI from hammering the provider.
    manual_refresh_cooldown_minutes: int = 15

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

    @field_validator("sumit_environment", mode="before")
    @classmethod
    def normalize_sumit_environment(cls, value):
        normalized = value.strip().lower() if isinstance(value, str) else "test"
        return normalized if normalized in {"test", "live"} else "test"

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def enforce_cost_protection_floors(self):
        """Hard floors (owner directive 2026-07-17, after real SUMIT API-overage
        charges hit a client's card): daily sync only, never exceed provider
        quotas. Env/config mistakes must not be able to loosen these — values
        below the floor are clamped up, silently and unconditionally."""
        if self.of_sync_min_interval_hours < 20:
            self.of_sync_min_interval_hours = 20
        if self.sumit_sync_min_interval_hours < 20:
            self.sumit_sync_min_interval_hours = 20
        self.sumit_global_requests_per_minute = min(
            80, max(0, self.sumit_global_requests_per_minute),
        )
        self.sumit_org_daily_request_limit = min(
            300, max(0, self.sumit_org_daily_request_limit),
        )
        self.sumit_test_monthly_request_limit = min(
            200, max(0, self.sumit_test_monthly_request_limit),
        )
        self.sumit_live_monthly_request_limit = min(
            2000, max(0, self.sumit_live_monthly_request_limit),
        )
        self.sumit_live_monthly_paid_action_limit = min(
            90, max(0, self.sumit_live_monthly_paid_action_limit),
        )
        self.sumit_test_monthly_paid_action_limit = min(
            90, max(0, self.sumit_test_monthly_paid_action_limit),
        )
        self.sumit_test_org_daily_request_limit = min(
            20, max(0, self.sumit_test_org_daily_request_limit),
        )
        self.sumit_test_requests_per_minute = min(
            10, max(0, self.sumit_test_requests_per_minute),
        )
        if self.sumit_environment == "test":
            self.sumit_org_daily_request_limit = min(
                self.sumit_org_daily_request_limit,
                self.sumit_test_org_daily_request_limit,
            )
            self.sumit_global_requests_per_minute = min(
                self.sumit_global_requests_per_minute,
                self.sumit_test_requests_per_minute,
            )
        self.sumit_enrichment_daily_action_limit = min(
            25,
            max(0, self.sumit_enrichment_daily_action_limit),
        )
        self.ocr_daily_document_limit = min(
            25,
            max(0, self.ocr_daily_document_limit),
        )
        self.chat_receipt_daily_limit = min(
            50,
            max(0, self.chat_receipt_daily_limit),
        )
        if self.manual_refresh_cooldown_minutes < 15:
            self.manual_refresh_cooldown_minutes = 15
        return self

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
