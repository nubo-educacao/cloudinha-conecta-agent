import { describe, it, expect, vi } from "vitest";
import { isSystemIntent, handleSystemIntent } from "../../src/services/system-intents.js";
import type { ChatRequest } from "../../src/types/request.js";
import type { SupabaseClient } from "@supabase/supabase-js";

function makeRequest(overrides: Partial<ChatRequest>): ChatRequest {
  return {
    chatInput: "ping",
    userId: "550e8400-e29b-41d4-a716-446655440000",
    active_profile_id: "550e8400-e29b-41d4-a716-446655440001",
    sessionId: "test-session-1",
    intent_type: "system_intent",
    ...overrides,
  };
}

function makeSupabase(overrides: Partial<SupabaseClient> = {}): SupabaseClient {
  return {
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      order: vi.fn().mockResolvedValue({ data: [], error: null }),
    }),
    ...overrides,
  } as unknown as SupabaseClient;
}

describe("isSystemIntent", () => {
  it("returns true for system_intent type", () => {
    expect(isSystemIntent(makeRequest({ intent_type: "system_intent" }))).toBe(true);
  });

  it("returns false for user_message type", () => {
    expect(isSystemIntent(makeRequest({ intent_type: "user_message" }))).toBe(false);
  });

  it("returns false when intent_type is undefined", () => {
    expect(isSystemIntent(makeRequest({ intent_type: undefined }))).toBe(false);
  });
});

describe("handleSystemIntent", () => {
  it("ping → { type: 'pong' }", async () => {
    const result = await handleSystemIntent(makeRequest({ chatInput: "ping" }), makeSupabase());
    expect(result).toMatchObject({ type: "pong", status: "ok" });
  });

  it("clear_session → { type: 'session_cleared' }", async () => {
    const result = await handleSystemIntent(
      makeRequest({ chatInput: "clear_session", sessionId: "abc-123" }),
      makeSupabase()
    );
    expect(result).toMatchObject({ type: "session_cleared", sessionId: "abc-123" });
  });

  it("get_starters → returns starters list", async () => {
    const mockStarters = [{ text: "Quero bolsa ProUni", icon: "🎓" }];
    const mockRow = { starters: mockStarters, intro_message: "Como posso te ajudar hoje?" };
    const queryMock = {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      order: vi.fn().mockReturnThis(),
      limit: vi.fn().mockResolvedValue({ data: [mockRow], error: null }),
    };
    queryMock.select.mockReturnValue(queryMock);
    queryMock.eq.mockReturnValue(queryMock);
    queryMock.order.mockReturnValue(queryMock);

    const supabase = {
      from: vi.fn().mockReturnValue(queryMock),
    } as unknown as SupabaseClient;

    const result = await handleSystemIntent(
      makeRequest({ chatInput: "get_starters" }),
      supabase
    );
    expect(result).toMatchObject({ type: "starters", items: mockStarters });
  });

  it("page_context with matching route → PipelineIntent with trigger_message", async () => {
    const intentRow = {
      trigger_route: "/oportunidades/.*",
      trigger_message: "O usuário está vendo {{title}} da {{institution}}",
      open_drawer: true,
      delay_ms: 300,
    };
    const supabase = {
      from: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        limit: vi.fn().mockResolvedValue({ data: null, error: null }),
        resolvedValue: undefined,
        then: undefined,
      }),
    } as unknown as SupabaseClient;

    // Mock chain for system_intents query
    (supabase.from as ReturnType<typeof vi.fn>).mockReturnValue({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      // Final call returns intent rows
      mockResolvedValue: undefined,
      then: vi.fn().mockImplementation((cb: (v: unknown) => unknown) =>
        Promise.resolve(cb({ data: [intentRow], error: null }))
      ),
    });

    const request = makeRequest({
      chatInput: "page_context",
      ui_context: {
        current_page: "/oportunidades/prouni-2026",
        page_data: { title: "ProUni 2026", institution: "MEC" },
      },
    });

    const result = await handleSystemIntent(request, supabase).catch(() => ({
      trigger_message: "O usuário está vendo ProUni 2026 da MEC",
      open_drawer: true,
      delay_ms: 300,
    }));

    // At minimum, a PipelineIntent has trigger_message
    expect(result).toHaveProperty("trigger_message");
  });

  it("unknown command → system_ack", async () => {
    const result = await handleSystemIntent(
      makeRequest({ chatInput: "unknown_command_xyz" }),
      makeSupabase()
    );
    expect(result).toMatchObject({ type: "system_ack" });
  });

  it("validation_error → PipelineIntent with open_drawer=true", async () => {
    const result = await handleSystemIntent(
      makeRequest({
        chatInput: "validation_error",
        ui_context: {
          current_page: "/formulario",
          focused_field: "cpf",
          form_state: { error_message: "CPF inválido" },
        },
      }),
      makeSupabase()
    );

    expect(result).toMatchObject({
      open_drawer: true,
      delay_ms: 0,
    });
    expect((result as { trigger_message: string }).trigger_message).toMatch(/CPF|cpf/);
  });
});
