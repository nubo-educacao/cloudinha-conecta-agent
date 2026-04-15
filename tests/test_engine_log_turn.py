import pytest
from unittest.mock import MagicMock
from src.workflow.engine import _log_agent_turn, _estimate_cost
from src.contracts.agent_result import AgentResult
from src.models.chat_request import ChatRequest


def make_request():
    return ChatRequest(
        userId="00000000-0000-0000-0000-000000000001",
        sessionId="session-abc",
        chatInput="Quero uma bolsa",
        active_profile_id="00000000-0000-0000-0000-000000000002",
    )


def test_log_agent_turn_inserts_all_fields():
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.execute.return_value = MagicMock()

    planning_result = AgentResult(text="plan text", latency_ms=120, input_tokens=100, output_tokens=50)
    reasoning_result = AgentResult(
        text="reasoning text", latency_ms=800, input_tokens=500, output_tokens=300,
        tools_used=[{"name": "search_opportunities", "args": {}}]
    )
    response_result = AgentResult(text="response text", latency_ms=400, input_tokens=200, output_tokens=150)

    _log_agent_turn(
        supabase=mock_supabase,
        request=make_request(),
        total_latency_ms=1320,
        planning_result=planning_result,
        reasoning_result=reasoning_result,
        response_result=response_result,
        intent_category="course_search",
        reasoning_report="## INTENT\nBusca...",
        action="none",
    )

    mock_supabase.table.assert_called_with("agent_turns")
    call_args = mock_table.insert.call_args[0][0]

    # Verificar todos os campos obrigatórios
    required_fields = [
        "user_id", "session_id", "total_latency_ms",
        "planning_latency_ms", "reasoning_latency_ms", "response_latency_ms",
        "input_tokens", "output_tokens", "tools_used",
        "intent_category", "reasoning_report", "action",
        "planning_output", "reasoning_output", "response_output",
        "estimated_cost_usd",
    ]
    for field in required_fields:
        assert field in call_args, f"Campo ausente no INSERT: {field}"

    assert call_args["planning_latency_ms"] == 120
    assert call_args["reasoning_latency_ms"] == 800
    assert call_args["response_latency_ms"] == 400
    assert call_args["input_tokens"] == 800   # 100+500+200
    assert call_args["output_tokens"] == 500  # 50+300+150
    assert call_args["tools_used"] == [{"name": "search_opportunities", "args": {}}]
    assert call_args["intent_category"] == "course_search"
    assert call_args["planning_output"] == "plan text"
    assert call_args["reasoning_output"] == "reasoning text"
    assert call_args["response_output"] == "response text"
    assert isinstance(call_args["estimated_cost_usd"], float)


def test_estimate_cost():
    result = AgentResult(text="", latency_ms=100, input_tokens=1_000_000, output_tokens=1_000_000)
    cost = _estimate_cost(result)
    assert cost == pytest.approx(0.075 + 0.30, rel=1e-3)
