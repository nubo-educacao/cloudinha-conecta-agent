import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from supabase import Client

from src.config import settings
from src.dependencies import supabase_anon
from src.mcp.server import mcp
from src.models.chat_request import ChatRequest
from src.models.chat_events import TextEvent
from src.workflow.engine import run_pipeline
from src.workflow.system_intents import is_system_intent, handle_system_intent

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Cloudinha Conecta Agent iniciando... MCP SSE em {settings.MCP_SERVER_URL}")
    yield
    logger.info("Cloudinha Conecta Agent encerrando.")


app = FastAPI(
    title="Cloudinha Conecta Agent",
    description="Multi-agent AI backend for Nubo Conecta",
    version="0.2.0",
    lifespan=lifespan,
)

# MCP SSE Server embutido — elimina necessidade de processo separado
# Disponível em /mcp/sse (SSE stream) e /mcp/messages/ (POST)
app.mount("/mcp", mcp.sse_app())

cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "operational"}


@app.post("/chat")
async def chat(
    request: ChatRequest,
    supabase: Client = Depends(supabase_anon),
):
    """Endpoint de chat com streaming NDJSON.

    Para system intents (intent_type='system_intent'):
      - NÃO persiste em chat_messages
      - Responde com evento único (JSON) sem passar pelo pipeline LLM

    Para mensagens normais:
      - Pipeline Planning → Reasoning → Response
      - Streaming de eventos NDJSON (tool_start, tool_end, text, suggestions)
    """
    if is_system_intent(request):
        result = await handle_system_intent(request, supabase)
        return result

    async def generate():
        has_sent_events = False
        full_text = ""
        try:
            async for event in run_pipeline(request, supabase):
                has_sent_events = True
                if event.get("type") == "text":
                    full_text += event.get("content", "")
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as e:
            logger.error(f"Erro no gerador NDJSON: {e}")
            error_event = {"type": "error", "message": "Estou com dificuldades de conexão. Tente novamente."}
            yield json.dumps(error_event, ensure_ascii=False) + "\n"

        # Fallback final: nenhum evento emitido
        if not has_sent_events and not full_text:
            fallback = TextEvent(content="Desculpe, não consegui processar.")
            yield fallback.model_dump_json() + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )
