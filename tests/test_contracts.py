"""Unit tests para parsers de contratos (StructuredPlan e ReasoningReport).

Âncora: parsers devem validar o end-state dos contratos produzidos pelos agentes.
Inclui testes de contrato negativo (inputs inválidos).
"""
import pytest
from src.contracts.structured_plan import (
    parse_structured_plan,
    StructuredPlan,
    VALID_CATEGORIES,
    FALLBACK_PLAN,
)
from src.contracts.reasoning_report import (
    parse_reasoning_report,
    extract_suggestions,
    ReasoningReport,
)


# ─── StructuredPlan ────────────────────────────────────────────────────────────

class TestParseStructuredPlan:
    def test_parse_valid_full_plan(self):
        raw = """## INTENT
Usuário quer bolsas para medicina

## INTENT_CATEGORY
course_search

## TOOLS_TO_USE
- search_opportunities
- get_student_profile

## CONTEXT_NEEDED
Nota ENEM e renda familiar"""

        plan = parse_structured_plan(raw)

        assert plan.intent == "Usuário quer bolsas para medicina"
        assert plan.intent_category == "course_search"
        assert len(plan.tools_to_use) == 2
        assert plan.tools_to_use[0]["raw"] == "search_opportunities"
        assert plan.context_needed == "Nota ENEM e renda familiar"
        assert plan.raw == raw

    def test_parse_minimal_plan(self):
        raw = """## INTENT
Saudação casual

## INTENT_CATEGORY
casual"""
        plan = parse_structured_plan(raw)
        assert plan.intent == "Saudação casual"
        assert plan.intent_category == "casual"
        assert plan.tools_to_use == []
        assert plan.context_needed is None

    def test_all_valid_categories_accepted(self):
        for category in VALID_CATEGORIES:
            raw = f"## INTENT\nTest\n## INTENT_CATEGORY\n{category}"
            plan = parse_structured_plan(raw)
            assert plan.intent_category == category

    def test_unknown_category_falls_back_to_general_qa(self):
        raw = "## INTENT\nTest\n## INTENT_CATEGORY\nunknown_category"
        plan = parse_structured_plan(raw)
        assert plan.intent_category == "general_qa"

    def test_missing_intent_raises_value_error(self):
        """Contrato negativo: INTENT ausente deve levantar ValueError."""
        raw = "## INTENT_CATEGORY\ncourse_search"
        with pytest.raises(ValueError, match="INTENT ausente"):
            parse_structured_plan(raw)

    def test_empty_string_raises_value_error(self):
        """Contrato negativo: string vazia deve levantar ValueError."""
        with pytest.raises(ValueError):
            parse_structured_plan("")

    def test_no_tools_section_returns_empty_list(self):
        raw = "## INTENT\nPergunta\n## INTENT_CATEGORY\ngeneral_qa"
        plan = parse_structured_plan(raw)
        assert plan.tools_to_use == []

    def test_fallback_plan_is_valid(self):
        """FALLBACK_PLAN deve ser sempre um StructuredPlan válido."""
        assert isinstance(FALLBACK_PLAN, StructuredPlan)
        assert FALLBACK_PLAN.intent_category == "general_qa"
        assert FALLBACK_PLAN.intent != ""


# ─── ReasoningReport ──────────────────────────────────────────────────────────

class TestParseReasoningReport:
    VALID_REPORT = """## INTENT
Usuário busca bolsas de medicina

## DATA
ProUni: 3.200 bolsas disponíveis

## REASONING
Perfil compatível com ProUni

## ACTION
show_opportunities

## SUGGESTED_FOLLOWUPS
- Qual é a nota de corte?
- Como funciona o FIES?
- Quais faculdades aceitam ProUni em SP?
"""

    def test_parse_full_report(self):
        report = parse_reasoning_report(self.VALID_REPORT)

        assert "bolsas de medicina" in report.intent
        assert "ProUni" in report.data
        assert "compatível" in report.reasoning
        assert report.action == "show_opportunities"
        assert len(report.suggested_followups) == 3
        assert "nota de corte" in report.suggested_followups[0]

    def test_parse_empty_report_returns_defaults(self):
        """Contrato negativo: relatório vazio retorna ReasoningReport com defaults."""
        report = parse_reasoning_report("")
        assert isinstance(report, ReasoningReport)
        assert report.intent == ""
        assert report.action == "none"
        assert report.suggested_followups == []

    def test_action_defaults_to_none_when_absent(self):
        raw = "## INTENT\nTest\n## DATA\nDados"
        report = parse_reasoning_report(raw)
        assert report.action == "none"

    def test_suggested_followups_parsed_correctly(self, sample_reasoning_report_text):
        report = parse_reasoning_report(sample_reasoning_report_text)
        assert len(report.suggested_followups) == 3
        for item in report.suggested_followups:
            assert item  # nenhum item vazio
            assert not item.startswith("-")  # prefixo removido


class TestExtractSuggestions:
    def test_extract_from_valid_report(self, sample_reasoning_report_text):
        suggestions = extract_suggestions(sample_reasoning_report_text)
        assert len(suggestions) == 3
        assert all(isinstance(s, str) for s in suggestions)
        assert all(len(s) > 0 for s in suggestions)

    def test_extract_returns_empty_when_section_absent(self):
        """Contrato negativo: sem seção SUGGESTED_FOLLOWUPS retorna lista vazia."""
        raw = "## INTENT\nTest\n## DATA\nDados sem followups"
        result = extract_suggestions(raw)
        assert result == []

    def test_extract_strips_dash_prefix(self, sample_reasoning_report_text):
        suggestions = extract_suggestions(sample_reasoning_report_text)
        for s in suggestions:
            assert not s.startswith("-")
