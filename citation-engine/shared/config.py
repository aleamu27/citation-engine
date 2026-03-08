from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080

    geoip_db_path: str = "./GeoLite2-City.mmdb"
    environment: str = "development"

    # Embedding model — multilingual, handles NO + EN
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024

    # Chunking
    chunk_size: int = 400
    chunk_overlap: int = 60

    # Search
    top_k: int = 10

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
