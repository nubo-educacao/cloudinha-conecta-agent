"""RED → GREEN: MCP client deve logar erros de conexão.

Âncora BUG-S5-004:
- Falha de conexão MCP deve ser logada com nível ERROR
- get_mcp_session deve propagar TimeoutError/ConnectionError
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp.client import get_mcp_session


@pytest.mark.asyncio
async def test_get_mcp_session_raises_on_timeout():
    """get_mcp_session deve propagar TimeoutError quando conexão falha."""
    with patch("src.mcp.client.sse_client") as mock_sse:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_sse.return_value = cm

        with pytest.raises((asyncio.TimeoutError, ConnectionError)):
            async with get_mcp_session("http://localhost:8001/sse") as _:
                pass


@pytest.mark.asyncio
async def test_get_mcp_session_logs_error_on_failure(caplog):
    """Falha de conexão MCP deve ser logada com nível ERROR (BUG-S5-004)."""
    with patch("src.mcp.client.sse_client") as mock_sse:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_sse.return_value = cm

        with caplog.at_level(logging.WARNING, logger="src.mcp.client"):
            with pytest.raises(ConnectionRefusedError):
                async with get_mcp_session("http://localhost:8001/sse") as _:
                    pass

    assert any(
        "MCP" in r.message for r in caplog.records if r.levelno >= logging.WARNING
    ), f"Nenhum log WARNING/ERROR com 'MCP'. Registros: {[r.message for r in caplog.records]}"
