"""Unit tests para o Reasoning Agent MCP-Native.

Verifica que:
  - tool_start/tool_end são emitidos antes/depois de cada tool MCP
  - reasoning_complete carrega o texto final do LLM
  - Erros de MCP são propagados como reasoning_error (não raise)
  - A arquitetura não tem dependência direta de Supabase Client
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from google.genai import types as genai_types

from src.agents.reasoning import run_reasoning_agent
from src.contracts.structured_plan import StructuredPlan


def _make_mock_part_text(text: str):
    part = MagicMock()
    part.function_call = None
    part.function_response = None
    part.text = text
    return part


def _make_mock_part_function_call(name: str, args: dict):
    fc = MagicMock()
    fc.name = name
    fc.args = args
    part = MagicMock()
    part.function_call = fc
    part.function_response = None
    part.text = None
    return part


def _mock_mcp_session():
    """Cria um mock de ClientSession MCP."""
    session = AsyncMock()
    # list_tools retorna 2 tools fictícias
    tool1 = MagicMock()
    tool1.name = "search_opportunities"
    tool1.description = "Busca oportunidades"
    tool1.inputSchema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Termo"}},
        "required": ["query"],
    }
    tool2 = MagicMock()
    tool2.name = "get_student_profile"
    tool2.description = "Perfil do estudante"
    tool2.inputSchema = {
        "type": "object",
        "properties": {"profile_id": {"type": "string", "description": "UUID"}},
        "required": ["profile_id"],
    }
    session.list_tools.return_value = MagicMock(tools=[tool1, tool2])
    return session


@pytest.fixture
def plan_with_tools() -> StructuredPlan:
    return StructuredPlan(
        intent="Buscar bolsas para medicina",
        intent_category="course_search",
        tools_to_use=[{"raw": "search_opportunities"}],
    )


@pytest.fixture
def plan_no_tools() -> StructuredPlan:
    return StructuredPlan(
        intent="Saudação casual",
        intent_category="casual",
        tools_to_use=[],
    )


class TestReasoningAgentMcpNative:
    def test_reasoning_agent_has_no_supabase_client_import(self):
        """Arquitetura: reasoning.py NÃO deve importar supabase diretamente."""
        import importlib.util
        import ast
        import pathlib

        path = pathlib.Path(__file__).parent.parent / "src" / "agents" / "reasoning.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        supabase_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any("supabase" in (getattr(a, "name", "") or "") for a in getattr(node, "names", []))
            or (isinstance(node, ast.ImportFrom) and "supabase" in (node.module or ""))
        ]
        assert supabase_imports == [], (
            f"reasoning.py NÃO deve importar supabase. Encontrado: {supabase_imports}"
        )

    def test_reasoning_agent_imports_mcp_client(self):
        """Arquitetura: reasoning.py DEVE importar do src.mcp.client."""
        import ast
        import pathlib

        path = pathlib.Path(__file__).parent.parent / "src" / "agents" / "reasoning.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        mcp_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and "src.mcp.client" in (node.module or "")
        ]
        assert mcp_imports, "reasoning.py DEVE importar de src.mcp.client"

    @pytest.mark.asyncio
    async def test_emits_tool_start_then_tool_end_then_complete(self, plan_with_tools):
        """Ordem obrigatória: tool_start → tool_end → reasoning_complete."""
        fn_call_part = _make_mock_part_function_call(
            "search_opportunities", {"query": "medicina"}
        )
        text_part = _make_mock_part_text(
            "## INTENT\nTest\n## DATA\n-\n## REASONING\nOK\n## ACTION\nnone\n## SUGGESTED_FOLLOWUPS\n- P1?"
        )

        resp_with_call = MagicMock()
        resp_with_call.candidates = [MagicMock(content=MagicMock(parts=[fn_call_part]))]

        resp_with_text = MagicMock()
        resp_with_text.candidates = [MagicMock(content=MagicMock(parts=[text_part]))]

        mcp_session = _mock_mcp_session()
        mcp_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"results": [], "count": 0}')]
        )

        with patch("src.agents.reasoning.genai.Client") as mock_client_cls, \
             patch("src.agents.reasoning.get_mcp_session") as mock_ctx, \
             patch("src.agents.reasoning.list_genai_tools", new_callable=AsyncMock) as mock_tools, \
             patch("src.agents.reasoning.call_mcp_tool", new_callable=AsyncMock) as mock_call:

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(
                side_effect=[resp_with_call, resp_with_text]
            )

            # Mock do context manager get_mcp_session
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mcp_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_tools.return_value = []
            mock_call.return_value = {"results": [], "count": 0}

            events = []
            async for event in run_reasoning_agent(
                plan=plan_with_tools,
                lean_context="USER_ID: test\nNOME: Ana",
                few_shot_examples="",
                mcp_url="http://mock-mcp/mcp",
            ):
                events.append(event)

        types_emitted = [e["type"] for e in events]
        assert "tool_start" in types_emitted
        assert "tool_end" in types_emitted
        assert "reasoning_complete" in types_emitted

        idx_start = types_emitted.index("tool_start")
        idx_end = types_emitted.index("tool_end")
        idx_complete = types_emitted.index("reasoning_complete")
        assert idx_start < idx_end < idx_complete, (
            f"Ordem incorreta: {types_emitted}"
        )

    @pytest.mark.asyncio
    async def test_emits_reasoning_error_on_mcp_failure(self, plan_no_tools):
        """Quando MCP falha (conexão recusada), emite reasoning_error sem raise."""
        with patch("src.agents.reasoning.get_mcp_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("MCP connection refused")
            )
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            events = []
            async for event in run_reasoning_agent(
                plan=plan_no_tools,
                lean_context="USER_ID: test",
                few_shot_examples="",
                mcp_url="http://unreachable/mcp",
            ):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "reasoning_error"
        assert "error" in events[0]

    @pytest.mark.asyncio
    async def test_tool_start_event_contains_tool_name(self, plan_with_tools):
        """ToolStartEvent deve conter o nome correto da tool chamada."""
        fn_call_part = _make_mock_part_function_call(
            "get_student_profile", {"profile_id": "uuid-123"}
        )
        text_part = _make_mock_part_text(
            "## INTENT\nTest\n## DATA\n-\n## REASONING\nOK\n## ACTION\nnone\n## SUGGESTED_FOLLOWUPS\n- P?"
        )

        resp1 = MagicMock()
        resp1.candidates = [MagicMock(content=MagicMock(parts=[fn_call_part]))]
        resp2 = MagicMock()
        resp2.candidates = [MagicMock(content=MagicMock(parts=[text_part]))]

        with patch("src.agents.reasoning.genai.Client") as mock_client_cls, \
             patch("src.agents.reasoning.get_mcp_session") as mock_ctx, \
             patch("src.agents.reasoning.list_genai_tools", new_callable=AsyncMock) as mock_tools, \
             patch("src.agents.reasoning.call_mcp_tool", new_callable=AsyncMock) as mock_call:

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(
                side_effect=[resp1, resp2]
            )
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=_mock_mcp_session())
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_tools.return_value = []
            mock_call.return_value = {"profile": {"full_name": "Ana"}}

            events = []
            async for event in run_reasoning_agent(
                plan=plan_with_tools,
                lean_context="USER_ID: test",
                few_shot_examples="",
                mcp_url="http://mock/mcp",
            ):
                events.append(event)

        tool_start = next(e for e in events if e["type"] == "tool_start")
        assert tool_start["tool"] == "get_student_profile"
        assert tool_start["args"]["profile_id"] == "uuid-123"

    @pytest.mark.asyncio
    async def test_no_tools_plan_goes_direct_to_reasoning_complete(self, plan_no_tools):
        """Plano sem tools deve ir direto para reasoning_complete sem tool events."""
        report_text = "## INTENT\nSaudação\n## DATA\nnenhum\n## REASONING\nOK\n## ACTION\nnone\n## SUGGESTED_FOLLOWUPS\n- Oi?"
        text_part = _make_mock_part_text(report_text)
        response = MagicMock()
        response.candidates = [MagicMock(content=MagicMock(parts=[text_part]))]

        with patch("src.agents.reasoning.genai.Client") as mock_client_cls, \
             patch("src.agents.reasoning.get_mcp_session") as mock_ctx, \
             patch("src.agents.reasoning.list_genai_tools", new_callable=AsyncMock) as mock_tools:

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=response)
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=_mock_mcp_session())
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_tools.return_value = []

            events = []
            async for event in run_reasoning_agent(
                plan=plan_no_tools,
                lean_context="USER_ID: test\nNOME: Carlos",
                few_shot_examples="",
                mcp_url="http://mock/mcp",
            ):
                events.append(event)

        types_emitted = [e["type"] for e in events]
        assert "tool_start" not in types_emitted
        assert "tool_end" not in types_emitted
        assert "reasoning_complete" in types_emitted

        complete = next(e for e in events if e["type"] == "reasoning_complete")
        assert complete["report"] == report_text
