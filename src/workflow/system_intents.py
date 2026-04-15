"""Interceptor de System Intents.

System intents são comandos internos enviados pelo frontend com intent_type='system_intent'.

Dois tipos:
  - Intents leves (ping, clear_session, get_starters): processados localmente, sem LLM.
  - Intents contextuais (page_context): resolvidos contra a tabela system_intents,
    montam uma trigger_message e sinalizam ao main.py para rodar o pipeline LLM completo.
    A Cloudinha gera uma resposta real — NÃO é uma mensagem fake hardcoded.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
import httpx

from src.models.chat_request import ChatRequest

logger = logging.getLogger(__name__)

# Intents que BYPASSA o pipeline LLM (processados localmente)
LIGHTWEIGHT_COMMANDS = {"get_starters", "clear_session", "ping"}


@dataclass
class PipelineIntent:
    """Sinaliza que este system intent deve ir pelo pipeline LLM.

    O main.py substitui o chatInput pela trigger_message e roda run_pipeline.
    Os metadados (open_drawer, delay_ms) são emitidos como evento final.
    """
    trigger_message: str
    open_drawer: bool = False
    delay_ms: int = 0


def is_system_intent(request: ChatRequest) -> bool:
    """Retorna True se a requisição é um intent de sistema."""
    return request.intent_type == "system_intent"


async def handle_system_intent(request: ChatRequest, supabase) -> dict | PipelineIntent:
    """Processa system intents.

    Retorna:
      - dict: resposta direta (ping, starters, etc.)
      - PipelineIntent: sinaliza que deve rodar o pipeline LLM com a trigger_message
    """
    command = request.chatInput.strip().lower()
    logger.info(f"System intent: {command} | session={request.sessionId}")

    # ── Intents leves (sem LLM) ───────────────────────────────────────────────
    if command == "ping":
        return {"type": "pong", "status": "ok"}

    if command == "get_starters":
        route = request.ui_context.current_page if request.ui_context else "/"
        starters = await _fetch_starters(supabase, route)
        return {"type": "starters", "items": starters, "route": route}

    if command == "clear_session":
        return {"type": "session_cleared", "sessionId": request.sessionId}

    # ── Intents contextuais (vão pro pipeline LLM) ────────────────────────────
    if command == "page_context":
        route = request.ui_context.current_page if request.ui_context else "/"
        page_data = request.ui_context.page_data if request.ui_context else {}
        return await _resolve_page_context(supabase, route, page_data)

    # Comando desconhecido
    logger.warning(f"System intent desconhecido: {command}")
    return {"type": "system_ack", "command": command}


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=4),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.ProtocolError, httpx.RemoteProtocolError, Exception)),
    reraise=True
)
async def _resolve_page_context(supabase, route: str, page_data: dict) -> dict | PipelineIntent:
    """Busca config na tabela system_intents para a rota atual.

    Se encontra um intent ativo com trigger_route que faz match com a rota:
      - Preenche placeholders na trigger_message
      - Retorna PipelineIntent para que o main.py rode o pipeline LLM

    Se não encontra match: retorna system_ack silencioso.
    """
    try:
        resp = (
            supabase.table("system_intents")
            .select("trigger_route, trigger_message, open_drawer, delay_ms")
            .eq("command", "page_context")
            .eq("is_active", True)
            .execute()
        )

        if not resp.data:
            logger.info(f"page_context: nenhum intent ativo para command=page_context")
            return {"type": "system_ack", "command": "page_context", "open_drawer": False}

        # Tentar match de cada trigger_route contra a rota atual
        for intent_config in resp.data:
            pattern = intent_config.get("trigger_route")
            if not pattern:
                continue
            try:
                if re.match(pattern, route):
                    logger.info(f"page_context: match '{pattern}' para rota '{route}'")

                    # Resolver placeholders na trigger_message
                    trigger_msg = intent_config.get("trigger_message") or ""
                    trigger_msg = await _fill_placeholders(
                        supabase, trigger_msg, route, page_data
                    )

                    return PipelineIntent(
                        trigger_message=trigger_msg,
                        open_drawer=intent_config.get("open_drawer", False),
                        delay_ms=intent_config.get("delay_ms", 0),
                    )
            except re.error as e:
                logger.error(f"Regex inválida no system_intents: '{pattern}' — {e}")

        # Nenhuma rota fez match
        logger.info(f"page_context: nenhum trigger_route fez match com '{route}'")
        return {"type": "system_ack", "command": "page_context", "open_drawer": False}

    except Exception as e:
        logger.error(f"Erro ao buscar system_intents para page_context: {e}")
        return {"type": "system_ack", "command": "page_context", "open_drawer": False}


async def _fill_placeholders(supabase, template: str, route: str, page_data: dict) -> str:
    """Preenche {{placeholders}} na trigger_message com dados reais.

    Placeholders suportados:
      - {{title}}: título da oportunidade
      - {{institution}}: nome da instituição
      - {{route}}: rota atual
    """
    if not template:
        return f"O usuário está na página {route}."

    template = template.replace("{{route}}", route)

    # Se tem placeholders de oportunidade, buscar dados
    if "{{title}}" in template or "{{institution}}" in template:
        # Limpar a rota para evitar barras no final que quebram o split
        clean_route = route.strip("/")
        opp_id = page_data.get("opportunity_id") or (clean_route.split("/")[-1] if "/" in clean_route else clean_route)
        
        logger.info(f"Iniciando preenchimento de placeholders. Route: {route} | ID extraído: {opp_id}")
        opp_data = await _fetch_opportunity_data(supabase, opp_id)
        template = template.replace("{{title}}", opp_data.get("title", "esta oportunidade"))
        template = template.replace("{{institution}}", opp_data.get("institution", "esta instituição"))

    return template


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=4),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((httpx.ProtocolError, httpx.RemoteProtocolError, Exception)),
    reraise=True
)
async def _fetch_opportunity_data(supabase, opp_id: str) -> dict:
    """Busca dados básicos da oportunidade pelo unified_id."""
    try:
        logger.info(f"Buscando v_unified_opportunities para unified_id='{opp_id}'")
        resp = (
            supabase.table("v_unified_opportunities")
            .select("title, provider_name")
            .eq("unified_id", opp_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            opp = resp.data[0]
            logger.info(f"Oportunidade encontrada: {opp.get('title')}")
            return {
                "title": opp.get("title", "esta oportunidade"),
                "institution": opp.get("provider_name", "esta instituição"),
            }
        
        logger.warning(f"Oportunidade {opp_id} NÃO encontrada na view v_unified_opportunities")

        # Fallback: se não achou na view (ou ID puro), tenta partner_opportunities
        # Remove prefixo se existir para busca direta na tabela
        pure_uuid = opp_id.split("_")[-1] if "_" in opp_id else opp_id
        
        resp = (
            supabase.table("partner_opportunities")
            .select("title, partner_institutions(institutions(name))")
            .eq("id", pure_uuid)
            .limit(1)
            .execute()
        )
        if resp.data:
            opp = resp.data[0]
            # Supabase joins retornam listas ou objetos dependendo da config, tratamos ambos
            p_inst = opp.get("partner_institutions")
            if isinstance(p_inst, list) and len(p_inst) > 0:
                p_inst = p_inst[0]
            
            inst_data = p_inst.get("institutions") if p_inst else {}
            if isinstance(inst_data, list) and len(inst_data) > 0:
                inst_data = inst_data[0]
                
            inst_name = inst_data.get("name", "esta instituição") if inst_data else "esta instituição"
            
            return {
                "title": opp.get("title", "esta oportunidade"),
                "institution": inst_name,
            }
    except Exception as e:
        logger.error(f"Erro ao buscar dados de oportunidade {opp_id}: {e}")

    return {"title": "esta oportunidade", "institution": "esta instituição"}


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
