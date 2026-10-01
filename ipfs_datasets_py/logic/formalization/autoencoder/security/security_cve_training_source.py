"""Bounded, pinned CVE graph observations with fail-closed training admission.

The complete Publicus release is a GraphRAG projection, not the canonical-row
SecurityIR release. Graph CIDs and upstream row routing can be verified without
opening original code. They do not reconstruct SourceRecord/PolicyCandidate or
the code-body digests needed for benchmark decontamination. This reader makes
that distinction explicit and never converts a retrieval node into a policy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from ipfs_datasets_py.logic.security_ir.cvefixes import hf_complete_source as native
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_graph_layout import (
    CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION, _node_label,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_source import HuggingFaceSourcePin
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import GraphNode


PROJECTION = "security-graph-counts/v1"
NODE_TYPES = (
    "source", "cve", "cwe", "repository", "commit", "language", "code_unit",
    "precondition", "action", "effect", "mitigation",
)
FEATURES = tuple("node_" + name for name in NODE_TYPES) + (
    "code_unit_vulnerable", "code_unit_fixed",
)
_HEX = re.compile(r"[0-9a-f]{64}")
_PART = re.compile(r"data/graph/nodes/part-[0-9]{6}\.parquet")
_COLUMNS = (
    "node_cid", "node_type", "entry_cid", "label", "properties_json", "schema_version",
)


class CVETrainingSourceError(ValueError):
    """A pinned source or its bounded projection cannot be verified."""


def _family(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CVETrainingSourceError("repository family must be canonical text")
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise CVETrainingSourceError("repository family must be a public repository URL")
    path = parsed.path.casefold().rstrip("/").removesuffix(".git")
    if not path or "%" in path or "\\" in path or any(x in {".", ".."} for x in path.split("/")):
        raise CVETrainingSourceError("repository family path is not canonical")
    return parsed.hostname.casefold() + path


@dataclass(frozen=True)
class BenchmarkExclusions:
    """Explicit benchmark inputs; callers obtain these from permitted sources."""

    source_families: tuple[str, ...]
    file_names: tuple[str, ...]
    code_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        families = {_family(x) for x in self.source_families}
        # The qualification benchmark uses Bottle; exclude its whole family.
        families.add("github.com/bottlepy/bottle")
        if not self.file_names or not self.code_sha256:
            raise CVETrainingSourceError("benchmark filenames and code hashes must be supplied")
        names = set()
        for name in self.file_names:
            if (not isinstance(name, str) or not name or name != PurePosixPath(name).name
                    or "\\" in name or "\x00" in name or name in {".", ".."}):
                raise CVETrainingSourceError("benchmark filenames must be basenames")
            names.add(name.casefold())
        if any(not isinstance(x, str) or not _HEX.fullmatch(x) for x in self.code_sha256):
            raise CVETrainingSourceError("benchmark code hashes must be SHA-256")
        object.__setattr__(self, "source_families", tuple(sorted(families)))
        object.__setattr__(self, "file_names", tuple(sorted(names)))
        object.__setattr__(self, "code_sha256", tuple(sorted(set(self.code_sha256))))

    def excludes_family(self, value: str) -> bool:
        family = _family(value)
        return family in self.source_families or family.rsplit("/", 1)[-1] == "bottle"


def _read_graph_shard(root: Path, descriptor: Any, *, max_bytes: int,
                      max_rows: int) -> tuple[GraphNode, ...]:
    """Verify native file identity before bounded canonical graph decoding."""
    import pyarrow.parquet as pq

    if not _PART.fullmatch(descriptor.path) or descriptor.config_name != "graph_nodes":
        raise CVETrainingSourceError("only public derived graph-node shards are allowed")
    if descriptor.row_count > max_rows:
        raise CVETrainingSourceError("graph row bound exceeded")
    path = native._verify_file(root, descriptor, maximum=max_bytes)
    # Decode the same bytes we verify, so replacement during parsing cannot rebind
    # a receipt to different data. Original-data files are never opened.
    payload = native._bounded_bytes(path, max_bytes, "graph shard")
    if hashlib.sha256(payload).hexdigest() != descriptor.sha256:
        raise CVETrainingSourceError("graph shard changed after verification")
    import pyarrow as pa
    parquet = pq.ParquetFile(pa.BufferReader(payload))
    if parquet.metadata.num_rows != descriptor.row_count:
        raise CVETrainingSourceError("graph descriptor row count differs")
    if sum(parquet.metadata.row_group(i).total_byte_size
           for i in range(parquet.metadata.num_row_groups)) > 32 * 1024 * 1024:
        raise CVETrainingSourceError("decoded graph shard byte bound exceeded")
    table = parquet.read()
    if tuple(table.schema.names) != _COLUMNS or (
        table.schema.metadata or {}
    ).get(b"schema_version") != CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION.encode("ascii"):
        raise CVETrainingSourceError("graph shard schema differs")
    nodes = []
    for row in table.to_pylist():
        node = GraphNode.from_json(row["properties_json"])
        if (node.cid != row["node_cid"] or node.node_type != row["node_type"]
                or row["label"] != _node_label(node)
                or row["schema_version"] != CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION
                or node.node_type not in NODE_TYPES
                or node.payload.get("grants_execution_authority") is not False
                or node.payload.get("retrieval_only") is not True):
            raise CVETrainingSourceError("graph canonical identity or authority differs")
        nodes.append(node)
    if len({node.cid for node in nodes}) != len(nodes):
        raise CVETrainingSourceError("duplicate canonical graph node")
    return tuple(nodes)


def _project_observations(nodes: Iterable[GraphNode], *, admitted_source_cids: set[str],
                          exclusions: BenchmarkExclusions) -> list[dict[str, Any]]:
    """Join only present graph evidence; missing evidence never implies absence."""
    nodes = tuple(nodes)
    families: dict[str, set[str]] = defaultdict(set)
    per_source: dict[str, list[GraphNode]] = defaultdict(list)
    if sum(len(node.source_cids) for node in nodes) > 250_000:
        raise CVETrainingSourceError("graph provenance membership bound exceeded")
    for node in nodes:
        if not node.source_cids or not set(node.source_cids) <= admitted_source_cids:
            raise CVETrainingSourceError("graph references an unverified or rejected upstream source CID")
        for cid in node.source_cids:
            per_source[cid].append(node)
            if node.node_type == "repository":
                families[cid].add(_family(node.payload.get("repository")))
    observations = []
    for source_cid, evidence in sorted(per_source.items()):
        units = [x for x in evidence if x.node_type == "code_unit"]
        if not units:
            continue
        counts = {key: 0 for key in FEATURES}
        reasons = {"canonical_security_ir_records_absent", "code_body_hash_provenance_absent"}
        source_families = sorted(families[source_cid])
        if len(source_families) != 1:
            reasons.add("repository_provenance_missing_or_ambiguous")
        if any(exclusions.excludes_family(x) for x in source_families):
            reasons.add("benchmark_repository_family_excluded")
        paths = []
        for node in evidence:
            counts["node_" + node.node_type] += 1
            if node.node_type == "code_unit":
                path = node.payload.get("path")
                if not isinstance(path, str) or not path or "\x00" in path:
                    reasons.add("code_path_provenance_absent")
                else:
                    paths.append(path)
                    if PurePosixPath(path.replace("\\", "/")).name.casefold() in exclusions.file_names:
                        reasons.add("benchmark_filename_excluded")
                polarity = node.payload.get("polarity")
                if polarity in {"vulnerable", "fixed"}:
                    counts["code_unit_" + polarity] += 1
                # A future graph extension is still not a canonical CodeUnit
                # proof. Check any reported hash for overlap, never use it to
                # waive the missing canonical-record requirement.
                reported_hash = node.payload.get("body_sha256")
                if reported_hash in exclusions.code_sha256:
                    reasons.add("benchmark_code_hash_excluded")
        observations.append({
            "row_id": source_cid, "source_cid": source_cid,
            "source_families": source_families, "source_paths": sorted(set(paths)),
            "projection_family": PROJECTION, "feature_counts": counts,
            "node_cids": sorted(x.cid for x in evidence),
            "training_admitted": False, "reason_codes": sorted(reasons),
            "authority": "candidate", "grants_execution_authority": False,
        })
    return observations


def load_bounded_cve_graph_source(*, metadata_root: Path, data_root: Path,
                                 pin: HuggingFaceSourcePin,
                                 graph_shards: tuple[str, ...],
                                 exclusions: BenchmarkExclusions,
                                 max_total_bytes: int = 4 * 1024 * 1024,
                                 max_total_rows: int = 8192) -> dict[str, Any]:
    """Return verified partial observations and explicit training quarantine.

    Local files only. The complete native control-plane check validates all
    routing indexes; only the explicitly selected graph data shards are read.
    The upstream routing index verifies CID membership, not raw row preimages.
    """
    if not isinstance(exclusions, BenchmarkExclusions):
        raise CVETrainingSourceError("explicit benchmark exclusions are required")
    if (not graph_shards or len(graph_shards) != len(set(graph_shards))
            or any(not isinstance(x, str) or not _PART.fullmatch(x) for x in graph_shards)):
        raise CVETrainingSourceError("select unique public derived graph-node shards")
    if (type(max_total_bytes) is not int or not 0 < max_total_bytes <= 16 * 1024 * 1024
            or type(max_total_rows) is not int or not 0 < max_total_rows <= 32768):
        raise CVETrainingSourceError("invalid bounded source limits")
    loaded = native.load_huggingface_complete_release(metadata_root, pin, offline=True)
    metadata_root = Path(metadata_root).resolve(strict=True)
    data_root = Path(data_root)
    if data_root.is_symlink() or not data_root.is_dir():
        raise CVETrainingSourceError("data root must be a real directory")
    data_root = data_root.resolve(strict=True)
    manifest_bytes = native._bounded_bytes(native._safe_file(metadata_root, "manifest.json"),
                                           8 * 1024 * 1024, "manifest.json")
    if hashlib.sha256(manifest_bytes).hexdigest() != pin.manifest_sha256:
        raise CVETrainingSourceError("manifest changed after native verification")
    manifest = native._strict_json_object(manifest_bytes, "manifest.json")
    descriptors = {item["path"]: native._ArtifactDescriptor.from_dict(item)
                   for item in manifest["artifacts"]}
    if any(path not in descriptors for path in graph_shards):
        raise CVETrainingSourceError("selected graph shard is absent from pinned manifest")
    selected = [descriptors[path] for path in graph_shards]
    if (sum(x.byte_length for x in selected) > max_total_bytes
            or sum(x.row_count for x in selected) > max_total_rows):
        raise CVETrainingSourceError("selected graph shards exceed aggregate limits")
    limits = native.HuggingFaceCompleteReleaseLimits()
    index = native._read_index_table(metadata_root, descriptors["indexes/original_rows.parquet"],
                                    limits=limits)
    sources = {row["security_ir_source_cid"] for row in index.to_pylist()
               if row["source_status"] == "admitted"}
    nodes = tuple(node for descriptor in selected for node in _read_graph_shard(
        data_root, descriptor, max_bytes=max_total_bytes, max_rows=max_total_rows))
    if len({node.cid for node in nodes}) != len(nodes):
        raise CVETrainingSourceError("duplicate canonical node across selected shards")
    observations = _project_observations(nodes, admitted_source_cids=sources, exclusions=exclusions)
    reason_counts = Counter(reason for row in observations for reason in row["reason_codes"])
    return {
        "schema": "bounded-cve-training-source/v1", "status": "verified_graph_quarantined",
        "pin": pin.to_dict(), "native_control_receipt": asdict(loaded.receipt),
        "selected_artifacts": [{"path": d.path, "sha256": d.sha256,
            "content_id": d.content_id, "byte_length": d.byte_length, "row_count": d.row_count}
            for d in selected],
        "projection_family": PROJECTION, "feature_vocabulary": list(FEATURES),
        "benchmark_exclusions": asdict(exclusions), "observations": observations,
        "graph_node_count": len(nodes), "observed_source_count": len(observations),
        "quarantine_reason_counts": dict(sorted(reason_counts.items())),
        "training_rows": [], "training_row_count": 0, "training_performed": False,
        "source_cid_routing_verified": True, "raw_source_cid_preimages_verified": False,
        "canonical_graph_records_verified": True, "canonical_security_ir_records_loaded": False,
        "code_hash_disjointness_verified": False, "partial_graph_projection": True,
        "entry_cid_cross_table_links_verified": False, "native_cve_adapter_invoked": False,
        "required_training_export": ["canonical SourceRecord", "canonical PolicyCandidate",
            "canonical CodeUnit with repository, path, and body_sha256"],
        "raw_originals_loaded": False, "provider_calls": 0,
        "proof_authoritative": False, "grants_execution_authority": False,
    }
