"""Nubo Tools MCP Server.

Expõe as capacidades de dados do Nubo Conecta como ferramentas MCP.
Pode ser usado por:
  - Cloudinha Conecta Agent (como MCP Client)
  - Claude Desktop / Cursor (direto via HTTP ou stdio)
  - Agentes de Dev para debugging e inspeção de dados

Execução standalone:
  python -m src.mcp.server                    # stdio (Claude Desktop)
  python -m src.mcp.server --transport http   # HTTP na porta 8001
"""
import json
import logging
from mcp.server.fastmcp import FastMCP

from src.services.supabase_client import get_supabase_service
from src.tools.cep_lookup import lookup_cep as _cep_lookup

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="nubo-tools",
    instructions=(
        "Ferramentas de dados do Nubo Conecta. "
        "Use para buscar oportunidades educacionais, perfis de estudantes, "
        "resultados de match e informações de CEP no contexto brasileiro."
    ),
)


# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_opportunities(
    query: str,
    opportunity_type: str = "",
    limit: int = 5,
) -> str:
    """Busca bolsas, cursos e programas em v_unified_opportunities.

    Args:
        query: Termo de busca (ex: 'medicina', 'bolsa integral', 'FIES')
        opportunity_type: Filtro opcional — 'bolsa', 'curso' ou 'programa'
        limit: Máximo de resultados (padrão: 5)

    Returns:
        JSON com lista de oportunidades encontradas.
    """
    supabase = get_supabase_service()
    try:
        q = (
            supabase.table("v_unified_opportunities")
            .select("unified_id, title, provider_name, opportunity_type, is_partner, deadline, state")
            .ilike("title", f"%{query}%")
            .limit(limit)
        )
        if opportunity_type:
            q = q.eq("opportunity_type", opportunity_type)

        response = q.execute()
        data = response.data or []
        return json.dumps({"results": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"search_opportunities error: {e}")
        return json.dumps({"error": str(e), "results": []})


@mcp.tool()
async def get_student_profile(profile_id: str) -> str:
    """Obtém perfil e preferências do estudante ativo.

    Args:
        profile_id: UUID do perfil ativo (active_profile_id da requisição)

    Returns:
        JSON com dados do perfil e preferências educacionais.
    """
    supabase = get_supabase_service()
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
        result = {
            "profile": profile_resp.data,
            "preferences": prefs_resp.data,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"get_student_profile error: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def lookup_cep(cep: str) -> str:
    """Consulta endereço a partir de um CEP brasileiro via ViaCEP.

    Args:
        cep: CEP com 8 dígitos (com ou sem hífen)

    Returns:
        JSON com logradouro, bairro, localidade e UF.
    """
    result = await _cep_lookup(cep)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def get_match_results(profile_id: str, limit: int = 5) -> str:
    """Busca as oportunidades com maior match score para o perfil ativo.

    Args:
        profile_id: UUID do perfil ativo
        limit: Máximo de resultados (padrão: 5)

    Returns:
        JSON com lista de matches ordenados por score decrescente.
    """
    supabase = get_supabase_service()
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
        return json.dumps({"matches": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"get_match_results error: {e}")
        return json.dumps({"error": str(e), "matches": []})


@mcp.tool()
async def search_institutions(query: str, state: str = "") -> str:
    """Busca instituições de ensino (universidades, faculdades, institutos).

    Args:
        query: Nome ou sigla da instituição (ex: 'USP', 'UFMG', 'Anhanguera')
        state: Sigla do estado para filtrar (ex: 'SP', 'MG') — opcional

    Returns:
        JSON com lista de instituições encontradas.
    """
    supabase = get_supabase_service()
    try:
        q = (
            supabase.table("partners")
            .select("id, name, type, state, is_active")
            .ilike("name", f"%{query}%")
            .eq("is_active", True)
        )
        if state:
            q = q.eq("state", state)

        response = q.limit(5).execute()
        data = response.data or []
        return json.dumps({"institutions": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"search_institutions error: {e}")
        return json.dumps({"error": str(e), "institutions": []})


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8001, path="/mcp")
    else:
        mcp.run(transport="stdio")
