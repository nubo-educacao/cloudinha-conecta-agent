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
    "page_context",
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

    if command == "page_context":
        route = request.ui_context.current_page if request.ui_context else "/"
        page_data = request.ui_context.page_data if request.ui_context else {}
        return await _handle_page_context(supabase, route, page_data)

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


async def _handle_page_context(supabase, route: str, page_data: dict) -> dict:
    """Gera mensagem contextual da Cloudinha baseada na rota atual.

    Retorna dict com:
      - type: "system_message"
      - content: str (mensagem em markdown)
      - open_drawer: bool (True se deve abrir o drawer)
    """

    # Rota de oportunidade de parceiro
    if "/partner-opportunities/" in route:
        opp_id = page_data.get("opportunity_id") or route.split("/")[-1]
        content = await _get_opportunity_message(supabase, opp_id, is_partner=True)
        return {
            "type": "system_message",
            "content": content,
            "open_drawer": True,
        }

    # Rota de oportunidade MEC (Sisu/Prouni)
    if "/opportunities/" in route:
        opp_id = page_data.get("opportunity_id") or route.split("/")[-1]
        content = await _get_opportunity_message(supabase, opp_id, is_partner=False)
        return {
            "type": "system_message",
            "content": content,
            "open_drawer": True,
        }

    # Rota desconhecida → não interromper o usuário
    logger.info(f"page_context: rota sem handler específico: {route}")
    return {"type": "system_ack", "command": "page_context", "open_drawer": False}


async def _get_opportunity_message(supabase, opp_id: str, is_partner: bool) -> str:
    """Busca dados básicos da oportunidade e monta mensagem contextual."""
    try:
        if is_partner:
            resp = (
                supabase.table("partner_opportunities")
                .select("title, description, partner_institutions(institutions(name))")
                .eq("id", opp_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                opp = resp.data[0]
                title = opp.get("title", "esta oportunidade")
                inst = (
                    opp.get("partner_institutions", {})
                    .get("institutions", {})
                    .get("name", "esta instituição")
                )
                return (
                    f"Olá! Vejo que você está explorando **{title}** em {inst}. 🎓\n\n"
                    f"Posso te ajudar a entender os requisitos, prazos ou como se candidatar. "
                    f"O que você gostaria de saber?"
                )
        else:
            # Oportunidade MEC — buscar na view unificada
            resp = (
                supabase.table("v_unified_opportunities")
                .select("course_name, institution_name, modality")
                .eq("id", opp_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                opp = resp.data[0]
                course = opp.get("course_name", "este curso")
                inst = opp.get("institution_name", "esta instituição")
                modality = opp.get("modality", "")
                return (
                    f"Você está vendo **{course}** em {inst}! ✨\n\n"
                    f"Posso te contar sobre as notas de corte, critérios de elegibilidade "
                    f"ou como funciona o processo. Tem alguma dúvida?"
                )
    except Exception as e:
        logger.error(f"Erro ao buscar dados de oportunidade {opp_id}: {e}")

    return (
        "Olá! Estou por aqui caso queira tirar dúvidas sobre esta oportunidade. "
        "É só me chamar! 😊"
    )
