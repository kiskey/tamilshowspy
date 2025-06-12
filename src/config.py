import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # Application
    LOG_LEVEL: str = "INFO"
    PURGE_ON_START: bool = False
    DOMAIN_MONITOR: str = "www.1tamilblasters.fi"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Crawler
    FORUM_URL: str = "https://www.1tamilblasters.fi/index.php?/forums/forum/63-tamil-new-web-series-tv-shows/"
    CRAWL_INTERVAL: int = 1800  # 30 minutes
    THREAD_REVISIT_HOURS: int = 24
    MAX_CONCURRENCY: int = 8
    INITIAL_PAGES: int = 5
    REQUEST_THROTTLE_MS: int = 250

    # API Server
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8080

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
