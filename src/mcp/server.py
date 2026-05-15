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
from datetime import datetime, timezone
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
        JSON com lista de instituições encontradas incluindo logo, descrição e tipo.
    """
    supabase = get_supabase_service()
    try:
        # Tenta a view enriquecida primeiro; fallback para tabela partners
        try:
            q = (
                supabase.table("v_unified_institutions")
                .select("id, name, acronym, type, state, location, logo_url, description, brand_color")
                .or_(f"name.ilike.%{query}%,acronym.ilike.%{query}%")
            )
            if state:
                q = q.eq("state", state)
            response = q.limit(5).execute()
        except Exception:
            q = (
                supabase.table("partners")
                .select("id, name, type, state, logo_url, description, brand_color, is_active")
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
async def get_opportunity_details(unified_id: str) -> str:
    """Retorna detalhes completos de uma oportunidade pelo unified_id.

    Inclui título, instituição, tipo, datas, descrição, benefícios e elegibilidade.
    Use quando o usuário pergunta sobre uma oportunidade específica.

    Args:
        unified_id: ID unificado da oportunidade (ex: 'partner_uuid' ou 'mec_uuid')
    """
    supabase = get_supabase_service()
    try:
        resp = supabase.table("v_unified_opportunities") \
            .select("*") \
            .eq("unified_id", unified_id) \
            .limit(1).execute()

        if resp.data:
            return json.dumps({"opportunity": resp.data[0]}, ensure_ascii=False, default=str)

        # Fallback: buscar em partner_opportunities
        pure_uuid = unified_id.split("_", 1)[-1] if "_" in unified_id else unified_id
        resp = supabase.table("partner_opportunities") \
            .select("*, partner_institutions(institutions(name, state))") \
            .eq("id", pure_uuid) \
            .limit(1).execute()

        if resp.data:
            return json.dumps({"opportunity": resp.data[0]}, ensure_ascii=False, default=str)

        return json.dumps({"error": f"Oportunidade {unified_id} não encontrada"})
    except Exception as e:
        logger.error(f"get_opportunity_details error: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_important_dates(date_type: str = "", limit: int = 5) -> str:
    """Retorna datas importantes do calendário educacional.

    Inclui prazos de Sisu, Prouni, FIES, vestibulares e eventos de parceiros.
    Use quando o usuário pergunta sobre prazos, datas ou quando algo abre/encerra.

    Args:
        date_type: Filtro por tipo (ex: 'sisu', 'prouni', 'fies'). Se vazio, retorna todos.
        limit: Máximo de resultados (padrão: 5)
    """
    supabase = get_supabase_service()
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        q = supabase.table("important_dates") \
            .select("*") \
            .gte("start_date", today) \
            .order("start_date") \
            .limit(limit)
        if date_type:
            q = q.eq("type", date_type)
        resp = q.execute()
        data = resp.data or []
        return json.dumps({"dates": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"get_important_dates error: {e}")
        return json.dumps({"error": str(e), "dates": []})


@mcp.tool()
async def get_knowledge_article(topic: str, limit: int = 3) -> str:
    """Busca artigos na base de conhecimento do Nubo sobre educação.

    Útil para perguntas sobre processos (como funciona o Sisu, o que é Prouni, etc).

    Args:
        topic: Termo de busca (ex: 'Sisu', 'nota de corte', 'cotas')
        limit: Máximo de resultados (padrão: 3)
    """
    supabase = get_supabase_service()
    try:
        resp = supabase.table("knowledge_documents") \
            .select("id, title, description, storage_path") \
            .or_(f"title.ilike.%{topic}%,description.ilike.%{topic}%") \
            .limit(limit).execute()

        articles = []
        for doc in (resp.data or []):
            content = ""
            if doc.get("storage_path"):
                try:
                    file_data = supabase.storage.from_("knowledge-base").download(doc["storage_path"])
                    content = file_data.decode("utf-8")
                except Exception as fetch_err:
                    content = f"[Erro ao carregar conteúdo: {fetch_err}]"
            articles.append({
                "id": doc.get("id"),
                "title": doc.get("title"),
                "description": doc.get("description"),
                "content": content,
            })

        return json.dumps({"articles": articles, "count": len(articles)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"get_knowledge_article error: {e}")
        return json.dumps({"error": str(e), "articles": []})


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
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
