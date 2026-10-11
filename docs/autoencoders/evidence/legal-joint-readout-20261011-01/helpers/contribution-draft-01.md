# Joint copied-span readout and physical US Code review

The opt-in joint selector raises compatible copied proposals from1/8 to6/8
for each frozen decoder/control lane on the eight exposed US Code development
spans. Original model output remains separate and unchanged. This experiment
establishes source copying, canonical single-rule deontic syntax and nonoverlap;
it does not establish correct legal roles or higher semantic accuracy.

## What is implemented

`logic/formalization/autoencoder/retained_span_score_capture.py` attaches a
temporary observational forward hook to an already opened retained span model.
It captures complete modality, optional-presence and start/end logits from the
same existing inference forward. It neither opens nor invokes a model. The hook
is removed on success and failure. The raw report is saved before capture
validation, and the finalized score sidecar is saved before joint search.
Failed diagnostics cannot silently replace an original output with a repaired
candidate. Requested but unsubmitted rows remain in the denominator.

`logic/legal_ir/joint_span_selection.py` consumes the closed
`joint-source-span-scores/v1` packet. It keeps the learned modality and every
optional-facet presence decision fixed, retains up to8 spans per present facet
for this assay, and searches for a nonoverlapping assignment. Start/end pair
scores use float32 arithmetic; the joint objective uses the disclosed float64
sum. Token order resolves ranking ties, while ambiguous complete assignments
are refused. Search exhaustion and absent compatible assignments are explicit.
The result declares pool truncation and distinguishes retained-pool optimality
from full-domain optimality. It never drops a learned qualifier to avoid a
conflict. This is a new readout policy, not the original greedy output.

`logic/legal_ir/statutory_source_review.py` creates and validates a distinct
blank physical-source/context packet. It replays raw section/provenance hashes,
character and UTF8 byte selectors, physical occurrence identities and source
snapshots at opening and closing. Full context text is embedded once per unique
raw section. Exact and normalized textual duplicate groups are retained without
merging physical occurrences. The accompanying eight-item packet contains2070
selected-source bytes and148931 full-context bytes. Legal roles, normative
interpretations, context decisions, reviewer identities and targets are blank;
all training and evaluation masks remain0.

The old authored review schema and official HTML context profile are not aliases
for this raw archive profile. Its geometry API accepts a separate explicit
caller-declared reviewed proposal and checks interval representability only.
It does not authenticate a reviewer, record a completed review, create training
admission or establish semantic representability. A filled-in template alone
does not admit training. The provenance replay verifies local archived views;
it does not reopen the original374MB export or authenticate current law.

## Frozen comparison

The same existing raw384 and source-only warm-start checkpoints were restored
under the existing guardian. Cached native GTE-small384 paragraph vectors were
reused; full section text was for review and was not a decoder input. The recipe
compatibility audit permits raw384 only and cannot turn these vectors into
`core384`, `trained384`,8D or768D inputs. Each checkpoint ran under none, zero,
disabled and rotated latent controls. No encoder ran, no optimizer updated,
and no checkpoint or recipe was selected.

| Checkpoint | Control | Original copied proposals | Joint copied proposals | Joint refusals |
| --- | --- | ---: | ---: | ---: |
| raw384 | none |1/8|6/8|2/8|
| raw384 | zero |1/8|6/8|2/8|
| raw384 | disabled |1/8|6/8|2/8|
| raw384 | rotate |1/8|6/8|2/8|
| source-only | none |1/8|6/8|2/8|
| source-only | zero |1/8|6/8|2/8|
| source-only | disabled |1/8|6/8|2/8|
| source-only | rotate |1/8|6/8|2/8|

All64 original `decoder_row` payloads equal the previous frozen comparison in
canonical JSON bytes, including the56 overlap refusals. The joint readout
selects48 repeated instances; those are eight source cases evaluated repeatedly,
not64 independent legal examples. The two refusals in every lane are1USC112b
and10USC101, with no compatible assignment in the retained pool. All64 searches
are truncated to top8 pools; none exhausts the50000-node budget. Full-domain
optimality is not established.

All eight raw384 score packets change under each latent control. Compared with
the normal latent input, zero changes one selected canonical IR, disabled
changes two, and rotate changes none. Dispositions do not change. Source-only
scores and candidates are identical under all controls. This demonstrates that
the captured scores reflect conditioning, without demonstrating that conditioning
helps legal fidelity.

For example,1USC2 produces actor `or any other`, action `subdivision` and modality
P. They are source substrings in a valid shape, but are visibly poor candidates
for the statute's definition. A higher compatible-output count therefore cannot
serve as the model's accuracy score. Both retained decoders still need reviewed
legal-role supervision and an abstention policy informed by source semantics.

The unchanged resource envelope was2CPU/1536MiB/one child/200MB/300seconds.
The guardian completed in57.75seconds, observed nine model-phase RSS samples
with sampled peak681361408bytes, reaped the child and released only its own
reservation. Sampling is cooperative, not a kernel hard quota or absolute peak.
All509 pre-existing reservation bodies equal the closing snapshot; the sole
new record is this released attempt. The exact independent protocol review is
SHA-named and preserved unchanged before and after admission. The older
native-cache review-byte custody gap remains historical and unrepaired.

## Next training experiment

The existing span model trains modality, presence and independent start/end
heads. The joint assay exposes their compatibility gap without modifying that
training lineage. A separately identified candidate objective should retain
those losses and add a reviewed-gold structured term. For a source with admitted
role intervals, put the gold assignment in the training candidate pool and
compare its summed score with incompatible or incorrect role assignments using
a bounded structured margin loss. Do not inject gold into validation decoding,
use the generated joint candidate as its own label, or train the old checkpoint
in place. Record candidate construction, loss weights, curriculum, seeds,
optimizer state, effective steps and selection criteria with the new producer.

Before any such fit:

1. Obtain independent source/context review. Identify definitions and editorial
   material separately from O/P/F norms, adjudicate ambiguity, and authenticate
   reviewer identity and independence with an explicit completed-review workflow.
   The present API is a blank packet plus geometry aid, so recording/admission
   remains an implementation gap.
2. Mark exact representability. One flat rule with one contiguous copied value
   per facet cannot express multiple rules, definitions, variable binding,
   paraphrases or split/discontinuous qualifiers. Route these to a richer typed
   representation or refusal; do not discard meaning to meet this grammar.
3. Build grouped train/tune/held-out splits over physical section identity,
   exact/normalized text groups and cross-reference/definition dependencies.
   Preserve prior exposure. These eight development cases cannot qualify a new
   independent holdout. The public open-us-law inventory snapshot supplies
   jurisdiction counts, not independently reviewed US Code targets.
4. Compare unchanged greedy, this fixed-presence joint policy, and the candidate
   structured-loss decoder on the same admitted cohort. Score modality,
   actor/action/object roles, each qualifier and scope, whole-rule fidelity,
   contradiction and abstention calibration, with all refusals in denominators.
   Syntax, copying, proof success and fidelity must remain separate metrics.
5. Repeat source-only/correct/zero/disabled/rotate ablations. Extend8D and768D
   only through their genuine encoder/latent contracts, rather than padding,
   truncating or relabeling raw384 vectors. Set semantic selection thresholds
   before opening held-out labels and publish unchanged baseline weights beside
   any newly trained state.

## Logic-family and Lean gates

This selector emits the existing typed single-rule deontic representation only.
The shared family evaluator lists deontic, frame_logic, tdfol, knowledge_graphs,
cec, external_provers, decompiler, temporal and provenance evaluation views.
Those names alone are not evidence that this output lowers faithfully to every
backend. Each supported lowering needs an explicit typed source contract,
preserved scope/binding/provenance, backend syntax checks and independent
semantic tests. Refuse unsupported information instead of formatting it away.
Definitions and temporal/multiple-rule structure need richer LegalIR before
these families can be qualified.

Lean validation requires a pinned theorem/signature environment and generated
legal declarations without unsound placeholder proofs. Run `lake build legal`
for that environment and preserve source-to-declaration bindings and compiler
receipts. Compilation proves well-formedness/type correctness under that
environment; it does not prove the declaration matches the statute. No Lake
execution, broader family qualification, semantic admission or default promotion
is claimed by this experiment.

## Integration and evidence

This contribution adds separate source owners and leaves all24 selected retained
runtime/numerical owner bytes unchanged. Current public autoencoder branches
are already ancestors of the reviewed main effort; older diverged publication
recovery worktrees remain preserved. The normal source/root merges retain newer
US Code ancestry/source-unit provenance work and update only the owned dataset
gitlink, preserving the other eight root gitlinks.

The existing checkpoint bytes remain available in the immutable Hugging Face
[retained raw384/source-only release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/8279ea69452c0c72560211a1eda505ff1b1b5713/releases/20261011-retained-raw384-pointer-v1).
There is no new trained state to upload from this assay.

[Bounded evidence](evidence/legal-joint-readout-20261011-01/manifest.json) includes
raw outputs, full same-pass scores, separate joint results, review inputs,
source views, immutable reviews, resource receipts,452 passing inert tests and
preserved failed drafts. Raw weights and complete shared ledgers stay outside
the source evidence. Historical local paths document original custody, rather
than promising a standalone movable numerical environment.
