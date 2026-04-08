"""TDD: Testes das ferramentas nativas de dados do usuário (LGPD-safe).

Âncoras de verificação:
  1. get_student_profile_native retorna perfil e preferências do usuário correto
  2. get_student_profile_native usa profile_id da requisição (não do LLM)
  3. get_match_results_native retorna matches ordenados por score
  4. Ambas as funções retornam dicts estruturados (não strings JSON)
  5. Falhas de DB não propagam exceção — retornam dict com chave 'error'
"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4


class TestGetStudentProfileNative:
    """Testa a ferramenta nativa de perfil do estudante."""

    @pytest.mark.asyncio
    async def test_returns_profile_and_preferences(self):
        """Deve retornar dict com chaves 'profile' e 'preferences'."""
        profile_id = str(uuid4())

        mock_supabase = MagicMock()
        mock_profile_resp = MagicMock()
        mock_profile_resp.data = {"id": profile_id, "full_name": "João Silva", "birth_date": "2000-01-15"}
        mock_prefs_resp = MagicMock()
        mock_prefs_resp.data = {"enem_score": 750.0, "family_income_per_capita": 1200.0}

        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .single.return_value
            .execute.return_value
        ) = mock_profile_resp
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = mock_prefs_resp

        from src.tools.user_data import get_student_profile_native
        result = await get_student_profile_native(mock_supabase, profile_id)

        assert "profile" in result, "Deve conter chave 'profile'"
        assert "preferences" in result, "Deve conter chave 'preferences'"

    @pytest.mark.asyncio
    async def test_profile_id_is_injected_not_llm_controlled(self):
        """O profile_id NUNCA vem do LLM — é injetado pelo engine a partir
        da requisição autenticada. Este teste verifica que a função recebe
        profile_id como parâmetro posicional (não via args do modelo)."""
        import inspect
        from src.tools.user_data import get_student_profile_native

        sig = inspect.signature(get_student_profile_native)
        params = list(sig.parameters.keys())
        # Assinatura correta: (supabase, profile_id) — sem defaults ambíguos
        assert "supabase" in params, "Deve receber supabase como primeiro parâmetro"
        assert "profile_id" in params, "Deve receber profile_id explicitamente"
        # profile_id não deve ter default (não deve ser opcional)
        assert sig.parameters["profile_id"].default is inspect.Parameter.empty, (
            "profile_id não deve ter valor padrão — deve ser sempre injetado"
        )

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_db_failure(self):
        """Falha de DB deve retornar dict com chave 'error', não levantar exceção."""
        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = Exception("DB connection failed")

        from src.tools.user_data import get_student_profile_native
        result = await get_student_profile_native(mock_supabase, "some-uuid")

        assert "error" in result, "Falha de DB deve retornar chave 'error'"
        assert "profile" not in result or result.get("profile") is None

    @pytest.mark.asyncio
    async def test_returns_dict_not_json_string(self):
        """Ferramenta nativa retorna dict Python (não string JSON como MCP tools)."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = {"id": "abc", "full_name": "Maria"}
        mock_prefs_resp = MagicMock()
        mock_prefs_resp.data = None

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp
        mock_supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_prefs_resp

        from src.tools.user_data import get_student_profile_native
        result = await get_student_profile_native(mock_supabase, "abc")

        assert isinstance(result, dict), "Deve retornar dict, não string"


class TestGetMatchResultsNative:
    """Testa a ferramenta nativa de resultados de match."""

    @pytest.mark.asyncio
    async def test_returns_matches_list(self):
        """Deve retornar dict com chave 'matches' contendo lista."""
        profile_id = str(uuid4())

        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [
            {"unified_opportunity_id": "op_1", "match_score": 0.92},
            {"unified_opportunity_id": "op_2", "match_score": 0.78},
        ]
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_resp

        from src.tools.user_data import get_match_results_native
        result = await get_match_results_native(mock_supabase, profile_id)

        assert "matches" in result
        assert isinstance(result["matches"], list)
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self):
        """O parâmetro limit deve ser passado para a query Supabase."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = []
        chain = (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .order.return_value
        )
        chain.limit.return_value.execute.return_value = mock_resp

        from src.tools.user_data import get_match_results_native
        await get_match_results_native(mock_supabase, "abc", limit=3)

        chain.limit.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_db_failure(self):
        """Falha de DB deve retornar dict com 'error' e 'matches' vazio."""
        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = Exception("timeout")

        from src.tools.user_data import get_match_results_native
        result = await get_match_results_native(mock_supabase, "abc")

        assert "error" in result
        assert result.get("matches") == []

    @pytest.mark.asyncio
    async def test_returns_dict_not_json_string(self):
        """Ferramenta nativa retorna dict Python."""
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
        result = await get_match_results_native(mock_supabase, "abc")

        assert isinstance(result, dict), "Deve retornar dict, não string"
