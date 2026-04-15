"""MCP Client para o Reasoning Agent.

Conecta ao nubo-tools MCP Server via HTTP (streamable-http transport).
Converte tool schemas MCP → GenAI FunctionDeclarations automaticamente.

Uso típico:
    async with get_mcp_session(settings.MCP_SERVER_URL) as session:
        tools = await list_genai_tools(session)
        summary = await list_tools_summary(session)
        result = await call_mcp_tool(session, "search_opportunities", {"query": "medicina"})
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from mcp import ClientSession
from mcp.client.sse import sse_client
from google.genai import types

logger = logging.getLogger(__name__)

_MCP_CONNECT_TIMEOUT = 10.0  # segundos


@asynccontextmanager
async def get_mcp_session(mcp_url: str) -> AsyncGenerator[ClientSession, None]:
    """Context manager que abre uma sessão MCP via SSE com timeout de conexão.

    Args:
        mcp_url: URL do MCP Server (ex: 'http://localhost:8001/sse')

    Raises:
        asyncio.TimeoutError: Se a conexão não for estabelecida em _MCP_CONNECT_TIMEOUT segundos
    """
    logger.debug(f"Conectando ao MCP Server: {mcp_url}")
    try:
        async with asyncio.timeout(_MCP_CONNECT_TIMEOUT):
            async with sse_client(mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    logger.debug("Sessão MCP inicializada com sucesso")
                    yield session
    except asyncio.TimeoutError:
        logger.error(f"Timeout ao conectar ao MCP Server ({_MCP_CONNECT_TIMEOUT}s): {mcp_url}")
        raise
    except Exception as e:
        logger.error(f"Erro ao conectar ao MCP Server: {e}")
        raise


async def list_genai_tools(session: ClientSession) -> list[types.Tool]:
    """Lista as tools disponíveis no MCP Server e retorna como GenAI FunctionDeclarations.

    Args:
        session: Sessão MCP já inicializada

    Returns:
        Lista com um único types.Tool contendo todas as FunctionDeclarations.
    """
    tools_response = await session.list_tools()
    declarations = []

    for tool in tools_response.tools:
        try:
            schema = _json_schema_to_genai(tool.inputSchema or {})
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=schema,
                )
            )
        except Exception as e:
            logger.warning(f"Falha ao converter schema da tool {tool.name}: {e}")

    if not declarations:
        return []

    return [types.Tool(function_declarations=declarations)]


async def list_tools_summary(session: ClientSession) -> str:
    """Retorna uma string sumarizada das tools para injeção em prompts de texto (ex: Planning)."""
    try:
        tools_response = await session.list_tools()
        if not tools_response.tools:
            return "- nenhuma ferramenta disponível"
        
        lines = []
        for tool in tools_response.tools:
            desc = tool.description or "Sem descrição"
            lines.append(f"- {tool.name}: {desc}")
            
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Erro ao listar sumário de tools: {e}")
        return "- erro ao carger ferramentas do MCP"


async def call_mcp_tool(session: ClientSession, name: str, args: dict) -> dict:
    """Executa uma tool via MCP e retorna o resultado como dict.

    O MCP retorna conteúdo como lista de TextContent/ImageContent.
    Esta função extrai o texto e tenta fazer JSON parse.

    Args:
        session: Sessão MCP já inicializada
        name: Nome da tool a chamar
        args: Argumentos da tool

    Returns:
        Dict com o resultado (parsado de JSON se possível).
    """
    try:
        result = await session.call_tool(name, args)

        if not result.content:
            return {"result": ""}

        text_parts = [
            part.text
            for part in result.content
            if hasattr(part, "text") and part.text
        ]
        combined_text = " ".join(text_parts)

        # Tentar parse JSON (a maioria das tools retorna JSON)
        try:
            return json.loads(combined_text)
        except json.JSONDecodeError:
            return {"result": combined_text}

    except Exception as e:
        logger.error(f"Erro ao chamar MCP tool '{name}': {e}")
        return {"error": str(e), "tool": name}


# ─── Conversão de Schema ──────────────────────────────────────────────────────

_TYPE_MAP = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _json_schema_to_genai(schema: dict) -> types.Schema:
    """Converte um JSON Schema dict para google.genai.types.Schema.

    Suporta: type, properties, required, description.
    Ignores: $schema, additionalProperties, nested $ref.
    """
    schema_type = _TYPE_MAP.get(schema.get("type", "object"), types.Type.OBJECT)

    properties: dict[str, types.Schema] | None = None
    raw_props = schema.get("properties", {})
    if raw_props:
        properties = {
            key: types.Schema(
                type=_TYPE_MAP.get(val.get("type", "string"), types.Type.STRING),
                description=val.get("description", ""),
            )
            for key, val in raw_props.items()
        }

    return types.Schema(
        type=schema_type,
        properties=properties,
        required=schema.get("required") or [],
        description=schema.get("description", ""),
    )
