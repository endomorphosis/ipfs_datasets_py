# Logic Intent · Legal · Security Gate — Shadow and Canary Rollout

This runbook controls promotion of the Intent admissibility gate
(`IntentAdmissibilityGate@1`) and the supervisor bridge
(`SupervisorAdmissibilityBridge@1`) from offline evaluation into live agent
supervisor and MCP traffic.

Deterministic Legal and Security constraint evaluation, attestation integrity,
proof-corpus query, and fail-closed profile resolution remain authoritative.
The gate never executes skill, prompt, or MCP bodies. Simulated ZKP receipts
may appear only under clearly labeled development profiles and never authorize
a production dispatch.

| Item | Value |
|------|--------|
| Task | LIG-020 (goal LIG-G080) |
| Bundle / lane | `lig/eval-rollout` / `lig-eval` |
| Board namespace | `logic-intent-legal-gate-v1` |
| Branch | `feature/logic-intent-legal-gate` |
| State root | `data/agent_supervisor/logic_intent_legal_gate/` |
| Default disposition without constraints | **reject** (never allow) |
| Production rollout default | **shadow** |

Depends on completed gate and bridge work (LIG-016, LIG-017). Later authority
hardening (LIG-022…LIG-041) may extend modes and receipts without flipping the
production default without a canary receipt.

---

## Admissibility profiles

Closed vocabulary (`AdmissibilityProfile@1`, wire values pinned in
`ipfs_datasets_py/logic/admissibility/profiles.py`). Unknown profile ids fail
closed as **reject** (`invalid_profile`); they never resolve to a permissive
policy.

| Profile id | Legal required | Security required | ZKP verify | Simulated ZKP | Use |
|------------|----------------|-------------------|------------|---------------|-----|
| `dev-offline` | yes | yes | no | accepted when labeled | Offline fixtures, local dry-runs, CI without real ZKP |
| `security-lite` | no | yes | no | rejected | Security-first pilots; Legal optional |
| `legal-strict` | yes | yes | no | rejected | **Production default** |
| `zkp-required` | yes | yes | yes | rejected | High-assurance paths; missing ZKP → **abstain**, never allow |

Every registered profile sets `allow_without_constraints=false`. The registry
default is `legal-strict` (`DEFAULT_PROFILE_ID`).

Config digest: each profile exposes a stable SHA-256 of its canonical policy
map via `AdmissibilityProfile.config_digest()`. Bind that digest in canary
receipts and decision observations.

### Profile selection (supervisor / bridge)

```bash
# Production default when unset: legal-strict
export IPFS_ACCELERATE_ADMISSIBILITY_PROFILE=legal-strict

# Offline CI / local fixtures only
export IPFS_ACCELERATE_ADMISSIBILITY_PROFILE=dev-offline

# High-assurance canary (after corpus + ZKP stack ready)
export IPFS_ACCELERATE_ADMISSIBILITY_PROFILE=zkp-required
```

Related bridge environment flags (LIG-017):

| Variable | Default | Meaning |
|----------|---------|---------|
| `IPFS_ACCELERATE_ADMISSIBILITY_ENABLED` | enabled when datasets importable | `0`/`false` disables bridge construction path |
| `IPFS_ACCELERATE_ADMISSIBILITY_STORE` | unset | Filesystem root for `ProofCorpusStore` |
| `IPFS_ACCELERATE_ADMISSIBILITY_PROFILE` | `legal-strict` | Profile wire id |
| `IPFS_ACCELERATE_ADMISSIBILITY_REQUIRE_DATASETS` | false | When true, construction fails hard if gate is unavailable |

---

## Protected paths

Operator-protected repository inputs. Implementation agents, canaries, and
automated implementers must treat these as **read-only**. Never create, modify,
rename, delete, replace, or regenerate them unless an operator explicitly
approves a protected-path exception outside this runbook.

| Path | Role |
|------|------|
| `docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md` | Program plan and success criteria |
| `docs/architecture/logic_intent_legal_gate.objectives.md` | Goal heap (LIG-G\*) |
| `docs/architecture/logic_intent_legal_gate.todo.md` | Reviewed task board (LIG-\*) |

Related authority design (read for threat model; not the LIG-020 edit surface):

- `docs/architecture/INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`

Supervisor launch always passes the three protected paths as
`--implementation-protected-path` flags (see [Operator launch](#operator-launch-agent-supervisor-board)).

Do not co-launch `ir-family-v1` / IRF supervisors against the same worktree or
todo path while LIG lanes run. Keep state under
`data/agent_supervisor/logic_intent_legal_gate/` only.

---

## Rollout stages

Stages are ordered and reversible. **Do not skip shadow.** Do not flip the
production default to enforce without a canary receipt and operator approval.

| Stage | Gate behavior | Supervisor / dispatch effect | Exit criteria |
|-------|---------------|------------------------------|---------------|
| `off` | Gate not consulted for live traffic | Pre-LIG path; bridge may be disabled | N/A baseline |
| `audit` | Evaluate offline or on sample; log only | No dispatch change | Gate + bridge unit/integration green |
| `shadow` | **Default for first live enablement.** Evaluate every eligible intent; record allow/reject/abstain observations | Dispatch **unchanged** (gate result is observational only) | Zero authority-boundary violations on sample; metrics stable; no silent allow without constraints |
| `canary` | Evaluate on an allowlisted, time-bounded cohort | Optional **deny** enforcement for canary only; production allow remains gated | Zero authority violations; zero simulated-ZKP production allows; paired thresholds pass; rollback drill documented |
| `enforce` | Fail closed on live traffic | Non-allow → reject at dispatch boundary | Explicit release-owner + legal/security approval; canary receipt bound to exact tree |

Wire status remains `allow` | `reject` | `abstain`. At an enforcement boundary,
all non-allow outcomes map to rejection. Abstain never promotes to allow.

### Shadow (default)

1. Enable bridge observation with `legal-strict` (or the declared pilot profile).
2. Keep dispatch on the pre-canary path (observation-only).
3. Write decision observations with: `status`, `reasons`, `intent_cid`,
   `constraint_cids`, `attestation_results`, `profile_id`, `config_digest`.
4. Compare shadow decisions to offline fixtures and the LIG-019 benchmark.
5. Stay in shadow until canary criteria pass and an operator records approval.

```bash
# Shadow observation using offline fixtures / store (no network)
export IPFS_ACCELERATE_ADMISSIBILITY_ENABLED=1
export IPFS_ACCELERATE_ADMISSIBILITY_PROFILE=legal-strict
# Point at a local proof-corpus root when available:
# export IPFS_ACCELERATE_ADMISSIBILITY_STORE=/path/to/proof-corpus
```

Shadow must record, never mutate:

- canonical Intent formal artifacts and proof-corpus envelopes
- protected architecture documents
- production dispatch allow/deny policy defaults

### Canary criteria

Promote from shadow to canary only when **all** of the following hold:

1. **Validation suite green** on the exact release tree (commands below).
2. **Profile closed set** still matches `dev-offline`, `security-lite`,
   `legal-strict`, `zkp-required`; unknown ids reject.
3. **Zero authority-boundary violations** on the shadow sample: no allow without
   attested constraints; no simulated ZKP authorize under `legal-strict` or
   `zkp-required`.
4. **Lineage and integrity**: fixture and live sample decisions assert
   content-addressed Intent and constraint CIDs (LIG-016 acceptance).
5. **Leakage guards**: LIG-019 benchmark remains offline and deterministic;
   held-out sources never train the gate.
6. **Bridge import hygiene**: `agent_supervisor` import does not load heavy
   provers (`z3`, `cvc5`, `vampire`, `lean_dojo`, `shadowprover`) at module load
   (LIG-017).
7. **Canary cohort is explicit**: allowlisted actors/tools/effects, bounded
   duration, and a named owner. Prefer deny-canary (enforce reject on canary
   only) before any allow-token canary.
8. **Rollback drill** executed successfully within the canary window (see
   [Rollback](#rollback)).
9. **Canary receipt** written under the operator evidence root binding:
   - git tree / commit
   - profile id + config digest
   - proof-corpus / store snapshot digests when used
   - validation command exit codes
   - shadow metrics summary (allow/reject/abstain counts)
   - approval identity and timestamp

Canary requires **zero authority violations**. Any hard-gate regression, silent
allow, or simulated-proof production authorization aborts promotion and returns
to shadow or off.

### Enforce (later; not LIG-020 default)

Full enforce is out of band for LIG-020. Later work (LIG-G120 / LIG-039+) may
add staged policy (`off` → `audit` → `shadow` → `deny-canary` →
`allow-token-canary` → `enforce`) and redacted telemetry. Until that config
exists, operators treat **shadow as production default** and require manual
approval for any enforce-like wiring.

---

## Validation commands

Run from the `ipfs_datasets_py` repository root (worktree or checkout) with
`PYTHONPATH` including the datasets tree and, for supervisor bridge tests,
`../ipfs_accelerate_py` (or the path that provides
`ipfs_accelerate_py.agent_supervisor`).

### Runbook presence (LIG-020 acceptance)

```bash
test -f docs/implementation/runbooks/logic_intent_legal_gate_rollout.md
```

### Protected path presence (operator preflight)

```bash
test -f docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md \
  && test -f docs/architecture/logic_intent_legal_gate.objectives.md \
  && test -f docs/architecture/logic_intent_legal_gate.todo.md
```

### Gate and profiles (LIG-014 / LIG-015)

```bash
python -m pytest tests/unit/logic/admissibility/test_profiles.py -q
python -m pytest tests/unit/logic/admissibility/test_gate.py -q
```

### End-to-end admissibility (LIG-016)

```bash
python -m pytest tests/integration/logic/test_intent_admissibility_gate.py -q
```

### Supervisor bridge (LIG-017; accelerate tree on `PYTHONPATH`)

```bash
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/../ipfs_accelerate_py:$(pwd)"
python -m pytest test/api/test_agent_supervisor_intent_admissibility.py -q
```

### MCP tools (LIG-018)

```bash
python -m pytest tests/unit/mcp_server/test_logic_admissibility_tools.py -q
```

### Benchmark and leakage guards (LIG-019)

```bash
python -m pytest tests/benchmarks/logic/test_intent_admissibility_benchmark.py -q
```

### Recommended pre-canary bundle

```bash
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/../ipfs_accelerate_py:$(pwd)"

test -f docs/implementation/runbooks/logic_intent_legal_gate_rollout.md

python -m pytest \
  tests/unit/logic/admissibility/test_profiles.py \
  tests/unit/logic/admissibility/test_gate.py \
  tests/integration/logic/test_intent_admissibility_gate.py \
  tests/unit/mcp_server/test_logic_admissibility_tools.py \
  tests/benchmarks/logic/test_intent_admissibility_benchmark.py \
  test/api/test_agent_supervisor_intent_admissibility.py \
  -q
```

All of the above must pass offline (no network) before canary admission.

---

## Operator launch (agent supervisor board)

Preferred entry from `ipfs_datasets_py` root on
`feature/logic-intent-legal-gate`:

```bash
# Inspect ready tasks only (no implementation model)
scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh --dry-run

# Four isolated shards (default SHARD_COUNT=4)
scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh

# Single shard foreground
SHARD=0 SHARD_COUNT=4 scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh --foreground
```

Equivalent manual one-shard form:

```bash
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/../ipfs_accelerate_py:$(pwd)"
export SHARD=0   # 0..3 when SHARD_COUNT=4

python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor \
  --implement \
  --task-prefix "LIG-" \
  --task-shard-count 4 \
  --task-shard-index "$SHARD" \
  --todo-path docs/architecture/logic_intent_legal_gate.todo.md \
  --state-dir "data/agent_supervisor/logic_intent_legal_gate/shards/$SHARD/state" \
  --worktree-root "data/agent_supervisor/logic_intent_legal_gate/shards/$SHARD/worktrees" \
  --implementation-protected-path docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md \
  --implementation-protected-path docs/architecture/logic_intent_legal_gate.objectives.md \
  --implementation-protected-path docs/architecture/logic_intent_legal_gate.todo.md
```

Dry-run / no-implement planning (when supported by the launch script):

```bash
IMPLEMENT=0 scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh --dry-run
```

Do not use coarse objective-generated IRG/LIG refill boards concurrently with
this reviewed board unless refill is deliberately enabled.

---

## Rollback

Rollback is flag-based and reversible. Prefer the least disruptive step that
restores a safe posture.

### Immediate disable (bridge)

```bash
export IPFS_ACCELERATE_ADMISSIBILITY_ENABLED=0
# Optional: pin a conservative profile if partial observation continues
export IPFS_ACCELERATE_ADMISSIBILITY_PROFILE=legal-strict
```

### Return to shadow

1. Disable any canary allowlist / deny enforcement wiring.
2. Keep evaluation and observation enabled.
3. Preserve shadow and canary evidence (do not delete receipts used for the
   failure review).

### Return to off

```bash
export IPFS_ACCELERATE_ADMISSIBILITY_ENABLED=0
unset IPFS_ACCELERATE_ADMISSIBILITY_STORE
# Restart supervisor processes that cached the previous bridge config
```

### Mandatory rollback triggers

Roll back when any of the following occur during shadow or canary:

- allow without attested constraints
- simulated ZKP authorizes a non-`dev-offline` path
- unknown profile fails open or maps to a looser policy
- integrity / attestation verification false-negatives or false-allows
- authority-boundary or tenant isolation violation
- LIG-016 / LIG-017 / LIG-019 validation regression on the canary tree
- network dependency introduced into offline fixtures or benchmark rebuild

After rollback, re-run the [pre-canary bundle](#recommended-pre-canary-bundle)
and remain in shadow until a new canary receipt is approved.

---

## Decision semantics (operator quick reference)

| Status | Meaning | Live dispatch under enforce |
|--------|---------|-----------------------------|
| `allow` | Obligations covered by positive grants; profile families and integrity hold | May proceed only with a valid receipt path (later tasks) |
| `reject` | Hard Legal/Security forbid, contradiction, integrity fail, invalid profile | Block |
| `abstain` | Incomplete evidence, unsupported semantics, missing required ZKP | Block (never promote to allow) |

MCP surface (observational / fail-closed handlers):

- `normalize_intent`
- `formalize_intent`
- `query_proof_corpus`
- `check_intent_admissibility`

Handlers must never execute skill or prompt bodies.

---

## Evidence checklist (canary / promotion)

Capture before any stage transition past shadow:

- [ ] Profile id and `config_digest`
- [ ] Exact git commit / tree for datasets (and accelerate if bridge-touched)
- [ ] Validation command log (exit codes for the pre-canary bundle)
- [ ] Shadow metrics: allow / reject / abstain counts and sample size
- [ ] Zero authority-violation attestation for the sample window
- [ ] Canary cohort definition (who, tools, duration, owner)
- [ ] Rollback drill result and timestamps
- [ ] Operator approvals (release owner; legal/security when enforce is sought)

No production default flip without a canary receipt.

---

## Related artifacts

| Artifact | Path |
|----------|------|
| Profiles | `ipfs_datasets_py/logic/admissibility/profiles.py` |
| Gate | `ipfs_datasets_py/logic/admissibility/gate.py` |
| Reasons | `ipfs_datasets_py/logic/admissibility/reasons.py` |
| MCP tools | `ipfs_datasets_py/mcp_server/tools/logic_admissibility_tools.py` |
| Supervisor bridge | `ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py` |
| Integration fixtures | `tests/fixtures/logic/admissibility/`, `tests/fixtures/intent_ir/admissibility/` |
| Benchmark fixtures | `tests/fixtures/logic/admissibility/benchmark/` |
| Multi-lane ops | `scripts/ops/logic_intent_legal_gate/` |
| Leanstral LegalIR rollout (separate program) | `docs/implementation/runbooks/leanstral_legal_ir_rollout.md` |

This document is the LIG-020 shadow/canary runbook. Later governance tasks may
extend it with telemetry policy files and release-bound evidence manifests
without weakening the shadow-default or protected-path rules above.
