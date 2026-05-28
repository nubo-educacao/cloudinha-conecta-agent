import { HumanMessage, AIMessage, type BaseMessage } from "@langchain/core/messages";
import type { ChatRequest } from "../types/request.js";
import type { ChatEvent } from "../types/events.js";
import { getSupabaseAnon, getSupabaseService } from "../services/supabase.js";
import {
  getAgentPrompt,
  getSchemaContext,
  getFewShotExamples,
  buildSystemPrompt,
  buildLeanContext,
} from "./prompts.js";
import { createCloudinhaAgent } from "./react-agent.js";
import { createTools } from "../tools/index.js";
import { SessionService } from "../services/session.js";
import { logAgentTurn, estimateCost, type ReActStep } from "../services/telemetry.js";
import { logAgentError } from "../services/error-logger.js";

const MAX_RETRIES = 3;

// Fallback messages (pt-BR) — port from engine.py
const MSG_REACT_FAIL =
  "Desculpe, não consegui processar sua pergunta. Pode reformular?";
const MSG_TIMEOUT =
  "Estou com dificuldades de conexão ou limite de uso excedido. Tente novamente em alguns minutos.";
const MSG_MAX_STEPS =
  "Desculpe, precisei de mais passos do que o esperado. Pode simplificar sua pergunta?";
const MSG_FINAL_FALLBACK = "Desculpe, não consegui processar.";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Parse the structured <!--SUGESTÕES--> block that the agent is instructed to append.
// Returns { suggestions, cleanText } — cleanText has the block stripped out.
function parseSuggestions(text: string): { suggestions: string[]; cleanText: string } {
  const blockMatch = text.match(/<!--SUGESTÕES-->([\s\S]*?)<!--\/SUGESTÕES-->/);
  if (!blockMatch) return { suggestions: [], cleanText: text };

  const block = blockMatch[1];
  const suggestions = (block.match(/^[-•]\s+(.+)$/gm) ?? [])
    .map((s) => s.replace(/^[-•]\s+/, "").trim())
    .filter((s) => s.length > 0)
    .slice(0, 3);

  // Remove the entire block (plus any trailing whitespace/newlines) from the text
  const cleanText = text.replace(/\s*<!--SUGESTÕES-->[\s\S]*?<!--\/SUGESTÕES-->\s*$/, "").trimEnd();

  return { suggestions, cleanText };
}

async function loadProfile(
  supabaseService: ReturnType<typeof getSupabaseService>,
  userId: string,
  activeProfileId: string
): Promise<{ full_name: string; age?: number; cognitive_memory?: string }> {
  const { data: profileData } = await supabaseService
    .from("user_profiles")
    .select("full_name, birth_date")
    .eq("id", userId)
    .limit(1);

  const profile = profileData?.[0];
  let age: number | undefined;
  if (profile?.birth_date) {
    const birth = new Date(profile.birth_date);
    const now = new Date();
    age = Math.floor((now.getTime() - birth.getTime()) / (365.25 * 24 * 60 * 60 * 1000));
  }

  const { data: metaData } = await supabaseService
    .from("users_metadata")
    .select("cognitive_memory")
    .eq("profile_id", activeProfileId)
    .limit(1);

  return {
    full_name: profile?.full_name ?? "Estudante",
    age,
    cognitive_memory: metaData?.[0]?.cognitive_memory ?? undefined,
  };
}

export async function* runPipeline(request: ChatRequest): AsyncGenerator<ChatEvent> {
  const supabaseAnon = getSupabaseAnon();
  const supabaseService = getSupabaseService();

  // Normalize sessionId (strip "session-" prefix if present)
  const cleanSessionId = request.sessionId.startsWith("session-")
    ? request.sessionId.slice(8)
    : request.sessionId;

  const session = new SessionService(supabaseService, request.userId, cleanSessionId);

  const totalStart = Date.now();
  console.log(`[pipeline] request received userId=${request.userId} session=${cleanSessionId}`);

  let attempt = 0;
  let lastError: Error | null = null;

  while (attempt < MAX_RETRIES) {
    try {
      // 1. Load profile
      const { full_name, age, cognitive_memory } = await loadProfile(
        supabaseService,
        request.userId,
        request.active_profile_id
      );

      // 2. Load recent session history
      const recentMessages = await session.getRecentMessages(5);

      // 3. Load agent prompt from DB
      const promptRow = await getAgentPrompt(supabaseAnon);
      if (!promptRow) {
        yield { type: "error", message: "Agent configuration not found." };
        return;
      }

      // 4. Build schema context + few-shot examples + system prompt
      const [schemaContext, fewShotBlock] = await Promise.all([
        getSchemaContext(supabaseAnon),
        getFewShotExamples(supabaseAnon),
      ]);
      const systemPrompt = buildSystemPrompt(schemaContext, promptRow, fewShotBlock);

      // 5. Build lean context (no recent_messages — injected as real LangGraph messages below)
      const leanContext = buildLeanContext({
        user_id: request.userId,
        active_profile_id: request.active_profile_id,
        full_name,
        age,
        cognitive_memory,
        recent_messages: [],
        ui_context: request.ui_context,
      });

      // 6. Persist user message (system intents salvos com sender="system")
      if (request.intent_type === "system_intent") {
        await session.persistSystemMessage(request.chatInput);
      } else {
        await session.persistUserMessage(request.chatInput);
      }

      // 7. Create agent
      const tools = createTools(supabaseService);
      const agent = createCloudinhaAgent(tools, systemPrompt, {
        model: promptRow.model ?? "gemini-2.5-flash",
        maxSteps: promptRow.max_steps ?? 5,
        temperature: promptRow.temperature ?? 0.7,
      });

      // 8. Stream agent execution
      const steps: ReActStep[] = [];
      const toolsUsed: { name: string; args: Record<string, unknown> }[] = [];
      let fullOutput = "";
      let inputTokens = 0;
      let outputTokens = 0;
      let modelLatencyMs = 0;
      let toolsLatencyMs = 0;

      console.log(`[pipeline] streaming started (attempt ${attempt + 1})`);
      const modelStart = Date.now();

      // Build real LangGraph message history so the model has genuine conversational context.
      // First message: user profile context (always HumanMessage so the graph starts correctly).
      // Then: alternating HumanMessage/AIMessage from session history.
      // Last: the current user input.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const historyMessages: any[] = recentMessages.map((m) =>
        m.sender === "user" ? new HumanMessage(m.content) : new AIMessage(m.content)
      );

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const messages: any[] = [
        new HumanMessage(leanContext),
        ...historyMessages,
        new HumanMessage(request.chatInput),
      ];

      const stream = agent.streamEvents(
        { messages },
        {
          version: "v2",
          configurable: { recursion_limit: (promptRow.max_steps ?? 5) + 1 },
        }
      );

      let currentStep: ReActStep = {};
      // Buffer text per model turn; only emit if the turn has no tool calls
      // (suppresses intermediate "I'll look that up" preamble before tool calls).
      let turnTextBuffer = "";

      for await (const event of stream) {
        const { event: eventName, data } = event;
        if (eventName === "on_chat_model_start") {
          modelLatencyMs = Date.now();
          turnTextBuffer = "";
        }

        if (eventName === "on_chat_model_stream") {
          const chunk = data?.chunk;
          if (chunk?.content) {
            const text =
              typeof chunk.content === "string"
                ? chunk.content
                : chunk.content
                    .filter((c: { type: string; text?: string }) => c.type === "text")
                    .map((c: { type: string; text?: string }) => c.text ?? "")
                    .join("");
            if (text) {
              turnTextBuffer += text;
            }
          }
        }

        if (eventName === "on_chat_model_end") {
          modelLatencyMs = Date.now() - modelLatencyMs;
          const toolCalls = data?.output?.tool_calls ?? [];
          const usage = data?.output?.usage_metadata;
          if (usage) {
            inputTokens += usage.input_tokens ?? 0;
            outputTokens += usage.output_tokens ?? 0;
          }
          // Only stream text from turns with no tool calls (final answer turns).
          if (toolCalls.length === 0 && turnTextBuffer) {
            // Gemini sometimes emits "thought\n<reasoning>\n\n" before the actual response.
            // Strip it: everything from "thought\n" up to the first line that starts with
            // a Portuguese character or Markdown (capital letter, *, #, -, etc.).
            const stripped = turnTextBuffer.replace(
              /^thought\n[\s\S]*?\n\n(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ*#\-])/,
              ""
            );
            // Strip the suggestions block before showing text to the user;
            // parseSuggestions will re-process fullOutput at step 9.
            const { cleanText } = parseSuggestions(stripped);
            fullOutput += turnTextBuffer; // keep raw for suggestions parsing at step 9
            yield { type: "text", content: cleanText };
          }
          turnTextBuffer = "";
        }

        if (eventName === "on_tool_start") {
          const toolName = event.name as string;
          console.log(`[pipeline] tool_start: ${toolName}`);
          const toolInput = data?.input ?? {};
          currentStep = { action: { tool: toolName, args: toolInput as Record<string, unknown> } };
          toolsUsed.push({ name: toolName, args: toolInput as Record<string, unknown> });
          yield { type: "tool_start", tool: toolName, args: toolInput as Record<string, unknown> };
          toolsLatencyMs -= Date.now();
        }

        if (eventName === "on_tool_end") {
          toolsLatencyMs += Date.now();
          console.log(`[pipeline] tool_end: ${event.name}`);
          const toolName = event.name as string;
          const output =
            typeof data?.output === "string" ? data.output : JSON.stringify(data?.output);
          currentStep.observation = output;
          steps.push(currentStep);
          currentStep = {};
          yield { type: "tool_end", tool: toolName, output };
        }
      }

      modelLatencyMs = Date.now() - modelStart - Math.abs(toolsLatencyMs);
      console.log(`[pipeline] stream done — output=${fullOutput.length} chars, steps=${steps.length}`);

      // 9. Extract structured suggestions block and strip it from display text
      const { suggestions, cleanText } = parseSuggestions(fullOutput);
      if (suggestions.length > 0) {
        yield { type: "suggestions", items: suggestions };
      }

      // 10. Persist agent response (without the suggestions block)
      await session.persistAgentMessage(cleanText);

      // 11. Log telemetry
      const totalLatencyMs = Date.now() - totalStart;
      await logAgentTurn(supabaseService, {
        user_id: request.userId,
        session_id: cleanSessionId,
        total_latency_ms: totalLatencyMs,
        model_latency_ms: Math.max(0, modelLatencyMs),
        tools_latency_ms: Math.max(0, toolsLatencyMs),
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        tools_used: toolsUsed,
        intent_category: request.intent_type ?? "user_message",
        steps,
        agent_output: fullOutput,
        estimated_cost_usd: estimateCost(inputTokens, outputTokens),
      });

      return;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      console.error(`[pipeline] attempt ${attempt + 1} failed:`, lastError.message, lastError.stack?.split("\n")[1] ?? "");
      attempt++;

      const isMaxSteps =
        lastError.message.includes("Recursion limit") ||
        lastError.message.includes("recursion_limit");
      const isTimeout =
        lastError.message.includes("timeout") || lastError.message.includes("ETIMEDOUT");

      // Log error
      await logAgentError(supabaseService, {
        user_id: request.userId,
        session_id: request.sessionId,
        error_type: isMaxSteps
          ? "max_steps_exceeded"
          : isTimeout
          ? "tool_timeout"
          : "react_loop_error",
        error_message: lastError.message,
        stack_trace: lastError.stack,
        metadata: { attempt, chatInput: request.chatInput },
      });

      if (isMaxSteps) {
        yield { type: "text", content: MSG_MAX_STEPS };
        return;
      }

      if (isTimeout) {
        yield { type: "text", content: MSG_TIMEOUT };
        return;
      }

      if (attempt < MAX_RETRIES) {
        await sleep(Math.pow(2, attempt) * 1000);
        continue;
      }
    }
  }

  // All retries exhausted
  yield { type: "text", content: lastError ? MSG_REACT_FAIL : MSG_FINAL_FALLBACK };
}
