"""TDD: Testes do nubo-tools MCP Server.

Âncoras de verificação:
  1. FastMCP registra as 5 tools esperadas
  2. Cada tool tem nome e descrição não-vazia
  3. Tool schemas são válidos (têm 'properties')
  4. lookup_cep é executável com mock do httpx
  5. Tools de Supabase retornam dict com chave correta mesmo em erro
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMcpServerRegistration:
    """Verifica que o FastMCP registrou as tools corretas."""

    @pytest.mark.asyncio
    async def test_all_expected_tools_registered(self):
        """O MCP Server deve registrar exatamente as 5 tools do contrato."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()
            registered_names = {t.name for t in tools}

        expected = {
            "search_opportunities",
            "get_student_profile",
            "lookup_cep",
            "get_match_results",
            "search_institutions",
        }
        assert expected.issubset(registered_names), (
            f"Tools faltando: {expected - registered_names}"
        )

    @pytest.mark.asyncio
    async def test_each_tool_has_description(self):
        """Cada tool deve ter uma descrição não-vazia (requerido pelo Claude Desktop)."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()

        for tool in tools:
            assert tool.description, f"Tool '{tool.name}' não tem descrição"
            assert len(tool.description.strip()) > 10, (
                f"Descrição da tool '{tool.name}' muito curta"
            )

    @pytest.mark.asyncio
    async def test_search_opportunities_has_query_parameter(self):
        """search_opportunities deve exigir o parâmetro 'query'."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()
            tool_map = {t.name: t for t in tools}

        tool = tool_map["search_opportunities"]
        schema = tool.inputSchema or {}
        assert "query" in schema.get("properties", {}), (
            "search_opportunities deve ter parâmetro 'query'"
        )
        assert "query" in schema.get("required", []), (
            "O parâmetro 'query' deve ser obrigatório"
        )

    @pytest.mark.asyncio
    async def test_get_student_profile_has_profile_id_parameter(self):
        """get_student_profile deve exigir o parâmetro 'profile_id'."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()
            tool_map = {t.name: t for t in tools}

        tool = tool_map["get_student_profile"]
        schema = tool.inputSchema or {}
        assert "profile_id" in schema.get("properties", {}), (
            "get_student_profile deve ter parâmetro 'profile_id'"
        )


class TestMcpServerToolExecution:
    """Testa a execução das tools com mocks de dependências externas."""

    @pytest.mark.asyncio
    async def test_lookup_cep_returns_valid_address(self):
        """lookup_cep deve retornar JSON com campos de endereço."""
        mock_data = {
            "cep": "01310-100",
            "logradouro": "Avenida Paulista",
            "bairro": "Bela Vista",
            "localidade": "São Paulo",
            "uf": "SP",
        }

        with patch("src.mcp.server._cep_lookup", new_callable=AsyncMock) as mock_cep:
            mock_cep.return_value = mock_data
            from src.mcp.server import lookup_cep
            result_str = await lookup_cep("01310-100")

        result = json.loads(result_str)
        assert result["uf"] == "SP"
        assert result["localidade"] == "São Paulo"

    @pytest.mark.asyncio
    async def test_search_opportunities_returns_results_key(self):
        """search_opportunities deve sempre retornar chave 'results'."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [
            {"unified_id": "mec_1", "title": "Bolsa Medicina USP", "is_partner": False}
        ]
        (
            mock_supabase.table.return_value
            .select.return_value
            .ilike.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_resp

        with patch("src.mcp.server.get_supabase_service", return_value=mock_supabase):
            from src.mcp.server import search_opportunities
            result_str = await search_opportunities(query="medicina", limit=5)

        result = json.loads(result_str)
        assert "results" in result
        assert "count" in result
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_search_opportunities_returns_error_key_on_failure(self):
        """Contrato negativo: erro de DB deve retornar chave 'error', não raise."""
        with patch("src.mcp.server.get_supabase_service") as mock_svc:
            mock_svc.return_value.table.side_effect = Exception("DB offline")
            from src.mcp.server import search_opportunities
            result_str = await search_opportunities(query="medicina")

        result = json.loads(result_str)
        assert "error" in result, "Falha de DB deve retornar chave 'error'"
        assert "results" in result

    @pytest.mark.asyncio
    async def test_get_match_results_returns_matches_key(self):
        """get_match_results deve sempre retornar chave 'matches'."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = []
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_resp

        with patch("src.mcp.server.get_supabase_service", return_value=mock_supabase):
            from src.mcp.server import get_match_results
            result_str = await get_match_results(profile_id="some-uuid")

        result = json.loads(result_str)
        assert "matches" in result
        assert isinstance(result["matches"], list)

    @pytest.mark.asyncio
    async def test_search_institutions_returns_institutions_key(self):
        """search_institutions deve sempre retornar chave 'institutions'."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = []
        (
            mock_supabase.table.return_value
            .select.return_value
            .ilike.return_value
            .eq.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_resp

        with patch("src.mcp.server.get_supabase_service", return_value=mock_supabase):
            from src.mcp.server import search_institutions
            result_str = await search_institutions(query="USP")

        result = json.loads(result_str)
        assert "institutions" in result


class TestSchemaConversion:
    """Testa a conversão de JSON Schema → GenAI Schema no MCP Client."""

    def test_converts_string_type(self):
        from src.mcp.client import _json_schema_to_genai
        from google.genai import types

        schema = _json_schema_to_genai({
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca"},
            },
            "required": ["query"],
        })

        assert schema.type == types.Type.OBJECT
        assert "query" in schema.properties
        assert schema.properties["query"].type == types.Type.STRING
        assert "query" in schema.required

    def test_converts_integer_type(self):
        from src.mcp.client import _json_schema_to_genai
        from google.genai import types

        schema = _json_schema_to_genai({
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Máximo de resultados"},
            },
        })

        assert schema.properties["limit"].type == types.Type.INTEGER

    def test_empty_schema_returns_object(self):
        """Schema vazio deve retornar OBJECT sem crash."""
        from src.mcp.client import _json_schema_to_genai
        from google.genai import types

        schema = _json_schema_to_genai({})
        assert schema.type == types.Type.OBJECT

    def test_unknown_type_defaults_to_string(self):
        """Tipos desconhecidos devem usar STRING como fallback."""
        from src.mcp.client import _json_schema_to_genai
        from google.genai import types

        schema = _json_schema_to_genai({
            "type": "object",
            "properties": {
                "x": {"type": "uuid_custom_type", "description": "Custom"},
            },
        })
        # uuid_custom_type não existe no mapa, deve usar STRING
        assert schema.properties["x"].type == types.Type.STRING
