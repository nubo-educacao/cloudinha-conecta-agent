import logging
import httpx

logger = logging.getLogger(__name__)

CEP_API_URL = "https://viacep.com.br/ws/{cep}/json/"
TIMEOUT_SECONDS = 5.0


async def lookup_cep(cep: str) -> dict:
    """Consulta a API ViaCEP para obter dados de endereço a partir de um CEP.

    Única tool externa mantida da V0. Retorna dict com logradouro, bairro,
    localidade, uf. Em caso de falha retorna {"error": "<motivo>"}.
    """
    cep_clean = "".join(filter(str.isdigit, cep))
    if len(cep_clean) != 8:
        return {"error": f"CEP inválido: {cep}. Deve ter 8 dígitos."}

    url = CEP_API_URL.format(cep=cep_clean)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if data.get("erro"):
            return {"error": f"CEP {cep_clean} não encontrado."}

        return {
            "cep": data.get("cep"),
            "logradouro": data.get("logradouro"),
            "bairro": data.get("bairro"),
            "localidade": data.get("localidade"),
            "uf": data.get("uf"),
        }
    except httpx.TimeoutException:
        logger.warning(f"Timeout ao consultar CEP {cep_clean}")
        return {"error": "Timeout ao consultar o CEP. Tente novamente."}
    except Exception as e:
        logger.error(f"Erro ao consultar CEP {cep_clean}: {e}")
        return {"error": f"Não foi possível consultar o CEP: {str(e)}"}
