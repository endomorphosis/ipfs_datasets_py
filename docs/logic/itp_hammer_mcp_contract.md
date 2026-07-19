# ITP Hammer Governed MCP/CLI Contract

Status: Implemented (HAMMER-013)
Date: 2026-07-19
Module: `ipfs_datasets_py.mcp_server.tools.logic_hammer`
CLI: `scripts/cli/logic_cli.py` (`hammer-*` subcommands)
Tests: `tests/integration/logic/hammers/test_mcp_hammer_tools.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract every operation below either reads or enforces, never
bypasses), `docs/logic/itp_hammer_premise_selection.md` (HAMMER-004),
`docs/logic/itp_hammer_provenance.md` (HAMMER-009), the HAMMER-008 solver
portfolio in `ipfs_datasets_py.logic.hammers.portfolio`/`.policy`, the
HAMMER-010 reconstruction pipeline in `ipfs_datasets_py.logic.hammers.
reconstruction`, and `docs/logic/itp_hammer_receipts.md` (HAMMER-012).

## 1. Purpose

HAMMER-001 through HAMMER-012 implement a deterministic, auditable,
kernel-checked hammer pipeline as a set of importable Python modules. None
of them is, by itself, reachable from an MCP client or a shell — a caller
would otherwise need to import seven different modules, understand their
internal object graphs, and re-implement the taskboard's own governance
rules (an explicit policy, confirmation before spawning a native process, a
correlation id to thread through a multi-step run, structured handling of a
missing toolchain) by hand.

> Provide inspect, select-premises, translate, run-candidate, reconstruct,
> retrieve-receipt, and capability-status operations. Govern execution with
> explicit policy, confirmation for native process launch, correlation IDs,
> structured unavailable states, and no claim that a candidate proof is
> verified before kernel confirmation.

`ipfs_datasets_py.mcp_server.tools.logic_hammer` is that governed interface
layer. It is intentionally a **thin wrapper**: every operation below calls
straight into the already-implemented HAMMER-001..HAMMER-012 modules and
never re-implements premise selection, translation, solver execution,
reconstruction, or receipt persistence. `scripts/cli/logic_cli.py` exposes
the identical operations as `hammer-*` subcommands for shell/CI use, reading
JSON payloads from files or inline strings and calling the same async
functions via `asyncio.run`.

## 2. Governance model

Every operation in this module shares four governance properties:

### 2.1 Explicit policy

Every operation that could otherwise silently pick a timeout, resource
budget, or solver allow-list instead accepts a serialized
`ipfs_datasets_py.logic.hammers.models.HammerPolicy` (and, for
`run-candidate`, a serialized `ipfs_datasets_py.logic.hammers.policy.
PortfolioPolicy`) payload. When omitted, the conservative baseline
(`HammerPolicy()`: no solvers allowlisted, no learned/LLM opt-ins, a
30-second default timeout) is used — nothing here hard-codes a *looser*
default than the policy record's own field defaults, and every policy
payload is validated by the record's own `.validate()`/`PolicyError` checks
before anything executes.

### 2.2 Confirmation for native process launch

Three operations launch a real external process:

| Operation        | What it launches                                             |
|-------------------|---------------------------------------------------------------|
| `inspect`         | A native `lean`/`coqtop`/`isabelle` process (HAMMER-006 goal capture) |
| `run-candidate`   | One or more external `z3`/`cvc5`/`vampire`/`e` solver processes (HAMMER-008) |
| `reconstruct`     | A native `lean`/`coqtop`/`isabelle` process (goal capture *and* kernel check, HAMMER-010) |

Each of these three functions accepts `confirm_native_execution: bool =
False`. Unless the caller explicitly passes `confirm_native_execution=True`
(CLI: `--confirm`), the function returns a structured `confirmation_required`
response (see §3) **without launching anything** — no subprocess is
spawned, no temp file is written, no capability probe beyond an already
performed executable-discovery check runs.

`select-premises`, `translate`, `retrieve-receipt`, and `persist-receipt`
are pure, in-process computation (or plain local-disk/IPFS I/O) and have no
`confirm_native_execution` parameter at all — there is nothing to confirm.

`capability-status` is a deliberate, narrow exception: like
`scripts/ops/logic/probe_itp_hammer_environment.py` (HAMMER-002), it only
ever performs executable discovery (`shutil.which`) and, unless
`probe_versions=False` is passed, a *bounded* (5 second) `--version`-style
metadata probe against an executable that discovery already found — never a
goal capture, a proof search, or a kernel check. This mirrors HAMMER-002's
own "no solver invocation by default" design and therefore is not gated
behind `confirm_native_execution`.

### 2.3 Correlation IDs

Every response (see the envelope in §3) carries a `correlation_id`: the
caller-supplied value if one was passed (and non-blank), otherwise a freshly
generated `hammer-<uuid4 hex>` string. A caller can pass the same
`correlation_id` into `select-premises`, `translate`, `run-candidate`,
`reconstruct`, and `retrieve-receipt` to thread one identifier through an
entire multi-step run for logging/tracing/audit correlation.

### 2.4 Structured unavailable states

No operation in this module ever raises an uncaught exception across its
public boundary, and no capability gap or denial is ever silently
substituted with a default. Every response's `status` field is one of:

| `status`                 | Meaning                                                                 |
|--------------------------|---------------------------------------------------------------------------|
| `ok`                     | The operation ran to completion.                                       |
| `unavailable`            | A required ITP toolchain or solver executable is not present; `capability` carries structured evidence (mirrors `ipfs_datasets_py.logic.hammers.frontends.base.CapabilityEvidence`). Nothing was executed. |
| `policy_denied`          | The supplied (or default) policy rejected the request (e.g. an unknown solver name, a `top_k`/timeout exceeding a policy bound) before anything executed. |
| `confirmation_required`  | The operation would launch a native process but `confirm_native_execution=True` was not passed. Nothing was executed. |
| `unsupported_translation`| `translate` could not lower the construct (a dependent/higher-order/opaque construct fails closed per HAMMER-007); the `TranslationRecord` is still returned for inspection. |
| `not_found`              | `retrieve-receipt` was asked for a receipt id that does not exist in the configured store. |
| `error`                  | A caller error (malformed payload, unknown enum value, ...) or an underlying capture/kernel error distinct from a capability gap. |

## 3. Response envelope

Every operation returns exactly this shape, regardless of outcome:

```jsonc
{
  "success": true,            // false for any non-"ok" status
  "operation": "translate",   // the operation name, e.g. "inspect", "select-premises", ...
  "correlation_id": "hammer-3f9c...",
  "status": "ok",              // see the table in §2.4
  "data": { ... } | null,      // operation-specific payload; null on failure paths
  "error": "..." | null,       // human-readable error/denial/unavailable reason
  "capability": { ... } | null,// CapabilityEvidence.to_dict(), present for "unavailable"
  "notes": ["..."]             // free-form, non-authoritative diagnostic notes
}
```

## 4. Operations

All operations are `async def` functions in
`ipfs_datasets_py.mcp_server.tools.logic_hammer` and are also exposed as
plain OOP wrapper classes (`HammerInspectTool`, `HammerSelectPremisesTool`,
`HammerTranslateTool`, `HammerRunCandidateTool`, `HammerReconstructTool`,
`HammerRetrieveReceiptTool`, `HammerPersistReceiptTool`,
`HammerCapabilityStatusTool`), each with `name`/`category`/`tags` and an
`async execute(params=None, **kwargs)` method, matching the existing
`ipfs_datasets_py.mcp_server.tools.logic_tools` convention.

### 4.1 `hammer_inspect` (CLI: `hammer-inspect`)

Capture a genuine native `GoalSnapshot` for one incomplete theorem
(HAMMER-006).

| Argument | Type | Notes |
|---|---|---|
| `itp` | `str` | `"lean"` \| `"coq"` \| `"isabelle"` |
| `theorem_id` | `str` | Stable identifier for the declaration |
| `native_source` | `str` | Native source containing exactly one incomplete-proof marker (`sorry`/`admit.`/...) |
| `timeout` | `float?` | Bounded wall-clock override |
| `confirm_native_execution` | `bool` | Must be `True` to actually invoke the frontend |
| `correlation_id` | `str?` | Optional caller-supplied id |

`data.goal_snapshot` is a `GoalSnapshot.to_dict()`. Returns `unavailable` if
the ITP executable is not found, `confirmation_required` if not confirmed,
and `error` if the native invocation fails or its output cannot be parsed
into a genuine goal (e.g. no `sorry` marker present — this frontend never
fabricates a goal from plain text).

### 4.2 `hammer_select_premises` (CLI: `hammer-select-premises`)

Deterministically rank premises from a content-addressed corpus manifest
(HAMMER-003/HAMMER-004). Never launches a native process.

| Argument | Type | Notes |
|---|---|---|
| `goal_statement` | `str` | Raw goal text |
| `corpus_manifest` | `dict?` | `CorpusManifest.to_dict()` output |
| `corpus_manifest_path` | `str?` | Path to a manifest written by `CorpusManifest.save`; mutually exclusive with `corpus_manifest` |
| `theorem_id` | `str?` | For self-exclusion if the goal is itself a corpus theorem |
| `imports` | `list[str]?` | Goal's module/theory dependencies |
| `top_k` | `int` | Selection cutoff; must not exceed `policy.max_premises` |
| `policy` | `dict?` | `HammerPolicy.to_dict()`-shaped payload |
| `correlation_id` | `str?` | |

`data.selection` is a `PremiseSelectionResult.to_dict()`; `data.
corpus_revision` is the manifest's content-addressed revision. Returns
`policy_denied` if `top_k` exceeds `policy.max_premises`.

### 4.3 `hammer_translate` (CLI: `hammer-translate`)

Lower one goal/premise construct to TPTP or SMT-LIB (HAMMER-007). Never
launches a native process.

| Argument | Type | Notes |
|---|---|---|
| `request_id` | `str` | Stamped onto the produced `TranslationRecord` |
| `source_construct` | `str` | Identifier of the construct being translated |
| `term` | `dict` | A JSON term-AST node (see §5) |
| `target` | `str` | `"tptp"` \| `"smtlib"` |
| `monomorphization` | `dict[str, str]?` | Polymorphic type-variable name -> concrete sort name |
| `correlation_id` | `str?` | |

`data.translation` is a `TranslationRecord.to_dict()`; `data.
translation_map` is the accumulated `TranslationMap.to_dict()`. A dependent,
higher-order, or opaque construct is reported with `status =
"unsupported_translation"` and `success = False` — it is never silently
dropped or coerced into a supported-looking result.

### 4.4 `hammer_run_candidate` (CLI: `hammer-run-candidate`)

Execute a policy-controlled ATP/SMT solver portfolio and normalize its raw
output into untrusted evidence (HAMMER-008/HAMMER-009).

| Argument | Type | Notes |
|---|---|---|
| `request` | `dict` | `HammerRequest.to_dict()` |
| `attempts` | `list[dict]` | `[{"translation": <TranslationRecord dict>, "solver_name": <str>}, ...]` |
| `portfolio_policy` | `dict?` | `PortfolioPolicy.to_dict()`; defaults to wrapping `request.policy` |
| `premise_ids` | `list[str]?` | In-scope premise ids, cross-referenced against a parsed unsat core |
| `translation_map` | `dict?` | `TranslationMap.to_dict()` |
| `confirm_native_execution` | `bool` | Must be `True` to actually run the portfolio |
| `correlation_id` | `str?` | |

`data.run_result` is a `PortfolioRunResult.to_dict()`; `data.
normalized_evidence` maps `attempt_id -> NormalizedEvidence.to_dict()`;
`data.proof_candidate` is a `ProofCandidateRecord.to_dict()` if any attempt
produced one; `data.recommended_status` is **one of** `"candidate"` /
`"counterexample"` / `"unknown"` / `"timeout"` / `"unavailable"` —
**this operation can never report `"verified"`**. Only
`hammer_reconstruct` may ever report that, and only after an independent
kernel check.

### 4.5 `hammer_reconstruct` (CLI: `hammer-reconstruct`)

Reconstruct a native tactic/proof term from candidate evidence and
independently kernel-check it (HAMMER-010) — **the only operation in this
module whose response may report `"verified"`**.

| Argument | Type | Notes |
|---|---|---|
| `request` | `dict` | `HammerRequest.to_dict()` |
| `candidate` | `dict` | `ProofCandidateRecord.to_dict()` — the *untrusted* candidate |
| `itp` | `str` | Must match `request["itp"]` |
| `theorem_id` | `str` | |
| `native_source` | `str` | Native source with exactly one incomplete-proof marker; used both for goal capture and as the reconstruction substitution target |
| `environment_lock` | `dict?` | `EnvironmentLockRecord.to_dict()` to reuse; a fresh lock is captured if omitted |
| `timeout` | `float?` | |
| `confirm_native_execution` | `bool` | Must be `True` to invoke the frontend/kernel |
| `correlation_id` | `str?` | |

`data.reconstruction` is a `ReconstructionRecord.to_dict()`; `data.
reconstruction_evidence` is a `ReconstructionEvidence.to_dict()`; `data.
environment_lock` is an `EnvironmentLockRecord.to_dict()`; `data.status` is
`"verified"` **if and only if** `data.reconstruction.kernel_accepted` is
`true` — a value set exclusively from a real kernel subprocess exit
status/output inside `ipfs_datasets_py.logic.hammers.reconstruction`, never
assumed here. A false theorem statement or a corrupted candidate causes
every native automation alternative to fail and the real kernel to reject
the reconstruction; this operation reports `data.status = "candidate"` in
that case, never `"verified"` (see the adversarial test
`test_false_theorem_is_never_verified_despite_real_kernel_invocation` in
the test suite).

### 4.6 `hammer_retrieve_receipt` (CLI: `hammer-retrieve-receipt`)

Fetch a previously persisted, replayable `HammerReceipt` (HAMMER-012). Never
launches a native process.

| Argument | Type | Notes |
|---|---|---|
| `receipt_id` | `str` | The receipt's content-addressed id |
| `publishable` | `bool` | Fetch the redacted, publishable view instead of the full receipt |
| `store_root` | `str?` | Override of the `ReceiptStore` root directory |
| `correlation_id` | `str?` | |

`data.receipt` is either a full `HammerReceipt.to_dict()` (with `data.
is_verified` alongside it) or the redacted publishable payload, depending on
`publishable`. Returns `not_found` if the id is not known to the store.

### 4.7 `hammer_capability_status` (CLI: `hammer-capability-status`)

Report structured, no-proof-search capability evidence for every ITP
frontend/reconstructor and allowlisted solver family (HAMMER-002/
HAMMER-006/HAMMER-010). Never gated behind `confirm_native_execution` (see
§2.2).

| Argument | Type | Notes |
|---|---|---|
| `itps` | `list[str]?` | Subset of `["lean", "coq", "isabelle"]`; defaults to all |
| `solvers` | `list[str]?` | Subset of `known_solver_names()`; defaults to all |
| `probe_versions` | `bool` | Whether to run the bounded `--version` probe per discovered executable |
| `frontend_timeout` | `float?` | |
| `correlation_id` | `str?` | |

`data.itps` maps each ITP name to `{"frontend": CapabilityEvidence.to_dict(),
"reconstruction": CapabilityEvidence.to_dict()}`. `data.solvers` maps each
solver family name to `{"display_name", "target", "candidate_executables",
"available", "path", "version", "version_probe_error"}`. `data.
any_capability_available` is `true` if any reported ITP frontend or solver
is available.

### 4.8 `hammer_persist_receipt` (utility, CLI: `hammer-persist-receipt`)

Not one of the seven named governed operations, but exposed as a supporting
utility (mirroring `ReceiptStore.put`/`persist_hammer_receipt`) so a
caller/test can close the loop from a hammer run's assembled `HammerReceipt`
to a retrievable id via `hammer_retrieve_receipt`. Accepts `receipt`
(`HammerReceipt.to_dict()`), `publish: bool`, `store_root: str?`, and
`correlation_id: str?`; returns `data.receipt_id` and `data.persist_result`
(a `PersistResult.to_dict()`).

## 5. Term AST JSON schema (for `translate`)

The HAMMER-007 translation pipeline (`ipfs_datasets_py.logic.hammers.
translation`) operates on a typed term AST
(`ipfs_datasets_py.logic.hammers.translation.Term`/`TypeRef`), not on raw
goal-statement text — that typed structure is exactly what lets it
distinguish a genuinely first-order construct from a dependent/
higher-order/opaque one it must fail closed on. `hammer_translate` accepts
that AST as a plain, JSON-serializable `{"kind": ..., ...}` node per
`Term`/`TypeRef` variant, so MCP/CLI callers never need to import the
translation module's dataclasses directly.

Type nodes (`TypeRef`):

| `kind` | Fields | Maps to |
|---|---|---|
| `"sort"` | `name: str` | `SortRef(name)` |
| `"type_var"` | `name: str` | `TypeVarRef(name)` |
| `"function"` | `params: [TypeRef]`, `result: TypeRef` | `FunctionTypeRef(params, result)` |
| `"dependent"` | `description: str` | `DependentTypeRef(description)` -- always fails closed |

Term nodes (`Term`):

| `kind` | Fields | Maps to |
|---|---|---|
| `"var"` | `name: str`, `type: TypeRef` | `Var(name, type)` |
| `"const"` | `name: str`, `type: TypeRef`, `opaque: bool = False`, `opaque_reason: str?` | `Const(...)` |
| `"app"` | `fn: Term`, `args: [Term]` | `App(fn, args)` |
| `"lambda"` | `params: [{"name": str, "type": TypeRef}]`, `body: Term` | `Lambda(params, body)` |
| `"forall"` | `var: str`, `var_type: TypeRef`, `body: Term` | `Forall(var, var_type, body)` |
| `"exists"` | `var: str`, `var_type: TypeRef`, `body: Term` | `Exists(var, var_type, body)` |
| `"not"` | `term: Term` | `Not(term)` |
| `"and"` / `"or"` / `"implies"` / `"iff"` / `"eq"` | `left: Term`, `right: Term` | `And`/`Or`/`Implies`/`Iff`/`Eq` |
| `"bool"` | `value: bool` | `BoolLit(value)` |
| `"opaque"` | `reason: str`, `type: TypeRef?` | `Opaque(reason, type)` -- always fails closed |

Example -- `forall x. p(x) => p(x)`:

```json
{
  "kind": "forall", "var": "x", "var_type": {"kind": "sort", "name": "nat"},
  "body": {
    "kind": "implies",
    "left": {"kind": "app", "fn": {"kind": "const", "name": "p", "type": {"kind": "function", "params": [{"kind": "sort", "name": "nat"}], "result": {"kind": "sort", "name": "$prop"}}}, "args": [{"kind": "var", "name": "x", "type": {"kind": "sort", "name": "nat"}}]},
    "right": {"kind": "app", "fn": {"kind": "const", "name": "p", "type": {"kind": "function", "params": [{"kind": "sort", "name": "nat"}], "result": {"kind": "sort", "name": "$prop"}}}, "args": [{"kind": "var", "name": "x", "type": {"kind": "sort", "name": "nat"}}]}
  }
}
```

## 6. Worked example: a full inspect -> ... -> reconstruct flow

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.logic_hammer import (
    hammer_inspect, hammer_translate, hammer_reconstruct,
)

correlation_id = "trace-42"
source = "theorem demo : 1 = 1 := by sorry"

async def main():
    inspected = await hammer_inspect(
        itp="lean", theorem_id="demo", native_source=source,
        confirm_native_execution=True, correlation_id=correlation_id,
    )
    assert inspected["status"] == "ok"

    # ... select-premises / translate / run-candidate the goal as needed ...

    reconstructed = await hammer_reconstruct(
        request={
            "request_id": "req-demo", "itp": "lean", "theorem_id": "demo",
            "goal_statement": inspected["data"]["goal_snapshot"]["goal_text"],
            "corpus_revision": "sha256:...", "policy": {"allowed_solvers": []},
        },
        candidate={
            "candidate_id": "req-demo:candidate", "request_id": "req-demo",
            "solver_attempt_id": "native-automation-fallback", "premise_ids": [],
        },
        itp="lean", theorem_id="demo", native_source=source,
        confirm_native_execution=True, correlation_id=correlation_id,
    )
    assert reconstructed["data"]["status"] == "verified"
    assert reconstructed["data"]["reconstruction"]["kernel_accepted"] is True

asyncio.run(main())
```

Equivalent CLI flow:

```bash
PYTHONPATH=. python scripts/cli/logic_cli.py hammer-inspect \
  --itp lean --theorem-id demo --native-source "theorem demo : 1 = 1 := by sorry" \
  --confirm --correlation-id trace-42

PYTHONPATH=. python scripts/cli/logic_cli.py hammer-reconstruct \
  --request-file request.json --candidate-file candidate.json \
  --itp lean --theorem-id demo \
  --native-source "theorem demo : 1 = 1 := by sorry" \
  --confirm --correlation-id trace-42
```

## 7. Testing

`tests/integration/logic/hammers/test_mcp_hammer_tools.py` covers, for every
operation: the shared envelope shape; confirmation gating (where
applicable); structured `unavailable` responses (using whichever of
`lean`/`coq`/`isabelle`/`vampire`/`cvc5` happens to be absent on the test
host, gated with `pytest.mark.skipif`, mirroring the existing HAMMER-006/
HAMMER-008/HAMMER-010 integration suites); policy validation/denial;
translate's fail-closed behavior for a dependent type; a real, genuine
`lean` kernel check that reaches `"verified"`; an adversarial false-theorem
case proving that a real kernel rejection is never silently upgraded to
`"verified"`; a real `cvc5` solver invocation whose `run-candidate` response
never contains a `"verified"` claim; and a full persist -> retrieve ->
retrieve-publishable receipt round trip. Run with:

```bash
PYTHONPATH=. python -m pytest tests/integration/logic/hammers/test_mcp_hammer_tools.py -q
```
