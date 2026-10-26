"""Full-population declared identity custody; no source or meaning authority.

Input is a canonical JSONL header followed by bounded ordered declaration rows.
Source metadata remains in the genuine immutable saved inventory. This owner
never opens source/package files, chooses cache occurrences, fills missing text,
assigns partitions or treats declared evidence as an authenticated legal review.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json

from . import legal_parent_source_metadata_inventory_v1 as inventories

SCHEMA = "legal-parent-source-identity-binding-preparation/v1"
DECLARATION_SCHEMA = "legal-parent-source-identity-binding-declarations/v1"
EVIDENCE_SCHEMA = "legal-parent-declared-identity-evidence/v1"
ENCODING = "canonical-header-and-rows-jsonl/v1"
UNKNOWN_PROFILE = "null-means-all-unknown/v1"
DOCUMENT_FIELDS = ("jurisdiction", "title", "section", "kind", "subsection", "appendix",
    "note", "granule", "edition", "schedule", "chapter")
REVISION_FIELDS = ("hub_revision", "producer_source_revision", "release_point", "edition_view", "legal_as_of")
_BASE_FIELDS = {"jurisdiction", "title", "section", "kind"}
_STATUSES = {"unresolved", "declared_with_evidence", "conflicting", "unsupported_profile"}
_ROW_FIELDS = {"parquet_row_index", "physical_section_id", "full_raw_row_sha256",
    "source_projection_sha256", "status", "document", "revision_coordinates", "cid_referent", "evidence_refs", "issues"}
_UNRESOLVED_ISSUE = "no_independent_identity_binding_supplied"
_UNRESOLVED_HEADER_BYTES = 1024
_UNRESOLVED_ROW_BYTES = 768


class ParentSourceIdentityBindingError(ValueError):
    """Finite original declarations/evidence, subjects or source custody differ."""


def _need(ok, message):
    if not ok:
        raise ParentSourceIdentityBindingError(message)


def _integer(value, maximum, minimum=0):
    _need(type(value) is int and minimum <= value <= maximum, "bounded plain integer required")
    return value


def _sha(value):
    _need(type(value) is str and inventories._SHA.fullmatch(value), "literal lowercase SHA256 required")
    return value


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _wire(value):
    try:
        return inventories._wire(value)
    except inventories.ParentSourceMetadataInventoryError as exc:
        raise ParentSourceIdentityBindingError("finite canonical metadata required") from exc


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _parse(raw, maximum):
    try:
        return inventories._parse(raw, maximum)
    except inventories.ParentSourceMetadataInventoryError as exc:
        raise ParentSourceIdentityBindingError("bounded canonical JSON metadata required") from exc


def _literal(value, maximum=256):
    _need(type(value) is str and 0 < len(value) <= maximum, "bounded nonblank literal required")
    try:
        _need(value.strip() and len(value.encode("utf-8")) <= maximum, "literal byte bound exceeded")
    except UnicodeError as exc:
        raise ParentSourceIdentityBindingError("literal UTF-8 required") from exc
    return value


@dataclass(frozen=True)
class ParentSourceIdentityBindingLimits:
    """Lower-only wire/evidence bounds; not a resident-memory measurement."""
    max_rows: int = 65536
    max_declaration_bytes: int = 64 * 1024**2
    max_declaration_row_bytes: int = 4096
    max_preparation_bytes: int = 64 * 1024**2
    max_total_evidence_bytes: int = 8 * 1024**2
    max_evidence_body_bytes: int = 1024**2
    max_evidence_objects: int = 4096
    max_refs_per_row: int = 16

    def __post_init__(self):
        for name, maximum in (("max_rows", 65536), ("max_declaration_bytes", 64 * 1024**2),
                ("max_declaration_row_bytes", 4096), ("max_preparation_bytes", 64 * 1024**2),
                ("max_total_evidence_bytes", 8 * 1024**2), ("max_evidence_body_bytes", 1024**2),
                ("max_evidence_objects", 4096), ("max_refs_per_row", 16)):
            _integer(getattr(self, name), maximum, 1)


def _limits_snapshot(value):
    _need(type(value) is ParentSourceIdentityBindingLimits, "genuine identity-binding limits required")
    fields = {name: getattr(value, name) for name in ParentSourceIdentityBindingLimits.__dataclass_fields__}
    checked = ParentSourceIdentityBindingLimits(**fields)
    return checked, _wire(fields)


def _source_state():
    # Reuse the exact all-false authority profile of the genuine saved inventory.
    return inventories._source_only()


def _inventory(inventory, limits):
    _need(type(inventory) is inventories.HistoricalParentSourceInventory,
        "genuine historical-parent saved inventory required")
    summary = inventory.to_dict()
    _integer(inventory.row_count, limits.max_rows, 1)
    _need(summary["row_count"] == inventory.row_count and summary["manifest"]["sha256"] == inventory.sha256,
        "inventory summary identity differs")
    return {"manifest_file_sha256": inventory.sha256,
        "manifest_canonical_sha256": inventory.manifest_canonical_sha256,
        "parent_descriptor_sha256": summary["parent_descriptor_sha256"],
        "preflight_report_sha256": summary["preflight_report_sha256"], "row_count": inventory.row_count}, summary


def parent_source_identity_projection_sha256(row):
    """Hash the complete original detached inventory row, without a final LF.

    This commits all original physical/text/observed-status/evidence/flag fields;
    it is not independent verification of the values committed by the scanner.
    """
    try:
        return hashlib.sha256(inventories._plain_snapshot(row, 4096)[1]).hexdigest()
    except inventories.ParentSourceMetadataInventoryError as exc:
        raise ParentSourceIdentityBindingError("bounded source projection required") from exc


def _header(binding):
    return {"schema": DECLARATION_SCHEMA, "encoding": ENCODING, "inventory": binding,
        "unknown_declaration_profile": UNKNOWN_PROFILE}


def _slot(source, ordinal):
    return {"parquet_row_index": ordinal, "physical_section_id": source["physical_section_id"],
        "full_raw_row_sha256": source["full_raw_row_sha256"],
        "source_projection_sha256": parent_source_identity_projection_sha256(source), "status": "unresolved",
        "document": None, "revision_coordinates": None, "cid_referent": None,
        "evidence_refs": [], "issues": [_UNRESOLVED_ISSUE]}


def build_unresolved_parent_source_identity_bindings_v1(inventory, *, limits=ParentSourceIdentityBindingLimits()):
    """Build explicit full-population unknown declarations, never fake bindings.

    Worst-case fixed ASCII rows are bounded at 768 bytes, header at 1024 bytes:
    65536 * 768 + 1024 = 50332672 < 67108864. No qualifier-state object is
    repeated for null/all-unknown declarations. Actual bytes are checked before
    every buffer write; lower caller limits can still refuse the whole result.
    """
    original_limits = limits
    limits, limits_raw = _limits_snapshot(limits)
    binding, _ = _inventory(inventory, limits)
    header = _wire(_header(binding)) + b"\n"
    _need(len(header) <= min(_UNRESOLVED_HEADER_BYTES, limits.max_declaration_row_bytes),
        "unresolved header bound exceeded")
    _need(binding["row_count"] * _UNRESOLVED_ROW_BYTES + _UNRESOLVED_HEADER_BYTES <= 64 * 1024**2,
        "fixed complete unresolved profile exceeds hard envelope")
    stream = BytesIO()
    total = len(header)
    _need(total <= limits.max_declaration_bytes, "declaration byte bound exceeded")
    stream.write(header)
    count = 0
    for ordinal, source in enumerate(inventory.iter_rows()):
        _need(ordinal < binding["row_count"] and source["physical_key"]["parquet_row_index"] == ordinal,
            "complete source order differs")
        raw = _wire(_slot(source, ordinal)) + b"\n"
        _need(len(raw) <= min(_UNRESOLVED_ROW_BYTES, limits.max_declaration_row_bytes)
            and total + len(raw) <= limits.max_declaration_bytes, "complete unresolved declaration byte bound exceeded")
        stream.write(raw); total += len(raw); count += 1
    _need(count == binding["row_count"] and _inventory(inventory, limits)[0] == binding,
        "full unresolved population/inventory changed")
    _need(_limits_snapshot(original_limits)[1] == limits_raw, "caller limits changed during unresolved construction")
    return stream.getvalue()


def _refs(value, limits, *, nonempty=False):
    _need(type(value) is list and int(nonempty) <= len(value) <= limits.max_refs_per_row,
        "bounded evidence references required")
    for reference in value:
        _sha(reference)
    _need(value == sorted(set(value)), "sorted unique evidence references required")
    return value


def _evidence_snapshot(value, limits):
    _need(type(value) is dict and len(value) <= limits.max_evidence_objects, "bounded original evidence map required")
    total = 0
    for key, raw in value.items():
        _sha(key)
        _need(type(raw) is bytes and 0 < len(raw) <= limits.max_evidence_body_bytes, "bounded immutable evidence bytes required")
        total += len(raw)
        _need(total <= limits.max_total_evidence_bytes, "aggregate original evidence byte bound exceeded")
    captured = dict(value)
    for key, raw in captured.items():
        _need(hashlib.sha256(raw).hexdigest() == key, "independent raw evidence pin differs")
    return captured


def _line(stream, maximum):
    raw = stream.readline(maximum + 1)
    _need(raw and len(raw) <= maximum and raw.endswith(b"\n"), "bounded complete canonical JSONL line required")
    value = _parse(raw, maximum)
    _need(_wire(value) + b"\n" == raw, "canonical sorted UTF-8 JSON plus one LF required")
    return value


def _coordinate_states(value, fields, row_refs, limits, *, document=False):
    if value is None:
        return None
    _keys(value, fields, "coordinate-state map")
    for name in fields:
        entry = value[name]
        _keys(entry, {"state", "value", "evidence_refs"}, "coordinate state")
        state = entry["state"]
        _need(state in ("present", "absent", "unknown"), "explicit present/absent/unknown state required")
        refs = _refs(entry["evidence_refs"], limits, nonempty=state != "unknown")
        _need(set(refs) <= set(row_refs), "coordinate evidence outside row reference population")
        if state == "present":
            _literal(entry["value"])
        else:
            _need(entry["value"] is None, "absent/unknown coordinate must have null value")
        _need(state != "unknown" or refs == [], "unknown cannot claim supporting evidence")
        _need(not document or name not in _BASE_FIELDS or state != "absent", "required document coordinate cannot be absent")
        _need(name != "hub_revision" or state != "absent", "bound Hub revision cannot be absent")
    return value


def _receipt(raw, subject, originals, limits):
    receipt = _parse(raw, limits.max_evidence_body_bytes)
    _need(_wire(receipt) + b"\n" == raw, "canonical assertion evidence plus one LF required")
    _keys(receipt, {"schema", "subject", "assertions", "provenance"}, "declared assertion evidence")
    _need(receipt["schema"] == EVIDENCE_SCHEMA, "unsupported identity evidence profile")
    _keys(receipt["subject"], subject, "evidence subject")
    _need(receipt["subject"] == subject, "evidence subject differs from exact inventory/physical/raw-row identity")
    assertions = receipt["assertions"]
    _need(type(assertions) is list and 0 < len(assertions) <= 32, "bounded declared assertion population required")
    allowed = {"document." + name for name in DOCUMENT_FIELDS} | {"revision." + name for name in REVISION_FIELDS}
    seen = set()
    for assertion in assertions:
        _keys(assertion, {"field", "state", "value"}, "declared identity assertion")
        _need(type(assertion["field"]) is str and assertion["field"] in allowed
            and assertion["state"] in ("present", "absent"), "unsupported declared assertion coordinate")
        if assertion["state"] == "present":
            _literal(assertion["value"])
        else:
            _need(assertion["value"] is None, "absent assertion requires null value")
        key = _wire(assertion)
        _need(key not in seen, "duplicate declared assertion")
        seen.add(key)
    provenance = receipt["provenance"]
    _keys(provenance, {"declared_by", "method", "originals"}, "assertion provenance")
    _literal(provenance["declared_by"])
    _need(provenance["method"] == "declared_identity_assertion/v1", "unsupported declaration method")
    refs = provenance["originals"]
    _need(type(refs) is list and 0 < len(refs) <= limits.max_refs_per_row, "bounded original evidence population required")
    keys = []
    for reference in refs:
        _keys(reference, {"sha256", "bytes"}, "original evidence reference")
        key = _sha(reference["sha256"])
        size = _integer(reference["bytes"], limits.max_evidence_body_bytes, 1)
        _need(key in originals and len(originals[key]) == size, "original evidence bytes missing or size differs")
        keys.append(key)
    _need(keys == sorted(set(keys)), "sorted unique original evidence references required")
    return assertions, set(keys)


def _supported(states, prefix, receipts):
    """Keep conflicts as blockers; receipt custody never decides legal truth."""
    if states is None:
        return False, False
    known, conflict = True, False
    for name, entry in states.items():
        if entry["state"] == "unknown":
            known = False
            continue
        wanted = {"field": prefix + name, "state": entry["state"], "value": entry["value"]}
        matched = False
        for key in entry["evidence_refs"]:
            applicable = [item for item in receipts[key] if item["field"] == wanted["field"]]
            matched = matched or wanted in applicable
            conflict = conflict or not applicable or any(item != wanted for item in applicable)
        # Every supplied scoped receipt is part of the observation population.
        # A contradictory extra receipt cannot be hidden by omitting it from a
        # coordinate's nominated supporting subset.
        conflict = conflict or any(item != wanted for assertions in receipts.values()
            for item in assertions if item["field"] == wanted["field"])
        conflict = conflict or not matched
    return known, conflict


def _states_only(value):
    return None if value is None else {name: {"state": item["state"], "value": item["value"]} for name, item in value.items()}


def _document_result(document, revision, *, supported):
    companion = {"schema": "legal-parent-declared-qualifier-companion/v1",
        "document": _states_only(document), "revision": _states_only(revision), "unknown_profile": UNKNOWN_PROFILE}
    legal_id = key = None
    if supported:
        # Use the genuine public owner. Its package initialization/optional-import
        # compatibility belongs to the separately frozen execution closure.
        from ipfs_datasets_py.processors.legal_data.uscode_identity import LegalIdentity
        values = {name: item["value"] for name, item in document.items()}
        _need(values["kind"] in ("section", "subsection", "appendix", "note", "schedule", "granule", "chapter", "title", "other"),
            "literal supported document kind required; no unknown-kind coercion")
        try:
            identity = LegalIdentity(**values)
        except (TypeError, ValueError) as exc:
            raise ParentSourceIdentityBindingError("declared identity rejected by existing canonical owner") from exc
        legal_id = identity.legal_id
        for name in DOCUMENT_FIELDS:
            companion["document"][name]["value"] = getattr(identity, name)
        # Chapter is deliberately present here: LegalIdentity.legal_id omits it.
        # Neither physical identity nor evidence receipts are document union keys.
        key = "sha256:" + _digest({"schema": "legal-parent-declared-document-key/v1",
            "legal_id": legal_id, "qualifier_companion": companion})
    if document is None and revision is None:
        return None, None
    return {"legal_id": legal_id, "qualifier_companion": companion,
        "qualifier_companion_sha256": _digest(companion)}, key


def _report_hash(value, maximum):
    """Bound a caller's plain structure without making another full row tree."""
    nodes = size = 0
    active = set()
    def charge(number):
        nonlocal size
        size += number
        _need(size <= maximum, "preparation canonical byte bound exceeded before encoding")
    def string_size(value):
        # Reserve JSON escapes and UTF-8 before JSONEncoder can allocate its
        # string fragment. This also rejects lone surrogates without encoding a
        # caller's entire potentially large string first.
        charge(2)
        for character in value:
            code = ord(character)
            _need(not 0xD800 <= code <= 0xDFFF, "finite UTF-8 preparation string required")
            charge(2 if character in '\\"\b\f\n\r\t' else 6 if code < 32 else
                1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
    def visit(item, depth):
        nonlocal nodes, size
        nodes += 1
        _need(nodes <= 4_000_000 and depth <= 16, "preparation node/depth bound exceeded")
        kind = type(item)
        if kind is str:
            _need(len(item) <= maximum, "preparation string bound exceeded")
            string_size(item)
        elif kind is int:
            _integer(item, 2**63 - 1, -(2**63))
            charge(len(str(item)))
        elif item is None or kind is bool:
            charge(4 if item is None or item is True else 5)
            return
        else:
            _need(kind in (dict, list) and len(item) <= 65536, "bounded plain preparation required")
            identifier = id(item)
            _need(identifier not in active, "cyclic preparation refused")
            active.add(identifier)
            try:
                charge(2 + max(0, len(item) - 1) + (len(item) if kind is dict else 0))
                if kind is list:
                    for child in item:
                        visit(child, depth + 1)
                else:
                    for key, child in item.items():
                        _need(type(key) is str and len(key) <= 4096, "bounded preparation key required")
                        visit(key, depth + 1); visit(child, depth + 1)
            finally:
                active.remove(identifier)
    try:
        visit(value, 0)
        # Iterative chunks avoid a second serialized complete preparation body.
        hashed, count = hashlib.sha256(), 0
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        for fragment in encoder.iterencode(value):
            raw = fragment.encode("utf-8")
            count += len(raw)
            _need(count <= maximum, "complete preparation byte bound exceeded")
            hashed.update(raw)
        _need(count == size, "canonical preparation byte reservation differs")
        return hashed.hexdigest(), count
    except (TypeError, ValueError, UnicodeError, RecursionError, RuntimeError) as exc:
        if isinstance(exc, ParentSourceIdentityBindingError):
            raise
        raise ParentSourceIdentityBindingError("invalid finite preparation metadata") from exc


def _closing(original_limits, limits_raw, original_evidence, evidence, limits, inventory, binding, primary):
    try:
        _need(_limits_snapshot(original_limits)[1] == limits_raw, "caller limits changed during preparation")
        fresh = _evidence_snapshot(original_evidence, limits)
        _need(fresh == evidence, "original evidence population/bytes changed during preparation")
        _need(_inventory(inventory, limits)[0] == binding, "inventory binding changed during preparation")
    except BaseException as failure:
        if primary is None:
            raise
        primary.add_note("Closing original-input custody check also failed: " + type(failure).__name__)


def prepare_parent_source_identity_bindings_v1(inventory, bindings_raw, *, expected_bindings_sha256,
        evidence_raw_by_sha256, limits=ParentSourceIdentityBindingLimits()):
    """Prepare every original source row from independently pinned declarations.

    Evidence is a scoped declared assertion plus immutable original-byte custody,
    never legal/source authentication. Missing text and scientific dependencies
    remain unresolved even when a declared document coordinate becomes usable.
    """
    original_limits = limits
    limits, limits_raw = _limits_snapshot(limits)
    _sha(expected_bindings_sha256)
    _need(type(bindings_raw) is bytes and 0 < len(bindings_raw) <= limits.max_declaration_bytes,
        "bounded immutable original declaration bytes required")
    _need(hashlib.sha256(bindings_raw).hexdigest() == expected_bindings_sha256, "independent declaration pin differs")
    binding, summary = _inventory(inventory, limits)
    evidence = _evidence_snapshot(evidence_raw_by_sha256, limits)
    primary = None
    try:
        stream = BytesIO(bindings_raw)
        header = _line(stream, limits.max_declaration_row_bytes)
        _keys(header, {"schema", "encoding", "inventory", "unknown_declaration_profile"}, "declaration header")
        _need(_wire(header) == _wire(_header(binding)), "declaration header/profile/full inventory binding differs")
        rows, counts, blockers = [], Counter(), Counter()
        available = Counter(document=0, exact_text_sha256=0, normalized_content_sha256=0)
        used_receipts, used_originals = set(), set()
        row_bytes = count = 0
        for ordinal, source in enumerate(inventory.iter_rows()):
            _need(ordinal < binding["row_count"], "inventory row denominator exceeded")
            declaration = _line(stream, limits.max_declaration_row_bytes)
            _keys(declaration, _ROW_FIELDS, "identity declaration row")
            _integer(declaration["parquet_row_index"], binding["row_count"] - 1)
            _need(declaration["parquet_row_index"] == ordinal
                and source["physical_key"]["parquet_row_index"] == ordinal
                and declaration["physical_section_id"] == source["physical_section_id"]
                and declaration["full_raw_row_sha256"] == source["full_raw_row_sha256"]
                and declaration["source_projection_sha256"] == parent_source_identity_projection_sha256(source),
                "original physical/raw-row/source-projection binding differs")
            status = declaration["status"]
            _need(type(status) is str and status in _STATUSES, "explicit declaration status required")
            refs = _refs(declaration["evidence_refs"], limits)
            _need(all(reference in evidence for reference in refs), "referenced original assertion evidence unavailable")
            issues = declaration["issues"]
            _need(type(issues) is list and len(issues) <= 16, "bounded explicit declaration issues required")
            for issue in issues:
                _literal(issue, 128)
            _need(issues == sorted(set(issues)), "sorted unique declaration issues required")
            document = _coordinate_states(declaration["document"], DOCUMENT_FIELDS, refs, limits, document=True)
            revision = _coordinate_states(declaration["revision_coordinates"], REVISION_FIELDS, refs, limits)
            _need(declaration["cid_referent"] is None, "CID referent interpretation unsupported; retain opaque observation")
            if status == "unresolved":
                _need(document is None and revision is None and not refs and issues,
                    "unresolved profile requires explicit all-unknown declarations/issues")
            elif status == "declared_with_evidence":
                _need(refs and (document is not None or revision is not None), "declared coordinates require scoped evidence")
            else:
                _need(issues, "conflicting/unsupported declarations require issues")
            subject = {"inventory_sha256": binding["manifest_file_sha256"],
                "physical_section_id": source["physical_section_id"], "full_raw_row_sha256": source["full_raw_row_sha256"]}
            receipts = {}
            for reference in refs:
                assertions, originals = _receipt(evidence[reference], subject, evidence, limits)
                receipts[reference] = assertions
                used_receipts.add(reference); used_originals.update(originals)
            known_document, document_conflict = _supported(document, "document.", receipts)
            known_revision, revision_conflict = _supported(revision, "revision.", receipts)
            unresolved = []
            if not known_document:
                unresolved.append("document_identity_unresolved")
            if not known_revision:
                unresolved.append("revision_coordinates_unresolved")
            if revision is not None and revision["hub_revision"]["state"] == "present":
                _need(revision["hub_revision"]["value"] == summary["parent"]["revision"],
                    "declared Hub revision differs from original inventory")
            conflict = document_conflict or revision_conflict
            if conflict:
                unresolved.append("declared_evidence_conflict")
            if status in ("conflicting", "unsupported_profile"):
                unresolved.append("status_" + status)
            supported = known_document and known_revision and not conflict and status == "declared_with_evidence"
            document_result, document_key = _document_result(document, revision, supported=supported)
            if document_key is None and "document_identity_unresolved" not in unresolved:
                unresolved.append("document_identity_unresolved")
            text_sha = None if source["text"] is None else source["text"]["sha256"]
            normalized = source["normalized_content_sha256"]
            if text_sha is None:
                unresolved.append("exact_text_unavailable")
            if normalized is None:
                unresolved.append("normalized_content_unavailable")
            for name, value in (("document", document_key), ("exact_text_sha256", text_sha), ("normalized_content_sha256", normalized)):
                if value is not None:
                    available[name] += 1
            row = {"parquet_row_index": ordinal, "physical_section_id": source["physical_section_id"],
                "full_raw_row_sha256": source["full_raw_row_sha256"], "source_projection_sha256": declaration["source_projection_sha256"],
                "keys": {"document": document_key, "exact_text_sha256": text_sha, "normalized_content_sha256": normalized},
                "status": status, "document": document_result, "cid_referent_status": "opaque_unresolved",
                "evidence_refs": refs, "issues": issues, "blockers": sorted(set(unresolved)),
                "group_id": None, "split": None, "inference_view": None, "training_mask": 0, "evaluation_gold_mask": 0}
            size = len(_wire(row)) + 1
            _need(size <= limits.max_declaration_row_bytes and row_bytes + size <= limits.max_preparation_bytes,
                "complete preparation row/byte bound exceeded")
            row_bytes += size; rows.append(row); counts[status] += 1; blockers.update(row["blockers"]); count += 1
        _need(count == binding["row_count"] and stream.read(1) == b"", "complete declaration population/order differs")
        _need(not (used_receipts & used_originals) and used_receipts | used_originals == set(evidence),
            "unused evidence or assertion/original role cycle refused")
        evidence_summary = [{"sha256": key, "bytes": len(evidence[key]),
            "role": "assertion_receipt" if key in used_receipts else "opaque_original"} for key in sorted(evidence)]
        report = {"schema": SCHEMA, "scope": "declared_identity_custody_only",
            "inventory_sha256": binding["manifest_file_sha256"], "bindings_sha256": expected_bindings_sha256,
            "declaration_bytes": len(bindings_raw), "unknown_declaration_profile": UNKNOWN_PROFILE,
            "evidence": evidence_summary, "evidence_bytes": sum(len(raw) for raw in evidence.values()),
            "row_count": len(rows), "rows": rows, "status_counts": dict(counts), "blocker_counts": dict(blockers),
            "key_availability_counts": dict(available), "all_document_keys_available": available["document"] == len(rows),
            "complete_source_partitions_constructed": False, "source_text_repaired": False,
            "original_projections_changed": False, "scientific_dependency_closure_verified": False,
            "evidence_assertions_authenticated": False, "current_source_bytes_verified": False, **_source_state()}
        report["preparation_sha256"] = _report_hash(report, limits.max_preparation_bytes)[0]
        _report_hash(report, limits.max_preparation_bytes)
        return report
    except BaseException as failure:
        primary = failure
        raise
    finally:
        _closing(original_limits, limits_raw, evidence_raw_by_sha256, evidence, limits, inventory, binding, primary)


def parent_source_identity_binding_sha256(report):
    """Full canonical preparation SHA including internal seal; not validation."""
    return _report_hash(report, 64 * 1024**2)[0]


def validate_parent_source_identity_bindings_v1(report, inventory, bindings_raw, *, expected_report_sha256,
        expected_bindings_sha256, evidence_raw_by_sha256, limits=ParentSourceIdentityBindingLimits()):
    """Fully regenerate from original inventory, declaration bytes and evidence."""
    _sha(expected_report_sha256)
    original_limits = limits
    checked, limits_raw = _limits_snapshot(limits)
    before = _report_hash(report, checked.max_preparation_bytes)[0]
    _need(before == expected_report_sha256, "independent preparation report pin differs")
    expected = prepare_parent_source_identity_bindings_v1(inventory, bindings_raw,
        expected_bindings_sha256=expected_bindings_sha256, evidence_raw_by_sha256=evidence_raw_by_sha256, limits=limits)
    _need(_report_hash(expected, checked.max_preparation_bytes)[0] == before
        == _report_hash(report, checked.max_preparation_bytes)[0], "preparation differs from complete original-input regeneration")
    _need(_limits_snapshot(original_limits)[1] == limits_raw, "caller limits changed during validation")
    return {"valid": True, "row_count": inventory.row_count, "complete_source_partitions_constructed": False,
        "all_authority_false": True}


__all__ = ["SCHEMA", "DECLARATION_SCHEMA", "EVIDENCE_SCHEMA", "ENCODING", "UNKNOWN_PROFILE",
    "DOCUMENT_FIELDS", "REVISION_FIELDS", "ParentSourceIdentityBindingError", "ParentSourceIdentityBindingLimits",
    "parent_source_identity_projection_sha256", "build_unresolved_parent_source_identity_bindings_v1",
    "prepare_parent_source_identity_bindings_v1", "validate_parent_source_identity_bindings_v1",
    "parent_source_identity_binding_sha256"]
