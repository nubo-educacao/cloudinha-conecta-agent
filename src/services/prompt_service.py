"""Serviço de resolução dinâmica de prompts de sistema.

Busca as instruções dos agentes na tabela 'agent_prompts' antes de cada execução,
permitindo atualizações de persona/comportamento sem redeploy.

Em caso de falha de conectividade, usa o fallback passado pelo chamador.
"""
import logging
from supabase import Client

logger = logging.getLogger(__name__)


def resolve_system_prompt(supabase: Client, agent_key: str, fallback: str) -> str:
    """Busca a instrução de sistema para um agente na tabela agent_prompts.

    Args:
        supabase: Cliente Supabase (service key recomendado para evitar RLS).
        agent_key: Identificador do agente ('planning', 'reasoning', 'response').
        fallback: Instrução a usar se o registro não for encontrado ou houver falha.

    Returns:
        A instrução de sistema do banco, ou o fallback em caso de ausência/falha.
    """
    try:
        resp = (
            supabase.table("agent_prompts")
            .select("system_instruction")
            .eq("agent_key", agent_key)
            .maybe_single()
            .execute()
        )
        if resp.data:
            instruction = resp.data.get("system_instruction", "")
            if instruction and instruction.strip():
                return instruction.strip()
    except Exception as e:
        logger.warning(f"prompt_service: falha ao buscar prompt '{agent_key}': {e}. Usando fallback.")

    return fallback
