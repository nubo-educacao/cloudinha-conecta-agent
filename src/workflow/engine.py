"""Orquestrador do pipeline Planning → Reasoning → Response.

Implementa o padrão de Resiliência V1: retry manual com asyncio.sleep backoff exponencial,
log de erros na tabela agent_errors, fallbacks empáticos em pt-BR,
e resolução dinâmica de prompts via agent_prompts (Remote Config).
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
from src.contracts.agent_result import AgentResult
from src.contracts.reasoning_report import parse_reasoning_report, extract_suggestions
from src.contracts.structured_plan import FALLBACK_PLAN, StructuredPlan
from src.mcp.client import get_mcp_session, list_tools_summary
from src.models.chat_events import ErrorEvent, SuggestionsEvent, TextEvent
from src.models.chat_request import ChatRequest
from src.services.context_service import build_lean_context
from src.services.prompt_service import resolve_system_prompt
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
        supabase=supabase_service,
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

    # ── Resolver prompts dinâmicos (Remote Config) ────────────────────────────
    planning_prompt = resolve_system_prompt(supabase_service, "planning", fallback="")
    reasoning_prompt = resolve_system_prompt(supabase_service, "reasoning", fallback="")
    response_prompt = resolve_system_prompt(supabase_service, "response", fallback="")

    # Persistir mensagem de entrada
    if request.intent_type == "system_intent_pipeline":
        session_svc.persist_system_message(request.chatInput)
    else:
        session_svc.persist_user_message(request.chatInput)

    has_sent_events = False
    full_response_text = ""
    start_ts = time.time()

    _empty_result = AgentResult(text="", latency_ms=0)

    # Declarados fora do loop de retry para que o finally sempre log com os melhores dados disponíveis
    planning_result = _empty_result
    reasoning_result = _empty_result
    response_result = _empty_result
    intent_category = "general_qa"
    reasoning_report_text = ""
    action = "none"

    try:
        for attempt in range(MAX_PIPELINE_RETRIES):
            # Variáveis por tentativa (reset a cada retry)
            _pr = _empty_result
            _rr = _empty_result
            _resp = _empty_result
            _ic = "general_qa"
            _rrt = ""
            _act = "none"

            try:
                async for event in _execute_pipeline(
                    request=request,
                    lean_context=lean_context,
                    supabase_anon=supabase_anon,
                    supabase_service=supabase_service,
                    mcp_url=settings.MCP_SERVER_URL,
                    planning_prompt=planning_prompt or None,
                    reasoning_prompt=reasoning_prompt or None,
                    response_prompt=response_prompt or None,
                ):
                    has_sent_events = True
                    if event.get("type") == "_planning_done":
                        # Captura planning_result logo após Planning (antes do MCP/Reasoning)
                        _pr = event.get("planning_result", _empty_result)
                        continue
                    elif event.get("type") == "_telemetry":
                        # Internal event — captura reasoning/response, não encaminha ao cliente
                        _rr = event.get("reasoning_result", _empty_result)
                        _resp = event.get("response_result", _empty_result)
                        _ic = event.get("intent_category", "general_qa")
                        _rrt = event.get("reasoning_report", "")
                        _act = event.get("action", "none")
                        continue
                    elif event.get("type") == "text":
                        full_response_text += event.get("content", "")
                    yield event

                # Pipeline completo — salvar dados finais e persistir resposta
                planning_result = _pr
                reasoning_result = _rr
                response_result = _resp
                intent_category = _ic
                reasoning_report_text = _rrt
                action = _act

                if full_response_text:
                    session_svc.persist_agent_message(full_response_text)

                return  # Sucesso — finally roda a seguir

            except TimeoutError:
                planning_result = _pr  # preservar dados parciais para telemetria
                logger.warning(f"Pipeline timeout (tentativa {attempt + 1}/{MAX_PIPELINE_RETRIES})")
                if attempt < MAX_PIPELINE_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                yield ErrorEvent(message=MSG_TIMEOUT).model_dump()
                _log_tool_error(
                    supabase_service, str(request.userId), request.sessionId,
                    "pipeline", MSG_TIMEOUT, error_type="server_stream_error",
                )
                return  # finally roda a seguir

            except Exception as e:
                planning_result = _pr  # preservar dados parciais para telemetria
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
                return  # finally roda a seguir

        # Fallback final: nenhum evento emitido após todos os retries
        if not has_sent_events and not full_response_text:
            yield TextEvent(content=MSG_FINAL_FALLBACK).model_dump()

    finally:
        # Executado UMA vez — garante telemetria mesmo em falha parcial (BUG-S5-003)
        _log_agent_turn(
            supabase=supabase_service,
            request=request,
            total_latency_ms=int((time.time() - start_ts) * 1000),
            planning_result=planning_result,
            reasoning_result=reasoning_result,
            response_result=response_result,
            intent_category=intent_category,
            reasoning_report=reasoning_report_text,
            action=action,
        )


async def _execute_pipeline(
    request: ChatRequest,
    lean_context: str,
    supabase_anon: Client,
    supabase_service: Client,
    mcp_url: str = "",
    planning_prompt: str | None = None,
    reasoning_prompt: str | None = None,
    response_prompt: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Execução single-attempt do pipeline. Levanta exceções para o retry wrapper tratar."""

    _empty_result = AgentResult(text="", latency_ms=0)
    planning_result = _empty_result
    reasoning_result = _empty_result
    response_result = _empty_result

    # ── Fase 1: Planning (com descoberta dinâmica de tools via MCP) ───────────
    try:
        # Tenta injetar a lista dinâmica de tools do MCP no prompt do Planning
        dynamic_tools_summary = ""
        if mcp_url:
            try:
                async with get_mcp_session(mcp_url) as mcp_session:
                    dynamic_tools_summary = await list_tools_summary(mcp_session)
            except Exception as e:
                logger.warning(f"Falha ao obter lista dinâmica de tools no Planning: {e}")
                dynamic_tools_summary = "- MCP Offline (usando lista interna)"

        # Injetar no prompt (substituindo placeholder ou anexando)
        final_planning_prompt = planning_prompt or ""
        if "{{AVAILABLE_TOOLS}}" in final_planning_prompt:
            final_planning_prompt = final_planning_prompt.replace("{{AVAILABLE_TOOLS}}", dynamic_tools_summary)
        elif dynamic_tools_summary:
            final_planning_prompt += f"\n\nFerramentas disponíveis no sistema:\n{dynamic_tools_summary}"

        plan, planning_result = await run_planning_agent(
            user_message=request.chatInput,
            lean_context=lean_context,
            system_prompt=final_planning_prompt or None,
        )
    except Exception as e:
        logger.error(f"Planning agent error: {e}")
        _log_tool_error(
            supabase_service, str(request.userId), request.sessionId,
            "planning_agent", str(e), stack_trace=traceback.format_exc(),
            error_type="planning_agent_error",
        )
        plan = FALLBACK_PLAN

    # Emite planning_result ANTES do MCP/Reasoning — garante captura mesmo se Reasoning falhar
    yield {"type": "_planning_done", "planning_result": planning_result}

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
            system_prompt=reasoning_prompt,
        ):
            if event.get("type") == "reasoning_complete":
                reasoning_text = event.get("report", "")
                reasoning_result = event.get("result", _empty_result)
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
        async for text_chunk, agent_result in run_response_agent(
            reasoning_report=report,
            lean_context=lean_context,
            user_message=request.chatInput,
            system_prompt=response_prompt,
        ):
            if agent_result is not None:
                response_result = agent_result
            elif text_chunk:
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

    # ── Fase 6: Telemetria interna (capturada pelo run_pipeline) ──────────────
    action_str = report.action if report else "none"
    yield {
        "type": "_telemetry",
        "planning_result": planning_result,
        "reasoning_result": reasoning_result,
        "response_result": response_result,
        "intent_category": plan.intent_category,
        "reasoning_report": reasoning_text,
        "action": action_str,
    }


async def _load_profile(supabase: Client, profile_id: str) -> dict:
    """Carrega dados mínimos do perfil para o contexto."""
    try:
        profile = (
            supabase.table("user_profiles")
            .select("full_name, birth_date")
            .eq("id", profile_id)
            .execute()
        )
        meta = (
            supabase.table("users_metadata")
            .select("cognitive_memory")
            .eq("profile_id", profile_id)
            .limit(1)
            .execute()
        )
        data = profile.data[0] if profile.data else {}
        if meta.data:
            data["cognitive_memory"] = meta.data[0].get("cognitive_memory")

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


# Preços Gemini 2.0 Flash (https://ai.google.dev/pricing)
_COST_PER_M_INPUT  = 0.075  / 1_000_000   # USD por token input
_COST_PER_M_OUTPUT = 0.300  / 1_000_000   # USD por token output


def _estimate_cost(*results: AgentResult) -> float:
    """Calcula custo estimado em USD com base nos tokens consumidos."""
    total = sum(
        r.input_tokens * _COST_PER_M_INPUT + r.output_tokens * _COST_PER_M_OUTPUT
        for r in results
    )
    return round(total, 6)


def _log_agent_turn(
    supabase: Client,
    request: ChatRequest,
    total_latency_ms: int,
    planning_result: AgentResult | None = None,
    reasoning_result: AgentResult | None = None,
    response_result: AgentResult | None = None,
    intent_category: str = "general_qa",
    reasoning_report: str = "",
    action: str = "none",
) -> None:
    """Registra telemetria completa do turno na tabela agent_turns."""
    _empty = AgentResult(text="", latency_ms=0)
    pr = planning_result or _empty
    rr = reasoning_result or _empty
    resp = response_result or _empty

    try:
        supabase.table("agent_turns").insert({
            "user_id":              str(request.userId),
            "session_id":           request.sessionId,
            "total_latency_ms":     total_latency_ms,
            "planning_latency_ms":  pr.latency_ms,
            "reasoning_latency_ms": rr.latency_ms,
            "response_latency_ms":  resp.latency_ms,
            "input_tokens":         pr.input_tokens + rr.input_tokens + resp.input_tokens,
            "output_tokens":        pr.output_tokens + rr.output_tokens + resp.output_tokens,
            "tools_used":           rr.tools_used or [],
            "intent_category":      intent_category,
            "reasoning_report":     reasoning_report,
            "action":               action,
            "planning_output":      pr.text,
            "reasoning_output":     rr.text,
            "response_output":      resp.text,
            "estimated_cost_usd":   _estimate_cost(pr, rr, resp),
        }).execute()
    except Exception as e:
        logger.warning(f"Falha ao registrar agent_turn: {e}")
