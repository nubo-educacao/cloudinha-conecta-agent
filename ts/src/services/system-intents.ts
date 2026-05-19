import pRetry from "p-retry";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { ChatRequest } from "../types/request.js";

export interface PipelineIntent {
  trigger_message: string;
  open_drawer: boolean;
  delay_ms: number;
}

const LIGHTWEIGHT_COMMANDS = new Set(["get_starters", "clear_session", "ping"]);

export function isSystemIntent(request: ChatRequest): boolean {
  return request.intent_type === "system_intent";
}

export async function handleSystemIntent(
  request: ChatRequest,
  supabase: SupabaseClient
): Promise<Record<string, unknown> | PipelineIntent> {
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
    return resolvePageContext(supabase, request);
  }

  if (command === "step_change") {
    return buildStepChangeIntent(request);
  }

  if (command === "validation_error") {
    return buildValidationErrorIntent(request);
  }

  if (command === "welcome_back") {
    return buildWelcomeBackIntent();
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
        .select("text, icon")
        .eq("is_active", true);

      if (currentPage) {
        query.eq("page_route", currentPage);
      }

      const { data, error } = await query.order("sort_order");
      if (error) throw error;
      return { type: "starters", items: data ?? [] };
    },
    { retries: 3, factor: 2, minTimeout: 1000, maxTimeout: 4000 }
  );
}

async function resolvePageContext(
  supabase: SupabaseClient,
  request: ChatRequest
): Promise<PipelineIntent | Record<string, unknown>> {
  return pRetry(
    async () => {
      const { data: intents, error } = await supabase
        .from("system_intents")
        .select("trigger_route, trigger_message, open_drawer, delay_ms")
        .eq("command", "page_context")
        .eq("is_active", true);

      if (error) throw error;
      if (!intents || intents.length === 0) {
        return { type: "system_ack", message: "No page_context intent configured." };
      }

      const currentPage = request.ui_context?.current_page ?? "";
      const matched = intents.find((intent: { trigger_route: string }) => {
        try {
          return new RegExp(intent.trigger_route, "i").test(currentPage);
        } catch {
          return intent.trigger_route === currentPage;
        }
      });

      if (!matched) {
        return { type: "system_ack", message: "No intent matched for current page." };
      }

      let triggerMessage = matched.trigger_message as string;

      // Resolve placeholders {{title}}, {{institution}}
      const pageData = request.ui_context?.page_data ?? {};
      const title = pageData.title ?? pageData.name;
      const institution = pageData.institution ?? pageData.partner_name;

      if (title) triggerMessage = triggerMessage.replace(/\{\{title\}\}/g, String(title));
      if (institution)
        triggerMessage = triggerMessage.replace(/\{\{institution\}\}/g, String(institution));

      // If placeholders remain, try DB resolution
      if (triggerMessage.includes("{{") && pageData.opportunity_id) {
        const resolved = await resolveOpportunityPlaceholders(
          supabase,
          triggerMessage,
          String(pageData.opportunity_id)
        );
        triggerMessage = resolved;
      }

      return {
        trigger_message: triggerMessage,
        open_drawer: matched.open_drawer ?? false,
        delay_ms: matched.delay_ms ?? 0,
      } as PipelineIntent;
    },
    { retries: 3, factor: 2, minTimeout: 1000, maxTimeout: 4000 }
  );
}

async function resolveOpportunityPlaceholders(
  supabase: SupabaseClient,
  message: string,
  opportunityId: string
): Promise<string> {
  const { data } = await supabase
    .from("v_unified_opportunities")
    .select("title, institution")
    .eq("id", opportunityId)
    .limit(1);

  if (!data || data.length === 0) {
    // Fallback to partner_opportunities
    const { data: partnerData } = await supabase
      .from("partner_opportunities")
      .select("title, partner_name")
      .eq("id", opportunityId)
      .limit(1);

    if (partnerData?.[0]) {
      return message
        .replace(/\{\{title\}\}/g, partnerData[0].title ?? "")
        .replace(/\{\{institution\}\}/g, partnerData[0].partner_name ?? "");
    }
    return message;
  }

  return message
    .replace(/\{\{title\}\}/g, data[0].title ?? "")
    .replace(/\{\{institution\}\}/g, data[0].institution ?? "");
}

function buildStepChangeIntent(request: ChatRequest): PipelineIntent {
  const formState = request.ui_context?.form_state ?? {};
  const currentStep = formState.current_step ?? "desconhecido";
  const stepName = formState.step_name ?? "";

  return {
    trigger_message: `O usuário avançou para o passo ${currentStep}${stepName ? ` (${stepName})` : ""} do formulário. Contexto do formulário: ${JSON.stringify(formState)}`,
    open_drawer: false,
    delay_ms: 500,
  };
}

function buildValidationErrorIntent(request: ChatRequest): PipelineIntent {
  const formState = request.ui_context?.form_state ?? {};
  const focusedField = request.ui_context?.focused_field ?? "";
  const errorMessage = formState.error_message ?? formState.validation_error ?? "erro de validação";

  return {
    trigger_message: `O usuário encontrou um erro de validação no campo "${focusedField}": ${errorMessage}. Ajude-o a corrigir.`,
    open_drawer: true,
    delay_ms: 0,
  };
}

function buildWelcomeBackIntent(): PipelineIntent {
  return {
    trigger_message:
      "O usuário acabou de entrar na plataforma. Dê uma saudação calorosa e proativa mencionando eventos importantes do calendário educacional de hoje.",
    open_drawer: false,
    delay_ms: 1500,
  };
}
