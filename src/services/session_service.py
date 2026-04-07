import logging
from typing import Optional
from supabase import Client

logger = logging.getLogger(__name__)


class InMemorySessionService:
    """Sessão transient para Planning e Reasoning — descartada após cada turno."""

    def __init__(self) -> None:
        self._history: list[dict] = []

    def add_message(self, role: str, content: str) -> None:
        self._history.append({"role": role, "content": content})

    def get_history(self) -> list[dict]:
        return list(self._history)

    def clear(self) -> None:
        self._history.clear()


class SupabaseSessionService:
    """Sessão persistente para o Response Agent — salva em chat_messages."""

    def __init__(self, supabase: Client, user_id: str, session_id: str) -> None:
        self._supabase = supabase
        self._user_id = user_id
        self._session_id = session_id

    def persist_user_message(self, content: str) -> None:
        """Persiste a mensagem do usuário em chat_messages."""
        try:
            self._supabase.table("chat_messages").insert({
                "user_id": self._user_id,
                "session_id": self._session_id,
                "role": "user",
                "content": content,
            }).execute()
        except Exception as e:
            logger.error(f"Falha ao persistir mensagem do usuário: {e}")

    def persist_agent_message(self, content: str) -> None:
        """Persiste a resposta da Cloudinha em chat_messages."""
        try:
            self._supabase.table("chat_messages").insert({
                "user_id": self._user_id,
                "session_id": self._session_id,
                "role": "assistant",
                "content": content,
            }).execute()
        except Exception as e:
            logger.error(f"Falha ao persistir mensagem do agente: {e}")

    def get_recent_messages(self, limit: int = 5) -> list[dict]:
        """Retorna as últimas N mensagens da sessão atual."""
        try:
            response = (
                self._supabase.table("chat_messages")
                .select("role, content")
                .eq("session_id", self._session_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(f"Falha ao carregar histórico da sessão: {e}")
            return []
