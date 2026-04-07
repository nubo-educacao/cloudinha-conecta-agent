"""FastAPI dependency injection."""
from fastapi import Depends
from supabase import Client

from src.services.supabase_client import get_supabase_anon, get_supabase_service


def supabase_anon() -> Client:
    return get_supabase_anon()


def supabase_service() -> Client:
    return get_supabase_service()
