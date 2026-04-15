import asyncio
import os
from supabase import create_client, Client
from dotenv import load_dotenv
import logging

# Configuração de log básica para ver o que acontece
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Importar a função que acabamos de mudar
import sys
sys.path.append(os.getcwd())
from src.workflow.system_intents import _fetch_opportunity_data

async def test_resolution():
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("Erro: SUPABASE_URL ou SUPABASE_KEY não encontradas no ambiente.")
        return

    supabase: Client = create_client(url, key)
    
    # ID real que você encontrou no banco
    test_id = "partner_98fdbe58-6e03-438a-90e8-1777e32851fb"
    
    print(f"\n--- TESTANDO RESOLUÇÃO PARA: {test_id} ---")
    data = await _fetch_opportunity_data(supabase, test_id)
    print(f"RESULTADO: {data}")
    
    if data['title'] != "esta oportunidade":
        print("\n✅ SUCESSO! A oportunidade foi identificada corretamente.")
    else:
        print("\n❌ FALHA. Ainda não está identificando.")

if __name__ == "__main__":
    asyncio.run(test_resolution())
