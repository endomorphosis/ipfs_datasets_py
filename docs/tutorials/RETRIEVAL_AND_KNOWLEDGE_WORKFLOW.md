# Retrieval and knowledge workflow

| Field | Value |
| --- | --- |
| Interface | `RetrievalKnowledgeTutorial@1` |
| Task | `IPFSDOC-083` |
| Status | `canonical` |
| Owner | tutorials / retrieval + knowledge planes |
| Last verified | 2026-08-03 |
| Audience | developer, agent, offline operator |
| Related | [PROCESSING_AND_RETRIEVAL.md](../api/domains/PROCESSING_AND_RETRIEVAL.md), [retrieval/README.md](../architecture/retrieval/README.md), [knowledge/README.md](../architecture/knowledge/README.md), [ADR-001](../architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

> **Purpose.** Bounded, **offline-first** journey from install/import through
> embedding generation, vector index construction, similarity query, and
> in-memory knowledge-graph facts. Declares extras, temporary data, cleanup,
> expected evidence, and **mock / fallback / unavailable** distinctions.
> Search **scores are not graph facts**; graph facts are not **proof**.

**Upstream tutorial:** complete
[FIRST_DATASET_WORKFLOW.md](FIRST_DATASET_WORKFLOW.md) first if you need local
dataset processing and content-identity patterns.

---

## 1. Learning objectives

1. Declare retrieval/knowledge extras and degrade honestly when they are missing.
2. Use **canonical imports** for embeddings, vector stores, and knowledge graphs.
3. Generate embeddings and detect **fallback** constant vectors.
4. Build a local FAISS collection (or mock index) and run a top-k query.
5. Create in-memory graph nodes/relationships with `GraphEngine`.
6. Separate embedding vector, index location, search score, and graph fact.
7. Clean up temporary indexes and state.

---

## 2. Prerequisites and declared extras

### 2.1 Minimum (offline tutorial path)

| Requirement | Notes |
| --- | --- |
| Python ≥ 3.12 | Project requirement |
| `pip install -e .` | Package importable from repo root |
| `faiss` (via `vectors` extra or direct) | Local ANN in this journey |

```bash
pip install -e .
# Recommended for the real FAISS path in this tutorial:
pip install "faiss-cpu>=1.8.0"
```

### 2.2 Optional extras

| Extra / dependency | Enables | If missing |
| --- | --- | --- |
| `vectors` / `sentence-transformers` | Production dense embeddings | `generate_embedding*` uses **fallback** low-dim constant vectors — **not** production similarity |
| `faiss-cpu` / `faiss` | `FAISSVectorStore` ANN | Import or create_collection fails; use `MockVectorStoreService` (mock scores) |
| `knowledge_graphs` (spaCy, networkx, …) | NLP extraction, Neo4j export | In-memory `GraphEngine` still works for CRUD demos |
| Qdrant / Elasticsearch daemons | Remote stores | Out of scope offline — do not require |
| Neo4j | Compatibility export | Not required for `GraphEngine` memory path |

```bash
# Optional production-quality embeddings (may download models — not offline-pure)
pip install "sentence-transformers>=3.0.0,<6.0.0"
# Optional broader extra group from pyproject:
# pip install -e ".[vectors,knowledge_graphs]"
```

**Side effects**

| Action | Side effect |
| --- | --- |
| First real ST model use | May download model weights to HF cache |
| FAISS `create_collection` / `add_embeddings` | Writes under configured `index_path`/`metadata_path` (this tutorial uses temp `WORK`) |
| `GraphEngine.save_graph` without IPLD backend | May return `None` / “persistence disabled” |
| Mock vector search | Synthetic scores and timings — **not** ranking evidence |

---

## 3. Canonical imports

```python
# Embeddings (reviewed package surface)
from ipfs_datasets_py.embeddings import (
    generate_embedding,
    generate_batch_embeddings,
)

# Vector stores — prefer submodule imports when package __init__ is soft-optional
from ipfs_datasets_py.vector_stores.config import create_faiss_config
from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
from ipfs_datasets_py.vector_stores.schema import EmbeddingResult
from ipfs_datasets_py.vector_stores.vector_store_engine import MockVectorStoreService

# Knowledge graph — prefer non-deprecated core/storage paths
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage import Entity
```

**Compatibility / avoid for new code**

| Import | Status |
| --- | --- |
| `from ipfs_datasets_py.knowledge_graphs import GraphEngine` | **Deprecated** re-export; prefer `.core` |
| `from ipfs_datasets_py.knowledge_graphs import Entity` | **Deprecated**; prefer `.storage` |
| `from ipfs_datasets_py.core_operations import KnowledgeGraphManager` | Reviewed MCP/core facade; current `Entity(id=…)` construction can **error** against storage `Entity` — prefer `GraphEngine` for this tutorial |
| Root `embeddings_router` / `embedding_router` | Compatibility routers, not the first tutorial surface |

**Core inequalities (do not collapse)**

- embedding **vector** ≠ vector-store **index** ≠ content **CID**
- search **score** ≠ committed graph **fact** ≠ **proof**
- fallback / mock embedding results ≠ production similarity
- mock vector-store scores ≠ FAISS scores over real vectors

---

## 4. Offline corpus (temporary data)

```python
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

WORK = Path(tempfile.mkdtemp(prefix="retrieval_knowledge_workflow_"))
TEXTS: List[str] = [
    "IPFS content addressing uses CIDs for identity.",
    "Vector indexes store locations, not content identity.",
    "Knowledge graphs hold committed entity facts.",
]
(WORK / "corpus.json").write_text(json.dumps(TEXTS, indent=2), encoding="utf-8")
print("workspace", WORK)
```

Cleanup requirement: remove `WORK` at the end of every full run (§10–§11).

---

## 5. Embeddings: real vs fallback

Canonical helpers are **async**. Inspect the response `message` and
`dimension` before trusting vectors for ranking.

```python
from ipfs_datasets_py.embeddings import generate_batch_embeddings, generate_embedding


def is_fallback_embedding_payload(payload: Dict[str, Any]) -> bool:
    message = str(payload.get("message", "")).lower()
    return "fallback" in message or int(payload.get("dimension") or 0) <= 8


async def encode_corpus(texts: List[str]) -> Dict[str, Any]:
    batch = await generate_batch_embeddings(texts)
    assert batch.get("status") == "success", batch
    vectors = batch["embeddings"]
    assert len(vectors) == len(texts)
    fallback = is_fallback_embedding_payload(batch)
    print(
        "embedding_batch",
        {
            "count": batch.get("count"),
            "dimension": batch.get("dimension"),
            "model": batch.get("model"),
            "fallback": fallback,
            "message": batch.get("message"),
        },
    )
    return {"batch": batch, "vectors": vectors, "fallback": fallback}


# encoding = asyncio.run(encode_corpus(TEXTS))
```

| Signal | Meaning | Production ranking? |
| --- | --- | --- |
| `message` contains `fallback` | Constant/low-dim stand-in vectors | **No** |
| `dimension` is 4 with identical rows | Fallback path in this tree | **No** |
| ST model dims (e.g. 384) without fallback message | Real encoder path | Candidate yes (still validate quality) |
| ImportError / missing torch | **Unavailable** | Use fallback only as wiring test |

When fallback is active, FAISS may still index and return hits with high
scores because vectors are constant — treat ranking as **non-authoritative**.

---

## 6. Index: FAISS collection

```python
from ipfs_datasets_py.vector_stores.config import create_faiss_config
from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
from ipfs_datasets_py.vector_stores.schema import EmbeddingResult


async def build_faiss_index(
    texts: List[str],
    vectors: List[List[float]],
    model_name: str,
    work: Path,
    collection_name: str = "rk_tutorial",
) -> FAISSVectorStore:
    """Build a FAISS collection under ``work`` (never the repo root).

    ``FAISSVectorStore`` defaults to ``./faiss_index`` and ``./faiss_metadata``
    relative to the process CWD. Pass temp paths so tutorial runs do not leave
    binary artifacts in the repository tree.
    """
    dimension = len(vectors[0])
    index_dir = work / "faiss_index"
    metadata_dir = work / "faiss_metadata"
    index_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    config = create_faiss_config(
        collection_name=collection_name,
        dimension=dimension,
        distance_metric="cosine",
        connection_params={
            "index_path": str(index_dir),
            "metadata_path": str(metadata_dir),
        },
    )
    store = FAISSVectorStore(config)
    created = await store.create_collection(collection_name, dimension=dimension)
    assert created is True

    results = [
        EmbeddingResult(
            embedding=list(vector),
            chunk_id=f"chunk-{idx}",
            content=text,
            metadata={"source": "tutorial", "ordinal": idx},
            model_name=model_name,
        )
        for idx, (text, vector) in enumerate(zip(texts, vectors))
    ]
    ids = await store.add_embeddings(results, collection_name=collection_name)
    assert len(ids) == len(texts)
    info = await store.get_collection_info(collection_name)
    print("collection_info", info)
    print("faiss_paths", {"index": str(index_dir), "metadata": str(metadata_dir)})
    return store
```

**Expected evidence**

| Field | Pass criterion |
| --- | --- |
| `create_collection` | `True` |
| `add_embeddings` | One id per text (`chunk-0` …) |
| `get_collection_info` | `total_vectors` / `active_vectors` equal corpus size; `dimension` matches |

**Unavailable:** if `faiss` cannot import, skip this section and use §7 mock
index. Do not pretend FAISS succeeded.

---

## 7. Mock index path (explicit non-production)

`MockVectorStoreService` is for development wiring. Its search results include
**synthetic** scores and timings.

```python
from ipfs_datasets_py.vector_stores.vector_store_engine import MockVectorStoreService


async def build_mock_index(
    texts: List[str],
    vectors: List[List[float]],
    collection: str = "rk_mock",
) -> MockVectorStoreService:
    service = MockVectorStoreService()
    created = await service.create_index(
        collection,
        config={"dimension": len(vectors[0]), "metric": "cosine", "index_type": "mock"},
    )
    assert created.get("status") == "created"
    payload = [
        {"id": f"v{i}", "vector": list(vec), "metadata": {"text": text}}
        for i, (text, vec) in enumerate(zip(texts, vectors))
    ]
    added = await service.add_vectors(collection, payload)
    assert added.get("status") in {"success", "added"}
    print("mock_index", created, added)
    return service
```

| Path | Production retrieval evidence? |
| --- | --- |
| `FAISSVectorStore.search` over real embeddings | Yes, when embeddings are non-fallback |
| `FAISSVectorStore.search` over fallback embeddings | Index works; **ranking not meaningful** |
| `MockVectorStoreService.search_vectors` | **No** — mock scores |

---

## 8. Query

### 8.1 FAISS query

```python
async def query_faiss(
    store: FAISSVectorStore,
    query: str,
    collection_name: str = "rk_tutorial",
    top_k: int = 2,
) -> List[Any]:
    encoded = await generate_embedding(query)
    assert encoded.get("status") == "success", encoded
    fallback = is_fallback_embedding_payload(encoded)
    hits = await store.search(
        list(encoded["embedding"]),
        top_k=top_k,
        collection_name=collection_name,
    )
    print(
        "query",
        {
            "text": query,
            "fallback_query_embedding": fallback,
            "hit_count": len(hits),
            "hits": [
                {
                    "chunk_id": h.chunk_id,
                    "score": h.score,
                    "content": h.content[:80],
                }
                for h in hits
            ],
        },
    )
    return hits
```

### 8.2 Mock query

```python
async def query_mock(
    service: MockVectorStoreService,
    query_vector: List[float],
    collection: str = "rk_mock",
    top_k: int = 2,
) -> Dict[str, Any]:
    result = await service.search_vectors(
        collection, query_vector=list(query_vector), top_k=top_k
    )
    print("mock_query", result)
    # Label explicitly — do not promote to production success.
    result["disposition"] = "mock_scores_not_production"
    return result
```

**Reading results**

- High scores with fallback embeddings do **not** mean semantic match quality.
- Mock service may return fixed decreasing scores (e.g. 0.9, 0.8) independent
  of true geometry.
- Empty hits with a real store indicate missing data or dimension mismatch —
  fail closed and inspect `dimension`.

---

## 9. Knowledge results: in-memory graph facts

Use `GraphEngine` for offline committed **nodes** and **relationships**.
This is the knowledge data plane for the tutorial — not GraphRAG orchestration
and not formal proof.

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage import Entity


def build_knowledge_demo() -> Dict[str, Any]:
    engine = GraphEngine()
    cid_node = engine.create_node(
        labels=["Concept"],
        properties={
            "name": "CID",
            "description": "Content identifier for addressed bytes",
        },
    )
    index_node = engine.create_node(
        labels=["Concept"],
        properties={
            "name": "VectorIndex",
            "description": "ANN structure over embedding vectors",
        },
    )
    rel = engine.create_relationship(
        rel_type="DISTINCT_FROM",
        start_node=str(cid_node.id),
        end_node=str(index_node.id),
        properties={"note": "identity is not index location"},
    )
    concepts = engine.find_nodes(labels=["Concept"])
    # Optional schema object (storage Entity) — fact-shaped record, not a proof
    entity = Entity(
        entity_id="entity-cid",
        entity_type="Concept",
        name="CID",
        properties={"authority": "tutorial-demo"},
        confidence=1.0,
    )
    # Persistence may be disabled offline
    root = engine.save_graph()
    print(
        "knowledge",
        {
            "node_count": len(concepts),
            "relationship_type": rel.type if hasattr(rel, "type") else "DISTINCT_FROM",
            "entity_id": entity.entity_id if hasattr(entity, "entity_id") else getattr(entity, "id", None),
            "save_graph_root": root,
            "save_disposition": (
                "persisted_cid" if root else "in_memory_only_or_persistence_disabled"
            ),
        },
    )
    return {
        "engine": engine,
        "nodes": concepts,
        "relationship": rel,
        "entity": entity,
        "root": root,
    }
```

| Object | Authority |
| --- | --- |
| `GraphEngine` node/relationship in memory | Demo **fact** in process only |
| `save_graph()` → `None` | Persistence **unavailable/disabled** — not silent durability |
| Search score from §8 | **Not** a graph fact |
| Optimizer / LLM proposal (out of scope) | Advisory only ([OPTIMIZATION_LOOPS](../architecture/knowledge/OPTIMIZATION_LOOPS.md)) |
| Formal IR proof | **Out of scope** — see logic tutorials |

---

## 10. End-to-end offline script (runnable)

Selected runnable journey: encode → FAISS index → query → knowledge graph →
cleanup. Labels fallback embeddings and mock alternatives explicitly.

```python
"""Retrieval + knowledge offline workflow (selected runnable snippet)."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from ipfs_datasets_py.embeddings import generate_batch_embeddings, generate_embedding
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage import Entity
from ipfs_datasets_py.vector_stores.config import create_faiss_config
from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
from ipfs_datasets_py.vector_stores.schema import EmbeddingResult
from ipfs_datasets_py.vector_stores.vector_store_engine import MockVectorStoreService


def is_fallback_embedding_payload(payload: Dict[str, Any]) -> bool:
    message = str(payload.get("message", "")).lower()
    return "fallback" in message or int(payload.get("dimension") or 0) <= 8


async def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="retrieval_knowledge_workflow_"))
    store: FAISSVectorStore | None = None
    try:
        texts = [
            "IPFS content addressing uses CIDs for identity.",
            "Vector indexes store locations, not content identity.",
            "Knowledge graphs hold committed entity facts.",
        ]
        (work / "corpus.json").write_text(json.dumps(texts, indent=2), encoding="utf-8")

        batch = await generate_batch_embeddings(texts)
        assert batch["status"] == "success"
        vectors = batch["embeddings"]
        fallback = is_fallback_embedding_payload(batch)
        dimension = len(vectors[0])

        # FAISS path (requires faiss). Keep index/metadata under WORK — the
        # store defaults to ./faiss_index and ./faiss_metadata in the CWD.
        collection = "rk_tutorial"
        index_dir = work / "faiss_index"
        metadata_dir = work / "faiss_metadata"
        index_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        config = create_faiss_config(
            collection_name=collection,
            dimension=dimension,
            distance_metric="cosine",
            connection_params={
                "index_path": str(index_dir),
                "metadata_path": str(metadata_dir),
            },
        )
        store = FAISSVectorStore(config)
        assert await store.create_collection(collection, dimension=dimension)
        embeddings = [
            EmbeddingResult(
                embedding=list(vec),
                chunk_id=f"chunk-{i}",
                content=text,
                metadata={"ordinal": i},
                model_name=batch.get("model"),
            )
            for i, (text, vec) in enumerate(zip(texts, vectors))
        ]
        ids = await store.add_embeddings(embeddings, collection_name=collection)
        assert len(ids) == len(texts)
        info = await store.get_collection_info(collection)

        query = await generate_embedding("What is content identity?")
        assert query["status"] == "success"
        hits = await store.search(
            list(query["embedding"]), top_k=2, collection_name=collection
        )
        assert len(hits) >= 1

        # Explicit mock index (non-production scores)
        mock = MockVectorStoreService()
        await mock.create_index(
            "rk_mock", config={"dimension": dimension, "metric": "cosine"}
        )
        await mock.add_vectors(
            "rk_mock",
            [
                {"id": f"v{i}", "vector": list(vec), "metadata": {"text": text}}
                for i, (text, vec) in enumerate(zip(texts, vectors))
            ],
        )
        mock_hits = await mock.search_vectors(
            "rk_mock", query_vector=list(query["embedding"]), top_k=2
        )

        # Knowledge graph facts (in-memory)
        engine = GraphEngine()
        n1 = engine.create_node(
            labels=["Concept"], properties={"name": "CID"}
        )
        n2 = engine.create_node(
            labels=["Concept"], properties={"name": "VectorIndex"}
        )
        engine.create_relationship(
            rel_type="DISTINCT_FROM",
            start_node=str(n1.id),
            end_node=str(n2.id),
            properties={"note": "tutorial"},
        )
        concepts = engine.find_nodes(labels=["Concept"])
        entity = Entity(
            entity_id="entity-cid",
            entity_type="Concept",
            name="CID",
            properties={"authority": "tutorial-demo"},
        )
        root = engine.save_graph()

        print(
            "evidence",
            {
                "corpus": len(texts),
                "embedding_fallback": fallback,
                "dimension": dimension,
                "faiss_vectors": info.get("total_vectors") or info.get("active_vectors"),
                "faiss_hits": len(hits),
                "mock_hit_count": len(mock_hits.get("results", [])),
                "mock_disposition": "mock_scores_not_production",
                "graph_concepts": len(concepts),
                "entity_name": entity.name,
                "save_graph_root": root,
            },
        )
    finally:
        if store is not None:
            await store.close()
        shutil.rmtree(work, ignore_errors=True)
        print("cleanup", "closed_store_and_removed_temp_workspace")


if __name__ == "__main__":
    asyncio.run(main())
```

**How to run**

```bash
# Save the §10 script and execute with package on PYTHONPATH / editable install
python /tmp/retrieval_knowledge_workflow.py
```

**Expected evidence**

| Field | Expected offline |
| --- | --- |
| `corpus` | `3` |
| `embedding_fallback` | `true` without sentence-transformers; `false` with real models |
| `faiss_vectors` | `3` when faiss available |
| `faiss_hits` | `>= 1` |
| `mock_disposition` | `mock_scores_not_production` |
| `graph_concepts` | `2` |
| `save_graph_root` | Often `None` offline |
| Cleanup | Store closed; temp dir removed |

If `faiss` is missing, the script raises on import/create — install
`faiss-cpu` or temporarily switch the FAISS block for the mock-only path in §7.

---

## 11. Cleanup

| Artifact | Action |
| --- | --- |
| Temp `WORK` directory (includes `faiss_index/` + `faiss_metadata/` under it) | `shutil.rmtree(work, ignore_errors=True)` |
| `FAISSVectorStore` | `await store.close()` then remove `WORK` (never leave `./faiss_index` at repo root) |
| `MockVectorStoreService` | Drop reference (in-process) |
| `GraphEngine` | Drop reference; no durable file unless `save_graph` returned a root |
| HF model cache (optional ST) | User-managed; not created by fallback path |

---

## 12. Unavailable, mock, and success matrix

| Step | Success | Unavailable | Mock / degraded |
| --- | --- | --- | --- |
| `generate_*_embeddings` | `status=success` + vectors | Missing module import | Fallback constant vectors (`message` says fallback) |
| FAISS create/add/search | Collection info + hits | `faiss` not installed | Meaningful geometry only with non-fallback embeddings |
| Mock vector service | Created/added/search dicts | — | **Always** non-production scores |
| `GraphEngine` CRUD | Nodes/rels findable | — | In-memory only until persistence configured |
| `save_graph` | Root CID string | Persistence disabled → `None` | Do not invent CIDs |
| GraphRAG / optimizers | Out of scope here | Optional stacks | Proposals ≠ facts |

---

## 13. Verification ledger (this tutorial)

| Item | Value |
| --- | --- |
| Owner | tutorials / IPFSDOC-083 |
| Source page | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` |
| Setup | `pip install -e .` and `faiss-cpu`; ST optional |
| Bounded command | Run §10 script; `python -m compileall -q docs/tutorials` |
| Expected evidence | FAISS vectors=3, hits≥1, graph concepts=2, fallback/mock labels printed, cleanup |
| Network / models | None required for fallback embeddings; ST may download if installed and used |
| Last verified tree | task `IPFSDOC-083` (2026-08-03) |
| Disposition | Offline FAISS+fallback+GraphEngine path **verified** in implementation environment; ranking under fallback is non-authoritative |

---

## 14. Next steps

| Goal | Go to |
| --- | --- |
| First dataset / identity / storage | [FIRST_DATASET_WORKFLOW.md](FIRST_DATASET_WORKFLOW.md) |
| Embeddings architecture | [retrieval/EMBEDDINGS_AND_INDEXING.md](../architecture/retrieval/EMBEDDINGS_AND_INDEXING.md) |
| Vector backends | [retrieval/VECTOR_STORES.md](../architecture/retrieval/VECTOR_STORES.md) |
| Query composition | [retrieval/SEARCH_AND_QUERY.md](../architecture/retrieval/SEARCH_AND_QUERY.md) |
| Graph lifecycle / GraphRAG | [knowledge/README.md](../architecture/knowledge/README.md), [graphrag_tutorial.md](graphrag_tutorial.md) |
| Logic and proof | `LOGIC_AND_PROOF_WORKFLOW.md` (sibling track) |
| API symbols | [PROCESSING_AND_RETRIEVAL.md](../api/domains/PROCESSING_AND_RETRIEVAL.md) |

---

## 15. Non-goals

- Remote Qdrant/Elasticsearch/Neo4j as required steps.
- Presenting fallback embeddings or mock scores as production retrieval quality.
- Full GraphRAG evidence chains, optimizer loops, or formal proof.
- Exhaustive hybrid fusion or streaming query contracts (see architecture leaves).
