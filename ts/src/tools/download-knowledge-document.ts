import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";

// T3: Cap de conteúdo — ~12k chars para não inflar contexto
const MAX_CONTENT_CHARS = 12000;

const schema = z.object({
  storage_path: z
    .string()
    .describe(
      "Exact path to the markdown file in the knowledge-base storage bucket. " +
        "Example: 'documents/edital_prouni_2026.md'. " +
        "NEVER guess or invent this path — always obtain it first via query_educational_catalog " +
        "with: SELECT storage_path FROM knowledge_documents WHERE title ILIKE '%term%' LIMIT 5."
    ),
});

// T4: Description rica com quando usar / quando NÃO usar
const TOOL_DESCRIPTION =
  "Downloads the full markdown content of a document from the knowledge-base storage bucket. " +
  "USE for: answering questions about ProUni, Sisu, FIES, partner programs, editais, and any Nubo knowledge content. " +
  "DO NOT USE without first querying knowledge_documents to get the exact storage_path — never guess the path. " +
  "DO NOT USE for searching opportunities (use query_educational_catalog instead). " +
  "Input: exact storage_path obtained from knowledge_documents.storage_path column. " +
  "Returns: { content: '...markdown...', path: '...' } or an actionable error guiding you to find the correct path.";

export function createDownloadKnowledgeDocument(supabase: SupabaseClient): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "download_knowledge_document",
    description: TOOL_DESCRIPTION,
    schema,
    func: async ({ storage_path }) => {
      const { data, error } = await supabase.storage
        .from("knowledge-base")
        .download(storage_path);

      if (error) {
        // Erro real do Storage (permissão, rede, etc.) — surface a mensagem real,
        // distinto de "não achou o documento" (ver bloco abaixo).
        return JSON.stringify({
          error: `Storage error: ${error.message}`,
          hint:
            "To find the correct path, use query_educational_catalog with: " +
            "SELECT title, storage_path FROM knowledge_documents WHERE title ILIKE '%<keyword>%' LIMIT 5. " +
            "Then use the exact storage_path value returned.",
        });
      }

      if (!data) {
        // T3: Dica acionável — instrui o agente a buscar o storage_path via query
        return JSON.stringify({
          error: `Document not found at path: '${storage_path}'.`,
          hint:
            "To find the correct path, use query_educational_catalog with: " +
            "SELECT title, storage_path FROM knowledge_documents WHERE title ILIKE '%<keyword>%' LIMIT 5. " +
            "Then use the exact storage_path value returned.",
        });
      }

      let content = new TextDecoder("utf-8").decode(await data.arrayBuffer());

      // T3: Cap de conteúdo para não inflar contexto
      let truncated = false;
      if (content.length > MAX_CONTENT_CHARS) {
        content = content.slice(0, MAX_CONTENT_CHARS);
        truncated = true;
      }

      return JSON.stringify({
        content,
        path: storage_path,
        ...(truncated && { warning: `Content truncated to ${MAX_CONTENT_CHARS} chars to preserve context.` }),
      });
    },
  });
}
