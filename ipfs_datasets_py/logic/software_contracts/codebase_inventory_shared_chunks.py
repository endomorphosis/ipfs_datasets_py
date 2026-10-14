"""Inert records for shared-manifest, streamed numerical scan chunks.

These records describe advisory saved values. Validation proves byte identity,
closed shapes and deterministic row accounting, not that a process executed,
that a checkout is current, or that a proof was discharged. Native receiving
must independently replay source/model bindings and its closing observations.
The existing single-request and full-target chunk records keep their original
interpretation. Shared transport accounting is an inert claim until a native
receiver independently reconstructs the shared envelope and every source row.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json

from . import codebase_inventory_resume as resume
from .content import cid_for_bytes, cid_for_structured

CHUNK_SCHEMA = "codebase-inventory-resume-numerical-chunk@2"
PAGE_SCHEMA = "codebase-inventory-resume-page@3"
CURSOR_SCHEMA = "codebase-inventory-resume-cursor@3"
COMPLETION_SCHEMA = "codebase-inventory-resume-completion@3"
REFS_SCHEMA = "codebase-resume-completion-advisory@3"
PROFILE = "shared512-streamed-native-projection-feature-inference@1"
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_SHARED_BYTES = 16 * 1024 * 1024
MAX_TARGET_BYTES = 4 * 1024 * 1024
MAX_FEATURE_CELLS = 262144

CodebaseScanChunkError = resume.CodebaseScanResumeError
_require = resume._require
_closed = resume._closed
_int = resume._int
_cid = resume._cid
_sha = resume._sha
_wire = resume._wire
_FALSE = resume._FALSE
_ENTRY_FIELDS = (resume._ENTRY_FIELDS - {"inference_index"}) | {"chunk_ordinal", "row_index"}
_CHUNK_DESCRIPTOR_FIELDS = {"chunk_cid", "bytes", "sha256", "chunk_ordinal", "member_indices",
                            "target_sha256s", "source_digests", "rows", "projection_records"}
_PAGE_DESCRIPTOR_FIELDS = {"page_cid", "bytes", "sha256", "start", "end", "membership_cid",
                           "inferred_rows", "projection_records", "chunks", "dispositions"}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate chunk record JSON key")
        result[key] = value
    return result


def _constant(value):
    raise CodebaseScanChunkError("nonfinite chunk record JSON constant: " + value)


def _read_payload(artifact_cid, payload, shape):
    _require(type(payload) is bytes and 0 < len(payload) <= MAX_ARTIFACT_BYTES,
             "independently bounded immutable chunk-profile artifact required")
    _cid(artifact_cid, "raw")
    try:
        value = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant)
        _require(_wire(value) == payload and cid_for_bytes(payload) == artifact_cid,
                 "canonical finite JSON/raw artifact identity differs")
        shape(value)
    except CodebaseScanChunkError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as exc:
        raise CodebaseScanChunkError("malformed inert chunk-profile artifact") from exc
    return value


def _profile(value, schema):
    _require(value["schema"] == schema and value["profile"] == PROFILE,
             "explicit chunk-profile schema differs")


def _identities(value):
    for key in ("root_cid", "head_cid", "membership_cid"):
        _cid(value[key])
    _cid(value["model_artifact_cid"], "raw")


def _page_bounds(start, end, total=None):
    _int(start, 1023)
    _int(end, 1024, 1)
    _require(start < end and end - start <= 64, "bounded contiguous page required")
    if total is not None:
        _int(total, 1024, 1)
        _require(end <= total, "page exceeds complete inventory")


def _coverage(value, entries=None, *, pages=None):
    fields = {"inventory_entries", "inferred_rows", "projection_records", "chunks", "dispositions"}
    if pages is not None:
        fields.add("pages")
    _closed(value, fields, "chunk aggregate coverage")
    base = {key: value[key] for key in ("inventory_entries", "inferred_rows", "dispositions")}
    resume._coverage_shape(base, entries)
    _int(value["projection_records"], 2048)
    _int(value["chunks"], 1024)
    _require((value["inferred_rows"] == 0) == (value["chunks"] == 0)
             and value["chunks"] <= value["inferred_rows"]
             and value["inferred_rows"] <= value["projection_records"] <= 2 * value["inferred_rows"],
             "chunk/row/projection conservation differs")
    if entries is not None:
        _require(value["projection_records"] == sum(len(row["coverage"]) for row in entries
                                                      if row["disposition"] == "inferred"),
                 "entry projection count differs")
    if pages is not None:
        _int(value["pages"], 1024)
        _require(value["pages"] == pages, "chunk completion page count differs")


def _entry_shape(row):
    _closed(row, _ENTRY_FIELDS, "chunked page entry")
    inferred = row["disposition"] == "inferred"
    _require(inferred == (row["chunk_ordinal"] is not None)
             and inferred == (row["row_index"] is not None), "explicit chunk/row mapping differs")
    if inferred:
        _int(row["chunk_ordinal"], 63)
        _int(row["row_index"], 63)
    legacy = {key: value for key, value in row.items() if key not in {"chunk_ordinal", "row_index"}}
    legacy["inference_index"] = row["row_index"]
    resume._entry_shape(legacy)


def _worker_counters(value, rows, optimized):
    native_replays = (1 if optimized else 2) * rows
    expected = {"shared_inventory_validations": 1, "shared_manifest_parses": 1,
        "shared_receipt_parses": 1, "shared_replay_preparations": 1 if optimized else 0,
        "target_restorations": rows, "native_target_replays": native_replays,
        "native_lowering_replays": native_replays, "full_target_comparisons": native_replays,
        "streamed_feature_rows": rows, "matrix_builds": 1, "vocabulary_builds": 1,
        "weight_tensor_builds": 4, "input_tensor_builds": 1,
        "contract_validations": 1 if optimized else 2,
        "state_validations": 1 if optimized else 2, "rows": rows, "training_calls": 0,
        "max_retained_restored_targets": 1, "gc_collections": 0 if optimized else rows}
    _closed(value, expected, "shared chunk worker counters")
    _require(all(type(number) is int for number in value.values()) and value == expected,
             "streamed shared-request worker counters differ")


def _transport_shape(value, rows, receipt):
    _closed(value, {"shared", "compact_targets", "restored_targets", "feature_cells",
                    "maximum_restored_targets"}, "shared chunk transport accounting")
    _int(value["shared"], MAX_SHARED_BYTES, 1)
    for key in ("compact_targets", "restored_targets"):
        _int(value[key], rows * MAX_TARGET_BYTES, rows)
    _int(value["feature_cells"], MAX_FEATURE_CELLS, rows)
    _int(value["maximum_restored_targets"], 1, 1)
    _require(value["shared"] + value["compact_targets"] <= receipt["input_bytes"],
             "shared and compact wire bytes exceed actual worker input")


def _worker_profile(value):
    _closed(value, {"python", "torch", "device", "dtype", "cpu_threads", "repository_code_executed",
        "registry_opened", "training_executed", "proof_authority", "decoded_formulas_generated"},
        "chunk worker profile")
    _require(all(type(value[key]) is str and 0 < len(value[key]) <= 128 for key in ("python", "torch"))
             and value["device"] == "cpu" and value["dtype"] == "float64"
             and type(value["cpu_threads"]) is int and value["cpu_threads"] == 1
             and all(value[key] is False for key in ("repository_code_executed", "registry_opened",
                "training_executed", "proof_authority", "decoded_formulas_generated")),
             "chunk worker representation/authority differs")


def _chunk_entries(value):
    indices, inference = value["member_indices"], value["inference"]
    _require(type(inference) is dict and type(inference.get("coverage")) is list,
             "nonempty actual numerical chunk required")
    coverage = inference["coverage"]
    _require(len(coverage) in {len(indices), 2 * len(indices)}, "chunk projection cardinality differs")
    width = len(coverage) // len(indices)
    return [{"disposition": "inferred", "inference_index": row,
             "source_digest": value["source_digests"][row],
             "coverage": coverage[row * width:(row + 1) * width]}
            for row in range(len(indices))]


def validate_codebase_chunk_lifecycle_receipt(value):
    """Validate inert ownership accounting; never establish actual process drain."""
    _closed(value, {"schema", "parent", "leader", "observed_descendants", "leader_reaped",
        "descendant_tracking_complete", "group_scan_complete", "remaining_group_members",
        "remaining_tracked_descendants", "readers", "stdin_writer", "workspace", "observation_errors",
        "ownership_is_sampled", "kernel_containment_attested", "cleanup_confirmed"}, "chunk lifecycle receipt")
    _require(value["schema"] == "native-owned-tool-lifecycle@1", "native lifecycle schema differs")
    _closed(value["parent"], {"pid", "birth_ticks"}, "lifecycle parent identity")
    _int(value["parent"]["pid"], 2**31 - 1, 1)
    _int(value["parent"]["birth_ticks"], 2**63 - 1, 1)

    def identity(row):
        _closed(row, {"pid", "birth_ticks", "parent_pid", "process_group_id", "session_id"},
                "lifecycle Linux process identity")
        for key in ("pid", "parent_pid", "process_group_id", "session_id"):
            _int(row[key], 2**31 - 1, 1)
        _int(row["birth_ticks"], 2**63 - 1, 1)
        return row["pid"], row["birth_ticks"]

    leader = value["leader"]
    leader_key = identity(leader)
    _require(leader["parent_pid"] == value["parent"]["pid"]
             and leader["process_group_id"] == leader["pid"] and leader["session_id"] == leader["pid"]
             and leader["pid"] != value["parent"]["pid"], "owned lifecycle leader binding differs")
    for key in ("observed_descendants", "remaining_group_members", "remaining_tracked_descendants"):
        rows = value[key]
        _require(type(rows) is list and len(rows) <= 4096, "bounded lifecycle identity list required")
        keys = [identity(row) for row in rows]
        _require(keys == sorted(set(keys)), "sorted unique lifecycle process identities required")
        if key == "observed_descendants":
            _require(leader_key not in keys and all(row["pid"] != value["parent"]["pid"] for row in rows),
                     "lifecycle descendants contain owner or leader")
    for key in ("leader_reaped", "descendant_tracking_complete", "group_scan_complete", "ownership_is_sampled",
                "cleanup_confirmed"):
        _require(value[key] is True, "successful sampled native lifecycle required")
    _require(value["kernel_containment_attested"] is False
             and value["remaining_group_members"] == [] and value["remaining_tracked_descendants"] == [],
             "chunk lifecycle drain/authority differs")
    for key in ("readers", "stdin_writer"):
        _closed(value[key], {"started", "joined"}, "lifecycle I/O accounting")
        _int(value[key]["started"], 2)
        _int(value[key]["joined"], 2)
    _require(value["readers"] == {"started": 2, "joined": 2}
             and value["stdin_writer"] in ({"started": 0, "joined": 0}, {"started": 1, "joined": 1}),
             "lifecycle I/O drain differs")
    _closed(value["workspace"], {"device", "inode", "removed"}, "lifecycle workspace identity")
    _int(value["workspace"]["device"], 2**64 - 1)
    _int(value["workspace"]["inode"], 2**64 - 1, 1)
    _require(value["workspace"]["removed"] is True and type(value["observation_errors"]) is list
             and value["observation_errors"] == [], "lifecycle workspace/observation cleanup differs")
    return value


def _chunk_shape(value):
    _closed(value, {"schema", "profile", "root_cid", "head_cid", "membership_cid",
        "model_artifact_cid", "model_state_sha256", "optimized", "page_start", "page_end",
        "chunk_ordinal", "previous_chunk_cid", "member_indices", "target_sha256s", "source_digests",
        "shared_inventory_sha256", "transport_bytes", "inference", "worker_receipt", "worker_counters",
        "worker_profile", "lifecycle_receipt", "authority"},
        "numerical chunk")
    _profile(value, CHUNK_SCHEMA)
    _identities(value)
    _sha(value["model_state_sha256"])
    _sha(value["shared_inventory_sha256"])
    _require(type(value["optimized"]) is bool, "exact chunk optimization flag required")
    _page_bounds(value["page_start"], value["page_end"])
    _int(value["chunk_ordinal"], 63)
    if value["previous_chunk_cid"] is not None:
        _cid(value["previous_chunk_cid"], "raw")
    _require((value["previous_chunk_cid"] is None) == (value["chunk_ordinal"] == 0),
             "chunk prefix identity differs")
    indices = value["member_indices"]
    _require(type(indices) is list and 1 <= len(indices) <= 64, "nonempty bounded chunk membership required")
    for index in indices:
        _int(index, value["page_end"] - 1, value["page_start"])
    _require(indices == sorted(set(indices)), "ordered unique chunk member indices required")
    for key in ("target_sha256s", "source_digests"):
        _require(type(value[key]) is list and len(value[key]) == len(indices), "complete chunk target mapping required")
        for digest in value[key]:
            _sha(digest)
    _require(len(set(value["source_digests"])) == len(indices), "duplicate numerical chunk source")
    entries = _chunk_entries(value)
    for row in entries:
        ids = []
        for coverage in row["coverage"]:
            _closed(coverage, {"projection_id", "known_atoms", "unknown_atoms"}, "chunk projection coverage")
            _require(type(coverage["projection_id"]) is str, "exact chunk projection identity required")
            _int(coverage["known_atoms"], 2**63 - 1, 1)
            _int(coverage["unknown_atoms"], 2**63 - 1)
            ids.append(coverage["projection_id"])
        _require(ids == sorted(set(ids)), "ordered unique chunk projections required")
    resume._inference_shape(value["inference"], entries)
    _require(value["inference"]["state_sha256"] == value["model_state_sha256"], "chunk state digest differs")
    resume._receipt_shape(value["worker_receipt"], value["inference"])
    _transport_shape(value["transport_bytes"], len(indices), value["worker_receipt"])
    _worker_counters(value["worker_counters"], len(indices), value["optimized"])
    _worker_profile(value["worker_profile"])
    validate_codebase_chunk_lifecycle_receipt(value["lifecycle_receipt"])
    resume._authority(value["authority"])


@dataclass(frozen=True, slots=True)
class CodebaseScanNumericalChunk:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _read_payload(self.artifact_cid, self._payload, _chunk_shape)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, _wire(value))


def chunk_descriptor(chunk):
    _require(type(chunk) is CodebaseScanNumericalChunk, "exact immutable numerical chunk required")
    value = chunk.to_dict()
    return {"chunk_cid": chunk.artifact_cid, "bytes": len(chunk._payload),
        "sha256": hashlib.sha256(chunk._payload).hexdigest(), "chunk_ordinal": value["chunk_ordinal"],
        "member_indices": value["member_indices"], "target_sha256s": value["target_sha256s"],
        "source_digests": value["source_digests"], "rows": len(value["member_indices"]),
        "projection_records": len(value["inference"]["coverage"])}


def _chunk_descriptor_shape(value):
    _closed(value, _CHUNK_DESCRIPTOR_FIELDS, "chunk descriptor")
    _cid(value["chunk_cid"], "raw")
    _int(value["bytes"], MAX_ARTIFACT_BYTES, 1)
    _sha(value["sha256"])
    _require(value["chunk_cid"] == resume._encode_cid_digest("base32", 1, "raw",
        bytes.fromhex("1220" + value["sha256"])), "chunk descriptor CID/SHA identity differs")
    _int(value["chunk_ordinal"], 63)
    _int(value["rows"], 64, 1)
    _int(value["projection_records"], 128, 1)
    indices = value["member_indices"]
    _require(type(indices) is list and len(indices) == value["rows"], "chunk descriptor row mapping differs")
    for index in indices:
        _int(index, 1023)
    _require(indices == sorted(set(indices))
             and value["projection_records"] in {value["rows"], 2 * value["rows"]},
             "chunk descriptor ordering/projection count differs")
    for key in ("target_sha256s", "source_digests"):
        _require(type(value[key]) is list and len(value[key]) == len(indices), "complete descriptor target mapping required")
        for digest in value[key]:
            _sha(digest)
    _require(len(set(value["source_digests"])) == len(indices), "duplicate chunk descriptor numerical source")


def _page_shape(value):
    _closed(value, {"schema", "profile", "root_cid", "head_cid", "membership_cid", "model_artifact_cid",
        "start", "end", "total_entries", "page_membership_cid", "previous_page_cid", "entries",
        "chunks", "coverage", "authority"}, "chunked page")
    _profile(value, PAGE_SCHEMA)
    _identities(value)
    _cid(value["page_membership_cid"])
    _page_bounds(value["start"], value["end"], value["total_entries"])
    if value["previous_page_cid"] is not None:
        _cid(value["previous_page_cid"], "raw")
    _require((value["previous_page_cid"] is None) == (value["start"] == 0), "page prefix identity differs")
    entries = value["entries"]
    _require(type(entries) is list and len(entries) == value["end"] - value["start"],
             "complete contiguous page entry ledger required")
    for row in entries:
        _entry_shape(row)
    _require([row["member_index"] for row in entries] == list(range(value["start"], value["end"]))
             and len({row["source_key"] for row in entries}) == len(entries), "page source membership/order differs")
    descriptors = value["chunks"]
    _require(type(descriptors) is list and len(descriptors) <= 64, "bounded ordered chunk descriptors required")
    mapped = []
    projections = 0
    for ordinal, descriptor in enumerate(descriptors):
        _chunk_descriptor_shape(descriptor)
        _require(descriptor["chunk_ordinal"] == ordinal, "contiguous chunk ordinal required")
        mapped.extend(descriptor["member_indices"])
        projections += descriptor["projection_records"]
    inferred = [row for row in entries if row["disposition"] == "inferred"]
    _require(mapped == [row["member_index"] for row in inferred]
             and len({row["chunk_cid"] for row in descriptors}) == len(descriptors)
             and len({row["source_digest"] for row in inferred}) == len(inferred),
             "exact one-to-one inferred chunk membership differs")
    for ordinal, descriptor in enumerate(descriptors):
        by_index = {row["member_index"]: row for row in inferred}
        for row_index, member_index in enumerate(descriptor["member_indices"]):
            row = by_index[member_index]
            _require(row["chunk_ordinal"] == ordinal and row["row_index"] == row_index
                     and row["target_sha256"] == descriptor["target_sha256s"][row_index]
                     and row["source_digest"] == descriptor["source_digests"][row_index],
                     "explicit page chunk/row mapping differs")
        _require(descriptor["projection_records"] == sum(len(by_index[index]["coverage"])
                   for index in descriptor["member_indices"]), "descriptor entry projection mapping differs")
    _coverage(value["coverage"], entries)
    _require(value["coverage"]["chunks"] == len(descriptors)
             and value["coverage"]["projection_records"] == projections, "page aggregate chunk ledger differs")
    resume._authority(value["authority"])


@dataclass(frozen=True, slots=True)
class CodebaseScanChunkedCursor:
    root_cid: str
    next_offset: int
    previous_page_cid: str

    def __post_init__(self):
        _cid(self.root_cid)
        _cid(self.previous_page_cid, "raw")
        _int(self.next_offset, 1024, 1)

    def to_dict(self):
        return {"schema": CURSOR_SCHEMA, "profile": PROFILE, "root_cid": self.root_cid,
                "next_offset": self.next_offset, "previous_page_cid": self.previous_page_cid}

    @classmethod
    def from_dict(cls, value):
        _closed(value, {"schema", "profile", "root_cid", "next_offset", "previous_page_cid"}, "chunked cursor")
        _profile(value, CURSOR_SCHEMA)
        return cls(value["root_cid"], value["next_offset"], value["previous_page_cid"])

    @classmethod
    def from_page(cls, root, page):
        """Advance only at a root-bound completed page; the final page returns None."""
        bind_codebase_scan_chunked_page_root(page, root)
        return page.next_cursor


@dataclass(frozen=True, slots=True)
class CodebaseScanChunkedPage:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _read_payload(self.artifact_cid, self._payload, _page_shape)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, _wire(value))

    @property
    def next_cursor(self):
        value = self.to_dict()
        return None if value["end"] == value["total_entries"] else CodebaseScanChunkedCursor(
            value["root_cid"], value["end"], self.artifact_cid)


def page_descriptor(page):
    _require(type(page) is CodebaseScanChunkedPage, "exact immutable chunked page required")
    value = page.to_dict()
    return {"page_cid": page.artifact_cid, "bytes": len(page._payload),
        "sha256": hashlib.sha256(page._payload).hexdigest(), "start": value["start"], "end": value["end"],
        "membership_cid": value["page_membership_cid"],
        **{key: value["coverage"][key] for key in ("inferred_rows", "projection_records", "chunks", "dispositions")}}


def _page_descriptor_shape(value):
    _closed(value, _PAGE_DESCRIPTOR_FIELDS, "chunked page descriptor")
    _cid(value["page_cid"], "raw")
    _int(value["bytes"], MAX_ARTIFACT_BYTES, 1)
    _sha(value["sha256"])
    _require(value["page_cid"] == resume._encode_cid_digest("base32", 1, "raw",
        bytes.fromhex("1220" + value["sha256"])), "page descriptor CID/SHA identity differs")
    _cid(value["membership_cid"])
    _page_bounds(value["start"], value["end"])
    _coverage({"inventory_entries": value["end"] - value["start"],
        **{key: value[key] for key in ("inferred_rows", "projection_records", "chunks", "dispositions")}})


def _completion_shape(value):
    _closed(value, {"schema", "profile", "root_cid", "head_cid", "membership_cid", "model_artifact_cid",
        "pages", "coverage", "authority"}, "chunked completion")
    _profile(value, COMPLETION_SCHEMA)
    _identities(value)
    pages = value["pages"]
    _require(type(pages) is list and len(pages) <= 1024, "bounded complete chunked page ledger required")
    offset, rows, projections, chunks = 0, 0, 0, 0
    counts = Counter()
    for page in pages:
        _page_descriptor_shape(page)
        _require(page["start"] == offset, "chunked completion page gap/overlap")
        offset = page["end"]
        rows += page["inferred_rows"]
        projections += page["projection_records"]
        chunks += page["chunks"]
        counts.update(page["dispositions"])
    _require(len({page["page_cid"] for page in pages}) == len(pages), "duplicate durable chunked page")
    _coverage(value["coverage"], pages=len(pages))
    _require(value["coverage"] == {"inventory_entries": offset, "inferred_rows": rows,
        "projection_records": projections, "chunks": chunks, "pages": len(pages),
        "dispositions": dict(sorted(counts.items()))}, "completion aggregate ledger differs")
    resume._authority(value["authority"])


@dataclass(frozen=True, slots=True)
class CodebaseScanChunkedCompletion:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _read_payload(self.artifact_cid, self._payload, _completion_shape)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, _wire(value))

    def advisory_refs(self, root):
        bind_codebase_scan_chunked_completion_root(self, root)
        r, c = root.to_dict(), self.to_dict()
        refs = {"schema": REFS_SCHEMA, "profile": PROFILE, "root_cid": root.artifact_cid,
            "completion_cid": self.artifact_cid, "head": r["head"], "head_cid": r["head_cid"],
            "membership_cid": r["membership_cid"], "members": r["members"], "model": r["model"],
            "pages": c["pages"], "coverage": c["coverage"], "limits": r["limits"],
            "implementation": r["implementation"], "root_record": r, "completion_record": c,
            "authority": dict(_FALSE)}
        _require(len(_wire(refs)) <= MAX_ARTIFACT_BYTES, "bounded chunked advisory required")
        return refs


def _bind_identities(value, root):
    _require(type(root) is resume.CodebaseScanResumeRoot, "exact root@1 required for chunked profile")
    r = root.to_dict()
    _require(r["limits"]["max_inventory_entries"] <= 512,
             "shared512 root inventory limit required")
    _require(value["root_cid"] == root.artifact_cid and value["head_cid"] == r["head_cid"]
             and value["membership_cid"] == r["membership_cid"]
             and value["model_artifact_cid"] == r["model"]["artifact_cid"],
             "chunked root/head/model identity differs")
    return r, resume.CodebaseScanResumeLimits.from_dict(r["limits"])


def bind_codebase_scan_chunk(chunk, root):
    """Pure root binding; does not replay targets or authenticate execution."""
    _require(type(chunk) is CodebaseScanNumericalChunk, "exact immutable numerical chunk required")
    value = chunk.to_dict()
    r, limits = _bind_identities(value, root)
    _require(value["optimized"] is r["optimized"]
             and value["model_state_sha256"] == r["model"]["state_sha256"], "chunk root optimization/state differs")
    _require(value["page_start"] % limits.page_entries == 0
             and value["page_end"] == min(value["page_start"] + limits.page_entries, len(r["members"]))
             and len(value["member_indices"]) <= limits.page_entries
             and len(value["member_indices"]) <= limits.max_inferred_rows
             and len(chunk._payload) <= limits.max_output_bytes, "chunk root page/artifact limits differ")
    resume._inference_shape(value["inference"], _chunk_entries(value), r["model"])
    transport = value["transport_bytes"]
    rows = len(value["member_indices"])
    _require(transport["feature_cells"] == rows * r["model"]["feature_columns"]
             and transport["compact_targets"] <= rows * limits.max_target_bytes
             and transport["restored_targets"] <= rows * limits.max_target_bytes,
             "shared chunk root feature/target accounting differs")
    receipt_limits = value["worker_receipt"]["limits"]
    _require(receipt_limits["max_input_bytes"] == limits.max_input_bytes
             and receipt_limits["max_output_bytes"] == limits.max_output_bytes, "chunk root worker limits differ")
    return value


def bind_codebase_scan_chunked_page_root(page, root):
    """Pure root/ledger binding without claiming that chunk bodies were read."""
    _require(type(page) is CodebaseScanChunkedPage, "exact immutable chunked page required")
    p = page.to_dict()
    r, limits = _bind_identities(p, root)
    _require(p["total_entries"] == len(r["members"])
             and p["start"] % limits.page_entries == 0
             and p["end"] == min(p["start"] + limits.page_entries, len(r["members"]))
             and p["coverage"]["inferred_rows"] <= limits.max_inferred_rows
             and len(page._payload) <= limits.max_output_bytes, "chunked root page/artifact bounds differ")
    members = r["members"][p["start"]:p["end"]]
    _require(p["page_membership_cid"] == cid_for_structured(members)
             and [(entry["source_key"], entry["entry_cid"]) for entry in p["entries"]]
                 == [(member["source_key"], member["entry_cid"]) for member in members],
             "chunked exact source membership differs")
    return p


def bind_codebase_scan_chunked_page(page, root, chunks):
    """Bind the complete inventory ledger to one actual saved record per chunk."""
    _require(type(chunks) in {list, tuple, dict}, "ordered or page-local keyed chunks required")
    p = bind_codebase_scan_chunked_page_root(page, root)
    if type(chunks) is dict:
        _require(set(chunks) == {descriptor["chunk_cid"] for descriptor in p["chunks"]},
                 "complete page-local chunk population required")
        chunks = [chunks[descriptor["chunk_cid"]] for descriptor in p["chunks"]]
    _require(len(chunks) == len(p["chunks"]), "complete saved chunk population required")
    previous = None
    for ordinal, (chunk, descriptor) in enumerate(zip(chunks, p["chunks"])):
        value = bind_codebase_scan_chunk(chunk, root)
        _require(chunk_descriptor(chunk) == descriptor and value["chunk_ordinal"] == ordinal
                 and value["previous_chunk_cid"] == previous
                 and value["page_start"] == p["start"] and value["page_end"] == p["end"],
                 "saved chunk descriptor/prefix/page binding differs")
        transient = _chunk_entries(value)
        for row_index, member_index in enumerate(value["member_indices"]):
            entry = p["entries"][member_index - p["start"]]
            _require(entry["disposition"] == "inferred" and entry["chunk_ordinal"] == ordinal
                     and entry["row_index"] == row_index
                     and entry["target_sha256"] == value["target_sha256s"][row_index]
                     and entry["source_digest"] == value["source_digests"][row_index]
                     and _wire(entry["coverage"]) == _wire(transient[row_index]["coverage"]),
                     "chunk source/target/coverage/row mapping differs")
        previous = chunk.artifact_cid
    return p


def bind_codebase_scan_chunked_completion_root(completion, root):
    """Validate root/ledger identity without claiming that chunk bodies were read."""
    _require(type(completion) is CodebaseScanChunkedCompletion, "exact immutable chunked completion required")
    value = completion.to_dict()
    r, limits = _bind_identities(value, root)
    _require(value["coverage"]["inventory_entries"] == len(r["members"])
             and value["coverage"]["inferred_rows"] <= limits.max_inferred_rows
             and len(value["pages"]) <= limits.max_pages
             and len(completion._payload) <= limits.max_output_bytes, "chunked completion root budget differs")
    for page in value["pages"]:
        _require(page["start"] % limits.page_entries == 0
                 and page["end"] == min(page["start"] + limits.page_entries, len(r["members"]))
                 and page["membership_cid"] == cid_for_structured(r["members"][page["start"]:page["end"]]),
                 "chunked completion root page partition differs")
    return value


def validate_codebase_scan_chunked_chain(root, pages, chunks_by_cid):
    """Pure complete-prefix validation; no native source or numerical execution."""
    _require(type(root) is resume.CodebaseScanResumeRoot and type(pages) in {list, tuple}
             and type(chunks_by_cid) is dict, "exact bounded chunked chain population required")
    limits = resume.CodebaseScanResumeLimits.from_dict(root.to_dict()["limits"])
    _require(len(pages) <= limits.max_pages and len(chunks_by_cid) <= 1024,
             "bounded chunked chain population required")
    offset, previous, inferred, projections, chunk_count = 0, None, 0, 0, 0
    counts, used, page_ids = Counter(), set(), set()
    descriptors = []
    for page in pages:
        _require(type(page) is CodebaseScanChunkedPage and page.artifact_cid not in page_ids,
                 "unique explicit page@3 chain required")
        p = page.to_dict()
        _require(p["start"] == offset and p["previous_page_cid"] == previous, "chunked page chain gap/prefix differs")
        chunks = []
        for descriptor in p["chunks"]:
            identity = descriptor["chunk_cid"]
            _require(identity in chunks_by_cid and identity not in used, "missing or reused chunk record")
            used.add(identity)
            chunks.append(chunks_by_cid[identity])
        bind_codebase_scan_chunked_page(page, root, chunks)
        inferred += p["coverage"]["inferred_rows"]
        _require(inferred <= limits.max_inferred_rows, "global inferred row budget exceeded")
        projections += p["coverage"]["projection_records"]
        chunk_count += p["coverage"]["chunks"]
        counts.update(p["coverage"]["dispositions"])
        offset, previous = p["end"], page.artifact_cid
        page_ids.add(page.artifact_cid)
        descriptors.append(page_descriptor(page))
    _require(set(chunks_by_cid) == used, "foreign unused chunk record")
    return {"pages": descriptors, "coverage": {"inventory_entries": offset, "inferred_rows": inferred,
        "projection_records": projections, "chunks": chunk_count, "pages": len(pages),
        "dispositions": dict(sorted(counts.items()))}}


def bind_codebase_scan_chunked_completion(completion, root, pages, chunks_by_cid):
    value = bind_codebase_scan_chunked_completion_root(completion, root)
    chain = validate_codebase_scan_chunked_chain(root, pages, chunks_by_cid)
    _require(_wire(chain) == _wire({key: value[key] for key in ("pages", "coverage")}),
             "completion differs from complete page/chunk chain")
    return value


def validate_codebase_scan_chunked_completion_refs(refs):
    """Pure historical advisory identity; does not load or authenticate chunks."""
    _closed(refs, {"schema", "profile", "root_cid", "completion_cid", "head", "head_cid",
        "membership_cid", "members", "model", "pages", "coverage", "limits", "implementation",
        "root_record", "completion_record", "authority"}, "chunked completion advisory refs")
    _require(len(_wire(refs)) <= MAX_ARTIFACT_BYTES, "bounded chunked advisory required")
    _profile(refs, REFS_SCHEMA)
    root = resume.CodebaseScanResumeRoot.from_dict(refs["root_cid"], refs["root_record"])
    completion = CodebaseScanChunkedCompletion.from_dict(refs["completion_cid"], refs["completion_record"])
    expected = completion.advisory_refs(root)
    _require(_wire(refs) == _wire(expected), "chunked advisory refs differ from records")
    return expected


__all__ = ["CHUNK_SCHEMA", "PAGE_SCHEMA", "CURSOR_SCHEMA", "COMPLETION_SCHEMA", "REFS_SCHEMA", "PROFILE",
    "MAX_ARTIFACT_BYTES", "MAX_SHARED_BYTES", "MAX_TARGET_BYTES", "MAX_FEATURE_CELLS",
    "CodebaseScanChunkError", "CodebaseScanNumericalChunk", "CodebaseScanChunkedPage",
    "CodebaseScanChunkedCursor", "CodebaseScanChunkedCompletion", "chunk_descriptor", "page_descriptor",
    "bind_codebase_scan_chunk", "bind_codebase_scan_chunked_page_root", "bind_codebase_scan_chunked_page",
    "bind_codebase_scan_chunked_completion_root",
    "bind_codebase_scan_chunked_completion", "validate_codebase_scan_chunked_chain",
    "validate_codebase_scan_chunked_completion_refs", "validate_codebase_chunk_lifecycle_receipt"]
