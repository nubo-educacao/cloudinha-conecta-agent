"""In-process MCP tool execution — bypasses HTTP loopback for Cloud Run.

Quando o MCP_SERVER_URL aponta para localhost (Cloud Run não suporta loopback
confiável), o Reasoning Agent chama as tools diretamente sem HTTP.

Expõe a mesma interface de `client.py`:
  - list_genai_tools_in_process()
  - call_mcp_tool_in_process(name, args)
"""
import json
import logging

from google.genai import types

from src.mcp.client import _json_schema_to_genai

logger = logging.getLogger(__name__)


def _get_mcp_tool_manager():
    """Importação lazy do mcp server para evitar circular imports na inicialização."""
    from src.mcp.server import mcp as _mcp  # noqa: PLC0415
    return _mcp._tool_manager


async def list_genai_tools_in_process() -> list[types.Tool]:
    """Lista tools do MCP Server diretamente (sem HTTP)."""
    try:
        tool_manager = _get_mcp_tool_manager()
        tools = tool_manager.list_tools()
        declarations = []
        for tool in tools:
            try:
                schema = _json_schema_to_genai(tool.parameters or {})
                declarations.append(
                    types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description or "",
                        parameters=schema,
                    )
                )
            except Exception as e:
                logger.warning(f"[in-process] Falha ao converter schema da tool {tool.name}: {e}")
        if not declarations:
            return []
        return [types.Tool(function_declarations=declarations)]
    except Exception as e:
        logger.error(f"[in-process] Erro ao listar tools: {e}")
        return []


async def call_mcp_tool_in_process(name: str, args: dict) -> dict:
    """Executa uma tool MCP diretamente (sem HTTP).

    Retorna dict compatível com call_mcp_tool() de client.py.
    """
    try:
        tool_manager = _get_mcp_tool_manager()
        result = await tool_manager.call_tool(name, args, convert_result=True)

        logger.info(f"[in-process] tool={name} result_type={type(result).__name__} result={repr(result)[:200]}")

        # Extrair texto do resultado — suporta múltiplos formatos de retorno
        combined = _extract_text(result)

        if not combined:
            return {"result": ""}

        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            return {"result": combined}

    except Exception as e:
        logger.error(f"[in-process] Erro ao chamar tool '{name}': {e}", exc_info=True)
        return {"error": str(e), "tool": name}


def _extract_text(result) -> str:
    """Extrai texto de qualquer formato de retorno do FastMCP.

    Suporta:
      - str (retorno bruto sem convert_result)
      - tuple (unstructured, structured) — FastMCP convert_result com output_schema
      - list[TextContent] (retorno com convert_result=True sem output_schema)
      - CallToolResult (retorno em versões futuras do MCP)
      - None / falsy
    """
    if not result:
        return ""

    # Caso 1: resultado já é string (convert_result=False ou versão antiga)
    if isinstance(result, str):
        return result

    # Caso 2: tuple (unstructured_content, structured_output) do convert_result
    if isinstance(result, tuple):
        result = result[0]  # pegar a lista de TextContent (unstructured)

    # Caso 3: tem atributo .content (CallToolResult)
    if hasattr(result, "content"):
        result = result.content

    # Caso 4: é iterável (list[TextContent])
    if isinstance(result, list):
        text_parts = [
            part.text for part in result if hasattr(part, "text") and part.text
        ]
        return " ".join(text_parts)

    # Caso 5: fallback — converter para string
    return str(result)
