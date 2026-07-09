# TypeScript Solver Dependency Remediation Runbook

Status: active
Task: `PORTAL-CXTP-089`
Depends on: `PORTAL-CXTP-058`, `PORTAL-CXTP-088`
Date: 2026-07-08

## Purpose

`PORTAL-CXTP-058` probes the crypto_exchange theorem-prover environment and
found this host **blocked** for a required TypeScript compiler (`tsc`)
dependency: the security IR workflow emits TypeScript proof-consumer schemas
(`scripts/ops/security_verification/emit_security_typescript_schema.py`) that
must type-check before those schemas can be trusted by downstream clients, and
no `tsc` was available on `PATH`.

This runbook and its companion script,
`scripts/ops/security_verification/provision_required_typescript_toolchain.py`,
remediate that blocker with a **reproducible, repo-scoped** TypeScript
compiler install instead of relying on an ambient, machine-wide `npm install
-g typescript`. The remediation:

1. Checks whether `tsc` is already resolvable (via an explicit `TSC_EXE`
   override, the repo-scoped toolchain directory, or `PATH`).
2. If not, provisions TypeScript into
   `security_ir_artifacts/environment/typescript_toolchain/` using a pinned
   `npm install` against a checked-in `package.json`.
3. Re-resolves and verifies `tsc --version` against the provisioned binary.
4. Refreshes `security_ir_artifacts/environment/solver-dependency-probe.json`
   (the `PORTAL-CXTP-058` evidence artifact) so the checked-in probe reflects
   the current, real dependency state.
5. Writes a machine-readable remediation report to
   `security_ir_artifacts/environment/typescript-remediation-report.json`.

If TypeScript still cannot be resolved after remediation (for example, `npm`
itself is unavailable or the install fails), both the remediation report and
the refreshed probe keep `proof_acceptance_blocked: true`. This script never
marks TypeScript "present" without a real, successful `tsc --version`
invocation against the resolved executable.

## Remediation Strategy: Repo-Scoped npm Install

Rather than requiring a global `npm install -g typescript` (which depends on
write access to a shared global `node_modules` and is not reproducible across
hosts or CI workers), this task pins TypeScript inside the repository at:

```
security_ir_artifacts/environment/typescript_toolchain/
├── package.json          # tracked in git; pins the typescript version
├── package-lock.json      # gitignored (matches **/package-lock.json)
└── node_modules/          # gitignored (matches **/node_modules)
    └── .bin/tsc           # resolved by name after install
```

`package.json` is committed so the pinned TypeScript version is reviewable and
reproducible from a clean checkout. `node_modules/` and `package-lock.json`
are gitignored the same way every other Node toolchain in this repository is
(`**/node_modules`, `**/package-lock.json` in `.gitignore`), so provisioning
must be repeatable rather than relying on a committed `node_modules` tree.

### Resolution order

`scripts/ops/security_verification/probe_theorem_prover_environment.py` and
`scripts/ops/security_verification/provision_required_typescript_toolchain.py`
resolve `tsc` in the same order:

1. `TSC_EXE` environment variable, when set, pointing directly at an
   executable (or a name resolvable on `PATH`). Use this to pin an explicit,
   audited compiler outside the repo-scoped toolchain when required.
2. The repo-scoped toolchain path:
   `security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin/tsc`.
   The probe checks this path automatically, relative to the detected repo
   root, even without any environment variable set.
3. `tsc` on `PATH`, for hosts that provision TypeScript globally instead.

## Running the Remediation

From the repository root, with the same interpreter used for the probe and
proof gates:

```bash
cd /home/barberb/barberb/copilot-worktrees/lift_coding/hallucinate-llc-psychic-adventure/external/ipfs_datasets
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/provision_required_typescript_toolchain.py \
  --probe security_ir_artifacts/environment/solver-dependency-probe.json \
  --out security_ir_artifacts/environment/typescript-remediation-report.json
```

This is idempotent: if `tsc` is already resolvable (for example, from a prior
run of this script), the script records
`remediation_status: "skipped_already_present"` and does not re-run `npm
install`. If the pinned TypeScript version changes
(`--typescript-version`), the script rewrites `package.json` and reinstalls.

Useful flags:

- `--toolchain-dir PATH` — use a different repo-scoped install directory
  (default `security_ir_artifacts/environment/typescript_toolchain`).
- `--typescript-version X.Y.Z` — pin a different TypeScript release (default
  `5.6.3`).
- `--skip-install` — only check for an existing `tsc`; never attempt `npm
  install` (useful for offline verification-only runs).
- `--skip-refresh-probe` — do not rewrite the solver dependency probe
  artifact; only write the remediation report.
- `--refresh-probe-out PATH` — write the refreshed probe evidence to a
  different path instead of overwriting `--probe` in place.
- `--fail-on-blocking` — exit non-zero when proof acceptance remains blocked
  after remediation (for CI gates that should hard-fail).

Inspect the script's full flag set:

```bash
PYTHONPATH=. python scripts/ops/security_verification/provision_required_typescript_toolchain.py --help
```

## Manual Reproduction (No Script)

An operator can reproduce the same toolchain by hand if the script is
unavailable:

```bash
mkdir -p security_ir_artifacts/environment/typescript_toolchain
cat > security_ir_artifacts/environment/typescript_toolchain/package.json <<'JSON'
{
  "name": "crypto-exchange-typescript-toolchain",
  "private": true,
  "version": "1.0.0",
  "devDependencies": {
    "typescript": "5.6.3"
  }
}
JSON
npm install --no-audit --no-fund --prefix security_ir_artifacts/environment/typescript_toolchain
security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin/tsc --version
```

Then either export an explicit override:

```bash
export TSC_EXE="$PWD/security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin/tsc"
```

or rely on the probe's automatic repo-relative resolution described above,
and re-run the probe:

```bash
PYTHONPATH=. python scripts/ops/security_verification/probe_theorem_prover_environment.py \
  --out security_ir_artifacts/environment/solver-dependency-probe.json
```

## Interpreting the Remediation Report

`security_ir_artifacts/environment/typescript-remediation-report.json` fields:

- `remediation_status` — one of `skipped_already_present`,
  `skipped_install_disabled`, `resolved`, `resolved_but_unverified`,
  `failed_no_npm`, `failed_install_error`, `failed_still_missing`.
- `typescript_status_before` — the `typescript` dependency entry copied from
  the input `--probe` baseline (from `PORTAL-CXTP-058`), or `null` if that
  file was missing or unreadable.
- `typescript_status_after` — the recomputed status following remediation,
  including the resolved `executable`, `version`, and whether it is still
  `blocking`.
- `refreshed_probe` — a summary of the re-run solver dependency probe
  (`overall_status`, `proof_acceptance_blocked`,
  `blocking_evidence_count`), or `null` when `--skip-refresh-probe` was
  used.
- `proof_acceptance_blocked` — `true` when TypeScript remains unavailable
  **or** when the refreshed probe reports any other required dependency
  still missing. This mirrors the fail-closed contract already used by
  `PORTAL-CXTP-058` and `PORTAL-CXTP-088`.
- `security_decision` — one of `TYPESCRIPT_DEPENDENCY_REMEDIATED`,
  `BLOCK_PROOF_ACCEPTANCE_TYPESCRIPT_DEPENDENCY_UNAVAILABLE`,
  `BLOCK_PROOF_ACCEPTANCE_OTHER_REQUIRED_DEPENDENCY_MISSING`.
- `reproduction_instructions` — the manual command sequence documented above,
  rendered with the resolved toolchain directory.

## Acceptance Rule

Treat `PORTAL-CXTP-089` as satisfied only when:

1. Running the remediation script on a clean checkout resolves `tsc` from the
   repo-scoped toolchain (or an explicit `TSC_EXE` override) and
   `typescript_status_after.status == "present"` with a real, successful
   `tsc --version` result.
2. The refreshed `security_ir_artifacts/environment/solver-dependency-probe.json`
   no longer lists `typescript` in `blocking_evidence`.
3. If remediation fails for any reason (no network, no `npm`, install error),
   the remediation report and the refreshed probe both keep
   `proof_acceptance_blocked: true`, and proof acceptance for this host stays
   blocked until a human or CI operator resolves the underlying failure.

Do not hand-edit `security_ir_artifacts/environment/solver-dependency-probe.json`
or `security_ir_artifacts/environment/typescript-remediation-report.json` to
mark TypeScript present. Only the probe and remediation scripts, running a
real `tsc --version` command, may set that state.
