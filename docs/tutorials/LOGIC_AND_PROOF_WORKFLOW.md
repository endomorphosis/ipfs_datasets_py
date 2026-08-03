# Logic and proof workflow tutorial

| Field | Value |
| --- | --- |
| Interface | `LogicProofTutorial@1` |
| Task | `IPFSDOC-084` |
| Status | `canonical` |
| Owner | tutorials / logic-proof |
| Audience | developer, agent, security reviewer |
| Last verified | 2026-08-03 |
| Source of truth | `ipfs_datasets_py/logic/` (`ir_core/protocols.py`, `formalization/`, `external_provers/`, `intent_ir/`); `ipfs_datasets_py/core_operations/logic_processor.py`; architecture leaves under `docs/architecture/logic/` |
| Related | [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md), [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md), [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](../architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md), [KNOWLEDGE_LOGIC_AND_PROOF.md](../api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md), [MCP_CLIENT_WORKFLOW.md](MCP_CLIENT_WORKFLOW.md) |

## 1. Purpose

This tutorial walks a **bounded offline-first** path through the governed
logic plane:

1. **Validation** — structural / formula / IR well-formedness.
2. **Formalization** — domain-neutral samples and constraint contracts
   (compile-ready declarations, not proofs).
3. **Prover capability** — discover which external solvers/ITPs are present
   and bound them with timeouts.
4. **Typed result handling** — attach and enforce `AuthorityKind` so SAT,
   monitor, evidence, and policy outcomes never promote to theorem proof or
   execution allow.

It deliberately **does not** treat parser success, model/LLM output, string
similarity, or simulated ZKP as proof. Those are candidates or diagnostics
only.

```text
  text / structured declaration
           │
           ▼
  validate (well-formed?)          ← not proof
           │
           ▼
  formalize (IR / constraints)     ← not proof
           │
           ▼
  capability probe (provers)
           │
           ▼
  bounded prove attempt            ← typed status under AuthorityKind
           │
           ▼
  reject authority substitution    ← proof ≠ allow ≠ parse-ok
```

## 2. Learning objectives

After this tutorial you can:

- Import the logic façade (`LogicProcessor`) and the IR kernel contracts.
- Validate formulas and reject empty/malformed inputs with typed envelopes.
- Build or inspect formalization contracts without claiming theorem authority.
- Probe prover availability without import-time install side effects.
- Construct `ResultAuthority` / reject cross-kind substitution.
- State native prerequisites, timeouts, cleanup, redaction, and side effects.

## 3. Prerequisites, timeouts, cleanup, redaction, side effects

### 3.1 Software prerequisites

| Layer | Requirement | Optional? |
| --- | --- | --- |
| Python package | Installable `ipfs_datasets_py` (this tree) | Required |
| Core façade | `core_operations.LogicProcessor` | Required for §5–§6 |
| IR kernel | `logic.ir_core.protocols` | Required for §8 |
| Formalization | `logic.formalization` | Required for §7 |
| External provers | Z3 / CVC5 / Lean / Coq binaries or Python bindings | **Optional** |
| Neural prover | SymbolicAI / LLM credentials | **Optional**; never theorem authority |
| CEC / ErgoAI trees | May be empty checkouts | **Optional**; capability gap if missing |

Probe before claiming success:

```python
from ipfs_datasets_py.logic.external_provers import (
    get_available_provers,
    check_prover_availability,
)

print(get_available_provers())          # registry of known provers
print(check_prover_availability("z3"))  # True/False for this host
```

Listing a prover name is **not** the same as a successful kernel-checked
proof.

### 3.2 Timeouts (recommended bounds)

| Operation | Suggested bound | Why |
| --- | --- | --- |
| Formula validation / analysis | ≤ 5 s | Local parse; should be near-instant |
| Capability probe | ≤ 2 s per binary | `find_executable` / import check only |
| SMT / ATP prove attempt | 1–30 s (`timeout` / `timeout_ms`) | Hard wall; prefer short tutorial budgets |
| ITP (Lean/Coq) interactive check | 30–120 s | Kernel check only after reconstruction |
| Batch portfolio | per-formula timeout × N | Cap total wall clock |

Pass explicit timeouts into façades:

```python
# LogicProcessor DCEC path (seconds)
# await lp.prove_dcec(goal, axioms=[...], timeout=5)

# LogicProcessor TDFOL path (milliseconds)
# await lp.prove_tdfol(formula, axioms=[...], timeout_ms=5000)

# ProverRouter default
# ProverRouter(default_timeout=5)
```

On timeout, treat the outcome as **non-proof** (`unknown` / error /
timeout), never as `proved`.

### 3.3 Side effects

| Surface | Side effects |
| --- | --- |
| Import `logic.external_provers` | May soft-fail missing bridges; does not install by default |
| `lazy_install_prover` / `ensure_prover_executable` | **May download or install** user-local binaries when env gates allow — **do not** call in CI without policy |
| `ProverRouter.prove` / bridge `prove` | Spawns solver processes; CPU-heavy; writes optional proof cache |
| `LogicProcessor` prove / KB paths | Optional prover invocation; may mutate in-memory KB |
| Formalization / IR kernel types | Pure contracts when used as validation only |
| Simulated ZKP / bridge helpers | May emit **simulated** attestation — label as simulation |

### 3.4 Cleanup

- Prefer ephemeral axioms and in-memory results for tutorials; do not write
  production proof corpora unless that is the explicit goal.
- If you enable proof caches under a temp directory, delete the directory
  after the session.
- Cancel or await outstanding prover processes before process exit (router /
  portfolio helpers own process groups when used correctly).
- Do not leave lazy-install partial downloads if you opted into install
  (operator concern; this tutorial does not install).

### 3.5 Redaction

When logging prove requests or diagnostics:

- Redact API keys, bearer tokens, and wallet secrets from any NL goal text
  or metadata.
- Prefer content digests (`sha256` hex) over full source bodies in shared
  logs.
- Do not paste private legal corpora or credentials into bug reports.
- Solver stdout can contain premise text — store digests in receipts when
  the corpus is sensitive.

### 3.6 Non-goals for this tutorial

- Calling **parser output** or **model draft** a proof.
- Full ITP hammer portfolio operations (see architecture leaf).
- Governed authorization allow / dispatch (see
  [GOVERNED_AUTHORIZATION.md](../architecture/logic/GOVERNED_AUTHORIZATION.md)).
- Production ZKP circuit setup.

## 4. Authority inequalities (read before coding)

These inequalities are binding for every snippet below:

| Claim | Not interchangeable with |
| --- | --- |
| `valid` / parse-ok | `proved` / theorem proof |
| SAT / UNSAT model | Theorem permission under another encoding |
| Formalization artifact / compile success | Kernel-checked proof |
| Optimizer score / LLM confidence | `AuthorityKind.THEOREM_PROOF` |
| Simulated attestation | Production proof |
| Proof alone | Authorization **allow** or tool dispatch |

Wire kinds (`logic.ir_core.protocols.AuthorityKind`):

| Kind | Wire value |
| --- | --- |
| Theorem proof | `theorem_proof` |
| Satisfiability | `satisfiability` |
| Runtime monitor | `runtime_monitor` |
| Evidence readiness | `evidence_readiness` |
| Policy approval | `policy_approval` |

## 5. Step 1 — Health and capability inventory

```python
import asyncio
from ipfs_datasets_py.core_operations import LogicProcessor
from ipfs_datasets_py.logic.external_provers import (
    get_available_provers,
    check_prover_availability,
)

async def inventory() -> dict:
    lp = LogicProcessor()
    health = await lp.check_health()
    caps = await lp.get_capabilities()

    prover_names = get_available_provers()
    prover_host = {
        name: check_prover_availability(name)
        for name in ("z3", "cvc5", "lean", "coq")
    }

    return {
        "health_success": health.get("success"),
        "modules": health.get("modules"),
        "logic_families": list((caps.get("logics") or {}).keys()),
        "prover_registry": prover_names,
        "prover_host_available": prover_host,
    }

if __name__ == "__main__":
    print(asyncio.run(inventory()))
```

**How to read results**

- `health["modules"][name] == "ok"` means the Python module imported, not that
  every native binary is production-ready.
- `caps["logics"][family]["available"]` is a façade feature flag.
- `check_prover_availability` is a host probe. False → treat prove paths as
  **unavailable**, not as disproved.

## 6. Step 2 — Validation (well-formedness only)

Validation answers “is this formula/structure acceptable under the declared
system?” It does **not** answer “is this theorem true?”

```python
import asyncio
from ipfs_datasets_py.core_operations import LogicProcessor

async def validate_examples() -> None:
    lp = LogicProcessor()

    good = await lp.validate_formula("forall x. P(x)", logic_system="fol")
    empty = await lp.validate_formula("", logic_system="fol")
    analysis = await lp.analyze_formula("forall x. P(x) -> Q(x)")

    assert good.get("success") is True and good.get("valid") is True
    assert empty.get("valid") is False
    assert "errors" in empty

    # typed handling: never map valid=True → proved
    if good.get("valid"):
        status_label = "well_formed_candidate"
    else:
        status_label = "invalid_input"

    print(
        {
            "good": good,
            "empty": empty,
            "analysis_keys": sorted(analysis.keys()),
            "authority_note": status_label,
        }
    )

if __name__ == "__main__":
    asyncio.run(validate_examples())
```

**Expected shapes**

| Case | Typical envelope |
| --- | --- |
| Valid formula | `success=True`, `valid=True`, `errors=[]` |
| Empty / bad | `success=False` or `valid=False`, non-empty `errors` |
| Analysis | Structural metrics (`depth`, `size`, `operators`, `parsed_ok`) |

`parsed_ok` / `valid` are **evidence_readiness-adjacent diagnostics**, not
`theorem_proof`.

## 7. Step 3 — Formalization without proof claims

Formalization lowers a grounded declaration into constraint-ready structure.
A successful compile or sample validation yields a **declaration artifact**,
not a proof receipt.

```python
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    reject_result_authority_substitution,
    forbid_silent_logic_concatenation,
)
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind

# 1) Refuse silent multi-family formula concatenation on one statement body.
try:
    forbid_silent_logic_concatenation(
        ["fol", "deontic", "smt"],
        context="tutorial-statement",
    )
except Exception as exc:
    print("concatenation_guard:", type(exc).__name__, exc)

# 2) Refuse using SAT-shaped authority as theorem authority after formalization.
try:
    reject_result_authority_substitution(
        claimed=AuthorityKind.SATISFIABILITY,
        required=AuthorityKind.THEOREM_PROOF,
    )
except Exception as exc:
    print("authority_guard:", type(exc).__name__, str(exc))
```

Domain-neutral sample contracts live in
`ipfs_datasets_py.logic.formalization.samples.FormalizationSample`. They
require:

- Stable identifiers (`sample_id`, `domain`, `declaration_id`).
- A declaration digest and provenance grounding.
- Immutable JSON-representable `payload`.

Adapters (Legal IR, Security IR, Intent IR) own corpus-specific validation.
This tutorial only requires that you treat formalization success as
**structural readiness**, then run a separate prove attempt with an explicit
`AuthorityKind`.

Intent IR structural validation (document must already be Intent-shaped):

```python
# from ipfs_datasets_py.logic.intent_ir import validate_intent_ir
# document = validate_intent_ir(mapping_or_document)
# validate_intent_ir raises / returns a typed IntentIRDocument — still not proof.
```

## 8. Step 4 — Prover capability and bounded attempt

### 8.1 Capability-first routing

```python
from ipfs_datasets_py.logic.external_provers import (
    ProverRouter,
    check_prover_availability,
    get_available_provers,
)

def probe_and_build_router(timeout_s: int = 5) -> ProverRouter | None:
    print("registry:", get_available_provers())
    if not check_prover_availability("z3"):
        print("z3 unavailable on this host — skip SMT prove path")
        return None
    # Prefer explicit enables; keep timeout small for tutorials.
    return ProverRouter(
        enable_z3=True,
        enable_cvc5=check_prover_availability("cvc5"),
        enable_lean=False,   # ITP paths are heavier; enable when kernel is installed
        enable_coq=False,
        default_timeout=timeout_s,
        enable_cache=False,  # avoid leftover cache artifacts in tutorials
    )

router = probe_and_build_router()
if router is not None:
    print("router_available:", router.get_available_provers())
```

### 8.2 Interpreting prove outcomes (typed)

When you call a prove method, map the raw façade dict into an explicit
authority kind **before** any downstream policy:

```python
from dataclasses import dataclass
from typing import Any, Mapping
from ipfs_datasets_py.logic.ir_core.protocols import (
    AuthorityKind,
    ResultAuthority,
    AuthorityMismatchError,
)

DIGEST_PLACEHOLDER = "a" * 64  # replace with request/scope digest in production


@dataclass(frozen=True)
class TypedProveView:
    authority_kind: AuthorityKind
    status: str
    proved_claim: bool
    raw: Mapping[str, Any]


def type_smt_facade_result(raw: Mapping[str, Any]) -> TypedProveView:
    """Map a LogicProcessor / bridge dict into a SAT-oriented view.

    SMT façades answer satisfiability-style questions unless a separate
    ITP kernel reconstruction marks theorem_proof. Do not upgrade here.
    """
    if raw.get("error") or raw.get("success") is False:
        status = "error"
        proved_claim = False
    elif raw.get("proved") is True:
        # Still SAT-portfolio or façade "proved" — NOT automatic theorem_proof.
        status = "proved_candidate"
        proved_claim = True
    else:
        status = "not_proved"
        proved_claim = False

    return TypedProveView(
        authority_kind=AuthorityKind.SATISFIABILITY,
        status=status,
        proved_claim=proved_claim,
        raw=raw,
    )


def attach_authority(view: TypedProveView) -> ResultAuthority:
    return ResultAuthority(
        kind=view.authority_kind,
        issuer="tutorial-logic-workflow",
        method="facade-typed-mapping",
        scope_digest=DIGEST_PLACEHOLDER,
    )


def refuse_parser_as_proof(parsed_ok: bool) -> None:
    """Explicit non-substitution: parser/model success is not proof."""
    if parsed_ok:
        # Well-formed input only. Require a separate prove path + authority.
        return
    raise ValueError("input not well-formed; refuse prove attempt")


def as_theorem_or_raise(authority: ResultAuthority) -> None:
    try:
        authority.require(AuthorityKind.THEOREM_PROOF)
    except AuthorityMismatchError as exc:
        # Expected for SMT-typed views.
        raise RuntimeError(
            "refusing to treat non-theorem authority as theorem_proof"
        ) from exc
```

**Critical tutorial rule:** if a model or parser returns text that *looks*
like a proof script, keep it as a **candidate artifact** under evidence or
SAT authority until an ITP kernel check issues `theorem_proof`.

```python
def model_output_is_not_proof(model_text: str) -> dict:
    return {
        "kind": AuthorityKind.EVIDENCE_READINESS.value,
        "status": "ready" if model_text.strip() else "not_ready",
        "note": "LLM/parser draft only; no theorem_proof authority",
        "bytes": len(model_text.encode("utf-8")),
    }
```

### 8.3 Optional façade prove (only if provers available)

```python
import asyncio
from ipfs_datasets_py.core_operations import LogicProcessor

async def bounded_prove_if_available() -> dict:
    lp = LogicProcessor()
    # Short timeout; treat any error/unavailable as non-proof.
    raw = await lp.prove_dcec(
        goal="P(a)",
        axioms=["forall x. P(x)"],
        timeout=2,
    )
    view = type_smt_facade_result(raw)
    authority = attach_authority(view)
    return {
        "typed_status": view.status,
        "authority": authority.to_dict(),
        "permits_theorem": authority.permits(AuthorityKind.THEOREM_PROOF),
        "raw_success": raw.get("success"),
        "raw_proved": raw.get("proved"),
        "raw_error": raw.get("error"),
    }

# print(asyncio.run(bounded_prove_if_available()))
```

If the host returns `success=False` with an error string (missing strategy
enum, missing binary, timeout), record **unavailable** or **error**, not
`disproved`.

## 9. Step 5 — Typed result handling checklist

Use this checklist on every trust-bearing path:

1. **Declare the query kind** you intended (theorem vs SAT vs monitor vs
   evidence vs policy).
2. **Validate** input structure; on failure stop (invalid ≠ disproved).
3. **Formalize** only with domain adapters that preserve identity/provenance.
4. **Probe** prover capability; skip or degrade when unavailable.
5. **Run** with an explicit timeout and capture usage/diagnostics.
6. **Attach** `ResultAuthority` whose `kind` matches the query.
7. **Reject** substitution via `ResultAuthority.require` or
   `reject_result_authority_substitution`.
8. **Never** promote:
   - `valid` / `parsed_ok` → `proved`
   - SAT model → theorem proof
   - proof → authorization allow

```python
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    reject_result_authority_substitution,
)
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind

def gate_for_consumers(claimed_kind: AuthorityKind, needed: AuthorityKind) -> str:
    try:
        reject_result_authority_substitution(claimed=claimed_kind, required=needed)
        return "authority_match"
    except Exception as exc:
        return f"denied:{type(exc).__name__}:{exc}"

print(gate_for_consumers(AuthorityKind.SATISFIABILITY, AuthorityKind.THEOREM_PROOF))
# denied:AuthorityMismatchError:...
```

## 10. End-to-end offline script

Copy into a temporary file and run with the package on `PYTHONPATH`:

```python
"""Bounded logic/proof journey — validation → formalization guards → probe → type."""

from __future__ import annotations

import asyncio
from typing import Any

from ipfs_datasets_py.core_operations import LogicProcessor
from ipfs_datasets_py.logic.external_provers import (
    check_prover_availability,
    get_available_provers,
)
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    reject_result_authority_substitution,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AuthorityKind,
    AuthorityMismatchError,
    ResultAuthority,
)


async def main() -> dict[str, Any]:
    lp = LogicProcessor()
    health = await lp.check_health()
    validation = await lp.validate_formula("P(x)", logic_system="fol")

    # Parser/model path must not become proof:
    parse_ok = bool(validation.get("valid"))
    model_draft = "sorry  -- LLM placeholder"
    draft_view = {
        "authority_kind": AuthorityKind.EVIDENCE_READINESS.value,
        "ready": bool(model_draft.strip()) and parse_ok,
        "note": "draft only",
    }

    provers = {
        "registry": get_available_provers(),
        "z3": check_prover_availability("z3"),
    }

    sat_authority = ResultAuthority(
        kind=AuthorityKind.SATISFIABILITY,
        issuer="tutorial-e2e",
        method="capability-and-validation-only",
        scope_digest="b" * 64,
    )

    substitution = "allowed"
    try:
        reject_result_authority_substitution(
            claimed=sat_authority,
            required=AuthorityKind.THEOREM_PROOF,
        )
    except AuthorityMismatchError as exc:
        substitution = f"rejected:{exc}"

    return {
        "health_ok": health.get("success"),
        "validation_valid": validation.get("valid"),
        "draft_view": draft_view,
        "provers": provers,
        "sat_authority": sat_authority.to_dict(),
        "theorem_substitution": substitution,
        "side_effects": "none (no prove/install in this script)",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(asyncio.run(main()), indent=2, default=str))
```

## 11. Unavailable and degraded outcomes

| Symptom | Treat as | Do not claim |
| --- | --- | --- |
| `check_prover_availability` False | unavailable | disproved |
| ImportError on bridge | unavailable / optional missing | domain absent |
| Prove `timeout` | unknown / error | proved |
| `valid=False` | invalid input | theorem false |
| Simulated ZKP flag | simulation | production attestation |
| Empty CEC/ErgoAI checkout | capability gap | full CEC support |

Fail closed: prefer explicit error envelopes over silent success.

## 12. Verification commands

```bash
# Tutorials present and non-empty (task gate)
test -s docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md

# Syntax-check this docs tree (task gate includes compileall on tutorials)
python -m compileall -q docs/tutorials

# Optional live probes (environment-dependent)
python -c "from ipfs_datasets_py.logic.external_provers import get_available_provers; print(get_available_provers())"
python -c "from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind; print([k.value for k in AuthorityKind])"
```

## 13. Next steps

- Architecture: [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md),
  [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md).
- API map: [KNOWLEDGE_LOGIC_AND_PROOF.md](../api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md).
- MCP transport of logic tools: [MCP_CLIENT_WORKFLOW.md](MCP_CLIENT_WORKFLOW.md).
- Authorization compose (proof still ≠ allow):
  [GOVERNED_AUTHORIZATION.md](../architecture/logic/GOVERNED_AUTHORIZATION.md).
