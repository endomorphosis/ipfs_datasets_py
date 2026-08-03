# Testing and evidence selection

| Field | Value |
| --- | --- |
| Interface | `TestingEvidenceGuide@1` |
| Task | `IPFSDOC-072` |
| Status | `canonical` |
| Owner | developer-docs |
| Source of truth | Live worktree: `pytest.ini`, `pyproject.toml` (`testpaths`), `tests/`, `tests/conftest.py`, `benchmarks/`, optional-deps extras; sibling [REPOSITORY_MAP.md](REPOSITORY_MAP.md) §7; logic/security evidence architecture under `docs/architecture/logic/` and `docs/security_verification/` |
| Last verified | 2026-08-03 |
| Measured at (UTC) | `2026-08-03T08:19:46Z` |
| Commit | `2903f921968eb74af1894dd642a849a6d7dcfe4f` |
| Measurement Python | `Python 3.12.3` |
| Audience | developer, agent, maintainer, architect |
| Related | [REPOSITORY_MAP.md](REPOSITORY_MAP.md), [EXTENSION_RECIPES.md](EXTENSION_RECIPES.md) (when present), [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md), [VALIDATION_RUNBOOK.md](../maintenance/VALIDATION_RUNBOOK.md), [PROOF_ATTESTATION_AND_ZKP.md](../architecture/logic/PROOF_ATTESTATION_AND_ZKP.md), [evidence_promotion_workflow.md](../security_verification/evidence_promotion_workflow.md), root [CONTRIBUTING.md](../../CONTRIBUTING.md) |
| Review cadence | after large test-tree moves, gating flag changes, or evidence-class schema changes |

## 1. Purpose

This guide tells contributors and agents how to **select proportional checks**
for a change and how to **report what those checks prove**—and what they do
not.

It answers:

1. Which **nearest** unit, integration, conformance, security, benchmark, and
   build checks belong to a given change type?
2. Which **fixtures** and **optional provisioning** (extras, solvers, GPU,
   network, LLM) apply, and what to do when they are unavailable?
3. How to distinguish **tests**, **metrics**, **solver candidates**, **proof**,
   **policy**, **runtime**, and **release** evidence so authority is not
   inflated?
4. How to record **negative paths**, **unavailable gates**, and **exact
   command/tree receipts**?

It does **not** claim that the entire multi-thousand-file suite is the first
gate for every change. Full-tree `pytest` is a **broad** or **release** option,
not the default local first step.

### Authority

When this page disagrees with session summaries, badges, or historical
“all green” reports, prefer:

1. Live tests and implementation under `ipfs_datasets_py/` and `tests/`
2. Packaging and gating config (`pytest.ini`, `pyproject.toml`, `tests/conftest.py`)
3. Accepted architecture and security evidence docs
4. This guide’s selection tables
5. Historical completion reports (lowest authority)

Nearest-path inventory for domains lives in
[REPOSITORY_MAP.md](REPOSITORY_MAP.md) §7. This page owns **selection rules**
and **evidence classes**, not the full filesystem map.

---

## 2. First principles (must follow)

| Rule | Meaning |
| --- | --- |
| **Nearest first** | Run the smallest path that exercises the changed code (single file or domain directory) before wider trees. |
| **Proportional gates** | Match check class to risk: pure refactor → unit; registry/export → unit + import smoke; cross-domain → integration; formal claim → proof/conformance; shipping → release evidence. |
| **No suite-as-first-gate** | Do not start with `python -m pytest tests/` or blank `pytest` as the primary local validation for a focused change. Reserve full suite / CI matrices for merge or release when required by policy. |
| **Evidence class honesty** | Passing unit tests does not establish proof, policy approval, runtime health, or release readiness. Never promote one class into another. |
| **Negative and unavailable** | Every non-trivial change must document at least one **negative** path (rejected input, missing optional, deny policy) or state why none applies. If a gate was not run, label it **unavailable** or **deferred** with reason—do not omit it silently. |
| **Exact receipts** | Record the **exact command(s)**, working directory (repo root unless stated), exit code, and tree identity (`git rev-parse HEAD` or equivalent). Vague “tests passed” is not evidence. |
| **Optional is lazy** | Do not eagerly install GPU/LLM/solver stacks for a unit-only change. Prefer mocks/fixtures; provision only when the change touches that stack. |
| **Markers and defaults** | Default pytest skips LLM/network/heavy unless `--run-llm` / `--run-network` / `--run-heavy` or env `RUN_*_TESTS=1`. Treat skipped optional tests as **unavailable**, not as pass. |

---

## 3. Suite layout and configuration (current tree)

### 3.1 Primary suite

| Fact | Value |
| --- | --- |
| Discovery root | `tests/` (`pytest.ini` / `pyproject.toml` `testpaths = ["tests"]`) |
| Config | `pytest.ini` (markers, `addopts`, `norecursedirs`); package tool config also sets `testpaths` |
| Shared fixtures / gating | `tests/conftest.py` (primary), root `conftest.py` |
| Not primary | `test/` (legacy thin root); `ipfs_datasets_py/tests/` (package-local helpers); `archive/` |

### 3.2 Area map (selection, not full inventory)

Counts are **filesystem** `test_*.py` / `*_test.py` heuristics at measurement
time—not collected pytest node counts. Prefer the first existing path.

| Area | Approx. files | Use as evidence of… |
| --- | ---: | --- |
| `tests/unit/` | ~1400 | Preferred unit mirror of package domains |
| `tests/unit_tests/` | ~600 | Older / parallel unit layout (still active) |
| `tests/mcp/` | ~209 | MCP tool and server behavior |
| `tests/integration/` | ~144 | Cross-domain integration |
| `tests/logic/` | ~105 | Logic-family focused tests |
| `tests/conformance/` | small (`legal_ir/`, …) | Spec/corpus conformance |
| `tests/performance/` | ~16 | Perf / benchmark-style pytest |
| `tests/e2e/` | ~4 | End-to-end flows |
| `tests/architecture/` | few | Architecture boundary markers |
| `tests/dual_runtime/` | ~6 | Dual-runtime paths |
| `tests/fixtures/` | fixture packages (not test counts) | Shared data / recipes |
| `benchmarks/` | ~33 `bench_*.py` | Standalone performance benches (**metrics**, not product API) |
| Root `tests/test_*.py`, `_test_*.py` | many | Top-level / legacy MCP-style modules |

Gherkin / stub trees under `tests/gherkin_features/`,
`tests/test_stubs_from_gherkin/`, and related paths are **excluded from default
recursion** via `norecursedirs` in `pytest.ini`. Do not treat them as the default
gate.

### 3.3 Declared markers (`pytest.ini`)

| Marker | Typical meaning |
| --- | --- |
| `unit` | Unit scope |
| `integration` | Cross-component |
| `e2e` | End-to-end |
| `slow` | Long-running |
| `llm` | Needs LLM / large model stack |
| `network` | Needs external network |
| `heavy` | GPU / large models / large datasets |
| `gpu` / `multi_gpu` | CUDA resources |
| `performance` / `benchmark` | Perf / bench |
| `architecture` | Boundary / architecture contracts |
| `ml_dependencies` / `graphrag` | Optional ML / GraphRAG stacks |

Default local run: **omit** LLM/network/heavy unless the change requires them.
Enable with:

```bash
python -m pytest tests/unit/logic/ --run-llm -q
python -m pytest tests/integration/ --run-network -q
python -m pytest tests/performance/ --run-heavy -q
# or: RUN_LLM_TESTS=1 RUN_NETWORK_TESTS=1 RUN_HEAVY_TESTS=1
```

### 3.4 Optional packaging extras (provisioning)

Install only the extras the change needs. Names come from
`[project.optional-dependencies]` in `pyproject.toml` (non-exhaustive):

| Extra / stack | When to provision | If unavailable |
| --- | --- | --- |
| base editable install | Almost all unit/integration offline | Fix install; do not claim package tests |
| `logic`, `theorem-provers` | Compiler/prover, IR, Z3/CVC5 paths | Skip prover integration; unit-mock + **unavailable** receipt |
| `vectors`, `knowledge_graphs` | Vector stores, GraphRAG, KG | Use fixtures/mocks; mark optional tests unavailable |
| `file_conversion`, `multimedia`, `ocr` | Processors needing those stacks | Fixture-only or skip with reason |
| `ipld` | CAR/IPLD encode paths | Skip encode integration |
| GPU / self-hosted CI | `.github/workflows/gpu-tests.yml` class work | Document deferred; do not invent GPU pass |
| Native solver binaries | Lazy install / operator docs under `docs/security_verification/` | Solver **candidate** or skip—not proof |

Native theorem-prover binaries remain lazy and user-local; see
`docs/security_verification/lazy_theorem_prover_installation.md` and related
optional-solver docs. Python extras alone do not install every native tool.

---

## 4. Evidence classes (non-substitutable)

Use these labels in PR descriptions, completion receipts, and agent handoffs.
**Classes do not form a ladder**—a higher-sounding name does not absorb a lower
one.

| Class | What it is | What it is **not** | Typical artifacts |
| --- | --- | --- | --- |
| **Test evidence** | Deterministic automated checks (unit/integration/conformance/security pytest, architecture markers) that passed or failed under a stated command | Proof of theorem truth; production runtime health; release sign-off | pytest JUnit/log, exit code, node ids |
| **Metrics evidence** | Measured performance or cost numbers (latency, throughput, memory, bench ranks) | Correctness proof; security approval | `benchmarks/`, `tests/performance/`, CI logic-benchmarks output |
| **Solver candidate evidence** | A candidate model/proof/obligation produced by a solver or compiler pipeline that is **not** yet independently verified under the declared trust policy | Accepted proof; release-blocking theorem claim | Solver logs, obligation digests, candidate artifacts, `result_authority` that is not theorem-authoritative |
| **Proof evidence** | Independent verification of a bound statement/assumptions/obligations under declared algorithms and authority (`direct-proof-verification` and related production rules) | Unit test green; membership; signature alone; simulation | Proof objects, digests, attestation envelopes; see [PROOF_ATTESTATION_AND_ZKP.md](../architecture/logic/PROOF_ATTESTATION_AND_ZKP.md) |
| **Policy evidence** | Explicit policy decision, constraint evaluation, or reviewed promotion record for a claim gate | Implicit “tests passed so policy OK” | Policy id, decision receipt, promotion JSON, deny/allow traces |
| **Runtime evidence** | Behavior of a live or provisioned service/process (health, deploy smoke, dual-runtime, operator probe) | Static unit suite; offline CI alone | Deploy logs, smoke command output, dual-runtime results |
| **Release evidence** | Tree-bound, reviewed package of child receipts + required gates for a ship decision | Any single local pytest run | Commit/tree id, child task receipts, quality reports, known limitations, provisioned build disposition |

### 4.1 Forbidden promotions (fail-closed)

| Do not claim… | From only… |
| --- | --- |
| Proof / theorem proved | Unit or integration tests; solver **candidate** output; cache hit; producer claim alone |
| Policy approved | Green tests without a policy decision or promotion record |
| Release ready | Unscoped “full suite” anecdote; leaf task completion alone; unreviewed heuristic facts |
| Runtime healthy | Offline unit slice |
| Security “audited” | One `tests/mcp/test_security.py` pass without scope statement |
| Metrics “improved” | Untimed functional tests |
| Conformance | Unit tests that do not load the conformance corpus/spec |

Security IR and crypto-exchange paths use an explicit promotion workflow
([evidence_promotion_workflow.md](../security_verification/evidence_promotion_workflow.md)):
`heuristic` / `machine_extracted` facts are **not** release-grade until
`human_reviewed` or `trusted_fixture`.

### 4.2 Solver candidates vs proof (logic / formal)

| Stage | Evidence class | Gate language |
| --- | --- | --- |
| Compile / extract obligations | Test or pipeline intermediate | “Compiled”; not “proved” |
| Solver returns SAT/UNSAT/model/proof object | **Solver candidate** until independent verify | “Candidate”; “solver output” |
| Independent verifier accepts under bound digests + policy | **Proof** | “Verified” / theorem authority only when attestation kind allows |
| Simulation / dev-offline profile | Never production proof | Label simulation; never promote |

---

## 5. Change-type → nearest checks

**How to use this table:** pick the row that best matches the change. Run
**Primary (first gate)** first. Add **Next** only if primary is green or if the
change explicitly spans that concern. Full-suite and heavy CI are **Broad /
release**, not automatic first gates.

Fixtures: prefer `tests/fixtures/`, domain fixtures under
`tests/unit/**/`, and compact **recipe/generators** over bulk golden dumps that
re-emit full envelopes per case.

### 5.1 Product code and extensions

| Change type | Primary (first gate) | Next (same change, if needed) | Conformance / security / bench / build | Fixtures & optional provisioning | Negative / unavailable |
| --- | --- | --- | --- | --- | --- |
| **Single pure function / pure module** (no I/O) | `python -m pytest path/to/test_file.py -q` or nearest `tests/unit/<domain>/` | Adjacent unit files in same domain | Build: `python -m py_compile` on touched modules if import-sensitive | In-memory fixtures only | Invalid inputs; boundary values |
| **Processor** | `tests/unit/processors/` (and domain siblings e.g. `tests/unit/legal_scrapers/`) | `tests/integration/processors/` or root processor tests if present | Bench only if perf claim: `tests/performance/` or `benchmarks/` | Sample docs/bytes under fixtures; extras `file_conversion` / `ocr` / `multimedia` only if exercised | Unsupported format; missing optional dep; empty input |
| **Storage / vector backend** | `tests/unit/vector_stores/`, embedding router unit tests | MCP vector tool tests under `tests/mcp/`; integration search paths | Security: no secret leakage in config tests if touched | `vectors` extra or mocks; never require live Qdrant/ES for unit | Backend down; optional import missing; dimension mismatch |
| **MCP tool / server** | Nearest under `tests/mcp/` (or `tests/unit/mcp_server/`) | Integration MCP; duplicate-registration tests if registry changed | Security: `tests/mcp/test_security.py` when auth/surface changes; architecture registration tests | Mock MCP; avoid live network | Unknown tool; double register; unauthorized; missing dep |
| **Logic IR / compiler / prover** | `tests/unit/logic/` (+ `tests/logic/` if family-specific) | Registry: `tests/unit/logic/test_logic_submodule_registry.py`; integration logic paths | Conformance: `tests/conformance/` (e.g. legal_ir); proof corpus under fixtures/`proof_corpus`; **not** bench-as-proof | `logic` / `theorem-provers` extras; native solvers lazy | Unsatisfiable obligations; solver missing → **unavailable** + candidate-only label |
| **Policy / constraint / security model** | Domain unit under `tests/unit/logic/security_*` or security_models tests; policy unit files | Integration deny/allow paths | **Policy evidence** artifact; promotion workflow for release claims | Trusted fixtures only for “reviewed” claims | Explicit **deny**; expired review; unpromoted heuristic |
| **Knowledge graphs / GraphRAG optimizer** | `tests/unit/knowledge_graphs/`, `tests/unit/optimizers/` (subpath) | Integration KG; MCP if tools change | `benchmarks/` or `tests/performance/` only for perf claims; marker `graphrag` | `knowledge_graphs` extra; LLM/heavy flags only if required | Empty graph; missing spacy/model → skip with reason |
| **CLI** | `tests/cli/`, root `tests/test_*_cli.py` | Integration CLI install/search as needed | Build: CLI entry smoke if packaging scripts changed | No network by default | Bad args; missing subcommand |
| **Embeddings / search** | `tests/unit/test_embedding_*`, `tests/unit/search/` | MCP embedding/search tools; integration | Bench only if latency/quality claim | Model fixtures or mocks; `--run-heavy` only when real models required | Empty query; backend unavailable |
| **Wallet / auth-sensitive** | `tests/unit/test_data_wallet.py`, wallet MCP tests | Integration as present | Security-focused tests on same paths | Never log secrets in fixtures | Invalid key material; denied operation |
| **Error reporting / monitoring** | `tests/error_reporting/`, `tests/unit/error_reporting/` | Integration if pipeline-wide | — | Captured logs fixtures | Emitter failure path |
| **Compatibility / migration** | `tests/compatibility/`, `tests/migration_tests/`, `tests/unit/migration/` | — | Do not use archive/ as gate | Legacy fixtures labeled historical | Dual-read failure; removed symbol |
| **Deploy / infra scripts** | Focused `tests/test_deployment_infrastructure.py` / `tests/test_infrastructure.py` when present | Manual `deployments/` / docker smoke as **runtime** evidence | Build: image build only if change owns Docker and environment allows | Compose profiles; mark network/docker **unavailable** if no daemon | Missing env; dry-run failure |
| **Documentation only** | [VALIDATION_RUNBOOK.md](../maintenance/VALIDATION_RUNBOOK.md): `python docs/maintenance/check_docs.py --root docs/...` | Link/metadata checks on touched subtree | Site build is **release**/provisioned—not default first gate | No product extras | Broken link; missing metadata; stale claim |
| **Packaging / pyproject / entry points** | Import smoke of affected modules; relevant unit registry tests | CLI `--help` smoke | Build: `python -m build` or install dry-run only when packaging task owns it | Clean venv if claiming install | Extra missing; wrong console script |
| **CI workflow only** | YAML syntax / workflow validator if present; do not re-run entire product suite locally by default | Path-filter reasoning in the PR | Treat workflow file change as **policy/runtime** of CI, not product proof | Self-hosted/GPU may be unavailable offline | Document which jobs were not exercised |

### 5.2 Domain → start paths (quick index)

Aligned with [REPOSITORY_MAP.md](REPOSITORY_MAP.md) §7.2—prefer the first path
that exists:

```text
processors      → tests/unit/processors/ , tests/unit/legal_scrapers/
logic           → tests/unit/logic/ , tests/logic/
logic registry  → tests/unit/logic/test_logic_submodule_registry.py
mcp             → tests/mcp/ , tests/mcp_server/ , tests/unit/mcp_server/
optimizers      → tests/unit/optimizers/
knowledge_graphs→ tests/unit/knowledge_graphs/
vector_stores   → tests/unit/vector_stores/
embeddings      → tests/unit/test_embeddings_router_* , test_embedding_*
search          → tests/unit/search/ , tests/test_search_*
CLI             → tests/cli/ , tests/test_*_cli.py
conformance     → tests/conformance/ (e.g. legal_ir)
performance     → tests/performance/ , benchmarks/
architecture    → tests/architecture/
dual_runtime    → tests/dual_runtime/
```

### 5.3 Example focused commands (copy and adapt)

Work from repository root. Replace paths with the nearest domain for your
change.

```bash
# --- Identity receipt (always useful at start of a validation block) ---
date -u +%Y-%m-%dT%H:%M:%SZ
git rev-parse HEAD
python3 --version

# --- Unit slice (default first gate for code) ---
python -m pytest tests/unit/logic/test_logic_submodule_registry.py -q
python -m pytest tests/unit/processors/ -q
python -m pytest tests/unit/optimizers/graphrag/ -q

# --- MCP ---
python -m pytest tests/mcp/test_tool_metadata.py -q
python -m pytest tests/mcp/ -q   # broader MCP only after file-level green

# --- Integration (second gate when cross-domain) ---
python -m pytest tests/integration/logic/ -q
python -m pytest tests/integration/ -m "not slow" -q

# --- Conformance ---
python -m pytest tests/conformance/legal_ir/ -q

# --- Security-adjacent MCP ---
python -m pytest tests/mcp/test_security.py -q

# --- Architecture marker ---
python -m pytest tests/architecture/ -m architecture -q

# --- Benchmarks / metrics (only if change claims perf) ---
python -m pytest tests/performance/ -m "benchmark or performance" -q
# standalone benches (metrics evidence; not correctness proof):
# python benchmarks/bench_logic_validator_scaling.py   # if applicable

# --- Explicitly NOT the default first gate ---
# python -m pytest tests/          # full primary suite — merge/release or explicit charter
# pytest -m "not slow"             # still very large; use after domain slices
```

### 5.4 Build and static checks (when they are the right gate)

| Check | Command pattern | Evidence class |
| --- | --- | --- |
| Syntax / importability of touched files | `python -m py_compile path/to/module.py` | Test / build adjunct |
| Docs validator | `python docs/maintenance/check_docs.py --root docs/developer_guides` | Test (docs) |
| Typecheck trees (if owned by change) | paths under `tests/typecheck/` when present | Test |
| Package build | only when packaging/release task requires; record env | Release / build |
| Docker image | only with daemon; else **unavailable** | Runtime / release |

Do not substitute `py_compile` for unit tests, or docs check for product
correctness.

---

## 6. Fixtures and optional provisioning

### 6.1 Fixture preferences

| Prefer | Avoid |
| --- | --- |
| Small synthetic inputs in `tests/fixtures/` or test-local factories | Multi-megabyte golden dumps per case |
| Generators/recipes that build envelopes on the fly | Re-emitting full production envelopes in git for every variant |
| Shared conftest fixtures with clear scope (`function` default for asyncio) | Hidden global network calls inside fixtures |
| Labeled historical fixtures for migration tests | Using archive data as current API authority |

### 6.2 Provisioning decision tree

```text
Does the changed code path import optional stacks at runtime only?
  yes → unit test with importorskip / mocks; do not install stack for unit gate
Does the change modify the optional integration itself?
  yes → provision the named extra; run marked tests with --run-* if needed
Is the environment missing GPU / native solver / network?
  yes → record gate unavailable; keep unit + negative paths; do not claim those classes
Is the claim about proof or release?
  yes → follow proof/policy/release sections; tests alone are insufficient
```

### 6.3 Default skip semantics

From `tests/conftest.py` gating:

| Flag / env | Enables |
| --- | --- |
| `--run-llm` / `RUN_LLM_TESTS=1` | LLM-marked / keyword-detected LLM tests |
| `--run-network` / `RUN_NETWORK_TESTS=1` | Network tests |
| `--run-heavy` / `RUN_HEAVY_TESTS=1` | Heavy resource tests |

A default green run that **skipped** optional nodes is evidence only for the
nodes that ran. List skips when they touch the change surface.

---

## 7. Negative paths and unavailable gates

### 7.1 Negative paths (required for non-trivial changes)

Include at least one of:

| Category | Examples |
| --- | --- |
| Invalid input | Bad schema, empty payload, wrong IR version |
| Missing optional | Import of prover/vector stack fails closed |
| Policy deny | Constraint rejects action; auth failure |
| Idempotency / double apply | Duplicate MCP registration rejected |
| Resource absence | Backend URL unset; solver binary missing |

If the change is pure docs typography with no behavioral surface, state:
“Negative path: N/A (docs-only; validator is the gate).”

### 7.2 Unavailable / deferred gates

When a listed next gate cannot run:

```text
Gate: tests/integration/logic/ with theorem-provers extra
Status: unavailable
Reason: native solver binary not installed in this environment
What was run instead: tests/unit/logic/ (exit 0)
What must not be claimed: proof evidence; release readiness for prover path
```

Never convert “not run” into “passed.”

---

## 8. Command and tree receipts

### 8.1 Minimum receipt fields

Every validation block in a PR, task receipt, or agent handoff should include:

| Field | Example |
| --- | --- |
| Tree id | `git rev-parse HEAD` → full SHA |
| Timestamp (UTC) | `date -u +%Y-%m-%dT%H:%M:%SZ` |
| Python | `python3 --version` |
| Working directory | repository root (or state otherwise) |
| Exact command | full argv, including markers and paths |
| Exit code | `0` / non-zero |
| Evidence class(es) covered | e.g. `test` only |
| Negative path | command or description + outcome |
| Not run / unavailable | list with reasons |

### 8.2 Receipt template

```markdown
## Validation receipt

- Tree: `<full sha>`
- UTC: `<ISO timestamp>`
- Python: `Python 3.12.x`
- CWD: repository root

### Commands

1. `python -m pytest tests/unit/<domain>/test_<topic>.py -q`
   - Exit: 0
   - Class: test (unit)
2. `python -m pytest tests/integration/<topic> -q`
   - Exit: 0 or **unavailable**: <reason>
   - Class: test (integration)

### Negative

- `<description or command>` → expected failure / deny observed

### Explicitly not claimed

- proof, policy approval, runtime health, release evidence
  (unless separate receipts attached)
```

### 8.3 What “full suite” means here

| Phrase | Meaning in this repo |
| --- | --- |
| Focused unit | One file or one domain directory under `tests/unit/` or `tests/unit_tests/` |
| Domain broader | Entire domain tree or `tests/mcp/` |
| Integration band | `tests/integration/` (optionally `-m "not slow"`) |
| Primary suite | All of `tests/` discovered by pytest (very large; **not** default first gate) |
| CI matrix | Workflow-defined jobs (GPU, logic benchmarks, docker, etc.)—environment-specific |

CI workflows under `.github/workflows/` (examples: `gpu-tests.yml`,
`logic-benchmarks.yml`, `workflow-integration-tests.yml`,
`documentation-maintenance.yml`) are **runtime/policy of CI**, not a promise
that every contributor runs every job locally.

---

## 9. Selecting evidence by claim strength

Match the **strongest claim you will make** to the minimum evidence class:

| If you will say… | You need at least… |
| --- | --- |
| “Unit behavior for X is covered” | Test evidence on nearest unit path + receipt |
| “Cross-module wiring works offline” | Integration test evidence |
| “Matches corpus/spec S” | Conformance tests / corpus fixtures |
| “No open auth regression on tool surface” | Security-relevant tests + scoped statement (not “audited”) |
| “Latency improved by N%” | Metrics evidence with method, hardware notes, commands |
| “Solver produced a candidate” | Solver candidate evidence (explicitly not proof) |
| “Obligation is proved under policy P” | Proof evidence + policy binding |
| “Policy denies/allows as specified” | Policy evidence (decision/receipt) |
| “Service responds in env E” | Runtime evidence in E |
| “Ship/release this tree” | Release evidence bundle (tree id, child receipts, required gates, limitations) |

---

## 10. Documentation and docs-only changes

For documentation tasks (including this guide):

| Gate | Command |
| --- | --- |
| Non-empty / content | `test -s path/to/page.md` |
| Focused docs check | `python docs/maintenance/check_docs.py --root docs/developer_guides` |
| Program validation example | task-specific `rg` / link checks |

Docs checks are **test evidence for documentation quality**, not product
correctness. Do not cite them as proof, metrics, or runtime evidence.

See [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) and
[VALIDATION_RUNBOOK.md](../maintenance/VALIDATION_RUNBOOK.md).

---

## 11. Anti-patterns

| Anti-pattern | Correct approach |
| --- | --- |
| First command is full `pytest` / `pytest tests/` | Start with nearest file or domain directory |
| “All tests passed” without command | Paste exact commands and exit codes |
| Claiming proof from unit tests | Label test evidence only; run proof path separately |
| Treating skipped LLM/GPU as pass | List skips; mark unavailable |
| Installing every extra “just in case” | Provision only stacks under test |
| Using `benchmarks/` as correctness gate | Metrics only unless a test asserts invariants |
| Copying CI badge as release evidence | Bind commit, child receipts, and required gates |
| Editing production code to make docs green | Record product defect; docs task owns docs only |
| Silent omission of failed optional gate | Unavailable block with reason |
| Golden dump sprawl for envelopes | Compact fixtures/generators |

---

## 12. Agent checklist (focused validation)

Use before marking an implementation task complete:

1. [ ] Identify **change type** row in §5 and **evidence class** of claims in §4.
2. [ ] Run **primary** nearest tests (file or domain)—not the full suite first.
3. [ ] Run **negative** path or document N/A.
4. [ ] Record **unavailable** optional gates (solver, GPU, network, extras).
5. [ ] Attach **tree receipt** (`HEAD`, UTC time, Python, exact commands, exits).
6. [ ] Refuse claim inflation (no proof/policy/release language without those artifacts).
7. [ ] If docs changed: run docs validator on the owned subtree when practical.
8. [ ] Point to [REPOSITORY_MAP.md](REPOSITORY_MAP.md) for path discovery; keep
      selection rules here.

---

## 13. Related CI and scripts (reference only)

These are **pointers**, not a requirement to run every item on every change:

| Artifact | Role |
| --- | --- |
| `.github/workflows/gpu-tests.yml` | GPU/CPU matrix on provisioned runners |
| `.github/workflows/logic-benchmarks.yml` | Logic path benchmarks (metrics) |
| `.github/workflows/workflow-integration-tests.yml` | Workflow integration |
| `.github/workflows/documentation-maintenance.yml` | Docs maintenance automation |
| `scripts/testing/pytest-fast.sh` | Optional fast pytest wrapper (cache/ff helpers) |
| `scripts/test/` | Ad-hoc historical runners—prefer `python -m pytest` on `tests/` |

---

## 14. Provenance of this page

| Kind | Notes |
| --- | --- |
| Tracked / filesystem fact | Suite paths, markers, conftest flags, extras names measured from this worktree |
| Derived | Selection tables mapping change types to those paths |
| Not measured | Full `pytest --collect-only` node counts; live CI job greenness |

Re-verify paths after large test-tree moves. Update **Last verified** and the
header commit when tables change.

---

## 15. Summary

- **Nearest unit (or docs check) is the default first gate**—not the entire
  large suite.
- Map change types to unit → integration → conformance/security/benchmark/build
  using §5; provision fixtures and extras only as needed.
- Keep **tests, metrics, solver candidates, proof, policy, runtime, and release**
  evidence distinct; never promote silently.
- Always record **negative** paths, **unavailable** gates, and **exact
  command/tree receipts**.
)
