#!/usr/bin/env node
/**
 * NUB-RD-86 (C1) — converte o arquivo resgatado do Snaps (materialização OIDC,
 * ADR-NUBO-DEPLOY-01) no YAML que `gcloud run deploy --env-vars-file` aplica.
 * O `--env-vars-file` SUBSTITUI o conjunto inteiro de variáveis do serviço: não
 * sobra variável velha de deploy anterior.
 *
 * Uso: node ts/scripts/ci/materialize-cloudrun-env.mjs <arquivo-resgatado> <saida.yaml> <supabase-ref-esperado>
 *   stdout: `::add-mask::<valor>` por valor e depois só os NOMES das chaves.
 *   Nunca imprime valor. Falha ANTES de escrever se o Supabase não for o esperado
 *   (o "banco errado" já aconteceu duas vezes neste serviço).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const CHAVE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const OBRIGATORIAS = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"];

/** Lê o formato do snaps-api (`_linha`): valor cru ou entre aspas simples. */
export function parseStackEnv(conteudo) {
  const valores = {};
  conteudo.split(/\r?\n/).forEach((linha, i) => {
    if (linha.trim() === "") return;
    const igual = linha.indexOf("=");
    const chave = igual > 0 ? linha.slice(0, igual) : "";
    if (!CHAVE.test(chave)) throw new Error(`arquivo resgatado fora do contrato na linha ${i + 1}`);
    let valor = linha.slice(igual + 1);
    if (valor.length >= 2 && valor.startsWith("'") && valor.endsWith("'")) valor = valor.slice(1, -1);
    valores[chave] = valor;
  });
  if (Object.keys(valores).length === 0) {
    throw new Error("arquivo resgatado vazio: o environment do Snaps não tem chaves");
  }
  return valores;
}

/** Exige as chaves do Supabase e o projeto esperado. Só cita nomes e refs públicos. */
export function conferirSupabase(valores, refEsperado) {
  const faltando = OBRIGATORIAS.filter((k) => !valores[k]);
  if (faltando.length > 0) throw new Error(`chave(s) obrigatória(s) ausente(s): ${faltando.join(", ")}`);
  const ref = (/^https:\/\/([a-z0-9]+)\.supabase\.co\/?$/.exec(valores.SUPABASE_URL) ?? [])[1] ?? "desconhecido";
  if (ref !== refEsperado) {
    throw new Error(`banco errado: SUPABASE_URL aponta para ${ref}, esperado ${refEsperado}`);
  }
}

export function linhasDeMascara(valores) {
  return Object.values(valores).filter((v) => v !== "").map((v) => `::add-mask::${v}`);
}

/** YAML de `--env-vars-file`: cada valor como string JSON (JSON é YAML válido). */
export function paraYamlDoCloudRun(valores) {
  return Object.keys(valores)
    .sort()
    .map((k) => `${k}: ${JSON.stringify(valores[k])}\n`)
    .join("");
}

export function materializar(conteudo, refEsperado) {
  const valores = parseStackEnv(conteudo);
  conferirSupabase(valores, refEsperado);
  return {
    chaves: Object.keys(valores).sort(),
    mascaras: linhasDeMascara(valores),
    yaml: paraYamlDoCloudRun(valores),
  };
}

function principal() {
  const [entrada, saida, ref] = process.argv.slice(2);
  if (!entrada || !saida || !ref) {
    console.error("uso: materialize-cloudrun-env.mjs <arquivo> <saida.yaml> <supabase-ref-esperado>");
    process.exit(2);
  }
  try {
    const r = materializar(readFileSync(entrada, "utf8"), ref);
    for (const m of r.mascaras) console.log(m);
    writeFileSync(saida, r.yaml, { mode: 0o600 });
    console.log(`config do Snaps materializada: ${r.chaves.length} chave(s): ${r.chaves.join(", ")}`);
  } catch (erro) {
    console.error(`::error::${erro.message}`);
    process.exit(1);
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) principal();
