import type { SupabaseClient } from "@supabase/supabase-js";
import type { DynamicStructuredTool } from "@langchain/core/tools";
import { createQueryEducationalCatalog } from "./query-educational-catalog.js";
import { createGetStudentContext } from "./get-student-context.js";
import { createDownloadKnowledgeDocument } from "./download-knowledge-document.js";

export { createQueryEducationalCatalog } from "./query-educational-catalog.js";
export { createGetStudentContext } from "./get-student-context.js";
export { createDownloadKnowledgeDocument } from "./download-knowledge-document.js";

export function createTools(supabase: SupabaseClient): DynamicStructuredTool[] {
  return [
    createQueryEducationalCatalog(supabase),
    createGetStudentContext(supabase),
    createDownloadKnowledgeDocument(supabase),
  ];
}
