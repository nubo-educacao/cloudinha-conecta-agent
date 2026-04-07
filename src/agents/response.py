import logging
from typing import AsyncGenerator
from google import genai
from google.genai import types

from src.config import settings
from src.contracts.reasoning_report import ReasoningReport

logger = logging.getLogger(__name__)

RESPONSE_SYSTEM_PROMPT = """Você é a Cloudinha, assistente educacional empática do Nubo Conecta.

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
) -> AsyncGenerator[str, None]:
    """Executa o Response Agent e faz streaming da resposta final.

    Emite chunks de texto puro (str) para o engine montar os TextEvents.
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)

    prompt = _build_response_prompt(reasoning_report, lean_context, user_message)

    async for chunk in await client.aio.models.generate_content_stream(
        model=settings.RESPONSE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=RESPONSE_SYSTEM_PROMPT,
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
