from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    SERVICE_NAME: str
    ENVIRONMENT: str = "local"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    INTER_SERVICE_SECRET: str
    GATEWAY_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
