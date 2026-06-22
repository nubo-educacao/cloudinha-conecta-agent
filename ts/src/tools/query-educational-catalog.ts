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

// T3: Cap de output — evita inflar contexto com resultados enormes
const MAX_ROWS = 30;
const MAX_CHARS = 8000;

const schema = z.object({
  sql_query: z
    .string()
    .describe(
      "SQL SELECT query against the educational catalog (public tables only). " +
        "Accessible tables: v_unified_opportunities, partners, knowledge_documents, " +
        "important_dates, partner_opportunities, v_unified_institutions. " +
        "Column names come from {{SCHEMA_CONTEXT}}. Use 'title' for course name (NOT 'name'). " +
        "Use ILIKE for text search. Never use columns not listed in the schema. " +
        "Do NOT add a trailing semicolon — the query is wrapped internally."
    ),
});

// T4: Description rica com quando usar / quando NÃO usar / formato de entrada
const TOOL_DESCRIPTION =
  "Executes a read-only SQL SELECT against the public educational catalog. " +
  "USE for: searching opportunities by title/location/type/institution; listing partners; finding important dates; querying knowledge_documents metadata. " +
  "DO NOT USE for: student personal data (use get_student_context); downloading document content (use download_knowledge_document). " +
  "Input: valid SQL SELECT. Columns must match {{SCHEMA_CONTEXT}}. " +
  "Returns: { results: [...], count: N } or an actionable error with valid columns listed.";

export function createQueryEducationalCatalog(supabase: SupabaseClient): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "query_educational_catalog",
    description: TOOL_DESCRIPTION,
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
        // T3: Dica acionável em erro de coluna/sintaxe
        const hint =
          "Check column names against {{SCHEMA_CONTEXT}}. Common fixes: " +
          "use 'title' (not 'name') for course name; " +
          "use 'location' (not 'state'/'city') for geography; " +
          "use 'provider_name' (not 'university_name') for institution name; " +
          "use ILIKE for text matching.";
        return JSON.stringify({ error: `Database error: ${error.message}`, hint });
      }

      // Hard block: Strip out external_redirect_config from any result
      const sanitizedData = (data ?? []).map((row: any) => {
        if (row && typeof row === "object" && "external_redirect_config" in row) {
          const { external_redirect_config, ...rest } = row;
          return rest;
        }
        return row;
      });

      // T3: Cap de linhas e chars
      const capped = sanitizedData.slice(0, MAX_ROWS);
      let output = JSON.stringify({ results: capped, count: sanitizedData.length });
      if (output.length > MAX_CHARS) {
        output = output.slice(0, MAX_CHARS);
        return output + `... [TRUNCATED — returned first ${capped.length} rows of ${sanitizedData.length}]`;
      }

      // T3: Dica acionável em 0 resultados
      if (capped.length === 0) {
        return JSON.stringify({
          results: [],
          count: 0,
          hint:
            "No rows found. Suggestions: " +
            "(1) Use ILIKE '%term%' instead of = for text columns. " +
            "(2) Check valid values for 'type', 'opportunity_type', 'category', 'location' in {{SCHEMA_CONTEXT}}. " +
            "(3) Remove invented filters — only use columns listed in the schema.",
        });
      }

      return output;
    },
  });
}

// Export pattern for testing
export { BLOCKED_PATTERN };
