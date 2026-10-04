"""Meaningful integrity, provenance, split, qualifier, and context boundaries."""

import importlib.util
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_panel.py"
spec = importlib.util.spec_from_file_location("alignment_richer_panel_subject", PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


@pytest.fixture
def panel():
    return subject.build_alignment_richer_panel()


def positives(panel, split):
    return [row for row in panel["rows"] if row["row_kind"] == "positive" and row["split"] == split]


def rebind(panel, row=None):
    """Refresh hashes so rejection exercises the semantic *contract* guard."""
    if row is not None:
        row["source_sha256"] = subject._source_digest(row["source_text"])
        row["context"]["sha256"] = subject._source_digest(row["context"]["text"])
        row["input_sha256"] = subject._input_digest(row)
        row["target_sha256"] = subject._digest(row["target"]) if row["target"] is not None else None
        row["qualifier_vocabulary"] = subject._qualifier_status(row, subject._vocabulary_fields(panel["rows"]))
    panel["integrity"] = subject._integrity(panel)


def test_panel_is_deterministic_detached_json_and_remains_unqualified(panel):
    again = subject.build_alignment_richer_panel()
    assert again == panel
    assert json.loads(json.dumps(panel, allow_nan=False)) == panel
    receipt = subject.validate_alignment_richer_panel(panel)
    assert receipt["training_positive_rows"] == 16
    assert receipt["development_positive_rows"] == 8
    assert receipt["development_oov_qualifier_positive_rows"] == 2
    assert receipt["row_kind_counts"] == {"positive": 24, "unsupported": 6, "ambiguous": 2, "explicit_context": 2}
    assert receipt["typed_target_contract_validated"] is True
    assert receipt["source_meaning_adjudicated"] is False
    for key in ("qualified", "proof_authority", "independent_fidelity_available"):
        assert receipt[key] is False
        assert panel[key] is False
    assert panel["production_admitted"] is False and panel["primary_fidelity"] == "unavailable"
    panel["rows"][0]["target"]["rules"][0]["conditions"].append("mutable_local_value")
    assert subject.build_alignment_richer_panel() == again


def test_whole_case_groups_sources_and_full_references_are_split_disjoint(panel):
    train = positives(panel, "train")
    development = positives(panel, "validation")
    assert len({r["group_id"] for r in train}) == 4
    assert len({r["group_id"] for r in development}) == 2
    assert set(Counter(r["group_id"] for r in train).values()) == {4}
    assert set(Counter(r["group_id"] for r in development).values()) == {4}
    for field in ("id", "group_id", "source_sha256", "input_sha256", "target_sha256"):
        assert {r[field] for r in train}.isdisjoint(r[field] for r in development)
    train_compositions = {(r["target"]["rules"][0]["actor"], r["target"]["rules"][0]["action"],
                           r["target"]["rules"][0]["object"]) for r in train}
    development_compositions = {(r["target"]["rules"][0]["actor"], r["target"]["rules"][0]["action"],
                                 r["target"]["rules"][0]["object"]) for r in development}
    assert train_compositions.isdisjoint(development_compositions)
    for facet in subject.CORE_FACETS:
        known = {r["target"]["rules"][0][facet] for r in train}
        assert all(r["target"]["rules"][0][facet] in known for r in development)


def test_all_positive_qualifiers_are_typed_nonempty_and_identity_contrasts_are_real(panel):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    rows = [r for r in panel["rows"] if r["target"] is not None]
    for row in rows:
        assert CanonicalRoundTripIR.from_dict(row["target"]).to_dict() == row["target"]
        assert row["target_sha256"] == subject._digest(row["target"])
        assert all(0 < len(row["target"]["rules"][0][f]) <= 3 for f in subject.QUALIFIER_FACETS)
    for group in {r["group_id"] for r in positives(panel, "train") + positives(panel, "validation")}:
        group_rows = [r for r in panel["rows"] if r["group_id"] == group]
        a = next(r["target"]["rules"][0] for r in group_rows if r["case_variant"] == "single_a")
        b = next(r["target"]["rules"][0] for r in group_rows if r["case_variant"] == "single_b")
        assert all(a[f] == b[f] for f in subject.CORE_FACETS)
        assert all(len(a[f]) == len(b[f]) == 1 and a[f] != b[f] for f in subject.QUALIFIER_FACETS)
        multiple = next(r["target"]["rules"][0] for r in group_rows if r["case_variant"] == "multiple")
        assert all(len(multiple[f]) == 2 for f in subject.QUALIFIER_FACETS)
        assert {r["target"]["rules"][0]["modality"] for r in group_rows} == {"O", "P", "F"}
    assert panel["capabilities"]["conditions_connective"] == "all"
    assert panel["capabilities"]["exceptions_connective"] == "any"
    assert panel["capabilities"]["temporal_connective"] == "all_named_constraints"


def test_train_vocabulary_excludes_development_oov_and_context_only_core(panel):
    vocab = subject.richer_training_vocabulary(panel).to_dict()
    assert vocab == {"actors": ["clerk", "custodian", "officer", "registrar"],
                     "actions": ["audit", "authorize", "notify", "retain"],
                     "objects": ["applicant", "application", "filing"],
                     "qualifiers": ["application_complete", "before_the_review_deadline", "court_order",
                                    "fees_paid", "legal_hold", "within_48_hours"]}
    assert "identity_verified" not in vocab["qualifiers"] and "case_file" not in vocab["objects"]
    development = positives(panel, "validation")
    known = [r for r in development if r["qualifier_vocabulary"]["status"] == "train_known"]
    oov = [r for r in development if r["qualifier_vocabulary"]["status"] == "contains_authored_oov_atoms"]
    assert len(known) == 6 and len(oov) == 2
    assert all(r["qualifier_vocabulary"]["oov_atoms"] == {
        "conditions": ["identity_verified"], "exceptions": [], "temporal": []} for r in oov)


def test_reference_mutation_changes_diagnostics_not_source_input_or_train_vocab(panel):
    row = positives(panel, "validation")[0]
    before_input = subject.richer_row_input(row)
    before_vocab = subject.richer_training_vocabulary(panel).to_dict()
    row["target"]["rules"][0]["actor"] = "registrar"
    rebind(panel, row)
    # Structural acceptance deliberately does not certify this changed label.
    assert subject.validate_alignment_richer_panel(panel)["source_meaning_adjudicated"] is False
    assert subject.richer_row_input(row) == before_input
    assert subject.richer_training_vocabulary(panel).to_dict() == before_vocab


def test_source_payload_never_contains_reference_expectation_or_authorship_hints(panel):
    for row in panel["rows"]:
        if row["row_kind"] != "explicit_context":
            payload = subject.richer_row_input(row)
            assert payload["source_text"] == row["source_text"]
            assert payload["source_sha256"] == subject._source_digest(row["source_text"])
            assert not {"target", "target_sha256", "expectation", "case_variant", "row_kind", "group_id",
                        "qualifier_vocabulary", "provenance", "context"} & payload.keys()


def test_shared_source_interpretations_require_explicit_different_context_inputs(panel):
    rows = [r for r in panel["rows"] if r["row_kind"] == "explicit_context"]
    a, b = rows
    assert a["source_text"] == b["source_text"] and a["source_sha256"] == b["source_sha256"]
    assert a["group_id"] == b["group_id"] and a["split"] == b["split"] == "validation"
    assert a["context"]["sha256"] != b["context"]["sha256"]
    assert a["input_sha256"] != b["input_sha256"] and a["target_sha256"] != b["target_sha256"]
    for row in rows:
        with pytest.raises(ValueError, match="cannot be consumed as source-only"):
            subject.richer_row_input(row)
        payload = subject.richer_row_input(row, mode="source_with_context")
        assert payload["source_text"] == row["source_text"]
        assert payload["context"] == row["context"] and "target" not in payload
        payload["context"]["bindings"].clear()
        assert row["context"]["bindings"]
    bundle = panel["interpretation_bundles"][0]
    assert bundle["source_only_consumption_allowed"] is False
    assert bundle["excluded_from_source_only_training"] is True
    assert bundle["excluded_from_source_only_evaluation_gold"] is True
    assert set(bundle["row_ids"]) == {r["id"] for r in rows}
    assert panel["capabilities"]["current_compiler_context_input"] == "unavailable"


def test_scope_binder_and_ambiguity_cases_have_no_positive_or_training_gold(panel):
    negatives = [r for r in panel["rows"] if r["row_kind"] in {"unsupported", "ambiguous"}]
    assert len(negatives) == 8
    assert all(r["target"] is r["target_sha256"] is None and r["split"] == "validation" for r in negatives)
    reasons = {r["expectation"]["reason_code"] for r in negatives}
    assert {"quantified_binders", "quantified_cardinality", "relational_variable_binding",
            "condition_disjunction", "exception_conjunction", "negated_deontic_modality",
            "ambiguous_actor_reference", "missing_calendar_context"} == reasons
    for row in negatives:
        assert row["expectation"]["authored_unreviewed"] is True
        assert row["expectation"]["compiler_outcome_observed"] is False
    assert panel["capabilities"]["quantified_binders"] == "unsupported"
    assert panel["capabilities"]["nested_scope"] == "unsupported"
    assert panel["capabilities"]["native_temporal_semantics_verified"] is False


@pytest.mark.parametrize("fault", ["source", "source_digest", "context_digest", "input_digest", "target_digest", "panel_digest"])
def test_each_integrity_binding_rejects_altered_inputs(panel, fault):
    row = positives(panel, "validation")[0]
    if fault == "source":
        row["source_text"] += " Altered source."
    elif fault == "source_digest":
        row["source_sha256"] = "0" * 64
    elif fault == "context_digest":
        row["context"]["sha256"] = "0" * 64
    elif fault == "input_digest":
        row["input_sha256"] = "0" * 64
    elif fault == "target_digest":
        row["target_sha256"] = "0" * 64
    else:
        panel["integrity"]["panel_payload_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.validate_alignment_richer_panel(panel)


@pytest.mark.parametrize("fault", ["group", "source", "target", "id"])
def test_rehashed_cross_split_leakage_is_rejected(panel, fault):
    train = positives(panel, "train")[0]
    development = positives(panel, "validation")[0]
    field = {"group": "group_id", "source": "source_text", "target": "target", "id": "id"}[fault]
    development[field] = deepcopy(train[field])
    rebind(panel, development)
    with pytest.raises(ValueError, match="leakage|duplicate"):
        subject.validate_alignment_richer_panel(panel)


@pytest.mark.parametrize("fault", ["sealed_split", "sealed_role", "authority", "provenance", "new_facet",
                                  "empty_qualifier", "qualifier_budget", "source_budget", "hidden_context",
                                  "row_budget", "oov_claim", "review_claim", "model_claim"])
def test_rehashed_scope_and_authority_fail_closed(panel, fault):
    row = positives(panel, "validation")[0]
    if fault == "sealed_split":
        row["split"] = "test"
    elif fault == "sealed_role":
        row["evaluation_role"] = "sealed_final"
    elif fault == "authority":
        row["proof_authority"] = True
    elif fault == "provenance":
        row["provenance"]["review_status"] = "independently_reviewed"
    elif fault == "new_facet":
        row["target"]["rules"][0]["forall_binder"] = "x"
    elif fault == "empty_qualifier":
        row["target"]["rules"][0]["conditions"] = []
    elif fault == "qualifier_budget":
        row["target"]["rules"][0]["conditions"] = ["a", "b", "c", "d"]
    elif fault == "source_budget":
        row["source_text"] = "x" * (panel["limits"]["max_source_chars"] + 1)
    elif fault == "hidden_context":
        row["context"] = subject._context("Assume the clerk denotes the custodian.",
                                           {"clerk": {"kind": "actor_atom", "value": "custodian"}})
    elif fault == "row_budget":
        panel["rows"] = panel["rows"] * 3
    elif fault == "oov_claim":
        row["qualifier_vocabulary"] = {"status": "contains_authored_oov_atoms", "oov_atoms": {
            "conditions": ["invented"], "exceptions": [], "temporal": []}}
    elif fault == "review_claim":
        panel["review_contract"]["completed_reviews"] = 2
    else:
        panel["resource_scope"]["encoder_calls"] = 1
    if fault == "oov_claim":
        rebind(panel)
    else:
        rebind(panel, row)
    with pytest.raises(ValueError):
        subject.validate_alignment_richer_panel(panel)


@pytest.mark.parametrize("fault", ["drop_bundle", "different_context_actor", "same_context", "allow_source_only", "negative_target"])
def test_rehashed_context_and_negative_gold_boundaries(panel, fault):
    contexts = [r for r in panel["rows"] if r["row_kind"] == "explicit_context"]
    row = contexts[0]
    if fault == "drop_bundle":
        panel["interpretation_bundles"] = []
    elif fault == "different_context_actor":
        row["target"]["rules"][0]["actor"] = "officer"
    elif fault == "same_context":
        row = contexts[1]
        row["context"] = deepcopy(contexts[0]["context"])
        row["target"] = deepcopy(contexts[0]["target"])
    elif fault == "allow_source_only":
        panel["interpretation_bundles"][0]["source_only_consumption_allowed"] = True
    else:
        row = next(r for r in panel["rows"] if r["row_kind"] == "unsupported")
        row["target"] = deepcopy(positives(panel, "train")[0]["target"])
    rebind(panel, row)
    if panel["interpretation_bundles"]:
        panel["interpretation_bundles"][0]["input_sha256s"] = [r["input_sha256"] for r in contexts]
        rebind(panel)
    with pytest.raises(ValueError):
        subject.validate_alignment_richer_panel(panel)


def test_no_parser_renderer_model_prover_or_network_imports(monkeypatch):
    import builtins

    original = builtins.__import__
    forbidden_roots = {"torch", "transformers", "sentence_transformers", "spacy", "requests", "httpx", "z3", "cvc5"}
    forbidden_modules = {"ipfs_datasets_py.logic.legal_ir.canonical_compiler",
                         "ipfs_datasets_py.logic.legal_ir.canonical_decompiler",
                         "ipfs_datasets_py.logic.deontic.converter"}

    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden_roots and name not in forbidden_modules, name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    panel = subject.build_alignment_richer_panel()
    subject.richer_training_vocabulary(panel)
    assert panel["resource_scope"] == {"vectors_present": False, "encoder_calls": 0, "model_calls": 0,
        "provider_calls": 0, "prover_calls": 0, "compiler_calls": 0, "decoder_calls": 0, "sealed_inputs_accessed": False}
