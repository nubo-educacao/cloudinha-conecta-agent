"""Unit tests para o serviço de descoberta de schema (schema_discovery.py).

Atende diretamente aos BDD scenarios do Card 439c3bea (Schema Auto-Discover):
1. Schema discovery retorna DDL via RPC
2. Fallback hardcoded funciona quando RPC falha
3. Cache TTL 5min evita queries repetidas
4. Schema é injetado no prompt do Planning Agent
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import time

from src.services.schema_discovery import (
    get_schema_context,
    _fallback_schema,
    SCHEMA_CACHE_TTL,
)
import src.services.schema_discovery as sd


@pytest.fixture(autouse=True)
def reset_schema_cache():
    """Garante que o cache global do schema seja resetado antes de cada teste."""
    sd._schema_cache = {}
    sd._schema_cache_ts = 0.0
    yield
    sd._schema_cache = {}
    sd._schema_cache_ts = 0.0


@pytest.mark.asyncio
async def test_schema_discovery_returns_ddl_via_rpc():
    """Cenário 1: Retorna markdown com DDL das tabelas chave via RPC."""
    mock_supabase = MagicMock()
    mock_resp = MagicMock()
    mock_resp.data = [
        {"table_name": "v_unified_opportunities", "column_name": "unified_id", "data_type": "text", "is_nullable": "NO"},
        {"table_name": "knowledge_documents", "column_name": "title", "data_type": "text", "is_nullable": "YES"},
        {"table_name": "important_dates", "column_name": "start_date", "data_type": "date", "is_nullable": "NO"},
    ]
    mock_supabase.rpc.return_value.execute.return_value = mock_resp

    result = await get_schema_context(mock_supabase)

    assert "### SCHEMA DAS TABELAS PRINCIPAIS" in result
    assert "**v_unified_opportunities**" in result
    assert "**knowledge_documents**" in result
    assert "**important_dates**" in result
    assert "unified_id: text NOT NULL" in result


@pytest.mark.asyncio
async def test_fallback_schema_when_rpc_fails():
    """Cenário 2: Fallback hardcoded funciona quando RPC falha."""
    mock_supabase = MagicMock()
    mock_supabase.rpc.side_effect = Exception("Falha de permissão na RPC")

    result = await get_schema_context(mock_supabase)

    assert "### SCHEMA DAS TABELAS PRINCIPAIS (fallback)" in result
    assert "**v_unified_opportunities**" in result
    assert "starts_at: timestamptz" in result


@pytest.mark.asyncio
async def test_cache_ttl_avoids_repeated_queries():
    """Cenário 3: Cache TTL 5min evita queries repetidas."""
    mock_supabase = MagicMock()
    mock_resp = MagicMock()
    mock_resp.data = [
        {"table_name": "table_1", "column_name": "col_1", "data_type": "text", "is_nullable": "NO"}
    ]
    mock_supabase.rpc.return_value.execute.return_value = mock_resp

    t0 = time.time()
    with patch("src.services.schema_discovery.time.time", return_value=t0):
        res1 = await get_schema_context(mock_supabase)

    assert mock_supabase.rpc.call_count == 1
    assert "table_1" in res1

    # Segunda chamada dentro do TTL (t0 + 10s)
    with patch("src.services.schema_discovery.time.time", return_value=t0 + 10.0):
        res2 = await get_schema_context(mock_supabase)

    # Não deve ter chamado RPC novamente
    assert mock_supabase.rpc.call_count == 1
    assert res2 == res1


@pytest.mark.asyncio
async def test_schema_is_injected_into_planning_prompt():
    """Cenário 4: Schema é injetado no prompt do Planning Agent."""
    from src.workflow.engine import _execute_pipeline
    from src.models.chat_request import ChatRequest
    from uuid import uuid4

    req = ChatRequest(
        chatInput="Quais bolsas para medicina?",
        userId=uuid4(),
        active_profile_id=uuid4(),
        sessionId="session_test",
    )

    mock_supabase_anon = MagicMock()
    mock_supabase_service = MagicMock()
    
    mock_schema_str = "### SCHEMA DAS TABELAS PRINCIPAIS\n**v_unified_opportunities**"

    with (
        patch("src.workflow.engine.get_schema_context", new_callable=AsyncMock) as mock_get_schema,
        patch("src.workflow.engine.run_planning_agent", new_callable=AsyncMock) as mock_run_planning,
        patch("src.workflow.engine.retrieve_few_shot_examples", new_callable=AsyncMock),
        patch("src.workflow.engine.run_reasoning_agent", new_callable=MagicMock),
    ):
        mock_get_schema.return_value = mock_schema_str
        mock_run_planning.return_value = (MagicMock(), MagicMock())
        
        async def empty_gen(*args, **kwargs):
            if False: yield

        mock_reasoning_fn = MagicMock()
        mock_reasoning_fn.return_value = empty_gen()

        with patch("src.workflow.engine.run_reasoning_agent", mock_reasoning_fn):
            async for _ in _execute_pipeline(
                req, "context", mock_supabase_anon, mock_supabase_service, planning_prompt="PROMPT BASE"
            ):
                pass

        # Verificar se run_planning_agent foi chamado com o schema injetado no system_prompt
        assert mock_run_planning.call_count == 1
        kwargs = mock_run_planning.call_args[1]
        assert "PROMPT BASE" in kwargs["system_prompt"]
        assert "### SCHEMA DAS TABELAS PRINCIPAIS" in kwargs["system_prompt"]
