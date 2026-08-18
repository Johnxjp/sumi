from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
    )

    data_dir: str = "../data/notion-export-markdown"
    model_name: str = Field(
        default="gpt-4o-mini", description="LLM model identifier from OpenRouter"
    )
    api_key: str = Field(
        default="",
        validation_alias="openrouter_api_key",
        description="OpenRouter API key. Can also be set via OPENROUTER_API_KEY environment variable.",
    )


app_config = Settings()
