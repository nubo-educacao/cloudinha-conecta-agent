import os
import uvicorn
from src.mcp.server import mcp

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"Iniciando Nubo Tools MCP Server (SSE) na porta {port}...")
    # sse_app() retorna a aplicação Starlette para o transport SSE
    app = mcp.sse_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
