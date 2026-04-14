"""Unit tests para o Planning Agent com mock do LLM.

O Planning Agent deve classificar intenções corretamente e aplicar fallback
quando o modelo retorna output malformado.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.agents.planning import run_planning_agent, _call_planning
from src.contracts.structured_plan import FALLBACK_PLAN, VALID_CATEGORIES


MOCK_VALID_PLAN_RESPONSE = """## INTENT
Usuário quer saber quais bolsas existem para o curso de medicina

## INTENT_CATEGORY
course_search

## TOOLS_TO_USE
- search_opportunities
- get_student_profile

## CONTEXT_NEEDED
Nota ENEM e preferência de estado"""

MOCK_CASUAL_RESPONSE = """## INTENT
Usuário está fazendo uma saudação informal

## INTENT_CATEGORY
casual

## TOOLS_TO_USE
- nenhuma

## CONTEXT_NEEDED
nenhum"""

MOCK_INVALID_RESPONSE = "Resposta sem estrutura de markdown alguma"


class TestPlanningAgent:
    @pytest.mark.asyncio
    async def test_classifies_course_search_correctly(self):
        """Planning deve classificar perguntas sobre cursos como course_search."""
        mock_response = MagicMock()
        mock_response.text = MOCK_VALID_PLAN_RESPONSE

        with patch("src.agents.planning.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            plan, _ = await run_planning_agent(
                user_message="Quais bolsas tenho para medicina?",
                lean_context="USER_ID: test\nNOME: Ana",
            )

        assert plan.intent_category == "course_search"
        assert "medicina" in plan.intent.lower()
        assert any(t["raw"] == "search_opportunities" for t in plan.tools_to_use)

    @pytest.mark.asyncio
    async def test_classifies_casual_correctly(self):
        """Planning deve classificar saudações como casual."""
        mock_response = MagicMock()
        mock_response.text = MOCK_CASUAL_RESPONSE

        with patch("src.agents.planning.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            plan, _ = await run_planning_agent(
                user_message="Oi tudo bem?",
                lean_context="USER_ID: test\nNOME: Carlos",
            )

        assert plan.intent_category == "casual"
        assert plan.tools_to_use == [] or plan.tools_to_use[0]["raw"] == "nenhuma"

    @pytest.mark.asyncio
    async def test_uses_fallback_plan_when_llm_returns_invalid_output(self):
        """Planning deve retornar FALLBACK_PLAN após 2 tentativas com output malformado."""
        mock_response = MagicMock()
        mock_response.text = MOCK_INVALID_RESPONSE

        with patch("src.agents.planning.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            # Ambas as tentativas retornam output inválido
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            plan, _ = await run_planning_agent(
                user_message="mensagem qualquer",
                lean_context="USER_ID: test\nNOME: Maria",
            )

        assert plan is FALLBACK_PLAN
        assert plan.intent_category == "general_qa"

    @pytest.mark.asyncio
    async def test_retries_once_on_parse_failure_then_succeeds(self):
        """Após 1 falha de parse, Planning deve tentar novamente com prompt corretivo."""
        invalid_response = MagicMock()
        invalid_response.text = MOCK_INVALID_RESPONSE

        valid_response = MagicMock()
        valid_response.text = MOCK_VALID_PLAN_RESPONSE

        with patch("src.agents.planning.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            # Primeira chamada retorna inválido, segunda retorna válido
            mock_client.aio.models.generate_content = AsyncMock(
                side_effect=[invalid_response, valid_response]
            )

            plan, _ = await run_planning_agent(
                user_message="Quero bolsas",
                lean_context="USER_ID: test\nNOME: Pedro",
            )

        assert plan.intent_category == "course_search"
        assert mock_client.aio.models.generate_content.call_count == 2

    @pytest.mark.asyncio
    async def test_all_intent_categories_are_valid(self):
        """Cada categoria retornada pelo planning deve pertencer ao conjunto válido."""
        for category in VALID_CATEGORIES:
            mock_response = MagicMock()
            mock_response.text = (
                f"## INTENT\nTest intent\n## INTENT_CATEGORY\n{category}"
            )
            with patch("src.agents.planning.genai.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client_cls.return_value = mock_client
                mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

                plan, _ = await run_planning_agent("test", "USER_ID: x")

            assert plan.intent_category in VALID_CATEGORIES
