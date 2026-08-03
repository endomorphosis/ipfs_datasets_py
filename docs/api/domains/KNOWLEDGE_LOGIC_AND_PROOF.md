# Knowledge, logic, and proof API domain reference

| Field | Value |
| --- | --- |
| Interface | `KnowledgeLogicAPIReference@1` |
| Task | `IPFSDOC-081` |
| Status | `canonical` |
| Owner | api-reference / knowledge-logic-proof |
| Source of truth | `ipfs_datasets_py/knowledge_graphs/`; `ipfs_datasets_py/optimizers/`; `ipfs_datasets_py/logic/` (`__init__.py`, `submodule_registry.py`, `ir_core/`, `intent_ir/`, `legal_ir/`, `security_ir/`, `formalization/`, `external_provers/`, `admissibility/`, `proof_corpus/`, `integration/`, `profile_d_policy.py`, `profile_g.py`); `ipfs_datasets_py/core_operations/{knowledge_graph_manager,logic_processor}.py`; architecture leaves under `docs/architecture/{knowledge,logic}/`; legacy auto-doc [OPTIMIZERS_API_REFERENCE.md](../OPTIMIZERS_API_REFERENCE.md) |
| Last verified | 2026-08-03 |
| Audience | developer, agent, security reviewer, operator |
| Related | [CORE_AND_DATA.md](CORE_AND_DATA.md), [PROCESSING_AND_RETRIEVAL.md](PROCESSING_AND_RETRIEVAL.md), [MCP_AND_RUNTIME.md](MCP_AND_RUNTIME.md), [OPERATIONS_AND_INTEGRATIONS.md](OPERATIONS_AND_INTEGRATIONS.md), [knowledge/README.md](../../architecture/knowledge/README.md), [logic/README.md](../../architecture/logic/README.md), [RESULT_AUTHORITY.md](../../architecture/logic/RESULT_AUTHORITY.md), [DOMAIN_MAP.md](../../architecture/DOMAIN_MAP.md) |
| Review cadence | after IR identity, prover, admissibility, optimizer loop, or knowledge-graph export changes |

## 1. Purpose

This page maps **callable** knowledge, optimizer, IR, compiler, prover, and
policy surfaces with provenance:

1. **Knowledge graphs** — extraction, engine, storage, query, Neo4j-compat,
   and the core-operations `KnowledgeGraphManager` façade.
2. **Optimizers** — `BaseOptimizer` loop contract, GraphRAG / logic-theorem /
   agentic product trees, and package-root exports.
3. **Logic IR families** — `ir_core` kernel, Intent / Legal / Security IR,
   formalization / compilers, external provers, hammers.
4. **Policy and proof** — Profile D execution policy, admissibility /
   authorization gates, proof corpus attestation, Profile G planning helpers.
5. **Result authority** — which outcomes are proof, SAT, policy, or
   authorization, and what must never be substituted.

Importability is **not** public stability. Root re-exports, simulated ZKP,
mock optimizers, and empty CEC/ErgoAI checkouts must not be presented as
production success.

## 2. Authority legend

| Tag | Meaning |
| --- | --- |
| **Stability: public** | Preferred external contract |
| **Stability: reviewed** | Exported / protocol-backed; AST is authority |
| **Stability: compatibility** | Dual path, alias, lazy re-export, or migration shim |
| **Stability: internal** | Implementation detail; no stability promise |
| **Optional** | Models, provers, Neo4j, GPU, extras, empty submodules |
| **Side effects** | Filesystem, network, prover binaries, index mutation, receipt stores |

**Result authority inequalities (binding):**

- extraction **candidate** ≠ committed **graph fact**
- optimizer **score** / proposal ≠ theorem **proof** ≠ authorization **allow**
- SAT/SMT **model** ≠ theorem permission
- **simulated** attestation ≠ production proof
- proof alone **does not** grant dispatch

Architecture detail: [RESULT_AUTHORITY.md](../../architecture/logic/RESULT_AUTHORITY.md).

---

## 3. Package map

```text
knowledge_graphs/     # data plane: extract → engine → store → query → reason
optimizers/           # control loops: generate → critique → optimize → validate
logic/                # IR kernel, families, provers, gates, attestation
core_operations/      # KnowledgeGraphManager, LogicProcessor (MCP/CLI façades)
```

| Concern | Owns | Does not own |
| --- | --- | --- |
| Graph facts / Neo4j-compat views | `knowledge_graphs` | Formal IR identity (`logic.ir_core`); MCP transport |
| Optimization sessions / critic scores | `optimizers` | Authorization allow; theorem soundness |
| IR identity, provers, gates, corpus | `logic` | GraphRAG product loops; vector ANN backends |
| Thin operational façades | `core_operations` | Deep IR / registry ownership |

---

## 4. Knowledge graphs

### 4.1 Package root (stable exceptions only)

| Field | Value |
| --- | --- |
| **Canonical import** | Prefer **subpackages** (below). Root exceptions only: |
| **Source** | `ipfs_datasets_py/knowledge_graphs/__init__.py` |
| **Stability** | public for exception types; **compatibility** for root class re-exports |

**Stable at package root (`__all__`):**

```python
from ipfs_datasets_py.knowledge_graphs import (
    KnowledgeGraphError,
    ExtractionError,
    EntityExtractionError,
    RelationshipExtractionError,
    ValidationError,
    QueryError,
    QueryParseError,
    QueryExecutionError,
    MigrationError,
    EntityNotFoundError,
    RelationshipNotFoundError,
)
```

**Deprecated root re-exports** (lazy `__getattr__`, emit `DeprecationWarning`):

| Symbol | Prefer instead |
| --- | --- |
| `GraphDatabase`, `IPFSDriver`, `IPFSSession` | `knowledge_graphs.neo4j_compat` |
| `GraphEngine`, `QueryExecutor` | `knowledge_graphs.core` |
| `IPLDBackend`, `LRUCache`, `Entity`, `Relationship` | `knowledge_graphs.storage` (or extraction types as appropriate) |

### 4.2 Canonical subpackage imports

| Subpackage | Canonical import examples | Role | Stability |
| --- | --- | --- | --- |
| `core` | `from ipfs_datasets_py.knowledge_graphs.core import GraphEngine, QueryExecutor` | Engine CRUD / query executor | reviewed |
| `extraction` | `from ipfs_datasets_py.knowledge_graphs.extraction import Entity, Relationship, KnowledgeGraph, …` | Extract candidates | reviewed; NLP **optional** |
| `storage` | `from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend, Entity, Relationship` | IPLD-backed graph storage | reviewed |
| `query` | `knowledge_graphs.query.*` | Query budgets, federation, explanation | reviewed / optional backends |
| `neo4j_compat` | `from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase` | Neo4j driver-shaped **view** | reviewed; **not** fact authority |
| `transactions` | `knowledge_graphs.transactions` | WAL / transaction manager | reviewed |
| `migration` | `knowledge_graphs.migration` | Import/export / integrity | reviewed; I/O side effects |
| `reasoning` | `knowledge_graphs.reasoning` | Cross-document reasoning helpers | reviewed / optional LLM |

Architecture: [KNOWLEDGE_GRAPH_LIFECYCLE.md](../../architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md),
[GRAPHRAG.md](../../architecture/knowledge/GRAPHRAG.md).

**Side effects:** engine and storage mutate graph state; migration and Neo4j
paths may open drivers and write files; extraction may load spaCy/transformers
and download models (**optional**).

**Result authority:** committed engine/storage records are graph **facts** for
the knowledge data plane. Neo4j-compat projections and extraction candidates
are **views** / **candidates**, not interchangeable with formal proof.

### 4.3 KnowledgeGraphManager (core-operations façade)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import KnowledgeGraphManager` |
| **Source** | `ipfs_datasets_py/core_operations/knowledge_graph_manager.py` |
| **Stability** | reviewed (one of eight `core_operations` exports) |
| **Optional** | Graph driver URL / backend; SRL/ontology extras |
| **Side effects** | Driver connect; entity/relationship writes; transactions |

#### Signatures (AST) — primary methods **async**

```python
class KnowledgeGraphManager:
    def __init__(self, driver_url: Optional[str] = None) -> None
    async def initialize(self) -> Dict[str, Any]
    async def add_entity(self, entity_id, entity_type, properties=None) -> Dict[str, Any]
    async def add_relationship(
        self, source_id, target_id, relationship_type, properties=None
    ) -> Dict[str, Any]
    async def query_cypher(self, query, parameters=None) -> Dict[str, Any]
    async def hybrid_search(self, query, search_type="hybrid", limit=10) -> Dict[str, Any]
    async def close(self) -> Dict[str, Any]
    async def transaction_begin(self) -> Dict[str, Any]
    async def transaction_commit(self, transaction_id) -> Dict[str, Any]
    async def transaction_rollback(self, transaction_id) -> Dict[str, Any]
    async def index_create(self, index_name, entity_type, properties) -> Dict[str, Any]
    async def constraint_add(
        self, constraint_name, constraint_type, entity_type, properties
    ) -> Dict[str, Any]
    async def extract_srl(self, text, backend="auto", ...) -> Dict[str, Any]
    async def ontology_materialize(self, graph_name, schema=None, ...) -> Dict[str, Any]
    async def distributed_execute(self, query, ...) -> Dict[str, Any]
    async def graphql_query(self, query, kg_data=None) -> Dict[str, Any]
    async def visualize(self, format="json", ...) -> Dict[str, Any]
    async def suggest_completions(self, kg_data=None, ...) -> Dict[str, Any]
    async def explain_entity(self, explain_type="entity", ...) -> Dict[str, Any]
    async def verify_provenance(self, provenance_jsonl=None, kg_data=None) -> Dict[str, Any]
```

Result authority: dict envelopes with `status` of `"success"` / `"error"`.
Deep engine types remain under `knowledge_graphs.*`. Full method notes also in
[CORE_AND_DATA.md](CORE_AND_DATA.md).

---

## 5. Optimizers

### 5.1 Package root exports

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.optimizers import LogicPortDaemonConfig, LogicPortDaemonOptimizer, parse_llm_patch_response` |
| **Source** | `ipfs_datasets_py/optimizers/__init__.py` |
| **Stability** | reviewed for listed symbols (lazy `__getattr__`); other subtrees import by path |
| **Optional** | LLM backends, worktrees, domain extras |

```python
# Root __all__ (lazy)
LogicPortDaemonConfig
LogicPortDaemonOptimizer
parse_llm_patch_response
```

### 5.2 BaseOptimizer contract (reviewed)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.optimizers.common import BaseOptimizer, OptimizationContext, OptimizerConfig, OptimizerResult, …` |
| **Source** | `ipfs_datasets_py/optimizers/common/base_optimizer.py` (+ sibling common modules) |
| **Stability** | reviewed |
| **Optional** | `llm_backend`, metrics collectors |
| **Side effects** | LLM/network when backends configured; sessions may write metrics |

#### Signatures (AST)

```python
class BaseOptimizer:  # ABC
    def __init__(self, config=None, llm_backend=None, metrics_collector=None)
    def generate(self, input_data: Any, context: OptimizationContext) -> Any
    def critique(
        self, artifact: Any, context: OptimizationContext
    ) -> Tuple[float, List[str]]
    def optimize(
        self, artifact: Any, score: float, feedback: List[str],
        context: OptimizationContext,
    ) -> Any
    def validate(self, artifact: Any, context: OptimizationContext) -> bool
    def run_session(
        self, input_data: Any, context: OptimizationContext
    ) -> OptimizerResult
    def get_capabilities(self) -> Dict[str, Any]
    def dry_run(
        self, input_data: Any, context: OptimizationContext
    ) -> OptimizerResult
    def state_checksum(self) -> str
```

Loop: **generate → critique → optimize → validate** (via `run_session`).
`dry_run` validates setup without a full optimization.

**Result authority:** critic scores and `OptimizerResult` are **advisory**.
`validate` is session acceptance, **not** formal theorem proof or MCP
authorization allow. Architecture: [OPTIMIZATION_LOOPS.md](../../architecture/knowledge/OPTIMIZATION_LOOPS.md).

### 5.3 Product optimizer trees

| Tree | Location | Role | Stability |
| --- | --- | --- | --- |
| GraphRAG | `optimizers/graphrag/` | Ontology / query / traversal / Wikipedia optimizers | reviewed paths; import by module |
| Logic theorem | `optimizers/logic_theorem_optimizer/`, `optimizers/logic/` | Logic extraction / unified optimizers | reviewed; provers **optional** |
| Agentic | `optimizers/agentic/` | Agentic base and task loops | reviewed / optional LLM |
| Logic port daemon | `optimizers/logic_port_daemon.py` | `LogicPortDaemonOptimizer(BaseOptimizer)` supervised/daemon runs | reviewed; **side effects:** worktrees, patches, process control |
| Performance | `optimizers/performance_optimizer.py`, `advanced_performance_optimizer.py` | Website / pipeline resource optimization | reviewed; monitoring side effects |
| Integrations | `optimizers/integrations/` | DuckDB, ES, Kafka, Neo4j loaders | **optional** external systems |
| Common utilities | `optimizers/common/` | Critics, harness, cache, resilience, contexts | reviewed |

#### LogicPortDaemonOptimizer (AST summary)

```python
class LogicPortDaemonOptimizer(BaseOptimizer):
    def __init__(self, daemon_config: LogicPortDaemonConfig)
    def generate / critique / optimize / validate(...)  # BaseOptimizer
    def run_once(self) ...
    def run_daemon(self) ...
    def run_supervised(self) ...
    def cleanup_stale_worktrees(self) ...
```

**Side effects:** filesystem worktrees, optional git/process commands, LLM
patch parsing via `parse_llm_patch_response`.

### 5.4 Legacy optimizers API dump

[OPTIMIZERS_API_REFERENCE.md](../OPTIMIZERS_API_REFERENCE.md) is an **auto-generated**
method dump. Use it for discovery of class names; **this page** and package
`__all__` / AST own **stability and authority** labeling. Prefer
`optimizers.common` for new control-loop work.

---

## 6. Logic package surface

### 6.1 Namespace and registry

| Field | Value |
| --- | --- |
| **Canonical import** | `import ipfs_datasets_py.logic as logic` then submodule imports |
| **Source** | `ipfs_datasets_py/logic/__init__.py` |
| **Stability** | reviewed for registry + profile exports; submodule availability varies |

**Lazy submodule names** (package `__all__` / `_SUBMODULE_EXPORTS`):  
`api`, `batch_processing`, `benchmarks`, `bridge`, `CEC`, `cli`, `common`,
`config`, `deontic`, `e2e_validation`, `external_provers`, `flogic`,
`flogic_optimizer`, `fol`, `hammers`, `integration`, `integrations`,
`ml_confidence`, `modal`, `monitoring`, `observability`, `security`,
`security_models`, `submodule_registry`, `TDFOL`, `tools`, `types`, `zkp`.

**Registry helpers (machine-readable authority):**

```python
from ipfs_datasets_py.logic import (
    LogicSubmoduleSpec,
    logic_submodule_specs,
    logic_submodule_names,
    logic_submodule_spec,
    logic_integration_manifest,
    logic_submodule_import_report,
    logic_optimizer_scope_for_component,
    logic_optimizer_target_file_hints,
)
```

| Helper | Role |
| --- | --- |
| `logic_submodule_specs()` / `logic_submodule_names()` | Enumerate registry |
| `logic_submodule_spec(name)` | One `LogicSubmoduleSpec` |
| `logic_integration_manifest()` | Integration visibility map |
| `logic_submodule_import_report()` | Importability report (availability ≠ stability) |
| `logic_optimizer_*` | Optimizer scope / file hints |

**Compatibility:** `from ipfs_datasets_py.logic import tools` redirects to
`logic.integration` with **DeprecationWarning** (removed in v2.0). Prefer
`logic.integration` or family modules (`logic.fol`, `logic.deontic`).

**Optional empty trees:** `CEC`, `ErgoAI` may fail import until checked out —
capability gap, not domain absence.

### 6.2 LogicProcessor (core-operations façade)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.core_operations import LogicProcessor` |
| **Source** | `core_operations/logic_processor.py` |
| **Stability** | reviewed core export; deep ownership remains `logic` |
| **Optional** | CEC assets, TDFOL, theorem provers, NL models |
| **Side effects** | Optional prover invocation; KB mutation |

All primary methods are **async**. Method inventory is documented in
[PROCESSING_AND_RETRIEVAL.md](PROCESSING_AND_RETRIEVAL.md) §3.2 (`list_cec_rules`,
`prove_dcec`, `prove_tdfol`, `manage_kb`, `verify_rag_output`, …).

```python
lp = LogicProcessor()
caps = await lp.get_capabilities()
health = await lp.check_health()
```

Result authority: operational dict envelopes. Formal `AuthorityKind` lives in
`logic.ir_core`, not in these envelopes.

---

## 7. IR core and families

### 7.1 `logic.ir_core` (dependency-light kernel)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic.ir_core import AuthorityKind, ResultAuthority, BoundedResult, canonical_json, …` |
| **Source** | `ipfs_datasets_py/logic/ir_core/` (lazy package `__getattr__`) |
| **Stability** | public / reviewed kernel contracts |
| **Optional** | none for kernel types; backends optional at call sites |
| **Side effects** | pure contracts; no network at import |

Leaf groups (non-exhaustive): `artifacts`, `canonical`, `claims`,
`diagnostics`, `evidence`, `protocols` (`AuthorityKind`, `QueryKind`,
`ResultStatus`, `ResultAuthority`, `BoundedResult`, backend request/result),
identity / CID helpers.

#### Authority kinds (AST — `ir_core.protocols`)

| `AuthorityKind` | Wire value | Not interchangeable with |
| --- | --- | --- |
| `THEOREM_PROOF` | `theorem_proof` | SAT, monitor, policy, allow |
| `SATISFIABILITY` | `satisfiability` | theorem proof |
| `RUNTIME_MONITOR` | `runtime_monitor` | proof |
| `EVIDENCE_READINESS` | `evidence_readiness` | authorization allow |
| `POLICY_APPROVAL` | `policy_approval` | execution grant |

Legacy aliases on the enum (`PROOF`, `RUNTIME_MONITORING`, …) map to the same
wire values — **compatibility**, not new kinds.

#### Result status vocabulary (selected)

`proved`, `disproved`, `satisfiable`, `unsatisfiable`, `monitor_satisfied`,
`monitor_violated`, `ready`, `not_ready`, `approved`, `rejected`, `unknown`,
`error` — each legal only under the matching kind (see architecture leaf).

```python
from ipfs_datasets_py.logic.ir_core import AuthorityKind, ResultAuthority

# ResultAuthority fields: kind, issuer, method, scope_digest,
# evidence_digests, configuration_digest, schema_version
```

Architecture: [IR_FAMILY_AND_IDENTITY.md](../../architecture/logic/IR_FAMILY_AND_IDENTITY.md).

### 7.2 Intent IR

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic.intent_ir import IntentIRDocument, validate_intent_ir, decode_intent_ir, …` |
| **Source** | `ipfs_datasets_py/logic/intent_ir/` |
| **Stability** | reviewed |
| **Side effects** | pure encode/decode/validate; artifact store may I/O if used |

Public highlights: `IntentIRDocument`, `IntentStatement`, `IntentFormalizer`,
`IntentNormalizer`, `canonical_intent_ir_json`, `validate_intent_ir`,
`decode_intent_ir`, `migrate_intent_ir`, invocation adapters under
`intent_ir.invocation` (**non-executing** adapters — they do not dispatch tools).

### 7.3 Legal IR / Security IR / formalization

| Family | Path | Role | Stability |
| --- | --- | --- | --- |
| Legal IR | `logic/legal_ir/` | Legal formalization adapter | reviewed |
| Security IR | `logic/security_ir/` | Security declarations + result authority helpers | reviewed |
| Formalization | `logic/formalization/` | Compiler / constraint contracts / formal views | reviewed |
| FOL / deontic / modal / TDFOL / flogic | `logic/{fol,deontic,modal,TDFOL,flogic}/` | Family compilers and KBs | reviewed; binaries **optional** |
| Bridge | `logic/bridge/` | Optimizer/prover/KG bridges; ZKP attestation helpers | reviewed; default ZKP may be **simulated** |

Architecture: [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](../../architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md),
[LEGAL_AND_SECURITY_CONSTRAINTS.md](../../architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md).

---

## 8. External provers and hammers

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic.external_provers import ProverRouter, get_available_provers, Z3ProverBridge, …` |
| **Source** | `ipfs_datasets_py/logic/external_provers/` |
| **Stability** | reviewed API; prover **availability** is optional |
| **Optional** | Z3, CVC5, Lean, Coq, SymbolicAI; lazy install flags |
| **Side effects** | spawn prover processes; optional download/install; CPU-heavy |

#### Package exports (selected)

```python
Z3ProverBridge, CVC5ProverBridge, SMTProverInterface
LeanProverBridge, CoqProverBridge, SymbolicAIProverBridge
ProverRouter, FormulaAnalyzer, FormulaAnalysis, FormulaType, FormulaComplexity
get_available_provers, check_prover_availability
find_executable, ensure_prover_executable, lazy_install_prover
select_deterministic_prover_route
Z3_AVAILABLE, CVC5_AVAILABLE, LEAN_AVAILABLE, COQ_AVAILABLE, SYMBOLICAI_AVAILABLE
```

#### `ProverRouter` (AST)

```python
class ProverRouter:
    def __init__(
        self,
        enable_z3=..., enable_cvc5=..., enable_lean=..., enable_coq=...,
        enable_native=..., enable_symbolicai=...,
        default_strategy=..., default_timeout=...,
        enable_cache=..., enable_syntactic_fallback=...,
    )
    def get_available_provers(self) -> List[str]
    def select_prover(self, formula) ...
    def route(self, formula) ...
    def prove(self, formula, axioms=None, strategy=None, timeout=None) ...
    def prove_parallel(self, formula, axioms=None, timeout=None) ...
    def select_best(self, result) ...
```

**Result authority:** prover outcomes must be labeled with the correct
`AuthorityKind` (theorem vs SAT). Missing binaries → availability failure,
fail-closed for production profiles — not “proved false”.

Hammers: `logic.hammers` (router-side strategies). Architecture:
[EXTERNAL_PROVERS.md](../../architecture/logic/EXTERNAL_PROVERS.md).

---

## 9. Policy, admissibility, and proof corpus

### 9.1 Profile D — `evaluate_execution_policy`

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic import evaluate_execution_policy, ProfileDPolicyError` |
| **Source** | `ipfs_datasets_py/logic/profile_d_policy.py` |
| **Stability** | reviewed |
| **Side effects** | pure evaluation by default; optional ZKP certificate request |

```python
def evaluate_execution_policy(
    actor: str,
    action: str,
    resource: str | None = None,
    policy: Mapping[str, Any] | None = None,
    policy_text: str | Sequence[str] | None = None,
    evaluated_at: str | None = None,
    intent_cid: str | None = None,
    request_zkp_certificate: bool = False,
) -> dict[str, Any]
```

Typical result keys include `decision` and `allowed` (boolean). Treat
`allowed is True` as **policy-layer** approval only — still not MCP dispatch
or wallet grant consumption.

### 9.2 Admissibility / authorization gate

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic.admissibility import evaluate_admissibility, IntentAdmissibilityGate, AuthorizationDecision, NON_ALLOWING_AUTHORITY_PATHS, …` |
| **Source** | `ipfs_datasets_py/logic/admissibility/` (lazy exports by leaf) |
| **Stability** | public / reviewed contracts |
| **Optional** | prover backends for portfolio jobs; ZKP |
| **Side effects** | receipt stores, portfolio runs, optional prover spawn |

Export families (package map):

| Leaf | Representative symbols |
| --- | --- |
| `profiles` | `AdmissibilityProfile`, `get_profile`, `resolve_profile_fail_closed`, `DEFAULT_PROFILE_ID` |
| `reasons` | `AdmissibilityReason`, `AdmissibilityReasonCode`, `AdmissibilityStatus` |
| `gate` | `IntentAdmissibilityGate`, `AdmissibilityDecision`, `evaluate_admissibility` |
| `compose` | `AuthorizationQueryComposer`, `compose_authorization_query`, `evaluate_authorization_decision`, `NON_ALLOWING_AUTHORITY_PATHS` |
| `portfolio` | `AuthorizationPortfolio`, portfolio run/attempt records |
| receipts / service | `DecisionReceipt`, `build_decision_receipt`, service evaluate paths |

**Production rules (code-backed):** simulated evidence is rejected under
production profiles; `NON_ALLOWING_AUTHORITY_PATHS` can never produce
authorization **allow**. Architecture:
[GOVERNED_AUTHORIZATION.md](../../architecture/logic/GOVERNED_AUTHORIZATION.md).

### 9.3 Proof corpus and attestation

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic.proof_corpus import AttestedProofEnvelope, attest, ProofTrustPolicy, NON_AUTHORITATIVE_ATTESTATION_KINDS, …` |
| **Source** | `ipfs_datasets_py/logic/proof_corpus/` |
| **Stability** | reviewed |
| **Optional** | real ZKP circuits (`logic.zkp`, extras `profile-f-zk`, `provekit`, `groth16`) |
| **Side effects** | store/index I/O; revocation snapshots |

Key inequalities encoded as exports: `NON_AUTHORITATIVE_ATTESTATION_KINDS`,
`attestation_kind_is_theorem_authoritative`, non-substitutable evidence kinds.
Simulated ZKP backends remain **non-production-authoritative**.

Architecture: [PROOF_ATTESTATION_AND_ZKP.md](../../architecture/logic/PROOF_ATTESTATION_AND_ZKP.md).

### 9.4 Profile G helpers

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic import GoalPlanValidator, RiskEvidenceStore, Ed25519Signer, NeighborhoodAttestationEngine, evaluate_risk_model, profile_g_cid, validate_profile_g_artifact, ProfileGError` |
| **Source** | `ipfs_datasets_py/logic/profile_g.py` |
| **Stability** | reviewed |
| **Side effects** | `RiskEvidenceStore` persists artifacts to a path |

Planning / risk / neighborhood attestation helpers support supervised agent
workflows. They **do not** replace MCP policy stages or wallet UCAN grants.

### 9.5 Integration (preferred over `tools`)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.logic.integration import …` |
| **Source** | `logic/integration/` |
| **Stability** | reviewed preferred bridge; `logic.tools` = **compatibility** |
| **Optional** | SymbolicAI (`enable_symbolicai`, `SYMBOLIC_AI_AVAILABLE`) |

---

## 10. Canonical import cheat sheet

| Intent | Canonical import | Stability | Authority notes |
| --- | --- | --- | --- |
| KG exceptions | `knowledge_graphs` root exceptions | public | — |
| Graph engine | `knowledge_graphs.core.GraphEngine` | reviewed | fact plane |
| Neo4j view | `knowledge_graphs.neo4j_compat` | reviewed | view ≠ fact |
| KG ops façade | `core_operations.KnowledgeGraphManager` | reviewed | status envelopes |
| Optimizer loop | `optimizers.common.BaseOptimizer` | reviewed | scores advisory |
| Logic port daemon | `optimizers.LogicPortDaemonOptimizer` | reviewed | worktree side effects |
| Logic registry | `logic.logic_submodule_*` | reviewed | availability report |
| Logic façade | `core_operations.LogicProcessor` | reviewed | not AuthorityKind |
| IR kernel | `logic.ir_core.AuthorityKind` / `ResultAuthority` | public | non-substitutable |
| Intent IR | `logic.intent_ir` | reviewed | non-executing adapters |
| Provers | `logic.external_provers.ProverRouter` | reviewed / optional | kind-labeled results |
| Profile D policy | `logic.evaluate_execution_policy` | reviewed | `allowed` ≠ dispatch |
| Admissibility | `logic.admissibility.evaluate_admissibility` | reviewed | fail-closed profiles |
| Proof corpus | `logic.proof_corpus` | reviewed | simulation non-authoritative |
| Prefer over tools | `logic.integration` | reviewed | tools deprecated |

---

## 11. Side-effect and optional summary

| Surface | Common side effects | Typical optional deps |
| --- | --- | --- |
| Knowledge engine / storage | graph mutation, IPLD/files | Neo4j, IPFS |
| Extraction | model download, CPU | spaCy, transformers |
| Optimizers | LLM calls, metrics, worktrees | provider SDKs, GPU |
| External provers | process spawn, install | z3, cvc5, lean, coq |
| Admissibility portfolio | prover + receipt I/O | same + ZKP extras |
| Proof corpus / zkp | store I/O, circuit prove | circom/snarkjs, groth16 |
| CEC / ErgoAI | engine binaries | submodule checkout |

---

## 12. Discrepancies and deferred items

| Item | Disposition |
| --- | --- |
| Root KG class re-exports | **Compatibility** + deprecation warning; prefer subpackages |
| `logic.tools` | **Deprecated** → `logic.integration` |
| Empty CEC/ErgoAI | Availability gap; registry still lists them |
| Simulated ZKP default paths | Explicitly non-authoritative for production |
| Auto-generated optimizers dump | Discovery only; stability owned here |
| Exhaustive per-optimizer method tables | Point to AST / `OPTIMIZERS_API_REFERENCE.md`; product trees listed navigationally |
| MCP tool wrappers for logic/KG | See [MCP_AND_RUNTIME.md](MCP_AND_RUNTIME.md) — thin wrappers, not second engines |

---

## 13. Validation evidence for this page

- Knowledge package `__all__`, deprecated root map, and subpackage exports
  reviewed from AST / `__init__.py` (2026-08-03).
- Optimizer root exports, `BaseOptimizer` methods, and
  `LogicPortDaemonOptimizer` AST summarized.
- Logic package exports, submodule registry helpers, Profile D/G signatures,
  `ProverRouter` methods, and `AuthorityKind` enum values from source AST.
- Admissibility / proof_corpus export families from package `_EXPORTS` maps.
- Cross-linked to architecture knowledge/logic leaves (IPFSDOC-031–044) and
  sibling API domain pages (IPFSDOC-080/081).
