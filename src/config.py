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

    # MCP Server (nubo-tools)
    MCP_SERVER_URL: str = "http://localhost:8001/sse"

    # App
    CORS_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"



settings = Settings()
