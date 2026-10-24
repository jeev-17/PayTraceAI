from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_webhook_id: str | None = None
    database_url: str = "sqlite:///./paytrace.db"
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    frontend_origin: str = "http://localhost:5173"
    pending_threshold_minutes: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def config_presence(self) -> dict[str, bool]:
        return {
            "paypal_client_id": bool(self.paypal_client_id),
            "paypal_client_secret": bool(self.paypal_client_secret),
            "paypal_base_url": bool(self.paypal_base_url),
            "paypal_webhook_id": bool(self.paypal_webhook_id),
            "database_url": bool(self.database_url),
            "llm_provider": bool(self.llm_provider),
            "llm_api_key": bool(self.llm_api_key),
            "llm_model": bool(self.llm_model),
            "frontend_origin": bool(self.frontend_origin),
            "pending_threshold_minutes": self.pending_threshold_minutes > 0,
        }


settings = Settings()
