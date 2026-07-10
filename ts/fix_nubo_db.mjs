import { createClient } from '@supabase/supabase-js';

const DEV_URL = 'https://yfgciamhzjvarwgzosto.supabase.co';
const DEV_SERVICE_KEY = process.env.DEV_SERVICE_KEY;

const supabase = createClient(DEV_URL, DEV_SERVICE_KEY);

async function fixIntents() {
  // validation_error should ONLY pulsate (not open drawer) — user is mid-form
  const { error: e1 } = await supabase
    .from('system_intents')
    .update({ open_drawer: false })
    .eq('command', 'validation_error');
  console.log('validation_error -> open_drawer=false:', e1 ?? 'OK');

  // Verify final state
  const { data } = await supabase
    .from('system_intents')
    .select('command, open_drawer, is_active')
    .order('command');
  console.table(data);
}

fixIntents();
