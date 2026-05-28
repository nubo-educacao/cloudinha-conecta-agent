import { describe, it, expect, vi } from "vitest";
import { createDownloadKnowledgeDocument } from "../../../src/tools/download-knowledge-document.js";
import type { SupabaseClient } from "@supabase/supabase-js";

function makeSupabase(downloadResult: { data: unknown; error: unknown }) {
  return {
    storage: {
      from: vi.fn().mockReturnValue({
        download: vi.fn().mockResolvedValue(downloadResult),
      }),
    },
  } as unknown as SupabaseClient;
}

function makeBlob(content: string): Blob {
  return new Blob([content], { type: "text/markdown" });
}

describe("download_knowledge_document", () => {
  it("downloads existing document and returns content", async () => {
    const content = "# ProUni 2026\n\nEdital completo...";
    const supabase = makeSupabase({ data: makeBlob(content), error: null });
    const tool = createDownloadKnowledgeDocument(supabase);

    const result = await tool.invoke({ storage_path: "documents/edital_prouni_2026.md" });
    const parsed = JSON.parse(result);

    expect(parsed.content).toBe(content);
    expect(parsed.path).toBe("documents/edital_prouni_2026.md");
  });

  it("returns error for non-existent path", async () => {
    const supabase = makeSupabase({ data: null, error: { message: "Object not found" } });
    const tool = createDownloadKnowledgeDocument(supabase);

    const result = await tool.invoke({ storage_path: "documents/nonexistent.md" });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/Storage error/);
  });

  it("returns error when data is null without error object", async () => {
    const supabase = makeSupabase({ data: null, error: null });
    const tool = createDownloadKnowledgeDocument(supabase);

    const result = await tool.invoke({ storage_path: "documents/missing.md" });
    const parsed = JSON.parse(result);

    expect(parsed.error).toMatch(/document not found/);
  });
});
