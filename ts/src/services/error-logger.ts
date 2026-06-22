import type { SupabaseClient } from "@supabase/supabase-js";

export type AgentErrorType =
  | "react_loop_error"
  | "max_steps_exceeded"
  | "tool_timeout"
  | "tool_error"
  | "tool_empty_result"
  | "quota_exceeded"; // T5: Gemini 429 prepayment credits depleted


export async function logAgentError(
  supabase: SupabaseClient,
  params: {
    user_id: string;
    session_id: string;
    error_type: AgentErrorType;
    error_message: string;
    stack_trace?: string;
    metadata?: Record<string, unknown>;
  }
): Promise<void> {
  const { error } = await supabase.from("agent_errors").insert({
    user_id: params.user_id,
    session_id: params.session_id,
    error_type: params.error_type,
    error_message: params.error_message,
    stack_trace: params.stack_trace ?? null,
    metadata: params.metadata ?? {},
  });

  if (error) {
    console.error("[error-logger] Failed to log agent error:", error.message);
  }
}
