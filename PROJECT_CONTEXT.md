# Project Context: Cloudinha Conecta Agent
> Este arquivo é o cérebro local do back-end multi-agente.
> Tanto Antigravity (IDE) quanto Claude (CLI) devem ler este arquivo ao atuar nesta pasta.

## Source of Truth (PRD)
@import ../nubo-ops/docs/prd_nova_cloudinha.md

## Technical Stack
- **API Framework**: FastAPI / Python 3.12+
- **Agent Orchestration**: LangChain / LangGraph
- **Database Connection**: MCP PostgreSQL (`nubo-hub`)
- **Package Manager**: Uv / Pipenv (A definir)

## Sprint 01 — Orientação Foundation Scaffold
A Nova Cloudinha na Sprint 01 tem escopo prototípico estrutural focado em deploys de Health-Check, antecedendo os 3 nós LangGraph.

- `[ ]` **PyProject / Requirements**: Criar a definição de bibliotecas contendo fastapi, uvicorn.
- `[ ]` **Entrypoint (`main.py`)**: Subir a instância assíncrona FastAPI, definindo CORS e a rota vital base `GET /health` (`status: operational`).
- `[ ]` **Containerização Pronta**: Construir o `Dockerfile` com ambiente multi-stage python lightweight (alpine/slim).

Isso habilita a infra do Conecta conectar suas pontas sem os LLMs engessados antes da Sprint 3.
