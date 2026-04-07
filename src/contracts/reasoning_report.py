import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ReasoningReport:
    intent: str = ""
    data: str = ""
    reasoning: str = ""
    action: str = "none"
    suggested_followups: List[str] = field(default_factory=list)
    raw: str = ""


def parse_reasoning_report(raw: str) -> ReasoningReport:
    """Extrai seções do Markdown estruturado do Reasoning Agent."""
    sections: dict[str, list[str]] = {}
    current = None

    for line in raw.split("\n"):
        header = re.match(r"^## (.+)", line)
        if header:
            current = header.group(1).strip()
            sections[current] = []
        elif current:
            sections[current].append(line)

    return ReasoningReport(
        intent="\n".join(sections.get("INTENT", [])).strip(),
        data="\n".join(sections.get("DATA", [])).strip(),
        reasoning="\n".join(sections.get("REASONING", [])).strip(),
        action="\n".join(sections.get("ACTION", [])).strip() or "none",
        suggested_followups=_parse_followups(sections.get("SUGGESTED_FOLLOWUPS", [])),
        raw=raw,
    )


def extract_suggestions(reasoning_report: str) -> List[str]:
    """Micro-parser para extrair chips em microssegundos (regex pura, zero LLM)."""
    match = re.search(r"## SUGGESTED_FOLLOWUPS\n((?:- .+\n?)+)", reasoning_report)
    if not match:
        return []
    return [
        line.lstrip("- ").strip()
        for line in match.group(1).strip().split("\n")
        if line.strip()
    ]


def _parse_followups(lines: list) -> List[str]:
    return [line.lstrip("- ").strip() for line in lines if line.strip().startswith("- ")]
