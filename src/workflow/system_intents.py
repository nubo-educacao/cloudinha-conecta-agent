"""Interceptor de System Intents.

System intents são comandos internos enviados pelo frontend com intent_type='system_intent'.
Eles NÃO são persistidos em chat_messages e NÃO passam pelo pipeline completo.
"""
import logging
from typing import Optional

from src.models.chat_request import ChatRequest

logger = logging.getLogger(__name__)

# Comandos de sistema reconhecidos
SYSTEM_INTENT_COMMANDS = {
    "get_starters",       # Buscar conversation starters para a rota atual
    "clear_session",      # Limpar histórico da sessão
    "ping",               # Health check do pipeline
}


def is_system_intent(request: ChatRequest) -> bool:
    """Retorna True se a requisição é um intent de sistema."""
    return request.intent_type == "system_intent"


async def handle_system_intent(request: ChatRequest, supabase) -> dict:
    """Processa system intents sem passar pelo pipeline LLM.

    Retorna um dict que será serializado como evento NDJSON único.
    """
    command = request.chatInput.strip().lower()
    logger.info(f"System intent: {command} | session={request.sessionId}")

    if command == "ping":
        return {"type": "pong", "status": "ok"}

    if command == "get_starters":
        route = request.ui_context.current_page if request.ui_context else "/"
        starters = await _fetch_starters(supabase, route)
        return {"type": "starters", "items": starters, "route": route}

    if command == "clear_session":
        return {"type": "session_cleared", "sessionId": request.sessionId}

    # Comando desconhecido — responde sem erro
    logger.warning(f"System intent desconhecido: {command}")
    return {"type": "system_ack", "command": command}


async def _fetch_starters(supabase, route: str) -> list[str]:
    """Busca starters da tabela cloudinha_starters para a rota indicada."""
    try:
        response = (
            supabase.table("cloudinha_starters")
            .select("starters, intro_message")
            .eq("page_route", route)
            .eq("is_active", True)
            .order("route_priority", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            starters = response.data[0].get("starters", [])
            return starters if isinstance(starters, list) else []
        return []
    except Exception as e:
        logger.error(f"Erro ao buscar starters para {route}: {e}")
        return []
