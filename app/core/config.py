from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aereo Geospatial Measurement API"
    app_env: str = "development"
    debug: bool = False
    database_url: str = "sqlite:///./aereo.db"
    storage_dir: str = "./uploads"
    max_upload_size_mb: int = 25

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
