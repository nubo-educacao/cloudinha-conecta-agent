@echo off
echo Starting Nubo Tools MCP Server (SSE) on port 8001...
echo.
set PORT=8001
uv run python mcp_launcher.py
pause
