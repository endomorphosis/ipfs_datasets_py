"""Bounded snapshot evidence and closed metadata-DAG admission.

Admission checks reference structure and exact population identity. It does
not verify source blob bytes; project_chunked_repository must still rehash
those immutable Git objects before their contents can be positively used.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
from types import MappingProxyType
from typing import Any

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid,
)
from .git_decoder_profile import (
    GitBlobDecoderProfile, GitBlobDecoderBudget, DEFAULT_DECODER_PROFILE,
    DEFAULT_DECODER_BUDGET, EXPLICIT_DECODER_ADDRESS_BYTES, admit_decoder_profile,
)
from .chunked_snapshot import (
    BlobChunk, ChunkedBlob, ChunkedRepositorySnapshot, ChunkedSnapshotLimits,
    GIT_DECODER_CONFIG, MAX_FRAME_BYTES,
)
from .committed_snapshot import CommittedPopulationEntry, preflight_committed_repository
from .snapshot import RepositorySnapshot, SNAPSHOT_SCHEMA, SnapshotError, _git_oid

PAGED_SNAPSHOT_SCHEMA = "ipfs-datasets.paged-repository-snapshot@1"
SNAPSHOT_PAGE_SCHEMA = "ipfs-datasets.snapshot-entry-page@1"
SNAPSHOT_HEADER_FIELDS = {"schema", "repository_id", "mode", "max_file_bytes", "max_entries",
                          "git_tree", "git_commit", "exclusions"}


def _closed(value, fields, schema=None):
    if type(value) is not dict or set(value) != set(fields):
        raise SnapshotError("metadata record has unknown or missing fields")
    if schema is not None and value.get("schema") != schema:
        raise SnapshotError("unsupported metadata schema")
    return value


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise SnapshotError(name + " must be a bounded integer")
    return value


def _cid(value, codec="dag-json"):
    try:
        if type(value) is not str or len(value) > 128:
            raise ValueError("reference exceeds the fixed CID profile bound")
        return validate_cid(value, codecs={codec})
    except Exception as exc:
        raise SnapshotError("invalid metadata content reference") from exc


def _oid(value, width):
    try:
        if type(value) is not str or len(value) != width or not _git_oid(value, "object"):
            raise ValueError("object id width")
    except (ValueError, TypeError) as exc:
        raise SnapshotError("invalid committed object reference") from exc
    return value


def _ordered(values, name):
    if any(left >= right for left, right in zip(values, values[1:])):
        raise SnapshotError(name + " are duplicated or reordered")


class _Graph:
    def __init__(self, blocks, max_metadata_bytes, max_blocks):
        _integer(max_metadata_bytes, "max_metadata_bytes", 1)
        _integer(max_blocks, "max_blocks", 1)
        if not isinstance(blocks, Mapping):
            raise SnapshotError("manifest blocks must be a CID-to-bytes mapping")
        total, checked = 0, {}
        for count, (cid, raw) in enumerate(blocks.items(), 1):
            if count > max_blocks:
                raise SnapshotError("manifest block count exceeds population bounds")
            _cid(cid)
            if type(raw) is not bytes or not raw or len(raw) > MAX_FRAME_BYTES:
                raise SnapshotError("manifest block exceeds the fixed frame/type bounds")
            total += len(raw)
            if total > max_metadata_bytes:
                raise SnapshotError("manifest blocks exceed metadata budget")
            checked[cid] = raw
        self.blocks, self.seen, self.total = checked, set(), total

    def read(self, cid):
        _cid(cid)
        if cid not in self.blocks:
            raise SnapshotError("manifest reference is missing")
        raw = self.blocks[cid]
        try:
            payload = json.loads(raw)
            if canonical_dag_json_bytes(payload) != raw or cid_for_structured(payload) != cid:
                raise ValueError("noncanonical or substituted block")
        except Exception as exc:
            raise SnapshotError("manifest block CID or canonical bytes do not verify") from exc
        self.seen.add(cid)
        return payload

    def refs(self, refs):
        if type(refs) is not list or any(type(ref) is not str for ref in refs) or len(set(refs)) != len(refs):
            raise SnapshotError("manifest page references are malformed or duplicated")
        return refs

    def finish(self, expected):
        if self.seen != set(self.blocks):
            raise SnapshotError("manifest contains unreachable or omitted metadata blocks")
        if set(expected) != set(self.blocks) or any(self.blocks[cid] != raw for cid, raw in expected.items()):
            raise SnapshotError("manifest paging is not canonical")


def parse_chunked_snapshot_manifest(
    expected_snapshot_cid: str, blocks: Mapping[str, bytes], *, repository_id: str,
    expected_commit: str, expected_tree: str, expected_population_cid: str,
    limits: ChunkedSnapshotLimits = ChunkedSnapshotLimits(),
    decoder_profile: GitBlobDecoderProfile = DEFAULT_DECODER_PROFILE,
    decoder_budget: GitBlobDecoderBudget = DEFAULT_DECODER_BUDGET,
) -> ChunkedRepositorySnapshot:
    """Admit a closed reference DAG; no contained source-hash claim is verified."""
    if not isinstance(limits, ChunkedSnapshotLimits):
        raise SnapshotError("manifest admission requires typed limits")
    profile = admit_decoder_profile(decoder_profile, decoder_budget)
    # At most one blob plus two index pages per entry, and one root.
    graph = _Graph(blocks, limits.max_metadata_bytes, 3 * limits.max_entries + 1)
    payload = graph.read(expected_snapshot_cid)
    schema = payload.get("schema") if type(payload) is dict else None
    if schema not in {"ipfs-datasets.git-chunked-snapshot@1", "ipfs-datasets.git-chunked-snapshot@2"}:
        raise SnapshotError("unsupported Git decoder manifest schema")
    fields = {"schema", "repository_id", "git_commit", "git_tree", "population_cid", "scope",
              "entry_pages", "blob_pages", "entry_count", "unique_blob_count", "limits",
              "git_decoder_address_bytes", "git_decoder_config"}
    if schema.endswith("@2"):
        fields.add("git_decoder_profile")
    root = _closed(payload, fields, schema)
    if schema.endswith("@1"):
        if profile != DEFAULT_DECODER_PROFILE:
            raise SnapshotError("Git decoder profile differs from immutable v1 request")
    elif (profile.address_space_bytes != EXPLICIT_DECODER_ADDRESS_BYTES
          or canonical_dag_json_bytes(root["git_decoder_profile"]) != canonical_dag_json_bytes(profile.payload())):
        raise SnapshotError("Git decoder profile differs from immutable v2 request")
    if (root["repository_id"], root["git_commit"], root["git_tree"], root["population_cid"], root["scope"]) != (
            repository_id, expected_commit, expected_tree, expected_population_cid, "complete-committed"):
        raise SnapshotError("manifest differs from requested committed population")
    if type(expected_commit) is not str or len(expected_commit) not in {40, 64}:
        raise SnapshotError("invalid requested commit")
    width = len(expected_commit)
    _oid(expected_commit, width)
    _oid(expected_tree, width)
    _cid(expected_population_cid)
    try:
        declared = ChunkedSnapshotLimits(**_closed(root["limits"], asdict(limits)))
    except TypeError as exc:
        raise SnapshotError("invalid declared manifest limits") from exc
    if any(getattr(declared, name) > value for name, value in asdict(limits).items()):
        raise SnapshotError("manifest exceeds qualified admission limits")
    if (type(root["git_decoder_address_bytes"]) is not int
            or root["git_decoder_address_bytes"] != profile.address_space_bytes
            or root["git_decoder_config"] != dict(GIT_DECODER_CONFIG)):
        raise SnapshotError("manifest changes fixed Git decoder bounds")
    if graph.total > declared.max_metadata_bytes:
        raise SnapshotError("manifest exceeds its declared metadata budget")

    def records(refs, kind):
        values = []
        for ref in graph.refs(refs):
            page = _closed(graph.read(ref), {"schema", "kind", "records"},
                           "ipfs-datasets.git-chunk-index-page@1")
            if page["kind"] != kind or type(page["records"]) is not list or not page["records"]:
                raise SnapshotError("invalid manifest index page")
            values.extend(page["records"])
            if len(values) > declared.max_entries:
                raise SnapshotError("manifest index exceeds entry budget")
        return values

    entries = []
    for item in records(root["entry_pages"], "entries"):
        item = _closed(item, {"raw_path_hex", "git_mode", "object_type", "git_object_oid", "size_bytes"})
        raw = item["raw_path_hex"]
        try:
            if type(raw) is not str or not raw or bytes.fromhex(raw).hex() != raw:
                raise ValueError("noncanonical raw path")
        except ValueError as exc:
            raise SnapshotError("invalid committed raw path") from exc
        mode, kind = item["git_mode"], item["object_type"]
        if type(mode) is not str or type(kind) is not str or (mode, kind) not in {("100644", "blob"), ("100755", "blob"), ("120000", "blob"), ("160000", "commit")}:
            raise SnapshotError("invalid committed population mode/type")
        _oid(item["git_object_oid"], width)
        if kind == "blob":
            _integer(item["size_bytes"], "blob size")
        elif item["size_bytes"] is not None:
            raise SnapshotError("gitlink cannot declare local blob bytes")
        entries.append(CommittedPopulationEntry(**item))
    _ordered([entry.raw_path_hex for entry in entries], "population entries")
    if len(entries) != _integer(root["entry_count"], "entry_count"):
        raise SnapshotError("manifest entry count does not verify")
    population = {"schema": "ipfs-datasets.complete-committed-population@1", "repository_id": repository_id,
                  "commit": expected_commit, "tree": expected_tree, "scope": "complete-committed",
                  "exclusions": [], "entries": [entry.to_dict() for entry in entries]}
    if cid_for_structured(population) != expected_population_cid:
        raise SnapshotError("manifest population CID does not verify")
    sizes = {}
    for entry in entries:
        if entry.object_type == "blob":
            if entry.git_object_oid in sizes and sizes[entry.git_object_oid] != entry.size_bytes:
                raise SnapshotError("population has contradictory blob sizes")
            sizes[entry.git_object_oid] = entry.size_bytes
    if sum(sizes.values()) > declared.max_stream_bytes:
        raise SnapshotError("manifest exceeds streaming work budget")
    blobs, chunk_count = [], 0
    index = records(root["blob_pages"], "blobs")
    for item in index:
        item = _closed(item, {"git_object_oid", "manifest_cid"})
        oid = _oid(item["git_object_oid"], width)
        payload = _closed(graph.read(item["manifest_cid"]), {
            "schema", "git_object_oid", "size_bytes", "source_cid", "chunks"}, "ipfs-datasets.git-blob-chunks@1")
        if oid not in sizes or (payload["git_object_oid"], payload["size_bytes"]) != (oid, sizes[oid]):
            raise SnapshotError("blob manifest differs from committed inventory")
        _cid(payload["source_cid"], "raw")
        if type(payload["chunks"]) is not list:
            raise SnapshotError("invalid blob chunk records")
        chunks, offset = [], 0
        for item in payload["chunks"]:
            item = _closed(item, {"offset", "size_bytes", "source_cid"})
            _integer(item["offset"], "chunk offset")
            size = _integer(item["size_bytes"], "chunk size", 1)
            if item["offset"] != offset or size != min(declared.frame_bytes, sizes[oid] - offset):
                raise SnapshotError("blob chunks are omitted, duplicated or reordered")
            _cid(item["source_cid"], "raw")
            chunks.append(BlobChunk(**item))
            offset += size
            chunk_count += 1
            if chunk_count > declared.max_chunks:
                raise SnapshotError("manifest exceeds chunk count budget")
        if offset != sizes[oid] or (not offset and payload["source_cid"] != cid_for_bytes(b"")):
            raise SnapshotError("blob chunks do not cover the recorded blob")
        blobs.append(ChunkedBlob(oid, sizes[oid], payload["source_cid"], tuple(chunks)))
    _ordered([blob.git_object_oid for blob in blobs], "blob index entries")
    if set(sizes) != {blob.git_object_oid for blob in blobs} or len(blobs) != _integer(root["unique_blob_count"], "blob_count"):
        raise SnapshotError("blob index population or count does not verify")
    result = ChunkedRepositorySnapshot(repository_id, expected_commit, expected_tree, expected_population_cid,
                                       tuple(entries), tuple(blobs), declared, profile)
    cid, canonical = result.manifest_blocks()
    if cid != expected_snapshot_cid:
        raise SnapshotError("chunked manifest root is not canonical")
    graph.finish(canonical)
    return result


def admit_chunked_snapshot_manifest(
    repository, expected_snapshot_cid: str, blocks: Mapping[str, bytes], *, repository_id: str,
    expected_commit: str, expected_tree: str, limits: ChunkedSnapshotLimits = ChunkedSnapshotLimits(),
    decoder_profile: GitBlobDecoderProfile = DEFAULT_DECODER_PROFILE,
    decoder_budget: GitBlobDecoderBudget = DEFAULT_DECODER_BUDGET,
) -> ChunkedRepositorySnapshot:
    """Bind closed manifest metadata to the current exact Git population.

    This is metadata admission only. Full content projection is still required.
    """
    if not isinstance(limits, ChunkedSnapshotLimits):
        raise SnapshotError("manifest admission requires typed limits")
    admit_decoder_profile(decoder_profile, decoder_budget)
    plan = preflight_committed_repository(repository, repository_id=repository_id,
                                         expected_commit=expected_commit, expected_tree=expected_tree,
                                         max_entries=limits.max_entries, max_metadata_bytes=limits.max_metadata_bytes)
    result = parse_chunked_snapshot_manifest(expected_snapshot_cid, blocks, repository_id=repository_id,
                                             expected_commit=expected_commit, expected_tree=expected_tree,
                                             expected_population_cid=plan.population_cid, limits=limits,
                                             decoder_profile=decoder_profile, decoder_budget=decoder_budget)
    if result.entries != plan.entries:
        raise SnapshotError("admitted manifest substitutes committed population entries")
    return result


@dataclass(frozen=True)
class PagedSnapshotEvidence:
    root_cid: str
    snapshot_cid: str
    source_manifest_cid: str
    repository_id: str
    git_commit: str
    git_tree: str
    entry_count: int
    blocks: Mapping[str, bytes]

    def artifact(self):
        from .models import ArtifactRecord
        return ArtifactRecord("artifact:snapshot-evidence", "snapshot-evidence", "@snapshot-evidence",
                              self.snapshot_cid, "exact", {
                                  "snapshot": {"schema": "ipfs-datasets.paged-snapshot-reference@1",
                                               "snapshot_cid": self.snapshot_cid, "paged_snapshot_cid": self.root_cid,
                                               "repository_id": self.repository_id, "git_commit": self.git_commit,
                                               "git_tree": self.git_tree, "entry_count": self.entry_count},
                                  "source_manifest_cid": self.source_manifest_cid,
                                  "acquisition": "git-clean", "exclusions": []})


def page_snapshot_evidence(
    snapshot: RepositorySnapshot, source_manifest_cid: str, *, page_bytes: int = MAX_FRAME_BYTES,
    max_metadata_bytes: int = 32 * 1024 * 1024,
) -> PagedSnapshotEvidence:
    """Page existing snapshot metadata without changing its identity/schema."""
    if not isinstance(snapshot, RepositorySnapshot) or snapshot.mode != "git-clean" or snapshot.exclusions:
        raise SnapshotError("paged evidence requires explicit committed snapshot scope")
    _cid(source_manifest_cid)
    if not 512 <= _integer(page_bytes, "page_bytes", 1) <= MAX_FRAME_BYTES:
        raise SnapshotError("invalid snapshot metadata frame bound")
    _integer(max_metadata_bytes, "max_metadata_bytes", 1)
    blocks, refs, page, page_start, total, estimate = {}, [], [], 0, 0, 256

    def put(payload):
        nonlocal total
        raw = canonical_dag_json_bytes(payload)
        if len(raw) > page_bytes:
            raise SnapshotError("snapshot metadata exceeds frame bound")
        cid = cid_for_structured(payload)
        if cid not in blocks:
            total += len(raw)
            if total > max_metadata_bytes:
                raise SnapshotError("snapshot metadata exceeds aggregate budget")
            blocks[cid] = raw
        return cid

    for ordinal, entry in enumerate(snapshot.entries):
        record = entry.to_dict()
        extent = len(canonical_dag_json_bytes(record)) + 1
        if page and estimate + extent > page_bytes:
            refs.append(put({"schema": SNAPSHOT_PAGE_SCHEMA, "first_ordinal": page_start, "records": page}))
            page, page_start, estimate = [], ordinal, 256
        page.append(record)
        estimate += extent
    if page:
        refs.append(put({"schema": SNAPSHOT_PAGE_SCHEMA, "first_ordinal": page_start, "records": page}))
    header = {"schema": SNAPSHOT_SCHEMA, "repository_id": snapshot.repository_id, "mode": snapshot.mode,
              "max_file_bytes": snapshot.max_file_bytes, "max_entries": snapshot.max_entries,
              "git_tree": snapshot.git_tree, "git_commit": snapshot.git_commit, "exclusions": []}
    snapshot_cid = snapshot.snapshot_cid
    root = put({"schema": PAGED_SNAPSHOT_SCHEMA, "snapshot_header": header, "snapshot_cid": snapshot_cid,
                "source_manifest_cid": source_manifest_cid, "entry_pages": refs, "entry_count": len(snapshot.entries),
                "page_bytes": page_bytes, "max_metadata_bytes": max_metadata_bytes})
    return PagedSnapshotEvidence(root, snapshot_cid, source_manifest_cid, snapshot.repository_id,
                                 snapshot.git_commit, snapshot.git_tree, len(snapshot.entries), MappingProxyType(blocks))


def parse_paged_snapshot_evidence(
    expected_root_cid: str, blocks: Mapping[str, bytes], *, expected_snapshot_cid: str,
    expected_source_manifest_cid: str, repository_id: str, expected_commit: str, expected_tree: str,
    max_entries: int = 20000, max_metadata_bytes: int = 32 * 1024 * 1024,
) -> tuple[RepositorySnapshot, PagedSnapshotEvidence]:
    """Check every metadata page and reconstruct the exact legacy snapshot CID.

    Returned entries contain no captured bytes and remain reference claims.
    """
    _integer(max_entries, "max_entries", 1)
    graph = _Graph(blocks, max_metadata_bytes, max_entries + 1)
    root = _closed(graph.read(expected_root_cid), {"schema", "snapshot_header", "snapshot_cid", "source_manifest_cid",
                                                  "entry_pages", "entry_count", "page_bytes", "max_metadata_bytes"},
                   PAGED_SNAPSHOT_SCHEMA)
    header = _closed(root["snapshot_header"], SNAPSHOT_HEADER_FIELDS, SNAPSHOT_SCHEMA)
    if _integer(header["max_entries"], "snapshot max_entries", 1) > max_entries:
        raise SnapshotError("paged snapshot exceeds qualified entry bound")
    if (header["repository_id"], header["git_commit"], header["git_tree"], header["mode"], header["exclusions"],
            root["snapshot_cid"], root["source_manifest_cid"]) != (
            repository_id, expected_commit, expected_tree, "git-clean", [], expected_snapshot_cid, expected_source_manifest_cid):
        raise SnapshotError("paged snapshot differs from expected committed snapshot")
    page_bytes = _integer(root["page_bytes"], "page_bytes", 1)
    declared_metadata = _integer(root["max_metadata_bytes"], "max_metadata_bytes", 1)
    if page_bytes > MAX_FRAME_BYTES or declared_metadata > max_metadata_bytes or graph.total > declared_metadata:
        raise SnapshotError("paged snapshot exceeds qualified metadata bounds")
    if any(len(raw) > page_bytes for raw in graph.blocks.values()):
        raise SnapshotError("paged snapshot block exceeds declared frame bound")
    entries = []
    for ref in graph.refs(root["entry_pages"]):
        page = _closed(graph.read(ref), {"schema", "first_ordinal", "records"}, SNAPSHOT_PAGE_SCHEMA)
        if _integer(page["first_ordinal"], "page ordinal") != len(entries):
            raise SnapshotError("snapshot pages are omitted, duplicated or reordered")
        if type(page["records"]) is not list or not page["records"]:
            raise SnapshotError("invalid snapshot entry page")
        entries.extend(page["records"])
        if len(entries) > max_entries:
            raise SnapshotError("paged snapshot exceeds entry budget")
    if len(entries) != _integer(root["entry_count"], "entry_count"):
        raise SnapshotError("paged snapshot entry count does not verify")
    try:
        _ordered([entry["raw_path_hex"] for entry in entries], "snapshot entries")
        snapshot = RepositorySnapshot.from_dict({**header, "entries": entries, "snapshot_cid": expected_snapshot_cid})
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotError("paged snapshot entries or snapshot CID do not verify") from exc
    evidence = page_snapshot_evidence(snapshot, expected_source_manifest_cid,
                                      page_bytes=page_bytes, max_metadata_bytes=declared_metadata)
    if evidence.root_cid != expected_root_cid:
        raise SnapshotError("paged snapshot root is not canonical")
    graph.finish(evidence.blocks)
    return snapshot, evidence


__all__ = ["PagedSnapshotEvidence", "page_snapshot_evidence", "parse_paged_snapshot_evidence",
           "parse_chunked_snapshot_manifest", "admit_chunked_snapshot_manifest"]
