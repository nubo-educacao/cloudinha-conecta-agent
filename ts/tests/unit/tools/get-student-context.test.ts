import { describe, it, expect, vi } from "vitest";
import { createGetStudentContext } from "../../../src/tools/get-student-context.js";
import type { SupabaseClient } from "@supabase/supabase-js";

const VALID_PROFILE_ID = "550e8400-e29b-41d4-a716-446655440000";

function makeSupabase(rpcResult: { data: unknown; error: unknown }) {
  return {
    rpc: vi.fn().mockResolvedValue(rpcResult),
  } as unknown as SupabaseClient;
}

describe("get_student_context", () => {
  it("executes query with profile_id present", async () => {
    const supabase = makeSupabase({ data: [{ profile_id: VALID_PROFILE_ID, gpa: 750 }], error: null });
    const tool = createGetStudentContext(supabase);

    const result = await tool.invoke({
      sql_query: `SELECT * FROM user_enem_scores WHERE profile_id = '${VALID_PROFILE_ID}'`,
      profile_id: VALID_PROFILE_ID,
    });
    const parsed = JSON.parse(result);

    expect(parsed.results).toHaveLength(1);
    expect(supabase.rpc).toHaveBeenCalled();
  });

  it("rejects query that does not contain profile_id", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createGetStudentContext(supabase);

    const result = await tool.invoke({
      sql_query: "SELECT * FROM user_profiles WHERE id = 'other-id'",
      profile_id: VALID_PROFILE_ID,
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/Security/);
    expect(supabase.rpc).not.toHaveBeenCalled();
  });

  it("blocks query referencing chat_messages (not in whitelist)", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createGetStudentContext(supabase);

    const result = await tool.invoke({
      sql_query: `SELECT * FROM chat_messages WHERE profile_id = '${VALID_PROFILE_ID}'`,
      profile_id: VALID_PROFILE_ID,
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/LGPD|Security/);
  });

  it("blocks query referencing agent_errors", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createGetStudentContext(supabase);

    const result = await tool.invoke({
      sql_query: `SELECT * FROM agent_errors WHERE profile_id = '${VALID_PROFILE_ID}'`,
      profile_id: VALID_PROFILE_ID,
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/LGPD|Security/);
  });

  it("rejects query against a non-whitelisted table", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createGetStudentContext(supabase);

    const result = await tool.invoke({
      sql_query: `SELECT * FROM knowledge_documents WHERE profile_id = '${VALID_PROFILE_ID}'`,
      profile_id: VALID_PROFILE_ID,
    });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/Security/);
  });
});
