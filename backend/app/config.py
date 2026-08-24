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
    # LoginKey panel pickUpChat before send (clears visitor waiting / ringing)
    liveagent_panel_accept: bool = True
    # Keep PinGo CS chat presence online via Devices API (does not replace auto-transfer)
    liveagent_keep_online: bool = True
    liveagent_keep_online_interval_sec: int = 60
    liveagent_agent_user_id: str = ""  # optional; else resolve via LIVEAGENT_AGENT_EMAIL
    liveagent_chat_department_id: str = ""  # optional; else prefer dept containing the agent

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # OpenAI-compatible API root (default official). Use with OPENAI_PROXY on geo-blocked VPS.
    openai_base_url: str = "https://api.openai.com/v1"
    # Optional HTTP(S)/SOCKS proxy for OpenAI SDK only (Singapore VPN egress from Aliyun HK).
    # Also honors HTTPS_PROXY / HTTP_PROXY / ALL_PROXY if this is empty.
    openai_proxy: str = ""
    default_reply_lang: str = "id"
    min_faq_score: float = 0.18
    min_history_score: float = 0.22
    ai_enabled: bool = True
    # When false: Smart still generates + stores local AI bubbles for agents,
    # but does NOT post_reply / outbox-deliver to LiveAgent (visitors).
    # Set true when reply quality is OK to resume customer-facing AI.
    ai_send_to_customer: bool = False

    # Evening history learning (worker scheduled task; rebuilds from full DB)
    history_learn_enabled: bool = True
    history_learn_hour: int = 22  # local hour, default 22:00 (evening)
    history_learn_timezone: str = "Asia/Jakarta"
    history_learn_limit_conversations: int = 8000

    # After HISTORY_LEARN: promote high-quality human replies into faq.json
    faq_auto_promote: bool = True
    faq_promote_max_per_night: int = 50
    faq_promote_min_answer_chars: int = 20
    faq_promote_max_answer_chars: int = 2000
    faq_promote_min_question_chars: int = 8
    faq_promote_min_repeat: int = 2  # prefer questions seen >= N times
    faq_promote_dedupe_similarity: float = 0.82
    faq_promote_category_similarity: float = 0.35

    seed_agent_email: str = "agent@pingo.com"
    seed_agent_password: str = "agent123"
    # Optional system admin (created on seed when both set)
    seed_admin_email: str = ""
    seed_admin_password: str = ""

    default_product_code: str = "pingo"
    default_country_code: str = "ID"

    # Optional second product: Avantee (separate LiveAgent tenant)
    avantee_product_code: str = "avantee"
    avantee_product_name: str = "Avantee"
    avantee_country_code: str = "ID"
    avantee_customer_reply_lang: str = "id"
    avantee_workspace_name: str = "Avantee Indonesia"
    avantee_liveagent_base_url: str = ""
    avantee_liveagent_api_v3_key: str = ""
    avantee_liveagent_api_v1_key: str = ""
    avantee_liveagent_agent_email: str = ""
    avantee_liveagent_dry_run: bool = False
    avantee_agent_display_name: str = "Joy"
    avantee_kb_source_product_code: str = "pingo"

    faq_path: Path = BACKEND_ROOT / "knowledge" / "faq.json"
    categories_path: Path = BACKEND_ROOT / "knowledge" / "categories.json"
    history_path: Path = BACKEND_ROOT / "knowledge" / "history_pairs.json"
    unknown_questions_path: Path = BACKEND_ROOT / "knowledge" / "unknown_questions.jsonl"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
