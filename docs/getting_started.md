# Getting Started with IPFS Datasets Python

| Field | Value |
| --- | --- |
| Interface | `GettingStartedGuide@1` |
| Task | `IPFSDOC-092` |
| Status | `canonical` (root user entry) |
| Owner | user-docs |
| Package | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Last verified | 2026-08-03 |
| Audience | new developer, agent, offline operator |
| Related | [installation.md](installation.md), [configuration.md](configuration.md), [user_guide.md](user_guide.md), [FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md) |

This page is the **shortest verified first success** for `ipfs_datasets_py`.
Longer paths (MCP, retrieval, logic/proof, operations) route to **canonical
tutorials and references**—they are not re-taught here with legacy package-root
imports or invalid extras.

---

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| **Python 3.12+** | `requires-python = ">=3.12"`. Python 3.7–3.11 are **not** supported. |
| Virtual environment | Strongly recommended |
| Write access to a temp directory | First-success artifacts are disposable |

**Optional** (not needed for §3):

| Optional | Enables | If missing |
| --- | --- | --- |
| Hugging Face `datasets` | Hub/local HF loaders via `DatasetLoader` | Loader returns **unavailable**/error — use plain JSON |
| `vectors` / `faiss` / ST models | Dense embeddings + ANN | Fallback or mock scores — not production ranking |
| `knowledge_graphs` | NLP extraction / Neo4j export | In-memory graph demos may still work |
| `theorem-provers` + native solvers | Z3/CVC5/… bridges | Prover routes **unavailable**; not proof |
| MCP SDK / live server | HTTP MCP client | Use local hierarchical manager (see MCP tutorial) |
| IPFS daemon / Kubo | Real pin/add | Mock CIDs are **not** content identity |

**Do not use** nonexistent or wrong extra names (`theorem_proving`, `graphrag`,
`vector`, `webarchive`, `dev` as a pyproject extra). Real names and install
profiles: [installation.md](installation.md) and
[CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md).

---

## 2. Install (base)

```bash
# Prefer a venv
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip setuptools wheel

# From this repository (verified current-tree path)
pip install -e .

# Or, when published for your channel:
# pip install ipfs-datasets-py

python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
```

**Side effects:** may resolve vendored or VCS dependencies for `ipfs_kit_py` /
`ipfs_accelerate_py` unless `IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES=0`.
Default-on auto-install can pull packages at **use** time in developer
profiles—disable for hermetic/production images (see
[configuration.md](configuration.md)).

**Not installed by base:** native provers, FFmpeg, Kubo, Playwright browsers,
heavy `ml` / full vector stacks. Missing pieces surface as **unavailable**
features at use time, not as a failed base import.

---

## 3. Shortest verified first success (offline)

Goal: import the package, materialize a tiny **local JSON** dataset, run one
canonical `DataProcessor` transform, and clean up—**no network**, no IPFS
daemon, no Hugging Face Hub. Full multi-step offline journey (convert, mock
storage, pin disposition): [FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md).

```python
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import ipfs_datasets_py
from ipfs_datasets_py.core_operations import DataProcessor

work = Path(tempfile.mkdtemp(prefix="getting_started_"))
records = [
    {"id": "doc-1", "text": "IPFS content addressing uses CIDs for identity."},
    {"id": "doc-2", "text": "Optional stacks degrade when extras are missing."},
]
sample = work / "sample.json"

async def main() -> None:
    try:
        sample.write_text(json.dumps(records, indent=2), encoding="utf-8")
        loaded = json.loads(sample.read_text(encoding="utf-8"))
        assert isinstance(loaded, list) and len(loaded) == 2

        processor = DataProcessor()
        normalized = await processor.transform_data(loaded[0]["text"], "normalize_text")
        assert normalized.get("status") == "success", normalized

        print(
            "first_success",
            {
                "version": ipfs_datasets_py.__version__,
                "records": len(loaded),
                "transform": normalized.get("status"),
                "path": str(sample),
            },
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        print("cleanup_ok")

asyncio.run(main())
```

| Check | Pass criterion |
| --- | --- |
| Import | `ipfs_datasets_py` and `DataProcessor` import without error |
| Local JSON | Non-empty file under temp; two records load back |
| Transform | `status == "success"` from `normalize_text` |
| Network | No hub/IPFS calls required |
| Cleanup | Temp directory removed (`cleanup_ok`) |

**Honest notes**

- Prefer **plain JSON** for the first durable write. `DatasetSaver` /
  `DatasetConverter` return success **envelopes** used by CLI/MCP; treat a
  success status as an API envelope unless you also observe the written file
  (see FIRST_DATASET_WORKFLOW evidence tables).
- Package-root `load_dataset` is a **compatibility** path that needs Hugging
  Face `datasets`—not the offline first success.

**One-liner smoke (import only):**

```bash
python -c "import ipfs_datasets_py; from ipfs_datasets_py.core_operations import DataProcessor; print(ipfs_datasets_py.__version__, 'ok')"
```

**CLI (when setuptools console scripts are installed):**

```bash
# setup.py registers ipfs-datasets / ipfs-datasets-cli; or run the tree script:
python ipfs_datasets_cli.py --help
python ipfs_datasets_cli.py info version
```

If the console script is not on `PATH`, use `python ipfs_datasets_cli.py` from
the repository root—compatibility, not a failure of the library import.

---

## 4. What this first success is **not**

| Outcome | Meaning |
| --- | --- |
| Save success | Local durable write for that path only |
| Mock IPFS CID (later demos) | **Not** content identity or network pin |
| Search scores / graph facts | **Not** theorem proof |
| Tool list / MCP transport 200 | **Not** policy allow or domain success |
| Probe “module available” | **Not** production readiness or authorization |

See [ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md),
[ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md).

---

## 5. Choose your next journey

Route to the **canonical** tutorial for the full path (extras, cleanup,
unavailable labeling, evidence tables). Do not invent package-root shortcuts
documented only on old marketing pages.

| Journey | Start here | Deep references |
| --- | --- | --- |
| **Processing / storage** (datasets, convert, process, identity) | [FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md) | [CORE_AND_DATA.md](api/domains/CORE_AND_DATA.md), [storage/README.md](architecture/storage/README.md) |
| **Python / CLI / MCP** (discovery, dispatch, denial, receipts) | [MCP_CLIENT_WORKFLOW.md](tutorials/MCP_CLIENT_WORKFLOW.md) | [MCP_QUICKSTART.md](MCP_QUICKSTART.md), [MCP_AND_RUNTIME.md](api/domains/MCP_AND_RUNTIME.md), [cli_quick_start.md](quickstart/cli_quick_start.md) |
| **Retrieval / knowledge** (embeddings, vector index, graph facts) | [RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) | [PROCESSING_AND_RETRIEVAL.md](api/domains/PROCESSING_AND_RETRIEVAL.md), [retrieval/README.md](architecture/retrieval/README.md) |
| **Logic / proof** (validation, provers, typed authority—not NL “proof”) | [LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md) | [KNOWLEDGE_LOGIC_AND_PROOF.md](api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md), [RESULT_AUTHORITY.md](architecture/logic/RESULT_AUTHORITY.md) |
| **Operations** (deploy, MCP runbook, diagnostics) | [user_guide.md](user_guide.md#operations-journeys) | [guides/operations/](guides/operations/), [OPERATIONS_AND_INTEGRATIONS.md](api/domains/OPERATIONS_AND_INTEGRATIONS.md) |

Full multi-journey map, optional/side-effect/compatibility tables:
**[User Guide](user_guide.md)**.

---

## 6. Optional requirements, side effects, cleanup, unavailable

| Topic | Guidance |
| --- | --- |
| **Optional requirements** | Install only the extras/binaries your journey needs; base path needs none of them |
| **Side effects** | Model/wheel downloads, auto-install, temp indexes, prover processes, MCP ports |
| **Cleanup** | Prefer `tempfile` workspaces; delete local indexes/WARC outputs you create; stop MCP servers you start |
| **Compatibility** | Prefer `ipfs_datasets_py.core_operations` / domain packages over stale root imports (`ipfs_knn_index`, `knowledge_graph` singular, invented `EmbeddingGenerator` APIs) |
| **Unavailable / degraded** | Missing extra → error envelope, fallback vectors, mock storage, or labeled **unavailable**—never treat silence as success |

Example probe (importability only):

```bash
python -c "from ipfs_datasets_py.logic.common.feature_detection import is_module_available as a; print('faiss', a('faiss'))"
```

If a module is missing, treat the feature as **optional/unavailable**.

---

## 7. Next links

| Need | Link |
| --- | --- |
| Install / extras / natives | [installation.md](installation.md) |
| Env precedence / hermetic / offline | [configuration.md](configuration.md) |
| Capability status labels | [FEATURES.md](FEATURES.md) |
| Supported journeys (this track) | [user_guide.md](user_guide.md) |
| Example verification ledger | [EXAMPLE_VERIFICATION.md](maintenance/EXAMPLE_VERIFICATION.md) |
| Architecture hub | [architecture/README.md](architecture/README.md) |

---

**Time to first success:** minutes after a base install, offline.  
**Success rate claim:** not 100% universal—depends on Python 3.12+, a working
venv, and honest **unavailable** labeling for optional stacks.  
**Production readiness:** not claimed by this page; see ops guides and ADRs.
