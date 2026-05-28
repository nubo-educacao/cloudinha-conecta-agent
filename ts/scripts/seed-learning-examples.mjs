import { createClient } from "@supabase/supabase-js";
import fs from "fs";
import path from "path";

const SUPABASE_URL = process.env.SUPABASE_URL || "https://yfgciamhzjvarwgzosto.supabase.co";
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY || "";
if (!SUPABASE_SERVICE_KEY) {
  console.error("Missing SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY env var");
  process.exit(1);
}
const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

const examples = [
  {
    intent_category: 'geral',
    input_query: 'Quais bolsas combinam com o meu perfil?',
    ideal_output: 'Para descobrir as melhores bolsas para o seu perfil, preciso conferir o seu histórico e preferências!\n\n<call tool="get_student_context">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'geral',
    input_query: 'Quero uma vaga mas não sei por onde começar.',
    ideal_output: 'Fico muito feliz que você queira dar esse passo! Para te guiar da melhor forma, vou dar uma olhada no seu perfil.\n\n<call tool="get_student_context">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'geral',
    input_query: 'Quero entender a diferença entre ProUni e SISU.',
    ideal_output: 'Ótima pergunta! Vou consultar as regras oficiais para te explicar com precisão.\n\n<call tool="query_educational_catalog" target="knowledge_documents">\n<call tool="download_knowledge_document">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'parceiro',
    input_query: 'Qual a melhor universidade perto de mim?',
    ideal_output: 'Vamos encontrar as melhores instituições na sua região! Vou consultar as opções disponíveis.\n\n<call tool="query_educational_catalog" target="v_unified_institutions">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'parceiro',
    input_query: 'O que significa IGC?',
    ideal_output: 'O IGC (Índice Geral de Cursos) é uma métrica do MEC. Vou pegar a explicação completa nos nossos documentos.\n\n<call tool="query_educational_catalog" target="knowledge_documents">\n<call tool="download_knowledge_document">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'parceiro',
    input_query: 'Quais faculdades são parceiras do Nubo?',
    ideal_output: 'Temos várias instituições parceiras incríveis! Vou listar algumas delas para você.\n\n<call tool="query_educational_catalog" target="partners">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'prouni',
    input_query: 'O que é nota de corte?',
    ideal_output: 'A nota de corte é a pontuação mínima necessária para entrar em um curso. Vou consultar os detalhes sobre isso nos documentos.\n\n<call tool="query_educational_catalog" target="knowledge_documents">\n<call tool="download_knowledge_document">',
    is_active: true,
    source: 'seed'
  },
  {
    intent_category: 'candidatura',
    input_query: 'Quais documentos preciso para me candidatar?',
    ideal_output: 'Os documentos podem variar dependendo da bolsa ou programa. Vou buscar a lista exata para você.\n\n<call tool="query_educational_catalog" target="knowledge_documents">\n<call tool="download_knowledge_document">',
    is_active: true,
    source: 'seed'
  }
];

async function seed() {
  console.log("Seeding learning_examples...");
  // Clear old seeds if needed (or just insert new ones)
  const { error: delErr } = await supabase.from('learning_examples').delete().eq('source', 'seed');
  if (delErr) {
    console.error("Failed to clean old seeds", delErr);
  }

  const { data, error } = await supabase
    .from('learning_examples')
    .insert(examples)
    .select();

  if (error) {
    console.error("Error inserting examples", error);
  } else {
    console.log(`Inserted ${data.length} learning examples successfully.`);
  }
}

seed();
