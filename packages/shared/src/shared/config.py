"""Shared configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = Field(default="openai", description="openai or anthropic")
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # External data APIs
    currents_api_key: str | None = None
    metals_api_key: str | None = None
    # MetalpriceAPI (https://metalpriceapi.com) — generous free tier, multi-metal.
    metalprice_api_key: str | None = None

    # Feature flags
    use_mock: bool = Field(default=True, description="Use mock data when true")
    log_level: str = "INFO"

    # Ports
    agent_port: int = 3000
    news_mcp_port: int = 8000
    pdf_mcp_port: int = 8001
    price_mcp_port: int = 8002

    # Public base URL used when rendering clickable links to uploaded files.
    agent_public_base_url: str = "http://localhost:3000"

    # Service name (used in health checks)
    mcp_server_name: str = "default"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
