# Example verification ledger

| Field | Value |
| --- | --- |
| Interface | `ExampleVerificationLedger@1` |
| Task | `IPFSDOC-085` |
| Status | `canonical` |
| Owner | tutorials / documentation-governance |
| Source of truth | Executable end-to-end fences in `docs/tutorials/*_WORKFLOW.md`; this ledger records command, environment, tree, result, and external disposition |
| Last verified | 2026-08-03 |
| Audience | maintainer, developer, agent, release reviewer |
| Depends on | `IPFSDOC-083`, `IPFSDOC-084` |
| Companion | [VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md), [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md) |

## Purpose

This ledger is the durable inventory of **maintained core tutorials** and
**high-traffic snippets** for the documentation refresh program. Every row
records:

| Column | Meaning |
| --- | --- |
| **Owner** | Who maintains the example and accepts re-verification |
| **Page** | Source Markdown path and section of the runnable fence |
| **Setup** | Install / environment preconditions for the bounded path |
| **Command** | Exact, bounded shell command used (or equivalent extract-then-run) |
| **Expected evidence** | Observable stdout fields / assertions that count as success |
| **Tree** | Git commit (HEAD) under which the run was performed |
| **Result** | Actual exit code, evidence payload, and pass/fail/labeled disposition |
| **External / network / native / service** | What was required vs optional vs unavailable |
| **Deferred** | Provisioned gates not executed in this offline environment |

**Non-negotiable evidence policy**

| Allowed as verification | Not allowed as verification |
| --- | --- |
| Executed command with exit code and captured evidence fields | Screenshots of UI or notebooks alone |
| Import/runtime execution of the selected runnable fence | Syntax-only `ast.parse` / `compileall` standing in for run success |
| Explicit **fail** / **unavailable** / **mock** / **deferred** labels | Plausible prose that “should work” |
| Supporting syntax gates as **secondary** hygiene only | Treating mock pins, fallback embeddings, or policy `allowed` as production success |

Syntax checks (`python -m compileall`, `check_docs.py --checks python_syntax`)
are recorded as supporting hygiene; they **cannot** replace execution rows.

---

## 1. Environment

| Field | Value |
| --- | --- |
| Measured at (UTC) | `2026-08-03T18:23:22Z` |
| Host Python | `Python 3.12.3` (`/usr/bin/python3`) |
| OS kernel | Linux 6.17.0-1014-nvidia |
| Package | `ipfs_datasets_py` **0.2.0** (`requires-python >=3.12`) |
| Install mode | In-tree package via `PYTHONPATH=<repo-root>` (equivalent to editable install for imports) |
| Working directory | Repository root |
| Network policy for this ledger | Offline-first: no hub downloads, no live MCP HTTP server, no remote vector DBs required for **pass** rows |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` (empty at start; no prior valid checkpoint reused) |

### 1.1 Dependency disposition (this environment)

| Dependency | Disposition | Notes |
| --- | --- | --- |
| Core package imports | **available** | `DatasetLoader`, `DataProcessor`, `LogicProcessor`, `HierarchicalToolManager` import |
| `faiss` | **available** (`1.13.2`) | Used by retrieval tutorial FAISS path |
| `z3` / `z3-solver` | **available** | `Z3_AVAILABLE` true in logic tutorial |
| `sentence_transformers` | **present** but embeddings used **fallback** path | Runnable still labeled `embedding_fallback=True` (non-authoritative ranking) |
| Hugging Face `datasets` | **unavailable** | Broken/shadowed import (`cannot import name 'load_dataset'`); offline JSON path is the verified success path |
| `IPFSDatasetsMCPClient` | **unavailable** (`None`) | Even when a top-level `mcp` module imports; local hierarchical route is the verified path |
| IPFS daemon / `ipfs_kit_py` pin backend | **not required** | Offline path expects mock-shaped pins |
| Live MCP HTTP server (`127.0.0.1:8000`) | **not started** | Deferred provisioned gate |
| Qdrant / Elasticsearch / Neo4j daemons | **not required** | Out of scope for offline tutorials |
| Lean / Coq / CVC5 binaries | **not required** | Optional native provers; labeled when absent |

### 1.2 Tree identity

| Field | Value |
| --- | --- |
| **Tree** (full HEAD) | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| Short | `5a155d8b3` |
| Subject | Merge branch `implementation/ipfsdoc-084-99be7947e40b-attempt-1-1785780829` into `agent/ipfs-datasets-documentation-refresh-20260803` |
| Committer date | `2026-08-03 18:21:23 +0000` |
| Envelope tree id | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |

```bash
git rev-parse HEAD
git log -1 --format='%H %ci %s'
```

All execution **Result** rows below were produced on this **Tree** unless a row
states otherwise.

---

## 2. How to re-run (extract-then-execute pattern)

Core tutorials embed a single **selected runnable** Python fence (end-to-end
script). The exact bounded **Command** is: extract that fence to a temp file,
then execute it with the package importable.

```bash
# From repository root
export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"
# 1) Extract the fenced script that contains "selected runnable snippet"
#    from the tutorial page into /tmp/<name>.py
# 2) Run:
timeout 120 python3 /tmp/<name>.py
```

Supporting hygiene only (not sufficient evidence alone):

```bash
python3 -m compileall -q docs/tutorials
python3 docs/maintenance/check_docs.py --root docs/tutorials --checks python_syntax --fail-on error
```

On this tree, both supporting commands exited **0** (13 tutorial files;
0 syntax errors). They are **not** substitutes for the execution rows.

---

## 3. Result vocabulary

| Result label | Meaning |
| --- | --- |
| **pass** | Exit 0; expected evidence fields matched; cleanup observed |
| **pass-labeled** | Exit 0; tutorial success criteria met **with** explicit mock/unavailable/fallback/unknown labels that must not be upgraded to production claims |
| **fail** | Exit non-zero, assertion failure, or missing required evidence |
| **deferred** | Not executed here; requires a separately provisioned gate (network, daemon, credential, binary) |
| **not-maintained** | Page exists but is not a G092 canonical workflow; re-verification not claimed by this ledger |

---

## 4. Core maintained tutorials (G092)

These four pages are the program’s maintained executable journeys
(`DatasetWorkflowTutorial@1`, `RetrievalKnowledgeTutorial@1`,
`LogicProofTutorial@1`, `MCPClientTutorial@1`).

### 4.1 Inventory summary

| ID | Owner | Page | Result | External disposition |
| --- | --- | --- | --- | --- |
| EV-CORE-001 | tutorials / IPFSDOC-083 (data plane) | `docs/tutorials/FIRST_DATASET_WORKFLOW.md` §10 | **pass-labeled** | No network; HF `datasets` unavailable; IPFS pin mock-shaped |
| EV-CORE-002 | tutorials / IPFSDOC-083 (retrieval+knowledge) | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` §10 | **pass-labeled** | Offline FAISS; embedding **fallback**; mock scores labeled; graph in-memory |
| EV-CORE-003 | tutorials / IPFSDOC-084 (logic-proof) | `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` §11 | **pass-labeled** | Offline; Z3 available; prove returned **unknown** (not treated as theorem proof) |
| EV-CORE-004 | tutorials / IPFSDOC-084 (MCP runtime) | `docs/tutorials/MCP_CLIENT_WORKFLOW.md` §10 | **pass-labeled** | Local hierarchical only; HTTP client unavailable; HF load_dataset unavailable |

### 4.2 EV-CORE-001 — First dataset workflow

| Field | Value |
| --- | --- |
| **Owner** | tutorials / IPFSDOC-083 (data plane) |
| **Page** | `docs/tutorials/FIRST_DATASET_WORKFLOW.md` — §10 end-to-end offline script |
| **Interface** | `DatasetWorkflowTutorial@1` |
| **Setup** | Repo root; `PYTHONPATH=.` or `pip install -e .`; Python ≥ 3.12; writable temp dir. **No** Hugging Face hub, **no** IPFS daemon required for offline path |
| **Command** | `timeout 120 python3 /tmp/first_dataset_workflow.py` (fence extracted from §10; `PYTHONPATH=<repo-root>`) |
| **Expected evidence** | `records=3`, `chunk_total>=3`, `stored_items=3`, `identity_count=3`; cleanup `removed_temp_workspace`; loader/pin dispositions explicit |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass-labeled** — exit `0` |
| Captured evidence | `records=3`, `chunk_total=6`, `stored_items=3`, `identity_count=3`, `pin_status=success`, `pin_is_mock_shaped=True`; cleanup printed |
| Labeled non-production | `pin_is_mock_shaped=True` (not content-addressed IPFS); `DatasetLoader` error: HF `datasets` unavailable |
| **External / network / native / service** | Network: none required. Native: none. Service: IPFS daemon **not used**. Optional HF `datasets`: **unavailable** (error envelope, not silent success) |
| **Deferred** | Real IPFS add/pin against a live daemon; HF hub `load_dataset` success path |

### 4.3 EV-CORE-002 — Retrieval and knowledge workflow

| Field | Value |
| --- | --- |
| **Owner** | tutorials / IPFSDOC-083 (retrieval + knowledge planes) |
| **Page** | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` — §10 end-to-end offline script |
| **Interface** | `RetrievalKnowledgeTutorial@1` |
| **Setup** | Repo root; package importable; `faiss` (`faiss-cpu`) for the FAISS path; temp dirs for index/metadata under the script workspace |
| **Command** | `timeout 120 python3 /tmp/retrieval_knowledge_workflow.py` (fence extracted from §10; `PYTHONPATH=<repo-root>`) |
| **Expected evidence** | `corpus=3`, `faiss_vectors=3`, `faiss_hits>=1`, `graph_concepts=2`, `mock_disposition=mock_scores_not_production`, fallback/mock labels, cleanup closes store and removes temp workspace |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass-labeled** — exit `0` |
| Captured evidence | `corpus=3`, `embedding_fallback=True`, `dimension=4`, `faiss_vectors=3`, `faiss_hits=2`, `mock_hit_count=2`, `mock_disposition=mock_scores_not_production`, `graph_concepts=2`, `entity_name=CID`, `save_graph_root=None`; cleanup printed |
| Labeled non-production | Fallback embeddings (dim 4) — ranking **not** production similarity; mock vector scores non-production; `save_graph_root=None` (persistence disabled) |
| **External / network / native / service** | Network: none required for verified path. Native: FAISS local. Service: no Qdrant/ES/Neo4j. ST models may download if forced; this run stayed on **fallback** |
| **Deferred** | Production ST embeddings as authoritative ranking; remote vector stores; Neo4j export; GraphRAG end-to-end |

### 4.4 EV-CORE-003 — Logic and proof workflow

| Field | Value |
| --- | --- |
| **Owner** | tutorials / IPFSDOC-084 (logic-proof plane) |
| **Page** | `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` — §11 end-to-end offline script |
| **Interface** | `LogicProofTutorial@1` |
| **Setup** | Repo root; package importable; temp workspace. Z3 optional (present here). Timeouts: `prove_tdfol timeout_ms=5000`, `ProverRouter default_timeout=5.0` |
| **Command** | `timeout 120 python3 /tmp/logic_proof_workflow.py` (fence extracted from §11; `PYTHONPATH=<repo-root>`) |
| **Expected evidence** | Health envelope; validation/analysis non-proof; formalization disposition string; prove attempt **labeled** (proved or unknown); typed `ResultAuthority` kind; `policy_allow=true` / `policy_deny=false`; `parser_or_model_called_proof=false`; cleanup |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass-labeled** — exit `0` |
| Captured evidence | `health_status=healthy`, `validation_valid=True`, `analysis_parsed_ok=True`, `formalization_disposition=formalization_contract_not_theorem_proof`, `z3_available=True`, `prove_success=True`, `prove_proved=False`, `prove_status=unknown`, `prove_disposition=not_proved_or_unknown_not_disproof`, `authority_kind=evidence_readiness`, `authority_schema=result-authority/v1`, `policy_allow=True`, `policy_deny=False`, `parser_or_model_called_proof=False`; cleanup printed |
| Labeled non-production | `prove_proved=False` / `unknown` is **not** theorem proof and **not** disproof; policy allow is **not** MCP dispatch or theorem permission; formalization contract ≠ proof |
| **External / network / native / service** | Network: none. Native: Z3 **available** (optional). Service: none. Lean/Coq/CVC5 not required |
| **Deferred** | Interactive Lean/Coq workflows; production ZKP circuit proving; claiming operational prove success as formal theorem archive authority |

### 4.5 EV-CORE-004 — MCP client workflow

| Field | Value |
| --- | --- |
| **Owner** | tutorials / IPFSDOC-084 (MCP runtime plane) |
| **Page** | `docs/tutorials/MCP_CLIENT_WORKFLOW.md` — §10 end-to-end local script |
| **Interface** | `MCPClientTutorial@1` |
| **Setup** | Repo root; package importable; temp workspace. **No** MCP HTTP server required for the verified local route (`HierarchicalToolManager`) |
| **Command** | `timeout 120 python3 /tmp/mcp_client_workflow.py` (fence extracted from §10; `PYTHONPATH=<repo-root>`) |
| **Expected evidence** | `category_count>0`; `schema_load_dataset=success`; `audit_status=success` + event id; denials for missing tool/category = `error`; `load_dataset` often error without HF; HTTP client disposition; cleanup |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass-labeled** — exit `0` |
| Captured evidence | `category_count=52`, `dataset_tool_count=9`, `audit_tool_count=3`, `logic_tool_count=0`, `schema_load_dataset=success`, `schema_missing_tool=error`, `audit_status=success`, `audit_event_id_present=True`, `load_dataset_status=error`, `load_dataset_disposition=dependency_unavailable`, denials `error`/`error`, `http_client_disposition=client_unavailable`; cleanup printed |
| Labeled non-production | Tool list presence ≠ backend ready; `load_dataset` dependency unavailable; HTTP client unavailable; category discovery is not domain success |
| **External / network / native / service** | Network: none for local route. Service: HTTP MCP server **not started**. SDK client class: **unavailable** (`None`) |
| **Deferred** | Live `IPFSDatasetsMCPServer` + client list/call over HTTP; authenticated deny paths; gRPC/P2P/MCP++ carriers |

---

## 5. High-traffic snippets

High-traffic entry surfaces that are frequently copy-pasted. Only **executed**
checks appear as pass rows; legacy marketing claims remain **deferred** or
**not-maintained** until rewritten under a later task.

### 5.1 EV-SNIP-001 — Package import and version smoke

| Field | Value |
| --- | --- |
| **Owner** | documentation-governance / install surface |
| **Page** | Install / entry guidance (`docs/installation.md`, `docs/getting_started.md` import-style checks); package authority `pyproject.toml` + `ipfs_datasets_py.__version__` |
| **Setup** | Repo root; Python ≥ 3.12; package importable |
| **Command** | `python3 -c 'import ipfs_datasets_py; from ipfs_datasets_py.core_operations import DatasetLoader, DataProcessor, LogicProcessor; from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager; print(ipfs_datasets_py.__version__)'` |
| **Expected evidence** | Version `0.2.0`; imports succeed without network |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass** — exit `0`; printed `version 0.2.0`, `imports_ok True` |
| **External / network / native / service** | None |
| **Deferred** | GPU wheel installs; full extras matrix (`pip install -e ".[all]"`) |

### 5.2 EV-SNIP-002 — MCP hierarchical discovery smoke

| Field | Value |
| --- | --- |
| **Owner** | tutorials / MCP runtime (aligned with `docs/MCP_QUICKSTART.md` discovery pattern and `MCP_CLIENT_WORKFLOW.md`) |
| **Page** | `docs/MCP_QUICKSTART.md` (discovery fragments); authoritative local route in `docs/tutorials/MCP_CLIENT_WORKFLOW.md` |
| **Setup** | Package importable; no HTTP server |
| **Command** | Bounded async discovery: `HierarchicalToolManager().list_categories(include_count=True)` and `list_tools("dataset_tools")` via `python3` one-shot (≤ 60s) |
| **Expected evidence** | `category_count > 0`; dataset tools count present |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass** — exit `0`; `category_count=52`, `dataset_tools=9` |
| **External / network / native / service** | Local disk tool tree only |
| **Deferred** | Meta-tool surface over live MCP transport; “347 tools → 4 meta-tools” marketing numbers as KPI (count method is inventory-based, not this smoke) |

Note: `docs/MCP_QUICKSTART.md` fragments call `tools_list_categories` etc. as if
injected into an agent tool namespace. The **executed** equivalent is the
`HierarchicalToolManager` API used in the canonical MCP tutorial. Snippet prose
on the quickstart page is not re-certified as a standalone agent runtime.

### 5.3 EV-SNIP-003 — Getting-started “legal statements proven” claim

| Field | Value |
| --- | --- |
| **Owner** | user-docs (legacy entry page; not G092 canonical) |
| **Page** | `docs/getting_started.md` (claims “12 legal statements proven with 100% success rate in under 30 seconds”) |
| **Setup** | Not exercised as a bounded offline command in this task |
| **Command** | — (no exact bounded offline command established on this page for IPFSDOC-085) |
| **Expected evidence** | Would require a named script, timeouts, and labeled proof-vs-policy semantics |
| **Tree** | n/a (not executed) |
| **Result** | **deferred** / not re-verified — claim is **not** accepted as execution evidence here |
| **External / network / native / service** | Unknown; likely depends on optional logic/prover stacks |
| **Deferred** | Full rewrite/verification under a user-docs honesty task; until then treat as **unverified marketing-shaped prose**, not a ledger pass |

### 5.4 EV-SNIP-004 — Tutorial tree syntax hygiene (supporting only)

| Field | Value |
| --- | --- |
| **Owner** | documentation-governance (`DocumentationValidator@1`) |
| **Page** | All of `docs/tutorials/` |
| **Setup** | Offline; stdlib + `docs/maintenance/check_docs.py` |
| **Command** | `python3 -m compileall -q docs/tutorials` and `python3 docs/maintenance/check_docs.py --root docs/tutorials --checks python_syntax --fail-on error` |
| **Expected evidence** | Exit 0; zero syntax errors on fences |
| **Tree** | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| **Result** | **pass** (supporting hygiene only) — compileall exit `0`; check_docs scanned 13 files, errors=0 |
| **External / network / native / service** | None |
| **Deferred** | Full-docs `check_docs.py --root docs` release report (later quality task) |

**Explicit statement:** EV-SNIP-004 does **not** satisfy acceptance for
EV-CORE-001..004. Screenshots and syntax-only checks cannot stand in for
execution.

---

## 6. Legacy / non-canonical tutorials (disposition)

These pages live under `docs/tutorials/` but are **not** G092 canonical
workflows and were **not** re-executed for this ledger:

| Page | Disposition | Notes |
| --- | --- | --- |
| `graphrag_tutorial.md` | **not-maintained** (for this ledger) | Historical narrative; supersede paths point at retrieval/knowledge + architecture |
| `graphrag_website_processing_tutorial.md` | **not-maintained** | Not G092 output |
| `web_archive_tutorial.md` | **not-maintained** | Not G092 output |
| `media_scraping_tutorial.md` | **not-maintained** | Not G092 output |
| `distributed_dataset_tutorial.md` | **not-maintained** | Not G092 output |
| `security_tutorial.md` / `security_compliance_tutorial.md` | **not-maintained** | Security journeys owned by operations/security wave |
| `README.md` / `index.md` | Index only | Index content may still list legacy tutorials; canonical workflows are the four `*_WORKFLOW.md` pages |

**Deferred:** dedicated disposition/refresh tasks may promote, rewrite, or
archive legacy tutorials. Absence from EV-CORE rows means **no execution claim**.

---

## 7. Deferred provisioned gates (explicit)

These gates require external provisioning. They are **not** failures of the
offline path; they are **Deferred** until an environment with the named
service/binary/credential is provisioned and a new ledger row is written.

| Gate ID | Prerequisite | Related rows | Why deferred |
| --- | --- | --- | --- |
| GATE-HF-DATASETS | Working `datasets` package (`load_dataset` import) | EV-CORE-001, EV-CORE-004 | Current environment has broken/shadowed HF import |
| GATE-IPFS-DAEMON | Live IPFS / kit pin backend | EV-CORE-001 | Offline path intentionally mock-shaped |
| GATE-ST-EMBEDDINGS | Forced production ST path with model cache | EV-CORE-002 | Fallback path is the offline default evidence |
| GATE-REMOTE-VECTOR | Qdrant/Elasticsearch (or similar) daemon | EV-CORE-002 | Out of offline scope |
| GATE-MCP-HTTP | `IPFSDatasetsMCPServer` on localhost + non-`None` client | EV-CORE-004 | Local hierarchical route is verified instead |
| GATE-LEAN-COQ-CVC5 | Native prover binaries | EV-CORE-003 | Optional; Z3-only probe is sufficient offline |
| GATE-GETTING-STARTED-LEGAL | Bounded, labeled script replacing marketing claim | EV-SNIP-003 | Page lacks execution contract under G092 |

No deferred gate is recorded as a silent **pass**.

---

## 8. Failures

| ID | Result | Notes |
| --- | --- | --- |
| — | No **fail** rows for maintained core offline paths on this tree | All four EV-CORE scripts exited 0 with required evidence |
| — | No core tutorial assertion failures | Labeled unknown/unavailable outcomes are **pass-labeled**, not fail |

If a future re-run exits non-zero on an offline-required path, add a **fail**
row with stdout/stderr excerpts and do not paper over it with syntax checks.

---

## 9. Supporting hygiene results (secondary)

| Check | Command | Result |
| --- | --- | --- |
| Tutorial compile | `python3 -m compileall -q docs/tutorials` | exit **0** |
| Tutorial Python fences | `python3 docs/maintenance/check_docs.py --root docs/tutorials --checks python_syntax --fail-on error` | exit **0** (13 files, 0 errors) |

Again: these rows support maintainability; **execution** rows in §4 are
authoritative for example verification.

---

## 10. Maintenance process

1. When a maintained tutorial changes its runnable fence, re-extract and re-run
   the exact **Command** on a known **Tree**.
2. Update the matching EV-CORE row: evidence, result label, environment
   dispositions, and deferred gates.
3. Never mark a row **pass** from screenshots, CI green on unrelated tests, or
   syntax-only validators alone.
4. Prefer **pass-labeled** when mocks, fallbacks, unavailable deps, or
   non-proof authority kinds are part of the honest offline path.
5. Add new EV-SNIP rows only for high-traffic snippets that have an exact
   bounded command and captured evidence.
6. Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*`
   must not be modified by ledger maintainers.

---

## 11. Non-goals

- Exhaustive execution of every fence in `docs/examples/`, optimizers, or archive trees.
- Networked hub downloads or multi-node IPFS as a default pass criterion.
- Promoting mock pins, fallback embeddings, mock vector scores, policy
  `allowed`, or parser success into production or theorem claims.
- Replacing architecture ADRs or API domain references with this ledger.
- Claiming legacy tutorials are verified merely because they live under
  `docs/tutorials/`.

---

## 12. Traceability

| Artifact | Role |
| --- | --- |
| `docs/tutorials/FIRST_DATASET_WORKFLOW.md` | Source + per-page mini-ledger (IPFSDOC-083) |
| `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` | Source + per-page mini-ledger (IPFSDOC-083) |
| `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` | Source + per-page mini-ledger (IPFSDOC-084) |
| `docs/tutorials/MCP_CLIENT_WORKFLOW.md` | Source + per-page mini-ledger (IPFSDOC-084) |
| This file | Aggregated execution ledger (IPFSDOC-085) |
| `docs/maintenance/VALIDATION_RUNBOOK.md` | Offline docs validator (syntax/links; not example execution) |
| Program goal | `IPFSDOC-G092` executable journeys and example verification |
