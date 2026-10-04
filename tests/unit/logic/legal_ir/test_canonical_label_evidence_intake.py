"""Synthetic evidence exercises integrity; no person or meaning is verified."""

import builtins
import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_binding_review as recorder
from ipfs_datasets_py.logic.legal_ir import canonical_label_evidence_intake as subject

MASKS = (
    "weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision",
    "proof_supervision", "fidelity_evaluation",
)
AUTHORITY = (
    "qualified", "accepted", "production_admitted", "independent_fidelity_available",
    "source_fidelity_established", "source_semantics_verified", "proof_authority",
    "independent_semantic_review_completed", "reviewer_identity_authenticated",
    "reviewer_independence_authenticated", "source_author_independence_authenticated",
    "reviewer_identity_attestations_created", "reviewer_attestations_created",
    "semantic_gold_created", "actual_training_or_evaluation_admission",
)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def binding(value):
    # File metadata is declared, not observed by this dictionary API. Pretty
    # serialization deliberately distinguishes file and canonical identities.
    file_bytes = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return {"content_sha256": digest(value), "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
            "file_bytes": len(file_bytes)}


def packet(count=2):
    items = []
    for index in range(count):
        source = f"Synthetic intake fixture {index}: the clerk must retain the filing."
        context = {"role": "none_required", "text": "", "bindings": {}, "sha256": text_sha("")}
        input_sha = digest({"source_text": source, "context": context})
        identity = "binding-review-item-" + hashlib.sha256(
            b"authored-binding-review-v1\0" + bytes.fromhex(input_sha)).hexdigest()[:24]
        items.append({"item_id": identity, "source_text": source, "source_sha256": text_sha(source),
                      "input_sha256": input_sha, "context": context,
                      "annotation": dict.fromkeys(recorder.ANNOTATION_FIELDS)})
    instructions = {key: "Synthetic fixture only; no human review occurred." for key in (
        "task", "context", "normative_rules", "qualifier_scope", "blank_annotations", "identity", "provenance",
    )}
    return {"schema": "symbol-binding-source-reviewer/v1", "instructions": instructions,
            "items": sorted(items, key=lambda row: row["item_id"])}


def rule():
    return {"modality": "O", "actor": "fixture_actor", "action": "retain", "object": "filing",
            "conditions": ["condition_b", "condition_a", "condition_b"],
            "exceptions": ["exception"], "temporal": ["opaque_time"]}


def annotation(reviewer="synthetic-reviewer-A"):
    return {"interpretation_status": "normative", "ambiguity": False, "unsupported_meaning": False,
            "normative_rules": [rule()], "freeform_qualifier_scope": "Declared synthetic scope only.",
            "notes": "Synthetic declaration, not an actual review.", "reviewer_id": reviewer,
            "reviewed_at_utc": "2026-10-04T04:00:00Z"}


def payload(original, reviewer="synthetic-reviewer-A", *, indices=(0,), complete=True):
    value = copy.deepcopy(original)
    value["items"] = [value["items"][index] for index in indices]
    if complete:
        for item in value["items"]:
            item["annotation"] = annotation(reviewer)
    return value


def declaration(item, entry):
    return {"submission_binding": {"submission_index": entry["submission_index"],
                                   "submission_sha256": entry["submission_sha256"]},
            "item_id": item["item_id"], "annotation_content_sha256": digest(entry["annotation"]),
            "meaning_signature_sha256": entry["meaning_signature_sha256"] or "0" * 64}


def provenance(item, ref, principal, *, role="reviewer"):
    return {"process_id": "synthetic-process", "responsible_organizer": "synthetic-organizer",
            "principal_id": principal, "role": role, "identity_method": "Unverified synthetic declaration",
            "author_model_relationship": "Synthetic fixture; relationship not authenticated",
            "independence_assessment": "Declared only; not verified",
            "inputs_exposed": {"source_input_sha256": item["input_sha256"],
                               "candidate_or_reference_exposed": False, "organizer_metadata_exposed": False,
                               "other_exposure": ""},
            "annotation_binding": copy.deepcopy(ref), "assessed_at_utc": "2026-10-04T04:00:00Z",
            "rationale": "Synthetic provenance association only", "limitations": "No real identity evidence"}


def interpretation(identity="synthetic-interpretation"):
    return {"interpretation_id": identity, "family": "deontic", "profile": "synthetic-unqualified-profile/v1",
            "ordered_rules": [rule()], "qualifier_scope": "Synthetic occurrence and attachment declaration",
            "coverage_assessment": {"status": "complete", "omitted_meaning": [],
                                    "rationale": "Declared coverage only, not independently checked"},
            "unrepresented_meaning": [], "formal_target_binding": None, "derivation_refs": []}


def seal(value):
    value["content_sha256"] = digest({key: entry for key, entry in value.items() if key != "content_sha256"})
    return value


def case(*, count=2, submissions=None, indices=(0,), empty=False):
    original = packet(count)
    if submissions is None:
        submissions = [] if empty else [payload(original), payload(original, "synthetic-reviewer-B")]
    receipt = recorder.record_reviews(original, copy.deepcopy(submissions), expected_packet_sha256=digest(original))
    expected = {"packet": binding(original), "receipt": binding(receipt),
                "submissions": [binding(value) for value in submissions],
                "organizer": None, "process": None, "cohort": None}
    selected = None
    rows = []
    if not empty:
        expected.update(organizer=binding({"organizer_id": "synthetic-organizer"}),
                        process=binding({"process_id": "synthetic-process", "organizer_id": "synthetic-organizer"}),
                        cohort=binding({"scope": "synthetic cohort only"}))
        selected = {"process_id": "synthetic-process", "organizer_id": "synthetic-organizer",
                    "content_sha256": expected["process"]["content_sha256"]}
        by_id = {row["item_id"]: row for row in receipt["items"]}
        for index in indices:
            item = by_id[original["items"][index]["item_id"]]
            refs = [declaration(item, entry) for entry in item["received_declarations"]]
            rows.append({"item_id": item["item_id"], "source_sha256": item["source_sha256"],
                         "input_sha256": item["input_sha256"], "declaration_refs": refs,
                         "provenance_refs": [provenance(item, ref, entry["annotation"]["reviewer_id"])
                                             for ref, entry in zip(refs, item["received_declarations"], strict=True)],
                         "interpretations": [interpretation()], "adjudication_ref": None})
    package = seal({"schema": "canonical-binding-label-evidence/v1", "packet_binding": expected["packet"],
                    "recording_binding": expected["receipt"], "organizer_binding": expected["organizer"],
                    "review_process_binding": expected["process"], "cohort_policy_binding": expected["cohort"],
                    "supersedes_package_sha256": None, "items": rows})
    return {"packet": original, "recording": {"receipt": receipt, "reviewed_payloads": copy.deepcopy(submissions)},
            "package": copy.deepcopy(package), "expected_bindings": copy.deepcopy(expected),
            "selected_process_binding": selected}


def intake(value):
    return subject.validate_label_evidence_intake(**value)


def refresh_recording(value):
    recording = value["recording"]
    recording["receipt"] = recorder.record_reviews(value["packet"], recording["reviewed_payloads"],
                                                   expected_packet_sha256=digest(value["packet"]))
    value["expected_bindings"]["receipt"] = binding(recording["receipt"])
    value["expected_bindings"]["submissions"] = [binding(entry) for entry in recording["reviewed_payloads"]]
    value["package"]["recording_binding"] = copy.deepcopy(value["expected_bindings"]["receipt"])


def add_adjudication(value, *, alternatives=False):
    row = value["package"]["items"][0]
    if alternatives:
        row["interpretations"].append(interpretation("synthetic-alternative"))
    principal = "synthetic-adjudicator"
    row["provenance_refs"].append(provenance(row, row["declaration_refs"][0], principal, role="adjudicator"))
    identifiers = [entry["interpretation_id"] for entry in row["interpretations"]]
    row["adjudication_ref"] = {
        "principal_id": principal, "declaration_refs": copy.deepcopy(row["declaration_refs"]),
        "interpretation_refs": identifiers, "decision": "accept_alternatives" if alternatives else "accept_unique",
        "accepted_interpretation_ids": list(identifiers), "unresolved_scope": [],
        "rationale": "Synthetic declared adjudication; no verification occurred",
        "adjudicated_at_utc": "2026-10-04T04:01:00Z", "provenance_ref": len(row["provenance_refs"]) - 1,
    }
    seal(value["package"])


def assert_unverified(receipt):
    for value in (receipt, *receipt["items"]):
        assert value["masks"] == dict.fromkeys(MASKS, 0)
        assert all(type(entry) is int and entry == 0 for entry in value["masks"].values())
        assert all(value[field] is False for field in AUTHORITY)
        assert value["verification_status"] == value["admission_status"] == "pending"
    for field in ("formal_targets_admitted", "human_reviews_authenticated", "independent_reviews_authenticated",
                  "model_calls", "provider_calls", "encoder_calls", "prover_calls"):
        assert type(receipt[field]) is int and receipt[field] == 0
    for field in ("file_bindings_verified", "metadata_content_verified", "semantic_profile_validated",
                  "training_executed", "automatic_adjudication", "submissions_created"):
        assert receipt[field] is False


def test_empty_64_item_readiness_is_pending_without_reviews_or_process():
    value = case(count=64, empty=True)
    before = copy.deepcopy(value)
    receipt = intake(value)
    assert receipt["item_count"] == 64
    assert receipt["declared_package_item_count"] == 0
    assert receipt["status"] == "pending"
    assert all(row["evidence_status"] == "pending" and row["declared_evidence"] is None for row in receipt["items"])
    assert_unverified(receipt)
    assert value == before


@pytest.mark.parametrize("alternatives", [False, True])
def test_complete_declarations_and_declared_adjudication_never_authenticate_or_admit(alternatives):
    value = case()
    add_adjudication(value, alternatives=alternatives)
    receipt = intake(value)
    assert receipt["status"] == "declared_evidence_intake_only"
    assert receipt["declared_package_item_count"] == 1
    assert receipt["items"][0]["recording_status"] == "agreed_multiple_reviews"
    assert receipt["items"][0]["declared_evidence"] == value["package"]["items"][0]
    assert receipt["items"][0]["independent_adjudication_completed"] is False
    assert receipt["items"][0]["external_adjudication_status"] == "pending"
    assert_unverified(receipt)


def test_canonical_and_file_identities_are_distinct_and_file_metadata_is_not_verified():
    value = case()
    for field in ("packet", "receipt", "organizer", "process", "cohort"):
        assert value["expected_bindings"][field]["content_sha256"] != value["expected_bindings"][field]["file_sha256"]
    receipt = intake(value)
    assert receipt["expected_bindings"] == value["expected_bindings"]
    assert receipt["file_bindings_verified"] is receipt["metadata_content_verified"] is False


def test_original_submission_order_is_bound_even_when_every_content_pin_is_valid():
    value = case()
    value["recording"]["reviewed_payloads"].reverse()
    value["expected_bindings"]["submissions"].reverse()
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


def test_payload_subset_order_is_preserved_without_reordering_or_normalizing_annotations():
    original = packet(3)
    value = case(count=3, submissions=[payload(original, indices=(2, 0))], indices=(2, 0))
    before = copy.deepcopy(value)
    receipt = intake(value)
    assert receipt["declared_package_item_count"] == 2
    assert value == before
    declared = next(row for row in receipt["items"] if row["declared_evidence"] is not None)
    qualifiers = declared["declared_evidence"]["interpretations"][0]["ordered_rules"][0]["conditions"]
    assert qualifiers == ["condition_b", "condition_a", "condition_b"]


@pytest.mark.parametrize("rewrite_item_id", [False, True])
def test_valid_hash_cross_item_submission_cannot_supply_another_items_declaration(rewrite_item_id):
    original = packet()
    value = case(submissions=[payload(original, indices=(0,)), payload(original, indices=(1,))])
    first, second = value["recording"]["receipt"]["items"]
    assert first["received_declarations"][0]["annotation"] == second["received_declarations"][0]["annotation"]
    foreign = declaration(second, second["received_declarations"][0])
    if rewrite_item_id:
        foreign["item_id"] = first["item_id"]
    row = value["package"]["items"][0]
    row["declaration_refs"] = [foreign]
    row["provenance_refs"][0]["annotation_binding"] = copy.deepcopy(foreign)
    seal(value["package"])
    with pytest.raises(ValueError, match="another item|not recorded"):
        intake(value)


def test_stale_full_annotation_is_rejected_when_meaning_signature_is_unchanged():
    value = case()
    previous = value["recording"]["receipt"]["items"][0]["received_declarations"][0]
    value["recording"]["reviewed_payloads"][0]["items"][0]["annotation"]["notes"] += " Revised synthetic note."
    refresh_recording(value)
    current = value["recording"]["receipt"]["items"][0]["received_declarations"][0]
    assert current["meaning_signature_sha256"] == previous["meaning_signature_sha256"]
    assert digest(current["annotation"]) != digest(previous["annotation"])
    row = value["package"]["items"][0]
    for ref in (row["declaration_refs"][0], row["provenance_refs"][0]["annotation_binding"]):
        ref["submission_binding"]["submission_sha256"] = current["submission_sha256"]
    seal(value["package"])
    with pytest.raises(ValueError, match="full annotation"):
        intake(value)


@pytest.mark.parametrize("fault", ["old_package", "old_receipt", "old_declaration", "wrong_submission_pin"])
def test_stale_recording_and_submission_generations_fail_closed(fault):
    value = case()
    if fault == "wrong_submission_pin":
        value["expected_bindings"]["submissions"][0]["content_sha256"] = "0" * 64
    else:
        old_binding = copy.deepcopy(value["package"]["recording_binding"])
        value["recording"]["reviewed_payloads"][0]["items"][0]["annotation"]["notes"] += " Changed generation."
        if fault == "old_receipt":
            value["expected_bindings"]["submissions"][0] = binding(value["recording"]["reviewed_payloads"][0])
        else:
            refresh_recording(value)
            if fault == "old_package":
                value["package"]["recording_binding"] = old_binding
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


def test_partial_declaration_cannot_be_referenced_as_complete_evidence():
    original = packet()
    submitted = payload(original)
    submitted["items"][0]["annotation"]["normative_rules"][0]["conditions"] = None
    value = case(submissions=[submitted])
    assert value["recording"]["receipt"]["items"][0]["received_declarations"][0]["complete"] is False
    with pytest.raises(ValueError, match="must be complete"):
        intake(value)


@pytest.mark.parametrize("fault", ["package_process", "selected_process", "provenance_process", "organizer", "cohort"])
def test_unknown_process_or_changed_externally_selected_metadata_is_rejected(fault):
    value = case()
    if fault == "package_process":
        value["package"]["review_process_binding"]["content_sha256"] = "0" * 64
    elif fault == "selected_process":
        value["selected_process_binding"]["content_sha256"] = "0" * 64
    elif fault == "provenance_process":
        value["package"]["items"][0]["provenance_refs"][0]["process_id"] = "package-selected-process"
    else:
        field = "organizer_binding" if fault == "organizer" else "cohort_policy_binding"
        value["package"][field]["file_sha256"] = "0" * 64
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("fault", ["source", "input", "added_context", "changed_context_role"])
def test_rehashed_source_or_context_changes_cannot_replace_frozen_input(fault):
    value = case()
    if fault in {"source", "input"}:
        value["package"]["items"][0][fault + "_sha256"] = "0" * 64
    else:
        item = value["packet"]["items"][0]
        if fault == "added_context":
            item["context"]["text"] = "A newly supplied assumption."
            item["context"]["sha256"] = text_sha(item["context"]["text"])
        else:
            item["context"]["role"] = "explicit_assumptions"
        item["input_sha256"] = digest({"source_text": item["source_text"], "context": item["context"]})
        value["expected_bindings"]["packet"] = binding(value["packet"])
        value["package"]["packet_binding"] = copy.deepcopy(value["expected_bindings"]["packet"])
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("where", ["package", "item", "declaration", "submission_binding", "provenance",
                                   "exposure", "interpretation", "coverage", "adjudication", "selected_process"])
def test_nested_extra_fields_and_caller_authentication_claims_are_rejected(where):
    value = case()
    add_adjudication(value)
    row = value["package"]["items"][0]
    targets = {"package": value["package"], "item": row, "declaration": row["declaration_refs"][0],
               "submission_binding": row["declaration_refs"][0]["submission_binding"],
               "provenance": row["provenance_refs"][0], "exposure": row["provenance_refs"][0]["inputs_exposed"],
               "interpretation": row["interpretations"][0],
               "coverage": row["interpretations"][0]["coverage_assessment"],
               "adjudication": row["adjudication_ref"], "selected_process": value["selected_process_binding"]}
    targets[where]["identity_authenticated"] = True
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("fault", ["mask", "mask_alias", "authority_alias", "count_alias", "complete_alias"])
def test_resealed_recording_cannot_promote_masks_or_numeric_authority_aliases(fault):
    value = case()
    receipt = value["recording"]["receipt"]
    item = receipt["items"][0]
    if fault in {"mask", "mask_alias"}:
        item["masks"]["weak_decoder_fit"] = 1 if fault == "mask" else False
    elif fault == "authority_alias":
        receipt["qualified"] = 0
    elif fault == "count_alias":
        item["complete_declaration_count"] = 2.0
    else:
        item["received_declarations"][0]["complete"] = 1
    receipt["receipt_sha256"] = digest({key: entry for key, entry in receipt.items() if key != "receipt_sha256"})
    value["expected_bindings"]["receipt"] = binding(receipt)
    value["package"]["recording_binding"] = copy.deepcopy(value["expected_bindings"]["receipt"])
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("where,bad", [("file_bytes", True), ("file_bytes", 1.0), ("file_bytes", 0),
                                      ("submission_index", False), ("submission_index", 0.0),
                                      ("provenance_ref", False), ("provenance_ref", 2.0),
                                      ("exposure", 0), ("exposure", "false")])
def test_integer_and_boolean_contracts_reject_python_numeric_aliases(where, bad):
    value = case()
    row = value["package"]["items"][0]
    if where == "file_bytes":
        value["expected_bindings"]["packet"][where] = bad
        value["package"]["packet_binding"][where] = bad
    elif where == "submission_index":
        row["declaration_refs"][0]["submission_binding"][where] = bad
    elif where == "provenance_ref":
        add_adjudication(value)
        row["adjudication_ref"][where] = bad
    else:
        row["provenance_refs"][0]["inputs_exposed"]["candidate_or_reference_exposed"] = bad
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("fault", ["missing", "wrong_principal", "wrong_role", "wrong_input", "missing_exposure",
                                   "unknown_annotation", "duplicate", "non_utc", "invalid_calendar"])
def test_every_declaration_requires_exact_declared_provenance_and_exposure(fault):
    value = case()
    row = value["package"]["items"][0]
    provenance_row = row["provenance_refs"][0]
    if fault == "missing":
        row["provenance_refs"].pop(0)
    elif fault == "wrong_principal":
        provenance_row["principal_id"] = "another-person"
    elif fault == "wrong_role":
        provenance_row["role"] = "verified-reviewer"
    elif fault == "wrong_input":
        provenance_row["inputs_exposed"]["source_input_sha256"] = "0" * 64
    elif fault == "missing_exposure":
        del provenance_row["inputs_exposed"]["organizer_metadata_exposed"]
    elif fault == "unknown_annotation":
        provenance_row["annotation_binding"]["annotation_content_sha256"] = "0" * 64
    elif fault == "duplicate":
        row["provenance_refs"].append(copy.deepcopy(provenance_row))
    else:
        provenance_row["assessed_at_utc"] = "2026-10-04T04:00:00+01:00" if fault == "non_utc" else "2026-02-30T04:00:00Z"
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


def test_declared_candidate_exposure_is_preserved_without_becoming_blind_or_independent_evidence():
    value = case()
    exposure = value["package"]["items"][0]["provenance_refs"][0]["inputs_exposed"]
    exposure.update(candidate_or_reference_exposed=True, organizer_metadata_exposed=True,
                    other_exposure="Synthetic fixture declares prior exposure")
    seal(value["package"])
    receipt = intake(value)
    assert receipt["items"][0]["declared_evidence"]["provenance_refs"][0]["inputs_exposed"] == exposure
    assert_unverified(receipt)


@pytest.mark.parametrize("fault", ["reviewer_overlap", "wrong_provenance", "unknown_interpretation", "not_referenced",
                                   "wrong_count", "unresolved_acceptance", "unknown_decision", "duplicate_declaration"])
def test_declared_adjudication_requires_consistent_references_and_distinct_declared_role(fault):
    value = case()
    add_adjudication(value)
    row = value["package"]["items"][0]
    adjudication = row["adjudication_ref"]
    if fault == "reviewer_overlap":
        principal = row["provenance_refs"][0]["principal_id"]
        adjudication["principal_id"] = principal
        row["provenance_refs"][-1]["principal_id"] = principal
    elif fault == "wrong_provenance":
        adjudication["provenance_ref"] = 0
    elif fault == "unknown_interpretation":
        adjudication["interpretation_refs"] = ["unknown"]
    elif fault == "not_referenced":
        adjudication["interpretation_refs"] = []
    elif fault == "wrong_count":
        adjudication["decision"] = "accept_alternatives"
    elif fault == "unresolved_acceptance":
        adjudication["unresolved_scope"] = ["Unresolved attachment"]
    elif fault == "unknown_decision":
        adjudication["decision"] = "verified_acceptance"
    else:
        adjudication["declaration_refs"].append(copy.deepcopy(adjudication["declaration_refs"][0]))
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("fault", ["family", "missing_facet", "scope", "coverage_loss", "target", "derivation", "duplicate_id"])
def test_v1_interpretation_cannot_silently_lower_scope_or_claim_a_formal_target(fault):
    value = case()
    row = value["package"]["items"][0]
    declared = row["interpretations"][0]
    if fault == "family":
        declared["family"] = "first-order"
    elif fault == "missing_facet":
        del declared["ordered_rules"][0]["exceptions"]
    elif fault == "scope":
        declared["qualifier_scope"] = ""
    elif fault == "coverage_loss":
        declared["coverage_assessment"]["omitted_meaning"] = ["An omitted clause"]
    elif fault == "target":
        declared["formal_target_binding"] = binding({"rules": [rule()]})
    elif fault == "derivation":
        declared["derivation_refs"] = ["caller-declared-proof"]
    else:
        row["interpretations"].append(copy.deepcopy(declared))
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


def test_partial_coverage_is_preserved_as_declared_unverified_without_target_or_admission():
    value = case()
    declared = value["package"]["items"][0]["interpretations"][0]
    declared["coverage_assessment"].update(status="partial", omitted_meaning=["Unrepresented connective"])
    declared["unrepresented_meaning"] = ["An unresolved qualifier attachment"]
    seal(value["package"])
    receipt = intake(value)
    assert receipt["items"][0]["declared_evidence"]["interpretations"][0] == declared
    assert_unverified(receipt)


@pytest.mark.parametrize("fault", ["non_null_supersedes", "duplicate_item", "unknown_item", "empty_refs", "duplicate_ref"])
def test_unowned_revisions_and_duplicate_or_unbound_evidence_are_rejected(fault):
    value = case()
    row = value["package"]["items"][0]
    if fault == "non_null_supersedes":
        value["package"]["supersedes_package_sha256"] = "0" * 64
    elif fault == "duplicate_item":
        value["package"]["items"].append(copy.deepcopy(row))
    elif fault == "unknown_item":
        row["item_id"] = "unknown-item"
    elif fault == "empty_refs":
        row["declaration_refs"] = []
    else:
        row["declaration_refs"].append(copy.deepcopy(row["declaration_refs"][0]))
    seal(value["package"])
    with pytest.raises(ValueError):
        intake(value)


@pytest.mark.parametrize("fault", ["interpretations", "provenance", "declarations", "text_bytes"])
def test_evidence_budgets_reject_without_truncating(fault):
    value = case()
    row = value["package"]["items"][0]
    if fault == "interpretations":
        row["interpretations"] = [interpretation(str(index)) for index in range(subject.MAX_INTERPRETATIONS + 1)]
    elif fault == "provenance":
        row["provenance_refs"] *= subject.MAX_PROVENANCE + 1
    elif fault == "declarations":
        row["declaration_refs"] *= recorder.MAX_SUBMISSIONS + 1
    else:
        row["provenance_refs"][0]["rationale"] = "é" * (subject.MAX_TEXT_BYTES // 2 + 1)
    seal(value["package"])
    before = copy.deepcopy(value)
    with pytest.raises(ValueError):
        intake(value)
    assert value == before


@pytest.mark.parametrize("poison", [float("nan"), float("inf"), object()])
def test_nonordinary_inputs_fail_before_recorder_replay(poison, monkeypatch):
    value = case()
    value["package"]["items"][0]["provenance_refs"][0]["limitations"] = poison

    def unexpected_replay(*args, **kwargs):
        pytest.fail("nonordinary evidence reached recorder replay")

    monkeypatch.setattr(recorder, "validate_recording", unexpected_replay)
    with pytest.raises(ValueError):
        intake(value)


def test_returned_evidence_is_detached_and_repeatable():
    value = case()
    add_adjudication(value)
    before = copy.deepcopy(value)
    receipt = intake(value)
    assert receipt == intake(value)
    assert receipt["content_sha256"] == digest({key: entry for key, entry in receipt.items() if key != "content_sha256"})
    receipt["items"][0]["declared_evidence"]["interpretations"][0]["ordered_rules"][0]["conditions"].append("mutation")
    receipt["expected_bindings"]["submissions"][0]["file_bytes"] = 999
    receipt["selected_process_binding"]["process_id"] = "mutation"
    assert value == before
    assert intake(value)["items"][0]["declared_evidence"] == before["package"]["items"][0]


def test_intake_uses_no_io_models_provers_or_legacy_reference_bundle(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_admission as legacy,
    )

    value = case()
    original_import = builtins.__import__
    forbidden = {"torch", "numpy", "spacy", "transformers", "sentence_transformers", "requests", "httpx", "openai", "z3", "cvc5"}

    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, name
        return original_import(name, *args, **kwargs)

    def unexpected_io(*args, **kwargs):
        pytest.fail("dictionary intake attempted file I/O")

    def unexpected_bundle(*args, **kwargs):
        pytest.fail("intake invoked authored reference bundle preparation")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(builtins, "open", unexpected_io)
    monkeypatch.setattr(legacy, "_blank_bundle", unexpected_bundle)
    assert_unverified(intake(value))
