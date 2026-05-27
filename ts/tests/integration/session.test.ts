import { describe, it, expect, vi } from "vitest";
import { SessionService } from "../../src/services/session.js";
import type { SupabaseClient } from "@supabase/supabase-js";

const USER_ID = "550e8400-e29b-41d4-a716-446655440000";
const SESSION_ID = "session-abc-123";

describe("SessionService", () => {
  it("persists user message with sender='user'", async () => {
    const insertMock = vi.fn().mockResolvedValue({ error: null });
    const supabase = {
      from: vi.fn().mockReturnValue({ insert: insertMock }),
    } as unknown as SupabaseClient;

    const svc = new SessionService(supabase, USER_ID, SESSION_ID);
    await svc.persistUserMessage("Quero bolsa ProUni");

    expect(insertMock).toHaveBeenCalledWith(
      expect.objectContaining({ sender: "user", content: "Quero bolsa ProUni" })
    );
  });

  it("persists agent message with sender='cloudinha'", async () => {
    const insertMock = vi.fn().mockResolvedValue({ error: null });
    const supabase = {
      from: vi.fn().mockReturnValue({ insert: insertMock }),
    } as unknown as SupabaseClient;

    const svc = new SessionService(supabase, USER_ID, SESSION_ID);
    await svc.persistAgentMessage("Vou te ajudar!");

    expect(insertMock).toHaveBeenCalledWith(
      expect.objectContaining({ sender: "cloudinha", content: "Vou te ajudar!" })
    );
  });

  it("getRecentMessages returns messages in ascending order (oldest first)", async () => {
    const messages = [
      { sender: "user", content: "Tenho dúvida" },
      { sender: "cloudinha", content: "Oi!" },
      { sender: "user", content: "Olá" },
    ];

    const supabase = {
      from: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        neq: vi.fn().mockReturnThis(),
        order: vi.fn().mockReturnThis(),
        limit: vi.fn().mockResolvedValue({ data: messages, error: null }),
      }),
    } as unknown as SupabaseClient;

    const svc = new SessionService(supabase, USER_ID, SESSION_ID);
    const result = await svc.getRecentMessages(5);

    expect(result).toHaveLength(3);
    expect(result[0].sender).toBe("user");
    expect(result[0].content).toBe("Olá");

    // Verify ascending order was requested
    const orderCall = (supabase.from as ReturnType<typeof vi.fn>).mock.results[0].value.order;
    expect(orderCall).toHaveBeenCalledWith("created_at", { ascending: false });
  });

  it("getRecentMessages returns empty array on error", async () => {
    const supabase = {
      from: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        neq: vi.fn().mockReturnThis(),
        order: vi.fn().mockReturnThis(),
        limit: vi.fn().mockResolvedValue({ data: null, error: { message: "DB error" } }),
      }),
    } as unknown as SupabaseClient;

    const svc = new SessionService(supabase, USER_ID, SESSION_ID);
    const result = await svc.getRecentMessages(5);

    expect(result).toEqual([]);
  });
});
