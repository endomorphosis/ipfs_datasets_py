# Hammer, SyMAI, spaCy, and Leanstral Benchmark Plan

- Status: proposed
- Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
- Todo seed: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark.todo.seed.md`

## Decision to make

This benchmark decides whether Hammer, SyMAI/SymbolicAI, spaCy, and Leanstral
improve the current legal-logic architecture, and which component should own
each overlapping responsibility. It must distinguish a genuine improvement in
kernel-verified results from an apparent improvement caused by extra model
calls, easier fixtures, cache leakage, retries, or accepting unverified model
claims.

The expected outcome is a measured delegation policy, not a requirement to put
every component on every request. spaCy is already the modal compiler's default
parser backend, so the experiment must record the effective pipeline and
separate a fully loaded spaCy model from its blank-model fallback and the
regex/legal parser. The likely production shape is a conditional cascade:

```text
source text
  -> deterministic compiler plus spaCy linguistic evidence
  -> SyMAI only for semantic ambiguity or contract repair
  -> Hammer for premise selection and bounded ATP/SMT search
  -> Leanstral for Lean-native synthesis or failed-proof repair
  -> independent Lean kernel check
  -> content-addressed receipt and routing telemetry
```

The benchmark may reject that shape. No component is promoted merely because it
is already integrated or performs well on its own examples.

## Existing integration anchors

The implementation should reuse these repository boundaries:

- `ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py`
  for spaCy legal/modal encoding.
- `ipfs_datasets_py/logic/modal/codec.py` for the current default
  `parser_backend="spacy"` and the deterministic modal compiler facade.
- `ipfs_datasets_py/knowledge_graphs/extraction/srl.py` for dependency-based
  semantic-role evidence.
- `ipfs_datasets_py/logic/integration/bridges/symbolic_fol_bridge.py` and
  `ipfs_datasets_py/logic/external_provers/neural/symbolicai_prover_bridge.py`
  for SymbolicAI/SyMAI semantic conversion.
- `ipfs_datasets_py/utils/symai_ipfs_engine.py` for routing SyMAI calls through
  the existing `llm_router`, cache, and IPFS-aware dependency layer.
- `ipfs_datasets_py/logic/hammers/` for premise selection, translation,
  portfolio execution, reconstruction, provenance, and receipts.
- `ipfs_datasets_py/logic/modal/leanstral.py` for bounded Leanstral proposals,
  typed failure-branch candidates, and Lean validation.
- `docs/LEGAL_IR_HAMMER_LEANSTRAL_OPERATOR_RUNBOOK.md` for existing trust and
  rollout gates.

The benchmark must not add a second model manager, a second proof authority, or
a second canonical Legal IR.

### Supervisor scanner prerequisite discovered during validation

The committed supervisor currently permits empty JavaScript AST symbols into
the objective evidence index. Its fuzzy symbol comparison then treats an empty
symbol as a substring of every requested evidence term, so ordinary objective
scans may report zero gaps. `HSSL-G009` exists to add the empty-symbol filter and
regression test in the isolated benchmark worktree.

Until that goal is completed, invoke the first objective-daemon pass with
`--force-goal-id HSSL-G009`. The supported forced-goal path was validated to
produce todo and bundle artifacts. After the scanner regression test passes,
omit the force flag and allow the opaque evidence markers to drive normal
incremental scans.

## Delegation charter

| Capability | Primary owner | Optional assistant | Authority boundary |
|---|---|---|---|
| Sentence splitting, tokens, lemmas, POS, dependencies, entities | full spaCy pipeline | deterministic/blank fallback as separately labeled variants | Linguistic evidence only |
| Modal/deontic cue extraction | deterministic compiler plus spaCy | SyMAI on ambiguity | Canonical IR validator |
| Natural-language semantic disambiguation | SyMAI | spaCy features as context | Structured candidate only |
| Text-to-FOL or Legal IR proposal | deterministic compiler first; SyMAI fallback | spaCy | Canonical parser and schema |
| Contract repair and explanation | SyMAI | Leanstral for Lean-specific failures | Contract validation |
| Premise retrieval and ranking | deterministic Hammer selector | learned or LLM ranking as separate opt-in arms | Corpus IDs and policy gate |
| TPTP/SMT-LIB translation | Hammer | none | Translation validator |
| ATP/SMT portfolio execution | Hammer | none | Untrusted solver evidence |
| Lean proof synthesis | Leanstral | Hammer-selected premises | Untrusted proof draft |
| Failed Lean proof repair | Leanstral | Hammer failure evidence | Bounded retry policy |
| Native reconstruction | Hammer | Leanstral candidate as input | Reconstruction record |
| Proof truth | Lean kernel | none | Kernel-accepted receipt |
| Routing decision | deterministic delegation policy | learned policy after benchmark | Auditable rule and telemetry |

### Overlap rules

1. spaCy and SyMAI may both analyze language, but spaCy emits reproducible
   linguistic observations while SyMAI emits a semantic hypothesis. They must
   not silently overwrite one another.
2. SyMAI and Leanstral may both call an LLM, but SyMAI owns language-to-logic
   interpretation and Leanstral owns Lean-native proof synthesis.
3. Hammer and Leanstral may both suggest proof steps. Hammer owns premise
   selection, external solvers, normalization, and reconstruction; Leanstral
   owns bounded Lean proof drafts and repairs.
4. SyMAI formal-engine results, Hammer solver verdicts, and Leanstral responses
   remain unverified until the repository's independent kernel path accepts the
   reconstructed proof.
5. A route must not recurse from SyMAI into `llm_router` and back into SyMAI.
6. Only one 119B Leanstral model instance is used. SyMAI should call the existing
   router when it needs that backend rather than start another model server.
7. Legacy `SymbolicAIProverBridge.is_proved()` confidence is a safety-diagnostic
   prediction only. It must never populate the primary verified outcome.
8. Hammer runs count as positive primary outcomes only at kernel trust with a
   verified reconstruction, even if a legacy router defaults to backend trust.

## Hypotheses

The experiment preregisters the following hypotheses:

- H1: a full spaCy model improves normalized IR accuracy over the recorded
  current effective configuration, blank-model fallback, and regex/legal parser
  on syntactically difficult inputs without materially increasing latency.
- H2: SyMAI improves semantic accuracy primarily on ambiguous inputs and is not
  cost-effective on clear deterministic inputs.
- H3: Hammer improves proof completion where a canonical structured obligation
  and useful premise corpus already exist.
- H4: Leanstral improves Lean-native proof completion and repair, especially
  after Hammer exposes a bounded failure context.
- H5: Hammer-first with Leanstral fallback is safer and cheaper than invoking
  both on every proof.
- H6: a conditional routing policy reaches most of the full-stack quality gain
  with fewer model calls and lower p95 latency.
- H7: any increase in unverified "proved" claims disappears when evaluation is
  restricted to kernel-accepted receipts.

The null hypothesis for every addition is that it does not improve paired
kernel-verified outcomes enough to justify its latency, resource use, and
operational complexity.

## Experimental unit and corpus

The unit of comparison is one immutable case with one source digest, expected
semantic result, and proof outcome. Every enabled variant sees the same case.

The corpus should contain 150 to 300 reviewed cases after a 30-to-50-case pilot.
It should be stratified across:

- simple first-order logic;
- nested and interacting quantifiers;
- modal, deontic, temporal, and epistemic rules;
- Legal IR compiler ambiguity packets;
- multi-premise entailment;
- contradiction and counterexample cases;
- missing-premise and irrelevant-premise cases;
- Hammer-solvable ATP/SMT obligations;
- Lean-native goals that benefit from tactic synthesis;
- invalid statements that must never verify;
- adversarial prompt-like text and proof text containing `sorry`, `admit`, or
  unsupported declarations;
- inputs for which the correct result is `ambiguous` or `unsupported`.

Preferred sources are existing versioned fixtures and regression tests. New
cases must be reviewed independently of model output. Each case should carry:

```json
{
  "schema": "ipfs-datasets.logic-pipeline-benchmark.case.v1",
  "case_id": "legal-modal-0001",
  "split": "pilot|development|holdout",
  "stratum": "modal",
  "difficulty": "easy|medium|hard",
  "source_text": "...",
  "source_sha256": "...",
  "expected_class": "proved|disproved|ambiguous|unsupported",
  "expected_ir": {},
  "required_predicates": [],
  "required_entities": [],
  "proof_obligation": {},
  "negative_controls": [],
  "provenance": {}
}
```

### Leakage controls

- Freeze pilot, development, and holdout IDs before comparing variants.
- Do not tune prompts or thresholds on holdout results.
- Store fixture and corpus-manifest digests in every run manifest.
- Use separate cache namespaces per variant and split.
- Report cold-cache and warm-cache results separately.
- Exclude a case from paired statistics only for a preregistered capability
  reason, never because a component produced a poor answer.
- Record whether a case appeared in an existing prompt, example, or model-facing
  development artifact when that can be determined.
- Require a nonempty candidate IR when computing semantic metrics. Missing IR
  is unavailable or failed evidence, never an implicit perfect score.

Initial fixture sources should include the Hammer golden and premise-selection
corpora, existing modal/compiler ambiguity tests, deterministic legal samples,
Leanstral validation regressions, and the external expert Legal IR benchmark.
The existing external expert and Hammer fixture sets are too small by
themselves for a performance claim; source/citation-clustered expansion and a
pilot-based power calculation are required.

## Stage contracts

Every stage should emit a versioned record rather than passing mutable free-form
state.

### Linguistic evidence

The spaCy adapter emits tokens, sentence spans, lemmas, POS tags, dependencies,
entities, noun chunks, semantic roles, modal cues, model identity, fallback
status, and a digest. It must not emit `proved` or `verified`.

### Semantic interpretation

The deterministic/SyMAI boundary emits canonical candidate IR, normalized
predicates, quantifiers, entities, ambiguity flags, confidence, backend
provenance, validation errors, and a digest. SyMAI raw output is retained
separately and never becomes canonical without parsing and validation.

### Proof request

The proof request reuses Hammer's request and policy types. It references the
canonical obligation and premise corpus by digest, includes strict process and
time budgets, and identifies the variant and routing decision.

### Leanstral request

Leanstral receives only:

- the exact theorem and proof-obligation ID;
- bounded, selected premises;
- allowed imports and constructs;
- structured failure evidence when repairing;
- output schema, byte/token limit, timeout, and retry count.

The response is an untrusted candidate. Forbidden constructs, copied source,
unknown obligation IDs, and malformed JSON fail closed.

### Verification and receipt

Only a native kernel result can set the final status to verified. The final
record includes stage digests, selected premises, solver attempts, model
identity, proof candidate, reconstruction source, kernel result, environment
lock, per-stage timings, resource measurements, and receipt ID.

## Variant matrix

The experiment uses a fractional, stage-aware matrix rather than an expensive
Cartesian product. Every arm records both requested and effective
configuration. If a requested full spaCy model, solver, SyMAI package, or model
service is unavailable, that arm is `unavailable`; it must not silently become
another arm.

| ID | Configuration | Purpose |
|---|---|---|
| A0 | Exact current effective configuration and revisions | Real-world frozen baseline |
| A1 | Full spaCy, SyMAI off, deterministic/native proof routes, Leanstral off | Controlled deterministic core |
| A2 | A1 plus deterministic Hammer premise selection, portfolio, and verified reconstruction | Hammer marginal value |
| A3 | A2 plus Leanstral only after Hammer failure, unproved, unsupported, or reconstruction failure | Recommended proof cascade |
| A4 | A3 plus ambiguity-gated SyMAI semantic contract | Recommended conditional stack |
| A5 | A4 with SyMAI always on | SyMAI gate efficiency control |
| A6 | A4 with Leanstral before Hammer | Proof-order/redundancy control |
| A7 | A4 with regex/legal parser instead of spaCy | spaCy marginal value |
| A8 | A4 with forced spaCy blank-model fallback | Full-model versus fallback control |
| A9 | A4 with Hammer removed, native then Leanstral | Hammer marginal value |
| A10 | A4 with pinned learned Hammer selector and all required opt-in gates | Learned selector experiment |
| A11 | A4 with SyMAI/LLM premise ranking instead of deterministic Hammer ranking | Premise-ranking overlap |
| A12 | SyMAI always, Leanstral first, and Hammer always | Duplicated-work stress control |
| S1 | Legacy SymbolicAI prover prediction compared with kernel truth | False-positive safety diagnostic only |

An optional same-model arm compares a direct structured LLM contract with the
SyMAI contract while using the exact same pinned Leanstral provider. This
isolates SyMAI's framework value from the underlying model's capability.

### Execution stages

1. **Capability probe:** record available spaCy model, SyMAI package/config,
   Hammer solvers, Lean executable, Leanstral endpoint/model, and resource
   scheduler.
2. **Deterministic smoke:** run A0, A1, A7, and A8 on small fixtures without network or
   model calls.
3. **Pilot screen:** run all applicable variants on 30 to 50 cases with strict
   budgets.
4. **Shortlist:** retain the baseline plus at most four Pareto-relevant
   candidates.
5. **Development evaluation:** run shortlisted variants on the development set,
   tune only routing thresholds, and freeze the policy.
6. **Holdout evaluation:** run the frozen baseline and policy on the untouched
   holdout set.
7. **Replay:** replay all successful receipts and a sample of failures in a
   fresh worktree/cache namespace.

Randomize variant order within case or use a balanced block schedule so thermal
state, model-server warmup, and transient load do not consistently favor one
variant. Record the order.

## Metrics

### Primary metrics

- kernel-verified completion rate;
- false-positive kernel verification rate on invalid controls;
- normalized IR exact match;
- semantic-equivalence acceptance by deterministic validators;
- paired verified-outcome delta versus V00.

### Secondary quality metrics

- predicate, quantifier, entity, modal-operator, and temporal-operator
  precision/recall;
- ambiguity classification accuracy;
- premise recall at fixed premise budget;
- solver-conclusive rate;
- Leanstral schema-compliance rate;
- reconstruction rate conditional on candidate creation;
- repair success conditional on an initial kernel rejection;
- regression count on cases V00 already solves;
- unsupported and fail-closed classification accuracy.

### Performance and resource metrics

- end-to-end and per-stage p50, p95, and p99 latency;
- throughput;
- CPU time, peak RSS, GPU utilization, and model-server queue time;
- solver subprocess count and cancellation count;
- model calls, input/output tokens, retries, and timeouts;
- cold-cache and warm-cache hit rates;
- receipt bytes and artifact-storage cost;
- useful verified deltas per model call and per accelerator-minute.

### Routing metrics

- percentage resolved before SyMAI;
- percentage resolved before Leanstral;
- escalation precision: escalated cases that gain a verified result;
- escalation recall: improvable cases that were escalated;
- unnecessary-call rate;
- disagreement rate between deterministic, spaCy, and SyMAI interpretations;
- Hammer/Leanstral candidate agreement and unique wins.

### Required failure taxonomy

Every failure is assigned a stable code:

- capability unavailable;
- fixture invalid;
- spaCy parse/model fallback;
- SyMAI import/configuration error;
- SyMAI contract or JSON failure;
- canonical IR rejection;
- premise-selection miss;
- translation unsupported;
- solver timeout/error/inconclusive;
- Leanstral timeout/schema/forbidden-construct failure;
- reconstruction failure;
- kernel rejection;
- receipt/provenance failure;
- resource-lease cancellation;
- benchmark infrastructure failure.

Infrastructure failures are reported separately and are not silently counted as
logical failures.

## Statistical analysis

- Use paired comparisons because variants process identical case IDs.
- Report absolute percentage-point and relative deltas.
- Use bootstrap confidence intervals over cases for verified-rate and IR
  metrics.
- Use McNemar-style paired outcome analysis for binary successes where sample
  size permits.
- Report latency distributions and paired median deltas; do not rely only on
  means.
- Stratify by logic family, difficulty, ambiguity, and proof route.
- Correct or clearly label multiple exploratory comparisons.
- Publish every case-level result so aggregate conclusions are reproducible.

A candidate wins the quality gate when:

1. no invalid control receives a kernel-verified result;
2. the 95% paired bootstrap interval for verified-outcome delta does not cross
   a material regression boundary;
3. its point estimate improves hard-case verified completion by at least five
   percentage points, or it remains within one point of the best quality while
   reducing p95 latency/model usage by at least twenty percent;
4. V00-solved regressions are explained and below the preregistered tolerance;
5. all claimed successes have replayable, kernel-bound receipts.

These are initial thresholds. The protocol goal must freeze final thresholds
before pilot results are inspected.

## Delegation policy candidates

### Policy P0: always-on full stack

Run spaCy, SyMAI, Hammer, and Leanstral for every eligible case. This establishes
an upper-cost comparison and is not the expected production policy.

### Policy P1: deterministic first

Run the controlled full-spaCy compiler. Call SyMAI only for ambiguity,
missing predicates, schema rejection, or low deterministic confidence. Send
valid obligations to Hammer. Call Leanstral only after Hammer is inconclusive or
native reconstruction fails.

### Policy P2: proof-family router

Use Hammer first for FOL/SMT-friendly obligations and Leanstral first for
Lean-native dependent-type or tactic-heavy goals. Fall back across the boundary
once, then stop.

### Policy P3: learned threshold router

Train or tune a small routing decision over development telemetry, but constrain
it to the same allowlisted actions and budgets. Compare it against P1 and P2.
The learned router cannot alter verification or trust rules.

The final report should select a policy per case stratum, not necessarily one
global winner.

## Worktree and progress-safety protocol

The benchmark must run from a dedicated worktree created from a recorded commit.
The active checkout is never cleaned, reset, stashed, switched, or used as an
artifact directory.

```bash
IPFS_DATASETS_SOURCE=/home/barberb/portland-laws.github.io/ipfs_datasets_py
BENCHMARK_RUN_ID=hammer-symai-spacy-leanstral-eval-001
BENCHMARK_WORKTREE=/home/barberb/portland-laws.github.io/.worktrees/$BENCHMARK_RUN_ID
BENCHMARK_BRANCH=benchmark/$BENCHMARK_RUN_ID

git -C "$IPFS_DATASETS_SOURCE" status --short
git -C "$IPFS_DATASETS_SOURCE" rev-parse HEAD
git -C "$IPFS_DATASETS_SOURCE" worktree add -b "$BENCHMARK_BRANCH" "$BENCHMARK_WORKTREE" HEAD
git -C "$BENCHMARK_WORKTREE" submodule update --init --recursive
```

Before starting, write a run manifest containing the parent and submodule commit
IDs. If uncommitted work is required for a later comparison, first commit it on
an appropriate branch or use an explicitly reviewed non-mutating snapshot
procedure. The benchmark supervisor must not manufacture a hidden commit from
untracked files.

All mutable state goes below an isolated root:

```text
workspace/benchmarks/hammer-symai-spacy-leanstral/<run-id>/
  cache/
  corpus/
  objective_bundles/
  receipts/
  results/
  state/
  logs/
  worktrees/
```

Use run-specific SyMAI cache keys, Hammer receipt stores, model logs, and
supervisor state. Never point these at production state. Default execution is
shadow-only and may not merge benchmark-created code automatically.

## Resource and process controls

- Acquire model, solver, kernel, and validation leases through the shared
  scheduler.
- Treat SyMAI and Leanstral as the same model-resource class when both route to
  the local Leanstral server.
- Run Hammer solvers in bounded child processes with allowlisted commands,
  memory/time/process limits, and process-group cancellation.
- Cap Leanstral to one request per case per route plus at most one bounded repair
  attempt during the pilot.
- Keep kernel checks in the separate kernel resource lane.
- Record queue delay separately from inference or solver time.
- Stop a variant after repeated OOM, orphaned child, corrupted receipt, or
  safety-control failure.
- Keep Hammer learned selection, LLM premise ranking, and LLM decomposition
  disabled except in the explicitly named experimental arms.

## Proposed implementation layout

The goals may refine this layout, but one coherent benchmark package is
preferred:

```text
benchmarks/logic_pipeline/
  README.md
  adapters.py
  capabilities.py
  cases.py
  contracts.py
  delegation.py
  metrics.py
  report.py
  runner.py
  statistics.py
  variants.py

tests/fixtures/logic_pipeline_benchmark/
  corpus.jsonl
  manifest.json

tests/unit/benchmarks/logic_pipeline/
tests/integration/benchmarks/logic_pipeline/
```

Results and caches belong under `workspace/` and are not source fixtures.
Point-in-time aggregate summaries may be copied to
`docs/performance_snapshots/` after review.

## Existing preflight validation to reuse

Run these focused checks inside the benchmark worktree before writing new
comparison code. Direct all generated output to the isolated run root.

```bash
PYTHONPATH=. python -m pytest \
  tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py \
  tests/unit_tests/logic/modal/test_modal_codec.py -q

PYTHONPATH=. python -m pytest \
  tests/unit/utils/test_symai_config_defaults.py \
  tests/unit/utils/test_symai_engine_backend_selection.py \
  tests/unit/test_symai_ipfs_engine_cache.py -q

PYTHONPATH=. python -m pytest \
  tests/unit_tests/logic/hammers \
  tests/integration/logic/hammers -q

PYTHONPATH=. python -m pytest \
  tests/unit_tests/logic/modal/test_leanstral.py \
  tests/unit_tests/logic/modal/test_leanstral_validation.py \
  tests/unit_tests/logic/modal/test_leanstral_verifier.py \
  tests/unit_tests/logic/modal/test_leanstral_audit_worker.py -q
```

Also reuse the Hammer environment probe and existing Hammer benchmarks where
available. Record missing test paths as version/capability differences rather
than silently skipping them.

`scripts/benchmark_symai.py` is only an `llm_router.generate_text` provider
smoke; it does not exercise SyMAI Symbols, contracts, or
`IPFSSyMAIEngine`. It may be retained as a model-provider health check but
cannot stand in for the A4/A5 semantic-contract ablation.

Leanstral audit telemetry already includes queue, inference, verification,
cache, GPU-seconds, and verified-audits-per-GPU-second measurements. Reuse
those fields rather than defining incompatible duplicates.

## Agent supervisor ingestion

The companion objective heap follows the native
`ipfs_accelerate_py.agent_supervisor.objective_graph.parse_goal_heap` format:
`## GOAL-ID Title` plus `- Field: value` rows.

From an isolated worktree:

```bash
BENCHMARK_ROOT="$PWD/workspace/benchmarks/hammer-symai-spacy-leanstral/supervisor"
OBJECTIVE_PATH="$PWD/docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md"
TODO_PATH="$BENCHMARK_ROOT/benchmark.todo.md"

mkdir -p "$BENCHMARK_ROOT"
cp docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark.todo.seed.md "$TODO_PATH"

PYTHONPATH=ipfs_accelerate_py python -m \
  ipfs_accelerate_py.agent_supervisor.objective_daemon \
  --repo-root "$PWD" \
  --objective-path "$OBJECTIVE_PATH" \
  --todo-path "$TODO_PATH" \
  --discovery-dir "$BENCHMARK_ROOT/discovery" \
  --bundle-dir "$BENCHMARK_ROOT/objective_bundles" \
  --dataset-dir "$BENCHMARK_ROOT/objective_datasets" \
  --graph-path "$BENCHMARK_ROOT/objective_graph.json" \
  --task-prefix HSSL-BENCH- \
  --force-goal-id HSSL-G009 \
  --max-findings 12 \
  --surplus-findings-per-goal 1 \
  --no-reconcile-goal-completion \
  --no-generate-bounded-work
```

Omitting `--submit-bundles` keeps this as local planning and artifact
generation. Inspect the generated todo, graph, bundle index, and vector index
before starting workers. The first pass intentionally generates the scanner
repair. After that repair validates, rerun without `--force-goal-id` to compile
the remaining goals and raise `--max-findings` to at least 64 so no unresolved
phase parent is truncated. Use the bundle supervisor's default dry-run planning
before any `--start`. The compiled task graph must contain all 27 unresolved
goal IDs (HSSL-G009 is the only evidence-complete omission), no invalid task or
dependency-repair record, and exactly one initially claimable foundation task.
Any packet aggregate must contain tasks from one bundle shard only.

Goals are ordered through Fibonacci priority, parent relationships, bundles,
and phase gates. The objective file intentionally names goal-specific opaque
evidence markers. Each marker must remain absent until a validated receipt
embeds it; this prevents semantic evidence matching from treating descriptive
plan prose as completed work.

For supervisor ingestion, `Parent` denotes an executable prerequisite whenever
that parent also has a materialized task. The heap therefore uses HSSL-G000 as
the sole foundation root and HSSL-G100 as the terminal decision leaf; phase
parents encode runnable order rather than merely a documentation outline.

## Phase gates

### Gate A: protocol ready

- clean worktree and capability probes pass;
- corpus schema and immutable manifest exist;
- baseline command is frozen;
- safety controls and metrics are preregistered.

### Gate B: adapters ready

- each component can run independently;
- all stage records validate;
- unavailable capability is explicit rather than silently replaced;
- model and kernel resource classes remain isolated.

### Gate C: pilot complete

- all pilot variants produce case-level records;
- invalid controls have zero kernel-verified false positives;
- failures are classified;
- no orphaned processes or cross-variant cache contamination exists.

### Gate D: shortlist frozen

- shortlist and routing thresholds are selected using pilot/development only;
- holdout remains unopened;
- run manifest, variants, prompts, solver policies, and model identities are
  frozen.

### Gate E: holdout complete

- baseline and shortlisted policies complete paired holdout runs;
- successful receipts replay;
- statistics and resource results are generated from immutable case records.

### Gate F: architecture decision

The final report selects one of:

- retain the current architecture;
- add one component in a bounded role;
- adopt a conditional delegation cascade;
- adopt the full stack for selected strata only;
- gather more evidence because results are inconclusive.

No automatic production promotion or merge is part of this benchmark.

## Required final deliverables

- immutable fixture corpus and manifest;
- capability and environment receipt;
- baseline snapshot;
- case-level result JSONL for every executed variant;
- content-addressed proof and reconstruction receipts;
- ablation and routing comparison report;
- failure taxonomy report;
- resource and latency report;
- replay report;
- recommended delegation policy with explicit thresholds;
- final architecture decision and rejected alternatives;
- operator runbook for repeating the benchmark in a fresh worktree.

## Principal risks

- **Ground-truth weakness:** mitigate with reviewed cases, negative controls, and
  deterministic validation.
- **Cache leakage:** use per-run and per-variant namespaces and report warm/cold
  separately.
- **Backend drift:** record model, prompt, solver, kernel, package, and commit
  identities.
- **Duplicate model use:** route SyMAI through the existing model manager and
  resource scheduler.
- **False proof claims:** only kernel-bound receipts count.
- **Benchmark overfitting:** freeze a holdout and limit threshold changes.
- **Operational complexity:** include calls, retries, subprocesses, and receipt
  size in the decision.
- **Current-progress damage:** operate only in dedicated worktrees and isolated
  state roots; never clean or reset the active checkout.
