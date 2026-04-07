import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StructuredPlan:
    intent: str
    intent_category: str  # course_search | eligibility_query | application_help | form_support | general_qa | system_intent | casual
    tools_to_use: List[dict] = field(default_factory=list)
    context_needed: Optional[str] = None
    raw: str = ""


VALID_CATEGORIES = {
    "course_search",
    "eligibility_query",
    "application_help",
    "form_support",
    "general_qa",
    "system_intent",
    "casual",
}

FALLBACK_PLAN = StructuredPlan(
    intent="Responder a pergunta geral do usuário",
    intent_category="general_qa",
    tools_to_use=[],
    context_needed=None,
    raw="## INTENT\nResposta geral\n## INTENT_CATEGORY\ngeneral_qa",
)


def parse_structured_plan(raw: str) -> StructuredPlan:
    """Extrai seções do Markdown estruturado do Planning Agent."""
    sections: dict[str, list[str]] = {}
    current = None

    for line in raw.split("\n"):
        header = re.match(r"^## (.+)", line)
        if header:
            current = header.group(1).strip()
            sections[current] = []
        elif current:
            sections[current].append(line)

    intent = "\n".join(sections.get("INTENT", [])).strip()
    category_raw = "\n".join(sections.get("INTENT_CATEGORY", [])).strip()
    tools_raw = sections.get("TOOLS_TO_USE", [])
    context = "\n".join(sections.get("CONTEXT_NEEDED", [])).strip() or None

    if not intent:
        raise ValueError("StructuredPlan inválido: INTENT ausente")

    category = category_raw if category_raw in VALID_CATEGORIES else "general_qa"

    tools: List[dict] = []
    for line in tools_raw:
        line = line.strip()
        if line.startswith("- "):
            tools.append({"raw": line[2:]})

    return StructuredPlan(
        intent=intent,
        intent_category=category,
        tools_to_use=tools,
        context_needed=context,
        raw=raw,
    )
