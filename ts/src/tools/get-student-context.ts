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

// T3: Cap de output
const MAX_ROWS = 20;
const MAX_CHARS = 6000;

const schema = z.object({
  sql_query: z
    .string()
    .describe(
      "SQL SELECT query against student-specific tables. Must include profile_id filter for security. " +
        `Allowed tables: ${ALLOWED_TABLES.join(", ")}. ` +
        "Always filter by profile_id in the WHERE clause."
    ),
  profile_id: z.string().uuid().describe("UUID of the active student profile"),
});

// T4: Description rica
const TOOL_DESCRIPTION =
  "Executes a read-only SQL SELECT against student personal data tables. " +
  "USE for: checking student applications, ENEM scores, income, preferences, favorites, and opportunity matches. " +
  `Allowed tables: ${ALLOWED_TABLES.join(", ")}. ` +
  "DO NOT USE for: educational catalog data (use query_educational_catalog); document content (use download_knowledge_document). " +
  "Input: SQL SELECT with mandatory profile_id filter + profile_id UUID. " +
  "Returns: { results: [...], count: N } or an actionable error.";

export function createGetStudentContext(supabase: SupabaseClient): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "get_student_context",
    description: TOOL_DESCRIPTION,
    schema,
    func: async ({ sql_query, profile_id }) => {
      BLOCKED_PATTERN.lastIndex = 0;
      if (BLOCKED_PATTERN.test(sql_query)) {
        return JSON.stringify({ error: "LGPD: Query references restricted system tables." });
      }

      if (!sql_query.includes(profile_id)) {
        return JSON.stringify({
          error: "Security: query must contain profile_id for row-level enforcement.",
          hint: `Add WHERE profile_id = '${profile_id}' (or equivalent) to your query.`,
        });
      }

      const hasAllowedTable = ALLOWED_TABLES.some((t) =>
        new RegExp(`\\b${t}\\b`, "i").test(sql_query)
      );
      if (!hasAllowedTable) {
        return JSON.stringify({
          error: `Security: query must reference one of the allowed tables: ${ALLOWED_TABLES.join(", ")}.`,
          hint: "For educational catalog data, use query_educational_catalog instead.",
        });
      }

      const { data, error } = await supabase.rpc("execute_readonly_query", {
        query_text: sql_query,
      });

      if (error) {
        return JSON.stringify({
          error: `Database error: ${error.message}`,
          hint: `Check column names against the schema. Allowed tables: ${ALLOWED_TABLES.join(", ")}.`,
        });
      }

      // T3: Cap de linhas e chars
      const rows = data ?? [];
      const capped = rows.slice(0, MAX_ROWS);
      let output = JSON.stringify({ results: capped, count: rows.length });
      if (output.length > MAX_CHARS) {
        output = output.slice(0, MAX_CHARS) + `... [TRUNCATED — first ${capped.length} of ${rows.length} rows]`;
      }
      return output;
    },
  });
}

export { ALLOWED_TABLES, BLOCKED_PATTERN as STUDENT_BLOCKED_PATTERN };
