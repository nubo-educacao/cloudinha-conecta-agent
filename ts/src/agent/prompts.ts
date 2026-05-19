import type { SupabaseClient } from "@supabase/supabase-js";

export interface AgentPromptRow {
  agent_key: string;
  system_instruction: string;
  model: string;
  max_steps: number;
  temperature?: number;
  is_active: boolean;
}

export interface LeanContextParams {
  user_id: string;
  active_profile_id: string;
  full_name: string;
  age?: number;
  cognitive_memory?: string;
  recent_messages: { sender: string; content: string }[];
  ui_context?: {
    current_page?: string;
    focused_field?: string;
    form_state?: Record<string, unknown>;
    page_data?: Record<string, unknown>;
  };
}

// DDL tables to discover
const DDL_TABLES = [
  "v_unified_opportunities",
  "partner_opportunities",
  "partners",
  "knowledge_documents",
  "important_dates",
  "v_unified_institutions",
  "user_profiles",
  "user_enem_scores",
  "student_applications",
];

// Schema cache: 5 minute TTL
let _schemaCache: { ddl: string; expiresAt: number } | null = null;

export async function getSchemaContext(supabase: SupabaseClient): Promise<string> {
  const now = Date.now();
  if (_schemaCache && now < _schemaCache.expiresAt) {
    return _schemaCache.ddl;
  }

  // information_schema.columns does not include materialized views.
  // Use pg_catalog to cover tables, views, AND materialized views.
  const tableList = DDL_TABLES.map((t) => `'${t}'`).join(", ");
  const query = `
    SELECT
      c.relname AS table_name,
      a.attname AS column_name,
      pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
      CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    WHERE c.relname IN (${tableList})
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum
  `;

  const { data, error } = await supabase.rpc("execute_readonly_query", { query_text: query });
  if (error || !data) {
    return "-- Schema unavailable";
  }

  // Format as DDL-like summary
  const grouped: Record<string, { column_name: string; data_type: string; is_nullable: string }[]> =
    {};
  for (const row of data as {
    table_name: string;
    column_name: string;
    data_type: string;
    is_nullable: string;
  }[]) {
    if (!grouped[row.table_name]) grouped[row.table_name] = [];
    grouped[row.table_name].push({
      column_name: row.column_name,
      data_type: row.data_type,
      is_nullable: row.is_nullable,
    });
  }

  const ddl = Object.entries(grouped)
    .map(([table, cols]) => {
      const colDefs = cols
        .map(
          (c) => `  ${c.column_name} ${c.data_type}${c.is_nullable === "NO" ? " NOT NULL" : ""}`
        )
        .join(",\n");
      return `-- TABLE: ${table}\n(\n${colDefs}\n)`;
    })
    .join("\n\n");

  _schemaCache = { ddl, expiresAt: now + 5 * 60 * 1000 };
  return ddl;
}

export async function getAgentPrompt(supabase: SupabaseClient): Promise<AgentPromptRow | null> {
  const { data, error } = await supabase
    .from("agent_prompts")
    .select("agent_key, system_instruction, model, max_steps, temperature, is_active")
    .eq("agent_key", "cloudinha_react")
    .eq("is_active", true)
    .limit(1);

  if (error || !data || data.length === 0) return null;
  return data[0] as AgentPromptRow;
}

export function buildSystemPrompt(schemaContext: string, promptRow: AgentPromptRow): string {
  return promptRow.system_instruction
    .replace("{{SCHEMA_CONTEXT}}", schemaContext)
    .replace(
      "{{AVAILABLE_TOOLS}}",
      "query_educational_catalog, get_student_context, download_knowledge_document"
    );
}

export function buildLeanContext(params: LeanContextParams): string {
  const lines: string[] = [];

  lines.push(`[CONTEXTO DO USUÁRIO]`);
  lines.push(`user_id: ${params.user_id}`);
  lines.push(`active_profile_id: ${params.active_profile_id}`);
  lines.push(`nome: ${params.full_name}`);
  if (params.age !== undefined) lines.push(`idade: ${params.age} anos`);
  if (params.cognitive_memory) {
    lines.push(`\n[MEMÓRIA COGNITIVA]\n${params.cognitive_memory}`);
  }

  if (params.recent_messages.length > 0) {
    lines.push(`\n[HISTÓRICO RECENTE]`);
    for (const msg of params.recent_messages) {
      const sender = msg.sender === "cloudinha" ? "Cloudinha" : "Usuário";
      lines.push(`${sender}: ${msg.content}`);
    }
  }

  if (params.ui_context?.current_page) {
    lines.push(`\n[CONTEXTO DA INTERFACE]`);
    lines.push(`página atual: ${params.ui_context.current_page}`);
    if (params.ui_context.focused_field) {
      lines.push(`campo em foco: ${params.ui_context.focused_field}`);
    }
    if (params.ui_context.form_state) {
      lines.push(`estado do formulário: ${JSON.stringify(params.ui_context.form_state)}`);
    }
  }

  return lines.join("\n");
}
