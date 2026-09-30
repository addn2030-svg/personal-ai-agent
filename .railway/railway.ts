/**
 * Railway Infrastructure as Code — Abdulrahman AI OS
 * =============================================================================
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * Railway's old `railway.json` / `railway.toml` "Config as Code" is DEPRECATED:
 * new services cannot opt into it, and existing files stop being read on
 * 2026-12-01. `.railway/railway.ts` (Infrastructure as Code) is the replacement,
 * and unlike the old format it can also declare the **volume** and the
 * **variables** — which is exactly what this deployment needs.
 *
 * HOW TO USE IT
 * -------------
 *   npm install                 # installs the `railway` SDK this file imports
 *   railway login
 *   railway link                # pick the project + environment
 *   railway config plan         # SAFE: read-only, prints what would change
 *   railway config apply        # applies after you confirm the plan
 *
 * Full walkthrough: docs/railway-setup.md
 *
 * READ THE PLAN BEFORE EVERY APPLY. Omitting a resource from this file means
 * DELETING it. `railway config plan` marks destructive changes explicitly.
 *
 * SECRETS ARE NOT IN THIS FILE
 * ----------------------------
 * Values marked `preserve()` mean "keep whatever is already set in Railway".
 * Set them once with `railway variables --set` or in the dashboard; this file
 * then leaves them alone forever. Never paste a token into this file — it is
 * committed to Git.
 */

import { defineRailway, github, preserve, project, service, volume } from "railway/iac";

/** GitHub repository Railway builds from. */
const REPO = "addn2030-svg/personal-ai-agent";

/** Branch Railway deploys. Production is `main`. */
const BRANCH = "main";

/**
 * The container entrypoint MUST be invoked as a module (`python3 -m`).
 *
 * Running it as a script (`python3 connectors/telegram_webhook_runtime_memory.py`)
 * puts /app/connectors on sys.path instead of /app, so `from connectors import ...`
 * raises ModuleNotFoundError and the deploy crash-loops forever. This is guarded
 * by tests/test_production_entrypoint.py — do not "simplify" it.
 */
const START_COMMAND = "python3 -u -m connectors.telegram_webhook_runtime_memory";

export default defineRailway(() => {
  /**
   * Persistent state. Without this volume every redeploy factory-resets the
   * proactive engine: cfg overrides, standing orders, pause state, the
   * `last_full` marker, the `automation_runs` deduplication ledger and the
   * open-loops ledger all live in data/state.json, which is git-ignored
   * runtime state.
   *
   * `sizeMB` is deliberately omitted so the volume inherits the plan default
   * (Free/Trial = 0.5 GB, Hobby = 5 GB). Set `sizeMB` explicitly only after
   * upgrading to Hobby — Railway supports growing a volume, never shrinking it.
   *
   * `region` is omitted too: a volume always follows the region of the service
   * it is attached to, so pinning it here can only create a mismatch that
   * forces a downtime-causing migration.
   */
  const data = volume("ai-os-data");

  const aiOs = service("ai-os", {
    source: github(REPO, { branch: BRANCH }),

    // The repository Dockerfile is the build contract. Railway would also
    // auto-detect it, but stating it here stops a future Railpack/Nixpacks
    // auto-detection change from silently altering how the image is built.
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "Dockerfile",
    },

    deploy: {
      startCommand: START_COMMAND,

      // MUST be /health, never /ready.
      // /health returns 200 even when a provider is degraded, which is what
      // lets the container boot with variables still missing and report the
      // gap instead of crash-looping.
      // /ready returns 503 until Google Sheets credentials are valid — using
      // it as the healthcheck makes the very first deploy fail permanently.
      healthcheckPath: "/health",
      healthcheckTimeout: 300,

      // Exactly one. Railway does not allow replicas on a service with a
      // volume, and a second replica would double-send every proactive brief.
      numReplicas: 1,

      // Do NOT enable app sleeping. The webhook would wake on an inbound
      // Telegram request, but the proactive worker is a background loop:
      // a sleeping container silently skips the morning brief, the weekly
      // review and the calendar reminders. Saving credits this way buys
      // silence, not uptime.
      sleepApplication: false,

      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 10,
    },

    volumeMounts: {
      "/data": data,
    },

    env: {
      // ---- state location -------------------------------------------------
      // Mounting the volume is only half the job: without this variable the
      // process still writes state.json inside the ephemeral container layer.
      AI_OS_DATA_DIR: "/data",
      MANAGER_TIMEZONE: "Asia/Riyadh",

      // ---- model routing --------------------------------------------------
      AI_MODEL_PROVIDER: "gemini",
      AI_CLINICAL_PROVIDER: "gemini",
      GEMINI_MODEL: "google/gemini-3.7-flash",

      // ---- conversational memory -----------------------------------------
      AGENT_MEMORY_TURNS: "10",
      AGENT_CONTEXT_CHARS: "14000",

      // ---- proactive layer -------------------------------------------------
      PROACTIVE_ENABLED: "1",
      PROACTIVE_WORKER_ENABLED: "1",
      PROACTIVE_WORKER_INTERVAL_SECONDS: "900",
      PROACTIVE_WORKER_DISPATCH_SCHEDULER: "1",
      PROACTIVE_TELEGRAM_PUSH: "1",

      // ---- non-secret identifiers -----------------------------------------
      AI_OS_GITHUB_REPO: REPO,

      // ---- deliberately-off switches --------------------------------------
      // Financial autopay stays off until the payment provider and the
      // approval policy have been tested on purpose (docs/v1.1-money-threshold.md).
      MONEY_AUTOPAY_ENABLED: "0",
      // Supabase writes stay off until a secret key is configured
      // (docs/supabase-setup.md, docs/supabase-rollout.md).
      SUPABASE_WRITE_ENABLED: "0",
      SUPABASE_BACKUP_SCHEDULE_ENABLED: "0",

      // ---- secrets: values live in Railway, never here ---------------------
      // Set these once:
      //   railway variables --skip-deploys --set "TELEGRAM_BOT_TOKEN=..." ...
      // After that, preserve() keeps them and every plan shows "no change".
      TELEGRAM_BOT_TOKEN: preserve(),
      TELEGRAM_ALLOWED_CHAT_ID: preserve(),
      TELEGRAM_WEBHOOK_SECRET: preserve(),
      GEMINI_API_KEY: preserve(),
      GOOGLE_SERVICE_ACCOUNT_JSON: preserve(),
      GOOGLE_SHEET_ID: preserve(),
      GOOGLE_CALENDAR_ID: preserve(),

      // TELEGRAM_WEBHOOK_BASE_URL is intentionally NOT set.
      // connectors/telegram_webhook.py falls back to Railway's built-in
      // RAILWAY_PUBLIC_DOMAIN, which Railway injects into the container once a
      // domain exists. Generate the domain, then redeploy once so the running
      // container actually receives it. Only set this variable if you attach a
      // custom HTTPS domain.

      // ---- optional connectors --------------------------------------------
      // Uncomment a line ONLY when you have configured that provider. An unset
      // optional connector stays disabled; a preserve() on a variable you never
      // set just adds noise to every plan.
      //
      // CLINICAL_SHEET_ID: preserve(),
      // CLINICAL_SHEET_TAB: preserve(),
      // GOOGLE_DRIVE_FOLDER_ID: preserve(),
      // GOOGLE_DOCS_DOCUMENT_ID: preserve(),
      // GITHUB_TOKEN: preserve(),
      // KIMI_API_KEY: preserve(),
      // SUPABASE_URL: preserve(),
      // SUPABASE_SERVICE_ROLE_KEY: preserve(),
      // BUFFER_API_KEY: preserve(),
      // YOUTUBE_API_KEY: preserve(),
    },
  });

  return project("abdulrahman-ai-os", {
    resources: [aiOs, data],
  });
});
