#!/usr/bin/env node
/**
 * Out-of-process RuntimeMTLMonitor@1 CLI for the independent TypeScript engine.
 *
 * Never imports or dispatches to the Python reference. Speaks the portable
 * evaluate-case JSON contract used by ExternalRuntimeMTLVendorCertification@1.
 *
 * Certification controls (env, optional):
 *   RUNTIME_MTL_EXTERNAL_FORCE_STATUS
 *   RUNTIME_MTL_EXTERNAL_FORCE_VERDICT
 *   RUNTIME_MTL_EXTERNAL_DISAGREE
 *   RUNTIME_MTL_EXTERNAL_MALFORMED
 *   RUNTIME_MTL_EXTERNAL_SLEEP_SECONDS
 *   RUNTIME_MTL_EXTERNAL_AUTHORIZE_GLOBAL_PROOF
 */

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  RUNTIME_MTL_INTERFACE,
  evaluateCase,
  type MonitorEvaluationDict,
  type MonitorStatus,
  type Verdict,
} from "./index.js";

const ENV_FORCE_STATUS = "RUNTIME_MTL_EXTERNAL_FORCE_STATUS";
const ENV_FORCE_VERDICT = "RUNTIME_MTL_EXTERNAL_FORCE_VERDICT";
const ENV_DISAGREE = "RUNTIME_MTL_EXTERNAL_DISAGREE";
const ENV_MALFORMED = "RUNTIME_MTL_EXTERNAL_MALFORMED";
const ENV_SLEEP = "RUNTIME_MTL_EXTERNAL_SLEEP_SECONDS";
const ENV_AUTHORIZE_GLOBAL_PROOF = "RUNTIME_MTL_EXTERNAL_AUTHORIZE_GLOBAL_PROOF";

const TOOL_ID = "runtime-mtl-external";

function packageVersion(): string {
  try {
    const require = createRequire(import.meta.url);
    // Prefer local package.json when installed as a package tree.
    const candidates = [
      fileURLToPath(new URL("../package.json", import.meta.url)),
      fileURLToPath(new URL("../../package.json", import.meta.url)),
    ];
    for (const path of candidates) {
      try {
        const pkg = require(path) as { version?: string; name?: string };
        if (pkg.version) {
          return pkg.version;
        }
      } catch {
        // try next
      }
    }
  } catch {
    // fall through
  }
  return process.env.RUNTIME_MTL_EXTERNAL_VERSION?.trim() || "1.0.0-reviewed";
}

function versionBanner(): string {
  const version = packageVersion();
  return `${TOOL_ID} ${version} (typescript-vendor-engine; ${RUNTIME_MTL_INTERFACE})`;
}

function flipStatus(status: string): MonitorStatus {
  const table: Record<string, MonitorStatus> = {
    satisfied: "violated",
    violated: "satisfied",
    unknown: "satisfied",
    malformed: "satisfied",
  };
  return table[status] ?? "violated";
}

function flipVerdict(verdict: string): Verdict {
  const table: Record<string, Verdict> = {
    true: "false",
    false: "true",
    inconclusive: "true",
  };
  return table[verdict] ?? "false";
}

function sleepIfRequested(): void {
  const raw = process.env[ENV_SLEEP]?.trim();
  if (!raw) {
    return;
  }
  const seconds = Number(raw);
  const delay = Number.isFinite(seconds) ? Math.max(0, seconds) : 2.0;
  // Synchronous sleep for certification timeout probes (no async main).
  spawnSync("sleep", [String(delay)], { stdio: "ignore" });
}

function truthy(value: string | undefined): boolean {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}

function applyCertificationControls(
  result: MonitorEvaluationDict,
  version: string,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...result };

  const forcedStatus = process.env[ENV_FORCE_STATUS]?.trim().toLowerCase();
  if (
    forcedStatus === "satisfied" ||
    forcedStatus === "violated" ||
    forcedStatus === "unknown" ||
    forcedStatus === "malformed"
  ) {
    next.status = forcedStatus;
  }

  const forcedVerdict = process.env[ENV_FORCE_VERDICT]?.trim().toLowerCase();
  if (
    forcedVerdict === "true" ||
    forcedVerdict === "false" ||
    forcedVerdict === "inconclusive"
  ) {
    next.verdict = forcedVerdict;
  } else if (truthy(process.env[ENV_DISAGREE])) {
    next.status = flipStatus(String(next.status));
    next.verdict = flipVerdict(String(next.verdict));
    next.reason = "external_disagreement_forced";
  }

  // Certification may deliberately elevate to prove quarantine; default is false.
  next.authorizes_global_proof = truthy(process.env[ENV_AUTHORIZE_GLOBAL_PROOF]);
  next.authority = "monitor";
  next.engine_id = TOOL_ID;
  next.engine_version = version;
  next.is_hermetic_parity_engine = false;
  next.is_vendor_build = true;
  return next;
}

function main(argv: string[]): number {
  if (argv.some((arg) => arg === "--version" || arg === "-v" || arg === "version")) {
    process.stdout.write(versionBanner() + "\n");
    return 0;
  }

  sleepIfRequested();

  if (truthy(process.env[ENV_MALFORMED])) {
    process.stdout.write("%%% not-a-valid-monitor-result %%%\n");
    process.stderr.write("malformed external Runtime MTL output forced\n");
    return 0;
  }

  let args = argv.slice(2).filter((a) => !a.startsWith("-"));
  if (args[0] === "evaluate") {
    args = args.slice(1);
  }
  if (!args[0]) {
    process.stderr.write(`${TOOL_ID}: missing evaluation case path\n`);
    return 2;
  }

  const casePath = args[0];
  let payload: unknown;
  try {
    payload = JSON.parse(readFileSync(casePath, "utf8"));
  } catch (error) {
    process.stderr.write(
      `${TOOL_ID}: cannot read case ${casePath}: ${error instanceof Error ? error.message : String(error)}\n`,
    );
    return 2;
  }

  if (
    typeof payload !== "object" ||
    payload === null ||
    !("formula" in payload) ||
    !("trace" in payload)
  ) {
    process.stdout.write("%%% malformed evaluation case %%%\n");
    process.stderr.write("evaluation case missing formula/trace\n");
    return 0;
  }

  const version = packageVersion();
  try {
    const result = evaluateCase(
      payload as {
        formula: Parameters<typeof evaluateCase>[0]["formula"];
        trace: Parameters<typeof evaluateCase>[0]["trace"];
        position?: number;
        case_id?: string;
      },
    );
    const controlled = applyCertificationControls(result, version);
    // Stable key order for deterministic digests.
    const ordered: Record<string, unknown> = {};
    for (const key of Object.keys(controlled).sort()) {
      ordered[key] = controlled[key];
    }
    process.stdout.write(JSON.stringify(ordered) + "\n");
    return 0;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const err = {
      authority: "monitor",
      authorizes_global_proof: false,
      interface: RUNTIME_MTL_INTERFACE,
      late_events: false,
      logic: "ltlf",
      missing_observation: false,
      monitorability: "prefix",
      position: 0,
      reason: `external_engine_error:${message}`,
      schema_version: "runtime-mtl-result/v1",
      status: "malformed",
      trace_kind: "finite",
      verdict: "inconclusive",
      engine_id: TOOL_ID,
      engine_version: version,
      is_hermetic_parity_engine: false,
      is_vendor_build: true,
    };
    const ordered: Record<string, unknown> = {};
    for (const key of Object.keys(err).sort()) {
      ordered[key] = (err as Record<string, unknown>)[key];
    }
    process.stdout.write(JSON.stringify(ordered) + "\n");
    return 0;
  }
}

// Only auto-run when executed as the program entry (not imported).
const isMain =
  typeof process.argv[1] === "string" &&
  (import.meta.url === pathToFileURL(process.argv[1]).href ||
    process.argv[1].endsWith("/cli.js") ||
    process.argv[1].endsWith("\\cli.js") ||
    process.argv[1].includes("logic-runtime-mtl"));

if (isMain) {
  process.exitCode = main(process.argv);
}

export { main, versionBanner };
