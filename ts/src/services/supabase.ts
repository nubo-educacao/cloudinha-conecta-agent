import { createClient, SupabaseClient } from "@supabase/supabase-js";

let _supabaseAnon: SupabaseClient | null = null;
let _supabaseService: SupabaseClient | null = null;

export function getSupabaseAnon(): SupabaseClient {
  if (!_supabaseAnon) {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_ANON_KEY;
    if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_ANON_KEY are required");
    _supabaseAnon = createClient(url, key);
  }
  return _supabaseAnon;
}

export function getSupabaseService(): SupabaseClient {
  if (!_supabaseService) {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_KEY are required");
    _supabaseService = createClient(url, key, {
      auth: { persistSession: false },
    });
  }
  return _supabaseService;
}
