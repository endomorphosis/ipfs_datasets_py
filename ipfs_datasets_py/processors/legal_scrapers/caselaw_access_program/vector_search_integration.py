"""Vector search integration for Caselaw Access Project embedding datasets.

This module provides a focused integration path for the Hugging Face dataset:
`justicedao/Caselaw_Access_Project_embeddings`.

The integration is intentionally split into three stages:
1. Discover and load embedding rows from Hugging Face parquet files
2. Ingest vectors into the project's vector store backends
3. Prepare normalized node/edge seed records for later knowledge graph building
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from ipfs_datasets_py.ml.embeddings.schema import EmbeddingResult, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class CAPVectorSearchConfig:
    """Configuration for CAP embedding ingestion and search."""

    dataset_id: str = "justicedao/Caselaw_Access_Project_embeddings"
    split: str = "train"
    cache_dir: Optional[str] = None
    text_field_candidates: Tuple[str, ...] = (
        "text",
        "content",
        "document",
        "opinion_text",
        "case_text",
        "summary",
        "title",
    )
    embedding_field_candidates: Tuple[str, ...] = (
        "embedding",
        "embeddings",
        "vector",
        "vectors",
        "centroid",
    )
    id_field_candidates: Tuple[str, ...] = (
        "chunk_id",
        "cid",
        "id",
        "case_id",
        "document_id",
    )
    metadata_priority_fields: Tuple[str, ...] = (
        "cid",
        "citation",
        "case_id",
        "court",
        "jurisdiction",
        "decision_date",
        "date",
        "docket_number",
        "reporter",
        "source",
        "cluster_id",
    )


@dataclass
class CAPIngestionResult:
    """Summary of an embedding ingestion run."""

    collection_name: str
    store_type: str
    source_file: str
    ingested_count: int
    vector_dimension: int


@dataclass
class KGSeedGraph:
    """Knowledge graph seed payload derived from search results."""

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CAPRetrievalPlan:
    """Centroid-first retrieval planning and execution metadata."""

    centroid_collection_name: str
    target_collection_name: str
    centroid_candidates: List["SearchResult"] = field(default_factory=list)
    selected_cluster_ids: List[str] = field(default_factory=list)
    retrieved_results: List["SearchResult"] = field(default_factory=list)


class CaselawAccessVectorSearch:
    """Integration helper for Caselaw Access Project vector search workflows."""

    def __init__(self, config: Optional[CAPVectorSearchConfig] = None):
        """Initialize the integration helper.

        Args:
            config: Optional configuration object.
        """
        self.config = config or CAPVectorSearchConfig()

    def list_embedding_files(
        self,
        model_hint: Optional[str] = None,
        include_centroids: bool = False,
    ) -> List[str]:
        """List candidate parquet files containing embeddings.

        Args:
            model_hint: Optional substring used to match model-specific files.
            include_centroids: Whether centroid parquet files should be included.

        Returns:
            Sorted list of parquet file paths in the dataset repository.
        """
        files = self._list_dataset_files()
        parquet_files = [f for f in files if f.endswith(".parquet")]

        filtered: List[str] = []
        for file_name in parquet_files:
            lowered = file_name.lower()
            if "cids" in lowered:
                continue
            if not include_centroids and "centroid" in lowered:
                continue
            if model_hint and model_hint.lower() not in lowered:
                continue
            filtered.append(file_name)

        return sorted(filtered)

    def list_available_models(self) -> List[str]:
        """Infer available embedding model identifiers from dataset file names."""
        files = self._list_dataset_files()
        models = set()

        canonical_patterns = (
            r"gte-qwen2-1\.5b-instruct",
            r"gte-large-en-v1\.5",
            r"gte-small",
        )

        for file_name in files:
            lowered = file_name.lower()
            if not lowered.endswith(".parquet"):
                continue
            if "cids" in lowered or "centroid" in lowered:
                continue

            matched = False
            for pattern in canonical_patterns:
                found = re.search(pattern, lowered)
                if found:
                    models.add(found.group(0))
                    matched = True
                    break

            if matched:
                continue

            # Fallback heuristic: keep only tokens that look like model identifiers.
            stem = lowered.rsplit(".parquet", 1)[0]
            for token in re.split(r"[^a-z0-9\.\-]+", stem):
                if not token:
                    continue
                if any(marker in token for marker in ("gte", "bge", "e5", "embedding")):
                    if len(token) >= 4:
                        models.add(token)

        return sorted(models)

    def describe_dataset_files(self, model_hint: Optional[str] = None) -> Dict[str, Any]:
        """Return grouped CAP file metadata for discovery and operator selection."""
        files = self._list_dataset_files()
        if model_hint:
            files = [f for f in files if model_hint.lower() in f.lower()]

        parquet_files = [f for f in files if f.endswith(".parquet")]
        centroid_files = [f for f in parquet_files if "centroid" in f.lower()]
        cid_map_files = [f for f in parquet_files if "cids" in f.lower()]
        embedding_files = [
            f
            for f in parquet_files
            if f not in centroid_files and f not in cid_map_files
        ]

        return {
            "dataset_id": self.config.dataset_id,
            "model_hint": model_hint,
            "total_files": len(files),
            "parquet_files": sorted(parquet_files),
            "embedding_files": sorted(embedding_files),
            "centroid_files": sorted(centroid_files),
            "cid_map_files": sorted(cid_map_files),
            "available_models": self.list_available_models(),
        }

    async def ingest_embeddings(
        self,
        collection_name: str,
        store_type: str = "faiss",
        parquet_file: Optional[str] = None,
        model_hint: Optional[str] = None,
        max_rows: int = 10000,
        batch_size: int = 512,
        distance_metric: str = "cosine",
        create_collection: bool = True,
        **store_kwargs: Any,
    ) -> CAPIngestionResult:
        """Ingest CAP embeddings into a vector store backend.

        Args:
            collection_name: Target vector collection name.
            store_type: Vector store backend (e.g., ``faiss`` or ``ipld``).
            parquet_file: Explicit parquet file path from the HF dataset repo.
            model_hint: Optional model selector used when ``parquet_file`` is omitted.
            max_rows: Maximum number of rows to ingest in this run.
            batch_size: Batch size for vector store writes.
            distance_metric: Store distance metric.
            create_collection: Whether to create collection if missing.
            **store_kwargs: Extra store creation kwargs.

        Returns:
            CAPIngestionResult summary object.

        Raises:
            ValueError: If no suitable parquet file is found or no embeddings are parsed.
        """
        selected_file = parquet_file or self._select_default_parquet_file(model_hint=model_hint)
        if not selected_file:
            raise ValueError("No CAP embedding parquet file could be resolved")

        rows = self._load_parquet_rows(selected_file, max_rows=max_rows)
        embeddings = self._rows_to_embeddings(rows)
        if not embeddings:
            raise ValueError(
                "No embeddings parsed from CAP parquet rows; verify schema/columns for the selected file"
            )

        vector_dimension = len(embeddings[0].embedding)

        from ipfs_datasets_py.vector_stores.api import create_vector_store

        store = await create_vector_store(
            store_type=store_type,
            collection_name=collection_name,
            dimension=vector_dimension,
            distance_metric=distance_metric,
            **store_kwargs,
        )

        if create_collection and not await store.collection_exists(collection_name):
            await store.create_collection(collection_name=collection_name, dimension=vector_dimension)

        ingested = 0
        for start in range(0, len(embeddings), batch_size):
            batch = embeddings[start : start + batch_size]
            await store.add_embeddings(batch, collection_name=collection_name)
            ingested += len(batch)

        logger.info(
            "Ingested %s CAP embeddings into %s/%s from %s",
            ingested,
            store_type,
            collection_name,
            selected_file,
        )

        return CAPIngestionResult(
            collection_name=collection_name,
            store_type=store_type,
            source_file=selected_file,
            ingested_count=ingested,
            vector_dimension=vector_dimension,
        )

    async def search_by_vector(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        store_type: str = "faiss",
        top_k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
        **store_kwargs: Any,
    ) -> List[SearchResult]:
        """Search CAP vectors using a precomputed query vector.

        Args:
            collection_name: Collection to query.
            query_vector: Query embedding vector.
            store_type: Vector store backend type.
            top_k: Number of nearest neighbors to return.
            filter_dict: Optional metadata filter.
            **store_kwargs: Extra vector store connection kwargs.

        Returns:
            List of search results.
        """
        from ipfs_datasets_py.vector_stores.api import create_vector_store

        store = await create_vector_store(
            store_type=store_type,
            collection_name=collection_name,
            dimension=len(query_vector),
            **store_kwargs,
        )
        return await store.search(
            query_vector=list(query_vector),
            top_k=top_k,
            collection_name=collection_name,
            filter_dict=filter_dict,
        )

    async def search_with_centroid_routing(
        self,
        target_collection_name: str,
        centroid_collection_name: str,
        query_vector: Sequence[float],
        store_type: str = "faiss",
        centroid_top_k: int = 5,
        per_cluster_top_k: int = 20,
        final_top_k: int = 10,
        cluster_metadata_field: str = "cluster_id",
        cluster_cids_parquet_file: Optional[str] = None,
        cid_metadata_field: str = "cid",
        cid_list_field: str = "cids",
        cluster_id_field_in_cid_map: str = "cluster_id",
        cid_candidate_multiplier: int = 20,
        base_filter_dict: Optional[Dict[str, Any]] = None,
        **store_kwargs: Any,
    ) -> CAPRetrievalPlan:
        """Run a centroid-first two-stage retrieval strategy.

        Stage 1: retrieve nearest clusters from a centroid collection.
        Stage 2: map cluster -> content IDs (cid) using cluster_cids parquet when provided.
        Stage 3: query target collection and filter candidates to mapped cids.
        """
        centroid_hits = await self.search_by_vector(
            collection_name=centroid_collection_name,
            query_vector=query_vector,
            store_type=store_type,
            top_k=centroid_top_k,
            **store_kwargs,
        )

        cluster_ids = self._extract_cluster_ids(
            centroid_hits,
            cluster_metadata_field=cluster_metadata_field,
        )

        cluster_to_cids: Dict[str, List[str]] = {}
        if cluster_cids_parquet_file:
            cluster_to_cids = self._load_cluster_to_cids_map(
                parquet_file=cluster_cids_parquet_file,
                cluster_id_field=cluster_id_field_in_cid_map,
                cid_list_field=cid_list_field,
            )

        merged_hits: Dict[str, SearchResult] = {}
        for cluster_id in cluster_ids:
            cluster_filter = dict(base_filter_dict or {})
            mapped_cids = {str(cid) for cid in cluster_to_cids.get(str(cluster_id), [])}

            # If we don't have cid mappings, fall back to cluster metadata filter.
            if not mapped_cids:
                cluster_filter[cluster_metadata_field] = cluster_id

            search_top_k = per_cluster_top_k
            if mapped_cids:
                search_top_k = max(per_cluster_top_k, per_cluster_top_k * max(cid_candidate_multiplier, 1))

            hits = await self.search_by_vector(
                collection_name=target_collection_name,
                query_vector=query_vector,
                store_type=store_type,
                top_k=search_top_k,
                filter_dict=cluster_filter or None,
                **store_kwargs,
            )

            if mapped_cids:
                hits = [
                    hit
                    for hit in hits
                    if str((hit.metadata or {}).get(cid_metadata_field, "")) in mapped_cids
                ]
                hits = hits[:per_cluster_top_k]

            for hit in hits:
                existing = merged_hits.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    merged_hits[hit.chunk_id] = hit

        ranked = sorted(merged_hits.values(), key=lambda item: item.score, reverse=True)
        return CAPRetrievalPlan(
            centroid_collection_name=centroid_collection_name,
            target_collection_name=target_collection_name,
            centroid_candidates=centroid_hits,
            selected_cluster_ids=cluster_ids,
            retrieved_results=ranked[:final_top_k],
        )

    def build_knowledge_graph_seeds(self, results: Sequence["SearchResult"]) -> KGSeedGraph:
        """Build node/edge seed records from vector search results.

        This does not construct a full graph database. It emits a normalized,
        deduplicated payload that can be fed into a future KG pipeline.

        Args:
            results: Search results returned from a CAP vector search.

        Returns:
            KGSeedGraph containing node and edge dictionaries.
        """
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: Dict[str, Dict[str, Any]] = {}

        for result in results:
            metadata = result.metadata or {}
            case_key = self._resolve_case_key(result, metadata)
            case_node_id = f"case:{case_key}"
            nodes[case_node_id] = {
                "id": case_node_id,
                "type": "Case",
                "properties": {
                    "chunk_id": result.chunk_id,
                    "score": result.score,
                    "cid": metadata.get("cid"),
                    "citation": metadata.get("citation"),
                    "court": metadata.get("court"),
                    "jurisdiction": metadata.get("jurisdiction"),
                    "decision_date": metadata.get("decision_date") or metadata.get("date"),
                },
            }

            jurisdiction = metadata.get("jurisdiction")
            if jurisdiction:
                jurisdiction_id = f"jurisdiction:{jurisdiction}"
                nodes[jurisdiction_id] = {
                    "id": jurisdiction_id,
                    "type": "Jurisdiction",
                    "properties": {"name": jurisdiction},
                }
                edge_id = f"{case_node_id}->IN_JURISDICTION->{jurisdiction_id}"
                edges[edge_id] = {
                    "id": edge_id,
                    "source": case_node_id,
                    "target": jurisdiction_id,
                    "type": "IN_JURISDICTION",
                    "properties": {},
                }

            court = metadata.get("court")
            if court:
                court_id = f"court:{court}"
                nodes[court_id] = {
                    "id": court_id,
                    "type": "Court",
                    "properties": {"name": court},
                }
                edge_id = f"{case_node_id}->DECIDED_BY->{court_id}"
                edges[edge_id] = {
                    "id": edge_id,
                    "source": case_node_id,
                    "target": court_id,
                    "type": "DECIDED_BY",
                    "properties": {},
                }

            citation = metadata.get("citation")
            if citation:
                citation_id = f"citation:{citation}"
                nodes[citation_id] = {
                    "id": citation_id,
                    "type": "Citation",
                    "properties": {"value": citation},
                }
                edge_id = f"{case_node_id}->HAS_CITATION->{citation_id}"
                edges[edge_id] = {
                    "id": edge_id,
                    "source": case_node_id,
                    "target": citation_id,
                    "type": "HAS_CITATION",
                    "properties": {},
                }

        return KGSeedGraph(nodes=list(nodes.values()), edges=list(edges.values()))

    def _list_dataset_files(self) -> List[str]:
        """List files in the configured Hugging Face dataset repository."""
        try:
            from huggingface_hub import list_repo_files
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub is required for CAP file discovery. "
                "Install with: pip install huggingface_hub"
            ) from exc

        return list_repo_files(repo_id=self.config.dataset_id, repo_type="dataset")

    def _select_default_parquet_file(self, model_hint: Optional[str] = None) -> Optional[str]:
        """Pick a default parquet embedding file using deterministic ordering."""
        files = self.list_embedding_files(model_hint=model_hint, include_centroids=False)
        if files:
            return files[0]
        files = self.list_embedding_files(model_hint=model_hint, include_centroids=True)
        return files[0] if files else None

    def _load_parquet_rows(self, parquet_file: str, max_rows: int) -> List[Dict[str, Any]]:
        """Load rows from a CAP parquet file on Hugging Face."""
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError(
                "datasets is required for CAP parquet loading. "
                "Install with: pip install datasets pyarrow"
            ) from exc

        hf_url = (
            f"https://huggingface.co/datasets/{self.config.dataset_id}/resolve/main/{parquet_file}"
        )
        split_selector = self.config.split if max_rows <= 0 else f"{self.config.split}[:{max_rows}]"

        dataset = load_dataset(
            "parquet",
            data_files={self.config.split: hf_url},
            split=split_selector,
            cache_dir=self.config.cache_dir,
        )

        rows: List[Dict[str, Any]] = []
        for row in dataset:
            rows.append(dict(row))

        return rows

    def _rows_to_embeddings(self, rows: Iterable[Dict[str, Any]]) -> List["EmbeddingResult"]:
        """Convert raw parquet rows into EmbeddingResult objects."""
        from ipfs_datasets_py.embeddings.schema import EmbeddingResult

        embeddings: List[EmbeddingResult] = []

        for row_index, row in enumerate(rows):
            vector = self._extract_embedding_vector(row)
            if vector is None:
                continue

            content = self._extract_content(row)
            chunk_id = self._extract_chunk_id(row=row, row_index=row_index)
            metadata = self._extract_metadata(row)

            embeddings.append(
                EmbeddingResult(
                    embedding=vector,
                    chunk_id=chunk_id,
                    content=content,
                    metadata=metadata,
                    model_name=metadata.get("model_name"),
                )
            )

        return embeddings

    def _extract_embedding_vector(self, row: Dict[str, Any]) -> Optional[List[float]]:
        """Extract and validate a numeric embedding vector from a row."""
        for field_name in self.config.embedding_field_candidates:
            if field_name not in row:
                continue
            vector = self._to_float_list(row[field_name])
            if vector:
                return vector

        for value in row.values():
            vector = self._to_float_list(value)
            if vector:
                return vector

        return None

    def _extract_content(self, row: Dict[str, Any]) -> str:
        """Extract content text from a row with fallback serialization."""
        for field_name in self.config.text_field_candidates:
            value = row.get(field_name)
            if isinstance(value, str) and value.strip():
                return value

        prioritized: Dict[str, Any] = {}
        for field_name in self.config.metadata_priority_fields:
            if field_name in row:
                prioritized[field_name] = row[field_name]

        if prioritized:
            return json.dumps(prioritized, sort_keys=True, default=str)

        return json.dumps(row, sort_keys=True, default=str)

    def _extract_chunk_id(self, row: Dict[str, Any], row_index: int) -> str:
        """Resolve a stable chunk ID for a row."""
        for field_name in self.config.id_field_candidates:
            value = row.get(field_name)
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str:
                return value_str

        return f"cap-row-{row_index}"

    def _extract_metadata(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata while excluding large vector payload fields."""
        metadata: Dict[str, Any] = {}
        excluded_fields = set(self.config.embedding_field_candidates)

        for key, value in row.items():
            if key in excluded_fields:
                continue
            metadata[key] = value

        return metadata

    def _resolve_case_key(self, result: "SearchResult", metadata: Dict[str, Any]) -> str:
        """Resolve a deterministic case key used by graph node IDs."""
        for candidate in ("case_id", "cid", "citation", "document_id", "id"):
            value = metadata.get(candidate)
            if value:
                return str(value)
        return result.chunk_id

    def _extract_cluster_ids(
        self,
        centroid_hits: Sequence["SearchResult"],
        *,
        cluster_metadata_field: str,
    ) -> List[str]:
        """Extract cluster IDs from centroid search hits with permissive fallbacks."""
        cluster_ids: List[str] = []
        for hit in centroid_hits:
            metadata = hit.metadata or {}

            candidate = metadata.get(cluster_metadata_field)
            if candidate is None:
                for alt in ("cluster_id", "cluster", "id", "cid"):
                    if metadata.get(alt) is not None:
                        candidate = metadata.get(alt)
                        break

            if candidate is None:
                candidate = hit.chunk_id

            candidate_str = str(candidate).strip()
            if candidate_str and candidate_str not in cluster_ids:
                cluster_ids.append(candidate_str)

        return cluster_ids

    def _load_cluster_to_cids_map(
        self,
        *,
        parquet_file: str,
        cluster_id_field: str,
        cid_list_field: str,
    ) -> Dict[str, List[str]]:
        """Load mapping of cluster_id -> list[cid] from CAP cluster_cids parquet."""
        rows = self._load_parquet_rows(parquet_file=parquet_file, max_rows=0)
        mapping: Dict[str, List[str]] = {}

        for row in rows:
            cluster_id = row.get(cluster_id_field)
            if cluster_id is None:
                for alt in ("cluster_id", "cluster", "id"):
                    if row.get(alt) is not None:
                        cluster_id = row.get(alt)
                        break
            if cluster_id is None:
                continue

            cid_values = row.get(cid_list_field)
            if cid_values is None:
                for alt in ("cids", "content_ids", "ids"):
                    if row.get(alt) is not None:
                        cid_values = row.get(alt)
                        break

            cid_list: List[str] = []
            if isinstance(cid_values, (list, tuple)):
                cid_list = [str(v) for v in cid_values if v is not None]
            elif isinstance(cid_values, str) and cid_values.strip():
                cid_list = [cid_values.strip()]

            cluster_key = str(cluster_id)
            if cluster_key not in mapping:
                mapping[cluster_key] = []
            if cid_list:
                mapping[cluster_key].extend(cid_list)

        # Deduplicate while preserving insertion order.
        deduped: Dict[str, List[str]] = {}
        for cluster_key, cids in mapping.items():
            seen = set()
            ordered = []
            for cid in cids:
                if cid in seen:
                    continue
                seen.add(cid)
                ordered.append(cid)
            deduped[cluster_key] = ordered

        return deduped

    @staticmethod
    def _to_float_list(value: Any) -> Optional[List[float]]:
        """Convert a candidate value into a float list when possible."""
        if value is None:
            return None

        if hasattr(value, "tolist"):
            value = value.tolist()

        if not isinstance(value, (list, tuple)) or not value:
            return None

        floats: List[float] = []
        for item in value:
            if isinstance(item, (int, float)):
                floats.append(float(item))
                continue
            return None

        return floats if floats else None


def create_caselaw_access_vector_search(
    config: Optional[CAPVectorSearchConfig] = None,
) -> CaselawAccessVectorSearch:
    """Factory for CaselawAccessVectorSearch."""
    return CaselawAccessVectorSearch(config=config)


__all__ = [
    "CAPVectorSearchConfig",
    "CAPIngestionResult",
    "CAPRetrievalPlan",
    "KGSeedGraph",
    "CaselawAccessVectorSearch",
    "create_caselaw_access_vector_search",
]
