/**
 * Guards .railway/railway.ts against the mistakes that actually break this deploy.
 *
 *   npm run railway:check
 *
 * Runs fully offline: it does not contact Railway and needs no login, so it can
 * run in CI and before every `railway config apply`.
 *
 * Each assertion corresponds to a failure mode that has either happened in
 * production or is documented in docs/railway-setup.md. This is the same idea
 * as tests/test_production_entrypoint.py, applied to the infrastructure file.
 */

import { createRailwayContext, project as projectFn } from "railway/iac";
import type { ProjectDefinition, ServiceNode, VolumeNode } from "railway/iac";

import program from "../.railway/railway.ts";

const failures: string[] = [];
const checks: string[] = [];

function check(label: string, condition: boolean, detail: string): void {
  if (condition) {
    checks.push(label);
  } else {
    failures.push(`${label}\n       ${detail}`);
  }
}

const ctx = createRailwayContext({
  command: "plan",
  environment: "production",
  environmentName: "production",
  projectName: "abdulrahman-ai-os",
});

const definition = (await program(ctx, projectFn)) as ProjectDefinition;
const resources = (definition.resources ?? []).flat() as Array<ServiceNode | VolumeNode>;

const services = resources.filter((r): r is ServiceNode => r.type === "service");
const volumes = resources.filter((r): r is VolumeNode => r.type === "volume");

check(
  "exactly one service is declared",
  services.length === 1,
  `found ${services.length}. A second always-on service doubles the bill and can double-send proactive briefs.`,
);

const svc = services[0];
if (!svc) {
  console.error("FATAL: no service declared in .railway/railway.ts");
  process.exit(1);
}

const deploy = svc.deploy ?? {};
const env = (svc.variables ?? {}) as Record<string, { type?: string; value?: string } | undefined>;

/** The SDK normalises env values to {type:"literal",value} or {type:"preserve"}. */
function literal(name: string): string | undefined {
  const entry = env[name];
  return entry && entry.type === "literal" ? entry.value : undefined;
}

// --- entrypoint --------------------------------------------------------------
// `python3 connectors/telegram_webhook_runtime_memory.py` puts /app/connectors on
// sys.path instead of /app, so `from connectors import ...` raises
// ModuleNotFoundError and the deploy crash-loops.
check(
  "start command uses the module form (python3 -m)",
  typeof deploy.startCommand === "string"
    && / -m connectors\.telegram_webhook_runtime_memory\b/.test(deploy.startCommand),
  `got ${JSON.stringify(deploy.startCommand)}. The script form crash-loops with "ModuleNotFoundError: No module named 'connectors'".`,
);

// --- healthcheck -------------------------------------------------------------
// /ready returns 503 until Google Sheets credentials are valid. Using it as the
// healthcheck makes the first deploy fail forever, before you can add variables.
check(
  "healthcheck is /health, not /ready",
  deploy.healthcheckPath === "/health",
  `got ${JSON.stringify(deploy.healthcheckPath)}. /ready returns 503 until Sheets is configured and would fail every first deploy.`,
);

// --- replicas ----------------------------------------------------------------
// Railway forbids replicas on a service with a volume, and a second replica
// would run a second proactive worker against the same state.
check(
  "exactly one replica",
  deploy.numReplicas === 1,
  `got ${JSON.stringify(deploy.numReplicas)}. Volumes cannot be used with replicas, and >1 double-sends every brief.`,
);

// --- app sleeping ------------------------------------------------------------
// A sleeping container wakes for an inbound Telegram webhook but not for the
// background proactive loop, so the morning brief silently stops.
check(
  "app sleeping is explicitly disabled",
  deploy.sleepApplication === false,
  `got ${JSON.stringify(deploy.sleepApplication)}. Sleeping silently kills the proactive worker's scheduled pushes.`,
);

// --- persistence -------------------------------------------------------------
const attachments = Object.values(svc.volumeAttachments ?? {});
const mountPaths = attachments.map((a) => a.mountPath);
check(
  "a volume is mounted at /data",
  mountPaths.includes("/data"),
  `mount paths: ${JSON.stringify(mountPaths)}. Without it every redeploy wipes data/state.json.`,
);
check(
  "the mounted volume is declared as a project resource",
  volumes.length === 1 && attachments.every((a) => volumes.some((v) => v.address === a.volume)),
  `found ${volumes.length} volume resources for ${attachments.length} attachment(s). A volume missing from project() resources is a deletion on the next apply.`,
);
check(
  "AI_OS_DATA_DIR points at the mount path",
  literal("AI_OS_DATA_DIR") === "/data",
  `got ${JSON.stringify(env.AI_OS_DATA_DIR)}. Mounting the volume without this variable still writes state to the ephemeral layer.`,
);

// --- build -------------------------------------------------------------------
const build = typeof svc.build === "object" && svc.build !== null ? svc.build : {};
check(
  "the repository Dockerfile is the build contract",
  build.builder === "DOCKERFILE",
  `got ${JSON.stringify(build.builder)}. Auto-detection can change under you; the Dockerfile pins the Python runtime.`,
);

// --- secret hygiene ----------------------------------------------------------
// This file is committed to Git. A literal secret here is a leak, not a config.
const SECRET_NAMES = [
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_WEBHOOK_SECRET",
  "GEMINI_API_KEY",
  "GOOGLE_SERVICE_ACCOUNT_JSON",
  "GITHUB_TOKEN",
  "KIMI_API_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "BUFFER_API_KEY",
  "PAYMENT_GATEWAY_WEBHOOK_SECRET",
];
for (const name of SECRET_NAMES) {
  if (!(name in env)) continue;
  check(
    `${name} carries no literal value`,
    env[name]?.type === "preserve",
    `it resolves to ${JSON.stringify(env[name])} in a committed file. Use preserve() and set the real value with \`railway variables --set\`.`,
  );
}

// --- deliberately-off switches ----------------------------------------------
check(
  "financial autopay is off by default",
  literal("MONEY_AUTOPAY_ENABLED") === "0",
  `got ${JSON.stringify(env.MONEY_AUTOPAY_ENABLED)}. Autopay must be enabled deliberately, never by a deploy default.`,
);

// --- source ------------------------------------------------------------------
check(
  "the GitHub source names this repository",
  svc.source?.repo === "addn2030-svg/personal-ai-agent",
  `got ${JSON.stringify(svc.source?.repo)}.`,
);

// --- report ------------------------------------------------------------------
for (const label of checks) console.log(`  ok   ${label}`);
if (failures.length > 0) {
  console.error(`\n${failures.length} check(s) FAILED:\n`);
  for (const f of failures) console.error(`  FAIL ${f}\n`);
  process.exit(1);
}
console.log(`\n${checks.length} checks passed — .railway/railway.ts is safe to plan.`);
