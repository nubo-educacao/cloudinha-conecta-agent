import { describe, it, expect, vi, beforeEach } from "vitest";
import { createQueryEducationalCatalog, BLOCKED_PATTERN } from "../../../src/tools/query-educational-catalog.js";
import type { SupabaseClient } from "@supabase/supabase-js";

function makeSupabase(rpcResult: { data: unknown; error: unknown }) {
  return {
    rpc: vi.fn().mockResolvedValue(rpcResult),
  } as unknown as SupabaseClient;
}

describe("query_educational_catalog", () => {
  beforeEach(() => {
    BLOCKED_PATTERN.lastIndex = 0;
  });

  it("executes valid query against public table", async () => {
    const supabase = makeSupabase({ data: [{ id: 1, title: "ProUni" }], error: null });
    const tool = createQueryEducationalCatalog(supabase);

    const result = await tool.invoke({ sql_query: "SELECT * FROM v_unified_opportunities LIMIT 5" });
    const parsed = JSON.parse(result);

    expect(parsed.results).toHaveLength(1);
    expect(parsed.count).toBe(1);
    expect(supabase.rpc).toHaveBeenCalledWith("execute_readonly_query", {
      query_text: "SELECT * FROM v_unified_opportunities LIMIT 5",
    });
  });

  it("blocks query referencing user_profiles (LGPD)", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createQueryEducationalCatalog(supabase);

    const result = await tool.invoke({
      sql_query: "SELECT * FROM user_profiles WHERE id = '123'",
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/LGPD/);
    expect(supabase.rpc).not.toHaveBeenCalled();
  });

  it("blocks query referencing auth.users", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createQueryEducationalCatalog(supabase);

    const result = await tool.invoke({
      sql_query: "SELECT * FROM auth.users",
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/LGPD/);
  });

  it("blocks query with uppercase table name (case-insensitive)", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createQueryEducationalCatalog(supabase);

    const result = await tool.invoke({
      sql_query: "SELECT * FROM USER_PROFILES",
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/LGPD/);
  });

  it("blocks query referencing agent_turns", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createQueryEducationalCatalog(supabase);

    const result = await tool.invoke({
      sql_query: "SELECT * FROM agent_turns",
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/LGPD/);
  });

  it("returns error on database failure", async () => {
    const supabase = makeSupabase({ data: null, error: { message: "connection refused" } });
    const tool = createQueryEducationalCatalog(supabase);

    const result = await tool.invoke({
      sql_query: "SELECT * FROM partners",
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/Database error/);
  });
});
