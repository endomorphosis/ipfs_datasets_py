"""Complete authored context inventories, without inference-permission claims.

The supplied contexts are explicitly target-derived test declarations. Tests
exercise the existing public batch and prefix owners without models, training,
reference repair, or protected data. Execution belongs to native admission.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_content_context_evaluation_v1 as owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens


def _fixtures():
    path = Path(__file__).with_name("test_legal_relational_content_token_batch_evaluation_v1.py")
    spec = importlib.util.spec_from_file_location("_content_context_inventory_authored_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fixtures = _fixtures()
material = fixtures.material
wire, sha = fixtures.wire, fixtures.sha
SCHEMA = "legal-relational-content-context-inventory/v1"
REPORT_SCHEMA = "legal-relational-content-context-evaluation/v1"
DECLARED = ("unavailable", "unsupported", "pending", "error", "timeout", "cancellation", "not_started")
AVAILABILITY = {"available", *DECLARED, "missing", "duplicate", "malformed", "unverifiable_binding"}
BINDINGS = {"matched", "mismatched", "unavailable", "missing", "duplicate", "malformed",
            "unverifiable_binding", "unexpected", "unidentifiable", "not_generated"}


def available(row, context, *, origin="target_derived_label", raw=None, **changes):
    raw = wire(context) if raw is None else raw
    return {**row, "status": "available", "content_context_utf8": raw.decode("utf-8"),
        "content_context_sha256": sha(raw), "content_context_origin": origin, "reason": None, **changes}


def absent(row, status):
    return {**row, "status": status, "content_context_utf8": None, "content_context_sha256": None,
        "content_context_origin": None, "reason": "Explicit authored context disposition"}


def make_case(material, ids=("one",), *, unavailable=()):
    case = fixtures.make_case(material, ids, unavailable=unavailable)
    case["contexts"] = {"schema": SCHEMA, "population_sha256": sha(case["population_raw"]),
        "rows": [available(row, material["context"]) for row in case["population"]["rows"]]}
    return case


def originals(case):
    raw, pins = fixtures.legacy.originals(case)
    contexts_raw = case.get("contexts_raw", wire(case["contexts"]))
    return (*raw, contexts_raw), {**pins, "expected_contexts_sha256": sha(contexts_raw)}


def prepare(case, **changes):
    raw, pins = originals(case)
    return owner.prepare_relational_content_context_evaluation_v1(*raw, **{**pins, **changes})


def validate(case, report, **changes):
    raw, pins = originals(case)
    return owner.validate_relational_content_context_evaluation_v1(report, *raw,
        **{**pins, "expected_evaluation_sha256": sha(wire(report)), **changes})


def direct_prefix(row, material):
    return tokens.compact_content_allowed_token_ids_v1([], row["content_context_utf8"].encode("utf-8"),
        expected_context_sha256=row["content_context_sha256"], codec=material["codec"],
        expected_codec_sha256=material["codec_sha256"])


def boundaries(report):
    assert report["schema"] == REPORT_SCHEMA
    assert report["profile"] == "full-selected-unverified-content-context-inventory/v1"
    assert report["context_claims_are_declarations_only"] is True
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for name in ("permitted_inference_context_verified", "content_context_origin_verified",
                 "content_context_independence_verified", "context_available_before_generation_verified",
                 "context_inventory_completeness_authenticated", "numerical_execution_authenticated"):
        assert report["authority"][name] is False
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert set(report["availability_counts"]) == AVAILABILITY
    assert sum(report["availability_counts"].values()) == len(report["occurrences"])
    assert set(report["generated_context_binding_counts"]) == BINDINGS
    assert sum(report["generated_context_binding_counts"].values()) == len(report["generated_context_bindings"])
    assert report["population"] == report["original_evaluation"]["population"]
    assert report["original_evaluation_sha256"] == sha(wire(report["original_evaluation"]))
    fixtures.assert_no_authority(report["original_evaluation"])
    for row in report["observation_ledger"]:
        assert row["sha256"] == sha(wire(row["raw_observation"]))
        if row["available_prefix"] is not None:
            assert row["available_prefix_sha256"] == sha(wire(row["available_prefix"]))
            assert all(value is False for value in row["available_prefix"]["authority"].values())


def retain(case, report, directory, record_property):
    directory.mkdir()
    raw, _ = originals(case)
    artifacts = dict(zip(("population.json", "references.json", "predictions.json", "contexts.json"), raw))
    artifacts.update({"request.json": wire(case["request"]), "report.json": wire(report)})
    artifacts["source-declarations.json"] = wire({"authored_fixture": True, "statutory_source": False,
        "context_origin": "target_derived_label", "context_permission_verified": False, "model_executed": False,
        "rows": [{"id": row["id"], "source_text": "source:" + row["id"],
                  "source_context_text": "context:" + row["id"], "source_sha256": row["source_sha256"],
                  "source_context_sha256": row["context_sha256"]} for row in case["population"]["rows"]]})
    manifest = {}
    for name, value in artifacts.items():
        path = directory / name
        path.write_bytes(value)
        manifest[name] = {"path": str(path), "bytes": len(value), "sha256": sha(value)}
    raw_manifest = wire({"schema": "authored-content-context-inventory-fixture/v1", "artifacts": manifest})
    path = directory / "manifest.json"
    path.write_bytes(raw_manifest)
    record_property("content_context_inventory_fixture", json.dumps({"path": str(path), "sha256": sha(raw_manifest)}, sort_keys=True))


def test_unique_available_context_has_real_prefix_evidence_and_unchanged_public_batch(material):
    case = make_case(material)
    before = deepcopy(case)
    original = fixtures.prepare(case)
    report = prepare(case)
    assert case == before and report["original_evaluation"] == original
    assert validate(case, report) == report
    assert owner.relational_content_context_evaluation_sha256(report) == sha(wire(report))
    assert report["coverage"]["valid"] is True
    assert report["availability_counts"]["available"] == 1
    ledger = report["observation_ledger"][0]
    assert ledger["available_prefix"] == direct_prefix(case["contexts"]["rows"][0], material)
    assert ledger["raw_observation"] == case["contexts"]["rows"][0]
    assert ledger["available_prefix"]["offered_ids"] == []
    bound = report["generated_context_bindings"][0]
    assert bound["status"] == "matched" and bound["original_outcome"] == "compared"
    assert bound["raw_equal"] is bound["canonical_equal"] is bound["origin_equal"] is True
    boundaries(report)


def test_missing_inventory_never_borrows_generated_or_reference_context_and_keeps_all_selected(material):
    case = make_case(material, ("first", "second"), unavailable={"second"})
    case["contexts"]["rows"] = []
    original = fixtures.prepare(case)
    report = prepare(case)
    assert report["original_evaluation"] == original
    assert report["availability_counts"]["missing"] == 2
    assert report["coverage"]["missing_ids"] == ["first", "second"]
    assert report["observation_ledger"] == []
    assert [row["status"] for row in report["generated_context_bindings"]] == ["missing", "missing"]
    assert original["valid_typed_output"] == {"count": 2, "total": 2, "fraction": 1.0}
    boundaries(report)


def test_mixed_context_population_retains_all_declarations_duplicates_orphans_and_raw_rows(material, tmp_path, record_property):
    names = ["available", *DECLARED, "missing", "duplicate", "malformed", "unverifiable_binding"]
    case = make_case(material, names)
    rows = {row["id"]: row for row in case["population"]["rows"]}
    offered = [available(rows["available"], material["context"]),
        *[absent(rows[name], name) for name in DECLARED],
        available(rows["duplicate"], material["context"]), absent(rows["duplicate"], "pending"),
        available(rows["malformed"], material["context"], extra="original observation retained"),
        available(rows["unverifiable_binding"], material["context"], source_sha256="0" * 64),
        available({**rows["available"], "id": "orphan"}, material["context"]),
        available({k: v for k, v in rows["available"].items() if k != "id"}, material["context"]),
        ["unidentifiable", True, 5]]
    case["contexts"]["rows"] = offered
    original = fixtures.prepare(case)
    report = prepare(case)
    assert report["original_evaluation"] == original
    assert report["coverage"] == {"valid": False, "expected_count": 12, "context_row_count": 15,
        "missing_ids": ["missing"], "duplicate_ids": {"duplicate": [8, 9]},
        "unexpected_ids": {"orphan": [12]}, "unidentifiable_indices": [13, 14]}
    assert report["availability_counts"] == {status: 1 for status in AVAILABILITY}
    assert [row["raw_observation"] for row in report["observation_ledger"]] == offered
    assert [row["outcome"] for row in report["observation_ledger"][-3:]] == ["unexpected", "unidentifiable", "unidentifiable"]
    assert [row["id"] for row in report["occurrences"]] == names
    assert [row["status"] for row in report["occurrences"]] == names
    assert len(report["generated_context_bindings"]) == 12
    assert report["generated_context_binding_counts"] == {status: (7 if status == "unavailable" else
        1 if status in {"matched", "missing", "duplicate", "malformed", "unverifiable_binding"} else 0) for status in BINDINGS}
    assert all(row["original_outcome"] == "compared" for row in report["generated_context_bindings"])
    boundaries(report)
    retain(case, report, tmp_path / "mixed-authored-contexts", record_property)


@pytest.mark.parametrize("change", ["whitespace", "roles", "origin"])
def test_generated_binding_distinguishes_raw_canonical_and_origin_identity_without_rescoring(material, change):
    case = make_case(material)
    row = case["contexts"]["rows"][0]
    if change == "whitespace":
        raw = (json.dumps(material["context"], indent=2) + "\n").encode()
        row.update(content_context_utf8=raw.decode(), content_context_sha256=sha(raw))
    elif change == "roles":
        context = deepcopy(material["context"])
        context["argument_roles"][0]["roles"].reverse()
        row.update(content_context_utf8=wire(context).decode(), content_context_sha256=sha(wire(context)))
    else:
        row["content_context_origin"] = "caller_supplied_unverified"
    original = fixtures.prepare(case)
    report = prepare(case)
    bound = report["generated_context_bindings"][0]
    assert bound["status"] == "mismatched"
    assert bound["raw_equal"] is (change == "origin")
    assert bound["canonical_equal"] is (change != "roles")
    assert bound["origin_equal"] is (change != "origin")
    assert report["availability_counts"]["available"] == 1
    assert report["original_evaluation"] == original
    boundaries(report)


@pytest.mark.parametrize("origin", ["authored_fixture", "target_derived_label", "caller_supplied_unverified"])
def test_matching_origin_labels_remain_declarations_not_permission(material, origin):
    case = make_case(material)
    case["contexts"]["rows"][0]["content_context_origin"] = origin
    case["predictions"]["rows"][0]["content_context_origin"] = origin
    report = prepare(case)
    assert report["generated_context_bindings"][0]["status"] == "matched"
    boundaries(report)


@pytest.mark.parametrize("status", DECLARED)
def test_explicit_unavailable_contexts_remain_distinct_despite_present_generated_context(material, status):
    case = make_case(material)
    case["contexts"]["rows"][0] = absent(case["population"]["rows"][0], status)
    report = prepare(case)
    assert report["occurrences"][0]["status"] == status
    assert report["availability_counts"][status] == 1
    assert report["generated_context_bindings"][0]["status"] == "unavailable"
    assert report["observation_ledger"][0]["available_prefix"] is None
    assert report["original_evaluation"]["terminal_counts"]["compared"] == 1
    boundaries(report)


@pytest.mark.parametrize("mode", ["none", "declared", "duplicate", "orphan", "unidentifiable"])
def test_context_inventory_never_invents_or_selects_a_generated_observation(material, mode):
    case = make_case(material)
    original_row = case["predictions"]["rows"][0]
    if mode == "none": case["predictions"]["rows"] = []
    elif mode == "declared": case["predictions"]["rows"] = [fixtures.declared(case["population"]["rows"][0], "not_started")]
    elif mode == "duplicate": case["predictions"]["rows"].append(deepcopy(original_row))
    elif mode == "orphan": original_row["id"] = "orphan"
    else: original_row.pop("id")
    original = fixtures.prepare(case)
    report = prepare(case)
    assert report["original_evaluation"] == original
    assert report["availability_counts"]["available"] == 1
    expected = {"none": [], "declared": ["not_generated"], "duplicate": ["matched", "matched"],
                "orphan": ["unexpected"], "unidentifiable": ["unidentifiable"]}[mode]
    assert [row["status"] for row in report["generated_context_bindings"]] == expected
    assert [row["original_outcome"] for row in report["generated_context_bindings"]] == [
        row["outcome"] for row in original["observation_ledger"]]
    boundaries(report)


@pytest.mark.parametrize("field", ["source_sha256", "context_sha256"])
def test_inventory_binding_mismatch_is_separate_from_valid_context_and_model_outcome(material, field):
    case = make_case(material)
    case["contexts"]["rows"][0][field] = "0" * 64
    report = prepare(case)
    assert report["occurrences"][0]["status"] == "unverifiable_binding"
    assert report["observation_ledger"][0]["available_prefix"] is not None
    assert report["generated_context_bindings"][0]["status"] == "unverifiable_binding"
    assert report["original_evaluation"]["terminal_counts"]["compared"] == 1


@pytest.mark.parametrize("damage", ["extra", "missing_status", "missing_context", "bad_origin", "bad_status",
                                    "nonavailable_context", "available_reason", "bad_hash_syntax"])
def test_malformed_rows_stay_visible_without_available_credit(material, damage):
    case = make_case(material)
    row = case["contexts"]["rows"][0]
    if damage == "extra": row["identity_sidecar"] = {"id": "not-permitted"}
    elif damage == "missing_status": row.pop("status")
    elif damage == "missing_context": row["content_context_utf8"] = None
    elif damage == "bad_origin": row["content_context_origin"] = "verified_source_only"
    elif damage == "bad_status": row["status"] = "accepted"
    elif damage == "nonavailable_context": row.update(status="pending", reason="authored pending")
    elif damage == "available_reason": row["reason"] = "must be null"
    else: row["content_context_sha256"] = "not-a-digest"
    report = prepare(case)
    assert report["occurrences"][0]["status"] == "malformed"
    assert report["observation_ledger"][0]["raw_observation"] == row
    assert report["availability_counts"]["available"] == 0
    assert report["generated_context_bindings"][0]["status"] == "malformed"
    boundaries(report)


@pytest.mark.parametrize("location", ["selected", "duplicate", "orphan"])
@pytest.mark.parametrize("damage", ["wrong_pin", "invalid_context"])
def test_invalid_available_context_assets_abort_even_uncredited_or_duplicate_rows(material, location, damage):
    case = make_case(material)
    row = deepcopy(case["contexts"]["rows"][0])
    if damage == "wrong_pin": row["content_context_sha256"] = "0" * 64
    else:
        context = deepcopy(material["context"])
        context["source_binding"] = {"accepted": True}
        raw = wire(context)
        row.update(content_context_utf8=raw.decode(), content_context_sha256=sha(raw))
    if location == "selected": case["contexts"]["rows"] = [row]
    elif location == "duplicate": case["contexts"]["rows"].append(row)
    else: row["id"] = "orphan"; case["contexts"]["rows"].append(row)
    before = deepcopy(case)
    with pytest.raises(ValueError): prepare(case)
    assert case == before


@pytest.mark.parametrize("damage", ["schema", "population_pin", "nonlist", "too_many", "invalid_utf8",
    "duplicate_key", "nonfinite", "oversize", "independent_pin", "references_pin", "asset_oversize", "asset_oversize_bad_pin"])
def test_inventory_preflight_refuses_before_owner_import_or_partial_report(material, monkeypatch, damage):
    case = make_case(material)
    changes = {}
    if damage == "schema": case["contexts"]["schema"] += "-unknown"
    elif damage == "population_pin": case["contexts"]["population_sha256"] = "0" * 64
    elif damage == "nonlist": case["contexts"]["rows"] = {}
    elif damage == "too_many": case["contexts"]["rows"] *= 257
    elif damage == "invalid_utf8": case["contexts_raw"] = b"\xff"
    elif damage == "duplicate_key": case["contexts_raw"] = b'{"schema":"duplicate",' + wire(case["contexts"])[1:]
    elif damage == "nonfinite": case["contexts_raw"] = b'{"schema":NaN}'
    elif damage == "oversize": case["contexts_raw"] = b" " * (owner.MAX_CONTEXTS_BYTES + 1)
    elif damage == "references_pin": changes["expected_references_sha256"] = "0" * 64
    elif damage in {"asset_oversize", "asset_oversize_bad_pin"}:
        raw = b"x" * (owner.MAX_CONTEXT_BYTES + 1)
        case["contexts"]["rows"][0].update(content_context_utf8=raw.decode(),
            content_context_sha256=sha(raw) if damage == "asset_oversize" else None)
    else: changes["expected_contexts_sha256"] = "0" * 64
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner imported before malformed inventory preflight"))
    with pytest.raises(ValueError): prepare(case, **changes)


def test_full_context_output_bound_refuses_without_truncating_original_evaluation(material, monkeypatch):
    case = make_case(material)
    before = deepcopy(case)
    report = prepare(case)
    monkeypatch.setattr(owner, "MAX_OUTPUT_BYTES", len(wire(report)) - 1)
    with pytest.raises(ValueError): prepare(case)
    assert case == before


@pytest.mark.parametrize("damage", ["raw_context", "original_result", "availability", "authority"])
def test_resealed_companion_tampering_refuses_full_original_replay(material, damage):
    case = make_case(material)
    report = prepare(case)
    if damage == "raw_context": report["observation_ledger"][0]["raw_observation"]["content_context_origin"] = "authored_fixture"
    elif damage == "original_result":
        report["original_evaluation"]["terminal_counts"]["compared"] = 0
        report["original_evaluation_sha256"] = sha(wire(report["original_evaluation"]))
    elif damage == "availability": report["availability_counts"]["available"] = 0
    else: report["authority"][next(iter(report["authority"]))] = True
    with pytest.raises(ValueError): validate(case, report)


def test_independent_companion_report_pin_refuses_before_full_replay(material, monkeypatch):
    case = make_case(material)
    report = prepare(case)
    monkeypatch.setattr(owner, "prepare_relational_content_context_evaluation_v1",
                        lambda *a, **k: pytest.fail("replayed before independent report pin"))
    with pytest.raises(ValueError): validate(case, report, expected_evaluation_sha256="0" * 64)


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, KeyboardInterrupt])
def test_owner_loading_failure_and_cancellation_propagate_exactly(material, monkeypatch, error_type):
    case = make_case(material)
    failure = error_type("authored companion owner failure")
    def failed(): raise failure
    monkeypatch.setattr(owner, "_owners", failed)
    with pytest.raises(error_type) as caught: prepare(case)
    assert caught.value is failure


def test_final_serialization_precedes_closing_source_fence(material, monkeypatch):
    case = make_case(material)
    original_wire, original_sources = owner._wire, owner._sources
    armed = []
    failure = ValueError("authored final source identity change")
    def wire_then_arm(value, maximum):
        result = original_wire(value, maximum)
        if type(value) is dict and value.get("schema") == REPORT_SCHEMA: armed.append(True)
        return result
    def sources(*args, **kwargs):
        if armed: raise failure
        return original_sources(*args, **kwargs)
    monkeypatch.setattr(owner, "_wire", wire_then_arm)
    monkeypatch.setattr(owner, "_sources", sources)
    with pytest.raises(ValueError) as caught: prepare(case)
    assert caught.value is failure and armed


@pytest.mark.parametrize("anchor", ["self", "token", "content"])
def test_real_source_anchor_change_refuses_without_partial_availability(material, monkeypatch, anchor):
    case = make_case(material)
    if anchor == "self": monkeypatch.setattr(owner, "_SELF_SNAPSHOT", ("0" * 64, owner._SELF_SNAPSHOT[1]))
    elif anchor == "token": monkeypatch.setattr(tokens, "_SELF_SHA", "0" * 64)
    else: monkeypatch.setattr(fixtures.content_owner, "_SELF_SHA", "0" * 64)
    monkeypatch.setattr(tokens, "compact_content_allowed_token_ids_v1",
                        lambda *a, **k: pytest.fail("changed source reached inventory validation"))
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize("damage", ["raw_pin", "canonical_pin", "codec_pin", "status", "allowed_ids", "allowed_bool",
    "producer_bytes", "duplicate_producer", "producer_population", "authority", "training_mask_false", "evaluation_mask_one"])
def test_altered_real_public_prefix_evidence_cannot_upgrade_context_availability(material, monkeypatch, damage):
    case = make_case(material)
    original = tokens.compact_content_allowed_token_ids_v1
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        if damage == "raw_pin": report["context_raw_sha256"] = "0" * 64
        elif damage == "canonical_pin": report["context_sha256"] = "0" * 64
        elif damage == "codec_pin": report["codec_sha256"] = "0" * 64
        elif damage == "status": report["status"] = "rejected"
        elif damage == "allowed_ids": report["allowed_token_ids"] = []
        elif damage == "allowed_bool": report["allowed_token_ids"] = [True]
        elif damage == "producer_bytes": report["owner_pins"][0]["bytes"] += 1
        elif damage == "duplicate_producer": report["owner_pins"][1] = deepcopy(report["owner_pins"][0])
        elif damage == "authority": report["authority"]["permitted_inference_context_verified"] = True
        elif damage == "training_mask_false": report["training_mask"] = False
        elif damage == "evaluation_mask_one": report["evaluation_gold_mask"] = 1
        else: report["owner_pins"].pop()
        return report
    monkeypatch.setattr(tokens, "compact_content_allowed_token_ids_v1", changed)
    with pytest.raises(ValueError): prepare(case)


def test_detached_codec_mutation_during_real_context_validation_trips_input_fence(material, monkeypatch):
    case = make_case(material)
    before = deepcopy(case)
    original = tokens.compact_content_allowed_token_ids_v1
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        kwargs["codec"]["vocabulary"][0] = "changed-after-genuine-prefix-check"
        return report
    monkeypatch.setattr(tokens, "compact_content_allowed_token_ids_v1", changed)
    with pytest.raises(ValueError): prepare(case)
    assert case == before


def test_context_prefix_intake_uses_only_own_inventory_and_existing_fixed_codec(material, monkeypatch):
    case = make_case(material, unavailable={"one"})
    original = tokens.compact_content_allowed_token_ids_v1
    calls = []
    def observed(prefix, raw, **options):
        assert prefix == []
        assert set(options) == {"expected_context_sha256", "codec", "expected_codec_sha256"}
        assert raw == case["contexts"]["rows"][0]["content_context_utf8"].encode()
        calls.append(sha(raw))
        return original(prefix, raw, **options)
    monkeypatch.setattr(tokens, "compact_content_allowed_token_ids_v1", observed)
    monkeypatch.setattr(fixtures.content_owner, "reconstruct_request_v1",
                        lambda *a, **k: pytest.fail("archival reference reconstruction entered inventory"))
    report = prepare(case)
    assert calls == [case["contexts"]["rows"][0]["content_context_sha256"]]
    assert report["original_evaluation"]["terminal_counts"]["valid_without_reference"] == 1
    assert report["availability_counts"]["available"] == 1


def test_report_detaches_raw_contexts_from_callers_and_later_reports(material):
    case = make_case(material)
    original_case = deepcopy(case)
    report = prepare(case)
    snapshot = deepcopy(report)
    case["contexts"]["rows"][0]["reason"] = "changed caller"
    assert report == snapshot
    report["observation_ledger"][0]["raw_observation"]["content_context_utf8"] = "changed report"
    report["original_evaluation"]["observation_ledger"][0]["raw_observation"]["generated_ids"].clear()
    assert prepare(original_case) == snapshot
