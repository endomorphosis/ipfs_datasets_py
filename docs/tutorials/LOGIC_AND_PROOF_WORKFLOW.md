# Logic and proof workflow

| Field | Value |
| --- | --- |
| Interface | `LogicProofTutorial@1` |
| Task | `IPFSDOC-084` |
| Status | `canonical` |
| Owner | tutorials / logic-proof plane |
| Last verified | 2026-08-03 |
| Audience | developer, agent, offline operator, security reviewer |
| Related | [KNOWLEDGE_LOGIC_AND_PROOF.md](../api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md), [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md), [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md), [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

> **Purpose.** Bounded, **offline-first** journey through logic **capability
> probe**, **syntactic validation**, **formalization contracts**, **prover
> availability**, and **typed result authority**. This tutorial deliberately
> **never** promotes parser output, NL model output, SAT models, optimizer
> scores, or policy `allowed` into theorem **proof**. Every path declares
> native prerequisites, timeouts, temporary data, cleanup, redaction, and
> side effects.

**Upstream tutorials:** complete
[FIRST_DATASET_WORKFLOW.md](FIRST_DATASET_WORKFLOW.md) and
[RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) if
you need dataset and retrieval context. Graph facts and search scores are
**not** proof (see inequalities below).

**Sibling service plane:** [MCP_CLIENT_WORKFLOW.md](MCP_CLIENT_WORKFLOW.md).

---

## 1. Learning objectives

By the end of this tutorial you can:

1. Declare logic/prover native extras and degrade honestly when they are missing.
2. Probe `LogicProcessor` capabilities and health without claiming proof.
3. Validate and analyze formula **syntax** as non-proof evidence.
4. Use formalization **contracts** (schemas / views) without treating compile
   success as theorem authority.
5. Probe external prover availability (`ProverRouter` / Z3 flags) with timeouts.
6. Build and inspect typed `ResultAuthority` objects and refuse kind substitution.
7. Evaluate Profile D policy as **policy-layer** approval only.
8. Clean up temp workspaces and redact proof/policy artifacts for logs.

---

## 2. Prerequisites and declared extras

### 2.1 Minimum (offline tutorial path)

| Requirement | Notes |
| --- | --- |
| Python ≥ 3.12 | Project `requires-python` |
| Editable or installed `ipfs_datasets_py` | From repository root |
| Write access to a temp directory | Tutorial uses `tempfile` |

```bash
# From the repository root
pip install -e .
```

### 2.2 Optional native / service extras

| Extra / dependency | Enables | If missing |
| --- | --- | --- |
| `z3-solver` (Z3) | `Z3ProverBridge`, router route `z3` | `Z3_AVAILABLE` false; router omits z3 |
| CVC5 binary / bindings | `CVC5ProverBridge` | Availability check fails; fail closed for production |
| Lean / Coq toolchain | Interactive theorem bridges | `LEAN_AVAILABLE` / `COQ_AVAILABLE` false |
| SymbolicAI | Neural/symbolic bridge | `SYMBOLICAI_AVAILABLE` false |
| CEC / ErgoAI submodules | Deep DCEC / F-logic engines | `LogicProcessor` health marks module **unavailable** |
| ZKP extras (`profile-f-zk`, circuits) | Production attestation paths | Simulated ZKP remains **non-authoritative** |

```bash
# Optional only — not required for the validation / typed-authority path
pip install z3-solver
# Optional: CVC5, Lean, Coq are environment-specific binaries; do not assume install.
```

**Native side effects:** prover packages may download wheels; first Z3 use can
spawn solver processes and burn CPU. This tutorial bounds timeouts and never
requires network provers or hub downloads for the **verified offline path**.

### 2.3 Timeouts (declared budgets)

| Surface | Tutorial budget | Notes |
| --- | --- | --- |
| `LogicProcessor.prove_tdfol` | `timeout_ms=5000` | Milliseconds |
| `LogicProcessor.prove_dcec` | `timeout=5` | Seconds |
| `ProverRouter` / `Z3ProverBridge` | `default_timeout=5.0` | Seconds |
| Capability / health / validate | sub-second expected | No solver required |
| Profile D `evaluate_execution_policy` | pure evaluation | Optional ZKP certificate is statement-ready, not a proof |

If a call exceeds the budget, treat the outcome as **unknown / error**, not
as `disproved`.

---

## 3. Canonical imports

```python
# Operational façade (MCP/CLI-aligned envelopes)
from ipfs_datasets_py.core_operations import LogicProcessor

# Typed result authority (kernel contracts)
from ipfs_datasets_py.logic.ir_core import (
    AuthorityKind,
    ResultAuthority,
    ResultStatus,
    RESULT_AUTHORITY_SCHEMA_VERSION,
)

# External provers (availability is optional)
from ipfs_datasets_py.logic.external_provers import (
    ProverRouter,
    Z3_AVAILABLE,
    check_prover_availability,
    get_available_provers,
)

# Formalization contracts (schemas / compiler protocol — not theorem proof)
from ipfs_datasets_py.logic.formalization import (
    FormalizationCompilerConfig,
    FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION,
    validate_view_artifacts,
)

# Policy layer (allowed ≠ proof ≠ MCP dispatch)
from ipfs_datasets_py.logic import evaluate_execution_policy, ProfileDPolicyError
```

**Avoid for this journey**

| Pattern | Why |
| --- | --- |
| Treating `parse_*` / NL→formula success as proof | Parser/model output is a **candidate**, not theorem authority |
| Collapsing `proved` with `satisfiable` or `allowed` | Different `AuthorityKind` values — non-substitutable |
| `logic.tools` as preferred import | **Compatibility** redirect; prefer `logic.integration` or family modules |
| Simulated ZKP / mock attestation as production proof | Non-authoritative by contract |

**Core inequalities (binding)**

- formula **parse** / **validate** ≠ theorem **proof**
- SAT/SMT **model** ≠ theorem permission
- optimizer **score** ≠ proof
- graph **fact** / retrieval **score** ≠ proof
- policy `allowed` ≠ authorization **dispatch grant** ≠ theorem proof
- capability **available** ≠ successful proof of a goal

Architecture: [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md).

---

## 4. Offline workspace setup

```python
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

WORK = Path(tempfile.mkdtemp(prefix="logic_proof_workflow_"))
RECEIPTS = WORK / "receipts"
RECEIPTS.mkdir(parents=True, exist_ok=True)
print("workspace", WORK)
```

**Temporary data:** everything under `WORK` is disposable. Cleanup is mandatory
(§12). Do not write prover caches or receipt dumps into the repository tree.

---

## 5. Capability and health probe

Probe what is importable **before** claiming a proof path. Availability is not
stability and not proof.

```python
import asyncio
from ipfs_datasets_py.core_operations import LogicProcessor


async def probe_logic_plane() -> Dict[str, Any]:
    lp = LogicProcessor()
    caps = await lp.get_capabilities()
    health = await lp.check_health()
    assert caps.get("success") is True
    assert health.get("success") is True
    print(
        "capability_probe",
        {
            "health_status": health.get("status"),  # healthy | degraded | unavailable
            "healthy_modules": health.get("healthy"),
            "total_modules": health.get("total"),
            "logics": {
                name: {
                    "available": meta.get("available"),
                    "features": meta.get("features"),
                }
                for name, meta in (caps.get("logics") or {}).items()
            },
            "conversions": caps.get("conversions"),
        },
    )
    return {"caps": caps, "health": health}


# probe = asyncio.run(probe_logic_plane())
```

| Signal | Meaning | Production proof? |
| --- | --- | --- |
| `health.status == "healthy"` | Listed modules import | **No** |
| `logics.tdfol.available` | TDFOL prover module present | **No** — only a capability bit |
| `health.status == "degraded"` | Some modules missing | Use only available families; fail closed for missing ones |
| `health.status == "unavailable"` | No logic modules | Stop; do not invent proved outcomes |

---

## 6. Validation and analysis (explicitly non-proof)

`validate_formula` checks syntactic / structural fitness.
`analyze_formula` returns structural metrics. Neither emits
`AuthorityKind.THEOREM_PROOF`.

```python
async def validate_and_analyze(lp: LogicProcessor) -> Dict[str, Any]:
    formula = "P -> Q"
    validation = await lp.validate_formula(formula, logic_system="dcec")
    analysis = await lp.analyze_formula(formula)
    # Label disposition — never call this proof
    disposition = "syntax_only_not_proof"
    print(
        "validation",
        {
            "formula": formula,
            "valid": validation.get("valid"),
            "errors": validation.get("errors"),
            "warnings": validation.get("warnings"),
            "analysis_operators": analysis.get("operators"),
            "parsed_ok": analysis.get("parsed_ok"),
            "disposition": disposition,
        },
    )
    (RECEIPTS / "validation.json").write_text(
        json.dumps(
            {
                "validation": validation,
                "analysis": analysis,
                "disposition": disposition,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {"validation": validation, "analysis": analysis, "disposition": disposition}
```

| Outcome | Means | Does **not** mean |
| --- | --- | --- |
| `valid=True` | String accepted by validator | Goal is a theorem |
| `parsed_ok=True` | Structural parse succeeded | Semantic entailment |
| `errors` non-empty | Reject / fix input | Goal is false |
| NL parse tools (`parse_dcec`, …) | Candidate formula | Proof (out of scope as authority) |

**Rule:** never attach `ResultAuthority(kind=THEOREM_PROOF)` to validation-only
envelopes.

---

## 7. Formalization capability (contracts, not proofs)

Formalization exports deterministic **schemas and compiler protocols**. Treat
them as identity/view contracts. Compilation into a formal view is still
**not** a terminal native-kernel theorem receipt.

```python
from ipfs_datasets_py.logic.formalization import (
    FormalizationCompilerConfig,
    FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION,
)


def formalization_capability_note() -> Dict[str, Any]:
    # Config object documents the compiler contract surface.
    # Instantiation proves the import/capability path — not a theorem.
    note = {
        "compiler_config_schema": FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION,
        "config_type": FormalizationCompilerConfig.__name__,
        "disposition": "formalization_contract_not_theorem_proof",
        "authority_kind": None,  # do not invent theorem_proof here
    }
    print("formalization", note)
    (RECEIPTS / "formalization_capability.json").write_text(
        json.dumps(note, indent=2), encoding="utf-8"
    )
    return note
```

| Surface | Role | Authority |
| --- | --- | --- |
| `FormalizationCompilerConfig` / schema versions | Wire/config identity | Contract only |
| `validate_view_artifacts` | Structural view checks | Not theorem proof |
| `FormalizationCompiler.compile` (when used) | Produce formal views | Still requires separate prover/kernel for proof claims |

---

## 8. Prover capability and bounded prove attempt

### 8.1 Availability probe

```python
from ipfs_datasets_py.logic.external_provers import (
    ProverRouter,
    Z3_AVAILABLE,
    check_prover_availability,
    get_available_provers,
)


def probe_provers(timeout: float = 5.0) -> Dict[str, Any]:
    advertised = get_available_provers()  # catalog names (may include unavailable)
    z3_ok = bool(Z3_AVAILABLE) and bool(check_prover_availability("Z3"))
    router = ProverRouter(default_timeout=timeout, enable_cache=False)
    live = router.get_available_provers()
    evidence = {
        "catalog": advertised,
        "z3_available": z3_ok,
        "router_live": live,
        "timeout_seconds": timeout,
        "disposition": "capability_probe_not_proof",
    }
    print("prover_probe", evidence)
    return evidence
```

### 8.2 Bounded TDFOL prove (typed operational envelope)

`LogicProcessor.prove_tdfol` returns an operational dict. Map outcomes carefully:

| Field | Reading |
| --- | --- |
| `success=True`, `proved=True` | Prover claims proved under its method — still not MCP allow |
| `success=True`, `proved=False`, `status="unknown"` | **Not** disproved; fail closed if you need certainty |
| `success=False` | Error / parse failure / unavailable path |

```python
async def bounded_prove_attempt(lp: LogicProcessor) -> Dict[str, Any]:
    formula = "P -> P"
    result = await lp.prove_tdfol(
        formula,
        axioms=None,
        strategy="auto",
        timeout_ms=5000,
        max_depth=10,
        include_proof_steps=False,  # keep receipts small; redact if enabled
    )
    # Operational envelope ≠ ResultAuthority until you attach a kind deliberately
    status = result.get("status")
    if result.get("success") and result.get("proved"):
        disposition = "operational_proved_claim_needs_authority_binding"
    elif result.get("success") and not result.get("proved"):
        disposition = "not_proved_or_unknown_not_disproof"
    else:
        disposition = "prove_error_or_unavailable"
    labeled = {
        "formula": formula,
        "success": result.get("success"),
        "proved": result.get("proved"),
        "status": status,
        "method": result.get("method"),
        "elapsed_ms": result.get("elapsed_ms"),
        "disposition": disposition,
        # Explicitly withhold proof_steps from logs by default (redaction)
        "proof_steps_included": False,
    }
    print("prove_attempt", labeled)
    (RECEIPTS / "prove_attempt.json").write_text(
        json.dumps(labeled, indent=2, default=str), encoding="utf-8"
    )
    return labeled
```

**Do not:**

- Call parser-only success a proof.
- Upgrade `status="unknown"` to `disproved`.
- Treat DCEC errors (missing strategy / empty submodule) as semantic falsehood.

---

## 9. Typed result authority handling

Construct `ResultAuthority` only when you intentionally bind a kind. Kinds are
**non-hierarchical**: `permits` is exact match only.

```python
from ipfs_datasets_py.logic.ir_core import (
    AuthorityKind,
    ResultAuthority,
    RESULT_AUTHORITY_SCHEMA_VERSION,
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_typed_authority_demo(
    formula: str,
    prove_labeled: Dict[str, Any],
) -> Dict[str, Any]:
    scope = sha256_hex(formula.encode("utf-8"))
    config = sha256_hex(b"logic_proof_workflow@1")
    evidence = sha256_hex(
        json.dumps(
            {
                "proved": prove_labeled.get("proved"),
                "status": prove_labeled.get("status"),
                "method": prove_labeled.get("method"),
            },
            sort_keys=True,
        ).encode("utf-8")
    )

    # Only attach THEOREM_PROOF when the operational path actually claimed proved.
    # Unknown / not-proved attempts stay unlabeled or use a non-theorem kind.
    if prove_labeled.get("proved") is True and prove_labeled.get("success"):
        kind = AuthorityKind.THEOREM_PROOF
        method = str(prove_labeled.get("method") or "tdfol_prover")
    else:
        # Evidence readiness: "we measured an attempt" — not a theorem.
        kind = AuthorityKind.EVIDENCE_READINESS
        method = "bounded_prove_attempt_receipt"

    authority = ResultAuthority(
        kind=kind,
        issuer="logic_proof_workflow",
        method=method,
        scope_digest=scope,
        evidence_digests=(evidence,),
        configuration_digest=config,
        # schema_version defaults to RESULT_AUTHORITY_SCHEMA_VERSION
        # ("result-authority/v1") — do not invent "1.0.0"
    )
    payload = authority.to_dict()
    # Non-substitution checks
    assert authority.permits(kind) is True
    assert authority.permits(AuthorityKind.SATISFIABILITY) is False
    mismatch = None
    try:
        authority.require(AuthorityKind.POLICY_APPROVAL)
    except Exception as exc:  # AuthorityMismatchError
        mismatch = type(exc).__name__

    out = {
        "schema_version": RESULT_AUTHORITY_SCHEMA_VERSION,
        "authority": payload,
        "permits_same_kind": True,
        "permits_sat_substitution": False,
        "policy_require_error": mismatch,
        "note": "theorem_proof never substitutes for policy_approval or dispatch allow",
    }
    print("typed_authority", out)
    (RECEIPTS / "result_authority.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    return out
```

| Kind (`AuthorityKind`) | Legal statuses (selected) | Not interchangeable with |
| --- | --- | --- |
| `theorem_proof` | `proved`, `disproved`, `unknown`, `error` | SAT, policy, allow |
| `satisfiability` | `satisfiable`, `unsatisfiable`, … | Theorem proof |
| `evidence_readiness` | `ready`, `not_ready`, … | Authorization allow |
| `policy_approval` | `approved`, `rejected`, … | Execution grant / MCP dispatch |

---

## 10. Policy layer (allowed ≠ proof)

Profile D evaluation is **policy-layer**. A true `allowed` never upgrades
parser output or theorem claims into dispatch rights by itself.

```python
from ipfs_datasets_py.logic import evaluate_execution_policy


def policy_layer_demo() -> Dict[str, Any]:
    allow = evaluate_execution_policy(
        actor="did:example:alice",
        action="compile.legal_ir",
        resource="tutorial:demo",
        evaluated_at="2026-08-03T00:00:00Z",
        policy={
            "clauses": [
                {
                    "clause_type": "permission",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "tutorial:demo",
                }
            ]
        },
    )
    deny = evaluate_execution_policy(
        actor="did:example:alice",
        action="compile.legal_ir",
        resource="tutorial:demo",
        evaluated_at="2026-08-03T00:00:00Z",
        policy={
            "clauses": [
                {
                    "clause_type": "permission",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "tutorial:demo",
                },
                {
                    "clause_type": "prohibition",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "tutorial:demo",
                },
            ]
        },
    )
    # Redact full formal_logic lists in shared logs if they embed private actors
    summary = {
        "allow_decision": allow.get("decision"),
        "allow_allowed": allow.get("allowed"),
        "deny_decision": deny.get("decision"),
        "deny_allowed": deny.get("allowed"),
        "disposition": "policy_layer_not_theorem_proof_not_mcp_dispatch",
        "policy_cids_redacted": True,  # omit CIDs from stdout if logging externally
    }
    print("policy", summary)
    # Persist full witness only under WORK (local temp), not stdout
    (RECEIPTS / "policy_allow.json").write_text(
        json.dumps(allow, indent=2, default=str), encoding="utf-8"
    )
    (RECEIPTS / "policy_deny.json").write_text(
        json.dumps(deny, indent=2, default=str), encoding="utf-8"
    )
    return summary
```

| Result | Means | Does not mean |
| --- | --- | --- |
| `allowed=True` | Policy clauses permit the intent | Tool ran; theorem proved |
| `decision="deny"` | Prohibition / fail-closed | Goal is unsatisfiable |
| `zkp_certificate` when requested | Statement-ready artifact | Production ZKP proof |

---

## 11. End-to-end offline script (runnable)

Selected runnable journey: workspace → capability/health → validate/analyze →
formalization contract note → prover probe → bounded prove → typed authority →
policy allow/deny → cleanup.

```python
"""Logic and proof offline workflow (selected runnable snippet)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from ipfs_datasets_py.core_operations import LogicProcessor
from ipfs_datasets_py.logic import evaluate_execution_policy
from ipfs_datasets_py.logic.external_provers import (
    ProverRouter,
    Z3_AVAILABLE,
    check_prover_availability,
    get_available_provers,
)
from ipfs_datasets_py.logic.formalization import (
    FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION,
    FormalizationCompilerConfig,
)
from ipfs_datasets_py.logic.ir_core import (
    RESULT_AUTHORITY_SCHEMA_VERSION,
    AuthorityKind,
    ResultAuthority,
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="logic_proof_workflow_"))
    receipts = work / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    try:
        lp = LogicProcessor()
        caps = await lp.get_capabilities()
        health = await lp.check_health()
        assert caps.get("success") is True
        assert health.get("success") is True

        formula = "P -> P"
        validation = await lp.validate_formula(formula, logic_system="dcec")
        analysis = await lp.analyze_formula(formula)
        assert validation.get("success") is True
        # valid syntax is not proof — do not promote to AuthorityKind.THEOREM_PROOF

        formalization = {
            "compiler_config_schema": FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION,
            "config_type": FormalizationCompilerConfig.__name__,
            "disposition": "formalization_contract_not_theorem_proof",
        }

        z3_ok = bool(Z3_AVAILABLE) and bool(check_prover_availability("Z3"))
        router = ProverRouter(default_timeout=5.0, enable_cache=False)
        prover_probe = {
            "catalog": get_available_provers(),
            "z3_available": z3_ok,
            "router_live": router.get_available_provers(),
            "timeout_seconds": 5.0,
        }

        prove = await lp.prove_tdfol(
            formula, timeout_ms=5000, include_proof_steps=False
        )
        if prove.get("success") and prove.get("proved"):
            kind = AuthorityKind.THEOREM_PROOF
            method = str(prove.get("method") or "tdfol_prover")
            prove_disp = "operational_proved_claim"
        else:
            kind = AuthorityKind.EVIDENCE_READINESS
            method = "bounded_prove_attempt_receipt"
            prove_disp = "not_proved_or_unknown_not_disproof"

        authority = ResultAuthority(
            kind=kind,
            issuer="logic_proof_workflow",
            method=method,
            scope_digest=sha256_hex(formula.encode("utf-8")),
            evidence_digests=(
                sha256_hex(
                    json.dumps(
                        {
                            "proved": prove.get("proved"),
                            "status": prove.get("status"),
                            "method": prove.get("method"),
                        },
                        sort_keys=True,
                    ).encode("utf-8")
                ),
            ),
            configuration_digest=sha256_hex(b"logic_proof_workflow@1"),
        )
        assert authority.permits(kind) is True
        assert authority.permits(AuthorityKind.SATISFIABILITY) is False

        allow = evaluate_execution_policy(
            actor="did:example:alice",
            action="compile.legal_ir",
            resource="tutorial:demo",
            evaluated_at="2026-08-03T00:00:00Z",
            policy={
                "clauses": [
                    {
                        "clause_type": "permission",
                        "actor": "did:example:alice",
                        "action": "compile.legal_ir",
                        "resource": "tutorial:demo",
                    }
                ]
            },
        )
        deny = evaluate_execution_policy(
            actor="did:example:alice",
            action="compile.legal_ir",
            resource="tutorial:demo",
            evaluated_at="2026-08-03T00:00:00Z",
            policy={
                "clauses": [
                    {
                        "clause_type": "permission",
                        "actor": "did:example:alice",
                        "action": "compile.legal_ir",
                        "resource": "tutorial:demo",
                    },
                    {
                        "clause_type": "prohibition",
                        "actor": "did:example:alice",
                        "action": "compile.legal_ir",
                        "resource": "tutorial:demo",
                    },
                ]
            },
        )
        assert allow.get("allowed") is True
        assert deny.get("allowed") is False

        evidence = {
            "health_status": health.get("status"),
            "validation_valid": validation.get("valid"),
            "analysis_parsed_ok": analysis.get("parsed_ok"),
            "formalization_disposition": formalization["disposition"],
            "z3_available": prover_probe["z3_available"],
            "prove_success": prove.get("success"),
            "prove_proved": prove.get("proved"),
            "prove_status": prove.get("status"),
            "prove_disposition": prove_disp,
            "authority_kind": authority.kind.value,
            "authority_schema": RESULT_AUTHORITY_SCHEMA_VERSION,
            "policy_allow": allow.get("allowed"),
            "policy_deny": deny.get("allowed"),
            "parser_or_model_called_proof": False,
        }
        (receipts / "evidence.json").write_text(
            json.dumps(evidence, indent=2, default=str), encoding="utf-8"
        )
        print("evidence", evidence)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        print("cleanup", "removed_temp_workspace")


if __name__ == "__main__":
    asyncio.run(main())
```

**How to run**

```bash
# Save the §11 script and execute with package on PYTHONPATH / editable install
python /tmp/logic_proof_workflow.py
```

**Expected evidence**

| Field | Expected offline |
| --- | --- |
| `health_status` | `healthy` or `degraded` (never silent) |
| `validation_valid` | `true` for `P -> P` when CEC validator path works |
| `formalization_disposition` | `formalization_contract_not_theorem_proof` |
| `prove_proved` | May be `false` with `status=unknown` — still success of the **tutorial** if disposition is labeled |
| `authority_kind` | `theorem_proof` only if proved; else `evidence_readiness` |
| `policy_allow` / `policy_deny` | `true` / `false` |
| `parser_or_model_called_proof` | `false` |
| Cleanup | Temp dir removed |

---

## 12. Cleanup, redaction, and side effects

### 12.1 Cleanup

| Artifact | Action |
| --- | --- |
| Temp `WORK` / `receipts/` | `shutil.rmtree(work, ignore_errors=True)` |
| In-process `LogicProcessor` / `ProverRouter` | Drop references; process exit clears memory |
| Optional prover process children | Bound by timeout; do not leave long-running solvers |
| Optional HF / model caches | Not used on offline path; user-managed if you opt in |

### 12.2 Redaction

| Data | Guidance |
| --- | --- |
| `proof_steps` | Default **off** in this tutorial; may embed large intermediate formulas |
| Policy `formal_logic` / actor DIDs | Prefer summaries in shared logs; full witness only under temp `WORK` |
| ZKP certificates / keys | Never print secrets; certificate blobs may still be sensitive metadata |
| Environment paths | Avoid logging absolute home paths in published receipts |

### 12.3 Side effects

| Action | Side effect |
| --- | --- |
| `get_capabilities` / `check_health` | Import probes; may be slow first time |
| `validate_formula` / `analyze_formula` | CPU only; may warn if CEC native missing |
| `prove_tdfol` / external provers | Solver CPU; optional process spawn; timeout bounds |
| `evaluate_execution_policy` | Pure evaluation; optional ZKP **statement** fields |
| Writing `RECEIPTS` | Local filesystem under temp dir only |

---

## 13. Unavailable, mock, and success matrix

| Step | Success | Unavailable | Mock / degraded |
| --- | --- | --- | --- |
| Capability probe | `success=True` + logics map | Import failure of façade | `degraded` health with partial modules |
| Validate / analyze | `valid` / structural fields | CEC validator missing → warnings | **Never** proof |
| Formalization contracts | Import + schema version | Package path missing | Contract-only disposition |
| Prover probe | Live router list | Binary missing | Catalog names without live backend |
| `prove_tdfol` | Envelope with status | Parse/module error | `unknown` / not proved |
| `ResultAuthority` | Valid digests + schema | Bad schema version rejected | Wrong kind is a logic bug, not soft success |
| Profile D policy | `allowed` bool + decision | Malformed policy raises | ZKP statement ≠ production proof |

---

## 14. Verification ledger (this tutorial)

| Item | Value |
| --- | --- |
| Owner | tutorials / IPFSDOC-084 |
| Source page | `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` |
| Setup | `pip install -e .` from repo root; Z3 optional |
| Bounded command | Run §11 script; `python -m compileall -q docs/tutorials` |
| Expected evidence | Health/validation envelopes; formalization disposition; prove attempt **labeled**; typed authority non-substitution; policy allow/deny; cleanup |
| Network / native / service | No network required; Z3/CVC5/Lean optional natives |
| Last verified tree | task `IPFSDOC-084` (2026-08-03) |
| Disposition | Offline path **verified** for capability, validation, typed authority, and policy; prove may return unknown without failing the tutorial when labeled |

---

## 15. Next steps

| Goal | Go to |
| --- | --- |
| MCP discovery, denial, local dispatch | [MCP_CLIENT_WORKFLOW.md](MCP_CLIENT_WORKFLOW.md) |
| API map for logic / proof / KG | [KNOWLEDGE_LOGIC_AND_PROOF.md](../api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md) |
| Authority taxonomy | [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md) |
| External prover architecture | [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md) |
| Retrieval / knowledge (facts ≠ proof) | [RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) |

---

## 16. Non-goals

- Calling parser, NL formalization, or model output **proof**.
- Full Lean/Coq interactive development workflows.
- Production ZKP circuit proving or wallet/UCAN consumption.
- Exhaustive IR family matrices (FOL, event calculus, legal IR deep dives).
- Remote MCP HTTP as the primary path (see sibling MCP tutorial).
- Treating policy `allowed` or SAT models as theorem permission.
