from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: str  # Server-side only — schema discovery

    # Gemini
    GOOGLE_API_KEY: str
    PLANNING_MODEL: str = "gemini-2.0-flash-lite"
    REASONING_MODEL: str = "gemini-2.0-flash"
    RESPONSE_MODEL: str = "gemini-2.0-flash"

    # MCP Server (nubo-tools)
    MCP_SERVER_URL: str = "http://localhost:8001/mcp"

    # App
    CORS_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
