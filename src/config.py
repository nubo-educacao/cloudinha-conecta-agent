import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_mcp_url() -> str:
    """Constrói a URL do MCP embutido usando a porta do próprio servidor.

    Cloud Run define PORT=8080. Dev local usa PORT=8000 (ou 8080 se não definido).
    O MCP SSE é montado em /mcp/sse dentro do mesmo processo FastAPI.
    """
    port = os.getenv("PORT", "8000")
    return f"http://localhost:{port}/mcp/sse"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: str  # Server-side only — schema discovery

    # Gemini
    GOOGLE_API_KEY: str
    TIMEZONE: str = "America/Sao_Paulo"
    PLANNING_MODEL: str = "gemini-2.0-flash-lite"
    REASONING_MODEL: str = "gemini-2.0-flash"
    RESPONSE_MODEL: str = "gemini-2.0-flash"

    # MCP Server embutido — URL calculada via PORT env var (override via MCP_SERVER_URL no .env)
    MCP_SERVER_URL: str = Field(default_factory=_default_mcp_url)

    # App
    CORS_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"


settings = Settings()
