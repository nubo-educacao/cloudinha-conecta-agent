import os
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # MCP SSE embutido no FastAPI — URL padrão usa porta do servidor.
    # Se .env tiver a URL legada (localhost:8001) ela é substituída automaticamente.
    # Para apontar a um MCP externo, defina MCP_SERVER_URL com outro host/porta.
    MCP_SERVER_URL: str = ""

    @field_validator("MCP_SERVER_URL", mode="before")
    @classmethod
    def resolve_mcp_url(cls, v: str) -> str:
        """Redireciona URL legada (processo separado :8001) para o MCP embutido.

        pydantic_settings lê o .env com prioridade sobre default_factory, então
        usamos um validator para interceptar e substituir a URL obsoleta.
        O MCP SSE está montado em /mcp/sse no mesmo processo FastAPI (PORT env var).
        """
        v = str(v or "")
        # URL legada do processo separado ou ausente → usar MCP embutido
        if not v or "localhost:8001" in v:
            port = os.getenv("PORT", "8000")
            return f"http://localhost:{port}/mcp/sse"
        return v

    # App
    CORS_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"


settings = Settings()
