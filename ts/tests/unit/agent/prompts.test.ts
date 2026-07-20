import { describe, it, expect, vi } from "vitest";
import {
  getLearningExamples,
  buildSystemPrompt,
  DDL_TABLES,
  TABLE_PURPOSE,
} from "../../../src/agent/prompts.js";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { AgentPromptRow } from "../../../src/agent/prompts.js";

// Mocka o query builder: .from().select().eq().order() -> Promise<{data, error}>
function makeSupabase(result: { data: unknown; error: unknown }) {
  const order = vi.fn().mockResolvedValue(result);
  const eq = vi.fn().mockReturnValue({ order });
  const select = vi.fn().mockReturnValue({ eq });
  const from = vi.fn().mockReturnValue({ select });
  return { client: { from } as unknown as SupabaseClient, from, select, eq, order };
}

describe("getLearningExamples", () => {
  it("lê de learning_examples e monta o bloco a partir de input_query/ideal_output", async () => {
    const m = makeSupabase({
      data: [
        {
          input_query: "Quero uma vaga mas não sei por onde começar.",
          ideal_output: 'Vou olhar seu perfil. <call tool="get_student_context">',
          intent_category: "geral",
        },
      ],
      error: null,
    });

    const out = await getLearningExamples(m.client);

    expect(m.from).toHaveBeenCalledWith("learning_examples");
    expect(out).toContain("## Exemplos de Interação");
    expect(out).toContain("Quero uma vaga mas não sei por onde começar.");
    expect(out).toContain("get_student_context"); // demonstração de tool vem do ideal_output
  });

  it("NÃO consulta a tabela inexistente few_shot_examples", async () => {
    const m = makeSupabase({ data: [], error: null });
    await getLearningExamples(m.client);
    expect(m.from).not.toHaveBeenCalledWith("few_shot_examples");
  });

  it("retorna string vazia em erro ou sem dados", async () => {
    const err = makeSupabase({ data: null, error: { message: "boom" } });
    expect(await getLearningExamples(err.client)).toBe("");

    const empty = makeSupabase({ data: [], error: null });
    expect(await getLearningExamples(empty.client)).toBe("");
  });
});

// Card "Erro ao alterar base de conhecimento" / plano N:N — a Cloudinha só usa
// knowledge_keywords e o join com oportunidades se essas tabelas estiverem em
// DDL_TABLES/TABLE_PURPOSE. Sem isso, a busca de KB fica restrita a title ILIKE
// mesmo quando keywords/partner_id já resolveriam a pergunta.
describe("visibilidade de schema para retrieval de Base de Conhecimento", () => {
  it("inclui knowledge_keywords e knowledge_document_opportunities em DDL_TABLES", () => {
    expect(DDL_TABLES).toContain("knowledge_keywords");
    expect(DDL_TABLES).toContain("knowledge_document_opportunities");
  });

  it("documenta o propósito de knowledge_keywords orientando o join com knowledge_documents", () => {
    expect(TABLE_PURPOSE.knowledge_keywords).toBeDefined();
    expect(TABLE_PURPOSE.knowledge_keywords.toLowerCase()).toContain("knowledge_documents");
  });

  it("documenta o propósito de knowledge_document_opportunities orientando o join por partner_opportunity_id", () => {
    expect(TABLE_PURPOSE.knowledge_document_opportunities).toBeDefined();
    expect(TABLE_PURPOSE.knowledge_document_opportunities.toLowerCase()).toContain(
      "partner_opportunity_id"
    );
  });

  it("atualiza o propósito de knowledge_documents para não depender só de título", () => {
    expect(TABLE_PURPOSE.knowledge_documents.toLowerCase()).not.toMatch(
      /^metadados de documentos\/editais \(título, storage_path\)/
    );
  });
});

describe("buildSystemPrompt — instrução de retrieval de Base de Conhecimento", () => {
  const promptRow: AgentPromptRow = {
    agent_key: "cloudinha_react",
    system_instruction: "{{SCHEMA_CONTEXT}} {{AVAILABLE_TOOLS}} {{CURRENT_DATETIME}}",
    model: "test-model",
    max_steps: 5,
    is_active: true,
  };

  it("instrui resolver a oportunidade por nome antes de buscar em knowledge_documents por título", () => {
    const out = buildSystemPrompt("-- schema --", promptRow);
    expect(out).toContain("knowledge_document_opportunities");
    expect(out).toContain("knowledge_keywords");
    // Ordem: resolver partner_opportunities -> join -> keywords -> título como último recurso.
    const partnerIdx = out.indexOf("partner_opportunities");
    const titleFallbackIdx = out.lastIndexOf("title ILIKE");
    expect(partnerIdx).toBeGreaterThan(-1);
    expect(titleFallbackIdx).toBeGreaterThan(partnerIdx);
  });
});
