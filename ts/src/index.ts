import "dotenv/config";
import express, { Request, Response } from "express";
import { ChatRequestSchema } from "./types/request.js";
import { serializeEvent } from "./streaming/ndjson.js";
import { isSystemIntent, handleSystemIntent } from "./services/system-intents.js";
import { runPipeline } from "./agent/pipeline.js";
import { getSupabaseAnon } from "./services/supabase.js";
import type { PipelineIntent } from "./services/system-intents.js";

const app = express();

// CORS MUST BE THE FIRST MIDDLEWARE
// Always reflect the requesting origin to prevent credential issues and env var mismatches
app.use((req, res, next) => {
  const origin = req.headers.origin || "*";
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  
  // Dynamically allow requested headers (useful for tracing headers like sentry-trace)
  if (req.headers["access-control-request-headers"]) {
    res.setHeader("Access-Control-Allow-Headers", req.headers["access-control-request-headers"]);
  } else {
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  }

  if (req.method === "OPTIONS") {
    res.sendStatus(204);
    return;
  }
  next();
});

// Increase limit to 10mb because ui_context can send large page_data or form_state
app.use(express.json({ limit: '10mb' }));

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok", version: "2.0.0", arch: "react" });
});

app.post("/chat", async (req: Request, res: Response) => {
  const parsed = ChatRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(422).json({ error: "Invalid request", details: parsed.error.flatten() });
    return;
  }

  const chatRequest = parsed.data;

  res.setHeader("Content-Type", "application/x-ndjson");
  res.setHeader("Transfer-Encoding", "chunked");
  res.setHeader("Cache-Control", "no-cache");
  res.flushHeaders();

  try {
    if (isSystemIntent(chatRequest)) {
      const supabaseAnon = getSupabaseAnon();
      const result = await handleSystemIntent(chatRequest, supabaseAnon);

      if ("trigger_message" in result) {
        const pipelineIntent = result as PipelineIntent;
        const pipelineRequest = {
          ...chatRequest,
          chatInput: pipelineIntent.trigger_message,
          intent_type: "user_message" as const,
        };
        for await (const event of runPipeline(pipelineRequest)) {
          res.write(serializeEvent(event));
        }
        res.write(
          serializeEvent({
            type: "intent_metadata",
            open_drawer: pipelineIntent.open_drawer,
            delay_ms: pipelineIntent.delay_ms,
          })
        );
      } else {
        const resObj = result as Record<string, unknown>;
        const contentText = typeof resObj.message === "string" ? resObj.message : JSON.stringify(result);
        res.write(serializeEvent({ type: "text", content: contentText }));
        if (resObj.open_drawer !== undefined) {
          res.write(serializeEvent({
            type: "intent_metadata",
            open_drawer: resObj.open_drawer,
            delay_ms: resObj.delay_ms ?? 0,
          }));
        }
      }
    } else {
      for await (const event of runPipeline(chatRequest)) {
        res.write(serializeEvent(event));
      }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Internal error";
    res.write(serializeEvent({ type: "error", message: msg }));
  } finally {
    res.end();
  }
});

const PORT = parseInt(process.env.PORT ?? "8080", 10);
app.listen(PORT, () => {
  console.log(`Cloudinha ReAct agent listening on port ${PORT}`);
});

export default app;
