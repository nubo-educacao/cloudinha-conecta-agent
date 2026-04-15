import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.agents.planning import run_planning_agent
from src.contracts.agent_result import AgentResult
from src.contracts.structured_plan import StructuredPlan


@pytest.mark.asyncio
async def test_planning_returns_tuple():
    """run_planning_agent deve retornar (StructuredPlan, AgentResult)."""

    mock_response = MagicMock()
    mock_response.text = """## INTENT\nBusca de cursos\n## INTENT_CATEGORY\ncourse_search\n## TOOLS_TO_USE\n- search_opportunities\n## CONTEXT_NEEDED\nnenhum"""
    mock_response.usage_metadata = MagicMock(
        prompt_token_count=120,
        candidates_token_count=80
    )

    with patch("src.agents.planning.genai.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        plan, result = await run_planning_agent("quero uma bolsa", "contexto fake")

    assert isinstance(plan, StructuredPlan)
    assert isinstance(result, AgentResult)
    assert result.input_tokens == 120
    assert result.output_tokens == 80
    assert result.latency_ms >= 0
    assert result.text != ""


@pytest.mark.asyncio
async def test_planning_logs_to_console(caplog):
    """Deve emitir log INFO com latency e tokens."""
    import logging
    mock_response = MagicMock()
    mock_response.text = """## INTENT\nX\n## INTENT_CATEGORY\ncasual\n## TOOLS_TO_USE\n- nenhuma\n## CONTEXT_NEEDED\nnenhum"""
    mock_response.usage_metadata = MagicMock(prompt_token_count=50, candidates_token_count=30)

    with patch("src.agents.planning.genai.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with caplog.at_level(logging.INFO, logger="src.agents.planning"):
            await run_planning_agent("oi", "ctx")

    assert any("[Planning]" in r.message for r in caplog.records)
