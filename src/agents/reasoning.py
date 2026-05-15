"""Reasoning Agent — MCP-Native.

Atua como MCP Client: lista tools do nubo-tools MCP Server,
converte para GenAI FunctionDeclarations, e executa o loop de tool-calling.

Nenhuma lógica de SQL ou Supabase aqui — toda a lógica de dados fica no MCP Server.
Dados do usuário (perfil, match) são injetados pelo engine, não buscados via MCP.
"""
import asyncio
import json
import logging
import time
from typing import AsyncGenerator

from google import genai
from google.genai import types

from src.config import settings
from src.contracts.agent_result import AgentResult
from src.contracts.structured_plan import StructuredPlan
from src.mcp.client import get_mcp_session, list_genai_tools, call_mcp_tool
from src.mcp.in_process import list_genai_tools_in_process, call_mcp_tool_in_process
from src.models.chat_events import ToolStartEvent, ToolEndEvent

logger = logging.getLogger(__name__)

# Fallback usado apenas quando o banco (agent_prompts) está indisponível
_REASONING_FALLBACK_PROMPT = """Você é o Reasoning Agent da Cloudinha — assistente educacional do Nubo Conecta.

Sua função é COLETAR DADOS via tools e RACIOCINAR sobre a pergunta do usuário.
Você NÃO gera a resposta final — apenas o relatório de raciocínio para o Response Agent.

SEMPRE use as tools disponíveis antes de raciocinar quando o plano indicar dados externos.

Produza ao final (após usar todas as tools necessárias) APENAS o markdown:

## INTENT
<intenção identificada>

## DATA
<dados coletados das tools, formatados de forma clara>

## REASONING
<seu raciocínio sobre como responder a pergunta com base nos dados>

## ACTION
<ação recomendada: none | show_opportunities | show_profile | navigate>

## SUGGESTED_FOLLOWUPS
- <pergunta de acompanhamento 1>
- <pergunta de acompanhamento 2>
- <pergunta de acompanhamento 3>"""


async def run_reasoning_agent(
    plan: StructuredPlan,
    lean_context: str,
    few_shot_examples: str,
    mcp_url: str | None = None,
    system_prompt: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Executa o Reasoning Agent via MCP Client.

    Conecta ao nubo-tools MCP Server (via SSE ou in-process se localhost),
    converte as tools para GenAI FunctionDeclarations, e executa o loop de
    tool-calling com streaming de eventos UX.

    Emite:
      - ToolStartEvent antes de cada chamada de tool
      - ToolEndEvent após cada chamada de tool
      - {"type": "tool_error", ...} quando tool retorna erro (consumido pelo engine)
      - {"type": "tool_empty_result", ...} quando tool retorna vazio (consumido pelo engine)
      - {"type": "reasoning_complete", "report": <markdown>, "result": AgentResult} ao final

    Args:
        plan: Plano estruturado do Planning Agent
        lean_context: Contexto do usuário montado pelo context_service
        few_shot_examples: Exemplos de tom/estilo da retrieval_service
        mcp_url: URL do MCP Server (usa settings.MCP_SERVER_URL se None)
        system_prompt: System instruction dinâmica do banco. Se None, usa fallback.
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    url = mcp_url or settings.MCP_SERVER_URL
    instruction = system_prompt or _REASONING_FALLBACK_PROMPT
    prompt = _build_reasoning_prompt(plan, lean_context, few_shot_examples)

    # Detectar se a URL aponta para localhost — usar in-process para evitar loopback HTTP
    _use_in_process = "localhost" in url or "127.0.0.1" in url

    t0 = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    all_tools_used: list[dict] = []
    captured_text = ""

    try:
        # ── Listar tools ──────────────────────────────────────────────────────
        if _use_in_process:
            logger.info(f"[Reasoning] Usando in-process MCP (URL={url})")
            genai_tools = await list_genai_tools_in_process()
        else:
            logger.info(f"[Reasoning] Usando SSE MCP (URL={url})")

        # ── Executar loop de tool-calling ─────────────────────────────────────
        async def _do_loop(call_tool_fn) -> AsyncGenerator[dict, None]:
            nonlocal total_input_tokens, total_output_tokens, captured_text

            config = types.GenerateContentConfig(
                system_instruction=instruction,
                tools=genai_tools if genai_tools else None,
                temperature=0.2,
                max_output_tokens=2048,
            )
            contents: list = [{"role": "user", "parts": [{"text": prompt}]}]
            max_turns = 20

            async def _generate_with_retry(contents_snap):
                last_exc = None
                for attempt in range(3):
                    try:
                        return await client.aio.models.generate_content(
                            model=settings.REASONING_MODEL,
                            contents=contents_snap,
                            config=config,
                        )
                    except Exception as exc:
                        err_str = str(exc).lower()
                        if "429" in err_str or "quota" in err_str or "rate" in err_str:
                            wait = 2 ** attempt
                            logger.warning(f"Gemini 429 — aguardando {wait}s antes de retry {attempt+1}/3")
                            await asyncio.sleep(wait)
                            last_exc = exc
                        else:
                            raise
                raise last_exc

            for _turn in range(max_turns):
                response = await _generate_with_retry(contents)

                if response.usage_metadata:
                    total_input_tokens += response.usage_metadata.prompt_token_count or 0
                    total_output_tokens += response.usage_metadata.candidates_token_count or 0

                if not response.candidates:
                    break

                candidate = response.candidates[0]
                has_function_call = False
                function_responses: list[types.Part] = []

                for part in candidate.content.parts:
                    if part.function_call:
                        has_function_call = True
                        fn_name = part.function_call.name
                        fn_args = dict(part.function_call.args) if part.function_call.args else {}

                        all_tools_used.append({"name": fn_name, "args": fn_args})
                        yield ToolStartEvent(tool=fn_name, args=fn_args).model_dump()

                        tool_result = await call_tool_fn(fn_name, fn_args)

                        # Telemetria: erros e resultados vazios de tools
                        if "error" in tool_result:
                            logger.warning(
                                f"[tool_error] tool={fn_name} args={fn_args} error={tool_result['error']}"
                            )
                            yield {"type": "tool_error", "tool": fn_name, "args": fn_args, "error": tool_result["error"]}
                        elif (
                            tool_result.get("result") == ""
                            or (tool_result.get("results") == [] and tool_result.get("count") == 0)
                        ):
                            logger.warning(f"[tool_empty_result] tool={fn_name} args={fn_args}")
                            yield {"type": "tool_empty_result", "tool": fn_name, "args": fn_args}

                        yield ToolEndEvent(
                            tool=fn_name,
                            output=json.dumps(tool_result, ensure_ascii=False),
                        ).model_dump()

                        function_responses.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=fn_name,
                                    response=tool_result,
                                )
                            )
                        )

                    elif part.text:
                        captured_text += part.text

                if has_function_call:
                    contents.append({"role": "model", "parts": candidate.content.parts})
                    contents.append({"role": "user", "parts": function_responses})
                else:
                    break

        if _use_in_process:
            async for ev in _do_loop(call_mcp_tool_in_process):
                yield ev
        else:
            async with get_mcp_session(url) as mcp_session:
                genai_tools = await list_genai_tools(mcp_session)

                async def _sse_call_tool(name: str, args: dict) -> dict:
                    return await call_mcp_tool(mcp_session, name, args)

                async for ev in _do_loop(_sse_call_tool):
                    yield ev

    except Exception as e:
        # Unwrap ExceptionGroup (anyio/asyncio TaskGroup) para expor a sub-exceção real
        real_error = e
        if isinstance(e, ExceptionGroup):
            logger.error(
                f"Reasoning Agent ExceptionGroup ({len(e.exceptions)} sub-exceção(es)):"
            )
            for i, sub_exc in enumerate(e.exceptions, 1):
                logger.error(f"  [{i}] {type(sub_exc).__name__}: {sub_exc}")
            real_error = e.exceptions[0]
        elif hasattr(e, '__cause__') and e.__cause__:
            real_error = e.__cause__

        err_str = str(real_error).lower()
        if "429" in err_str or "quota" in err_str or "rate" in err_str:
            logger.warning(f"Reasoning Agent: Gemini rate limit atingido")
            yield {
                "type": "text",
                "content": "⚠️ Estou recebendo muitas perguntas ao mesmo tempo. Aguarde alguns segundos e tente novamente!",
            }
        else:
            logger.error(f"Reasoning Agent erro: {type(real_error).__name__}: {real_error}")
            yield {"type": "reasoning_error", "error": f"{type(real_error).__name__}: {real_error}"}
        return

    latency_ms = int((time.time() - t0) * 1000)
    reasoning_result = AgentResult(
        text=captured_text,
        latency_ms=latency_ms,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        tools_used=all_tools_used,
    )
    logger.info(
        f"[Reasoning] tools={len(all_tools_used)} latency={latency_ms}ms "
        f"tokens_in={total_input_tokens} tokens_out={total_output_tokens}"
    )
    yield {"type": "reasoning_complete", "report": captured_text, "result": reasoning_result}


def _build_reasoning_prompt(
    plan: StructuredPlan,
    lean_context: str,
    few_shot_examples: str,
) -> str:
    parts = [lean_context, ""]
    parts.append(
        f"PLANO DE EXECUÇÃO:\nIntenção: {plan.intent}\nCategoria: {plan.intent_category}"
    )
    if plan.tools_to_use:
        tools_str = "\n".join(f"  - {t['raw']}" for t in plan.tools_to_use)
        parts.append(f"Tools a usar:\n{tools_str}")
    if plan.context_needed:
        parts.append(f"Contexto necessário: {plan.context_needed}")
    if few_shot_examples:
        parts.append(few_shot_examples)
    return "\n".join(parts)
