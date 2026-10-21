# Typed relational batch output diagnostics

This additive evaluator accounts for a complete, caller-declared population before comparing typed relational outputs. It preserves missing outputs, duplicate IDs, malformed observations, abstentions, explicit unsupported declarations and unavailable references. It reuses the [paired reconstruction diagnostic](legal_relational_reconstruction_v1.md) for valid comparable inputs. A successful pair cannot remove another occurrence from the batch denominator.

The corrected owner and a separate retained-input consumer have completed the native checks described below. Qualification covers authored engineering controls; it establishes no model prediction, training result, statutory accuracy or Lean build.

## Public interface

The owner is `ipfs_datasets_py.logic.autoformal.legal_relational_batch_evaluation_v1`. Its public import uses the standard library; operation owners load only after bounded input preflight.

```python
prepare_relational_batch_evaluation_v1(
    population_raw, references_raw, predictions_raw,
    expected_population_sha256=population_pin,
    expected_references_sha256=references_pin,
    expected_predictions_sha256=predictions_pin,
)

relational_batch_evaluation_sha256(report)

validate_relational_batch_evaluation_v1(
    report, population_raw, references_raw, predictions_raw,
    expected_evaluation_sha256=evaluation_pin,
    expected_population_sha256=population_pin,
    expected_references_sha256=references_pin,
    expected_predictions_sha256=predictions_pin,
)
```

The three inputs are original UTF-8 JSON byte transports with independently supplied raw SHA-256 pins. Validation also requires the full canonical output pin and regenerates the complete result from all three original transports. A stored self-address or resealed edited report cannot replace that replay. The owner raises `RelationalBatchEvaluationError` when the batch cannot be evaluated under its contract.

Output schema: `legal-relational-batch-evaluation/v1`. Profile: `full-selected-authored-relational-output-diagnostics/v1`.

## Three complete input populations

The population envelope uses `legal-relational-batch-population/v1`. It contains a partition label, selection hash and ordered rows with `id`, `source_sha256` and `context_sha256`. IDs represent occurrences and must be unique. Distinct IDs may share source and context hashes. This complete independently pinned population supplies the selected denominator, **N**. Partition, selection and source/context commitments remain caller declarations; their presence does not authenticate source custody, split membership or legal applicability.

The reference envelope uses `legal-relational-batch-references/v1` and binds the population pin. It must contain exactly one row per occurrence, in population order. An `available` reference supplies exact `request_utf8`, its raw-byte pin, the complete original relational report and its full canonical pin. Every available reference is publicly replayed before candidates, including references whose predictions are absent, duplicated or abstained. An invalid offered reference is an asset error and refuses the batch.

An `unavailable` reference supplies a bounded explicit reason and null request, report and payload pins. Its population occurrence remains in N. Omitting a reference row does not declare unavailability. Available references are authored unreviewed declarations; the evaluator does not create reviewed targets.

The prediction envelope uses `legal-relational-batch-predictions/v1`. Its `rows` retain every submitted finite JSON observation in arrival order, including scalar rows, invalid IDs, unfamiliar statuses and malformed closed-row shapes. Unknown envelope schema/keys or an invalid rows container refuse intake. Candidate request JSON is carried inside a `request_utf8` string: malformed candidate JSON can therefore remain an accounted output failure while the outer transport is valid. This text intake does not represent arbitrary raw non-UTF8 decoder bytes; invalid outer UTF-8 refuses intake. A later byte-preserving inference capture must retain such failures explicitly.

A well-formed prediction row binds an occurrence ID, source/context commitments, explicit `teacher_forcing=False` and `target_access=False`, and a declared status. `decoded` supplies the exact candidate request and raw-byte pin with no reason. `abstained` or `unsupported` supplies a reason and null request/pin. An abstention containing an output is malformed. Explicit `unsupported` is a caller-declared outcome; it does not independently discover a logic family's capabilities.

The generation declaration distinguishes `authored_control` from `decoder_declared`. An authored control has null latent dimension, checkpoint and encoder hashes. A decoder declaration requires dimension 8, 384 or 768 and checkpoint/encoder hashes. Both bind the population and settings hashes and declare no teacher forcing or target access. Missing, malformed or contradictory generation declarations remain visible and can prevent comparison credit. No checkpoint, encoder or model is opened by the evaluator.

## Complete coverage and terminal outcomes

The report preserves an observation ledger with each arrival index, valid ID or null, complete canonical observation hash, associated population index or null, and separate shape/provenance/outcome diagnostics. Full original envelopes remain bound by their raw transport hashes rather than echoed as model/source text.

Every valid submitted ID indexes all its observation indices, even when a row is malformed. Duplicate IDs receive no favorable first, last or best candidate selection. Unexpected IDs and unidentifiable observations remain in the coverage ledger. They do not create new selected occurrences or change N. Matching source text or hashes never repairs an ID mismatch.

Each selected occurrence receives exactly one terminal outcome, in population order:

| Outcome | Meaning |
| --- | --- |
| `missing` | No observation has the expected ID. |
| `duplicate` | More than one observation has the expected ID; none receives comparison credit. |
| `malformed` | The unique observation violates the closed row/status/payload contract. |
| `unverifiable_generation` | Generation declarations or source/context commitments disagree or lack the required conditions. |
| `abstained` | The unique well-formed observation explicitly declines an output. |
| `unsupported` | The unique well-formed observation explicitly declares unsupported output. |
| `invalid_typed_output` | The decoded candidate cannot be accepted by the existing relational owner. |
| `valid_without_reference` | The decoded candidate validates, but the reference is explicitly unavailable. |
| `compared` | Both valid declarations are compared, whether they agree or disagree. |

Precedence is missing/duplicate, malformed row, provenance/generation disagreement, abstained/unsupported, candidate failure, unavailable reference, then comparison. Separate diagnostics retain overlapping facts, including the originally declared status. The exhaustive terminal counts sum to N.

`coverage.valid` means each expected ID occurs exactly once, with no unexpected IDs or unidentifiable observations. It does not mean all outputs are valid typed expressions or all references are available. An honest abstention can complete the ID inventory while receiving zero reconstruction credit.

## Typed comparison and denominators

The evaluator reuses public relational preparation/validation and the existing paired comparator. It introduces no second AST, alpha-equivalence rule or seven-facet reduction. The supported fragment remains exactly `tdfol/tdfol_default` version `1.0.0`, with Bool/Object sorts, ordered bound-variable predicate arguments, explicit nonshadowing binders, supported Boolean connectives and exact O/P/F extensions. The authored request's `source_binding` stays null. Batch source commitments supply separate declared custody metadata; they do not turn this fragment into a statutory interpretation.

Valid comparable pairs retain all six existing booleans:

- Exact typed-expression identity.
- Family/profile agreement.
- Signature declaration agreement.
- Ordered argument-role agreement.
- Declared structure agreement.
- Lexical alpha structure agreement.

Each boolean has two explicitly different denominators. `full_selected_structure_diagnostics` reports matches over N; every missing, duplicated, malformed, unverified, abstained, unsupported, invalid or unavailable-reference occurrence receives zero matching credit. `comparable_pair_structure_diagnostics` reports matches over the number of valid compared pairs, **K**. A zero K has a null fraction. The report also gives available-reference and valid-typed-output fractions over N; valid typed outputs include `compared` and `valid_without_reference`.

These are agreement diagnostics against declared references. Conditional agreement alone cannot describe selected-population coverage, independently reviewed legal fidelity or decoder accuracy. Family/signature/role agreement is a structural gate, not a legal correctness verdict.

Each comparable row binds the full canonical pair diagnostic hash, six outcomes, shared/reference-only/candidate-only feature counts and exclusive path lists. The evaluator does not accumulate every complete nested pair report. Original inputs allow independent regeneration of the complete paired diagnostics.

## Bounds and source integrity

The input limits are 128 KiB for the population and 16 MiB each for references and predictions, with at most 64 selected occurrences and 256 submitted observations. The output limit is 8 MiB. The three input transports share a 500,000-node JSON budget, with depth at most 96; output JSON is separately bounded. Ordinary JSON integers have magnitude at most `2**63 - 1`, and floats must be finite. Values outside these intake bounds refuse the whole batch. Request UTF-8 is subject to the existing 524,288-byte limit; original reference reports are bounded to 8 MiB and each paired diagnostic to 4 MiB. An oversized decoded candidate request inside an otherwise safe outer transport becomes `invalid_typed_output` without relational lowering. An oversized original reference or unsafe whole envelope refuses the batch. Bounds are explicit. The owner never truncates a population, drops observations or clips results to fit.

Whole-transport pin mismatch, malformed outer JSON, duplicate outer JSON keys, nonfinite values or unsafe aggregate bounds refuse before operation imports. Inputs are detached ordinary finite values. Offered paths and report producer filenames never select files to read. Trusted fixed owner sources are fenced before and after operations, including candidate rejection paths, using bounded regular-file reads and physical identity checks.

Invalid original references, public pair replay failures and source-owner failures refuse the batch. They cannot become decoder failure rows. Trusted relational and pair import anchors, together with any established source populations, must agree with the fixed snapshots before candidate rejection can be counted. Candidate declaration rejection has a narrow error boundary; operational import, I/O and runtime failures cannot be converted into ordinary invalid-output counts. Generic file hashes cannot prove which bytecode an arbitrary preloaded, unanchored module executed. A qualified native checked-buffer import profile supplies that separate execution context.

## Generation evidence and remaining work

Deterministic lowering of a supplied typed request is postprocessing. It does not establish that a trained decoder emitted that request, ran without targets, used a particular latent, or depended usefully on that latent. Generation declarations and hash consistency remain distinct from numerical execution authentication. This evaluator performs scoring with reference access; it starts no inference, training, native backend or Lake build. Existing relational preparation may produce syntax-only Lean text.

All authority flags remain false, and `training_mask` and `evaluation_gold_mask` remain integer zero. The report explicitly leaves model execution, partition membership, source commitments, reviewed targets and decoder accuracy unverified. No declaration supplies an independent proof of generation.

A later separately qualified inference integration must bind actual checkpoint/task/codec and family/dimension identities, permitted source/context and latent lineage, decoding and retrieval policies, generated bytes/tokens and stop outcomes, producer closure and unchanged model state. Prefix receipts can document self-generated tokens; offline receipt inspection alone still cannot authenticate numerical execution. Seal predictions before reference scoring, and distinguish source-only, latent-only, source-plus-latent and oracle controls. Target-derived encoder features cannot become target-free evidence merely because the decoder receives a vector. Matched correct, zero and permuted latent interventions remain necessary for claims of useful latent dependence.

The retained §7213 alternatives are authored, exposed engineering hypotheses. The completed native consumer keeps them `authored_control`, with missing, duplicate and abstaining observations retained. They are not trained-model predictions or independently reviewed statutory targets.

## Native qualification

Native qualification02 passed all 299 unique cases: 112 new batch cases, 84 existing paired-reconstruction cases, 70 relational-owner cases and 33 expression-algebra cases. Collection, successful calls and JUnit identities account for the same 299 cases, with no failures, errors or skips. The run declared 242 source pins, checked 90 product source origins and recorded no network or extra-child attempts. Its qualification receipt elapsed time is 19.71599748893641 seconds. These overlapping module counts are counted once, not added to earlier qualification totals or treated as statutory coverage.

The captured native parent result is a path to a completed result with return code zero. Its final record reports durable artifacts, released storage and native lease, zero live group processes and no cleanup error. The run used a 2 GiB memory grant and a separate 1 GiB storage reservation. Captured native engineering evidence supplies this closeout; the evaluator itself grants no resource or semantic authority.

The first qualification remains a distinct failed run: 299 cases collected, 223 successful calls and 76 failures at the fixed source-file guard. The explicit owner tuple had included the natural `families` namespace, which has no source file. The correction removes only that namespace import/tuple entry and retains its concrete `namespaces.py` source, all required source-file checks and the entire accounting contract. Existing owners, tests and native guard were unchanged; the complete 299-case roster was rerun. The original source and failure evidence remain retained. Explicit recovery through the existing owner recorded ten files totaling 481,667 bytes, with no output deletion or new grant/reservation. Recovery supplies no successful qualification claim for that failed run.

## Retained authored accounting consumer

A separate fresh native interpreter completed seven named artifact checks, including two required refusal operations: an incorrect independent population pin and a resealed favorable denominator. It used two retained §7213 authored requests to construct ten accounting queries and twelve submitted observations. These are controlled queries about two competing hypotheses for one paragraph, not ten sampled laws or decoder predictions. The source/context hashes came from retained metadata declarations; no source HTML, scope/join lowering or old producer main was replayed.

All ten selected queries remain in the result. Two outcomes are `compared`; each of the other eight terminal outcomes occurs once. Nine references are available, one is explicitly unavailable, and three outputs validate as typed declarations, including the one without a reference. Missing, duplicate, unexpected and unidentifiable observations make coverage invalid, as intended by these controls.

| Structural diagnostics | Complete selected population, N = 10 | Comparable valid pairs, K = 2 |
| --- | --- | --- |
| Exact identity, declared structure and lexical alpha agreement | Each 1/10 | Each 1/2 |
| Family/profile, signature declarations and argument roles | Each 2/10 | Each 2/2 |

The self pair retains nineteen feature rows. The competing modal-scope pair retains thirty-one union rows: seven shared paths and twelve exclusive paths on each side. Matching signatures and roles do not erase that structural disagreement. These ratios demonstrate denominator accounting against authored references; they are not measured decoder accuracy.

The consumer declared 245 source pins, checked 87 product source origins and recorded 1.9195055039599538 receipt seconds. It wrote four local payload files totaling 818,480 bytes: population, references, predictions and batch evaluation. Saved batch validation regenerated from the original transports in that same consumer interpreter; it was not a second fresh output consumer. Selected original/export request files and metadata were rechecked before and after, including full physical identities. This does not establish immutability of the complete old producer tree or authenticate its live resource ledger.

The captured parent records completed native closeout with durable artifacts, released storage and lease, zero live group processes and no cleanup error. The consumer used a 2 GiB memory grant and a separate 256 MiB storage reservation. All review, inference, model, training, legal/proof authority and Lean action claims remain false, and training/evaluation-gold masks remain integer zero.

The publication copy roster (`../autoencoders/evidence/legal-typed-batch-evaluation-20261016/publication-copy-roster.json`; historical reference unavailable in this checkout) contains copied source and engineering metadata, including the failed first qualification and recovery. The retained request bodies and four new payload files remain local; copied metadata does not make this a self-contained payload replay bundle.
