"""Ferramentas nativas de dados do usuário (LGPD-safe).

Estas funções NÃO são expostas via MCP. São chamadas diretamente pelo engine
com o profile_id extraído da requisição autenticada — o LLM nunca controla
qual perfil é consultado.

Isso garante conformidade com LGPD: o modelo não pode vazar dados de um usuário
para outro através de injeção de prompt ou manipulação de argumentos de tool.
"""
import logging
from supabase import Client

logger = logging.getLogger(__name__)


async def get_student_profile_native(supabase: Client, profile_id: str) -> dict:
    """Obtém perfil e preferências do estudante dono da requisição.

    Args:
        supabase: Cliente Supabase (anon ou service, dependendo do contexto).
        profile_id: UUID do perfil — injetado pelo engine a partir da requisição
                    autenticada. Nunca fornecido pelo LLM.

    Returns:
        Dict com chaves 'profile' e 'preferences', ou 'error' em caso de falha.
    """
    try:
        profile_resp = (
            supabase.table("user_profiles")
            .select("id, full_name, birth_date")
            .eq("id", profile_id)
            .single()
            .execute()
        )
        prefs_resp = (
            supabase.table("user_preferences")
            .select("enem_score, family_income_per_capita, course_interest, quota_types, state_preference")
            .eq("user_id", profile_id)
            .maybe_single()
            .execute()
        )
        return {
            "profile": profile_resp.data,
            "preferences": prefs_resp.data,
        }
    except Exception as e:
        logger.error(f"get_student_profile_native error for profile {profile_id}: {e}")
        return {"error": str(e)}


async def get_match_results_native(
    supabase: Client,
    profile_id: str,
    limit: int = 5,
) -> dict:
    """Busca as oportunidades com maior match score para o perfil dono da requisição.

    Args:
        supabase: Cliente Supabase.
        profile_id: UUID do perfil — injetado pelo engine, nunca pelo LLM.
        limit: Máximo de resultados (padrão: 5).

    Returns:
        Dict com chaves 'matches' e 'count', ou 'error' em caso de falha.
    """
    try:
        response = (
            supabase.table("user_opportunity_matches")
            .select("unified_opportunity_id, match_score, match_details")
            .eq("profile_id", profile_id)
            .order("match_score", desc=True)
            .limit(limit)
            .execute()
        )
        data = response.data or []
        return {"matches": data, "count": len(data)}
    except Exception as e:
        logger.error(f"get_match_results_native error for profile {profile_id}: {e}")
        return {"error": str(e), "matches": []}
