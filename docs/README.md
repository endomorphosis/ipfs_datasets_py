# Documentation directory

| Field | Value |
| --- | --- |
| Interface | `DocumentationDirectoryOverview@1` |
| Task | `IPFSDOC-095` |
| Status | `canonical` (docs tree overview) |
| Owner | documentation-governance / navigation |
| Source of truth | Live `docs/` layout; [INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md); [LEGACY_DISPOSITION.md](maintenance/LEGACY_DISPOSITION.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, developer, operator, maintainer, agent |
| Related | [index.md](index.md) (product landing), [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) (deep map) |

> **Start here for product navigation:** **[index.md](index.md)** — the single
> canonical landing page. This README explains **what lives under `docs/`** and
> how the three entry files cooperate. It is not a competing product index.

---

## 1. Canonical landing flow

```text
docs/index.md                 ← product entry (audience + task routes)
    │
    ├─ Getting Started / install / user / developer journeys
    ├─ Architecture / API / Operations / Security hubs
    │
docs/DOCUMENTATION_INDEX.md   ← deep catalog of every maintained domain
docs/README.md (this file)    ← tree roles: maintained / generated / historical
```

| File | Role | Do not use it as… |
| --- | --- | --- |
| [index.md](index.md) | **Canonical product landing** | Feature marketing or completion report |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | **Deep map** of maintained guides and domains | Second home page with different claims |
| [README.md](README.md) (this file) | **Directory overview** and lifecycle map | Exhaustive link dump of every leaf |

Superseded duplicates (prefer the three files above):
`DOCUMENTATION_INDEX_COMPLETE.md`, `root_DOCUMENTATION_INDEX.md`.

---

## 2. Getting Started

| Need | Page |
| --- | --- |
| Shortest first success | [getting_started.md](getting_started.md) |
| Install + extras | [installation.md](installation.md) |
| Configuration | [configuration.md](configuration.md) |
| User journeys | [user_guide.md](user_guide.md) |
| Capability status | [FEATURES.md](FEATURES.md) |
| Tutorials | [tutorials/](tutorials/) |
| Examples | [examples/](examples/) |

Full audience routes: [index.md](index.md).

---

## 3. Directory map (by role)

### Maintained (may be current authority)

| Path | Purpose |
| --- | --- |
| `index.md`, `getting_started.md`, `installation.md`, `configuration.md`, `user_guide.md`, `developer_guide.md` | Product entry and journeys |
| `architecture/` | Architecture hub, domain leaves, ADRs |
| `developer_guides/` | Contributor map, recipes, agents, testing |
| `api/` | Source-grounded API domain references |
| `guides/operations/`, `guides/security/`, `guides/installation/`, `guides/deployment/` | Operations, Security, install detail, deploy |
| `tutorials/`, `examples/` | Workflows and samples |
| `FEATURES.md`, `GLOSSARY.md`, `CHANGELOG.md`, `faq.md` | Capability matrix, vocabulary, release policy, FAQ |
| `maintenance/` | IA, authority, coverage, disposition, receipts |
| Selected root guides (e.g. `CORE_OPERATIONS_GUIDE.md`, `MCP_QUICKSTART.md`, `IPLD_VECTOR_DATABASE_GUIDE.md`) | Product guides still at root until later disposition |

### Architecture

Canonical hub: [architecture/README.md](architecture/README.md) — system context,
domain map, processing, storage, retrieval, knowledge, logic, MCP, runtime,
wallet, and decisions.

### Developers

Canonical landing: [developer_guide.md](developer_guide.md) — setup and routes
into [developer_guides/](developer_guides/).

### API

Canonical index: [api/README.md](api/README.md) — domain pages under
[api/domains/](api/domains/). Hand-maintained maps beat generated dumps.

### Operations

Start: [guides/operations/DEPLOYMENT_AND_RUNTIME.md](guides/operations/DEPLOYMENT_AND_RUNTIME.md).
Also [guides/deployment/](guides/deployment/), [deployment/](deployment/).

### Security

Start: [guides/security/](guides/security/) (threat model, secrets, audit,
governance) and [architecture/WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md).

### Generated (regenerate; limited authority)

| Path | Notes |
| --- | --- |
| `auto_generated_stubs/`, package `*_stubs.md` | Signature dumps beside or relocated from source |
| `tdfol/_build/` | Committed Sphinx HTML — not hand-edited design |
| MkDocs `site/` (when present) | Build output from root `mkdocs.yml` |
| Some `api/*` legacy dumps | See [api/GENERATION_AND_FRESHNESS.md](api/GENERATION_AND_FRESHNESS.md) |

### Historical (not current product truth)

| Path | Notes |
| --- | --- |
| `archive/` | Completion reports, deprecated trees, reorganization history |
| `archived_stubs/` | Relocated stubs kept for audit |
| `reports/` | Project reports and session-era summaries |
| Many root `*_COMPLETE.md`, `*_SESSION_*`, undated status pages | Prefer maintenance evidence + architecture leaves |
| Versioned plan series under `logic/`, old processor integration summaries under `guides/processors/` | Plans / migration history — not evergreen architecture |

### Plans (intent only)

| Path | Notes |
| --- | --- |
| `implementation/plans/` | Program and domain plans (some protected; read-only for workers) |
| `architecture/*_PLAN.md`, `*.objectives.md`, `*.todo.md` | Proposed work — not shipped architecture |

### Evidence

| Path | Notes |
| --- | --- |
| `maintenance/CURRENT_STATE_BASELINE.md`, `DRIFT_AND_CLAIM_MATRIX.md`, `COVERAGE_MATRIX.md`, … | Measured baselines and matrices |
| `maintenance/completion_receipts/` | Task completion receipts (point-in-time) |

---

## 4. Deep component docs

Module README files under `ipfs_datasets_py/` remain the **local** entry for
package subtrees. Surface them from hubs; do not orphan them:

- [vector_stores](../ipfs_datasets_py/vector_stores/README.md)
- [search](../ipfs_datasets_py/search/README.md)
- [knowledge_graphs](../ipfs_datasets_py/knowledge_graphs/README.md)
- [logic](../ipfs_datasets_py/logic/README.md)
- [mcp_server](../ipfs_datasets_py/mcp_server/README.md)
- [optimizers](../ipfs_datasets_py/optimizers/README.md)
- [audit](../ipfs_datasets_py/audit/README.md)
- [utils](../ipfs_datasets_py/utils/README.md)

Authority map:
[PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md).
Catalog: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md).

---

## 5. Build and serve (MkDocs)

Root `mkdocs.yml` publishes from `docs/` (including generated API pages when
configured).

```bash
pip install mkdocs
mkdocs serve    # local preview
mkdocs build    # static site under site/
```

MkDocs nav may expose only a subset of pages. Prefer **index.md** +
**DOCUMENTATION_INDEX.md** for full routing; do not treat nav length as the
corpus inventory.

---

## 6. Documentation maintenance

| Rule | Reference |
| --- | --- |
| Writing contract, audiences, lifecycle | [INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md) |
| Authority order | [SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md) |
| Legacy disposition | [LEGACY_DISPOSITION.md](maintenance/LEGACY_DISPOSITION.md) |
| Package-local / generated map | [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) |
| Validation tooling | [check_docs.py](maintenance/check_docs.py), [VALIDATION_RUNBOOK.md](maintenance/VALIDATION_RUNBOOK.md) |
| Doc contribution style | [DOCUMENTATION_CONTRIBUTING.md](developer_guides/DOCUMENTATION_CONTRIBUTING.md) |

When adding or moving **maintained** pages: update [index.md](index.md) (if
entry-relevant) and [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) (domain
catalog). Do not reintroduce undated “latest features,” February marketing
blocks, or completion-percentage claims on entry pages.

---

## 7. Need help?

| Question type | Page |
| --- | --- |
| Product how-to | [index.md](index.md), [user_guide.md](user_guide.md), [faq.md](faq.md) |
| Architecture | [architecture/README.md](architecture/README.md) |
| API | [api/README.md](api/README.md) |
| Operations | [guides/operations/](guides/operations/) |
| Security | [guides/security/](guides/security/) |
| Contributing | [developer_guide.md](developer_guide.md), [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| Terms | [GLOSSARY.md](GLOSSARY.md) |
