from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+pysqlite:////Users/lu/Desktop/cursor/cs-midplatform/backend/cs.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret: str = "change-me-jwt-secret"
    webhook_secret: str = "dev-secret"
    cors_origins: str = "http://localhost:3000"

    liveagent_base_url: str = "https://pingo.ladesk.com"
    liveagent_api_v3_key: str = ""
    liveagent_api_v1_key: str = ""
    liveagent_agent_email: str = ""
    liveagent_dry_run: bool = True
    # Transfer/assign chat to LIVEAGENT_AGENT_EMAIL before posting AI replies
    liveagent_auto_transfer: bool = True

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    default_reply_lang: str = "id"
    min_faq_score: float = 0.18
    min_history_score: float = 0.22
    ai_enabled: bool = True

    # Evening history learning (worker scheduled task; rebuilds from full DB)
    history_learn_enabled: bool = True
    history_learn_hour: int = 22  # local hour, default 22:00 (evening)
    history_learn_timezone: str = "Asia/Jakarta"
    history_learn_limit_conversations: int = 8000

    seed_agent_email: str = "agent@pingo.com"
    seed_agent_password: str = "agent123"

    faq_path: Path = BACKEND_ROOT / "knowledge" / "faq.json"
    history_path: Path = BACKEND_ROOT / "knowledge" / "history_pairs.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
