"""Reviewer blinding, reproducible coverage and unreviewed one-facet contrasts."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_review.py"
spec = importlib.util.spec_from_file_location("alignment_review_subject", PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def row(identity, group, split, actor, modality="O", object_="certificate", style=0):
    source = f"The {actor} {dict(O='must', P='may', F='must not')[modality]} issue the {object_}. Wording style {style}."
    target = {"rules": [{"modality": modality, "actor": actor, "action": "issue", "object": object_,
                         "conditions": [], "exceptions": [], "temporal": []}]}
    return {"id": identity, "group_id": group, "split": split, "source_text": source,
            "source_sha256": subject._source_digest(source), "target": target, "wording_style": style,
            "embedding": ["unused confidential vector"], "compiler_outcome": {"secret_candidate": "withheld"}}


@pytest.fixture
def inputs():
    training = [row("private-training-id", "private-training-group", "train", "clerk")]
    development = [row(f"private-development-id-{g}-{modality}-{object_}-{style}", f"private-development-group-{g}",
                       "validation", f"actor{g}", modality, object_, style)
                   for g in range(5) for modality in ("O", "P", "F")
                   for object_ in ("certificate", "filing") for style in range(4)]
    bindings = {"train": {"path": "corpus/train.json", "sha256": "a" * 64},
                "development": {"path": "corpus/validation.json", "sha256": "b" * 64},
                "evaluation_role": "exposed_development"}
    return training, development, bindings


def prepare(inputs):
    return subject.prepare_alignment_review(*inputs)


def walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


def test_review_payload_is_source_only_pseudonymous_and_annotations_blank(inputs):
    result = prepare(inputs)
    reviewer = result["reviewer_payload"]
    serialized = json.dumps(reviewer)
    prohibited = {"target", "reference_target", "synthetic_authored_reference_target", "candidate", "embedding",
                  "compiler_outcome", "original_id", "original_group_id", "source_bindings", "wording_style"}
    assert not prohibited & set(walk_keys(reviewer))
    assert "private-development" not in serialized and "unused confidential vector" not in serialized
    originals = {row_["source_sha256"]: row_ for row_ in inputs[1]}
    assert len(reviewer["items"]) == 40
    for item in reviewer["items"]:
        assert set(item) == {"item_id", "group_pseudonym", "source_text", "source_sha256", "evaluation_role", "annotation"}
        assert item["source_text"] == originals[item["source_sha256"]]["source_text"]
        assert subject._source_digest(item["source_text"]) == item["source_sha256"]
        assert item["item_id"].startswith("review-item-") and item["group_pseudonym"].startswith("review-group-")
        assert item["evaluation_role"] == "exposed_development"
        assert item["annotation"]["facets"] == {facet: None for facet in subject.FACETS}
        assert all(value is None for key, value in item["annotation"].items() if key != "facets")
    assert reviewer["preparation_status"] == "pending_human_review"


def test_sampling_is_stable_balances_groups_and_covers_modalities_constructions(inputs):
    first = prepare(inputs)
    second = prepare((list(reversed(inputs[0])), list(reversed(inputs[1])), deepcopy(inputs[2])))
    assert first == second
    sampling = first["organizer_payload"]["sampling"]
    assert sampling["selected_groups"] == sampling["available_groups"] == 5
    assert set(sampling["authored_modality_counts"]) == {"O", "P", "F"}
    assert set(sampling["construction_style_counts"]) == {"0", "1", "2", "3"}
    by_group = {}
    for entry in first["organizer_payload"]["reviewer_key"]:
        by_group.setdefault(entry["original_group_id"], []).append(entry)
    assert max(map(len, by_group.values())) - min(map(len, by_group.values())) <= 1
    assert all({entry["synthetic_authored_reference_target"]["rules"][0]["modality"] for entry in entries} == {"O", "P", "F"}
               for entries in by_group.values())


def test_mutants_preserve_exact_source_and_change_only_declared_typed_facet(inputs):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule
    result = prepare(inputs)
    organizer = result["organizer_payload"]
    originals = {entry["item_id"]: entry for entry in organizer["reviewer_key"]}
    sources = {item["item_id"]: item for item in result["reviewer_payload"]["items"]}
    contrasts = organizer["contrast_corpus"]["rows"]
    assert len(contrasts) == 40 * len(subject.FACETS)
    assert {proposal["changed_facet"] for proposal in contrasts} == set(subject.FACETS)
    assert len({proposal["proposal_id"] for proposal in contrasts}) == len(contrasts)
    for proposal in contrasts:
        entry = originals[proposal["item_id"]]
        original = entry["synthetic_authored_reference_target"]["rules"][0]
        proposed = proposal["proposed_target"]["rules"][0]
        assert CanonicalRule.from_dict(proposed).to_dict() == proposed
        assert [key for key in subject.FACETS if original[key] != proposed[key]] == [proposal["changed_facet"]]
        assert proposal["source_text"] == sources[proposal["item_id"]]["source_text"]
        assert proposal["source_sha256"] == sources[proposal["item_id"]]["source_sha256"]
        assert proposal["original_reference_target_sha256"] == entry["reference_target_sha256"]
        assert subject._digest(proposal["proposed_target"]) == proposal["proposed_target_sha256"]
        assert proposal["status"] == "unreviewed_ir_contrast_proposal"
        assert proposal["typed_contract_validated"] is True
        assert proposal["excluded_from_training"] is proposal["excluded_from_evaluation_gold"] is True
        assert proposal["encoded"] is proposal["semantic_mismatch_adjudicated"] is proposal["proof_verified"] is False


def test_manifests_bind_separate_payloads_and_never_create_authority(inputs):
    snapshot = deepcopy(inputs)
    result = prepare(inputs)
    assert inputs == snapshot
    for audience in ("reviewer", "organizer"):
        manifest = result[audience + "_manifest"]
        assert manifest["payload_sha256"] == subject._digest(result[audience + "_payload"])
        assert manifest["source_bindings_sha256"] == subject._digest(inputs[2])
        assert manifest["candidate_blind"] is (audience == "reviewer")
        assert manifest["automatic_adjudication"] is False
        assert all(manifest[key] is False for key in subject._AUTHORITY)
    assert all(result[key] is False for key in subject._AUTHORITY)
    assert result["model_calls"] == result["provider_calls"] == result["encoder_calls"] == result["prover_calls"] == 0
    assert result["organizer_payload"]["do_not_send_to_reviewers"] is True
    assert result["organizer_payload"]["contrast_corpus"]["not_ground_truth"] is True


@pytest.mark.parametrize("fault", ["source_hash", "target_hash", "sealed_split", "sealed_role", "group_leak", "source_leak", "target_leak", "binding"])
def test_changed_integrity_or_protected_inputs_rejected(inputs, fault):
    training, development, bindings = deepcopy(inputs)
    if fault == "source_hash":
        development[0]["source_text"] += " altered"
    elif fault == "target_hash":
        development[0]["target_sha256"] = "0" * 64
    elif fault == "sealed_split":
        development[0]["split"] = "test"
    elif fault == "sealed_role":
        development[0]["evaluation_role"] = "sealed"
    elif fault == "group_leak":
        development[0]["group_id"] = training[0]["group_id"]
    elif fault == "source_leak":
        development[0]["source_text"] = training[0]["source_text"]
        development[0]["source_sha256"] = training[0]["source_sha256"]
    elif fault == "target_leak":
        development[0]["target"] = training[0]["target"]
    elif fault == "binding":
        bindings["development"]["path"] = "corpus/sealed/validation.json"
    with pytest.raises(ValueError):
        prepare((training, development, bindings))


def test_present_qualifier_mutation_removes_one_value_without_other_changes(inputs):
    inputs[1][0]["target"]["rules"][0]["conditions"] = ["condition_a", "condition_b"]
    # A single-item exposed panel ensures this qualifier case is selected.
    result = prepare((inputs[0], inputs[1][:1], inputs[2]))
    proposal = next(row_ for row_ in result["organizer_payload"]["contrast_corpus"]["rows"]
                    if row_["changed_facet"] == "conditions")
    assert proposal["proposed_target"]["rules"][0]["conditions"] == ["condition_b"]
    assert len(result["reviewer_payload"]["items"]) == 1


def test_preparation_does_not_import_or_invoke_model_provider_encoder_or_prover(inputs, monkeypatch):
    import builtins
    original = builtins.__import__
    forbidden = {"torch", "transformers", "sentence_transformers", "requests", "httpx", "z3", "cvc5"}
    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, name
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert prepare(inputs)["status"] == "prepared_pending_human_review"
