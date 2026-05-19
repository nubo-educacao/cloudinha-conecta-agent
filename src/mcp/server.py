"""Nubo Tools MCP Server — Catálogo Educacional (Read-Only).

Expõe ferramentas de consulta ao catálogo público do Nubo Conecta via MCP.
"""
import json
import logging
import re
from datetime import datetime, timezone
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

from src.services.supabase_client import get_supabase_service

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="nubo-tools",
    instructions=(
        "Ferramentas de consulta ao catálogo educacional e dados do estudante do Nubo Conecta. "
        "Use para buscar oportunidades, instituições e dados do aluno ativo."
    ),
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
    """Valida se a query NÃO referencia tabelas privadas."""
    match = _BLOCKED_PATTERN.search(sql_query)
    if match:
        return (
            f"Acesso negado: a tabela '{match.group()}' contém dados pessoais "
            "protegidos por LGPD. Use apenas tabelas do catálogo educacional."
        )
    return None

# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def query_educational_catalog(sql_query: str) -> str:
    """Executa uma consulta SQL read-only no catálogo educacional do Nubo.

    Use para buscar oportunidades, instituições, cursos e datas.
    Tabelas acessíveis: v_unified_opportunities, institutions, partners, courses, 
    partner_opportunities, knowledge_documents, important_dates.

    Tabelas de dados pessoais (user_*, student_*) NÃO são acessíveis por aqui.

    Args:
        sql_query: Query SQL SELECT para executar.
    """
    error = _validate_catalog_query(sql_query)
    if error:
        return json.dumps({"error": error})

    supabase = get_supabase_service()
    try:
        response = supabase.rpc("execute_readonly_query", {"query_text": sql_query}).execute()
        data = response.data or []
        return json.dumps({"results": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"query_educational_catalog error: {e}")
        return json.dumps({"error": str(e), "results": []})


@mcp.tool()
async def get_student_context(sql_query: str, profile_id: str) -> str:
    """Executa uma consulta SQL read-only sobre os dados do estudante ativo.

    Use para buscar status de candidaturas, matches, preferências e perfil do aluno.
    Tabelas acessíveis: student_applications, user_opportunity_matches, user_profiles, 
    user_preferences, user_income, user_enem_scores, user_favorites.

    O parâmetro `profile_id` DEVE ser usado na query para filtrar os dados do aluno.

    Args:
        sql_query: Query SQL SELECT filtrando por profile_id ou user_id.
        profile_id: ID do perfil do estudante ativo.
    """
    allowed_tables = [
        "student_applications",
        "user_opportunity_matches",
        "user_profiles",
        "user_preferences",
        "user_income",
        "user_enem_scores",
        "user_favorites",
    ]
    
    for tbl in _BLOCKED_TABLES:
        if tbl not in allowed_tables and re.search(r"\b" + re.escape(tbl) + r"\b", sql_query, re.IGNORECASE):
            return json.dumps({"error": f"Acesso negado à tabela '{tbl}' nesta ferramenta."})
            
    if profile_id not in sql_query:
        return json.dumps({"error": f"A query deve conter o profile_id '{profile_id}' para garantir a segurança dos dados."})

    supabase = get_supabase_service()
    try:
        response = supabase.rpc("execute_readonly_query", {"query_text": sql_query}).execute()
        data = response.data or []
        return json.dumps({"results": data, "count": len(data)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"get_student_context error: {e}")
        return json.dumps({"error": str(e), "results": []})


@mcp.tool()
async def download_knowledge_document(storage_path: str) -> str:
    """Baixa o conteúdo markdown de um documento de conhecimento do storage.

    Use após encontrar o storage_path via query_educational_catalog.

    Args:
        storage_path: Caminho do arquivo no bucket 'knowledge-base'.
    """
    supabase = get_supabase_service()
    try:
        file_data = supabase.storage.from_("knowledge-base").download(storage_path)
        content = file_data.decode("utf-8")
        return json.dumps({"content": content}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"download_knowledge_document error: {e}")
        return json.dumps({"error": f"Erro ao baixar documento: {str(e)}"})


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
