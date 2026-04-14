"""RED → GREEN: telemetria deve ser registrada mesmo quando MCP falha.

Âncora BUG-S5-003:
- _log_agent_turn deve ser chamado em TODA execução do pipeline
- planning_result deve conter dados reais (latency > 0) mesmo quando reasoning falha
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.workflow.engine import run_pipeline
from src.models.chat_request import ChatRequest


def make_request() -> ChatRequest:
    return ChatRequest(
        userId="00000000-0000-0000-0000-000000000001",
        sessionId="session-test",
        chatInput="Quero uma bolsa",
        active_profile_id="00000000-0000-0000-0000-000000000002",
    )


@pytest.mark.asyncio
async def test_telemetry_logged_even_when_mcp_fails():
    """_log_agent_turn deve ser chamado com planning_result preenchido mesmo com MCP falhando.

    Fluxo testado:
      Planning (sucesso, latency=120ms) → Reasoning (reasoning_error via MCP) → pipeline encerra
      Esperado: _log_agent_turn chamado com planning_result.latency_ms == 120
    """
    from src.contracts.agent_result import AgentResult
    from src.contracts.structured_plan import FALLBACK_PLAN

    mock_supabase_anon = MagicMock()
    mock_planning_result = AgentResult(
        text="plan text", latency_ms=120, input_tokens=100, output_tokens=50
    )

    async def fake_reasoning_gen(*args, **kwargs):
        yield {"type": "reasoning_error", "error": "MCP timeout"}

    with (
        patch("src.workflow.engine.get_supabase_service", return_value=MagicMock()),
        patch("src.workflow.engine._load_profile", new_callable=AsyncMock, return_value={}),
        patch("src.workflow.engine.build_lean_context", return_value="ctx"),
        patch("src.workflow.engine.resolve_system_prompt", return_value=""),
        patch(
            "src.workflow.engine.retrieve_few_shot_examples",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch("src.workflow.engine.SupabaseSessionService") as mock_session_cls,
        patch(
            "src.workflow.engine.run_planning_agent",
            new_callable=AsyncMock,
            return_value=(FALLBACK_PLAN, mock_planning_result),
        ),
        patch(
            "src.workflow.engine.run_reasoning_agent",
            return_value=fake_reasoning_gen(),
        ),
        patch("src.workflow.engine._log_agent_turn") as mock_log,
    ):
        mock_session = MagicMock()
        mock_session.get_recent_messages.return_value = []
        mock_session_cls.return_value = mock_session

        events = []
        async for event in run_pipeline(make_request(), mock_supabase_anon):
            events.append(event)

    # _log_agent_turn deve ter sido chamado exatamente 1 vez
    assert mock_log.called, "_log_agent_turn não foi chamado mesmo com MCP falhando"
    assert mock_log.call_count == 1, f"_log_agent_turn chamado {mock_log.call_count}x (esperado 1x)"

    call_kwargs = mock_log.call_args.kwargs
    planning_result = call_kwargs.get("planning_result")

    assert planning_result is not None, "planning_result não foi passado para _log_agent_turn"
    assert planning_result.latency_ms == 120, (
        f"planning_result.latency_ms deveria ser 120 (dados reais), mas foi {planning_result.latency_ms} "
        f"(zero = telemetria zerada — BUG-S5-003 não resolvido)"
    )
    assert planning_result.input_tokens == 100
