# First dataset workflow

| Field | Value |
| --- | --- |
| Interface | `DatasetWorkflowTutorial@1` |
| Task | `IPFSDOC-083` |
| Status | `canonical` |
| Owner | tutorials / data plane |
| Last verified | 2026-08-03 |
| Audience | new developer, agent, offline operator |
| Related | [CORE_AND_DATA.md](../api/domains/CORE_AND_DATA.md), [storage/README.md](../architecture/storage/README.md), [ADR-001](../architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

> **Purpose.** Bounded, **offline-first** journey from install/import through
> local dataset materialization, processing, content identity, and storage.
> Every path declares optional extras, temporary files, cleanup, expected
> evidence, and **mock / unavailable** outcomes. Prefer the **canonical
> imports** below; do not invent root package shortcuts for core operations.

---

## 1. Learning objectives

By the end of this tutorial you can:

1. Install the package and declare optional extras honestly.
2. Import the reviewed core dataset/storage surfaces.
3. Materialize a local JSON sample without network access.
4. Process text with `DataProcessor` (chunk + transform).
5. Compute content identity (SHA-256) and store items via `MockStorageManager`.
6. Attempt optional pin/load paths and **label** mock or unavailable results.
7. Clean up temporary data and know what evidence counts as success.

---

## 2. Prerequisites and declared extras

### 2.1 Minimum (offline core path)

| Requirement | Notes |
| --- | --- |
| Python ≥ 3.12 | Project `requires-python` |
| Editable or installed `ipfs_datasets_py` | From this repository root |
| Write access to a temp directory | Tutorial uses `tempfile` |

```bash
# From the repository root (offline, no hub download)
pip install -e .
```

### 2.2 Optional extras (not required for the offline path)

| Extra / dependency | Enables | If missing |
| --- | --- | --- |
| `datasets` (Hugging Face) | `DatasetLoader` hub/local HF loaders | Loader returns `status="error"` — use plain JSON I/O |
| IPFS daemon / `ipfs_kit_py` pin path | Portable CIDs via real add/pin | `IPFSPinner` may return **mock** `Qm…` strings — **not** content identity |
| Format writers beyond JSON | Parquet/Arrow save paths | Stick to JSON for this tutorial |

```bash
# Optional only — not required for the offline journey
pip install datasets
# Optional IPFS tooling is environment-specific; do not assume a daemon here.
```

**Install side effects:** optional packages may download wheels. This tutorial
never requires Hugging Face Hub or IPFS network access for the **verified
offline path**.

---

## 3. Canonical imports

Use these paths for new code (reviewed in
[CORE_AND_DATA.md](../api/domains/CORE_AND_DATA.md)):

```python
from ipfs_datasets_py.core_operations import (
    DatasetLoader,
    DatasetSaver,
    DatasetConverter,
    DataProcessor,
    IPFSPinner,
    IPFSGetter,
)
from ipfs_datasets_py.storage import (
    MockStorageManager,
    StorageType,
    CompressionType,
)
```

**Avoid for this journey:**

- Treating package-root `load_dataset` as the primary dataset API (it is a
  **compatibility** lazy re-export of Hugging Face `datasets.load_dataset`).
- Invented imports such as `from ipfs_datasets_py import DatasetLoader`.
- Treating `MockStorageManager` paths as durable multi-host storage.

---

## 4. Offline workspace setup

Create a temporary workspace, write a tiny local dataset, and keep the path
for cleanup. **Temporary data:** everything under the temp directory is
disposable.

```python
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

WORK = Path(tempfile.mkdtemp(prefix="first_dataset_workflow_"))
SAMPLE_PATH = WORK / "sample.json"
SAVED_PATH = WORK / "saved.json"
CONVERTED_NOTE = WORK / "convert_result.json"

RECORDS: List[Dict[str, Any]] = [
    {
        "id": "doc-1",
        "text": "IPFS content addressing uses CIDs for identity.",
        "topic": "identity",
    },
    {
        "id": "doc-2",
        "text": "Vector indexes store locations, not content identity.",
        "topic": "retrieval",
    },
    {
        "id": "doc-3",
        "text": "Knowledge graphs hold committed entity facts.",
        "topic": "knowledge",
    },
]

SAMPLE_PATH.write_text(json.dumps(RECORDS, indent=2), encoding="utf-8")
print("workspace", WORK)
print("sample_bytes", SAMPLE_PATH.stat().st_size)
```

**Expected evidence**

| Check | Pass criterion |
| --- | --- |
| Workspace | Path exists under the system temp dir |
| Sample file | Non-empty JSON array with three objects |
| Network | No hub/IPFS calls in this step |

---

## 5. Save and convert (offline, no Hugging Face)

`DatasetSaver` and `DatasetConverter` operate on local paths. Use them when
you already have in-memory records or a local file.

```python
from ipfs_datasets_py.core_operations import DatasetSaver, DatasetConverter

saver = DatasetSaver()
save_result = saver.save_sync(RECORDS, str(SAVED_PATH), format="json")
assert save_result.get("status") == "success", save_result
print("save", save_result)

converter = DatasetConverter()
convert_result = converter.convert_sync(
    str(SAMPLE_PATH),
    target_format="csv",
    source_format="json",
)
print("convert", convert_result)
CONVERTED_NOTE.write_text(json.dumps(convert_result, indent=2), encoding="utf-8")
```

**Expected evidence**

| Surface | Success | Unavailable / degraded |
| --- | --- | --- |
| `DatasetSaver.save_sync` | `status="success"`, `destination` points at written file | Writer-specific format errors return `status="error"` |
| `DatasetConverter.convert_sync` | `status="success"` for supported local conversion | Missing format libraries → error envelope |

---

## 6. Load paths: offline JSON vs `DatasetLoader`

### 6.1 Offline-first load (always available)

Prefer plain JSON for the first success when you control the file:

```python
loaded_offline = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
assert isinstance(loaded_offline, list) and len(loaded_offline) == 3
print("offline_load_count", len(loaded_offline))
```

### 6.2 Canonical `DatasetLoader` (optional `datasets` library)

`DatasetLoader` currently requires the Hugging Face `datasets` library even
for many local paths. When the library is missing or broken, the call returns
an **error envelope** — that is **unavailable**, not silent success.

```python
from ipfs_datasets_py.core_operations import DatasetLoader

loader = DatasetLoader()
load_result = loader.load_sync(str(SAMPLE_PATH), format="json")
print("loader_status", load_result.get("status"))
print("loader_message", load_result.get("message", "")[:200])

if load_result.get("status") == "success":
    print("loader_dataset_id", load_result.get("dataset_id"))
else:
    # Expected offline disposition when HF datasets is not importable:
    # status == "error" and a message that names the missing dependency.
    assert load_result.get("status") == "error"
    print("loader_unavailable_as_expected")
```

| Outcome | Meaning | Counts as production load? |
| --- | --- | --- |
| `status="success"` with metadata | HF `datasets` path worked | Yes, for that source |
| `status="error"` missing `datasets` | **Unavailable** capability | No — use §6.1 |
| Hub name without network | Error or hang risk | Do not use offline |

---

## 7. Process: chunk and transform

Canonical import: `from ipfs_datasets_py.core_operations import DataProcessor`.

Primary methods are **async**. Valid transformations include
`normalize_text`, `filter_fields`, `clean_data`, and others on
`DataProcessor.valid_transformations`.

```python
import asyncio

from ipfs_datasets_py.core_operations import DataProcessor

processor = DataProcessor()


async def process_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed: List[Dict[str, Any]] = []
    for row in records:
        text = row["text"]
        normalized = await processor.transform_data(text, "normalize_text")
        assert normalized.get("status") == "success", normalized

        chunks = await processor.chunk_text(
            normalized["result"],
            strategy="fixed_size",
            chunk_size=40,
            overlap=5,
        )
        assert chunks.get("status") == "success", chunks

        filtered = await processor.transform_data(
            row,
            "filter_fields",
            fields=["id", "text", "topic"],
        )
        assert filtered.get("status") == "success", filtered

        processed.append(
            {
                "id": row["id"],
                "normalized_text": normalized["result"],
                "total_chunks": chunks["total_chunks"],
                "chunks": [c["text"] for c in chunks["chunks"]],
                "fields": filtered["result"],
            }
        )
    return processed


processed_rows = asyncio.run(process_records(loaded_offline))
print("processed_count", len(processed_rows))
print("first_chunks", processed_rows[0]["total_chunks"], processed_rows[0]["chunks"][:2])
```

**Expected evidence**

| Call | Pass criterion |
| --- | --- |
| `normalize_text` | `status="success"`, lowercased/stripped `result` |
| `chunk_text` | `status="success"`, `total_chunks >= 1` |
| `filter_fields` | `result` contains only requested keys |

**Invalid transformation** returns `status="error"` with the allowed list —
treat that as a caller mistake, not a mock success.

---

## 8. Content identity and mock storage

### 8.1 Content hash (identity, not location)

Content identity is a function of bytes. Collection paths and mock pins are
**not** substitutes for a content hash ([ADR-001](../architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).

```python
def content_sha256(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


identities = {
    row["id"]: content_sha256(row)
    for row in loaded_offline
}
print("identities", identities)
assert len(set(identities.values())) == len(identities)
```

### 8.2 `MockStorageManager` (in-process only)

```python
from ipfs_datasets_py.storage import (
    CompressionType,
    MockStorageManager,
    StorageType,
)

store = MockStorageManager()
store.create_collection("first_dataset", description="tutorial offline collection")

stored_ids: List[str] = []
for row in loaded_offline:
    item = store.store_item(
        row,
        storage_type=StorageType.MEMORY,
        compression=CompressionType.NONE,
        metadata={"record_id": row["id"], "sha256": identities[row["id"]]},
        tags=["tutorial", "offline"],
        collection_name="first_dataset",
    )
    stored_ids.append(item.id)
    print("stored", item.id, item.path, item.content_hash[:16])

listed = store.list_items(collection_name="first_dataset")
assert len(listed) == 3
stats = store.get_storage_stats()
print("stats_total_items", stats["basic_stats"]["total_items"])

retrieved = store.retrieve_item(stored_ids[0])
assert retrieved is not None
assert retrieved["metadata"]["record_id"] == "doc-1"
```

| Kind of truth | Example in this step |
| --- | --- |
| Content hash | `sha256` over canonical JSON bytes |
| Storage item id | Derived hash id inside `MockStorageManager` |
| Storage path | `/memory/first_dataset/<id>` — **location**, not CID |
| Durable IPFS object | **Not** created here |

`MockStorageManager` is for tests and local demos. It is **not** a production
backend and does not pin to a network.

---

## 9. Optional IPFS pin (label mock vs real)

Canonical import: `from ipfs_datasets_py.core_operations import IPFSPinner`.

Without a working pin backend, `IPFSPinner` often still returns
`status="success"` with a synthetic `Qm…` string derived from a Python `hash`.
That string is a **mock / fallback CID**, not portable multihash identity.

```python
from ipfs_datasets_py.core_operations import IPFSPinner

pinner = IPFSPinner(integration_mode="direct")
pin_result = pinner.pin_sync(str(SAMPLE_PATH))
print("pin_result", pin_result)

cid = pin_result.get("cid", "")
is_mock_shaped = (
    isinstance(cid, str)
    and cid.startswith("Qm")
    and cid[2:].isdigit()
)
if pin_result.get("status") == "success" and is_mock_shaped:
    print("pin_disposition", "mock_or_fallback_cid_not_portable")
elif pin_result.get("status") == "success":
    print("pin_disposition", "backend_reported_cid_verify_before_trust")
else:
    print("pin_disposition", "unavailable_or_error")
```

| Result shape | Disposition |
| --- | --- |
| `Qm` + digits only (e.g. `Qm049118072`) | **Mock / fallback** — not production identity |
| Real CIDv0/CIDv1 from a live daemon | Candidate pin — still verify with `IPFSGetter` / gateway |
| `status="error"` missing path | Fail-closed path error |

Do **not** record mock `Qm…` values as release or provenance identity.

---

## 10. End-to-end offline script (runnable)

The following script is the **selected runnable journey** for this tutorial.
It uses only local files, processing, hashing, and mock storage. Optional
loader/pin steps print dispositions without claiming production success.

```python
"""First-dataset offline workflow (selected runnable snippet)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from ipfs_datasets_py.core_operations import (
    DataProcessor,
    DatasetConverter,
    DatasetLoader,
    DatasetSaver,
    IPFSPinner,
)
from ipfs_datasets_py.storage import CompressionType, MockStorageManager, StorageType


def content_sha256(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="first_dataset_workflow_"))
    try:
        records: List[Dict[str, Any]] = [
            {"id": "doc-1", "text": "IPFS content addressing uses CIDs for identity.", "topic": "identity"},
            {"id": "doc-2", "text": "Vector indexes store locations, not content identity.", "topic": "retrieval"},
            {"id": "doc-3", "text": "Knowledge graphs hold committed entity facts.", "topic": "knowledge"},
        ]
        sample = work / "sample.json"
        sample.write_text(json.dumps(records, indent=2), encoding="utf-8")

        # Prefer async methods inside async main — *_sync helpers nest another
        # event loop and raise AsyncContextError when already inside asyncio.
        saver = DatasetSaver()
        save_result = await saver.save(records, str(work / "saved.json"), format="json")
        assert save_result["status"] == "success"

        convert_result = await DatasetConverter().convert(
            str(sample), target_format="csv", source_format="json"
        )
        assert convert_result["status"] == "success"

        offline = json.loads(sample.read_text(encoding="utf-8"))
        assert len(offline) == 3

        loader_result = await DatasetLoader().load(str(sample), format="json")
        print("dataset_loader", loader_result.get("status"), loader_result.get("message", "")[:120])

        processor = DataProcessor()
        chunk_total = 0
        for row in offline:
            norm = await processor.transform_data(row["text"], "normalize_text")
            assert norm["status"] == "success"
            chunks = await processor.chunk_text(
                norm["result"], strategy="fixed_size", chunk_size=40, overlap=5
            )
            assert chunks["status"] == "success"
            chunk_total += chunks["total_chunks"]

        identities = {row["id"]: content_sha256(row) for row in offline}
        store = MockStorageManager()
        store.create_collection("first_dataset", description="tutorial")
        for row in offline:
            store.store_item(
                row,
                storage_type=StorageType.MEMORY,
                compression=CompressionType.NONE,
                metadata={"record_id": row["id"], "sha256": identities[row["id"]]},
                tags=["tutorial"],
                collection_name="first_dataset",
            )
        listed = store.list_items(collection_name="first_dataset")
        assert len(listed) == 3

        pin_result = await IPFSPinner().pin(str(sample))
        cid = str(pin_result.get("cid", ""))
        mock_cid = cid.startswith("Qm") and cid[2:].isdigit()
        print(
            "evidence",
            {
                "records": len(offline),
                "chunk_total": chunk_total,
                "stored_items": len(listed),
                "identity_count": len(identities),
                "pin_status": pin_result.get("status"),
                "pin_is_mock_shaped": mock_cid,
            },
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        print("cleanup", "removed_temp_workspace")


if __name__ == "__main__":
    asyncio.run(main())
```

**How to run (from repository root, with package importable):**

```bash
python - <<'PY'
# Paste the end-to-end script body, or save it to a temp .py file and execute.
# Expected stdout includes evidence with records=3, stored_items=3, cleanup message.
PY
```

Or extract the fence to a file:

```bash
# Example: save the §10 script as /tmp/first_dataset_workflow.py then:
python /tmp/first_dataset_workflow.py
```

**Expected evidence (offline path)**

| Field | Expected |
| --- | --- |
| `records` | `3` |
| `chunk_total` | `>= 3` |
| `stored_items` | `3` |
| `identity_count` | `3` |
| `pin_is_mock_shaped` | Often `true` without a real daemon — **not** failure of the offline path |
| Temp workspace | Removed in `finally` |

---

## 11. Cleanup

| Artifact | Action |
| --- | --- |
| Temp directory from `tempfile.mkdtemp` | `shutil.rmtree(work, ignore_errors=True)` |
| In-process `MockStorageManager` | Drop reference; process exit clears memory |
| Optional HF cache (if you opted into hub loads) | Out of scope for offline path; user-managed |
| Mock pin CIDs | Do not persist as provenance |

```python
# Pattern used in §10
# shutil.rmtree(work, ignore_errors=True)
```

---

## 12. Unavailable, mock, and success matrix

| Step | Success | Unavailable | Mock / degraded |
| --- | --- | --- | --- |
| Plain JSON load | List of records | File missing | — |
| `DatasetLoader` | HF path with metadata | Missing `datasets` lib | — |
| `DatasetSaver` / convert | Written path / success envelope | Missing format dep | — |
| `DataProcessor` | `status="success"` | — | Invalid transform → error |
| Content SHA-256 | Stable hex digest | — | — |
| `MockStorageManager` | Item ids + list count | — | Entire manager is **mock storage** |
| `IPFSPinner` | Real daemon CID | Backend error | Synthetic `Qm`+digits |

---

## 13. Verification ledger (this tutorial)

| Item | Value |
| --- | --- |
| Owner | tutorials / IPFSDOC-083 |
| Source page | `docs/tutorials/FIRST_DATASET_WORKFLOW.md` |
| Setup | `pip install -e .` from repo root; no hub/IPFS required for offline path |
| Bounded command | Run §10 script; also `python -m compileall -q docs/tutorials` |
| Expected evidence | `records=3`, `stored_items=3`, cleanup printed; loader/pin dispositions explicit |
| Network / native / service | None required for offline path; `datasets` and IPFS optional |
| Last verified tree | task `IPFSDOC-083` (2026-08-03) |
| Disposition | Offline path **verified** in implementation environment; loader may be unavailable; pin often mock-shaped |

---

## 14. Next steps

| Goal | Go to |
| --- | --- |
| Embeddings, vector index, query, knowledge facts | [RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) |
| Storage architecture (CID, backends, pins) | [architecture/storage/README.md](../architecture/storage/README.md) |
| Core API reference | [api/domains/CORE_AND_DATA.md](../api/domains/CORE_AND_DATA.md) |
| Logic / proof journeys | `LOGIC_AND_PROOF_WORKFLOW.md` (sibling tutorial track) |
| MCP client journeys | `MCP_CLIENT_WORKFLOW.md` (sibling tutorial track) |

---

## 15. Non-goals

- Hugging Face hub downloads as the first success path.
- Claiming mock pins or mock storage paths as distributed completion.
- GraphRAG, ANN production ranking, or formal proof (later tutorials).
- Exhaustive format matrices or multi-node cluster operations.
