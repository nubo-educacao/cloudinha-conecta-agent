import logging
from supabase import Client

logger = logging.getLogger(__name__)


async def retrieve_few_shot_examples(
    supabase: Client,
    query: str,
    intent_category: str = "general_qa",
    limit: int = 3,
) -> str:
    """Busca exemplos de tom e estilo da tabela learning_examples.

    Injeção: concatenar no prompt do Reasoning Agent (não do Planning nem do Response).
    A intent_category é extraída do StructuredPlan.intent_category.
    """
    try:
        response = (
            supabase.table("learning_examples")
            .select("input_query, ideal_output, reasoning")
            .eq("is_active", True)
            .eq("intent_category", intent_category)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        if not response.data:
            return ""

        formatted = []
        for ex in response.data:
            q = ex.get("input_query", "").replace("\n", " ")
            a = ex.get("ideal_output", "").replace("\n", " ")
            r = ex.get("reasoning", "")
            formatted.append(f"- Exemplo: {q}\n  Resposta Ideal: {a}\n  Motivo: {r}")

        return (
            "\n\n### EXEMPLOS DE TOM E ESTILO (APRENDIZADO)\n"
            "Os exemplos abaixo mostram qualidade esperada. "
            "Use as tools disponíveis antes de formular a resposta.\n\n"
            + "\n\n".join(formatted)
        )
    except Exception as e:
        logger.error(f"Erro ao buscar few-shot examples: {e}")
        return ""
