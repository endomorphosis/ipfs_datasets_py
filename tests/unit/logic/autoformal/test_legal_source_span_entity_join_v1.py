"""Three-cache orchestration, with already-qualified delegates replaced by fakes.

These tests exercise selection custody and manifest replay. They neither claim
that the fake records qualify a lower transport nor decode a real source table.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as join


ENTITY_FIELDS = (
    "record_kind", "meta_category", "graph_kind", "label", "legal_id", "node_id",
    "src", "dst", "logic_role", "in_formula", "admitted", "formalized",
)
BOOLEAN_FIELDS = ("in_formula", "admitted", "formalized")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def paired_row(marker="same", *, ordinal=0, disposition="candidate_unbound"):
    value = {
        "schema_version": "uscode-paired-span-census/v1",
        "observation_id": "observation-" + marker,
        "source": {"span_id": "span-" + marker, "revision": "ipfs-uscode-5016b86a",
                   "legal_id": "10 USC 101", "text": "§ Clerk shall file.",
                   "text_sha256": sha("§ Clerk shall file.".encode())},
        "opaque_formal_outputs": ["same", "same"],
    }
    raw = wire(value)
    return {"row_ordinal": ordinal, "observation_id": value["observation_id"],
            "row_sha256": sha(raw), "derived_row_json": raw.decode(),
            "disposition": disposition, "candidate": None,
            "error": {"type": "CorpusContractError", "message": "unsupported"}
            if disposition == "adapter_rejected" else None}


@pytest.fixture
def harness(monkeypatch):
    source_raw = wire({"schema": "fake-source-request/v1",
                       "repository_id": "justicedao/ipfs_uscode", "revision": "a" * 40})
    paired_raw = wire({"schema": "fake-paired-request/v1", "revision": "b" * 40})
    info = {"partial": False, "dataset_info": {"dataset_name": "uscode-autoformal-entity-cache",
        "config_name": "autoformal_uscode",
        "features": {field: {"_type": "Value", "dtype": "bool" if field in BOOLEAN_FIELDS else "string"}
                     for field in ENTITY_FIELDS}, "splits": {"train": {"num_examples": 1960876}}}}
    selected = []
    payloads = {}
    blobs = {}
    locations = []
    for index, version in enumerate((1, 2)):
        path = f"autoformal/uscode/paired-v{version}/manifests/bank{index}/manifest.json"
        table = {"path_in_repo": f"paired-v{version}/rows-{index}.parquet",
                 "sha256": sha(f"file-{index}".encode()), "row_count": 1}
        blobs[path] = wire({"table": table})
        selected.append({"path_in_repo": path, "sha256": sha(blobs[path]),
                         "bank": f"paired-v{version}",
                         "manifest": {"tables": {"paired_spans": table}}})
        locations.append({"manifest_path_in_repo": path, "repository_root": "/retained/" + "b" * 40})
        payloads[path] = {"rows": [paired_row()], "source_bindings_supplied": False}
    state = {
        "source_raw": source_raw, "paired_raw": paired_raw, "info_raw": wire(info),
        "source_metadata": {"manifest.json": b'{"source":"metadata only"}'},
        "manifest_bytes": blobs, "payloads": payloads, "legacy_inputs": {},
        "legacy_candidates": {}, "calls": [], "pins": {"fake-owner": "f" * 64},
        "source_report": {"profile": "publicus-ir-graphrag/v2", "table_rows_verified": False,
                          "integrity_issues": [{"path": "README.md", "status": "digest_mismatch"}]},
        "inventory": {"repository_id": "justicedao/uscode-autoformal-span-cache",
                      "revision": "b" * 40, "manifests": selected},
    }
    state["request"] = {"schema": join.REQUEST_SCHEMA,
        "source_request_sha256": sha(source_raw), "paired_inventory_request_sha256": sha(paired_raw),
        "paired_bundles": locations, "legacy_joins": {},
        "entity": {"repository_id": "justicedao/uscode-autoformal-entity-cache",
                   "revision": "c" * 40, "configuration": "autoformal_uscode",
                   "info_sha256": sha(state["info_raw"])}}
    original_source_metadata = dict(state["source_metadata"])
    original_manifests = dict(blobs)

    def source_prepare(raw, metadata, *, expected_request_sha256):
        state["calls"].append(("source", raw))
        assert raw == source_raw and sha(raw) == expected_request_sha256
        assert metadata == original_source_metadata
        return state["source_report"]

    def inventory_prepare(raw, manifests, *, expected_request_sha256):
        state["calls"].append(("inventory", raw))
        assert raw == paired_raw and sha(raw) == expected_request_sha256
        assert manifests == original_manifests
        return state["inventory"]

    def payload_prepare(**kwargs):
        state["calls"].append(("payload", dict(kwargs)))
        assert "source_bindings" not in kwargs
        path = kwargs["manifest_path_in_repo"]
        selection = next(row for row in selected if row["path_in_repo"] == path)
        location = next(row for row in state["request"]["paired_bundles"]
                        if row["manifest_path_in_repo"] == path)
        assert kwargs == {"repository_root": location["repository_root"],
            "repository_id": state["inventory"]["repository_id"],
            "revision": state["inventory"]["revision"], "manifest_path_in_repo": path,
            "expected_manifest_sha256": selection["sha256"]}
        return payloads[path]

    def legacy_prepare(raw_rows, **kwargs):
        state["calls"].append(("legacy", (list(raw_rows), deepcopy(kwargs))))
        assert [sha(raw) for raw in raw_rows] == [row["row_sha256"] for row in kwargs["expected_population"]]
        return {"profile": "pinned-parquet-text-column-as-stored/v1",
                "rows": [deepcopy(state["legacy_candidates"][sha(raw)]) for raw in raw_rows]}

    owners = (SimpleNamespace(prepare_source_package_intake=source_prepare),
              SimpleNamespace(prepare_paired_manifest_inventory=inventory_prepare),
              SimpleNamespace(prepare_paired_payload_intake=payload_prepare),
              SimpleNamespace(build_legacy_source_join=legacy_prepare),
              SimpleNamespace(FIELDS=ENTITY_FIELDS, BOOLEAN_FIELDS=BOOLEAN_FIELDS, MAX_ROWS=3000000))
    state["owners"] = owners
    monkeypatch.setattr(join, "_owners", lambda: (*owners, dict(state["pins"])))
    return state


def arguments(state):
    return (wire(state["request"]), state["source_raw"], state["source_metadata"],
            state["paired_raw"], state["manifest_bytes"], state["info_raw"])


def prepare(state):
    args = arguments(state)
    return join.prepare_source_span_entity_join_manifest(*args,
        expected_request_sha256=sha(args[0]), legacy_join_inputs=state["legacy_inputs"])


def replay(state, report, *, expected_report_sha256=None):
    args = arguments(state)
    return join.validate_source_span_entity_join_manifest(report, *args,
        expected_request_sha256=sha(args[0]), legacy_join_inputs=state["legacy_inputs"],
        expected_report_sha256=expected_report_sha256 or join.source_span_entity_join_manifest_sha256(report))


def add_legacy_candidates(state, path, *, count=1):
    rows = state["payloads"][path]["rows"]
    expected = []
    for row in rows:
        original = json.loads(row["derived_row_json"])
        expected.append({"row_sha256": row["row_sha256"], "source_span_id": original["source"]["span_id"],
            "text_sha256": original["source"]["text_sha256"], "source_revision": original["source"]["revision"]})
        state["legacy_candidates"][row["row_sha256"]] = {
            "row_sha256": row["row_sha256"], "selected_occurrence": None,
            "original_producer_occurrence_attested": False, "occurrence_count": count,
            "disposition": "unique_exact_candidate" if count == 1 else "ambiguous_exact_candidates",
            "candidates": [{"source_occurrence": {"record_cid": "fake-occurrence-" + str(index)},
                            "context_declaration": {"availability": "required_unavailable"}}
                           for index in range(count)],
        }
    inputs = {"expected_population": expected, "producer_receipt_bytes": None,
              "expected_producer_receipt_sha256": None,
              "source_sections": [], "expected_source_sections": []}
    state["legacy_inputs"][path] = inputs
    state["request"]["legacy_joins"][path] = join.legacy_join_inputs_sha256(inputs)


def owner_must_not_load(monkeypatch):
    monkeypatch.setattr(join, "_owners", lambda: pytest.fail("owners loaded before input refusal"))


def test_exact_replay_preserves_distinct_physical_rows_with_identical_content(harness):
    report = prepare(harness)
    assert replay(harness, report) == report
    assert replay(harness, wire(report), expected_report_sha256=join.source_span_entity_join_manifest_sha256(report)) == report
    assert report["counts"]["physical_paired_rows"] == report["counts"]["selected_row_references"] == 2
    references = report["row_references"]
    assert references[0]["row_sha256"] == references[1]["row_sha256"]
    assert references[0]["physical_identity_sha256"] != references[1]["physical_identity_sha256"]
    assert [row["bank"] for row in references] == ["paired-v1", "paired-v2"]
    assert [row["row_reference_ordinals"] for row in report["physical_rows"]] == [[0], [1]]
    assert [row["payload_intake"] for row in report["paired_bundles"]] == list(harness["payloads"].values())
    assert report["request_raw_utf8"].encode() == arguments(harness)[0]
    assert report["selection_complete"] is True
    assert all(value is False for value in report["authority"].values())
    for row in [report, *references]:
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0


def test_repeated_manifest_reference_keeps_references_without_double_counting_physical_row(harness):
    first, second = harness["inventory"]["manifests"]
    second["manifest"]["tables"]["paired_spans"] = deepcopy(first["manifest"]["tables"]["paired_spans"])
    report = prepare(harness)
    assert report["counts"]["selected_row_references"] == 2
    assert report["counts"]["physical_paired_rows"] == 1
    assert report["physical_rows"][0]["row_reference_ordinals"] == [0, 1]
    assert len(report["row_references"]) == 2


def test_conflicting_observations_for_same_physical_row_refuse(harness):
    first, second = harness["inventory"]["manifests"]
    second["manifest"]["tables"]["paired_spans"] = deepcopy(first["manifest"]["tables"]["paired_spans"])
    harness["payloads"][second["path_in_repo"]]["rows"] = [paired_row("different")]
    with pytest.raises(ValueError, match="conflicting observations"):
        prepare(harness)


def test_unique_legacy_candidate_stays_unselected_and_current_source_is_separate(harness):
    path = harness["inventory"]["manifests"][0]["path_in_repo"]
    add_legacy_candidates(harness, path)
    report = prepare(harness)
    row = report["row_references"][0]
    assert row["source_disposition"] == "unique_exact_candidate"
    assert row["selected_occurrence"] is row["source_candidate_record"]["selected_occurrence"] is None
    assert row["source_candidate_record"]["original_producer_occurrence_attested"] is False
    assert row["producer_source_revision_label"] == "ipfs-uscode-5016b86a"
    assert row["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["source_repository"]["revision"] == "a" * 40
    assert report["source_metadata_intake"]["profile"] == "publicus-ir-graphrag/v2"
    assert report["paired_bundles"][0]["legacy_candidate_join"]["profile"] == "pinned-parquet-text-column-as-stored/v1"
    assert report["source_metadata_intake"]["integrity_issues"] == harness["source_report"]["integrity_issues"]
    assert report["counts"]["candidate_occurrence_references"] == 1
    assert report["counts"]["distinct_candidate_occurrence_cids"] == 1
    assert replay(harness, report) == report


def test_duplicate_rows_within_file_remain_physical_rows_and_delegate_candidate_computation_once(harness):
    selected = harness["inventory"]["manifests"][0]
    path = selected["path_in_repo"]
    second = deepcopy(harness["payloads"][path]["rows"][0])
    second["row_ordinal"] = 1
    harness["payloads"][path]["rows"].append(second)
    selected["manifest"]["tables"]["paired_spans"]["row_count"] = 2
    add_legacy_candidates(harness, path, count=2)
    report = prepare(harness)
    assert report["counts"]["physical_paired_rows"] == 3
    assert report["counts"]["candidate_occurrence_references"] == 4
    assert report["counts"]["distinct_candidate_occurrence_cids"] == 2
    calls = [value for kind, value in harness["calls"] if kind == "legacy"]
    assert len(calls) == 1 and len(calls[0][0]) == len(calls[0][1]["expected_population"]) == 1
    assert [row["physical_identity"]["row_ordinal"] for row in report["row_references"]] == [0, 1, 0]


def test_rejected_candidate_and_missing_join_remain_in_denominator(harness):
    path = harness["inventory"]["manifests"][0]["path_in_repo"]
    row = harness["payloads"][path]["rows"][0]
    row["disposition"] = "adapter_rejected"
    row["error"] = {"type": "CorpusContractError", "message": "explicit refusal"}
    report = prepare(harness)
    assert report["counts"]["source_dispositions"] == {
        "paired_candidate_adapter_rejected": 1, "source_join_unavailable": 1}
    assert len(report["row_references"]) == 2
    assert report["paired_bundles"][0]["payload_intake"]["rows"][0]["error"] == row["error"]


def test_entity_schema_is_metadata_only_and_never_populates_entity_bindings(harness):
    report = prepare(harness)
    entity = report["entity_metadata"]
    assert entity["declared_rows"] == 1960876
    assert entity["verified_file_rows"] == report["counts"]["entity_file_rows_verified"] == 0
    assert entity["scope"] == "metadata_only_no_entity_file_or_semantic_companions"
    assert entity["schema_fields"] == list(ENTITY_FIELDS)
    assert entity["raw_utf8"].encode() == harness["info_raw"]
    assert all(row["entity_binding"] == "unavailable_semantic_companions_not_supplied"
               for row in report["row_references"])
    assert not report["authority"]["entity_file_rows_verified"]


@pytest.mark.parametrize("damage", ["extra", "missing", "schema", "source_pin", "paired_pin",
    "duplicate_bundle", "relative_root", "parent_root", "foreign_entity", "moving_revision", "entity_config"])
def test_closed_request_and_nested_pins_refuse_before_owners(harness, monkeypatch, damage):
    request = harness["request"]
    if damage == "extra": request["extra"] = None
    elif damage == "missing": request.pop("entity")
    elif damage == "schema": request["schema"] = "other/v1"
    elif damage == "source_pin": request["source_request_sha256"] = "0" * 64
    elif damage == "paired_pin": request["paired_inventory_request_sha256"] = "0" * 64
    elif damage == "duplicate_bundle": request["paired_bundles"].append(deepcopy(request["paired_bundles"][0]))
    elif damage == "relative_root": request["paired_bundles"][0]["repository_root"] = "relative/root"
    elif damage == "parent_root": request["paired_bundles"][0]["repository_root"] = "/retained/../foreign"
    elif damage == "foreign_entity": request["entity"]["repository_id"] = "other/entity"
    elif damage == "moving_revision": request["entity"]["revision"] = "main"
    elif damage == "entity_config": request["entity"]["configuration"] = "other"
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError):
        prepare(harness)


@pytest.mark.parametrize("which", ["request", "source", "paired", "entity"])
def test_independent_exact_bytes_not_self_reported_hashes_are_required(harness, monkeypatch, which):
    args = list(arguments(harness))
    original = sha(args[0])
    index = {"request": 0, "source": 1, "paired": 3, "entity": 5}[which]
    args[index] += b" "
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError):
        join.prepare_source_span_entity_join_manifest(*args, expected_request_sha256=original)


def test_changed_legacy_input_or_unlisted_bank_refuses_before_owners(harness, monkeypatch):
    path = harness["inventory"]["manifests"][0]["path_in_repo"]
    add_legacy_candidates(harness, path)
    harness["legacy_inputs"][path]["source_sections"].append({"text": "changed"})
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="commitment differs"):
        prepare(harness)
    harness["request"]["legacy_joins"] = {}
    with pytest.raises(ValueError, match="population differs"):
        prepare(harness)


def test_source_delegation_cannot_mutate_snapshotted_legacy_inputs(harness, monkeypatch):
    path = harness["inventory"]["manifests"][0]["path_in_repo"]
    add_legacy_candidates(harness, path)
    original = deepcopy(harness["legacy_inputs"][path])
    source = harness["owners"][0]
    source_prepare = source.prepare_source_package_intake

    def mutate_caller_inputs(*args, **kwargs):
        result = source_prepare(*args, **kwargs)
        supplied = harness["legacy_inputs"][path]
        supplied["expected_population"][0]["source_span_id"] = "changed-after-preflight"
        supplied["source_sections"].append({"text": "changed source section"})
        supplied["expected_source_sections"].append({"legal_id": "changed expectation"})
        return result

    monkeypatch.setattr(source, "prepare_source_package_intake", mutate_caller_inputs)
    report = prepare(harness)
    calls = [value for kind, value in harness["calls"] if kind == "legacy"]
    assert len(calls) == 1
    assert calls[0][1] == original
    assert harness["legacy_inputs"][path] != original
    assert report["row_references"][0]["source_disposition"] == "unique_exact_candidate"
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="legacy join input commitment differs"):
        replay(harness, report)


@pytest.mark.parametrize("damage", ["partial", "dataset", "config", "missing_field", "wrong_type",
                                     "missing_train", "row_boolean"])
def test_entity_metadata_contract_refuses_incompatible_views(harness, damage):
    info = json.loads(harness["info_raw"])
    if damage == "partial": info["partial"] = True
    elif damage == "dataset": info["dataset_info"]["dataset_name"] = "foreign-entity-cache"
    elif damage == "config": info["dataset_info"]["config_name"] = "other"
    elif damage == "missing_field": info["dataset_info"]["features"].pop("node_id")
    elif damage == "wrong_type": info["dataset_info"]["features"]["admitted"]["dtype"] = "string"
    elif damage == "missing_train": info["dataset_info"]["splits"].pop("train")
    elif damage == "row_boolean": info["dataset_info"]["splits"]["train"]["num_examples"] = True
    harness["info_raw"] = wire(info)
    harness["request"]["entity"]["info_sha256"] = sha(harness["info_raw"])
    with pytest.raises(ValueError):
        prepare(harness)


@pytest.mark.parametrize("damage", ["selection_order", "payload_count", "row_order", "row_hash", "source_bound"])
def test_replayed_payload_must_cover_exact_selected_physical_population(harness, damage):
    path = harness["inventory"]["manifests"][0]["path_in_repo"]
    row = harness["payloads"][path]["rows"][0]
    if damage == "selection_order": harness["request"]["paired_bundles"].reverse()
    elif damage == "payload_count": harness["payloads"][path]["rows"].clear()
    elif damage == "row_order": row["row_ordinal"] = 1
    elif damage == "row_hash": row["row_sha256"] = "0" * 64
    elif damage == "source_bound": row["disposition"] = "candidate_bound"
    with pytest.raises(ValueError):
        prepare(harness)


@pytest.mark.parametrize("damage", ["counts", "omit_physical", "select_occurrence", "crosswalk", "source", "authority", "mask"])
def test_resealed_report_cannot_replace_complete_replay(harness, damage):
    report = prepare(harness)
    forged = deepcopy(report)
    if damage == "counts": forged["counts"]["physical_paired_rows"] += 1
    elif damage == "omit_physical": forged["physical_rows"].pop()
    elif damage == "select_occurrence": forged["row_references"][0]["selected_occurrence"] = "invented"
    elif damage == "crosswalk": forged["row_references"][0]["current_source_release_correspondence"] = "exact"
    elif damage == "source": forged["source_metadata_intake"]["integrity_issues"] = []
    elif damage == "authority": forged["authority"]["admitted"] = True
    elif damage == "mask": forged["training_mask"] = 1
    with pytest.raises(ValueError, match="full replay"):
        replay(harness, forged)


def test_wrong_report_pin_refuses_before_delegation(harness, monkeypatch):
    report = prepare(harness)
    owner_must_not_load(monkeypatch)
    with pytest.raises(ValueError, match="report SHA256"):
        replay(harness, report, expected_report_sha256="0" * 64)


def test_changed_delegated_source_evidence_invalidates_previously_pinned_report(harness):
    report = prepare(harness)
    harness["source_report"]["integrity_issues"].append({"path": "new", "status": "unavailable"})
    with pytest.raises(ValueError, match="full replay"):
        replay(harness, report)


def test_output_is_detached_from_all_delegated_reports_and_caller_inputs(harness):
    before = deepcopy({key: harness[key] for key in ("request", "payloads", "source_report", "inventory", "source_metadata")})
    report = prepare(harness)
    assert {key: harness[key] for key in before} == before
    report["paired_bundles"][0]["payload_intake"]["rows"].clear()
    report["source_metadata_intake"]["integrity_issues"].clear()
    report["request"]["paired_bundles"].clear()
    assert {key: harness[key] for key in before} == before


def test_population_and_report_bounds_refuse_without_partial_manifest(harness, monkeypatch):
    monkeypatch.setattr(join, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="population exceeds bound"):
        prepare(harness)
    monkeypatch.setattr(join, "MAX_ROWS", 256)
    monkeypatch.setattr(join, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError):
        prepare(harness)


def test_changed_owner_generation_refuses_the_complete_result(harness, monkeypatch):
    calls = 0

    def owners():
        nonlocal calls
        calls += 1
        return (*harness["owners"], {"fake-owner": ("f" if calls == 1 else "e") * 64})

    monkeypatch.setattr(join, "_owners", owners)
    with pytest.raises(ValueError, match="owners changed"):
        prepare(harness)
