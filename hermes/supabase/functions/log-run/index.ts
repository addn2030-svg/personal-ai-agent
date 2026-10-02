// ============================================================================
// Hermes → Supabase webhook (Step 5, Option B)
//
// Deploy:
//   supabase functions deploy log-run --project-ref <YOUR_PROJECT_REF>
//   supabase secrets set HERMES_WEBHOOK_SECRET=<random-long-string>
//
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically into
// Edge Functions — no extra secrets needed for the DB connection.
//
// API (POST, JSON, header "x-hermes-secret: <secret>"):
//   {"type":"run_start","run_label":"telegram chat"}            → {run_id}
//   {"type":"log","run_id":1,"level":"info","message":"..."}    → {ok}
//   {"type":"run_end","run_id":1,"status":"completed",
//    "total_tokens":1234,"estimated_cost":0.0021}               → {ok}
//   {"type":"config","key":"model","value":"hermes-4-405b"}     → {ok}
//
// NEVER send secrets or raw personal content in "message".
// ============================================================================

import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  // Shared-secret auth — reject anything without the header.
  const secret = Deno.env.get("HERMES_WEBHOOK_SECRET");
  if (!secret || req.headers.get("x-hermes-secret") !== secret) {
    return json({ error: "unauthorized" }, 401);
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid JSON" }, 400);
  }

  try {
    switch (body.type) {
      case "run_start": {
        const { data, error } = await supabase
          .from("agent_runs")
          .insert({ run_label: String(body.run_label ?? "unlabeled") })
          .select("id")
          .single();
        if (error) throw error;
        return json({ ok: true, run_id: data.id });
      }

      case "log": {
        const level = ["info", "warn", "error"].includes(String(body.level))
          ? String(body.level)
          : "info";
        const { error } = await supabase.from("agent_logs").insert({
          run_id: body.run_id ?? null,
          level,
          message: String(body.message ?? "").slice(0, 4000),
        });
        if (error) throw error;
        return json({ ok: true });
      }

      case "run_end": {
        const status = ["completed", "failed"].includes(String(body.status))
          ? String(body.status)
          : "completed";
        const { error } = await supabase
          .from("agent_runs")
          .update({
            status,
            completed_at: new Date().toISOString(),
            total_tokens: body.total_tokens ?? null,
            estimated_cost: body.estimated_cost ?? null,
          })
          .eq("id", body.run_id);
        if (error) throw error;
        return json({ ok: true });
      }

      case "config": {
        const { error } = await supabase.from("agent_config").upsert({
          key: String(body.key),
          value: String(body.value ?? ""),
          updated_at: new Date().toISOString(),
        });
        if (error) throw error;
        return json({ ok: true });
      }

      default:
        return json({ error: "unknown type" }, 400);
    }
  } catch (e) {
    // Never echo secrets; return a short error summary only.
    return json({ error: String((e as Error).message ?? e).slice(0, 300) }, 500);
  }
});
