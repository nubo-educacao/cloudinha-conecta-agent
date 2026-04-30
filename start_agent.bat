@echo off
echo Starting Cloudinha Conecta Agent (FastAPI) on port 8080...
echo.
uv run uvicorn main:app --reload --port 8080 --log-level debug
pause
