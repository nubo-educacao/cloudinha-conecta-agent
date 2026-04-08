"""Nubo Tools MCP Server — Catálogo Educacional (Read-Only).

Expõe ferramentas de consulta ao catálogo público do Nubo Conecta via MCP.
Pode ser usado por:
  - Cloudinha Conecta Agent (como MCP Client)
  - Claude Desktop / Cursor (direto via HTTP ou stdio)
  - Agentes de Dev para debugging e inspeção de dados

SEGURANÇA (LGPD):
  - Ferramentas de dados do USUÁRIO (perfil, match, candidaturas) NÃO estão aqui.
  - Elas vivem em src/tools/user_data.py e são chamadas diretamente pelo engine
    com o profile_id da requisição autenticada (anti-forge).
  - A tool search_educational_catalog valida SQL contra uma blocklist de tabelas
    privadas antes de executar.

Execução standalone:
  python -m src.mcp.server                    # stdio (Claude Desktop)
  python -m src.mcp.server --transport http   # HTTP na porta 8001
"""
import json
import logging
import re
from mcp.server.fastmcp import FastMCP

from src.services.supabase_client import get_supabase_service
from src.tools.cep_lookup import lookup_cep as _cep_lookup

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="nubo-tools",
    instructions=(
        "Ferramentas de consulta ao catálogo educacional do Nubo Conecta. "
        "Use para buscar oportunidades educacionais (bolsas, cursos, programas) "
        "e instituições de ensino. Dados pessoais do aluno NÃO estão disponíveis "
        "aqui — eles são injetados automaticamente pelo backend."
    ),
)

# ─── Blocklist LGPD ──────────────────────────────────────────────────────────

_BLOCKED_TABLES = [
    "user_profiles",
    "user_preferences",
    "user_enem_scores",
    "user_income",
    "users_metadata",
    "user_opportunity_matches",
    "student_applications",
    "chat_messages",
    "agent_errors",
    "agent_turns",
    "agent_prompts",
    "auth",
]

_BLOCKED_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _BLOCKED_TABLES) + r")\b",
    re.IGNORECASE,
)


def _validate_catalog_query(sql_query: str) -> str | None:
    """Valida se a query NÃO referencia tabelas privadas.

    Returns:
        None se válida, ou mensagem de erro se bloqueada.
    """
    match = _BLOCKED_PATTERN.search(sql_query)
    if match:
        return (
            f"Acesso negado: a tabela '{match.group()}' contém dados pessoais "
            "protegidos por LGPD. Use apenas tabelas do catálogo educacional "
            "(v_unified_opportunities, institutions, partners, courses, etc.)."
        )
    return None


# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_educational_catalog(sql_query: str) -> str:
    """Executa uma consulta SQL read-only no catálogo educacional do Nubo.

    Use esta ferramenta para buscar cursos, bolsas, programas e instituições
    usando queries SQL livres. Você tem acesso às tabelas:
    - v_unified_opportunities (vagas MEC + parceiros consolidados)
    - institutions (universidades, faculdades, institutos)
    - partners (parceiros do Nubo)
    - courses (cursos disponíveis)
    - partner_opportunities (vagas de parceiros)
    - knowledge_documents (base de conhecimento)
    - important_dates (calendário educacional)

    IMPORTANTE: Tabelas de dados pessoais (user_profiles, users_metadata, etc.)
    NÃO são acessíveis por esta ferramenta.

    Args:
        sql_query: Query SQL SELECT para executar no catálogo educacional.

    Returns:
        JSON com os resultados da query ou mensagem de erro.
    """
    # Validação LGPD
    error = _validate_catalog_query(sql_query)
    if error:
        logger.warning(f"search_educational_catalog BLOQUEOU query: {sql_query[:100]}")
        return json.dumps({"error": error})

    supabase = get_supabase_service()
    try:
        response = supabase.rpc("execute_readonly_query", {"query_text": sql_query}).execute()
        data = response.data or []
        return json.dumps({"results": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"search_educational_catalog error: {e}")
        return json.dumps({"error": str(e), "results": []})


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
