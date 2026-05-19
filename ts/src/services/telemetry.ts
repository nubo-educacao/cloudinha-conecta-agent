import type { SupabaseClient } from "@supabase/supabase-js";

export interface ReActStep {
  thought?: string;
  action?: { tool: string; args: Record<string, unknown> };
  observation?: string;
}

export interface TurnTelemetry {
  user_id: string;
  session_id: string;
  total_latency_ms: number;
  model_latency_ms: number;
  tools_latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  tools_used: { name: string; args: Record<string, unknown> }[];
  intent_category: string;
  steps: ReActStep[];
  agent_output: string;
  estimated_cost_usd: number;
}

// Gemini 2.5 Flash pricing (verify at https://ai.google.dev/pricing)
const COST_PER_INPUT_TOKEN = 0.15 / 1_000_000;
const COST_PER_OUTPUT_TOKEN = 0.60 / 1_000_000;

export function estimateCost(inputTokens: number, outputTokens: number): number {
  return inputTokens * COST_PER_INPUT_TOKEN + outputTokens * COST_PER_OUTPUT_TOKEN;
}

export async function logAgentTurn(
  supabase: SupabaseClient,
  telemetry: TurnTelemetry
): Promise<void> {
  const { error } = await supabase.from("agent_turns").insert({
    user_id: telemetry.user_id,
    session_id: telemetry.session_id,
    total_latency_ms: telemetry.total_latency_ms,
    model_latency_ms: telemetry.model_latency_ms,
    tools_latency_ms: telemetry.tools_latency_ms,
    input_tokens: telemetry.input_tokens,
    output_tokens: telemetry.output_tokens,
    tools_used: telemetry.tools_used,
    intent_category: telemetry.intent_category,
    steps: telemetry.steps,
    agent_output: telemetry.agent_output,
    estimated_cost_usd: telemetry.estimated_cost_usd,
  });

  if (error) {
    console.error("[telemetry] Failed to log agent turn:", error.message);
  }
}
