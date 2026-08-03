# Capability matrix — IPFS Datasets Python

| Field | Value |
| --- | --- |
| Interface | `CapabilityStatusMatrix@1` |
| Task | `IPFSDOC-064` |
| Status | `canonical` (product capability surface) |
| Package | `ipfs_datasets_py` **0.2.0** (`pyproject.toml`) |
| Python | `requires-python = ">=3.12"` |
| Last verified | 2026-08-03 |
| Authority | Tests/schemas → current code → packaging → ADRs → guides → history ([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)) |
| Related | [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md), [SYSTEM_CONTEXT.md](architecture/SYSTEM_CONTEXT.md), [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md), [DRIFT_AND_CLAIM_MATRIX.md](maintenance/DRIFT_AND_CLAIM_MATRIX.md) |

## Purpose

This page is the **source-grounded product capability matrix** for
`ipfs_datasets_py`. It replaces undated marketing and hard count claims with
labeled capability states derived from the current tree, packaging extras, and
architecture guides.

**This is not a release notes file.** Release policy and retained history live
in [CHANGELOG.md](CHANGELOG.md). Documentation coverage (where guides exist)
lives in [COVERAGE_MATRIX.md](maintenance/COVERAGE_MATRIX.md).

### Rules for reading claims

1. **Code presence ≠ production readiness.** A package directory means code
   exists; trust, proof, and side effects follow fail-closed policy
   ([ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).
2. **Probe ≠ capability.** Feature detection may report “present” without
   authorizing use or proving correctness.
3. **Optional stacks are not base install.** Base package import is hermetic;
   heavy stacks require extras, binaries, submodules, or env flags.
4. **Counts are inventory estimates** unless a measurement command and date are
   attached. Prefer category names over “N+ tools” marketing.
5. **Empty git submodules** make nested backends **unavailable** in this
   checkout until initialized—not “missing from the product design.”

---

## Capability status vocabulary

Exactly one primary **product-status** label per row. Secondary notes may add
install or authority detail.

| Status | Meaning | Typical evidence |
| --- | --- | --- |
| **Stable** | Intended public path for new work; contracts and ownership are documented and code exists in-tree | Package path + tests/architecture leaf; packaging entry when install-facing |
| **Optional** | Works only when declared extras, native binaries, services, or initialized submodules are present | `pyproject.toml` extras; lazy installers; submodule paths |
| **Experimental** | Present and exercised, but contracts, trust class, or UX may change; not a silent production trust claim | Explicit experimental flags, portfolio provers, evolving IR adapters |
| **Compatibility** | Alias, facade, dual packaging path, or migration surface; prefer the canonical path for new work | Root facades, `setup.py`-only scripts, legacy tool trees |
| **Deprecated** | Scheduled for removal or migration; still may exist for migration windows | Deprecation modules, registry `deprecated` roles, migration guides |
| **Unavailable** | Required dependency, submodule, binary, or network is not present **in this environment**—feature degrades or errors; never silent allow for trust gates | Empty submodule checkout; missing prover binary; offline mode |

**Current** (used in tables as a snapshot qualifier) means “verified against this
tree on the date above,” not “always production-ready on every host.”

---

## 1. Product surfaces (entry points)

| Surface | Status | Anchors | Notes |
| --- | --- | --- | --- |
| Python library API | **Stable** | `ipfs_datasets_py/`, hermetic `__init__`, `initialize()` | Heavy stacks opt-in; see env flags in dependency architecture |
| MCP server (stdio default) | **Stable** | `python -m ipfs_datasets_py.mcp_server` | Tools wrap domains; do not own domain algorithms |
| MCP HTTP / FastAPI host | **Optional** | `mcp_server/fastapi_service.py`, extra `api` | Requires API stack install |
| Primary CLI (`ipfs-datasets`) | **Compatibility** | `setup.py` console_scripts; root `ipfs-datasets` wrapper | **Not** in `pyproject.toml` `[project.scripts]` |
| pyproject console scripts | **Stable** | `ipfs-datasets-install-provers`, `ipfs-datasets-sms-bridge`, `netherlands-laws`, `ipfs-netherlands-laws` | Pure pyproject install surface |
| File converter CLI (`file-converter` / `fc`) | **Compatibility** | `setup.py` only | Prefer package API or setuptools install path |
| Docker / compose / k8s | **Optional** | `docker/`, `deployments/` | Ops manifests; environment-dependent |
| Profile G planning service | **Optional** / fail-closed | `profile_g.py` → `logic.profile_g`; MCP `profile_g_service` | Placement advisory; side effects fail closed unless validators configured |

---

## 2. Packaging extras (install surface)

Authoritative keys: `pyproject.toml` `[project.optional-dependencies]` (18 extras).
`setup.py` extras are a **superset**—document setuptools-only names only when
the install path uses setuptools.

| Extra | Status | Role |
| --- | --- | --- |
| *(base / no extra)* | **Stable** | Hermetic library core; not full platform |
| `lazy` | **Optional** | Curated optional Python deps for lazy resolution (~20 catalog entries) |
| `vectors` | **Optional** | Embeddings / FAISS-class local search stack |
| `knowledge_graphs` | **Optional** | Graph / Neo4j-adjacent KG dependencies |
| `logic` | **Optional** | Logic-domain Python deps |
| `theorem-provers` | **Optional** | Python bindings toward external provers (not native Lean/Coq binaries) |
| `multimedia` | **Optional** | yt-dlp / media Python deps; FFmpeg still system-level |
| `file_conversion` | **Optional** | File converter backends |
| `ocr` | **Optional** | OCR tooling |
| `scraping` | **Optional** | Web/legal scraping stacks |
| `ipld` | **Optional** | IPLD/CAR related Python deps |
| `api` | **Optional** | FastAPI / HTTP service stack |
| `test` | **Optional** | Test harness deps |
| `legal_netherlands` | **Optional** | Netherlands laws scraper surface |
| `symai_router` | **Optional** / **Experimental** | SymbolicAI router path |
| `groth16` / `provekit` / `profile-f-zk` | **Optional** / **Experimental** | ZK / circuit profile tooling |
| `all` | **Optional** | Union of declared non-platform extras in pyproject; still not OS binaries or submodules |

**Lazy behavior:** `lazy_dependencies.py` + `auto_installer` resolve modules on
first use when configured. Lazy install does **not** turn a missing trust
dependency into an allow decision. Native provers: prefer
`ipfs-datasets-install-provers` (pyproject script) after Python extras.

There is **no** `vector`, `graphrag`, `webarchive`, or `theorem_proving` extra
key in pyproject—use the names above.

---

## 3. Major domain capability matrix

Statuses reflect **product design and current tree presence**, not a full
CI matrix for every host. Submodule-backed rows note **Unavailable** when the
declared gitlink is empty in this worktree (`git submodule status` all `-`).

### 3.1 Processing and ingest

| Capability | Status | Package anchors | Optional prerequisites | Degrades when missing |
| --- | --- | --- | --- | --- |
| Processor pipelines (PDF, batch, domains) | **Stable** | `processors/` | Domain extras as needed | Feature error / skip path |
| File conversion (`FileConverter`) | **Stable** | `processors/file_converter/` | `file_conversion` extra; system tools per backend | Conversion unavailable for that format |
| Web archiving engines | **Optional** | `web_archiving/`, `processors/web_archiving/` | Network; Common Crawl submodule | Engine **Unavailable** |
| Legal / medical scrapers | **Optional** | `processors/legal_scrapers/`, … | `scraping`, `legal_netherlands` | Scraper offline |
| Multimedia download (yt-dlp wrapper) | **Optional** | `processors/multimedia/` | `multimedia`; FFmpeg | Download/transcode **Unavailable** |
| Nested multimedia converters | **Optional** / often **Unavailable** | git submodules under `multimedia/` | `git submodule update --init` | Empty tree → **Unavailable** |
| Legacy convert_to_txt paths | **Deprecated** | migration guides; deprecation schedule | — | Prefer `FileConverter` |

### 3.2 Logic, IR, proof, and authorization

| Capability | Status | Package anchors | Notes |
| --- | --- | --- | --- |
| IR core (canonical JSON, CID identity, provenance) | **Stable** | `logic/ir_core/` | Domain-neutral kernel; not theorem authority |
| Legal IR | **Stable** | `logic/legal_ir/` | Non-interchangeable with Security/Intent |
| Security IR | **Stable** | `logic/security_ir/` | Immutable declaration/result authority patterns |
| **Intent IR** | **Stable** (schema) / **Experimental** (rollout) | `logic/intent_ir/` | Source-grounded intent documents; invocation adapters are **non-executing** |
| Intent invocation / SkillCenter adapters | **Experimental** / fail-closed | `logic/intent_ir/invocation/` | Must not be documented as silent side-effect dispatch |
| **Proof corpus** | **Stable** (store/query model) | `logic/proof_corpus/` | Attested artifacts, query, revocation; simulated ZKP is **not** production theorem authority |
| Admissibility / authorization gate | **Stable** | `logic/admissibility/` | Deny-overrides; incomplete evidence → abstain / non-allow |
| External provers (Z3, CVC5, Lean, Coq, …) | **Optional** | `logic/external_provers/`, `theorem-provers` extra | Bindings vs native binaries; lazy install path |
| ITP hammer / portfolio | **Experimental** | `logic/hammers/`, backends | Typed outcomes: proved / countermodel / UNKNOWN / unavailable |
| CEC / ShadowProver / Talos assets | **Optional** / often **Unavailable** | `logic/CEC/*` submodules | Empty checkout until initialized |
| ErgoAI placeholder | **Optional** / **Unavailable** without binary | registry `ErgoAI` | `import_check=False` style external |
| `logic.tools` | **Deprecated** / **Compatibility** | registry role | Prefer `logic.integration` |
| FOL / deontic / modal / TDFOL | **Stable**–**Experimental** by path | `logic/fol`, `deontic`, `modal`, `TDFOL` | Domain-specific; check registry |
| ZK / Groth16 / Provekit bridges | **Optional** / **Experimental** | extras + processors backends | Not base install |

### 3.3 Knowledge, retrieval, and optimization

| Capability | Status | Package anchors | Optional prerequisites |
| --- | --- | --- | --- |
| Knowledge graphs / extraction | **Stable** | `knowledge_graphs/` | `knowledge_graphs` extra for heavy backends |
| GraphRAG optimizers | **Stable**–**Experimental** | `optimizers/` (GraphRAG / agentic / theorem loops) | Models, graph backends |
| Embeddings engines | **Optional** | `embeddings/`, routers | `vectors` / model deps |
| Vector stores (FAISS, Qdrant, ES bridges) | **Optional** | `vector_stores/` | `vectors` extra; backend services |
| Search / discovery | **Stable** (library) | `search/` | Hybrid stacks optional |
| ML helpers | **Optional** / thin | `ml/` | Heavy optional stacks |

### 3.4 Storage, network, and publication

| Capability | Status | Package anchors | Notes |
| --- | --- | --- | --- |
| Storage facade / caching | **Stable** (thin) | `storage/`, `caching/` | Backend depth varies |
| IPLD / CAR helpers | **Optional** | `ipld` extra; related processors | Not full IPFS kit |
| `ipfs_kit_py` operations | **Optional** / often **Unavailable** | git submodule (root + `.tools`) | External ownership |
| `ipfs_accelerate_py` acceleration | **Optional** / often **Unavailable** | git submodule | External ownership; speedup claims require the package |
| P2P networking helpers | **Optional** | `p2p_networking/` | Network-dependent |
| Hugging Face dataset helpers | **Optional** | `huggingface/` | Hub availability external |
| Voice immutable dataset contracts | **Stable** (contracts) | `voice/`, `voice_router.py` | HF/release paths optional |

### 3.5 Trust, wallet, audit, Profile G

| Capability | Status | Package anchors | Notes |
| --- | --- | --- | --- |
| **Wallet** trust / grants / privacy | **Stable** (domain code) | `wallet/` | User-controlled trust surface; not chain settlement SLA |
| Wallet CLI / API / multisig / proofs | **Stable**–**Optional** | `wallet/cli.py`, `service.py`, `proofs.py`, … | External proof backends optional |
| Audit / provenance helpers | **Stable** (helpers) | `audit/`, package `audit.py` | **Not** formal proof authority |
| Security facade | **Compatibility** | package `security.py` | Prefer domain logic security / wallet / audit as appropriate |
| **Profile G** datasets primitives | **Stable** (facade + logic) | `profile_g.py` → `logic.profile_g` | Planning/evidence oriented |
| Profile G MCP service | **Optional** / fail-closed | `mcp_server/profile_g_service.py` | Side effects require configured validators |
| Agent supervisor / taskboards | **Unavailable** as in-tree owner | external `ipfs_accelerate` | Datasets provides compat hooks only |

### 3.6 MCP tool surface (inventory, not marketing)

| Fact | Value | Kind |
| --- | --- | --- |
| Tool category directories (`*_tools`) | **47** under `mcp_server/tools/` | Filesystem inventory (this tree) |
| Non-`__init__` tool `.py` files | **~394** | Filesystem inventory—not registered-callable census |
| Registration | `tool_registration.py`, hierarchical manager | Runtime may expose a subset |
| Legacy tools tree | **Compatibility** | `legacy_mcp_tools` |
| MCP++ peers/workflows | **Optional** / **Experimental** | `mcplusplus*` tools |

Representative **Stable** categories (directories present): `dataset_tools`,
`ipfs_tools`, `embedding_tools`, `graph_tools`, `pdf_tools`, `media_tools`,
`logic_tools`, `legal_dataset_tools`, `security_tools`, `audit_tools`,
`storage_tools`, `file_converter_tools`, `monitoring_tools`, admin/dashboard
tools, and others listed under `ipfs_datasets_py/mcp_server/tools/`.

Do **not** treat “200+ tools / 50+ categories” as an exact product KPI without
a dated registry measurement. Prefer this inventory method or a runtime
discovery command.

### 3.7 Cross-cutting lifecycle

| Capability | Status | Anchors |
| --- | --- | --- |
| Hermetic default import | **Stable** | `ipfs_datasets_py/__init__.py` flags (`IPFS_DATASETS_PY_*`) |
| Explicit `initialize()` / RouterDeps | **Stable** | `router_deps.py` |
| **Lazy** dependency proxy | **Optional** | `lazy_dependencies.py`, `auto_installer.py`, extra `lazy` |
| Capability probing without import | **Stable** | `logic/common/feature_detection.py` |
| Error reporting helpers | **Stable** | `error_reporting/` |
| Rate limiting / sessions / messaging | **Optional** / thin | respective packages; SMS bridge script |
| Package `install/` directory | **Unavailable** as feature | Empty / n/a—do not advertise |

---

## 4. External and submodule gates

| Dependency | Status in empty worktree | How to enable (operator) |
| --- | --- | --- |
| `ipfs_kit_py` | **Unavailable** until submodule init | `git submodule update --init` (or product-approved path) |
| `ipfs_accelerate_py` | **Unavailable** until submodule init | Same |
| CEC / multimedia / Common Crawl submodules | **Unavailable** until init | Same |
| Native theorem provers | **Unavailable** until install | `ipfs-datasets-install-provers` + OS packages as needed |
| IPFS daemon / network | **Optional** | Local or remote API; offline → network features **Unavailable** |

---

## 5. Explicit non-claims

The product **does not** claim any of the following as evergreen facts on this
page:

- Fixed “production-ready everywhere” for every domain listed.
- Exact tool counts, test function totals, or “4,400+ tests” without a
  measurement command and date.
- Universal “60+ formats” / “1000+ platforms” as local enumeration (those are
  backend/upstream characteristics when the optional stack is present).
- Fixed 2–20× acceleration without a populated accelerate integration and
  benchmark evidence.
- That **Intent IR**, **proof corpus**, **Profile G**, or **wallet** discovery
  equals authorization or theorem proof.
- That **lazy** install or a green probe is an allow decision for side effects.

---

## 6. Where to go next

| Need | Document |
| --- | --- |
| Install extras and first success | [installation.md](installation.md), [getting_started.md](getting_started.md) |
| Ownership and canonical imports | [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md) |
| Lazy install and probes | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) |
| Intent IR / IR family | [logic/IR_FAMILY_AND_IDENTITY.md](architecture/logic/IR_FAMILY_AND_IDENTITY.md) |
| External provers | [logic/EXTERNAL_PROVERS.md](architecture/logic/EXTERNAL_PROVERS.md) |
| Fail-closed outcomes | [ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Release / history policy | [CHANGELOG.md](CHANGELOG.md) |
| Claim drift inventory | [DRIFT_AND_CLAIM_MATRIX.md](maintenance/DRIFT_AND_CLAIM_MATRIX.md) |

---

*Capability rows are re-verified when packaging extras, major domain ownership,
or submodule topology change. Prefer architecture leaves for deep contracts.*
