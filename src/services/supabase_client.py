import logging
from functools import lru_cache
from supabase import create_client, Client

from src.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_supabase_anon() -> Client:
    """Supabase client com chave anon — para operações autenticadas por RLS."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


@lru_cache(maxsize=1)
def get_supabase_service() -> Client:
    """Supabase client com service key — apenas para server-side (schema discovery, agent_errors)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
