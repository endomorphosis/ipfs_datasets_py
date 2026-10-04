"""Real source parsing, independent reference diagnostics and evidence limits."""
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_evaluation.py"
spec = importlib.util.spec_from_file_location("alignment_richer_evaluation_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)

SOURCE = "Agency shall file notice within 48 hours if public interest unless emergency."


def vocabulary():
    return {"actors": ["agency", "company_a"], "actions": ["file", "submit"],
            "objects": ["backup_report", "notice"], "qualifiers": ["emergency", "public_interest", "within_48_hours"]}


def target(modality="O", actor="agency", conditions=None, exceptions=None, temporal=None):
    return {"rules": [{"modality": modality, "actor": actor, "action": "file", "object": "notice",
                       "conditions": ["public_interest"] if conditions is None else conditions,
                       "exceptions": ["emergency"] if exceptions is None else exceptions,
                       "temporal": ["within_48_hours"] if temporal is None else temporal}]}


@pytest.fixture
def construction():
    return subject.construct_source(SOURCE, vocabulary(), request_id="authored-test")


def reseal(value):
    value["content_sha256"] = subject._digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def test_lazy_import_and_real_source_execution_load_no_optional_models():
    code = """
import importlib.abc
import importlib.util
import sys
class RejectModels(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name.split('.')[0] in {'torch','transformers','sentence_transformers','spacy'}:
            raise AssertionError('optional model imported')
sys.meta_path.insert(0,RejectModels())
spec=importlib.util.spec_from_file_location('lazy_richer',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
v={'actors':['agency'],'actions':['file'],'objects':['notice'],'qualifiers':['public_interest']}
r=module.construct_source('Agency shall file notice if public interest.',v,request_id='lazy-native')
assert r['construction_status']=='success'
assert r['model_call_count']==0
assert 'torch' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(MODULE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_actual_source_compiler_preserves_condition_exception_temporal(construction):
    assert construction["canonical_ir"] == target()
    assert construction["construction_status"] == "success"
    assert construction["schema_acceptance"] is True
    assert construction["schema_check"]["operation"] == "CanonicalRoundTripIR.from_dict"
    assert construction["schema_check"]["jsonschema_validator_run"] is False
    assert construction["roundtrip"]["exact_ir"] is True
    assert construction["roundtrip"]["rendered_text"] == "Agency must file notice within 48 hours if public interest unless emergency."
    assert construction["roundtrip"]["success_means"] == "stage_completion_only"
    native = construction["roundtrip"]["native_result"]
    assert native["completed_stages"] == ["l1_compile", "t1_decompile", "l2_compile"]
    assert all(record["status"] == "unrun" for record in construction["proof_scopes"].values())
    assert construction["qualified"] is False and construction["source_fidelity_established"] is False


def test_source_and_train_vocabulary_only_reach_compiler_before_posthoc_reference(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler

    captured, original = [], TypedDeonticCanonicalCompiler.compile
    def capture(self, request):
        captured.append({"text": request.source_text, "vocabulary": request.atom_vocabulary.to_dict(),
                         "config": dict(request.config), "partial": request.allow_explicit_partial})
        return original(self, request)
    monkeypatch.setattr(TypedDeonticCanonicalCompiler, "compile", capture)
    frozen = vocabulary()
    construction = subject.construct_source(SOURCE, frozen, request_id="capture-source")
    assert len(captured) == 2
    assert captured[0]["text"] == SOURCE and captured[1]["text"] == construction["roundtrip"]["rendered_text"]
    assert all(record["vocabulary"] == frozen and record["config"] == {} and record["partial"] is False for record in captured)
    original_calls = deepcopy(captured)
    score = subject.score_authored_reference(construction, target(actor="unseen_authored_actor"))
    assert captured == original_calls and "unseen_authored_actor" not in frozen["actors"]
    assert score["exact_ir"] is False and score["core_tuple_counts"]["fn"] == 1
    with pytest.raises(TypeError):
        subject.construct_source(SOURCE, frozen, request_id="oracle-reject", authored_target=target())


def test_independent_reference_agreement_is_separate_from_roundtrip_and_proof(construction):
    exact = subject.score_authored_reference(construction, target())
    assert exact["exact_ir"] is True and exact["reference_read_after_construction"] is True
    assert all(record["tp"] == 1 and record["fp"] == record["fn"] == 0 for record in exact["typed_qualifier_counts"].values())
    altered = subject.score_authored_reference(construction, target(conditions=["application_complete"]))
    assert altered["roundtrip_exact_ir"] is True and altered["exact_ir"] is False
    assert altered["typed_qualifier_counts"]["conditions"] == {"tp": 0, "fp": 1, "fn": 1, "precision": 0., "recall": 0., "exact": False}
    assert altered["core_tuple_counts"]["exact"] is True
    assert altered["semantic_equivalence_checked"] is False and altered["source_fidelity_established"] is False


def test_polarity_mismatch_blocks_scoped_qualifier_credit(construction):
    score = subject.score_authored_reference(construction, target(modality="F"))
    assert score["core_tuple_counts"]["tp"] == 0
    assert all(record["tp"] == 0 and record["fp"] == record["fn"] == 1 for record in score["typed_qualifier_counts"].values())
    assert all(record["exact"] for record in score["unscoped_qualifier_presence"].values())
    prohibition = subject.construct_source(SOURCE.replace("shall", "must not"), vocabulary(), request_id="native-prohibition")
    assert prohibition["canonical_ir"] == target(modality="F")


def test_cross_facet_migrations_are_reported_without_rewriting_candidate(construction):
    before = subject._raw(construction)
    score = subject.score_authored_reference(construction, target(conditions=[], exceptions=["emergency", "public_interest"]))
    assert score["cross_facet_migrations"] == [{"core": {"modality": "O", "actor": "agency", "action": "file", "object": "notice"},
        "atom": "public_interest", "reference_facet": "exceptions", "proposed_facets": ["conditions"], "missing_count": 1}]
    assert score["typed_qualifier_counts"]["conditions"]["fp"] == 1
    assert score["typed_qualifier_counts"]["exceptions"]["fn"] == 1
    assert subject._raw(construction) == before


def test_multiset_diagnostics_do_not_claim_rule_coassociation_equivalence():
    proposed = {"rules": [target(conditions=["a"], exceptions=["d"])["rules"][0],
                           target(conditions=["c"], exceptions=["b"])["rules"][0]]}
    reference = {"rules": [target(conditions=["a"], exceptions=["b"])["rules"][0],
                           target(conditions=["c"], exceptions=["d"])["rules"][0]]}
    diagnostics = subject._ir_diagnostics(proposed, reference)
    assert all(record["exact"] for record in diagnostics["typed_qualifier_counts"].values())
    assert diagnostics["exact_ir"] is False and diagnostics["full_rule_counts"]["tp"] == 0
    assert diagnostics["qualifier_rule_coassociation"] == "checked_by_full_rule_and_exact_ir_only"


def test_context_required_case_abstains_even_when_query_could_parse_and_premise_is_bound(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler

    calls, original = [], TypedDeonticCanonicalCompiler.compile
    def capture(self, request):
        calls.append(request.source_text)
        return original(self, request)
    monkeypatch.setattr(TypedDeonticCanonicalCompiler, "compile", capture)
    premise = "Company A shall submit backup report."
    result = subject.construct_source(SOURCE, vocabulary(), request_id="context-case",
        context_premises=({"id": "declared-role", "text": premise},), requires_context_resolution=True)
    assert calls == [premise]
    assert result["construction_status"] == "unavailable" and result["canonical_ir"] is None
    assert result["roundtrip"]["exact_ir"] is None and result["roundtrip"]["native_result"] is None
    assert result["context_compilations"][0]["compiler_result"]["status"] == "success"
    assert result["input_policy"]["context_consumed_by_constructor"] is False
    assert subject.score_authored_reference(result, target())["exact_ir"] is False


def test_optional_premises_are_separate_and_not_inserted_into_query_ir():
    result = subject.construct_source(SOURCE, vocabulary(), request_id="premise-diagnostic",
        context_premises=({"id": "separate-source", "text": "Company A shall submit backup report."},))
    assert result["canonical_ir"] == target()
    assert result["context_compilations"][0]["applied_to_query_construction"] is False
    assert result["context_compilations"][0]["compiler_result"]["canonical_ir"] != result["canonical_ir"]


def test_actual_unsupported_procedure_abstention_is_not_patched_to_gold():
    atoms = vocabulary()
    atoms["qualifiers"] = ["application_complete", "court_order", "within_48_hours"]
    source = "Agency shall file notice within 48 hours if application complete unless court order."
    construction = subject.construct_source(source, atoms, request_id="unsupported-procedure")
    assert construction["construction_status"] == "abstained" and construction["canonical_ir"] is None
    native = construction["roundtrip"]["native_result"]
    assert native["stage_results"]["l1"]["unsupported_semantics"][0]["code"] == "typed_deontic.unrepresented_procedure"
    score = subject.score_authored_reference(construction, target(conditions=["application_complete"], exceptions=["court_order"]))
    assert score["exact_ir"] is False and score["typed_qualifier_counts"]["conditions"]["fn"] == 1
    assert construction["native_projection"]["status"] == "unrun"


def test_null_reference_checks_operational_no_candidate_without_certifying_legal_meaning():
    result = subject.construct_source("A descriptive paragraph with no normative rule.", vocabulary(), request_id="non-norm")
    score = subject.score_authored_reference(result, None)
    assert result["canonical_ir"] is None and score["negative_expectation_met"] is True
    assert score["negative_semantics_certified"] is False
    positive = subject.construct_source(SOURCE, vocabulary(), request_id="false-positive")
    assert subject.score_authored_reference(positive, None)["negative_expectation_met"] is False


def test_saved_native_bridge_artifact_is_bound_and_transport_gaps_are_explicit(construction):
    projection = construction["native_projection"]
    assert projection["status"] == "executed" and projection["proofs_executed"] is False
    assert projection["artifact_sha256"] == subject._digest(projection["artifact"])
    assert projection["artifact"]["bridge_cid"] == projection["bridge_cid"]
    assert projection["scope"] == "typed_bridge_transport_with_disclosed_gaps"
    assert any("proof" in record["construct_id"] for record in projection["unsupported_constructs"])
    assert projection["domain_logic_slice"]["disposition"] == "explicit_partial"


def test_native_projection_failure_remains_unavailable_without_invalidating_actual_source_compile(monkeypatch):
    from ipfs_datasets_py.logic.bridge import canonical

    def unavailable(*args, **kwargs):
        raise RuntimeError("unavailable test adapter")
    monkeypatch.setattr(canonical, "wrap_compiler_result", unavailable)
    result = subject.construct_source(SOURCE, vocabulary(), request_id="unavailable-projection")
    assert result["canonical_ir"] == target() and result["native_projection"]["status"] == "unavailable"
    assert subject.score_authored_reference(result, target())["exact_ir"] is True


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(qualified=True),
    lambda value: value.update(schema_acceptance=False),
    lambda value: value.update(construction_status="proved"),
    lambda value: value["canonical_ir"]["rules"][0].update(actor="oracle_actor"),
    lambda value: value["roundtrip"].update(exact_ir=False),
    lambda value: value["roundtrip"].update(rendered_text="Copied gold sentence."),
    lambda value: value["input_policy"].update(context_consumed_by_constructor=True),
    lambda value: value["native_projection"].update(proofs_executed=True),
    lambda value: value["native_projection"].update(artifact_sha256="0"*64),
    lambda value: value["proof_scopes"]["kernel_proof"].update(status="proved"),
    lambda value: value["proof_scopes"].pop("native_proof"),
])
def test_resealed_corruption_cannot_promote_or_replace_native_evidence(construction, mutation):
    value = deepcopy(construction)
    mutation(value)
    reseal(value)
    with pytest.raises(ValueError):
        subject.score_authored_reference(value, target())


def test_content_corruption_is_rejected_before_reference_scoring(construction):
    value = deepcopy(construction)
    value["source_sha256"] = "0"*64
    with pytest.raises(ValueError, match="digest"):
        subject.score_authored_reference(value, target())


@pytest.mark.parametrize("source", ["", " ", True, "x"*(subject.MAX_SOURCE_CHARS+1)])
def test_source_inputs_are_bounded_nonblank_text(source):
    with pytest.raises(ValueError):
        subject.construct_source(source, vocabulary(), request_id="invalid-source")


@pytest.mark.parametrize("premises", [None, [{"id":"x","text":SOURCE,"target":target()}],
                                       [{"id":"x","text":SOURCE},{"id":"x","text":SOURCE}],
                                       [{"id":"x","text":""}], [{"id":True,"text":SOURCE}]])
def test_context_is_closed_explicit_text_with_unique_ids(premises):
    with pytest.raises(ValueError):
        subject.construct_source(SOURCE, vocabulary(), request_id="invalid-context", context_premises=premises)


def test_records_and_scores_are_finite_json_and_reference_is_not_modified(construction):
    reference = target()
    before = deepcopy(reference)
    score = subject.score_authored_reference(construction, reference)
    assert reference == before
    assert json.loads(json.dumps(construction, allow_nan=False)) == construction
    assert json.loads(json.dumps(score, allow_nan=False)) == score
    assert construction["vocabulary_origin"] == "caller_provenance_required_no_fit_here"
