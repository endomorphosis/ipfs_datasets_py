"""Review admission preserves source bindings and cannot manufacture authority."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]


def load(name, filename):
    path = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


subject = load("alignment_review_admission_subject", "alignment_review_admission.py")
preparation = load("alignment_review_preparation_subject", "alignment_review.py")


def row(identity, split, actor):
    source = f"The {actor} must issue the certificate."
    return {"id": identity, "group_id": "group-" + identity, "split": split, "source_text": source,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "wording_style": 0,
            "target": {"rules": [{"modality": "O", "actor": actor, "action": "issue", "object": "certificate",
                                   "conditions": [], "exceptions": [], "temporal": []}]}}


@pytest.fixture
def bundle():
    return preparation.prepare_alignment_review(
        [row("training", "train", "clerk")],
        [row("development-a", "validation", "officer"), row("development-b", "validation", "citizen")],
        {"train": {"path": "corpus/train.json", "sha256": "a" * 64},
         "development": {"path": "corpus/validation.json", "sha256": "b" * 64},
         "evaluation_role": "exposed_development"})


def payload(bundle, reviewer="reviewer-a", *, complete=True, subset=None):
    result = deepcopy(bundle["reviewer_payload"])
    if subset is not None:
        result["items"] = [item for item in result["items"] if item["item_id"] in subset]
    if complete:
        references = {entry["item_id"]: entry["synthetic_authored_reference_target"]["rules"][0]
                      for entry in bundle["organizer_payload"]["reviewer_key"]}
        # Synthetic test annotations are fixtures, not claimed human reviews.
        for item in result["items"]:
            item["annotation"] = {"facets": deepcopy(references[item["item_id"]]), "notes": None,
                                  "ambiguity": False, "unsupported_meaning": False, "reviewer_id": reviewer,
                                  "reviewed_at_utc": "2026-10-03T14:23:01Z"}
    return result


def admit(bundle, *reviews):
    return subject.admit_alignment_reviews(bundle, list(reviews))


def assert_no_authority(result):
    assert all(result[field] is False for field in subject._AUTHORITY)
    assert result["production_admitted"] is False
    assert result["primary_independently_adjudicated_fidelity"] == {"status": "unavailable", "value": None}
    assert result["native_useful_proof_coverage"] == {"status": "unrun", "value": None}
    for evidence in ("reviewer_identity_evidence", "source_author_independence_evidence", "reviewer_attestation_evidence"):
        assert result[evidence] == {"status": "unavailable", "authenticated": False}
    assert result["automatic_adjudication"] is result["reference_used_to_resolve_disputes"] is False
    for item in result["items"]:
        assert all(item[field] is False for field in subject._AUTHORITY)
        assert item["external_adjudication_status"] == "pending"


def test_blank_submission_remains_pending_without_generated_labels_or_signoff(bundle):
    blank = payload(bundle, complete=False)
    snapshot = deepcopy((bundle, blank))
    result = admit(bundle, blank)
    assert result["status"] == "pending"
    assert result["status_counts"]["pending"] == 2
    assert result["preliminary_candidate_count"] == 0
    for item in result["items"]:
        submission = item["submissions"][0]
        assert submission["complete"] is False
        assert submission["annotation"]["facets"] == {facet: None for facet in subject.FACETS}
        assert submission["annotation"]["reviewer_id"] is submission["annotation"]["reviewed_at_utc"] is None
        assert item["authored_reference_diagnostic"]["status"] == "unavailable"
    assert (bundle, blank) == snapshot
    assert_no_authority(result)


def test_no_submissions_and_partial_annotations_are_pending(bundle):
    assert admit(bundle)["status_counts"]["pending"] == 2
    partial = payload(bundle, complete=False)
    partial["items"][0]["annotation"]["notes"] = "Source needs further reading."
    partial["items"][0]["annotation"]["facets"]["modality"] = "O"
    result = admit(bundle, partial)
    assert result["status"] == "pending"
    assert all(item["complete_distinct_reviewer_count"] == 0 for item in result["items"])
    assert result["items"][0]["authored_reference_diagnostic"]["value"] is None


def test_single_complete_review_scores_authored_agreement_without_qualification(bundle):
    result = admit(bundle, payload(bundle))
    assert result["status_counts"]["single_review"] == 2
    assert result["preliminary_candidate_count"] == 0
    for item in result["items"]:
        diagnostic = item["authored_reference_diagnostic"]
        assert diagnostic["status"] == "computed_after_annotation_acceptance"
        assert diagnostic["value"] is True
        assert diagnostic["reference_origin"] == "synthetic_authored_unreviewed"
        assert diagnostic["role"] == "authored_agreement_diagnostic"
        assert diagnostic["independent_fidelity"] is False
        assert item["submissions"][0]["annotation"]["facets"]["conditions"] == []
    assert_no_authority(result)


def test_two_distinct_reviewers_are_only_preliminary_candidates_and_notes_need_not_match(bundle):
    second = payload(bundle, "reviewer-b")
    second["items"][0]["annotation"]["notes"] = "Independently submitted explanation."
    second["items"][0]["annotation"]["reviewed_at_utc"] = "2026-10-03T14:24:01.123456+00:00"
    result = admit(bundle, payload(bundle), second)
    assert result["status_counts"]["agreed_multiple_reviews"] == 2
    assert result["preliminary_candidate_count"] == 2
    assert all(item["complete_distinct_reviewer_count"] == 2 for item in result["items"])
    assert all(item["preliminary_independent_adjudication_candidate"] for item in result["items"])
    assert_no_authority(result)


@pytest.mark.parametrize("facet", subject.FACETS)
def test_conflicting_completed_facets_are_disputed_not_resolved_by_references(bundle, facet):
    first, second = payload(bundle), payload(bundle, "reviewer-b")
    rule = second["items"][0]["annotation"]["facets"]
    rule[facet] = "P" if facet == "modality" else "alternative" if facet in ("actor", "action", "object") else ["constraint"]
    result = admit(bundle, first, second)
    disputed = next(item for item in result["items"] if item["item_id"] == second["items"][0]["item_id"])
    assert disputed["status"] == "disputed"
    assert disputed["authored_reference_diagnostic"]["status"] == "unavailable"
    assert disputed["preliminary_independent_adjudication_candidate"] is False
    assert result["status_counts"]["agreed_multiple_reviews"] == 1
    assert_no_authority(result)


@pytest.mark.parametrize("flag,status", [("ambiguity", "ambiguous"), ("unsupported_meaning", "unsupported")])
def test_explicit_problem_flags_block_preliminary_adjudication_and_flag_conflicts_dispute(bundle, flag, status):
    first, second = payload(bundle), payload(bundle, "reviewer-b")
    first["items"][0]["annotation"][flag] = True
    result = admit(bundle, first)
    assert result["status_counts"][status] == 1
    assert result["preliminary_candidate_count"] == 0
    disputed = admit(bundle, first, second)
    assert disputed["status_counts"]["disputed"] == 1
    second["items"][0]["annotation"][flag] = True
    agreed_problem = admit(bundle, first, second)
    assert agreed_problem["status_counts"][status] == 1
    assert agreed_problem["preliminary_candidate_count"] == 1  # Only the other, clean item.
    assert_no_authority(agreed_problem)


def test_item_subsets_and_reordering_preserve_pending_item_accounting(bundle):
    first_id = bundle["reviewer_payload"]["items"][0]["item_id"]
    partial = payload(bundle, subset={first_id})
    result = admit(bundle, partial)
    assert result["status_counts"]["single_review"] == result["status_counts"]["pending"] == 1
    reordered = payload(bundle)
    reordered["items"].reverse()
    assert admit(bundle, reordered)["status_counts"]["single_review"] == 2


@pytest.mark.parametrize("field", ["item_id", "group_pseudonym", "source_text", "source_sha256", "evaluation_role"])
def test_changed_item_or_source_identity_is_rejected_even_if_new_source_digest_is_consistent(bundle, field):
    changed = payload(bundle)
    item = changed["items"][0]
    item[field] = "changed" if field != "source_sha256" else "0" * 64
    if field == "source_text":
        item["source_sha256"] = hashlib.sha256(item["source_text"].encode()).hexdigest()
    with pytest.raises(ValueError):
        admit(bundle, changed)


@pytest.mark.parametrize("fault", ["unknown_schema", "unknown_payload_field", "unknown_item_field", "unknown_annotation_field",
                                   "unknown_facet", "changed_instructions", "missing_item_field", "missing_annotation_field"])
def test_closed_schema_and_prepared_metadata_are_enforced(bundle, fault):
    changed = payload(bundle)
    item = changed["items"][0]
    if fault == "unknown_schema":
        changed["schema"] = "claimed-reviewed/v99"
    elif fault == "unknown_payload_field":
        changed["qualified"] = True
    elif fault == "unknown_item_field":
        item["adjudicated"] = True
    elif fault == "unknown_annotation_field":
        item["annotation"]["reviewer_authenticated"] = True
    elif fault == "unknown_facet":
        item["annotation"]["facets"]["invented"] = "value"
    elif fault == "changed_instructions":
        changed["instructions"] = "Read the organizer references."
    elif fault == "missing_item_field":
        del item["source_sha256"]
    else:
        del item["annotation"]["ambiguity"]
    with pytest.raises(ValueError):
        admit(bundle, changed)


@pytest.mark.parametrize("field,value", [
    ("modality", "obligation"), ("modality", 1), ("actor", ""), ("action", True), ("object", ["certificate"]),
    ("conditions", "none"), ("exceptions", [""]), ("temporal", [1]), ("ambiguity", "false"),
    ("unsupported_meaning", 0), ("reviewer_id", " "), ("reviewer_id", "reviewer-a "),
    ("reviewed_at_utc", "2026-10-03"), ("reviewed_at_utc", "2026-10-03T14:23:01"),
    ("reviewed_at_utc", "2026-10-03T14:23:01+01:00"), ("reviewed_at_utc", "2026-02-30T14:23:01Z"),
    ("reviewed_at_utc", 1), ("notes", ["explanation"]),
])
def test_malformed_annotation_values_and_non_utc_timestamps_rejected(bundle, field, value):
    changed = payload(bundle)
    annotation = changed["items"][0]["annotation"]
    (annotation["facets"] if field in subject.FACETS else annotation)[field] = value
    with pytest.raises(ValueError):
        admit(bundle, changed)


def test_none_qualifier_is_pending_but_empty_list_is_reviewed_absence(bundle):
    partial = payload(bundle)
    partial["items"][0]["annotation"]["facets"]["conditions"] = None
    result = admit(bundle, partial)
    assert result["status_counts"]["pending"] == result["status_counts"]["single_review"] == 1
    item = next(item for item in result["items"] if item["status"] == "pending")
    assert item["submissions"][0]["missing_fields"] == ["conditions"]


def test_duplicate_items_submissions_and_reviewer_identity_do_not_inflate_review_count(bundle):
    original = payload(bundle)
    duplicate_item = deepcopy(original)
    duplicate_item["items"].append(deepcopy(duplicate_item["items"][0]))
    with pytest.raises(ValueError, match="duplicate item"):
        admit(bundle, duplicate_item)
    with pytest.raises(ValueError, match="duplicate review submission"):
        admit(bundle, original, deepcopy(original))
    same_reviewer = deepcopy(original)
    same_reviewer["items"][0]["annotation"]["notes"] = "A second file from the same reviewer."
    with pytest.raises(ValueError, match="duplicate reviewer"):
        admit(bundle, original, same_reviewer)


def test_original_blank_payload_and_organizer_hashes_are_binding_prerequisites(bundle):
    changed = deepcopy(bundle)
    changed["reviewer_payload"]["items"][0]["annotation"]["facets"]["modality"] = "O"
    changed["reviewer_manifest"]["payload_sha256"] = subject._digest(changed["reviewer_payload"])
    with pytest.raises(ValueError, match="blank annotation"):
        admit(changed)
    changed = deepcopy(bundle)
    changed["organizer_payload"]["reviewer_key"][0]["original_id"] = "altered"
    with pytest.raises(ValueError, match="digest mismatch"):
        admit(changed)
    changed = deepcopy(bundle)
    changed["reviewer_manifest"]["source_bindings_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        admit(changed)


def test_authored_reference_change_affects_diagnostic_only_and_cannot_resolve_disputes(bundle):
    first, second = payload(bundle), payload(bundle, "reviewer-b")
    second["items"][0]["annotation"]["facets"]["actor"] = "alternative"
    changed = deepcopy(bundle)
    entry = changed["organizer_payload"]["reviewer_key"][0]
    entry["synthetic_authored_reference_target"]["rules"][0]["actor"] = "alternative"
    entry["reference_target_sha256"] = subject._digest(entry["synthetic_authored_reference_target"])
    changed["organizer_manifest"]["payload_sha256"] = subject._digest(changed["organizer_payload"])
    before, after = admit(bundle, first, second), admit(changed, first, second)
    assert before["status_counts"] == after["status_counts"]
    disputed = next(item for item in after["items"] if item["status"] == "disputed")
    assert disputed["authored_reference_diagnostic"]["value"] is None
    single = admit(changed, first)
    assert single["status_counts"]["single_review"] == 2
    assert sum(item["authored_reference_diagnostic"]["value"] is True for item in single["items"]) == 1
    assert_no_authority(single)


def test_receipt_binds_original_payloads_and_submissions_and_is_ordinary_json(bundle):
    reviewed = payload(bundle)
    result = admit(bundle, reviewed)
    assert result["reviewer_payload_sha256"] == bundle["reviewer_manifest"]["payload_sha256"]
    assert result["organizer_payload_sha256"] == bundle["organizer_manifest"]["payload_sha256"]
    assert result["submissions"][0]["payload_sha256"] == subject._digest(reviewed)
    unsigned = deepcopy(result)
    del unsigned["receipt_sha256"]
    assert result["receipt_sha256"] == subject._digest(unsigned)
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_bounded_reader_rejects_hash_drift_duplicate_keys_nonfinite_and_wrong_envelope(tmp_path):
    path = tmp_path / "review.json"
    def read(raw, **kwargs):
        path.write_bytes(raw)
        return subject.read_alignment_review_file(path, hashlib.sha256(raw).hexdigest(), **kwargs)
    assert read(b'{"items": []}') == {"items": []}
    for raw in (b'{"items": [], "items": [1]}', b'{"value": NaN}', b'{"value": Infinity}', b'[]'):
        with pytest.raises(ValueError):
            read(raw)
    with pytest.raises(ValueError, match="byte bound"):
        read(b'{"large": "abcdefgh"}', max_bytes=8)
    path.write_bytes(b'{}')
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        subject.read_alignment_review_file(path, "0" * 64)


def test_admission_does_not_import_optional_models_provers_or_make_network_calls(bundle, monkeypatch):
    import builtins
    original = builtins.__import__
    forbidden = {"torch", "transformers", "sentence_transformers", "requests", "httpx", "z3", "cvc5"}
    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, name
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = admit(bundle, payload(bundle))
    assert result["model_calls"] == result["provider_calls"] == result["encoder_calls"] == result["prover_calls"] == 0


def test_fifo_review_input_is_rejected_without_blocking(tmp_path):
    import os

    fifo=tmp_path/"review.fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError,match="regular review file"):
        subject.read_alignment_review_file(fifo,"0"*64)


def test_symlink_review_input_is_rejected(tmp_path):
    file=tmp_path/"review.json"
    file.write_text("{}")
    link=tmp_path/"linked.json"
    link.symlink_to(file)
    with pytest.raises(OSError):
        subject.read_alignment_review_file(link,hashlib.sha256(file.read_bytes()).hexdigest())
