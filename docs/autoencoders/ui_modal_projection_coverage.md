# Explicit UI temporal, normative, and cognitive projections

This extends the [declared-source coverage](source_family_coverage.md) work with
actual interpretations for the three missing UI floor entries: temporal logic,
TDFOL, and DCEC. The inputs are authored declarations. They are not learned
decoder outputs, authenticated event history, or proofs that a UI policy holds.

## What the candidate must contain

The closed `ui-declared-logic-source/v1` source contains `schema`, `candidate`,
and `interpretations`. The entire original candidate has this structure:

```text
kind: ui_declared_logic
document: complete native UI document
logic:
  temporal: explicit state/temporal descriptor or null
  tdfol: explicit state/norm/temporal descriptor or null
  dcec: explicit agent/event/fluent/time/formula descriptor or null
```

At least one logic descriptor is required. The source's `candidate` and the
generated or authored candidate must agree on every typed field. A source-only
norm cannot be attached to a plain component prediction during audit. The
complete behavior, guard, and event interpretation bodies must also occur in
the original source. Only bookkeeping hashes are derived.

This compound target is separate from the current learned decoder's native
target grammar. Its preparation does not add a decoder head or migrate a
checkpoint. The existing 64-token target limit stays fixed; complete target
sizes are measured without truncation. Verified local semantic embeddings,
source-context checks, a lossless representation within existing limits, and
held-out learned reconstruction remain separate work.

## Temporal and TDFOL meaning

The state predicates refer to exact declared UI states. Reversible symbols
bind each predicate argument to its original state identifier. For example,
`ui_state:v636c6f736564` denotes the explicitly declared state `closed`.

```text
G(UIState(ui_state:v6f70656e))
O(◊(UIState(ui_state:v636c6f736564)))
P(X(UIState(ui_state:v6f70656e)))
F(G(UIState(ui_state:v6f70656e)))
```

Here `G`, `◊`, and `X` mean always, eventually, and next over unbounded discrete
logical steps. Native ASTs distinguish prohibition `F` from eventually `◊`.
The supported fragment also includes until and Boolean composition. The TFOL
route requires temporal operators without deontic operators; TDFOL requires
both. An obligation without temporal structure cannot fill the TDFOL gap.

Known states come from replaying the complete explicitly declared bounded EC trace. Step
zero is its explicit clock origin, and physical time is origin plus resolution
times logical step. Lean checks join every known state predicate to the actual
EC `holdsAt` definition. After the known prefix, the state is supplied by an
arbitrary continuation over the declared state type. It is never defaulted to
false or inferred to follow the observed workflow forever.

O/P/F remain distinct state-norm interpretation parameters. They introduce no
modal axioms, actor duties, or proof that a formula holds. Unsupported indexed
norms, metric time bounds, other predicates, or undeclared states are rejected.

## DCEC meaning

For example, an explicit descriptor may declare:

```text
B(Operator,O(Happens(Close,Tick12)))
K(Operator,F(HoldsAt(Open,Tick14)))
I(Operator,P(not(Happens(Close,Tick12))))
```

Each alias has an explicit role. An agent alias names a declared actor; an
event alias joins an exact UI transition and event; a fluent alias joins a
native state; a time alias supplies an aligned physical tick on the EC clock.
Source references are checked. Aliases cannot collide or be silently ignored.

Every formula must contain cognitive, deontic, and event/fluent structure.
`Happens` and `HoldsAt` lower to the existing EC definitions, with Lean checks
for knownness and the declared value. They are not arbitrary renamed atoms.
The first fragment accepts only known ground times and these two EC operators.
For a prefix of N event ticks, event observations stop before N, while state
observations include the successor at N. Later observations remain unknown
and are rejected by this fragment.

B/K/I and O/P/F remain separate interpretation parameters. A belief about a
known-false event is still a well-formed declaration; the system does not
assert that the belief or norm is true. User interaction provenance cannot
establish knowledge, intention, or compliance.

## Entry points and gates

| Module | Entry point | Role |
| --- | --- | --- |
| `ui_declared_logic_source` | `audit_candidate` | Compare the complete original source and compound candidate |
| `ui_declared_logic_source` | `prepare_family_targets` | Replay explicit context, preserve base projections, and append native modal targets |
| `ui_declared_logic_source` | `validate_family_training_report` | Check report integrity; with original inputs, replay the entire source/candidate/report |
| `intent_ui_candidate_pipeline_v4` | `infer_and_audit`, `audit_candidates` | Run target-free inference first, then route compound candidates to source audit; delegate all previous routes in one batch |
| `native_ui_temporal_logic` | `prepare_payload`, `emit_projection` | Native temporal ASTs and EC/state semantics |
| `native_ui_dcec_logic` | `prepare_payload`, `emit_projection` | Native DCEC ASTs and typed, known EC leaves |
| `parallel_projection_checks_v4` | `run_parallel_projection_checks` | Schedule real native builds through the shared resource owner |
| `resumable_native_validation_v2` | `run_resumable_native_validation` | Preserve bounded retry/resume with the new native owner |
| `family_coverage_frontier_v2` | `diagnose_family_coverage` | Separate operator, parser, lowering, Lake, and coverage gaps |

The versioned native v8 issuer and policy preserve the previous minimum floors
and 40-family review requirement. Existing v1–v7 owners and checkpoints are
unchanged. Every original projection remains in the report, with its complete
base report retained for exact replay. An invalid owned projection cannot fall
back to a generic interpretation. Only actual `lake build UIUXIR` creates live
Lean execution evidence; stored JSON receipts cannot reopen a training gate.
TLA+ retains its separate syntax check. A successful partial build does not
waive missing families or applicability reviews.

Pipeline v4 preserves a raw compound candidate rejected by the existing native
decoder as `native_generation_rejected`. It does not repair that output or
promote it into `candidate_ir`. Being eligible to prepare family targets is
explicitly separate from training eligibility.

## Validation protocol

`scripts/ops/autoencoder/benchmark_ui_modal_coverage.py` records every predeclared
positive and negative fixture before execution, retains complete source and
candidate records, and requests all 40 families. It checks that every new
declared projection passes its parser, supported lowering, and actual Lake
build. It separately checks the unchanged UI batch floor and closed strict
training gates. It runs no model, embedding generator, or training optimizer.

Run in a frozen canonical export under the existing storage/resource guardian.
The output directory must be new. Installed Lake/Java/TLA tools are pinned; no
weights or tools are downloaded. Native scheduling uses at most two workers,
with bounded individual subprocess and lease waits. The complete source tree
is hashed before and after execution to detect drift.

## Measured frozen validation, 2026-10-02

The [retained results](../implementation/reports/evidence/ui-modal-coverage-20261002/results.json)
and their manifest/archive preserve the source, every fixture, native Lean inputs,
execution output, failed attempts, and resource accounting.

| Check | Result |
| --- | --- |
| Frozen regression suite | 745 passed, no skips; 130.15 seconds |
| Successful guardian's cleanup tests | 4 passed |
| Authored fixture panel | 23 cases: 9 prepared, 14 expected rejections |
| Actual native builds | 9/9 `lake build UIUXIR` passed |
| Newly declared modal projection occurrences | 12/12 parser, lowering, and Lake checks passed |
| UI minimum floor | All seven requirements satisfied, including separate TLA+ syntax evidence |
| Complete catalog | 7 of 40 families have validated projections somewhere in the panel |
| Strict training gates | Closed for every case and the complete batch |
| Neural inference, optimizer steps, checkpoint promotion | None |

The validated family union is first-order, frame logic, event calculus,
temporal, TDFOL, DCEC, and transition systems. Minimum-floor satisfaction does
not replace source-specific applicability review for the rest of the catalog.
It does not prove that declared beliefs, norms, or temporal formulas hold.

The successful benchmark took 212.49 seconds, excluding outer resource admission
and guardian closeout. Preparing a positive source/projection case took
4.69–7.27 seconds (mean 5.36); expected rejections took 0.004–0.402 seconds.
Python parent peak RSS was 808,316 KiB; this excludes native child memory.
At most two native workers were scheduled. Native job workspaces were fresh,
using the existing pinned toolchain, with no downloads. These are authored
projection-validation timings. No legal-IR bridge-on autoencoder evaluation or
model throughput comparison ran.

The first native attempt passed five DCEC-only builds and failed four builds
containing temporal projections. Lean rejected `decide` with a free future
parameter in the expected type. The correction retains the quantified theorem
and arbitrary future interpretation, then uses definitional `change` to reduce
each known-prefix goal to its closed EC observation before `decide`.
The failed attempt and original source remain archived.

One later attempt was stopped during preparation by the 140 GB campaign cap;
it produced no native result. Two outer admission waits also timed out before
starting a child. Their records remain separate. Audited recovery released only
the first empty admission claim and the stopped preparation claim, preserving
all artifacts and other reservations. The next attempt reserved 100 MB based
on the first run's measured 20.4 MB outputs. Its outer scheduler wait was 300
seconds; native subprocess limits and proof/qualification gates were unchanged.

All complete compound targets use 575–759 tokens under the current lexical
codec, above the unchanged 64-token limit, and the current learned decoder's
target grammar does not accept this compound form. None was truncated, inserted
into a checkpoint, or counted as learned reconstruction. Remaining training
work is a lossless supported decoder representation, verified local embedding
and source-context checks, source-specific catalog review, and target-free
held-out reconstruction with the same native gates.
