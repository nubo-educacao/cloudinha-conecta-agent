# Project Context: Cloudinha Conecta Agent
> Este arquivo é o cérebro local do back-end multi-agente.
> Tanto Antigravity (IDE) quanto Claude (CLI) devem ler este arquivo ao atuar nesta pasta.
> **Última atualização:** Sprint 03 — 2026-04-07 (playbook-curator)

## Source of Truth (PRD)
@import ../nubo-ops/docs/prd_nova_cloudinha.md

## Gap Analysis (V0 → V1 Audit)
@import ../.cursor/plans/cloudinha-v0-v1-gap-analysis.md

---

## Technical Stack

| Camada | Tecnologia | Notas |
|--------|-----------|-------|
| Runtime | Python 3.12+ | uv como package manager |
| API Framework | FastAPI ≥ 0.115 | `main.py` — `/health` + `/chat` (NDJSON stream) |
| LLM SDK | `google-genai` ≥ 1.0 | SDK oficial Gemini. **NÃO** usar google.adk ou LangChain |
| Tool Protocol | `mcp` ≥ 1.0 (FastMCP) | nubo-tools MCP Server em `src/mcp/server.py` |
| Orchestration | Python puro em `src/workflow/engine.py` | Sem LangChain/LangGraph |
| Database | Supabase (via `supabase-py`) | MCP PostgreSQL para schema discovery |
| Resilience | Tenacity ≥ 9.0 | Retry backoff exponencial em `src/services/resilience.py` |
| Validation | Pydantic ≥ 2.9 | Schemas em `src/models/` e `src/contracts/` |
| Testing | pytest + pytest-asyncio | 46/46 passando. `conftest.py` na raiz injeta env vars |

---

## Arquitetura MCP-Native (ESTABILIZADA — Sprint 03)

### Topologia de Serviços

```
Claude Desktop / Cursor
        │  (stdio ou http://host:8001/mcp)
        ▼
┌─────────────────────────────┐
│  nubo-tools MCP Server      │  → python -m src.mcp.server [--transport http]
│  src/mcp/server.py          │
│  ├── search_opportunities   │
│  ├── get_student_profile    │
│  ├── lookup_cep             │
│  ├── get_match_results      │
│  └── search_institutions    │
└──────────────┬──────────────┘
               │  MCP Client (streamable-http)
               │  src/mcp/client.py
               ▼
┌─────────────────────────────┐
│  Cloudinha FastAPI :8000    │
│  POST /chat                 │
│  └── workflow/engine.py     │
│      ├── Planning Agent     │
│      ├── Reasoning Agent ───┘  (conecta ao MCP Server)
│      └── Response Agent     │
└─────────────────────────────┘
```

**Regra de Ouro:** Toda lógica de dados (SQL/Supabase) fica no **MCP Server**.
O Reasoning Agent é um **MCP Client puro** — zero SQL hardcoded no agent.
Benefício: as mesmas capacidades são acessíveis pelo Claude Desktop/Cursor sem duplicação.

---

## Pipeline 3-Nós (Planning → Reasoning → Response)

### Tabela de Agentes

| Agente | Modelo | Sessão | Responsabilidade |
|--------|--------|--------|-----------------|
| Planning | `gemini-2.0-flash-lite` | InMemory transient | Classifica intenção → `StructuredPlan` |
| Reasoning | `gemini-2.0-flash` | InMemory transient | Executa tools MCP → `ReasoningReport` |
| Response | `gemini-2.0-flash` | Supabase persistente | Gera resposta final empática em pt-BR |

### Fluxo de Dados

```
POST /chat (ChatRequest)
  │
  ├─ [system_intent?] → system_intents.py → resposta direta (NÃO persiste chat_messages)
  │
  └─ [user_message]
       ├── 1. build_lean_context()         — user_id, nome, LTM, 5 msgs, ui_context
       ├── 2. Planning Agent               — gemini-flash-lite, retry corretivo 1x
       │       └── parse_structured_plan() — fallback para general_qa se parse falhar
       ├── 3. retrieve_few_shot_examples() — 3 exemplos por intent_category
       ├── 4. Reasoning Agent (MCP loop)
       │       ├── get_mcp_session(MCP_SERVER_URL)
       │       ├── list_genai_tools() → FunctionDeclarations automáticas do MCP schema
       │       ├── tool_start event ──► frontend (UX badge)
       │       ├── call_mcp_tool()   — zero SQL aqui
       │       └── tool_end event   ──► frontend
       ├── 5. extract_suggestions()        — regex, zero LLM
       ├── 6. Response Agent (stream)      — gemini-flash, streaming NDJSON
       └── 7. SuggestionsEvent             — APÓS o texto completo
```

---

## Contratos Inter-Agente (Markdown Estruturado)

### StructuredPlan (Planning → Reasoning)

```markdown
## INTENT
[Uma linha: o que o usuário quer]

## INTENT_CATEGORY
[course_search | eligibility_query | application_help | form_support | general_qa | system_intent | casual]

## TOOLS_TO_USE
- search_opportunities
- get_student_profile

## CONTEXT_NEEDED
[O que o Reasoning precisará buscar]
```

**Parser:** `src/contracts/structured_plan.py::parse_structured_plan()`
**Fallback:** `FALLBACK_PLAN` com `intent_category="general_qa"` e `tools=[]`

### ReasoningReport (Reasoning → Response)

```markdown
## INTENT
## DATA
## REASONING
## ACTION
[none | show_opportunities | show_profile | navigate]
## SUGGESTED_FOLLOWUPS
- Pergunta 1?
- Pergunta 2?
- Pergunta 3?
```

**Parser:** `src/contracts/reasoning_report.py::parse_reasoning_report()`
**Micro-parser de sugestões:** `extract_suggestions()` — regex pura, zero LLM.

---

## NDJSON Event Stream (Ordem Obrigatória)

| Evento | Tipo | Quando |
|--------|------|--------|
| `ToolStartEvent` | `tool_start` | Antes de cada `call_mcp_tool()` |
| `ToolEndEvent` | `tool_end` | Após cada `call_mcp_tool()` |
| `TextEvent` | `text` | Chunks do Response Agent (streaming) |
| `SuggestionsEvent` | `suggestions` | APÓS o último `text` chunk |
| `ErrorEvent` | `error` | Falhas (mensagem em pt-BR, sem stack trace) |

**Invariante:** `tool_start`/`tool_end` SEMPRE antes dos `text` chunks.
`suggestions` SEMPRE depois do último `text` chunk.

---

## Design Patterns Estabilizados

### 1. MCP Client no Reasoning Agent

```python
# CORRETO — MCP-Native
async with get_mcp_session(settings.MCP_SERVER_URL) as session:
    tools = await list_genai_tools(session)     # Conversão automática JSON Schema → GenAI
    result = await call_mcp_tool(session, name, args)

# ERRADO — não fazer SQL no agent
supabase.table("v_unified_opportunities").select(...).execute()
```

### 2. Conversão Automática de Schema MCP → GenAI

`src/mcp/client.py::list_genai_tools()` lê `tool.inputSchema` (JSON Schema) e
converte para `types.FunctionDeclaration` automaticamente. Ao adicionar uma nova
tool no MCP Server, o Reasoning Agent a recebe sem nenhuma alteração.

### 3. Retry Corretivo no Planning

Se `parse_structured_plan()` falhar (INTENT ausente), Planning reenvia com
prompt corretivo explicitando o formato. Se falhar 2x → `FALLBACK_PLAN`.

### 4. Error Boundaries — Tipos Obrigatórios em `agent_errors`

| `error_type` | Origem |
|---|---|
| `planning_agent_error` | Falha LLM Planning |
| `reasoning_agent_error` | Falha LLM ou MCP Reasoning |
| `response_agent_error` | Falha LLM Response |
| `tool_error` | Tool MCP retorna `success: false` |
| `plan_parse_error` | StructuredPlan com INTENT ausente |
| `server_stream_error` | Erro top-level no generator NDJSON |

### 5. MCP Server — Como Adicionar uma Nova Tool

1. Adicionar função com `@mcp.tool()` em `src/mcp/server.py`
2. Anotar com docstring completa (Claude Desktop exibe como description)
3. Escrever teste em `tests/test_mcp_server.py`
4. Zero alterações no Reasoning Agent — a tool aparece automaticamente via `list_genai_tools()`

---

## Invariantes de Produção

1. **MCP-Native**: Reasoning Agent é MCP Client puro. Zero SQL/Supabase imports em `src/agents/reasoning.py`.
2. **Resiliência**: Todo call LLM tem retry backoff exponencial (Tenacity, 3x, 1-10s) no engine.
3. **Observabilidade**: Falhas persistidas em `agent_errors` com `error_type` + `stack_trace`.
4. **Lean Context**: Contexto montado **exclusivamente** por `build_lean_context()`. NUNCA dump bruto de `user_profiles`.
5. **Sessão Transient**: Planning e Reasoning usam `InMemorySessionService`. SOMENTE Response persiste no Supabase.
6. **System Intents**: `intent_type="system_intent"` → `system_intents.py` → NÃO persiste em `chat_messages`.
7. **Fallbacks pt-BR**: Toda mensagem de erro ao usuário é empática, em português, sem stack traces.
8. **Read-Only**: Cloudinha V1 é estritamente consultiva. Zero tools de mutação (write/update/delete).
9. **Schema Cache**: Schema Discovery cacheado com TTL 5 minutos (`schema_discovery.py`).

---

## Sprint History

### Sprint 01 — Foundation Scaffold ✅
- PyProject / Requirements com fastapi, uvicorn
- Entrypoint (`main.py`) com `GET /health`
- Containerização Dockerfile multi-stage

### Sprint 03 — O Cérebro Unificado ✅ (2026-04-07)
- Pipeline completo Planning→Reasoning→Response
- Arquitetura MCP-Native: `src/mcp/server.py` (FastMCP) + `src/mcp/client.py`
- 5 tools no MCP Server: search_opportunities, get_student_profile, lookup_cep, get_match_results, search_institutions
- Conversão automática JSON Schema → GenAI FunctionDeclaration
- System Intent interceptor (ping, get_starters, clear_session)
- TDD: **46/46 testes passando** (contracts, mcp_server, planning, reasoning, workflow)
- `conftest.py` raiz para CI/CD sem `.env`
