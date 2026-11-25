"""Tests for LegalIR semantic-equivalence promotion metrics."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    COUNTEREXAMPLE_EQUIVALENCE,
    DECOMPILER_ROUND_TRIP_PRESERVATION,
    GRAPH_ISOMORPHISM,
    LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION,
    OBLIGATION_EQUIVALENCE,
    PROOF_OBLIGATION_DELTA,
    PROOF_OBLIGATION_DELTA_SCORE,
    SEMANTIC_EQUIVALENCE_METRICS,
    STRUCTURAL_EQUIVALENCE,
    TEMPORAL_WINDOW_AGREEMENT,
    SemanticEquivalenceConfig,
    compare_legal_ir_semantic_equivalence,
    evaluate_legal_ir_semantic_equivalence,
    semantic_equivalence_from_metrics,
    semantic_equivalence_promotion_gate,
)


def _reference_ir() -> dict:
    return {
        "rules": [
            {
                "id": "rule-a",
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "condition": "within 30 days",
                "proof_obligation_ids": ["po-notice"],
                "temporal_window": {"start": "2026-01-01", "duration": "30 days"},
            }
        ],
        "graph": {
            "nodes": [
                {"id": "n1", "label": "Agency", "type": "actor"},
                {"id": "n2", "label": "Notice", "type": "document"},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "label": "must_provide"},
            ],
        },
        "counterexamples": [{"assignment": {"notice": False}, "violates": "po-notice"}],
        "round_trip": {
            "decompiled": "O(agency, provide_notice)",
            "recompiled_ir": "O(agency, provide_notice)",
        },
    }


def _isomorphic_ir() -> dict:
    return {
        "rules": [
            {
                "id": "renumbered",
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "condition": "within 30 days",
                "proof_obligation_ids": ["po-notice"],
                "temporal_window": {"start": "2026-01-01", "duration": "30 days"},
            }
        ],
        "graph": {
            "nodes": [
                {"id": "x", "label": "Notice", "type": "document"},
                {"id": "y", "label": "Agency", "type": "actor"},
            ],
            "edges": [
                {"source": "y", "target": "x", "label": "must_provide"},
            ],
        },
        "counterexamples": [{"assignment": {"notice": False}, "violates": "po-notice"}],
        "round_trip": {
            "decompiled": "O(agency, provide_notice)",
            "recompiled_ir": "O(agency, provide_notice)",
        },
    }


def _regressed_ir() -> dict:
    changed = _isomorphic_ir()
    changed["rules"][0].update(
        {
            "modality": "permission",
            "condition": "within 60 days",
            "proof_obligation_ids": ["po-permit"],
            "temporal_window": {"start": "2026-01-01", "duration": "60 days"},
        }
    )
    changed["graph"]["edges"][0]["label"] = "may_provide"
    changed["counterexamples"] = [{"assignment": {"notice": True}, "violates": "po-permit"}]
    changed["round_trip"]["recompiled_ir"] = "P(agency, provide_notice)"
    return changed


def _all_semantic_scores(score: float = 1.0) -> dict[str, float]:
    values = {metric: score for metric in SEMANTIC_EQUIVALENCE_METRICS}
    values[PROOF_OBLIGATION_DELTA] = 0.0 if score == 1.0 else 1.0
    return values


def test_raw_ir_pair_scores_semantic_equivalence_beyond_ids_and_order() -> None:
    result = evaluate_legal_ir_semantic_equivalence(
        _reference_ir(),
        _isomorphic_ir(),
        family="deontic",
    )

    assert result.complete is True
    assert result.scores[STRUCTURAL_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[OBLIGATION_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[COUNTEREXAMPLE_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[GRAPH_ISOMORPHISM] == pytest.approx(1.0)
    assert result.scores[TEMPORAL_WINDOW_AGREEMENT] == pytest.approx(1.0)
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] == pytest.approx(1.0)
    assert result.scores[PROOF_OBLIGATION_DELTA_SCORE] == pytest.approx(1.0)
    assert result.raw_deltas[PROOF_OBLIGATION_DELTA] == pytest.approx(0.0)


def test_semantic_metrics_detect_obligation_graph_temporal_and_proof_delta() -> None:
    result = evaluate_legal_ir_semantic_equivalence(
        _reference_ir(),
        _regressed_ir(),
        family="deontic",
    )

    assert result.scores[OBLIGATION_EQUIVALENCE] < 1.0
    assert result.scores[COUNTEREXAMPLE_EQUIVALENCE] < 1.0
    assert result.scores[GRAPH_ISOMORPHISM] < 1.0
    assert result.scores[TEMPORAL_WINDOW_AGREEMENT] < 1.0
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] < 1.0
    assert result.scores[PROOF_OBLIGATION_DELTA_SCORE] == pytest.approx(0.0)
    assert result.raw_deltas[PROOF_OBLIGATION_DELTA] == pytest.approx(2.0)


def test_explicit_metric_payload_accepts_delta_alias_and_fails_closed_on_missing() -> None:
    complete = semantic_equivalence_from_metrics(
        {
            **_all_semantic_scores(),
            "proof_obligation_delta_count": 0,
        },
        family="kg",
    )
    incomplete = semantic_equivalence_from_metrics(
        {
            STRUCTURAL_EQUIVALENCE: 1.0,
            OBLIGATION_EQUIVALENCE: 1.0,
        },
        family="kg",
    )

    assert complete.family == "knowledge_graphs"
    assert complete.missing_metrics == ()
    assert incomplete.missing_metrics == (
        COUNTEREXAMPLE_EQUIVALENCE,
        GRAPH_ISOMORPHISM,
        TEMPORAL_WINDOW_AGREEMENT,
        DECOMPILER_ROUND_TRIP_PRESERVATION,
        PROOF_OBLIGATION_DELTA_SCORE,
    )


def test_comparison_reports_disagreement_when_ce_cosine_improve_but_semantics_regress() -> None:
    baseline = {
        "view_family_metrics": {
            "deontic": {
                **_all_semantic_scores(),
                "autoencoder_cross_entropy_loss": 0.80,
                "autoencoder_cosine_similarity": 0.70,
                "ir_cross_entropy_loss": 0.85,
                "ir_cosine_similarity": 0.68,
            }
        }
    }
    candidate = {
        "view_family_metrics": {
            "deontic": {
                **_all_semantic_scores(),
                OBLIGATION_EQUIVALENCE: 0.50,
                "autoencoder_cross_entropy_loss": 0.30,
                "autoencoder_cosine_similarity": 0.90,
                "ir_cross_entropy_loss": 0.35,
                "ir_cosine_similarity": 0.88,
            }
        }
    }

    report = compare_legal_ir_semantic_equivalence(
        baseline,
        candidate,
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )
    payload = report.to_dict()

    assert report.accepted is False
    assert report.schema_version == LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION
    assert report.disagreements == ("deontic:ce_cosine_improved_semantic_equivalence_regressed",)
    assert "deontic:ce_cosine_semantic_disagreement" in report.block_reasons
    assert payload["family_results"]["deontic"]["disagreement"] is True


def test_raw_family_payload_can_drive_hard_promotion_gate() -> None:
    baseline = {
        "view_family_metrics": {
            "deontic": {
                "reference_ir": _reference_ir(),
                "candidate_ir": _isomorphic_ir(),
                "autoencoder_cross_entropy_loss": 0.80,
                "autoencoder_cosine_similarity": 0.70,
            }
        }
    }
    candidate = {
        "view_family_metrics": {
            "deontic": {
                "reference_ir": _reference_ir(),
                "candidate_ir": _regressed_ir(),
                "autoencoder_cross_entropy_loss": 0.30,
                "autoencoder_cosine_similarity": 0.90,
            }
        }
    }

    gate = semantic_equivalence_promotion_gate(
        baseline,
        candidate,
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )

    assert gate["accepted"] is False
    assert gate["hard_promotion_gate"] is True
    assert gate["failed_families"] == ["deontic"]
    assert "deontic:semantic_equivalence_regressed" in gate["block_reasons"]


# Additive exact-payload diagnostics; no model, prover or runtime is invoked.
from copy import deepcopy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    evaluate_complete_norm_payloads,
)


def _complete_norm_payload_fixture():
    return {"profile": "fictional-payload/v1", "typed_expression": {"root": {"kind": "forall",
        "binders": [{"name": "actor", "sort": "person"}], "arguments": [{"kind": "obligation",
        "predicate": "file", "arguments": ["agency", "report"], "exception": "emergency",
        "cardinality": 1, "time": "30days"}]}}, "argument_roles": [{"symbol": "file", "roles": ["actor", "object"]}],
        "assumptions": [], "governing_context": {"jurisdiction": "fictional", "instrument_id": "act",
        "governing_edition": "v1", "legal_as_of_utc": "2026-01-01", "valid_from_utc": "2025-01-01", "valid_until_utc": "2027-01-01"},
        "interpretation_id": "fixture:one", "source_binding": {"source_version_cid": "source-one",
        "occurrence_cid": "span-one", "document_revision": "v1"}, "definition_uses": [{"definition_unit_id": "definition",
        "defined_predicate": "file", "use_unit_id": "norm", "use_occurrence_cid": "span-one", "target_typed_paths": ["/root/arguments/0"],
        "applicability": "governing", "interpretation_id": "fixture:one", "evidence_refs": []}],
        "cross_references": [{"from_unit_id": "norm", "dependency_artifact_id": "external-one",
        "dependency_sha256": "a" * 64, "version": "v1", "evidence_refs": []}]}


def _complete_norm_case(candidate=None, *, outcome="complete", case_id="case-one"):
    target = _complete_norm_payload_fixture()
    return {"case_id": case_id, "reference": target,
            "candidate": deepcopy(target) if candidate is None else candidate, "outcome": outcome}


def test_complete_norm_payload_exact_positive_has_only_payload_comparison_authority():
    report = evaluate_complete_norm_payloads([_complete_norm_case()])
    assert report["denominator"] == 1
    assert all(value == 1 for value in report["metric_numerators"].values())
    assert report["scope"] == "exact_structural_and_local_facet_payload_comparison_only"
    assert all(report[key] is False for key in ("producer_authenticity_verified", "reference_authenticity_verified",
        "syntax_or_logic_family_validity_verified", "semantic_equivalence_proved", "governing_definition_meaning_verified",
        "source_fidelity_proved", "legal_admission_or_proof_authority"))


@pytest.mark.parametrize("change", ["actor", "role_order", "argument_order", "binder", "quantifier", "modality",
                                   "exception", "cardinality", "time", "assumption", "definition_path", "definition_applicability"])
def test_complete_norm_payload_preserves_ordered_structure_and_local_facets(change):
    candidate = _complete_norm_payload_fixture()
    root = candidate["typed_expression"]["root"]
    node = root["arguments"][0]
    if change == "actor": node["arguments"][0] = "court"
    elif change == "role_order": candidate["argument_roles"][0]["roles"].reverse()
    elif change == "argument_order": node["arguments"].reverse()
    elif change == "binder": root["binders"][0]["sort"] = "organization"
    elif change == "quantifier": root["kind"] = "exists"
    elif change == "modality": node["kind"] = "permission"
    elif change == "exception": node["exception"] = "different-exception"
    elif change == "cardinality": node["cardinality"] = 2
    elif change == "time": node["time"] = "60days"
    elif change == "assumption": candidate["assumptions"] = ["new premise"]
    elif change == "definition_path": candidate["definition_uses"][0]["target_typed_paths"] = ["/other"]
    else: candidate["definition_uses"][0]["applicability"] = "non-governing"
    scores = evaluate_complete_norm_payloads([_complete_norm_case(candidate)])["cases"][0]["scores"]
    assert scores["local_structural_payload_exact"] == scores["full_nine_payload_exact"] == 0
    assert scores["interpretation_identity_exact"] == scores["source_binding_exact"] == 1


@pytest.mark.parametrize("change", ["interpretation", "definition_id", "xref_id", "xref_version", "source", "context"])
def test_complete_norm_payload_separates_custody_source_context_from_local_structure(change):
    candidate = _complete_norm_payload_fixture()
    if change == "interpretation": candidate["interpretation_id"] = "fixture:two"
    elif change == "definition_id": candidate["definition_uses"][0]["definition_unit_id"] = "other-definition"
    elif change == "xref_id": candidate["cross_references"][0]["dependency_artifact_id"] = "other-external"
    elif change == "xref_version": candidate["cross_references"][0]["version"] = "v2"
    elif change == "source": candidate["source_binding"]["source_version_cid"] = "other-source"
    else: candidate["governing_context"]["governing_edition"] = "v2"
    scores = evaluate_complete_norm_payloads([_complete_norm_case(candidate)])["cases"][0]["scores"]
    assert scores["local_structural_payload_exact"] == 1
    assert scores["full_nine_payload_exact"] == 0


def test_complete_norm_payload_retains_every_noncomplete_outcome_in_denominator():
    rows = [_complete_norm_case()]
    for outcome in ("incomplete", "abstained", "unsupported", "invalid", "error"):
        rows.append(_complete_norm_case(outcome=outcome, case_id=outcome))
    malformed = _complete_norm_case(case_id="missing-field")
    malformed["candidate"].pop("typed_expression")
    rows.append(malformed)
    report = evaluate_complete_norm_payloads(rows)
    assert report["denominator"] == 7
    assert report["outcome_counts"] == {"complete": 2, "incomplete": 1, "abstained": 1, "unsupported": 1, "invalid": 1, "error": 1}
    assert report["metric_numerators"]["full_nine_payload_exact"] == 1
    assert report["metric_denominators"]["full_nine_payload_exact"] == 7
    assert report["rates"]["full_nine_payload_exact"] == pytest.approx(1/7)
    assert all(sum(row["scores"].values()) == 0 for row in report["cases"][1:])


@pytest.mark.parametrize("fault", ["duplicate_ids", "bad_reference", "extra_reference", "nonfinite", "nonstring_key", "nested_tuple", "extra_example", "bad_source", "bad_context", "bad_definition", "bad_xref", "bad_root"])
def test_complete_norm_payload_refuses_invalid_reference_or_nonlossless_evaluation(fault):
    rows = [_complete_norm_case()]
    if fault == "duplicate_ids": rows.append(deepcopy(rows[0]))
    elif fault == "bad_reference": rows[0]["reference"]["argument_roles"] = "not a list"
    elif fault == "extra_reference": rows[0]["reference"]["hidden"] = "not silently ignored"
    elif fault == "nonfinite": rows[0]["candidate"]["typed_expression"]["root"]["value"] = float("nan")
    elif fault == "nonstring_key": rows[0]["candidate"]["typed_expression"][1] = "not coerced"
    elif fault == "nested_tuple": rows[0]["reference"]["assumptions"] = ("not silently converted",)
    elif fault == "bad_source": rows[0]["reference"]["source_binding"]["source_version_cid"] = 7
    elif fault == "bad_context": rows[0]["reference"]["governing_context"]["governing_edition"] = []
    elif fault == "bad_definition": rows[0]["reference"]["definition_uses"][0]["defined_predicate"] = None
    elif fault == "bad_xref": rows[0]["reference"]["cross_references"][0]["evidence_refs"] = ["not a reference"]
    elif fault == "bad_root": rows[0]["reference"]["typed_expression"]["root"] = {}
    else: rows[0]["hidden"] = "not accepted"
    with pytest.raises(ValueError): evaluate_complete_norm_payloads(rows)


@pytest.mark.parametrize("value", [True, 1.0])
def test_complete_norm_payload_does_not_round_or_coerce_bool_numeric_identity(value):
    candidate = _complete_norm_payload_fixture()
    candidate["typed_expression"]["root"]["arguments"][0]["cardinality"] = value
    report = evaluate_complete_norm_payloads([_complete_norm_case(candidate)])
    assert report["metric_numerators"]["typed_expression_exact"] == 0


def test_complete_norm_payload_snapshot_does_not_return_reference_or_prediction_labels():
    row = _complete_norm_case()
    report = evaluate_complete_norm_payloads([row])
    row["candidate"]["typed_expression"]["root"]["kind"] = "changed later"
    assert report["metric_numerators"]["full_nine_payload_exact"] == 1
    assert all("reference" not in case and "candidate" not in case for case in report["cases"])



def test_complete_norm_payload_absent_candidate_keeps_original_denominator():
    row = _complete_norm_case()
    row["candidate"] = None
    report = evaluate_complete_norm_payloads([row])
    assert report["denominator"] == report["malformed_complete_candidate_count"] == 1
    assert all(value == 0 for value in report["metric_numerators"].values())



def _retrieved_payload_case():
    import json,hashlib
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    a=_complete_norm_payload_fixture();b=deepcopy(a);b['typed_expression']['root']['arguments'][0]['arguments'][0]='court'
    references=[dict(id='q1',canonical_ir=deepcopy(a)),dict(id='q2',canonical_ir=deepcopy(b))]
    candidates=[dict(id='a',canonical_ir=a),dict(id='alias-a',canonical_ir=deepcopy(a)),dict(id='b',canonical_ir=b)]
    def payload_sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def result(mode,orders):
        return dict(schema='legal-joint-retrieval-result/v3',status='retrieval_completed',mode=mode,
            checkpoint_sha256='a'*64,current_index_handoff_sha256='b'*64,query_input_sha256='c'*64,
            query_lane_bundle_sha256='d'*64,query_target_access=False,inference_reference_content_forwarded=False,
            rows=[dict(id=key,status='retrieved',retrieved_ids=ids,eligible_rows=3,excluded_examples=[],
                retrieved_endpoint_refs=[dict(id=i,formal_view_sha256=payload_sha(next(row['canonical_ir'] for row in candidates if row['id']==i))) for i in ids]) for key,ids in orders])
    rankings={'joint':result('joint',[('q1',['a','alias-a','b']),('q2',['b','a','alias-a'])]),
              'raw':result('raw',[('q1',['b','a','alias-a']),('q2',['a','alias-a','b'])])}
    def options():return dict(expected_rankings_sha256=hashlib.sha256(owner._complete_norm_payload_wire(rankings)).hexdigest(),expected_reference_rows_sha256=hashlib.sha256(owner._complete_norm_payload_wire(references)).hexdigest(),expected_candidate_rows_sha256=hashlib.sha256(owner._complete_norm_payload_wire(candidates)).hexdigest(),ranking_depth=3,cutoffs=(1,2,3))
    return owner,rankings,references,candidates,options


def test_retrieved_complete_payloads_bind_frozen_rankings_and_separate_local_matches_from_legal_relevance():
    owner,rankings,references,candidates,options=_retrieved_payload_case()
    report=owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**options())
    assert report['reference_count']==2 and report['candidate_view_count']==3 and report['unique_candidate_payload_count']==2
    assert report['methods']['joint']['cutoffs']['1']['metric_numerators']['full_nine_payload_exact']==2
    assert report['methods']['raw']['cutoffs']['1']['metric_numerators']['full_nine_payload_exact']==0
    assert report['methods']['raw']['cutoffs']['2']['metric_numerators']['full_nine_payload_exact']==1
    assert report['methods']['raw']['cutoffs']['3']['metric_numerators']['full_nine_payload_exact']==2
    assert report['methods']['raw']['cutoffs']['1']['denominator']==2
    assert report['semantic_relevance_metrics'] is report['legal_applicability_metrics'] is None
    assert report['semantic_equivalence_proved'] is report['producer_authenticity_verified'] is False


def test_retrieved_payloads_retain_abstentions_and_absent_counterparts_without_false_recall():
    owner,rankings,references,candidates,options=_retrieved_payload_case()
    row=rankings['joint']['rows'][1];row.update(status='abstained',retrieved_ids=[],retrieved_endpoint_refs=[])
    references[1]['canonical_ir']['interpretation_id']='unavailable-in-candidate-bank'
    report=owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**options())
    joint=report['methods']['joint'];assert joint['abstention_count']==1
    assert joint['cutoffs']['1']['metric_numerators']['full_nine_payload_exact']==1
    assert joint['cutoffs']['1']['denominator']==2
    assert joint['cutoffs']['1']['eligible_index_match_counts']['full_nine_payload_exact']==1
    for row in references:row['canonical_ir']['source_binding']['source_version_cid']='absent-entirely'
    report=owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**options())
    assert report['methods']['joint']['cutoffs']['1']['conditional_exact_match_rates']['full_nine_payload_exact'] is None


@pytest.mark.parametrize('damage',['rankings-pin','reference-pin','candidate-pin','missing-query','duplicate-query','foreign-candidate','duplicate-rank','mixed-input','payload-binding','eligible-alias','cutoff-alias','target-access'])
def test_retrieved_payload_metrics_refuse_changed_population_binding_budget_and_opaque_rankings(damage):
    owner,rankings,references,candidates,options=_retrieved_payload_case()
    if damage=='missing-query':rankings['raw']['rows'].pop()
    elif damage=='duplicate-query':rankings['raw']['rows'][1]['id']='q1'
    elif damage=='foreign-candidate':rankings['raw']['rows'][0]['retrieved_ids'][0]='foreign'
    elif damage=='duplicate-rank':rankings['raw']['rows'][0]['retrieved_ids'][1]=rankings['raw']['rows'][0]['retrieved_ids'][0]
    elif damage=='mixed-input':rankings['raw']['query_input_sha256']='e'*64
    elif damage=='payload-binding':rankings['raw']['rows'][0]['retrieved_endpoint_refs'][0]['formal_view_sha256']='e'*64
    elif damage=='eligible-alias':rankings['raw']['rows'][0]['eligible_rows']=True
    elif damage=='target-access':rankings['raw']['query_target_access']=True
    kwargs=options()
    if damage in ('rankings-pin','reference-pin','candidate-pin'):
        kwargs[{'rankings-pin':'expected_rankings_sha256','reference-pin':'expected_reference_rows_sha256','candidate-pin':'expected_candidate_rows_sha256'}[damage]]='f'*64
    if damage=='cutoff-alias':kwargs['cutoffs']=(True,)
    with pytest.raises(ValueError):owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**kwargs)



def test_retrieved_payloads_detect_original_input_drift_during_posthoc_scoring(monkeypatch):
    owner,rankings,references,candidates,options=_retrieved_payload_case()
    original=owner.evaluate_complete_norm_payloads
    def mutate(rows):
        result=original(rows);candidates[0]['canonical_ir']['assumptions'].append('late mutation');return result
    monkeypatch.setattr(owner,'evaluate_complete_norm_payloads',mutate)
    with pytest.raises(ValueError,match='changed'):
        owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**options())



@pytest.mark.parametrize('damage',['remove','boolean-alias','float-alias'])
def test_retrieved_payloads_reject_cutoff_configuration_drift_during_scoring(monkeypatch,damage):
    owner,rankings,references,candidates,options=_retrieved_payload_case()
    kwargs=options();offered=list(kwargs['cutoffs']);kwargs['cutoffs']=offered
    original=owner.evaluate_complete_norm_payloads
    def mutate(rows):
        result=original(rows)
        if damage=='remove':offered.pop()
        elif damage=='boolean-alias':offered[0]=True
        else:offered[0]=1.0
        return result
    monkeypatch.setattr(owner,'evaluate_complete_norm_payloads',mutate)
    with pytest.raises(ValueError,match='changed'):
        owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**kwargs)



def test_retrieved_payloads_refuse_methods_with_different_eligible_candidate_sets():
    owner,rankings,references,candidates,options=_retrieved_payload_case()
    for producer in rankings.values():
        for row in producer['rows']:
            row['retrieved_ids']=row['retrieved_ids'][:1]
            row['retrieved_endpoint_refs']=row['retrieved_endpoint_refs'][:1]
    row=rankings['raw']['rows'][0]
    row['excluded_examples']=[dict(id=key,reason='reference_source_family') for key in ('a','alias-a')]
    row['eligible_rows']=1
    kwargs=options();kwargs.update(ranking_depth=1,cutoffs=(1,))
    with pytest.raises(ValueError,match='candidate population'):
        owner.evaluate_complete_norm_retrieval_rankings(rankings,references,candidates,**kwargs)


# Canonical AST validity is independent of exact payload equality and legal meaning.
def _canonical_typed_norm_fixture(symbol="P", *, term=False):
    from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate, mk_constant
    from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature, many_sorted_fol_signature, atomic_sort
    if term:
        person = atomic_sort("Person")
        signature = many_sorted_fol_signature("fixture:term-signature", sorts=(person,), constants=(("alice", person),))
        root = mk_constant("fixture:term", "alice", person)
    else:
        signature = propositional_signature("fixture:signature", ("P", "Q"))
        root = mk_predicate("fixture:predicate", symbol)
    payload = _complete_norm_payload_fixture()
    payload["typed_expression"] = TypedExpression(expression_id="fixture:expression", root=root, signature=signature).to_dict()
    return payload


def _canonical_typed_norm_case(candidate=None, *, outcome="complete"):
    reference = _canonical_typed_norm_fixture()
    return dict(case_id="typed-case", reference=reference, candidate=deepcopy(reference) if candidate is None else candidate,
                outcome=outcome)


def test_complete_norm_typed_structure_positive_is_not_proof_or_semantics():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    report = owner.evaluate_complete_norm_typed_structure([_canonical_typed_norm_case()])
    assert report["denominator"] == report["canonical_reference_count"] == 1
    assert report["counts"] == {"canonical_formula": 1, "invalid_complete": 0, "not_checked": 0}
    for name in ("native_proof_verified", "semantic_equivalence_proved", "source_fidelity_proved",
                 "legal_admission_or_proof_authority", "candidate_repaired", "generator_invoked_by_scorer",
                 "syntax_or_logic_family_validity_verified"):
        assert report[name] is False


@pytest.mark.parametrize("damage", ["digest", "interface", "signature", "kind", "missing_digest", "extra", "coerced_id", "term"])
def test_complete_norm_typed_structure_rejects_malformed_or_noncanonical_complete(damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    candidate = _canonical_typed_norm_fixture(term=damage == "term")
    wire = candidate["typed_expression"]
    if damage == "digest": wire["content_digest"] = "0" * 64
    elif damage == "interface": wire["interface"] = "Unknown@1"
    elif damage == "signature": wire["signature"]["symbols"] = []
    elif damage == "kind": wire["root"]["kind"] = "unknown_root"
    elif damage == "missing_digest": wire.pop("content_digest")
    elif damage == "extra": wire["ignored_unknown_field"] = True
    elif damage == "coerced_id": wire["expression_id"] = 7
    before = deepcopy(candidate)
    report = owner.evaluate_complete_norm_typed_structure([_canonical_typed_norm_case(candidate)])
    assert report["counts"] == {"canonical_formula": 0, "invalid_complete": 1, "not_checked": 0}
    assert candidate == before and report["candidate_repaired"] is False
    if damage == "term": assert report["cases"][0]["reason"] == "non_formula_root"


@pytest.mark.parametrize("outcome", ["incomplete", "abstained", "unsupported", "invalid", "error"])
def test_complete_norm_typed_structure_noncomplete_preserves_denominator(outcome):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    candidate = _complete_norm_payload_fixture()  # Not a canonical TypedExpression.
    report = owner.evaluate_complete_norm_typed_structure([_canonical_typed_norm_case(candidate, outcome=outcome)])
    assert report["denominator"] == 1 and report["counts"] == {"canonical_formula": 0, "invalid_complete": 0, "not_checked": 1}


@pytest.mark.parametrize("damage", ["digest", "minimal", "term"])
def test_complete_norm_typed_structure_refuses_reference_without_filtering(damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    rows = [_canonical_typed_norm_case()]
    if damage == "digest": rows[0]["reference"]["typed_expression"]["content_digest"] = "0" * 64
    elif damage == "minimal": rows[0]["reference"] = _complete_norm_payload_fixture()
    else: rows[0]["reference"] = _canonical_typed_norm_fixture(term=True)
    with pytest.raises(ValueError, match="reference"):
        owner.evaluate_complete_norm_typed_structure(rows)


def test_complete_norm_typed_structure_validity_does_not_equal_semantic_equivalence():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    rows = [_canonical_typed_norm_case(_canonical_typed_norm_fixture("Q"))]
    assert owner.evaluate_complete_norm_typed_structure(rows)["counts"]["canonical_formula"] == 1
    assert owner.evaluate_complete_norm_payloads(rows)["metric_numerators"]["typed_expression_exact"] == 0


def test_complete_norm_typed_structure_detects_input_mutation(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression
    rows = [_canonical_typed_norm_case()];original = TypedExpression.from_dict
    def mutate(cls, offered):
        rows[0]["reference"]["interpretation_id"] = "changed-during-audit"
        return original(offered)
    monkeypatch.setattr(TypedExpression, "from_dict", classmethod(mutate))
    with pytest.raises(ValueError, match="changed during"):
        owner.evaluate_complete_norm_typed_structure(rows)


def test_unsupported_ordered_argument_facet_cannot_receive_complete_equivalence() -> None:
    from copy import deepcopy

    # Fictional proposed facet: the author intends ordered role/actor pairs.
    # The legacy raw-IR contract does not establish a supported denotation for
    # these added fields; this is not claimed to be canonical typed LegalIR.
    # No conjunction or IDs are reordered. Reused ancillary graph/reported
    # round-trip summaries are not independent authority for this new facet.
    reference = _reference_ir()
    reference["rules"][0]["predicate"] = "ProvideNotice"
    reference["rules"][0]["arguments"] = [
        {"role": "provider", "actor": "Agency"},
        {"role": "recipient", "actor": "Contractor"},
    ]
    candidate = deepcopy(reference)
    candidate["rules"][0]["arguments"] = [
        {"role": "provider", "actor": "Contractor"},
        {"role": "recipient", "actor": "Agency"},
    ]
    result = evaluate_legal_ir_semantic_equivalence(reference, candidate, family="deontic")
    gate = semantic_equivalence_promotion_gate(
        {"view_family_metrics": {"deontic": {"reference_ir": reference, "candidate_ir": reference}}},
        {"view_family_metrics": {"deontic": {"reference_ir": reference, "candidate_ir": candidate}}},
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )

    # The expected failure-closed contract here is unsupported/incomplete,
    # rather than a numeric semantic-distance claim for an unapproved shape.
    assert result.complete is False
    assert gate["accepted"] is False


def test_absent_reverse_round_trip_cannot_be_credited_from_structural_agreement() -> None:
    reference, candidate = _reference_ir(), _isomorphic_ir()
    del reference["round_trip"]
    del candidate["round_trip"]
    # No reverse-decompiler/recompiler observation is supplied. Matching raw
    # structures cannot substitute for that unavailable measurement.
    result = evaluate_legal_ir_semantic_equivalence(reference, candidate, family="deontic")
    gate = semantic_equivalence_promotion_gate(
        {"view_family_metrics": {"deontic": {
            "reference_ir": _reference_ir(), "candidate_ir": _isomorphic_ir(),
        }}},
        {"view_family_metrics": {"deontic": {"reference_ir": reference, "candidate_ir": candidate}}},
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )

    assert result.scores.get(DECOMPILER_ROUND_TRIP_PRESERVATION, 0.0) < 1.0
    assert gate["accepted"] is False


@pytest.mark.parametrize("damage", ["absent", "empty", "scalar", "false", "only_decompiled",
    "only_recompiled", "blank_decompiled", "blank_recompiled", "nested_result", "extra_field",
    "ambiguous_source", "ambiguous_container"])
def test_raw_round_trip_requires_both_reported_nonempty_observations(damage):
    reference, candidate = _reference_ir(), _isomorphic_ir()
    for value in (reference, candidate):
        if damage == "absent":
            del value["round_trip"]
        elif damage == "empty": value["round_trip"] = {}
        elif damage == "scalar": value["round_trip"] = "reported success"
        elif damage == "false": value["round_trip"] = False
        elif damage == "only_decompiled": del value["round_trip"]["recompiled_ir"]
        elif damage == "only_recompiled": del value["round_trip"]["decompiled"]
        elif damage == "blank_decompiled": value["round_trip"]["decompiled"] = " "
        elif damage == "blank_recompiled": value["round_trip"]["recompiled_ir"] = ""
        elif damage == "nested_result": value["round_trip"]["recompiled_ir"] = {"uninterpreted": "O(a,b)"}
        elif damage == "extra_field": value["round_trip"]["verified"] = True
        elif damage == "ambiguous_source": value["round_trip"]["decompiler"] = value["round_trip"]["decompiled"]
        else: value["roundtrip"] = deepcopy(value["round_trip"])
    result = evaluate_legal_ir_semantic_equivalence(reference, candidate, family="deontic")
    assert DECOMPILER_ROUND_TRIP_PRESERVATION not in result.scores
    assert DECOMPILER_ROUND_TRIP_PRESERVATION in result.missing_metrics
    assert not result.complete


@pytest.mark.parametrize("side", ["reference", "candidate"])
def test_one_sided_round_trip_evidence_is_not_a_complete_pair(side):
    reference, candidate = _reference_ir(), _isomorphic_ir()
    del (reference if side == "reference" else candidate)["round_trip"]
    result = evaluate_legal_ir_semantic_equivalence(reference, candidate)
    assert DECOMPILER_ROUND_TRIP_PRESERVATION not in result.scores
    assert DECOMPILER_ROUND_TRIP_PRESERVATION in result.missing_metrics


@pytest.mark.parametrize("shape", ["unknown_root", "unknown_rule", "nested_condition", "empty", "sequence", "text"])
def test_unknown_legacy_shapes_are_diagnostic_and_cannot_claim_typed_semantics(shape):
    value = _reference_ir()
    if shape == "unknown_root": value["typed_expression"] = {"binders": ["x"]}
    elif shape == "unknown_rule": value["rules"][0]["arguments"] = ["agency", "notice"]
    elif shape == "nested_condition": value["rules"][0]["condition"] = {"if": "emergency"}
    elif shape == "empty": value = {}
    elif shape == "sequence": value = [_reference_ir()]
    else: value = "O(agency, provide_notice)"
    result = evaluate_legal_ir_semantic_equivalence(value, deepcopy(value))
    assert not result.complete
    assert STRUCTURAL_EQUIVALENCE in result.missing_metrics
    assert OBLIGATION_EQUIVALENCE in result.missing_metrics
    assert result.detail["raw_input_coverage"]["reference_unsupported_paths"]
    assert result.detail["raw_input_coverage"]["canonical_typed_ir_validated"] is False
    assert result.detail["raw_input_coverage"]["legal_source_correspondence_verified"] is False


def test_recognized_actor_change_still_blocks_legacy_raw_promotion():
    reference, candidate = _reference_ir(), _isomorphic_ir()
    candidate["rules"][0]["subject"] = "Contractor"
    report = compare_legal_ir_semantic_equivalence(
        {"view_family_metrics": {"deontic": {"reference_ir": reference, "candidate_ir": reference}}},
        {"view_family_metrics": {"deontic": {"reference_ir": reference, "candidate_ir": candidate}}},
        families=("deontic",),
    )
    assert report.accepted is False
    assert report.family_results["deontic"].after.scores[OBLIGATION_EQUIVALENCE] < 1.0


@pytest.mark.parametrize("damage", ["missing_reverse", "unknown_arguments"])
def test_explicit_scores_cannot_launder_uncovered_raw_pair_evidence(damage):
    reference, candidate = _reference_ir(), _isomorphic_ir()
    if damage == "missing_reverse":
        del reference["round_trip"]
        del candidate["round_trip"]
    else:
        reference["rules"][0]["arguments"] = ["actor", "object"]
        candidate["rules"][0]["arguments"] = ["actor", "object"]
    payload = {"reference_ir": reference, "candidate_ir": candidate, **_all_semantic_scores()}
    result = semantic_equivalence_from_metrics(payload, family="deontic")
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] == 1.0
    assert not result.complete
    gate = semantic_equivalence_promotion_gate(
        {"view_family_metrics": {"deontic": _all_semantic_scores()}},
        {"view_family_metrics": {"deontic": payload}},
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )
    assert gate["accepted"] is False
    assert "deontic:semantic_equivalence_evidence_missing" in gate["block_reasons"]


@pytest.mark.parametrize("alias", ["roundtrip", "direct", "field_aliases"])
def test_explicit_legacy_observation_aliases_retain_reported_only_scope(alias):
    reference, candidate = _reference_ir(), _isomorphic_ir()
    for value in (reference, candidate):
        block = value.pop("round_trip")
        if alias == "roundtrip": value["roundtrip"] = block
        elif alias == "direct": value.update(block)
        else: value["round_trip"] = {"decompiler": block["decompiled"], "reconstructed_ir": block["recompiled_ir"]}
    result = evaluate_legal_ir_semantic_equivalence(reference, candidate)
    assert result.complete
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] == 1.0
    assert result.detail["round_trip_evidence"]["independently_recompiled"] is False
    assert result.detail["round_trip_evidence"]["authority"] == "caller_reported_observations_only"


def test_explicit_metrics_without_a_raw_pair_keep_the_existing_contract():
    report = compare_legal_ir_semantic_equivalence(
        {"view_family_metrics": {"deontic": _all_semantic_scores()}},
        {"view_family_metrics": {"deontic": _all_semantic_scores()}},
        families=("deontic",),
    )
    assert report.accepted


@pytest.mark.parametrize('version,valid,unsupported', [('v2', 2, 1), ('v3', 3, 0)])
def test_complete_candidate_shared_metrics_match_existing_evaluator(version, valid, unsupported):
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as bridge
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidates
    options, rows, known, _ = bridge._candidate_audit_fixture()
    profile = getattr(candidates, 'CANDIDATE_SYNTAX_PROFILE_' + version.upper())
    artifact = bridge._producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
        producer=lambda _: bridge._producer_exact_outputs(rows), candidate_syntax_profile=profile,
        known_candidate_inputs=known)
    examples = [dict(case_id=r['id'], reference=r['canonical_ir'], candidate=r['canonical_ir'], outcome='complete') for r in rows]
    report = owner.evaluate_complete_norm_candidate_syntax(examples,
        known_candidate_inputs=known, candidate_syntax_profile=profile)
    assert report == artifact.to_dict()['metrics']['complete_candidate_syntax']
    assert report['counts']['syntax_validated_unreviewed'] == valid
    assert report['counts']['unsupported_complete'] == unsupported


@pytest.mark.parametrize('which', ['examples', 'known'])
def test_complete_candidate_shared_metrics_fence_original_inputs(which, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as bridge
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as owner
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidates
    _, rows, known, profile = bridge._candidate_audit_fixture()
    examples = [dict(case_id=r['id'], reference=r['canonical_ir'], candidate=None, outcome='incomplete') for r in rows]
    original = candidates.validate_complete_norm_candidate_v2
    def mutate(*args, **kwargs):
        if which == 'examples': examples[0]['outcome'] = 'error'
        else: known[rows[0]['id']]['known_source_binding']['document_revision'] = 'fixture:mutated-during-metrics'
        return original(*args, **kwargs)
    monkeypatch.setattr(candidates, 'validate_complete_norm_candidate_v2', mutate)
    with pytest.raises(ValueError, match='changed during'):
        owner.evaluate_complete_norm_candidate_syntax(examples,
            known_candidate_inputs=known, candidate_syntax_profile=profile)

@pytest.mark.parametrize("damage", ["actor", "proof_obligation_ids"])
def test_explicit_perfect_scores_cannot_launder_covered_raw_pair_evidence(damage):
    from copy import deepcopy

    reference, candidate = _reference_ir(), _isomorphic_ir()
    if damage == "actor":
        candidate["rules"][0]["subject"] = "Contractor"
    else:
        candidate["rules"][0]["proof_obligation_ids"] = ["po-other"]
    original_inputs = deepcopy((reference, candidate))

    measured = evaluate_legal_ir_semantic_equivalence(
        reference, candidate, family="deontic",
    )
    assert measured.complete is True
    assert measured.missing_metrics == ()
    coverage = measured.detail["raw_input_coverage"]
    assert coverage["reference_unsupported_paths"] == []
    assert coverage["candidate_unsupported_paths"] == []
    if damage == "actor":
        assert measured.scores[OBLIGATION_EQUIVALENCE] < 1.0
    else:
        assert measured.raw_deltas[PROOF_OBLIGATION_DELTA] > 0.0
        assert measured.scores[PROOF_OBLIGATION_DELTA_SCORE] < 1.0

    baseline = {"view_family_metrics": {"deontic": {
        "reference_ir": reference, "candidate_ir": reference,
    }}}
    raw_payload = {"reference_ir": reference, "candidate_ir": candidate}
    unspoofed = compare_legal_ir_semantic_equivalence(
        baseline,
        {"view_family_metrics": {"deontic": raw_payload}},
        families=("deontic",),
    )
    assert unspoofed.accepted is False

    # Only the candidate's caller-reported scores and proof delta are spoofed.
    # A covered, measured failure must retain its observations and block gate.
    report = compare_legal_ir_semantic_equivalence(
        baseline,
        {"view_family_metrics": {"deontic": {
            **raw_payload, **_all_semantic_scores(),
        }}},
        families=("deontic",),
    )
    observed = report.family_results["deontic"].after
    assert report.to_dict()["hard_promotion_gate"] is True
    assert (reference, candidate) == original_inputs
    assert {
        "accepted": report.accepted,
        "scores": dict(observed.scores),
        "raw_deltas": dict(observed.raw_deltas),
        "missing_metrics": observed.missing_metrics,
    } == {
        "accepted": False,
        "scores": dict(measured.scores),
        "raw_deltas": dict(measured.raw_deltas),
        "missing_metrics": measured.missing_metrics,
    }


@pytest.mark.parametrize("ranking_depth", [4, 16])
def test_retrieved_payloads_score_all_abstentions_when_depth_exceeds_the_bank(ranking_depth):
    owner, rankings, references, candidates, options = _retrieved_payload_case()
    for producer in rankings.values():
        for row in producer["rows"]:
            row.update(
                status="abstained",
                abstention_reasons=["insufficient_permitted_training_examples"],
                context=None,
                retrieved_ids=[],
            )
            del row["retrieved_endpoint_refs"]
    kwargs = options()
    kwargs.update(ranking_depth=ranking_depth, cutoffs=(1, 3, ranking_depth))
    report = owner.evaluate_complete_norm_retrieval_rankings(rankings, references, candidates, **kwargs)
    assert report["ranking_depth"] == ranking_depth
    assert report["reference_count"] == 2
    assert report["candidate_view_count"] == 3
    assert report["semantic_relevance_metrics"] is report["legal_applicability_metrics"] is None
    for result in report["methods"].values():
        assert result["query_count"] == result["abstention_count"] == 2
        assert result["retrieved_count"] == 0
        for cutoff in result["cutoffs"].values():
            assert cutoff["denominator"] == 2
            assert not any(cutoff["metric_numerators"].values())
            assert cutoff["eligible_index_match_counts"]["full_nine_payload_exact"] == 2
            assert cutoff["conditional_exact_match_rates"]["full_nine_payload_exact"] == 0


@pytest.mark.parametrize(
    ("ranking_depth", "all_abstain", "error"),
    [
        (4, False, "fixed ranking depth or explicit abstention"),
        (17, True, "bounded cutoff configuration and ranking depth"),
    ],
)
def test_retrieved_payloads_reject_short_rankings_or_unsupported_depth(ranking_depth, all_abstain, error):
    owner, rankings, references, candidates, options = _retrieved_payload_case()
    if all_abstain:
        for producer in rankings.values():
            for row in producer["rows"]:
                row.update(status="abstained", retrieved_ids=[], retrieved_endpoint_refs=[])
    kwargs = options()
    kwargs.update(ranking_depth=ranking_depth, cutoffs=(1, 3, ranking_depth))
    with pytest.raises(ValueError, match=error):
        owner.evaluate_complete_norm_retrieval_rankings(rankings, references, candidates, **kwargs)
