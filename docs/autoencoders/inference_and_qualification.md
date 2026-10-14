# Inference and qualification are separate operations

An autoencoder inference call returns learned representations or reconstruction metrics. It does not establish that a legal sentence compiled correctly, that a modality's projections preserve meaning, or that a theorem was admitted. Use the operation below that matches the evidence you need.

| Operation | Public entry point | Executes training? | Executes Lake? |
| --- | --- | --- | --- |
| Legal model metrics | `autoencoder_paths.run_inference` | No | No |
| Legal feature metrics with raw decoder | `autoencoder_paths.gated_evaluate(..., reconstruction_objective="raw_decoder")` | No | No |
| Legal source/model qualification | `run_incremental_autoencoders.py --execution-mode inference` | No | When the source is eligible and renderable |
| UI/UX, security or intent feature inference | `autoencoder_projection_features.infer_projection_features` | No | No |

The structural modality API needs its own contract, feature space and numerical state. It does not accept legal modal checkpoints, Arrow weight overlays or a legal shared-target bundle. See the [native feature quickstart](native_feature_quickstart.md) for its complete training/inference example.

## Reuse the optimized Legal runtime

The published Legal 384D loaders enable inference optimizations by default:

```python
from ipfs_datasets_py.logic.legal_ir import open_autoencoder

runtime = open_autoencoder(local_files_only=True)
result = runtime.infer_texts(["The agency shall retain records."])
# Reuse runtime for subsequent calls; the private decoder and encoder are cached.
original = open_autoencoder(local_files_only=True, optimized=False)
```

Both `checkpoint_hub.open_autoencoder("legal_ir", ...)` and
`checkpoint_hub.open_local_autoencoder("legal_ir", ...)` accept the same
`optimized=False` opt-out. The versioned `autoencoder_runtime_registry.open_runtime`
also defaults to optimized learned-formula inference for `legacy_v1`,
`legacy_v1_optimized` (8D), and `current_v2` (384D), when a formula head is attached.
Pass `optimized=False` when opening that runtime to retain the original decoder.
Metrics and compiler modes keep their existing evaluation behavior.

Checkpoint bytes, source bindings, full core checks, and decoder tensor checks
remain verified. Optimized results identify their inference implementation;
batched float32 calculations can differ slightly in confidence margins. GTE-small
uses CUDA when available and CPU otherwise. Timings with supplied embeddings
exclude the cost of this encoder.

## A runnable, offline legal inference example

This example uses a fresh small model and the deterministic **test** embedding supplied by `build_us_code_sample`. It demonstrates the inference gate without downloading a model, loading an archived checkpoint, generating bridge targets or running a prover. Its metrics are not semantic-embedding quality measurements and are not production training inputs.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0
export IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=0
export CUDA_VISIBLE_DEVICES=''

python3 -B - <<'PY'
import json
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
require_workspace_logic_tree()

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paths import run_inference

sample = build_us_code_sample(
    title='fixture',
    section='1',
    text='The agency shall not disclose records.',
)
model = AdaptiveModalAutoencoder(compute_device='python')
report = run_inference(model, [sample], legal_ir_bridge_names=())
print(json.dumps({key: report[key] for key in (
    'execution_path', 'training_executed', 'state_changed', 'sample_count',
    'legal_ir_target_count', 'cosine_similarity', 'reconstruction_loss',
    'qualified', 'admitted',
)}, indent=2))
assert report['training_executed'] is False
assert report['state_changed'] is False
assert report['legal_ir_target_count'] == 0
assert report['qualified'] is False and report['admitted'] is False
PY
```

`run_inference` uses `gated_evaluate`, checks the model's state revision and identity before/after evaluation, disables sample memory and external provers, and returns the native metrics. Its default reconstruction objective is `safety_projected`. The result deliberately records zero legal-IR targets because the bridge list is empty. That is not a bridge-on speed measurement.

For raw decoder metrics on the same model, replace the call with:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paths import gated_evaluate

evaluation = gated_evaluate(
    model, [sample], execution_mode='inference',
    legal_ir_bridge_names=(),
    reconstruction_objective='raw_decoder',
)
metrics = evaluation.to_dict()
```

Raw decoder evaluation measures learned residual features relative to the supplied embedding. It is not an independent text decoder. Do not compare it to safety-projected metrics as if they were the same objective.

## Evaluate an existing local legal checkpoint

Replace the fresh model construction with the following after independently verifying the checkpoint's artifact hash and selecting its matching embedding representation:

```python
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)

checkpoint = Path('/absolute/path/verified-complete.state.json')  # Replace this path.
state = ModalAutoencoderTrainingState.load_json(checkpoint)
model = AdaptiveModalAutoencoder(state=state, compute_device='python')
```

This snippet expects a **complete legal modal state**, not a sparse update manifest, DuckDB database, Arrow IPC overlay, tensor checkpoint or structural modality state. Resolve a sparse chain through its existing owner-verified materialization path first; see [artifacts and inputs](artifacts_and_inputs.md). Supply `build_us_code_sample` with the checkpoint-compatible `embedding_model` and `embedding_vector` from verified local input evidence. The test vectors above cannot validate a semantic checkpoint.

The model's `encode`/`decode` methods reconstruct embedding vectors. They do not return verified legal text or a theorem. Candidate qualification independently runs the deterministic compiler/decompiler on the original source.

For bridge-on evaluation, pass the full requested list explicitly:

```python
BRIDGES = (
    'modal_frame_logic', 'deontic_norms', 'fol_tdfol',
    'cec_dcec', 'external_prover_router',
)
report = run_inference(model, samples, legal_ir_bridge_names=BRIDGES)
```

Here `samples` must be your already constructed legal samples. This call performs potentially expensive bridge work; it is not part of the minimal smoke above. Record `seconds`, `sample_count`, `legal_ir_target_count`, `legal_ir_losses`, bridge names, worker count and cache/prover settings. Positive target count is necessary to call this a legal-IR measurement. Reuse a verified target mapping only after the shared-target loader has checked source, sample and configuration identities; do not pass arbitrary cached dictionaries as evidence.

## Run the full legal qualification path without training

The incremental CLI's inference mode runs separate qualification passes against an immutable local checkpoint. It writes receipts and may execute source-locked Lake builds, but opens no training registry, creates no optimizer candidates, and publishes no weights.

The following is an execution template, not a dry run. Fill the placeholders with an existing compatible **complete checkpoint**, local input JSONL and **1–32 disjoint tuning rows**. Use a new state directory, separate from every training state directory.

```bash
python3 -B scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --execution-mode inference \
  --state-directory /absolute/path/new-qualification-state \
  --checkpoint /absolute/path/verified-complete.state.json \
  --input-jsonl /absolute/path/input.jsonl \
  --validation-jsonl /absolute/path/disjoint-tuning.jsonl \
  --workers 1 \
  --parallel-workers 1 \
  --max-batches 1 \
  --lake-timeout-seconds 120 \
  --cycle-timeout 900 \
  --memory-mb 8192 \
  --storage-bytes 1000000000 \
  --polls 1
```

The state directory must be inside an approved resource-ledger root; use the [operations guide](operations_and_troubleshooting.md) to inspect admission first. The same execution-mode binding is checked on resume. Completed passes have sealed receipts; changing checkpoint, producer sources or validation policy requires a new state. An incomplete retained pass needs explicit recovery rather than overwriting its evidence.

Inference mode rejects optimizer settings, feature-training purpose, shared training targets, Arrow training overlays and network feed/publication arguments. Do not add `--training-purpose feature_pretraining` to this qualification command. The phrase `--execution-mode inference` here means “do not train”; it does not mean “skip source qualification.”

## What the legal qualification receipt checks

The thresholds below come from [candidate qualification](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py). They are existing gates, not suggested tunable success criteria.

| Gate | Requirement | Evidence limit |
| --- | --- | --- |
| `metric_gate` | Per-sample embedding cosine at least **0.72** and reconstruction loss at most **0.20**, finite values, correctly sized decoded vector | Embedding reconstruction, not textual roundtrip equivalence |
| `semantic_gate` | Every source clause completes deterministic compiler/decompiler roundtrip, with complete fields and nonempty decoded text | Source pipeline evidence; no model-generated text claim |
| `family_syntax_gate` | Actual source-bound exports pass each required syntax consumer | Syntax, not entailment, equivalence or proof |
| `lake_gate` | Eligible source semantics, a renderable source-locked numeric pattern, and a successful `lake build Legal` | Only that generated locked numeric theorem |
| `heldout_gate` | Nonempty tuning samples disjoint by identity and normalized text | Repeated selection tuning; receipt still says `heldout_canary: false` |

Required legal syntax exports are `fol`, `deontic_fol`, `temporal_fol`, `deontic_temporal_fol`, `deontic_cognitive_event_calculus`, and `frame_logic`. These are the legal gate's export labels. Other modalities use their own native routes and canonical family/profile/property/view identities; copying this list into a UI or security adapter would be incorrect. See [modalities](modalities.md).

Every qualification row and the aggregate must pass the applicable gates. The qualification code may permit **stricter** cosine/loss thresholds, but cannot weaken the existing floor/ceiling. Feature optimizer loss improvement is a separate observation.

The numeric theorem path uses an already installed `leanprover/lean4:v4.26.0` toolchain and invokes `lake build Legal`; it does not request a toolchain download or import Mathlib. `Legal` is the generated library name, and its capitalization matters. `lean lake legal` is not the command used by the gate.

The renderable temporal subset includes an integer `minimum_duration` threshold. `within_duration` deadlines remain non-renderable, including rules that also contain a minimum duration. A passing syntax parser, bridge report, compile/decompile cycle, NCA output, autoencoder score, or DuckDB row is not a Lean admit. An external prover/router status or an ErgoAI resolution log is not a substitute for the Lake receipt.

The U.S. Constitution is not formalized. Its detected spans return `constitution_not_formalized`; do not relabel them `roundtrip_ok` or bypass the exclusion. Existing qualification receipts retain aggregate `admitted: false` and `formalized: false` even when their scoped Lake subreceipts succeed. A narrowly admitted numeric theorem does not formalize the whole law.

## Temporal occurrence evidence

Candidate qualification now records `temporal_occurrence_provenance` beside its
compiler and gate receipts. It preserves the parser's exact temporal spans,
observations excluded inside conditions or exceptions, and every matching rule
and temporal-atom index as a **diagnostic candidate**. Repeated phrases at different
offsets retain different source-local `occurrence_id` values. A separate
`document_occurrence_id` binds translated offsets to the complete document digest:
identical clauses at different document positions stay distinct, and different
clause views of the same physical span share that document identity. Unresolved
translations have no document occurrence ID. Neither a unique string match nor an
exact adapter join establishes the legal owner, clock origin, or scope.

For direct compiler use, opt in with
`AutoformalSession(capture_temporal_provenance=True)` and retrieve
`session.temporal_occurrence_report()`. Each artifact contains a `receipt`, a
snapshot of `compiler_rows_at_capture`, `adapter_diagnostics`, and an
`interpretation_requests` inventory, and a `deadline_interpretation_requests`
inventory. The standalone occurrence
API lives in
[legal_temporal_occurrence_provenance.py](../../ipfs_datasets_py/logic/autoformal/legal_temporal_occurrence_provenance.py).
Validation needs the exact source and document text and the captured rows. Rows
may subsequently acquire a roundtrip status; validate against the recorded
snapshot. A receipt's internal `receipt_sha256` hashes its body without that
field; the containing artifact's `receipt_sha256` hashes the complete receipt.
Family evidence references the latter. These hashes bind bytes and do not attest
legal meaning or the authority of a caller-supplied document ID.

Offsets are half-open Unicode code-point positions in the exact parser input.
When segmentation changes whitespace, the existing clause selector is regenerated
and checked before translating into document coordinates. A boundary inside a
length-changing whitespace segment remains unresolved. Source and document slices
are retained separately. Parser and proposer spans must match exactly to join;
no trimming or approximate matching repairs a mismatch.

Whole-input inventories preserve unsupported spans even when no rule is emitted.
They do not attach rules produced from separately segmented clauses. The source
proposer's hard limits produce an explicit unavailable diagnostic; the source is
never truncated to fit. Constitutional sources retain their existing exclusion
and an explicit `not_evaluated` provenance status.

The occurrence evidence adds no canonical facets. The canonical v1 shape and
legacy three-field `temporal_records` shape are unchanged. The deadline cue
repair described below deliberately changes affected string values and their
content IDs. This evidence does not pass any qualification gate, execute a model
or Lake, or improve measured decoder accuracy by itself.

## Explicit event-relative interpretations

The opt-in temporal report also retains source-bound requests for surface event
proposals that have no parser occurrence. Each request binds the temporal and
event spans to the source and, when translation is exact, to the complete
document. A missing parser match stays missing. Unsupported and excluded
proposals remain in the inventory with their reasons. Proposer budget failures
produce an explicit unavailable inventory. Each session artifact hashes the
complete request inventory in `interpretation_requests_sha256`; family evidence
references that digest without changing its qualification result.

[legal_temporal_event_interpretation.py](../../ipfs_datasets_py/logic/autoformal/legal_temporal_event_interpretation.py)
provides `build_interpretation_requests`, `prepare_event_interpretation`, and
`validate_event_interpretation`. Preparation requires the original occurrence
receipt, authenticated proposer receipt, exact source/document text, captured
compiler rows, and a completed request's `declaration_skeleton`. The inventory
leaves every semantic choice unset. Callers must supply an exact preceding
subject span, distinct state/event atom names, strong or weak until, and the
supported clock, endpoint, and scope choices. A subject span is a caller's
interpretation anchor; it does not establish the legal owner or a complete
translation of the sentence. Validation regenerates the request and prepared
artifact against the current producers and rejects altered bindings.

This initial profile supports a temporal property over unbounded discrete
natural-number time with a caller-supplied evaluation origin. The state must
hold before the event tick; the event tick itself is excluded. Strong until
requires that the event eventually occurs. Weak until also allows the state to
hold forever without that event. The output includes a typed `TemporalFormula`,
a strict TDFOL `U` or `W` formula, and Lean declarations using separate `holds`
and `occurs` traces and the existing `untilTime`/`weakUntilTime` definitions.
Trace interpretations remain caller-supplied. Preparation does not execute Lake,
and parser acceptance does not prove source fidelity.

The profile does not assign a meaning to bare `after`, resolve anaphora, choose
an obligation/prohibition scope, or attest event occurrences. Those cases need
additional declarations or a supported translation profile. It cannot repair
canonical rules by inserting an opaque event string or strengthen a qualifier
silently. In particular, real US Code examples remain unresolved without
reviewed interpretations; buildable fictional examples are engineering checks.

For decoder training, keep these request inventories as unresolved examples
until the interpretation is independently reviewed. Explicitly supplied
interpretations can exercise serialization and lowering, but must retain their
caller-supplied provenance when used as training targets. Measure source
attachment, strength, endpoint, clock, modality scope, family syntax, and native
build success separately. A successful `U`/`W` lowering is not a new legal
accuracy score or a passed 8D/384D/768D qualification gate.

## Deadline cues and explicit response windows

The parser preserves `not later than` and `no later than` in its `value` and
`normalized_text`, including the complete duration and event complement. It
normalizes payload whitespace for these two kinds so that an explicit `after`
separated by tabs or newlines still retains its anchor. Exact `raw_text` and
source coordinates are unchanged. Quantity, unit, and anchor extraction still
use the duration payload. Canonical vocabulary, temporal strings, three-field
temporal records, and source-withheld decompilation retain the cue; affected
canonical content IDs consequently change. Historical receipts remain historical
evidence and must not be silently rewritten. This lexical repair does not resolve
event ownership or make the family exporter assign temporal semantics.

[legal_temporal_deadline_interpretation.py](../../ipfs_datasets_py/logic/autoformal/legal_temporal_deadline_interpretation.py)
provides `build_deadline_requests`, `prepare_deadline_interpretation`, and
`validate_deadline_interpretation`. It authenticates the same occurrence and
proposer receipts as the until route, with a separate versioned request inventory.
Session captures include its complete digest in
`deadline_interpretation_requests_sha256`; qualification binds that inventory
without promoting a gate. Unsupported and excluded proposals remain visible.

This initial profile accepts positive numeric `not/no later than … days/hours
after …` surfaces. Meaning fields remain null until a caller supplies a complete
declaration. That declaration specifies distinct trigger/response atoms, a
response source span outside the qualifier, positive integer ticks per source
unit, inclusive window endpoints, and a temporal property scope. The response
anchor may precede or follow the qualifier, including fronted deadline clauses.
The caller also explicitly chooses that every trigger at or after evaluation
origin creates a response window, and that one response can satisfy multiple
overlapping windows. Source anchors do not establish legal ownership.

For an explicitly declared window of `N` ticks, the output means
`G(trigger → B_N(response))`, where `B_0(p) = p` and
`B_(n+1)(p) = p ∨ X(B_n(p))`. This expansion uses supported typed LTL and strict
TDFOL syntax; it does not pretend the parser accepts bounded `F[N]` notation.
The Lean property requires a response between each trigger tick and that tick
plus `N`, inclusive. No trigger makes this implication vacuously true; it does
not prove an event occurred or a legal obligation was discharged. Preparation
emits code but does not run Lake.

The expansion is limited to 30 ticks to respect the existing native renderer's
depth bound. Excessive windows are rejected, not truncated. Business/calendar
qualifiers, weeks/months/years, fractional conversions, exclusive endpoints,
deontic scope, and per-trigger response identity require additional profiles.
Plain day/hour text does not automatically establish a wall-clock conversion.
Real-source declarations remain unresolved pending reviewed interpretations.

## Source-separated actor recovery and scope diagnostics

`LegalNormIR.from_parser_element` can remove a heading that a parser included in
the subject when the source provides a separate heading, a full stop, and the
actor's modal clause. This narrow recovery requires an exact action interval and
a consistent support window. Actor and modal spans come from the same occurrence;
a later modal elsewhere in the section cannot supply them. Coercible numeric
bounds, conflicting source views, ambiguous action spans, quoted or bracketed
contexts, and intervening clauses cannot authorize this recovery. Existing
institutional-title safeguards still apply outside this path.

The recovered label updates both actor/subject span aliases and matching entries
in `actor_entities`, preserving other entities and their order. Explicit modality
and quality/review fields keep their existing precedence. A source span remains
a lexical grounding diagnostic: it does not establish that an explicit operator
agrees with the source or that the rule is legally correct. Unreviewed regression
fixtures must not become independent legal gold or supervised training targets
merely because this normalization succeeds.

Default capability diagnostics for `conditional_normative` check each represented
condition, exception, and override, along with the core slots and any mental
state. An exception-only rule is no longer penalized for an absent condition.
Explicit nondefault slot requests retain their existing behavior. The existing
conditional-family precedence is unchanged, as are cross-reference and qualifier
review blockers. Source-specific quality summaries retain their per-source slot
requirements and also expose nested prover-target, corpus, and provenance
diagnostics, consistently with the aggregate summary.

For training evaluation, report these diagnostic corrections separately from
held-out decoder accuracy. They do not train or qualify an 8D, 384D, or 768D model,
attest source semantics, or execute `lake build legal`.

## Conditions around citations and procedure source spans

A structured condition before a fronted `notwithstanding section N.N` clause
can survive the numeric periods in that citation. Recovery verifies the full
source/support relationship and condition and override text/span aliases before
relaxing those specific sentence boundaries. Genuine sentence breaks, unrelated
clauses, quotes, and inconsistent source records remain outside this recovery.
The approval condition in `Subject to approval, notwithstanding section
5.01.020, the Director may issue a variance` therefore remains a formula
antecedent. Its presence prevents the existing override-only clearance from
marking the formula ready.

Persisted `pure_precedence_override` readiness is also checked against current
IR scope. A recovered condition, exception, temporal qualifier, or changed
override count invalidates that cached clearance. Formula, decoder, and repeated
metric projections cannot use the old clearance to bypass the current review
requirement. A genuine pure override retains its established behavior. This
check is limited to the override-only resolution type; it does not establish a
general authentication contract for all historical readiness records.

Procedure extraction now reads mentions and relation spans from the original
parser source. It never appends the action to manufacture a second source
occurrence. A unique exact action occurrence and a supported operative verb or
noun construction determine the event owner. Thus inspection owns the receipt
and before-approval relations in the supported inspection example. Ambiguous,
missing, quoted, cross-clause, or unsupported ownership evidence produces no
inferred owner relation. Every emitted `raw_text` is the exact indicated source
slice; the existing event taxonomy still maps approval to issuance.

For a source with a recognized procedure-event mention, unmatched connector
candidates remain in `procedure.unresolved_event_relations` with exact text,
spans, and a reason. These records assign no event owner or anchor. Clear scalar
duration/date anchors remain in the temporal inventory. The compiler's existing
unsupported-procedure guard therefore remains active when ownership is unknown.
The retained waiver example now abstains consistently on both its original
source and its decompiled text, rather than relying on an erroneous self-relation
to block only the second parse. Historical receipts remain unchanged.

These changes preserve parser action text and the temporal inventory. Existing
procedure exports distinguish trigger prerequisites from `before`/`after`
ordering provenance. That provenance does not supply a temporal interpretation,
and local formula readiness does not attest complete procedure semantics. Keep
source-grounding checks, reviewed semantic targets, decoder accuracy, and native
Lean checks as separate evaluation results.

When a procedure anchor occupies the same source interval inside an already
rendered deadline, the decoder renders that wording once and retains its
procedure provenance. Distinct occurrences or anchors remain separate. Removing
the temporal slot loses the duration while retaining an independently recorded
procedure anchor; the decoder cannot reconstruct the missing duration from it.

## Formula qualifier limits and readiness

The legacy deontic formula renderer includes at most three distinct substantive
condition predicates and three distinct exception predicates. The IR and decoder
can retain more. A formula that loses a predicate at either limit now carries
`formula_condition_cap_exceeded` or `formula_exception_cap_exceeded`, with
`proof_ready=false`, validation and repair required, and no deterministic
clearance. The formula string remains available for inspection; its readiness
record must accompany it when selecting proof or training targets.

Omission accounting follows the renderer's normalized predicate deduplication.
Repeated aliases of a represented predicate do not consume extra capacity or
produce false omission records. Each source occurrence of an actually omitted
predicate retains its own span. This check concerns the deontic renderer's caps;
it does not establish completeness for other frame renderers or resolve external
references and quoted or coordinated scope.

Canonical and formal exports, proof obligations, repair queues, decoder
validation, syntax summaries, and repeated metric projections preserve these
blocks. Historical parser readiness and cached deterministic clearances cannot
override them. The parser's original readiness remains separately visible as
historical evidence. Syntax acceptance and complete natural-language decoding
do not establish that the capped formula preserves all qualifiers.

## Reference qualifiers and cached readiness

Current formula records check reference-bearing conditions, exceptions, and
applicability scope before accepting parser or cached readiness. Unsupported
scope produces `formula_external_applicability_unresolved`,
`formula_reference_condition_unresolved`, or
`formula_reference_exception_unresolved`. These blockers require validation
and repair and clear deterministic readiness. Missing warning lists or missing
cross-reference inventories cannot waive a reference qualifier still present
in the IR. This contract covers recognized typed citations and reference-only
forms; it does not recover qualifiers lost earlier in parsing.

The parser preserves supported numeric section lists such as `sections 552,
553, and 554` as a complete qualifier. Each member has its own exact source
slice and inherits the section kind where the label is omitted. Citation-internal
commas do not end the qualifier; the following operative clause remains outside
it. Nearby durations and substantive text are not invented citation members.
Retaining that text can require validation even when the numbered references
have matching document headings. This handling does not expand ranges or
establish the legal effect of any referenced provision.

The supported local self-reference and pure same-document reference contracts
remain separate from generic reconstruction-warning clearance. Mixed
substantive and reference qualifiers require review until a dedicated combined
resolution contract exists. A matching citation records reference provenance;
it does not establish the legal effect of the referenced provision.

Same-document metadata must be noncontradictory and cover each required
citation. A section-number prefix or one member of a citation list is
insufficient. Unsupported reference kinds, external document scopes, and
conflicting resolution flags cannot supply clearance. Persisted resolution
names must be checked against the current scope and qualifiers.

The export and metric paths retain these current-formula blockers just as they
retain qualifier-limit blockers. Missing or duplicate source IDs do not permit
a row to borrow another row's cached readiness or reference projection.
Formula text remains available as a scaffold with its readiness record; these
checks do not qualify model weights or supply reviewed legal interpretations.

## Inline parenthetical exceptions

A balanced, unquoted `except` or `unless` parenthetical immediately after a
recognized modal can be separated from the following operative action. For
example, `shall (except as provided in section 552) publish notice` retains
`publish notice` with its own source span and keeps the exception and citation
as separate source-bound records. The modal and its negation remain intact.
Unresolved references still require validation after action recovery.
Recognized inline exceptions whose action and exception spans cannot be bound
receive `formula_inline_exception_action_unresolved`. Current formula, decoder,
and metric records retain this blocker despite cached readiness clearance.

Other parenthetical positions, unrecognized interrupters, quoted norms,
unbalanced delimiters, nested exception operators, and unsplit tails containing
a second independent duty remain outside this recovery contract. The explicit
semicolon scopes described below can separate supported duties before recovery.
A literal `not`
after the closing parenthesis stays in the action; recovery does not invent a
different modal span across the parenthetical. These source repairs require
fresh parsing; they do not certify previously cached parser rows or trained
decoder weights.

## Explicit semicolon duty scopes

Top-level semicolons can separate clauses when each clause has one explicit
actor and recognized modal. An optional `and` after the semicolon is supported.
Each row retains the entire original sentence, a distinct source-bound clause
support span, and local actor, modal, action, qualifier and reference spans.
Procedure and penalty enrichment uses the same local source window. A lowercase
actor cannot make modal recovery borrow a neighboring duty's source span.

`The Secretary shall publish notice; the Clerk shall file the report unless
approval is denied` produces two duties, with the exception attached to the
Clerk's duty. Immediate supported inline exceptions can also be recovered within
each clause. A leading condition on the right-hand clause stays with that
clause; a sentence-leading qualification that might govern both clauses is
outside this splitting contract.

For recognized semicolon layouts, `formula_duty_scope_unresolved` blocks current
formula, export, repair and metric readiness when core evidence crosses a duty
boundary or recognized qualifier/reference evidence is missing, altered or
attached to the wrong clause. Saved readiness cannot waive these checks.
Actor, modal, action and their spans must match a fresh deterministic parse of
the local clause. An arbitrary source substring or a changed modal operator
cannot supply core evidence merely because its span lies inside that clause.
Qualifiers are checked against their local source spans and inventories; this
does not resolve the legal meaning of referenced provisions.

Bare conjunctions, shared actors, malformed grouping and ambiguous shared
conditions retain their previous parsing behavior. Repeated-modal disjunctions
receive the separate readiness check below; there is no universal coordination
parser or readiness guard. Nested exception scope remains
unresolved under the existing inline-exception blocker. These changes improve
source-target construction and validation; they do not measure model accuracy
or qualify any 8D, 384D or 768D decoder weights.

## Unresolved alternative duties

Recognized top-level `or` between repeated modal duties must not qualify as
independent obligations. For example, `shall publish notice or shall file the
report` can still expose two diagnostic formula scaffolds, but both receive
`formula_coordination_scope_unresolved`. The check also covers an explicit actor
on the right and `; or` alternatives. It does not choose inclusive versus
exclusive alternatives or decide how deontic operators distribute over them.

`coordination_scope_evidence` retains exact source spans and text for the group,
its connectors and member modals, and the containing scope. Mixed `and`/`or`
coordination blocks the containing region without assigning precedence. Plain
semicolons and sentence boundaries bound independent regions. An unrelated norm
can remain clear only when its core fields and spans match its own source
support; moving cached spans or changing an operator cannot supply clearance.
Nested procedure occurrences also participate in scope checks. Procedure values
claimed by an independent duty must match local source-derived evidence; removing
their spans cannot hide a procedure copied from an alternative duty. This checks
ownership of claimed procedure records, not completeness of legal interpretation.

Formula, canonical, proof, repair and decoder records carry this evidence when
present. Readiness and repeated metric projection preserve the blocker despite
cached clearance, absent parser warnings or duplicate source IDs. Fresh parser
rows also carry `disjunctive_duty_scope_unresolved`, which the standalone text
decoder retains as a warning. Standalone decoded text and string-only formula
APIs are diagnostic scaffolds; use the readiness-bearing record APIs before
admitting a training target or proof candidate.

This is a lexical source contract. Object and citation lists, quoted or
parenthesized alternatives, subordinate clauses, unrepeated modals, malformed
delimiters and coordination lost during earlier segmentation remain outside it.
Their existing behavior is not certified by the absence of this blocker. The
readiness check excludes recognized unresolved targets. The separate candidate
and declared-scope APIs below provide an explicit representation for supported
groups while retaining their legal interpretation gates.

## Grouped coordination candidates and declared scope

The source grouping API in `logic.deontic.coordination` retains one candidate
per recognized alternative group, with separate actor, modal and action evidence
for each member. An implicit actor points to the earlier explicit member and
its original source span. Candidates keep their source digest and exact group,
connector and containing-scope coordinates. Deserialization rebuilds the
expected record from the original source; rewriting a digest cannot authorize
changed members, spans or readiness flags.

The initial structural profile supports two through eight plain branches.
Qualifiers, references, time and procedure clauses, object coordination and
mixed `and`/`or` scope retain unsupported candidate evidence. Each candidate
requires interpretation, including structurally complete groups.

`logic.autoformal.legal_coordination` requires three explicit caller choices:
modal scope, connective, and actor binding. `modal_over_actions` places one
shared modal over the alternatives and requires a common actor and operator.
`disjunction_of_norms` joins complete member norms and can retain different
actors or operators. The current connective is inclusive `or`; exclusive
alternatives need a separate contract. `universal_actor_predicate` declares the
quantified actor-predicate convention. Actor labels use whitespace/case
normalization and a leading `the` is removed for symbol identity; this is a
lexical convention and does not resolve real-world entity identity. Action
punctuation remains part of predicate identity, preventing sanitized names from
silently merging distinct source actions.

For example, an authored interpretation can be compiled as follows:

```python
from ipfs_datasets_py.logic.deontic.coordination import build_coordination_groups
from ipfs_datasets_py.logic.autoformal.legal_coordination import (
    interpretation_skeleton, compile_coordination_group, reconstruct_compiled_group,
)

source = "The Secretary shall publish notice or shall retain records."
group, = build_coordination_groups(source, source_id="authored:example")
declaration = interpretation_skeleton(group)
declaration.update(
    modal_scope="modal_over_actions",
    connective="inclusive_or",
    binding_profile="universal_actor_predicate",
)
record = compile_coordination_group(group, declaration)
assert record["structure_compiled"]
assert record["family_validation"]["passed"]
assert not record["proof_ready"]
assert reconstruct_compiled_group(record) == group.scope_raw_text
```

A complete declaration produces a strict deontic/TDFOL formula, its exact native
AST, collision-safe symbol mapping and a Lean definition through the existing
native emitter. Missing choices and unsupported structure produce an empty
logical artifact with blockers. Reconstruction validates the full compiled
record against its source and declaration, including AST, symbols and producer
versions, then returns the original source scope. This uses retained source
evidence; it is not a measurement of reconstruction with the source withheld.

The generated Lean definitions keep modal interpretation as a parameter.
Constructed two-world checks demonstrate that `O(A or B)` can hold while both
`O(A)` and `O(B)` fail. Successful syntax or `lake build legal` checks do not
review a caller's legal interpretation. Compiled group records continue to
require validation, and existing individual branch records keep their blockers.
The new records provide explicit candidate structure for future decoder targets;
they do not qualify training weights or establish reviewed US Code meanings.

## Decode grouped semantic IR with the original passage withheld

`coordination_decode_request_from_compiled` first revalidates the complete
source-bound artifact and then exports a closed semantic request. The request
contains only the schema, explicit modal scope, connective, binding profile,
and two through eight ordered actor/modality/action members. The original
passage, source IDs, digests, offsets, reference formula and reference AST are
excluded. Actor and action labels intentionally remain semantic IR and can
contain words from the source; this is not a latent-only reconstruction test.

```python
from ipfs_datasets_py.logic.autoformal.legal_coordination import (
    coordination_decode_request_from_compiled,
)
from ipfs_datasets_py.logic.deontic.coordination_decoder import (
    decode_coordination_request,
)
from ipfs_datasets_py.logic.autoformal.legal_coordination_evaluation import (
    evaluate_coordination_outputs,
)

request = coordination_decode_request_from_compiled(record)
decoded = decode_coordination_request(request)
assert decoded["context"] == "source_withheld_semantic_ir"
assert decoded["formula"] == record["formula"]
assert not decoded["proof_ready"]

# In a learned experiment, candidate_outputs must contain actual predictions.
# This identity check demonstrates the interface, not a model accuracy result.
candidate_outputs = [request.to_dict()]
report = evaluate_coordination_outputs([request], candidate_outputs)
assert report["all_outputs_agree_with_target_ir"]
assert report["model_calls"] == report["training_calls"] == 0
```

The decoder uses a fixed grammar to render a strict deontic formula, native AST,
Lean definition and explicit controlled scope text. It does not recover the
original legal wording or infer the caller's modal scope. The narrow lexical
profile rejects embedded modals, qualifiers, compound actions and metadata
fields; it is not a general detector of covert information in labels. Duplicate
members and their order remain observable. Shared-modal requests with differing
actors or modal operators fail rendering rather than being repaired.
Source groups with labels outside this narrower decoder profile retain an empty
artifact with `group_decoder_profile_unsupported`. The conservative lexical
checks also exclude otherwise ordinary labels such as `inspect tin can` or
`file section headings`; these are coverage limitations, not reviewed semantic
errors. Source evidence remains reconstructable and is never silently rewritten.

The evaluator holds typed target requests separately from candidate outputs.
Malformed, missing and extra predictions count as failures. Empty reference
sets cannot pass. Actor, modal, action, scope, member count, formula and native
AST agreement are reported separately. Exact structured request values are
distinct from normalized semantic agreement; neither measure attests legal
equivalence. Development and heldout engineering fixtures must be disjoint by
source and lexical labels, and independently reviewed legal references need a
separate provenance and interpretation review.

The inspected retained 8D and 384D formula heads emit one canonical rule; the
768D span head is source-conditioned and also emits individual rules. Their
current codecs do not represent grouped modal scope. The vector-reconstruction
autoencoders are a separate interface. A future grouped learned head therefore
needs a versioned codec for the request fields, a member-count/order objective,
and explicit scope supervision. Train it on development sources only, keep
unsupported structures as abstentions, and evaluate actual predictions through
this renderer and evaluator before native checks. Report latent-only and
source-conditioned runs separately for each dimension. Engineering identity
and mutation tests provide a decoder baseline; they do not establish trained
accuracy, qualify existing weights or justify publishing replacement weights.

## Experimental learned grouped span head

`logic.formalization.autoencoder.legal_grouped_span_decoder` adds a separate
source-conditioned training head. A fixed UTF-8 byte alphabet and token BiGRU
feed eight ordered member queries. Learned heads predict member count, modal
scope, O/P/F operators and actor/action start and end positions. The predictor
copies only its predicted spans and validates the resulting closed semantic
request. It does not consult the source parser, source groups, target spans or
reference requests during inference. Position and length features are generic
source features, not semantic parsing rules.

The caller supplies the modal scope explicitly. Missing or unsupported scope
declarations abstain before a forward pass; a learned scope prediction that
disagrees with the declaration is blocked. This measures declaration
preservation, not inferred legal scope. Invalid spans, lexical-profile
exclusions and shared-modal actor/operator mismatches retain failed outputs.
No target or parser fallback supplies missing fields. Ordinary source vocabulary
can still fall outside the current narrow semantic label profile.

Use `SpanDecoderConfig` and `GroupedSpanDecoder` to construct a seeded CPU head,
then `make_grouped_span_optimizer` and `train_grouped_span_step` with typed
`GroupedSpanExample`/`GroupedSpanTarget` labels. Labels hold exact half-open
character spans; training rejects token-boundary misalignment instead of
approximating it. Inference uses only
`predict_grouped_span_decoder(model, source_text, modal_scope)`. Pass its actual
`request` values, including failed `None` outputs, to
`evaluate_coordination_outputs`. Retain raw predicted token positions and score
source-span occurrences separately: duplicate labels can agree as semantic IR
while pointing to the wrong source occurrence.

`save_grouped_span_checkpoint` and `restore_grouped_span_checkpoint` serialize
closed finite JSON model and AdamW tensors, configuration, numerical progress,
tokenizer profile and exact producer versions. They verify shapes, inventory,
optimizer progress and the complete checkpoint seal. Restore uses no pickle.
Checkpoints contain no source passages or training targets. A changed producer
requires an explicit versioned migration or the original verified source.

This first head is initialized independently and does not consume the 8D,
384D or 768D autoencoder vectors or reuse their weights. Results from authored
engineering fixtures are source-conditioned model measurements; they cannot
qualify those latent decoders or independently reviewed US Code meanings.
Training, checkpoint selection and final evaluation require separate source
groups, with every interpretation of one source kept in the same split.
Report blocked outputs and full denominators, and keep final evaluation out of
checkpoint selection. Syntax/native builds, legal equivalence and learned
source fidelity remain separate observations.

## Ordered-byte grouped head with learned profile abstention

`legal_grouped_span_decoder_v2` preserves the published v1 implementation and
uses a separate checkpoint schema. Two byte convolutions encode ordered local
character neighborhoods before masked mean/max pooling and the token BiGRU.
Padding is masked after each convolution so padded-byte biases cannot change
real token features. This distinguishes the measured `shall`/`shlal`,
`must`/`msut` and `form`/`from` collisions; it does not prove an injective encoding
of every possible byte string.

Training examples add a required `supported` boolean. Supported examples retain
two through eight exact member spans. Unsupported examples carry an empty
member tuple and train only the source-support classifier. Here "unsupported"
means outside the current plain grouped-source profile: a single duty or a
qualified legal clause can be valid law while remaining outside that profile.
Count, scope, modality and pointer losses are masked on unsupported rows.
On all-negative batches, structural-head gradients remain absent, preventing
their Adam momentum or weight decay from updating those heads. The shared source
trunk still learns support, so predictions can change through that trunk.

Inference still receives only source text and an explicit caller scope. A
support probability below the fixed **0.5** threshold returns an abstention with
`learned_source_unsupported` and no request. Accepted inputs still undergo the
independent span and semantic-request checks. Missing scope abstains before a
forward pass. This learned decision does not certify source meaning or provide
universal detection of unsupported text.

V2 checkpoints verify mandatory shared/support Adam state at the global step
and structural state at its actual supported-batch count. Structural state can
be absent before the first supported batch. Save/restore retains exact numerical
continuation across negative and mixed batches; v1/v2 loaders reject each
other's schemas. Existing 8D/384D/768D runtime weights remain separate.

Evaluate supported targets and unsupported sources with complete denominators.
Report exact positive IR and source-span agreement, learned negative abstention,
incidental grammar blocking, and support classification separately. An always
abstaining model cannot pass positive fidelity. Reserve new final source groups
when an older holdout has been examined, and keep corrupted variants with their
parent source split. Caller-declared scope preservation and fictional grammar
checks remain distinct from independently reviewed US Code accuracy.

## Read failures without conflating them

- A low `metric_gate` score calls for compatible model/input inspection and possibly training.
- Failed `semantic_gate`, `family_syntax_gate` or `lake_gate` produces source-repair evidence; more feature epochs do not prove the deterministic compiler fixed itself.
- `source_rule_not_renderable` or `within_duration_not_renderable` records an unsupported Lean rendering scope. Do not replace the source with an easier theorem.
- `installed_lake_toolchain_missing` means the required local gate could not run.
- `heldout_samples_missing` or overlap means the selection panel is invalid; in-sample success is recorded separately.
- A producer-source mismatch means the evidence no longer matches the runtime. Preserve it and use a verified source snapshot/new state.

Qualification's model-metric pass intentionally uses an empty bridge list. Its `metric_evaluation.legal_ir_target_count` is zero and is labeled `embedding_metrics_only_not_a_legal_ir_evaluate`. The separate compiler/family/Lake observations do not turn that measurement into a bridge-on evaluation.

## API and implementation links

- [Execution gates and simple inference wrapper](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_paths.py)
- [Resumable qualification-only inference](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_inference.py)
- [Candidate qualification and fixed metric thresholds](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py)
- [Legal family syntax gate](../../ipfs_datasets_py/logic/autoformal/family_qualification.py)
- [Legal sample builder](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py)
- [Adaptive modal autoencoder](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py)
- [Structural modality feature inference](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_projection_features.py)
- [Training guide](legal_training.md), [API map](api_map.md), and [control plane and synchronization](control_plane_and_sync.md)

Documentation was checked against published dataset commit `3666ebad19422b8345ebe5432a1c02f26d2eba4c`. The minimal offline example was executed on the pinned canonical workspace without training, bridge target generation, Lake execution or downloads. Its shape/assertions were checked; its numerical values are intentionally not a quality baseline.
