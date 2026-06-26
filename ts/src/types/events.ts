export interface TextEvent {
  type: "text";
  content: string;
}

export interface ToolStartEvent {
  type: "tool_start";
  tool: string;
  args?: Record<string, unknown>;
}

export interface ToolEndEvent {
  type: "tool_end";
  tool: string;
  output?: string;
}

export interface SuggestionsEvent {
  type: "suggestions";
  items: string[];
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export interface IntentMetadataEvent {
  type: "intent_metadata";
  open_drawer: boolean;
  pulsate?: boolean;
  delay_ms: number;
}

export interface SystemMessageEvent {
  type: "system_message";
  content: string;
}

export type ChatEvent =
  | TextEvent
  | ToolStartEvent
  | ToolEndEvent
  | SuggestionsEvent
  | ErrorEvent
  | IntentMetadataEvent
  | SystemMessageEvent;
