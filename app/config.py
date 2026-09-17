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

    REQUEST_BUDGET_MS: int = 90000
    MAX_ATTEMPTS_PER_REQUEST: int = 4

    PHONE_RELAY_ENABLED: bool = False
    PHONE_RELAY_TOKEN: str = ""
    PHONE_RELAY_MAX_STREAMS_PER_PHONE: int = 4
    PHONE_RELAY_RENDER_TIMEOUT_MS: int = 45000
    PHONE_RELAY_COOLDOWN_MS: int = 5000
    PHONE_RELAY_BLOCK_PENALTY_MS: int = 180000
    PHONE_RELAY_TIMEOUT_PENALTY_MS: int = 60000
    PHONE_RELAY_TIMEOUT_STRIKE_LIMIT: int = 2
    PHONE_RELAY_USE_SEARCH_DEFAULT: bool = True

    PHONE_RELAY_STORE_ID: str = "2547"
    PHONE_RELAY_STORE_ZIP: str = "93552"
    PHONE_RELAY_STORE_STATE: str = "CA"
    PHONE_RELAY_STORE_REGION: str = "8"
    PHONE_RELAY_STORE_NEARBY_ID: str = "2502"
    PHONE_RELAY_STORE_CITY: str = "Palmdale"
    PHONE_RELAY_STORE_NAME: str = "E. Palmdale Lowe's"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
