"""Settings for the eval-generation scripts: model, temperature, concurrency."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    api_key: str = Field(
        default="",
        validation_alias="openrouter_api_key",
        description="OpenRouter API key. Set via OPENROUTER_API_KEY environment variable.",
    )
    model_name: str = Field(
        default="nvidia/nemotron-3.5-lightning:free",
        description="LLM model identifier from OpenRouter",
    )
    temperature: float = Field(default=0.7, description="Temperature for LLM sampling")
    queries_per_note: int = Field(
        default=3, description="Number of queries to generate per note"
    )
    concurrency: int = Field(
        default=8, description="Max concurrent LLM requests during query generation"
    )


settings = Settings()
