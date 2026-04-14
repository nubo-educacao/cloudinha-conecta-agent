import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.contracts.agent_result import AgentResult


@pytest.mark.asyncio
async def test_reasoning_emits_result_in_complete_event():
    """O evento reasoning_complete deve conter um AgentResult."""
    from src.agents.reasoning import run_reasoning_agent
    from src.contracts.structured_plan import FALLBACK_PLAN

    # Simular resposta do modelo sem function_calls (texto direto)
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [
        MagicMock(
            function_call=None,
            text="## INTENT\nX\n## DATA\ny\n## REASONING\nz\n## ACTION\nnone\n## SUGGESTED_FOLLOWUPS\n- Pergunta 1"
        )
    ]
    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata = MagicMock(prompt_token_count=200, candidates_token_count=150)

    with patch("src.agents.reasoning.get_mcp_session") as mock_mcp:
        mock_session = AsyncMock()
        mock_mcp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_mcp.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("src.agents.reasoning.list_genai_tools", return_value=[]):
            with patch("src.agents.reasoning.genai.Client") as MockClient:
                mock_client = MagicMock()
                MockClient.return_value = mock_client
                mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

                events = []
                async for event in run_reasoning_agent(FALLBACK_PLAN, "ctx", ""):
                    events.append(event)

    complete_events = [e for e in events if e.get("type") == "reasoning_complete"]
    assert len(complete_events) == 1
    assert "result" in complete_events[0]
    result = complete_events[0]["result"]
    assert isinstance(result, AgentResult)
    assert result.input_tokens >= 0
    assert result.latency_ms >= 0
