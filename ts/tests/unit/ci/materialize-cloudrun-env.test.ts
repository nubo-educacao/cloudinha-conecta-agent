/**
 * NUB-RD-86 (C1) — o deploy da Cloudinha recebe a config do Snaps PROD
 * (materialização OIDC, ADR-NUBO-DEPLOY-01) em vez das substitutions do trigger
 * do Cloud Build, onde o "banco errado" já aconteceu duas vezes.
 *
 * Contrato do arquivo resgatado: snaps-api services/materializacao.py `_linha`
 * (valor cru ou entre aspas simples, sem interpolação).
 */
import { describe, expect, it } from "vitest";
import {
  conferirSupabase,
  linhasDeMascara,
  materializar,
  paraYamlDoCloudRun,
  parseStackEnv,
} from "../../../scripts/ci/materialize-cloudrun-env.mjs";

const PROD = "aifzkybxhmefbirujvdg";
const ARQUIVO = [
  `SUPABASE_URL=https://${PROD}.supabase.co`,
  "SUPABASE_SERVICE_KEY=sb_secret_sentinela",
  "GOOGLE_API_KEY='chave com $VAR # e: dois pontos'",
  "",
].join("\n");

describe("parseStackEnv", () => {
  it("lê valor cru e entre aspas simples sem alterar nada", () => {
    expect(parseStackEnv(ARQUIVO)).toEqual({
      SUPABASE_URL: `https://${PROD}.supabase.co`,
      SUPABASE_SERVICE_KEY: "sb_secret_sentinela",
      GOOGLE_API_KEY: "chave com $VAR # e: dois pontos",
    });
  });

  it("recusa linha fora do contrato citando só o número da linha", () => {
    expect(() => parseStackEnv("SEM_IGUAL_sentinela")).toThrow(/linha 1/);
    expect(() => parseStackEnv("SEM_IGUAL_sentinela")).not.toThrow(/sentinela/);
  });

  it("recusa arquivo vazio", () => {
    expect(() => parseStackEnv("\n")).toThrow(/vazio/);
  });
});

describe("paraYamlDoCloudRun", () => {
  it("gera YAML com valores entre aspas duplas escapadas (JSON é YAML válido)", () => {
    expect(paraYamlDoCloudRun({ A: "simples", B: 'tem "aspas", $VAR, # e: dois pontos' })).toBe(
      'A: "simples"\nB: "tem \\"aspas\\", $VAR, # e: dois pontos"\n',
    );
  });

  it("ordena as chaves para o arquivo ser determinístico", () => {
    expect(paraYamlDoCloudRun({ Z: "1", A: "2" })).toBe('A: "2"\nZ: "1"\n');
  });
});

describe("conferirSupabase", () => {
  it("aceita o ref esperado e exige as duas chaves do Supabase", () => {
    expect(() =>
      conferirSupabase(
        { SUPABASE_URL: `https://${PROD}.supabase.co`, SUPABASE_ANON_KEY: "a", SUPABASE_SERVICE_KEY: "s" },
        PROD,
      ),
    ).not.toThrow();
  });

  it("recusa o banco errado (DEV em produção), citando só os refs públicos", () => {
    expect(() =>
      conferirSupabase(
        { SUPABASE_URL: "https://yfgciamhzjvarwgzosto.supabase.co", SUPABASE_ANON_KEY: "a", SUPABASE_SERVICE_KEY: "s-sentinela" },
        PROD,
      ),
    ).toThrow(/yfgciamhzjvarwgzosto/);
  });

  it("recusa quando falta chave obrigatória, citando só o nome", () => {
    expect(() =>
      conferirSupabase({ SUPABASE_URL: `https://${PROD}.supabase.co`, SUPABASE_ANON_KEY: "a" }, PROD),
    ).toThrow(/SUPABASE_SERVICE_KEY/);
  });
});

describe("materializar", () => {
  it("devolve nomes, máscaras e o YAML, e recusa o banco errado antes de qualquer saída", () => {
    const completo = ARQUIVO + "SUPABASE_ANON_KEY=anon\n";
    const r = materializar(completo, PROD);
    expect(r.chaves).toEqual(["GOOGLE_API_KEY", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_URL"]);
    expect(r.mascaras).toContain("::add-mask::sb_secret_sentinela");
    expect(r.yaml).toContain('SUPABASE_SERVICE_KEY: "sb_secret_sentinela"');
    expect(() => materializar(completo.replace(PROD, "yfgciamhzjvarwgzosto"), PROD)).toThrow(/banco/);
  });

  it("mascara todo valor não vazio", () => {
    expect(linhasDeMascara({ A: "x", B: "" })).toEqual(["::add-mask::x"]);
  });
});
