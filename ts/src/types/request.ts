import { z } from "zod";

export interface UIContext {
  current_page: string;
  page_data?: Record<string, unknown>;
  form_state?: Record<string, unknown>;
  focused_field?: string;
}

export interface ChatRequest {
  chatInput: string;
  userId: string;
  active_profile_id: string;
  sessionId: string;
  intent_type?: "user_message" | "system_intent";
  ui_context?: UIContext;
}

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const ChatRequestSchema = z.object({
  chatInput: z.string().min(1, "chatInput is required"),
  userId: z.string().regex(UUID_REGEX, "userId must be a valid UUID"),
  active_profile_id: z.string().regex(UUID_REGEX, "active_profile_id must be a valid UUID"),
  sessionId: z.string().min(1, "sessionId is required"),
  intent_type: z.enum(["user_message", "system_intent"]).optional(),
  ui_context: z
    .object({
      current_page: z.string(),
      page_data: z.record(z.unknown()).optional(),
      form_state: z.record(z.unknown()).optional(),
      focused_field: z.string().optional(),
    })
    .optional(),
});
