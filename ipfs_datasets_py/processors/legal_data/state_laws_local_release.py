"""Fail-closed local assembly of a complete state-law query release.

This module joins the independently written parent corpus, canonical chunks,
BM25, vector, and graph physical layouts.  It deliberately accepts a small
manifest-fragment protocol
instead of importing a concrete vector writer: vector production is a separate
pipeline stage and may evolve without weakening this release gate.

Assembly verifies every descriptor against local bytes, exact 51-jurisdiction
coverage, cross-family parent-key/count conservation, the pinned real
``thenlper/gte-small`` inference contract, BM25/lexical-graph vocabulary
parity, official closed-frontier receipts, and the sealed source-scope/access
receipt (retaining the legacy ``source-rights`` artifact name).  Enacted law
is admitted under the government-edicts doctrine; access evidence is a crawl
integrity gate, not a claim that a state owns copyright in its laws.  The
source-scope/access receipt and ``manifest.json`` are staged inside the local
release tree.  No network or publication action is available here.
"""

from __future__ import annotations

import ast
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import zip_longest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    DEFAULT_QUARANTINED_CONTENT_SCOPES,
    STATE_STATUTORY_TEXT_RIGHTS_BASIS,
    require_live_source_rights_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_TOKEN_COUNTER_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    FIELD_ORDER,
    SCORE_ABS_TOLERANCE,
    FieldWeightConfig,
    StateLawsBm25Config,
    document_route_key,
    project_legal_document,
    robertson_sparck_jones_idf,
    shared_tokenizer_identity,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    CANONICAL_CHUNK_ARTIFACT_DIGEST_CONTRACT,
    DOCUMENT_DATA_DIR,
    DOCUMENT_SCHEMA_VERSION,
    POSTING_DATA_DIR,
    POSTING_SCHEMA_VERSION,
    QUERY_BODY_FIELDS,
    QUERY_TITLE_FIELDS,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    SCHEMA_VERSION as BM25_PHYSICAL_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunk_physical import (
    CHUNK_DATA_DIR,
    CHUNK_INDEX_KIND,
    CHUNK_ROW_SCHEMA_VERSION,
    _chunk_schema,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import ONTOLOGY_VERSION
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    RELEASE_PROFILE,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
    canonical_json_dumps,
    digest_mapping,
    normalize_relative_artifact_path,
    normalize_sha256,
    require_immutable_revision,
    require_source_rights_binding,
    validate_digest,
    validate_semantic_family_closure,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_write_canonical_json,
    confine_path,
    file_digest,
    resolve_release_root,
    validate_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    verify_descriptor as verify_artifact_descriptor,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    ExternalSortError,
    external_sort_to_file,
    iter_jsonl,
    write_jsonl_atomic,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ROUTING_ROWS_PER_INDEX,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_bm25 import (
    digest_sorted_bm25_term_statistics,
)

SCHEMA_VERSION: Final = "state-laws-local-release-assembler/v1"
MANIFEST_PATH: Final = "manifest.json"
VECTOR_ASSIGNMENT: Final = "deterministic_balanced_spherical_kmeans"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False
BM25_SEMANTIC_DOCUMENT_BATCH_ROWS: Final = 32
BM25_SEMANTIC_POSTING_BATCH_ROWS: Final = 8
SOURCE_PROVENANCE_VERIFIER_ATTESTATION_SCHEMA_VERSION: Final = (
    "state-laws-source-provenance-verifier-attestation/v1"
)
SOURCE_PROVENANCE_VERIFIER_RELATIVE_PATH: Final = (
    "ipfs_datasets_py/processors/legal_data/state_laws_source_provenance.py"
)

REQUIRED_INDEX_PATHS: Final[Mapping[str, str]] = {
    "corpus_documents": "indexes/corpus_documents.parquet",
    "corpus_chunks": "indexes/corpus_chunks.parquet",
    "bm25_document_chunks": "indexes/bm25_document_chunks.parquet",
    "bm25_keyword_shards": "indexes/bm25_keyword_shards.parquet",
    "vector_chunks": "indexes/vector_chunks.parquet",
    "vector_entry_locator": "indexes/vector_entry_locator.parquet",
    "graph_node_chunks": "indexes/graph_node_chunks.parquet",
    "graph_edge_chunks": "indexes/graph_edge_chunks.parquet",
    "graph_out_adjacency": "indexes/graph_out_adjacency.parquet",
    "graph_in_adjacency": "indexes/graph_in_adjacency.parquet",
}

REQUIRED_DATA_FAMILIES: Final = frozenset(
    {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "centroids",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
        "locator_index",
        "receipt",
    }
)

_LINEAGE_FIELDS: Final = frozenset(
    {
        "acquisition_receipt_id",
        "acquisition_time",
        "full_lineage",
        "lineage",
        "lineage_payload",
        "official_source_url",
        "parser_version",
        "release_point",
        "source_authority_class",
        "source_checksum",
        "source_cid",
        "source_lineage",
        "verification_result",
    }
)


class StateLawsLocalReleaseError(ValueError):
    """Raised when a local candidate does not satisfy release invariants."""


class MissingManifestFragmentError(StateLawsLocalReleaseError):
    """Raised when a writer does not expose its manifest fragment."""


class DescriptorIntegrityError(StateLawsLocalReleaseError):
    """Raised when a descriptor differs from staged local bytes."""


class ReleaseKeyParityError(StateLawsLocalReleaseError):
    """Raised when corpus/BM25/vector/graph parent keys diverge."""


class VectorProductionGateError(StateLawsLocalReleaseError):
    """Raised when vectors are synthetic, unpinned, or not centroid-routed."""


class ReleaseReceiptError(StateLawsLocalReleaseError):
    """Raised when source or source-scope/access receipt closure is incomplete."""


def state_laws_source_provenance_verifier_attestation() -> dict[str, str]:
    """Hash the actual shared transport-receipt admission verifier bytes."""

    target = Path(__file__).with_name("state_laws_source_provenance.py")
    if target.is_symlink() or not target.is_file():
        raise ReleaseReceiptError(
            "state-law source-provenance verifier must be a regular file"
        )
    try:
        body = target.read_bytes()
    except OSError as exc:
        raise ReleaseReceiptError(
            "state-law source-provenance verifier bytes could not be read"
        ) from exc
    if target.is_symlink() or not body:
        raise ReleaseReceiptError(
            "state-law source-provenance verifier bytes are absent or unsafe"
        )
    return {
        "relative_path": SOURCE_PROVENANCE_VERIFIER_RELATIVE_PATH,
        "schema_version": SOURCE_PROVENANCE_VERIFIER_ATTESTATION_SCHEMA_VERSION,
        "sha256": sha256(body).hexdigest(),
    }


def _require_current_source_provenance_verifier_attestation(
    value: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Require an attestation to equal freshly hashed current verifier bytes."""

    current = state_laws_source_provenance_verifier_attestation()
    if value is not None and (
        not isinstance(value, Mapping) or dict(value) != current
    ):
        raise ReleaseReceiptError(
            "state-law source-provenance verifier attestation drifted from "
            "current code"
        )
    return current


@runtime_checkable
class ManifestFragmentProvider(Protocol):
    """Protocol implemented by physical writer results."""

    def to_manifest_fragment(self) -> Mapping[str, Any]: ...


@runtime_checkable
class AlternateManifestFragmentProvider(Protocol):
    """Protocol used by the graph physical result."""

    def manifest_fragment(self) -> Mapping[str, Any]: ...


@runtime_checkable
class ChunkCidEvidenceProvider(Protocol):
    """Physical result exposing replayable canonical searchable-chunk keys."""

    def iter_chunk_cids(self) -> Iterable[str]: ...


@runtime_checkable
class DocumentChunkEvidenceProvider(Protocol):
    """Physical result exposing the exact query-hydration ordinal mapping."""

    def iter_document_chunk_keys(self) -> Iterable[tuple[int, str]]: ...


def _plain_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StateLawsLocalReleaseError(f"{name} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _descriptor_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return _plain_mapping(value, name=name)


def _fragment(value: Any, *, family: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = dict(value)
    elif isinstance(value, ManifestFragmentProvider):
        payload = dict(value.to_manifest_fragment())
    elif isinstance(value, AlternateManifestFragmentProvider):
        payload = dict(value.manifest_fragment())
    else:
        raise MissingManifestFragmentError(
            f"{family} physical result must be a mapping or manifest-fragment provider"
        )
    if not payload:
        raise MissingManifestFragmentError(f"{family} manifest fragment is empty")
    return payload


def _require_production_source(source: Any, *, family: str) -> None:
    """Reject compatibility/materialized writers at the production gate."""

    if getattr(source, "production_ready", None) is not True:
        raise StateLawsLocalReleaseError(
            f"{family} physical source is not production-ready"
        )


def _sequence_descriptors(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (Mapping, str, bytes, bytearray)):
        raise StateLawsLocalReleaseError("artifact descriptors must be a sequence")
    return [
        _descriptor_mapping(item, name=f"artifacts[{position}]")
        for position, item in enumerate(value)
    ]


def _collect_source_descriptors(
    source: Any, fragment: Mapping[str, Any]
) -> list[dict[str, Any]]:
    out = _sequence_descriptors(fragment.get("artifacts", ()))
    for attribute in (
        "data_descriptors",
        "document_descriptors",
        "posting_descriptors",
        "centroid_descriptors",
        "receipt_descriptors",
        "locator_page_descriptors",
    ):
        value = getattr(source, attribute, None)
        if value:
            out.extend(_sequence_descriptors(value))
    physical = getattr(source, "physical", None)
    if physical is not None:
        value = getattr(physical, "data_descriptors", None)
        if value:
            out.extend(_sequence_descriptors(value))
    return out


def _merge_equivalent_descriptor(
    existing: Mapping[str, Any], incoming: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    """Merge alias-rich copies of one descriptor, rejecting real drift."""

    aliases = (
        ("relative_path", "path"),
        ("sha256",),
        ("size_bytes", "byte_length"),
        ("row_count",),
        ("family",),
        ("schema_id", "schema_identifier"),
    )
    for names in aliases:
        left = _first_value(*(existing.get(name) for name in names))
        right = _first_value(*(incoming.get(name) for name in names))
        if left is not None and right is not None and left != right:
            raise DescriptorIntegrityError(
                f"conflicting descriptors for {label!r}: {names[0]} drifted"
            )
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
    return merged


def _indexes(fragment: Mapping[str, Any], *, family: str) -> dict[str, dict[str, Any]]:
    raw = fragment.get("indexes")
    if not isinstance(raw, Mapping):
        # Defensively normalize the generic vector writer's result mapping.
        if family == "vectors":
            route = fragment.get("routing_index") or fragment.get(
                "routing_index_descriptor"
            )
            if route:
                return {
                    "vector_chunks": _descriptor_mapping(route, name="vector route")
                }
        raise MissingManifestFragmentError(f"{family} fragment has no indexes mapping")
    return {
        str(name): _descriptor_mapping(descriptor, name=f"indexes.{name}")
        for name, descriptor in raw.items()
    }


def _int_value(*values: Any, name: str) -> int:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            break
        try:
            number = int(value)
        except (TypeError, ValueError):
            break
        if number >= 0:
            return number
        break
    raise StateLawsLocalReleaseError(f"{name} must be a non-negative integer")


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _extract_vector_fragment(source: Any, fragment: dict[str, Any]) -> dict[str, Any]:
    """Normalize aliases without manufacturing production evidence."""

    if "vector" not in fragment:
        layout = fragment.get("layout")
        if layout is None and hasattr(source, "layout"):
            candidate = source.layout
            layout = (
                candidate.manifest_config()
                if hasattr(candidate, "manifest_config")
                else candidate.to_dict()
                if hasattr(candidate, "to_dict")
                else candidate
            )
        if isinstance(layout, Mapping):
            fragment["vector"] = dict(layout)
    if "artifacts" not in fragment:
        data = fragment.get("data_descriptors")
        if data is not None:
            fragment["artifacts"] = data
    if "indexes" not in fragment:
        route = fragment.get("routing_index") or fragment.get(
            "routing_index_descriptor"
        )
        if route is None:
            route = getattr(source, "routing_index_descriptor", None)
        if route is not None:
            fragment["indexes"] = {"vector_chunks": route}
    return fragment


def _extract_parent_keys(
    source: Any,
    fragment: Mapping[str, Any],
    *,
    family: str,
    explicit: Mapping[str, Iterable[str]] | None,
) -> tuple[str, ...]:
    candidates: Any = None
    if explicit is not None:
        candidates = explicit.get(family)
        if candidates is None and family == "vectors":
            candidates = explicit.get("vector")
    if candidates is None:
        evidence = fragment.get("key_evidence")
        if isinstance(evidence, Mapping):
            candidates = _first_value(
                evidence.get("parent_entry_cids"),
                evidence.get("entry_cids"),
            )
    if candidates is None:
        evidence = getattr(source, "key_evidence", None)
        if isinstance(evidence, Mapping):
            candidates = _first_value(
                evidence.get("parent_entry_cids"),
                evidence.get("entry_cids"),
            )
    if candidates is None and family == "corpus":
        rows = getattr(source, "rows", None)
        if rows is not None:
            candidates = [row["entry_cid"] for row in rows]
    if candidates is None and family == "bm25":
        index = getattr(source, "index", None)
        documents = getattr(index, "documents", None)
        if documents is not None:
            candidates = [
                document.parent_entry_cid or document.entry_cid
                for document in documents
            ]
    if candidates is None and family == "graph":
        graph = getattr(source, "graph", None)
        nodes = getattr(graph, "nodes", None)
        if nodes is not None:
            candidates = [node.entry_cid for node in nodes if node.entry_cid]
    if candidates is None and family == "vectors":
        candidates = getattr(source, "entry_cids", None)
    if candidates is None or isinstance(candidates, (str, bytes, bytearray)):
        raise ReleaseKeyParityError(
            f"{family} must expose runtime parent_entry_cid key evidence"
        )
    keys = tuple(str(item).strip() for item in candidates)
    if not keys or any(not item for item in keys):
        raise ReleaseKeyParityError(f"{family} key evidence is empty or malformed")
    return tuple(sorted(set(keys)))


def _assert_key_parity(key_sets: Mapping[str, tuple[str, ...]]) -> dict[str, Any]:
    corpus = key_sets["corpus"]
    for family in ("chunks", "bm25", "vectors", "graph"):
        if key_sets[family] != corpus:
            missing = sorted(set(corpus) - set(key_sets[family]))[:10]
            extra = sorted(set(key_sets[family]) - set(corpus))[:10]
            raise ReleaseKeyParityError(
                f"{family} parent-key set diverges from corpus: "
                f"missing={missing}, extra={extra}"
            )
    return {
        "exact": True,
        "parent_entry_cid_count": len(corpus),
        "parent_entry_cids_sha256": digest_mapping({"parent_entry_cids": list(corpus)}),
    }


def _document_chunk_records(
    source: Any,
    *,
    family: str,
) -> Iterable[dict[str, Any]]:
    if not isinstance(source, DocumentChunkEvidenceProvider):
        raise ReleaseKeyParityError(
            f"{family} physical source must expose replayable "
            "iter_document_chunk_keys()"
        )
    for position, value in enumerate(source.iter_document_chunk_keys()):
        try:
            document_index, chunk_cid = value
        except (TypeError, ValueError) as exc:
            raise ReleaseKeyParityError(
                f"{family} positional chunk key {position} is malformed"
            ) from exc
        if type(document_index) is not int or document_index < 0:
            raise ReleaseKeyParityError(
                f"{family} document index {position} is malformed"
            )
        if (
            not isinstance(chunk_cid, str)
            or not chunk_cid.strip()
            or chunk_cid != chunk_cid.strip()
            or "\x00" in chunk_cid
        ):
            raise ReleaseKeyParityError(
                f"{family} chunk CID {position} is empty or malformed"
            )
        yield {"chunk_cid": chunk_cid, "document_index": document_index}


def _assert_dense_document_chunk_file(
    path: Path,
    *,
    family: str,
    expected_count: int,
) -> None:
    observed = 0
    for expected_index, row in enumerate(iter_jsonl(path)):
        document_index = row.get("document_index")
        chunk_cid = row.get("chunk_cid")
        if document_index != expected_index:
            raise ReleaseKeyParityError(
                f"{family} document indexes are not dense: "
                f"{document_index!r}/{expected_index}"
            )
        if not isinstance(chunk_cid, str) or not chunk_cid:
            raise ReleaseKeyParityError(
                f"{family} positional chunk evidence contains an empty CID"
            )
        observed += 1
    if observed != expected_count:
        raise ReleaseKeyParityError(
            f"{family} positional chunk evidence count diverges from physical rows: "
            f"{observed}/{expected_count}"
        )


def _chunk_cid_records_from_mapping(path: Path) -> Iterable[dict[str, str]]:
    for row in iter_jsonl(path):
        yield {"chunk_cid": str(row.get("chunk_cid") or "")}


def _assert_unique_sorted_chunk_file(
    path: Path,
    *,
    family: str,
    expected_count: int,
) -> None:
    previous: str | None = None
    observed = 0
    for row in iter_jsonl(path):
        chunk_cid = str(row.get("chunk_cid") or "")
        if not chunk_cid:
            raise ReleaseKeyParityError(
                f"{family} sorted chunk evidence contains an empty CID"
            )
        if chunk_cid == previous:
            raise ReleaseKeyParityError(
                f"{family} chunk evidence contains duplicate CID {chunk_cid!r}"
            )
        if previous is not None and chunk_cid < previous:
            raise ReleaseKeyParityError(
                f"{family} canonical chunk evidence is not lexicographically sorted"
            )
        previous = chunk_cid
        observed += 1
    if observed != expected_count:
        raise ReleaseKeyParityError(
            f"{family} chunk evidence count diverges from its physical rows: "
            f"{observed}/{expected_count}"
        )


def _assert_chunk_cid_parity(
    chunks: Any,
    bm25: Any,
    vectors: Any,
    *,
    expected_count: int,
) -> dict[str, Any]:
    """Prove exact canonical-chunk/BM25/vector identity and ordinal parity."""

    with TemporaryDirectory(prefix="state-laws-chunk-parity-") as temporary:
        work = Path(temporary)
        mapping_receipts = {}
        cid_receipts = {}
        for family, source in (
            ("chunks", chunks),
            ("bm25", bm25),
            ("vectors", vectors),
        ):
            try:
                mapping_receipt = external_sort_to_file(
                    _document_chunk_records(source, family=family),
                    work / f"{family}-mapping.jsonl",
                    work_dir=work / f"{family}-mapping-sort",
                    key_fn=lambda row: (
                        int(row["document_index"]),
                        str(row["chunk_cid"]),
                    ),
                    family="documents",
                    max_records_in_memory=DEFAULT_MAX_RECORDS_IN_MEMORY,
                    resume=False,
                )
            except (ExternalSortError, OSError, ValueError) as exc:
                raise ReleaseKeyParityError(
                    f"{family} positional chunk evidence could not be canonicalized: "
                    f"{exc}"
                ) from exc
            if mapping_receipt.interrupted or mapping_receipt.status != "complete":
                raise ReleaseKeyParityError(
                    f"{family} positional chunk external sort did not complete"
                )
            if mapping_receipt.row_count != expected_count:
                raise ReleaseKeyParityError(
                    f"{family} chunk evidence count diverges from searchable rows: "
                    f"{mapping_receipt.row_count}/{expected_count}"
                )
            _assert_dense_document_chunk_file(
                Path(mapping_receipt.output_path),
                family=family,
                expected_count=expected_count,
            )
            try:
                cid_receipt = external_sort_to_file(
                    _chunk_cid_records_from_mapping(Path(mapping_receipt.output_path)),
                    work / f"{family}-cids.jsonl",
                    work_dir=work / f"{family}-cid-sort",
                    key_fn=lambda row: str(row["chunk_cid"]),
                    family="chunks",
                    max_records_in_memory=DEFAULT_MAX_RECORDS_IN_MEMORY,
                    resume=False,
                )
            except (ExternalSortError, OSError, ValueError) as exc:
                raise ReleaseKeyParityError(
                    f"{family} chunk identities could not be canonicalized: {exc}"
                ) from exc
            if cid_receipt.interrupted or cid_receipt.status != "complete":
                raise ReleaseKeyParityError(
                    f"{family} chunk-identity external sort did not complete"
                )
            _assert_unique_sorted_chunk_file(
                Path(cid_receipt.output_path),
                family=family,
                expected_count=expected_count,
            )
            mapping_receipts[family] = mapping_receipt
            cid_receipts[family] = cid_receipt

        canonical_cids = cid_receipts["chunks"]
        canonical_mapping = mapping_receipts["chunks"]
        for family in ("bm25", "vectors"):
            other_cids = cid_receipts[family]
            if canonical_cids.output_digest != other_cids.output_digest:
                missing = object()
                for position, (canonical_row, other_row) in enumerate(
                    zip_longest(
                        iter_jsonl(canonical_cids.output_path),
                        iter_jsonl(other_cids.output_path),
                        fillvalue=missing,
                    )
                ):
                    canonical_cid = (
                        None
                        if canonical_row is missing
                        else str(canonical_row.get("chunk_cid") or "")
                    )
                    other_cid = (
                        None
                        if other_row is missing
                        else str(other_row.get("chunk_cid") or "")
                    )
                    if canonical_cid != other_cid:
                        raise ReleaseKeyParityError(
                            f"canonical chunks/{family} chunk-CID sets diverge at "
                            f"canonical position {position}: "
                            f"{canonical_cid!r}/{other_cid!r}"
                        )
                raise ReleaseKeyParityError(
                    f"canonical chunks/{family} chunk-CID digests diverge"
                )

            other_mapping = mapping_receipts[family]
            if canonical_mapping.output_digest != other_mapping.output_digest:
                missing = object()
                for position, (canonical_row, other_row) in enumerate(
                    zip_longest(
                        iter_jsonl(canonical_mapping.output_path),
                        iter_jsonl(other_mapping.output_path),
                        fillvalue=missing,
                    )
                ):
                    if canonical_row != other_row:
                        raise ReleaseKeyParityError(
                            "canonical chunks/"
                            f"{family} document-index/chunk-CID mappings diverge "
                            f"at canonical position {position}: "
                            f"{canonical_row!r}/{other_row!r}"
                        )
                raise ReleaseKeyParityError(
                    f"canonical chunks/{family} positional mapping digests diverge"
                )

        return {
            "chunk_cid_count": expected_count,
            "chunk_cids_exact": True,
            "chunk_cids_sha256": canonical_cids.output_digest,
            "document_chunk_mapping_exact": True,
            "document_chunk_mapping_sha256": canonical_mapping.output_digest,
            "chunk_sort_max_records_in_memory": DEFAULT_MAX_RECORDS_IN_MEMORY,
            "chunk_sort_peak_resident_records": max(
                *(
                    receipt.peak_resident_records
                    for receipt in (
                        *mapping_receipts.values(),
                        *cid_receipts.values(),
                    )
                )
            ),
        }


def _assert_no_quarantine(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"
            if "quarant" in key_text:
                if isinstance(item, bool):
                    if item:
                        raise StateLawsLocalReleaseError(
                            f"quarantine is enabled at {child_path}"
                        )
                elif isinstance(item, (int, float)):
                    if item != 0:
                        raise StateLawsLocalReleaseError(
                            f"non-zero quarantine count at {child_path}"
                        )
                elif item not in (None, "", (), [], {}):
                    raise StateLawsLocalReleaseError(
                        f"quarantine content is present at {child_path}"
                    )
            _assert_no_quarantine(item, path=child_path)
    elif isinstance(value, (list, tuple)):
        for position, item in enumerate(value):
            _assert_no_quarantine(item, path=f"{path}[{position}]")


def _verify_descriptor(
    root: Path,
    descriptor: Mapping[str, Any],
    *,
    surface: str,
) -> dict[str, Any]:
    payload = dict(descriptor)
    relative_path = normalize_relative_artifact_path(
        payload.get("relative_path") or payload.get("path"),
        name=f"{surface}.relative_path",
    )
    digest = normalize_sha256(payload.get("sha256"), name=f"{surface}.sha256")
    size_bytes = _int_value(payload.get("size_bytes"), name=f"{surface}.size_bytes")
    row_count = _int_value(payload.get("row_count", 0), name=f"{surface}.row_count")
    payload.update(
        {
            "relative_path": relative_path,
            "row_count": row_count,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
    )
    try:
        path = verify_artifact_descriptor(root, payload)
    except Exception as exc:
        raise DescriptorIntegrityError(
            f"{surface} differs from staged bytes: {relative_path}"
        ) from exc
    media_type = str(payload.get("media_type") or "")
    if relative_path.endswith(".parquet") or "parquet" in media_type:
        try:
            validate_zstd_parquet(
                path,
                max_rows=MAX_ROWS_PER_PHYSICAL_SHARD,
                expected_row_count=row_count,
            )
        except Exception as exc:
            raise DescriptorIntegrityError(
                f"{surface} Parquet integrity failed: {relative_path}: {exc}"
            ) from exc
    return payload


def _read_canonical_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Read one release JSON object and reject aliases/non-canonical bytes."""

    if path.is_symlink() or not path.is_file():
        raise ReleaseReceiptError(f"{label} is missing or unsafe")
    try:
        encoded = path.read_bytes()
        payload = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseReceiptError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ReleaseReceiptError(f"{label} must be a JSON object")
    canonical = canonical_json_bytes(payload)
    if encoded not in {canonical, canonical + b"\n"}:
        raise ReleaseReceiptError(f"{label} is not canonical JSON")
    return dict(payload)


def _parquet_direct_columns(path: Path) -> frozenset[str]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise StateLawsLocalReleaseError(
            "pyarrow is required to assemble a release"
        ) from exc
    return frozenset(pq.ParquetFile(path).schema_arrow.names)


def _assert_lineage_not_duplicated(
    root: Path, descriptors: Sequence[Mapping[str, Any]]
) -> None:
    for descriptor in descriptors:
        family = str(descriptor.get("family") or "").strip().lower()
        if family in {"corpus", "receipt", "source_receipt"}:
            continue
        metadata = descriptor.get("metadata")
        if isinstance(metadata, Mapping):
            duplicated = _LINEAGE_FIELDS & {str(key) for key in metadata}
            if duplicated:
                raise StateLawsLocalReleaseError(
                    f"descriptor {descriptor['relative_path']} duplicates lineage "
                    f"in metadata: {sorted(duplicated)}"
                )
        path = confine_path(root, str(descriptor["relative_path"]))
        if path.suffix == ".parquet":
            duplicated = _LINEAGE_FIELDS & _parquet_direct_columns(path)
            if duplicated:
                raise StateLawsLocalReleaseError(
                    f"non-corpus artifact {descriptor['relative_path']} duplicates "
                    f"source lineage columns: {sorted(duplicated)}"
                )


def _validate_source_receipt_records(
    receipts: Sequence[SourceReceiptRecord],
    key_count: int,
) -> tuple[SourceReceiptRecord, ...]:
    """Validate the semantic exact-51 closure of typed source receipts."""

    receipts = tuple(receipts)
    if len(receipts) != EXPECTED_JURISDICTION_COUNT:
        raise ReleaseReceiptError(
            f"default release requires {EXPECTED_JURISDICTION_COUNT} source receipts"
        )
    if {receipt.jurisdiction for receipt in receipts} != set(CANONICAL_JURISDICTIONS):
        raise ReleaseReceiptError(
            "source receipts do not cover the exact 50 states + DC"
        )
    total_reported = 0
    for receipt in receipts:
        if receipt.source_authority_class is not SourceAuthorityClass.OFFICIAL:
            raise ReleaseReceiptError(f"{receipt.jurisdiction} receipt is not official")
        if receipt.verification_result is not VerificationResult.VERIFIED:
            raise ReleaseReceiptError(f"{receipt.jurisdiction} receipt is not verified")
        if not receipt.frontier_closed or receipt.failed_final or receipt.quarantined:
            raise ReleaseReceiptError(
                f"{receipt.jurisdiction} receipt has incomplete frontier work"
            )
        if receipt.payload.get("admission_eligible") is not True:
            raise ReleaseReceiptError(
                f"{receipt.jurisdiction} receipt lacks admission_eligible=true"
            )
        if receipt.payload.get("qualification_reasons"):
            raise ReleaseReceiptError(
                f"{receipt.jurisdiction} receipt has qualification reasons"
            )
        count = _first_value(
            receipt.payload.get("reported_canonical_row_count"),
            receipt.payload.get("adapter_input_row_count"),
        )
        if count is None:
            raise ReleaseReceiptError(
                f"{receipt.jurisdiction} receipt lacks canonical row-count evidence"
            )
        total_reported += int(count)
    if total_reported != key_count:
        raise ReleaseReceiptError(
            f"source receipts report {total_reported} rows, corpus has {key_count}"
        )
    return receipts


def _validate_source_receipts(
    corpus: Any, key_count: int
) -> tuple[SourceReceiptRecord, ...]:
    receipts = tuple(getattr(corpus, "source_receipts", ()) or ())
    if not all(isinstance(receipt, SourceReceiptRecord) for receipt in receipts):
        raise ReleaseReceiptError(
            "source receipts must be typed SourceReceiptRecord values"
        )
    return _validate_source_receipt_records(receipts, key_count)


def _state_rights_admission_ids(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the exact state-statutory rights IDs and reject unrelated IDs."""

    raw = receipt.get("admitted_record_ids") or receipt.get("admitted_source_ids") or ()
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise ReleaseReceiptError(
            "source-rights admitted_record_ids must be a sequence"
        )
    admitted = tuple(str(item).strip() for item in raw if str(item).strip())
    if len(admitted) != len(set(admitted)):
        raise ReleaseReceiptError("source-rights admitted_record_ids are not unique")

    decisions_raw = receipt.get("decisions") or ()
    if isinstance(decisions_raw, (str, bytes, bytearray)) or not isinstance(
        decisions_raw, Sequence
    ):
        raise ReleaseReceiptError("source-rights decisions must be a sequence")
    decisions: dict[str, Mapping[str, Any]] = {}
    for position, value in enumerate(decisions_raw):
        if not isinstance(value, Mapping):
            raise ReleaseReceiptError(
                f"source-rights decisions[{position}] must be an object"
            )
        record_id = str(value.get("record_id") or "").strip()
        if not record_id:
            raise ReleaseReceiptError(
                f"source-rights decisions[{position}] lacks record_id"
            )
        if record_id in decisions:
            raise ReleaseReceiptError(
                f"source-rights decisions duplicate record_id {record_id!r}"
            )
        decisions[record_id] = value
    if not decisions:
        raise ReleaseReceiptError(
            "source-rights receipt lacks record-level admission decisions"
        )
    decision_admitted_ids = {
        record_id
        for record_id, decision in decisions.items()
        if decision.get("admitted") is True
    }
    if decision_admitted_ids != set(admitted):
        raise ReleaseReceiptError(
            "source-rights admitted_record_ids do not exactly match admitted decisions"
        )

    by_jurisdiction: dict[str, list[str]] = {
        code: [] for code in CANONICAL_JURISDICTION_ORDER
    }
    unrelated: list[str] = []
    for record_id in admitted:
        lowered = record_id.casefold()
        code = next(
            (
                candidate
                for candidate in CANONICAL_JURISDICTION_ORDER
                if lowered.startswith(f"{candidate.casefold()}-")
            ),
            None,
        )
        if code is not None:
            by_jurisdiction[code].append(record_id)
            decision = decisions.get(record_id)
            if decision is None or (
                decision.get("admitted") is not True
                or decision.get("authorizing") is not True
                or str(decision.get("content_scope") or "").strip().casefold()
                != "statutory_text"
                or str(decision.get("rights_disposition") or "").strip().casefold()
                != "allowed"
            ):
                raise ReleaseReceiptError(
                    f"state rights admission {record_id!r} is not admitted statutory text"
                )
            continue

        # The shared rights receipt currently also covers the exact Federal
        # Register source.  It is harmless to carry that reviewed decision in
        # the release file, but arbitrary additional IDs are not state-law
        # admission evidence and must fail closed.
        decision = decisions.get(record_id)
        if decision is None or (
            decision.get("admitted") is not True
            or decision.get("authorizing") is not True
            or str(decision.get("content_scope") or "").strip().casefold()
            != "federal_government_text"
            or str(decision.get("rights_disposition") or "").strip().casefold()
            != "allowed"
        ):
            unrelated.append(record_id)

    if unrelated:
        raise ReleaseReceiptError(
            f"source-rights receipt contains unrelated admitted IDs: {sorted(unrelated)}"
        )
    drift = {
        code: values for code, values in by_jurisdiction.items() if len(values) != 1
    }
    if drift:
        raise ReleaseReceiptError(
            "source-rights receipt must bind exactly one statutory-text record "
            f"for every jurisdiction: {drift}"
        )
    declared_count = receipt.get("admitted_count")
    if declared_count is not None and (
        isinstance(declared_count, bool) or int(declared_count) != len(admitted)
    ):
        raise ReleaseReceiptError(
            "source-rights admitted_count does not match admitted_record_ids"
        )
    return tuple(by_jurisdiction[code][0] for code in CANONICAL_JURISDICTION_ORDER)


def _declared_rights_receipt_digest(receipt: Mapping[str, Any]) -> str:
    """Validate and return the receipt's declared content identity."""

    digest_field = next(
        (
            name
            for name in ("report_digest_sha256", "receipt_digest", "digest")
            if receipt.get(name) not in (None, "")
        ),
        None,
    )
    if digest_field is None:
        raise ReleaseReceiptError("source-rights receipt has no declared digest")
    declared = normalize_sha256(
        receipt[digest_field], name="source_rights_receipt_digest"
    )
    body = dict(receipt)
    body.pop(digest_field)
    if digest_mapping(body) != declared:
        raise ReleaseReceiptError(
            "source-rights receipt declared digest does not match its JSON content"
        )
    return declared


def _validate_rights_receipt(
    value: Mapping[str, Any],
    *,
    source_receipt_ids: Iterable[str],
) -> dict[str, Any]:
    receipt = _plain_mapping(value, name="rights_receipt")
    try:
        receipt = require_live_source_rights_receipt(receipt)
    except (OSError, TypeError, ValueError) as exc:
        raise ReleaseReceiptError(
            f"source-rights receipt failed authoritative live verification: {exc}"
        ) from exc
    status = str(receipt.get("status") or "").strip().lower()
    if status not in {"pass", "passed", "complete", "completed", "ok"}:
        raise ReleaseReceiptError(f"source-rights receipt did not pass: {status!r}")
    receipt_digest = _declared_rights_receipt_digest(receipt)
    catalog_digest = normalize_sha256(
        receipt.get("catalog_digest_sha256") or receipt.get("catalog_digest"),
        name="source_rights_catalog_digest",
    )
    admitted = _state_rights_admission_ids(receipt)
    source_ids = tuple(str(item).strip() for item in source_receipt_ids)
    if len(source_ids) != len(set(source_ids)):
        raise ReleaseReceiptError("source receipt IDs are not unique")
    blocked = {
        str(item).strip()
        for item in (
            *(receipt.get("prohibited_ids") or ()),
            *(receipt.get("unknown_ids") or ()),
            *(receipt.get("denied_record_ids") or ()),
        )
        if str(item).strip()
    }
    admitted_overlap = blocked & set(admitted)
    if admitted_overlap:
        raise ReleaseReceiptError(
            "source-rights receipt both admits and blocks IDs: "
            f"{sorted(admitted_overlap)}"
        )
    overlap = blocked & set(source_ids)
    if overlap:
        raise ReleaseReceiptError(
            f"source receipts bind prohibited/unknown rights identifiers: {sorted(overlap)}"
        )
    return {
        "admitted_record_count": len(admitted),
        "admitted_record_ids": list(admitted),
        "catalog_digest_sha256": catalog_digest,
        "excluded_content_scopes": sorted(
            scope.value for scope in DEFAULT_QUARANTINED_CONTENT_SCOPES
        ),
        "prohibited_and_unknown_excluded_from_default": True,
        "receipt_digest": receipt_digest,
        "relative_path": str(receipt.get("path") or SOURCE_RIGHTS_RECEIPT_RELPATH),
        "status": status,
        "statutory_text_rights_basis": STATE_STATUTORY_TEXT_RIGHTS_BASIS,
    }


def _stage_rights_receipt(
    root: Path,
    receipt: Mapping[str, Any],
    *,
    normalized: Mapping[str, Any],
) -> dict[str, Any]:
    """Stage and describe the exact source-scope/access receipt JSON."""

    relative_path = normalize_relative_artifact_path(
        normalized.get("relative_path"), name="source_rights_receipt.relative_path"
    )
    if relative_path != SOURCE_RIGHTS_RECEIPT_RELPATH:
        raise ReleaseReceiptError(
            "source-rights receipt must use the canonical in-release path"
        )
    target = confine_path(root, relative_path)
    if target.is_symlink():
        raise ReleaseReceiptError("source-rights receipt path is an unsafe symlink")
    atomic_write_canonical_json(target, dict(receipt))
    size_bytes, digest = file_digest(target)
    declared_digest = str(normalized["receipt_digest"])
    descriptor = {
        "family": "report",
        "first_key": declared_digest,
        "last_key": declared_digest,
        "media_type": "application/json",
        "metadata": {
            "receipt_digest": declared_digest,
            "receipt_kind": "source_rights_receipt",
        },
        "relative_path": relative_path,
        "row_count": 1,
        "schema_id": str(
            receipt.get("report_schema")
            or receipt.get("schema_version")
            or "state-laws-source-rights-receipt/v1"
        ),
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
    }
    return _verify_descriptor(root, descriptor, surface="source_rights_receipt")


def _vector_config(fragment: Mapping[str, Any]) -> dict[str, Any]:
    raw = fragment.get("vector")
    if not isinstance(raw, Mapping):
        raise VectorProductionGateError("vector fragment has no vector config")
    vector = dict(raw)
    model = vector.get("model") if isinstance(vector.get("model"), Mapping) else {}
    inference = _first_value(fragment.get("inference"), vector.get("inference"))
    inference = dict(inference) if isinstance(inference, Mapping) else {}
    model_id = _first_value(vector.get("model_id"), model.get("model_id"))
    revision = _first_value(
        vector.get("model_revision"),
        vector.get("revision"),
        model.get("model_revision"),
        model.get("revision"),
    )
    dimension = _first_value(vector.get("dimension"), model.get("dimension"))
    pooling = _first_value(vector.get("pooling"), model.get("pooling"))
    normalization = _first_value(
        vector.get("normalization"), model.get("normalization")
    )
    production_ready = _first_value(
        fragment.get("production_ready"), vector.get("production_ready")
    )
    real_inference = _first_value(
        inference.get("real_inference"),
        vector.get("real_inference"),
        fragment.get("real_inference"),
    )
    embedder_kind = _first_value(
        inference.get("embedder_kind"), vector.get("embedder_kind")
    )
    assignment = vector.get("assignment")
    layout = vector.get("layout")
    centroid_count = _first_value(
        vector.get("centroid_count"), vector.get("cluster_count")
    )
    total_rows = _first_value(
        vector.get("total_rows"),
        vector.get("row_count"),
        _nested(fragment, "counts", "vectors"),
        _nested(fragment, "counts", "vector_rows"),
    )
    failures: list[str] = []
    if model_id != DEFAULT_EMBEDDING_MODEL_ID:
        failures.append("model_id")
    if revision != DEFAULT_EMBEDDING_MODEL_REVISION:
        failures.append("model_revision")
    if dimension != DEFAULT_EMBEDDING_DIMENSION:
        failures.append("dimension")
    if pooling != "mean":
        failures.append("pooling")
    if normalization != "l2":
        failures.append("normalization")
    if production_ready is not True:
        failures.append("production_ready")
    if real_inference is not True:
        failures.append("real_inference")
    if embedder_kind != "sentence_transformers":
        failures.append("embedder_kind")
    if vector.get("projection_embeddings") is not False:
        failures.append("projection_embeddings")
    if assignment != VECTOR_ASSIGNMENT:
        failures.append("assignment")
    if layout != "semantic_centroid_groups":
        failures.append("layout")
    if centroid_count is None or int(centroid_count) <= 0:
        failures.append("centroid_count")
    if total_rows is None or int(total_rows) <= 0:
        failures.append("total_rows")
    if failures:
        raise VectorProductionGateError(
            "vector production contract failed: " + ", ".join(failures)
        )
    vector.update(
        {
            "assignment": assignment,
            "centroid_count": int(centroid_count),
            "dimension": int(dimension),
            "embedder_kind": str(embedder_kind),
            "layout": layout,
            "model_id": str(model_id),
            "model_revision": str(revision),
            "normalization": str(normalization),
            "pooling": str(pooling),
            "production_ready": True,
            "real_inference": True,
            "total_rows": int(total_rows),
        }
    )
    return vector


def _chunk_config(fragment: Mapping[str, Any]) -> dict[str, Any]:
    """Require the persisted canonical chunk/token-validation contract."""

    config = _plain_mapping(
        fragment.get("default_config") or {}, name="chunks.default_config"
    )
    corpus = _plain_mapping(fragment.get("corpus") or {}, name="chunks.corpus")
    validation = _plain_mapping(
        corpus.get("model_token_validation") or {},
        name="chunks.corpus.model_token_validation",
    )
    failures: list[str] = []
    if corpus.get("rechunk_downstream") is not False:
        failures.append("rechunk_downstream")
    if corpus.get("streaming") is not True:
        failures.append("streaming")
    if validation.get("passed") is not True:
        failures.append("model_token_validation.passed")
    if validation.get("pinned_identity_match") is not True:
        failures.append("model_token_validation.pinned_identity_match")
    if validation.get("counter_id") != PINNED_TOKEN_COUNTER_ID:
        failures.append("model_token_validation.counter_id")
    if config.get("model_token_counter_id") != PINNED_TOKEN_COUNTER_ID:
        failures.append("default_config.model_token_counter_id")
    if config.get("pinned_model_token_counter_id") != PINNED_TOKEN_COUNTER_ID:
        failures.append("default_config.pinned_model_token_counter_id")
    if not str(config.get("config_digest") or "").strip():
        failures.append("default_config.config_digest")
    if not str(corpus.get("parent_corpus_digest") or "").strip():
        failures.append("corpus.parent_corpus_digest")
    if failures:
        raise StateLawsLocalReleaseError(
            "canonical chunk production contract failed: " + ", ".join(failures)
        )
    return config


def _assert_descriptor_count_parity(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    counts: Mapping[str, int],
    vector: Mapping[str, Any],
) -> None:
    observed: dict[str, int] = {}
    for descriptor in artifacts:
        family = str(descriptor.get("family") or "").strip().lower()
        observed[family] = observed.get(family, 0) + int(
            descriptor.get("row_count") or 0
        )
    expected = {
        "bm25_documents": counts["bm25_documents"],
        "bm25_postings": counts["bm25_posting_rows"],
        "centroids": int(vector["centroid_count"]),
        "corpus": counts["corpus_documents"] + counts["canonical_chunks"],
        "graph_edges": counts["graph_edges"],
        "graph_nodes": counts["graph_nodes"],
        "locator_index": counts["vector_rows"],
        "receipt": EXPECTED_JURISDICTION_COUNT,
        "vectors": counts["vector_rows"],
    }
    drift = {
        family: {"expected": count, "observed": observed.get(family, 0)}
        for family, count in expected.items()
        if observed.get(family, 0) != count
    }
    if drift:
        raise StateLawsLocalReleaseError(
            f"artifact descriptor row counts do not reconcile: {drift}"
        )
    for family in ("graph_adjacency_in", "graph_adjacency_out"):
        if observed.get(family, 0) <= 0:
            raise StateLawsLocalReleaseError(
                f"artifact descriptor family {family!r} is empty"
            )


def _counts(
    corpus_fragment: Mapping[str, Any],
    chunk_fragment: Mapping[str, Any],
    bm25_fragment: Mapping[str, Any],
    vector: Mapping[str, Any],
    graph_fragment: Mapping[str, Any],
    *,
    key_count: int,
) -> dict[str, int]:
    corpus_counts = _plain_mapping(
        corpus_fragment.get("counts") or {}, name="corpus.counts"
    )
    chunk_counts = _plain_mapping(
        chunk_fragment.get("counts") or {}, name="chunks.counts"
    )
    bm25_counts = _plain_mapping(bm25_fragment.get("counts") or {}, name="bm25.counts")
    graph = _plain_mapping(graph_fragment.get("graph") or {}, name="graph")
    corpus_documents = _int_value(
        corpus_counts.get("corpus_documents"), name="corpus_documents"
    )
    canonical_chunks = _int_value(
        chunk_counts.get("canonical_chunks"),
        chunk_counts.get("searchable_chunks"),
        name="canonical_chunks",
    )
    chunk_parent_documents = _int_value(
        chunk_counts.get("parent_documents"), name="chunk_parent_documents"
    )
    bm25_documents = _int_value(
        bm25_counts.get("bm25_documents"),
        _nested(bm25_fragment, "bm25", "document_count"),
        name="bm25_documents",
    )
    bm25_terms = _int_value(
        bm25_counts.get("bm25_terms"),
        _nested(bm25_fragment, "bm25", "term_count"),
        name="bm25_terms",
    )
    vector_rows = _int_value(vector.get("total_rows"), name="vector_rows")
    graph_nodes = _int_value(graph.get("node_count"), name="graph_nodes")
    graph_edges = _int_value(graph.get("edge_count"), name="graph_edges")
    if corpus_documents != key_count:
        raise ReleaseKeyParityError(
            "corpus parent-statute count does not reconcile with parent keys: "
            f"{corpus_documents}/{key_count}"
        )
    if chunk_parent_documents != key_count:
        raise ReleaseKeyParityError(
            "canonical chunks do not conserve the complete parent corpus: "
            f"{chunk_parent_documents}/{key_count}"
        )
    if canonical_chunks != bm25_documents or canonical_chunks != vector_rows:
        raise ReleaseKeyParityError(
            "canonical chunk/BM25/vector searchable-chunk counts do not reconcile: "
            f"{canonical_chunks}/{bm25_documents}/{vector_rows}"
        )
    if canonical_chunks < key_count:
        raise ReleaseKeyParityError(
            "searchable-chunk count is smaller than the complete parent-key set: "
            f"{canonical_chunks}/{key_count}"
        )
    if bm25_terms <= 0 or graph_nodes <= 0 or graph_edges <= 0:
        raise StateLawsLocalReleaseError("BM25 and graph counts must be positive")
    return {
        **{str(key): int(value) for key, value in corpus_counts.items()},
        **{str(key): int(value) for key, value in bm25_counts.items()},
        "canonical_chunks": canonical_chunks,
        "graph_edges": graph_edges,
        "graph_nodes": graph_nodes,
        "parent_documents": corpus_documents,
        "searchable_chunks": canonical_chunks,
        "vector_rows": vector_rows,
    }


def _assert_bm25_graph_parity(
    bm25_fragment: Mapping[str, Any],
    graph_fragment: Mapping[str, Any],
    *,
    counts: Mapping[str, int],
) -> dict[str, Any]:
    bm25 = _plain_mapping(bm25_fragment.get("bm25") or {}, name="bm25")
    graph = _plain_mapping(graph_fragment.get("graph") or {}, name="graph")
    proof = _plain_mapping(
        graph.get("vocabulary_parity") or {}, name="graph.vocabulary_parity"
    )
    checks = _plain_mapping(graph.get("checks") or {}, name="graph.checks")
    required_checks = {
        "bm25_physical_vocabulary_proof",
        "bm25_neighbors_non_authoritative",
        "direct_parquet_columns",
        "edge_identities_exact",
        "endpoint_integrity",
        "node_identities_exact",
        "optional_bm25_neighbors_production_ready",
        "term_document_edges_not_materialized",
        "two_way_adjacency_required",
    }
    failed = sorted(name for name in required_checks if checks.get(name) is not True)
    if failed:
        raise StateLawsLocalReleaseError(
            f"graph physical guarantees are absent: {failed}"
        )
    if (
        proof.get("bm25_vocabulary_matches_overlay_exactly") is not True
        or proof.get("bm25_vocabulary_matches_physical_postings_exactly") is not True
        or proof.get("bm25_document_frequencies_match_physical_postings_exactly")
        is not True
        or proof.get("postings_parity_asserted") is not True
        or proof.get("full_term_document_expansion_performed") is not False
        or int(proof.get("durable_term_document_edge_count", -1)) != 0
        or proof.get("production_ready") is not True
        or proof.get("evidence_source") != "streaming_physical_postings"
    ):
        raise StateLawsLocalReleaseError(
            "lexical graph lacks exact virtual BM25 vocabulary/posting parity"
        )
    if int(proof.get("term_count", -1)) != counts["bm25_terms"]:
        raise StateLawsLocalReleaseError("BM25/lexical graph term counts diverge")
    if int(proof.get("document_count", -1)) != counts["bm25_documents"]:
        raise StateLawsLocalReleaseError("BM25/lexical graph document counts diverge")
    if proof.get("bm25_config_digest") != bm25.get("config_digest"):
        raise StateLawsLocalReleaseError("BM25/lexical graph config digests diverge")
    if proof.get("index_root_cid") != bm25.get("index_root_cid"):
        raise StateLawsLocalReleaseError("BM25/lexical graph root CIDs diverge")
    return proof


def _merge_artifacts(
    root: Path,
    sources: Sequence[tuple[Any, Mapping[str, Any]]],
    index_descriptors: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    by_path: dict[str, dict[str, Any]] = {}
    for source, fragment in sources:
        for descriptor in _collect_source_descriptors(source, fragment):
            path = str(descriptor.get("relative_path") or descriptor.get("path") or "")
            existing = by_path.get(path)
            by_path[path] = (
                _merge_equivalent_descriptor(existing, descriptor, label=path)
                if existing is not None
                else descriptor
            )
    for name, descriptor in index_descriptors.items():
        path = str(descriptor.get("relative_path") or descriptor.get("path") or "")
        existing = by_path.get(path)
        by_path[path] = (
            _merge_equivalent_descriptor(existing, descriptor, label=name)
            if existing is not None
            else descriptor
        )
    verified = tuple(
        _verify_descriptor(root, descriptor, surface=f"artifacts[{position}]")
        for position, descriptor in enumerate(
            descriptor for _, descriptor in sorted(by_path.items())
        )
    )
    families = {str(item.get("family") or "").strip().lower() for item in verified}
    missing = sorted(REQUIRED_DATA_FAMILIES - families)
    if missing:
        raise StateLawsLocalReleaseError(
            f"release descriptors lack required data families: {missing}"
        )
    _assert_lineage_not_duplicated(root, verified)
    return verified


def _descriptor_shard_order(descriptor: Mapping[str, Any]) -> tuple[int, str]:
    shard_id = descriptor.get("shard_id")
    if isinstance(shard_id, bool):
        raise DescriptorIntegrityError("artifact shard_id must be an integer")
    try:
        number = int(shard_id)
    except (TypeError, ValueError) as exc:
        raise DescriptorIntegrityError(
            "artifact shard_id is absent or malformed"
        ) from exc
    if number < 0:
        raise DescriptorIntegrityError("artifact shard_id must be non-negative")
    return number, str(descriptor["relative_path"])


def _verify_compact_routes(
    root: Path,
    *,
    index_descriptor: Mapping[str, Any],
    data_descriptors: Sequence[Mapping[str, Any]],
    kind: str,
    expected_total_rows: int,
    require_document_ranges: bool,
) -> None:
    """Reopen a compact index and bind every row to exactly one data shard."""

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional release extra
        raise StateLawsLocalReleaseError(
            "pyarrow is required to verify completed release routing indexes"
        ) from exc
    ordered = tuple(sorted(data_descriptors, key=_descriptor_shard_order))
    route_path = confine_path(root, str(index_descriptor["relative_path"]))
    try:
        rows = pq.read_table(route_path).to_pylist()
    except Exception as exc:
        raise DescriptorIntegrityError(
            f"{kind} routing index could not be reopened"
        ) from exc
    if len(rows) != len(ordered):
        raise DescriptorIntegrityError(
            f"{kind} routing rows do not cover its physical shards"
        )

    expected_document_index = 0
    previous_last: str | None = None
    for position, (route, descriptor) in enumerate(zip(rows, ordered)):
        relative = normalize_relative_artifact_path(
            route.get("relative_path"),
            name=f"{kind}.routes[{position}].relative_path",
        )
        descriptor_relative = str(descriptor["relative_path"])
        if (
            relative != descriptor_relative
            or route.get("kind") != kind
            or route.get("sha256") != descriptor.get("sha256")
            or int(route.get("size_bytes", -1)) != int(descriptor["size_bytes"])
            or int(route.get("row_count", -1)) != int(descriptor["row_count"])
            or int(route.get("shard_id", -1)) != int(descriptor["shard_id"])
            or route.get("first_key") != descriptor.get("first_key")
            or route.get("last_key") != descriptor.get("last_key")
        ):
            raise DescriptorIntegrityError(
                f"{kind} routing row {position} does not bind its data descriptor"
            )
        first_key = str(route.get("first_key") or "")
        last_key = str(route.get("last_key") or "")
        if not first_key or not last_key or first_key > last_key:
            raise DescriptorIntegrityError(
                f"{kind} routing row {position} has an invalid key range"
            )
        if previous_last is not None and previous_last >= first_key:
            raise DescriptorIntegrityError(
                f"{kind} routing key ranges overlap or are unordered"
            )
        previous_last = last_key
        if require_document_ranges:
            start = int(route.get("start_document_index", -1))
            end = int(route.get("end_document_index", -1))
            if (
                start != expected_document_index
                or end < start
                or end - start + 1 != int(route["row_count"])
            ):
                raise DescriptorIntegrityError(
                    f"{kind} routing document ranges are not dense and exact"
                )
            expected_document_index = end + 1
    observed_total = sum(int(item["row_count"]) for item in ordered)
    if observed_total != expected_total_rows or (
        require_document_ranges and expected_document_index != expected_total_rows
    ):
        raise DescriptorIntegrityError(
            f"{kind} routing row counts do not reconcile with the manifest"
        )


def _verify_completed_bm25_physical_closure(
    root: Path,
    *,
    payload: Mapping[str, Any],
    descriptors: Mapping[str, Mapping[str, Any]],
) -> None:
    """Recompute physical BM25 vocabulary/DF and compact-routing closure."""

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional release extra
        raise StateLawsLocalReleaseError(
            "pyarrow is required to verify completed release BM25 evidence"
        ) from exc
    bm25 = _plain_mapping(payload.get("bm25") or {}, name="completed.bm25")
    graph = _plain_mapping(payload.get("graph") or {}, name="completed.graph")
    proof = _plain_mapping(
        graph.get("vocabulary_parity") or {},
        name="completed.graph.vocabulary_parity",
    )
    counts = _plain_mapping(payload.get("counts") or {}, name="completed.counts")
    indexes = _plain_mapping(payload.get("indexes") or {}, name="completed.indexes")
    document_count = _int_value(
        counts.get("bm25_documents"), name="counts.bm25_documents"
    )
    expected_term_count = _int_value(counts.get("bm25_terms"), name="counts.bm25_terms")
    expected_posting_count = _int_value(
        counts.get("bm25_postings"), name="counts.bm25_postings"
    )
    expected_posting_rows = _int_value(
        counts.get("bm25_posting_rows"), name="counts.bm25_posting_rows"
    )
    expected_keyword_shards = _int_value(
        counts.get("bm25_keyword_shards"), name="counts.bm25_keyword_shards"
    )
    posting_descriptors = tuple(
        sorted(
            (
                descriptor
                for descriptor in descriptors.values()
                if str(descriptor.get("family") or "").strip().casefold()
                == "bm25_postings"
            ),
            key=_descriptor_shard_order,
        )
    )
    document_descriptors = tuple(
        sorted(
            (
                descriptor
                for descriptor in descriptors.values()
                if str(descriptor.get("family") or "").strip().casefold()
                == "bm25_documents"
            ),
            key=_descriptor_shard_order,
        )
    )
    if (
        not posting_descriptors
        or not document_descriptors
        or len(posting_descriptors) != expected_keyword_shards
    ):
        raise DescriptorIntegrityError("completed release lacks physical BM25 shards")

    required_columns = {
        "chunk_cids",
        "document_frequency",
        "document_indices",
        "entry_cids",
        "pointer_count",
        "posting_chunk_count",
        "posting_chunk_index",
        "term",
    }
    physical_posting_rows = 0
    physical_pointer_count = 0
    route_counts: dict[str, tuple[int, int]] = {}

    def term_statistics() -> Iterable[tuple[str, int]]:
        nonlocal physical_posting_rows, physical_pointer_count
        previous_term: str | None = None
        for descriptor in posting_descriptors:
            path = confine_path(root, str(descriptor["relative_path"]))
            parquet = pq.ParquetFile(path)
            if not required_columns.issubset(parquet.schema_arrow.names):
                missing = sorted(required_columns - set(parquet.schema_arrow.names))
                raise DescriptorIntegrityError(
                    f"BM25 posting shard lacks required columns: {missing}"
                )
            shard_first: str | None = None
            shard_last: str | None = None
            shard_term_count = 0
            shard_pointer_count = 0
            current_term: str | None = None
            current_df = 0
            current_chunk_count = 0
            next_chunk_index = 0
            current_pointer_count = 0
            previous_document_index = -1

            def finish_term() -> tuple[str, int] | None:
                nonlocal current_term
                if current_term is None:
                    return None
                if (
                    next_chunk_index != current_chunk_count  # noqa: B023
                    or current_pointer_count != current_df  # noqa: B023
                ):
                    raise DescriptorIntegrityError(
                        f"BM25 posting chunks do not reconcile for {current_term!r}"
                    )
                result = (current_term, current_df)  # noqa: B023
                current_term = None
                return result

            for batch in parquet.iter_batches(
                batch_size=MAX_ROWS_PER_PHYSICAL_SHARD,
                columns=sorted(required_columns),
            ):
                for row in batch.to_pylist():
                    physical_posting_rows += 1
                    term = str(row.get("term") or "").strip()
                    if not term:
                        raise DescriptorIntegrityError(
                            "BM25 posting row has an empty term"
                        )
                    if current_term is not None and term != current_term:
                        completed = finish_term()
                        assert completed is not None
                        yield completed
                    if current_term is None:
                        if previous_term is not None and previous_term >= term:
                            raise DescriptorIntegrityError(
                                "physical BM25 vocabulary is not strictly ordered"
                            )
                        current_term = term
                        previous_term = term
                        current_df = int(row.get("document_frequency", -1))
                        current_chunk_count = int(row.get("posting_chunk_count", -1))
                        next_chunk_index = 0
                        current_pointer_count = 0
                        previous_document_index = -1
                        shard_term_count += 1
                    if (
                        int(row.get("document_frequency", -1)) != current_df
                        or current_df < 1
                        or current_df > document_count
                        or int(row.get("posting_chunk_count", -1))
                        != current_chunk_count
                        or current_chunk_count < 1
                        or int(row.get("posting_chunk_index", -1)) != next_chunk_index
                    ):
                        raise DescriptorIntegrityError(
                            f"BM25 posting metadata is inconsistent for {term!r}"
                        )
                    pointers = list(row.get("document_indices") or ())
                    entry_cids = list(row.get("entry_cids") or ())
                    chunk_cids = list(row.get("chunk_cids") or ())
                    pointer_count = int(row.get("pointer_count", -1))
                    if (
                        pointer_count < 1
                        or pointer_count > MAX_POSTING_POINTERS_PER_ROW
                        or pointer_count != len(pointers)
                        or pointer_count != len(entry_cids)
                        or pointer_count != len(chunk_cids)
                        or entry_cids != chunk_cids
                        or any(not str(item).strip() for item in entry_cids)
                    ):
                        raise DescriptorIntegrityError(
                            f"BM25 posting pointers are inconsistent for {term!r}"
                        )
                    for document_index in pointers:
                        index = int(document_index)
                        if (
                            index <= previous_document_index
                            or index < 0
                            or index >= document_count
                        ):
                            raise DescriptorIntegrityError(
                                f"BM25 posting pointers are unordered/out of range for {term!r}"
                            )
                        previous_document_index = index
                    next_chunk_index += 1
                    current_pointer_count += pointer_count
                    physical_pointer_count += pointer_count
                    shard_pointer_count += pointer_count
                    shard_first = shard_first or term
                    shard_last = term
            completed = finish_term()
            if completed is not None:
                yield completed
            if shard_first is None or shard_last is None:
                raise DescriptorIntegrityError("BM25 posting shard is empty")
            metadata = descriptor.get("metadata")
            if (
                descriptor.get("first_key") != shard_first
                or descriptor.get("last_key") != shard_last
                or not isinstance(metadata, Mapping)
                or int(metadata.get("pointer_count", -1)) != shard_pointer_count
                or int(metadata.get("term_count", -1)) != shard_term_count
            ):
                raise DescriptorIntegrityError(
                    "BM25 posting descriptor key/count metadata drifted"
                )
            route_counts[str(descriptor["relative_path"])] = (
                shard_pointer_count,
                shard_term_count,
            )

    try:
        recomputed = digest_sorted_bm25_term_statistics(term_statistics())
    except (OSError, TypeError, ValueError) as exc:
        raise DescriptorIntegrityError(
            f"completed BM25 vocabulary evidence is invalid: {exc}"
        ) from exc
    if (
        physical_posting_rows != expected_posting_rows
        or physical_pointer_count != expected_posting_count
        or recomputed.term_count != expected_term_count
        or recomputed.term_document_pair_count != expected_posting_count
        or recomputed.vocabulary_sha256 != bm25.get("vocabulary_sha256")
        or recomputed.document_frequency_sha256 != bm25.get("document_frequency_sha256")
        or proof.get("vocabulary_sha256") != recomputed.vocabulary_sha256
        or proof.get("document_frequency_sha256")
        != recomputed.document_frequency_sha256
        or int(proof.get("term_count", -1)) != recomputed.term_count
        or int(proof.get("document_count", -1)) != document_count
        or int(proof.get("term_document_pair_count", -1))
        != recomputed.term_document_pair_count
    ):
        raise DescriptorIntegrityError(
            "completed BM25 vocabulary/posting evidence does not recompute exactly"
        )

    keyword_index = _descriptor_mapping(
        indexes.get("bm25_keyword_shards"), name="indexes.bm25_keyword_shards"
    )
    _verify_compact_routes(
        root,
        index_descriptor=keyword_index,
        data_descriptors=posting_descriptors,
        kind="bm25_postings",
        expected_total_rows=expected_posting_rows,
        require_document_ranges=False,
    )
    keyword_rows = pq.read_table(
        confine_path(root, str(keyword_index["relative_path"]))
    ).to_pylist()
    for position, row in enumerate(keyword_rows):
        expected = route_counts.get(str(row.get("relative_path") or ""))
        if expected is None or (
            int(row.get("posting_count", -1)) != expected[0]
            or int(row.get("term_count", -1)) != expected[1]
        ):
            raise DescriptorIntegrityError(
                f"BM25 keyword route {position} has stale posting counts"
            )

    _verify_compact_routes(
        root,
        index_descriptor=_descriptor_mapping(
            indexes.get("bm25_document_chunks"),
            name="indexes.bm25_document_chunks",
        ),
        data_descriptors=document_descriptors,
        kind="bm25_documents",
        expected_total_rows=document_count,
        require_document_ranges=True,
    )


_BM25_DOCUMENT_COLUMNS: Final = frozenset(
    {
        "census_region",
        "chunk_cid",
        "chunk_id",
        "document_index",
        "document_length",
        "entry_cid",
        "jurisdiction_code",
        "legal_id",
        "parent_entry_cid",
        "record_type",
        "route_key",
        "schema_version",
        "section",
        "title_code",
        *(f"{field_name}_length" for field_name in FIELD_ORDER),
    }
)

_BM25_POSTING_COLUMNS: Final = frozenset(
    {
        "body_frequencies",
        "chunk_cids",
        "corpus_frequency",
        "document_frequency",
        "document_indices",
        "document_lengths",
        "entry_cids",
        "idf",
        "pointer_count",
        "posting_chunk_count",
        "posting_chunk_index",
        "schema_version",
        "term",
        "title_frequencies",
        "total_frequencies",
        "weighted_corpus_frequency",
        "weighted_frequencies",
        *(f"legal_{field_name}_frequencies" for field_name in FIELD_ORDER),
        *(f"legal_{field_name}_lengths" for field_name in FIELD_ORDER),
    }
)


def _semantic_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DescriptorIntegrityError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise DescriptorIntegrityError(f"{name} must be a finite number")
    return result


def _assert_semantic_float(
    value: Any,
    expected: float,
    *,
    name: str,
) -> None:
    observed = _semantic_float(value, name=name)
    if not math.isclose(
        observed,
        float(expected),
        rel_tol=0.0,
        abs_tol=SCORE_ABS_TOLERANCE,
    ):
        raise DescriptorIntegrityError(
            f"{name} differs from canonical-chunk recomputation: "
            f"{observed!r}/{expected!r}"
        )


def _data_descriptors(
    descriptors: Mapping[str, Mapping[str, Any]],
    *,
    prefix: str,
    family: str,
    schema_id: str,
    label: str,
) -> tuple[dict[str, Any], ...]:
    selected = tuple(
        sorted(
            (
                dict(descriptor)
                for path, descriptor in descriptors.items()
                if path.startswith(f"{prefix}/")
            ),
            key=_descriptor_shard_order,
        )
    )
    if not selected:
        raise DescriptorIntegrityError(f"completed release lacks {label} shards")
    for expected_shard_id, descriptor in enumerate(selected):
        if (
            descriptor.get("family") != family
            or descriptor.get("schema_id") != schema_id
            or int(descriptor.get("shard_id", -1)) != expected_shard_id
            or int(descriptor.get("row_count", 0)) < 1
        ):
            raise DescriptorIntegrityError(
                f"{label} descriptor {expected_shard_id} violates its exact schema"
            )
    return selected


def _assert_parquet_schema(
    parquet: Any,
    *,
    columns: frozenset[str],
    schema_version: str,
    tokenizer_id: str | None,
    label: str,
) -> None:
    observed_columns = frozenset(parquet.schema_arrow.names)
    if observed_columns != columns:
        missing = sorted(columns - observed_columns)
        extra = sorted(observed_columns - columns)
        raise DescriptorIntegrityError(
            f"{label} direct columns drifted: missing={missing}, extra={extra}"
        )
    metadata = parquet.schema_arrow.metadata or {}
    observed_schema = metadata.get(b"schema_version", b"").decode(
        "utf-8", errors="strict"
    )
    if observed_schema != schema_version:
        raise DescriptorIntegrityError(
            f"{label} Parquet schema identity drifted"
        )
    if tokenizer_id is not None:
        observed_tokenizer = metadata.get(b"tokenizer", b"").decode(
            "utf-8", errors="strict"
        )
        if observed_tokenizer != tokenizer_id:
            raise DescriptorIntegrityError(
                f"{label} tokenizer metadata drifted"
            )


def _canonical_chunk_descriptors(
    root: Path,
    *,
    descriptors: Mapping[str, Mapping[str, Any]],
    indexes: Mapping[str, Any],
    pq: Any,
) -> tuple[dict[str, Any], ...]:
    """Bind the canonical-chunk compact index to its exact data shards."""

    selected = _data_descriptors(
        descriptors,
        prefix=CHUNK_DATA_DIR,
        family="corpus",
        schema_id=CHUNK_ROW_SCHEMA_VERSION,
        label="canonical chunk",
    )
    by_path = {str(item["relative_path"]): item for item in selected}
    index_descriptor = _descriptor_mapping(
        indexes.get("corpus_chunks"), name="indexes.corpus_chunks"
    )
    index_path = confine_path(root, str(index_descriptor["relative_path"]))
    try:
        rows = pq.read_table(index_path).to_pylist()
    except Exception as exc:
        raise DescriptorIntegrityError(
            "canonical chunk routing index could not be reopened"
        ) from exc
    if len(rows) != len(selected):
        raise DescriptorIntegrityError(
            "canonical chunk routes do not cover every canonical shard"
        )

    ordered: list[dict[str, Any]] = []
    expected_document_index = 0
    previous_key: tuple[str, str] | None = None
    seen_paths: set[str] = set()
    for position, route in enumerate(rows):
        relative = normalize_relative_artifact_path(
            route.get("relative_path"),
            name=f"canonical_chunk.routes[{position}].relative_path",
        )
        descriptor = by_path.get(relative)
        if descriptor is None or relative in seen_paths:
            raise DescriptorIntegrityError(
                "canonical chunk route targets an absent or duplicate shard"
            )
        seen_paths.add(relative)
        code = str(route.get("jurisdiction_code") or "").strip().upper()
        metadata = descriptor.get("metadata")
        start = int(route.get("start_document_index", -1))
        end = int(route.get("end_document_index", -1))
        first = str(route.get("first_key") or "")
        last = str(route.get("last_key") or "")
        key = (code, first)
        if (
            route.get("kind") != CHUNK_INDEX_KIND
            or int(route.get("shard_id", -1)) != int(descriptor["shard_id"])
            or route.get("sha256") != descriptor.get("sha256")
            or int(route.get("size_bytes", -1))
            != int(descriptor["size_bytes"])
            or int(route.get("row_count", -1)) != int(descriptor["row_count"])
            or first != descriptor.get("first_key")
            or last != descriptor.get("last_key")
            or not code
            or first > last
            or start != expected_document_index
            or end < start
            or end - start + 1 != int(descriptor["row_count"])
            or not isinstance(metadata, Mapping)
            or metadata.get("stage") != "canonical_chunks"
            or metadata.get("jurisdiction_code") != code
            or int(metadata.get("start_document_index", -1)) != start
            or int(metadata.get("end_document_index", -1)) != end
            or previous_key is not None
            and previous_key >= key
        ):
            raise DescriptorIntegrityError(
                f"canonical chunk route {position} is not exact"
            )
        previous_key = (code, last)
        expected_document_index = end + 1
        ordered.append(descriptor)
    if seen_paths != set(by_path):
        raise DescriptorIntegrityError(
            "canonical chunk compact index leaves unreferenced data shards"
        )
    return tuple(ordered)


def _iter_canonical_chunk_rows(
    root: Path,
    *,
    descriptors: Sequence[Mapping[str, Any]],
    pq: Any,
) -> Iterable[dict[str, Any]]:
    expected_columns = frozenset(_chunk_schema().names)
    expected_document_index = 0
    previous_key: tuple[str, str] | None = None
    for descriptor in descriptors:
        path = confine_path(root, str(descriptor["relative_path"]))
        parquet = pq.ParquetFile(path)
        _assert_parquet_schema(
            parquet,
            columns=expected_columns,
            schema_version=CHUNK_ROW_SCHEMA_VERSION,
            tokenizer_id=None,
            label="canonical chunk",
        )
        if int(parquet.metadata.num_rows) != int(descriptor["row_count"]):
            raise DescriptorIntegrityError(
                "canonical chunk Parquet row count drifted"
            )
        shard_observed = 0
        shard_first: str | None = None
        shard_last: str | None = None
        shard_code: str | None = None
        for batch in parquet.iter_batches(
            batch_size=BM25_SEMANTIC_DOCUMENT_BATCH_ROWS,
        ):
            for value in batch.to_pylist():
                row = dict(value)
                cid = str(row.get("chunk_cid") or "")
                code = str(row.get("jurisdiction_code") or "").strip().upper()
                key = (code, cid)
                if (
                    row.get("schema_version") != CHUNK_ROW_SCHEMA_VERSION
                    or row.get("entry_cid") != cid
                    or not cid
                    or not code
                    or int(row.get("document_index", -1))
                    != expected_document_index
                    or previous_key is not None
                    and previous_key >= key
                    or row.get("body") != row.get("exclusive_text")
                    or content_sha256(str(row.get("body") or ""))
                    != row.get("body_sha256")
                    or content_sha256(str(row.get("text") or ""))
                    != row.get("embedding_text_sha256")
                ):
                    raise DescriptorIntegrityError(
                        f"canonical chunk row {expected_document_index} is invalid"
                    )
                if shard_code is not None and code != shard_code:
                    raise DescriptorIntegrityError(
                        "canonical chunk shard crosses jurisdiction boundaries"
                    )
                shard_code = code
                shard_first = shard_first or cid
                shard_last = cid
                previous_key = key
                expected_document_index += 1
                shard_observed += 1
                yield row
        metadata = descriptor.get("metadata")
        if (
            shard_observed != int(descriptor["row_count"])
            or shard_first != descriptor.get("first_key")
            or shard_last != descriptor.get("last_key")
            or not isinstance(metadata, Mapping)
            or metadata.get("jurisdiction_code") != shard_code
        ):
            raise DescriptorIntegrityError(
                "canonical chunk descriptor does not match its rows"
            )


def _iter_bm25_document_rows(
    root: Path,
    *,
    descriptors: Sequence[Mapping[str, Any]],
    pq: Any,
    tokenizer_id: str,
) -> Iterable[dict[str, Any]]:
    expected_document_index = 0
    for descriptor in descriptors:
        path = confine_path(root, str(descriptor["relative_path"]))
        parquet = pq.ParquetFile(path)
        _assert_parquet_schema(
            parquet,
            columns=_BM25_DOCUMENT_COLUMNS,
            schema_version=DOCUMENT_SCHEMA_VERSION,
            tokenizer_id=tokenizer_id,
            label="BM25 document",
        )
        shard_observed = 0
        shard_first: str | None = None
        shard_last: str | None = None
        for batch in parquet.iter_batches(
            batch_size=DEFAULT_MAX_RECORDS_IN_MEMORY,
        ):
            for value in batch.to_pylist():
                row = dict(value)
                route_key = str(row.get("route_key") or "")
                if (
                    row.get("schema_version") != DOCUMENT_SCHEMA_VERSION
                    or int(row.get("document_index", -1))
                    != expected_document_index
                    or route_key != document_route_key(expected_document_index)
                ):
                    raise DescriptorIntegrityError(
                        f"BM25 document row {expected_document_index} is invalid"
                    )
                shard_first = shard_first or route_key
                shard_last = route_key
                shard_observed += 1
                expected_document_index += 1
                yield row
        if (
            shard_observed != int(descriptor["row_count"])
            or shard_first != descriptor.get("first_key")
            or shard_last != descriptor.get("last_key")
        ):
            raise DescriptorIntegrityError(
                "BM25 document descriptor does not match its rows"
            )


def _expected_bm25_document_row(document: Any) -> dict[str, Any]:
    result = {
        "census_region": document.census_region,
        "chunk_cid": document.chunk_cid,
        "chunk_id": document.chunk_id,
        "document_index": document.document_index,
        "document_length": document.total_length,
        "entry_cid": document.entry_cid,
        "jurisdiction_code": document.jurisdiction_code,
        "legal_id": document.legal_id,
        "parent_entry_cid": document.parent_entry_cid,
        "record_type": document.record_type,
        "route_key": document_route_key(document.document_index),
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "section": document.section,
        "title_code": document.title_code,
    }
    result.update(
        {
            f"{field_name}_length": document.field_length(field_name)
            for field_name in FIELD_ORDER
        }
    )
    return result


def _iter_expected_bm25_term_statistics(
    path: Path,
    *,
    document_count: int,
) -> Iterable[dict[str, Any]]:
    current_term: str | None = None
    document_frequency = 0
    corpus_frequency = 0
    weighted_corpus_frequency = 0.0
    previous_key: tuple[str, int] | None = None

    def finish() -> dict[str, Any]:
        assert current_term is not None
        return {
            "corpus_frequency": corpus_frequency,
            "document_frequency": document_frequency,
            "idf": robertson_sparck_jones_idf(
                document_frequency, document_count
            ),
            "term": current_term,
            "weighted_corpus_frequency": weighted_corpus_frequency,
        }

    for row in iter_jsonl(path):
        term = str(row.get("term") or "")
        document_index = int(row.get("document_index", -1))
        key = (term, document_index)
        if not term or document_index < 0 or (
            previous_key is not None and previous_key >= key
        ):
            raise DescriptorIntegrityError(
                "canonical BM25 posting projection is not strictly ordered"
            )
        if current_term is not None and term != current_term:
            yield finish()
            document_frequency = 0
            corpus_frequency = 0
            weighted_corpus_frequency = 0.0
        current_term = term
        document_frequency += 1
        corpus_frequency += int(row["total_frequency"])
        weighted_corpus_frequency += float(row["weighted_frequency"])
        previous_key = key
    if current_term is not None:
        yield finish()


def _assert_bm25_manifest_scoring_contract(
    bm25: Mapping[str, Any],
    *,
    corpus_chunks_index: Mapping[str, Any],
) -> Any:
    declared_config = bm25.get("config")
    if not isinstance(declared_config, Mapping):
        raise DescriptorIntegrityError(
            "completed BM25 manifest lacks its exact build config"
        )
    declared_config = dict(declared_config)
    weights = declared_config.get("field_weights")
    if not isinstance(weights, Mapping) or set(weights) != set(FIELD_ORDER):
        raise DescriptorIntegrityError(
            "completed BM25 field weights do not exactly cover scoring fields"
        )
    try:
        config = StateLawsBm25Config(
            k1=_semantic_float(declared_config.get("k1"), name="bm25.config.k1"),
            b=_semantic_float(declared_config.get("b"), name="bm25.config.b"),
            field_weights=FieldWeightConfig(
                **{
                    field_name: _semantic_float(
                        weights[field_name],
                        name=f"bm25.config.field_weights[{field_name}]",
                    )
                    for field_name in FIELD_ORDER
                }
            ),
            tokenizer_id=str(declared_config.get("tokenizer_id") or ""),
            max_documents=declared_config.get("max_documents"),
            max_text_characters=declared_config.get("max_text_characters"),
            max_query_terms=declared_config.get("max_query_terms"),
            max_rows_per_shard=declared_config.get("max_rows_per_shard"),
            postings_per_cell=declared_config.get("postings_per_cell"),
            max_route_page_rows=declared_config.get("max_route_page_rows"),
            max_records_in_memory=declared_config.get("max_records_in_memory"),
            schema_version=str(declared_config.get("schema_version") or ""),
        )
        config_digest = normalize_sha256(
            bm25.get("config_digest"), name="bm25.config_digest"
        )
    except (TypeError, ValueError) as exc:
        raise DescriptorIntegrityError(
            f"completed BM25 scoring contract is malformed: {exc}"
        ) from exc
    expected_projection = {
        "body_frequencies": list(QUERY_BODY_FIELDS),
        "exact_field_lengths": True,
        "exact_field_prefix": "legal_",
        "title_frequencies": list(QUERY_TITLE_FIELDS),
    }
    expected_analyzer = {
        "required": True,
        "tokenizer_id": config.tokenizer_id,
    }
    expected_physical_proof = {
        "document_frequency_column": "document_frequency",
        "document_frequency_sha256": bm25.get("document_frequency_sha256"),
        "keyword_index_path": "indexes/bm25_keyword_shards.parquet",
        "posting_glob": f"{POSTING_DATA_DIR}/*.parquet",
        "posting_rows_are_lexicographic": True,
        "term_column": "term",
        "vocabulary_sha256": bm25.get("vocabulary_sha256"),
    }
    if (
        declared_config != config.to_dict()
        or bm25.get("config_digest") != config_digest
        or config_digest != config.digest
        or bm25.get("field_weights") != config.field_weights.to_dict()
        or bm25.get("fields") != list(FIELD_ORDER)
        or bm25.get("tokenizer") != config.tokenizer_id
        or bm25.get("tokenizer_contract") != shared_tokenizer_identity(config)
        or bm25.get("query_analyzer") != expected_analyzer
        or bm25.get("query_field_projection") != expected_projection
        or bm25.get("physical_schema_version") != BM25_PHYSICAL_SCHEMA_VERSION
        or bm25.get("production_builder") != "shared_streaming_multifield"
        or bm25.get("canonical_chunk_artifact_digest")
        != corpus_chunks_index.get("sha256")
        or bm25.get("canonical_chunk_artifact_digest_contract")
        != CANONICAL_CHUNK_ARTIFACT_DIGEST_CONTRACT
        or bm25.get("physical_vocabulary_proof") != expected_physical_proof
    ):
        raise DescriptorIntegrityError(
            "completed BM25 scoring/tokenizer/chunk-binding contract drifted"
        )
    _assert_semantic_float(bm25.get("k1"), config.k1, name="bm25.k1")
    _assert_semantic_float(bm25.get("b"), config.b, name="bm25.b")
    _assert_semantic_float(
        bm25.get("title_weight"),
        config.field_weights.title,
        name="bm25.title_weight",
    )
    _assert_semantic_float(
        bm25.get("body_weight"),
        config.field_weights.body,
        name="bm25.body_weight",
    )
    return config


def _verify_completed_bm25_semantics(
    root: Path,
    *,
    payload: Mapping[str, Any],
    descriptors: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute every scoring value from canonical chunk text, fail closed.

    Descriptor hashes and internal posting consistency are insufficient: an
    attacker can forge documents, postings, counts, and their descriptors as
    one self-consistent surface.  This verifier treats the canonical chunk
    Parquet as the sole source of truth, reruns the pinned legal projection
    and tokenizer, externally sorts the resulting term/document pointers, and
    compares every persisted scoring column in bounded passes.
    """

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional release extra
        raise StateLawsLocalReleaseError(
            "pyarrow is required to verify completed release BM25 semantics"
        ) from exc

    bm25 = _plain_mapping(payload.get("bm25") or {}, name="completed.bm25")
    graph = _plain_mapping(payload.get("graph") or {}, name="completed.graph")
    graph_proof = _plain_mapping(
        graph.get("vocabulary_parity") or {},
        name="completed.graph.vocabulary_parity",
    )
    counts = _plain_mapping(payload.get("counts") or {}, name="completed.counts")
    indexes = _plain_mapping(payload.get("indexes") or {}, name="completed.indexes")
    corpus_chunks_index = _descriptor_mapping(
        indexes.get("corpus_chunks"), name="indexes.corpus_chunks"
    )
    config = _assert_bm25_manifest_scoring_contract(
        bm25,
        corpus_chunks_index=corpus_chunks_index,
    )

    canonical_descriptors = _canonical_chunk_descriptors(
        root,
        descriptors=descriptors,
        indexes=indexes,
        pq=pq,
    )
    document_descriptors = _data_descriptors(
        descriptors,
        prefix=DOCUMENT_DATA_DIR,
        family="bm25_documents",
        schema_id=DOCUMENT_SCHEMA_VERSION,
        label="BM25 document",
    )
    posting_descriptors = _data_descriptors(
        descriptors,
        prefix=POSTING_DATA_DIR,
        family="bm25_postings",
        schema_id=POSTING_SCHEMA_VERSION,
        label="BM25 posting",
    )
    if any(
        int(descriptor["row_count"]) > config.max_rows_per_shard
        for descriptor in (*document_descriptors, *posting_descriptors)
    ):
        raise DescriptorIntegrityError(
            "completed BM25 shard exceeds its declared physical row bound"
        )

    document_count = 0
    token_instance_count = 0
    field_length_sums = {field_name: 0 for field_name in FIELD_ORDER}
    document_semantics = sha256()
    document_semantics.update(b"[")
    first_document = True

    with TemporaryDirectory(prefix="state-laws-bm25-semantic-verify-") as temporary:
        work = Path(temporary)
        expected_pointer_path = work / "expected-pointers.jsonl"
        observed_document_rows = iter(
            _iter_bm25_document_rows(
                root,
                descriptors=document_descriptors,
                pq=pq,
                tokenizer_id=config.tokenizer_id,
            )
        )

        def expected_pointers() -> Iterable[dict[str, Any]]:
            nonlocal document_count
            nonlocal token_instance_count
            nonlocal first_document
            for canonical_row in _iter_canonical_chunk_rows(
                root,
                descriptors=canonical_descriptors,
                pq=pq,
            ):
                try:
                    observed = next(observed_document_rows)
                except StopIteration as exc:
                    raise DescriptorIntegrityError(
                        "BM25 documents end before canonical chunks"
                    ) from exc
                document = project_legal_document(
                    canonical_row,
                    document_index=document_count,
                    config=config,
                )
                expected_document = _expected_bm25_document_row(document)
                if observed != expected_document:
                    differing = sorted(
                        key
                        for key in expected_document
                        if observed.get(key) != expected_document[key]
                    )
                    raise DescriptorIntegrityError(
                        "BM25 document differs from canonical chunk projection at "
                        f"document {document_count}: {differing}"
                    )
                if not first_document:
                    document_semantics.update(b",")
                first_document = False
                document_semantics.update(canonical_json_bytes(expected_document))
                document_count += 1
                token_instance_count += document.total_length
                counters = {
                    field_name: Counter(document.fields[field_name].terms)
                    for field_name in FIELD_ORDER
                }
                terms: set[str] = set()
                for field_name in FIELD_ORDER:
                    length = document.field_length(field_name)
                    field_length_sums[field_name] += length
                    terms.update(counters[field_name])
                for term in sorted(terms):
                    field_tfs = [
                        int(counters[field_name].get(term, 0))
                        for field_name in FIELD_ORDER
                    ]
                    yield {
                        "chunk_cid": document.chunk_cid,
                        "document_index": document.document_index,
                        "document_length": document.total_length,
                        "field_lengths": [
                            # The physical posting schema stores a field length
                            # only when this term occurs in that field; absent
                            # field contributions are represented by zero.
                            (
                                document.field_length(field_name)
                                if field_tfs[position] > 0
                                else 0
                            )
                            for position, field_name in enumerate(FIELD_ORDER)
                        ],
                        "field_tfs": field_tfs,
                        "term": term,
                        "total_frequency": sum(field_tfs),
                        "weighted_frequency": sum(
                            field_tfs[position]
                            * config.field_weights.weight_for(field_name)
                            for position, field_name in enumerate(FIELD_ORDER)
                        ),
                    }
            try:
                extra = next(observed_document_rows)
            except StopIteration:
                extra = None
            if extra is not None:
                raise DescriptorIntegrityError(
                    "BM25 documents continue after canonical chunk exhaustion"
                )

        try:
            pointer_receipt = external_sort_to_file(
                expected_pointers(),
                expected_pointer_path,
                work_dir=work / "pointer-sort",
                key_fn=lambda row: (
                    str(row["term"]),
                    int(row["document_index"]),
                    str(row["chunk_cid"]),
                ),
                family="postings",
                max_records_in_memory=DEFAULT_MAX_RECORDS_IN_MEMORY,
                resume=False,
            )
        except DescriptorIntegrityError:
            raise
        except Exception as exc:
            raise DescriptorIntegrityError(
                f"canonical BM25 semantic projection failed: {exc}"
            ) from exc
        document_semantics.update(b"]")
        if (
            pointer_receipt.interrupted
            or pointer_receipt.status != "complete"
            or document_count < 1
            or pointer_receipt.row_count < 1
            or config.max_documents is not None
            and document_count > config.max_documents
        ):
            raise DescriptorIntegrityError(
                "canonical BM25 semantic projection did not complete"
            )

        expected_stats_path = work / "expected-term-statistics.jsonl"
        try:
            stats_write = write_jsonl_atomic(
                expected_stats_path,
                _iter_expected_bm25_term_statistics(
                    Path(pointer_receipt.output_path),
                    document_count=document_count,
                ),
            )
        except DescriptorIntegrityError:
            raise
        except Exception as exc:
            raise DescriptorIntegrityError(
                f"canonical BM25 term-statistic recomputation failed: {exc}"
            ) from exc
        if stats_write.row_count < 1:
            raise DescriptorIntegrityError(
                "canonical BM25 recomputation produced no vocabulary"
            )

        expected_stats_rows = iter(iter_jsonl(expected_stats_path))
        expected_pointer_rows = iter(iter_jsonl(pointer_receipt.output_path))
        physical_posting_rows = 0
        physical_pointer_count = 0
        route_counts: dict[str, tuple[int, int, int]] = {}
        previous_global_term: str | None = None
        observed_term_count = 0

        for descriptor in posting_descriptors:
            path = confine_path(root, str(descriptor["relative_path"]))
            parquet = pq.ParquetFile(path)
            _assert_parquet_schema(
                parquet,
                columns=_BM25_POSTING_COLUMNS,
                schema_version=POSTING_SCHEMA_VERSION,
                tokenizer_id=config.tokenizer_id,
                label="BM25 posting",
            )
            metadata = parquet.schema_arrow.metadata or {}
            try:
                metadata_k1 = float(metadata.get(b"k1", b"").decode("ascii"))
                metadata_b = float(metadata.get(b"b", b"").decode("ascii"))
                metadata_weights = ast.literal_eval(
                    metadata.get(b"field_weights", b"").decode("utf-8")
                )
            except (SyntaxError, UnicodeError, ValueError) as exc:
                raise DescriptorIntegrityError(
                    "BM25 posting scoring metadata is malformed"
                ) from exc
            if metadata_weights != config.field_weights.to_dict():
                raise DescriptorIntegrityError(
                    "BM25 posting field-weight metadata drifted"
                )
            _assert_semantic_float(
                metadata_k1,
                config.k1,
                name="BM25 posting metadata k1",
            )
            _assert_semantic_float(
                metadata_b,
                config.b,
                name="BM25 posting metadata b",
            )
            shard_first: str | None = None
            shard_last: str | None = None
            shard_term_count = 0
            shard_pointer_count = 0
            shard_token_instance_count = 0
            current_term: str | None = None
            current_stats: dict[str, Any] | None = None
            current_chunk_count = 0
            next_chunk_index = 0
            current_pointer_count = 0

            for batch in parquet.iter_batches(
                batch_size=BM25_SEMANTIC_POSTING_BATCH_ROWS,
            ):
                for value in batch.to_pylist():
                    row = dict(value)
                    physical_posting_rows += 1
                    term = str(row.get("term") or "")
                    if current_term is not None and term != current_term:
                        assert current_stats is not None
                        if (
                            next_chunk_index
                            != current_chunk_count
                            or current_pointer_count
                            != int(current_stats["document_frequency"])
                        ):
                            raise DescriptorIntegrityError(
                                "BM25 posting chunks do not close for "
                                f"{current_term!r}"
                            )
                        current_term = None
                        current_stats = None
                    if current_term is None:
                        if previous_global_term is not None and previous_global_term >= term:
                            raise DescriptorIntegrityError(
                                "physical BM25 vocabulary is not strictly ordered"
                            )
                        try:
                            current_stats = next(expected_stats_rows)
                        except StopIteration as exc:
                            raise DescriptorIntegrityError(
                                "physical BM25 contains vocabulary absent from canonical chunks"
                            ) from exc
                        if current_stats.get("term") != term:
                            raise DescriptorIntegrityError(
                                "physical BM25 vocabulary differs from canonical chunks"
                            )
                        current_term = term
                        previous_global_term = term
                        observed_term_count += 1
                        expected_df = int(current_stats["document_frequency"])
                        current_chunk_count = math.ceil(
                            expected_df / config.postings_per_cell
                        )
                        next_chunk_index = 0
                        current_pointer_count = 0
                        shard_term_count += 1
                        shard_first = shard_first or term
                    assert current_stats is not None
                    pointer_count = int(row.get("pointer_count", -1))
                    expected_pointer_count = min(
                        config.postings_per_cell,
                        int(current_stats["document_frequency"])
                        - next_chunk_index * config.postings_per_cell,
                    )
                    arrays = {
                        name: list(row.get(name) or ())
                        for name in (
                            "body_frequencies",
                            "chunk_cids",
                            "document_indices",
                            "document_lengths",
                            "entry_cids",
                            "title_frequencies",
                            "total_frequencies",
                            "weighted_frequencies",
                            *(f"legal_{name}_frequencies" for name in FIELD_ORDER),
                            *(f"legal_{name}_lengths" for name in FIELD_ORDER),
                        )
                    }
                    if (
                        row.get("schema_version") != POSTING_SCHEMA_VERSION
                        or int(row.get("document_frequency", -1))
                        != int(current_stats["document_frequency"])
                        or int(row.get("corpus_frequency", -1))
                        != int(current_stats["corpus_frequency"])
                        or int(row.get("posting_chunk_count", -1))
                        != current_chunk_count
                        or current_chunk_count < 1
                        or current_chunk_count > MAX_ROWS_PER_PHYSICAL_SHARD
                        or int(row.get("posting_chunk_index", -1))
                        != next_chunk_index
                        or pointer_count != expected_pointer_count
                        or any(len(items) != pointer_count for items in arrays.values())
                    ):
                        raise DescriptorIntegrityError(
                            f"BM25 posting row metadata is invalid for {term!r}"
                        )
                    _assert_semantic_float(
                        row.get("idf"),
                        float(current_stats["idf"]),
                        name=f"BM25 idf[{term}]",
                    )
                    _assert_semantic_float(
                        row.get("weighted_corpus_frequency"),
                        float(current_stats["weighted_corpus_frequency"]),
                        name=f"BM25 weighted_corpus_frequency[{term}]",
                    )
                    for offset in range(pointer_count):
                        try:
                            expected_pointer = next(expected_pointer_rows)
                        except StopIteration as exc:
                            raise DescriptorIntegrityError(
                                "physical BM25 pointers exceed canonical projection"
                            ) from exc
                        field_tfs = list(expected_pointer["field_tfs"])
                        field_lengths = list(expected_pointer["field_lengths"])
                        if (
                            len(field_tfs) != len(FIELD_ORDER)
                            or len(field_lengths) != len(FIELD_ORDER)
                        ):
                            raise DescriptorIntegrityError(
                                "canonical BM25 field vector width drifted"
                            )
                        expected_title_tf = sum(
                            int(field_tfs[FIELD_ORDER.index(name)])
                            for name in QUERY_TITLE_FIELDS
                        )
                        expected_body_tf = sum(
                            int(field_tfs[FIELD_ORDER.index(name)])
                            for name in QUERY_BODY_FIELDS
                        )
                        exact_pointer_values = {
                            "chunk_cids": expected_pointer["chunk_cid"],
                            "document_indices": int(
                                expected_pointer["document_index"]
                            ),
                            "document_lengths": int(
                                expected_pointer["document_length"]
                            ),
                            "entry_cids": expected_pointer["chunk_cid"],
                            "title_frequencies": expected_title_tf,
                            "body_frequencies": expected_body_tf,
                            "total_frequencies": int(
                                expected_pointer["total_frequency"]
                            ),
                        }
                        if expected_pointer.get("term") != term or any(
                            arrays[name][offset] != expected
                            for name, expected in exact_pointer_values.items()
                        ):
                            raise DescriptorIntegrityError(
                                "BM25 pointer identity/frequency differs from "
                                f"canonical chunks for {term!r}"
                            )
                        for field_position, field_name in enumerate(FIELD_ORDER):
                            if (
                                arrays[f"legal_{field_name}_frequencies"][offset]
                                != int(field_tfs[field_position])
                                or arrays[f"legal_{field_name}_lengths"][offset]
                                != int(field_lengths[field_position])
                            ):
                                raise DescriptorIntegrityError(
                                    "BM25 exact field TF/length differs from "
                                    f"canonical chunks for {term!r}/{field_name}"
                                )
                        _assert_semantic_float(
                            arrays["weighted_frequencies"][offset],
                            float(expected_pointer["weighted_frequency"]),
                            name=f"BM25 weighted_frequency[{term}]",
                        )
                    next_chunk_index += 1
                    current_pointer_count += pointer_count
                    physical_pointer_count += pointer_count
                    shard_pointer_count += pointer_count
                    shard_token_instance_count += sum(
                        int(value) for value in arrays["total_frequencies"]
                    )
                    shard_last = term
            if current_term is not None:
                assert current_stats is not None
                if (
                    next_chunk_index
                    != current_chunk_count
                    or current_pointer_count
                    != int(current_stats["document_frequency"])
                ):
                    raise DescriptorIntegrityError(
                        f"BM25 posting chunks do not close for {current_term!r}"
                    )
                current_term = None
                current_stats = None
            descriptor_metadata = descriptor.get("metadata")
            if (
                shard_first is None
                or shard_last is None
                or shard_first != descriptor.get("first_key")
                or shard_last != descriptor.get("last_key")
                or not isinstance(descriptor_metadata, Mapping)
                or int(descriptor_metadata.get("pointer_count", -1))
                != shard_pointer_count
                or int(descriptor_metadata.get("term_count", -1))
                != shard_term_count
            ):
                raise DescriptorIntegrityError(
                    "BM25 posting descriptor does not match canonical semantics"
                )
            route_counts[str(descriptor["relative_path"])] = (
                shard_pointer_count,
                shard_term_count,
                shard_token_instance_count,
            )

        try:
            extra_pointer = next(expected_pointer_rows)
        except StopIteration:
            extra_pointer = None
        try:
            extra_stats = next(expected_stats_rows)
        except StopIteration:
            extra_stats = None
        if extra_pointer is not None or extra_stats is not None:
            raise DescriptorIntegrityError(
                "physical BM25 omits canonical term/document semantics"
            )

        recomputed = digest_sorted_bm25_term_statistics(
            (str(row["term"]), int(row["document_frequency"]))
            for row in iter_jsonl(expected_stats_path)
        )
        if recomputed.term_count != observed_term_count:
            raise DescriptorIntegrityError(
                "physical BM25 vocabulary count differs from canonical chunks"
            )
        average_document_length = float(token_instance_count) / float(document_count)
        average_field_lengths = {
            field_name: float(field_length_sums[field_name]) / float(document_count)
            for field_name in FIELD_ORDER
        }
        expected_counts = {
            "bm25_document_chunks": len(document_descriptors),
            "bm25_documents": document_count,
            "bm25_keyword_shards": len(posting_descriptors),
            "bm25_posting_rows": physical_posting_rows,
            "bm25_postings": physical_pointer_count,
            "bm25_terms": recomputed.term_count,
            "bm25_token_instances": token_instance_count,
        }
        wrong_counts = {
            name: (counts.get(name), expected)
            for name, expected in expected_counts.items()
            if counts.get(name) != expected
        }
        if wrong_counts:
            raise DescriptorIntegrityError(
                f"BM25 corpus/statistic counts differ from canonical chunks: {wrong_counts}"
            )
        if (
            bm25.get("document_count") != document_count
            or bm25.get("term_count") != recomputed.term_count
            or bm25.get("token_instance_count") != token_instance_count
            or bm25.get("vocabulary_sha256") != recomputed.vocabulary_sha256
            or bm25.get("document_frequency_sha256")
            != recomputed.document_frequency_sha256
        ):
            raise DescriptorIntegrityError(
                "BM25 manifest statistics differ from canonical recomputation"
            )
        _assert_semantic_float(
            bm25.get("average_document_length"),
            average_document_length,
            name="bm25.average_document_length",
        )
        observed_field_averages = bm25.get("average_field_lengths")
        if not isinstance(observed_field_averages, Mapping) or set(
            observed_field_averages
        ) != set(FIELD_ORDER):
            raise DescriptorIntegrityError(
                "BM25 average_field_lengths does not exactly cover scoring fields"
            )
        for field_name in FIELD_ORDER:
            _assert_semantic_float(
                observed_field_averages[field_name],
                average_field_lengths[field_name],
                name=f"bm25.average_field_lengths[{field_name}]",
            )

        if (
            graph_proof.get("vocabulary_sha256") != recomputed.vocabulary_sha256
            or graph_proof.get("document_frequency_sha256")
            != recomputed.document_frequency_sha256
            or int(graph_proof.get("term_count", -1)) != recomputed.term_count
            or int(graph_proof.get("document_count", -1)) != document_count
            or int(graph_proof.get("term_document_pair_count", -1))
            != physical_pointer_count
            or graph_proof.get("bm25_config_digest")
            != bm25.get("config_digest")
            or graph_proof.get("index_root_cid") != bm25.get("index_root_cid")
        ):
            raise DescriptorIntegrityError(
                "knowledge-graph vocabulary proof differs from canonical BM25 semantics"
            )

        keyword_index = _descriptor_mapping(
            indexes.get("bm25_keyword_shards"),
            name="indexes.bm25_keyword_shards",
        )
        _verify_compact_routes(
            root,
            index_descriptor=keyword_index,
            data_descriptors=posting_descriptors,
            kind="bm25_postings",
            expected_total_rows=physical_posting_rows,
            require_document_ranges=False,
        )
        keyword_rows = pq.read_table(
            confine_path(root, str(keyword_index["relative_path"]))
        ).to_pylist()
        for position, row in enumerate(keyword_rows):
            expected = route_counts.get(str(row.get("relative_path") or ""))
            if expected is None or (
                int(row.get("posting_count", -1)) != expected[0]
                or int(row.get("term_count", -1)) != expected[1]
                or int(row.get("token_instance_count", -1))
                != expected[2]
            ):
                raise DescriptorIntegrityError(
                    f"BM25 keyword route {position} has stale semantic counts"
                )
        _verify_compact_routes(
            root,
            index_descriptor=_descriptor_mapping(
                indexes.get("bm25_document_chunks"),
                name="indexes.bm25_document_chunks",
            ),
            data_descriptors=document_descriptors,
            kind="bm25_documents",
            expected_total_rows=document_count,
            require_document_ranges=True,
        )

        return {
            "average_document_length": average_document_length,
            "average_field_lengths": average_field_lengths,
            "document_count": document_count,
            "document_frequency_sha256": recomputed.document_frequency_sha256,
            "document_semantics_sha256": document_semantics.hexdigest(),
            "posting_count": physical_pointer_count,
            "posting_semantics_sha256": pointer_receipt.output_digest,
            "term_count": recomputed.term_count,
            "term_statistics_sha256": stats_write.sha256,
            "token_instance_count": token_instance_count,
            "vocabulary_sha256": recomputed.vocabulary_sha256,
        }


def _bm25_semantic_attestation(proof: Mapping[str, Any]) -> dict[str, Any]:
    """Compact manifest evidence for the independently recomputed semantics."""

    return {
        "bm25_canonical_document_count": int(proof["document_count"]),
        "bm25_canonical_document_semantics_sha256": str(
            proof["document_semantics_sha256"]
        ),
        "bm25_canonical_posting_count": int(proof["posting_count"]),
        "bm25_canonical_posting_semantics_sha256": str(
            proof["posting_semantics_sha256"]
        ),
        "bm25_canonical_term_count": int(proof["term_count"]),
        "bm25_canonical_term_statistics_sha256": str(
            proof["term_statistics_sha256"]
        ),
        "bm25_canonical_token_instance_count": int(
            proof["token_instance_count"]
        ),
        "bm25_semantics_recomputed_from_canonical_chunks": True,
    }


@dataclass(frozen=True, slots=True)
class LocalStateLawsReleaseManifest:
    """One verified local manifest and its canonical content digest."""

    output_root: str
    relative_path: str
    payload: Mapping[str, Any]
    manifest_digest: str

    @property
    def path(self) -> Path:
        return Path(self.output_root) / self.relative_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_digest": self.manifest_digest,
            "output_root": self.output_root,
            "payload": dict(self.payload),
            "relative_path": self.relative_path,
        }


def verify_state_laws_local_release_manifest(
    output_root: str | Path,
    *,
    manifest_path: str = MANIFEST_PATH,
) -> LocalStateLawsReleaseManifest:
    """Reverify a completed exact-51 local release without rewriting it.

    This is the shared read-only admission seam for restart checkpoints and
    publication-package planning.  It validates canonical manifest bytes,
    production retrieval bindings, exact-51 source/rights closure, and every
    descriptor surface against the existing files.  It performs no network or
    publication action.
    """

    root = resolve_release_root(output_root, must_exist=True)
    manifest_relative = normalize_relative_artifact_path(
        manifest_path, name="manifest_path"
    )
    if manifest_relative != MANIFEST_PATH:
        raise StateLawsLocalReleaseError(
            f"canonical local release manifest path must be {MANIFEST_PATH!r}"
        )
    path = confine_path(root, manifest_relative)
    if path.is_symlink() or not path.is_file():
        raise DescriptorIntegrityError(
            "completed local release manifest is missing or unsafe"
        )
    try:
        encoded = path.read_bytes()
        payload = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DescriptorIntegrityError(
            "completed local release manifest is invalid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise DescriptorIntegrityError(
            "completed local release manifest must be a JSON object"
        )
    canonical = canonical_json_bytes(payload)
    if encoded not in {canonical, canonical + b"\n"}:
        raise DescriptorIntegrityError(
            "completed local release manifest is not canonical"
        )
    payload = dict(payload)

    release_control = payload.get("release_control")
    validation = payload.get("validation")
    indexes = payload.get("indexes")
    bm25 = payload.get("bm25")
    graph = payload.get("graph")
    vector = payload.get("vector")
    rights = payload.get("source_rights_receipt")
    source_provenance_verifier = payload.get("source_provenance_verifier")
    corpus_chunks_index = (
        indexes.get("corpus_chunks") if isinstance(indexes, Mapping) else None
    )
    graph_vocabulary = (
        graph.get("vocabulary_parity") if isinstance(graph, Mapping) else None
    )
    if (
        payload.get("schema_version") != RELEASE_SCHEMA_VERSION
        or payload.get("release_profile") != RELEASE_PROFILE
        or payload.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID
        or payload.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID
        or payload.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION
        or payload.get("jurisdictions") != list(CANONICAL_JURISDICTION_ORDER)
        or not isinstance(release_control, Mapping)
        or release_control.get("local_staging_only") is not True
        or release_control.get("authorizes_publication") is not False
        or release_control.get("authorizes_hub_upload") is not False
        or release_control.get("network_io_performed") is not False
        or release_control.get("publication_action_performed") is not False
        or not isinstance(validation, Mapping)
        or validation.get("status") != "passed"
        or validation.get("default_jurisdiction_count")
        != EXPECTED_JURISDICTION_COUNT
        or validation.get("descriptor_bytes_verified") is not True
        or validation.get("no_quarantine") is not True
        or validation.get("bm25_semantics_recomputed_from_canonical_chunks")
        is not True
        or validation.get("official_source_receipt_count")
        != EXPECTED_JURISDICTION_COUNT
        or validation.get("bm25_vocabulary_lexical_graph_exact") is not True
        or validation.get("term_document_edges_materialized") is not False
        or not isinstance(indexes, Mapping)
        or not set(REQUIRED_INDEX_PATHS).issubset(indexes)
        or not isinstance(corpus_chunks_index, Mapping)
        or not isinstance(bm25, Mapping)
        or bm25.get("canonical_chunk_artifact_digest")
        != corpus_chunks_index.get("sha256")
        or not isinstance(vector, Mapping)
        or vector.get("production_ready") is not True
        or vector.get("projection_embeddings") is not False
        or vector.get("real_inference") is not True
        or vector.get("source_production_ready") is not True
        or vector.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID
        or vector.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION
        or vector.get("dimension") != DEFAULT_EMBEDDING_DIMENSION
        or not isinstance(graph_vocabulary, Mapping)
        or graph_vocabulary.get("production_ready") is not True
        or graph_vocabulary.get("vocabulary_sha256")
        != bm25.get("vocabulary_sha256")
        or graph_vocabulary.get("bm25_config_digest")
        != bm25.get("config_digest")
        or not isinstance(rights, Mapping)
        or not isinstance(source_provenance_verifier, Mapping)
        or validation.get("source_provenance_verifier_current") is not True
    ):
        raise StateLawsLocalReleaseError(
            "completed manifest no longer satisfies local exact-51 release gates"
        )
    _require_current_source_provenance_verifier_attestation(
        source_provenance_verifier
    )
    for name, expected_path in REQUIRED_INDEX_PATHS.items():
        descriptor = indexes[name]
        if (
            not isinstance(descriptor, Mapping)
            or descriptor.get("relative_path") != expected_path
        ):
            raise StateLawsLocalReleaseError(
                f"completed manifest index {name!r} drifted"
            )

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(
        artifacts, (str, bytes, bytearray)
    ):
        raise DescriptorIntegrityError("completed manifest artifacts are malformed")
    artifact_paths: list[str] = []
    descriptor_by_path: dict[str, dict[str, Any]] = {}
    for position, value in enumerate(artifacts):
        descriptor = _descriptor_mapping(
            value, name=f"manifest.artifacts[{position}]"
        )
        relative = normalize_relative_artifact_path(
            descriptor.get("relative_path") or descriptor.get("path"),
            name=f"manifest.artifacts[{position}].relative_path",
        )
        if relative == MANIFEST_PATH or relative in descriptor_by_path:
            raise DescriptorIntegrityError(
                f"completed manifest has duplicate/self descriptor: {relative}"
            )
        descriptor = _verify_descriptor(
            root,
            descriptor,
            surface=f"manifest.artifacts[{position}]",
        )
        artifact_paths.append(relative)
        descriptor_by_path[relative] = descriptor
    if artifact_paths != sorted(artifact_paths):
        raise DescriptorIntegrityError(
            "completed manifest artifact descriptors are not deterministically ordered"
        )

    families = {
        str(descriptor.get("family") or "").strip().casefold()
        for descriptor in descriptor_by_path.values()
    }
    missing_families = sorted(REQUIRED_DATA_FAMILIES - families)
    if missing_families:
        raise StateLawsLocalReleaseError(
            f"completed manifest lacks physical families: {missing_families}"
        )
    validate_semantic_family_closure((*families, "manifest"))

    descriptor_surfaces: list[tuple[str, Mapping[str, Any]]] = [
        (f"manifest.indexes.{name}", indexes[name])
        for name in sorted(REQUIRED_INDEX_PATHS)
    ]
    source_receipts = payload.get("source_receipts")
    if not isinstance(source_receipts, Sequence) or isinstance(
        source_receipts, (str, bytes, bytearray)
    ) or len(source_receipts) != EXPECTED_JURISDICTION_COUNT:
        raise ReleaseReceiptError(
            "completed manifest must expose exactly 51 source-receipt descriptors"
        )
    receipt_jurisdictions: set[str] = set()
    receipt_ids: set[str] = set()
    receipt_paths: set[str] = set()
    typed_source_receipts: list[SourceReceiptRecord] = []
    for position, value in enumerate(source_receipts):
        receipt_descriptor = _descriptor_mapping(
            value, name=f"manifest.source_receipts[{position}]"
        )
        metadata = receipt_descriptor.get("metadata")
        if not isinstance(metadata, Mapping):
            raise ReleaseReceiptError(
                "source-receipt descriptor metadata is absent"
            )
        code = str(metadata.get("jurisdiction_code") or "").strip().upper()
        if metadata.get("receipt_kind") != "source_receipt" or not code:
            raise ReleaseReceiptError(
                "source-receipt descriptor metadata is incomplete"
            )
        relative = normalize_relative_artifact_path(
            receipt_descriptor.get("relative_path") or receipt_descriptor.get("path"),
            name=f"manifest.source_receipts[{position}].relative_path",
        )
        receipt_payload = _read_canonical_json_object(
            confine_path(root, relative),
            label=f"{code or position} source receipt",
        )
        required_receipt_fields = {
            "content_hashes",
            "discovered",
            "duplicates",
            "excluded",
            "failed_final",
            "fetched",
            "frontier_closed",
            "jurisdiction",
            "observation_time",
            "official_source_url",
            "payload",
            "quarantined",
            "receipt_id",
            "relative_path",
            "release_point",
            "schema_version",
            "source_authority_class",
            "source_checksum",
            "source_software_version",
            "start_urls",
            "verification_result",
        }
        missing_receipt_fields = sorted(
            required_receipt_fields.difference(receipt_payload)
        )
        if missing_receipt_fields:
            raise ReleaseReceiptError(
                f"{code or position} source receipt lacks required JSON fields: "
                f"{missing_receipt_fields}"
            )
        try:
            typed_receipt = SourceReceiptRecord.from_mapping(receipt_payload)
        except (TypeError, ValueError) as exc:
            raise ReleaseReceiptError(
                f"{code or position} source receipt is malformed: {exc}"
            ) from exc
        if typed_receipt.jurisdiction != code:
            raise ReleaseReceiptError(
                f"source-receipt jurisdiction mismatch: descriptor={code!r}, "
                f"JSON={typed_receipt.jurisdiction!r}"
            )
        if typed_receipt.relative_path != relative:
            raise ReleaseReceiptError(
                f"{code} source-receipt JSON path does not match its descriptor"
            )
        if (
            receipt_descriptor.get("family") != "receipt"
            or receipt_descriptor.get("media_type") != "application/json"
            or int(receipt_descriptor.get("row_count", -1)) != 1
            or receipt_descriptor.get("schema_id") != typed_receipt.schema_version
            or receipt_descriptor.get("first_key") != typed_receipt.receipt_id
            or receipt_descriptor.get("last_key") != typed_receipt.receipt_id
        ):
            raise ReleaseReceiptError(
                f"{code} source-receipt descriptor identity does not match its JSON"
            )
        if typed_receipt.receipt_id in receipt_ids:
            raise ReleaseReceiptError(
                f"duplicate source-receipt identity: {typed_receipt.receipt_id!r}"
            )
        if relative in receipt_paths:
            raise ReleaseReceiptError(f"duplicate source-receipt path: {relative!r}")
        receipt_ids.add(typed_receipt.receipt_id)
        receipt_paths.add(relative)
        receipt_jurisdictions.add(code)
        typed_source_receipts.append(typed_receipt)
        descriptor_surfaces.append(
            (f"manifest.source_receipts[{position}]", receipt_descriptor)
        )
    if receipt_jurisdictions != set(CANONICAL_JURISDICTIONS):
        raise ReleaseReceiptError(
            "source-receipt descriptors do not cover the exact 50 states plus DC"
        )
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        raise StateLawsLocalReleaseError("completed manifest counts are absent")
    corpus_document_count = _int_value(
        counts.get("corpus_documents"), name="counts.corpus_documents"
    )
    _validate_source_receipt_records(
        typed_source_receipts,
        corpus_document_count,
    )

    rights_descriptor = descriptor_by_path.get(SOURCE_RIGHTS_RECEIPT_RELPATH)
    if rights_descriptor is None:
        raise ReleaseReceiptError(
            "completed release lacks its source-scope/access receipt artifact"
        )
    rights_metadata = rights_descriptor.get("metadata")
    if (
        rights_descriptor.get("family") != "report"
        or rights_descriptor.get("media_type") != "application/json"
        or int(rights_descriptor.get("row_count", -1)) != 1
        or not isinstance(rights_metadata, Mapping)
        or rights_metadata.get("receipt_kind") != "source_rights_receipt"
    ):
        raise ReleaseReceiptError(
            "source-scope/access receipt descriptor is incomplete"
        )
    rights_payload = _read_canonical_json_object(
        confine_path(root, SOURCE_RIGHTS_RECEIPT_RELPATH),
        label="source-scope/access receipt",
    )
    expected_rights_schema = str(
        rights_payload.get("report_schema")
        or rights_payload.get("schema_version")
        or "state-laws-source-rights-receipt/v1"
    )
    if rights_descriptor.get("schema_id") != expected_rights_schema:
        raise ReleaseReceiptError(
            "source-scope/access receipt descriptor schema identity mismatched"
        )
    normalized_rights = _validate_rights_receipt(
        rights_payload,
        source_receipt_ids=receipt_ids,
    )
    if dict(rights) != normalized_rights:
        raise ReleaseReceiptError(
            "manifest source-scope/access receipt summary differs from its JSON"
        )
    rights_digest = str(normalized_rights["receipt_digest"])
    catalog_digest = str(normalized_rights["catalog_digest_sha256"])
    if (
        rights_metadata.get("receipt_digest") != rights_digest
        or rights_descriptor.get("first_key") != rights_digest
        or rights_descriptor.get("last_key") != rights_digest
    ):
        raise ReleaseReceiptError(
            "source-scope/access receipt descriptor digest identity mismatched"
        )
    require_source_rights_binding(
        payload,
        receipt_digest=rights_digest,
        catalog_digest=catalog_digest,
    )

    for label, descriptor in descriptor_surfaces:
        relative = normalize_relative_artifact_path(
            descriptor.get("relative_path") or descriptor.get("path"),
            name=f"{label}.relative_path",
        )
        canonical_descriptor = descriptor_by_path.get(relative)
        if canonical_descriptor is None:
            raise DescriptorIntegrityError(
                f"{label} is absent from manifest.artifacts"
            )
        _merge_equivalent_descriptor(
            canonical_descriptor,
            descriptor,
            label=relative,
        )
        _verify_descriptor(root, descriptor, surface=label)

    _assert_bm25_graph_parity(
        {"bm25": bm25},
        {"graph": graph},
        counts={str(key): int(value) for key, value in counts.items()},
    )
    semantic_proof = _verify_completed_bm25_semantics(
        root,
        payload=payload,
        descriptors=descriptor_by_path,
    )
    expected_semantic_attestation = _bm25_semantic_attestation(semantic_proof)
    observed_semantic_attestation = {
        key: validation.get(key) for key in expected_semantic_attestation
    }
    if observed_semantic_attestation != expected_semantic_attestation:
        raise DescriptorIntegrityError(
            "completed manifest BM25 semantic attestation does not match "
            "canonical-chunk recomputation"
        )

    manifest_size, manifest_file_digest = file_digest(path)
    if (
        manifest_size != len(encoded)
        or manifest_file_digest.hex() != sha256(encoded).hexdigest()
    ):
        raise DescriptorIntegrityError("completed local manifest bytes drifted")
    return LocalStateLawsReleaseManifest(
        output_root=str(root),
        relative_path=manifest_relative,
        payload=payload,
        manifest_digest=digest_mapping(payload),
    )


def assemble_state_laws_local_release_manifest(
    output_root: str | Path,
    *,
    corpus: Any,
    chunks: Any,
    bm25: Any,
    vectors: Any,
    graph: Any,
    rights_receipt: Mapping[str, Any],
    source_revision: str,
    release_point: str,
    build_config_cid: str | None = None,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    key_evidence: Mapping[str, Iterable[str]] | None = None,
    source_provenance_verifier: Mapping[str, Any] | None = None,
    manifest_path: str = MANIFEST_PATH,
) -> LocalStateLawsReleaseManifest:
    """Assemble and atomically stage a query-compatible local manifest.

    The function has no publish switch by design.  Absence of any required
    evidence is an error; production/readiness flags are never inferred.
    """

    root = resolve_release_root(output_root, must_exist=True)
    manifest_relative = normalize_relative_artifact_path(
        manifest_path, name="manifest_path"
    )
    if manifest_relative != MANIFEST_PATH:
        raise StateLawsLocalReleaseError(
            f"canonical local release manifest path must be {MANIFEST_PATH!r}"
        )
    revision = require_immutable_revision(source_revision, name="source_revision")
    release_point = str(release_point or "").strip()
    if not release_point or release_point.lower() in {
        "main",
        "master",
        "latest",
        "head",
    }:
        raise StateLawsLocalReleaseError("release_point must be exact and immutable")

    _require_production_source(corpus, family="corpus")
    _require_production_source(chunks, family="chunks")
    _require_production_source(bm25, family="bm25")
    _require_production_source(graph, family="graph")

    corpus_fragment = _fragment(corpus, family="corpus")
    chunk_fragment = _fragment(chunks, family="chunks")
    bm25_fragment = _fragment(bm25, family="bm25")
    vector_fragment = _extract_vector_fragment(
        vectors, _fragment(vectors, family="vectors")
    )
    graph_fragment = _fragment(graph, family="graph")
    fragments = {
        "corpus": corpus_fragment,
        "chunks": chunk_fragment,
        "bm25": bm25_fragment,
        "vectors": vector_fragment,
        "graph": graph_fragment,
    }
    for name, fragment in fragments.items():
        _assert_no_quarantine(fragment, path=name)

    corpus_jurisdictions = set(corpus_fragment.get("jurisdictions") or ())
    if len(
        corpus_jurisdictions
    ) != EXPECTED_JURISDICTION_COUNT or corpus_jurisdictions != set(
        CANONICAL_JURISDICTIONS
    ):
        raise StateLawsLocalReleaseError(
            "default corpus must contain the exact 50 states + DC"
        )
    default_config = corpus_fragment.get("default_config")
    if not isinstance(default_config, Mapping) or (
        default_config.get("admission_status") != "admitted"
        or default_config.get("allow_quarantine") is not False
    ):
        raise StateLawsLocalReleaseError(
            "default corpus config must be admitted-only with quarantine disabled"
        )

    key_sets = {
        family: _extract_parent_keys(
            source,
            fragments[family],
            family=family,
            explicit=key_evidence,
        )
        for family, source in (
            ("corpus", corpus),
            ("chunks", chunks),
            ("bm25", bm25),
            ("vectors", vectors),
            ("graph", graph),
        )
    }
    parity = _assert_key_parity(key_sets)
    receipts = _validate_source_receipts(corpus, len(key_sets["corpus"]))
    rights = _validate_rights_receipt(
        rights_receipt,
        source_receipt_ids=(receipt.receipt_id for receipt in receipts),
    )
    source_provenance_verifier = (
        _require_current_source_provenance_verifier_attestation(
            source_provenance_verifier
        )
    )

    vector = _vector_config(vector_fragment)
    chunk_config = _chunk_config(chunk_fragment)
    counts = _counts(
        corpus_fragment,
        chunk_fragment,
        bm25_fragment,
        vector,
        graph_fragment,
        key_count=len(key_sets["corpus"]),
    )
    parity.update(
        _assert_chunk_cid_parity(
            chunks,
            bm25,
            vectors,
            expected_count=counts["searchable_chunks"],
        )
    )
    vocabulary_parity = _assert_bm25_graph_parity(
        bm25_fragment, graph_fragment, counts=counts
    )

    all_indexes: dict[str, dict[str, Any]] = {}
    for family, fragment in fragments.items():
        for name, descriptor in _indexes(fragment, family=family).items():
            if name in all_indexes and all_indexes[name] != descriptor:
                raise DescriptorIntegrityError(f"conflicting index descriptor {name!r}")
            all_indexes[name] = descriptor
    missing_indexes = sorted(set(REQUIRED_INDEX_PATHS) - set(all_indexes))
    if missing_indexes:
        raise StateLawsLocalReleaseError(
            f"release lacks query-required indexes: {missing_indexes}"
        )
    unexpected_paths = {
        name: descriptor.get("relative_path")
        for name, expected_path in REQUIRED_INDEX_PATHS.items()
        if (descriptor := all_indexes[name]).get("relative_path") != expected_path
    }
    if unexpected_paths:
        raise StateLawsLocalReleaseError(
            f"canonical index path drift: {unexpected_paths}"
        )
    verified_indexes = {
        name: _verify_descriptor(root, descriptor, surface=f"indexes.{name}")
        for name, descriptor in sorted(all_indexes.items())
    }
    if any(
        item["row_count"] > MAX_ROUTING_ROWS_PER_INDEX
        for item in verified_indexes.values()
    ):
        raise StateLawsLocalReleaseError("routing index exceeds the sealed row bound")

    artifacts = _merge_artifacts(
        root,
        (
            (corpus, corpus_fragment),
            (chunks, chunk_fragment),
            (bm25, bm25_fragment),
            (vectors, vector_fragment),
            (graph, graph_fragment),
        ),
        verified_indexes,
    )
    _assert_descriptor_count_parity(artifacts, counts=counts, vector=vector)

    bm25_config = _plain_mapping(bm25_fragment.get("bm25") or {}, name="bm25")
    tokenizer_id = str(bm25_config.get("tokenizer") or "").strip()
    if not tokenizer_id:
        raise StateLawsLocalReleaseError("BM25 tokenizer identity is absent")
    vector_space_id = str(vector.get("vector_space_id") or "").strip()
    if not vector_space_id:
        raise VectorProductionGateError("vector_space_id is absent")
    if build_config_cid is None:
        build_config_cid = digest_mapping(
            {
                "bm25_config_digest": bm25_config.get("config_digest"),
                "canonical_chunk_config_digest": chunk_config.get("config_digest"),
                "canonical_chunk_parent_corpus_digest": chunk_fragment["corpus"].get(
                    "parent_corpus_digest"
                ),
                "model_token_validator_id": PINNED_TOKEN_COUNTER_ID,
                "source_provenance_verifier_sha256": (
                    source_provenance_verifier["sha256"]
                ),
                "graph_projection": _nested(
                    graph_fragment, "graph", "projection_graph_cid"
                ),
                "vector_space_id": vector_space_id,
            }
        )
    build_config_cid = validate_digest(build_config_cid, name="build_config_cid")

    if any(
        item.get("relative_path") == SOURCE_RIGHTS_RECEIPT_RELPATH
        for item in artifacts
    ):
        raise DescriptorIntegrityError(
            "source-rights receipt path conflicts with an existing artifact"
        )
    rights_descriptor = _stage_rights_receipt(
        root,
        rights_receipt,
        normalized=rights,
    )
    artifacts = tuple(
        sorted(
            (*artifacts, rights_descriptor),
            key=lambda item: str(item["relative_path"]),
        )
    )

    payload: dict[str, Any] = {
        "artifacts": list(artifacts),
        "bm25": bm25_config,
        "build_config_cid": build_config_cid,
        "configs": {
            "canonical_chunks": dict(chunk_config),
            "default": "state_statutes_exact_51",
            "local_staging_only": True,
        },
        "counts": counts,
        "dataset_repo_id": dataset_repo_id,
        "graph": dict(graph_fragment["graph"]),
        "graph_ontology_version": ONTOLOGY_VERSION,
        "indexes": verified_indexes,
        "jurisdictions": list(CANONICAL_JURISDICTION_ORDER),
        "key_parity": parity,
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_posting_pointers_per_row": MAX_POSTING_POINTERS_PER_ROW,
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
        "package_version": "2",
        "primary_key": "entry_cid",
        "release_control": {
            "authorizes_hub_upload": False,
            "authorizes_publication": False,
            "fail_closed": True,
            "local_staging_only": True,
            "network_io_performed": False,
            "publication_action_performed": False,
        },
        "release_point": release_point,
        "release_profile": RELEASE_PROFILE,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "source_revision": revision,
        "source_provenance_verifier": source_provenance_verifier,
        "source_rights_catalog_digest": rights["catalog_digest_sha256"],
        "source_rights_receipt": rights,
        "source_rights_receipt_digest": rights["receipt_digest"],
        "source_rights_receipt_path": rights["relative_path"],
        "source_receipts": [
            descriptor
            for descriptor in artifacts
            if str(descriptor.get("family") or "").lower() == "receipt"
            and _nested(descriptor, "metadata", "receipt_kind") == "source_receipt"
        ],
        "tokenizer_id": tokenizer_id,
        "validation": {
            "bm25_vocabulary_lexical_graph_exact": True,
            "default_jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
            "descriptor_bytes_verified": True,
            "index_descriptor_count": len(verified_indexes),
            "model_token_validator_id": PINNED_TOKEN_COUNTER_ID,
            "no_quarantine": True,
            "official_source_receipt_count": len(receipts),
            "source_provenance_verifier_current": True,
            "status": "passed",
            "term_document_edges_materialized": False,
            "vocabulary_sha256": vocabulary_parity.get("vocabulary_sha256"),
        },
        "vector": vector,
        "vector_space_id": vector_space_id,
    }
    semantic_proof = _verify_completed_bm25_semantics(
        root,
        payload=payload,
        descriptors={
            str(descriptor["relative_path"]): descriptor
            for descriptor in artifacts
        },
    )
    payload["validation"].update(_bm25_semantic_attestation(semantic_proof))
    # Ensure the public manifest itself does not expose a private/local absolute path.
    encoded = canonical_json_dumps(payload)
    if str(root) in encoded:
        raise StateLawsLocalReleaseError("manifest leaked its local output path")
    manifest_digest = digest_mapping(payload)
    atomic_write_canonical_json(confine_path(root, manifest_relative), payload)
    observed = confine_path(root, manifest_relative).read_bytes().rstrip(b"\n")
    if observed != canonical_json_bytes(payload):
        raise DescriptorIntegrityError("staged manifest bytes are not canonical")
    return LocalStateLawsReleaseManifest(
        output_root=str(root),
        relative_path=manifest_relative,
        payload=payload,
        manifest_digest=manifest_digest,
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "MANIFEST_PATH",
    "PERFORMS_NETWORK_IO",
    "REQUIRED_DATA_FAMILIES",
    "REQUIRED_INDEX_PATHS",
    "SCHEMA_VERSION",
    "SOURCE_PROVENANCE_VERIFIER_ATTESTATION_SCHEMA_VERSION",
    "SOURCE_PROVENANCE_VERIFIER_RELATIVE_PATH",
    "DescriptorIntegrityError",
    "LocalStateLawsReleaseManifest",
    "ManifestFragmentProvider",
    "MissingManifestFragmentError",
    "ReleaseKeyParityError",
    "ReleaseReceiptError",
    "StateLawsLocalReleaseError",
    "VectorProductionGateError",
    "assemble_state_laws_local_release_manifest",
    "state_laws_source_provenance_verifier_attestation",
    "verify_state_laws_local_release_manifest",
]
