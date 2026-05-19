import type { ChatEvent } from "../types/events.js";

export function serializeEvent(event: ChatEvent): string {
  return JSON.stringify(event) + "\n";
}
