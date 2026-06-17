import { describe, it, expect, vi } from "vitest";
import { getLearningExamples } from "../../../src/agent/prompts.js";
import type { SupabaseClient } from "@supabase/supabase-js";

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
