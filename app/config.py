from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PORT: int = 3000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGIN: str = "*"

    MIN_DELAY_MS: int = 800
    MAX_DELAY_MS: int = 3500

    REQUEST_BUDGET_MS: int = 60000
    MAX_ATTEMPTS_PER_REQUEST: int = 4

    PHONE_RELAY_ENABLED: bool = False
    PHONE_RELAY_TOKEN: str = ""
    PHONE_RELAY_MAX_STREAMS_PER_PHONE: int = 4
    PHONE_RELAY_RENDER_TIMEOUT_MS: int = 45000
    PHONE_RELAY_COOLDOWN_MS: int = 5000
    PHONE_RELAY_BLOCK_PENALTY_MS: int = 180000
    PHONE_RELAY_TIMEOUT_PENALTY_MS: int = 60000
    PHONE_RELAY_TIMEOUT_STRIKE_LIMIT: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
