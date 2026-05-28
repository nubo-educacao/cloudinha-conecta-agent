import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.SUPABASE_URL || "https://yfgciamhzjvarwgzosto.supabase.co";
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY || "";
if (!SUPABASE_SERVICE_KEY) {
  console.error("Missing SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY env var");
  process.exit(1);
}
const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

async function updateIntents() {
  console.log("Updating system_intents...");

  // 1. Update step_change: enrich trigger_message with per-step guidance
  const stepChangeMessage = `O usuário avançou para o passo "{{step_name}}" (passo {{current_step}}) do formulário de {{form_type}}.

ORIENTAÇÕES POR PASSO (use a que corresponder a {{step_name}}):
- Dados Pessoais: Dê boas-vindas e explique que precisamos do nome e data de nascimento para personalizar as oportunidades e verificar elegibilidade por idade.
- Endereço: Explique que o endereço ajuda a encontrar vagas presenciais próximas e determinar elegibilidade em programas estaduais.
- Renda Familiar: Explique que a renda per capita é fundamental para determinar elegibilidade no ProUni (até 1,5 salário mínimo para bolsa integral, até 3 salários mínimos para parcial) e em bolsas do Sisu com critérios de renda. Quanto mais precisa a informação, melhor o match.
- Notas do ENEM: Explique que as notas do ENEM (de 0 a 1000 por área) são o principal critério de classificação no Sisu e ProUni. Elas são usadas para calcular o match com as vagas disponíveis. Se o estudante não lembrar das notas exatas, pode consultar no site do INEP.
- Interesses e Filtros: Explique que os filtros de curso, turno e tipo de instituição refinam o match para encontrar as vagas mais relevantes para o perfil do estudante.

Dê uma orientação BREVE (máx. 2-3 frases) e motivadora sobre o passo atual. Não repita informações que o usuário já preencheu.`;

  const { error: stepErr } = await supabase
    .from("system_intents")
    .update({ trigger_message: stepChangeMessage, description: "Orientação contextual por passo do formulário de Match/Candidatura." })
    .eq("command", "step_change");

  if (stepErr) {
    console.error("Failed to update step_change:", stepErr);
  } else {
    console.log("✅ step_change updated with contextual per-step guidance");
  }

  // 2. Update validation_error: also enrich with ENEM-specific guidance
  const validationErrorMessage = `O usuário encontrou um erro de validação no campo "{{field}}": {{error_message}}.

ORIENTAÇÕES ESPECÍFICAS:
- Se o erro for em nota do ENEM: Explique que cada nota do ENEM varia de 0 a 1000 pontos. As notas oficiais podem ser consultadas no site do INEP (https://enem.inep.gov.br/participante/).
- Se o erro for de renda: Explique com empatia que a informação é importante para encontrar programas compatíveis e que os dados são tratados com sigilo.
- Se o erro for de CPF: Explique que o CPF é usado apenas para verificação e não é compartilhado.
- Para qualquer outro erro: Ajude o usuário a corrigir de forma clara e amigável.

Seja breve e empática. Não julgue.`;

  const { error: valErr } = await supabase
    .from("system_intents")
    .update({ trigger_message: validationErrorMessage, description: "Orientação contextual para erros de validação em formulários." })
    .eq("command", "validation_error");

  if (valErr) {
    console.error("Failed to update validation_error:", valErr);
  } else {
    console.log("✅ validation_error updated with contextual field guidance");
  }

  console.log("Done!");
}

updateIntents();
