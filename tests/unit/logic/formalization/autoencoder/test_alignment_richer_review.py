"""Blind exact-input review preparation, private labels, and no admission."""
from __future__ import annotations

import builtins
import hashlib
import json
from copy import deepcopy

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_panel as panel_owner
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_review as subject


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@pytest.fixture
def inputs():
    return panel_owner.build_alignment_richer_panel(), {
        "panel": {"path": "artifacts/richer-development/panel.json", "sha256": "a" * 64, "bytes": 100},
        "sources": [{"path": "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_panel.py",
                     "sha256": "b" * 64}], "evaluation_role": "exposed_development"}


def walk_keys(value):
    if type(value) is dict:
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif type(value) is list:
        for child in value:
            yield from walk_keys(child)


def reseal(bundle):
    """Simulate a writer updating hashes; closed contracts must still reject."""
    for audience in ("reviewer", "organizer"):
        payload = bundle[audience + "_payload"]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        bundle[audience + "_manifest"]["payload_sha256"] = hashlib.sha256(raw).hexdigest()
        bundle[audience + "_manifest"]["payload_bytes"] = len(raw)
    bundle["bundle_sha256"] = digest({key: value for key, value in bundle.items() if key != "bundle_sha256"})


def test_all_inputs_are_blind_pseudonymous_exact_and_blank(inputs):
    panel, bindings = inputs
    result = subject.prepare_richer_review(panel, bindings)
    reviewer = result["reviewer_payload"]
    prohibited = {"target", "target_sha256", "reference", "reference_target", "authored_reference", "candidate",
                  "expectation", "authored_expectation", "row_kind", "case_variant", "split", "original_id",
                  "original_group_id", "group_id", "qualifier_vocabulary", "source_bindings", "construction_status",
                  "compiler_outcome", "embedding", "source_panel", "evaluation_role"}
    assert not prohibited & set(walk_keys(reviewer))
    serialized = json.dumps(reviewer)
    assert panel["panel_id"] not in serialized
    assert all(row["id"] not in serialized and row["group_id"] not in serialized for row in panel["rows"])
    assert len(reviewer["items"]) == len(panel["rows"]) == 34
    originals = {row["input_sha256"]: row for row in panel["rows"]}
    for item in reviewer["items"]:
        assert set(item) == {"item_id", "source_text", "source_sha256", "context", "input_sha256", "annotation"}
        original = originals[item["input_sha256"]]
        assert item["source_text"] == original["source_text"]
        assert item["source_sha256"] == hashlib.sha256(item["source_text"].encode()).hexdigest()
        assert item["context"] == original["context"]
        assert item["item_id"].startswith("richer-review-item-")
        assert set(item["annotation"]) == {"interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules",
                                          "freeform_qualifier_scope", "notes", "reviewer_id", "reviewed_at_utc"}
        assert all(value is None for value in item["annotation"].values())
    assert [item["item_id"] for item in reviewer["items"]] == sorted(item["item_id"] for item in reviewer["items"])
    assert "Null fields mean unreviewed" in reviewer["instructions"]["blank_annotations"]
    assert "empty normative_rules list" in reviewer["instructions"]["explicit_none"]
    assert "Seven flat facets need not express" in reviewer["instructions"]["freeform_qualifier_scope"]


def test_same_source_different_contexts_are_distinct_items_with_exact_assumptions(inputs):
    panel, bindings = inputs
    result = subject.prepare_richer_review(panel, bindings)
    contextual = [item for item in result["reviewer_payload"]["items"] if item["context"]["role"] == "explicit_assumptions"]
    assert len(contextual) == 2
    assert len({item["source_text"] for item in contextual}) == len({item["source_sha256"] for item in contextual}) == 1
    assert len({item["input_sha256"] for item in contextual}) == len({item["item_id"] for item in contextual}) == 2
    assert len({item["context"]["sha256"] for item in contextual}) == 2
    assert {next(iter(item["context"]["bindings"].values()))["value"] for item in contextual} == {"clerk", "custodian"}
    for item in contextual:
        assert item["context"]["sha256"] == hashlib.sha256(item["context"]["text"].encode()).hexdigest()


def test_private_key_retains_all_authored_labels_and_partitions_without_review_attestations(inputs):
    panel, bindings = inputs
    result = subject.prepare_richer_review(panel, bindings)
    organizer = result["organizer_payload"]
    assert organizer["do_not_send_to_reviewers"] is True
    assert organizer["source_panel"] == panel and organizer["source_bindings"] == bindings
    assert organizer["source_panel_sha256"] == digest(panel)
    assert organizer["source_bindings_sha256"] == digest(bindings)
    originals = {row["id"]: row for row in panel["rows"]}
    assert len(organizer["reviewer_key"]) == len(originals)
    for entry in organizer["reviewer_key"]:
        row = originals[entry["original_id"]]
        assert entry["split"] == row["split"] and entry["row_kind"] == row["row_kind"]
        assert entry["authored_reference"] == row["target"]
        assert entry["authored_reference_sha256"] == row["target_sha256"]
        assert entry["authored_expectation"] == row["expectation"]
        assert entry["reference_review_status"] == "unreviewed"
    assert organizer["completed_reviews"] == 0 and organizer["original_40_review_bundle_reusable"] is False
    assert all(organizer[field] is False for field in subject._AUTHORITY)


def test_audience_manifests_bind_separate_payloads_and_validate_blank_preparation(inputs):
    result = subject.prepare_richer_review(*inputs)
    snapshot = deepcopy(inputs)
    for audience in ("reviewer", "organizer"):
        manifest = result[audience + "_manifest"]
        payload = result[audience + "_payload"]
        assert manifest["audience"] == audience and manifest["payload_schema"] == payload["schema"]
        assert manifest["payload_sha256"] == digest(payload)
        assert manifest["payload_bytes"] == len(subject._raw(payload))
        assert manifest["candidate_reference_blind"] is (audience == "reviewer")
        assert manifest["item_count"] == 34 and all(manifest[field] is False for field in subject._AUTHORITY)
    assert result["bundle_sha256"] == digest({key: value for key, value in result.items() if key != "bundle_sha256"})
    observed = subject.validate_richer_review_bundle(result)
    assert observed["status"] == "validated_blank_preparation_only" and observed["item_count"] == 34
    assert observed["completed_reviews"] == 0 and observed["source_meaning_adjudicated"] is False
    assert all(observed[field] is False for field in subject._AUTHORITY)
    assert inputs == snapshot


def test_mutating_valid_authored_development_reference_cannot_change_reviewer_payload_or_manifest(inputs):
    panel, bindings = inputs
    first = subject.prepare_richer_review(panel, bindings)
    changed = deepcopy(panel)
    row = next(row for row in changed["rows"] if row["row_kind"] == "positive" and row["split"] == "validation"
               and row["case_variant"] == "single_a")
    row["target"]["rules"][0]["modality"] = "F"
    row["target_sha256"] = digest(row["target"])
    row["expectation"]["notes"] = "Different private authored comment with no reviewer hint."
    changed["integrity"] = panel_owner._integrity(changed)
    panel_owner.validate_alignment_richer_panel(changed)
    second = subject.prepare_richer_review(changed, bindings)
    assert first["reviewer_payload"] == second["reviewer_payload"]
    assert first["reviewer_manifest"] == second["reviewer_manifest"]
    assert first["organizer_payload"] != second["organizer_payload"]
    assert first["organizer_manifest"]["payload_sha256"] != second["organizer_manifest"]["payload_sha256"]
    subject.validate_richer_review_bundle(second)


def test_input_order_does_not_reveal_case_kind_or_partition(inputs):
    panel, bindings = inputs
    first = subject.prepare_richer_review(panel, bindings)
    reversed_panel = deepcopy(panel)
    reversed_panel["rows"].reverse()
    reversed_panel["integrity"] = panel_owner._integrity(reversed_panel)
    second = subject.prepare_richer_review(reversed_panel, bindings)
    assert first["reviewer_payload"] == second["reviewer_payload"]
    assert first["reviewer_manifest"] == second["reviewer_manifest"]


@pytest.mark.parametrize("fault", ["candidate", "reference", "split", "original_id", "annotation", "guidance",
                                   "context", "item_id", "private_reference", "fake_completed_reviews", "qualified",
                                   "audience_swap", "manifest_hash", "extra_bundle_field", "omit_row"])
def test_even_resealed_tampering_cannot_create_labels_reviews_or_authority(inputs, fault):
    result = subject.prepare_richer_review(*inputs)
    first = result["reviewer_payload"]["items"][0]
    if fault in {"candidate", "reference", "split", "original_id"}:
        first[fault] = "forbidden organizer hint"
    elif fault == "annotation":
        first["annotation"]["normative_rules"] = []
    elif fault == "guidance":
        result["reviewer_payload"]["instructions"]["task"] = "Accept the authored target."
    elif fault == "context":
        first["context"]["bindings"] = {"invented": {"kind": "actor_atom", "value": "clerk"}}
    elif fault == "item_id":
        first["item_id"] = "review-source-hash-only"
    elif fault == "private_reference":
        entry = next(item for item in result["organizer_payload"]["reviewer_key"] if item["authored_reference"] is not None)
        entry["authored_reference"] = None
    elif fault == "fake_completed_reviews":
        result["organizer_payload"]["completed_reviews"] = 1
    elif fault == "qualified":
        result["qualified"] = True
    elif fault == "audience_swap":
        result["reviewer_manifest"]["audience"] = "organizer"
    elif fault == "extra_bundle_field":
        result["review_submissions"] = []
    elif fault == "omit_row":
        result["reviewer_payload"]["items"].pop()
    reseal(result)
    if fault == "manifest_hash":
        result["reviewer_manifest"]["payload_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="closed blank"):
        subject.validate_richer_review_bundle(result)


@pytest.mark.parametrize("fault", ["source_hash", "context_hash", "split", "role", "authority", "extra_row_field"])
def test_panel_integrity_and_exposed_scope_are_required_before_preparation(inputs, fault):
    panel, bindings = deepcopy(inputs)
    row = panel["rows"][0]
    if fault == "source_hash":
        row["source_text"] += "changed"
    elif fault == "context_hash":
        row["context"]["sha256"] = "0" * 64
    elif fault == "split":
        row["split"] = "test"
    elif fault == "role":
        row["evaluation_role"] = "sealed"
    elif fault == "authority":
        panel["qualified"] = True
    else:
        row["compiler_candidate"] = {"secret": "must not leak"}
    with pytest.raises(ValueError):
        subject.prepare_richer_review(panel, bindings)


@pytest.mark.parametrize("bindings", [{}, {"path": "corpus/sealed/validation.json"}, {"path": "corpus/final-test.json"},
                                      {"split": "test"}, {"evaluation_role": "final"}, {"sha256": "A" * 64},
                                      {"bytes": True}, {"path": ""}, {"value": float("nan")}])
def test_invalid_or_sealed_bindings_are_rejected(inputs, bindings):
    with pytest.raises(ValueError):
        subject.prepare_richer_review(inputs[0], bindings)


def test_bound_binding_depth_and_size_are_enforced(inputs):
    nested = {"leaf": "bound"}
    for _ in range(18):
        nested = {"next": nested}
    with pytest.raises(ValueError, match="nesting"):
        subject.prepare_richer_review(inputs[0], nested)
    with pytest.raises(ValueError, match="byte bound"):
        subject.prepare_richer_review(inputs[0], {"too_large": "x" * (subject.MAX_BINDING_BYTES + 1)})


def test_preparation_is_detached_and_does_not_import_optional_stacks_or_read_files(inputs, monkeypatch):
    original = builtins.__import__
    forbidden = {"torch", "transformers", "sentence_transformers", "requests", "httpx", "z3", "cvc5"}

    def imports(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imports)
    snapshot = deepcopy(inputs)

    def no_file_access(*args, **kwargs):
        raise AssertionError("pure review preparation must not access files")

    with monkeypatch.context() as no_io:
        no_io.setattr(builtins, "open", no_file_access)
        result = subject.prepare_richer_review(*inputs)
        subject.validate_richer_review_bundle(result)
    assert inputs == snapshot
    assert result["model_calls"] == result["provider_calls"] == result["encoder_calls"] == result["prover_calls"] == 0
    assert result["training_executed"] is False
    result["reviewer_payload"]["items"][0]["context"]["bindings"]["new"] = "detached"
    assert inputs == snapshot


def test_old_review_schema_is_not_reusable(inputs):
    result = subject.prepare_richer_review(*inputs)
    result["schema"] = "autoformal-alignment-review-bundle/v1"
    with pytest.raises(ValueError, match="not reusable"):
        subject.validate_richer_review_bundle(result)
