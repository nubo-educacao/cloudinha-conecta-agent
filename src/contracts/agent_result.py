"""Contrato de retorno padronizado para todos os agents do pipeline."""
from dataclasses import dataclass, field


@dataclass
class AgentResult:
    """Metadados de execução de um agente individual.

    Usado para transportar o output textual + métricas de execução
    de planning/reasoning/response de volta ao engine para telemetria.
    """
    text: str
    """Output textual bruto do agente."""

    latency_ms: int
    """Tempo de execução em milissegundos."""

    input_tokens: int = 0
    """Tokens de entrada (usage_metadata.prompt_token_count)."""

    output_tokens: int = 0
    """Tokens de saída (usage_metadata.candidates_token_count)."""

    tools_used: list[dict] = field(default_factory=list)
    """Lista de tools chamadas. Apenas o Reasoning Agent popula este campo.
    Formato: [{"name": "tool_name", "args": {...}}]
    """
