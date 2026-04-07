"""Reasoning Agent — MCP-Native.

Atua como MCP Client: lista tools do nubo-tools MCP Server,
converte para GenAI FunctionDeclarations, e executa o loop de tool-calling.

Nenhuma lógica de SQL ou Supabase aqui — toda a lógica de dados fica no MCP Server.
"""
import logging
from typing import AsyncGenerator

from google import genai
from google.genai import types

from src.config import settings
from src.contracts.structured_plan import StructuredPlan
from src.mcp.client import get_mcp_session, list_genai_tools, call_mcp_tool
from src.models.chat_events import ToolStartEvent, ToolEndEvent

logger = logging.getLogger(__name__)

REASONING_SYSTEM_PROMPT = """Você é o Reasoning Agent da Cloudinha — assistente educacional do Nubo Conecta.

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
) -> AsyncGenerator[dict, None]:
    """Executa o Reasoning Agent via MCP Client.

    Conecta ao nubo-tools MCP Server, converte as tools para GenAI FunctionDeclarations,
    e executa o loop de tool-calling com streaming de eventos UX.

    Emite:
      - ToolStartEvent antes de cada chamada de tool
      - ToolEndEvent após cada chamada de tool
      - {"type": "reasoning_complete", "report": <markdown>} ao final

    Args:
        plan: Plano estruturado do Planning Agent
        lean_context: Contexto do usuário montado pelo context_service
        few_shot_examples: Exemplos de tom/estilo da retrieval_service
        mcp_url: URL do MCP Server (usa settings.MCP_SERVER_URL se None)
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    url = mcp_url or settings.MCP_SERVER_URL
    prompt = _build_reasoning_prompt(plan, lean_context, few_shot_examples)

    try:
        async with get_mcp_session(url) as mcp_session:
            genai_tools = await list_genai_tools(mcp_session)

            config = types.GenerateContentConfig(
                system_instruction=REASONING_SYSTEM_PROMPT,
                tools=genai_tools if genai_tools else None,
                temperature=0.2,
                max_output_tokens=2048,
            )

            contents: list = [{"role": "user", "parts": [{"text": prompt}]}]
            captured_text = ""
            max_turns = 5

            for turn in range(max_turns):
                response = await client.aio.models.generate_content(
                    model=settings.REASONING_MODEL,
                    contents=contents,
                    config=config,
                )

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

                        # Emitir tool_start ANTES de chamar (UX badge "pesquisando...")
                        yield ToolStartEvent(tool=fn_name, args=fn_args).model_dump()

                        # Executar via MCP — zero SQL aqui
                        tool_result = await call_mcp_tool(mcp_session, fn_name, fn_args)

                        # Emitir tool_end com output
                        import json
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

    except Exception as e:
        logger.error(f"Reasoning Agent erro MCP: {e}")
        # Sinaliza erro para o engine tratar com fallback
        yield {"type": "reasoning_error", "error": str(e)}
        return

    yield {"type": "reasoning_complete", "report": captured_text}


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
