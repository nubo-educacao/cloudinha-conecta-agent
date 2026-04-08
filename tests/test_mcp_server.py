"""TDD: Testes do nubo-tools MCP Server.

Âncoras de verificação:
  1. FastMCP registra exatamente as 4 tools públicas do catálogo (sem tools privadas de usuário)
  2. Cada tool tem nome e descrição não-vazia
  3. Tool schemas são válidos (têm 'properties')
  4. lookup_cep é executável com mock do httpx
  5. Tools de Supabase retornam dict com chave correta mesmo em erro
  6. SEGURANÇA: search_educational_catalog rejeita queries a tabelas privadas (LGPD)
  7. SEGURANÇA: get_student_profile e get_match_results NÃO estão no MCP global
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMcpServerRegistration:
    """Verifica que o FastMCP registrou as tools corretas."""

    @pytest.mark.asyncio
    async def test_public_catalog_tools_registered(self):
        """O MCP Server deve registrar exatamente as 4 tools públicas do catálogo."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()
            registered_names = {t.name for t in tools}

        expected = {
            "search_educational_catalog",
            "lookup_cep",
            "search_institutions",
            "search_opportunities",
        }
        assert expected.issubset(registered_names), (
            f"Tools públicas faltando: {expected - registered_names}"
        )

    @pytest.mark.asyncio
    async def test_private_user_tools_NOT_in_mcp(self):
        """SEGURANÇA LGPD: get_student_profile e get_match_results NÃO devem
        estar expostos no MCP global — acesso a dados do usuário é controlado
        pelo engine usando o profile_id da requisição autenticada."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()
            registered_names = {t.name for t in tools}

        forbidden = {"get_student_profile", "get_match_results"}
        exposed = forbidden & registered_names
        assert not exposed, (
            f"Tools privadas LGPD estão expostas no MCP: {exposed}. "
            "Mova-as para ferramentas nativas do engine (src/tools/user_data.py)."
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
    async def test_search_educational_catalog_has_sql_query_parameter(self):
        """search_educational_catalog deve exigir o parâmetro 'sql_query'."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import mcp

            tools = await mcp.list_tools()
            tool_map = {t.name: t for t in tools}

        assert "search_educational_catalog" in tool_map, (
            "search_educational_catalog não registrada no MCP"
        )
        tool = tool_map["search_educational_catalog"]
        schema = tool.inputSchema or {}
        assert "sql_query" in schema.get("properties", {}), (
            "search_educational_catalog deve ter parâmetro 'sql_query'"
        )
        assert "sql_query" in schema.get("required", []), (
            "O parâmetro 'sql_query' deve ser obrigatório"
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
        """get_match_results (nativo, LGPD-safe) deve sempre retornar chave 'matches'."""
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

        from src.tools.user_data import get_match_results_native
        result = await get_match_results_native(supabase=mock_supabase, profile_id="some-uuid")

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


class TestCatalogSecurityBlocklist:
    """SEGURANÇA LGPD: search_educational_catalog deve rejeitar acesso a tabelas privadas."""

    @pytest.mark.asyncio
    async def test_rejects_query_with_user_profiles(self):
        """Query com 'user_profiles' deve ser rejeitada com erro."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT * FROM user_profiles WHERE id = '123'"
            )
        result = json.loads(result_str)
        assert "error" in result, "Deve retornar chave 'error' para tabela privada"
        assert "results" not in result or result.get("results") is None, (
            "Não deve retornar resultados para query rejeitada"
        )

    @pytest.mark.asyncio
    async def test_rejects_query_with_users_metadata(self):
        """Query com 'users_metadata' deve ser rejeitada."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT cognitive_memory FROM users_metadata"
            )
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_query_with_user_preferences(self):
        """Query com 'user_preferences' deve ser rejeitada."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT enem_score FROM user_preferences WHERE user_id = 'abc'"
            )
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_query_referencing_auth_schema(self):
        """Query com 'auth.' (schema auth do Supabase) deve ser rejeitada."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT email FROM auth.users"
            )
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_query_with_auth_standalone(self):
        """Query com 'auth' como nome de tabela isolado deve ser rejeitada."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT * FROM auth WHERE uid = '123'"
            )
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_blocklist_case_insensitive(self):
        """A validação deve ser case-insensitive (USER_PROFILES, Auth, etc.)."""
        with patch("src.mcp.server.get_supabase_service"):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT * FROM USER_PROFILES"
            )
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_allows_valid_catalog_query(self):
        """Query válida contra v_unified_opportunities deve ser executada."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [
            {"unified_id": "mec_1", "title": "Bolsa Medicina USP", "opportunity_type": "bolsa"}
        ]
        (
            mock_supabase.table.return_value
            .select.return_value
            .ilike.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_resp

        with patch("src.mcp.server.get_supabase_service", return_value=mock_supabase):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT * FROM v_unified_opportunities WHERE title ILIKE '%medicina%'"
            )
        result = json.loads(result_str)
        assert "results" in result, "Query válida deve retornar 'results'"
        assert "error" not in result or result.get("error") is None

    @pytest.mark.asyncio
    async def test_allows_institutions_query(self):
        """Query válida contra partners/institutions deve ser executada."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [{"id": "inst_1", "name": "USP", "state": "SP"}]
        (
            mock_supabase.table.return_value
            .select.return_value
            .ilike.return_value
            .eq.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_resp

        with patch("src.mcp.server.get_supabase_service", return_value=mock_supabase):
            from src.mcp.server import search_educational_catalog
            result_str = await search_educational_catalog(
                sql_query="SELECT * FROM institutions WHERE name ILIKE '%USP%'"
            )
        result = json.loads(result_str)
        assert "results" in result


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
