import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";

const BLOCKED_TABLES = [
  "user_profiles",
  "user_preferences",
  "user_enem_scores",
  "user_income",
  "users_metadata",
  "user_opportunity_matches",
  "student_applications",
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
      "SQL SELECT query against the educational catalog (public tables only). " +
        "Accessible tables: v_unified_opportunities, partners, knowledge_documents, " +
        "important_dates, partner_opportunities, v_unified_institutions."
    ),
});

export function createQueryEducationalCatalog(supabase: SupabaseClient): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "query_educational_catalog",
    description:
      "Executes a read-only SQL query against the public educational catalog. " +
      "Use this to search for opportunities, institutions, knowledge documents, and important dates. " +
      "Do NOT use for student personal data.",
    schema,
    func: async ({ sql_query }) => {
      // A RPC embrulha a query como `SELECT ... FROM (<sql>) t`, então um ';'
      // final causa erro de sintaxe. Removemos ';' e espaços nas pontas.
      const cleanedQuery = sql_query.replace(/;\s*$/g, "").trim();

      // Reset lastIndex for global regex
      BLOCKED_PATTERN.lastIndex = 0;
      if (BLOCKED_PATTERN.test(cleanedQuery)) {
        return JSON.stringify({
          error: "LGPD: Query references restricted tables. Use get_student_context for personal data.",
        });
      }

      const { data, error } = await supabase.rpc("execute_readonly_query", {
        query_text: cleanedQuery,
      });

      if (error) {
        return JSON.stringify({ error: `Database error: ${error.message}` });
      }

      // Hard block: Strip out external_redirect_config from any result
      // This prevents the agent from leaking the URL by completely hiding it
      const sanitizedData = (data ?? []).map((row: any) => {
        if (row && typeof row === 'object' && 'external_redirect_config' in row) {
          const { external_redirect_config, ...rest } = row;
          return rest;
        }
        return row;
      });

      return JSON.stringify({ results: sanitizedData, count: sanitizedData.length });
    },
  });
}

// Export pattern for testing
export { BLOCKED_PATTERN };
