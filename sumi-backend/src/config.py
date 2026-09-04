"""Application settings from .env. Every .env variable needs a field here."""

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
    gemini_api_key: str = Field(
        default="",
        description="Gemini API key for embeddings. Set via GEMINI_API_KEY environment variable.",
    )
    database_url: str = Field(
        default="postgresql://localhost:5432/sumi",
        description="Postgres connection URL for the pgvector index. Set via DATABASE_URL environment variable.",
    )
    embedding_dimensions: int = Field(
        default=768,
        description="Output dimensionality for embeddings. gemini-embedding-2 auto-normalizes truncated dimensions.",
    )
    breadbowl_api_url: str = Field(
        default="",
        description="BreadBowl API base URL. Set via BREADBOWL_API_URL environment variable.",
    )
    breadbowl_api_key: str = Field(
        default="",
        description="BreadBowl API key. Set via BREADBOWL_API_KEY environment variable.",
    )
    gmail_mcp_url: str = Field(
        default="http://localhost:8000/mcp",
        description="Endpoint of the locally-run workspace-mcp server (scripts/run_gmail_mcp.sh).",
    )
    google_oauth_client_id: str = Field(
        default="",
        description="OAuth web-app client ID for the workspace-mcp server. Set via GOOGLE_OAUTH_CLIENT_ID.",
    )
    google_oauth_client_secret: str = Field(
        default="",
        description="OAuth web-app client secret for the workspace-mcp server. Set via GOOGLE_OAUTH_CLIENT_SECRET.",
    )
    user_google_email: str = Field(
        default="",
        description="Gmail address the workspace-mcp server acts on. Set via USER_GOOGLE_EMAIL.",
    )
    logfire_api_key: str = Field(
        default="",
        description="Pydantic Logfire write token. Set via LOGFIRE_API_KEY; empty means traces are not sent.",
    )


app_config = Settings()
