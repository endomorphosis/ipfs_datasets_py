"""Original-bound engineering identity declarations, without source admission.

Reuse only the independent small saved-format fixture and genuine public loader
from the previous test module. None of its tests is selected or rerun. The real
saved package is consumed only inside a separately owned/admitted native case;
all actual declarations there remain explicitly unknown, not source bindings.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import resource

import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_source_identity_bindings_v1 as owner
from ipfs_datasets_py.logic.autoformal import legal_parent_source_metadata_inventory_v1 as inventory_owner
from tests.unit.logic.autoformal.test_legal_parent_source_metadata_inventory_v1 import (
    package, load as load_inventory,
)


EVIDENCE_NAME = "parent-source-identity-bindings-engineering-evidence.json"
MAX_DECLARATION_BYTES = 64 * 1024**2
REAL_ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353,
    3354, 3355, 3357, 3358]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(wire(value)).hexdigest()


def raw_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def physical_key(parent, ordinal):
    return {"repository_id": parent["repository"], "revision": parent["revision"],
        "path_in_repo": parent["path_in_repo"], "artifact_sha256": parent["sha256"],
        "artifact_bytes": parent["bytes"], "parquet_row_index": ordinal}


def inventory_binding(inventory):
    summary = inventory.to_dict()
    return {"manifest_file_sha256": inventory.manifest_file_sha256,
        "manifest_canonical_sha256": inventory.manifest_canonical_sha256,
        "parent_descriptor_sha256": summary["parent_descriptor_sha256"],
        "preflight_report_sha256": summary["preflight_report_sha256"],
        "row_count": inventory.row_count}


def header(inventory):
    return {"schema": "legal-parent-source-identity-binding-declarations/v1",
        "encoding": "canonical-header-and-rows-jsonl/v1", "inventory": inventory_binding(inventory),
        "unknown_declaration_profile": "null-means-all-unknown/v1"}


def encode(header_value, rows):
    raw = bytearray(wire(header_value) + b"\n")
    for row in rows:
        line = wire(row) + b"\n"
        assert len(line) <= 4096
        assert len(raw) + len(line) <= MAX_DECLARATION_BYTES
        raw.extend(line)
    return bytes(raw)


def fixture_inventory(tmp_path):
    state = package(tmp_path)
    return load_inventory(state), state


def unresolved_row(source):
    return {"parquet_row_index": source["physical_key"]["parquet_row_index"],
        "physical_section_id": source["physical_section_id"],
        "full_raw_row_sha256": source["full_raw_row_sha256"], "source_projection_sha256": sha(source),
        "status": "unresolved", "document": None, "revision_coordinates": None,
        "cid_referent": None, "evidence_refs": [], "issues": ["no_independent_identity_binding_supplied"]}


def unresolved(inventory):
    return header(inventory), [unresolved_row(row) for row in inventory.iter_rows()]


def call_prepare(inventory, header_value, rows, evidence=None, **kwargs):
    raw = encode(header_value, rows)
    result = owner.prepare_parent_source_identity_bindings_v1(inventory, raw,
        expected_bindings_sha256=raw_sha(raw), evidence_raw_by_sha256={} if evidence is None else evidence, **kwargs)
    return result, raw


def validate(report, inventory, raw, evidence=None, **kwargs):
    return owner.validate_parent_source_identity_bindings_v1(report, inventory, raw,
        expected_report_sha256=sha(report), expected_bindings_sha256=raw_sha(raw),
        evidence_raw_by_sha256={} if evidence is None else evidence, **kwargs)


def declared(inventory, ordinal=0, *, chapter=None):
    """Independent authored declarations and subject-bound assertion receipts.

    These fixture bytes explicitly claim only authored engineering assertions;
    they are not a real source reviewer or a corpus admission mechanism.
    """
    source = next(row for row in inventory.iter_rows() if row["physical_key"]["parquet_row_index"] == ordinal)
    raw_original = b"Authored engineering identity assertion; no statutory review or source authority.\n"
    original_sha = raw_sha(raw_original)
    values = {"jurisdiction": "US", "title": "26", "section": "1", "kind": "section",
        "subsection": None, "appendix": None, "note": None, "granule": None, "edition": "2024",
        "schedule": None, "chapter": chapter}
    revisions = {"hub_revision": inventory.manifest["parent"]["revision"],
        "producer_source_revision": "d" * 40, "release_point": "2024-final",
        "edition_view": "2024", "legal_as_of": "2024-12-31"}
    assertions = [{"field": namespace + "." + name, "state": "absent" if value is None else "present", "value": value}
        for namespace, fields in (("document", values), ("revision", revisions)) for name, value in fields.items()]
    receipt = {"schema": "legal-parent-declared-identity-evidence/v1",
        "subject": {"inventory_sha256": inventory.sha256, "physical_section_id": source["physical_section_id"],
            "full_raw_row_sha256": source["full_raw_row_sha256"]},
        "assertions": sorted(assertions, key=lambda item: item["field"]),
        "provenance": {"declared_by": "independent-authored-test-fixture", "method": "declared_identity_assertion/v1",
            "originals": [{"sha256": original_sha, "bytes": len(raw_original)}]}}
    receipt_raw = wire(receipt) + b"\n"
    receipt_sha = raw_sha(receipt_raw)
    row = unresolved_row(source)
    row.update(status="declared_with_evidence", document={name: {"state": "absent" if value is None else "present",
        "value": value, "evidence_refs": [receipt_sha]} for name, value in values.items()},
        revision_coordinates={name: {"state": "present", "value": value, "evidence_refs": [receipt_sha]}
            for name, value in revisions.items()}, evidence_refs=[receipt_sha], issues=[])
    return row, {original_sha: raw_original, receipt_sha: receipt_raw}, receipt


def merge_evidence(*maps):
    result = {}
    for values in maps:
        for key, raw in values.items():
            assert key not in result or result[key] == raw
            result[key] = raw
    return result


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is type(report["evaluation_gold_mask"]) is int
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["group_id"] is report["split"] is report["inference_view"] is None


def complete_fixture(inventory, ordinals=(0,)):
    head, rows = unresolved(inventory)
    evidence = {}
    receipts = {}
    for ordinal in ordinals:
        rows[ordinal], supplied, receipts[ordinal] = declared(inventory, ordinal)
        evidence = merge_evidence(evidence, supplied)
    return head, rows, evidence, receipts


def replace_receipt(row, evidence, receipt):
    old = row["evidence_refs"][0]
    raw = wire(receipt) + b"\n"
    new = raw_sha(raw)
    evidence.pop(old)
    evidence[new] = raw
    row["evidence_refs"] = [new]
    for section in (row["document"], row["revision_coordinates"]):
        for value in section.values():
            value["evidence_refs"] = [new if key == old else key for key in value["evidence_refs"]]
    return new


def test_unresolved_builder_matches_independent_complete_JSONL_and_preserves_source_projection(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    raw = encode(head, rows)
    assert owner.build_unresolved_parent_source_identity_bindings_v1(inventory) == raw
    for row, source in zip(rows, inventory.iter_rows(), strict=True):
        assert row["source_projection_sha256"] == sha(source)
        assert owner.parent_source_identity_projection_sha256(source) == sha(source)
    report, actual = call_prepare(inventory, head, rows)
    assert actual == raw and report["row_count"] == len(report["rows"]) == 3
    assert report["inventory_sha256"] == inventory.sha256 and report["bindings_sha256"] == raw_sha(raw)
    assert report["all_document_keys_available"] is False
    assert report["complete_source_partitions_constructed"] is report["source_text_repaired"] is False
    no_authority(report)
    for result, source in zip(report["rows"], inventory.iter_rows(), strict=True):
        assert result["source_projection_sha256"] == sha(source)
        assert result["keys"]["document"] is result["document"] is None
        assert result["cid_referent_status"] == "opaque_unresolved"
        assert "document_identity_unresolved" in result["blockers"]
    validate(report, inventory, raw)


def test_complete_evidence_declares_candidate_coordinates_without_authentication(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, _ = complete_fixture(inventory)
    report, raw = call_prepare(inventory, head, rows, evidence)
    result = report["rows"][0]
    assert result["keys"]["document"].startswith("sha256:")
    assert result["document"]["legal_id"] == "usc:us:26:1;edition=2024"
    assert result["document"]["qualifier_companion"]["document"]["chapter"] == {"state": "absent", "value": None}
    assert result["document"]["qualifier_companion_sha256"] == sha(result["document"]["qualifier_companion"])
    assert {row["role"] for row in report["evidence"]} == {"assertion_receipt", "opaque_original"}
    assert report["complete_source_partitions_constructed"] is False
    no_authority(report)
    validate(report, inventory, raw, evidence)


def test_distinct_subject_receipts_share_candidate_lineage_without_filling_missing_text(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, _ = complete_fixture(inventory, (0, 2))
    assert rows[0]["evidence_refs"] != rows[2]["evidence_refs"]
    report, raw = call_prepare(inventory, head, rows, evidence)
    first, missing = report["rows"][0], report["rows"][2]
    assert first["keys"]["document"] == missing["keys"]["document"]
    assert first["physical_section_id"] != missing["physical_section_id"]
    assert missing["keys"]["exact_text_sha256"] is missing["keys"]["normalized_content_sha256"] is None
    assert "exact_text_unavailable" in missing["blockers"]
    assert "normalized_content_unavailable" in missing["blockers"]
    assert next(row for row in inventory.iter_rows() if row["physical_key"]["parquet_row_index"] == 2)["text"] is None
    assert report["source_text_repaired"] is False
    validate(report, inventory, raw, evidence)


def test_unknown_qualifier_is_not_evidenced_absence(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, _ = complete_fixture(inventory)
    known, _ = call_prepare(inventory, head, rows, evidence)
    rows[0]["document"]["chapter"] = {"state": "unknown", "value": None, "evidence_refs": []}
    unknown, raw = call_prepare(inventory, head, rows, evidence)
    assert known["rows"][0]["keys"]["document"] is not None
    assert unknown["rows"][0]["keys"]["document"] is None
    assert "document_identity_unresolved" in unknown["rows"][0]["blockers"]
    validate(unknown, inventory, raw, evidence)


def test_chapter_companion_prevents_collision_despite_identical_legacy_legal_id(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    rows[0], evidence0, _ = declared(inventory, 0, chapter="7")
    rows[1], evidence1, _ = declared(inventory, 1, chapter="8")
    report, raw = call_prepare(inventory, head, rows, merge_evidence(evidence0, evidence1))
    first, second = report["rows"][:2]
    assert first["document"]["legal_id"] == second["document"]["legal_id"]
    assert first["document"]["qualifier_companion"]["document"]["chapter"] != second["document"]["qualifier_companion"]["document"]["chapter"]
    assert first["keys"]["document"] != second["keys"]["document"]
    validate(report, inventory, raw, merge_evidence(evidence0, evidence1))


def test_duplicate_opaque_alias_and_equal_text_do_not_select_document_or_referent(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    report, _ = call_prepare(inventory, head, rows)
    first, second = report["rows"][:2]
    assert first["full_raw_row_sha256"] == second["full_raw_row_sha256"]
    assert first["keys"]["exact_text_sha256"] == second["keys"]["exact_text_sha256"]
    assert first["physical_section_id"] != second["physical_section_id"]
    assert first["keys"]["document"] is second["keys"]["document"] is None
    assert first["cid_referent_status"] == second["cid_referent_status"] == "opaque_unresolved"


@pytest.mark.parametrize("coordinate", ["manifest_file_sha256", "manifest_canonical_sha256",
    "parent_descriptor_sha256", "preflight_report_sha256", "row_count"])
def test_rehashed_header_cannot_retarget_inventory_commitments(tmp_path, coordinate):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    head["inventory"][coordinate] = 2 if coordinate == "row_count" else "0" * 64
    with pytest.raises(ValueError):
        call_prepare(inventory, head, rows)


@pytest.mark.parametrize("field", ["parquet_row_index", "physical_section_id", "full_raw_row_sha256", "source_projection_sha256"])
def test_rehashed_declarations_cannot_change_physical_or_observed_projection(tmp_path, field):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    rows[0][field] = False if field == "parquet_row_index" else "sha256:" + "0" * 64 if field == "physical_section_id" else "0" * 64
    with pytest.raises(ValueError):
        call_prepare(inventory, head, rows)


@pytest.mark.parametrize("damage", ["drop", "duplicate", "reorder", "extra"])
def test_every_original_physical_slot_is_required_exactly_once_in_order(tmp_path, damage):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    if damage == "drop": rows.pop()
    elif damage == "duplicate": rows[1] = deepcopy(rows[0])
    elif damage == "reorder": rows.reverse()
    else: rows.append(deepcopy(rows[-1]))
    with pytest.raises(ValueError):
        call_prepare(inventory, head, rows)


@pytest.mark.parametrize("damage", ["missing_lf", "blank_line", "duplicate_key", "noncanonical_header"])
def test_JSONL_is_canonical_duplicate_free_and_fully_framed(tmp_path, damage):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    raw = encode(head, rows)
    if damage == "missing_lf": raw = raw[:-1]
    elif damage == "blank_line": raw += b"\n"
    elif damage == "duplicate_key": raw = b'{"encoding":"canonical-header-and-rows-jsonl/v1",' + raw[1:]
    else:
        _, tail = raw.split(b"\n", 1)
        raw = json.dumps(head, ensure_ascii=False).encode() + b"\n" + tail
    with pytest.raises(ValueError):
        owner.prepare_parent_source_identity_bindings_v1(inventory, raw,
            expected_bindings_sha256=raw_sha(raw), evidence_raw_by_sha256={})


@pytest.mark.parametrize("damage", ["inventory_subject", "physical_subject", "raw_row_subject", "original_sha",
    "original_size", "receipt_profile", "missing_receipt", "changed_receipt_bytes"])
def test_pinned_evidence_and_exact_subject_are_required(tmp_path, damage):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, receipts = complete_fixture(inventory)
    receipt = receipts[0]
    if damage == "missing_receipt": evidence.pop(rows[0]["evidence_refs"][0])
    elif damage == "changed_receipt_bytes": evidence[rows[0]["evidence_refs"][0]] += b" "
    else:
        if damage == "inventory_subject": receipt["subject"]["inventory_sha256"] = "0" * 64
        elif damage == "physical_subject": receipt["subject"]["physical_section_id"] = "sha256:" + "0" * 64
        elif damage == "raw_row_subject": receipt["subject"]["full_raw_row_sha256"] = "0" * 64
        elif damage == "original_sha": receipt["provenance"]["originals"][0]["sha256"] = "0" * 64
        elif damage == "original_size": receipt["provenance"]["originals"][0]["bytes"] += 1
        else: receipt["schema"] = "unrecognized-evidence/v1"
        replace_receipt(rows[0], evidence, receipt)
    with pytest.raises(ValueError):
        call_prepare(inventory, head, rows, evidence)


@pytest.mark.parametrize("damage", ["unknown_value", "absent_base", "missing_support", "unrecognized_state", "cid_claim"])
def test_qualifier_and_opaque_referent_contracts_cannot_be_relaxed(tmp_path, damage):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, _ = complete_fixture(inventory)
    if damage == "unknown_value": rows[0]["document"]["chapter"] = {"state": "unknown", "value": "7", "evidence_refs": []}
    elif damage == "absent_base": rows[0]["document"]["title"] = {"state": "absent", "value": None, "evidence_refs": rows[0]["evidence_refs"]}
    elif damage == "missing_support": rows[0]["document"]["chapter"]["evidence_refs"] = []
    elif damage == "unrecognized_state": rows[0]["document"]["chapter"]["state"] = "default_absent"
    else: rows[0]["cid_referent"] = {"kind": "source_text", "sha256": "0" * 64}
    with pytest.raises(ValueError):
        call_prepare(inventory, head, rows, evidence)


@pytest.mark.parametrize("damage", ["document_key", "text_key", "source_projection", "group", "split", "authority", "boolean_mask"])
def test_resealed_preparation_requires_exact_regeneration_from_original_inputs(tmp_path, damage):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    report, raw = call_prepare(inventory, head, rows)
    if damage == "document_key": report["rows"][0]["keys"]["document"] = "sha256:" + "0" * 64
    elif damage == "text_key": report["rows"][2]["keys"]["exact_text_sha256"] = raw_sha(b"")
    elif damage == "source_projection": report["rows"][0]["source_projection_sha256"] = "0" * 64
    elif damage == "group": report["rows"][0]["group_id"] = "fabricated-group"
    elif damage == "split": report["split"] = "train"
    elif damage == "authority": report["authority"]["training_qualified"] = True
    else: report["training_mask"] = False
    report["preparation_sha256"] = sha({key: value for key, value in report.items() if key != "preparation_sha256"})
    with pytest.raises(ValueError):
        validate(report, inventory, raw)


@pytest.mark.parametrize("case", ["declaration_bytes", "row_bytes", "evidence_bytes", "boolean", "raised"])
def test_limits_are_genuine_lower_only_and_bound_inputs_before_work(tmp_path, case):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, _ = complete_fixture(inventory)
    options = {"declaration_bytes": {"max_declaration_bytes": 64}, "row_bytes": {"max_declaration_row_bytes": 32},
        "evidence_bytes": {"max_total_evidence_bytes": 16}, "boolean": {"max_rows": True},
        "raised": {"max_rows": 65537}}[case]
    with pytest.raises(ValueError):
        limits = owner.ParentSourceIdentityBindingLimits(**options)
        call_prepare(inventory, head, rows, evidence, limits=limits)


def test_contradictory_supported_assertion_remains_conflict_without_document_key(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, receipts = complete_fixture(inventory)
    receipt = receipts[0]
    for assertion in receipt["assertions"]:
        if assertion["field"] == "document.chapter":
            assertion.update(state="present", value="7")
    replace_receipt(rows[0], evidence, receipt)
    report, raw = call_prepare(inventory, head, rows, evidence)
    assert report["rows"][0]["keys"]["document"] is None
    assert "declared_evidence_conflict" in report["rows"][0]["blockers"]
    assert report["rows"][0]["document"]["legal_id"] is None
    no_authority(report)
    validate(report, inventory, raw, evidence)


def test_unselected_row_receipt_cannot_hide_a_contradictory_coordinate(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, receipts = complete_fixture(inventory)
    selected_receipt_sha = rows[0]["evidence_refs"][0]
    rival = deepcopy(receipts[0])
    rival["assertions"] = [{"field": "document.title", "state": "present", "value": "27"}]
    rival["provenance"]["declared_by"] = "second-conflicting-authored-fixture"
    rival_raw = wire(rival) + b"\n"
    rival_sha = raw_sha(rival_raw)
    evidence[rival_sha] = rival_raw
    rows[0]["evidence_refs"] = sorted([selected_receipt_sha, rival_sha])
    # The candidate selects A for support, but B remains in the row's actual
    # evidence population and must be inspected for the conflicting title.
    assert rows[0]["document"]["title"]["evidence_refs"] == [selected_receipt_sha]
    report, raw = call_prepare(inventory, head, rows, evidence)
    result = report["rows"][0]
    assert result["status"] == "declared_with_evidence"
    assert result["keys"]["document"] is None
    assert "declared_evidence_conflict" in result["blockers"]
    assert set(result["evidence_refs"]) == {selected_receipt_sha, rival_sha}
    validate(report, inventory, raw, evidence)


def test_distinct_producer_revision_is_not_collapsed_into_Hub_revision(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, receipts = complete_fixture(inventory, (0, 1))
    rows[1]["revision_coordinates"]["producer_source_revision"]["value"] = "e" * 40
    receipt = receipts[1]
    for assertion in receipt["assertions"]:
        if assertion["field"] == "revision.producer_source_revision":
            assertion["value"] = "e" * 40
    replace_receipt(rows[1], evidence, receipt)
    report, raw = call_prepare(inventory, head, rows, evidence)
    first, second = report["rows"][:2]
    assert first["document"]["legal_id"] == second["document"]["legal_id"]
    assert first["keys"]["document"] != second["keys"]["document"]
    for row in (first, second):
        assert row["document"]["qualifier_companion"]["revision"]["hub_revision"]["value"] == inventory.manifest["parent"]["revision"]
    validate(report, inventory, raw, evidence)


def test_even_evidenced_Hub_revision_cannot_replace_original_inventory_revision(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows, evidence, receipts = complete_fixture(inventory)
    rows[0]["revision_coordinates"]["hub_revision"]["value"] = "e" * 40
    receipt = receipts[0]
    for assertion in receipt["assertions"]:
        if assertion["field"] == "revision.hub_revision":
            assertion["value"] = "e" * 40
    replace_receipt(rows[0], evidence, receipt)
    with pytest.raises(ValueError):
        call_prepare(inventory, head, rows, evidence)


def test_original_declaration_pin_cannot_be_replaced_by_a_new_target(tmp_path):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    raw = encode(head, rows)
    with pytest.raises(ValueError):
        owner.prepare_parent_source_identity_bindings_v1(inventory, raw,
            expected_bindings_sha256="0" * 64, evidence_raw_by_sha256={})


def test_late_caller_limits_mutation_is_refused_before_unchecked_serialization(tmp_path, monkeypatch):
    inventory, _ = fixture_inventory(tmp_path)
    head, rows = unresolved(inventory)
    limits = owner.ParentSourceIdentityBindingLimits()
    genuine_line, genuine_wire = owner._line, owner._wire
    replacement, changes = [7], []
    def checked_wire(value):
        if type(value) is dict and value.get("max_rows") is replacement:
            pytest.fail("unchecked noninteger caller limits reached serialization")
        return genuine_wire(value)
    def changed_line(*args, **kwargs):
        value = genuine_line(*args, **kwargs)
        if not changes:
            object.__setattr__(limits, "max_rows", replacement)
            changes.append(True)
        return value
    monkeypatch.setattr(owner, "_wire", checked_wire)
    monkeypatch.setattr(owner, "_line", changed_line)
    with pytest.raises(owner.ParentSourceIdentityBindingError, match="bounded plain integer"):
        call_prepare(inventory, head, rows, limits=limits)
    assert changes == [True]


def read_reference(reference, *, maximum):
    assert type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
    assert type(reference["bytes"]) is int and 0 < reference["bytes"] <= maximum
    path = Path(reference["path"])
    assert path.is_absolute() and path.resolve(strict=True) == path and path.stat().st_size == reference["bytes"]
    raw = path.read_bytes()
    assert len(raw) == reference["bytes"] and raw_sha(raw) == reference["sha256"]
    return json.loads(raw)


def test_real60077_identity_preparation_requires_owned_enrollment_and_remains_all_unknown(tmp_path):
    # This marker declares the selected roster only. The root-reviewed driver
    # must first freeze/admit this exact request and every saved input shard.
    assert os.environ["LEGAL_PARENT_IDENTITY_BINDINGS_ENROLLED"] == "1"
    request_path = Path(os.environ["LEGAL_PARENT_IDENTITY_BINDINGS_INPUTS"])
    request_ref = {"path": str(request_path), "bytes": 1045,
        "sha256": "8d726f1e81e4516507867b2597a87ce5258c8c62ab3f0c0d16fe55e0c0f50ad5"}
    request = read_reference(request_ref, maximum=4096)
    assert request["schema"] == "legal-parent-source-identity-bindings-inputs/v1"
    assert set(request) == {"schema", "loader_inputs", "prior_loader_qualification", "scope"}
    assert request["loader_inputs"]["bytes"] == 11407
    assert request["loader_inputs"]["sha256"] == "d55f6a66ea4ecaad279e93b3d882f12049e8684561befe17d143b3017b250676"
    loader_inputs = read_reference(request["loader_inputs"], maximum=128 * 1024)
    assert loader_inputs["schema"] == "legal-parent-source-metadata-loader-inputs/v1"
    pins = read_reference(loader_inputs["row_pins"], maximum=4096)
    retained = read_reference(loader_inputs["retained_sections"], maximum=128 * 1024)
    manifest = read_reference(loader_inputs["manifest"], maximum=2 * 1024**2)
    assert loader_inputs["row_pins"]["sha256"] == "1400269e4a664d431dd79649c9014ee200e6466ca87c1fbe423127288271e2e1"
    assert loader_inputs["retained_sections"]["sha256"] == "14305627bc8148ea409d97acbb7c78610f3f5e37cd5d6ca63f1bcfd69e96db5e"
    parent = pins["source_descriptor"]
    assert manifest["parent"] == parent and parent["row_count"] == 60077
    assert len(manifest["shards"]) == len(loader_inputs["shards"]) == 26
    assert len(manifest["source_schema"]) == 45 and pins["row_ordinals"] == REAL_ORDINALS
    package_root = Path(loader_inputs["manifest"]["path"]).parent
    for declared_shard, original in zip(manifest["shards"], loader_inputs["shards"], strict=True):
        assert original == {"path": str(package_root / declared_shard["relative_path"]),
            "bytes": declared_shard["bytes"], "sha256": declared_shard["sha256"]}
    inventory = inventory_owner.load_parent_source_metadata_inventory_v1(loader_inputs["manifest"]["path"],
        expected_manifest_sha256=loader_inputs["manifest"]["sha256"],
        expected_parent_descriptor_sha256=loader_inputs["expected_parent_descriptor_sha256"],
        expected_preflight_report_sha256=loader_inputs["expected_preflight_report_sha256"])
    assert inventory.row_count == 60077
    selected_hashes = dict(zip(REAL_ORDINALS, pins["expected_row_sha256s"], strict=True))
    sections = {row["parquet_row_index"]: row for row in retained["source_sections"]}
    selected, missing = [], []
    counts = Counter()
    def complete_unknown_slots():
        for ordinal, source in enumerate(inventory.iter_rows()):
            counts["rows"] += 1
            key = physical_key(parent, ordinal)
            assert source["physical_key"] == key and source["physical_section_id"] == "sha256:" + sha(key)
            no_authority(source)
            if ordinal in selected_hashes:
                text = sections[ordinal]["text"]
                assert source["full_raw_row_sha256"] == selected_hashes[ordinal]
                assert all(source["physical_key"][name] == sections[ordinal][name] for name in key)
                assert source["text"] == {"sha256": raw_sha(text.encode()), "utf8_bytes": len(text.encode()),
                    "unicode_characters": len(text)}
                assert source["text"]["sha256"] == sections[ordinal]["text_sha256"]
                assert source["normalized_content_sha256"] == raw_sha(" ".join(text.split()).casefold().encode())
                assert source["observed_identity"]["ipfs_cid"] == sections[ordinal]["entry_cid"]
                selected.append(deepcopy(source))
            if ordinal >= 60068:
                assert source["disposition"] == "missing_text"
                assert source["text"] is source["normalized_content_sha256"] is None
                assert all(value is None for value in source["observed_identity"].values())
                assert all(value == "missing" for value in source["observed_identity_status"].values())
                assert all(value is None for value in source["observed_identity_evidence"].values())
                missing.append(deepcopy(source))
            yield unresolved_row(source)
    raw = encode(header(inventory), complete_unknown_slots())
    # This byte check precedes every new-owner declaration parse/prepare call.
    assert type(raw) is bytes and 0 < len(raw) <= MAX_DECLARATION_BYTES
    assert counts["rows"] == 60077 and len(selected) == 13 and len(missing) == 9
    built = owner.build_unresolved_parent_source_identity_bindings_v1(inventory)
    assert built == raw
    del built
    report = owner.prepare_parent_source_identity_bindings_v1(inventory, raw,
        expected_bindings_sha256=raw_sha(raw), evidence_raw_by_sha256={})
    assert report["schema"] == "legal-parent-source-identity-binding-preparation/v1"
    assert report["row_count"] == len(report["rows"]) == 60077
    assert report["declaration_bytes"] == len(raw) and report["bindings_sha256"] == raw_sha(raw)
    assert report["status_counts"] == {"unresolved": 60077}
    assert report["key_availability_counts"] == {"document": 0, "exact_text_sha256": 60068,
        "normalized_content_sha256": 60068}
    assert report["blocker_counts"] == {"document_identity_unresolved": 60077,
        "revision_coordinates_unresolved": 60077, "exact_text_unavailable": 9, "normalized_content_unavailable": 9}
    assert report["evidence"] == [] and report["evidence_bytes"] == 0
    assert report["all_document_keys_available"] is False
    assert all(report[name] is False for name in ("complete_source_partitions_constructed", "source_text_repaired",
        "original_projections_changed", "scientific_dependency_closure_verified", "evidence_assertions_authenticated",
        "current_source_bytes_verified"))
    no_authority(report)
    selected_preparation, missing_preparation = [], []
    for ordinal, (row, source) in enumerate(zip(report["rows"], inventory.iter_rows(), strict=True)):
        assert row["parquet_row_index"] == ordinal
        key = physical_key(parent, ordinal)
        assert source["physical_key"] == key
        assert row["physical_section_id"] == source["physical_section_id"] == "sha256:" + sha(key)
        assert row["full_raw_row_sha256"] == source["full_raw_row_sha256"]
        assert row["source_projection_sha256"] == sha(source)
        assert row["keys"] == {"document": None,
            "exact_text_sha256": None if source["text"] is None else source["text"]["sha256"],
            "normalized_content_sha256": source["normalized_content_sha256"]}
        assert row["keys"]["document"] is row["document"] is None
        assert row["status"] == "unresolved" and row["evidence_refs"] == []
        assert row["cid_referent_status"] == "opaque_unresolved"
        assert row["group_id"] is row["split"] is row["inference_view"] is None
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
        if ordinal in selected_hashes:
            selected_preparation.append(deepcopy(row))
        if ordinal >= 60068:
            assert row["keys"]["exact_text_sha256"] is row["keys"]["normalized_content_sha256"] is None
            missing_preparation.append(deepcopy(row))
    for source, prepared in zip(selected + missing, selected_preparation + missing_preparation, strict=True):
        assert prepared["source_projection_sha256"] == sha(source)
        assert prepared["full_raw_row_sha256"] == source["full_raw_row_sha256"]
    public_validation = validate(report, inventory, raw)
    assert public_validation == {"valid": True, "row_count": 60077,
        "complete_source_partitions_constructed": False, "all_authority_false": True}
    canonical_sha = owner.parent_source_identity_binding_sha256(report)
    assert canonical_sha == sha(report)
    preparation_bytes = len(wire(report))
    assert 0 < preparation_bytes <= MAX_DECLARATION_BYTES
    assert report["preparation_sha256"] == sha({key: value for key, value in report.items() if key != "preparation_sha256"})
    evidence = {"schema": "legal-parent-source-identity-bindings-engineering-evidence/v1",
        "input_request": request_ref, "loader_inputs": request["loader_inputs"], "manifest": loader_inputs["manifest"],
        "originals": {"independent_selected_row_pins": loader_inputs["row_pins"],
            "retained_sections_assertion_only": loader_inputs["retained_sections"]},
        "prior_loader_qualification_custody_refs_only": request["prior_loader_qualification"],
        "inventory": inventory.to_dict(), "row_count": 60077, "shard_count": 26, "source_columns": 45,
        "declarations": {"encoding": "canonical-header-and-rows-jsonl/v1", "bytes": len(raw), "sha256": raw_sha(raw),
            "complete_population": True, "all_statuses": "unresolved", "independent_actual_identity_bindings_supplied": 0,
            "public_unresolved_builder_exact_bytes_match": True},
        "preparation": {"schema": report["schema"], "row_count": report["row_count"],
            "bytes": preparation_bytes,
            "preparation_sha256": report["preparation_sha256"], "full_canonical_sha256": canonical_sha,
            "status_counts": report["status_counts"], "blocker_counts": report["blocker_counts"],
            "key_availability_counts": report["key_availability_counts"], "all_document_keys_available": False,
            "complete_source_partitions_constructed": False, "source_text_repaired": False},
        "public_original_bound_validation": public_validation,
        "independent_full_row_hash_oracles_checked": 13, "other_full_row_hashes_have_independent_oracles": False,
        "selected_independent_oracle_rows": selected, "selected_preparation_rows": selected_preparation,
        "missing_identity_rows": missing, "missing_preparation_rows": missing_preparation,
        "worker_lifetime_peak_rss_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peak_rss_scope": "Whole worker lifetime; not isolated identity preparation RSS or a bound proof.",
        "parent_body_opened_here": False, "source_authentication_supplied": False,
        "actual_identity_or_lineage_decisions_supplied": False, "partitions_assigned": False,
        "semantic_or_training_eligibility_supplied": False,
        "all_original_physical_rows_preserved": True, "all_actual_declarations_explicitly_unresolved": True,
        "all_supplied_inventory_projections_preserved": True,
        "all_nine_missing_projections_unchanged": True,
        "full_declaration_or_preparation_roster_persisted": False,
        "scope": "All60077 declared slots are engineering unknowns over a sealed saved package. Only13 independent original row/text oracles are available; nine original null projections are unchanged. No original parent, source identity review, scientific grouping or training/proof authority."}
    output = wire(evidence) + b"\n"
    assert len(output) <= 128 * 1024
    (tmp_path / EVIDENCE_NAME).write_bytes(output)
