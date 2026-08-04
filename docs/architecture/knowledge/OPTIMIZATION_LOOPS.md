# Optimizer control loops

| Field | Value |
| --- | --- |
| Interface | `OptimizerLoopArchitecture@1` |
| Task | `IPFSDOC-032` |
| Status | `canonical` |
| Owner | architecture / optimizers domain |
| Source of truth | `ipfs_datasets_py/optimizers/common/base_optimizer.py`; `ipfs_datasets_py/optimizers/common/lifecycle_hooks.py`; `ipfs_datasets_py/optimizers/common/optimizer_result.py`; `ipfs_datasets_py/optimizers/common/base_critic.py`; `ipfs_datasets_py/optimizers/lifecycle_hooks.py`; `ipfs_datasets_py/optimizers/llm_lazy_loader.py`; `ipfs_datasets_py/optimizers/graphrag/`; `ipfs_datasets_py/optimizers/agentic/`; `ipfs_datasets_py/optimizers/logic_theorem_optimizer/`; [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after BaseOptimizer, critic, harness, or lazy-LLM contract changes |

> **Sibling guides:** GraphRAG product composition and provenance →
> [GRAPHRAG.md](GRAPHRAG.md).
> Knowledge-graph fact lifecycle →
> [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md).
> Domain ownership → [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.4.
> Interim short note (historical) →
> `docs/OPTIMIZATION_LOOP_ARCHITECTURE.md` (this guide is the canonical
> architecture leaf for IPFSDOC-032).

## 1. Purpose

This guide answers: **how optimizer control loops run—generate, critique,
optimize, validate—under the `BaseOptimizer` / `OptimizationContext`
contracts**, how **lifecycle hooks** and **quality/evaluation evidence**
attach, how **lazy LLM dependencies** load, and how **failure behavior** is
bounded so that **scores and model recommendations remain advisory rather
than truth or proof**.

## 2. Audience

- **Primary:** developers implementing or extending GraphRAG, logic-theorem,
  or agentic optimizers; reviewers of session results and critic scores.
- **Secondary:** agents interpreting `OptimizerResult` fields; operators
  tuning iterations, early stopping, and LLM enablement.

## 3. Scope and non-goals

### In scope

- `OptimizerConfig`, `OptimizationContext`, `BaseOptimizer`,
  `OptimizerResult`.
- Canonical **generate → critique → optimize → validate** loop in
  `run_session` and `dry_run`.
- Session lifecycle hooks (`LifecycleHooksMixin`) and ecosystem event hooks
  (`LifecycleManager` / `LifecycleEventType`).
- Critic contracts (`BaseCritic`, `CriticResult`, GraphRAG `CriticScore`).
- Quality metrics, evaluation evidence, and recommendation authority.
- Lazy LLM backends, circuit breakers, and optional metrics/tracing.
- Failure modes for generation, critique, validation, and optional deps.
- Concrete product loops: GraphRAG ontology session/harness; notes on logic
  and agentic families.

### Non-goals

- Graph hybrid retrieval internals → [GRAPHRAG.md](GRAPHRAG.md).
- Persisted graph fact authority →
  [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md).
- Formal proof corpus / admissibility gates → logic architecture.
- Auto-generated method laundry lists →
  `docs/api/OPTIMIZERS_API_REFERENCE.md`.
- How-to tutorials → `docs/optimizers/*` product guides.

## 4. Context

Optimizers close a loop around **artifacts** (ontologies, query plans, code
patches, logic statements, etc.):

1. Produce a candidate (**generate**).
2. Score and explain weaknesses (**critique**) using multi-dimensional
   **evidence**.
3. Apply feedback (**optimize**).
4. Optionally check domain constraints (**validate**).
5. Stop on target score, max iterations, or early-stopping plateau.

The same abstract loop appears in GraphRAG ontology harnesses, logic theorem
optimizers, and agentic optimizers. Domain packages implement the four steps;
`BaseOptimizer.run_session` owns the shared control flow, hooks, and result
shape.

**Authority posture (non-negotiable):** critic scores, quality metrics, trend
labels, and model-written recommendations are **evaluation evidence** and
**advisory guidance**. They never substitute for formal proof, policy
admission, or authorization
([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Closed-loop session orchestration | Knowledge-graph WAL / fact commit |
| Shared optimizer config and result types | Vector store backends |
| Critic/score **evidence** envelopes | Authorization decisions |
| Lifecycle hooks around stages | MCP transport |
| Lazy LLM load and circuit resilience for optimizers | Global package import policy (shared ADRs) |

**Inbound callers:** Python optimizers API, `optimizers.cli`, MCP analysis
tools, GraphRAG product code, agentic/todo daemons, benchmarks.

**Outbound dependencies:** optional LLM backends; optional provers
(logic-theorem paths); metrics (Prometheus/OpenTelemetry best-effort);
domain data plane (graphs, files, IR).

**Authority notes:** `OptimizerResult.score` and `valid` answer different
questions. `score` is quality evidence for the loop stop rule; `valid` is a
domain validation flag when enabled—neither is proof authority.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| `OptimizationStrategy` | `common/base_optimizer.py` | Strategy enum (SGD, evolutionary, reinforcement, hybrid) |
| `OptimizerConfig` | same | Max iterations, target score, early stopping, validation/metrics flags, seed |
| `OptimizationContext` | same | Session id, input, domain, constraints, metadata, timestamp |
| `BaseOptimizer` | same | Abstract generate/critique/optimize; default validate; `run_session` / `dry_run` |
| `OptimizerResult` | `common/optimizer_result.py` | TypedDict result shape |
| `LifecycleHooksMixin` | `common/lifecycle_hooks.py` | No-op session stage hooks mixed into `BaseOptimizer` |
| `LifecycleManager` / events | `optimizers/lifecycle_hooks.py` | Event-driven BEFORE/AFTER/ON_ERROR/ON_COMPLETE/ON_TIMEOUT hooks |
| `BaseCritic` / `CriticResult` | `common/base_critic.py` | Shared critic evaluate → score + feedback + dimensions |
| `LazyLLMBackend` | `optimizers/llm_lazy_loader.py` | Deferred LLM init, disable flag, circuit breaker |
| GraphRAG ontology loop | `optimizers/graphrag/*` | Generator, critic, mediator, session, harness, pipeline |
| Logic theorem optimizers | `optimizers/logic_theorem_optimizer/` | Domain-specific generate/critique/optimize |
| Agentic optimizers | `optimizers/agentic/` | Agent-driven loops over shared contracts |

### 6.1 Control-flow diagram

```text
input_data + OptimizationContext
            |
            v
   on_session_start (hook)
            |
            v
   +-------------------+
   | generate(...)     |  --> candidate artifact
   +-------------------+
            |
   on_generate_complete
            |
            v
   +-------------------+
   | critique(...)     |  --> score + feedback (evidence)
   +-------------------+
            |
   on_critique_complete
            |
            v
   +---------------------------------------------+
   | while not stop:                             |
   |   optimize(artifact, score, feedback, ctx)  |
   |   on_optimize_complete                      |
   |   critique(...) again                       |
   |   on_critique_complete                      |
   +---------------------------------------------+
            |
            v
   +-------------------+
   | validate(...)     |  (if validation_enabled)
   +-------------------+
            |
   on_validate_complete
            |
            v
   OptimizerResult { artifact, score, iterations,
                     valid, execution_time*, metrics? }
            |
   on_session_complete
```

**Stop conditions** (`run_session`):

- `score >= config.target_score`
- `iteration` reaches `config.max_iterations`
- Early stopping: improvement since previous score
  `< config.convergence_threshold` (when `early_stopping` and `iteration > 0`)

## 7. End-to-end flow

### 7.1 Happy path — `BaseOptimizer.run_session`

1. Caller builds `OptimizationContext(session_id, input_data, domain, …)` and
   an `OptimizerConfig` (or defaults).
2. Optional metrics collector starts a cycle; OTEL span opens when enabled.
3. `on_session_start` fires (exceptions swallowed as best-effort).
4. `generate(input_data, context)` produces the initial **candidate** artifact.
5. `critique(artifact, context)` returns `(score, feedback_list)`.
6. Loop: `optimize` → re-`critique` until stop rule.
7. If `validation_enabled`, `validate(artifact, context)` → `valid` bool.
8. Build `OptimizerResult`; record optional metrics; `on_session_complete`.
9. Return result to caller. **Caller decides** whether to persist, discard, or
   promote the artifact using domain-specific APIs.

### 7.2 Happy path — `dry_run`

Single cycle: generate → critique → optional validate. Returns artifact,
score, feedback, valid, and timing—**no** iterative optimize. Used to verify
pipeline wiring without full refinement cost. Failures re-raise
(`RuntimeError` / `ValueError` paths) after logging.

### 7.3 Happy path — GraphRAG ontology session (product)

1. Generator produces ontology candidates (entities/relationships).
2. Critic emits multi-dimension `CriticScore` plus **recommendations**.
3. Mediator chooses refinement actions; session/harness iterates.
4. Optional logic consistency checks contribute validation **evidence**.
5. Aggregators (`OntologyOptimizer` reports) may emit trends and model
   recommendations—still advisory.

See [GRAPHRAG.md](GRAPHRAG.md) §7.3 for product placement relative to
retrieval.

### 7.4 Initialization and lifecycle

- Construct optimizer with optional `llm_backend` and `metrics_collector`.
- Deterministic seed applied from config when set (`seed_control`).
- Prometheus metrics and OpenTelemetry are **best-effort optional**—import or
  recording failures must not abort the session.
- Session hooks are **best-effort**: failures log at debug and do not unwind
  the main loop.
- Ecosystem `LifecycleManager.operation_lifecycle` dispatches BEFORE/AFTER
  operation events (and ON_ERROR) for broader operation tracking outside the
  four-step artifact loop.

## 8. Contracts

### 8.1 `OptimizationContext`

| Field | Meaning |
| --- | --- |
| `session_id` | Correlates logs, metrics, and traces for one run |
| `input_data` | Domain input (document, ontology seed, theorem sketch, …) |
| `domain` | Label such as code / logic / graph (string) |
| `constraints` | Free-form dict of stop rules or domain limits |
| `metadata` | Caller-supplied correlation fields |
| `created_at` | Context creation timestamp |

Context is **session state**, not a proof envelope. Constraints guide the
loop; they do not authorize side effects.

### 8.2 `OptimizerConfig`

| Field | Default (code) | Role |
| --- | --- | --- |
| `strategy` | `SGD` | Strategy label for metrics/capabilities |
| `max_iterations` | `10` | Hard cap on optimize cycles |
| `target_score` | `0.85` | Soft quality target in `[0,1]` |
| `learning_rate` | `0.1` | Strategy parameter (domain use) |
| `convergence_threshold` | `0.01` | Early-stop improvement floor |
| `early_stopping` | `True` | Enable plateau stop |
| `validation_enabled` | `True` | Run `validate` after loop |
| `metrics_enabled` | `True` | Attach metrics sub-dict on result |
| `seed` | `None` | Optional deterministic seed |

`target_score` is a **loop control threshold**, not a claim that the world is
correct at that number.

### 8.3 `BaseOptimizer` method contracts

| Method | Responsibility | Returns |
| --- | --- | --- |
| `generate(input_data, context)` | Build initial **candidate** artifact | Artifact (domain-typed) |
| `critique(artifact, context)` | Evaluate quality; produce feedback | `(score: float, feedback: List[str])` |
| `optimize(artifact, score, feedback, context)` | Improve artifact from critique | New artifact |
| `validate(artifact, context)` | Domain constraints (default `True`) | `bool` |
| `run_session(input_data, context)` | Full loop + hooks + metrics | `OptimizerResult` |
| `dry_run(input_data, context)` | One-shot generate/critique/validate | `OptimizerResult` (with feedback) |
| `get_capabilities()` | Advertise config-facing capabilities | dict |
| `state_checksum()` | Fingerprint of config state | str |

Subclasses **must** implement `generate`, `critique`, and `optimize`. Override
`validate` for syntax, consistency, or domain checks.

### 8.4 `OptimizerResult` (evaluation evidence envelope)

| Field | Meaning | Authority |
| --- | --- | --- |
| `artifact` | Final (or dry-run) candidate | Domain object—not auto-committed fact |
| `score` | Final critique score | **Advisory quality evidence** |
| `iterations` | Optimize cycles performed | Observability |
| `valid` | Validation outcome when enabled | Domain validation flag—not proof |
| `execution_time` / `_ms` | Wall timing | Observability |
| `metrics` | initial/final score, improvement, … | Observability |
| `feedback` | Present on dry-run | Advisory suggestions |
| `metadata` | Optional extensions | Caller-defined |

### 8.5 Critic and quality evidence

Critics implement structured evaluation:

- `BaseCritic.evaluate` → `CriticResult(score, feedback, dimensions,
  strengths, weaknesses, metadata)`.
- GraphRAG `OntologyCritic` → `CriticScore` with weighted dimensions
  (completeness, consistency, clarity, granularity, relationship coherence,
  domain alignment) and **recommendations**.

**Evidence rules:**

1. Scores are in `[0, 1]` (critics clamp where implemented).
2. Dimension breakdowns are for diagnosis and refinement—not separate proof
   kinds.
3. **Recommendations** and model-suggested actions are **advisory**. Operators
   and callers choose whether to apply them.
4. Comparison helpers and trend reports (`OntologyOptimizer`) summarize
   history; trends are not guarantees of future quality.
5. Optional prover-backed consistency checks contribute **validation
   evidence** under the validation layer of ADR-003—not authorization.

### 8.6 Lifecycle hooks

#### Session hooks (`LifecycleHooksMixin` on `BaseOptimizer`)

| Hook | When |
| --- | --- |
| `on_session_start(context, input_data)` | Start of `run_session` |
| `on_generate_complete(artifact, context)` | After generate |
| `on_critique_complete(artifact, score, feedback, context)` | After each critique |
| `on_optimize_complete(artifact, score, feedback, iteration, context)` | After each optimize |
| `on_validate_complete(artifact, valid, context)` | After validate (if enabled) |
| `on_session_complete(result, context)` | Before return |

Hooks are for instrumentation, audit, and side-effect **observers**. Hook
exceptions must not rewrite the artifact or upgrade authority. Default
implementations are no-ops.

#### Ecosystem events (`LifecycleManager`)

| Event | Typical use |
| --- | --- |
| `BEFORE_OPERATION` | Pre-flight logging, budget checks |
| `AFTER_OPERATION` | Success path metrics |
| `ON_ERROR` | Error capture (`ErrorHandlingHook`) |
| `ON_COMPLETE` | Terminal success bookkeeping |
| `ON_TIMEOUT` | Timeout observers |

These compose with, but are not identical to, the generate/critique session
hooks. Domain code may use either surface; do not assume both fire unless
wired.

### 8.7 Public surfaces

- Python: `ipfs_datasets_py.optimizers.common.base_optimizer`
  (`BaseOptimizer`, `OptimizationContext`, `OptimizerConfig`).
- GraphRAG: `ipfs_datasets_py.optimizers.graphrag`.
- CLI: `optimizers.cli` and related REPL helpers.
- MCP: analysis/workflow tools that invoke optimizers (thin wrappers).
- Env: `LLM_ENABLED`, `OTEL_ENABLED`, Prometheus enable flags (best-effort).

### 8.8 Persistence and identity

Optimizer sessions produce **candidates** and **evidence**. Content-addressed
export (when used) identifies **bytes** of an exported artifact, not the
truth of critic scores. Session IDs correlate runs. Do not treat
`state_checksum` as a content CID or proof id.

## 9. Failure modes and fallbacks

| Failure | Detection | Caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| Invalid input to generate | `ValueError` | Session fails / dry_run re-raises | Fix input; no silent empty success as “optimized” |
| Generate runtime failure | `RuntimeError` | Propagates from `run_session` (not caught by default) | Caller handles; no fabricated artifact |
| Critique invalid artifact | `ValueError` | Propagates | Repair artifact or abort |
| Optimize failure | `RuntimeError` | Propagates | Keep last good artifact only if caller checkpointed |
| Validation false | `valid=False` | Result still returned with score | Caller must not treat as authorized/proved |
| Hook exception | catch in `run_session` | Debug log only | Main loop continues |
| Metrics/Prometheus/OTEL failure | catch best-effort | Debug/warn log | Optimization continues |
| LLM disabled | `LazyLLMBackend` | `get_backend()` → `None` | Non-LLM generation/critique if implemented; else feature unavailable |
| LLM import missing | `ImportError` on load | Backend init fails when first used | Degrade feature; do not claim model quality |
| Circuit open | breaker state | Rejected/failed backend calls | Temporary unavailability; no invent high scores |
| GraphRAG session exception | session try/except | Partial result with `failed` metadata | Expose failure; do not claim target quality |
| No critic scores in aggregate | empty score list | Report `no_scores` / zero average | Recommendations note absence of evidence |

Explicit distinctions:

- **Feature degradation** (no LLM, no Prometheus) is allowed.
- **Trust degradation** (missing validation treated as proved; missing
  feedback treated as perfect) is **not** allowed
  ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).
- `valid=True` means domain `validate` returned true—not that scores are
  objective truth.
- Hitting `target_score` stops the loop; it does not promote candidates to
  facts or proofs.

## 10. Extension points

1. Subclass `BaseOptimizer`; implement `generate`, `critique`, `optimize`;
   override `validate` when domain constraints exist.
2. Optionally override lifecycle hooks for audit/metrics—keep them
   non-fatal and non-authoritative.
3. Implement `BaseCritic` for structured multi-dimension evaluation; map to
   `(score, feedback)` inside `critique`.
4. Inject `LazyLLMBackend` or a test double; never force eager LLM import in
   library import paths.
5. Register ecosystem hooks via `LifecycleManager` for cross-cutting
   operation events.
6. Add tests for stop rules, dry_run, hook isolation, and disabled-LLM paths.
7. Update this guide when method contracts or result fields change.

Anti-patterns:

- Using critic score as authorization or proof status.
- Catching all exceptions in `generate` and returning “success” with a dummy
  high score.
- Writing business logic only inside MCP tools instead of optimizer modules.
- Auto-persisting artifacts without domain commit APIs.
- Treating model recommendations as mandatory mutations.

## 11. Invariants

1. **Loop order** is generate → critique → (optimize → critique)∗ → optional
   validate.
2. **Scores and recommendations are advisory evidence**, never truth or proof.
3. **`OptimizationContext` is not an authority envelope**—it is session
   correlation and constraints.
4. **Hooks must not change layered authority** of the result; best-effort only
   for session hooks.
5. **Optional metrics/tracing failures never abort** successful optimization
   of the artifact path.
6. **Lazy LLM** — construction of loaders does not imply backend readiness
   ([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).
7. **`valid` ≠ proved ≠ authorized** ([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).
8. **Candidate artifacts stay candidates** until an external domain commit
   promotes them.
9. **Stop rules are control**, not certification.
10. **dry_run does not claim full optimization**—single cycle only.

## 12. Rationale and decisions

| Topic | Summary | ADR / source |
| --- | --- | --- |
| Shared BaseOptimizer | One control loop for graphrag / logic / agentic | `base_optimizer.py` |
| Score + feedback critique | Structured refinement without free-form only | `BaseCritic`, OntologyCritic |
| Best-effort hooks | Instrumentation must not brick sessions | `run_session` try/except |
| Lazy LLM + circuit breaker | Optional heavy deps and failure isolation | `llm_lazy_loader.py`, ADR-002/004 |
| Layered authority | Scores remain retrieval/model evaluation layer | ADR-003 |
| dry_run | Cheap configuration validation | `BaseOptimizer.dry_run` |

Alternatives rejected (brief):

- Unbounded optimize until human stop — rejected for production budgets.
- Single boolean “success” for score+valid+proof — collapses authority layers.
- Eager LLM at import — breaks hermetic CI and embeds.

## 13. Security, privacy, and trust boundaries

- Prompts and artifacts may contain sensitive user data; redaction helpers
  under optimizers apply to logs where wired.
- Backend credentials must not appear in feedback lists or exported metrics
  labels.
- Hooks that exfiltrate artifacts must be treated as privileged observers.
- This layer **must not** issue authorization or formal proof claims based on
  score thresholds alone.

## 14. Observability and operations

- Structured log lines for `run_session` / `dry_run` completion (session_id,
  domain, iterations, score, valid, timing).
- Optional Prometheus: score, round completion, duration, score delta, errors.
- Optional OpenTelemetry spans around `run_session`.
- Operator knobs: `max_iterations`, `target_score`, `early_stopping`,
  `LLM_ENABLED`, circuit-breaker thresholds.
- Product references: `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md`,
  `docs/OPTIMIZATION_LOOP_ARCHITECTURE.md` (short ASCII), API reference.

## 15. Related documents

| Document | Relationship |
| --- | --- |
| [GRAPHRAG.md](GRAPHRAG.md) | Graph-aware retrieval/generation consuming these loops |
| [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Where candidates may be committed as facts |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | `optimizers` ownership |
| `docs/api/OPTIMIZERS_API_REFERENCE.md` | Generated method reference |
| `docs/optimizers/*` | Product tutorials and audits |
| ADR-002 / ADR-003 / ADR-004 | Lazy deps, authority, fail-closed trust |

## 16. Verification

```bash
# Declared task validation
test -s docs/architecture/knowledge/GRAPHRAG.md && test -s docs/architecture/knowledge/OPTIMIZATION_LOOPS.md
rg -n 'generate|critique|optimize|OptimizationContext|candidate|evidence' docs/architecture/knowledge/OPTIMIZATION_LOOPS.md

# Spot-check contracts still present
rg -n 'class BaseOptimizer|class OptimizationContext|def run_session|def generate|def critique|def optimize' \
  ipfs_datasets_py/optimizers/common/base_optimizer.py
rg -n 'class LifecycleHooksMixin|on_session_start|on_critique_complete' \
  ipfs_datasets_py/optimizers/common/lifecycle_hooks.py
rg -n 'class LazyLLMBackend|LLM_ENABLED' ipfs_datasets_py/optimizers/llm_lazy_loader.py
```
