import asyncio
import os
from dotenv import load_dotenv
import logging

# Configuração de log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import sys
sys.path.append(os.getcwd())
from src.mcp.client import get_mcp_session, list_tools_summary
from src.config import settings

async def check_tools():
    load_dotenv()
    mcp_url = os.environ.get("MCP_SERVER_URL", "http://localhost:8001/sse")
    
    print(f"\n--- CONECTANDO AO MCP EM: {mcp_url} ---")
    try:
        async with get_mcp_session(mcp_url) as session:
            summary = await list_tools_summary(session)
            print("\nFERRAMENTAS DESCOBERTAS:")
            print(summary)
            
            if "search_opportunities" in summary:
                print("\n✅ search_opportunities encontrada.")
            else:
                print("\n❌ search_opportunities NÃO encontrada!")
                
    except Exception as e:
        print(f"\n❌ Erro ao conectar: {e}")

if __name__ == "__main__":
    asyncio.run(check_tools())
