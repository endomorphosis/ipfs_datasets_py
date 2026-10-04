"""Bounded current inventory joined to historical conditional evidence.

Features nominate captured units; they never nominate a checked property. This
profile does not execute source, fit a model, launch a solver, publish a cache,
or discharge a planning requirement. Identity checks are not execution trust.
Serialized byte bounds and cooperative deadlines are not RSS containment.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import (
    CodebaseVerificationCatalog, CodebaseVerificationProjection,
)
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
    CodebaseVerificationSelector, CodebaseVerificationQueryCursor,
    CodebaseVerificationQueryEntry, CodebaseVerificationQueryPage,
)
from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
from . import codebase_inventory_scan as scanner
from . import codebase_inventory_lineage as lineage
from . import codebase_source_training as training
from .codebase_ir import CodebaseUnit
from .codebase_ir_targets import CodebaseTargetLimits
from .codebase_resources import acquire_codebase_resources
from .content import cid_for_bytes, cid_for_structured, validate_cid
from .semantic_index.snapshot import SnapshotEntry, _raw_display

SCHEMA = "codebase-inventory-conditional-evidence@1"
PROFILE = "current_inventory_historical_conditional_evidence_v1"
REFS_SCHEMA = "codebase-inventory-evidence-advisory-refs@1"
CODEC = "canonical-finite-native-json/raw-cidv1"
_MIB = 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = {name: False for name in (
    "source_semantics_verified", "runtime_behavior_verified", "proof_authority",
    "execution_authority", "completion_authority", "mutation_authority",
    "admission_authority", "authoritative_cache_eligible", "behavioral_satisfaction",
    "training_executed", "decoded_formulas_generated", "repository_code_executed",
    "source_execution_attested", "scan_execution_attested",
)}
_EVIDENCE_FALSE = {name: False for name in (
    "kernel_checked", "source_runtime_semantics_verified", "behavioral_satisfaction",
    "authoritative_cache_eligible", "admission_authority", "completion_authority",
)}
_ENTRY_FIELDS = {"source_key", "entry_cid", "evidence_disposition", "evidence_entry_ids"}
_DISPOSITIONS = {"matched_complete", "no_exact_indexed_conditional_evidence",
                 "matched_partial", "unknown_budget"}


class CodebaseInventoryEvidenceError(ValueError):
    """A native binding, complete inventory, query, or closing fence differs."""


def _require(value, message):
    if not value:
        raise CodebaseInventoryEvidenceError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise CodebaseInventoryEvidenceError("finite inert native JSON required") from exc


def _closed(value, fields, name):
    _require(type(value) is dict and set(value) == set(fields), "closed " + name + " fields required")


def _cid(value, codecs=None):
    _require(type(value) is str, "native content identity required")
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise CodebaseInventoryEvidenceError("invalid native content identity") from exc


def _sha(value):
    _require(type(value) is str and _SHA.fullmatch(value), "complete SHA-256 identity required")


def _false(value, expected):
    _closed(value, expected, "authority")
    _require(all(flag is False for flag in value.values()), "authority flags must be exact False")


def _integer(value, maximum, *, minimum=0):
    _require(type(value) is int and minimum <= value <= maximum, "bounded exact integer required")


@dataclass(frozen=True, slots=True)
class CodebaseInventoryEvidenceLimits:
    page_size: int = 16
    max_pages: int = 16
    max_evidence_entries: int = 256
    max_query_bytes: int = 16 * _MIB
    max_output_bytes: int = 32 * _MIB

    def __post_init__(self):
        for name, maximum in zip(self.__dataclass_fields__, (64, 16, 256, 16 * _MIB, 32 * _MIB)):
            _integer(getattr(self, name), maximum, minimum=1)

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _selector(value):
    _require(type(value) is CodebaseVerificationSelector, "exact native evidence selector required")
    result = CodebaseVerificationSelector.from_dict(value.to_dict())
    _require(result.dependency_kind is None and result.dependency_value is None,
             "dependency selectors require a separately qualified receiving profile")
    return result


def _model_shape(model):
    _closed(model, {"version_id", "variant_id", "artifact", "artifact_cid", "contract_sha256",
        "state_sha256", "feature_space_sha256", "runtime_version", "optimized", "basis_policy",
        "dtype", "device"}, "scan model")
    for name in ("version_id", "variant_id", "runtime_version"):
        _require(type(model[name]) is str and 0 < len(model[name]) <= 512, "bounded model identity required")
    _closed(model["artifact"], {"sha256", "bytes"}, "model artifact")
    _sha(model["artifact"]["sha256"])
    _integer(model["artifact"]["bytes"], 16 * _MIB, minimum=1)
    _cid(model["artifact_cid"], {"raw"})
    from multiformats import CID
    _require(bytes(CID.decode(model["artifact_cid"]).raw_digest).hex() == model["artifact"]["sha256"],
             "model checkpoint CID does not bind its SHA-256")
    for name in ("contract_sha256", "state_sha256", "feature_space_sha256"):
        _sha(model[name])
    _require(type(model["optimized"]) is bool and model["basis_policy"] == "unchanged_registered_vocabulary"
             and model["dtype"] == "float64" and model["device"] == "cpu"
             and model["runtime_version"] == training.runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
             "source-bound structural model profile differs")


def _scan_shape(scan, head):
    _closed(scan, {"artifact_cid", "record"}, "scan reference")
    raw = _wire(scan["record"])
    _require(len(raw) <= 16 * _MIB, "scan record exceeds receiving byte bound")
    scanner.CodebaseInventoryScanRecord(scan["artifact_cid"], raw)
    body = scan["record"]
    _require(_wire(body["head"]) == _wire(head.to_dict()), "scan full head differs")
    _model_shape(body["model"])
    limits = scanner.CodebaseInventoryScanLimits(**body["limits"])
    _require(len(body["entries"]) <= limits.max_entries, "scan inventory exceeds declared bounds")
    _require(len({row["entry_cid"] for row in body["entries"]}) == len(body["entries"]),
             "captured entry identities must be unique")
    previous = None
    for row in body["entries"]:
        _closed(row, {"path", "source_key", "raw_path_hex", "source_size_bytes", "source_sha256",
            "captured_source_available", "entry_cid", "source_cid", "ast_cid", "parse_status",
            "disposition", "frontiers", "cohort_membership", "authored_contracts_origin", "target_sha256",
            "source_digest", "coverage", "shard_index", "inference"}, "scan member")
        raw_path = row["raw_path_hex"]
        _require(type(raw_path) is str and 0 < len(raw_path) <= 8192, "bounded captured raw path required")
        try:
            _require(bytes.fromhex(raw_path).hex() == raw_path, "canonical captured raw path required")
        except ValueError as exc:
            raise CodebaseInventoryEvidenceError("canonical captured raw path required") from exc
        _require(row["source_key"] == "raw:" + raw_path and (previous is None or raw_path > previous),
                 "complete scan members must have unique native order")
        _require(row["path"] == _raw_display(bytes.fromhex(raw_path)), "scan display path differs from captured raw path")
        previous = raw_path
        _require(type(row["path"]) is str and type(row["parse_status"]) is str
                 and type(row["captured_source_available"]) is bool,
                 "exact native source observation fields required")
        _cid(row["entry_cid"], {"dag-json"})
        for name, codecs in (("source_cid", {"raw"}), ("ast_cid", {"dag-json", "raw"})):
            if row[name] is not None:
                _cid(row[name], codecs)
        if row["source_size_bytes"] is not None:
            _integer(row["source_size_bytes"], 2**63 - 1)
        for name in ("source_sha256", "target_sha256", "source_digest"):
            if row[name] is not None:
                _sha(row[name])
        _require(row["captured_source_available"] == (row["source_sha256"] is not None),
                 "scan source availability differs from captured digest")
        CodebaseUnit(row["source_key"], row["entry_cid"], row["ast_cid"], row["parse_status"])
        _require(type(row["frontiers"]) is list and type(row["coverage"]) is list,
                 "native coverage and frontier lists required")
        for coverage in row["coverage"]:
            _closed(coverage, {"projection_id", "known_atoms", "unknown_atoms"}, "feature coverage")
            _require(type(coverage["projection_id"]) is str, "native projection identity required")
            _integer(coverage["known_atoms"], 2**63 - 1)
            _integer(coverage["unknown_atoms"], 2**63 - 1)
        if row["disposition"] == "inferred":
            _integer(row["shard_index"], 15)
            inf = row["inference"]
            _closed(inf, {"source_digest", "latent", "reconstructed_projection_features"}, "scan inference")
            _require(inf["source_digest"] == row["source_digest"] and type(inf["latent"]) is list
                     and 1 <= len(inf["latent"]) <= 4096
                     and type(inf["reconstructed_projection_features"]) is dict,
                     "inference source identity or layout differs")
            numbers = list(inf["latent"])
            for values in inf["reconstructed_projection_features"].values():
                _require(type(values) is list and len(values) <= 1024, "bounded feature rows required")
                numbers.extend(values)
            _require(all(type(n) in (int, float) and math.isfinite(n) for n in numbers),
                     "finite exact numerical observations required")
        else:
            _require(row["inference"] is None and row["shard_index"] is None,
                     "noninferred member cannot carry numerical observations")
    return body


def _source_binding(value, head):
    _closed(value, {"head", "path", "entry", "content_sha256", "ast_cid", "source_revision"}, "evidence source binding")
    entry = SnapshotEntry.from_dict(value["entry"])
    _require(_wire(value["head"]) == _wire(head.to_dict())
        and value["path"] == entry.path
        and value["source_revision"] == "snapshot:" + head.snapshot_cid,
        "evidence exact source/unit/head binding differs")
    _cid(value["ast_cid"], {"dag-json"})
    _sha(value["content_sha256"])
    return entry


def _keys(contract):
    _closed(contract, {"contract_id", "requested_contract", "contract_cid", "lowered_contract_cid",
        "domain_id", "domain_cid", "canonical_keys", "applicability_keys"}, "conditional contract")
    _require(type(contract["requested_contract"]) is dict
             and type(contract["contract_id"]) is str and contract["requested_contract"].get("contract_id")
             == contract["contract_id"], "authored conditional contract identity differs")
    _require(cid_for_structured(contract["requested_contract"]) == contract["contract_cid"],
             "complete authored conditional contract CID differs")
    from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
    requested = ContractSpec(**contract["requested_contract"])
    _require(_wire(requested.to_dict()) == _wire(contract["requested_contract"]),
             "native authored conditional contract fields differ")
    for name in ("contract_cid", "lowered_contract_cid", "domain_cid"):
        if contract[name] is not None:
            _cid(contract[name], {"dag-json"})
    _require((contract["domain_id"] is None) == (contract["domain_cid"] is None)
        and (contract["domain_id"] is None or type(contract["domain_id"]) is str and 0 < len(contract["domain_id"]) <= 512),
        "paired exact conditional domain identities required")
    identities = set()
    for field, fields in (("canonical_keys", {"key_id", "key", "obligation_id"}),
                          ("applicability_keys", {"key_id", "key", "kind", "obligation_id"})):
        _require(type(contract[field]) is list and len(contract[field]) <= 128, "bounded native canonical key inventory required")
        for item in contract[field]:
            _closed(item, fields, "canonical key")
            native = CanonicalProofCacheKey.from_dict(item["key"])
            _require(native.key_id == item["key_id"] and _wire(native.to_dict()) == _wire(item["key"]),
                     "canonical conditional key identity differs")
            identities.add(native.key_id)
    return sorted(identities)


def _summary_shape(value, head, selector, rows):
    _closed(value, {"query_entry", "source_binding", "contract", "dependencies", "verification_status",
        "applicability_status", "applicability_summary", "historical_records_observed_live", "authority"}, "evidence summary")
    _false(value["authority"], _EVIDENCE_FALSE)
    _require(value["historical_records_observed_live"] is False, "conditional evidence origin must remain historical")
    entry = _source_binding(value["source_binding"], head)
    contract, row = value["contract"], value["query_entry"]
    keys = _keys(contract)
    _closed(row, {"entry_id", "contract_id", "projection_cid", "verification_cid", "applicability_cid",
        "path", "contract_cid", "domain_id", "domain_cid", "canonical_key_ids"}, "query entry summary")
    for name in ("entry_id", "projection_cid", "verification_cid", "applicability_cid"):
        if name != "applicability_cid" or row[name] is not None:
            _cid(row[name], {"dag-json"})
    _require(row["entry_id"] == cid_for_structured({"projection_cid": row["projection_cid"], "contract_id": row["contract_id"]})
        and row["path"] == entry.path and row["contract_id"] == contract["contract_id"]
        and row["contract_cid"] == contract["contract_cid"] and row["domain_id"] == contract["domain_id"]
        and row["domain_cid"] == contract["domain_cid"] and row["canonical_key_ids"] == keys,
        "conditional query entry identity differs")
    selected = rows.get(entry.source_key)
    _require(selected is not None and selected["entry_cid"] == entry.entry_cid
        and selected["path"] == entry.path and selected["raw_path_hex"] == entry.raw_path_hex
        and selected["source_cid"] == entry.source_cid and selected["source_size_bytes"] == entry.size_bytes
        and selected["ast_cid"] == value["source_binding"]["ast_cid"]
        and selected["source_sha256"] == value["source_binding"]["content_sha256"],
        "conditional evidence does not bind an exact complete scan member")
    deps = value["dependencies"]
    _require(type(deps) is dict, "native conditional dependencies required")
    for name, expected in (("head_cid", cid_for_structured(head.to_dict())), ("manifest_cid", head.manifest_cid),
        ("snapshot_cid", head.snapshot_cid), ("ast_revision_id", head.ast_revision_id),
        ("source_cid", entry.source_cid), ("ast_cid", value["source_binding"]["ast_cid"]),
        ("content_sha256", value["source_binding"]["content_sha256"]),
        ("source_revision", value["source_binding"]["source_revision"]), ("verification_cid", row["verification_cid"])):
        _require(deps.get(name) == expected, "native conditional dependency binding differs")
    for query_name, row_name in (("path", "path"), ("contract_id", "contract_id"),
        ("expected_contract_cid", "contract_cid"), ("verification_cid", "verification_cid"),
        ("requested_domain_id", "domain_id"), ("requested_domain_cid", "domain_cid")):
        wanted = getattr(selector, query_name)
        _require(wanted is None or row[row_name] == wanted, "evidence summary differs from exact selector")
    _require(selector.canonical_key_id is None or selector.canonical_key_id in keys,
             "evidence summary lacks exact selected canonical key")
    _require(value["verification_status"] in {"recorded_conditional_proved", "recorded_conditional_refuted", "unknown"}
        and (value["applicability_status"] is None or type(value["applicability_status"]) is str),
        "recorded conditional status profile differs")
    if value["applicability_summary"] is None:
        _require(value["applicability_status"] is None and row["applicability_cid"] is None,
                 "absent applicability cannot carry domain status")
    else:
        app = value["applicability_summary"]
        _closed(app, {"parent_contract_id", "contract_cid", "function_name", "domain_id", "domain_cid",
            "status", "classifications", "premises_satisfiable", "requested_domain_satisfiable",
            "requested_domain_within_preconditions", "model_applicability_established", "domain_property_classification",
            "conditional_proved", "conditional_refuted"}, "selected applicability summary")
        _require(app.get("parent_contract_id") == contract["contract_id"]
            and app.get("contract_cid") == contract["lowered_contract_cid"]
            and app.get("domain_id") == contract["domain_id"] and app.get("domain_cid") == contract["domain_cid"]
            and app.get("function_name") == contract["requested_contract"]["function_name"]
            and app.get("status") == value["applicability_status"] and row["applicability_cid"] is not None,
            "selected conditional applicability identity differs")
        _require(type(app["classifications"]) is list and len(app["classifications"]) == 4
            and all(type(item) is str for item in app["classifications"]), "exact four native domain classifications required")
        from .codebase_applicability import _summaries
        bindings = {name: app[name] for name in ("parent_contract_id", "contract_cid", "function_name", "domain_id", "domain_cid")}
        rebuilt = _summaries([{**bindings, "differential": {"classification": item}} for item in app["classifications"]])[0]
        _require(_wire(rebuilt) == _wire(app), "native applicability status or typed conditional flags differ")


def _ledger(scan_rows, evidence, complete):
    matches = {row["source_key"]: [] for row in scan_rows}
    for item in evidence:
        source_key = "raw:" + item["source_binding"]["entry"]["raw_path_hex"]
        matches[source_key].append(item["query_entry"]["entry_id"])
    return [{"source_key": row["source_key"], "entry_cid": row["entry_cid"],
        "evidence_disposition": ("matched_complete" if matches[row["source_key"]] else
            "no_exact_indexed_conditional_evidence") if complete else
            ("matched_partial" if matches[row["source_key"]] else "unknown_budget"),
        "evidence_entry_ids": sorted(matches[row["source_key"]])} for row in scan_rows]


def _query_bytes(pages, evidence):
    # A zero-row budget result retains no page or evidence body. Its fixed
    # resume header belongs to the separately bounded output record.
    return len(_wire({"pages": pages, "evidence": evidence})) if pages or evidence else 0


def _query_shape(query, selector, head, limits, evidence):
    _closed(query, {"selector_cid", "inventory_cid", "epoch", "pages", "complete", "next_cursor", "closing_page_cid"}, "query ledger")
    _require(query["selector_cid"] == selector.cid and type(query["complete"]) is bool,
             "exact query selector and complete flag required")
    _cid(query["inventory_cid"], {"dag-json"})
    _cid(query["closing_page_cid"], {"dag-json"})
    _integer(query["epoch"], 2**63 - 1, minimum=1)
    _require(type(query["pages"]) is list and len(query["pages"]) <= limits.max_pages,
             "query page bound exceeded")
    start, previous, identities, page_cids, terminal = None, None, [], set(), False
    for wrapper in query["pages"]:
        _require(not terminal, "query cannot continue after a complete terminal page")
        _closed(wrapper, {"page_size", "page"}, "query page wrapper")
        _integer(wrapper["page_size"], limits.page_size, minimum=1)
        page = wrapper["page"]
        _closed(page, {"schema", "selector", "selector_cid", "head", "head_cid", "inventory_cid", "epoch",
            "entries", "start_cursor", "next_cursor", "complete", "authority", "page_cid"}, "query page")
        _require(page["schema"] == "codebase-verification-query-page@1"
            and _wire(page["selector"]) == _wire(selector.to_dict()) and page["selector_cid"] == selector.cid
            and _wire(page["head"]) == _wire(head.to_dict()) and page["head_cid"] == cid_for_structured(head.to_dict())
            and page["inventory_cid"] == query["inventory_cid"] and type(page["epoch"]) is int
            and page["epoch"] == query["epoch"] and type(page["complete"]) is bool
            and page["complete"] == (page["next_cursor"] is None)
            and _wire(page["start_cursor"]) == _wire(start), "query page head/inventory/continuation differs")
        _closed(page["authority"], {"historical_conditional_evidence", *_EVIDENCE_FALSE}, "query authority")
        _require(page["authority"]["historical_conditional_evidence"] is True and all(
            page["authority"][name] is False for name in _EVIDENCE_FALSE), "query authority profile differs")
        _require(type(page["entries"]) is list and len(page["entries"]) <= wrapper["page_size"],
                 "exact bounded query page entries required")
        _require(cid_for_structured({k: v for k, v in page.items() if k != "page_cid"}) == page["page_cid"],
                 "query page content identity differs")
        _require(page["page_cid"] not in page_cids, "query page identities must be unique")
        page_cids.add(page["page_cid"])
        for item in page["entries"]:
            identity = item["entry_id"]
            _require(previous is None or identity > previous, "query entry order is repeated or regressed")
            identities.append(identity)
            previous = identity
        if page["next_cursor"] is not None:
            cursor = CodebaseVerificationQueryCursor.from_dict(page["next_cursor"])
            _require(page["entries"] and cursor.head_cid == page["head_cid"]
                and cursor.inventory_cid == query["inventory_cid"] and cursor.epoch == query["epoch"]
                and cursor.selector_cid == selector.cid and cursor.after == previous, "query continuation binding differs")
        start = page["next_cursor"]
        terminal = page["complete"]
    _require([item["query_entry"]["entry_id"] for item in evidence] == identities,
             "query pages and conditional evidence summaries differ")
    _require(_wire([item["query_entry"] for item in evidence]) == _wire([
        item for wrapper in query["pages"] for item in wrapper["page"]["entries"]]),
        "query row summaries differ from immutable pages")
    _require(query["complete"] == bool(query["pages"] and query["pages"][-1]["page"]["complete"])
        and _wire(query["next_cursor"]) == _wire(start), "query completeness or resume root differs")
    _require(len(evidence) <= limits.max_evidence_entries
        and _query_bytes(query["pages"], evidence) <= limits.max_query_bytes,
        "aggregate evidence row or serialized byte bound exceeded")


@dataclass(frozen=True, slots=True)
class CodebaseInventoryEvidenceRecord:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _require(type(self._payload) is bytes and len(self._payload) <= 32 * _MIB,
                 "bounded immutable inventory evidence bytes required")
        try:
            value = json.loads(self._payload)
            _require(_wire(value) == self._payload and cid_for_bytes(self._payload) == self.artifact_cid,
                     "inventory evidence raw CID differs")
            _closed(value, {"schema", "profile", "codec", "head", "head_cid", "scan", "selector", "query",
                "evidence", "entries", "limits", "implementation", "authority"}, "inventory evidence")
            _require(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["codec"] == CODEC,
                     "inventory evidence profile differs")
            _false(value["authority"], _FALSE)
            head = CodebaseHead.from_dict(value["head"])
            _require(value["head_cid"] == cid_for_structured(head.to_dict()), "inventory evidence full head CID differs")
            limits = CodebaseInventoryEvidenceLimits(**value["limits"])
            _require(len(self._payload) <= limits.max_output_bytes, "inventory evidence output bound exceeded")
            selector = _selector(CodebaseVerificationSelector.from_dict(value["selector"]))
            scan = _scan_shape(value["scan"], head)
            _require(type(value["evidence"]) is list and type(value["entries"]) is list,
                     "native immutable evidence and inventory lists required")
            rows = {row["source_key"]: row for row in scan["entries"]}
            for item in value["evidence"]:
                _summary_shape(item, head, selector, rows)
            _query_shape(value["query"], selector, head, limits, value["evidence"])
            _require(_wire(value["entries"]) == _wire(_ledger(scan["entries"], value["evidence"], value["query"]["complete"])),
                     "complete inventory evidence dispositions differ")
            _closed(value["implementation"], {"files", "sha256", "scope"}, "implementation")
            _require(type(value["implementation"]["files"]) is dict and value["implementation"]["scope"]
                == "listed_local_files_only_not_execution_attestation", "implementation scope differs")
            for pin in value["implementation"]["files"].values():
                _sha(pin)
            _require(training.features.digest(value["implementation"]["files"]) == value["implementation"]["sha256"],
                     "implementation identity differs")
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, CodebaseInventoryEvidenceError):
                raise
            raise CodebaseInventoryEvidenceError("malformed bounded inventory evidence record") from exc

    def to_dict(self):
        return json.loads(self._payload)

    def advisory_refs(self):
        value = self.to_dict()
        model, query = value["scan"]["record"]["model"], value["query"]
        entries = value["entries"]
        return {"schema": REFS_SCHEMA, "artifact_cid": self.artifact_cid, "head": value["head"],
            "head_cid": value["head_cid"], "scan_artifact_cid": value["scan"]["artifact_cid"],
            "membership_cid": value["scan"]["record"]["membership"]["cid"],
            "model": {name: model[name] for name in ("version_id", "variant_id", "artifact_cid",
                "contract_sha256", "state_sha256", "feature_space_sha256")},
            "coverage": {"inventory_entries": len(entries),
                "inferred_rows": sum(row["disposition"] == "inferred" for row in value["scan"]["record"]["entries"]),
                "evidence_entries": len(value["evidence"]),
                "evidence_matched_members": sum(bool(row["evidence_entry_ids"]) for row in entries),
                "evidence_complete_absent_members": sum(row["evidence_disposition"] == "no_exact_indexed_conditional_evidence" for row in entries),
                "evidence_unknown_members": sum(row["evidence_disposition"] == "unknown_budget" for row in entries)},
            "query": {"selector_cid": query["selector_cid"], "inventory_cid": query["inventory_cid"],
                "epoch": query["epoch"], "complete": query["complete"], "next_cursor": query["next_cursor"],
                "page_cids": [wrapper["page"]["page_cid"] for wrapper in query["pages"]]},
            "entry_evidence": entries, "authority": dict(_FALSE)}


def _implementation():
    result = scanner._implementation()
    files = dict(result["files"])
    files[__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for module in ("ipfs_datasets_py.duckdb_control.codebase_verification_catalog",
                   "ipfs_datasets_py.duckdb_control.codebase_verification_queries",
                   "ipfs_datasets_py.duckdb_control.codebase_verification_projection",
                   "ipfs_datasets_py.logic.software_contracts.codebase_verification",
                   "ipfs_datasets_py.logic.software_contracts.codebase_applicability",
                   "ipfs_datasets_py.logic.common.canonical_cache_key"):
        import importlib
        files[module] = hashlib.sha256(Path(importlib.import_module(module).__file__).read_bytes()).hexdigest()
    return {"files": files, "sha256": training.features.digest(files), "scope": result["scope"]}


def _owners(index, registry, catalog):
    training._native_owners(index, registry)
    _require(type(catalog) is CodebaseVerificationCatalog and catalog.index is index
        and catalog.store is index.catalog.store and catalog.artifacts is index.artifacts,
        "one exact native structural and verification owner required")
    catalog._ensure_owner()


@contextmanager
def _scope(index, registry, catalog, *, scheduler, parent_lease, cancel_event,
           admission_timeout_seconds, timeout_seconds, memory_mb):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
    _owners(index, registry, catalog)
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 600,
             "bounded finite overall deadline required")
    _require(type(admission_timeout_seconds) in (int, float) and math.isfinite(admission_timeout_seconds)
        and admission_timeout_seconds >= 0, "bounded finite admission deadline required")
    _require(type(memory_mb) is int and memory_mb >= 1024, "at least 1024 MB shared admission required")
    # Nested scan keeps its original 236 MiB retained-byte bound plus our
    # 8 MiB owner snapshot. Later phases release the entry seal/cache before
    # queries: scan 16 + ancestry 32 + query 16 + owner 8 + native result 64
    # + normalized inventory 64 = 200 MiB. Final source fences have no page.
    _require(catalog.limits.max_result_bytes <= 64 * _MIB and catalog.limits.max_query_inventory_bytes <= 64 * _MIB,
             "catalog byte profile exceeds joined reservation")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
        timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("inventory evidence join cancelled")
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise LeaseTimeoutError("inventory evidence join deadline exceeded")
            return seconds
        remaining()
        yield lease, signal, remaining


def _observe(index, repository, head, lease, signal, remaining, admission, memory_mb, scan_limits):
    return scanner._observe(index, repository, head, lease=lease, signal=signal, remaining=remaining,
        admission=admission, memory_mb=memory_mb, target_limits=CodebaseTargetLimits(
            max_source_bytes=scan_limits.max_file_bytes, max_target_bytes=scan_limits.max_target_bytes))


def _match_scan_members(scan, seal):
    rows = scan["entries"]
    _require(len(rows) == len(seal.members), "scan omits or adds captured members")
    for row, member in zip(rows, seal.members):
        entry, unit = member.entry, member.unit
        exact = {"path": entry.path, "source_key": entry.source_key, "raw_path_hex": entry.raw_path_hex,
            "entry_cid": entry.entry_cid, "source_cid": entry.source_cid, "source_size_bytes": entry.size_bytes,
            "source_sha256": None if member.raw is None else hashlib.sha256(member.raw).hexdigest(),
            "captured_source_available": member.raw is not None, "ast_cid": unit.ast_cid, "parse_status": unit.parse_status}
        _require(_wire({name: row[name] for name in exact}) == _wire(exact), "scan captured source member differs")
        if member.disposition != "captured_python":
            disposition = "unsupported_target" if member.disposition == "unsupported_extension" else member.disposition
            _require(row["disposition"] == disposition, "native unsupported inventory disposition differs")


def _match_model(scan, chain):
    row, saved, provenance = chain[0][:3]
    model = scan["model"]
    expected = {"version_id": row["version_id"], "variant_id": row["variant_id"], "artifact": row["artifact"],
        "artifact_cid": cid_for_bytes(training._wire(saved)), "contract_sha256": saved["state"]["contract_sha256"],
        "state_sha256": training.features.digest(saved["state"]), "feature_space_sha256": training.features.digest(saved["feature_space"])}
    _require(_wire({name: model[name] for name in expected}) == _wire(expected)
        and _wire(provenance["head"]) == _wire(scan["head"]), "exact current-head model checkpoint differs")
    for member in scan["entries"]:
        inf = member["inference"]
        if inf is not None:
            _require(len(inf["latent"]) == saved["state"]["latent_width"] and
                set(inf["reconstructed_projection_features"]) == set(saved["feature_space"]["projection_ids"]),
                "recorded inference differs from exact frozen model layout")
            for name, values in inf["reconstructed_projection_features"].items():
                _require(len(values) == sum(column[0] == name for column in saved["feature_space"]["columns"]),
                         "recorded projection width differs from exact frozen basis")


def _summary(entry, head, selector, rows):
    from .codebase_verification import CodebaseVerificationRecord
    from .codebase_applicability import CodebaseApplicabilityRecord
    from . import codebase_verification, codebase_applicability
    from ipfs_datasets_py.duckdb_control import codebase_verification_catalog
    _require(type(entry) is CodebaseVerificationQueryEntry and type(entry.projection) is CodebaseVerificationProjection,
             "native query entry and historical projection required")
    entry.__post_init__()
    projection = entry.projection
    projection.__post_init__()
    _require(type(projection.verification) is CodebaseVerificationRecord and projection.verification.observed_live is False,
             "native historical verification record required")
    value, parent = projection.to_dict(), projection.verification.to_dict()
    _require(cid_for_structured(parent) == projection.verification.artifact_cid
        and _wire(value["source_binding"]) == _wire(parent["source_binding"])
        and value["verification_cid"] == projection.verification.artifact_cid,
        "projection and native verification source identities differ")
    _require(_wire(parent["authority"]) == _wire(codebase_verification._AUTHORITY)
        and _wire(value["authority"]) == _wire(codebase_verification_catalog._AUTHORITY),
        "historical verification cannot claim elevated authority")
    selected = [row for row in value["contracts"] if row["contract_id"] == entry.contract_id]
    _require(len(selected) == 1 and [item for item in parent["requested_contracts"]
        if item["contract_id"] == entry.contract_id] == [selected[0]["requested_contract"]],
        "projection authored contract differs from native verification")
    solved = [item for item in parent["pipeline_result"]["obligation_results"]
              if item["vc_obligation"]["parent_contract_id"] == entry.contract_id]
    status = ("recorded_conditional_refuted" if any(item["verdict_classification"] == "agree_disproved" for item in solved)
        else "recorded_conditional_proved" if solved and all(item["verdict_classification"] == "agree_proved" for item in solved)
        and parent["pipeline_result"]["status"] == "success" else "unknown")
    app_status = app_summary = None
    if projection.applicability is not None:
        _require(type(projection.applicability) is CodebaseApplicabilityRecord and projection.applicability.observed_live is False,
                 "native historical applicability record required")
        app = projection.applicability.to_dict()
        _require(cid_for_structured(app) == projection.applicability.artifact_cid
            and app["verification_cid"] == projection.verification.artifact_cid
            and _wire(app["source_binding"]) == _wire(parent["source_binding"])
            and _wire(app["authority"]) == _wire(codebase_applicability._AUTHORITY),
            "native linked applicability identity or authority differs")
        selected_app = [item for item in app["contract_results"] if item["parent_contract_id"] == entry.contract_id]
        _require(len(selected_app) == 1, "selected contract applicability inventory differs")
        app_summary = selected_app[0]
        app_status = app_summary["status"]
    summary = {"query_entry": entry.to_dict(), "source_binding": value["source_binding"], "contract": selected[0],
        "dependencies": value["dependencies"], "verification_status": status, "applicability_status": app_status,
        "applicability_summary": app_summary,
        "historical_records_observed_live": False, "authority": dict(_EVIDENCE_FALSE)}
    _summary_shape(summary, head, selector, rows)
    return summary


def _page(catalog, repository, head, selector, page_size, cursor, lease, signal, remaining, admission, memory_mb):
    result = catalog.query_current(repository, expected_head=head, selector=selector, page_size=page_size, cursor=cursor,
        parent_lease=lease, cancel_event=signal, admission_timeout_seconds=min(admission, remaining()),
        timeout_seconds=remaining(), memory_mb=memory_mb)
    remaining()
    _require(type(result) is CodebaseVerificationQueryPage and type(result.head) is CodebaseHead
        and type(result.selector) is CodebaseVerificationSelector and type(result.entries) is tuple,
        "native exact query page required")
    result.__post_init__()
    _require(_wire(result.head.to_dict()) == _wire(head.to_dict()) and _wire(result.selector.to_dict()) == _wire(selector.to_dict())
        and _wire(None if result.start_cursor is None else result.start_cursor.to_dict()) == _wire(None if cursor is None else cursor.to_dict())
        and len(result.entries) <= page_size, "returned native query page differs from request")
    return result


def _replay_model(index, registry, scan, seal, remaining):
    _require(_wire(scan["implementation"]) == _wire(scanner._implementation()),
             "retained scan implementation generation differs")
    replay = lineage.replay_inventory_lineage(index, registry, scan["model"]["version_id"],
        training.CodebaseFeatureTrainingLimits(), current_seal=seal, checkpoint=remaining)
    _match_model(scan, replay.chain)
    heads = scanner._history_heads(replay.chain, binding=replay.context.binding)
    replay.context.release_historical_seals()
    return replay.chain, heads


def _close(index, repository, head, registry, catalog, scan, query, selector, chain, heads, history,
           registry_before, implementation, lease, signal, remaining, admission, memory_mb, scan_limits):
    _owners(index, registry, catalog)
    closing = _page(catalog, repository, head, selector, 1, None, lease, signal, remaining, admission, memory_mb)
    _require(closing.inventory_cid == query["inventory_cid"] and type(closing.epoch) is int and closing.epoch == query["epoch"],
             "conditional evidence inventory changed before return")
    closing_cid = closing.page_cid
    del closing
    seal = _observe(index, repository, head, lease, signal, remaining, admission, memory_mb, scan_limits)
    _match_scan_members(scan, seal)
    _require(scanner._history_fence(index, heads, remaining, seal) == history,
             "historical source evidence changed during join")
    del seal
    scanner._model_fence(registry, chain, remaining)
    _require(scanner._registry_inventory(registry, scan_limits, remaining) == registry_before,
             "model owner changed during inventory evidence join")
    _require(_implementation() == implementation, "inventory evidence implementation changed")
    # This is a final sequential observation, not an atomic snapshot across
    # independently owned model/source/evidence stores. A same-head append or
    # rebuild during the intervening source/model checks must still reject.
    final = _page(catalog, repository, head, selector, 1, None, lease, signal, remaining, admission, memory_mb)
    _require(final.inventory_cid == query["inventory_cid"] and type(final.epoch) is int and final.epoch == query["epoch"]
        and final.page_cid == closing_cid, "conditional evidence inventory changed during final fences")
    del final
    remaining()
    return closing_cid


def scan_current_codebase_evidence(index, repository, *, expected_head, registry, version_id,
        verification_catalog, selector=None, optimized=True, limits=None, scan_limits=None, scheduler=None, parent_lease=None,
        cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Return complete captured membership and an explicitly bounded evidence query.

    The exact selector scopes absence. Partial queries retain a root-bound
    continuation; an unconsumed first page uses ``next_cursor=None`` with
    ``complete=False`` and no pages, indicating restart at that sealed root.
    Empty native evidence inventories may be initialized by query_current.
    """
    _require(type(expected_head) is CodebaseHead and type(optimized) is bool, "exact head and boolean opt-out required")
    expected_head.__post_init__()
    selector = _selector(CodebaseVerificationSelector() if selector is None else selector)
    limits = CodebaseInventoryEvidenceLimits() if limits is None else limits
    _require(type(limits) is CodebaseInventoryEvidenceLimits, "native bounded evidence limits required")
    scan_limits = scanner.CodebaseInventoryScanLimits() if scan_limits is None else scan_limits
    _require(type(scan_limits) is scanner.CodebaseInventoryScanLimits, "native narrowed inventory scan limits required")
    with _scope(index, registry, verification_catalog, scheduler=scheduler, parent_lease=parent_lease,
        cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
        timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (lease, signal, remaining):
        implementation = _implementation()
        _require(limits.page_size <= verification_catalog.limits.max_query_page_size, "query page exceeds catalog bound")
        registry_before = scanner._registry_inventory(registry, scan_limits, remaining)
        record = scanner.scan_current_codebase_features(index, repository, expected_head=expected_head,
            registry=registry, version_id=version_id, optimized=optimized, parent_lease=lease,
            limits=scan_limits,
            cancel_event=signal, admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
            timeout_seconds=remaining(), memory_mb=memory_mb)
        _require(type(record) is scanner.CodebaseInventoryScanRecord, "native fresh inventory scanner record required")
        scan = {"artifact_cid": record.artifact_cid, "record": record.to_dict()}
        del record
        body = _scan_shape(scan, expected_head)
        seal = _observe(index, repository, expected_head, lease, signal, remaining, admission_timeout_seconds, memory_mb, scan_limits)
        _match_scan_members(body, seal)
        chain, heads = _replay_model(index, registry, body, seal, remaining)
        history = scanner._history_fence(index, heads, remaining, seal)
        del seal
        rows = {row["source_key"]: row for row in body["entries"]}
        pages, evidence, cursor, inventory, epoch, complete = [], [], None, None, None, False
        for _ in range(limits.max_pages):
            remaining()
            size = min(limits.page_size, limits.max_evidence_entries - len(evidence))
            if not size:
                break
            page = _page(verification_catalog, repository, expected_head, selector, size, cursor,
                lease, signal, remaining, admission_timeout_seconds, memory_mb)
            if inventory is None:
                inventory, epoch = page.inventory_cid, page.epoch
            _require(page.inventory_cid == inventory and type(page.epoch) is int and page.epoch == epoch,
                     "conditional evidence inventory changed between pages")
            summaries = [_summary(entry, expected_head, selector, rows) for entry in page.entries]
            wrapper = {"page_size": size, "page": page.to_dict()}
            next_cursor, page_complete = page.next_cursor, page.complete
            del page
            if _query_bytes([*pages, wrapper], [*evidence, *summaries]) > limits.max_query_bytes:
                del wrapper, summaries
                break
            pages.append(wrapper)
            evidence.extend(summaries)
            del wrapper, summaries
            cursor, complete = next_cursor, page_complete
            if complete:
                break
        query = {"selector_cid": selector.cid, "inventory_cid": inventory, "epoch": epoch,
            "pages": pages, "complete": complete, "next_cursor": None if cursor is None else cursor.to_dict(),
            "closing_page_cid": None}
        query["closing_page_cid"] = _close(index, repository, expected_head, registry, verification_catalog,
            body, query, selector, chain, heads, history, registry_before, implementation, lease, signal,
            remaining, admission_timeout_seconds, memory_mb, scan_limits)
        value = {"schema": SCHEMA, "profile": PROFILE, "codec": CODEC, "head": expected_head.to_dict(),
            "head_cid": cid_for_structured(expected_head.to_dict()), "scan": scan, "selector": selector.to_dict(),
            "query": query, "evidence": evidence, "entries": _ledger(body["entries"], evidence, complete),
            "limits": limits.to_dict(), "implementation": implementation, "authority": dict(_FALSE)}
        raw = _wire(value)
        _require(len(raw) <= limits.max_output_bytes, "joined record output byte bound exceeded")
        result = CodebaseInventoryEvidenceRecord(cid_for_bytes(raw), raw)
        remaining()
        return result


def validate_current_inventory_evidence(record, index, repository, *, registry, verification_catalog,
        expected_head=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Freshly replay an inert join before reuse, with no forward inference or fitting."""
    _require(type(record) is CodebaseInventoryEvidenceRecord, "native immutable inventory evidence record required")
    record = CodebaseInventoryEvidenceRecord(record.artifact_cid, record._payload)
    value = record.to_dict()
    head = CodebaseHead.from_dict(value["head"])
    _require(expected_head is None or type(expected_head) is CodebaseHead and _wire(expected_head.to_dict()) == _wire(head.to_dict()),
             "reused inventory evidence belongs to another full head")
    selector = _selector(CodebaseVerificationSelector.from_dict(value["selector"]))
    scan, query = value["scan"]["record"], value["query"]
    scan_limits = scanner.CodebaseInventoryScanLimits(**scan["limits"])
    with _scope(index, registry, verification_catalog, scheduler=scheduler, parent_lease=parent_lease,
        cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
        timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (lease, signal, remaining):
        implementation = _implementation()
        _require(implementation == value["implementation"], "retained join implementation generation differs")
        registry_before = scanner._registry_inventory(registry, scan_limits, remaining)
        seal = _observe(index, repository, head, lease, signal, remaining, admission_timeout_seconds, memory_mb, scan_limits)
        _match_scan_members(scan, seal)
        chain, heads = _replay_model(index, registry, scan, seal, remaining)
        history = scanner._history_fence(index, heads, remaining, seal)
        del seal
        rows = {row["source_key"]: row for row in scan["entries"]}
        offset = 0
        for wrapper in query["pages"]:
            remaining()
            old = wrapper["page"]
            cursor = None if old["start_cursor"] is None else CodebaseVerificationQueryCursor.from_dict(old["start_cursor"])
            page = _page(verification_catalog, repository, head, selector, wrapper["page_size"], cursor,
                lease, signal, remaining, admission_timeout_seconds, memory_mb)
            _require(_wire(page.to_dict()) == _wire(old), "retained exact evidence query page changed")
            summaries = [_summary(entry, head, selector, rows) for entry in page.entries]
            _require(_wire(summaries) == _wire(value["evidence"][offset:offset + len(summaries)]),
                     "retained native conditional evidence summary changed")
            offset += len(summaries)
            del page, summaries
        closing = _close(index, repository, head, registry, verification_catalog, scan, query, selector,
            chain, heads, history, registry_before, implementation, lease, signal, remaining,
            admission_timeout_seconds, memory_mb, scan_limits)
        _require(closing == query["closing_page_cid"], "retained closing evidence page changed")
        remaining()
        return record


__all__ = ["SCHEMA", "PROFILE", "REFS_SCHEMA", "CodebaseInventoryEvidenceError",
           "CodebaseInventoryEvidenceLimits", "CodebaseInventoryEvidenceRecord",
           "scan_current_codebase_evidence", "validate_current_inventory_evidence"]
