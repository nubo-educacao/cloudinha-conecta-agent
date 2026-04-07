# Project Context: Cloudinha Conecta Agent
> Este arquivo é o cérebro local do back-end multi-agente.
> Tanto Antigravity (IDE) quanto Claude (CLI) devem ler este arquivo ao atuar nesta pasta.

## Source of Truth (PRD)
@import ../nubo-ops/docs/prd_nova_cloudinha.md

## Gap Analysis (V0 → V1 Audit)
@import ../.cursor/plans/cloudinha-v0-v1-gap-analysis.md

## Technical Stack
- **Runtime**: Python 3.12+
- **API Framework**: FastAPI ≥ 0.115
- **LLM SDK**: `google-genai` ≥ 1.0 (SDK oficial Gemini — **NÃO** usar google.adk)
- **Orchestration**: Código Python puro em `src/workflow/engine.py` (sem LangChain/LangGraph)
- **Database**: MCP PostgreSQL (`nubo-hub` dev / `nubo-hub-prod`)
- **Package Manager**: Uv (`pyproject.toml`)
- **Resilience**: Tenacity ≥ 9.0 (retry com backoff exponencial)
- **Validation**: Pydantic ≥ 2.9 (schemas de request, events e contracts)
- **Testing**: pytest + pytest-asyncio

## Arquitetura Multi-Agente (Pipeline 3-Nós)

```
POST /chat → Workflow Engine
  ├── 📋 Planning Agent (Flash-Lite) → StructuredPlan
  ├── 🧠 Reasoning Agent (Flash) → StructuredReasoningReport + tool events
  └── 💬 Response Agent (Flash) → NDJSON stream empático
```

| Agente | Modelo | Sessão | Tools |
|--------|--------|--------|-------|
| Planning | `gemini-2.0-flash-lite` | InMemory (transient) | Zero |
| Reasoning | `gemini-2.0-flash` | InMemory (transient) | MCP + `cep_lookup` |
| Response | `gemini-2.0-flash` | Supabase (persistente) | Zero |

## Diretório-Alvo (Sprint 3)

```
cloudinha-conecta-agent/
├── main.py                        # FastAPI app (EXISTE — expandir)
├── pyproject.toml                 # Dependencies (EXISTE — expandir)
├── PROJECT_CONTEXT.md             # Este arquivo
├── Dockerfile                     # Container (EXISTE)
├── .env.example                   # [NOVO] Template de variáveis
├── src/
│   ├── __init__.py
│   ├── config.py                  # [NOVO] Settings (Pydantic BaseSettings)
│   ├── dependencies.py            # [NOVO] FastAPI dependency injection
│   ├── models/
│   │   ├── __init__.py
│   │   ├── chat_request.py        # [NOVO] ChatRequest + UIContext (§3.1 PRD)
│   │   └── chat_events.py         # [NOVO] TextEvent, ToolStartEvent, ToolEndEvent, SuggestionsEvent, ErrorEvent
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── planning.py            # [NOVO] Planning Agent (Flash-Lite)
│   │   ├── reasoning.py           # [NOVO] Reasoning Agent (Flash)
│   │   └── response.py            # [NOVO] Response Agent (Flash)
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── structured_plan.py     # [NOVO] StructuredPlan parser (regex)
│   │   └── reasoning_report.py    # [NOVO] ReasoningReport parser + extract_suggestions()
│   ├── services/
│   │   ├── __init__.py
│   │   ├── supabase_client.py     # [NOVO] Supabase client factory
│   │   ├── session_service.py     # [NOVO] InMemory (transient) + Supabase (persistent) session
│   │   ├── context_service.py     # [NOVO] Lean Context assembler (build_lean_context)
│   │   ├── schema_discovery.py    # [NOVO] Schema Auto-Discover on Boot (cache TTL=5min)
│   │   ├── retrieval_service.py   # [NOVO] Few-Shot learning_examples injector
│   │   └── resilience.py          # [NOVO] Retry decorators com Tenacity (backoff exponencial)
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── engine.py              # [NOVO] Orquestrador Planning→Reasoning→Response
│   │   ├── streaming.py           # [NOVO] NDJSON streaming helpers
│   │   └── system_intents.py      # [NOVO] System Intent interceptor
│   └── tools/
│       ├── __init__.py
│       └── cep_lookup.py          # [NOVO] Única tool HTTP externa mantida
└── tests/
    ├── __init__.py
    ├── test_contracts.py          # [NOVO] Unit tests para parsers
    ├── test_planning.py           # [NOVO] Planning agent (mock LLM)
    ├── test_reasoning.py          # [NOVO] Reasoning agent (mock LLM + tools)
    ├── test_workflow.py           # [NOVO] Integration test do pipeline
    └── conftest.py                # [NOVO] Fixtures compartilhadas
```

## Contratos Inter-Agente

### Structured Plan (Planning → Reasoning)
```markdown
## INTENT
[Uma linha: o que o usuário quer]
## INTENT_CATEGORY
[course_search | eligibility_query | application_help | form_support | general_qa | system_intent | casual]
## TOOLS_TO_USE
- tool_name: { param: value }
## CONTEXT_NEEDED
[O que o Reasoning precisará buscar]
```

### Structured Reasoning Report (Reasoning → Response)
```markdown
## INTENT
[Uma linha]
## DATA
- tool_usada: [resultado resumido]
## REASONING
[Conclusão: o que responder e por quê]
## ACTION
[none | application_started | profile_updated]
## SUGGESTED_FOLLOWUPS
- Pergunta 1?
- Pergunta 2?
- Pergunta 3?
```

## Invariantes de Produção (do Gap Analysis V0→V1)

1. **Resiliência**: Todo call LLM e Supabase DEVE ter retry com backoff exponencial (Tenacity, 3 tentativas, 1-10s).
2. **Observabilidade**: Falhas de tools/agents DEVEM ser persistidas na tabela `agent_errors` com `error_type`, `stack_trace` e `metadata` (tool_name, args, raw_output).
3. **Tool Badges**: `tool_start`/`tool_end` DEVEM ser emitidos como NDJSON durante o Reasoning, ANTES do Response começar.
4. **Lean Context**: Contexto mínimo (user_id, nome, idade, LTM, 5 msgs, ui_context) montado por `context_service.py`. NUNCA dump bruto de user_profiles.
5. **Sessão Transient**: Planning e Reasoning usam InMemorySessionService. SOMENTE Response persiste no Supabase.
6. **Few-Shot**: `retrieval_service.py` busca 3 exemplos de `learning_examples` por `intent_category` e injeta no Reasoning Agent.
7. **Fallbacks**: Token vazio → mensagem amigável em pt-BR. Plan parse fail → plano fallback `general_qa`. Network fail → retry 3x + mensagem empática.
8. **Schema Cache**: Schema Discovery cacheado com TTL de 5 minutos (`schema_discovery.py`).
9. **Read-Only**: Cloudinha V1 é estritamente consultiva. ZERO tools de mutação (write/update/delete). Únicas exceções: `cep_lookup` (API HTTP externa) e persistência de `chat_messages`/`agent_errors` pelo engine.

## Sprint History

### Sprint 01 — Foundation Scaffold ✅
- PyProject / Requirements com fastapi, uvicorn
- Entrypoint (`main.py`) com `GET /health`
- Containerização Dockerfile multi-stage

### Sprint 03 — O Cérebro Unificado (CURRENT)
Implementação completa do pipeline multi-agente Planning→Reasoning→Response.
Ver blueprint tático: `../.cursor/plans/2026-04-06_sprint-03-cerebro-dashboard.md`
