import { createReactAgent } from "@langchain/langgraph/prebuilt";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { SystemMessage } from "@langchain/core/messages";
import type { BaseMessage } from "@langchain/core/messages";
import type { DynamicStructuredTool } from "@langchain/core/tools";

export interface AgentConfig {
  model: string;
  maxSteps: number;
  temperature?: number;
}

export function createCloudinhaAgent(
  tools: DynamicStructuredTool[],
  systemPrompt: string,
  config: AgentConfig
// eslint-disable-next-line @typescript-eslint/no-explicit-any
): any {
  // thinkingConfig: { thinkingBudget: 0 } disables Gemini 2.5 thinking mode.
  // Without this, tool calls come back as content[].functionCall with thoughtSignature
  // instead of tool_calls[], which LangGraph's toolsCondition cannot detect.
  const llm = new ChatGoogleGenerativeAI({
    model: config.model ?? "gemini-2.5-flash",
    temperature: config.temperature ?? 0.7,
    maxOutputTokens: 4096,
    thinkingConfig: { thinkingBudget: 0 },
  });

  const messageModifier = (messages: BaseMessage[]): BaseMessage[] => {
    const hasToolResults = messages.some((m) => m._getType() === "tool");
    const sysContent = hasToolResults
      ? systemPrompt +
        "\n\n[SYSTEM INSTRUCTION]: Do NOT write your internal reasoning, monologue, or summary of what you just did. Start your response DIRECTLY with the answer to the user in Portuguese. Do not begin with phrases like 'I have successfully', 'I found', 'Based on my research', or any English text."
      : systemPrompt +
        "\n\n[SYSTEM INSTRUCTION — MANDATORY]: You MUST invoke one of the provided functions right now using the function calling interface. Do NOT write Python code, do NOT write prose. Select the appropriate function from the tools list and call it immediately.";
    return [
      new SystemMessage(sysContent),
      ...messages.filter((m) => m._getType() !== "system"),
    ];
  };

  return createReactAgent({
    llm,
    tools,
    messageModifier,
  });
}
