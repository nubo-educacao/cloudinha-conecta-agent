"""Response Agent — A Voz da Cloudinha.

Recebe o Reasoning Report e o contexto mínimo, formula a resposta empática
final em streaming. Zero tools. Grounded by design.

Sessão: SupabaseSessionService (histórico real do chat).
Modelo: gemini-2.0-flash.
"""
import logging
import time
from typing import AsyncGenerator
from google import genai
from google.genai import types

from src.config import settings
from src.contracts.agent_result import AgentResult
from src.contracts.reasoning_report import ReasoningReport

logger = logging.getLogger(__name__)

# Fallback usado apenas quando o banco (agent_prompts) está indisponível
_RESPONSE_FALLBACK_PROMPT = """Você é a Cloudinha, assistente educacional empática do Nubo Conecta.

Sua função é entregar a RESPOSTA FINAL ao usuário em português brasileiro, de forma:
- Amigável e encorajadora (você fala com estudantes em busca de oportunidades)
- Clara e direta — sem jargões técnicos
- Baseada EXCLUSIVAMENTE nos dados do Relatório de Raciocínio fornecido
- Com formatação Markdown leve (negrito para termos importantes, listas quando útil)
- Máximo 3-4 parágrafos, a menos que seja uma lista longa de oportunidades

NÃO invente dados. NÃO mencione as tools que usou. NÃO exponha IDs ou stack traces.
Se os dados forem insuficientes, diga honestamente que não encontrou informações completas."""


async def run_response_agent(
    reasoning_report: ReasoningReport,
    lean_context: str,
    user_message: str,
    system_prompt: str | None = None,
) -> AsyncGenerator[tuple[str, AgentResult | None], None]:
    """Executa o Response Agent e faz streaming da resposta final.

    Yields (text_chunk, None) para cada chunk de texto, e por último ("", AgentResult).

    Args:
        reasoning_report: Relatório parseado do Reasoning Agent
        lean_context: Contexto mínimo do usuário
        user_message: Mensagem original do usuário
        system_prompt: System instruction dinâmica do banco. Se None, usa fallback.
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    instruction = system_prompt or _RESPONSE_FALLBACK_PROMPT

    prompt = _build_response_prompt(reasoning_report, lean_context, user_message)

    t0 = time.time()
    input_tokens = 0
    output_tokens = 0
    full_text = ""

    # google-genai ≥1.70.0: generate_content_stream é coroutine → await retorna o async iterable
    stream = await client.aio.models.generate_content_stream(
        model=settings.RESPONSE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.7,
            max_output_tokens=1024,
        ),
    )
    async for chunk in stream:
        if chunk.text:
            full_text += chunk.text
            yield chunk.text, None

        # usage_metadata só aparece no último chunk
        if chunk.usage_metadata:
            input_tokens = chunk.usage_metadata.prompt_token_count or 0
            output_tokens = chunk.usage_metadata.candidates_token_count or 0

    latency_ms = int((time.time() - t0) * 1000)
    result = AgentResult(
        text=full_text,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    logger.info(
        f"[Response] latency={latency_ms}ms "
        f"tokens_in={input_tokens} tokens_out={output_tokens}"
    )
    yield "", result


def _build_response_prompt(
    report: ReasoningReport,
    lean_context: str,
    user_message: str,
) -> str:
    parts = [
        lean_context,
        "",
        f"PERGUNTA DO USUÁRIO: {user_message}",
        "",
        "RELATÓRIO DE RACIOCÍNIO (use para fundamentar sua resposta):",
        f"Intenção: {report.intent}",
    ]
    if report.data:
        parts.append(f"Dados coletados:\n{report.data}")
    if report.reasoning:
        parts.append(f"Raciocínio:\n{report.reasoning}")

    return "\n".join(parts)
