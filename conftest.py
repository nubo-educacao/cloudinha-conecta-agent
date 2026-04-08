"""Root conftest.py — injeta variáveis de ambiente para testes.

DEVE ser o primeiro arquivo executado pelo pytest.
Garante que src.config.Settings não falhe por falta de .env em CI/CD.
"""
import os

# Injetado ANTES de qualquer import de src.*
_TEST_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_KEY": "test-service-key",
    "GOOGLE_API_KEY": "test-google-key",
    "MCP_SERVER_URL": "http://localhost:8001/mcp",
    "CORS_ORIGINS": "*",
    "LOG_LEVEL": "WARNING",
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)
