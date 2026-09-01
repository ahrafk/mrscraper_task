from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PORT: int = 3000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGIN: str = "*"

    MAX_CONCURRENCY: int = 4
    MIN_DELAY_MS: int = 800
    MAX_DELAY_MS: int = 3500

    REQUEST_BUDGET_MS: int = 55000
    MAX_ATTEMPTS_PER_REQUEST: int = 4

    PROXY_LIST: str = ""
    MRSCRAPER_USERNAME: str = ""
    MRSCRAPER_PASSWORD: str = ""
    MRSCRAPER_HOST: str = "proxy.mrscraper.com"
    MRSCRAPER_PORT: int = 10000
    MRSCRAPER_SESSION_TEMPLATE: str = "{username}-sessid-{session}"
    PROXY_COOLDOWN_MS: int = 120000

    PROXY_BACKEND: str = "mrscraper"
    PHONE_RELAY_ENABLED: bool = False
    PHONE_RELAY_LOCAL_PORT: int = 8899
    PHONE_RELAY_TOKEN: str = ""
    PHONE_RELAY_MAX_STREAMS_PER_PHONE: int = 4
    PHONE_RELAY_OPEN_TIMEOUT_MS: int = 15000
    PHONE_RELAY_RENDER_TIMEOUT_MS: int = 45000
    PHONE_RELAY_COOLDOWN_MS: int = 5000

    HEADLESS: bool | Literal["virtual"] = True

    @property
    def proxy_list(self) -> list[str]:
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
