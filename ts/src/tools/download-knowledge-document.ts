import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";

const schema = z.object({
  storage_path: z
    .string()
    .describe(
      "Path to the markdown file in the knowledge-base storage bucket. " +
        "Example: 'documents/edital_prouni_2026.md'"
    ),
});

export function createDownloadKnowledgeDocument(supabase: SupabaseClient): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "download_knowledge_document",
    description:
      "Downloads the full markdown content of a document from the knowledge-base storage bucket. " +
      "MANDATORY for ProUni, Sisu, and partner program questions — never answer from parametric knowledge.",
    schema,
    func: async ({ storage_path }) => {
      const { data, error } = await supabase.storage
        .from("knowledge-base")
        .download(storage_path);

      if (error || !data) {
        return JSON.stringify({
          error: `Storage error: ${error?.message ?? "document not found at path: " + storage_path}`,
        });
      }

      const content = new TextDecoder("utf-8").decode(await data.arrayBuffer());
      return JSON.stringify({ content, path: storage_path });
    },
  });
}
