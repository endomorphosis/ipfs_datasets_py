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


# Coordinate eligibility reuses genuine source/report/candidate/audit owners.
# The retained join populations below are declared authored metadata rather than
# actual Parquet reads; join regeneration is deliberately outside this profile.
from pathlib import Path

from ipfs_datasets_py.logic.autoformal import span_cache as coordinate_cache
from ipfs_datasets_py.logic.autoformal import uscode_ingest as coordinate_ingest

_coordinate_genuine_owners = owner._owners


def coordinate_joined_fixture():
    documents = [
        {"z_metadata": "retained-before-a", "a_metadata": "retained-after-z",
         "legal_id": "usc:us:5:1",
         "text": "  Ω agency may retain records.\r\n Clerk shall file report.  "}
        for _ in range(2)
    ]
    report = coordinate_ingest.inventory_uscode_source_coordinates(documents,
        query="authored-coordinate-eligibility", release_id="authored-coordinate-release")
    pin = coordinate_ingest.uscode_source_coordinates_sha256(report)
    _, spans = coordinate_cache._coordinate_replay(report, pin)
    assert len(spans) == 4
    rows, provenance = [], []
    for ordinal, index in enumerate((1, 3)):
        source = spans[index]
        reference = coordinate_cache._coordinate_wire(
            coordinate_cache._coordinate_reference(report, spans, pin, index),
            coordinate_cache.MAX_SOURCE_COORDINATE_REFERENCE_BYTES).decode("utf-8")
        value = paired(str(ordinal), text=source["text"],
                       canonical=[formal(origin="authored_engineering_fixture")])
        value["schema_version"] = "uscode-paired-span-census/v2"
        value["source"].update(span_id=source["source_span_id"], legal_id=source["legal_id"],
                                 revision=report["release_id"])
        rows.append(value)
        provenance.append(reference)
    joined_report = joined(*rows)
    joined_report.update(schema="legal-source-span-entity-join-manifest/v2",
        source_compatibility_profile="paired-coordinate-three-cache-join/v1",
        selection_scope="exact_selected_paired_v3_bundle_with_complete_source_coordinates",
        producer_pins={"historical-declared-producer": "d" * 64})
    inventory = joined_report["span_inventory"]
    inventory["schema"] = "legal-paired-manifest-inventory/v2"
    selected = inventory["manifests"][0]
    old_path = selected["path_in_repo"]
    path = old_path.replace("paired-v1", "paired-v3")
    table = selected["manifest"]["tables"]["paired_spans"]
    table["path_in_repo"] = table["path_in_repo"].replace("paired-v1", "paired-v3")
    raw_report = json.dumps(report, sort_keys=False, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    carrier = {"report_raw_utf8": raw_report.decode("utf-8"), "report_bytes": len(raw_report),
               "report_artifact_sha256": sha(raw_report), "report_sha256": pin}
    assert sha(raw_report) != pin
    selected.update(path_in_repo=path, bank="paired-v3", source_coordinate_report_sha256=pin)
    selected["manifest"].update(schema="uscode-paired-span-bundle/v3", coordinate_transport={
        "schema": "paired-source-coordinate-transport/v1", "report_artifact_sha256": sha(raw_report),
        "report_sha256": pin, "index_artifact_sha256": "e" * 64})
    bundle = joined_report["paired_bundles"][0]
    bundle["manifest_path_in_repo"] = path
    intake = bundle["payload_intake"]
    intake.update(schema="legal-paired-payload-intake/v2", manifest_path_in_repo=path,
                  manifest_schema="uscode-paired-span-bundle/v3", source_coordinates=carrier)
    intake["tables"]["paired_spans"] = deepcopy(table)
    for index, (payload_row, physical, reference, provenance_json) in enumerate(zip(
            intake["rows"], joined_report["physical_rows"], joined_report["row_references"], provenance)):
        global_index = (1, 3)[index]
        coordinate_fields = {"source_provenance_json": provenance_json,
            "source_coordinate_report_sha256": pin, "source_coordinate_span_index": global_index}
        payload_row.update(coordinate_fields)
        physical["physical_identity"]["path_in_repo"] = table["path_in_repo"]
        identity = deepcopy(physical["physical_identity"])
        identity_sha = sha(wire(identity))
        physical.update(physical_identity=identity, physical_identity_sha256=identity_sha)
        reference.update(physical_identity=deepcopy(identity), physical_identity_sha256=identity_sha,
            manifest_path_in_repo=path, bank="paired-v3", **coordinate_fields,
            coordinate_transport_status="complete_report_occurrence_replayed")
    joined_report["counts"]["coordinate_occurrence_replayed_rows"] = 2
    return {"join": joined_report, "report": report, "pin": pin,
            "provenance": provenance, "documents": documents}


@pytest.fixture
def coordinate_harness(harness, monkeypatch):
    state = harness
    state.update(coordinate_joined_fixture())
    state["coordinate_calls"] = []
    real_load = coordinate_cache.load_source_coordinate_report
    real_validate = coordinate_cache.validate_source_coordinate_rows

    def load(raw, **kwargs):
        state["coordinate_calls"].append(("load", raw, dict(kwargs)))
        return real_load(raw, **kwargs)

    def validate_rows(report, rows, **kwargs):
        state["coordinate_calls"].append(("rows", deepcopy(rows), dict(kwargs)))
        return real_validate(report, rows, **kwargs)

    monkeypatch.setattr(coordinate_cache, "load_source_coordinate_report", load)
    monkeypatch.setattr(coordinate_cache, "validate_source_coordinate_rows", validate_rows)
    return state


def retained_coordinate_inputs_v1(state, *, pretty_join=False, **changes):
    join_raw = (json.dumps(state["join"], sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
                if pretty_join else wire(state["join"]))
    request = {"schema": owner.RETAINED_REQUEST_SCHEMA_V1,
        "source_compatibility_profile": owner.RETAINED_PROFILE_V1,
        "join_manifest_raw_sha256": sha(join_raw), "join_manifest_sha256": sha(wire(state["join"])),
        "expected_physical_ids": [entry["physical_identity_sha256"] for entry in state["join"]["physical_rows"]],
        "decoder_profile": "source_span_formula_v1", "latent_dimension": 0,
        "source_coordinate_report_sha256": state["pin"], **changes}
    return wire(request), join_raw


def coordinate_prepare(state, **changes):
    request, join_raw = retained_coordinate_inputs_v1(state, **changes)
    return owner.prepare_retained_source_span_target_eligibility_v1(request, join_raw,
        expected_request_sha256=sha(request))


def coordinate_validate(state, report, **changes):
    request, join_raw = retained_coordinate_inputs_v1(state, **changes)
    value = json.loads(report) if type(report) is bytes else report
    return owner.validate_retained_source_span_target_eligibility_v1(report, request, join_raw,
        expected_request_sha256=sha(request),
        expected_report_sha256=owner.source_span_target_eligibility_sha256(value))


def coordinate_carrier(state):
    return state["join"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]


def test_coordinate_eligibility_replays_genuine_complete_report_and_exact_occurrences(coordinate_harness):
    state = coordinate_harness
    before = deepcopy(state["join"])
    result = coordinate_prepare(state)
    assert coordinate_validate(state, result) == result
    assert coordinate_validate(state, wire(result)) == result
    assert state["join"] == before
    assert result["schema"] == owner.RETAINED_SCHEMA_V1
    assert result["source_coordinates"] == coordinate_carrier(state)
    assert result["source_coordinate_report_sha256"] == state["pin"]
    assert result["source_coordinates"]["report_artifact_sha256"] != state["pin"]
    assert result["upstream_reexecution_performed"] is False
    assert [entry["source_coordinate_span_index"] for entry in result["physical_rows"]] == [1, 3]
    assert [entry["source_provenance_json"] for entry in result["physical_rows"]] == state["provenance"]
    assert result["row_references"] == before["row_references"]
    assert [entry[0] for entry in state["coordinate_calls"]].count("load") >= 1
    assert [entry[0] for entry in state["coordinate_calls"]].count("rows") >= 1
    assert state["audit_calls"]
    assert result["counts"]["mechanically_supported_outputs"] == 2
    assert result["counts"]["consumer_eligible_rows"] == 0
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert all(type(value) is bool and value is False for value in result["authority"].values())
    assert all(type(row["training_mask"]) is int and row["training_mask"] == 0
               and row["selected_occurrence"] is None for row in result["physical_rows"])


def test_coordinate_eligibility_distinct_original_occurrences_keep_equal_text_and_physical_rows(coordinate_harness):
    state = coordinate_harness
    result = coordinate_prepare(state)
    physical = result["physical_rows"]
    assert physical[0]["source_text"] == physical[1]["source_text"] == "Clerk shall file report."
    assert len({row["physical_identity_sha256"] for row in physical}) == 2
    assert physical[0]["source_provenance_json"] != physical[1]["source_provenance_json"]
    assert [row["source_coordinate_span_index"] for row in physical] == [1, 3]
    assert result["counts"]["physical_rows"] == result["counts"]["output_occurrences"] == 2
    assert result["counts"]["distinct_source_texts"] == 1
    assert all("duplicate_source_text" in output["consumer_compatibility_blockers"]
               for output in result["output_occurrences"])


def test_coordinate_eligibility_preserves_report_transport_bytes_and_separate_raw_join_pin(coordinate_harness):
    state = coordinate_harness
    first = coordinate_prepare(state)
    carrier = coordinate_carrier(state)
    raw = json.dumps(json.loads(carrier["report_raw_utf8"]), sort_keys=False,
                     ensure_ascii=False, indent=2).encode("utf-8")
    assert raw.index(b'z_metadata') < raw.index(b'a_metadata')
    carrier.update(report_raw_utf8=raw.decode("utf-8"), report_bytes=len(raw), report_artifact_sha256=sha(raw))
    state["join"]["span_inventory"]["manifests"][0]["manifest"]["coordinate_transport"]["report_artifact_sha256"] = sha(raw)
    result = coordinate_prepare(state, pretty_join=True)
    assert coordinate_validate(state, result, pretty_join=True) == result
    assert result["source_coordinates"] == carrier
    assert result["source_coordinates"]["report_raw_utf8"].encode("utf-8") == raw
    assert result["source_coordinate_report_sha256"] == first["source_coordinate_report_sha256"]
    assert result["join_manifest_raw_sha256"] != first["join_manifest_raw_sha256"]
    result["source_coordinates"]["report_raw_utf8"] = "mutated returned value"
    assert coordinate_carrier(state)["report_raw_utf8"] == raw.decode("utf-8")


@pytest.mark.parametrize("route", ["v1_rejects_coordinate", "v2_rejects_legacy"])
def test_coordinate_eligibility_keeps_explicit_legacy_and_coordinate_entrypoints(coordinate_harness, route):
    state = coordinate_harness
    if route == "v1_rejects_coordinate":
        request, join_raw = inputs(state)
        with pytest.raises(ValueError):
            owner.prepare_source_span_target_eligibility(request, join_raw, expected_request_sha256=sha(request))
    else:
        state["join"] = joined(paired(canonical=[formal()]))
        with pytest.raises(ValueError):
            coordinate_prepare(state)


@pytest.mark.parametrize("damage", ["missing", "boolean", "uppercase", "different", "raw_artifact_pin"])
def test_coordinate_eligibility_requires_independent_canonical_coordinate_pin(coordinate_harness, damage):
    state = coordinate_harness
    request, join_raw = retained_coordinate_inputs_v1(state)
    request = json.loads(request)
    if damage == "missing":
        request.pop("source_coordinate_report_sha256")
    else:
        request["source_coordinate_report_sha256"] = {
            "boolean": True, "uppercase": "A" * 64, "different": "0" * 64,
            "raw_artifact_pin": coordinate_carrier(state)["report_artifact_sha256"]}[damage]
    raw = wire(request)
    with pytest.raises(ValueError):
        owner.prepare_retained_source_span_target_eligibility_v1(raw, join_raw, expected_request_sha256=sha(raw))
    assert state["audit_calls"] == []


@pytest.mark.parametrize("damage", ["missing", "extra", "raw_utf8", "length", "boolean_length",
                                    "artifact_hash", "report_pin", "source_text", "manifest_artifact"])
def test_coordinate_eligibility_resealed_carrier_and_report_forgeries_refuse(coordinate_harness, damage):
    state = coordinate_harness
    carrier = coordinate_carrier(state)
    if damage == "missing":
        del state["join"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    elif damage == "extra":
        carrier["source_verified"] = True
    elif damage == "raw_utf8":
        carrier["report_raw_utf8"] += " "
    elif damage == "length":
        carrier["report_bytes"] += 1
    elif damage == "boolean_length":
        carrier["report_bytes"] = True
    elif damage == "artifact_hash":
        carrier["report_artifact_sha256"] = "0" * 64
    elif damage == "report_pin":
        carrier["report_sha256"] = "0" * 64
    elif damage == "manifest_artifact":
        state["join"]["span_inventory"]["manifests"][0]["manifest"]["coordinate_transport"]["report_artifact_sha256"] = "0" * 64
    else:
        changed = json.loads(carrier["report_raw_utf8"])
        changed["documents"][0]["source_text"] += " changed"
        raw = json.dumps(changed, sort_keys=False, ensure_ascii=False).encode("utf-8")
        carrier.update(report_raw_utf8=raw.decode(), report_bytes=len(raw), report_artifact_sha256=sha(raw))
        state["join"]["span_inventory"]["manifests"][0]["manifest"]["coordinate_transport"]["report_artifact_sha256"] = sha(raw)
    with pytest.raises((ValueError, coordinate_cache.SpanCacheError)):
        coordinate_prepare(state)
    assert state["audit_calls"] == []


@pytest.mark.parametrize("damage", ["wrong_global_index", "boolean_index", "foreign_provenance",
                                    "foreign_report", "reference_index", "raw_source"])
def test_coordinate_eligibility_preserves_original_global_source_and_provenance(coordinate_harness, damage):
    state = coordinate_harness
    payload = state["join"]["paired_bundles"][0]["payload_intake"]["rows"][0]
    reference = state["join"]["row_references"][0]
    if damage == "wrong_global_index":
        payload["source_coordinate_span_index"] = reference["source_coordinate_span_index"] = 0
    elif damage == "boolean_index":
        payload["source_coordinate_span_index"] = reference["source_coordinate_span_index"] = True
    elif damage == "foreign_provenance":
        foreign = state["provenance"][1]
        payload["source_provenance_json"] = reference["source_provenance_json"] = foreign
    elif damage == "foreign_report":
        payload["source_coordinate_report_sha256"] = reference["source_coordinate_report_sha256"] = "0" * 64
    elif damage == "reference_index":
        reference["source_coordinate_span_index"] = 0
    else:
        def mutate(row):
            row["source"]["text"] = "Another clerk shall file report."
            row["source"]["text_sha256"] = sha(row["source"]["text"].encode())
        replace_retained_row(state, mutate)
    with pytest.raises((ValueError, coordinate_cache.SpanCacheError)):
        coordinate_prepare(state)
    assert state["audit_calls"] == []


@pytest.mark.parametrize("damage", ["drop_payload", "drop_reference", "drop_physical",
                                    "reorder_references", "duplicate_reference", "count"])
def test_coordinate_eligibility_refuses_population_loss_and_physical_relabeling(coordinate_harness, damage):
    state = coordinate_harness
    retained = state["join"]
    if damage == "drop_payload": retained["paired_bundles"][0]["payload_intake"]["rows"].pop()
    elif damage == "drop_reference": retained["row_references"].pop()
    elif damage == "drop_physical": retained["physical_rows"].pop()
    elif damage == "reorder_references": retained["row_references"].reverse()
    elif damage == "duplicate_reference": retained["row_references"][1] = deepcopy(retained["row_references"][0])
    else: retained["counts"]["coordinate_occurrence_replayed_rows"] += 1
    with pytest.raises(ValueError):
        coordinate_prepare(state)


@pytest.mark.parametrize("damage", ["authority", "training_boolean", "gold_one", "crosswalk", "entity"])
def test_coordinate_eligibility_coordinate_custody_cannot_promote_source_or_semantic_gates(coordinate_harness, damage):
    retained = coordinate_harness["join"]
    if damage == "authority": retained["authority"]["source_semantics_verified"] = True
    elif damage == "training_boolean": retained["training_mask"] = False
    elif damage == "gold_one": retained["evaluation_gold_mask"] = 1
    elif damage == "crosswalk": retained["row_references"][0]["current_source_release_correspondence"] = "reviewed"
    else: retained["row_references"][0]["entity_binding"] = "verified"
    with pytest.raises(ValueError):
        coordinate_prepare(coordinate_harness)


@pytest.mark.parametrize("damage", ["carrier", "index", "reference", "mask"])
def test_coordinate_eligibility_output_resealing_cannot_replace_original_replay(coordinate_harness, damage):
    result = coordinate_prepare(coordinate_harness)
    if damage == "carrier": result["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "index": result["physical_rows"][0]["source_coordinate_span_index"] = 0
    elif damage == "reference": result["row_references"][0]["source_provenance_json"] = "{}"
    else: result["training_mask"] = 1
    with pytest.raises(ValueError):
        coordinate_validate(coordinate_harness, result)


@pytest.mark.parametrize("stage", ["load", "rows"])
def test_coordinate_eligibility_closing_checks_detect_source_change_after_genuine_coordinate_work(
        coordinate_harness, monkeypatch, stage):
    function = "load_source_coordinate_report" if stage == "load" else "validate_source_coordinate_rows"
    real = getattr(coordinate_cache, function)

    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        monkeypatch.setattr(owner, "_SELF_PIN", "0" * 64)
        return result

    monkeypatch.setattr(coordinate_cache, function, changed)
    with pytest.raises(ValueError, match="producer changed"):
        coordinate_prepare(coordinate_harness)


def test_coordinate_eligibility_primary_helper_error_retains_secondary_closing_custody(
        coordinate_harness, monkeypatch):
    original = coordinate_cache.validate_source_coordinate_rows
    primary = RuntimeError("authored primary coordinate failure after genuine validation")

    def fail_after_genuine(*args, **kwargs):
        original(*args, **kwargs)
        monkeypatch.setattr(owner, "_SELF_PIN", "0" * 64)
        raise primary

    monkeypatch.setattr(coordinate_cache, "validate_source_coordinate_rows", fail_after_genuine)
    with pytest.raises(RuntimeError) as caught:
        coordinate_prepare(coordinate_harness)
    assert caught.value is primary
    assert any("secondary eligibility custody failure" in note
               for note in getattr(primary, "__notes__", []))


@pytest.mark.parametrize("target", ["complete_report", "selected_rows"])
def test_coordinate_eligibility_refuses_coordinate_delegate_mutation_after_genuine_validation(
        coordinate_harness, monkeypatch, target):
    original = coordinate_cache.validate_source_coordinate_rows

    def changed(report, rows, **kwargs):
        indices = original(report, rows, **kwargs)
        if target == "complete_report":
            report["documents"][0]["source_text"] += " changed after genuine validation"
        else:
            rows[0]["text"] += " changed after genuine validation"
        return indices

    monkeypatch.setattr(coordinate_cache, "validate_source_coordinate_rows", changed)
    with pytest.raises(ValueError):
        coordinate_prepare(coordinate_harness)


def test_coordinate_eligibility_uses_genuine_canonical_owner_closure_without_registry_or_join_doubles(
        coordinate_harness, monkeypatch):
    monkeypatch.setattr(owner, "_owners", _coordinate_genuine_owners)
    result = coordinate_prepare(coordinate_harness)
    assert coordinate_validate(coordinate_harness, result) == result
    assert "logic_tree_guard_paths" in result["producer_pins"]
    assert result["runtime_description"]["runtime_id"] == "legal_ir:source_span_formula_v1"
    assert result["current_coordinate_producer_pins"]
    assert result["counts"]["physical_rows"] == 2
    assert result["counts"]["consumer_eligible_rows"] == 0
    assert all(value is False for value in result["authority"].values())


def test_coordinate_eligibility_refuses_foreign_coordinate_owner_paths_before_reading_them(
        coordinate_harness, monkeypatch, tmp_path):
    foreign = tmp_path / "foreign-checkout"
    cache_path = foreign / "ipfs_datasets_py/logic/autoformal/span_cache.py"
    ingest_path = foreign / "ipfs_datasets_py/logic/autoformal/uscode_ingest.py"
    assert not foreign.exists()
    original = Path.read_bytes

    def deny_foreign_read(path):
        if foreign in path.parents:
            pytest.fail("foreign coordinate source was read before canonical-root refusal")
        return original(path)

    monkeypatch.setattr(coordinate_cache, "__file__", str(cache_path))
    monkeypatch.setattr(coordinate_ingest, "__file__", str(ingest_path))
    monkeypatch.setattr(Path, "read_bytes", deny_foreign_read)
    with pytest.raises(ValueError, match="escaped selected source tree"):
        coordinate_prepare(coordinate_harness)
    assert coordinate_harness["coordinate_calls"] == []
    assert coordinate_harness["audit_calls"] == []
    assert not foreign.exists()


@pytest.mark.parametrize("damage", ["legacy_candidate_join", "source_disposition"])
def test_coordinate_eligibility_rejects_unresolved_source_status_forgery_and_legacy_join_mixing(
        coordinate_harness, damage):
    retained = coordinate_harness["join"]
    if damage == "legacy_candidate_join":
        retained["paired_bundles"][0]["legacy_candidate_join"] = {"unprovided_legacy_correspondence": True}
    else:
        retained["row_references"][0]["source_disposition"] = "selected_governing_source"
    with pytest.raises(ValueError):
        coordinate_prepare(coordinate_harness)
    assert coordinate_harness["audit_calls"] == []


@pytest.mark.parametrize("damage", ["paired_v1", "foreign_source_revision", "foreign_reference_revision"])
def test_coordinate_eligibility_preserves_original_paired_generation_and_declared_report_release(
        coordinate_harness, damage):
    state = coordinate_harness
    payload = state["join"]["paired_bundles"][0]["payload_intake"]["rows"][0]
    reference = state["join"]["row_references"][0]
    if damage == "foreign_reference_revision":
        reference["producer_source_revision_label"] = "foreign-unadopted-release"
    else:
        def mutate(row):
            if damage == "paired_v1":
                row["schema_version"] = "uscode-paired-span-census/v1"
            else:
                row["source"]["revision"] = "foreign-unadopted-release"
        replace_retained_row(state, mutate)
        # Preserve a genuinely valid candidate for the changed row: the v2
        # coordinate-generation/release check must reject independently of an
        # unrelated stale candidate commitment.
        raw = payload["derived_row_json"].encode("utf-8")
        payload["candidate"] = adapter.adapt_paired_span_bytes(raw,
            expected_row_sha256=payload["row_sha256"])
        if damage == "foreign_source_revision":
            reference["producer_source_revision_label"] = "foreign-unadopted-release"
    with pytest.raises(ValueError):
        coordinate_prepare(state)
    assert state["audit_calls"] == []


# The additive coordinate cohort uses genuine source/package/Arrow/join/runtime
# owners. Only named negative controls replace a delegate after genuine work.
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as coordinate_join_owner
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import (
    coordinate_join, prepare as prepare_coordinate_join,
)


@pytest.fixture
def original_replay_v3(coordinate_join):
    case = coordinate_join
    raw = wire(case["request"])
    originals = {"request_raw": raw, "source_request_raw": case["source_raw"],
        "source_metadata_bytes": case["metadata"],
        "paired_inventory_request_raw": wire(case["paired_request"]),
        "paired_manifest_bytes": case["manifests"], "entity_info_raw": case["info_raw"],
        "expected_request_sha256": sha(raw), "legacy_join_inputs": None}
    return {"case": case, "join": prepare_coordinate_join(case), "originals": originals}


def original_replay_inputs_v3(case, **changes):
    raw = wire(case["join"])
    request = {"schema": owner.REQUEST_SCHEMA_V3, "join_manifest_raw_sha256": sha(raw),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(case["join"]),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in case["join"]["physical_rows"]],
        "decoder_profile": owner.DECODER_PROFILE, "latent_dimension": 0,
        "join_originals_sha256": owner.source_span_target_join_originals_sha256(case["originals"]),
        "source_coordinate_report_sha256": case["case"]["coordinate"]["pin"],
        "source_compatibility_profile": owner.ORIGINAL_REPLAY_PROFILE_V3, **changes}
    return wire(request), raw


def prepare_original_replay_v3(case, **changes):
    request, raw = original_replay_inputs_v3(case, **changes)
    return owner.prepare_source_span_target_eligibility_v3(request, raw,
        expected_request_sha256=sha(request), join_originals=case["originals"])


def validate_original_replay_v3(case, report):
    request, raw = original_replay_inputs_v3(case)
    value = json.loads(report) if type(report) is bytes else report
    return owner.validate_source_span_target_eligibility_v3(report, request, raw,
        expected_request_sha256=sha(request),
        expected_report_sha256=owner.source_span_target_eligibility_sha256(value),
        join_originals=case["originals"])


def assert_original_replay_unqualified_v3(report):
    assert all(type(flag) is bool and flag is False for flag in report["authority"].values())
    for row in [report, *report["physical_rows"], *report["row_references"], *report["output_occurrences"]]:
        assert type(row["training_mask"]) is int and row["training_mask"] == 0
        assert type(row["evaluation_gold_mask"]) is int and row["evaluation_gold_mask"] == 0
    for row in report["physical_rows"] + report["output_occurrences"]:
        assert row["consumer_eligible"] is False
        assert all(type(mask) is int and mask == 0 for mask in row["field_masks"].values())


def test_original_replay_v3_genuine_roundtrip_preserves_unresolved_semantics(original_replay_v3):
    case = original_replay_v3
    report = prepare_original_replay_v3(case)
    assert validate_original_replay_v3(case, report) == report
    assert validate_original_replay_v3(case, wire(report)) == report
    reordered = {key: report[key] for key in reversed(report)}
    assert validate_original_replay_v3(case, reordered) == report
    assert report["schema"] == owner.SCHEMA_V3
    assert report["upstream_reexecution_performed"] is True
    assert report["runtime_description"]["runtime_version"] == owner.DECODER_PROFILE
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["entity_binding"] == "unavailable_semantic_companions_not_supplied"
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["consumer_eligible_rows"] == 0
    assert report["counts"]["output_occurrences"] > 0
    assert_original_replay_unqualified_v3(report)


def test_original_replay_v3_retains_one_complete_join_and_exact_original_span_indices(original_replay_v3):
    case = original_replay_v3
    report = prepare_original_replay_v3(case)
    assert report["join_manifest_raw_utf8"].encode() == wire(case["join"])
    joined_report = json.loads(report["join_manifest_raw_utf8"])
    carrier = joined_report["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert len(json.loads(carrier["report_raw_utf8"])["spans"]) == 4
    assert carrier["report_sha256"] == report["source_coordinate_report_sha256"]
    assert [row["source_coordinate_span_index"] for row in report["physical_rows"]] == [1, 3]
    rows = report["physical_rows"]
    assert rows[0]["source_text"] == rows[1]["source_text"]
    assert rows[0]["physical_identity_sha256"] != rows[1]["physical_identity_sha256"]
    refs = {row["physical_identity_sha256"]: row for row in case["join"]["row_references"]}
    for row in rows + report["output_occurrences"]:
        original = refs[row["physical_identity_sha256"]]
        for key in owner._COORDINATE_FIELDS:
            assert row[key] == original[key]
        assert "report_raw_utf8" not in row
    assert "report_raw_utf8" not in report
    def retained_join_count(value):
        if type(value) is dict:
            return sum(retained_join_count(child) for child in value.values())
        if type(value) is list:
            return sum(retained_join_count(child) for child in value)
        return int(type(value) is str and value == report["join_manifest_raw_utf8"])
    # This checks the new report layer; the original join retains its own scope.
    assert retained_join_count(report) == 1


@pytest.mark.parametrize("dimension", [0, 384], ids=["zero", "native384"])
def test_original_replay_v3_dimension_never_dispatches_or_creates_latents(original_replay_v3, dimension):
    report = prepare_original_replay_v3(original_replay_v3, latent_dimension=dimension)
    assert report["request"]["latent_dimension"] == dimension
    assert not any("latent" in row for row in report["physical_rows"])
    assert_original_replay_unqualified_v3(report)


def test_original_replay_v3_legacy_entrypoint_rejects_v3_even_with_legacy_request_shape(original_replay_v3):
    request_raw, raw = original_replay_inputs_v3(original_replay_v3)
    request = json.loads(request_raw)
    request["schema"] = owner.REQUEST_SCHEMA
    request.pop("join_originals_sha256")
    request.pop("source_compatibility_profile")
    request.pop("source_coordinate_report_sha256")
    request_raw = wire(request)
    with pytest.raises(ValueError, match="complete selected join"):
        owner.prepare_source_span_target_eligibility(request_raw, raw,
            expected_request_sha256=sha(request_raw))


def test_original_replay_v3_refuses_legacy_join_before_discovery(original_replay_v3, monkeypatch):
    case = original_replay_v3
    case["join"] = joined(paired(canonical=[formal()]))
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("legacy join reached discovery"))
    with pytest.raises(ValueError, match="coordinate join v2"):
        prepare_original_replay_v3(case)


@pytest.mark.parametrize("damage", ["schema", "extra", "raw_pin", "canonical_pin", "originals_pin", "coordinate_pin"],
    ids=["schema", "extra", "raw-pin", "canonical-pin", "originals-pin", "coordinate-pin"])
def test_original_replay_v3_independent_closed_request_refuses(original_replay_v3, damage):
    changes = {"schema": {"schema": owner.REQUEST_SCHEMA}, "extra": {"reviewed": True},
        "raw_pin": {"join_manifest_raw_sha256": "0" * 64},
        "canonical_pin": {"join_manifest_sha256": "0" * 64},
        "originals_pin": {"join_originals_sha256": "0" * 64},
        "coordinate_pin": {"source_coordinate_report_sha256": "0" * 64}}[damage]
    with pytest.raises(ValueError):
        prepare_original_replay_v3(original_replay_v3, **changes)


@pytest.mark.parametrize("damage", ["omit", "reverse", "duplicate", "foreign"],
    ids=["omit", "reverse", "duplicate", "foreign"])
def test_original_replay_v3_requires_exact_physical_population(original_replay_v3, damage):
    case = original_replay_v3
    ids = [row["physical_identity_sha256"] for row in case["join"]["physical_rows"]]
    changed = {"omit": ids[:1], "reverse": ids[::-1], "duplicate": [ids[0], ids[0]],
        "foreign": [ids[0], "0" * 64]}[damage]
    with pytest.raises(ValueError):
        prepare_original_replay_v3(case, expected_physical_ids=changed)


@pytest.mark.parametrize("damage", ["index", "reference", "carrier", "physical", "row_count",
    "omit_row", "training_mask", "gold_mask", "crosswalk", "entity"],
    ids=["index", "reference", "carrier", "physical", "row-count", "omit-row", "training-mask",
         "gold-mask", "crosswalk", "entity"])
def test_original_replay_v3_rehashed_join_requires_genuine_original_replay(original_replay_v3, damage):
    report = original_replay_v3["join"]
    row = report["row_references"][0]
    if damage == "index": row["source_coordinate_span_index"] = 0
    elif damage == "reference": row["source_provenance_json"] = report["row_references"][1]["source_provenance_json"]
    elif damage == "carrier": report["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "physical": report["physical_rows"][0]["physical_identity_sha256"] = "0" * 64
    elif damage == "row_count": report["counts"]["physical_paired_rows"] += 1
    elif damage == "omit_row": report["paired_bundles"][0]["payload_intake"]["rows"].pop()
    elif damage == "training_mask": report["training_mask"] = True
    elif damage == "gold_mask": row["evaluation_gold_mask"] = 1
    elif damage == "crosswalk": row["current_source_release_correspondence"] = "verified"
    else: row["entity_binding"] = "verified"
    with pytest.raises(ValueError):
        prepare_original_replay_v3(original_replay_v3)


@pytest.mark.parametrize("damage", ["index", "index_bool", "reference", "join_bytes", "mask", "outputs"],
    ids=["index", "index-bool", "reference", "join-bytes", "mask", "outputs"])
def test_original_replay_v3_rehashed_report_requires_exact_regeneration(original_replay_v3, damage):
    report = prepare_original_replay_v3(original_replay_v3)
    if damage == "index": report["physical_rows"][0]["source_coordinate_span_index"] = 0
    elif damage == "index_bool": report["physical_rows"][0]["source_coordinate_span_index"] = True
    elif damage == "reference": report["output_occurrences"][0]["source_provenance_json"] = "{}"
    elif damage == "join_bytes": report["join_manifest_raw_utf8"] += " "
    elif damage == "mask": report["training_mask"] = 1
    else: report["output_occurrences"].pop()
    with pytest.raises(ValueError, match="full original-input replay"):
        validate_original_replay_v3(original_replay_v3, report)


def test_original_replay_v3_original_metadata_drift_is_caught_after_real_audit(original_replay_v3, monkeypatch):
    case = original_replay_v3
    actual, called = span.audit_examples, []
    def drift(rows):
        result = actual(rows)
        if not called:
            called.append(True)
            metadata = case["originals"]["source_metadata_bytes"]
            key = next(iter(metadata))
            metadata[key] += b"\n"
        return result
    monkeypatch.setattr(span, "audit_examples", drift)
    with pytest.raises(ValueError, match="originals changed"):
        prepare_original_replay_v3(case)
    assert called


@pytest.mark.parametrize("producer", ["eligibility", "join"], ids=["eligibility", "join"])
def test_original_replay_v3_stale_producer_refuses(original_replay_v3, monkeypatch, producer):
    module = owner if producer == "eligibility" else coordinate_join_owner
    monkeypatch.setattr(module, "_SELF_PIN", "0" * 64)
    with pytest.raises(ValueError, match="changed since import"):
        prepare_original_replay_v3(original_replay_v3)


def test_original_replay_v3_closing_replay_catches_physical_drift_after_real_audit(original_replay_v3, monkeypatch):
    case = original_replay_v3
    actual, called = span.audit_examples, []
    def drift(rows):
        result = actual(rows)
        if not called:
            called.append(True)
            table = case["join"]["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]
            root = Path(case["case"]["request"]["paired_bundles"][0]["repository_root"])
            target = root / table["path_in_repo"]
            target.write_bytes(target.read_bytes() + b"changed")
        return result
    monkeypatch.setattr(span, "audit_examples", drift)
    with pytest.raises(ValueError):
        prepare_original_replay_v3(case)
    assert called


def test_original_replay_v3_operational_error_still_attempts_genuine_closing_join(original_replay_v3, monkeypatch):
    actual_audit = span.audit_examples
    actual_replay = coordinate_join_owner.validate_source_span_entity_join_manifest_v2
    calls = []
    def replay(*args, **kwargs):
        calls.append(True)
        return actual_replay(*args, **kwargs)
    def fail(rows):
        actual_audit(rows)
        raise RuntimeError("authored failure after real decoder audit")
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", replay)
    monkeypatch.setattr(span, "audit_examples", fail)
    with pytest.raises(RuntimeError, match="authored failure"):
        prepare_original_replay_v3(original_replay_v3)
    assert len(calls) == 2


def test_original_replay_v3_primary_error_retains_secondary_original_custody_failure(original_replay_v3, monkeypatch):
    case = original_replay_v3
    actual = span.audit_examples
    def fail(rows):
        actual(rows)
        case["originals"]["source_metadata_bytes"]["extra"] = b"changed"
        raise RuntimeError("primary authored failure")
    monkeypatch.setattr(span, "audit_examples", fail)
    with pytest.raises(RuntimeError, match="primary authored failure") as caught:
        prepare_original_replay_v3(case)
    assert any("original inputs" in note for note in caught.value.__notes__)


def test_original_replay_v3_validator_checks_offered_report_after_real_replay(original_replay_v3, monkeypatch):
    case = original_replay_v3
    report = prepare_original_replay_v3(case)
    actual = span.audit_examples
    def mutate(rows):
        result = actual(rows)
        report["training_mask"] = True
        return result
    monkeypatch.setattr(span, "audit_examples", mutate)
    with pytest.raises(ValueError, match="offered coordinate eligibility report changed"):
        validate_original_replay_v3(case, report)


@pytest.mark.parametrize("damage", ["physical_rows", "metadata_count", "metadata_bytes"],
    ids=["physical-row-bound", "metadata-count-bound", "metadata-byte-bound"])
def test_original_replay_v3_bounds_refuse_before_discovery(original_replay_v3, monkeypatch, damage):
    case = original_replay_v3
    request, raw = original_replay_inputs_v3(case)
    request = json.loads(request)
    if damage == "physical_rows": request["expected_physical_ids"] = ["a" * 64] * 65
    elif damage == "metadata_count": case["originals"]["source_metadata_bytes"] = {str(i): b"x" for i in range(17)}
    else: case["originals"]["source_metadata_bytes"] = {"large": b"x" * (owner.MAX_COORDINATE_ORIGINAL_BYTES + 1)}
    request = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("invalid bound reached discovery"))
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility_v3(request, raw,
            expected_request_sha256=sha(request), join_originals=case["originals"])


def retained_request_from_original_replay_v3(case):
    request, raw = original_replay_inputs_v3(case)
    request = json.loads(request)
    request["schema"] = owner.RETAINED_REQUEST_SCHEMA_V1
    request.pop("join_originals_sha256")
    request["source_compatibility_profile"] = owner.RETAINED_PROFILE_V1
    return wire(request), raw


@pytest.mark.parametrize("damage", ["missing", "foreign", "boolean", "historical"],
    ids=["missing-profile", "foreign-profile", "boolean-profile", "historical-v2-profile"])
def test_original_replay_v3_requires_mandatory_profile_before_discovery(original_replay_v3, monkeypatch, damage):
    request, raw = original_replay_inputs_v3(original_replay_v3)
    request = json.loads(request)
    if damage == "missing": request.pop("source_compatibility_profile")
    else: request["source_compatibility_profile"] = {
        "foreign": "retained-report-audit/v1", "boolean": True,
        "historical": "paired-coordinate-target-eligibility/v1"}[damage]
    request = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("invalid profile reached discovery"))
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility_v3(request, raw,
            expected_request_sha256=sha(request), join_originals=original_replay_v3["originals"])


@pytest.mark.parametrize("generation", ["retained_v2", "historical_original_v2"],
    ids=["retained-v2-shape", "historical-original-v2-shape"])
def test_original_replay_v3_never_infers_upgrade_from_v2_shape(original_replay_v3, monkeypatch, generation):
    if generation == "retained_v2":
        request, raw = retained_request_from_original_replay_v3(original_replay_v3)
    else:
        request, raw = original_replay_inputs_v3(original_replay_v3)
        request = json.loads(request)
        request["schema"] = owner.REQUEST_SCHEMA_V2
        request.pop("source_compatibility_profile")
        request = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("v2 request reached v3 discovery"))
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility_v3(request, raw,
            expected_request_sha256=sha(request), join_originals=original_replay_v3["originals"])


@pytest.mark.parametrize("extra", ["join_originals_sha256", "source_compatibility_profile"],
    ids=["originals-commitment", "original-replay-profile"])
def test_retained_v1_rejects_original_replay_request_extensions(original_replay_v3, monkeypatch, extra):
    request, raw = retained_request_from_original_replay_v3(original_replay_v3)
    request = json.loads(request)
    request[extra] = (owner.source_span_target_join_originals_sha256(original_replay_v3["originals"])
        if extra == "join_originals_sha256" else owner.ORIGINAL_REPLAY_PROFILE_V3)
    request = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("extended v2 request reached discovery"))
    with pytest.raises(ValueError):
        owner.prepare_retained_source_span_target_eligibility_v1(request, raw, expected_request_sha256=sha(request))


@pytest.mark.parametrize("operation", ["prepare", "validate"], ids=["prepare-api", "validate-api"])
def test_retained_v1_requires_its_explicit_no_originals_signature(original_replay_v3, operation):
    request, raw = retained_request_from_original_replay_v3(original_replay_v3)
    kwargs = {"expected_request_sha256": sha(request), "join_originals": original_replay_v3["originals"]}
    with pytest.raises(TypeError, match="join_originals"):
        if operation == "prepare":
            owner.prepare_retained_source_span_target_eligibility_v1(request, raw, **kwargs)
        else:
            owner.validate_retained_source_span_target_eligibility_v1({}, request, raw,
                expected_report_sha256="0" * 64, **kwargs)


@pytest.mark.parametrize("offered_generation", ["retained_v2", "original_v3"],
    ids=["retained-v2-offered-to-v3", "original-v3-offered-to-v2"])
def test_recommitted_reports_cannot_cross_explicit_replay_generations(original_replay_v3, offered_generation):
    case = original_replay_v3
    request, raw = retained_request_from_original_replay_v3(case)
    retained = owner.prepare_retained_source_span_target_eligibility_v1(request, raw, expected_request_sha256=sha(request))
    original = prepare_original_replay_v3(case)
    assert retained["upstream_reexecution_performed"] is False
    assert retained["coordinate_validation_scope"] == "stored_supplied_documents_and_exact_selected_references_only"
    assert "source_coordinates" in retained and "join_manifest_raw_utf8" not in retained
    assert original["upstream_reexecution_performed"] is True
    assert "source_coordinates" not in original and "source_coordinates_reference" in original
    with pytest.raises(ValueError, match="differs from full"):
        if offered_generation == "retained_v2":
            validate_original_replay_v3(case, retained)
        else:
            owner.validate_retained_source_span_target_eligibility_v1(original, request, raw,
                expected_request_sha256=sha(request),
                expected_report_sha256=owner.source_span_target_eligibility_sha256(original))


@pytest.mark.parametrize("damage", ["path", "container", "artifact_pin", "canonical_pin", "boolean_bytes", "duplicate_carrier"],
    ids=["foreign-path", "foreign-container", "artifact-pin", "canonical-pin", "boolean-byte-count", "duplicate-carrier"])
def test_original_replay_v3_coordinate_reference_is_exact_under_recommitment(original_replay_v3, damage):
    report = prepare_original_replay_v3(original_replay_v3)
    reference = report["source_coordinates_reference"]
    carrier = json.loads(report["join_manifest_raw_utf8"])["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert reference == {"schema": owner.COORDINATE_REFERENCE_SCHEMA,
        "container": "join_manifest_raw_utf8", "json_pointer": "/paired_bundles/0/payload_intake/source_coordinates",
        "join_manifest_raw_sha256": report["join_manifest_raw_sha256"],
        "report_sha256": carrier["report_sha256"], "report_artifact_sha256": carrier["report_artifact_sha256"],
        "report_bytes": carrier["report_bytes"]}
    if damage == "path": reference["json_pointer"] = "/paired_bundles/1/payload_intake/source_coordinates"
    elif damage == "container": reference["container"] = "request_raw_utf8"
    elif damage == "artifact_pin": reference["report_artifact_sha256"] = "0" * 64
    elif damage == "canonical_pin": reference["report_sha256"] = "0" * 64
    elif damage == "boolean_bytes": reference["report_bytes"] = True
    else: report["source_coordinates"] = carrier
    with pytest.raises(ValueError, match="full original-input replay"):
        validate_original_replay_v3(original_replay_v3, report)


def test_original_replay_v3_fails_closed_without_genuine_join_api(original_replay_v3, monkeypatch):
    monkeypatch.delattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2")
    with pytest.raises(ValueError, match="requires the genuine coordinate join v2 owner"):
        prepare_original_replay_v3(original_replay_v3)


def test_original_replay_v3_opening_refusal_never_claims_completed_replay_or_runs_census(original_replay_v3, monkeypatch):
    calls = []
    def refused(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("authored opening refusal before genuine replay")
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", refused)
    monkeypatch.setattr(span, "audit_examples", lambda rows: pytest.fail("opening refusal reached census"))
    with pytest.raises(RuntimeError, match="authored opening refusal"):
        prepare_original_replay_v3(original_replay_v3)
    assert len(calls) == 1


def test_original_replay_v3_join_callable_replacement_after_real_audit_refuses(original_replay_v3, monkeypatch):
    actual_audit = span.audit_examples
    def changed(rows):
        result = actual_audit(rows)
        monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", lambda *a, **k: None)
        return result
    monkeypatch.setattr(span, "audit_examples", changed)
    with pytest.raises(ValueError, match="callable changed"):
        prepare_original_replay_v3(original_replay_v3)


def test_original_replay_v3_runtime_description_change_after_real_audit_refuses(original_replay_v3, monkeypatch):
    runtime = owner._owners()[4]
    actual_description, actual_audit = runtime.describe_runtime, span.audit_examples
    changed = []
    def describe(*args, **kwargs):
        result = actual_description(*args, **kwargs)
        return {**result, "authored_drift": True} if changed else result
    def audit(rows):
        result = actual_audit(rows)
        changed.append(True)
        return result
    monkeypatch.setattr(runtime, "describe_runtime", describe)
    monkeypatch.setattr(span, "audit_examples", audit)
    with pytest.raises(ValueError, match="runtime description changed"):
        prepare_original_replay_v3(original_replay_v3)


def test_original_replay_v3_primary_error_retains_genuine_closing_replay_failure(original_replay_v3, monkeypatch):
    actual_replay, actual_audit = coordinate_join_owner.validate_source_span_entity_join_manifest_v2, span.audit_examples
    calls = []
    def replay(*args, **kwargs):
        result = actual_replay(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2: raise RuntimeError("authored failure after genuine closing replay")
        return result
    def failed_audit(rows):
        actual_audit(rows)
        raise RuntimeError("authored primary census error")
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", replay)
    monkeypatch.setattr(span, "audit_examples", failed_audit)
    with pytest.raises(RuntimeError, match="authored primary census error") as caught:
        prepare_original_replay_v3(original_replay_v3)
    assert len(calls) == 2
    assert any("closing public join replay" in note and "authored failure" in note for note in caught.value.__notes__)


@pytest.mark.parametrize("target", ["originals", "retained", "callable", "runtime"],
    ids=["post-close-originals", "post-close-retained", "post-close-callable", "post-close-runtime"])
def test_original_replay_v3_rechecks_outer_custody_after_genuine_closing_replay(original_replay_v3, monkeypatch, target):
    case = original_replay_v3
    actual_replay = coordinate_join_owner.validate_source_span_entity_join_manifest_v2
    runtime = owner._owners()[4]
    actual_description, calls, closed = runtime.describe_runtime, [], []
    def describe(*args, **kwargs):
        result = actual_description(*args, **kwargs)
        return {**result, "authored_post_close_drift": True} if closed and target == "runtime" else result
    def replay(*args, **kwargs):
        result = actual_replay(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            closed.append(True)
            if target == "originals":
                metadata = case["originals"]["source_metadata_bytes"]
                metadata[next(iter(metadata))] += b"\n"
            elif target == "retained": args[0]["training_mask"] = True
            elif target == "callable":
                monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", lambda *a, **k: None)
        return result
    monkeypatch.setattr(runtime, "describe_runtime", describe)
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", replay)
    with pytest.raises(ValueError, match={"originals": "originals changed", "retained": "join changed",
            "callable": "callable changed", "runtime": "runtime description changed"}[target]):
        prepare_original_replay_v3(case)
    assert len(calls) == 2


@pytest.mark.parametrize("coordinate_join", [{
    "documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551",
                   "text": "Unselected Ω context. Clerk shall file report."}],
    "selected_indices": (1,), "compiler_rule": rule(),
}], ids=["supported-authored-source-span"], indirect=True)
@pytest.mark.parametrize("dimension", [0, 384], ids=["zero-latent", "declared-384d"])
def test_original_replay_v3_supported_target_preserves_source_custody_without_authority(
    original_replay_v3, dimension, monkeypatch,
):
    """Genuine mechanical support grants no legal, latent or consumer authority."""
    case = original_replay_v3
    original_join = wire(case["join"])
    original_inputs = deepcopy(case["originals"])
    target = rule()

    # Keep the actual audit and metadata owners; reject numerical entry points.
    for name in ("_torch", "_model", "build_checkpoint", "train_decoder", "load_checkpoint"):
        if hasattr(span, name):
            def forbidden(*args, _entrypoint=name, **kwargs):
                pytest.fail("mechanical coordinate audit invoked " + _entrypoint)
            monkeypatch.setattr(span, name, forbidden)

    request_raw, join_raw = original_replay_inputs_v3(case, latent_dimension=dimension)
    report = owner.prepare_source_span_target_eligibility_v3(request_raw, join_raw,
        expected_request_sha256=sha(request_raw), join_originals=case["originals"])
    assert owner.validate_source_span_target_eligibility_v3(report, request_raw, join_raw,
        expected_request_sha256=sha(request_raw),
        expected_report_sha256=owner.source_span_target_eligibility_sha256(report),
        join_originals=case["originals"]) == report
    assert report["schema"] == owner.SCHEMA_V3
    assert report["request"]["latent_dimension"] == dimension
    assert report["upstream_reexecution_performed"] is True
    assert report["checkpoint_status"] == "not_assessed"
    assert report["join_manifest_raw_utf8"].encode("utf-8") == join_raw == original_join
    assert wire(report).count(wire(report["join_manifest_raw_utf8"])) == 1
    assert case["originals"] == original_inputs
    assert wire(case["join"]) == original_join

    joined = json.loads(report["join_manifest_raw_utf8"])
    carrier = joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert carrier == case["join"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    raw_coordinates = carrier["report_raw_utf8"].encode("utf-8")
    coordinate_report = json.loads(raw_coordinates)
    assert coordinate_report == case["case"]["coordinate"]["report"]
    assert len(coordinate_report["spans"]) == 2
    assert "Unselected Ω context." in carrier["report_raw_utf8"]
    assert carrier["report_bytes"] == len(raw_coordinates)
    assert carrier["report_artifact_sha256"] == sha(raw_coordinates)
    assert carrier["report_sha256"] == report["source_coordinate_report_sha256"] == case["case"]["coordinate"]["pin"]
    assert "report_raw_utf8" not in report

    assert report["counts"]["physical_rows"] == report["counts"]["row_references"] == 1
    assert report["counts"]["output_occurrences"] == report["counts"]["mechanically_supported_outputs"] == 2
    assert report["counts"]["target_statuses"] == {"mechanically_supported": 2}
    assert report["counts"]["rows_without_outputs"] == 0
    assert report["duplicate_source_groups"] == []
    physical = report["physical_rows"][0]
    assert physical["physical_identity"]["row_ordinal"] == 0
    assert type(physical["source_coordinate_span_index"]) is int
    assert physical["source_coordinate_span_index"] == 1
    assert physical["source_text"] == "Clerk shall file report."
    assert physical["source_text_sha256"] == sha(physical["source_text"].encode("utf-8"))
    assert physical["source_unit_status"] == "unestablished"
    assert physical["meaning_unit_id"] is physical["selected_occurrence"] is None
    assert physical["output_occurrence_ordinals"] == [0, 1]
    assert "latent" not in physical
    for field in ("context_status", "source_review_status", "semantic_review_status", "exposure_status",
                  "split_status", "source_role_status", "applicability_status", "dependency_status",
                  "definition_binding_status"):
        assert physical[field] == "unresolved"
    for field in ("meaning_unit_mask", "source_binding_mask", "context_mask", "source_review_mask",
                  "source_role_mask", "applicability_mask", "dependency_mask", "definition_binding_mask"):
        assert type(physical[field]) is int and physical[field] == 0

    outputs = report["output_occurrences"]
    assert [(entry["route"], entry["ordinal"]) for entry in outputs] == [
        ("compiler.formal_outputs", 0), ("compiler.canonical_formal_outputs", 0)]
    assert len({entry["interpretation_cid"] for entry in outputs}) == 2
    reference = joined["row_references"][0]
    for row in [physical, report["row_references"][0], *outputs]:
        assert row["physical_identity_sha256"] == physical["physical_identity_sha256"]
        assert {key: row[key] for key in owner._COORDINATE_FIELDS} == {
            key: reference[key] for key in owner._COORDINATE_FIELDS}
        assert "report_raw_utf8" not in row
    for index, output in enumerate(outputs):
        assert output["target_status"] == "mechanically_supported"
        assert output["canonical_ir"] == {"rules": [target]}
        assert json.loads(output["formal_output"]["payload_json"]) == target
        assert output["formal_output"]["family"] == "typed_deontic"
        assert output["formal_output"]["format"] == "typed-deontic-rule/v1"
        assert output["producer_origin"] == output["formal_output"]["origin"] == "deterministic_compiler"
        assert output["formal_output"]["independent"] is True
        assert output["formal_output"]["target_conditioned"] is False
        assert output["decoder_audit"] == {"accepted_ids": [
            physical["physical_identity_sha256"] + ":" + str(index)], "rejected_rows": [], "all_supported": True}
        assert "unsupported_consumer_target_origin" in output["consumer_compatibility_blockers"]
        assert ("consumer_requires_zero_latent" in output["consumer_compatibility_blockers"]) == (dimension == 384)
        assert output["eligibility_blockers"]
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["entity_binding"] == "unavailable_semantic_companions_not_supplied"
    for field in ("consumer_eligible_rows", "source_units_established", "training_qualified_rows", "evaluation_gold_rows"):
        assert report["counts"][field] == 0
    assert_original_replay_unqualified_v3(report)



# Exact published original-input v2 controls; retained fixtures above use an
# explicitly named v1 route and cannot shadow this public request builder.
@pytest.fixture
def coordinate_eligibility(coordinate_join):
    case = coordinate_join
    raw = wire(case["request"])
    originals = {"request_raw": raw, "source_request_raw": case["source_raw"],
        "source_metadata_bytes": case["metadata"],
        "paired_inventory_request_raw": wire(case["paired_request"]),
        "paired_manifest_bytes": case["manifests"], "entity_info_raw": case["info_raw"],
        "expected_request_sha256": sha(raw), "legacy_join_inputs": None}
    return {"case": case, "join": prepare_coordinate_join(case), "originals": originals}


def coordinate_inputs(case, **changes):
    raw = wire(case["join"])
    request = {"schema": owner.REQUEST_SCHEMA_V2, "join_manifest_raw_sha256": sha(raw),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(case["join"]),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in case["join"]["physical_rows"]],
        "decoder_profile": owner.DECODER_PROFILE, "latent_dimension": 0,
        "join_originals_sha256": owner.source_span_target_join_originals_sha256(case["originals"]),
        "source_coordinate_report_sha256": case["case"]["coordinate"]["pin"], **changes}
    return wire(request), raw


def prepare_coordinate_eligibility(case, **changes):
    request, raw = coordinate_inputs(case, **changes)
    return owner.prepare_source_span_target_eligibility_v2(request, raw,
        expected_request_sha256=sha(request), join_originals=case["originals"])


def validate_coordinate_eligibility(case, report):
    request, raw = coordinate_inputs(case)
    value = json.loads(report) if type(report) is bytes else report
    return owner.validate_source_span_target_eligibility_v2(report, request, raw,
        expected_request_sha256=sha(request),
        expected_report_sha256=owner.source_span_target_eligibility_sha256(value),
        join_originals=case["originals"])


def assert_coordinate_unqualified(report):
    assert all(type(flag) is bool and flag is False for flag in report["authority"].values())
    for row in [report, *report["physical_rows"], *report["row_references"], *report["output_occurrences"]]:
        assert type(row["training_mask"]) is int and row["training_mask"] == 0
        assert type(row["evaluation_gold_mask"]) is int and row["evaluation_gold_mask"] == 0
    for row in report["physical_rows"] + report["output_occurrences"]:
        assert row["consumer_eligible"] is False
        assert all(type(mask) is int and mask == 0 for mask in row["field_masks"].values())


def test_coordinate_eligibility_genuine_roundtrip_preserves_unresolved_semantics(coordinate_eligibility):
    case = coordinate_eligibility
    report = prepare_coordinate_eligibility(case)
    assert validate_coordinate_eligibility(case, report) == report
    assert validate_coordinate_eligibility(case, wire(report)) == report
    assert report["schema"] == owner.SCHEMA_V2
    assert report["upstream_reexecution_performed"] is True
    assert report["runtime_description"]["runtime_version"] == owner.DECODER_PROFILE
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["entity_binding"] == "unavailable_semantic_companions_not_supplied"
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["consumer_eligible_rows"] == 0
    assert report["counts"]["output_occurrences"] > 0
    assert_coordinate_unqualified(report)


@pytest.mark.parametrize("damage", ["missing-profile", "old-retained-v2-wire", "public-v2-schema",
    "original-v3-wire", "strict-v1-schema", "public-profile", "boolean-profile", "originals-field"])
def test_retained_v1_refuses_old_or_implicit_wire_before_discovery(original_replay_v3, monkeypatch, damage):
    request, raw = retained_request_from_original_replay_v3(original_replay_v3)
    request = json.loads(request)
    if damage == "missing-profile":
        request.pop("source_compatibility_profile")
    elif damage == "old-retained-v2-wire":
        request["schema"] = owner.REQUEST_SCHEMA_V2
        request.pop("source_compatibility_profile")
    elif damage == "public-v2-schema":
        request["schema"] = owner.REQUEST_SCHEMA_V2
    elif damage == "original-v3-wire":
        request["schema"] = owner.REQUEST_SCHEMA_V3
        request["source_compatibility_profile"] = owner.ORIGINAL_REPLAY_PROFILE_V3
    elif damage == "strict-v1-schema":
        request["schema"] = owner.REQUEST_SCHEMA
    elif damage == "public-profile":
        request["source_compatibility_profile"] = owner.COORDINATE_PROFILE
    elif damage == "boolean-profile":
        request["source_compatibility_profile"] = True
    else:
        request["join_originals_sha256"] = owner.source_span_target_join_originals_sha256(original_replay_v3["originals"])
    request = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("unbound retained profile reached owner discovery"))
    with pytest.raises(ValueError):
        owner.prepare_retained_source_span_target_eligibility_v1(request, raw, expected_request_sha256=sha(request))


@pytest.mark.parametrize("operation", ["prepare", "validate"])
def test_published_original_v2_still_requires_join_originals(original_replay_v3, operation):
    request, raw = coordinate_inputs(original_replay_v3)
    with pytest.raises(TypeError, match="join_originals"):
        if operation == "prepare":
            owner.prepare_source_span_target_eligibility_v2(request, raw, expected_request_sha256=sha(request))
        else:
            owner.validate_source_span_target_eligibility_v2({}, request, raw,
                expected_request_sha256=sha(request), expected_report_sha256="0" * 64)


@pytest.mark.parametrize("target,offered", [
    ("retained-v1", "public-v2"), ("retained-v1", "original-v3"),
    ("public-v2", "retained-v1"), ("public-v2", "original-v3"),
    ("original-v3", "retained-v1"), ("original-v3", "public-v2"),
])
def test_resealed_reports_cannot_cross_retained_v1_public_v2_original_v3(original_replay_v3, target, offered):
    case = original_replay_v3
    retained_request, raw = retained_request_from_original_replay_v3(case)
    public_request, public_raw = coordinate_inputs(case)
    original_request, original_raw = original_replay_inputs_v3(case)
    assert raw == public_raw == original_raw
    reports = {
        "retained-v1": owner.prepare_retained_source_span_target_eligibility_v1(
            retained_request, raw, expected_request_sha256=sha(retained_request)),
        "public-v2": owner.prepare_source_span_target_eligibility_v2(
            public_request, raw, expected_request_sha256=sha(public_request), join_originals=case["originals"]),
        "original-v3": owner.prepare_source_span_target_eligibility_v3(
            original_request, raw, expected_request_sha256=sha(original_request), join_originals=case["originals"]),
    }
    assert {value["schema"] for value in reports.values()} == {
        owner.RETAINED_SCHEMA_V1, owner.SCHEMA_V2, owner.SCHEMA_V3}
    assert reports["retained-v1"]["source_compatibility_profile"] == owner.RETAINED_PROFILE_V1
    assert reports["public-v2"]["source_compatibility_profile"] == owner.COORDINATE_PROFILE
    assert reports["original-v3"]["source_compatibility_profile"] == owner.ORIGINAL_REPLAY_PROFILE_V3
    assert reports["retained-v1"]["upstream_reexecution_performed"] is False
    assert reports["public-v2"]["upstream_reexecution_performed"] is True
    assert reports["original-v3"]["upstream_reexecution_performed"] is True
    for value in reports.values():
        assert_coordinate_unqualified(value)
    value = reports[offered]
    pin = owner.source_span_target_eligibility_sha256(value)
    with pytest.raises(ValueError, match="differs from full"):
        if target == "retained-v1":
            owner.validate_retained_source_span_target_eligibility_v1(value, retained_request, raw,
                expected_request_sha256=sha(retained_request), expected_report_sha256=pin)
        elif target == "public-v2":
            owner.validate_source_span_target_eligibility_v2(value, public_request, raw,
                expected_request_sha256=sha(public_request), expected_report_sha256=pin, join_originals=case["originals"])
        else:
            owner.validate_source_span_target_eligibility_v3(value, original_request, raw,
                expected_request_sha256=sha(original_request), expected_report_sha256=pin, join_originals=case["originals"])


def test_coordinate_eligibility_retains_one_complete_join_and_exact_original_span_indices(coordinate_eligibility):
    case = coordinate_eligibility
    report = prepare_coordinate_eligibility(case)
    assert report["join_manifest_raw_utf8"].encode() == wire(case["join"])
    joined_report = json.loads(report["join_manifest_raw_utf8"])
    carrier = joined_report["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert len(json.loads(carrier["report_raw_utf8"])["spans"]) == 4
    assert carrier["report_sha256"] == report["source_coordinate_report_sha256"]
    assert [row["source_coordinate_span_index"] for row in report["physical_rows"]] == [1, 3]
    rows = report["physical_rows"]
    assert rows[0]["source_text"] == rows[1]["source_text"]
    assert rows[0]["physical_identity_sha256"] != rows[1]["physical_identity_sha256"]
    refs = {row["physical_identity_sha256"]: row for row in case["join"]["row_references"]}
    for row in rows + report["output_occurrences"]:
        original = refs[row["physical_identity_sha256"]]
        for key in owner._COORDINATE_FIELDS:
            assert row[key] == original[key]
        assert "report_raw_utf8" not in row
    assert "report_raw_utf8" not in report
    def retained_join_count(value):
        if type(value) is dict:
            return sum(retained_join_count(child) for child in value.values())
        if type(value) is list:
            return sum(retained_join_count(child) for child in value)
        return int(type(value) is str and value == report["join_manifest_raw_utf8"])
    # This checks the new report layer; the original join retains its own scope.
    assert retained_join_count(report) == 1


@pytest.mark.parametrize("dimension", [0, 384], ids=["zero", "native384"])
def test_coordinate_eligibility_dimension_never_dispatches_or_creates_latents(coordinate_eligibility, dimension):
    report = prepare_coordinate_eligibility(coordinate_eligibility, latent_dimension=dimension)
    assert report["request"]["latent_dimension"] == dimension
    assert not any("latent" in row for row in report["physical_rows"])
    assert_coordinate_unqualified(report)


def test_coordinate_eligibility_legacy_entrypoint_rejects_v2_even_with_legacy_request_shape(coordinate_eligibility):
    request_raw, raw = coordinate_inputs(coordinate_eligibility)
    request = json.loads(request_raw)
    request["schema"] = owner.REQUEST_SCHEMA
    request.pop("join_originals_sha256")
    request.pop("source_coordinate_report_sha256")
    request_raw = wire(request)
    with pytest.raises(ValueError, match="complete selected join"):
        owner.prepare_source_span_target_eligibility(request_raw, raw,
            expected_request_sha256=sha(request_raw))


def test_coordinate_eligibility_v2_refuses_legacy_join_before_discovery(coordinate_eligibility, monkeypatch):
    case = coordinate_eligibility
    case["join"] = joined(paired(canonical=[formal()]))
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("legacy join reached discovery"))
    with pytest.raises(ValueError, match="coordinate join v2"):
        prepare_coordinate_eligibility(case)


@pytest.mark.parametrize("damage", ["schema", "extra", "raw_pin", "canonical_pin", "originals_pin", "coordinate_pin"],
    ids=["schema", "extra", "raw-pin", "canonical-pin", "originals-pin", "coordinate-pin"])
def test_coordinate_eligibility_independent_closed_request_refuses(coordinate_eligibility, damage):
    changes = {"schema": {"schema": owner.REQUEST_SCHEMA}, "extra": {"reviewed": True},
        "raw_pin": {"join_manifest_raw_sha256": "0" * 64},
        "canonical_pin": {"join_manifest_sha256": "0" * 64},
        "originals_pin": {"join_originals_sha256": "0" * 64},
        "coordinate_pin": {"source_coordinate_report_sha256": "0" * 64}}[damage]
    with pytest.raises(ValueError):
        prepare_coordinate_eligibility(coordinate_eligibility, **changes)


@pytest.mark.parametrize("damage", ["omit", "reverse", "duplicate", "foreign"],
    ids=["omit", "reverse", "duplicate", "foreign"])
def test_coordinate_eligibility_requires_exact_physical_population(coordinate_eligibility, damage):
    case = coordinate_eligibility
    ids = [row["physical_identity_sha256"] for row in case["join"]["physical_rows"]]
    changed = {"omit": ids[:1], "reverse": ids[::-1], "duplicate": [ids[0], ids[0]],
        "foreign": [ids[0], "0" * 64]}[damage]
    with pytest.raises(ValueError):
        prepare_coordinate_eligibility(case, expected_physical_ids=changed)


@pytest.mark.parametrize("damage", ["index", "reference", "carrier", "physical", "row_count",
    "omit_row", "training_mask", "gold_mask", "crosswalk", "entity"],
    ids=["index", "reference", "carrier", "physical", "row-count", "omit-row", "training-mask",
         "gold-mask", "crosswalk", "entity"])
def test_coordinate_eligibility_rehashed_join_requires_genuine_original_replay(coordinate_eligibility, damage):
    report = coordinate_eligibility["join"]
    row = report["row_references"][0]
    if damage == "index": row["source_coordinate_span_index"] = 0
    elif damage == "reference": row["source_provenance_json"] = report["row_references"][1]["source_provenance_json"]
    elif damage == "carrier": report["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "physical": report["physical_rows"][0]["physical_identity_sha256"] = "0" * 64
    elif damage == "row_count": report["counts"]["physical_paired_rows"] += 1
    elif damage == "omit_row": report["paired_bundles"][0]["payload_intake"]["rows"].pop()
    elif damage == "training_mask": report["training_mask"] = True
    elif damage == "gold_mask": row["evaluation_gold_mask"] = 1
    elif damage == "crosswalk": row["current_source_release_correspondence"] = "verified"
    else: row["entity_binding"] = "verified"
    with pytest.raises(ValueError):
        prepare_coordinate_eligibility(coordinate_eligibility)


@pytest.mark.parametrize("damage", ["index", "index_bool", "reference", "join_bytes", "mask", "outputs"],
    ids=["index", "index-bool", "reference", "join-bytes", "mask", "outputs"])
def test_coordinate_eligibility_rehashed_report_requires_exact_regeneration(coordinate_eligibility, damage):
    report = prepare_coordinate_eligibility(coordinate_eligibility)
    if damage == "index": report["physical_rows"][0]["source_coordinate_span_index"] = 0
    elif damage == "index_bool": report["physical_rows"][0]["source_coordinate_span_index"] = True
    elif damage == "reference": report["output_occurrences"][0]["source_provenance_json"] = "{}"
    elif damage == "join_bytes": report["join_manifest_raw_utf8"] += " "
    elif damage == "mask": report["training_mask"] = 1
    else: report["output_occurrences"].pop()
    with pytest.raises(ValueError, match="full original-input replay"):
        validate_coordinate_eligibility(coordinate_eligibility, report)


def test_coordinate_eligibility_original_metadata_drift_is_caught_after_real_audit(coordinate_eligibility, monkeypatch):
    case = coordinate_eligibility
    actual, called = span.audit_examples, []
    def drift(rows):
        result = actual(rows)
        if not called:
            called.append(True)
            metadata = case["originals"]["source_metadata_bytes"]
            key = next(iter(metadata))
            metadata[key] += b"\n"
        return result
    monkeypatch.setattr(span, "audit_examples", drift)
    with pytest.raises(ValueError, match="originals changed"):
        prepare_coordinate_eligibility(case)
    assert called


@pytest.mark.parametrize("producer", ["eligibility", "join"], ids=["eligibility", "join"])
def test_coordinate_eligibility_stale_producer_refuses(coordinate_eligibility, monkeypatch, producer):
    module = owner if producer == "eligibility" else coordinate_join_owner
    monkeypatch.setattr(module, "_SELF_PIN", "0" * 64)
    with pytest.raises(ValueError, match="changed since import"):
        prepare_coordinate_eligibility(coordinate_eligibility)


def test_coordinate_eligibility_closing_replay_catches_physical_drift_after_real_audit(coordinate_eligibility, monkeypatch):
    case = coordinate_eligibility
    actual, called = span.audit_examples, []
    def drift(rows):
        result = actual(rows)
        if not called:
            called.append(True)
            table = case["join"]["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]
            root = Path(case["case"]["request"]["paired_bundles"][0]["repository_root"])
            target = root / table["path_in_repo"]
            target.write_bytes(target.read_bytes() + b"changed")
        return result
    monkeypatch.setattr(span, "audit_examples", drift)
    with pytest.raises(ValueError):
        prepare_coordinate_eligibility(case)
    assert called


def test_coordinate_eligibility_operational_error_still_attempts_genuine_closing_join(coordinate_eligibility, monkeypatch):
    actual_audit = span.audit_examples
    actual_replay = coordinate_join_owner.validate_source_span_entity_join_manifest_v2
    calls = []
    def replay(*args, **kwargs):
        calls.append(True)
        return actual_replay(*args, **kwargs)
    def fail(rows):
        actual_audit(rows)
        raise RuntimeError("authored failure after real decoder audit")
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v2", replay)
    monkeypatch.setattr(span, "audit_examples", fail)
    with pytest.raises(RuntimeError, match="authored failure"):
        prepare_coordinate_eligibility(coordinate_eligibility)
    assert len(calls) == 2


def test_coordinate_eligibility_primary_error_retains_secondary_original_custody_failure(coordinate_eligibility, monkeypatch):
    case = coordinate_eligibility
    actual = span.audit_examples
    def fail(rows):
        actual(rows)
        case["originals"]["source_metadata_bytes"]["extra"] = b"changed"
        raise RuntimeError("primary authored failure")
    monkeypatch.setattr(span, "audit_examples", fail)
    with pytest.raises(RuntimeError, match="primary authored failure") as caught:
        prepare_coordinate_eligibility(case)
    assert any("original inputs" in note for note in caught.value.__notes__)


def test_coordinate_eligibility_validator_checks_offered_report_after_real_replay(coordinate_eligibility, monkeypatch):
    case = coordinate_eligibility
    report = prepare_coordinate_eligibility(case)
    actual = span.audit_examples
    def mutate(rows):
        result = actual(rows)
        report["training_mask"] = True
        return result
    monkeypatch.setattr(span, "audit_examples", mutate)
    with pytest.raises(ValueError, match="offered coordinate eligibility report changed"):
        validate_coordinate_eligibility(case, report)


@pytest.mark.parametrize("damage", ["physical_rows", "metadata_count", "metadata_bytes"],
    ids=["physical-row-bound", "metadata-count-bound", "metadata-byte-bound"])
def test_coordinate_eligibility_bounds_refuse_before_discovery(coordinate_eligibility, monkeypatch, damage):
    case = coordinate_eligibility
    request, raw = coordinate_inputs(case)
    request = json.loads(request)
    if damage == "physical_rows": request["expected_physical_ids"] = ["a" * 64] * 65
    elif damage == "metadata_count": case["originals"]["source_metadata_bytes"] = {str(i): b"x" for i in range(17)}
    else: case["originals"]["source_metadata_bytes"] = {"large": b"x" * (owner.MAX_COORDINATE_ORIGINAL_BYTES + 1)}
    request = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("invalid bound reached discovery"))
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility_v2(request, raw,
            expected_request_sha256=sha(request), join_originals=case["originals"])


@pytest.mark.parametrize("coordinate_join", [{
    "documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551",
                   "text": "Unselected Ω context. Clerk shall file report."}],
    "selected_indices": (1,), "compiler_rule": rule(),
}], ids=["supported-authored-source-span"], indirect=True)
@pytest.mark.parametrize("dimension", [0, 384], ids=["zero-latent", "declared-384d"])
def test_coordinate_eligibility_supported_target_preserves_source_custody_without_authority(
    coordinate_eligibility, dimension, monkeypatch,
):
    """Genuine mechanical support grants no legal, latent or consumer authority."""
    case = coordinate_eligibility
    original_join = wire(case["join"])
    original_inputs = deepcopy(case["originals"])
    target = rule()

    # Keep the actual audit and metadata owners; reject numerical entry points.
    for name in ("_torch", "_model", "build_checkpoint", "train_decoder", "load_checkpoint"):
        if hasattr(span, name):
            def forbidden(*args, _entrypoint=name, **kwargs):
                pytest.fail("mechanical coordinate audit invoked " + _entrypoint)
            monkeypatch.setattr(span, name, forbidden)

    request_raw, join_raw = coordinate_inputs(case, latent_dimension=dimension)
    report = owner.prepare_source_span_target_eligibility_v2(request_raw, join_raw,
        expected_request_sha256=sha(request_raw), join_originals=case["originals"])
    assert owner.validate_source_span_target_eligibility_v2(report, request_raw, join_raw,
        expected_request_sha256=sha(request_raw),
        expected_report_sha256=owner.source_span_target_eligibility_sha256(report),
        join_originals=case["originals"]) == report
    assert report["schema"] == owner.SCHEMA_V2
    assert report["request"]["latent_dimension"] == dimension
    assert report["upstream_reexecution_performed"] is True
    assert report["checkpoint_status"] == "not_assessed"
    assert report["join_manifest_raw_utf8"].encode("utf-8") == join_raw == original_join
    assert wire(report).count(wire(report["join_manifest_raw_utf8"])) == 1
    assert case["originals"] == original_inputs
    assert wire(case["join"]) == original_join

    joined = json.loads(report["join_manifest_raw_utf8"])
    carrier = joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert carrier == case["join"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    raw_coordinates = carrier["report_raw_utf8"].encode("utf-8")
    coordinate_report = json.loads(raw_coordinates)
    assert coordinate_report == case["case"]["coordinate"]["report"]
    assert len(coordinate_report["spans"]) == 2
    assert "Unselected Ω context." in carrier["report_raw_utf8"]
    assert carrier["report_bytes"] == len(raw_coordinates)
    assert carrier["report_artifact_sha256"] == sha(raw_coordinates)
    assert carrier["report_sha256"] == report["source_coordinate_report_sha256"] == case["case"]["coordinate"]["pin"]
    assert "report_raw_utf8" not in report

    assert report["counts"]["physical_rows"] == report["counts"]["row_references"] == 1
    assert report["counts"]["output_occurrences"] == report["counts"]["mechanically_supported_outputs"] == 2
    assert report["counts"]["target_statuses"] == {"mechanically_supported": 2}
    assert report["counts"]["rows_without_outputs"] == 0
    assert report["duplicate_source_groups"] == []
    physical = report["physical_rows"][0]
    assert physical["physical_identity"]["row_ordinal"] == 0
    assert type(physical["source_coordinate_span_index"]) is int
    assert physical["source_coordinate_span_index"] == 1
    assert physical["source_text"] == "Clerk shall file report."
    assert physical["source_text_sha256"] == sha(physical["source_text"].encode("utf-8"))
    assert physical["source_unit_status"] == "unestablished"
    assert physical["meaning_unit_id"] is physical["selected_occurrence"] is None
    assert physical["output_occurrence_ordinals"] == [0, 1]
    assert "latent" not in physical
    for field in ("context_status", "source_review_status", "semantic_review_status", "exposure_status",
                  "split_status", "source_role_status", "applicability_status", "dependency_status",
                  "definition_binding_status"):
        assert physical[field] == "unresolved"
    for field in ("meaning_unit_mask", "source_binding_mask", "context_mask", "source_review_mask",
                  "source_role_mask", "applicability_mask", "dependency_mask", "definition_binding_mask"):
        assert type(physical[field]) is int and physical[field] == 0

    outputs = report["output_occurrences"]
    assert [(entry["route"], entry["ordinal"]) for entry in outputs] == [
        ("compiler.formal_outputs", 0), ("compiler.canonical_formal_outputs", 0)]
    assert len({entry["interpretation_cid"] for entry in outputs}) == 2
    reference = joined["row_references"][0]
    for row in [physical, report["row_references"][0], *outputs]:
        assert row["physical_identity_sha256"] == physical["physical_identity_sha256"]
        assert {key: row[key] for key in owner._COORDINATE_FIELDS} == {
            key: reference[key] for key in owner._COORDINATE_FIELDS}
        assert "report_raw_utf8" not in row
    for index, output in enumerate(outputs):
        assert output["target_status"] == "mechanically_supported"
        assert output["canonical_ir"] == {"rules": [target]}
        assert json.loads(output["formal_output"]["payload_json"]) == target
        assert output["formal_output"]["family"] == "typed_deontic"
        assert output["formal_output"]["format"] == "typed-deontic-rule/v1"
        assert output["producer_origin"] == output["formal_output"]["origin"] == "deterministic_compiler"
        assert output["formal_output"]["independent"] is True
        assert output["formal_output"]["target_conditioned"] is False
        assert output["decoder_audit"] == {"accepted_ids": [
            physical["physical_identity_sha256"] + ":" + str(index)], "rejected_rows": [], "all_supported": True}
        assert "unsupported_consumer_target_origin" in output["consumer_compatibility_blockers"]
        assert ("consumer_requires_zero_latent" in output["consumer_compatibility_blockers"]) == (dimension == 384)
        assert output["eligibility_blockers"]
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["entity_binding"] == "unavailable_semantic_companions_not_supplied"
    for field in ("consumer_eligible_rows", "source_units_established", "training_qualified_rows", "evaluation_gold_rows"):
        assert report["counts"][field] == 0
    assert_coordinate_unqualified(report)


# Explicit v4 consumes the qualified wire-coordinate join v3 without converting
# it into the older v2 carrier. Its five retained source metadata files and
# small authored coordinate tables are reused; no HF/model/corpus download.
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import (
    wire_coordinate_join, prepare_wire_join,
)

WIRE_ELIGIBILITY_PROFILE = "original-input-wire-coordinate-target-eligibility/v1"
WIRE_METADATA_PROFILE = "hf-default-parquet-envelope/v1"


@pytest.fixture
def wire_original_replay_v4(wire_coordinate_join):
    case = wire_coordinate_join
    raw = wire(case["request"])
    originals = {"request_raw": raw, "source_request_raw": case["source_raw"],
        "source_metadata_bytes": case["metadata"],
        "paired_inventory_request_raw": wire(case["paired_request"]),
        "paired_manifest_bytes": case["manifests"], "entity_info_raw": case["info_raw"],
        "expected_request_sha256": sha(raw), "legacy_join_inputs": None}
    return {"case": case, "join": prepare_wire_join(case), "originals": originals}


def wire_original_inputs_v4(case, **changes):
    raw = case.get("join_raw", wire(case["join"]))
    request = {"schema": "legal-source-span-target-eligibility-request/v4",
        "join_manifest_raw_sha256": sha(raw),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(case["join"]),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in case["join"]["physical_rows"]],
        "decoder_profile": owner.DECODER_PROFILE, "latent_dimension": 0,
        "join_originals_sha256": owner.source_span_target_join_originals_sha256(case["originals"]),
        "source_coordinate_report_sha256": case["case"]["coordinate"]["pin"],
        "source_compatibility_profile": WIRE_ELIGIBILITY_PROFILE,
        "metadata_profile": WIRE_METADATA_PROFILE, **changes}
    return wire(request), raw


def prepare_wire_eligibility_v4(case, **changes):
    request, raw = wire_original_inputs_v4(case, **changes)
    return owner.prepare_source_span_target_eligibility_v4(request, raw,
        expected_request_sha256=sha(request), join_originals=case["originals"])


def validate_wire_eligibility_v4(case, report, **changes):
    request, raw = wire_original_inputs_v4(case, **changes)
    value = json.loads(report) if type(report) is bytes else report
    return owner.validate_source_span_target_eligibility_v4(report, request, raw,
        expected_request_sha256=sha(request), expected_report_sha256=owner.source_span_target_eligibility_sha256(value),
        join_originals=case["originals"])


def assert_wire_eligibility_unqualified_v4(report):
    assert report["schema"] == "legal-source-span-target-eligibility/v4"
    assert report["source_compatibility_profile"] == WIRE_ELIGIBILITY_PROFILE
    assert report["metadata_profile"] == WIRE_METADATA_PROFILE
    assert report["checkpoint_status"] == "not_assessed"
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["entity_binding"] == "unavailable_semantic_companions_not_supplied"
    assert_original_replay_unqualified_v3(report)
    for row in report["physical_rows"]:
        assert row["meaning_unit_id"] is row["selected_occurrence"] is None
        assert row["source_unit_status"] == "unestablished"
        assert row["context_status"] == row["source_review_status"] == row["semantic_review_status"] == "unresolved"
        assert type(row["context_mask"]) is int and row["context_mask"] == 0
        assert "latent" not in row


@pytest.mark.parametrize("dimension", [0, 384], ids=["zero-latent", "declared-384d"])
def test_wire_v4_genuine_opening_closing_join_replay_retains_full_unreviewed_population(
    wire_original_replay_v4, monkeypatch, dimension,
):
    case = wire_original_replay_v4; before = deepcopy(case["originals"]), wire(case["join"])
    genuine = coordinate_join_owner.validate_source_span_entity_join_manifest_v3; calls = []
    def observed(*args, **kwargs):
        result = genuine(*args, **kwargs); calls.append(True)
        assert kwargs["expected_report_sha256"] == coordinate_join_owner.source_span_entity_join_manifest_sha256(case["join"])
        return result
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v3", observed)
    report = prepare_wire_eligibility_v4(case, latent_dimension=dimension)
    assert calls == [True, True]
    assert report["request"]["latent_dimension"] == dimension
    assert report["upstream_reexecution_performed"] is True
    assert report["selection_scope"] == "fully_replayed_wire_coordinate_join_original_inputs"
    assert report["upstream_reexecution_requirement"] == "opening_and_closing_public_wire_coordinate_join_replay"
    assert report["coordinate_validation_scope"] == "complete_original_public_wire_coordinate_join_operation"
    assert report["join_manifest_raw_utf8"].encode() == before[1]
    assert wire(report).count(wire(report["join_manifest_raw_utf8"])) == 1
    assert report["source_metadata_intake_sha256"] == case["join"]["source_metadata_intake_sha256"]
    assert report["counts"]["physical_rows"] == report["counts"]["row_references"] == 2
    assert report["counts"]["output_occurrences"] == 4
    assert len(report["duplicate_source_groups"]) == 1
    assert len(set(report["duplicate_source_groups"][0]["physical_ids"])) == 2
    rows = report["physical_rows"]
    assert rows[0]["source_text"] == rows[1]["source_text"]
    assert [row["source_coordinate_span_index"] for row in rows] == [1, 3]
    assert [row["source_provenance_json"] for row in rows] == case["case"]["coordinate"]["references"]
    joined = json.loads(report["join_manifest_raw_utf8"])
    carrier = joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert json.loads(carrier["report_raw_utf8"]) == case["case"]["coordinate"]["report"]
    assert len(json.loads(carrier["report_raw_utf8"])["spans"]) == 4
    assert report["source_coordinates_reference"]["container"] == "join_manifest_raw_utf8"
    assert report["source_coordinates_reference"]["json_pointer"] == "/paired_bundles/0/payload_intake/source_coordinates"
    assert report["source_coordinates_reference"]["report_sha256"] == carrier["report_sha256"]
    assert "report_raw_utf8" not in report
    assert all("report_raw_utf8" not in row for row in report["physical_rows"] + report["output_occurrences"])
    assert joined["source_metadata_intake"]["source_identity"]["aliases_mapped"] is False
    assert joined["source_metadata_intake"]["metadata_validation"]["table_rows_read"] is False
    assert case["originals"] == before[0] and wire(case["join"]) == before[1]
    assert_wire_eligibility_unqualified_v4(report)
    calls.clear()
    assert validate_wire_eligibility_v4(case, report, latent_dimension=dimension) == report
    assert calls == [True, True]


def test_wire_v4_raw_join_transport_and_canonical_identity_remain_separately_pinned(wire_original_replay_v4):
    case = wire_original_replay_v4
    case["join_raw"] = (json.dumps(case["join"], ensure_ascii=False, indent=2) + "\n").encode()
    request_raw, raw = wire_original_inputs_v4(case)
    request = json.loads(request_raw)
    assert request["join_manifest_raw_sha256"] != request["join_manifest_sha256"]
    report = prepare_wire_eligibility_v4(case)
    assert report["join_manifest_raw_utf8"].encode() == raw
    assert report["join_manifest_raw_sha256"] == sha(raw)
    assert report["source_coordinates_reference"]["join_manifest_raw_sha256"] == sha(raw)
    assert validate_wire_eligibility_v4(case, wire(report)) == report
    assert_wire_eligibility_unqualified_v4(report)


@pytest.mark.parametrize("coordinate_join", [{
    "documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551",
                   "text": "Unselected Ω context. Clerk shall file report."}],
    "selected_indices": (1,), "compiler_rule": rule(),
}], ids=["supported-authored-source-span"], indirect=True)
@pytest.mark.parametrize("dimension", [0, 384], ids=["zero-latent", "declared-384d"])
def test_wire_v4_supported_typed_target_does_not_create_inference_or_learning_authority(
    wire_original_replay_v4, monkeypatch, dimension,
):
    case = wire_original_replay_v4
    for name in ("_torch", "_model", "build_checkpoint", "train_decoder", "load_checkpoint"):
        if hasattr(span, name):
            def forbidden(*args, _entrypoint=name, **kwargs):
                pytest.fail("wire metadata eligibility invoked numerical entrypoint " + _entrypoint)
            monkeypatch.setattr(span, name, forbidden)
    report = prepare_wire_eligibility_v4(case, latent_dimension=dimension)
    assert report["counts"]["physical_rows"] == 1
    assert report["counts"]["output_occurrences"] == report["counts"]["mechanically_supported_outputs"] == 2
    assert report["counts"]["target_statuses"] == {"mechanically_supported": 2}
    assert report["physical_rows"][0]["source_text"] == "Clerk shall file report."
    assert report["physical_rows"][0]["source_coordinate_span_index"] == 1
    assert [(entry["route"], entry["ordinal"]) for entry in report["output_occurrences"]] == [
        ("compiler.formal_outputs", 0), ("compiler.canonical_formal_outputs", 0)]
    for output in report["output_occurrences"]:
        assert output["canonical_ir"] == {"rules": [rule()]}
        assert output["decoder_audit"]["all_supported"] is True
        assert "unsupported_consumer_target_origin" in output["consumer_compatibility_blockers"]
        assert ("consumer_requires_zero_latent" in output["consumer_compatibility_blockers"]) == (dimension == 384)
        assert output["consumer_eligible"] is False and output["eligibility_blockers"]
    joined = json.loads(report["join_manifest_raw_utf8"])
    assert "Unselected Ω context." in joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"]
    assert validate_wire_eligibility_v4(case, report, latent_dimension=dimension) == report
    assert_wire_eligibility_unqualified_v4(report)


@pytest.mark.parametrize("old_profile", ["legacy", "retained", "public_v2", "original_v3"])
def test_wire_v4_join_cannot_cross_any_of_the_four_old_eligibility_domains(wire_original_replay_v4, monkeypatch, old_profile):
    case = wire_original_replay_v4; request_raw, raw = wire_original_inputs_v4(case)
    request = json.loads(request_raw); request.pop("metadata_profile")
    if old_profile == "legacy":
        request["schema"] = owner.REQUEST_SCHEMA
        for field in ("join_originals_sha256", "source_coordinate_report_sha256", "source_compatibility_profile"): request.pop(field)
        operation = owner.prepare_source_span_target_eligibility; kwargs = {}
    elif old_profile == "retained":
        request["schema"] = owner.RETAINED_REQUEST_SCHEMA_V1; request.pop("join_originals_sha256")
        request["source_compatibility_profile"] = owner.RETAINED_PROFILE_V1
        operation = owner.prepare_retained_source_span_target_eligibility_v1; kwargs = {}
    elif old_profile == "public_v2":
        request["schema"] = owner.REQUEST_SCHEMA_V2; request.pop("source_compatibility_profile")
        operation = owner.prepare_source_span_target_eligibility_v2; kwargs = {"join_originals": case["originals"]}
    else:
        request["schema"] = owner.REQUEST_SCHEMA_V3
        request["source_compatibility_profile"] = owner.ORIGINAL_REPLAY_PROFILE_V3
        operation = owner.prepare_source_span_target_eligibility_v3; kwargs = {"join_originals": case["originals"]}
    request_raw = wire(request)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("old profile discovered owners for a wire-v3 join"))
    with pytest.raises(ValueError): operation(request_raw, raw, expected_request_sha256=sha(request_raw), **kwargs)


@pytest.mark.parametrize("old_join_schema", ["legal-source-span-entity-join-manifest/v1", "legal-source-span-entity-join-manifest/v2"])
def test_wire_v4_never_relabels_an_older_join_as_wire_transport(wire_original_replay_v4, monkeypatch, old_join_schema):
    case = wire_original_replay_v4; case["join"]["schema"] = old_join_schema
    case["join"]["source_compatibility_profile"] = "paired-coordinate-three-cache-join/v1"
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("old join reached wire eligibility owners"))
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case)


@pytest.mark.parametrize("damage", ["missing_metadata", "boolean_metadata", "foreign_metadata",
                                    "missing_compatibility", "boolean_compatibility", "older_compatibility"])
def test_wire_v4_requires_both_explicit_closed_profile_declarations(wire_original_replay_v4, monkeypatch, damage):
    case = wire_original_replay_v4; request, raw = wire_original_inputs_v4(case); value = json.loads(request)
    if damage == "missing_metadata": value.pop("metadata_profile")
    elif damage == "boolean_metadata": value["metadata_profile"] = True
    elif damage == "foreign_metadata": value["metadata_profile"] = "foreign-wire/v1"
    elif damage == "missing_compatibility": value.pop("source_compatibility_profile")
    elif damage == "boolean_compatibility": value["source_compatibility_profile"] = False
    else: value["source_compatibility_profile"] = owner.ORIGINAL_REPLAY_PROFILE_V3
    request = wire(value)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("malformed profile reached discovery"))
    with pytest.raises(ValueError):
        owner.prepare_source_span_target_eligibility_v4(request, raw, expected_request_sha256=sha(request), join_originals=case["originals"])


@pytest.mark.parametrize("pin", ["join_manifest_raw_sha256", "join_manifest_sha256", "join_originals_sha256", "source_coordinate_report_sha256"])
def test_wire_v4_raw_canonical_originals_and_coordinate_pins_are_independent(wire_original_replay_v4, pin):
    case = wire_original_replay_v4
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case, **{pin: "0" * 64})


@pytest.mark.parametrize("damage", ["missing", "reverse", "duplicate", "foreign"])
def test_wire_v4_requires_complete_ordered_physical_population(wire_original_replay_v4, damage):
    case = wire_original_replay_v4; ids = [row["physical_identity_sha256"] for row in case["join"]["physical_rows"]]
    if damage == "missing": ids.pop()
    elif damage == "reverse": ids.reverse()
    elif damage == "duplicate": ids[1] = ids[0]
    else: ids[0] = "0" * 64
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case, expected_physical_ids=ids)


@pytest.mark.parametrize("damage", ["intake_commitment", "metadata_alias", "coordinate_carrier", "source_index", "authority"])
def test_wire_v4_resealed_join_requires_genuine_original_wire_replay(wire_original_replay_v4, damage):
    case = wire_original_replay_v4; joined = case["join"]
    if damage == "intake_commitment": joined["source_metadata_intake_sha256"] = "0" * 64
    elif damage == "metadata_alias": joined["source_metadata_intake"]["source_identity"]["aliases_mapped"] = True
    elif damage == "coordinate_carrier": joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"] = "{}"
    elif damage == "source_index": joined["row_references"][0]["source_coordinate_span_index"] = 0
    else: joined["authority"]["training_qualified"] = True
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case)


@pytest.mark.parametrize("damage", ["metadata_commitment", "coordinate_reference", "physical_order", "field_mask", "crosswalk", "context"])
def test_wire_v4_resealed_eligibility_still_requires_exact_regeneration(wire_original_replay_v4, damage):
    case = wire_original_replay_v4; report = prepare_wire_eligibility_v4(case)
    if damage == "metadata_commitment": report["source_metadata_intake_sha256"] = "0" * 64
    elif damage == "coordinate_reference": report["source_coordinates_reference"]["report_bytes"] += 1
    elif damage == "physical_order": report["physical_rows"].reverse()
    elif damage == "field_mask": report["output_occurrences"][0]["field_masks"]["actor"] = 1
    elif damage == "crosswalk": report["current_source_release_correspondence"] = "invented_verified_crosswalk"
    else: report["physical_rows"][0]["context_status"] = "inference_authorized"
    with pytest.raises(ValueError): validate_wire_eligibility_v4(case, report)


def test_wire_v4_original_metadata_drift_after_real_audit_refuses(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; genuine = span.audit_examples; called = []
    def observed(*args, **kwargs):
        result = genuine(*args, **kwargs); called.append(True)
        case["originals"]["source_metadata_bytes"]["README.md"] += b"late original metadata drift"; return result
    monkeypatch.setattr(span, "audit_examples", observed)
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case)
    assert called


def test_wire_v4_closing_join_replay_catches_physical_table_drift(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; genuine = span.audit_examples; called = []
    def observed(*args, **kwargs):
        result = genuine(*args, **kwargs); called.append(True)
        entry = case["case"]["coordinate"]["written"]["artifacts"]
        path = Path(case["case"]["coordinate"]["request"]["repository_root"]) / entry["path_in_repo"]
        path.write_bytes(path.read_bytes() + b"late wire table drift"); return result
    monkeypatch.setattr(span, "audit_examples", observed)
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case)
    assert called


def test_wire_v4_join_callable_replacement_after_real_audit_refuses(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; genuine = span.audit_examples; called = []
    def observed(*args, **kwargs):
        result = genuine(*args, **kwargs); called.append(True)
        monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v3", lambda *a, **k: None)
        return result
    monkeypatch.setattr(span, "audit_examples", observed)
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case)
    assert called


def test_wire_v4_primary_audit_error_preserves_genuine_closing_custody_failure(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; genuine = span.audit_examples; actual_join = coordinate_join_owner.validate_source_span_entity_join_manifest_v3
    calls = []; sentinel = RuntimeError("negative wire eligibility audit boundary")
    def join_observed(*args, **kwargs):
        calls.append(True); return actual_join(*args, **kwargs)
    def audit_observed(*args, **kwargs):
        genuine(*args, **kwargs)
        case["originals"]["source_metadata_bytes"]["README.md"] += b"negative closing source drift"
        raise sentinel
    monkeypatch.setattr(coordinate_join_owner, "validate_source_span_entity_join_manifest_v3", join_observed)
    monkeypatch.setattr(span, "audit_examples", audit_observed)
    with pytest.raises(RuntimeError) as caught: prepare_wire_eligibility_v4(case)
    assert caught.value is sentinel and len(calls) == 2
    assert any("original inputs" in note and "originals changed during operation" in note
               for note in getattr(caught.value, "__notes__", []))


def test_wire_v4_validator_retains_offered_report_after_real_audit(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; report = prepare_wire_eligibility_v4(case)
    genuine = span.audit_examples; called = []
    def observed(*args, **kwargs):
        result = genuine(*args, **kwargs); called.append(True)
        report["training_mask"] = True; return result
    monkeypatch.setattr(span, "audit_examples", observed)
    with pytest.raises(ValueError): validate_wire_eligibility_v4(case, report)
    assert called


def test_wire_v4_final_serialization_keeps_original_metadata_custody(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; genuine = owner._wire; reached = []
    def observed(value, *args, **kwargs):
        raw = genuine(value, *args, **kwargs)
        if type(value) is dict and value.get("schema") == "legal-source-span-target-eligibility/v4":
            reached.append(True); case["originals"]["source_metadata_bytes"]["README.md"] += b"final wire metadata drift"
        return raw
    monkeypatch.setattr(owner, "_wire", observed)
    with pytest.raises(ValueError): prepare_wire_eligibility_v4(case)
    assert reached


def test_wire_v4_outer_validator_state_cannot_nominate_paths_after_genuine_inner_replay(wire_original_replay_v4, monkeypatch):
    case = wire_original_replay_v4; report = prepare_wire_eligibility_v4(case)
    genuine_preflight = owner._replay_preflight_v3
    genuine_prepare = owner._prepare_original_coordinate_eligibility
    genuine_files = coordinate_join_owner._coordinate_file_witnesses
    outer, changed, file_calls = [], [], []
    sentinel = "unselected/outer-validator-state.parquet"
    def observed_preflight(*args, **kwargs):
        result = genuine_preflight(*args, **kwargs)
        if kwargs.get("wire_source") is True: outer.append(result)
        return result
    def observed_prepare(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        assert kwargs.get("wire_source") is True and len(outer) >= 2
        # Change only the validator's outer parsed copy after the complete,
        # genuine inner operation has closed both upstream join replays.
        outer[0][1]["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]["path_in_repo"] = sentinel
        changed.append(True)
        return result
    def observed_files(location, selected):
        assert sentinel not in [entry["path_in_repo"] for entry in selected["manifest"]["tables"].values()], \
            "mutated outer validator state nominated an unselected file path"
        file_calls.append(True)
        return genuine_files(location, selected)
    monkeypatch.setattr(owner, "_replay_preflight_v3", observed_preflight)
    monkeypatch.setattr(owner, "_prepare_original_coordinate_eligibility", observed_prepare)
    monkeypatch.setattr(coordinate_join_owner, "_coordinate_file_witnesses", observed_files)
    with pytest.raises(ValueError): validate_wire_eligibility_v4(case, report)
    assert changed == [True] and file_calls


