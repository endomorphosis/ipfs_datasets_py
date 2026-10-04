"""Pure metadata/scoring controls; renderers are inert and no owners are loaded."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_SOURCE = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/ir_legal_text_roundtrip.py"
_SPEC = importlib.util.spec_from_file_location("detached_legal_roundtrip_controls", _SOURCE)
scorer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scorer)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def clone(value):
    return json.loads(raw(value))


def rule(actor="registrar"):
    return {"rules": [{"modality": "O", "actor": actor, "action": "approve", "object": "notice",
                       "conditions": [], "exceptions": [], "temporal": []}]}


@pytest.fixture
def bundle(tmp_path):
    texts = ["The registrar must approve the notice.", "The registrar is required to approve the notice."]
    rows = []
    for index, text in enumerate(texts):
        vector = [1.0] + [0.0] * 383
        rows.append({"id": "row-" + str(index), "source_text": text,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "embedding": vector,
            "embedding_sha256": digest(vector), "embedding_token_ids_sha256": "a" * 64,
            "group_id": "group-one", "split": "test", "target": rule(), "wording_style": index,
            "reference_metadata": {"authored": True}, "proof_authority": False, "source_semantics_verified": False})
    corpus = {"rows": rows, "source_embeddings": {"model_id": "thenlper/gte-small", "dimension": 384,
        "revision": "original-producer-declaration"}}
    path = tmp_path / "test.json"
    state = {"path": path, "corpus": corpus}

    def repin():
        payload = raw(corpus)
        path.write_bytes(payload)
        state["pin"] = {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        state["inputs"] = [{key: clone(row[key]) for key in ("id", "source_text", "embedding")} for row in rows]
        state["report"] = {"schema": "shared-source-384-autoencoder/v2", "domain_id": "legal_ir", "dimension": 384,
            **{key: False for key in scorer._FALSE}, "rows": []}
        for row in rows:
            state["report"]["rows"].append({"id": row["id"], "source_sha256": row["source_sha256"],
                "status": "unqualified_candidate", "reason": None, "candidate_ir": clone(row["target"]),
                "generated_tokens": ["{"], "ended": True, "reconstructed_embedding": clone(row["embedding"]),
                "weight_ablation": None, "weights_sha256": "b" * 64, "target_access": False,
                "teacher_forcing": False, "continue_planning": True, **{key: False for key in scorer._FALSE}})

    state["repin"] = repin
    repin()
    return state


def score(bundle, **options):
    return scorer.score_legal_original_text_roundtrip(bundle["pin"], bundle["inputs"], bundle["report"], **options)


def render_first(predicted, request_id):
    return {"status": "rendered", "text": "The registrar must approve the notice.", "reason": None}


def test_ir_exactness_does_not_manufacture_text_or_teacher_qualification(bundle):
    result = score(bundle)
    assert result["counts"]["exact_ir"] == 2
    assert result["counts"]["exact_original_utf8"] is None
    assert result["rendering_task"] == "not_requested"
    assert result["valid_evaluation"] and result["operational_complete"]
    assert result["native_grammar_verified"] is False
    assert result["producer_execution_authenticated"] is False
    assert result["independent_holdout_qualified"] is False
    assert result["teacher_qualified"] is False
    assert result["model_inference_executed_by_scorer"] is False
    assert result["learned_original_prose_head_evaluated"] is False
    assert result["retained_source_restoration_evaluated"] is False


def test_rendering_and_surface_collision_are_separate_from_perfect_ir(bundle):
    result = score(bundle, render_canonical=True, renderer=render_first)
    assert result["counts"]["attempted"] == result["counts"]["exact_ir"] == 2
    assert result["counts"]["rendered"] == 2
    assert result["counts"]["exact_original_utf8"] == 1
    assert result["rates"]["exact_original_utf8"] == .5
    surface = result["surface_information"]
    assert surface["semantic_group_count"] == 1
    assert surface["semantic_ir_only_single_output_exact_source_ceiling_rate"] == .5
    assert surface["is_global_model_limit"] is False
    assert surface["applies_to_learned_surface_or_residual_input"] is False
    assert result["renderer_behavior_authenticated"] is False
    assert result["renderer_uses_model"] is None


def test_renderer_gets_only_detached_predicted_ir_and_constant_non_source_id(bundle):
    before = raw((bundle["pin"], bundle["inputs"], bundle["report"], bundle["corpus"]))
    calls = []

    def renderer(predicted, request_id):
        assert set(predicted) == {"rules"}
        assert request_id == "legal-original-text-roundtrip"
        assert "source_text" not in predicted and "embedding" not in predicted and "id" not in predicted
        calls.append(clone(predicted))
        predicted["rules"][0]["actor"] = "changed"
        return render_first(None, None)

    result = score(bundle, render_canonical=True, renderer=renderer)
    assert len(calls) == 2 and result["counts"]["exact_ir"] == 2
    assert raw((bundle["pin"], bundle["inputs"], bundle["report"], bundle["corpus"])) == before


def test_text_whitespace_comparison_is_explicit_and_not_literal_utf8(bundle):
    bundle["corpus"]["rows"][:] = bundle["corpus"]["rows"][:1]
    row = bundle["corpus"]["rows"][0]
    row["source_text"] = "The  registrar\tmust approve the notice.\n"
    row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
    bundle["repin"]()
    result = score(bundle, render_canonical=True, renderer=render_first)
    assert result["counts"]["exact_original_utf8"] == 0
    assert result["counts"]["whitespace_collapsed_exact"] == 1
    rendered = result["rows"][0]["rendering"]
    assert rendered["character_edit"]["distance"] > 0
    assert rendered["whitespace_token_edit"]["distance"] == 0


def test_missing_prediction_stays_in_all_attempted_denominators(bundle):
    bundle["report"]["rows"].pop()
    result = score(bundle, render_canonical=True, renderer=render_first)
    assert result["counts"]["attempted"] == 2 and result["counts"]["missing"] == 1
    assert result["rates"]["exact_ir"] == .5 and result["rates"]["exact_original_utf8"] == .5
    assert result["coverage"]["missing_ids"] == ["row-1"]
    assert result["valid_evaluation"] is False


def test_duplicate_matching_output_never_receives_best_occurrence_credit(bundle):
    duplicate = clone(bundle["report"]["rows"][0])
    duplicate["candidate_ir"] = rule("other")
    bundle["report"]["rows"].append(duplicate)
    result = score(bundle, render_canonical=True, renderer=render_first)
    assert result["counts"]["duplicate"] == 1 and result["counts"]["exact_ir"] == 1
    assert result["rows"][0]["rendering"]["status"] == "unavailable"
    assert result["coverage"]["duplicate_ids"] == {"row-0": 2}


def test_unexpected_and_invalid_ids_invalidate_coverage_without_changing_denominator(bundle):
    bundle["report"]["rows"].append({"id": "unexpected"})
    bundle["report"]["rows"].append({"id": 5})
    result = score(bundle)
    assert result["counts"]["attempted"] == 2 and result["counts"]["exact_ir"] == 2
    assert result["coverage"]["unexpected_ids"] == ["unexpected"]
    assert result["coverage"]["invalid_id_row_indices"] == [3]
    assert result["valid_evaluation"] is False


def test_output_order_is_joined_by_id(bundle):
    bundle["report"]["rows"].reverse()
    assert score(bundle)["counts"]["exact_ir"] == 2


@pytest.mark.parametrize("change", ["teacher", "target", "source", "extra_gold", "width", "bool_vector", "weights", "continue"])
def test_output_provenance_and_closed_fields_refuse_leaky_or_mismatched_rows(bundle, change):
    row = bundle["report"]["rows"][0]
    if change == "teacher": row["teacher_forcing"] = True
    elif change == "target": row["target_access"] = True
    elif change == "source": row["source_sha256"] = "c" * 64
    elif change == "extra_gold": row["target"] = rule()
    elif change == "width": row["reconstructed_embedding"].pop()
    elif change == "bool_vector": row["reconstructed_embedding"][0] = True
    elif change == "weights": row["weights_sha256"] = None
    else: row["continue_planning"] = False
    result = score(bundle, render_canonical=True, renderer=render_first)
    assert result["counts"]["refused"] == 1 and result["counts"]["exact_ir"] == 1
    assert result["prediction_provenance_valid"] is False
    assert result["valid_evaluation"] is False


@pytest.mark.parametrize("change", ["truncated", "extra_facet", "multiple_rules", "invalid_modality", "empty_atom", "no_ir", "bad_status"])
def test_invalid_surface_candidates_are_refused_and_not_rendered(bundle, change):
    row = bundle["report"]["rows"][0]
    if change == "truncated": row["ended"] = False
    elif change == "extra_facet": row["candidate_ir"]["rules"][0]["source_text"] = "gold"
    elif change == "multiple_rules": row["candidate_ir"]["rules"].append(clone(row["candidate_ir"]["rules"][0]))
    elif change == "invalid_modality": row["candidate_ir"]["rules"][0]["modality"] = "X"
    elif change == "empty_atom": row["candidate_ir"]["rules"][0]["actor"] = ""
    elif change == "no_ir": row.update(status="fail_open_invalid_output", candidate_ir=None)
    else: row["status"] = "qualified"
    calls = []
    def renderer(predicted, request_id):
        calls.append(predicted)
        return render_first(predicted, request_id)
    result = score(bundle, render_canonical=True, renderer=renderer)
    assert result["counts"]["refused"] == 1 and len(calls) == 1
    assert result["counts"]["rendered"] == 1 and result["rates"]["exact_ir"] == .5


@pytest.mark.parametrize("rendered", [None, {"status": "rendered", "text": "", "reason": None},
    {"status": "rendered", "text": "x" * 16385, "reason": None},
    {"status": "refused", "text": "source", "reason": "bad"},
    {"status": "rendered", "text": "short", "reason": None, "gold": "leak"}])
def test_renderer_malformed_or_overlong_surface_is_retained_as_failure(bundle, rendered):
    result = score(bundle, render_canonical=True, renderer=lambda ir, request: rendered)
    assert result["counts"]["exact_ir"] == 2
    assert result["counts"]["rendering_refused"] == 2
    assert result["rates"]["exact_original_utf8"] == 0
    assert result["operational_complete"] is False


def test_ordinary_renderer_failure_is_per_row_and_preserves_ir(bundle):
    def renderer(ir, request):
        raise OSError("do not expose source details")
    result = score(bundle, render_canonical=True, renderer=renderer)
    assert result["counts"]["exact_ir"] == 2 and result["counts"]["rendering_refused"] == 2
    assert all(row["rendering"]["reason"] == "OSError" for row in result["rows"])


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_process_control_renderer_exceptions_propagate(bundle, error):
    def renderer(ir, request): raise error()
    with pytest.raises(error): score(bundle, render_canonical=True, renderer=renderer)


def test_global_edit_budget_reports_null_distance_without_false_zero(bundle):
    result = score(bundle, render_canonical=True, renderer=render_first, max_edit_cells=1)
    assert result["counts"]["exact_original_utf8"] == 1
    assert result["edit_budget"]["used_cells"] == 0
    assert all(row["rendering"]["character_edit"]["status"] == "cell_budget_exhausted" for row in result["rows"])
    assert all(row["rendering"]["character_edit"]["distance"] is None for row in result["rows"])


def test_edit_distance_is_exact_and_global_budget_is_consumed():
    budget = [20]
    assert scorer._distance("kitten", "sitting", budget)["status"] == "cell_budget_exhausted"
    assert budget == [20]
    assert scorer._distance("abc", "axc", budget)["distance"] == 1 and budget == [11]
    assert scorer._distance([], ["word"], budget)["distance"] == 1 and budget == [11]


def test_empirical_surface_ceiling_handles_repeated_identical_sources_and_subsets(bundle):
    third = clone(bundle["corpus"]["rows"][0]); third["id"] = "row-2"
    bundle["corpus"]["rows"].append(third); bundle["repin"]()
    result = score(bundle)
    assert result["surface_information"]["semantic_ir_only_single_output_exact_source_ceiling_rate"] == 2 / 3
    bundle["inputs"] = bundle["inputs"][:1]; bundle["report"]["rows"] = bundle["report"]["rows"][:1]
    assert score(bundle)["surface_information"]["semantic_ir_only_single_output_exact_source_ceiling_rate"] == 1


@pytest.mark.parametrize("change", ["source", "vector", "duplicate", "gold", "unknown", "bool_width"])
def test_captured_inputs_require_exact_target_free_cache_association(bundle, change):
    if change == "source": bundle["inputs"][0]["source_text"] += "different"
    elif change == "vector": bundle["inputs"][0]["embedding"][1] = .5
    elif change == "duplicate": bundle["inputs"][1] = clone(bundle["inputs"][0])
    elif change == "gold": bundle["inputs"][0]["target"] = rule()
    elif change == "unknown": bundle["inputs"][0]["id"] = "unknown"
    else: bundle["inputs"][0]["embedding"][0] = True
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)


@pytest.mark.parametrize("change", ["source_hash", "vector_hash", "row_extra", "target_shape", "duplicate", "authority", "envelope"])
def test_authenticated_but_incompatible_corpus_is_rejected(bundle, change):
    row = bundle["corpus"]["rows"][0]
    if change == "source_hash": row["source_sha256"] = "f" * 64
    elif change == "vector_hash": row["embedding_sha256"] = "f" * 64
    elif change == "row_extra": row["encoder_executed"] = True
    elif change == "target_shape": row["target"]["rules"] = []
    elif change == "duplicate": bundle["corpus"]["rows"][1]["id"] = row["id"]
    elif change == "authority": row["proof_authority"] = True
    else: bundle["corpus"]["full_document"] = True
    bundle["repin"]()
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)


def test_corpus_pin_hash_and_bytes_are_checked(bundle):
    bundle["path"].write_bytes(bundle["path"].read_bytes() + b" ")
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)


def test_symlink_corpus_is_not_accepted_as_an_original_file(bundle, tmp_path):
    alias = tmp_path / "alias.json"; alias.symlink_to(bundle["path"])
    bundle["pin"]["path"] = str(alias)
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)


def test_late_corpus_change_by_renderer_is_refused(bundle):
    def renderer(ir, request):
        bundle["path"].write_bytes(bundle["path"].read_bytes() + b" ")
        return render_first(ir, request)
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle, render_canonical=True, renderer=renderer)


@pytest.mark.parametrize("payload", [b'{"rows":[],"rows":[],"source_embeddings":{}}',
    b'{"rows":[],"source_embeddings":{"float":1e999}}'])
def test_duplicate_json_and_overflowed_float_refuse_even_with_matching_pin(bundle, payload):
    bundle["path"].write_bytes(payload)
    bundle["pin"] = {"path": str(bundle["path"]), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)


@pytest.mark.parametrize("options", [{"max_edit_cells": True}, {"max_edit_cells": 0},
    {"max_edit_cells": 4_000_001}, {"max_reference_bytes": 0}, {"render_canonical": "yes"}, {"renderer": render_first}])
def test_invalid_or_unselected_execution_budgets_refuse_before_render(bundle, options):
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle, **options)


def test_candidate_report_with_foreign_schema_cannot_get_any_credit(bundle):
    bundle["report"]["schema"] = "published-parser-assisted-package"
    result = score(bundle)
    assert result["report_envelope_valid"] is False and result["counts"]["refused"] == 2
    assert result["counts"]["exact_ir"] == 0


def test_huge_integer_vector_is_rejected_without_uncaught_overflow(bundle):
    bundle["inputs"][0]["embedding"][0] = 10 ** 400
    with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)
