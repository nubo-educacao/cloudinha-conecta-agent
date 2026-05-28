import type { SupabaseClient } from "@supabase/supabase-js";

export interface ChatMessage {
  sender: string;
  content: string;
}

export class SessionService {
  private supabase: SupabaseClient;
  private userId: string;
  private sessionId: string;

  constructor(supabase: SupabaseClient, userId: string, sessionId: string) {
    this.supabase = supabase;
    this.userId = userId;
    this.sessionId = sessionId;
  }

  async persistUserMessage(content: string): Promise<void> {
    const { error } = await this.supabase.from("chat_messages").insert({
      user_id: this.userId,
      session_id: this.sessionId,
      sender: "user",
      content,
    });
    if (error) console.error("[session] Failed to persist user message:", error.message);
  }

  async persistAgentMessage(content: string): Promise<void> {
    const { error } = await this.supabase.from("chat_messages").insert({
      user_id: this.userId,
      session_id: this.sessionId,
      sender: "cloudinha",
      content,
    });
    if (error) console.error("[session] Failed to persist agent message:", error.message);
  }

  async persistSystemMessage(content: string): Promise<void> {
    const { error } = await this.supabase.from("chat_messages").insert({
      user_id: this.userId,
      session_id: this.sessionId,
      sender: "system",
      content,
    });
    if (error) console.error("[session] Failed to persist system message:", error.message);
  }

  async getRecentMessages(limit = 5): Promise<ChatMessage[]> {
    const { data, error } = await this.supabase
      .from("chat_messages")
      .select("sender, content")
      .eq("session_id", this.sessionId)
      .order("created_at", { ascending: true }) // ascending=true — port from Python desc=False
      .limit(limit);

    if (error) {
      console.error("[session] Failed to get recent messages:", error.message);
      return [];
    }

    return (data ?? []) as ChatMessage[];
  }
}
