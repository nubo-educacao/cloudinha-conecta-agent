/**
 * BDD: Hotfix #4 — Silenciar system_ack no agente Cloudinha
 *
 * Cenário: Usuário navega para /candidaturas (ou qualquer página sem page_context configurado)
 * → O chat da Cloudinha NÃO deve exibir nenhuma mensagem de texto.
 *
 * Causa raíz: quando handleSystemIntent() retorna { type: 'system_ack' },
 * o bloco else do index.ts serializa resObj.message como evento 'text' e envia ao frontend.
 */

import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

// Mocks declarados antes de qualquer import de módulo (vitest hoist)
// Setar PORT=0 antes do app.listen() rodar no import de index.ts.
// A factory do vi.mock é executada durante o hoist, antes dos imports.
vi.mock("dotenv/config", () => {
  process.env.PORT = "0";
  return {};
});

vi.mock("../../src/services/system-intents.js", () => ({
  isSystemIntent: vi.fn(() => true),
  handleSystemIntent: vi.fn(async () => ({
    type: "system_ack",
    message: "No page_context intent matched for page: /candidaturas",
  })),
}));

vi.mock("../../src/services/supabase.js", () => ({
  getSupabaseAnon: vi.fn(() => ({})),
  getSupabaseService: vi.fn(() => ({})),
}));

vi.mock("../../src/agent/pipeline.js", () => ({
  runPipeline: vi.fn(async function* () {
    yield { type: "text", content: "pipeline response" };
  }),
}));

// Importar app APÓS os mocks
import app from "../../src/index.js";

const VALID_CHAT_BODY = {
  chatInput: "page_context",
  userId: "550e8400-e29b-41d4-a716-446655440000",
  active_profile_id: "550e8400-e29b-41d4-a716-446655440001",
  sessionId: "test-session-1",
  intent_type: "system_intent",
};

describe("POST /chat — system_ack deve ser silencioso", () => {
  let server: Server;
  let baseUrl: string;

  beforeAll(async () => {
    server = createServer(app);
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const { port } = server.address() as AddressInfo;
    baseUrl = `http://localhost:${port}`;
  });

  afterAll(() => {
    server.close();
  });

  it("retorna HTTP 200", async () => {
    const res = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(VALID_CHAT_BODY),
    });
    expect(res.status).toBe(200);
  });

  it("não emite nenhum evento do tipo 'text' quando system_ack é retornado", async () => {
    const res = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(VALID_CHAT_BODY),
    });

    const body = await res.text();
    const lines = body.trim().split("\n").filter(Boolean);
    const events = lines.map((l) => JSON.parse(l));

    const textEvents = events.filter((e) => e.type === "text");
    expect(textEvents).toHaveLength(0);
  });

  it("não vaza a mensagem interna 'No page_context intent matched' no body da resposta", async () => {
    const res = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(VALID_CHAT_BODY),
    });

    const body = await res.text();
    expect(body).not.toContain("No page_context intent matched");
  });

  it("não emite nenhum evento de qualquer tipo (resposta completamente vazia)", async () => {
    const res = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(VALID_CHAT_BODY),
    });

    const body = await res.text();
    const lines = body.trim().split("\n").filter(Boolean);
    expect(lines).toHaveLength(0);
  });
});
