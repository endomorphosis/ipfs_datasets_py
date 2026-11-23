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
    try:
        with pytest.raises(scorer.LegalTextRoundTripError): score(bundle)
    finally:
        alias.unlink()


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

def test_joint_metrics_are_unmeasured_without_rendering(bundle):
    result = score(bundle)
    assert result["counts"]["exact_ir"] == 2
    assert result["counts"]["joint_ir_original_utf8_exact"] is None
    assert result["rates"]["joint_ir_original_utf8_exact"] is None
    assert result["ir_text_joint_counts"] is None
    assert all(row["joint_ir_original_utf8_exact"] is None for row in result["rows"])


def test_discordant_ir_and_text_marginals_do_not_form_a_joint_success(bundle):
    bundle["report"]["rows"][1]["candidate_ir"] = rule("clerk")

    def renderer(predicted, request_id):
        # Authored diagnostic outputs exercise a renderer that can return the
        # original surface even when its supplied semantic IR is wrong.
        text = ("The registrar is required to approve the notice."
                if predicted["rules"][0]["actor"] == "clerk" else "Different wording.")
        return {"status": "rendered", "text": text, "reason": None}

    result = score(bundle, render_canonical=True, renderer=renderer)
    assert result["counts"]["exact_ir"] == result["counts"]["exact_original_utf8"] == 1
    assert result["rates"]["exact_ir"] == result["rates"]["exact_original_utf8"] == .5
    assert result["counts"]["joint_ir_original_utf8_exact"] == 0
    assert result["rates"]["joint_ir_original_utf8_exact"] == 0
    assert [row["joint_ir_original_utf8_exact"] for row in result["rows"]] == [False, False]
    assert result["ir_text_joint_counts"] == {"denominator": "all_captured_input_rows", "total": 2,
        "both_exact": 0, "ir_only_exact": 1, "text_only_exact": 1, "neither_exact": 0}


def test_ir_text_joint_table_keeps_all_four_cells_and_same_example_success(bundle):
    rows = bundle["corpus"]["rows"]
    for text in ("The clerk must approve the notice.", "The clerk is required to approve the notice."):
        row = clone(rows[0])
        row.update(id="row-" + str(len(rows)), source_text=text,
                   source_sha256=hashlib.sha256(text.encode()).hexdigest(), target=rule("clerk"))
        rows.append(row)
    bundle["repin"]()
    bundle["report"]["rows"][2]["candidate_ir"] = rule("visitor")
    bundle["report"]["rows"][3]["candidate_ir"] = rule("auditor")

    def renderer(predicted, request_id):
        outputs = {"registrar": "The registrar must approve the notice.",
                   "visitor": "The clerk must approve the notice.",
                   "auditor": "An officer shall reject the form."}
        return {"status": "rendered", "text": outputs[predicted["rules"][0]["actor"]], "reason": None}

    result = score(bundle, render_canonical=True, renderer=renderer)
    assert result["counts"]["attempted"] == 4
    assert result["counts"]["exact_ir"] == result["counts"]["exact_original_utf8"] == 2
    assert result["counts"]["joint_ir_original_utf8_exact"] == 1
    assert result["rates"]["joint_ir_original_utf8_exact"] == .25
    assert [row["joint_ir_original_utf8_exact"] for row in result["rows"]] == [True, False, False, False]
    assert result["ir_text_joint_counts"] == {"denominator": "all_captured_input_rows", "total": 4,
        "both_exact": 1, "ir_only_exact": 1, "text_only_exact": 1, "neither_exact": 1}


@pytest.mark.parametrize("failure", ["missing", "duplicate", "invalid_prediction", "renderer_refused"])
def test_joint_denominator_keeps_missing_duplicate_and_refused_rows(bundle, failure):
    row = bundle["corpus"]["rows"][1]
    row.update(source_text="The clerk must approve the notice.", target=rule("clerk"))
    row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
    bundle["repin"]()
    if failure == "missing":
        bundle["report"]["rows"].pop()
    elif failure == "duplicate":
        bundle["report"]["rows"].append(clone(bundle["report"]["rows"][1]))
    elif failure == "invalid_prediction":
        bundle["report"]["rows"][1].update(status="fail_open_invalid_output", candidate_ir=None)

    def renderer(predicted, request_id):
        if predicted["rules"][0]["actor"] == "clerk":
            return {"status": "refused", "text": None, "reason": "authored_refusal"}
        return render_first(predicted, request_id)

    result = score(bundle, render_canonical=True, renderer=renderer)
    assert result["counts"]["attempted"] == 2
    assert result["counts"]["joint_ir_original_utf8_exact"] == 1
    assert result["rates"]["joint_ir_original_utf8_exact"] == .5
    assert [row["joint_ir_original_utf8_exact"] for row in result["rows"]] == [True, False]
    table = result["ir_text_joint_counts"]
    assert table == {"denominator": "all_captured_input_rows", "total": 2, "both_exact": 1,
        "ir_only_exact": int(failure == "renderer_refused"), "text_only_exact": 0,
        "neither_exact": int(failure != "renderer_refused")}
    outcome = "rendering_refused" if failure == "renderer_refused" else (
        "refused" if failure == "invalid_prediction" else failure)
    assert result["counts"][outcome] == 1


def test_joint_exactness_is_independent_of_edit_distance_budget(bundle):
    result = score(bundle, render_canonical=True, renderer=render_first, max_edit_cells=1)
    assert result["counts"]["exact_ir"] == 2
    assert result["counts"]["exact_original_utf8"] == result["counts"]["joint_ir_original_utf8_exact"] == 1
    assert result["rates"]["joint_ir_original_utf8_exact"] == .5
    assert result["ir_text_joint_counts"] == {"denominator": "all_captured_input_rows", "total": 2,
        "both_exact": 1, "ir_only_exact": 1, "text_only_exact": 0, "neither_exact": 0}
    assert all(row["rendering"]["character_edit"]["status"] == "cell_budget_exhausted"
               and row["rendering"]["character_edit"]["distance"] is None for row in result["rows"])


# Authored relational prose scoring is an explicit additional path. These cases
# supply neither model outputs nor statutory interpretation/review evidence.
RELATIONAL_PROSE_PROFILE = "source-withheld-typed-relational-legal-prose/v1"


_RELATIONAL_SCORE_TEXT = (
    "Typed legal rule: tdfol/tdfol_default.\nTypes: Object.\n"
    "Predicate Serve: server of type Object; addressee of type Object.\n"
    "Rule: (for every officer of type Object, (there exists person of type Object such that "
    "(it is obligatory that (Serve holds for server: officer of type Object; "
    "addressee: person of type Object))))."
)


def _relational_score_reference():
    """Independent AST authored from role and binder expectations, not parser output."""
    from ipfs_datasets_py.logic.syntax_core import ast as relational_ast, signatures as relational_signatures
    obj = relational_signatures.LogicSort("Object")
    atom = relational_ast.mk_predicate("score:serve", "Serve", (
        relational_ast.mk_variable("score:officer", "officer", obj),
        relational_ast.mk_variable("score:person", "person", obj)))
    modal = relational_ast.mk_extension("score:obligation", family="tdfol", profile="tdfol_default",
        features=("legacy.obligation", "legacy.classic_letter"), payload_schema="legacy.deontic/v1",
        payload={"kind": "obligation", "letter": "O", "resolution": "deontic",
                 "schema_version": "legacy.deontic/v1"}, children=(atom,))
    root = relational_ast.mk_forall("score:all", (relational_ast.Binder("officer", obj),),
        relational_ast.mk_exists("score:some", (relational_ast.Binder("person", obj),), modal))
    signature = relational_signatures.LogicSignature("score:signature", family="tdfol",
        profile="tdfol_default", sorts=(obj,),
        symbols=(relational_signatures.declare_predicate("Serve", (obj, obj)),))
    return relational_ast.TypedExpression("score:expression", root, signature), [
        {"symbol": "Serve", "roles": ["server", "addressee"]}]


def _score_relational(candidate, *, original=None):
    expression, roles = _relational_score_reference()
    return scorer.score_relational_legal_text_roundtrip(expression, candidate,
        reference_argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE, original_text=original)


def test_relational_score_separates_typed_structure_normalized_prose_and_original_bytes():
    result = _score_relational(_RELATIONAL_SCORE_TEXT,
        original="Every officer shall serve some person.")
    assert result["status"] == "complete_candidate_scored"
    assert result["input_count"] == result["supported_count"] == 1
    assert result["abstention_count"] == 0
    assert result["normalized_candidate_prose"] == result["normalized_reference_prose"] == _RELATIONAL_SCORE_TEXT
    measurements = result["measurements"]
    assert measurements["complete_typed_structure_exact"] is True
    assert measurements["canonical_prose_exact"] is True
    assert measurements["exact_typed_expression_equal"] is False
    assert measurements["original_utf8_exact"] is False
    assert measurements["joint_typed_structure_original_utf8_exact"] is False
    assert all(measurements[key] is False for key in ("semantic_equivalence_verified",
        "source_correspondence_verified", "proof_validity_verified", "source_dependence_evaluated"))
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0


def test_relational_score_original_byte_measurement_is_optional_and_same_row_joint():
    without_source = _score_relational(_RELATIONAL_SCORE_TEXT)
    assert without_source["measurements"]["original_utf8_exact"] is None
    assert without_source["measurements"]["joint_typed_structure_original_utf8_exact"] is None
    with_source = _score_relational(_RELATIONAL_SCORE_TEXT, original=_RELATIONAL_SCORE_TEXT)
    assert with_source["measurements"]["original_utf8_exact"] is True
    assert with_source["measurements"]["joint_typed_structure_original_utf8_exact"] is True
    mutated = _RELATIONAL_SCORE_TEXT.replace("obligatory", "permitted")
    wrong_structure_exact_bytes = _score_relational(mutated, original=mutated)
    assert wrong_structure_exact_bytes["measurements"]["original_utf8_exact"] is True
    assert wrong_structure_exact_bytes["measurements"]["complete_typed_structure_exact"] is False
    assert wrong_structure_exact_bytes["measurements"]["canonical_prose_exact"] is False
    assert wrong_structure_exact_bytes["measurements"]["joint_typed_structure_original_utf8_exact"] is False


@pytest.mark.parametrize("candidate", ["", "   ", "An officer must serve a person.",
    _RELATIONAL_SCORE_TEXT + " Further obligations apply.",
    _RELATIONAL_SCORE_TEXT.replace("addressee: person", "server: person")])
def test_relational_score_whole_input_abstentions_remain_in_denominator(candidate):
    result = _score_relational(candidate, original=candidate)
    assert result["input_count"] == result["abstention_count"] == 1
    assert result["supported_count"] == 0
    assert result["status"] == "unsupported_candidate_abstained"
    assert result["normalized_candidate_prose"] is None
    assert result["measurements"]["complete_typed_structure_exact"] is False
    assert result["measurements"]["canonical_prose_exact"] is False
    assert result["measurements"]["original_utf8_exact"] is True
    assert result["measurements"]["joint_typed_structure_original_utf8_exact"] is False


def test_relational_score_never_passes_original_source_or_reference_to_inverse(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import extended_compiler
    observed = []
    original_compile = extended_compiler.compile_relational
    def observe(text, *, profile):
        observed.append((text, profile))
        return original_compile(text, profile=profile)
    monkeypatch.setattr(extended_compiler, "compile_relational", observe)
    sentinel = "PRIVATE original UTF8 wording — unavailable to the inverse."
    result = _score_relational(_RELATIONAL_SCORE_TEXT, original=sentinel)
    assert observed == [(_RELATIONAL_SCORE_TEXT, RELATIONAL_PROSE_PROFILE)]
    assert result["original_source_available_to_inverse"] is False
    assert result["reference_target_available_to_inverse"] is False
    assert sentinel not in result["normalized_candidate_prose"]
    assert sentinel not in result["normalized_reference_prose"]


@pytest.mark.parametrize("value", [None, 7, True])
def test_relational_score_requires_explicit_text_candidate(value):
    with pytest.raises(scorer.LegalTextRoundTripError):
        _score_relational(value)


@pytest.mark.parametrize("fault, message", [
    ("candidate_surrogate", "valid UTF8 candidate and optional original text required"),
    ("original_surrogate", "valid UTF8 candidate and optional original text required"),
    ("original_bool", "optional original source text required"),
])
def test_relational_score_input_guards_run_before_any_reference_realization(monkeypatch, fault, message):
    from ipfs_datasets_py.logic.legal_ir import extended_decompiler
    def forbidden_realization(*args, **kwargs):
        raise AssertionError("reference realization must follow scorer input guards")
    monkeypatch.setattr(extended_decompiler, "decompile_relational", forbidden_realization)
    candidate = _RELATIONAL_SCORE_TEXT + "\ud800" if fault == "candidate_surrogate" else _RELATIONAL_SCORE_TEXT
    original = {"candidate_surrogate": None, "original_surrogate": "\ud800", "original_bool": True}[fault]
    with pytest.raises(scorer.LegalTextRoundTripError, match=message):
        _score_relational(candidate, original=original)


@pytest.mark.parametrize("changed", ["governing_context", "definition_uses"])
def test_relational_score_detects_changed_governing_fields_with_identical_prose(changed):
    reference = {"governing_context": {"valid_from_utc": "2030-01-01T00:00:00Z"},
        "definition_uses": [{"definition_unit_id": "fixture:definition-A", "applicability": "governing"}]}
    candidate = {**reference, changed: {
        "governing_context": {"valid_from_utc": "2030-04-01T00:00:00Z"},
        "definition_uses": [{"definition_unit_id": "fixture:definition-B", "applicability": "governing"}],
    }[changed]}
    expression, roles = _relational_score_reference()
    result = scorer.score_relational_legal_text_roundtrip(expression, _RELATIONAL_SCORE_TEXT,
        reference_argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE, original_text=_RELATIONAL_SCORE_TEXT,
        reference_governing_fields=reference, candidate_governing_fields=candidate)
    assert result["measurements"]["complete_typed_structure_exact"] is True
    assert result["measurements"]["canonical_prose_exact"] is True
    assert result["measurements"]["original_utf8_exact"] is True
    assert result["measurements"]["semantic_equivalence_verified"] is False
    assert result["governing_fields_comparison"] == {
        "reference": reference, "candidate": candidate,
        "measurements": {"governing_context_exact": changed != "governing_context",
                         "definition_uses_exact": changed != "definition_uses"},
        "authority": {"applicability_verified": False, "governing_use_verified": False},
    }


def test_relational_score_governing_fields_never_reach_renderer_or_inverse(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import extended_compiler, extended_decompiler
    compile_relational = extended_compiler.compile_relational
    decompile_relational = extended_decompiler.decompile_relational
    inverse_inputs, renderer_inputs = [], []

    def observe_inverse(text, *, profile):
        inverse_inputs.append((text, profile))
        return compile_relational(text, profile=profile)

    def observe_renderer(expression, *, argument_roles, profile):
        renderer_inputs.append((expression, argument_roles, profile))
        return decompile_relational(expression, argument_roles=argument_roles, profile=profile)

    monkeypatch.setattr(extended_compiler, "compile_relational", observe_inverse)
    monkeypatch.setattr(extended_decompiler, "decompile_relational", observe_renderer)
    expression, roles = _relational_score_reference()
    reference = {"governing_context": {"instrument_id": "fixture:reference-only-instrument"},
        "definition_uses": [{"definition_unit_id": "fixture:reference-only-definition"}]}
    result = scorer.score_relational_legal_text_roundtrip(expression, _RELATIONAL_SCORE_TEXT,
        reference_argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE,
        original_text="Original source appears only in the UTF-8 score.", reference_governing_fields=reference)
    assert inverse_inputs == [(_RELATIONAL_SCORE_TEXT, RELATIONAL_PROSE_PROFILE)]
    assert renderer_inputs and all(decompile_relational(expression, argument_roles=roles, profile=profile)
                                   == _RELATIONAL_SCORE_TEXT for expression, roles, profile in renderer_inputs)
    assert result["normalized_candidate_prose"] == result["normalized_reference_prose"] == _RELATIONAL_SCORE_TEXT
    assert result["governing_fields_comparison"]["candidate"] == {}
    assert result["governing_fields_comparison"]["measurements"] == {
        "governing_context_exact": False, "definition_uses_exact": False,
    }


def test_relational_score_governing_observation_cannot_turn_abstention_into_success():
    expression, roles = _relational_score_reference()
    declared = {"definition_uses": None}
    result = scorer.score_relational_legal_text_roundtrip(expression, "",
        reference_argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE,
        reference_governing_fields=declared, candidate_governing_fields=declared)
    assert result["status"] == "unsupported_candidate_abstained"
    assert result["input_count"] == result["abstention_count"] == 1
    assert result["supported_count"] == 0
    assert result["measurements"]["complete_typed_structure_exact"] is False
    comparison = result["governing_fields_comparison"]
    assert comparison["reference"] == comparison["candidate"] == declared
    assert comparison["measurements"] == {"governing_context_exact": None, "definition_uses_exact": True}
    assert not any(comparison["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0


def test_relational_score_governing_measurements_are_explicitly_opt_in():
    assert "governing_fields_comparison" not in _score_relational(_RELATIONAL_SCORE_TEXT)


def _recompiled(candidate=None):
    return {"status": "recompiled", "candidate_ir": clone(rule() if candidate is None else candidate),
            "reason": None}



def test_prose_recompilation_is_unmeasured_and_old_shape_stays_default(bundle):
    result = score(bundle, render_canonical=True, renderer=render_first)
    assert "prose_recompilation" not in result
    assert all("recompilation" not in row for row in result["rows"])



@pytest.mark.parametrize("options", [
    {"recompile_rendered": "yes"},
    {"recompiler": lambda text, request: _recompiled()},
    {"recompile_rendered": True},
    {"recompile_rendered": True, "recompiler": lambda text, request: _recompiled()},
    {"render_canonical": True, "recompile_rendered": True, "recompiler": False},
])
def test_prose_recompilation_requires_explicit_complete_selection(bundle, options):
    with pytest.raises(scorer.LegalTextRoundTripError, match="prose recompilation"):
        score(bundle, **options)



def test_recompiler_receives_only_selected_prose_and_constant_non_source_id(bundle):
    for index, row in enumerate(bundle["corpus"]["rows"]):
        row["source_text"] = "Hidden authored source wording " + str(index)
        row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
    bundle["repin"]()
    before = raw((bundle["inputs"], bundle["report"], bundle["corpus"]))
    calls = []
    prose = "Registrar must approve notice."

    def recompiler(*args, **kwargs):
        assert kwargs == {}
        assert args == (prose, "legal-selected-prose-recompile")
        assert all(row["id"] not in str(args) and row["source_text"] not in str(args)
                   for row in bundle["corpus"]["rows"])
        assert not any(isinstance(arg, (dict, list)) for arg in args)
        calls.append(args)
        return _recompiled()

    result = score(bundle, render_canonical=True,
        renderer=lambda predicted, request: {"status": "rendered", "text": prose, "reason": None},
        recompile_rendered=True, recompiler=recompiler)
    metric = result["prose_recompilation"]
    assert len(calls) == 2
    assert metric["callback_calls"] == metric["attempted_rows"] == 2
    assert metric["counts"]["exact_predicted_ir"] == metric["counts"]["exact_reference_ir"] == 2
    assert metric["rates"] == {"exact_predicted_ir": 1.0, "exact_reference_ir": 1.0}
    assert result["counts"]["exact_original_utf8"] == 0
    assert result["counts"]["joint_ir_original_utf8_exact"] == 0
    assert result["operational_complete"]
    assert raw((bundle["inputs"], bundle["report"], bundle["corpus"])) == before
    for row in result["rows"]:
        rerun = row["recompilation"]
        assert rerun["input_text_sha256"] == hashlib.sha256(prose.encode()).hexdigest()
        assert rerun["output_ir"] == rule()
        assert rerun["output_ir_sha256"] == digest(rule())
    assert metric["scope"] == "single_rule_CanonicalRoundTripIR@1_seven_facet_syntax_only"
    assert not metric["callback_behavior_authenticated"]
    assert not metric["hidden_source_or_target_copying_ruled_out"]
    assert not metric["native_compiler_or_model_execution_authenticated"]
    assert not metric["proof_authority"]
    assert not metric["semantic_correctness_qualified"]
    assert all(metric[key] is None for key in ("complete_typed_AST_fidelity",
        "semantic_equivalence", "legal_source_faithfulness", "proof_validity"))



@pytest.mark.parametrize("facet,value", [
    ("modality", "P"),
    ("actor", "court"),
    ("action", "publish"),
    ("object", "record"),
    ("conditions", ["licensed"]),
    ("exceptions", ["emergency"]),
    ("temporal", ["on_notice"]),
])
def test_prose_cycle_detects_complete_supported_canonical_facet_mutations(bundle, facet, value):
    changed = rule()
    changed["rules"][0][facet] = value
    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=lambda text, request: _recompiled(changed))
    metric = result["prose_recompilation"]
    assert result["counts"]["exact_ir"] == 2
    assert metric["counts"]["recompiled"] == 2
    assert metric["counts"]["exact_predicted_ir"] == metric["counts"]["exact_reference_ir"] == 0
    assert metric["facets_predicted"][facet] == {"matched": 0, "total": 2}
    assert metric["facets_reference"][facet] == {"matched": 0, "total": 2}
    assert all(row["recompilation"]["output_ir"] == changed for row in result["rows"])
    assert metric["semantic_equivalence"] is None



def test_exact_cycle_does_not_make_the_source_translation_reference_correct(bundle):
    changed = rule()
    changed["rules"][0]["modality"] = "P"
    for prediction in bundle["report"]["rows"]:
        prediction["candidate_ir"] = clone(changed)
    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=lambda text, request: _recompiled(changed))
    metric = result["prose_recompilation"]
    assert result["counts"]["exact_ir"] == 0
    assert metric["counts"]["exact_predicted_ir"] == 2
    assert metric["counts"]["exact_reference_ir"] == 0
    assert metric["rates"] == {"exact_predicted_ir": 1.0, "exact_reference_ir": 0.0}
    assert metric["legal_source_faithfulness"] is None



@pytest.mark.parametrize("semantics,left,right", [
    ("quantifier_and_binder_scope",
     "Every agency must notify one clerk.", "One clerk must receive notice from every agency."),
    ("observed_compliance",
     "The agency must notify the clerk.", "The agency notified the clerk."),
    ("nested_exception_scope",
     "Every agency must file unless each clerk objects.", "Every agency must file unless one clerk objects."),
    ("calendar_interpretation",
     "The agency must file within ten calendar days.", "The agency must file within ten business days."),
    ("legal_effective_dates",
     "The duty is effective on 1 January 2024.", "The duty is effective on 1 January 2025."),
    ("typed_cardinality",
     "The agency must appoint exactly three members.", "The agency must appoint at least three members."),
    ("governing_definition_dependencies",
     "The governing definition is unavailable.", "Two conflicting definitions may govern."),
])
def test_unrepresented_norm_semantics_stay_explicitly_unsupported(bundle, semantics, left, right):
    # These are authored unsupported-language controls, not a parser or teacher.
    # The narrow canonical schema must never manufacture a full-norm score for
    # either member of a pair by stashing its meaning inside an opaque atom.
    render_calls, recompile_calls = [], []

    def renderer(predicted, request):
        text = (left, right)[len(render_calls)]
        render_calls.append(text)
        return {"status": "rendered", "text": text, "reason": None}

    def recompiler(text, request):
        assert text in (left, right)
        recompile_calls.append(text)
        return {"status": "unsupported", "candidate_ir": None, "reason": semantics}

    result = score(bundle, render_canonical=True, renderer=renderer,
        recompile_rendered=True, recompiler=recompiler)
    metric = result["prose_recompilation"]
    assert render_calls == recompile_calls == [left, right]
    assert semantics in metric["unsupported_semantics"]
    assert metric["counts"]["unsupported"] == 2
    assert metric["counts"]["exact_predicted_ir"] == metric["counts"]["exact_reference_ir"] == 0
    assert not result["operational_complete"]
    assert metric["rates"]["exact_predicted_ir"] == 0
    assert all(row["recompilation"]["status"] == "unsupported"
        and row["recompilation"]["output_ir"] is None for row in result["rows"])
    assert metric["semantic_equivalence"] is None
    assert result["proof_authority"] is False



@pytest.mark.parametrize("field,value", [
    ("binders", [{"variable": "x", "type": "Person"}]),
    ("exception_scope", {"inside": "forall"}),
    ("calendar", {"kind": "business_days", "amount": 10}),
    ("effective_date", "2024-01-01"),
    ("cardinality", {"minimum": 3}),
    ("governing_definition", {"definition_id": "fictional:def:A"}),
    ("observed_compliance", True),
])
def test_full_typed_or_context_fields_cannot_be_silently_dropped_into_canonical_IR(bundle, field, value):
    unsupported = rule()
    unsupported["rules"][0][field] = value
    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=lambda text, request: _recompiled(unsupported))
    metric = result["prose_recompilation"]
    assert metric["counts"]["invalid"] == 2
    assert metric["counts"]["recompiled"] == 0
    assert metric["counts"]["exact_predicted_ir"] == 0
    assert all(row["recompilation"]["output_ir"] is None for row in result["rows"])



@pytest.mark.parametrize("failure", ["missing", "duplicate", "invalid_prediction", "renderer_refused"])
def test_prose_recompile_denominator_retains_unavailable_rows_without_callback(bundle, failure):
    if failure == "missing":
        bundle["report"]["rows"].pop()
    elif failure == "duplicate":
        bundle["report"]["rows"].append(clone(bundle["report"]["rows"][1]))
    elif failure == "invalid_prediction":
        bundle["report"]["rows"][1]["candidate_ir"] = {}
    calls = []

    def recompile(text, request):
        calls.append(text)
        return _recompiled()

    # The recompile calls happen after all rendering. A renderer's own count is
    # kept separately to exercise the second-row refusal.
    render_calls = []

    def counted_render(predicted, request):
        render_calls.append(request)
        if failure == "renderer_refused" and len(render_calls) == 2:
            return {"status": "refused", "text": None, "reason": "fictional refusal"}
        return render_first(predicted, request)

    result = score(bundle, render_canonical=True, renderer=counted_render,
        recompile_rendered=True, recompiler=recompile)
    metric = result["prose_recompilation"]
    assert metric["attempted_rows"] == 2
    assert metric["callback_calls"] == len(calls) == 1
    assert metric["counts"]["recompiled"] == metric["counts"]["unavailable"] == 1
    assert metric["rates"]["exact_predicted_ir"] == metric["rates"]["exact_reference_ir"] == .5
    assert result["rows"][1]["recompilation"]["input_text_sha256"] is None



@pytest.mark.parametrize("status", ["abstained", "unsupported"])
def test_prose_recompiler_abstention_and_unsupported_are_distinct(bundle, status):
    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True,
        recompiler=lambda text, request: {"status": status, "candidate_ir": None, "reason": "fictional"})
    metric = result["prose_recompilation"]
    assert metric["counts"][status] == 2
    assert metric["counts"]["error"] == metric["counts"]["invalid"] == 0
    assert metric["counts"]["exact_predicted_ir"] == 0



def test_prose_recompiler_errors_are_sanitized_and_preserve_IR_metrics(bundle):
    def broken(text, request):
        raise RuntimeError("sensitive provider text must not enter the result")
    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=broken)
    assert result["counts"]["exact_ir"] == 2
    assert result["prose_recompilation"]["counts"]["error"] == 2
    assert all(row["recompilation"]["reason"] == "RuntimeError" for row in result["rows"])
    assert "sensitive provider text" not in str(result)



@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_prose_recompiler_process_control_exceptions_propagate(bundle, error):
    def stop(text, request):
        raise error()
    with pytest.raises(error):
        score(bundle, render_canonical=True, renderer=render_first,
            recompile_rendered=True, recompiler=stop)



@pytest.mark.parametrize("output", [
    None,
    {"status": "recompiled", "candidate_ir": rule(), "reason": None, "proof_valid": True},
    {"status": "unsupported", "candidate_ir": rule(), "reason": "cannot"},
    {"status": "abstained", "candidate_ir": None, "reason": None},
    {"status": "complete", "candidate_ir": rule(), "reason": None},
    {"status": "recompiled", "candidate_ir": {"rules": [rule()["rules"][0], rule()["rules"][0]]}, "reason": None},
])
def test_malformed_or_out_of_profile_recompiler_outputs_receive_no_credit(bundle, output):
    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=lambda text, request: clone(output))
    metric = result["prose_recompilation"]
    assert metric["counts"]["invalid"] == 2
    assert metric["counts"]["recompiled"] == 0
    assert metric["counts"]["exact_predicted_ir"] == 0



def test_recompiled_output_is_detached_from_callback_reuse(bundle):
    shared = rule()
    calls = []

    def callback(text, request):
        if calls:
            shared["rules"][0]["actor"] = "court"
        calls.append(text)
        return {"status": "recompiled", "candidate_ir": shared, "reason": None}

    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=callback)
    first, second = [row["recompilation"] for row in result["rows"]]
    assert first["output_ir"] == rule()
    assert first["exact_predicted_ir"] is True
    assert second["output_ir"]["rules"][0]["actor"] == "court"
    assert second["exact_predicted_ir"] is False
    assert result["prose_recompilation"]["rates"]["exact_predicted_ir"] == .5



def test_corpus_endpoint_is_rechecked_after_prose_recompiler_callback(bundle):
    def callback(text, request):
        bundle["path"].write_bytes(b"changed by authored callback")
        return _recompiled()
    with pytest.raises(scorer.LegalTextRoundTripError):
        score(bundle, render_canonical=True, renderer=render_first,
            recompile_rendered=True, recompiler=callback)


def test_relational_score_refuses_live_role_change_that_falsifies_prose_equality(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import extended_compiler
    expression,roles=_relational_score_reference()
    candidate=_RELATIONAL_SCORE_TEXT.replace('server','sender').replace('addressee','recipient')
    original=extended_compiler.compile_relational
    def mutate_reference(text,*,profile):
        parsed=original(text,profile=profile)
        roles[0]['roles'][:]=parsed[1][0]['roles']
        return parsed
    monkeypatch.setattr(extended_compiler,'compile_relational',mutate_reference)
    with pytest.raises(scorer.LegalTextRoundTripError,match='changed during'):
        report=scorer.score_relational_legal_text_roundtrip(expression,candidate,
            reference_argument_roles=roles,profile=RELATIONAL_PROSE_PROFILE)
        # The unfenced implementation returns this contradictory witness.
        assert report['measurements']['canonical_prose_exact'] is True
        assert report['normalized_reference_prose']!=report['normalized_candidate_prose']
        print(json.dumps(dict(false_canonical_prose_exact=report['measurements']['canonical_prose_exact'],
            normalized_reference_prose=report['normalized_reference_prose'],normalized_candidate_prose=report['normalized_candidate_prose'])))


@pytest.mark.parametrize('which',['reference','candidate'])
def test_relational_score_refuses_governing_observation_change_during_inverse(monkeypatch,which):
    from ipfs_datasets_py.logic.legal_ir import extended_compiler
    expression,roles=_relational_score_reference()
    reference={'governing_context':{'instrument_id':'fixture:one'},'definition_uses':[]}
    candidate=clone(reference);original=extended_compiler.compile_relational
    def mutate_observation(text,*,profile):
        (reference if which=='reference' else candidate)['governing_context']['instrument_id']='fixture:changed-during-inverse'
        return original(text,profile=profile)
    monkeypatch.setattr(extended_compiler,'compile_relational',mutate_observation)
    with pytest.raises(scorer.LegalTextRoundTripError,match='changed during'):
        scorer.score_relational_legal_text_roundtrip(expression,_RELATIONAL_SCORE_TEXT,
            reference_argument_roles=roles,profile=RELATIONAL_PROSE_PROFILE,
            reference_governing_fields=reference,candidate_governing_fields=candidate)


def test_relational_score_reference_inputs_are_detached_before_rendering(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import extended_decompiler
    expression,roles=_relational_score_reference();original=extended_decompiler.decompile_relational;seen=[]
    def observe(value,*,argument_roles,profile):
        seen.append((value is expression,argument_roles is roles))
        return original(value,argument_roles=argument_roles,profile=profile)
    monkeypatch.setattr(extended_decompiler,'decompile_relational',observe)
    report=scorer.score_relational_legal_text_roundtrip(expression,_RELATIONAL_SCORE_TEXT,
        reference_argument_roles=roles,profile=RELATIONAL_PROSE_PROFILE)
    assert report['measurements']['canonical_prose_exact'] is True
    assert seen and all(not original_ast and not original_roles for original_ast,original_roles in seen)


def test_selected_prose_cycle_distinguishes_predicted_modality_from_reference_rewrite(bundle):
    """An authored text-only callback is no semantic inverse or model witness."""
    # The second predicted IR permits the act; both references require it.
    # The existing inert renderer supplies must-prose in either case, and this
    # deliberately reference-correct callback must not gain predicted-cycle credit.
    bundle["report"]["rows"][1]["candidate_ir"]["rules"][0]["modality"] = "P"
    calls = []

    def recompiler(text, request_id):
        calls.append((text, request_id))
        return {"status": "recompiled", "candidate_ir": rule(), "reason": None}

    result = score(bundle, render_canonical=True, renderer=render_first,
        recompile_rendered=True, recompiler=recompiler)
    assert calls == [("The registrar must approve the notice.",
        "legal-selected-prose-recompile")] * 2
    cycle = result["prose_recompilation"]
    assert cycle["denominator"] == "all_captured_input_rows" and cycle["attempted_rows"] == 2
    assert cycle["callback_calls"] == cycle["counts"]["recompiled"] == 2
    assert cycle["counts"]["exact_predicted_ir"] == 1
    assert cycle["counts"]["exact_reference_ir"] == 2
    assert cycle["rates"]["exact_predicted_ir"] == .5
    assert cycle["rates"]["exact_reference_ir"] == 1.0
    changed = result["rows"][1]["recompilation"]
    assert changed["exact_predicted_ir"] is False and changed["exact_reference_ir"] is True
    assert changed["facets_predicted"]["modality"] is False
    assert changed["facets_reference"]["modality"] is True
    assert cycle["scope"] == "single_rule_CanonicalRoundTripIR@1_seven_facet_syntax_only"
    assert cycle["callback_behavior_authenticated"] is False
    assert cycle["hidden_source_or_target_copying_ruled_out"] is False
    assert cycle["native_compiler_or_model_execution_authenticated"] is False
    assert all(cycle[name] is None for name in ("complete_typed_AST_fidelity",
        "semantic_equivalence", "legal_source_faithfulness", "proof_validity"))
    assert cycle["semantic_correctness_qualified"] is cycle["proof_authority"] is False
    assert result["model_inference_executed_by_scorer"] is False
    assert result["training_executed"] is result["semantic_correctness_qualified"] is False


@pytest.mark.parametrize("stage", ("renderer", "inverse"))
@pytest.mark.parametrize("changed_input", ("roles", "reference_governing", "candidate_governing"))
def test_relational_score_refuses_mutation_of_original_scoring_inputs(monkeypatch, stage, changed_input):
    from ipfs_datasets_py.logic.legal_ir import extended_compiler, extended_decompiler
    expression, roles = _relational_score_reference()
    reference = {"governing_context": {"valid_from_utc": "2030-01-01T00:00:00Z"},
        "definition_uses": [{"definition_unit_id": "fixture:definition-A", "applicability": "governing"}]}
    candidate = clone(reference)
    mutations = []

    def mutate_original():
        if changed_input == "roles":
            roles[0]["roles"][0] = "witness"
        else:
            selected = reference if changed_input == "reference_governing" else candidate
            selected["governing_context"]["valid_from_utc"] = "2030-04-01T00:00:00Z"
        mutations.append(changed_input)

    owner = extended_decompiler if stage == "renderer" else extended_compiler
    name = "decompile_relational" if stage == "renderer" else "compile_relational"
    original = getattr(owner, name)

    def changing_callback(*args, **kwargs):
        result = original(*args, **kwargs)
        mutate_original()
        return result

    monkeypatch.setattr(owner, name, changing_callback)
    with pytest.raises(scorer.LegalTextRoundTripError, match="inputs changed during scoring"):
        scorer.score_relational_legal_text_roundtrip(expression, _RELATIONAL_SCORE_TEXT,
            reference_argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE,
            reference_governing_fields=reference, candidate_governing_fields=candidate)
    assert mutations
