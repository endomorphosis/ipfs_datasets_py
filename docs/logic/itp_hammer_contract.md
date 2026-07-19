# ITP Hammer Trust Contract and Result Schema

Status: Implemented (HAMMER-001)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.models`
Tests: `tests/unit_tests/logic/hammers/test_models.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of).

## 1. Purpose

This document is the narrative specification for the versioned request,
premise, translation, solver-attempt, proof-candidate, reconstruction,
environment-lock, and final-result records that make up the ITP hammer
pipeline's trust contract. It exists so that every later taskboard item
(HAMMER-002 and beyond) has a single, stable contract to implement against,
and so that anyone consuming a `HammerResult` — a human reviewer, a CI gate,
or another tool — can determine exactly what is and is not being claimed
without reading the pipeline's implementation.

The pipeline's job is to take a goal from an Interactive Theorem Prover
(ITP) — Lean, Coq/Rocq, or Isabelle/HOL — select relevant premises, translate
the goal to TPTP or SMT-LIB, run a bounded external Automated Theorem
Prover/SMT solver portfolio (Vampire, E, Z3, CVC5, ...), and, if a solver
finds a proof, reconstruct and re-check that proof inside the *originating*
ITP's trusted kernel. Every stage before that final kernel check is
untrusted. This document defines the exact boundary between "a solver said
so" and "a kernel checked it," and encodes that boundary as software
invariants, not just prose.

## 2. Trust boundary (the single most important rule)

> A solver `sat`, `unsat`, or `proved` response is an untrusted candidate,
> never a verified theorem. A result may be marked `verified` only after the
> target ITP kernel accepts the reconstructed proof under a pinned
> environment.

Concretely:

- `SolverAttemptRecord.verdict` (a `SolverVerdict` of `sat`, `unsat`,
  `proved`, `disproved`, `unknown`, `timeout`, or `error`) is **always**
  untrusted. It only describes what the external solver process claimed.
- A solver verdict of `proved`/`unsat` can only ever produce a
  `ProofCandidateRecord`. That record type deliberately has **no**
  "verified" or "kernel_accepted" field — there is no way to mark a
  candidate as trusted from within the candidate record itself.
- The **only** record that can assert a kernel-checked outcome is
  `ReconstructionRecord.kernel_accepted`. This is the single bit of ground
  truth the whole contract is built around.
- `HammerResult.status` may be `HammerResultStatus.VERIFIED` **if and only
  if** the result carries a `ReconstructionRecord` with
  `kernel_accepted=True`, itself pointing at the exact
  `ProofCandidateRecord` that was checked and the exact
  `EnvironmentLockRecord` the kernel ran under. This is enforced at
  *construction time* by `HammerResult.__post_init__`, which calls
  `HammerResult.validate()` — it is impossible to build a `HammerResult`
  instance with `status=VERIFIED` that lacks a successful reconstruction;
  attempting to do so raises `ValueError` immediately.
- The converse also holds: a `ReconstructionRecord` with
  `kernel_accepted=True` attached to a `HammerResult` whose `status` is
  anything other than `VERIFIED` is rejected as an inconsistent record graph
  (a successful kernel check can never be silently downgraded or hidden
  behind another status).

LLMs and learned components (HAMMER-005) may only ever influence premise
ranking or decomposition planning, and only when an operator opts in via
`HammerPolicy.allow_llm_premise_ranking` /
`HammerPolicy.allow_learned_premise_selector`. Nothing in this schema gives
an LLM, a learned selector, or an external solver a path to set
`kernel_accepted=True` — that field can only be populated by the
reconstruction stage that actually invokes the target ITP's kernel.

## 3. Result states

`HammerResultStatus` defines exactly eight terminal states. Every hammer run
ends in exactly one of these:

| State | Meaning | Invariants enforced |
| --- | --- | --- |
| `verified` | The reconstructed proof was independently accepted by the target ITP kernel. The only status asserting a checked theorem. | Requires `reconstruction.kernel_accepted=True`, matching `proof_candidate`, and matching `environment_lock`. |
| `candidate` | A solver produced an untrusted proof/certificate that has not been (or could not be) reconstructed and kernel-checked yet. | Requires a `proof_candidate`. |
| `counterexample` | A solver produced an untrusted countermodel/refutation of the goal. | Requires at least one `solver_attempts` entry. |
| `unknown` | No solver reached a conclusive verdict within budget. | No additional requirement beyond general record validity. |
| `timeout` | Every attempted solver exhausted its bounded timeout. | Requires at least one `solver_attempts` entry. |
| `unsupported_translation` | The goal or a required construct could not be lowered to any supported translation target (e.g. dependent types, higher-order quantifiers, unresolved polymorphism, raw lambdas). | Requires at least one `translations` entry with `status=UNSUPPORTED`; forbids any `solver_attempts`/`proof_candidate`/`reconstruction` (nothing should have executed). |
| `unavailable` | A required capability (ITP, solver, frontend adapter) was missing from the environment; nothing was executed. | Forbids any `solver_attempts`/`proof_candidate`/`reconstruction`. |
| `policy_denied` | Operator policy (timeouts, CPU/memory budget, network access, solver allow-list, disabled learned components, ...) forbade the run before execution. | Forbids any `solver_attempts`/`proof_candidate`/`reconstruction`; requires a non-empty `errors` explanation. |

`unsupported_translation`, `unavailable`, and `policy_denied` are the three
"fail closed before executing anything" states. They exist specifically so
the pipeline never has to choose between silently dropping semantics (to
force a translation to "succeed") and crashing — instead it produces an
explicit, typed, auditable result.

## 4. Record catalogue

All records live in `ipfs_datasets_py.logic.hammers.models` and share the
same conventions: they are `@dataclass`es, they carry a `schema_version:
str` field checked against `SUPPORTED_SCHEMA_VERSIONS`, they expose a
`validate()` method that raises `ValueError` with a descriptive message on
any constraint violation, and they expose `to_dict()`/`from_dict()` for
JSON-compatible (de)serialization.

### 4.1 `HammerPolicy`

Operator-controlled budgets and capability flags: `timeout_seconds`,
`cpu_seconds`, `memory_mb`, `network_allowed`, `allowed_solvers` (an
allow-list — an empty list means no external solver may run),
`allow_learned_premise_selector`, `allow_llm_premise_ranking`, and
`max_premises`. Every external executable path, timeout, CPU/memory budget,
and network-access decision the pipeline makes must be traceable to a
`HammerPolicy` instance; nothing may be hard-coded downstream.

### 4.2 `HammerRequest`

The versioned entry point of a hammer run: `request_id`, `itp` (an
`ITPKind`: `lean` | `coq` | `isabelle`), `theorem_id`, a diagnostic
`goal_statement`, the `corpus_revision` this request is bound to (see
HAMMER-003), an embedded `HammerPolicy`, `created_at`, and free-form,
non-authoritative `metadata`.

### 4.3 `PremiseRecord`

One premise selected from the content-addressed corpus: `premise_id`,
`statement`, `source_itp`, `corpus_revision` (must match the owning
request), `rank` (0-indexed, non-negative — enforces stable ordering per
HAMMER-004), `score` (any finite float; selectors define their own scale but
must be reproducible for identical input), `selection_method`, and an
optional `content_digest`.

### 4.4 `TranslationRecord`

The outcome of lowering one goal/premise construct to TPTP or SMT-LIB
(`target: TranslationTarget`). `status: TranslationStatus` is one of:

- `supported` — fully lowered; `translated_text` is required and
  `unsupported_reason` must be `None`.
- `partial` — lowered with side conditions; `translated_text` and a
  non-empty `obligations` list (documenting what remains unhandled, e.g.
  monomorphization instances or lambda-lifted definitions) are both
  required.
- `unsupported` — could not be lowered; `unsupported_reason` is required and
  `translated_text` must be `None`. This is the record type that makes
  `HammerResultStatus.UNSUPPORTED_TRANSLATION` possible and is what stops an
  unsupported dependent/higher-order/polymorphic/lambda construct from
  silently vanishing.

### 4.5 `SolverAttemptRecord`

One bounded, policy-controlled external solver invocation: `attempt_id`,
`translation_id` consumed, `solver_name`/`solver_version`, `target`,
`timeout_seconds`, the untrusted `verdict: SolverVerdict`, `exit_code`,
`wall_time_seconds`, `raw_output_digest` (full logs are stored out-of-band
and addressed by digest to keep the record small), `started_at`/
`finished_at`, `resource_usage`, and `network_used` (must only be `True`
when the owning policy's `network_allowed` is `True`). A `TIMEOUT` verdict
with a `wall_time_seconds` less than the configured `timeout_seconds` is
rejected as self-contradictory.

### 4.6 `ProofCandidateRecord`

An **untrusted** candidate proof/certificate produced by a solver attempt:
`candidate_id`, `solver_attempt_id`, `premise_ids` used, an optional raw
`certificate` and its `certificate_format` (e.g. `tstp`, `lfsc`, `alethe`).
As noted in §2, this record intentionally has no field that could assert a
verified/checked status.

### 4.7 `ReconstructionRecord`

The record of feeding a `ProofCandidateRecord` back through the target ITP
kernel: `candidate_id`, `target_itp`, `environment_lock_id`,
`kernel_command` (exact invocation, for audit/reproducibility), and the
ground-truth `kernel_accepted: bool`. When `kernel_accepted` is `False`, a
non-empty `failure_reason` is required; when `True`, `failure_reason` must
be `None`.

### 4.8 `EnvironmentLockRecord`

A pinned, versioned snapshot of the environment a reconstruction ran under:
`lock_id`, `itp`/`itp_version`, `kernel_command_template`,
`solver_versions` (exact version per solver), `executable_paths`, `os_info`,
an optional `container_digest`, `pinned_at`, and an optional
`policy_digest`. A `ReconstructionRecord` is only meaningful if its
`environment_lock_id` resolves to one of these — no floating "latest" tags.

### 4.9 `HammerResult`

The final, versioned outcome tying every other record together:
`result_id`, the originating `request`, the terminal `status`, the
`corpus_revision` (must match `request.corpus_revision`), an optional
`environment_lock`, lists of `premises`/`translations`/`solver_attempts`
(each internally deduplicated by id), an optional `proof_candidate`, an
optional `reconstruction`, `created_at`/`completed_at`, and free-form
`notes`/`errors`. Construction (`__post_init__`) eagerly calls `validate()`,
which checks every nested record plus the full status-invariant matrix
described in §2–3.

## 5. Serialization

Every record exposes `to_dict()` (producing a plain, JSON-serializable
`dict` — enums become their `.value`, `datetime`s become ISO-8601 strings)
and a matching `from_dict()` classmethod. `HammerResult.to_dict()` /
`HammerResult.from_dict()` recursively (de)serialize the entire record
graph, so a full result — including a `verified` one — can be persisted to
disk or IPFS/IPLD storage and reloaded without losing the trust-boundary
guarantees (`from_dict` reconstructs a real `HammerResult`, which re-runs
`validate()` via `__post_init__`).

## 6. Versioning

`SCHEMA_VERSION` (currently `"1.0.0"`) is checked against
`SUPPORTED_SCHEMA_VERSIONS` by every record's `validate()`. Backward-
incompatible schema changes should bump `SCHEMA_VERSION` and add the
previous value to `SUPPORTED_SCHEMA_VERSIONS` (with any necessary migration
logic in `from_dict`) rather than mutating the meaning of an existing
version in place.

## 7. Non-goals of this document

This document defines the *shape* of the trust contract only. It does not:

- Implement premise selection, translation, solver execution, or
  reconstruction logic — those are HAMMER-002 through HAMMER-0xx.
- Prescribe which solvers/ITPs are installed in a given environment — see
  the capability inventory (HAMMER-002).
- Relax the trust boundary for convenience. Any future change that would
  let a non-kernel-checked artifact produce `HammerResultStatus.VERIFIED`
  is out of scope and must not be made without revising this document and
  its enforcement in `models.py` together.
