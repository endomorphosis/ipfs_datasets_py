# Attested Intent Authorization

Operator and developer guide for the Intent · Legal · Security **attested
authorization** stack delivered under LIG-G090–LIG-G120 (terminal integration
task **LIG-041**).

This guide complements the architecture plans (read-only for implementers):

- `docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md`
- `docs/architecture/INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`
- `docs/architecture/logic_intent_legal_gate.objectives.md`

Rollout operations live in
[`docs/implementation/runbooks/logic_intent_legal_gate_rollout.md`](../implementation/runbooks/logic_intent_legal_gate_rollout.md).

---

## What this system does

Given a **canonical invocation envelope** (SkillCenter skill, prompt, or MCP
tool request), the stack:

1. Projects source records into `InvocationIntentEnvelope@1` **without executing**
   skill, prompt, or tool bodies.
2. Selects applicable Legal/Security proof envelopes from a content-addressed
   **proof corpus** under an immutable manifest + revocation root.
3. Independently verifies native and/or ZK attestations (simulated ZK never
   authorizes production).
4. Composes obligation proof jobs and a deterministic portfolio decision.
5. Emits an exact-context **decision receipt** and optional one-time capability.
6. Enforces non-allow outcomes at the pre-dispatch boundary when rollout policy
   permits consumption.

Wire outcomes remain the closed set: **`allow` | `reject` | `abstain`**.
Abstain never promotes to allow. Production default profile is **`legal-strict`**.

---

## Package surfaces (LIG-041 exports)

All three packages use **lazy, dependency-light** exports. A plain import does
not load optional solvers (`z3`, `cvc5`, …), network clients, or circuit tooling.

| Package | Import | Primary symbols |
|---------|--------|-----------------|
| Admissibility / authorization | `ipfs_datasets_py.logic.admissibility` | `IntentAdmissibilityGate`, `IntentAuthorizationService`, `DecisionReceipt`, `AuthorizationRolloutPolicy`, `evaluate_admissibility`, `evaluate_authorization` |
| Proof corpus | `ipfs_datasets_py.logic.proof_corpus` | `ProofCorpusStore`, `AttestedProofEnvelope`, `ProofCorpusQuery`, `AttestedProofVerifier`, `ProofRevocationSnapshot`, `ProofTrustPolicy` |
| Invocation | `ipfs_datasets_py.logic.intent_ir.invocation` | `InvocationIntentEnvelope`, `SkillCenterInvocationAdapter`, `PromptInvocationAdapter`, `MCPInvocationAdapter` |

Registry discovery:

```python
from ipfs_datasets_py.logic.submodule_registry import logic_submodule_spec

logic_submodule_spec("admissibility")
logic_submodule_spec("proof_corpus")
logic_submodule_spec("intent_ir.invocation")
```

Leaf modules remain the authority for implementation details; package roots
re-export reviewed `__all__` symbols only.

---

## Offline evaluation (no execution)

Golden fixtures under
`tests/fixtures/logic/attested_authorization/` encode skill / prompt / MCP
equivalent cases with **bound expected decisions**. Offline evaluation:

- never executes skill, prompt, or MCP bodies;
- never requires network, paid models, or optional solvers;
- reaches the **exact** status, internal status, reason codes, filters, and
  obligations declared on each case;
- treats simulated ZKP / non-authoritative attestation kinds as **cannot allow**
  under production profiles (`legal-strict`, `zkp-required`, `security-lite`).

Structural contract: `tests/unit/logic/admissibility/test_attested_golden_contract.py`  
Release conformance: `tests/integration/logic/test_attested_intent_authorization.py`

---

## Production invariants

| Invariant | Rule |
|-----------|------|
| No unconstrained allow | Every profile sets `allow_without_constraints=false` |
| Simulated ZKP | Never authorizes production; `accept_simulated_zkp=false` outside `dev-offline` |
| Non-authoritative kinds | `simulation`, `artifact-membership` cannot substitute for direct proof verification |
| Unknown profile | Fail closed as reject (`invalid_profile`) |
| Receipt consumption | Default **off**; enabled only under allowlisted canary/enforce with approvals |
| Secrets / PII in telemetry | Forbidden as metric labels (bounded redaction vocabulary) |

---

## Corpus, circuit, VK, and policy promotion

Promotion of any of the following requires human **legal** and **security**
review plus a release-owner approval, bound to exact roots:

1. **Proof corpus root** (manifest CID / content digest)
2. **Revocation snapshot root**
3. **Trust / coverage policy** document and digest
4. **Circuit ID** and **verification key (VK)** set (including trusted setup)
5. **Admissibility / rollout policy** config (`config/intent_authorization_rollout.json`)
6. **Fixture / golden corpus** revision used for release gates

Promotion receipt fields (minimum):

- git commit / tree for `ipfs_datasets_py` (and accelerate if bridge-touched)
- corpus root, revocation root, policy root, circuit/VK identifiers
- profile id + `config_digest`
- selected test paths and exit codes
- known gaps and optional-capability coverage
- approval identities and timestamps
- rollback drill result

Never mark old receipts valid under a new policy or corpus root.

---

## Privacy and retention

- Telemetry uses **bounded, redacted labels** only (source kind, outcome class,
  policy profile, authority class, latency buckets, cache/filter classes).
- Raw prompts, tool arguments, formulas, witnesses, secrets, and free-form CIDs
  are rejected as metric labels.
- Fixture corpus is synthetic (`privacy_class=public_synthetic`); production
  tenant data must not be committed to the golden tree.
- Evidence retained on rollback: redacted decision observations and canary
  receipts; disable **receipt consumption** first.

---

## Incidents and disable

**Immediate disable** (prefer first):

```bash
# Rollout / receipt consumption
# (config stage may remain shadow/audit; consumption must go false)

# Bridge observation kill-switch
export IPFS_ACCELERATE_ADMISSIBILITY_ENABLED=0
export IPFS_ACCELERATE_ADMISSIBILITY_PROFILE=legal-strict
```

Programmatic: `AuthorizationRolloutPolicy.immediate_disable_receipt_consumption()`
(or equivalent config write with `receipt_consumption_enabled=false`).

Preserve redacted evidence. Do not delete canary receipts needed for incident
review. After fix, re-run the release validation suite before re-entering
shadow or canary.

---

## Shadow / deny / allow canary thresholds

Staged ladder (see runbook for operator commands):

`off` → `audit` → `shadow` → `deny-canary` → `allow-token-canary` → `enforce`

| Stage | Threshold / gate |
|-------|------------------|
| shadow | Zero authority-boundary violations on sample; metrics stable; no silent allow without constraints |
| deny-canary | Zero false-allow; false-deny budget measured; allowlisted cohort; rollback drill pass |
| allow-token-canary | Reversible effect allowlist only; short-lived one-time receipts; zero simulated-ZKP allows; approvals present |
| enforce | Explicit legal/security/release approvals; current-tree evidence receipt; canary receipt bound |

Skipped transitions are rejected. Production default remains **shadow** for live
observation until enforce is explicitly approved.

---

## Rollback drill

1. Disable receipt consumption immediately.
2. Return live traffic to shadow (or off) without deleting evidence.
3. Re-run:

```bash
python -m pytest \
  tests/unit/logic/admissibility/test_attested_golden_contract.py \
  tests/integration/logic/test_attested_intent_authorization.py \
  tests/integration/logic/test_intent_admissibility_gate.py \
  tests/integration/logic/test_ir_family_conformance.py \
  tests/integration/logic/test_ir_compatibility_exports.py \
  -q
```

4. Record drill timestamps, pre/post stage, and operator identity in the release
   evidence bundle.
5. Resume promotion only with a **new** canary receipt on the fixed tree.

---

## Release evidence binding (LIG-041)

A release is not complete when the task board is green. Fresh evidence must
bind:

| Binding | Example |
|---------|---------|
| Exact code tree | git commit SHA / tree id |
| Corpus / revocation / policy roots | CIDs or digests |
| Circuits / VKs / keys | circuit_id, vk_id, key material id (not secrets) |
| Config | rollout JSON digest, profile `config_digest` |
| Capabilities | optional solver availability matrix |
| Selected tests | the validation command paths above |
| Gaps | skipped optional coverage, known limitations |
| Approvals | release owner, legal, security |

Interface names for automation:

- `AttestedAuthorizationGoldenCorpus@1`
- `AttestedAuthorizationConformance@1`
- `AttestedAuthorizationRollout@1`
- `AuthorizationTelemetry@1` / `AuthorizationRolloutPolicy@1`

---

## Related code map

| Concern | Path |
|---------|------|
| Gate / profiles / reasons | `ipfs_datasets_py/logic/admissibility/` |
| Authorization service / receipts | `…/service.py`, `…/receipt.py`, `…/enforcement.py` |
| Telemetry / rollout | `…/telemetry.py`, `config/intent_authorization_rollout.json` |
| Proof corpus | `ipfs_datasets_py/logic/proof_corpus/` |
| Invocation adapters | `ipfs_datasets_py/logic/intent_ir/invocation/` |
| Registry | `ipfs_datasets_py/logic/submodule_registry.py` |
| Golden fixtures | `tests/fixtures/logic/attested_authorization/` |
| Rollout runbook | `docs/implementation/runbooks/logic_intent_legal_gate_rollout.md` |
