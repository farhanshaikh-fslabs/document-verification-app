from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GCC/CPC Compliance POC"
    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Default SQLite for local POC; set DATABASE_URL to postgresql+asyncpg://... for Postgres
    database_url: str = "sqlite+aiosqlite:///./poc_compliance.db"

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    uploads_dir: Path = data_dir / "uploads"
    lab_accreditation_file: Path = data_dir / "lab_accreditation.json"

    confidence_threshold: float = 0.75

    # OCR: optional; if tesseract not installed, pipeline uses text-only
    ocr_enabled: bool = True
    # document_processor: "bedrock" (primary) or "rule" fallback-only mode
    document_processor: str = "bedrock"
    aws_region: str = "us-east-1"
    # Example Bedrock model IDs:
    # - anthropic.claude-3-5-sonnet-20240620-v1:0
    # - amazon.nova-pro-v1:0
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    return s
