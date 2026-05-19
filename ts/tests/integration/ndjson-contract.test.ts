import { describe, it, expect } from "vitest";
import { serializeEvent } from "../../src/streaming/ndjson.js";
import type { ChatEvent } from "../../src/types/events.js";

describe("NDJSON contract", () => {
  const validEventTypes = [
    "text",
    "tool_start",
    "tool_end",
    "suggestions",
    "error",
    "intent_metadata",
    "system_message",
  ];

  it("serializes text event as valid NDJSON line", () => {
    const event: ChatEvent = { type: "text", content: "Olá! Como posso ajudar?" };
    const line = serializeEvent(event);

    expect(line.endsWith("\n")).toBe(true);
    const parsed = JSON.parse(line.trim());
    expect(parsed.type).toBe("text");
    expect(parsed.content).toBe("Olá! Como posso ajudar?");
  });

  it("serializes tool_start event", () => {
    const event: ChatEvent = {
      type: "tool_start",
      tool: "query_educational_catalog",
      args: { sql_query: "SELECT * FROM partners" },
    };
    const line = serializeEvent(event);
    const parsed = JSON.parse(line.trim());

    expect(parsed.type).toBe("tool_start");
    expect(parsed.tool).toBe("query_educational_catalog");
    expect(parsed.args).toHaveProperty("sql_query");
  });

  it("serializes tool_end event", () => {
    const event: ChatEvent = {
      type: "tool_end",
      tool: "query_educational_catalog",
      output: '{"results":[],"count":0}',
    };
    const line = serializeEvent(event);
    const parsed = JSON.parse(line.trim());

    expect(parsed.type).toBe("tool_end");
    expect(parsed.tool).toBe("query_educational_catalog");
  });

  it("serializes suggestions event with items array", () => {
    const event: ChatEvent = {
      type: "suggestions",
      items: ["Como me inscrever?", "Quais são os requisitos?", "Quando abre o ProUni?"],
    };
    const line = serializeEvent(event);
    const parsed = JSON.parse(line.trim());

    expect(parsed.type).toBe("suggestions");
    expect(parsed.items).toHaveLength(3);
  });

  it("serializes error event", () => {
    const event: ChatEvent = { type: "error", message: "Serviço indisponível" };
    const line = serializeEvent(event);
    const parsed = JSON.parse(line.trim());

    expect(parsed.type).toBe("error");
    expect(parsed.message).toBeTruthy();
  });

  it("serializes intent_metadata event", () => {
    const event: ChatEvent = {
      type: "intent_metadata",
      open_drawer: true,
      delay_ms: 500,
    };
    const line = serializeEvent(event);
    const parsed = JSON.parse(line.trim());

    expect(parsed.type).toBe("intent_metadata");
    expect(parsed.open_drawer).toBe(true);
    expect(parsed.delay_ms).toBe(500);
  });

  it("each event type produces valid JSON parseable line", () => {
    const events: ChatEvent[] = [
      { type: "text", content: "test" },
      { type: "tool_start", tool: "query_educational_catalog" },
      { type: "tool_end", tool: "query_educational_catalog" },
      { type: "suggestions", items: ["a", "b"] },
      { type: "error", message: "err" },
      { type: "intent_metadata", open_drawer: false, delay_ms: 0 },
      { type: "system_message", content: "{}" },
    ];

    for (const event of events) {
      const line = serializeEvent(event);
      expect(() => JSON.parse(line.trim())).not.toThrow();
      expect(validEventTypes).toContain(JSON.parse(line.trim()).type);
    }
  });
});
