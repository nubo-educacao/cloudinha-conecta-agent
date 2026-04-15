import pytest
from unittest.mock import AsyncMock, MagicMock
from src.workflow.system_intents import handle_system_intent
from src.models.chat_request import ChatRequest
import uuid


def make_page_context_request(route: str, page_data: dict = {}):
    return ChatRequest(
        userId=uuid.uuid4(),
        sessionId="session-abc",
        chatInput="page_context",
        intent_type="system_intent",
        active_profile_id=uuid.uuid4(),
        ui_context={
            "current_page": route,
            "page_data": page_data,
        },
    )


@pytest.mark.asyncio
async def test_page_context_opportunity_returns_pipeline_intent():
    """page_context em rota com match ativo deve retornar PipelineIntent com open_drawer=True."""
    from src.workflow.system_intents import PipelineIntent

    mock_supabase = MagicMock()

    # Query: .table("system_intents").select().eq("command", "page_context").eq("is_active", True).execute()
    # Cadeia real: .table().select().eq().eq().execute()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "trigger_route": r"/partner-opportunities/.*",
            "trigger_message": "O usuário está visualizando uma oportunidade de bolsa.",
            "open_drawer": True,
            "delay_ms": 3000,
        }]
    )

    request = make_page_context_request(
        route="/partner-opportunities/abc-123",
        page_data={"opportunity_id": "abc-123"},
    )
    result = await handle_system_intent(request, mock_supabase)

    assert isinstance(result, PipelineIntent), (
        f"Esperava PipelineIntent mas recebeu {type(result).__name__}: {result}"
    )
    assert result.open_drawer is True
    assert len(result.trigger_message) > 10  # mensagem não vazia


@pytest.mark.asyncio
async def test_page_context_unknown_route_returns_generic():
    """page_context em rota desconhecida retorna mensagem genérica sem open_drawer."""
    mock_supabase = MagicMock()
    request = make_page_context_request(route="/perfil")

    result = await handle_system_intent(request, mock_supabase)

    # Rota desconhecida → ack genérico ou get_starters
    assert result["type"] in ("system_ack", "starters", "system_message")
    # open_drawer = False para rotas desconhecidas (não interromper o usuário sem contexto)
    assert result.get("open_drawer", False) is False
