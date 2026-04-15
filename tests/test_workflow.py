"""Integration tests do pipeline Planning→Reasoning→Response.

Âncora PRD:
- POST /chat retorna stream NDJSON válido
- System Intent com intent_type=system_intent NÃO persiste em chat_messages
- Suggestions emitidas ANTES do stream de resposta terminar (i.e., após o texto)
- Fallback emitido quando Reasoning retorna vazio
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.contracts.agent_result import AgentResult

from src.models.chat_request import ChatRequest, UIContext
from src.workflow.engine import run_pipeline
from src.workflow.system_intents import is_system_intent, handle_system_intent

# Mock global para prompt_service (impede chamada ao Supabase em testes)
@pytest.fixture(autouse=True)
def mock_prompt_service():
    with patch("src.workflow.engine.resolve_system_prompt", return_value="") as mock:
        yield mock


# ─── System Intent ────────────────────────────────────────────────────────────

class TestSystemIntentInterceptor:
    def test_is_system_intent_returns_true_for_system_type(self, system_intent_request):
        assert is_system_intent(system_intent_request) is True

    def test_is_system_intent_returns_false_for_user_message(self, sample_chat_request):
        assert is_system_intent(sample_chat_request) is False

    @pytest.mark.asyncio
    async def test_system_intent_ping_returns_pong(self):
        req = ChatRequest(
            chatInput="ping",
            userId=uuid4(),
            active_profile_id=uuid4(),
            sessionId="sys-test",
            intent_type="system_intent",
        )
        mock_supabase = MagicMock()
        result = await handle_system_intent(req, mock_supabase)
        assert result["type"] == "pong"

    @pytest.mark.asyncio
    async def test_lightweight_system_intent_does_not_persist(self):
        """Intents leves (ping, etc) NÃO devem persistir no banco."""
        mock_supabase = MagicMock()
        req = ChatRequest(
            chatInput="ping",
            userId=uuid4(),
            active_profile_id=uuid4(),
            sessionId="sys-test",
            intent_type="system_intent",
        )
        await handle_system_intent(req, mock_supabase)

        # insert NUNCA deve ser chamado para intents leves
        insert_calls = [
            call for call in mock_supabase.method_calls
            if "insert" in str(call) and "chat_messages" in str(call)
        ]
        assert len(insert_calls) == 0


# ─── Pipeline Integration ─────────────────────────────────────────────────────

MOCK_PLANNING_OUTPUT = """## INTENT
Usuário busca bolsas de medicina

## INTENT_CATEGORY
course_search

## TOOLS_TO_USE
- search_opportunities

## CONTEXT_NEEDED
Nota ENEM"""

MOCK_REASONING_EVENTS = [
    {"type": "tool_start", "tool": "search_opportunities", "args": {"query": "medicina"}},
    {"type": "tool_end", "tool": "search_opportunities", "output": '{"results": [], "count": 0}'},
    {"type": "reasoning_complete", "report": """## INTENT
Bolsas medicina

## DATA
Sem resultados encontrados

## REASONING
Não há bolsas cadastradas para medicina no momento

## ACTION
none

## SUGGESTED_FOLLOWUPS
- Quais cursos têm mais bolsas disponíveis?
- Como funciona o ProUni?
- Posso me inscrever no FIES?
"""},
]

MOCK_RESPONSE_CHUNKS = ["Olá! ", "Encontrei algumas informações ", "sobre bolsas para medicina."]
_EMPTY_AGENT_RESULT = AgentResult(text="", latency_ms=0)


class TestPipelineIntegration:
    @pytest.fixture
    def mock_supabase_with_profile(self):
        """Supabase mock que retorna dados de perfil mínimos."""
        mock = MagicMock()
        # user_profiles
        profile_mock = MagicMock()
        profile_mock.data = {"full_name": "Ana Silva", "birth_date": "2000-01-01"}
        mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = profile_mock
        # users_metadata
        meta_mock = MagicMock()
        meta_mock.data = None
        # chat_messages recent
        hist_mock = MagicMock()
        hist_mock.data = []
        mock.table.return_value.insert.return_value.execute.return_value = MagicMock()
        return mock

    @pytest.mark.asyncio
    async def test_pipeline_emits_text_events(self, sample_chat_request):
        """Pipeline deve emitir pelo menos 1 evento de tipo 'text'."""
        with (
            patch("src.workflow.engine.run_planning_agent", new_callable=AsyncMock) as mock_plan,
            patch("src.workflow.engine.run_reasoning_agent") as mock_reasoning,
            patch("src.workflow.engine.run_response_agent") as mock_response,
            patch("src.workflow.engine._load_profile", new_callable=AsyncMock) as mock_profile,
            patch("src.workflow.engine.retrieve_few_shot_examples", new_callable=AsyncMock) as mock_fs,
            patch("src.workflow.engine.get_supabase_service") as mock_svc,
        ):
            from src.contracts.structured_plan import StructuredPlan, FALLBACK_PLAN
            mock_plan.return_value = (FALLBACK_PLAN, _EMPTY_AGENT_RESULT)
            mock_fs.return_value = ""
            mock_profile.return_value = {"full_name": "Ana", "age": 24}
            mock_svc.return_value = MagicMock()

            async def mock_reasoning_gen(*args, **kwargs):
                for event in MOCK_REASONING_EVENTS:
                    yield event

            async def mock_response_gen(*args, **kwargs):
                for chunk in MOCK_RESPONSE_CHUNKS:
                    yield chunk, None
                yield "", _EMPTY_AGENT_RESULT

            mock_reasoning.return_value = mock_reasoning_gen()
            mock_response.return_value = mock_response_gen()

            mock_supabase = MagicMock()
            mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
            mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

            events = []
            async for event in run_pipeline(sample_chat_request, mock_supabase):
                events.append(event)

        text_events = [e for e in events if e["type"] == "text"]
        assert len(text_events) >= 1

    @pytest.mark.asyncio
    async def test_suggestions_emitted_after_text(self, sample_chat_request):
        """Suggestions devem ser emitidas APÓS os eventos de texto."""
        with (
            patch("src.workflow.engine.run_planning_agent", new_callable=AsyncMock) as mock_plan,
            patch("src.workflow.engine.run_reasoning_agent") as mock_reasoning,
            patch("src.workflow.engine.run_response_agent") as mock_response,
            patch("src.workflow.engine._load_profile", new_callable=AsyncMock) as mock_profile,
            patch("src.workflow.engine.retrieve_few_shot_examples", new_callable=AsyncMock) as mock_fs,
            patch("src.workflow.engine.get_supabase_service") as mock_svc,
        ):
            from src.contracts.structured_plan import FALLBACK_PLAN
            mock_plan.return_value = (FALLBACK_PLAN, _EMPTY_AGENT_RESULT)
            mock_fs.return_value = ""
            mock_profile.return_value = {"full_name": "Carlos", "age": 20}
            mock_svc.return_value = MagicMock()

            async def mock_reasoning_gen(*args, **kwargs):
                for event in MOCK_REASONING_EVENTS:
                    yield event

            async def mock_response_gen(*args, **kwargs):
                for chunk in MOCK_RESPONSE_CHUNKS:
                    yield chunk, None
                yield "", _EMPTY_AGENT_RESULT

            mock_reasoning.return_value = mock_reasoning_gen()
            mock_response.return_value = mock_response_gen()

            mock_supabase = MagicMock()
            mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
            mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

            events = []
            async for event in run_pipeline(sample_chat_request, mock_supabase):
                events.append(event)

        types = [e["type"] for e in events]
        if "suggestions" in types and "text" in types:
            last_text_idx = max(i for i, t in enumerate(types) if t == "text")
            suggestions_idx = types.index("suggestions")
            assert suggestions_idx > last_text_idx, "Suggestions devem vir após o texto"

    @pytest.mark.asyncio
    async def test_ndjson_events_are_valid_json(self, sample_chat_request):
        """Todos os eventos do pipeline devem ser serializáveis como JSON."""
        with (
            patch("src.workflow.engine.run_planning_agent", new_callable=AsyncMock) as mock_plan,
            patch("src.workflow.engine.run_reasoning_agent") as mock_reasoning,
            patch("src.workflow.engine.run_response_agent") as mock_response,
            patch("src.workflow.engine._load_profile", new_callable=AsyncMock) as mock_profile,
            patch("src.workflow.engine.retrieve_few_shot_examples", new_callable=AsyncMock) as mock_fs,
            patch("src.workflow.engine.get_supabase_service") as mock_svc,
        ):
            from src.contracts.structured_plan import FALLBACK_PLAN
            mock_plan.return_value = (FALLBACK_PLAN, _EMPTY_AGENT_RESULT)
            mock_fs.return_value = ""
            mock_profile.return_value = {"full_name": "Maria"}
            mock_svc.return_value = MagicMock()

            async def mock_reasoning_gen(*args, **kwargs):
                yield {"type": "reasoning_complete", "report": "## INTENT\nTest\n## DATA\n-\n## REASONING\nok\n## ACTION\nnone\n## SUGGESTED_FOLLOWUPS\n"}

            async def mock_response_gen(*args, **kwargs):
                yield "Resposta de teste", None
                yield "", _EMPTY_AGENT_RESULT

            mock_reasoning.return_value = mock_reasoning_gen()
            mock_response.return_value = mock_response_gen()

            mock_supabase = MagicMock()
            mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
            mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

            events = []
            async for event in run_pipeline(sample_chat_request, mock_supabase):
                events.append(event)

        for event in events:
            # Deve serializar sem erros
            serialized = json.dumps(event, ensure_ascii=False)
            reparsed = json.loads(serialized)
            assert reparsed["type"] in {"text", "tool_start", "tool_end", "suggestions", "error"}

    @pytest.mark.asyncio
    async def test_pipeline_persists_system_message(self):
        """Pipeline deve persistir com sender='system' quando intent_type é system_intent_pipeline."""
        req = ChatRequest(
            chatInput="Trigger message",
            userId=uuid4(),
            active_profile_id=uuid4(),
            sessionId="sys-test",
            intent_type="system_intent_pipeline",
        )
        
        mock_supabase = MagicMock()
        # Mock para o histórico recente
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        # Mock para o perfil
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"full_name": "Test"}
        
        with (
            patch("src.workflow.engine.run_planning_agent", new_callable=AsyncMock) as mock_plan,
            patch("src.workflow.engine.run_reasoning_agent") as mock_reasoning,
            patch("src.workflow.engine.run_response_agent") as mock_response,
            patch("src.workflow.engine.resolve_system_prompt", return_value=""),
            patch("src.workflow.engine.retrieve_few_shot_examples", return_value=""),
            patch("src.workflow.engine.get_supabase_service", return_value=mock_supabase),
        ):
            from src.contracts.structured_plan import FALLBACK_PLAN
            mock_plan.return_value = (FALLBACK_PLAN, _EMPTY_AGENT_RESULT)
            
            async def empty_gen(*args, **kwargs):
                yield {"type": "reasoning_complete", "report": "..."}
                if False: yield # Deixa o gerador ser um async generator
                
            async def resp_gen(*args, **kwargs):
                yield "ok", None
                yield "", _EMPTY_AGENT_RESULT

            mock_reasoning.return_value = empty_gen()
            mock_response.return_value = resp_gen()

            async for _ in run_pipeline(req, mock_supabase):
                pass

        # Verificar se insert foi chamado com sender='system'
        # Usamos call_args_list para garantir que pegamos a chamada correta mesmo com múltiplos inserts
        insert_calls = mock_supabase.table.return_value.insert.call_args_list
        system_insert = next(
            (call[0][0] for call in insert_calls if call[0][0].get("sender") == "system"),
            None
        )
        assert system_insert is not None, "Chamada de insert com sender='system' não encontrada"
        assert system_insert["content"] == "Trigger message"
