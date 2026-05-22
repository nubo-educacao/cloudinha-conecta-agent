import "dotenv/config";
import express, { Request, Response } from "express";
import { ChatRequestSchema } from "./types/request.js";
import { serializeEvent } from "./streaming/ndjson.js";
import { isSystemIntent, handleSystemIntent } from "./services/system-intents.js";
import { runPipeline } from "./agent/pipeline.js";
import { getSupabaseAnon } from "./services/supabase.js";
import type { PipelineIntent } from "./services/system-intents.js";

const app = express();
app.use(express.json());

// CORS
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS ?? "http://localhost:3000").split(",").map(o => o.trim());
const ALLOW_ALL_ORIGINS = ALLOWED_ORIGINS.includes("*");
app.use((req, res, next) => {
  const origin = req.headers.origin ?? "";
  if (ALLOW_ALL_ORIGINS || ALLOWED_ORIGINS.includes(origin)) {
    // Always reflect the requesting origin to prevent credential issues with '*'
    res.setHeader("Access-Control-Allow-Origin", origin || "*");
  }
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
        res.write(serializeEvent({ type: "system_message", content: JSON.stringify(result) }));
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
