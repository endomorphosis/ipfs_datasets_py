"""Read-only saved-parent package custody and grouping-preparation checks.

Most small packages below are independent canonical-format engineering fixtures;
one tiny scanner-to-loader check exercises the current producer format. Neither
is a source-authentication stand-in. The separately enrolled real case reads the
sealed genuine producer package, never the parent Parquet, and has independent
original row/text oracles for thirteen rows only.
"""
from copy import deepcopy
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import resource

import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_source_metadata_inventory_v1 as owner


MANIFEST_NAME = "parent-source-metadata.json"
AUTHORITY_NAMES = (
    "source_semantics_verified", "source_authority_authenticated",
    "official_edition_correspondence_verified", "original_producer_occurrence_attested",
    "source_equivalence_proven", "context_permission_verified", "context_closure_verified",
    "source_encoder_authenticated", "global_holdout_verified", "training_qualified",
    "evaluation_gold_qualified", "model_executed", "training_executed", "database_executed",
    "prover_executed", "Lean_admitted", "convergence_proved", "admitted",
)
SCAN_LIMITS = {
    "max_rows": 65536, "max_total_decoded_page_bytes": 2 * 1024**3,
    "max_total_canonical_hashed_bytes": 4 * 1024**3, "max_metadata_row_bytes": 4096,
    "max_identity_literal_bytes": 512, "max_resident_metadata_bytes": 256 * 1024**2,
    "max_rows_per_metadata_shard": 4096, "max_metadata_shard_bytes": 4 * 1024**2,
    "max_metadata_shards": 128, "max_preflight_bytes": 8 * 1024**2,
    "max_manifest_bytes": 2 * 1024**2, "max_total_metadata_package_bytes": 384 * 1024**2,
}
REAL_ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353,
    3354, 3355, 3357, 3358]
REAL_ORIGINALS = {
    "row_pins": ("LEGAL_PARENT_ROW_PINS", 3439,
        "1400269e4a664d431dd79649c9014ee200e6466ca87c1fbe423127288271e2e1"),
    "retained_sections": ("LEGAL_PARENT_EXPECTED_SECTIONS", 123063,
        "14305627bc8148ea409d97acbb7c78610f3f5e37cd5d6ca63f1bcfd69e96db5e"),
}
EVIDENCE_NAME = "parent-source-metadata-loader-engineering-evidence.json"
INPUTS_BYTES = 11407
INPUTS_SHA256 = "d55f6a66ea4ecaad279e93b3d882f12049e8684561befe17d143b3017b250676"


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


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is type(report["evaluation_gold_mask"]) is int
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["group_id"] is report["split"] is report["inference_view"] is None


def metadata_row(raw, parent, ordinal):
    """Independent public-format projection from an authored full-row oracle."""
    key = physical_key(parent, ordinal)
    result = {"physical_key": key, "physical_section_id": "sha256:" + sha(key),
        "full_raw_row_sha256": sha(raw), "raw_row_canonical_bytes": len(wire(raw)),
        "text": None, "normalized_content_sha256": None,
        "observed_identity": {}, "observed_identity_status": {}, "observed_identity_evidence": {},
        "disposition": "missing_text", "group_id": None, "split": None, "inference_view": None,
        "authority": dict.fromkeys(AUTHORITY_NAMES, False), "training_mask": 0,
        "evaluation_gold_mask": 0}
    text = raw.get("text")
    if type(text) is str:
        result["text"] = {"sha256": raw_sha(text.encode()), "utf8_bytes": len(text.encode()),
            "unicode_characters": len(text)}
        result["normalized_content_sha256"] = raw_sha(" ".join(text.split()).casefold().encode())
        result["disposition"] = "stored_text_available" if text else "empty_text"
    elif text is not None:
        result["disposition"] = "unsupported_text_type"
    for field in ("ipfs_cid", "title_number", "section_number"):
        value = raw.get(field)
        result["observed_identity"][field] = None
        result["observed_identity_evidence"][field] = None
        if type(value) is str and len(value.encode()) <= 512:
            result["observed_identity"][field] = value
            result["observed_identity_status"][field] = "observed_string"
        elif type(value) is str:
            result["observed_identity_status"][field] = "unsupported_size"
            result["observed_identity_evidence"][field] = {
                "sha256": raw_sha(value.encode()), "utf8_bytes": len(value.encode())}
        else:
            result["observed_identity_status"][field] = "missing" if value is None else "unsupported_type"
    return result


def package(tmp_path, raw_rows=None, *, shard_rows=2, text_kind="utf8"):
    """Build only the saved format; no producer, parser or scanner is executed."""
    if raw_rows is None:
        raw_rows = [
            {"ipfs_cid": "same:opaque-alias", "title_number": "26", "section_number": "1",
                "text": "Café\t雪 shall act."},
            {"ipfs_cid": "same:opaque-alias", "title_number": "26", "section_number": "1",
                "text": "Café\t雪 shall act."},
            {"ipfs_cid": None, "title_number": None, "section_number": None, "text": None},
        ]
    root = tmp_path / "package"
    (root / "metadata").mkdir(parents=True)
    parent = {"repository": "fixture/saved-parent", "revision": "a" * 40,
        "path_in_repo": "source/laws.parquet", "local_path": str(tmp_path / "NEVER_OPEN_PARENT.parquet"),
        "sha256": "b" * 64, "bytes": 4096, "row_count": len(raw_rows),
        "profile": "legacy_laws_parquet/v1"}
    fields = ["ipfs_cid", "title_number", "section_number", "text"]
    schema = [{"index": i, "name": name, "path": [name],
        "physical_type": 2 if name == "text" and text_kind == "int64" else 6,
        "kind": text_kind if name == "text" else "utf8",
        "max_definition_level": 1, "max_repetition_level": 0} for i, name in enumerate(fields)]
    rows = [metadata_row(raw, parent, i) for i, raw in enumerate(raw_rows)]
    witnesses = [{"page_id": raw_sha(("page:" + str(i)).encode()), "column_index": i,
        "offset": 4 + i * 32, "header_sha256": raw_sha(("header:" + str(i)).encode()),
        "compressed_body_sha256": raw_sha(("compressed:" + str(i)).encode()),
        "decoded_body_sha256": raw_sha(("decoded:" + str(i)).encode()),
        "uncompressed_bytes": 16 + i} for i in range(len(fields))]
    manifest = {"schema": "legal-parent-complete-source-metadata/v1",
        "profile": "historical-parent-complete-source-metadata/v1", "scope": "declared_parent_artifact_only",
        "parent": parent, "parent_descriptor_sha256": sha(parent), "preflight_report_sha256": "c" * 64,
        "source_schema": schema, "source_schema_sha256": sha(schema),
        "content_normalization": "unicode-whitespace-casefold-v1", "limits": deepcopy(SCAN_LIMITS),
        "row_count": len(rows), "shards": [], "coverage": {"declared_parent_rows": len(rows),
            "replayed_parent_rows": len(rows), "whole_parent_inventoried": True},
        "all_source_columns_hashed": True, "raw_rows_stored": False, "source_text_stored": False,
        "grouping_metadata_complete": False, "page_count": len(witnesses),
        "decoded_page_bytes": sum(w["uncompressed_bytes"] for w in witnesses),
        "decoded_page_witnesses": witnesses,
        "raw_row_canonical_bytes": sum(row["raw_row_canonical_bytes"] for row in rows),
        "total_metadata_bytes": 0, "disposition_counts": dict(Counter(row["disposition"] for row in rows)),
        "group_id": None, "split": None, "inference_view": None,
        "authority": dict.fromkeys(AUTHORITY_NAMES, False), "training_mask": 0, "evaluation_gold_mask": 0}
    state = {"root": root, "path": root / MANIFEST_NAME, "manifest": manifest,
        "rows": rows, "raw_rows": deepcopy(raw_rows), "shard_rows": shard_rows}
    save_package(state)
    return state


def save_package(state):
    """Recommit tampered fixture bytes so syntax checks cannot hide behind SHA."""
    manifest, rows = state["manifest"], state["rows"]
    manifest["shards"] = []
    for start in range(0, len(rows), state["shard_rows"]):
        chunk = rows[start:start + state["shard_rows"]]
        raw = b"".join(wire(row) + b"\n" for row in chunk)
        relative = "metadata/part-" + str(len(manifest["shards"])).zfill(6) + ".jsonl"
        (state["root"] / relative).write_bytes(raw)
        manifest["shards"].append({"relative_path": relative, "bytes": len(raw), "sha256": raw_sha(raw),
            "row_count": len(chunk), "start_ordinal": start, "end_ordinal": start + len(chunk)})
    manifest["total_metadata_bytes"] = sum(s["bytes"] for s in manifest["shards"])
    save_manifest(state)


def save_manifest(state):
    manifest = state["manifest"]
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = sha(manifest)
    raw = wire(manifest) + b"\n"
    state["path"].write_bytes(raw)
    state["pins"] = {"expected_manifest_sha256": raw_sha(raw),
        "expected_parent_descriptor_sha256": manifest["parent_descriptor_sha256"],
        "expected_preflight_report_sha256": manifest["preflight_report_sha256"]}


def load(state, **options):
    return owner.load_parent_source_metadata_inventory_v1(state["path"], **state["pins"], **options)


def pinned_json(environment, size, digest):
    path = Path(os.environ[environment])
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert path.stat().st_size == size
    raw = path.read_bytes()
    assert len(raw) == size and raw_sha(raw) == digest
    return json.loads(raw), {"path": str(path), "bytes": size, "sha256": digest}


def test_saved_package_preserves_unicode_full_hashes_and_duplicate_physical_occurrences(tmp_path):
    state = package(tmp_path)
    observed = load(state)
    assert type(observed) is owner.HistoricalParentSourceInventory
    assert observed.row_count == 3
    assert observed.sha256 == observed.manifest_file_sha256 == state["pins"]["expected_manifest_sha256"]
    assert observed.manifest_canonical_sha256 == sha(state["manifest"])
    assert observed.internal_manifest_sha256 == state["manifest"]["manifest_sha256"]
    rows = tuple(observed.iter_rows())
    assert rows == tuple(state["rows"])
    assert rows[0]["full_raw_row_sha256"] == rows[1]["full_raw_row_sha256"]
    assert rows[0]["physical_section_id"] != rows[1]["physical_section_id"]
    assert rows[0]["text"]["utf8_bytes"] > rows[0]["text"]["unicode_characters"]
    for row in rows:
        no_authority(row)


def test_small_scanner_package_loads_and_preserves_unresolved_grouping(tmp_path):
    from tests.unit.logic.autoformal.test_legal_parent_complete_metadata import input_report, scan

    duplicate = {"ipfs_cid": "same:opaque-alias", "title_number": "26",
        "section_number": "1", "text": "Café\t雪 shall act."}
    expected = [duplicate, dict(duplicate),
        {"ipfs_cid": "empty:opaque-alias", "title_number": "26", "section_number": "2", "text": ""},
        {"ipfs_cid": None, "title_number": None, "section_number": None, "text": None}]
    descriptor, preflight = input_report(tmp_path, expected, groups=2)
    output = tmp_path / "actual-scanner-package"
    manifest = scan(descriptor, preflight, output, max_rows_per_metadata_shard=2)
    manifest_path = output / MANIFEST_NAME
    inventory = owner.load_parent_source_metadata_inventory_v1(manifest_path,
        expected_manifest_sha256=raw_sha(manifest_path.read_bytes()),
        expected_parent_descriptor_sha256=sha(descriptor),
        expected_preflight_report_sha256=sha(preflight))

    # The oracle comes from authored complete rows, not the emitted shards.
    rows = tuple(inventory.iter_rows())
    assert inventory.row_count == len(rows) == 4
    assert len(manifest["shards"]) == 2
    assert rows == tuple(metadata_row(raw, descriptor, ordinal)
        for ordinal, raw in enumerate(expected))
    assert len({row["physical_section_id"] for row in rows}) == 4
    assert rows[0]["full_raw_row_sha256"] == rows[1]["full_raw_row_sha256"] == sha(duplicate)
    assert rows[0]["text"]["utf8_bytes"] > rows[0]["text"]["unicode_characters"]
    assert rows[2]["text"]["sha256"] == rows[2]["normalized_content_sha256"] == raw_sha(b"")
    assert rows[3]["text"] is rows[3]["normalized_content_sha256"] is None
    assert inventory.to_dict()["disposition_counts"] == {
        "stored_text_available": 2, "empty_text": 1, "missing_text": 1}
    assert inventory.to_dict()["current_source_bytes_verified"] is False
    for row in rows:
        no_authority(row)
    no_authority(inventory.to_dict())

    preparation = owner.prepare_parent_source_grouping_v1(inventory)
    assert preparation["row_count"] == len(preparation["rows"]) == 4
    assert preparation["key_availability_counts"] == {
        "document": 0, "exact_text_sha256": 3, "normalized_content_sha256": 3}
    assert preparation["blocker_counts"] == {
        "document_identity_unresolved": 4, "exact_text_unavailable": 1,
        "normalized_content_unavailable": 1}
    assert preparation["all_required_keys_available"] is False
    assert preparation["complete_source_partitions_constructed"] is False
    assert preparation["canonical_document_identity_inferred"] is False
    assert preparation["scientific_training_eligibility_established"] is False
    for ordinal, row in enumerate(preparation["rows"]):
        assert row["parquet_row_index"] == ordinal
        assert row["physical_section_id"] == rows[ordinal]["physical_section_id"]
        text = expected[ordinal]["text"]
        assert row["keys"] == {"document": None,
            "exact_text_sha256": None if text is None else raw_sha(text.encode()),
            "normalized_content_sha256": None if text is None else raw_sha(" ".join(text.split()).casefold().encode())}
        assert row["group_id"] is row["split"] is row["inference_view"] is None
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
    no_authority(preparation)


def test_saved_custody_does_not_open_or_authenticate_the_original_parent(tmp_path, monkeypatch):
    state = package(tmp_path)
    forbidden = Path(state["manifest"]["parent"]["local_path"])
    assert not forbidden.exists()
    genuine = os.open
    def guarded(path, *args, **kwargs):
        assert Path(path) != forbidden, "saved-package loader attempted original parent access"
        return genuine(path, *args, **kwargs)
    monkeypatch.setattr(os, "open", guarded)
    inventory = load(state)
    assert inventory.row_count == 3
    assert inventory.to_dict()["current_source_bytes_verified"] is False


def test_inventory_is_a_distinct_immutable_type_not_a_release_inventory(tmp_path):
    inventory = load(package(tmp_path))
    with pytest.raises((AttributeError, TypeError)):
        inventory.row_count = 1
    with pytest.raises((AttributeError, TypeError)):
        inventory.sha256 = "0" * 64
    assert "USCodeSourceInventory" not in [base.__name__ for base in type(inventory).__mro__]
    with pytest.raises((ValueError, TypeError)):
        owner.HistoricalParentSourceInventory()


def test_row_manifest_and_summary_reads_are_detached(tmp_path):
    state = package(tmp_path)
    inventory = load(state)
    first = next(inventory.iter_rows())
    first["physical_key"]["parquet_row_index"] = 99
    first["authority"]["admitted"] = True
    manifest = inventory.manifest
    manifest["parent"]["row_count"] = 1
    summary = inventory.to_dict()
    summary["current_source_bytes_verified"] = True
    assert next(inventory.iter_rows()) == state["rows"][0]
    assert inventory.manifest == state["manifest"]
    assert inventory.to_dict()["current_source_bytes_verified"] is False


@pytest.mark.parametrize("pin", ["expected_manifest_sha256", "expected_parent_descriptor_sha256",
    "expected_preflight_report_sha256"])
def test_independent_original_pins_are_required(tmp_path, pin):
    state = package(tmp_path)
    state["pins"][pin] = "0" * 64
    with pytest.raises(ValueError):
        load(state)


@pytest.mark.parametrize("damage", ["authority", "authority_integer", "boolean_mask", "coverage_integer",
    "schema_index", "boolean_row_count", "disposition_count", "canonical_total", "page_count", "duplicate_page", "internal_seal"])
def test_resealed_manifest_cannot_promote_authority_or_change_closed_accounting(tmp_path, damage):
    state = package(tmp_path)
    manifest = state["manifest"]
    if damage == "authority": manifest["authority"]["training_qualified"] = True
    elif damage == "authority_integer": manifest["authority"]["model_executed"] = 0
    elif damage == "boolean_mask": manifest["training_mask"] = False
    elif damage == "coverage_integer": manifest["coverage"]["whole_parent_inventoried"] = 1
    elif damage == "schema_index":
        manifest["source_schema"][1]["index"] = 0
        manifest["source_schema_sha256"] = sha(manifest["source_schema"])
    elif damage == "boolean_row_count": manifest["row_count"] = True
    elif damage == "disposition_count": manifest["disposition_counts"]["missing_text"] = 2
    elif damage == "canonical_total": manifest["raw_row_canonical_bytes"] += 1
    elif damage == "page_count": manifest["page_count"] += 1
    elif damage == "duplicate_page":
        manifest["decoded_page_witnesses"][1] = deepcopy(manifest["decoded_page_witnesses"][0])
    save_manifest(state)
    if damage == "internal_seal":
        manifest["manifest_sha256"] = "0" * 64
        raw = wire(manifest) + b"\n"
        state["path"].write_bytes(raw)
        state["pins"]["expected_manifest_sha256"] = raw_sha(raw)
    with pytest.raises(ValueError):
        load(state)


@pytest.mark.parametrize("damage", ["authority", "boolean_mask", "physical_id", "boolean_ordinal",
    "parent_artifact", "text_geometry", "missing_normalized", "identity_status", "extra_field", "missing_text_hash"])
def test_rehashed_rows_still_require_exact_physical_and_projection_contracts(tmp_path, damage):
    state = package(tmp_path)
    row = state["rows"][0]
    if damage == "authority": row["authority"]["source_semantics_verified"] = True
    elif damage == "boolean_mask": row["evaluation_gold_mask"] = False
    elif damage == "physical_id": row["physical_section_id"] = "sha256:" + "0" * 64
    elif damage == "boolean_ordinal": row["physical_key"]["parquet_row_index"] = False
    elif damage == "parent_artifact":
        row["physical_key"]["artifact_sha256"] = "0" * 64
        row["physical_section_id"] = "sha256:" + sha(row["physical_key"])
    elif damage == "text_geometry": row["text"]["utf8_bytes"] = 1
    elif damage == "missing_normalized": row["normalized_content_sha256"] = None
    elif damage == "identity_status": row["observed_identity_status"]["ipfs_cid"] = "missing"
    elif damage == "extra_field": row["source_text"] = "unexpected hidden source"
    else:
        state["rows"][2]["text"] = {"sha256": raw_sha(b""), "utf8_bytes": 0, "unicode_characters": 0}
    save_package(state)
    with pytest.raises(ValueError):
        load(state)


@pytest.mark.parametrize("damage", ["missing", "reordered", "duplicate", "interval", "parent_traversal"])
def test_resealed_shard_roster_must_be_safe_complete_ordered_and_nonoverlapping(tmp_path, damage):
    state = package(tmp_path)
    shards = state["manifest"]["shards"]
    if damage == "missing": (state["root"] / shards[-1]["relative_path"]).unlink()
    elif damage == "reordered": shards.reverse()
    elif damage == "duplicate": shards[1] = deepcopy(shards[0])
    elif damage == "interval": shards[0]["end_ordinal"] -= 1
    else: shards[0]["relative_path"] = "../outside.jsonl"
    save_manifest(state)
    with pytest.raises(ValueError):
        load(state)


@pytest.mark.parametrize("damage", ["noncanonical", "duplicate_key", "unterminated", "blank_line"])
def test_rehashed_jsonl_requires_canonical_single_records_and_final_newlines(tmp_path, damage):
    state = package(tmp_path)
    shard = state["manifest"]["shards"][0]
    path = state["root"] / shard["relative_path"]
    lines = path.read_bytes().splitlines(keepends=True)
    if damage == "noncanonical": lines[0] = json.dumps(state["rows"][0], ensure_ascii=False, indent=1).encode() + b"\n"
    elif damage == "duplicate_key": lines[0] = b'{"training_mask":0,' + lines[0][1:]
    elif damage == "unterminated": lines[-1] = lines[-1][:-1]
    else: lines.insert(1, b"\n")
    raw = b"".join(lines)
    old_size = shard["bytes"]
    path.write_bytes(raw)
    shard.update(bytes=len(raw), sha256=raw_sha(raw))
    state["manifest"]["total_metadata_bytes"] += len(raw) - old_size
    save_manifest(state)
    with pytest.raises(ValueError):
        load(state)


@pytest.mark.parametrize("alias", ["manifest", "shard", "root"])
def test_package_files_and_ancestors_cannot_be_symlink_aliases(tmp_path, alias):
    state = package(tmp_path)
    if alias == "manifest":
        real = tmp_path / "real-manifest.json"
        state["path"].rename(real)
        state["path"].symlink_to(real)
        link, target = state["path"], real
    elif alias == "shard":
        path = state["root"] / state["manifest"]["shards"][0]["relative_path"]
        real = tmp_path / "real-shard.jsonl"
        path.rename(real)
        path.symlink_to(real)
        link, target = path, real
    else:
        alias_path = tmp_path / "alias-package"
        alias_path.symlink_to(state["root"], target_is_directory=True)
        state["path"] = alias_path / MANIFEST_NAME
        link, target = alias_path, state["root"]
    try:
        with pytest.raises(ValueError):
            load(state)
    finally:
        # Native durable evidence contains regular files. Remove only this
        # fixture's own exact symlink; retain every original target unchanged.
        if link.is_symlink() and link.readlink() == target:
            link.unlink()


def test_empty_text_is_a_real_hash_while_null_is_unavailable(tmp_path):
    state = package(tmp_path, [
        {"ipfs_cid": "opaque", "title_number": "26", "section_number": "1", "text": ""},
        {"ipfs_cid": None, "title_number": None, "section_number": None, "text": None}])
    inventory = load(state)
    rows = tuple(inventory.iter_rows())
    assert rows[0]["disposition"] == "empty_text" and rows[0]["text"]["sha256"] == raw_sha(b"")
    assert rows[0]["normalized_content_sha256"] == raw_sha(b"")
    assert rows[1]["text"] is rows[1]["normalized_content_sha256"] is None
    preparation = owner.prepare_parent_source_grouping_v1(inventory)
    assert preparation["rows"][0]["keys"]["exact_text_sha256"] == raw_sha(b"")
    assert preparation["rows"][1]["keys"]["exact_text_sha256"] is None


def test_unsupported_text_and_oversize_identity_remain_explicit_not_dropped(tmp_path):
    state = package(tmp_path, [{"ipfs_cid": "雪" * 180, "title_number": None,
        "section_number": "1", "text": 7}], text_kind="int64")
    inventory = load(state)
    row = next(inventory.iter_rows())
    assert row["disposition"] == "unsupported_text_type"
    assert row["observed_identity"]["ipfs_cid"] is None
    assert row["observed_identity_status"]["ipfs_cid"] == "unsupported_size"
    assert row["observed_identity_evidence"]["ipfs_cid"] == {
        "sha256": raw_sha(("雪" * 180).encode()), "utf8_bytes": 540}
    preparation = owner.prepare_parent_source_grouping_v1(inventory)
    assert preparation["row_count"] == len(preparation["rows"]) == 1
    assert preparation["rows"][0]["keys"] == {
        "document": None, "exact_text_sha256": None, "normalized_content_sha256": None}
    assert set(preparation["rows"][0]["blockers"]) == {
        "document_identity_unresolved", "exact_text_unavailable", "normalized_content_unavailable"}


def test_grouping_retains_all_occurrences_without_null_union_alias_or_partition_promotion(tmp_path):
    state = package(tmp_path)
    inventory = load(state)
    preparation = owner.prepare_parent_source_grouping_v1(inventory)
    assert preparation["schema"] == "legal-parent-source-grouping-preparation/v1"
    assert preparation["inventory_sha256"] == inventory.sha256
    assert preparation["row_count"] == len(preparation["rows"]) == 3
    assert preparation["all_required_keys_available"] is False
    assert preparation["complete_source_partitions_constructed"] is False
    assert [row["parquet_row_index"] for row in preparation["rows"]] == [0, 1, 2]
    assert [row["keys"]["document"] for row in preparation["rows"]] == [None, None, None]
    assert preparation["rows"][0]["opaque_cid_observation"] == "same:opaque-alias"
    assert preparation["rows"][0]["keys"] == preparation["rows"][1]["keys"]
    assert preparation["rows"][0]["physical_section_id"] != preparation["rows"][1]["physical_section_id"]
    assert preparation["rows"][2]["keys"]["exact_text_sha256"] is None
    assert preparation["blocker_counts"]["document_identity_unresolved"] == 3
    assert preparation["blocker_counts"]["exact_text_unavailable"] == 1
    assert preparation["preparation_sha256"] == sha({k: v for k, v in preparation.items() if k != "preparation_sha256"})
    assert owner.parent_source_grouping_sha256(preparation) == sha(preparation)
    no_authority(preparation)
    for row in preparation["rows"]:
        assert row["group_id"] is row["split"] is row["inference_view"] is None
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
    preparation["rows"][0]["keys"]["document"] = "invented"
    assert owner.prepare_parent_source_grouping_v1(inventory)["rows"][0]["keys"]["document"] is None


@pytest.mark.parametrize("case", ["row_count", "row_bytes", "package_bytes", "boolean", "raised"])
def test_resource_limits_are_lower_only_plain_integers_and_enforced(tmp_path, case):
    state = package(tmp_path)
    options = {"row_count": {"max_rows": 2}, "row_bytes": {"max_metadata_row_bytes": 64},
        "package_bytes": {"max_total_package_bytes": 32}, "boolean": {"max_rows": True},
        "raised": {"max_rows": 65537}}[case]
    with pytest.raises(ValueError):
        limits = owner.ParentSourceMetadataInventoryLimits(**options)
        load(state, limits=limits)


def test_real_shard_read_followed_by_same_path_mutation_is_refused(tmp_path, monkeypatch):
    state = package(tmp_path)
    path = state["root"] / state["manifest"]["shards"][0]["relative_path"]
    info = path.stat()
    identity = info.st_dev, info.st_ino
    genuine_file = owner._file
    mutations = []
    @contextmanager
    def changing_file(*args, **kwargs):
        # The real file owner opens and validates the genuine file first. The
        # proxy then delegates the actual bounded read and leaves its returned
        # bytes intact; the real owner's exit must detect the private mutation.
        with genuine_file(*args, **kwargs) as (stream, before):
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != identity:
                yield stream, before
                return
            class Reader:
                def readline(self, count):
                    raw = stream.readline(count)
                    if raw and not mutations:
                        # Replace a byte already returned to the caller while
                        # preserving length. The consumed original line/hash is
                        # genuine; later path/FD metadata must reject the edit.
                        with path.open("r+b") as destination:
                            destination.write(b"[")
                        mutations.append(True)
                    return raw
            yield Reader(), before
    monkeypatch.setattr(owner, "_file", changing_file)
    with pytest.raises(ValueError):
        load(state)
    assert mutations == [True]


def test_late_original_limits_mutation_is_revalidated_before_limit_serialization(tmp_path, monkeypatch):
    state = package(tmp_path)
    limits = owner.ParentSourceMetadataInventoryLimits()
    info = state["path"].stat()
    identity = info.st_dev, info.st_ino
    genuine_file, genuine_wire = owner._file, owner._wire
    replacement, mutations = [7], []
    def checked_wire(value):
        if type(value) is dict and value.get("max_rows") is replacement:
            pytest.fail("unchecked caller limits reached serialization")
        return genuine_wire(value)
    @contextmanager
    def changing_file(*args, **kwargs):
        with genuine_file(*args, **kwargs) as (stream, before):
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != identity:
                yield stream, before
                return
            class Reader:
                def read(self, count):
                    raw = stream.read(count)
                    if raw and not mutations:
                        object.__setattr__(limits, "max_rows", replacement)
                        mutations.append(True)
                    return raw
            yield Reader(), before
    monkeypatch.setattr(owner, "_file", changing_file)
    monkeypatch.setattr(owner, "_wire", checked_wire)
    with pytest.raises(owner.ParentSourceMetadataInventoryError, match="bounded plain integer"):
        load(state, limits=limits)
    assert mutations == [True]


def read_reference(ref, *, maximum):
    assert type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}
    assert type(ref["bytes"]) is int and 0 < ref["bytes"] <= maximum
    path = Path(ref["path"])
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert path.stat().st_size == ref["bytes"]
    raw = path.read_bytes()
    assert len(raw) == ref["bytes"] and raw_sha(raw) == ref["sha256"]
    return json.loads(raw)


@pytest.mark.integration
@pytest.mark.heavy
@pytest.mark.skipif(
    os.environ.get("LEGAL_PARENT_METADATA_LOADER_ENROLLED") != "1",
    reason="historical metadata replay requires explicit LEGAL_PARENT_METADATA_LOADER_ENROLLED=1 enrollment",
)
def test_real_saved60077_package_requires_original_owned_loader_enrollment(tmp_path):
    # A roster marker is not resource/source admission. The reviewed native
    # driver must freeze/admit this exact input request and every listed shard
    # before selecting this case. Once enrolled, missing inputs or mismatched
    # evidence are failures; the assertions below are unchanged.
    assert os.environ["LEGAL_PARENT_METADATA_LOADER_ENROLLED"] == "1"
    request, request_ref = pinned_json("LEGAL_PARENT_METADATA_LOADER_INPUTS", INPUTS_BYTES, INPUTS_SHA256)
    assert set(request) == {"schema", "manifest", "shards", "row_pins", "retained_sections",
        "expected_parent_descriptor_sha256", "expected_preflight_report_sha256", "prior_qualification"}
    assert request["schema"] == "legal-parent-source-metadata-loader-inputs/v1"
    assert request["expected_parent_descriptor_sha256"] == "27c6baf5f435870fa87f8ea8481672737f75c721fa0a1cadb85704fd1baac284"
    assert request["expected_preflight_report_sha256"] == "9e1801654f9c351087ad8d053e90eadf222918050f21fcb9b63928dff2ae840f"
    assert set(request["prior_qualification"]) == {"summary", "saved_readback"}
    pins = read_reference(request["row_pins"], maximum=4096)
    retained = read_reference(request["retained_sections"], maximum=128 * 1024)
    for key in ("row_pins", "retained_sections"):
        _, size, digest = REAL_ORIGINALS[key]
        assert request[key]["bytes"] == size and request[key]["sha256"] == digest
    manifest = read_reference(request["manifest"], maximum=2 * 1024**2)
    parent = pins["source_descriptor"]
    assert manifest["parent"] == parent and sha(parent) == request["expected_parent_descriptor_sha256"]
    assert parent["row_count"] == 60077 and parent["bytes"] == 374277662
    assert parent["sha256"] == "4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8"
    assert pins["row_ordinals"] == REAL_ORDINALS
    assert len(manifest["source_schema"]) == 45
    assert manifest["row_count"] == 60077 and len(manifest["shards"]) == len(request["shards"]) == 26
    root = Path(request["manifest"]["path"]).parent
    for declared, original in zip(manifest["shards"], request["shards"], strict=True):
        assert original == {"path": str(root / declared["relative_path"]),
            "bytes": declared["bytes"], "sha256": declared["sha256"]}
    inventory = owner.load_parent_source_metadata_inventory_v1(request["manifest"]["path"],
        expected_manifest_sha256=request["manifest"]["sha256"],
        expected_parent_descriptor_sha256=request["expected_parent_descriptor_sha256"],
        expected_preflight_report_sha256=request["expected_preflight_report_sha256"])
    assert inventory.row_count == 60077 and inventory.manifest == manifest
    assert inventory.manifest_canonical_sha256 == sha(manifest)
    assert inventory.to_dict()["current_source_bytes_verified"] is False
    selected_hashes = dict(zip(REAL_ORDINALS, pins["expected_row_sha256s"], strict=True))
    sections = {row["parquet_row_index"]: row for row in retained["source_sections"]}
    dispositions, selected, missing = Counter(), [], []
    canonical_bytes, count = 0, 0
    for ordinal, row in enumerate(inventory.iter_rows()):
        key = physical_key(parent, ordinal)
        assert row["physical_key"] == key and row["physical_section_id"] == "sha256:" + sha(key)
        no_authority(row)
        dispositions[row["disposition"]] += 1
        canonical_bytes += row["raw_row_canonical_bytes"]
        count += 1
        if ordinal in selected_hashes:
            section = sections[ordinal]
            text = section["text"]
            assert row["full_raw_row_sha256"] == selected_hashes[ordinal]
            assert all(row["physical_key"][name] == section[name] for name in row["physical_key"])
            assert row["text"] == {"sha256": raw_sha(text.encode()), "utf8_bytes": len(text.encode()),
                "unicode_characters": len(text)}
            assert row["text"]["sha256"] == section["text_sha256"]
            assert row["observed_identity"]["ipfs_cid"] == section["entry_cid"]
            assert row["normalized_content_sha256"] == raw_sha(" ".join(text.split()).casefold().encode())
            selected.append(row)
        if ordinal >= 60068:
            assert row["disposition"] == "missing_text"
            assert row["text"] is row["normalized_content_sha256"] is None
            assert all(value is None for value in row["observed_identity"].values())
            assert all(value == "missing" for value in row["observed_identity_status"].values())
            assert all(value is None for value in row["observed_identity_evidence"].values())
            missing.append({"physical_section_id": row["physical_section_id"], "physical_key": key,
                "full_raw_row_sha256": row["full_raw_row_sha256"], "disposition": row["disposition"],
                "text": row["text"], "normalized_content_sha256": row["normalized_content_sha256"],
                "observed_identity": row["observed_identity"],
                "observed_identity_status": row["observed_identity_status"],
                "observed_identity_evidence": row["observed_identity_evidence"]})
    assert count == 60077 and len(selected) == 13 and len(missing) == 9
    assert dispositions == {"stored_text_available": 60068, "missing_text": 9}
    assert canonical_bytes == manifest["raw_row_canonical_bytes"] == 1277511548
    assert manifest["total_metadata_bytes"] == 108348325
    assert manifest["page_count"] == 423 and manifest["decoded_page_bytes"] == 1169575763
    preparation = owner.prepare_parent_source_grouping_v1(inventory)
    assert preparation["row_count"] == len(preparation["rows"]) == 60077
    assert preparation["all_required_keys_available"] is False
    assert preparation["complete_source_partitions_constructed"] is False
    for ordinal, row in enumerate(preparation["rows"]):
        assert row["parquet_row_index"] == ordinal
        assert row["physical_section_id"] == "sha256:" + sha(physical_key(parent, ordinal))
        assert row["keys"]["document"] is None and "document_identity_unresolved" in row["blockers"]
        assert row["group_id"] is row["split"] is row["inference_view"] is None
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
        if ordinal >= 60068:
            assert row["keys"]["exact_text_sha256"] is row["keys"]["normalized_content_sha256"] is None
            assert set(row["blockers"]) == {"document_identity_unresolved", "exact_text_unavailable",
                "normalized_content_unavailable"}
    assert preparation["blocker_counts"] == {"document_identity_unresolved": 60077,
        "exact_text_unavailable": 9, "normalized_content_unavailable": 9}
    no_authority(preparation)
    preparation_canonical_sha = owner.parent_source_grouping_sha256(preparation)
    assert preparation_canonical_sha == sha(preparation)
    assert preparation["preparation_sha256"] == sha({key: value for key, value in preparation.items()
        if key != "preparation_sha256"})
    evidence = {"schema": "legal-parent-source-metadata-loader-engineering-evidence/v1",
        "input_request": request_ref, "manifest": request["manifest"],
        "originals": {"independent_selected_row_pins": request["row_pins"],
            "retained_sections_assertion_only": request["retained_sections"]},
        "prior_qualification_custody_refs_only": request["prior_qualification"],
        "inventory": inventory.to_dict(), "row_count": count, "shard_count": 26,
        "source_columns": 45, "disposition_counts": dict(dispositions),
        "canonical_raw_row_bytes": canonical_bytes, "metadata_shard_bytes": manifest["total_metadata_bytes"],
        "independent_full_row_hash_oracles_checked": 13, "other_full_row_hashes_have_independent_oracles": False,
        "selected_independent_oracle_rows": selected, "missing_identity_rows": missing,
        "preparation": {"schema": preparation["schema"], "row_count": preparation["row_count"],
            "preparation_sha256": preparation["preparation_sha256"],
            "full_canonical_sha256": preparation_canonical_sha,
            "key_availability_counts": preparation["key_availability_counts"],
            "blocker_counts": preparation["blocker_counts"],
            "all_required_keys_available": False, "complete_source_partitions_constructed": False},
        "worker_lifetime_peak_rss_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peak_rss_scope": "Whole worker lifetime high-water mark; not isolated loader memory or a bound proof.",
        "parent_body_opened_here": False, "source_authentication_supplied": False,
        "partitions_assigned": False, "semantic_or_training_eligibility_supplied": False,
        "scope": "Saved genuine producer-package custody and incomplete source-only grouping preparation. All60077 metadata occurrences are checked; only13 independent retained row/text commitments are available. Prior qualification references are not rerun or inherited source authority."}
    raw = wire(evidence) + b"\n"
    assert len(raw) <= 128 * 1024
    (tmp_path / EVIDENCE_NAME).write_bytes(raw)
