# ITP Hammer Native-Automation and Decomposition Failure Policy

Status: Implemented (HAMMER-011)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.fallbacks`
Tests: `tests/unit_tests/logic/hammers/test_fallbacks.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract this module never weakens), and the HAMMER-010 native
reconstruction pipeline in `ipfs_datasets_py.logic.hammers.reconstruction`
and `ipfs_datasets_py.logic.hammers.reconstructors` (whose machinery this
module reuses, rather than reimplementing, for every kernel invocation it
makes).

## 1. Purpose

HAMMER-007's translation layer, HAMMER-008's solver portfolio, and
HAMMER-010's reconstruction/kernel-check step are each allowed — indeed,
required by their own contracts — to fail closed instead of fabricating a
proof:

- HAMMER-007 reports `TranslationStatus.UNSUPPORTED` for a dependent,
  higher-order, polymorphic, or lambda construct it cannot lower.
- HAMMER-008's bounded solver portfolio can exhaust its budget with no
  conclusive verdict (`SolverVerdict.UNKNOWN`/`TIMEOUT`), or run zero
  solvers at all when none are allowlisted.
- HAMMER-010 can reconstruct a candidate and have the target ITP kernel
  reject it (`ReconstructionRecord.kernel_accepted is False`).

None of these are implementation bugs — they are the honest, fail-closed
outcomes the trust contract is designed to produce instead of a false
positive. This document specifies what the pipeline does *next*: a bounded,
auditable recovery step that never weakens the trust contract, implemented
by `ipfs_datasets_py.logic.hammers.fallbacks` (HAMMER-011).

> On translation, search, or reconstruction failure, try an explicitly
> enabled native tactic such as Lean automation, then return a bounded
> subgoal decomposition plan. Any LLM-assisted plan is redacted, reviewed,
> and marked untrusted until each resulting native subproof passes the
> kernel.

## 2. The two recovery strategies, tried in order

### 2.1 Native automation fallback

`attempt_native_automation()` is an **explicitly operator-enabled** attempt
to close the goal using nothing but the target ITP's own built-in closing
tactics/methods — no untrusted external solver is involved at all. It is
gated by `HammerPolicy.allow_native_automation_fallback` (default `False`);
an operator must opt in per-request, matching the taskboard's "explicitly
enabled" requirement.

Mechanically, this function is *not* a new proof-search engine. It reuses
HAMMER-010's own `Reconstructor.reconstruct()` machinery with a synthetic,
**empty**-`premise_ids` `ProofCandidateRecord`. Every one of HAMMER-010's
anti-cheating checks and bounded-subprocess guarantees therefore applies
unchanged:

- Lean's `#print axioms <decl>` scan for a residual `sorryAx`.
- Coq/Rocq's `Print Assumptions <decl>.` scan for `Closed under the global
  context`.
- Isabelle's error-marker/`sorry`-residue scan.
- The same process-group-aware wall-clock/CPU/memory budget every solver
  attempt gets (`ipfs_datasets_py.logic.hammers.portfolio.
  run_bounded_solver_process`, via `run_kernel_check`).

Because no premises are supplied, each reconstructor's "try each in turn"
tactic (Lean's `first | ... `, Coq's `solve [ ... ]`, Isabelle's
`(m1 | m2 | ...)`) is built purely from its small, fixed, deterministic set
of native closing tactics (Lean: `rfl`, `trivial`, `decide`, `omega`,
`simp_all`, `assumption`; Coq: `reflexivity`, `assumption`, `now auto`,
`now easy`, `lia`, `trivial`; Isabelle: `simp`, `auto`, `blast`, `force`,
`fastforce`, `assumption`). A `NativeAutomationAttempt` with
`recovered=True` therefore carries a genuine, independently kernel-checked
`ReconstructionRecord` — exactly as trustworthy as any other HAMMER-010
reconstruction, never merely "the fallback logic decided this was fine."

`attempt_native_automation()` never raises for an expected "could not run"
outcome:

| Situation | Result |
| --- | --- |
| `allow_native_automation_fallback` is `False` | `attempted=False`, `skipped_reason` explains the policy gate |
| Target ITP kernel unavailable (`Reconstructor.capability().available` is `False`) | `attempted=False`, `skipped_reason` includes the capability's `unavailable_reason` |
| `ReconstructionInputError`/`KernelUnavailableError` from the underlying reconstructor | `attempted=False`, `skipped_reason` includes the original error |
| Kernel invocation ran, kernel rejected | `attempted=True`, `recovered=False`, `reconstruction.kernel_accepted is False` |
| Kernel invocation ran, kernel accepted | `attempted=True`, `recovered=True`, `reconstruction.kernel_accepted is True` |

A caller who recovers via this path assembles the final `HammerResult`
exactly the way any other HAMMER-010 caller does — using the returned
`ReconstructionRecord`, `ProofCandidateRecord`, and `EnvironmentLockRecord`
— since `HammerResult.validate()`'s trust invariant (HAMMER-001) is
unmodified and unaware this reconstruction came from a fallback path rather
than a solver-driven one.

### 2.2 Bounded subgoal decomposition plan

If native automation is disabled, unavailable, or itself rejected by the
kernel, `build_decomposition_plan()` returns a `DecompositionPlan` of at
most `HammerPolicy.max_decomposition_subgoals` `DecompositionSubgoal`
entries (default `4`). A plan is never itself a proof of the original goal
— `DecompositionPlan.is_fully_verified()` is the only way to learn whether
every subgoal in it has independently passed its own native kernel check.

Subgoals are derived from two sources, always native-structural first:

- **Native-structural** (`DecompositionSource.NATIVE_STRUCTURAL`):
  `split_top_level_conjuncts()` deterministically splits the goal's own
  text on its top-level `∧`/`/\` connectives, tracking bracket depth so a
  connective nested inside `()`/`[]`/`{}` is never split on. If fewer than
  two top-level conjuncts exist, no native-structural subgoal is produced —
  an honest "no decomposition available," never a fabricated split. When
  more conjuncts exist than the bound allows, the excess is folded,
  verbatim, into the final subgoal rather than silently dropped.
- **LLM-suggested** (`DecompositionSource.LLM_SUGGESTED`): considered only
  when *both* an `llm_decomposition_provider` callable is supplied to
  `build_decomposition_plan()`/`attempt_fallback()` *and*
  `HammerPolicy.allow_llm_decomposition_hints` is `True`. If either
  condition is not met, any supplied suggestions are ignored entirely and
  recorded in `DecompositionPlan.notes`.

Native subgoals always fill the bound first; only remaining room (if any)
is offered to the LLM provider, and any suggestions beyond that remaining
room are dropped with an explanatory note — the bound is never exceeded
regardless of how many subgoals either source proposes.

## 3. The LLM redaction/review/trust gate

Every `LLM_SUGGESTED` subgoal goes through three independent, sequential
gates before it can ever be marked trusted. None of them can be skipped by
constructing the record directly — `DecompositionSubgoal.validate()`
(called explicitly by every builder function in this module) enforces each
one:

1. **Redacted on arrival.** The instant a suggestion is accepted into a
   plan, `redact_llm_text()` computes `redacted_suggestion` — a placeholder
   containing only the suggestion's length and a deterministic content
   digest, never the raw text. `DecompositionSubgoal.statement` still holds
   the real text (verification needs it to build a genuine native source),
   but `redacted_suggestion` is what anything other than the internal
   verification path should ever surface. `review_status` starts at
   `PENDING_REVIEW` — never `NOT_REQUIRED` — the moment a subgoal's source
   is `LLM_SUGGESTED`.
2. **Reviewed.** `review_decomposition_subgoal()` is the only way to move a
   subgoal out of `PENDING_REVIEW`. It requires a non-empty `reviewer`
   identity, refuses to run twice on the same subgoal, and refuses outright
   on a `NATIVE_STRUCTURAL` subgoal (which never needs review since no LLM
   was involved). Approval (`review_status=REVIEWED`) does **not** mean the
   suggestion is trusted — it only permits `verify_decomposition_subgoal()`
   to attempt a kernel check at all. Rejection
   (`review_status=REJECTED`) immediately and permanently forces
   `status=SubgoalStatus.REJECTED`.
3. **Untrusted until kernel-verified.** `verify_decomposition_subgoal()`
   refuses to run at all for an `LLM_SUGGESTED` subgoal whose
   `review_status` is not `REVIEWED` (`FallbackInputError`, no kernel
   invocation is made). Once reviewed, it builds a genuine, self-contained
   native source for the subgoal (see §4) and reuses the same
   HAMMER-010 reconstructor machinery `attempt_native_automation()` uses.
   `DecompositionSubgoal.status` becomes `VERIFIED` — the only status that
   means "trust this" — if and only if the target ITP kernel genuinely
   accepted the reconstruction; otherwise it becomes `REJECTED` (kernel ran
   and rejected) or `SKIPPED` (target kernel unavailable; no attempt made).
   `DecompositionSubgoal.validate()` additionally enforces that `VERIFIED`
   always carries a non-empty `reconstruction_id`, and that an
   `LLM_SUGGESTED` subgoal can only be `VERIFIED` when `review_status` is
   `REVIEWED` — the review and verification records can never be
   inconsistent with each other.

In short: an LLM may propose *text to attempt*. It can never supply an
accepted proof, and its proposal is redacted and untrusted from the moment
it exists until a human has reviewed it **and** a real native kernel has
independently checked it.

## 4. Synthesizing a native source per subgoal

`verify_decomposition_subgoal()` needs a genuine, self-contained native
source for each subgoal's statement — not a reinterpretation of the
original theorem's proof state. It builds one deterministically per target
ITP, reusing the caller's own `GoalSnapshot.hypotheses` as parameter
binders (never inventing a binder):

- **Lean**: `theorem {decl} (n : Nat) (h : n = n) : {statement} := by` /
  `  sorry`, mirroring `reconstructors/lean.py`'s own `sorry` marker so the
  same reconstructor code path applies unchanged.
- **Coq/Rocq**: `Theorem {decl} (n : nat) (h : n = n) : {statement}.` /
  `Proof.` / `  intros.` / `Admitted.`, mirroring the "good source" fixture
  shape already used by `test_reconstruction.py`.
- **Isabelle/HOL**: a `theory ... imports Main begin ... lemma {decl}: ...
  sorry ... end` rendering with hypotheses folded into a `fixes`/`shows`
  lemma. Isabelle is confirmed unavailable in this repository's probed
  environment (`docs/logic/itp_hammer_capability_inventory.md`), exactly as
  documented by `reconstructors/isabelle.py` itself, so — like that
  module — this builder is a conservative best-effort rendering that has
  not been validated against a live Isabelle kernel; it is only exercised
  in this module's tests against a mocked reconstructor.

The synthetic `GoalSnapshot` passed alongside this source is explicitly
marked (`extra={"synthetic_decomposition": True, ...}`) and its
`raw_native_output` says outright that it was not independently captured
via a native ITP diagnostic invocation — never presented as if it were a
genuine HAMMER-006 capture.

## 5. Why this never weakens the trust contract

- Neither recovery strategy can construct a `HammerResultStatus.VERIFIED`
  `HammerResult` by itself; `HammerResult.validate()`'s invariant (HAMMER-001)
  is untouched, and every kernel-facing call in this module still goes
  through `Reconstructor.reconstruct()` — the *same* function whose
  anti-cheating checks were verified empirically in HAMMER-010.
- `attempt_native_automation()` recovers a goal only via a real subprocess
  kernel invocation with a real exit status and output — never by
  assuming an untrusted candidate is fine because no solver was involved.
- `DecompositionPlan`/`DecompositionSubgoal` are, by construction, never
  proofs. `is_fully_verified()` is the only aggregate signal, and it is
  only `True` when every subgoal's own `ReconstructionRecord.
  kernel_accepted` was independently `True`.
- Every function in this module raises `FallbackInputError` — never
  silently downgrades or upgrades a status — for misuse: a mismatched
  request/goal snapshot, an unreviewed or review-rejected LLM subgoal
  submitted for verification, or an already-verified subgoal resubmitted.

## 6. Schema summary

| Type | Purpose |
| --- | --- |
| `FallbackTrigger` | Which upstream stage failed (`translation_failure`, `search_failure`, `reconstruction_failure`); provenance only — the recovery logic is identical across all three. |
| `NativeAutomationAttempt` | Outcome of one `attempt_native_automation()` call: `attempted`/`recovered` plus the genuine `ProofCandidateRecord`/`ReconstructionRecord`/`ReconstructionEvidence`/`EnvironmentLockRecord` when attempted. |
| `DecompositionSource` | `native_structural` or `llm_suggested` provenance of a subgoal's text. |
| `ReviewStatus` | `not_required` (native), `pending_review`/`reviewed`/`rejected` (LLM-suggested). |
| `SubgoalStatus` | `pending`, `verified` (kernel-accepted), `rejected` (kernel-rejected or review-rejected), `skipped` (kernel unavailable). |
| `DecompositionSubgoal` | One bounded subgoal: statement, redaction, review, and verification state. |
| `DecompositionPlan` | A bounded, ranked list of subgoals plus `is_fully_verified()`. |
| `FallbackOutcome` | The overall `attempt_fallback()` result: native automation attempt plus (if not recovered) a decomposition plan. |

## 7. New `HammerPolicy` fields (HAMMER-001 extension)

- `allow_native_automation_fallback: bool = False` — must be explicitly set
  `True` per request for `attempt_native_automation()` to ever invoke a
  kernel.
- `allow_llm_decomposition_hints: bool = False` — must be explicitly set
  `True` for an `llm_decomposition_provider`'s suggestions to be considered
  at all (they are otherwise ignored with a note, never silently dropped
  without explanation).
- `max_decomposition_subgoals: int = 4` — hard upper bound on the combined
  native-structural and LLM-suggested subgoal count in any one
  `DecompositionPlan`.

## 8. Worked example

```python
from ipfs_datasets_py.logic.hammers import fallbacks as fb
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, HammerRequest, ITPKind

policy = HammerPolicy(
    allowed_solvers=[],
    allow_native_automation_fallback=True,
    allow_llm_decomposition_hints=True,
    max_decomposition_subgoals=4,
)
request = HammerRequest(
    request_id="req-1", itp=ITPKind.LEAN, theorem_id="my_thm",
    goal_statement="n = n and m = m", corpus_revision="rev-1", policy=policy,
)

# goal_snapshot/native_source come from the HAMMER-006 Lean frontend.
outcome = fb.attempt_fallback(
    request=request,
    trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
    goal_snapshot=goal_snapshot,
    native_source=native_source,
    llm_decomposition_provider=my_llm_decomposer,  # optional
)

if outcome.recovered:
    # outcome.native_automation.{proof_candidate,reconstruction,environment_lock}
    # assemble a VERIFIED HammerResult exactly like any HAMMER-010 caller.
    ...
else:
    for subgoal in outcome.decomposition_plan.subgoals:
        if subgoal.source is fb.DecompositionSource.LLM_SUGGESTED:
            fb.review_decomposition_subgoal(subgoal, approve=True, reviewer="alice")
        fb.verify_decomposition_subgoal(
            subgoal, request=request, goal_snapshot=goal_snapshot
        )
    if outcome.decomposition_plan.is_fully_verified():
        # every subgoal independently passed its own native kernel check.
        ...
```
