import pRetry from "p-retry";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { ChatRequest } from "../types/request.js";

// Renamed from PipelineIntent → SystemIntentAction to align with ReAct arch (ADR-0013)
export interface SystemIntentAction {
  trigger_message: string;
  open_drawer: boolean;
  delay_ms: number;
}

/** @deprecated Use SystemIntentAction instead */
export type PipelineIntent = SystemIntentAction;

export function isSystemIntent(request: ChatRequest): boolean {
  return request.intent_type === "system_intent";
}

/**
 * Generic DB-driven intent resolver.
 * Queries `system_intents` for the given command, matches trigger_route against
 * the current page, and substitutes all {{placeholder}} tokens from ui_context.
 * Falls back to `fallback()` if no DB row matches; returns system_ack if neither.
 */
async function resolveIntentFromDB(
  supabase: SupabaseClient,
  command: string,
  request: ChatRequest,
  fallback?: () => SystemIntentAction
): Promise<SystemIntentAction | Record<string, unknown>> {
  return pRetry(
    async () => {
      const { data: intents, error } = await supabase
        .from("system_intents")
        .select("trigger_route, trigger_message, open_drawer, delay_ms")
        .eq("command", command)
        .eq("is_active", true);

      if (error) throw error;

      if (!intents || intents.length === 0) {
        return fallback?.() ?? { type: "system_ack", message: `No ${command} intent configured.` };
      }

      const currentPage = request.ui_context?.current_page ?? "";
      const matched = intents.find((intent: { trigger_route: string | null }) => {
        if (!intent.trigger_route) return true; // null = match all pages
        try {
          return new RegExp(intent.trigger_route, "i").test(currentPage);
        } catch {
          return intent.trigger_route === currentPage;
        }
      });

      if (!matched) {
        return fallback?.() ?? { type: "system_ack", message: `No ${command} intent matched for page: ${currentPage}` };
      }

      // Substitute all {{key}} placeholders from page_data, form_state, and focused_field
      let triggerMessage = matched.trigger_message as string;
      const pageData = request.ui_context?.page_data ?? {};
      const formState = request.ui_context?.form_state ?? {};
      const allPlaceholders: Record<string, unknown> = {
        ...pageData,
        ...formState,
        focused_field: request.ui_context?.focused_field,
      };

      for (const [key, value] of Object.entries(allPlaceholders)) {
        if (value != null) {
          triggerMessage = triggerMessage.replace(
            new RegExp(`\\{\\{${key}\\}\\}`, "g"),
            String(value)
          );
        }
      }

      return {
        trigger_message: triggerMessage,
        open_drawer: matched.open_drawer ?? false,
        delay_ms: matched.delay_ms ?? 0,
      } as SystemIntentAction;
    },
    { retries: 3, factor: 2, minTimeout: 1000, maxTimeout: 4000 }
  );
}

export async function handleSystemIntent(
  request: ChatRequest,
  supabase: SupabaseClient
): Promise<Record<string, unknown> | SystemIntentAction> {
  const command = request.chatInput.trim().toLowerCase();

  if (command === "ping") {
    return { type: "pong", status: "ok" };
  }

  if (command === "clear_session") {
    return { type: "session_cleared", sessionId: request.sessionId };
  }

  if (command === "get_starters") {
    return fetchStarters(supabase, request.ui_context?.current_page);
  }

  if (command === "page_context") {
    return resolveIntentFromDB(supabase, "page_context", request);
  }

  if (command === "step_change") {
    return resolveIntentFromDB(supabase, "step_change", request, () =>
      buildStepChangeFallback(request)
    );
  }

  if (command === "validation_error") {
    return resolveIntentFromDB(supabase, "validation_error", request, () =>
      buildValidationErrorFallback(request)
    );
  }

  if (command === "welcome_back") {
    return resolveIntentFromDB(supabase, "welcome_back", request, buildWelcomeBackFallback);
  }

  return { type: "system_ack", message: `Unknown intent: ${command}` };
}

async function fetchStarters(
  supabase: SupabaseClient,
  currentPage?: string
): Promise<Record<string, unknown>> {
  return pRetry(
    async () => {
      const query = supabase
        .from("cloudinha_starters")
        .select("starters, intro_message")
        .eq("is_active", true);

      if (currentPage) {
        query.eq("page_route", currentPage);
      } else {
        query.eq("page_route", "/"); // Fallback global
      }

      // Ordenar por route_priority (maior prioridade vence)
      const { data, error } = await query.order("route_priority", { ascending: false }).limit(1);
      if (error) throw error;
      
      const row = data?.[0];
      return { 
        type: "starters", 
        intro_message: row?.intro_message ?? "Como posso te ajudar hoje?",
        items: row?.starters ?? [] 
      };
    },
    { retries: 3, factor: 2, minTimeout: 1000, maxTimeout: 4000 }
  );
}

// --- Hardcoded fallbacks (used when no DB row matches) ---

function buildStepChangeFallback(request: ChatRequest): SystemIntentAction {
  const formState = request.ui_context?.form_state ?? {};
  const currentStep = formState.current_step ?? "desconhecido";
  const stepName = formState.step_name ?? "";

  return {
    trigger_message: `O usuário avançou para o passo ${currentStep}${stepName ? ` (${stepName})` : ""} do formulário. Contexto do formulário: ${JSON.stringify(formState)}`,
    open_drawer: false,
    delay_ms: 500,
  };
}

function buildValidationErrorFallback(request: ChatRequest): SystemIntentAction {
  const formState = request.ui_context?.form_state ?? {};
  const focusedField = request.ui_context?.focused_field ?? "";
  const errorMessage = formState.error_message ?? formState.validation_error ?? "erro de validação";

  return {
    trigger_message: `O usuário encontrou um erro de validação no campo "${focusedField}": ${errorMessage}. Ajude-o a corrigir.`,
    open_drawer: true,
    delay_ms: 0,
  };
}

function buildWelcomeBackFallback(): SystemIntentAction {
  return {
    trigger_message:
      "O usuário acabou de entrar na plataforma. Dê uma saudação calorosa e proativa mencionando eventos importantes do calendário educacional de hoje.",
    open_drawer: false,
    delay_ms: 1500,
  };
}
