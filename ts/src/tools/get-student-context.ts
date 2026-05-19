import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";

const ALLOWED_TABLES = [
  "student_applications",
  "user_opportunity_matches",
  "user_profiles",
  "user_preferences",
  "user_income",
  "user_enem_scores",
  "user_favorites",
];

// Same blocklist as catalog tool — shared private tables not in whitelist
const BLOCKED_TABLES = [
  "users_metadata",
  "chat_messages",
  "agent_errors",
  "agent_turns",
  "agent_prompts",
  "auth",
];

const BLOCKED_PATTERN = new RegExp(
  `\\b(${BLOCKED_TABLES.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`,
  "gi"
);

const schema = z.object({
  sql_query: z
    .string()
    .describe(
      "SQL SELECT query against student-specific tables. Must include profile_id filter for security. " +
        `Allowed tables: ${ALLOWED_TABLES.join(", ")}.`
    ),
  profile_id: z.string().uuid().describe("UUID of the active student profile"),
});

export function createGetStudentContext(supabase: SupabaseClient): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "get_student_context",
    description:
      "Executes a read-only SQL query against student personal data tables. " +
      "The query MUST contain the profile_id to enforce row-level security. " +
      "Use for applications, scores, income, preferences.",
    schema,
    func: async ({ sql_query, profile_id }) => {
      BLOCKED_PATTERN.lastIndex = 0;
      if (BLOCKED_PATTERN.test(sql_query)) {
        return JSON.stringify({ error: "LGPD: Query references restricted system tables." });
      }

      if (!sql_query.includes(profile_id)) {
        return JSON.stringify({
          error: "Security: query must contain profile_id for row-level enforcement.",
        });
      }

      const hasAllowedTable = ALLOWED_TABLES.some((t) =>
        new RegExp(`\\b${t}\\b`, "i").test(sql_query)
      );
      if (!hasAllowedTable) {
        return JSON.stringify({
          error: `Security: query must reference one of the allowed tables: ${ALLOWED_TABLES.join(", ")}.`,
        });
      }

      const { data, error } = await supabase.rpc("execute_readonly_query", {
        query_text: sql_query,
      });

      if (error) {
        return JSON.stringify({ error: `Database error: ${error.message}` });
      }

      return JSON.stringify({ results: data ?? [], count: (data ?? []).length });
    },
  });
}

export { ALLOWED_TABLES, BLOCKED_PATTERN as STUDENT_BLOCKED_PATTERN };
