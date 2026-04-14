import pytest
from src.contracts.agent_result import AgentResult


def test_agent_result_defaults():
    result = AgentResult(text="hello", latency_ms=100)
    assert result.text == "hello"
    assert result.latency_ms == 100
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.tools_used == []


def test_agent_result_full():
    result = AgentResult(
        text="output", latency_ms=250,
        input_tokens=500, output_tokens=200,
        tools_used=[{"name": "search_opportunities", "args": {}}]
    )
    assert len(result.tools_used) == 1
    assert result.tools_used[0]["name"] == "search_opportunities"
