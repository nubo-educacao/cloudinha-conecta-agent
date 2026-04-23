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
from src.workflow.system_intents import is_system_intent, handle_system_intent, PipelineIntent

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
      - Intents leves (ping, starters, clear_session): resposta direta sem LLM
      - Intents contextuais (page_context): resolvem a trigger_message via DB
        e rodam o pipeline LLM completo. A Cloudinha gera resposta real.

    Para mensagens normais:
      - Pipeline Planning → Reasoning → Response
      - Streaming de eventos NDJSON (tool_start, tool_end, text, suggestions)
    """
    if is_system_intent(request):
        result = await handle_system_intent(request, supabase)

        # PipelineIntent → rodar pipeline LLM com a trigger_message oculta
        if isinstance(result, PipelineIntent):
            # Substituir o chatInput pela trigger_message (mensagem invisível para a Cloudinha)
            request.chatInput = result.trigger_message
            request.intent_type = "system_intent_pipeline"  # Marcar para telemetria

            # Metadados para o frontend (open_drawer, delay_ms)
            intent_metadata = {
                "open_drawer": result.open_drawer,
                "delay_ms": result.delay_ms,
            }

            async def generate_intent():
                has_sent_events = False
                full_text = ""
                try:
                    async for event in run_pipeline(request, supabase):
                        has_sent_events = True
                        if event.get("type") == "text":
                            full_text += event.get("content", "")
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                except Exception as e:
                    logger.error(f"Erro no pipeline de system intent: {e}")
                    error_event = {"type": "error", "message": "Desculpe, não consegui processar."}
                    yield json.dumps(error_event, ensure_ascii=False) + "\n"

                if not has_sent_events and not full_text:
                    fallback = TextEvent(content="Desculpe, não consegui processar.")
                    yield fallback.model_dump_json() + "\n"

                # Emitir metadados para o frontend (NÃO vai pro agente — é pós-pipeline)
                yield json.dumps({"type": "intent_metadata", **intent_metadata}, ensure_ascii=False) + "\n"

            return StreamingResponse(
                generate_intent(),
                media_type="application/x-ndjson",
                headers={"X-Content-Type-Options": "nosniff"},
            )

        # Intent leve — resposta direta
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
            
            # Log error to database for observability
            try:
                import traceback
                # Sanitize session_id for UUID database field (remove 'session-' prefix if present)
                db_session_id = request.sessionId.replace("session-", "") if request.sessionId else None
                
                supabase.table('agent_errors').insert({
                    'user_id': request.userId,
                    'session_id': db_session_id,
                    'error_type': 'conecta_agent_error',
                    'error_message': str(e),
                    'stack_trace': traceback.format_exc(),
                    'metadata': {'chat_input': request.chatInput}
                }).execute()
            except Exception as db_err:
                logger.error(f"Falha ao logar erro no banco: {db_err}")

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

