import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.contracts.agent_result import AgentResult
from src.contracts.reasoning_report import ReasoningReport


@pytest.mark.asyncio
async def test_response_yields_text_and_returns_result():
    from src.agents.response import run_response_agent

    fake_report = ReasoningReport(
        intent="X", data="D", reasoning="R", action="none", suggested_followups=[]
    )

    mock_chunk_final = MagicMock()
    mock_chunk_final.text = "chunk final"
    mock_chunk_final.usage_metadata = MagicMock(
        prompt_token_count=300, candidates_token_count=100
    )
    mock_chunk_middle = MagicMock()
    mock_chunk_middle.text = "chunk meio"
    mock_chunk_middle.usage_metadata = None

    async def fake_stream(*args, **kwargs):
        yield mock_chunk_middle
        yield mock_chunk_final

    with patch("src.agents.response.genai.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.aio.models.generate_content_stream = fake_stream

        chunks = []
        result = None
        async for text, agent_result in run_response_agent(fake_report, "ctx", "msg"):
            if agent_result is not None:
                result = agent_result
            else:
                chunks.append(text)

    assert "chunk meio" in chunks
    assert isinstance(result, AgentResult)
    assert result.input_tokens == 300
    assert result.output_tokens == 100
