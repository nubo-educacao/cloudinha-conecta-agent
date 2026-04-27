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
from mcp.server.fastmcp.server import TransportSecuritySettings

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
    # Desabilita o bloqueio de Host header para compatibilidade com Cloud Run / Proxy
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
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

# Schema estático de v_unified_opportunities — fallback quando information_schema não a retorna
_STATIC_VIEW_SCHEMA = [
    {"column": "unified_id", "type": "text", "nullable": False},
    {"column": "title", "type": "text", "nullable": False},
    {"column": "provider_name", "type": "text", "nullable": True},
    {"column": "type", "type": "text", "nullable": False, "values": "sisu | prouni | partner"},
    {"column": "category", "type": "text", "nullable": True},
    {"column": "is_partner", "type": "boolean", "nullable": False},
    {"column": "location", "type": "text", "nullable": True},
    {"column": "badges", "type": "jsonb", "nullable": True},
    {"column": "status", "type": "text", "nullable": True, "values": "approved"},
    {"column": "starts_at", "type": "timestamptz", "nullable": True},
    {"column": "ends_at", "type": "timestamptz", "nullable": True},
    {"column": "created_at", "type": "timestamptz", "nullable": True},
    {"column": "external_redirect_url", "type": "text", "nullable": True},
    {"column": "external_redirect_enabled", "type": "boolean", "nullable": True},
]


# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def describe_catalog_schema(table_name: str = "") -> str:
    """Retorna o schema (colunas, tipos) das tabelas do catálogo educacional.

    Use ANTES de search_educational_catalog para descobrir quais colunas e
    valores existem. Isso permite construir queries SQL precisas.

    Tabelas disponíveis no catálogo:
    - v_unified_opportunities (visão consolidada: bolsas MEC + parceiros)
    - institutions (universidades, faculdades)
    - partners (instituições parceiras)
    - courses (cursos disponíveis)
    - partner_opportunities (vagas de parceiros)
    - knowledge_documents (base de conhecimento)
    - important_dates (calendário educacional)

    Args:
        table_name: Nome da tabela para descrever. Se vazio, lista todas as tabelas disponíveis com suas colunas.

    Returns:
        JSON com schema das tabelas (colunas, tipos, nullable).
    """
    supabase = get_supabase_service()

    # Tabelas permitidas no catálogo (excluindo dados pessoais LGPD)
    catalog_tables = [
        "v_unified_opportunities", "institutions", "partners",
        "courses", "partner_opportunities", "knowledge_documents",
        "important_dates",
    ]

    if table_name and table_name not in catalog_tables:
        return json.dumps({
            "error": f"Tabela '{table_name}' não disponível. Tabelas permitidas: {catalog_tables}"
        })

    target_tables = [table_name] if table_name else catalog_tables

    try:
        response = supabase.rpc("execute_readonly_query", {
            "query_text": f"""
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name IN ({','.join(f"'{t}'" for t in target_tables)})
                ORDER BY table_name, ordinal_position
            """
        }).execute()

        data = response.data or []
        # Agrupar por tabela
        schema: dict = {}
        for row in data:
            tbl = row["table_name"]
            schema.setdefault(tbl, []).append({
                "column": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
            })

        # Fallback: se v_unified_opportunities pedida mas não retornada (view issue)
        if "v_unified_opportunities" in target_tables and "v_unified_opportunities" not in schema:
            schema["v_unified_opportunities"] = _STATIC_VIEW_SCHEMA

        return json.dumps({"schema": schema, "tables": list(schema.keys())}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"describe_catalog_schema error: {e}")
        return json.dumps({
            "schema": {"v_unified_opportunities": _STATIC_VIEW_SCHEMA},
            "tables": ["v_unified_opportunities"],
            "_note": "Schema estático (fallback). Use search_opportunities para buscas simples.",
        }, ensure_ascii=False)


@mcp.tool()
async def search_educational_catalog(sql_query: str) -> str:
    """Executa uma consulta SQL read-only no catálogo educacional do Nubo.

    FERRAMENTA PRINCIPAL para buscas complexas. Use para qualquer consulta que
    envolva filtros, agregações, JOINs ou condições que as outras tools não cobrem.

    Dica: chame describe_catalog_schema primeiro para descobrir colunas e tipos,
    depois monte a query SQL adequada.

    Tabelas acessíveis:
    - v_unified_opportunities (vagas MEC + parceiros consolidados)
    - institutions (universidades, faculdades, institutos)
    - partners (parceiros do Nubo)
    - courses (cursos disponíveis)
    - partner_opportunities (vagas de parceiros)
    - knowledge_documents (base de conhecimento)
    - important_dates (calendário educacional)

    Exemplos de uso:
    - Oportunidades abertas: "SELECT * FROM v_unified_opportunities WHERE status = 'approved' LIMIT 10"
    - Por tipo: "SELECT * FROM v_unified_opportunities WHERE type = 'prouni' AND status = 'approved'"
    - Datas: "SELECT title, starts_at, ends_at FROM v_unified_opportunities WHERE ends_at > NOW()"

    IMPORTANTE: Tabelas de dados pessoais (user_profiles, users_metadata, etc.)
    NÃO são acessíveis por esta ferramenta (proteção LGPD).

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
    query: str = "",
    opportunity_type: str = "",
    status: str = "approved",
    limit: int = 10,
) -> str:
    """Busca bolsas, cursos e programas no catálogo unificado (v_unified_opportunities).

    Use para encontrar oportunidades educacionais abertas, buscar por termo,
    ou listar todas as oportunidades disponíveis. A view contém oportunidades
    MEC (Sisu, Prouni) e de parceiros.

    Todas as oportunidades na view com status 'approved' estão abertas para inscrição.
    Quando o aluno perguntar sobre oportunidades "abertas" ou "disponíveis",
    use status='approved' (padrão).

    Args:
        query: Termo de busca opcional no título (ex: 'medicina', 'FIES', 'Estudar').
               Se vazio, retorna oportunidades sem filtro de título.
        opportunity_type: Filtro por tipo — 'sisu', 'prouni' ou 'partner'. Opcional.
        status: Filtro pela coluna status da view — 'approved' (abertas/ativas), 'all' (sem filtro). Padrão: 'approved'.
        limit: Máximo de resultados (padrão: 10)

    Returns:
        JSON com lista de oportunidades encontradas incluindo status, starts_at e ends_at.
    """

    supabase = get_supabase_service()
    try:
        q = (
            supabase.table("v_unified_opportunities")
            .select("unified_id, title, provider_name, type, is_partner, status, starts_at, ends_at, location")
            .limit(limit)
        )
        # Filtro de texto no título — só se tiver query
        if query:
            q = q.ilike("title", f"%{query}%")
        # Filtro de tipo de oportunidade
        if opportunity_type:
            q = q.eq("type", opportunity_type)
        # Filtro de status — 'all' desabilita o filtro
        if status and status != "all":
            q = q.eq("status", status)

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


@mcp.tool()
async def list_admin_alerts(status: str = "pending", limit: int = 10) -> str:
    """Lista alertas operacionais do Action Center para administradores.

    Retorna alertas sobre oportunidades expirando, periodos MEC abrindo/encerrando,
    e outros eventos que exigem acao do admin.

    Args:
        status: Filtro de status — 'pending', 'acknowledged', 'resolved', 'dismissed' (padrao: 'pending')
        limit: Maximo de resultados (padrao: 10)

    Returns:
        JSON com lista de alertas e contagem.
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.table("admin_alerts")
            .select("*")
            .eq("status", status)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        data = response.data or []
        return json.dumps({"alerts": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"list_admin_alerts error: {e}")
        return json.dumps({"error": str(e), "alerts": []})


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    if transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
