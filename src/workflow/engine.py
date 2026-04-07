"""Orquestrador do pipeline Planning → Reasoning → Response.

Implementa o padrão de Resiliência V0: retry manual com asyncio.sleep backoff exponencial,
log de erros na tabela agent_errors, e fallbacks empáticos em pt-BR.
"""
import asyncio
import json
import logging
import time
import traceback
from typing import AsyncGenerator

from supabase import Client

from src.agents.planning import run_planning_agent
from src.agents.reasoning import run_reasoning_agent
from src.agents.response import run_response_agent
from src.contracts.reasoning_report import parse_reasoning_report, extract_suggestions
from src.contracts.structured_plan import FALLBACK_PLAN, StructuredPlan
from src.models.chat_events import ErrorEvent, SuggestionsEvent, TextEvent
from src.models.chat_request import ChatRequest
from src.services.context_service import build_lean_context
from src.services.retrieval_service import retrieve_few_shot_examples
from src.services.session_service import SupabaseSessionService
from src.config import settings
from src.services.supabase_client import get_supabase_service

logger = logging.getLogger(__name__)

MAX_PIPELINE_RETRIES = 3

# ─── Mensagens de fallback ────────────────────────────────────────────────────
MSG_PLANNING_FAIL = "Desculpe, tive dificuldade em entender sua pergunta. Pode reformular?"
MSG_REASONING_FAIL = "Desculpe, não consegui processar sua pergunta. Pode reformular?"
MSG_RESPONSE_FAIL = "Estou com dificuldades de conexão. Tente novamente em alguns instantes."
MSG_TIMEOUT = "Estou com dificuldades de conexão ou limite de uso excedido. Tente novamente em alguns minutos."
MSG_FINAL_FALLBACK = "Desculpe, não consegui processar."


async def run_pipeline(
    request: ChatRequest,
    supabase_anon: Client,
) -> AsyncGenerator[dict, None]:
    """Pipeline principal Planning→Reasoning→Response.

    Emite eventos NDJSON (dicts) em ordem:
      1. tool_start / tool_end  (durante Reasoning)
      2. text chunks            (durante Response streaming)
      3. suggestions            (após Response)
    """
    supabase_service = get_supabase_service()
    session_svc = SupabaseSessionService(
        supabase=supabase_anon,
        user_id=str(request.userId),
        session_id=request.sessionId,
    )

    # Carregar dados de contexto
    profile_data = await _load_profile(supabase_anon, str(request.active_profile_id))
    recent_messages = session_svc.get_recent_messages(limit=5)

    lean_context = build_lean_context(
        user_id=str(request.userId),
        active_profile_id=str(request.active_profile_id),
        full_name=profile_data.get("full_name", ""),
        age=profile_data.get("age"),
        cognitive_memory=profile_data.get("cognitive_memory"),
        recent_messages=recent_messages,
        ui_context=request.ui_context,
    )

    # Persistir mensagem do usuário
    session_svc.persist_user_message(request.chatInput)

    has_sent_events = False
    full_response_text = ""
    start_ts = time.time()

    for attempt in range(MAX_PIPELINE_RETRIES):
        try:
            async for event in _execute_pipeline(
                request=request,
                lean_context=lean_context,
                supabase_anon=supabase_anon,
                supabase_service=supabase_service,
                mcp_url=settings.MCP_SERVER_URL,
            ):
                has_sent_events = True
                if event.get("type") == "text":
                    full_response_text += event.get("content", "")
                yield event

            # Pipeline completo — persistir resposta do agente
            if full_response_text:
                session_svc.persist_agent_message(full_response_text)

            # Registrar telemetria
            _log_agent_turn(
                supabase=supabase_service,
                request=request,
                total_latency_ms=int((time.time() - start_ts) * 1000),
            )
            return  # Sucesso — não retentamos

        except TimeoutError:
            logger.warning(f"Pipeline timeout (tentativa {attempt + 1}/{MAX_PIPELINE_RETRIES})")
            if attempt < MAX_PIPELINE_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            yield ErrorEvent(message=MSG_TIMEOUT).model_dump()
            _log_tool_error(
                supabase_service, str(request.userId), request.sessionId,
                "pipeline", MSG_TIMEOUT, error_type="server_stream_error",
            )
            return

        except Exception as e:
            logger.error(f"Pipeline error (tentativa {attempt + 1}): {e}")
            if attempt < MAX_PIPELINE_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            _log_tool_error(
                supabase_service, str(request.userId), request.sessionId,
                "pipeline", str(e), stack_trace=traceback.format_exc(),
                error_type="server_stream_error",
            )
            yield ErrorEvent(message=MSG_RESPONSE_FAIL).model_dump()
            return

    # Fallback final: nenhum evento emitido
    if not has_sent_events and not full_response_text:
        yield TextEvent(content=MSG_FINAL_FALLBACK).model_dump()


async def _execute_pipeline(
    request: ChatRequest,
    lean_context: str,
    supabase_anon: Client,
    supabase_service: Client,
    mcp_url: str = "",
) -> AsyncGenerator[dict, None]:
    """Execução single-attempt do pipeline. Levanta exceções para o retry wrapper tratar."""

    # ── Fase 1: Planning ──────────────────────────────────────────────────────
    try:
        plan = await run_planning_agent(
            user_message=request.chatInput,
            lean_context=lean_context,
        )
    except Exception as e:
        logger.error(f"Planning agent error: {e}")
        _log_tool_error(
            supabase_service, str(request.userId), request.sessionId,
            "planning_agent", str(e), stack_trace=traceback.format_exc(),
            error_type="planning_agent_error",
        )
        plan = FALLBACK_PLAN

    # ── Fase 2: Few-Shot Retrieval ─────────────────────────────────────────────
    few_shot = await retrieve_few_shot_examples(
        supabase=supabase_anon,
        query=request.chatInput,
        intent_category=plan.intent_category,
    )

    # ── Fase 3: Reasoning (MCP-Native, com streaming de tool events) ─────────
    reasoning_text = ""
    try:
        async for event in run_reasoning_agent(
            plan=plan,
            lean_context=lean_context,
            few_shot_examples=few_shot,
            mcp_url=mcp_url,
        ):
            if event.get("type") == "reasoning_complete":
                reasoning_text = event.get("report", "")
            elif event.get("type") == "reasoning_error":
                # MCP connection error — propaga como ErrorEvent
                raise RuntimeError(f"MCP error: {event.get('error')}")
            else:
                # tool_start / tool_end — emitir AGORA (antes do Response)
                yield event

    except Exception as e:
        logger.error(f"Reasoning agent error: {e}")
        _log_tool_error(
            supabase_service, str(request.userId), request.sessionId,
            "reasoning_agent", str(e), stack_trace=traceback.format_exc(),
            error_type="reasoning_agent_error",
        )
        yield ErrorEvent(message=MSG_REASONING_FAIL).model_dump()
        return

    if not reasoning_text:
        yield ErrorEvent(message=MSG_REASONING_FAIL).model_dump()
        _log_tool_error(
            supabase_service, str(request.userId), request.sessionId,
            "reasoning_agent", "Reasoning retornou texto vazio",
            error_type="reasoning_agent_error",
        )
        return

    # Extrair suggestions ANTES do Response streaming
    suggestions = extract_suggestions(reasoning_text)

    # Parse do relatório
    try:
        report = parse_reasoning_report(reasoning_text)
    except Exception as e:
        logger.error(f"Reasoning report parse error: {e}")
        report = None  # Response agent receberá fallback

    # ── Fase 4: Response streaming ─────────────────────────────────────────────
    try:
        async for text_chunk in run_response_agent(
            reasoning_report=report,
            lean_context=lean_context,
            user_message=request.chatInput,
        ):
            yield TextEvent(content=text_chunk).model_dump()
    except Exception as e:
        logger.error(f"Response agent error: {e}")
        _log_tool_error(
            supabase_service, str(request.userId), request.sessionId,
            "response_agent", str(e), stack_trace=traceback.format_exc(),
            error_type="response_agent_error",
        )
        yield ErrorEvent(message=MSG_RESPONSE_FAIL).model_dump()
        return

    # ── Fase 5: Suggestions (após response completo) ───────────────────────────
    if suggestions:
        yield SuggestionsEvent(items=suggestions[:3]).model_dump()


async def _load_profile(supabase: Client, profile_id: str) -> dict:
    """Carrega dados mínimos do perfil para o contexto."""
    try:
        profile = (
            supabase.table("user_profiles")
            .select("full_name, birth_date")
            .eq("id", profile_id)
            .single()
            .execute()
        )
        meta = (
            supabase.table("users_metadata")
            .select("cognitive_memory")
            .eq("profile_id", profile_id)
            .maybeSingle()
            .execute()
        )
        data = profile.data or {}
        if meta.data:
            data["cognitive_memory"] = meta.data.get("cognitive_memory")

        # Calcular idade a partir de birth_date
        if data.get("birth_date"):
            import datetime
            bd = datetime.date.fromisoformat(data["birth_date"])
            today = datetime.date.today()
            data["age"] = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))

        return data
    except Exception as e:
        logger.warning(f"Não foi possível carregar perfil {profile_id}: {e}")
        return {}


def _log_tool_error(
    supabase_client,
    user_id: str,
    session_id: str,
    tool_name: str,
    error_msg: str,
    stack_trace: str | None = None,
    args: dict | None = None,
    raw_output: str | None = None,
    error_type: str = "tool_error",
) -> None:
    """Persiste erros de tools/agents na tabela agent_errors para debugging."""
    try:
        supabase_client.table("agent_errors").insert({
            "user_id": user_id,
            "session_id": session_id,
            "error_type": error_type,
            "error_message": error_msg,
            "stack_trace": stack_trace,
            "metadata": {
                "tool_name": tool_name,
                "args": args,
                "raw_output": raw_output,
            },
        }).execute()
    except Exception as e:
        logging.error(f"Falha ao persistir erro no agent_errors: {e}")


def _log_agent_turn(
    supabase: Client,
    request: ChatRequest,
    total_latency_ms: int,
) -> None:
    """Registra telemetria do turno na tabela agent_turns."""
    try:
        supabase.table("agent_turns").insert({
            "user_id": str(request.userId),
            "session_id": request.sessionId,
            "total_latency_ms": total_latency_ms,
            "action": "none",
        }).execute()
    except Exception as e:
        logger.warning(f"Falha ao registrar agent_turn: {e}")
