@echo off
echo Starting Cloudinha Conecta Agent (FastAPI) on port 8000...
echo.
uv run uvicorn main:app --reload --port 8000
pause
