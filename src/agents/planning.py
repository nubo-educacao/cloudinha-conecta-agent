"""Planning Agent — Classificador de Intenção.

Recebe contexto mínimo, classifica a intenção do usuário e emite um Structured Plan.
Zero tools, zero persona. Puro classificador e planejador.

Sessão: InMemorySessionService transient.
Modelo: gemini-2.0-flash-lite (rápido e barato).
"""
import logging
import time
from google import genai
from google.genai import types

from src.config import settings
from src.contracts.agent_result import AgentResult
from src.contracts.structured_plan import StructuredPlan, parse_structured_plan, FALLBACK_PLAN

logger = logging.getLogger(__name__)

# Fallback usado apenas quando o banco está indisponível
_PLANNING_FALLBACK_PROMPT = """Você é o Planning Agent da Cloudinha — assistente educacional do Nubo Conecta.

SUA MISSÃO: Classificar a intenção e definir as ferramentas para buscar dados.
DETERMINISMO: Produza APENAS os blocos Markdown abaixo. Proibido introduções, comentários ou mensagens diretas ao usuário.

## INTENT
<descrição técnica da intenção>

## INTENT_CATEGORY
<uma das categorias: course_search | eligibility_query | application_help | form_support | general_qa | system_intent | casual>

## TOOLS_TO_USE
- <lista de tools necessárias do MCP>
{{AVAILABLE_TOOLS}}

REGRA DE OURO [OBRIGATÓRIO]:
Se o contexto indicar que o usuário está visualizando uma oportunidade específica (ex: possui um ID como 'partner_...' ou 'mec_...'), você DEVE obrigatoriamente incluir a ferramenta 'search_opportunities' na lista de tools para que o Reasoning Agent possa extrair os detalhes técnicos (bolsas, requisitos, descrição).

## CONTEXT_NEEDED
<dados ausentes necessários, ou "nenhum">

Categorias:
- application_help: DÚVIDAS SOBRE OPORTUNIDADES (Ex: Fundação Estudar, Prouni, Sisu). SUCESSO = Usar 'search_opportunities'.
- course_search: Busca por novos cursos/vagas.
- eligibility_query: Dúvidas sobre quem pode participar.
- casual: Saudações e agradecimentos (aqui tools podem ser "- nenhuma").
"""


async def run_planning_agent(
    user_message: str,
    lean_context: str,
    system_prompt: str | None = None,
) -> tuple[StructuredPlan, AgentResult]:
    """Executa o Planning Agent para classificar intenção e definir plano.

    Usa gemini-2.0-flash-lite (leve e rápido). Sessão InMemory transient.
    Retry manual: 1 retry com prompt corretivo se parse falhar.

    Args:
        user_message: Mensagem do usuário
        lean_context: Contexto mínimo montado pelo context_service
        system_prompt: System instruction dinâmica do banco. Se None, usa fallback.
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    prompt = f"{lean_context}\n\nMENSAGEM DO USUÁRIO: {user_message}"
    instruction = system_prompt or _PLANNING_FALLBACK_PROMPT

    raw, result = await _call_planning(client, prompt, instruction)
    try:
        plan = parse_structured_plan(raw)
        logger.info(
            f"[Planning] latency={result.latency_ms}ms "
            f"tokens_in={result.input_tokens} tokens_out={result.output_tokens}"
        )
        return plan, result
    except ValueError as e:
        logger.warning(f"Planning parse error (tentativa 1): {e}. Tentando com prompt corretivo.")

    # Retry com prompt corretivo
    corrective_prompt = (
        f"{prompt}\n\n"
        "ATENÇÃO: Sua resposta anterior não seguiu o formato correto. "
        "Você DEVE começar com '## INTENT' e incluir todas as seções obrigatórias."
    )
    try:
        raw_retry, result_retry = await _call_planning(client, corrective_prompt, instruction)
        plan = parse_structured_plan(raw_retry)
        logger.info(
            f"[Planning-retry] latency={result_retry.latency_ms}ms "
            f"tokens_in={result_retry.input_tokens} tokens_out={result_retry.output_tokens}"
        )
        return plan, result_retry
    except (ValueError, Exception) as e:
        logger.error(f"Planning parse error (tentativa 2): {e}. Usando plano fallback.")
        return FALLBACK_PLAN, AgentResult(text="", latency_ms=0)


async def _call_planning(
    client: genai.Client,
    prompt: str,
    system_instruction: str,
) -> tuple[str, AgentResult]:
    """Chamada direta ao modelo de planning. Retorna (raw_text, AgentResult)."""
    t0 = time.time()
    response = await client.aio.models.generate_content(
        model=settings.PLANNING_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            max_output_tokens=512,
        ),
    )
    latency_ms = int((time.time() - t0) * 1000)
    raw_text = response.text or ""

    input_tokens = 0
    output_tokens = 0
    if response.usage_metadata:
        input_tokens = response.usage_metadata.prompt_token_count or 0
        output_tokens = response.usage_metadata.candidates_token_count or 0

    return raw_text, AgentResult(
        text=raw_text,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
