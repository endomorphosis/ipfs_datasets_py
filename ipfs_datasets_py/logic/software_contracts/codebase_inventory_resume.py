"""Durable, root-bound structural scan pages for up to 1024 captured members.

This versioned profile leaves the legacy 256-member scanner and checkpoint
producers unchanged. Every page uses the complete native manifest and the same
registered feature basis. Stored bytes are advisory: receiving replay verifies
source/model identities and deterministic dispositions, never numerical
execution, semantics, proof, or planner authority. All freshness checks are
sequential observations, not an atomic checkout/database snapshot. Serialized
bounds do not describe Python RSS; native Git and lineage replay use cooperative
checkpoints and the isolated numerical child uses sampled process-tree RSS.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import sysconfig
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as numerical
from . import codebase_source_training as training
from . import codebase_inventory_scan as legacy
from . import codebase_inventory_lineage as lineage
from . import codebase_ir_targets as targets
from .ast_ir import ASTRecord
from .cache import ImmutableCAS
from .codebase_ir import CodebaseScanLimits, StaleCodebaseError
from .codebase_inventory_targets import _artifact_size, _failure_payload, _member_disposition
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid, _encode_cid_digest
from .duckdb_ast_store import classify_parse_status
from .semantic_index.snapshot import snapshot_repository, _raw_display

ROOT_SCHEMA = "codebase-inventory-resume-root@1"
PAGE_SCHEMA = "codebase-inventory-resume-page@1"
COMPLETION_SCHEMA = "codebase-inventory-resume-completion@1"
CURSOR_SCHEMA = "codebase-inventory-resume-cursor@1"
REFS_SCHEMA = "codebase-resume-completion-advisory@1"
_MIB = 1024 * 1024
_FALSE = {key: False for key in (
    "source_semantics_verified", "runtime_behavior_verified", "proof_authority",
    "execution_authority", "completion_authority", "mutation_authority",
    "admission_authority", "authoritative_cache_eligible", "behavioral_satisfaction",
    "training_executed", "decoded_formulas_generated", "repository_code_executed",
    "source_execution_attested", "scan_execution_attested")}
_DISPOSITIONS = frozenset(("inferred", "opaque", "unindexed", "parse_failed", "parse_partial",
                          "unsupported_target", "feature_incompatible", "deferred_budget"))
_MEMBER_FIELDS = {"source_key", "path", "raw_path_hex", "entry_cid", "source_cid", "ast_cid",
                  "parse_status", "source_size_bytes", "opaque_reason"}
_ENTRY_FIELDS = {"member_index", "source_key", "entry_cid", "disposition", "reason",
                 "target_sha256", "source_digest", "coverage", "inference_index"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class CodebaseScanResumeError(ValueError):
    """A native binding, immutable page chain or bounded protocol differs."""


def _require(value, message):
    if not value:
        raise CodebaseScanResumeError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise CodebaseScanResumeError("finite inert native JSON required") from exc


def _closed(value, keys, name):
    _require(type(value) is dict and set(value) == set(keys), "closed " + name + " required")


def _int(value, maximum, minimum=0):
    _require(type(value) is int and minimum <= value <= maximum, "bounded exact integer required")


def _cid(value, codec="dag-json"):
    _require(type(value) is str, "exact content identity required")
    try:
        validate_cid(value, codecs={codec})
    except (ValueError, TypeError) as exc:
        raise CodebaseScanResumeError("invalid " + codec + " CID") from exc


def _sha(value):
    _require(type(value) is str and _SHA.fullmatch(value), "SHA-256 identity required")


def _authority(value):
    _closed(value, _FALSE, "authority")
    _require(all(flag is False for flag in value.values()), "all authority flags must be exact False")


def _head(value):
    head = CodebaseHead.from_dict(value)
    _require(_wire(head.to_dict()) == _wire(value), "canonical typed head required")
    return head


@dataclass(frozen=True, slots=True)
class CodebaseScanResumeLimits:
    max_inventory_entries: int = 1024
    page_entries: int = 16
    max_pages: int = 1024
    max_inferred_rows: int = 1024
    max_file_bytes: int = 64 * 1024
    max_manifest_bytes: int = 4 * _MIB
    max_target_bytes: int = 4 * _MIB
    max_input_bytes: int = 32 * _MIB
    max_output_bytes: int = 16 * _MIB

    def __post_init__(self):
        for name, maximum in zip(self.__dataclass_fields__,
                (1024, 64, 1024, 1024, 64 * 1024, 4 * _MIB, 4 * _MIB, 32 * _MIB, 16 * _MIB)):
            _int(getattr(self, name), maximum, 1)
        _require(self.max_pages * self.page_entries >= self.max_inventory_entries,
                 "root limits must allow complete inventory pagination")

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value):
        _closed(value, cls.__dataclass_fields__, "resume limits")
        return cls(**value)


def _members(manifest):
    units = {unit.source_key: unit for unit in manifest.units}
    return [{"source_key": entry.source_key, "path": entry.path, "raw_path_hex": entry.raw_path_hex,
             "entry_cid": entry.entry_cid, "source_cid": entry.source_cid,
             "ast_cid": units[entry.source_key].ast_cid, "parse_status": units[entry.source_key].parse_status,
             "source_size_bytes": entry.size_bytes, "opaque_reason": entry.opaque_reason}
            for entry in manifest.snapshot.entries]


def _member_shape(member):
    _closed(member, _MEMBER_FIELDS, "inventory member")
    raw_hex = member["raw_path_hex"]
    _require(type(raw_hex) is str and raw_hex and len(raw_hex) <= 8192
             and re.fullmatch(r"(?:[0-9a-f]{2})+", raw_hex), "canonical raw path required")
    raw_path = bytes.fromhex(raw_hex)
    _require(member["source_key"] == "raw:" + raw_hex and member["path"] == _raw_display(raw_path),
             "exact captured source path required")
    _cid(member["entry_cid"])
    if member["source_cid"] is not None:
        _cid(member["source_cid"], "raw")
    if member["ast_cid"] is not None:
        _cid(member["ast_cid"])
    if member["source_size_bytes"] is not None:
        _int(member["source_size_bytes"], 2**63 - 1)
    _require(member["parse_status"] in {"ok", "partial", "failed", "opaque", "unindexed"},
             "native parse status required")
    _require(member["opaque_reason"] is None or
             (type(member["opaque_reason"]) is str and 0 < len(member["opaque_reason"]) <= 512),
             "opaque disposition reason required")
    opaque = member["parse_status"] == "opaque"
    _require(opaque == (member["opaque_reason"] is not None)
             and (member["ast_cid"] is None) == (member["parse_status"] in {"opaque", "unindexed"})
             and (opaque or (member["source_cid"] is not None and member["source_size_bytes"] is not None)),
             "native source/AST opacity binding differs")


def _artifact_shape(value):
    _closed(value, {"sha256", "bytes"}, "model artifact")
    _sha(value["sha256"])
    _int(value["bytes"], 16 * _MIB, 1)


def _model_shape(model):
    _closed(model, {"version_id", "variant_id", "artifact", "artifact_cid", "contract_sha256",
        "state_sha256", "feature_space_sha256", "latent_width", "feature_columns", "projection_ids",
        "projection_widths", "ancestry"}, "model identity")
    for key in ("version_id", "variant_id"):
        training._text(model[key], key)
    _artifact_shape(model["artifact"])
    _cid(model["artifact_cid"], "raw")
    _require(model["artifact_cid"] == _encode_cid_digest("base32", 1, "raw",
        bytes.fromhex("1220" + model["artifact"]["sha256"])), "model artifact CID/SHA binding differs")
    for key in ("contract_sha256", "state_sha256", "feature_space_sha256"):
        _sha(model[key])
    _int(model["latent_width"], 64, 1)
    _int(model["feature_columns"], 1024, 1)
    ids = model["projection_ids"]
    _require(type(ids) is list and ids == sorted(set(ids)) and 1 <= len(ids) <= 2
             and all(type(key) is str for key in ids), "ordered projection identities required")
    _closed(model["projection_widths"], ids, "projection layout")
    for value in model["projection_widths"].values():
        _int(value, 1024, 1)
    _require(sum(model["projection_widths"].values()) == model["feature_columns"], "feature layout differs")
    ancestry = model["ancestry"]
    _require(type(ancestry) is list and 1 <= len(ancestry) <= 8, "bounded model ancestry required")
    for row in ancestry:
        _closed(row, {"version_id", "artifact"}, "ancestor identity")
        training._text(row["version_id"], "ancestor version")
        _artifact_shape(row["artifact"])
    _require(len({row["version_id"] for row in ancestry}) == len(ancestry)
             and ancestry[0] == {"version_id": model["version_id"], "artifact": model["artifact"]},
             "model ancestry identity differs")


def _implementation_shape(value):
    _closed(value, {"files", "sha256", "scope"}, "implementation")
    _require(type(value["files"]) is dict and 1 <= len(value["files"]) <= 32
             and all(type(key) is str and 0 < len(key) <= 256 for key in value["files"]),
             "bounded implementation file identities required")
    for digest in value["files"].values():
        _sha(digest)
    _require(value["sha256"] == features.digest(value["files"])
             and value["scope"] == "listed_local_files_only_not_execution_attestation",
             "implementation digest differs")


def _root_shape(value):
    _closed(value, {"schema", "head", "head_cid", "members", "membership_cid", "model", "limits",
                    "optimized", "implementation", "authority"}, "resume root")
    _require(value["schema"] == ROOT_SCHEMA and type(value["optimized"]) is bool, "root schema/opt-out differs")
    _head(value["head"])
    _require(value["head_cid"] == cid_for_structured(value["head"]), "head digest differs")
    limits = CodebaseScanResumeLimits.from_dict(value["limits"])
    members = value["members"]
    _require(type(members) is list and len(members) <= limits.max_inventory_entries, "bounded complete membership required")
    for member in members:
        _member_shape(member)
        if member["parse_status"] != "opaque":
            _int(member["source_size_bytes"], limits.max_file_bytes)
    _require([row["raw_path_hex"] for row in members] == sorted({row["raw_path_hex"] for row in members})
             and len({row["entry_cid"] for row in members}) == len(members)
             and value["membership_cid"] == cid_for_structured(members), "complete ordered membership differs")
    _model_shape(value["model"])
    _implementation_shape(value["implementation"])
    _authority(value["authority"])


@dataclass(frozen=True, slots=True)
class CodebaseScanResumeRoot:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _require(type(self._payload) is bytes and len(self._payload) <= 4 * _MIB, "bounded immutable root required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid,
                 "root structured identity differs")
        _root_shape(value)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, canonical_dag_json_bytes(value))


@dataclass(frozen=True, slots=True)
class CodebaseScanResumeCursor:
    root_cid: str
    next_offset: int
    previous_page_cid: str

    def __post_init__(self):
        _cid(self.root_cid)
        _cid(self.previous_page_cid, "raw")
        _int(self.next_offset, 1024, 1)

    def to_dict(self):
        return {"schema": CURSOR_SCHEMA, "root_cid": self.root_cid, "next_offset": self.next_offset,
                "previous_page_cid": self.previous_page_cid}

    @classmethod
    def from_dict(cls, value):
        _closed(value, {"schema", "root_cid", "next_offset", "previous_page_cid"}, "resume cursor")
        _require(value["schema"] == CURSOR_SCHEMA, "cursor schema differs")
        return cls(value["root_cid"], value["next_offset"], value["previous_page_cid"])


def _coverage_shape(value, entries, pages=None):
    fields = {"inventory_entries", "inferred_rows", "dispositions"} | ({"pages"} if pages is not None else set())
    _closed(value, fields, "coverage ledger")
    _int(value["inventory_entries"], 1024)
    _int(value["inferred_rows"], 1024)
    counts = value["dispositions"]
    _require(type(counts) is dict and set(counts) <= _DISPOSITIONS, "closed disposition counts required")
    for count in counts.values():
        _int(count, 1024, 1)
    _require(sum(counts.values()) == value["inventory_entries"]
             and value["inferred_rows"] == counts.get("inferred", 0), "coverage count conservation differs")
    if entries is not None:
        _require(value["inventory_entries"] == len(entries)
                 and counts == dict(sorted(Counter(row["disposition"] for row in entries).items())),
                 "entry dispositions differ from coverage")
    if pages is not None:
        _int(value["pages"], 1024)
        _require(value["pages"] == pages, "page count differs")


def _entry_shape(row):
    _closed(row, _ENTRY_FIELDS, "page entry")
    _int(row["member_index"], 1023)
    _require(type(row["source_key"]) is str and re.fullmatch(r"raw:(?:[0-9a-f]{2})+", row["source_key"]),
             "raw source key required")
    _cid(row["entry_cid"])
    _require(row["disposition"] in _DISPOSITIONS, "closed entry disposition required")
    _require(row["reason"] is None or (type(row["reason"]) is str and 0 < len(row["reason"]) <= 256),
             "bounded disposition reason required")
    for key in ("target_sha256", "source_digest"):
        if row[key] is not None:
            _sha(row[key])
    _require((row["target_sha256"] is None) == (row["source_digest"] is None), "target binding is incomplete")
    _require(type(row["coverage"]) is list and len(row["coverage"]) <= 2, "bounded feature coverage required")
    ids = []
    for coverage in row["coverage"]:
        _closed(coverage, {"projection_id", "known_atoms", "unknown_atoms"}, "feature coverage")
        _require(type(coverage["projection_id"]) is str, "projection identity required")
        _int(coverage["known_atoms"], 2**63 - 1)
        _int(coverage["unknown_atoms"], 2**63 - 1)
        ids.append(coverage["projection_id"])
    _require(ids == sorted(set(ids)), "ordered feature coverage required")
    inferred = row["disposition"] == "inferred"
    _require(inferred == (row["inference_index"] is not None), "inference index/disposition differs")
    if inferred:
        _int(row["inference_index"], 63)
        _require(row["target_sha256"] is not None and row["reason"] is None
                 and bool(row["coverage"]) and all(item["known_atoms"] > 0 for item in row["coverage"]),
                 "inferred target identity/coverage differs")


def _inference_shape(inference, entries, model=None):
    inferred = [row for row in entries if row["disposition"] == "inferred"]
    _require((inference is None) == (not inferred), "numerical result presence differs")
    if inference is None:
        return
    expected = {"schema", "contract_sha256", "state_sha256", "feature_space_sha256", "rows", "coverage",
                "training_executed", "decoded_formulas_generated", "representation", *features.FALSE}
    _closed(inference, expected, "inference")
    _require(inference["schema"] == "native-projection-feature-inference/v1"
             and inference["representation"] == "native_compiler_structural_features_not_semantic_text_embeddings"
             and all(inference[key] is False for key in (*features.FALSE, "training_executed", "decoded_formulas_generated")),
             "inference representation/authority differs")
    for key in ("contract_sha256", "state_sha256", "feature_space_sha256"):
        _sha(inference[key])
        if model is not None:
            _require(inference[key] == model[key], "inference model identity differs")
    _require(_wire(inference["coverage"]) == _wire([item for row in inferred for item in row["coverage"]]),
             "inference feature coverage differs")
    rows = inference["rows"]
    _require(type(rows) is list and len(rows) == len(inferred), "exact numerical rows required")
    for ordinal, (row, entry) in enumerate(zip(rows, inferred)):
        _closed(row, {"source_digest", "latent", "reconstructed_projection_features"}, "numerical row")
        _require(entry["inference_index"] == ordinal and row["source_digest"] == entry["source_digest"],
                 "numerical source/order differs")
        _require(type(row["latent"]) is list and 1 <= len(row["latent"]) <= 64
                 and type(row["reconstructed_projection_features"]) is dict, "bounded numerical layout required")
        ids = [item["projection_id"] for item in entry["coverage"]]
        _closed(row["reconstructed_projection_features"], ids, "reconstructed projections")
        values = list(row["latent"])
        for key, block in row["reconstructed_projection_features"].items():
            _require(type(block) is list and 1 <= len(block) <= 1024, "bounded projection vector required")
            if model is not None:
                _require(len(block) == model["projection_widths"][key], "projection width differs")
            values.extend(block)
        _require(all(type(number) in {int, float} and math.isfinite(number) for number in values),
                 "finite numerical values required")
        if model is not None:
            _require(len(row["latent"]) == model["latent_width"] and ids == model["projection_ids"],
                     "registered numerical layout differs")


def _receipt_shape(receipt, inference):
    _require((receipt is None) == (inference is None), "worker receipt presence differs")
    if receipt is None:
        return
    _closed(receipt, {"executable_sha256", "worker_sha256", "input_sha256", "output_sha256",
        "input_bytes", "output_bytes", "elapsed_ms", "returncode", "workspace_cleaned", "limits",
        "memory_enforcement", "source_execution_attested"}, "worker receipt")
    for key in ("executable_sha256", "worker_sha256", "input_sha256", "output_sha256"):
        _sha(receipt[key])
    _int(receipt["input_bytes"], 32 * _MIB, 1)
    _int(receipt["output_bytes"], 16 * _MIB, 1)
    _int(receipt["elapsed_ms"], 2**63 - 1)
    _require(type(receipt["returncode"]) is int and receipt["returncode"] == 0
             and receipt["workspace_cleaned"] is True and receipt["source_execution_attested"] is False
             and receipt["memory_enforcement"] == "sampled_process_tree_rss_with_possible_overshoot",
             "worker accounting/authority differs")
    _closed(receipt["limits"], {"resident_memory_bytes", "max_input_bytes", "max_output_bytes"}, "worker limits")
    _int(receipt["limits"]["resident_memory_bytes"], 64 * 1024 * _MIB, 1024 * _MIB)
    _int(receipt["limits"]["max_input_bytes"], 32 * _MIB, 1)
    _int(receipt["limits"]["max_output_bytes"], 16 * _MIB, 1)
    _require(receipt["input_bytes"] <= receipt["limits"]["max_input_bytes"]
             and receipt["output_bytes"] <= receipt["limits"]["max_output_bytes"], "worker byte accounting differs")


def _page_shape(value):
    _closed(value, {"schema", "root_cid", "head_cid", "membership_cid", "model_artifact_cid", "start", "end",
                    "total_entries", "page_membership_cid", "previous_page_cid", "entries", "inference",
                    "worker_receipt", "coverage", "authority"}, "resume page")
    _require(value["schema"] == PAGE_SCHEMA, "page schema differs")
    for key in ("root_cid", "head_cid", "membership_cid", "page_membership_cid"):
        _cid(value[key])
    _cid(value["model_artifact_cid"], "raw")
    _int(value["start"], 1023)
    _int(value["end"], 1024, 1)
    _int(value["total_entries"], 1024, 1)
    _require(value["start"] < value["end"] <= value["total_entries"]
             and value["end"] - value["start"] <= 64, "contiguous bounded page required")
    if value["previous_page_cid"] is not None:
        _cid(value["previous_page_cid"], "raw")
    _require((value["previous_page_cid"] is None) == (value["start"] == 0), "page prefix link differs")
    entries = value["entries"]
    _require(type(entries) is list and len(entries) == value["end"] - value["start"], "complete page entries required")
    for row in entries:
        _entry_shape(row)
    _require([row["member_index"] for row in entries] == list(range(value["start"], value["end"]))
             and len({row["source_key"] for row in entries}) == len(entries), "page membership/order differs")
    _coverage_shape(value["coverage"], entries)
    _inference_shape(value["inference"], entries)
    _receipt_shape(value["worker_receipt"], value["inference"])
    _authority(value["authority"])


@dataclass(frozen=True, slots=True)
class CodebaseScanResumePage:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _require(type(self._payload) is bytes and len(self._payload) <= 16 * _MIB, "bounded immutable page required")
        value = json.loads(self._payload)
        _require(_wire(value) == self._payload and cid_for_bytes(self._payload) == self.artifact_cid,
                 "page finite JSON/raw identity differs")
        _page_shape(value)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, _wire(value))

    @property
    def next_cursor(self):
        value = self.to_dict()
        return None if value["end"] == value["total_entries"] else CodebaseScanResumeCursor(
            value["root_cid"], value["end"], self.artifact_cid)


def _descriptor(page):
    value = page.to_dict()
    return {"page_cid": page.artifact_cid, "start": value["start"], "end": value["end"],
            "membership_cid": value["page_membership_cid"], "inferred_rows": value["coverage"]["inferred_rows"],
            "dispositions": value["coverage"]["dispositions"]}


def _completion_shape(value):
    _closed(value, {"schema", "root_cid", "head_cid", "membership_cid", "model_artifact_cid", "pages",
                    "coverage", "authority"}, "resume completion")
    _require(value["schema"] == COMPLETION_SCHEMA, "completion schema differs")
    for key in ("root_cid", "head_cid", "membership_cid"):
        _cid(value[key])
    _cid(value["model_artifact_cid"], "raw")
    pages = value["pages"]
    _require(type(pages) is list and len(pages) <= 1024, "bounded complete page ledger required")
    offset, counts, inferred = 0, Counter(), 0
    for page in pages:
        _closed(page, {"page_cid", "start", "end", "membership_cid", "inferred_rows", "dispositions"}, "page descriptor")
        _cid(page["page_cid"], "raw")
        _cid(page["membership_cid"])
        _int(page["start"], 1023)
        _int(page["end"], 1024, 1)
        _require(page["start"] == offset and 0 < page["end"] - page["start"] <= 64, "page ledger gap/overlap")
        _coverage_shape({"inventory_entries": page["end"] - page["start"],
            "inferred_rows": page["inferred_rows"], "dispositions": page["dispositions"]}, None)
        counts.update(page["dispositions"])
        inferred += page["inferred_rows"]
        offset = page["end"]
    _require(len({page["page_cid"] for page in pages}) == len(pages), "duplicate durable page identity")
    _coverage_shape(value["coverage"], None, len(pages))
    _require(value["coverage"]["inventory_entries"] == offset and value["coverage"]["inferred_rows"] == inferred
             and value["coverage"]["dispositions"] == dict(sorted(counts.items())), "completion ledger differs")
    _authority(value["authority"])


@dataclass(frozen=True, slots=True)
class CodebaseScanResumeCompletion:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _require(type(self._payload) is bytes and len(self._payload) <= 4 * _MIB, "bounded immutable completion required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid,
                 "completion structured identity differs")
        _completion_shape(value)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, canonical_dag_json_bytes(value))

    def advisory_refs(self, root):
        _require(type(root) is CodebaseScanResumeRoot, "exact native resume root required")
        r, c = root.to_dict(), self.to_dict()
        _bind_completion(c, root)
        return {"schema": REFS_SCHEMA, "root_cid": root.artifact_cid, "completion_cid": self.artifact_cid,
            "head": r["head"], "head_cid": r["head_cid"], "membership_cid": r["membership_cid"],
            "members": r["members"], "model": r["model"], "pages": c["pages"], "coverage": c["coverage"],
            "limits": r["limits"], "implementation": r["implementation"],
            "root_record": r, "completion_record": c, "authority": dict(_FALSE)}


def validate_codebase_scan_completion_refs(refs):
    """Pure historical shape/identity validation; grants no current authority."""
    _closed(refs, {"schema", "root_cid", "completion_cid", "head", "head_cid", "membership_cid", "members",
        "model", "pages", "coverage", "limits", "implementation", "root_record", "completion_record", "authority"},
        "completion advisory refs")
    root = CodebaseScanResumeRoot.from_dict(refs["root_cid"], refs["root_record"])
    completion = CodebaseScanResumeCompletion.from_dict(refs["completion_cid"], refs["completion_record"])
    expected = completion.advisory_refs(root)
    _require(canonical_dag_json_bytes(refs) == canonical_dag_json_bytes(expected), "advisory refs differ from records")
    return expected


def _cas(artifacts):
    _require(type(artifacts) is ImmutableCAS and type(artifacts.max_object_bytes) is int
             and 0 < artifacts.max_object_bytes <= 16 * _MIB, "exact bounded native CAS required")


def load_codebase_scan_resume_root(artifacts, root_cid):
    _cas(artifacts)
    _artifact_size(artifacts, root_cid, 4 * _MIB)
    return CodebaseScanResumeRoot.from_dict(root_cid, artifacts.get(root_cid, expected_schema=ROOT_SCHEMA))


def load_codebase_scan_resume_page(artifacts, page_cid):
    _cas(artifacts)
    _artifact_size(artifacts, page_cid, 16 * _MIB, source=True)
    return CodebaseScanResumePage(page_cid, artifacts.get_bytes(page_cid))


def load_codebase_scan_resume_completion(artifacts, completion_cid):
    _cas(artifacts)
    _artifact_size(artifacts, completion_cid, 4 * _MIB)
    return CodebaseScanResumeCompletion.from_dict(completion_cid, artifacts.get(completion_cid, expected_schema=COMPLETION_SCHEMA))


def _bind_page(page, root):
    r, p = root.to_dict(), page.to_dict()
    _require(p["root_cid"] == root.artifact_cid and p["head_cid"] == r["head_cid"]
             and p["membership_cid"] == r["membership_cid"]
             and p["model_artifact_cid"] == r["model"]["artifact_cid"]
             and p["total_entries"] == len(r["members"]), "page root/head/model identity differs")
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    _require(p["start"] % limits.page_entries == 0
             and p["end"] == min(p["start"] + limits.page_entries, len(r["members"]))
             and len(page._payload) <= limits.max_output_bytes, "root page bounds/order differ")
    members = r["members"][p["start"]:p["end"]]
    _require(p["page_membership_cid"] == cid_for_structured(members)
             and [(row["source_key"], row["entry_cid"]) for row in p["entries"]]
                 == [(row["source_key"], row["entry_cid"]) for row in members], "exact page membership differs")
    _inference_shape(p["inference"], p["entries"], r["model"])
    if p["worker_receipt"] is not None:
        receipt = p["worker_receipt"]
        _require(receipt["limits"]["max_input_bytes"] == limits.max_input_bytes
                 and receipt["limits"]["max_output_bytes"] == limits.max_output_bytes, "root worker limits differ")


def _bind_completion(value, root):
    r = root.to_dict()
    _require(value["root_cid"] == root.artifact_cid and value["head_cid"] == r["head_cid"]
             and value["membership_cid"] == r["membership_cid"]
             and value["model_artifact_cid"] == r["model"]["artifact_cid"]
             and value["coverage"]["inventory_entries"] == len(r["members"]), "completion root coverage differs")
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    _require(len(value["pages"]) <= limits.max_pages
             and value["coverage"]["inferred_rows"] <= limits.max_inferred_rows, "completion root budget differs")
    for page in value["pages"]:
        _require(page["start"] % limits.page_entries == 0
                 and page["end"] == min(page["start"] + limits.page_entries, len(r["members"]))
                 and page["membership_cid"] == cid_for_structured(r["members"][page["start"]:page["end"]]),
                 "completion page membership/partition differs")


def _implementation():
    files = dict(training._pins()["files"])
    for name in (__name__, "ipfs_datasets_py.optimizers.logic_theorem_optimizer.codebase_inventory_resume_worker",
                 numerical.__name__, legacy.__name__, "ipfs_datasets_py.logic.software_contracts.codebase_inventory_targets",
                 "ipfs_datasets_py.logic.software_contracts.codebase_ir",
                 "ipfs_datasets_py.logic.software_contracts.codebase_inventory_projection_replay",
                 "ipfs_datasets_py.logic.software_contracts.codebase_inventory_receiving",
                 lineage.__name__,
                 "ipfs_datasets_py.logic.software_contracts.duckdb_ast_store",
                 "ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot"):
        module = importlib.import_module(name)
        files[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {"files": files, "sha256": features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}


def _owners(index, registry):
    training._native_owners(index, registry)
    _require(type(index.catalog) is CodebaseCatalog and index.catalog.store is index.ingestor.store
             and index.catalog.artifacts is index.artifacts, "one exact structural store/CAS owner required")
    index.catalog._ensure_owner()
    _cas(index.artifacts)


class _ResumeLineageContext(lineage.InventoryLineageContext):
    """One bounded replay; full native targets preserve the larger capture.

    Only preparation differs from the reviewed inventory context. It uses
    the unchanged legacy full-envelope producer, rather than a 256-member
    inventory seal. Every distinct complete canonical target is natively
    replayed before any binding reuse. No context survives the operation.
    """

    def prepare(self, head, path, contracts=()):
        self.checkpoint()
        key = lineage._wire({"head": head.to_dict(), "path": path,
                             "contracts": [item.to_dict() for item in contracts]})
        if key in self._prepared:
            raw = self._prepared[key]
            target = self._targets[raw]
            training._require(target.canonical_bytes == raw, "operation prepared target was mutated")
            self.counters.target_preparation_cache_hits += 1
            return target
        target = targets.prepare_codebase_targets(self.index, expected_head=head, path=path, contracts=contracts)
        self.counters.target_preparations += 1
        target = self.validated(target)
        self._retain(len(key) + len(target.canonical_bytes))
        self._prepared[key] = target.canonical_bytes
        self.checkpoint()
        return target

    def _verify_snapshots(self):
        # The caches are private and their payloads are frozen/byte-backed.
        # Detect forced local object mutation before returning the chain too.
        for row_raw, saved_raw, row, saved in self._candidates.values():
            self.checkpoint()
            training._require(lineage._wire(row) == row_raw and lineage._wire(saved) == saved_raw,
                              "operation candidate snapshot was mutated")
        training._require(set(self._bindings) == set(self._targets), "operation binding inventory was mutated")
        for raw, target in self._targets.items():
            self.checkpoint()
            training._require(target.canonical_bytes == raw, "operation validated target was mutated")
            details = target.to_dict()["validation"][0]["details"]
            binding_raw = lineage._wire({**details["source_binding"],
                                        "authored_contracts": details["authored_contracts"]})
            training._require(self._bindings[raw] == binding_raw, "operation target binding was mutated")


def _resume_lineage(index, registry, version_id, limits, remaining, *, optimized=True):
    """Return the native chain, with reuse confined to this admitted operation.

    This does not observe the live checkout or authenticate retained numerical
    execution. The owning scanner still closes fresh source/CAS/model fences.
    Counters belong to the private context, never a public attestation record.
    """
    _require(type(optimized) is bool and callable(remaining), "exact lineage opt-out/checkpoint required")
    remaining()
    if not optimized:
        chain = training._lineage(index, registry, version_id, limits)
    else:
        context = _ResumeLineageContext(index, registry, limits, checkpoint=remaining)
        chain = lineage._lineage(index, registry, version_id, limits, context)
        context._verify_snapshots()
        lineage._reference_guard(context.counters)
        # The returned chain references the same candidate/target payloads;
        # it does not retain the cache indexes, snapshot bytes or bindings.
        del context
    remaining()
    return chain


@contextmanager
def _scope(index, registry, *, scheduler, parent_lease, cancel_event,
           admission_timeout_seconds, timeout_seconds, memory_mb):
    _owners(index, registry)
    _require(type(timeout_seconds) in {int, float} and math.isfinite(timeout_seconds)
             and 0 < timeout_seconds <= 600, "finite bounded operation deadline required")
    _require(type(admission_timeout_seconds) in {int, float} and math.isfinite(admission_timeout_seconds)
             and 0 <= admission_timeout_seconds <= 600, "finite bounded admission timeout required")
    _int(memory_mb, 64 * 1024, 1024)
    # The ancestry, registry snapshots, request/response, manifest/root and a
    # single bounded source/AST/target are retained in separate phases. The
    # lineage cache is at most 40 MiB including candidate/target payloads
    # shared with the returned chain, plus a <=16 MiB canonical candidate
    # recheck transient. Its indexes are discarded before history/streams.
    # These serialized ceilings deliberately do not claim RSS containment.
    _require(224 * _MIB <= memory_mb * _MIB // 4, "serialized retention exceeds memory reservation")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(admission_timeout_seconds, timeout_seconds),
            memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("resumable inventory cancelled")
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise LeaseTimeoutError("resumable inventory deadline exceeded")
            return seconds
        remaining()
        yield lease, signal, remaining
        remaining()


def _receipt(index, head, remaining):
    with index.catalog.store._lock:
        index.catalog._ensure_owner()
        with index.catalog.store._transaction():
            index.catalog._check_schema()
            remaining()
            receipt = index.catalog._read_receipt("receipt_cid", head.receipt_cid)
    _require(receipt is not None and receipt.head == head
             and len(canonical_dag_json_bytes(receipt.to_dict())) <= 64 * 1024,
             "exact bounded native publication receipt required")
    return receipt


def _member_native(index, manifest, entry, unit, limits, remaining, *, snapshot_cid=None):
    # Only fresh owning observations supply this operation-local identity.
    # Public receiving APIs never accept a caller's prevalidated identity.
    _require(snapshot_cid is None or type(snapshot_cid) is str, "exact operation snapshot identity required")
    remaining()
    raw, record = None, None
    if not entry.is_opaque:
        _artifact_size(index.artifacts, entry.source_cid, limits.max_file_bytes, source=True)
        raw = index.artifacts.get_bytes(entry.source_cid)
        _require(len(raw) == entry.size_bytes and len(raw) <= limits.max_file_bytes, "captured source byte identity differs")
    if unit.ast_cid is not None:
        _artifact_size(index.artifacts, unit.ast_cid, 4 * _MIB)
        value = index.artifacts.get(unit.ast_cid)
        if value.get("kind") == "parse_failure":
            _failure_payload(value, entry, unit, manifest)
        else:
            record = ASTRecord.from_dict(value)
            p = record.provenance
            _require(_wire(record.to_dict()) == _wire(value) and classify_parse_status(record) == unit.parse_status
                     and p.source_cid == entry.source_cid and p.path == entry.path
                     and p.repository_id == manifest.snapshot.repository_id
                     and p.revision == "snapshot:" + (manifest.snapshot.snapshot_cid if snapshot_cid is None else snapshot_cid)
                     and p.repository_tree_cid == (manifest.snapshot.snapshot_cid if snapshot_cid is None else snapshot_cid),
                     "native AST/source bindings differ")
    remaining()
    return raw, record


def _observe(index, repository, head, limits, remaining, memory_mb, *, optimized=True):
    _require(type(optimized) is bool, "exact projection replay opt-out required")
    if index.current(head.repository_id) != head:
        raise StaleCodebaseError("resume catalog head changed")
    _artifact_size(index.artifacts, head.manifest_cid, limits.max_manifest_bytes)
    manifest = index.load(head.manifest_cid)
    captured = manifest.snapshot
    snapshot_cid = captured.snapshot_cid
    _require(manifest.cid == head.manifest_cid and manifest.snapshot.repository_id == head.repository_id
             and snapshot_cid == head.snapshot_cid and manifest.ast_revision_id == head.ast_revision_id,
             "head/global native manifest binding differs")
    _require(captured.max_entries <= limits.max_inventory_entries and len(captured.entries) <= limits.max_inventory_entries
             and captured.max_file_bytes <= limits.max_file_bytes, "capture exceeds versioned resume profile")
    CodebaseScanLimits(captured.max_entries, captured.max_file_bytes).validate_reservation(memory_mb)
    _require(len(canonical_dag_json_bytes(manifest.to_dict())) <= limits.max_manifest_bytes, "native manifest byte bound exceeded")
    receipt = _receipt(index, head, remaining)
    units = {unit.source_key: unit for unit in manifest.units}
    _require([entry.raw_path_hex for entry in captured.entries] == sorted({entry.raw_path_hex for entry in captured.entries}),
             "native inventory ordering differs")
    if optimized:
        from .codebase_inventory_projection_replay import replay_current_inventory_projections
        replay_current_inventory_projections(index, manifest, expected_head=head, checkpoint=remaining)
    for entry in captured.entries:
        remaining()
        if not optimized:
            index.lookup(manifest, entry.path)
        raw, record = _member_native(index, manifest, entry, units[entry.source_key], limits, remaining,
                                     snapshot_cid=snapshot_cid if optimized else None)
        del raw, record
    remaining()
    observed = snapshot_repository(repository, repository_id=head.repository_id,
        max_file_bytes=captured.max_file_bytes, max_entries=captured.max_entries, exclusions=captured.exclusions)
    remaining()
    if observed.snapshot_cid != head.snapshot_cid or index.current(head.repository_id) != head:
        raise StaleCodebaseError("current source differs from resume root")
    _require(manifest.cid == head.manifest_cid and manifest.snapshot.snapshot_cid == head.snapshot_cid,
             "observed native manifest changed during member replay")
    return manifest, receipt


def _model(chain):
    row, saved, _ = chain[0][:3]
    space, state = saved["feature_space"], saved["state"]
    return {"version_id": row["version_id"], "variant_id": row["variant_id"], "artifact": row["artifact"],
        "artifact_cid": cid_for_bytes(training._wire(saved)), "contract_sha256": state["contract_sha256"],
        "state_sha256": features.digest(state), "feature_space_sha256": features.digest(space),
        "latent_width": state["latent_width"], "feature_columns": len(space["columns"]),
        "projection_ids": space["projection_ids"],
        "projection_widths": {key: sum(column[0] == key for column in space["columns"]) for key in space["projection_ids"]},
        "ancestry": [{"version_id": ancestor[0]["version_id"], "artifact": ancestor[0]["artifact"]} for ancestor in chain]}


def _history_fence(index, chain, current_head, limits, remaining, *, optimized=True):
    """Stream immutable ancestral captures without asserting active checkout."""
    _require(type(optimized) is bool, "exact historical replay opt-out required")
    for head in legacy._history_heads(chain):
        remaining()
        if head == current_head:
            continue
        _artifact_size(index.artifacts, head.manifest_cid, limits.max_manifest_bytes)
        manifest = index.load(head.manifest_cid)
        snapshot_cid = manifest.snapshot.snapshot_cid
        _require(manifest.snapshot.repository_id == head.repository_id
                 and snapshot_cid == head.snapshot_cid
                 and manifest.ast_revision_id == head.ast_revision_id
                 and manifest.snapshot.max_entries <= limits.max_inventory_entries
                 and manifest.snapshot.max_file_bytes <= limits.max_file_bytes,
                 "historical capture exceeds native resume profile")
        receipt = _receipt(index, head, remaining)
        units = {unit.source_key: unit for unit in manifest.units}
        for entry in manifest.snapshot.entries:
            raw, record = _member_native(index, manifest, entry, units[entry.source_key], limits, remaining,
                                         snapshot_cid=snapshot_cid if optimized else None)
            del raw, record
        remaining()
        _require(manifest.cid == head.manifest_cid and manifest.snapshot.snapshot_cid == head.snapshot_cid,
                 "historical native manifest changed during member replay")
        del manifest, receipt


def _entry(index, repository, root, registry, remaining, memory_mb):
    _require(type(root) is CodebaseScanResumeRoot, "exact native resume root required")
    _require(load_codebase_scan_resume_root(index.artifacts, root.artifact_cid)._payload == root._payload,
             "durable root bytes differ")
    r = root.to_dict()
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    _require(r["implementation"] == _implementation(), "resume implementation changed")
    before = legacy._registry_inventory(registry, legacy.CodebaseInventoryScanLimits(), remaining)
    manifest, receipt = _observe(index, repository, _head(r["head"]), limits, remaining, memory_mb,
                                 optimized=r["optimized"])
    _require(_wire(_members(manifest)) == _wire(r["members"]), "native global membership differs")
    chain = _resume_lineage(index, registry, r["model"]["version_id"], training.CodebaseFeatureTrainingLimits(),
                            remaining, optimized=r["optimized"])
    remaining()
    _require(_wire(_model(chain)) == _wire(r["model"])
             and _wire(chain[0][2]["head"]) == _wire(r["head"]), "resume native model/head/basis differs")
    _history_fence(index, chain, _head(r["head"]), limits, remaining, optimized=r["optimized"])
    return manifest, receipt, chain, before


def _close(index, repository, root, registry, chain, before, remaining, memory_mb):
    r = root.to_dict()
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    manifest, receipt = _observe(index, repository, _head(r["head"]), limits, remaining, memory_mb,
                                 optimized=r["optimized"])
    _require(_wire(_members(manifest)) == _wire(r["members"]), "closing global membership differs")
    del manifest, receipt
    _history_fence(index, chain, _head(r["head"]), limits, remaining, optimized=r["optimized"])
    legacy._model_fence(registry, chain, remaining)
    _require(legacy._registry_inventory(registry, legacy.CodebaseInventoryScanLimits(), remaining) == before,
             "registry namespace changed during resume operation")
    _owners(index, registry)
    _require(r["implementation"] == _implementation(), "resume producer changed")
    remaining()


def _walk(artifacts, root, tail_cid, remaining, check_page=None):
    """Walk one immutable prefix backwards, then stream it forwards for replay."""
    r, reversed_cids, seen, next_start = root.to_dict(), [], set(), None
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    current = tail_cid
    while current is not None:
        remaining()
        _require(current not in seen and len(seen) < limits.max_pages, "duplicate/cyclic/oversized page chain")
        seen.add(current)
        page = load_codebase_scan_resume_page(artifacts, current)
        _bind_page(page, root)
        p = page.to_dict()
        if next_start is not None:
            _require(p["end"] == next_start, "page chain omission/overlap/reordering")
        next_start = p["start"]
        reversed_cids.append(current)
        current = p["previous_page_cid"]
        del page, p
    _require(not reversed_cids or next_start == 0, "prefix must begin at global offset zero")
    descriptors, counts, inferred, offset = [], Counter(), 0, 0
    for current in reversed(reversed_cids):
        remaining()
        page = load_codebase_scan_resume_page(artifacts, current)
        if check_page is not None:
            check_page(page, inferred)
        descriptor = _descriptor(page)
        _require(descriptor["start"] == offset, "page chain gap")
        inferred += descriptor["inferred_rows"]
        _require(inferred <= limits.max_inferred_rows, "global inference budget exceeded")
        counts.update(descriptor["dispositions"])
        offset = descriptor["end"]
        descriptors.append(descriptor)
        del page
    return descriptors, offset, inferred, dict(sorted(counts.items()))


def _payload(root, saved):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_resume_worker as worker
    r = root.to_dict()
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    return {"schema": worker.SCHEMA, "root_cid": root.artifact_cid, "root": r, "optimized": r["optimized"],
        "contract": saved["contract"], "feature_space": saved["feature_space"], "state": saved["state"],
        "targets": [], "member_indices": [], "max_seconds": 600.0,
        "limits": {"max_rows": limits.page_entries, "max_target_bytes": limits.max_target_bytes,
                   "max_input_bytes": limits.max_input_bytes, "max_output_bytes": limits.max_output_bytes}}


def _prepare_page(index, root, manifest, receipt, chain, start, inferred_before, remaining, *, retain_targets=True):
    _require(type(retain_targets) is bool, "exact target retention mode required")
    r, saved, provenance = root.to_dict(), chain[0][1], chain[0][2]
    limits = CodebaseScanResumeLimits.from_dict(r["limits"])
    end = min(start + limits.page_entries, len(r["members"]))
    units = {unit.source_key: unit for unit in manifest.units}
    selected = {item.path: item for item in [training.CodebaseTrainingSelection.from_dict(row)
                                           for row in provenance["selections"]]}
    vocabulary = numerical.prepare_inventory_vocabulary(saved["feature_space"])
    request, entries, inferred = _payload(root, saved), [], inferred_before
    accepted = 0
    request_bytes = len(_wire(request)) if r["optimized"] else None
    target_limits = targets.CodebaseTargetLimits(max_source_bytes=limits.max_file_bytes,
                                                  max_target_bytes=limits.max_target_bytes)
    known_errors = {
        "source or contract AST exceeds the bounded target profile": ("unsupported_target", "native_ast_shape_profile_bound"),
        "function inventory exceeds the target profile": ("unsupported_target", "native_function_count_profile_bound"),
        "contract identity or condition inventory exceeds the profile": ("unsupported_target", "authored_contract_inventory_profile_bound"),
        "captured source exceeds the target profile": ("deferred_budget", "native_source_byte_profile_bound"),
        "CodebaseIR target exceeds its byte bound": ("deferred_budget", "native_serialization_byte_profile_bound")}
    for ordinal in range(start, end):
        remaining()
        entry = manifest.snapshot.entries[ordinal]
        unit = units[entry.source_key]
        raw, record = _member_native(index, manifest, entry, unit, limits, remaining,
                                     snapshot_cid=r["head"]["snapshot_cid"] if r["optimized"] else None)
        disposition, frontiers = _member_disposition(entry, unit, record)
        if disposition == "unsupported_extension":
            disposition = "unsupported_target"
        row = {"member_index": ordinal, "source_key": entry.source_key, "entry_cid": entry.entry_cid,
            "disposition": disposition, "reason": None if not frontiers else frontiers[0]["reason"],
            "target_sha256": None, "source_digest": None, "coverage": [], "inference_index": None}
        if disposition == "captured_python":
            selection = selected.get(entry.path)
            specs = targets._specs(selection.contracts if selection else (), target_limits)
            try:
                target = targets._prepare_bound(binding=targets._binding(_head(r["head"]), manifest, entry, unit, raw),
                    manifest=manifest, receipt=receipt, ast_record=record, raw=raw, specs=specs, limits=target_limits)
            except targets.CodebaseTargetError as exc:
                if type(exc) is not targets.CodebaseTargetError or str(exc) not in known_errors:
                    raise
                row["disposition"], row["reason"] = known_errors[str(exc)]
            else:
                target_value = target.to_dict()
                row["target_sha256"], row["source_digest"] = hashlib.sha256(target.canonical_bytes).hexdigest(), target_value["source_digest"]
                if target_value["ready_for_training"] is not True:
                    row["disposition"], row["reason"] = "unsupported_target", "native_target_not_complete"
                else:
                    coverage = numerical.inventory_target_coverage(vocabulary, target)
                    row["coverage"] = coverage["coverage"]
                    if not coverage["compatible"]:
                        row["disposition"], row["reason"] = "feature_incompatible", "projection_has_no_known_atoms"
                    elif inferred >= limits.max_inferred_rows:
                        row["disposition"], row["reason"] = "deferred_budget", "global_inferred_row_budget"
                    else:
                        if r["optimized"]:
                            # Only the two initially empty arrays grow. One
                            # serialization per actual target retains exact
                            # finite JSON escaping and integer digit widths.
                            charge = len(_wire(target_value)) + len(str(ordinal)) + (2 if accepted else 0)
                            fits = request_bytes + charge + 64 <= limits.max_input_bytes
                        else:
                            request["targets"].append(target_value)
                            request["member_indices"].append(ordinal)
                            fits = len(_wire(request)) + 64 <= limits.max_input_bytes
                        if not fits:
                            if not r["optimized"]:
                                request["targets"].pop()
                                request["member_indices"].pop()
                            row["disposition"], row["reason"] = "deferred_budget", "page_worker_input_byte_budget"
                        else:
                            if r["optimized"]:
                                request_bytes += charge
                                if retain_targets:
                                    request["targets"].append(target_value)
                                    request["member_indices"].append(ordinal)
                            row["disposition"], row["reason"] = "inferred", None
                            row["inference_index"] = accepted
                            accepted += 1
                            inferred += 1
                del target_value, target
        entries.append(row)
        del raw, record
    if r["optimized"] and retain_targets:
        _require(len(_wire(request)) == request_bytes, "incremental exact worker byte charge differs")
    remaining()
    _require(manifest.cid == r["head"]["manifest_cid"]
             and manifest.snapshot.snapshot_cid == r["head"]["snapshot_cid"],
             "page native manifest changed during target replay")
    return entries, request


def _replay_page(index, root, manifest, receipt, chain, page, inferred_before, remaining):
    _bind_page(page, root)
    p = page.to_dict()
    expected, request = _prepare_page(index, root, manifest, receipt, chain, p["start"], inferred_before, remaining,
                                     retain_targets=not root.to_dict()["optimized"])
    _require(_wire(p["entries"]) == _wire(expected), "native receiving dispositions/target/coverage differ")
    del request
    # Numerical floats and producer accounting are shape-checked advisory
    # bytes, not authenticated execution. No forward pass or fit occurs here.


def _worker(request, lease, signal, remaining, memory_mb, limits):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_resume_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    executable, script = Path(sys.executable).resolve(), Path(worker.__file__).resolve()
    spec = importlib.util.find_spec("torch")
    _require(spec is not None and spec.origin is not None, "installed numerical dependency required")
    libraries = list(dict.fromkeys((str(Path(sysconfig.get_path("purelib")).resolve()),
                                   str(Path(spec.origin).resolve().parent.parent))))
    _require(all(Path(path).is_dir() for path in libraries), "installed numerical library roots required")
    executable_sha, script_sha = hashlib.sha256(executable.read_bytes()).hexdigest(), hashlib.sha256(script.read_bytes()).hexdigest()
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
    with lease.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=1, memory_mb=memory_mb, child_process_slots=1,
            timeout=remaining(), cancel_event=signal, request_id="codebase-inventory-resume:page-inference") as child:
        request["max_seconds"] = min(600.0, remaining())
        raw = _wire(request)
        _require(len(raw) <= limits.max_input_bytes, "page worker input byte bound exceeded")
        bounds = ToolRunLimits(timeout_seconds=remaining(), resident_memory_bytes=memory_mb * _MIB,
            max_output_bytes=limits.max_output_bytes, max_input_bytes=limits.max_input_bytes,
            max_workspace_bytes=limits.max_input_bytes + limits.max_output_bytes)
        process = run_bounded_stdin_tool([str(executable), "-I", "-B", str(script), json.dumps(libraries)], raw,
            runner=runner, limits=bounds, cancellation=child.combined_cancellation_signal(signal))
    remaining()
    _require(process.returncode == 0 and not any((process.timed_out, process.cancelled, process.unavailable,
        process.output_truncated, process.resource_exhausted)) and process.workspace_cleaned,
        "resume numerical child failed: " + str(process.termination_reason or process.error or "execution error")
        + ": " + process.stderr[-2048:])
    _require(hashlib.sha256(executable.read_bytes()).hexdigest() == executable_sha
             and hashlib.sha256(script.read_bytes()).hexdigest() == script_sha, "resume numerical producer changed")
    response = json.loads(process.stdout, object_pairs_hook=worker._json_pairs, parse_constant=worker._json_constant)
    receipt = {"executable_sha256": executable_sha, "worker_sha256": script_sha,
        "input_sha256": hashlib.sha256(raw).hexdigest(), "output_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
        "input_bytes": len(raw), "output_bytes": len(process.stdout.encode()), "elapsed_ms": process.elapsed_ms,
        "returncode": process.returncode, "workspace_cleaned": process.workspace_cleaned,
        "limits": {"resident_memory_bytes": bounds.resident_memory_bytes, "max_input_bytes": bounds.max_input_bytes,
                   "max_output_bytes": bounds.max_output_bytes},
        "memory_enforcement": "sampled_process_tree_rss_with_possible_overshoot", "source_execution_attested": False}
    _closed(response, {"schema", "optimized", "inference", "counters", "worker"}, "page numerical response")
    _require(response["schema"] == worker.SCHEMA and response["optimized"] is request["optimized"], "page worker profile differs")
    count = len(request["targets"])
    expected_counters = {"native_target_replays": (1 if request["optimized"] else 2) * count,
        "matrix_builds": 1, "vocabulary_builds": 1,
        "weight_tensor_builds": 4, "input_tensor_builds": 1,
        "contract_validations": 1 if request["optimized"] else 2,
        "state_validations": 1 if request["optimized"] else 2, "rows": count, "training_calls": 0}
    _require(type(response["counters"]) is dict and all(type(value) is int for value in response["counters"].values())
             and response["counters"] == expected_counters, "numerical worker accounting differs")
    _closed(response["worker"], {"python", "torch", "device", "dtype", "cpu_threads", "repository_code_executed",
        "registry_opened", "training_executed", "proof_authority", "decoded_formulas_generated"}, "worker profile")
    profile = response["worker"]
    _require(type(profile["python"]) is str and type(profile["torch"]) is str and profile["device"] == "cpu"
             and profile["dtype"] == "float64" and type(profile["cpu_threads"]) is int and profile["cpu_threads"] == 1
             and all(profile[key] is False for key in ("repository_code_executed", "registry_opened", "training_executed",
                                                       "proof_authority", "decoded_formulas_generated")), "numerical worker authority differs")
    return response["inference"], receipt


def start_current_codebase_scan(index, repository, *, expected_head, registry, version_id, limits=None,
        optimized=True, scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    """Persist an immutable complete root using one existing source-bound model."""
    _require(type(expected_head) is CodebaseHead and type(optimized) is bool, "exact native head and opt-out required")
    training._text(version_id, "version_id")
    limits = CodebaseScanResumeLimits() if limits is None else limits
    _require(type(limits) is CodebaseScanResumeLimits, "exact resume limits required")
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (_, _, remaining):
        before = legacy._registry_inventory(registry, legacy.CodebaseInventoryScanLimits(), remaining)
        implementation = _implementation()
        manifest, receipt = _observe(index, repository, expected_head, limits, remaining, memory_mb, optimized=optimized)
        chain = _resume_lineage(index, registry, version_id, training.CodebaseFeatureTrainingLimits(),
                                remaining, optimized=optimized)
        remaining()
        _require(_wire(chain[0][2]["head"]) == _wire(expected_head.to_dict()), "selected model is not bound to current head")
        members = _members(manifest)
        value = {"schema": ROOT_SCHEMA, "head": expected_head.to_dict(), "head_cid": cid_for_structured(expected_head.to_dict()),
            "members": members, "membership_cid": cid_for_structured(members), "model": _model(chain), "limits": limits.to_dict(),
            "optimized": optimized, "implementation": implementation, "authority": dict(_FALSE)}
        root = CodebaseScanResumeRoot.from_dict(cid_for_structured(value), value)
        _history_fence(index, chain, expected_head, limits, remaining, optimized=optimized)
        del manifest, receipt
        remaining()
        _require(index.artifacts.put(value) == root.artifact_cid, "durable root publication differs")
        _close(index, repository, root, registry, chain, before, remaining, memory_mb)
        remaining()
        return root


def scan_current_codebase_page(index, repository, *, root, registry, cursor=None, scheduler=None, parent_lease=None,
        cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Resume exactly one contiguous page; every budget refusal stays explicit."""
    _require(cursor is None or type(cursor) is CodebaseScanResumeCursor, "exact root-bound cursor required")
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (lease, signal, remaining):
        manifest, receipt, chain, before = _entry(index, repository, root, registry, remaining, memory_mb)
        r = root.to_dict()
        limits = CodebaseScanResumeLimits.from_dict(r["limits"])
        replay = lambda page, inferred: _replay_page(index, root, manifest, receipt, chain, page, inferred, remaining)
        if cursor is None:
            start, previous, inferred = 0, None, 0
        else:
            _require(cursor.root_cid == root.artifact_cid, "cursor belongs to another root")
            descriptors, start, inferred, _ = _walk(index.artifacts, root, cursor.previous_page_cid, remaining, replay)
            _require(start == cursor.next_offset and len(descriptors) < limits.max_pages, "cursor offset/prefix differs")
            previous = cursor.previous_page_cid
        _require(start < len(r["members"]), "no remaining members; complete the durable chain")
        entries, request = _prepare_page(index, root, manifest, receipt, chain, start, inferred, remaining)
        inference = worker_receipt = None
        if request["targets"]:
            inference, worker_receipt = _worker(request, lease, signal, remaining, memory_mb, limits)
        del request, manifest, receipt
        end = start + len(entries)
        counts = dict(sorted(Counter(row["disposition"] for row in entries).items()))
        value = {"schema": PAGE_SCHEMA, "root_cid": root.artifact_cid, "head_cid": r["head_cid"],
            "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"],
            "start": start, "end": end, "total_entries": len(r["members"]),
            "page_membership_cid": cid_for_structured(r["members"][start:end]), "previous_page_cid": previous,
            "entries": entries, "inference": inference, "worker_receipt": worker_receipt,
            "coverage": {"inventory_entries": len(entries), "inferred_rows": counts.get("inferred", 0), "dispositions": counts},
            "authority": dict(_FALSE)}
        raw = _wire(value)
        page = CodebaseScanResumePage(cid_for_bytes(raw), raw)
        _bind_page(page, root)
        remaining()
        _require(index.artifacts.put_bytes(raw) == page.artifact_cid, "atomic durable page publication differs")
        _close(index, repository, root, registry, chain, before, remaining, memory_mb)
        remaining()
        return page


def validate_current_codebase_scan_page(page, index, repository, *, root, registry, scheduler=None, parent_lease=None,
        cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Replay a stored prefix and live bindings without forward inference/fits."""
    _require(type(page) is CodebaseScanResumePage, "exact native resume page required")
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (_, _, remaining):
        manifest, receipt, chain, before = _entry(index, repository, root, registry, remaining, memory_mb)
        _require(load_codebase_scan_resume_page(index.artifacts, page.artifact_cid)._payload == page._payload,
                 "durable page bytes differ")
        _walk(index.artifacts, root, page.artifact_cid, remaining,
            lambda item, inferred: _replay_page(index, root, manifest, receipt, chain, item, inferred, remaining))
        del manifest, receipt
        _close(index, repository, root, registry, chain, before, remaining, memory_mb)
        return page


def _completion_value(root, descriptors, offset, inferred, counts):
    r = root.to_dict()
    _require(offset == len(r["members"]), "incomplete prefix is unknown, never absence/completion")
    return {"schema": COMPLETION_SCHEMA, "root_cid": root.artifact_cid, "head_cid": r["head_cid"],
        "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"], "pages": descriptors,
        "coverage": {"inventory_entries": offset, "inferred_rows": inferred, "pages": len(descriptors), "dispositions": counts},
        "authority": dict(_FALSE)}


def complete_current_codebase_scan(index, repository, *, root, registry, tail_page_cid=None, scheduler=None,
        parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Persist completeness only after replaying the entire ordered native chain."""
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (_, _, remaining):
        manifest, receipt, chain, before = _entry(index, repository, root, registry, remaining, memory_mb)
        descriptors, offset, inferred, counts = _walk(index.artifacts, root, tail_page_cid, remaining,
            lambda item, prior: _replay_page(index, root, manifest, receipt, chain, item, prior, remaining))
        value = _completion_value(root, descriptors, offset, inferred, counts)
        completion = CodebaseScanResumeCompletion.from_dict(cid_for_structured(value), value)
        _bind_completion(value, root)
        del manifest, receipt
        remaining()
        _require(index.artifacts.put(value) == completion.artifact_cid, "durable completeness publication differs")
        _close(index, repository, root, registry, chain, before, remaining, memory_mb)
        remaining()
        return completion


def validate_current_codebase_scan_completion(completion, index, repository, *, root, registry, scheduler=None,
        parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Fresh native receiving replay; advisory numbers are never execution trust."""
    _require(type(completion) is CodebaseScanResumeCompletion, "exact native completion required")
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (_, _, remaining):
        manifest, receipt, chain, before = _entry(index, repository, root, registry, remaining, memory_mb)
        _require(load_codebase_scan_resume_completion(index.artifacts, completion.artifact_cid)._payload == completion._payload,
                 "durable completion bytes differ")
        c = completion.to_dict()
        _bind_completion(c, root)
        tail = c["pages"][-1]["page_cid"] if c["pages"] else None
        descriptors, offset, inferred, counts = _walk(index.artifacts, root, tail, remaining,
            lambda item, prior: _replay_page(index, root, manifest, receipt, chain, item, prior, remaining))
        _require(canonical_dag_json_bytes(c) == canonical_dag_json_bytes(
            _completion_value(root, descriptors, offset, inferred, counts)), "native receiving completion ledger differs")
        del manifest, receipt
        _close(index, repository, root, registry, chain, before, remaining, memory_mb)
        return completion


__all__ = ["CodebaseScanResumeError", "CodebaseScanResumeLimits", "CodebaseScanResumeRoot", "CodebaseScanResumeCursor",
    "CodebaseScanResumePage", "CodebaseScanResumeCompletion", "start_current_codebase_scan", "scan_current_codebase_page",
    "complete_current_codebase_scan", "validate_current_codebase_scan_page", "validate_current_codebase_scan_completion",
    "validate_codebase_scan_completion_refs", "load_codebase_scan_resume_root", "load_codebase_scan_resume_page",
    "load_codebase_scan_resume_completion"]
