import time
import logging

logger = logging.getLogger(__name__)

_schema_cache: dict = {}
_schema_cache_ts: float = 0.0
SCHEMA_CACHE_TTL = 300  # 5 minutos

KEY_TABLES = [
    "v_unified_opportunities",
    "user_profiles",
    "user_preferences",
    "student_applications",
    "user_opportunity_matches",
    "partners",
]


async def get_schema_context(supabase_client) -> str:
    """Retorna DDL das tabelas-chave como string markdown. Cacheado com TTL de 5 minutos."""
    global _schema_cache, _schema_cache_ts

    if _schema_cache and (time.time() - _schema_cache_ts) < SCHEMA_CACHE_TTL:
        return _schema_cache.get("content", "")

    logger.info("Schema Discovery: refreshing cache...")
    try:
        rows = (
            supabase_client.table("information_schema.columns")
            .select("table_name, column_name, data_type, is_nullable")
            .in_("table_name", KEY_TABLES)
            .order("table_name")
            .order("ordinal_position")
            .execute()
        )
        schema_str = _format_schema(rows.data or [])
    except Exception as e:
        logger.warning(f"Schema Discovery: falha ao buscar DDL via information_schema: {e}")
        schema_str = _fallback_schema()

    _schema_cache = {"content": schema_str}
    _schema_cache_ts = time.time()
    return schema_str


def _format_schema(rows: list[dict]) -> str:
    """Formata as colunas como markdown por tabela."""
    tables: dict[str, list[str]] = {}
    for row in rows:
        tbl = row["table_name"]
        nullable = "NULL" if row["is_nullable"] == "YES" else "NOT NULL"
        tables.setdefault(tbl, []).append(f"  - {row['column_name']}: {row['data_type']} {nullable}")

    parts = ["### SCHEMA DAS TABELAS PRINCIPAIS\n"]
    for tbl, cols in tables.items():
        parts.append(f"**{tbl}**")
        parts.extend(cols)
        parts.append("")

    return "\n".join(parts)


def _fallback_schema() -> str:
    """Schema mínimo hardcoded como fallback quando information_schema não está acessível."""
    return """### SCHEMA DAS TABELAS PRINCIPAIS (fallback)

**v_unified_opportunities**
  - unified_id: text
  - title: text
  - provider_name: text
  - type: text (sisu | prouni | partner)
  - category: text
  - is_partner: boolean
  - location: text
  - status: text
  - starts_at: timestamptz
  - ends_at: timestamptz

**user_profiles**
  - id: uuid
  - full_name: text
  - birth_date: date
  - parent_user_id: uuid (NULL = perfil principal)

**user_preferences**
  - user_id: uuid
  - enem_score: numeric
  - family_income_per_capita: numeric
  - course_interest: text[]
  - quota_types: text[]
  - state_preference: text

**student_applications**
  - id: uuid
  - profile_id: uuid
  - unified_opportunity_id: text
  - status: text
  - applied_at: timestamptz

**user_opportunity_matches**
  - profile_id: uuid
  - unified_opportunity_id: text
  - match_score: numeric(5,2)
  - match_details: jsonb
"""
