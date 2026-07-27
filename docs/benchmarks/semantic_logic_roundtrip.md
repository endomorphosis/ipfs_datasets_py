# Semantic text/logic round-trip benchmark

## Question

Can the repository take nontrivial legal or policy text, compile it into
logic, generate natural language from that logic without seeing the source,
and recover equivalent logic from the generated text?

This pilot compares every relevant path that is currently runnable:

- the modal codec with regex and full spaCy frontends;
- the typed deontic converter and decoder;
- controlled CNL v2;
- DCEC;
- direct Leanstral;
- spaCy evidence supplied to Leanstral;
- SyMAI routed to the same Leanstral service;
- Hammer with cvc5 and the Lean kernel as independent validators.

The benchmark is intentionally an experiment, not a production-promotion
gate. Its purpose is to expose which component should own each part of the
translation and where semantic information is lost.

## Method

Each case follows this source-withheld cycle:

```text
adjudicated source T0
        |
        v
candidate logic L1 ---- compared with adjudicated gold logic
        |
        | source T0 is not available to the realizer
        v
generated natural language T1
        |
        v
recompiled logic L2
```

Three scores are reported independently:

1. **Forward:** gold logic versus L1. This measures text-to-logic fidelity.
2. **Cycle:** L1 versus L2. This measures whether a tool preserves its own
   interpretation through natural language.
3. **End-to-end:** gold logic versus L2. This is the important combined
   result.

Separating these scores prevents a consistently wrong translation from
looking correct merely because it can reproduce its own mistake.

The canonical benchmark IR represents:

- modality: obligation, permission, or prohibition;
- actor, action, and object;
- conditions and exceptions;
- temporal constraints.

Rule similarity is a weighted structural score: modality 25%, action 20%,
actor 15%, and object, condition, exception, and temporal facets 10% each.
Rules are paired with an exact maximum-weight bipartite assignment. Missing
or extra rules reduce the score. A failed or missing case scores zero in the
all-case means.

The pilot uses a closed, case-specific atom vocabulary containing every gold
atom plus two distractors per atom group. That isolates modality, scope,
roles, and rule structure; it does not test open-world ontology induction.

All benchmark identities use CIDv1/base32 with canonical DAG-JSON or raw
bytes. The only legacy SHA-256 fields are those required by an existing
SyMAI `StageRequest` interface. The complete fixture, including atom
vocabularies and distractors, is bound by corpus CID
`baguqeerahcfd4gby6nzstcnybokfnd4oeou6lcevjdvc5ry22xzvvtmjhrqq`.

## Corpus

| Case | Tier | Words | Gold rules | Main difficulty |
|---|---:|---:|---:|---|
| `exception_with_window` | 1 | 11 | 1 | deadline plus exception |
| `legal_doc_1` | 2 | 59 | 3 | threshold, deadline, consent exception |
| `exec_order_1` | 2 | 45 | 4 | mixed obligations and prohibition |
| `corp_policy_1` | 2 | 58 | 4 | mixed actors, deadline, gift prohibition |
| `construction_contract` | 3 | 147 | 12 | headings, permissions, prohibitions, conditions, deadlines |

The full fixture contains 320 normalized tokens and 24 adjudicated rules.
The source cases come from checked-in repository fixtures and examples, so
this is a reproducible pilot rather than an invented prompt-only demo.

## Environment

- Python 3.12.3
- spaCy 3.8.14 with `en_core_web_sm` 3.8.0 and the full tokenizer, tagger,
  dependency parser, lemmatizer, attribute ruler, and NER pipeline
- SymbolicAI/SyMAI 1.14.0
- cvc5 1.3.3 through the repository Hammer portfolio
- Lean 4.32.1
- llama.cpp Leanstral endpoint at `http://127.0.0.1:8080/v1`
- exact model
  `Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4`
- one model slot, so direct Leanstral, hybrid, oracle, and SyMAI requests ran
  serially

SyMAI is not an independent model in this experiment. It is a prompting and
routing layer over the same physical Leanstral service.

## Results

Scores below are all-case means. “Coverage” requires both a non-empty L1 and
a non-empty L2. “Exact cycle” means non-vacuous canonical L1/L2 rule-CID
identity accepted by both the Hammer/cvc5 check and the Lean kernel; it does
not mean that L1 was correct relative to the source.

| Arm | Executed | Coverage | Forward | Cycle | End-to-end | Mean arm seconds | Exact cycle |
|---|---:|---:|---:|---:|---:|---:|---:|
| typed deontic | 5/5 | 5/5 | 0.915 | 1.000 | 0.915 | 8.97 | 5/5 |
| modal + spaCy | 5/5 | 5/5 | 0.833 | 0.921 | 0.783 | 16.30 | 0/5 |
| direct Leanstral | 5/5 | 5/5 | 0.745 | 0.732 | 0.607 | 19.07 | 0/5 |
| spaCy evidence + Leanstral | 5/5 | 5/5 | 0.650 | 0.642 | 0.485 | 28.87 | 1/5 |
| gold logic + Leanstral reverse | 5/5 | 5/5 | 1.000 | 0.573 | 0.573 | 14.00 | 0/5 |
| controlled CNL v2 | 4/5 | 1/5 | 0.200 | 0.200 | 0.200 | <0.01 | 1/5 |
| DCEC projection | 5/5 | 0/5 | 0.000 | 0.000 | 0.000 | <0.01 | 0/5 |
| modal + regex | 5/5 | 0/5 | 0.000 | 0.000 | 0.000 | 6.60 | 0/5 |

SyMAI completed 5/5 forward calls with mean gold-atom lexical recall 0.602.
That number is not directly comparable with the structural scores: the
current pinned SyMAI contract returns forward semantic evidence but has no
logic-to-natural-language output field, so a genuine SyMAI round trip could
not be measured.

The timings are each arm's own reported wall time and cover different
internal scopes. They are useful for rough cost comparison, not as a
uniform system-throughput measurement.

## Reconstruction loss

Reconstruction loss is `1 - semantic score`. The oracle-reverse arm starts
from adjudicated gold logic, so its loss isolates the
logic-to-natural-language-to-logic portion of Leanstral.

| Case | Typed forward/end loss | Typed cycle loss | Leanstral oracle reverse loss |
|---|---:|---:|---:|
| `exception_with_window` | 0.000 | 0.000 | 0.400 |
| `legal_doc_1` | 0.133 | 0.000 | 0.367 |
| `exec_order_1` | 0.050 | 0.000 | 0.363 |
| `corp_policy_1` | 0.100 | 0.000 | 0.388 |
| `construction_contract` | 0.142 | 0.000 | 0.621 |
| **Mean** | **0.085** | **0.000** | **0.428** |

The complexity trend is clearest in the oracle arm: Leanstral loses 40% of
the one-rule exception case and 62.1% of the 12-rule contract even when the
input logic is perfect.

The typed score of 0.915 is a weighted semantic score, not exact extraction
accuracy. Forward exact-rule F1 ranged from 0 to 1 across cases. The typed
path generally preserved actors, actions, and modalities but sometimes
lost or altered temporal and conditional facets.

## What failed and why

### Typed deontic

This was the strongest path. Its deterministic decoder reproduced L1 exactly
in all five cases. Remaining loss is therefore in initial extraction, not
the reverse transformation. Examples include:

- dropping the suspicious-activity reporting deadline;
- conflating the law-enforcement condition and consent exception;
- omitting “before arbitration” and some contract deadlines;
- producing 11 canonical rules for the 12-rule construction contract.

This makes typed deontic the best primary compiler and realizer, while
identifying temporal and condition attachment as the next repair target.

### Modal codec with spaCy

The full spaCy frontend produced non-empty logic for every case and ranked
second. It often recovered actors, predicates, and modal cues, but its
compact realization duplicated qualifiers and sometimes inverted or
duplicated clauses. On the executive-order case it rendered the equipment
prohibition as a positive use statement.

spaCy is therefore useful for segmentation, dependency structure, entities,
and cue evidence. It should not be treated as the authority for modality or
scope.

### Direct Leanstral

Leanstral was available and completed every constrained request. Its failures
were semantic rather than availability failures:

- whole-document extraction dropped or collapsed rules;
- the second compilation changed modality, scope, or rule association;
- repeated clauses appeared in the 12-rule contract;
- deterministic-looking settings (`temperature=0`, `seed=0`) did not make
  the shared GPU service bitwise deterministic across reruns.

The JSON-schema grammar was useful for shape and vocabulary control, but it
cannot guarantee that the chosen structure is semantically correct.

### Leanstral reverse from gold logic

This arm exposes the main model weakness for the requested use case. The
generated prose was fluent but not reliably truth preserving:

- a prohibition on Chinese-manufactured equipment became “shall use”;
- a prohibition on accepting gifts became “must accept”;
- permissions in the contract became obligations;
- conditions and temporal scope were omitted or reassigned.

An earlier prompt contained a generic semantic example, which the model
copied into one output. Removing that example improved the affected case.
The final results use the corrected source-free prompt.

### spaCy plus Leanstral

Supplying the model with raw token, entity, dependency, and modal-cue evidence
reduced end-to-end score from 0.607 to 0.485 and increased time. The evidence
was too broad and distracted the model. One case had an exact L1/L2 cycle,
but its end-to-end score was only 0.600: exact self-consistency did not make
the interpretation correct.

Future hybrid experiments should send only compact evidence about a specific
ambiguous clause or slot.

### SyMAI

The repaired SyMAI route worked, but its output schema is forward-only and
coarse for this task. Because it invokes the same Leanstral model, it does
not add independent evidence. Its value is orchestration, typed prompting,
and ambiguity handling. A reverse contract and a controlled semantic IR
projection are required before it can be evaluated as a round-trip arm.

### Controlled CNL v2

CNL v2 works for the intended simple, controlled, single-norm grammar. The
marker duplication bug (`if if_*`, `unless unless_*`) was fixed, and simple
conditions now replay exactly as readable CNL. It is not presently a
document-scale compiler:

- four multi-rule or structurally richer cases were unsupported or projected
  to empty benchmark logic;
- readable composite boolean conditions currently reparse as flattened
  atoms, so complex AST replay is not guaranteed.

CNL remains useful at an explicitly controlled boundary, not as the default
parser for arbitrary documents.

### DCEC and regex modal paths

Both APIs executed, but neither produced non-empty canonical semantic rules
under the benchmark projection. DCEC commonly collapsed a multi-rule
document into one weak formula and lost actor structure. The regex modal
path emitted records that lacked sufficient typed roles for the canonical
projection.

This uncovered a validation trap: both paths can yield empty L1 and L2.
Lean can prove that two empty rule lists are equal, but that is vacuous. The
benchmark now records raw kernel acceptance separately and requires both
sides to be non-empty before exact identity counts.

### Hammer, cvc5, and Lean

These tools correctly validate a narrow claim: whether the canonical L1 and
L2 rule-CID collections are exactly identical and non-empty. They cannot
decide whether the original natural language was formalized correctly.
They belong after semantic compilation, not in place of it.

## Recommended division of responsibility

1. Use spaCy for sentence/clause segmentation, dependencies, entities, and
   modal-cue evidence.
2. Use the typed deontic converter as the primary semantic compiler.
3. Store a canonical typed IR that keeps modality, negation, actor, action,
   object, conditions, exceptions, temporal scope, and quantification
   explicit.
4. Use the deterministic typed decoder as the primary logic-to-language
   path.
5. Invoke Leanstral only for a bounded, low-confidence clause or slot, or to
   propose an alternate paraphrase. Never accept it as authoritative without
   structural comparison against the typed IR.
6. Use SyMAI to orchestrate those bounded ambiguity and repair calls once it
   has an explicit reverse contract; do not count it as a second model.
7. Use Hammer/cvc5 and Lean to verify supported formal identities and proof
   obligations, always with a non-vacuity check.
8. Use CNL v2 only when the input is deliberately restricted to its grammar.

## Next experiment

The next useful ablation is not an always-on ensemble. It is a clause-level
selective-repair test:

- baseline: typed deontic plus deterministic decoder;
- candidate: the same baseline, with Leanstral called only for a typed slot
  that is missing, contradictory, or below a fixed confidence threshold;
- spaCy input: only the local clause, dependency roles, and modal cues;
- acceptance: the repaired IR must improve adjudicated fidelity without
  changing already-confident modalities, and must pass non-vacuous
  structural validation;
- repeat model arms at least three times because the service was not
  bitwise deterministic;
- add an open-vocabulary corpus and human adjudication before drawing
  production conclusions.

The immediate engineering priority is to improve typed temporal and
condition/exception attachment. That is where the strongest path loses
information, and fixing it has more evidence behind it than adding another
always-on model layer.

## Reproduction

From the isolated benchmark worktree:

```bash
PYTHONPATH=. python benchmarks/bench_semantic_logic_roundtrip.py \
  --mode all \
  --output-directory /var/tmp/semantic-roundtrip-run
```

Use `--mode deterministic` to omit model calls. The live default pins the
local endpoint and exact model identity above. The runner refuses an
ambiguous or missing model identity, bounds response sizes and retries, and
serializes calls because the endpoint exposes one slot.

Focused validation:

```bash
PYTHONPATH=. pytest -q \
  tests/unit/benchmarks/test_semantic_logic_roundtrip.py \
  tests/reasoner/test_hybrid_v2_parse_replay.py \
  tests/unit_tests/logic/modal/test_modal_codec_source_copy_ratio.py \
  tests/unit_tests/logic/modal/test_modal_codec.py::test_codec_source_copy_loss_detects_structurally_excluded_source_spans
```

Final audited artifact CIDs and paths are recorded in
`docs/performance_snapshots/2026-07-26_semantic_logic_roundtrip_pilot.json`.
