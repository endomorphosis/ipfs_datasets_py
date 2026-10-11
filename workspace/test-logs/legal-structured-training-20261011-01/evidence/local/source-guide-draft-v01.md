# Explicit structured span training and statutory review recording

This contribution adds a separately identified training objective, a continuation
worker that resumes complete retained model and Adam state, and a recorder for
caller-declared statutory source/context reviews. The numerical comparison is
prepared; actual fitting, numerical probes and measured outcomes are pending in
this draft. No higher training or legal accuracy is established by preparation.

The [previous joint readout](legal_joint_readout_20261011.md) increased compatible
copied proposals from 1/8 to 6/8 per frozen decoder/control lane on eight exposed
US Code cases. Those counts measure exact copying, single-rule deontic shape and
nonoverlap. Some candidates have visibly poor legal roles. They supply a reason
to test geometric training terms, not semantic supervision for the statute.

## Three separate owners

| Owner | Responsibility | Boundary |
| --- | --- | --- |
| `logic/legal_ir/structured_span_objective.py` | Compute old CE plus optional order/overlap loss from one supplied head output. | Opens no model, calls no forward and admits no labels. |
| `logic/formalization/autoencoder/structured_span_continuation.py` | Fork a pinned warm parent, preserve complete Adam state and schedule, perform bounded explicit updates, and expose target-free inference. | Uses a distinct checkpoint schema and objective lineage; historical checkpoints remain unchanged. |
| `logic/legal_ir/statutory_review_recording.py` | Record source/context-bound caller declarations, exact agreement, evidence-byte integrity and separate declared adjudication. | Does not authenticate humans, resolve legal meaning, create a target or promote any admission mask. |

The existing retained span/continuation owners, raw384/native recipes, joint
selector and blank statutory packet remain separate. The new worker uses a
private temporary legacy topology view for restoration and greedy decoding;
it does not publish its trained state as a legacy checkpoint or change the old
optimizer owner's loss. No manager/default registration is added.

## What the objective means

The unchanged base loss is modality CE plus six equally weighted facet losses,
divided by seven. Each facet averages start and end pointer CE; optional facets
also include presence CE. Explicit absent pointer labels retain the old ignored
index behavior. A zero structure weight returns this CE directly and skips
structured computation, including its float64 accumulation.

For each present reference facet, independent start/end distributions define
an interval probability. The valid-order term is the negative log probability
of `start <= end`. The overlap term is the probability that intervals from two
present fields overlap, after each field's distribution is normalized over valid
intervals. For inclusive token intervals,
`P(overlap) = 1 - P(end_a < start_b) - P(end_b < start_a)`.
The implementation obtains these probabilities from interval marginals and
strict prefix sums rather than enumerating every pair of intervals.

Order loss averages present fields within a row; overlap averages their unordered
pairs. Row averages then give the batch values. The planned combined loss is:

```text
total = CE + structure_weight * (validity + overlap) / 2
```

Reference presence gates these terms. A model cannot lower the structure penalty
by predicting that a labeled qualifier is absent. Structured softmax crops each
row to its actual token count; padded logits remain part of the preserved CE
arithmetic. Masked log probabilities and valid-pair normalization use float64
after CPU float32 heads. Valid mass may underflow to zero in diagnostics while
the log-mass loss remains finite. Extremely large finite float32 logits may still
overflow the inherited float32 CE and are refused as a nonfinite objective.

These terms encourage order and separation. They do not determine actor/action
roles, modality truth, qualifier scope, full-context meaning or logical fidelity.
Correct syntax and nonoverlap cannot substitute for those labels.

```python
from ipfs_datasets_py.logic.legal_ir import structured_span_objective as objective

# torch, head_output and internal_batch come from the caller's admitted CPU run.
# head_output is the one existing forward's modality/presence/start/end dictionary.
losses = objective.objective_from_output(
    torch, head_output, internal_batch, structure_weight=0.1)
losses["total"].backward()  # the caller owns optimization and admission
```

`reference_geometry(records)` is an inert check of retained internal token/label
records, bounded to 32 rows and 256 actual tokens. It checks reference presence,
token geometry and nonoverlapping labeled intervals; complete source bytes and
legal authority are outside that record format. `probability_reference` is a
small scalar oracle for synthetic/saved pointer rows, without model or gradient
execution. Neither function independently reviews legal text.

## Equal continuation recipe

The selected warm parents are `raw384-1729/checkpoint-400.json` and
`source_only-1729/checkpoint-400.json` from the retained native-conditioning run.
Their original file SHA256 values are respectively
`21f4954e11dd482a65e5f1083d2f9cc074b817e049ec0f24ee71b15267a7eac0`
and `5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb`.
The raw384 parent consumes pinned cached GTE-small384 vectors. The source-only
parent uses the same source span topology with latent conditioning disabled.
These two parents are different states; each objective pair starts from its own
exactly equal parent model and optimizer, rather than treating all four arms as
identically initialized.

| Planned arm | Warm parent | Structure weight | Requested new updates |
| --- | --- | ---: | ---: |
| `raw384-1729-ce0` | raw384 | 0.0 | 32 |
| `raw384-1729-probability01` | raw384 | 0.1 | 32 |
| `source_only-1729-ce0` | source-only | 0.0 | 32 |
| `source_only-1729-probability01` | source-only | 0.1 | 32 |

Each fork preserves all parent model tensors, all Adam first/second moments and
parameter step counters, learning rate 0.001, batch size 12, seed 1729, epoch 4
and row cursor 192. The inherited continuation counter is 400; after a complete
32-update arm, the new lineage reports inherited 400, new 32 and absolute 432.
Earlier counters embedded in historical source parents remain separate and
unchanged. The deterministic schedule uses the retained seed-plus-epoch shuffle;
all four arms must consume the same ordered next 32 batches. A partial fit keeps
its actual committed prefix and cannot support an equal-step comparison.

Preparation exports only the exact ordered 1,152 TRAIN and 96 TUNE rows whose
canonical manifests match both warm parents. These are authored construction
targets with cached native384 contexts, already exposed in earlier work. They
are not independently reviewed legal targets. Challenge/OOV labels are excluded
from this fit and are not reassigned to TRAIN. TUNE supplies external authored
loss and source-only greedy reconstruction diagnostics, without optimizer
updates. Previously reported tuning reconstruction is already at the 96/96
ceiling; this 96-row exposed set cannot establish higher independent accuracy.
Current baseline and post-fit counts must be measured and retained separately.

The new checkpoint schema is `objective-resumed-source-span-checkpoint/v1`, with
lineage `objective_resumed_source_span_v1`. Its outer objective and initialization
are authoritative. Nested historical `loss` and `from_scratch` strings describe
the old constructor/topology; they do not relabel this resumed objective. The
current state stores model/Adam tensors without embedding source/target examples.

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    structured_span_continuation as worker,
)

# parent, TRAIN and TUNE were read from separately verified exact file bindings.
# These API pins are canonical digests, distinct from the original file SHA256.
entry = worker.prepare_checkpoint(
    parent, TRAIN, TUNE, structure_weight=0.1,
    expected_parent_sha256=worker.digest(parent),
    expected_training_sha256=worker.digest(TRAIN),
    expected_tuning_sha256=worker.digest(TUNE))
schedule = worker.next_batch_ids(entry, TRAIN, steps=32)  # inert preparation

# Explicit numerical operations belong only in the admitted guardian child.
trained = worker.train_decoder(entry, TRAIN, TUNE, max_steps=32, max_seconds=32)
saved = worker.save_checkpoint(trained["checkpoint"], new_checkpoint_path)
runtime = worker.open_checkpoint(trained["checkpoint"])
raw_report = runtime.infer(source_only_rows, control="none", capture_scores=True)
```

Inference rows are exactly `{id, source_text, latent}`; target/reference fields
are refused. Controls are `none`, `zero`, `disabled` and `rotate`. A temporary
hook captures all scores from the same greedy forward and is removed on success
or failure. The authoritative outer report identifies the new objective/state;
original greedy rows remain distinct from any subsequent joint selection.
Inference checks model/Adam/RNG custody and performs no optimizer updates.

## Experiment limits and pending outcomes

The planned four-arm child uses the unchanged guardian envelope: 2 CPU slots,
1,536 MiB sampled RSS allowance, one child, 200,000,000 storage bytes and a
300-second wall deadline. Each arm requests at most 32 new updates with a
32-second soft training allowance; the worker checks time before each batch.
Restoration, a forward/backward batch and checkpoint packing are not individually
interruptible. The guardian's outer wall limit and cooperative RSS accounting
remain distinct from a kernel quota or absolute-peak measurement. Existing or
foreign claims are not released to create capacity.

The numerical child must verify independently pinned source, model, data,
runner and protocol bytes; install process/network/encoder denials; prepare
all four schedules before opening models; and save each fitted state/report
durably before later diagnostics. Original combined corpus/context files,
challenge/OOV targets and the statutory-review packet/recording are forbidden
inputs after preparation. Native vectors are reused without new encoding.
No state is selected or promoted based on these exposed diagnostics.

Actual fit and numerical-probe results are **pending** in this draft. The root
run must fill this table from preserved attempt receipts, including refusals,
truncated evaluation and failures. Requested steps are not completed steps.

| Evidence | Current status |
| --- | --- |
| Same-output old CE versus zero-weight CE and gradient parity | Pending numerical probe |
| Oracle/Torch valid mass, pair overlap and finite backward | Pending numerical probe |
| Mixed-length cropped-padding invariance | Pending numerical probe |
| Four exact 32-update arms and equal actual batches | Pending actual fit |
| Current baseline/post-fit authored TUNE loss and reconstruction | Pending measured comparison |
| Real8 greedy/joint outputs under four latent controls | Pending post-fit diagnostics |
| Test execution, resource admission and final custody | Pending root validation |

The planned real-law diagnostic has eight exposed source occurrences, four
new states and four controls: 128 repeated dispositions, not 128 independent
statutes. Joint decoding uses fixed learned presence/modality, top eight span
candidates per facet and a 50,000-node budget. It must retain raw outputs,
truncation/refusal denominators and pool-versus-full-domain limits. Neither
more compatible candidates nor smaller training loss establishes legal fidelity.

## Statutory declarations are now recordable; admission remains pending

The prior immutable packet supplies eight physical occurrences: 2,070 selected
UTF8 bytes and 148,931 complete raw-section context bytes. Full-packet canonical
SHA is `73fbfd8731ea3b11ec8a49a4f8b21ba2f80a0f34009d744c301540417d559054`;
embedded body SHA is
`2c52ca09ae2178f61e95b39c272da95cffaaa1e9f76cf9e917629f7b265b6b5e`;
exact original file SHA is
`bf42fb6a854d0a5b8f77e09b1bfd6e1fad4a6bf47323dd246826774b9bf6dc06`.
These three identities have different scopes. The parent packet's 168 review
and context slots stay null and its training/evaluation masks stay zero.

The new recorder accepts a separate
`statutory-source-context-review-submission/v1` declaration, bound to the
immutable packet, selected text, physical occurrence, full context artifact and
character selector. It types normative eligibility, definitions, multiple rules,
ordered O/P/F interpretations, source-role/trigger anchors, qualifier attachments,
context sufficiency, operative/editorial boundaries and unresolved dependencies.
Null means unanswered; explicit empty values where allowed mean a declared
absence. Multiple rules, repeated surfaces, overlaps and multiple qualifiers are
preserved rather than flattened into the decoder's one-rule profile.

```python
from ipfs_datasets_py.logic.legal_ir import statutory_review_recording as recording

# resolver maps externally selected content references to verified local paths.
packet_pin = recording.digest(blank_packet)
guide = recording.submission_guide(
    blank_packet, expected_packet_sha256=packet_pin, artifact_resolver=resolver)
pending = recording.record_reviews(
    blank_packet, [], expected_packet_sha256=packet_pin, artifact_resolver=resolver)
replay = recording.validate_recording(
    pending, blank_packet, [],
    expected_packet_sha256=packet_pin, artifact_resolver=resolver)
```

The actual eight-item pending receipt has zero submissions, zero authenticated
human reviews, zero targets and zero training/evaluation admissions. Generating
a blank guide or recording an empty list is not completed legal review.
Callers supply declarations separately; the API does not invent them.
`parse_json_bytes` rejects duplicate keys, invalid UTF8 and nonfinite JSON.
Per-item source anchors use selected-source Unicode characters, while full-section
boundary anchors explicitly use complete-section characters and the context hash.

Exact agreement compares filled interpretation/context fields, ordered rules,
anchors and scope. Identity, time, free notes and evidence references do not
establish agreement or independence. The recorder retains partial submissions
and disputes without selecting an answer. Evidence SHA/size and opening/closing
bytes identify supplied artifacts without authenticating their contents, source
currentness, people, independence or blindness.

`record_adjudications` binds separate caller-declared decisions to the exact
recording and complete declaration hashes. Declared adjudicator IDs cannot match
any recorded non-null reviewer ID, including partial reviewers. Accepted-reference
cardinality and unresolved scope are checked, but actual independent adjudication
remains pending. `assess_declaration_geometry` assesses one explicit complete
normative declaration against the unchanged flat copied-span profile; successful
geometry never creates a target or promotes a mask.

The authored empty-context recorder, official HTML review profile and synthetic
alignment signature verifier are incompatible profiles, not drop-in aliases.
A real admission owner still needs externally verified review identity and
independence, adjudicated source meaning, target/derivation coverage, exposure
policy and applicable training/evaluation rights. Signature math alone would
not supply those facts. Every recorder output keeps weak/strong fit, contrastive,
proof and fidelity-evaluation masks zero and every gold/authority flag false.

## Joining the existing effort

The intake review observed source main
`cdae06198a229760ca139d48f9e311e80d0df8c6` and root main
`a3cea4aa2d9317ed2631392545aeb2df1d8ceb49`. The prior normal merges,
[source PR1282](https://github.com/endomorphosis/ipfs_datasets_py/pull/1282)
at `61515a171c4c19fd5d977c5e5e1263a8c172c82c` and
[workspace PR548](https://github.com/endomorphosis/lift_coding/pull/548)
at `640dd608c397897053688585c03b4938674f4523`, are ancestors of those respective
observed main heads. New main already contains other agents' source-unit
provenance links and a separate experimental learned NumPy selector over the
shared Legal384 projection. Those findings stay in their own numerical/input
contracts; they cannot relabel raw GTE384 pointer states or prove this objective.

The bounded review found all 21 selected source and nine root remote branch heads
already represented in main. Five older publication/recovery histories diverge;
they are retained rather than importing large incompatible snapshots wholesale.
Uncommitted work was not inspected, so this is not a claim that other agents
have no active progress. All 24 selected retained source-owner byte identities
match the prior pins. Dirty canonical root/child HEAD and index custody are
separate from these isolated worktrees. Final publication must reconcile any
newer main commits, preserve other agents' files and keep the other eight root
gitlinks against the actual merge parent.

## Remaining semantic, dimension and logic gates

The bounded assay uses only raw384 conditioned and source-only span states.
It executes no genuine learned8D or native768D fitting. Core/trained384 recipes,
raw GTE384, historical8D features and native768D remain distinct contracts;
width alone cannot make them compatible. Complete raw sections are available
for review but are not learned full-context inputs in this decoder.

One flat copied O/P/F rule cannot express definitions, multiple rules, variable
binding, paraphrase, cross-reference reasoning or discontinuous qualifier scope.
Broader FOL, temporal/deontic, DCEC/CEC, frame, knowledge-graph and prover views
need typed lowering contracts and source-preserving semantic evidence. Geometry
loss does not qualify these families. Unsupported meaning must remain explicit
or be refused, rather than discarded to pass a syntax check.

No `lake build legal` is executed here. A later Lean gate needs a pinned theorem
environment, generated declarations without unsound placeholder proofs, exact
source/declaration bindings and retained compiler receipts. Compilation checks
the chosen formal environment; independent review must still establish whether
the declaration expresses the statute. Legal-role supervision, authenticated
adjudication, grouped exposure-aware evaluation, semantic abstention and richer
representations remain prerequisites for a real US Code fidelity claim.
