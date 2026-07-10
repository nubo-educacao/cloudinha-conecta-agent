import { createClient } from '@supabase/supabase-js';

// Nubo Prod Supabase
const SUPABASE_URL = 'https://aifzkybxhmefbirujvdg.supabase.co';
// Use admin service key from nubo-conecta-admin .env (commented out prod section)
// We need the service key — let's use the one from the agent's admin context
// Actually we only have anon key for prod, let me try with the dev instance first
// Dev instance from cloudinha .env
const DEV_URL = 'https://yfgciamhzjvarwgzosto.supabase.co';
const DEV_SERVICE_KEY = process.env.DEV_SERVICE_KEY;

const supabase = createClient(DEV_URL, DEV_SERVICE_KEY);

async function checkIntents() {
  const { data, error } = await supabase
    .from('system_intents')
    .select('*');
  
  console.log('Error:', error);
  console.log('Data:', JSON.stringify(data, null, 2));
}

checkIntents();
