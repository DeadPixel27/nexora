"""
Configuration — single place for all settings.

WHY: Instead of hardcoding paths like "uploads/" in 10 files,
     we read them once here. Change one place, everything updates.

HOW: pydantic-settings reads from .env file + environment variables.
"""

from pathlib import Path
import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (parent of app/)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
    )

    # Where uploaded files are saved on disk
    upload_dir: Path = BACKEND_DIR / "uploads"

    # Max file size per upload (in megabytes)
    max_upload_size_mb: int = 10
    # Max PDF pages per file (images count as 1). Soft product guard for
    # single-call GPT-4o extract quality; raise when chunked extract ships.
    max_pages_per_file: int = 10

    # File types we accept
    allowed_extensions: set[str] = {".pdf", ".png", ".jpg", ".jpeg"}

    # Groq LLM — field extraction
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Refiner — can use a stronger model if configured
    groq_refiner_model: str = "llama-3.3-70b-versatile"
    # Owner master template synthesis
    groq_owner_model: str = "llama-3.3-70b-versatile"
    # Comma-separated fallbacks when primary model fails
    groq_fallback_models: str = (
        "llama-3.1-8b-instant,"
        "meta-llama/llama-4-scout-17b-16e-instruct,"
        "openai/gpt-oss-20b"
    )

    # OpenAI — primary extraction model
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    # Comma-separated OpenAI fallbacks (Mini as fallback for cost savings)
    openai_fallback_models: str = "gpt-4o-mini"

    # JWT authentication
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 72
    # Short-lived capability tokens for <img>/<iframe> document URLs
    document_token_expiry_minutes: int = 15

    # Usage limits
    free_page_limit_monthly: int = 50
    max_refines_per_run: int = 10
    # Global page brake across all users (UTC day). Keep low while OpenAI
    # credit balance is small — 100 pages ≈ ~$1 at typical extract cost.
    global_daily_page_limit: int = 100
    # Estimated OpenAI USD budget (token-based). 0 = disabled. Hard fail-closed gate.
    # With ~$5 credit, $1/day keeps the balance alive ~5 full days of burn.
    openai_daily_budget_usd: float = 1.0
    # Outbound free-tier units (separate from page pool)
    free_email_limit_monthly: int = 20
    free_sheets_limit_monthly: int = 20
    # BackgroundTasks orphan reclaim (single-replica launch posture)
    orphan_reclaim_on_startup: bool = True
    orphan_run_stale_minutes: int = 30

    # OCR engine — "tesseract" or "rapidocr"
    ocr_engine: str = "rapidocr"

    # Layout preservation — use Docling for digital PDFs
    use_layout_preservation: bool = True

    admin_api_key: str = ""

    # User template version payloads: auto | local | supabase | aws_s3
    user_template_storage: str = "auto"
    supabase_user_templates_bucket: str = "user-templates"
    # Future AWS S3 swap (USER_TEMPLATE_STORAGE=aws_s3)
    aws_s3_bucket: str = ""
    aws_s3_region: str = ""
    aws_s3_user_templates_prefix: str = "user-templates"

    # Deployment environment — set APP_ENV=production on Railway
    app_env: str = "development"
    # Log prompt tails / extracted field values (local debug only)
    log_payloads: bool = False

    # Supabase — persistence (optional; falls back to in-memory)
    supabase_url: str = ""
    supabase_secret_key: str = ""

    # Document file storage: auto | local | supabase
    document_storage: str = "auto"
    supabase_documents_bucket: str = "documents"

    # Data persistence: auto | memory | supabase
    persistence_backend: str = "auto"

    # Auth: email = lookup by email (no password); Google uses POST /api/auth/google
    auth_backend: str = "email"
    # Allow passwordless email session (local/tests only). Production should be false.
    auth_allow_email: bool = False
    # Google Identity Services OAuth Web client ID (ID token audience)
    google_client_id: str = ""

    # Email delivery (Resend)
    resend_api_key: str = ""
    resend_from_email: str = "onboarding@resend.dev"

    # Google Sheets (service account JSON path or raw JSON string)
    google_service_account_json: str = ""

    # Inbound email (Mailgun webhook)
    inbound_email_domain: str = "ingest.nexora.app"
    inbound_webhook_secret: str = ""
    # Reject webhooks whose timestamp is older/newer than this many seconds
    inbound_webhook_max_age_seconds: int = 300
    # How long to remember tokens to ignore replays (single-replica in-memory)
    inbound_webhook_token_ttl_seconds: int = 900

    # Job queue — Redis URL enables Arq workers (empty = in-process asyncio fallback)
    redis_url: str = ""

    # Comma-separated origins for CORS (e.g. http://localhost:3000,https://app.vercel.app)
    cors_origins: str = "http://localhost:3000"

    # slowapi rate limits (see https://slowapi.readthedocs.io/en/latest/)
    rate_limit_runs_adhoc: str = "10/minute"
    rate_limit_upload: str = "20/minute"
    rate_limit_email: str = "5/minute"
    rate_limit_sheets: str = "5/minute"
    rate_limit_extract: str = "10/minute"
    rate_limit_refine_plan: str = "20/minute"
    rate_limit_pipeline: str = "10/minute"
    rate_limit_auth: str = "10/minute"
    rate_limit_waitlist: str = "5/minute"
    rate_limit_inbound: str = "60/minute"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _normalize_cors_origins(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(item).strip() for item in value if str(item).strip())
        return str(value) if value is not None else "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def groq_fallback_models_list(self) -> list[str]:
        return [
            model.strip()
            for model in self.groq_fallback_models.split(",")
            if model.strip()
        ]

    @property
    def openai_fallback_models_list(self) -> list[str]:
        return [
            model.strip()
            for model in self.openai_fallback_models.split(",")
            if model.strip()
        ]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        env = self.app_env.strip().lower()
        if env in {"production", "prod"}:
            return True
        return os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "production"

    @property
    def job_queue_enabled(self) -> bool:
        """True when REDIS_URL is set — API enqueues; Arq workers execute runs."""
        return bool(self.redis_url.strip())

    def require_persistent_backend(self, backend_name: str) -> None:
        """Raise if production is using in-memory data persistence."""
        if self.is_production and backend_name == "memory":
            raise RuntimeError(
                "In-memory persistence is not allowed in production. "
                "Set SUPABASE_URL and SUPABASE_SECRET_KEY, or unset APP_ENV=production."
            )


settings = Settings()

# Create upload folder on startup if it doesn't exist
settings.upload_dir.mkdir(parents=True, exist_ok=True)
