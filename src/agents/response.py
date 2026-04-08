"""Response Agent — A Voz da Cloudinha.

Recebe o Reasoning Report e o contexto mínimo, formula a resposta empática
final em streaming. Zero tools. Grounded by design.

Sessão: SupabaseSessionService (histórico real do chat).
Modelo: gemini-2.0-flash.
"""
import logging
from typing import AsyncGenerator
from google import genai
from google.genai import types

from src.config import settings
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
) -> AsyncGenerator[str, None]:
    """Executa o Response Agent e faz streaming da resposta final.

    Emite chunks de texto puro (str) para o engine montar os TextEvents.

    Args:
        reasoning_report: Relatório parseado do Reasoning Agent
        lean_context: Contexto mínimo do usuário
        user_message: Mensagem original do usuário
        system_prompt: System instruction dinâmica do banco. Se None, usa fallback.
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    instruction = system_prompt or _RESPONSE_FALLBACK_PROMPT

    prompt = _build_response_prompt(reasoning_report, lean_context, user_message)

    async for chunk in await client.aio.models.generate_content_stream(
        model=settings.RESPONSE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.7,
            max_output_tokens=1024,
        ),
    ):
        if chunk.text:
            yield chunk.text


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
