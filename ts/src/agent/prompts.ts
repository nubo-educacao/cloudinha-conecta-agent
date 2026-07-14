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
  "user_opportunity_matches",
];

// ADR-0015: Entity Mapping via DDL Injection — o propósito de cada tabela é injetado
// junto do DDL para reduzir confusão entre tabelas com colunas de nome parecido
// (ex.: `description` existe em partner_opportunities mas não em v_unified_opportunities).
// Isto é orientação POSITIVA ("use esta tabela para X"), não uma regra negativa.
const TABLE_PURPOSE: Record<string, string> = {
  v_unified_opportunities:
    "Catálogo público unificado (Sisu + ProUni + Parceiros). Use para QUALQUER busca geral de oportunidades: curso, instituição, tipo, status, vagas, localização.",
  partner_opportunities:
    "Dados brutos específicos de UMA oportunidade de parceiro (ex.: description). Só consulte aqui quando já tiver o id do parceiro e precisar de um campo que não existe em v_unified_opportunities.",
  partners: "Cadastro de instituições parceiras.",
  knowledge_documents:
    "Metadados de documentos/editais (título, storage_path). Use para achar o storage_path antes de chamar download_knowledge_document.",
  important_dates: "Datas importantes do calendário educacional (Sisu, ProUni, editais).",
  v_unified_institutions: "Catálogo unificado de instituições (MEC + parceiras).",
  user_opportunity_matches:
    "Match Score e explicação de compatibilidade do aluno com uma oportunidade. SEMPRE consultar via get_student_context (NUNCA query_educational_catalog), filtrando por profile_id e unified_opportunity_id.",
};

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
      AND a.attname != 'external_redirect_config'
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
      const purpose = TABLE_PURPOSE[table];
      const purposeLine = purpose ? `-- USO: ${purpose}\n` : "";
      return `-- TABLE: ${table}\n${purposeLine}(\n${colDefs}\n)`;
    })
    .join("\n\n");

  // ADR-0015: BOOLEAN columns grounding — derivado do data_type real (não hardcoded),
  // então nunca fica desatualizado. Evita comparações inválidas tipo `coluna > 0` numa
  // coluna boolean.
  const allRows = data as { table_name: string; column_name: string; data_type: string }[];
  const booleanCols = allRows
    .filter((r) => r.data_type === "boolean")
    .map((r) => `${r.table_name}.${r.column_name}`);
  const booleanBlock =
    booleanCols.length > 0
      ? `\n\n-- COLUNAS BOOLEAN (comparar com = true / = false — NUNCA com > 0 ou outro operador numérico):\n  ${booleanCols.join(", ")}`
      : "";

  // T2: Grounding de valores — busca DISTINCT das colunas categóricas de v_unified_opportunities.
  // Derivado dos dados reais (auto-corrige se um valor for descontinuado, ex.: 'approved' → 'opened'),
  // em vez de hardcodar o valor válido em prosa.
  const categoricalCols = ["type", "opportunity_type", "category", "location", "status"];
  const valueLines: string[] = [];
  for (const col of categoricalCols) {
    const { data: valData } = await supabase.rpc("execute_readonly_query", {
      query_text: `SELECT DISTINCT ${col} FROM v_unified_opportunities WHERE ${col} IS NOT NULL ORDER BY ${col} LIMIT 30`,
    });
    if (valData && Array.isArray(valData) && valData.length > 0) {
      const vals = (valData as Record<string, unknown>[])
        .map((r) => r[col])
        .filter(Boolean)
        .map((v) => `'${v}'`)
        .join(", ");
      if (vals) valueLines.push(`  ${col} ∈ {${vals}}`);
    }
  }
  const groundingBlock =
    valueLines.length > 0
      ? `\n\n-- VALORES VÁLIDOS em v_unified_opportunities (não invente outros):\n${valueLines.join("\n")}`
      : "";

  const fullDdl = ddl + booleanBlock + groundingBlock;
  _schemaCache = { ddl: fullDdl, expiresAt: now + 5 * 60 * 1000 };
  return fullDdl;
}

const FEW_SHOT_TOKEN_CAP = 2000; // ~8-10 examples

export async function getLearningExamples(supabase: SupabaseClient): Promise<string> {
  // Fonte: tabela `learning_examples` (colunas reais: input_query, ideal_output,
  // intent_category, is_active, created_at). O ideal_output já contém a demonstração
  // de tool call (ex.: <call tool="get_student_context">), então o exemplo ensina o
  // uso da ferramenta por demonstração — não há coluna de "tools" separada.
  const { data, error } = await supabase
    .from("learning_examples")
    .select("input_query, ideal_output, intent_category")
    .eq("is_active", true)
    .order("created_at", { ascending: true });

  if (error || !data || data.length === 0) return "";

  const blocks: string[] = [];
  let approxTokens = 0;

  for (let i = 0; i < data.length; i++) {
    const ex = data[i] as {
      input_query: string;
      ideal_output: string;
      intent_category: string | null;
    };

    const header = ex.intent_category
      ? `### Exemplo ${i + 1} (${ex.intent_category})`
      : `### Exemplo ${i + 1}`;

    const block = `${header}
**Usuário:** "${ex.input_query}"
**Resposta esperada:** "${ex.ideal_output}"`;

    // ~4 chars per token approximation
    approxTokens += Math.ceil(block.length / 4);
    if (approxTokens > FEW_SHOT_TOKEN_CAP) break;

    blocks.push(block);
  }

  if (blocks.length === 0) return "";

  return `## Exemplos de Interação\n\n${blocks.join("\n\n")}`;
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

export function buildSystemPrompt(
  schemaContext: string,
  promptRow: AgentPromptRow,
  learningExamplesBlock = ""
): string {
  const now = new Date().toLocaleString('pt-BR', {
    timeZone: 'America/Sao_Paulo',
    dateStyle: 'full',
    timeStyle: 'short',
  });

  const smartLinksInstruction = `
## Links de Navegação
Quando você mencionar uma oportunidade ou instituição específica que encontrou via query, inclua um link markdown para que o usuário possa navegar diretamente:
- Oportunidades: [Nome do Curso - Instituição](/oportunidades/{unified_id})
- Instituições: [Nome da Instituição](/instituicoes/{institution_id})

Inclua links apenas quando tiver o ID real retornado pela ferramenta. Nunca invente IDs.`;

  // ADR-0015: Entity Mapping — mapeamento POSITIVO de conceito de negócio → coluna real.
  // Regras sobre valores válidos, tipos boolean e propósito de cada tabela vêm do
  // schemaContext (DDL real, ver getSchemaContext), não são hardcoded aqui — isso evita
  // que a instrução fique desatualizada quando o schema/dados mudam (ex.: status
  // 'approved' → 'opened').
  const entityMappingInstruction = `
## Dicionário de Dados e Mapeamento de Entidades
Conceito de negócio → coluna real em \`v_unified_opportunities\` (para nomes de coluna, tipos, valores válidos e qual tabela usar, SEMPRE confie no schema acima — ele reflete o banco real e é atualizado a cada consulta):
- **Nome do curso/programa**: coluna \`title\`.
- **Nome da instituição**: coluna \`provider_name\`.
- **Tipo da oportunidade**: coluna \`type\`.
- **Match Score e explicação de compatibilidade**: NÃO existem em \`v_unified_opportunities\`. Para explicar por que uma oportunidade combina com o aluno, use \`get_student_context\` para consultar \`user_opportunity_matches\` (colunas \`match_score\`, \`match_details\`) filtrando por \`profile_id\` e \`unified_opportunity_id\`.

## Recuperação de Erros de Tool (genérico — vale para QUALQUER tabela, não só as citadas acima)
Se uma tool retornar um campo \`error\` (ex.: "column does not exist"), isso NÃO é o fim do turno: remova a coluna inválida da query usando o schema acima como referência e chame a tool DE NOVO no mesmo turno, antes de responder ao usuário. Só desista e explique o problema ao usuário após uma segunda tentativa também falhar.`;

  const editalRulesInstruction = `
## Regras de Editais (Sisu/ProUni)
Para QUALQUER dúvida sobre regras, prazos ou critérios do Sisu ou ProUni, primeiro localize o documento correspondente via \`query_educational_catalog\` (tabela \`knowledge_documents\`) e leia o conteúdo com \`download_knowledge_document\`. É PROIBIDO responder com conhecimento paramétrico sobre regras de editais.`;

  let built = promptRow.system_instruction
    .replace("{{SCHEMA_CONTEXT}}", schemaContext)
    .replace(
      "{{AVAILABLE_TOOLS}}",
      "query_educational_catalog, get_student_context, download_knowledge_document"
    )
    .replace(/\{\{CURRENT_DATETIME\}\}/g, now);

  // T1: Injeção resiliente de learning_examples.
  // Se o placeholder existe no template, substitui normalmente.
  // Se não existe (ex.: backoffice removeu), APPENDE o bloco ao final em vez de descartá-lo.
  if (built.includes("{{LEARNING_EXAMPLES}}")) {
    built = built.replace("{{LEARNING_EXAMPLES}}", learningExamplesBlock);
  } else if (learningExamplesBlock) {
    built = built + "\n\n" + learningExamplesBlock;
  }

  return built + smartLinksInstruction + entityMappingInstruction + editalRulesInstruction;
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
