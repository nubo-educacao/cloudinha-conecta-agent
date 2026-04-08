"""Fixtures compartilhadas para testes do pipeline Cloudinha."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from src.models.chat_request import ChatRequest, UIContext
from src.contracts.structured_plan import StructuredPlan
from src.contracts.reasoning_report import ReasoningReport


@pytest.fixture
def sample_plan() -> StructuredPlan:
    return StructuredPlan(
        intent="Usuário quer encontrar bolsas de estudo para medicina",
        intent_category="course_search",
        tools_to_use=[{"raw": "search_opportunities"}],
        context_needed="Localização e nota ENEM do usuário",
        raw="## INTENT\nBolsas medicina\n## INTENT_CATEGORY\ncourse_search\n## TOOLS_TO_USE\n- search_opportunities",
    )


@pytest.fixture
def sample_reasoning_report_text() -> str:
    return """## INTENT
Usuário busca bolsas de medicina

## DATA
- ProUni: 3.200 bolsas disponíveis para medicina
- FIES: taxa de juros 0,5% a.a.

## REASONING
O usuário tem perfil compatível com ProUni e FIES baseado nos dados de renda.

## ACTION
show_opportunities

## SUGGESTED_FOLLOWUPS
- Qual é a nota de corte para medicina pelo ProUni?
- Como funciona o processo de candidatura do FIES?
- Quais faculdades de medicina aceitam ProUni em SP?
"""


@pytest.fixture
def sample_chat_request() -> ChatRequest:
    return ChatRequest(
        chatInput="Quais bolsas tenho para medicina?",
        userId=uuid4(),
        active_profile_id=uuid4(),
        sessionId="test-session-123",
        intent_type="user_message",
        ui_context=UIContext(current_page="/oportunidades"),
    )


@pytest.fixture
def system_intent_request() -> ChatRequest:
    return ChatRequest(
        chatInput="get_starters",
        userId=uuid4(),
        active_profile_id=uuid4(),
        sessionId="test-session-sys",
        intent_type="system_intent",
        ui_context=UIContext(current_page="/"),
    )


@pytest.fixture
def mock_supabase():
    """Mock do cliente Supabase para testes unitários."""
    mock = MagicMock()
    # Encadear chamadas de query builder
    mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {}
    mock.table.return_value.insert.return_value.execute.return_value = MagicMock()
    return mock
