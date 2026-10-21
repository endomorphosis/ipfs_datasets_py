"""Synthetic join custody and actual source-span expressibility, without gold.

The join hashing and registry-discovery delegates are fixtures. Candidate
validation and source-span audits use their actual owners; no model is built.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_span_adapter as adapter
from ipfs_datasets_py.logic.autoformal import legal_source_span_target_eligibility_v1 as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rule(**changes):
    return {"modality": "O", "actor": "Clerk", "action": "file", "object": "report",
            "conditions": [], "exceptions": [], "temporal": [], **changes}


def formal(payload=None, **changes):
    if payload is None:
        payload = rule()
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return {"family": "typed_deontic", "format": "typed-deontic-rule/v1",
            "payload_json": raw.decode("utf-8"), "sha256": sha(raw),
            "origin": "deterministic_compiler", "independent": True,
            "target_conditioned": False, "syntax_status": "compiler_accepted", **changes}


def paired(marker="one", *, text="Clerk shall file report.", direct=None, canonical=None, guided=None):
    return {"schema_version": "uscode-paired-span-census/v1", "repository_id": "fixture",
            "observation_id": "observation-" + marker,
            "source": {"span_id": "span-" + marker, "text": text,
                       "text_sha256": sha(text.encode("utf-8")), "legal_id": "usc:5:1",
                       "revision": "historical-release-alias", "constitution": False},
            "autoencoder": {"formal_outputs": [] if guided is None else guided,
                            "status": "guided_output", "embedding_model": "mock:stable-sha256",
                            "semantic_embeddings": False},
            "compiler": {"formal_outputs": [] if direct is None else direct,
                         "canonical_formal_outputs": [] if canonical is None else canonical},
            "admitted": False, "formalized": False}


def joined(*rows):
    path = "autoformal/uscode/paired-v1/manifests/fixture/manifest-" + "a" * 64 + ".json"
    table = {"path_in_repo": "autoformal/uscode/paired-v1/paired_spans/fixture/paired_spans-" + "b" * 64 + ".parquet",
             "sha256": "b" * 64, "bytes": 123, "row_count": len(rows)}
    selected = {"path_in_repo": path, "bank": "paired-v1", "sha256": "a" * 64,
                "manifest": {"tables": {"paired_spans": table}}}
    intake_rows, physical_rows, references = [], [], []
    for ordinal, value in enumerate(rows):
        raw = wire(value)
        candidate = adapter.adapt_paired_span_bytes(raw, expected_row_sha256=sha(raw))
        intake_rows.append({"row_ordinal": ordinal, "observation_id": value["observation_id"],
                           "row_sha256": sha(raw), "derived_row_json": raw.decode("utf-8"),
                           "disposition": "candidate_unbound", "candidate": candidate, "error": None})
        identity = {"repository_id": "justicedao/uscode-autoformal-span-cache", "revision": "c" * 40,
                    "path_in_repo": table["path_in_repo"], "file_sha256": table["sha256"], "row_ordinal": ordinal}
        identity_sha = sha(wire(identity))
        physical_rows.append({"physical_identity": identity, "physical_identity_sha256": identity_sha,
                              "row_sha256": sha(raw), "observation_id": value["observation_id"],
                              "row_reference_ordinals": [ordinal]})
        references.append({"physical_identity": identity, "physical_identity_sha256": identity_sha,
                           "manifest_path_in_repo": path, "bank": "paired-v1", "row_sha256": sha(raw),
                           "observation_id": value["observation_id"],
                           "producer_source_revision_label": value["source"]["revision"],
                           "payload_disposition": "candidate_unbound", "source_disposition": "source_join_unavailable",
                           "source_candidate_record": None, "selected_occurrence": None,
                           "current_source_release_correspondence": "unverified_no_independent_crosswalk",
                           "entity_binding": "unavailable_semantic_companions_not_supplied",
                           "training_mask": 0, "evaluation_gold_mask": 0})
    intake = {"repository_id": "justicedao/uscode-autoformal-span-cache", "revision": "c" * 40,
              "manifest_path_in_repo": path, "manifest_sha256": "a" * 64,
              "tables": {"paired_spans": table}, "rows": intake_rows,
              "bundle_integrity_verified": True, "source_binding_population_supplied": False}
    return {"schema": "legal-source-span-entity-join-manifest/v1", "selection_complete": True,
            "selection_scope": "exact_selected_paired_bundles_and_supplied_legacy_candidate_inputs",
            "span_inventory": {"repository_id": "justicedao/uscode-autoformal-span-cache", "revision": "c" * 40,
                               "manifests": [selected]},
            "paired_bundles": [{"manifest_path_in_repo": path, "payload_intake": intake,
                                "legacy_candidate_join": None}],
            "physical_rows": physical_rows, "row_references": references,
            "counts": {"physical_paired_rows": len(rows), "selected_row_references": len(rows),
                       "selected_bundles": 1, "source_dispositions": {"source_join_unavailable": len(rows)},
                       "candidate_occurrence_references": 0, "distinct_candidate_occurrence_cids": 0,
                       "entity_file_rows_verified": 0},
            "authority": {"source_semantics_verified": False, "historical_occurrence_selected": False,
                          "training_qualified": False}, "training_mask": 0, "evaluation_gold_mask": 0}


@pytest.fixture
def harness(monkeypatch):
    state = {"join": joined(paired(canonical=[formal()])), "audit_calls": []}
    join_owner = SimpleNamespace(source_span_entity_join_manifest_sha256=lambda value: sha(wire(value)))

    def describe(domain, version):
        assert domain == "legal_ir" and version == "source_span_formula_v1"
        return {"runtime_id": "legal_ir:source_span_formula_v1", "runtime_version": version,
                "supported_latent_dimensions": [0, 384], "capabilities": ["load_checkpoint", "infer", "decode_formal_logic"],
                "source_semantics_verified": False, "proof_ready": False}

    runtime = SimpleNamespace(describe_runtime=describe, SPAN_FORMULA_VERSION="source_span_formula_v1")
    monkeypatch.setattr(owner, "_owners", lambda: (join_owner, adapter, contracts, span, runtime, {"fixture-owner": "f" * 64}))
    original_audit = span.audit_examples

    def audit(rows):
        state["audit_calls"].append(deepcopy(rows))
        return original_audit(rows)

    monkeypatch.setattr(span, "audit_examples", audit)
    for name in ("_torch", "_model", "build_checkpoint", "train_decoder", "load_checkpoint"):
        if hasattr(span, name):
            monkeypatch.setattr(span, name, lambda *a, **k: pytest.fail("numerical/model operation invoked"))
    return state


def inputs(state, **changes):
    raw = wire(state["join"])
    request = {"schema": "legal-source-span-target-eligibility-request/v1",
               "join_manifest_raw_sha256": sha(raw), "join_manifest_sha256": sha(wire(state["join"])),
               "expected_physical_ids": [row["physical_identity_sha256"] for row in state["join"]["physical_rows"]],
               "decoder_profile": "source_span_formula_v1", "latent_dimension": 0, **changes}
    return wire(request), raw


def prepare(state, **changes):
    request, join = inputs(state, **changes)
    return owner.prepare_source_span_target_eligibility(request, join, expected_request_sha256=sha(request))


def validate(state, report, **changes):
    request, join = inputs(state, **changes)
    value = json.loads(report) if type(report) is bytes else report
    return owner.validate_source_span_target_eligibility(report, request, join,
        expected_request_sha256=sha(request),
        expected_report_sha256=owner.source_span_target_eligibility_sha256(value))


def replace_retained_row(state, mutate, *, ordinal=0):
    """Reseal outer transport identities while retaining the original candidate.

    This lets the operation's actual adapter reject malformed payload custody;
    a matching newly supplied outer hash must not make malformed JSON valid.
    """
    row = state["join"]["paired_bundles"][0]["payload_intake"]["rows"][ordinal]
    original = json.loads(row["derived_row_json"])
    mutate(original)
    raw = wire(original)
    row.update(derived_row_json=raw.decode("utf-8"), row_sha256=sha(raw))
    state["join"]["physical_rows"][ordinal]["row_sha256"] = sha(raw)
    state["join"]["row_references"][ordinal]["row_sha256"] = sha(raw)


def test_real_audit_wraps_exact_single_rule_without_numerical_calls(harness):
    before = deepcopy(harness["join"])
    report = prepare(harness)
    assert validate(harness, report) == report
    assert harness["join"] == before
    assert report["selection_scope"] == "pinned_retained_join_report_only"
    assert report["upstream_reexecution_performed"] is False
    assert len(report["physical_rows"]) == 1
    assert len(report["output_occurrences"]) == 1
    output = report["output_occurrences"][0]
    assert output["canonical_ir"] == {"rules": [rule()]}
    assert output["decoder_audit"]["all_supported"] is True
    assert output["formal_output"] == formal()
    assert harness["audit_calls"]
    assert all(call[0]["source_text"] == "Clerk shall file report."
               and call[0]["canonical_ir"] == {"rules": [rule()]} for call in harness["audit_calls"])
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert all(type(flag) is bool and flag is False for flag in report["authority"].values())
    assert output["consumer_compatibility_blockers"]


@pytest.mark.parametrize("dimension", [0, 384])
def test_explicit_supported_dimension_is_retained_without_creating_latents(harness, dimension):
    report = prepare(harness, latent_dimension=dimension)
    assert report["request"]["latent_dimension"] == dimension
    assert report["runtime_description"]["runtime_id"] == "legal_ir:source_span_formula_v1"
    assert all("latent" not in row for call in harness["audit_calls"] for row in call)
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("dimension", [True, False, None, -1, 8, 768, "384"])
def test_wrong_or_coerced_dimension_refuses(harness, dimension):
    with pytest.raises(ValueError):
        prepare(harness, latent_dimension=dimension)


@pytest.mark.parametrize("profile", [None, True, "source_conditioned_formula_v1",
                                     "source_conditioned_grouped_v2", "source_span_formula_v2"])
def test_wrong_decoder_profile_refuses(harness, profile):
    with pytest.raises(ValueError):
        prepare(harness, decoder_profile=profile)


@pytest.mark.parametrize("damage", ["schema", "extra_field", "missing_field", "raw_join_hash", "canonical_join_hash"])
def test_closed_request_and_independent_join_pins_refuse(harness, damage):
    request_raw, join_raw = inputs(harness)
    request = json.loads(request_raw)
    if damage == "schema":
        request["schema"] = "future/v2"
    elif damage == "extra_field":
        request["reviewed"] = True
    elif damage == "missing_field":
        request.pop("decoder_profile")
    elif damage == "raw_join_hash":
        request["join_manifest_raw_sha256"] = "0" * 64
    else:
        request["join_manifest_sha256"] = "0" * 64
    raw = wire(request)
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility(raw, join_raw, expected_request_sha256=sha(raw))


@pytest.mark.parametrize("pin", [None, True, "", "a" * 63, "A" * 64, "0" * 64])
def test_expected_request_hash_is_independent_and_exact(harness, pin):
    request_raw, join_raw = inputs(harness)
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility(request_raw, join_raw, expected_request_sha256=pin)


@pytest.mark.parametrize("damage", ["omit", "reverse", "duplicate", "foreign"])
def test_exact_ordered_complete_physical_selection_required(harness, damage):
    harness["join"] = joined(paired("one", canonical=[formal()]),
                              paired("two", text="Agent shall retain log.", direct=[]))
    ids = [row["physical_identity_sha256"] for row in harness["join"]["physical_rows"]]
    changed = {"omit": ids[:1], "reverse": ids[::-1], "duplicate": [ids[0], ids[0]],
               "foreign": [ids[0], "0" * 64]}[damage]
    with pytest.raises(ValueError):
        prepare(harness, expected_physical_ids=changed)


@pytest.mark.parametrize("damage", ["incomplete", "authority", "training_mask", "gold_mask", "row_omitted",
                                    "reference_omitted", "row_count", "output_candidate"])
def test_join_custody_cannot_be_resealed_into_complete_semantic_evidence(harness, damage):
    joined_report = harness["join"]
    if damage == "incomplete":
        joined_report["selection_complete"] = False
    elif damage == "authority":
        joined_report["authority"]["training_qualified"] = True
    elif damage == "training_mask":
        joined_report["training_mask"] = True
    elif damage == "gold_mask":
        joined_report["evaluation_gold_mask"] = 1
    elif damage == "row_omitted":
        joined_report["paired_bundles"][0]["payload_intake"]["rows"] = []
    elif damage == "reference_omitted":
        joined_report["row_references"] = []
    elif damage == "row_count":
        joined_report["counts"]["physical_paired_rows"] += 1
    else:
        joined_report["paired_bundles"][0]["payload_intake"]["rows"][0]["candidate"]["interpretations"] = []
    with pytest.raises(ValueError):
        prepare(harness)


@pytest.mark.parametrize("payload", ['{"modality":"O","modality":"P"}', '{"bad":NaN}', 'null', '42'])
def test_rehashed_malformed_payload_rejected_by_actual_candidate_owner(harness, payload):
    def mutate(row):
        output = row["compiler"]["canonical_formal_outputs"][0]
        output.update(payload_json=payload, sha256=sha(payload.encode("utf-8")))
    replace_retained_row(harness, mutate)
    with pytest.raises(ValueError):
        prepare(harness)


@pytest.mark.parametrize("damage", ["payload_pin", "source_pin", "independence_type"])
def test_rehashed_outer_row_does_not_repair_inner_integrity(harness, damage):
    def mutate(row):
        if damage == "payload_pin":
            row["compiler"]["canonical_formal_outputs"][0]["sha256"] = "0" * 64
        elif damage == "source_pin":
            row["source"]["text_sha256"] = "0" * 64
        else:
            row["compiler"]["canonical_formal_outputs"][0]["independent"] = 1
    replace_retained_row(harness, mutate)
    with pytest.raises(ValueError):
        prepare(harness)


@pytest.mark.parametrize("damage", ["authority", "mask", "source", "origin", "drop_output", "drop_row"])
def test_resealed_output_mutations_fail_full_regeneration(harness, damage):
    report = prepare(harness)
    changed = deepcopy(report)
    if damage == "authority":
        changed["authority"]["training_qualified"] = True
    elif damage == "mask":
        changed["evaluation_gold_mask"] = 1
    elif damage == "source":
        changed["physical_rows"][0]["source_text"] += " changed"
    elif damage == "origin":
        changed["output_occurrences"][0]["formal_output"]["origin"] = "reviewed_legal_gold"
    elif damage == "drop_output":
        changed["output_occurrences"] = []
    else:
        changed["physical_rows"] = []
    with pytest.raises(ValueError):
        validate(harness, changed)


def test_no_outputs_and_unsupported_modal_outputs_have_distinct_denominators(harness):
    modal = formal({"operator": "O", "body": "file(report)"}, family="modal", format="opaque-modal/v1")
    harness["join"] = joined(paired("empty"), paired("modal", text="Agent may act.", direct=[modal]))
    report = prepare(harness)
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["rows_without_outputs"] == 1
    assert report["counts"]["output_occurrences"] == 1
    assert report["counts"]["target_statuses"] == {"unsupported_formal_format": 1}
    assert report["physical_rows"][0]["output_occurrence_ordinals"] == []
    assert "no_formal_outputs" in report["physical_rows"][0]["consumer_compatibility_blockers"]
    output = report["output_occurrences"][0]
    assert output["formal_output"] == modal
    assert output["canonical_ir"] is output["decoder_audit"] is None
    assert harness["audit_calls"] == []


def test_every_route_order_duplicate_and_guided_origin_is_preserved(harness):
    guided = formal(origin="autoencoder_guided_compiler", independent=False, target_conditioned=True)
    direct = formal(origin="deterministic_compiler")
    harness["join"] = joined(paired(guided=[guided, deepcopy(guided)], direct=[direct], canonical=[direct]))
    report = prepare(harness)
    outputs = report["output_occurrences"]
    assert [(entry["route"], entry["ordinal"]) for entry in outputs] == [
        ("autoencoder.formal_outputs", 0), ("autoencoder.formal_outputs", 1),
        ("compiler.formal_outputs", 0), ("compiler.canonical_formal_outputs", 0)]
    assert [entry["formal_output"] for entry in outputs] == [guided, guided, direct, direct]
    assert [entry["producer_origin"] for entry in outputs] == [
        "autoencoder_guided_compiler", "autoencoder_guided_compiler", "deterministic_compiler", "deterministic_compiler"]
    assert len({entry["interpretation_cid"] for entry in outputs}) == 4
    assert report["physical_rows"][0]["output_occurrence_ordinals"] == [0, 1, 2, 3]
    assert report["counts"]["mechanically_supported_outputs"] == 4
    assert all("unsupported_consumer_target_origin" in entry["consumer_compatibility_blockers"] for entry in outputs)
    assert all(entry["consumer_eligible"] is False for entry in outputs)


def test_repeated_source_text_is_grouped_without_dropping_physical_observations(harness):
    harness["join"] = joined(paired("first", canonical=[formal()]), paired("second", canonical=[formal()]))
    report = prepare(harness)
    ids = [row["physical_identity_sha256"] for row in report["physical_rows"]]
    assert len(ids) == len(set(ids)) == 2
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["distinct_source_texts"] == 1
    assert report["counts"]["output_occurrences"] == 2
    assert report["duplicate_source_groups"] == [{"source_text_sha256": sha(b"Clerk shall file report."), "physical_ids": ids}]
    assert all("duplicate_source_text" in output["consumer_compatibility_blockers"]
               for output in report["output_occurrences"])


def test_repeated_bundle_references_do_not_duplicate_one_physical_output(harness):
    joined_report = harness["join"]
    joined_report["span_inventory"]["manifests"] *= 2
    joined_report["paired_bundles"] *= 2
    joined_report["row_references"] *= 2
    joined_report["physical_rows"][0]["row_reference_ordinals"] = [0, 1]
    joined_report["counts"].update(selected_row_references=2, selected_bundles=2)
    report = prepare(harness)
    assert report["counts"]["physical_rows"] == 1
    assert report["counts"]["row_references"] == 2
    assert report["counts"]["output_occurrences"] == 1
    assert report["physical_rows"][0]["row_reference_ordinals"] == [0, 1]
    assert report["row_references"] == joined_report["row_references"]


@pytest.mark.parametrize("target,text", [
    (rule(actor="Agency"), "Clerk shall file report."),
    (rule(action="send"), "Clerk shall file report."),
    (rule(conditions=["A", "B"]), "Clerk shall file report if A and B."),
    (rule(), "Clerk shall file report when Clerk agrees."),
    (rule(object="Clerk"), "Clerk shall file."),
    (rule(), "Clerk shall file report. " + "token " * 252),
    (rule(), "Clerk shall file report. " + "x" * 16384),
    (rule(), "Clerk shall file report. " + "x" * 2049),
])
def test_actual_span_audit_reports_target_and_source_profile_limits(harness, target, text):
    harness["join"] = joined(paired(text=text, canonical=[formal(target)]))
    report = prepare(harness)
    output = report["output_occurrences"][0]
    assert output["target_status"] == "decoder_rejected"
    assert output["canonical_ir"] == {"rules": [target]}
    assert output["decoder_audit"]["all_supported"] is False
    assert len(output["decoder_audit"]["rejected_rows"]) == 1
    assert "decoder_rejected" in output["consumer_compatibility_blockers"]
    assert report["counts"]["physical_rows"] == report["counts"]["output_occurrences"] == 1


def test_non_ascii_source_and_exact_payload_spelling_survive_audit(harness):
    target = rule(actor="Café")
    output = formal(target)
    harness["join"] = joined(paired(text="Café shall file report.", canonical=[output]))
    report = prepare(harness)
    assert report["physical_rows"][0]["source_text"] == "Café shall file report."
    assert report["physical_rows"][0]["source_text_sha256"] == sha("Café shall file report.".encode())
    assert report["output_occurrences"][0]["formal_output"]["payload_json"] == output["payload_json"]
    assert report["output_occurrences"][0]["target_status"] == "mechanically_supported"
    assert report["output_occurrences"][0]["canonical_ir"] == {"rules": [target]}


@pytest.mark.parametrize("payload", [{"rules": [rule()]}, [rule()], "O(file(report))"])
def test_unrecognized_payload_shapes_are_not_repaired_into_canonical_rules(harness, payload):
    harness["join"] = joined(paired(canonical=[formal(payload)]))
    report = prepare(harness)
    output = report["output_occurrences"][0]
    assert output["canonical_ir"] == {"rules": [payload]}
    assert output["target_status"] == "decoder_rejected"
    assert output["decoder_audit"]["all_supported"] is False


@pytest.mark.parametrize("origin", ["authored_engineering_fixture", "model_generated_weak"])
def test_supported_consumer_origin_is_metadata_compatibility_without_authority(harness, origin):
    harness["join"] = joined(paired(canonical=[formal(origin=origin)]))
    report = prepare(harness)
    output = report["output_occurrences"][0]
    assert output["target_status"] == "mechanically_supported"
    assert output["producer_origin"] == origin
    assert "unsupported_consumer_target_origin" not in output["consumer_compatibility_blockers"]
    assert output["consumer_eligible"] is False
    assert report["counts"]["consumer_eligible_rows"] == report["counts"]["training_qualified_rows"] == 0


def test_384_metadata_profile_cannot_authorize_zero_latent_consumer(harness):
    harness["join"] = joined(paired(canonical=[formal(origin="model_generated_weak")]))
    report = prepare(harness, latent_dimension=384)
    assert "consumer_requires_zero_latent" in report["output_occurrences"][0]["consumer_compatibility_blockers"]
    assert report["counts"]["consumer_eligible_rows"] == 0


def test_source_review_and_complete_meaning_masks_remain_unknown_even_for_supported_output(harness):
    report = prepare(harness)
    physical = report["physical_rows"][0]
    assert physical["source_unit_status"] == "unestablished"
    assert physical["meaning_unit_id"] is None
    assert physical["selected_occurrence"] is None
    for field in ("context_status", "source_review_status", "semantic_review_status", "exposure_status", "split_status",
                  "source_role_status", "applicability_status", "dependency_status", "definition_binding_status"):
        assert physical[field] == "unresolved"
    for field in ("meaning_unit_mask", "source_binding_mask", "context_mask", "source_review_mask",
                  "source_role_mask", "applicability_mask", "dependency_mask", "definition_binding_mask",
                  "training_mask", "evaluation_gold_mask"):
        assert type(physical[field]) is int and physical[field] == 0
    for record in (physical, report["output_occurrences"][0]):
        assert set(record["field_masks"]) == set(rule())
        assert all(type(value) is int and value == 0 for value in record["field_masks"].values())
        assert {"source_role_unresolved", "applicability_unresolved", "dependency_unresolved",
                "definition_binding_unresolved"} <= set(record["eligibility_blockers"])
    assert report["checkpoint_status"] == "not_assessed"
    assert report["counts"]["source_units_established"] == report["counts"]["evaluation_gold_rows"] == 0


def test_report_is_detached_and_raw_file_hash_differs_from_canonical_identity(harness):
    report = prepare(harness)
    assert validate(harness, wire(report)) == report
    request_raw, join_raw = inputs(harness)
    offered = json.loads(request_raw)
    pretty_join = json.dumps(harness["join"], ensure_ascii=False, indent=2).encode()
    offered["join_manifest_raw_sha256"] = sha(pretty_join)
    new_request = wire(offered)
    regenerated = owner.prepare_source_span_target_eligibility(new_request, pretty_join,
        expected_request_sha256=sha(new_request))
    assert regenerated["join_manifest_sha256"] == report["join_manifest_sha256"]
    assert regenerated["join_manifest_raw_sha256"] != report["join_manifest_raw_sha256"]
    report["output_occurrences"][0]["formal_output"]["origin"] = "mutated-private-report"
    assert harness["join"]["paired_bundles"][0]["payload_intake"]["rows"][0]["candidate"]["interpretations"][0]["formal_output"]["origin"] == "deterministic_compiler"


def test_changed_producer_source_refuses_before_delegating(harness, monkeypatch):
    monkeypatch.setattr(owner, "_SELF_PIN", "0" * 64)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner loaded after producer freshness failed"))
    with pytest.raises(ValueError, match="producer changed"):
        prepare(harness)


def test_changed_producer_during_audit_refuses_final_receipt(harness, monkeypatch):
    audit = span.audit_examples

    def changed(rows):
        result = audit(rows)
        monkeypatch.setattr(owner, "_SELF_PIN", "0" * 64)
        return result

    monkeypatch.setattr(span, "audit_examples", changed)
    with pytest.raises(ValueError, match="producer changed"):
        prepare(harness)


def test_changed_delegate_pin_refuses_final_receipt(harness, monkeypatch):
    original = owner._owners
    calls = []

    def changed():
        values = original()
        calls.append(True)
        return (*values[:-1], {"fixture-owner": ("f" if len(calls) == 1 else "e") * 64})

    monkeypatch.setattr(owner, "_owners", changed)
    with pytest.raises(ValueError, match="owners changed"):
        prepare(harness)


@pytest.mark.parametrize("bound", ["MAX_REQUEST_BYTES", "MAX_JOIN_BYTES", "MAX_REPORT_BYTES"])
def test_complete_byte_bounds_refuse_instead_of_truncating(harness, monkeypatch, bound):
    request, join = inputs(harness)
    size = {"MAX_REQUEST_BYTES": len(request), "MAX_JOIN_BYTES": len(join),
            "MAX_REPORT_BYTES": len(wire(prepare(harness)))}[bound]
    monkeypatch.setattr(owner, bound, size - 1)
    with pytest.raises(ValueError):
        prepare(harness)


def test_complete_output_bound_refuses_instead_of_filtering(harness, monkeypatch):
    harness["join"] = joined(paired(direct=[formal()], canonical=[formal()]))
    monkeypatch.setattr(owner, "MAX_OUTPUTS", 1)
    with pytest.raises(ValueError, match="output population"):
        prepare(harness)


def test_physical_population_bound_refuses_instead_of_filtering(harness, monkeypatch):
    harness["join"] = joined(paired("first"), paired("second", text="Agent shall act."))
    monkeypatch.setattr(owner, "MAX_ROWS", 1)
    with pytest.raises(ValueError):
        prepare(harness)


def test_missing_empty_and_emitted_routes_remain_distinct(harness):
    original = paired(canonical=[formal()])
    del original["autoencoder"]["formal_outputs"]
    harness["join"] = joined(original)
    report = prepare(harness)
    assert report["physical_rows"][0]["route_inventory"] == [
        {"route": "autoencoder.formal_outputs", "output_count": 0, "availability": "missing"},
        {"route": "compiler.formal_outputs", "output_count": 0, "availability": "empty"},
        {"route": "compiler.canonical_formal_outputs", "output_count": 1, "availability": "outputs"}]


def test_exact_replayed_candidate_refusal_retains_every_output_without_audit(harness):
    malformed = '{"x":1,"x":2}'

    def mutate(row):
        row["compiler"]["canonical_formal_outputs"][0].update(
            payload_json=malformed, sha256=sha(malformed.encode()))

    replace_retained_row(harness, mutate)
    row = harness["join"]["paired_bundles"][0]["payload_intake"]["rows"][0]
    with pytest.raises(contracts.CorpusContractError) as refusal:
        adapter.adapt_paired_span_bytes(row["derived_row_json"].encode(), expected_row_sha256=row["row_sha256"])
    row.update(candidate=None, disposition="adapter_rejected",
               error={"type": type(refusal.value).__name__, "message": str(refusal.value)[:512]})
    harness["join"]["row_references"][0]["payload_disposition"] = "adapter_rejected"
    report = prepare(harness)
    assert report["physical_rows"][0]["payload_disposition"] == "adapter_rejected"
    assert report["counts"]["physical_rows"] == report["counts"]["output_occurrences"] == 1
    output = report["output_occurrences"][0]
    assert output["target_status"] == "candidate_custody_refused"
    assert output["formal_output"]["payload_json"] == malformed
    assert output["interpretation_cid"] is output["canonical_ir"] is output["decoder_audit"] is None
    assert harness["audit_calls"] == []


@pytest.mark.parametrize("damage", ["foreign_accepted", "empty_rejection", "wrong_rejection_id", "extra_field", "numeric_supported"])
def test_incomplete_or_foreign_decoder_audit_cannot_supply_support(harness, monkeypatch, damage):
    def audit(rows):
        identity = rows[0]["id"]
        result = {"accepted_ids": [identity], "rejected_rows": [], "all_supported": True}
        if damage == "foreign_accepted":
            result["accepted_ids"] = ["foreign"]
        elif damage == "empty_rejection":
            result.update(accepted_ids=[], rejected_rows=[], all_supported=False)
        elif damage == "wrong_rejection_id":
            result.update(accepted_ids=[], rejected_rows=[{"id": "foreign", "reason": "unsupported"}], all_supported=False)
        elif damage == "extra_field":
            result["reviewed"] = True
        else:
            result["all_supported"] = 1
        return result

    monkeypatch.setattr(span, "audit_examples", audit)
    with pytest.raises(ValueError):
        prepare(harness)


def test_decoder_audit_cannot_mutate_the_canonical_target(harness, monkeypatch):
    audit = span.audit_examples

    def mutate(rows):
        result = audit(rows)
        rows[0]["canonical_ir"]["rules"][0]["actor"] = "injected"
        return result

    monkeypatch.setattr(span, "audit_examples", mutate)
    with pytest.raises(ValueError, match="audit mutated"):
        prepare(harness)


@pytest.mark.parametrize("damage", ["candidate_false_as_zero", "reference_ordinal_false", "physical_ordinal_false"])
def test_custody_equality_preserves_boolean_and_integer_types(harness, damage):
    retained = harness["join"]
    if damage == "candidate_false_as_zero":
        candidate = retained["paired_bundles"][0]["payload_intake"]["rows"][0]["candidate"]
        candidate["interpretations"][0]["formal_output"]["target_conditioned"] = 0
    else:
        field = "row_references" if damage == "reference_ordinal_false" else "physical_rows"
        retained[field][0]["physical_identity"] = deepcopy(retained[field][0]["physical_identity"])
        retained[field][0]["physical_identity"]["row_ordinal"] = False
    with pytest.raises(ValueError):
        prepare(harness)


def test_typed_format_with_mismatched_family_is_preserved_without_decoder_audit(harness):
    output = formal(family="modal")
    harness["join"] = joined(paired(canonical=[output]))
    report = prepare(harness)
    retained = report["output_occurrences"][0]
    assert retained["formal_output"] == output
    assert retained["target_status"] == "unsupported_formal_format"
    assert retained["canonical_ir"] is retained["decoder_audit"] is None
    assert report["counts"]["target_statuses"] == {"unsupported_formal_format": 1}
    assert harness["audit_calls"] == []
