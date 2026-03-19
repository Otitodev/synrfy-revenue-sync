from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # VenueSuite
    venuesuite_base_url: str
    venuesuite_token: str
    venuesuite_venue_id: str

    # MEWS
    mews_base_url: str
    mews_client_token: str
    mews_access_token: str
    mews_client_name: str = "SynrfyRevenueSync/1.0"

    # Scheduler (24h clock, time before night audit)
    sync_hour: int = 22
    sync_minute: int = 0

    # Local state
    database_url: str = "sqlite:///./synrfy.db"
    category_mapping_path: str = "config/category_mapping.yaml"
    fallback_category: str = "GeneralRevenue"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
