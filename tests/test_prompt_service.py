"""TDD: Testes do serviço de prompts dinâmicos.

Âncoras de verificação:
  1. resolve_system_prompt busca instrução do Supabase por agent_key
  2. Retorna fallback se registro não encontrado no banco
  3. Retorna fallback se conexão com banco falha (resiliência)
  4. REASONING_SYSTEM_PROMPT e RESPONSE_SYSTEM_PROMPT removidos dos módulos de agent
  5. Reasoning agent e Response agent usam resolve_system_prompt em runtime
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestResolveSystemPrompt:
    """Testa a resolução dinâmica de prompts por agent_key."""

    def test_returns_instruction_from_db(self):
        """Deve retornar a instrução do Supabase quando encontrada."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = {"system_instruction": "Você é a Cloudinha v2, prompt atualizado."}
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = mock_resp

        from src.services.prompt_service import resolve_system_prompt
        result = resolve_system_prompt(mock_supabase, "reasoning", fallback="fallback_prompt")

        assert result == "Você é a Cloudinha v2, prompt atualizado."

    def test_returns_fallback_when_not_found(self):
        """Deve retornar fallback quando agent_key não existe no banco."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = None  # not found
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = mock_resp

        from src.services.prompt_service import resolve_system_prompt
        result = resolve_system_prompt(mock_supabase, "reasoning", fallback="FALLBACK_PROMPT")

        assert result == "FALLBACK_PROMPT"

    def test_returns_fallback_on_db_error(self):
        """Deve retornar fallback quando a conexão com o banco falha (resiliência)."""
        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = Exception("connection refused")

        from src.services.prompt_service import resolve_system_prompt
        result = resolve_system_prompt(mock_supabase, "reasoning", fallback="FALLBACK_SAFE")

        assert result == "FALLBACK_SAFE", (
            "Em caso de falha de DB, o agente deve continuar com o prompt de fallback"
        )

    def test_queries_agent_prompts_table(self):
        """Deve consultar a tabela 'agent_prompts' com o agent_key correto."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = {"system_instruction": "prompt"}
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_resp

        from src.services.prompt_service import resolve_system_prompt
        resolve_system_prompt(mock_supabase, "response", fallback="fb")

        mock_supabase.table.assert_called_with("agent_prompts")
        mock_table.select.assert_called_with("system_instruction")

    def test_empty_instruction_uses_fallback(self):
        """Instrução em branco no banco deve usar o fallback."""
        mock_supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = {"system_instruction": "   "}  # only whitespace
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = mock_resp

        from src.services.prompt_service import resolve_system_prompt
        result = resolve_system_prompt(mock_supabase, "planning", fallback="FALLBACK")

        assert result == "FALLBACK"


class TestConstantsRemovedFromAgents:
    """Verifica que as constantes hard-coded foram removidas dos módulos de agent."""

    def test_reasoning_system_prompt_not_in_module(self):
        """REASONING_SYSTEM_PROMPT não deve existir como constante de módulo em reasoning.py."""
        import importlib
        import src.agents.reasoning as reasoning_module
        importlib.reload(reasoning_module)

        assert not hasattr(reasoning_module, "REASONING_SYSTEM_PROMPT"), (
            "REASONING_SYSTEM_PROMPT deve ser removida — use resolve_system_prompt() em runtime"
        )

    def test_response_system_prompt_not_in_module(self):
        """RESPONSE_SYSTEM_PROMPT não deve existir como constante de módulo em response.py."""
        import importlib
        import src.agents.response as response_module
        importlib.reload(response_module)

        assert not hasattr(response_module, "RESPONSE_SYSTEM_PROMPT"), (
            "RESPONSE_SYSTEM_PROMPT deve ser removida — use resolve_system_prompt() em runtime"
        )
