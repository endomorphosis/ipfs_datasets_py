"""Pure saved-score domain tests; no models, encoder, fit or semantic gold."""
import builtins
import copy
import hashlib
import itertools
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.legal_ir import joint_span_selection as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as owner


def packet(source="alpha beta gamma", *, present=()):
    tokens = [{key: token[key] for key in ("text", "start", "end")}
              for token in owner.tokenize_source(source)]
    count = len(tokens)
    result = {"schema": "joint-source-span-scores/v1", "tokens": tokens,
              "modality_logits": [3.0, 1.0, -2.0],
              "presence_logits": {field: [-2.0, 2.0] if field in present else [2.0, -2.0]
                                  for field in ("object", "conditions", "exceptions", "temporal")},
              "start_logits": {field: [-20.0] * count for field in subject.FIELDS},
              "end_logits": {field: [-20.0] * count for field in subject.FIELDS}}
    for field, position in (("actor", 0), ("action", min(1, count - 1))):
        point(result, field, position, 30.0)
    for position, field in enumerate(present, start=2):
        point(result, field, min(position, count - 1), 25.0)
    return result


def point(scores, field, position, value):
    scores["start_logits"][field][position] = value
    scores["end_logits"][field][position] = value


def coordinates(result, field):
    span = result["span_diagnostics"][field]["span"]
    return span["token_start"], span["token_end_inclusive"]


def test_joint_selection_resolves_overlap_without_relabeling_raw_readout():
    source = "alpha beta gamma"
    scores = packet(source)
    for field in ("actor", "action"):
        scores["start_logits"][field] = [-20.0] * 3
        scores["end_logits"][field] = [-20.0] * 3
        point(scores, field, 0, 5.0)
    point(scores, "actor", 1, 4.5)
    point(scores, "action", 2, 4.0)
    before = copy.deepcopy(scores)
    result = subject.select_joint_spans(source, scores, top_k=3)
    assert scores == before
    assert result["status"] == "selected" and result["reason"] is None
    assert result["independent_greedy"]["status"] == "abstained"
    assert result["independent_greedy"]["reason"] == "copied_spans_overlap"
    assert result["independent_greedy"]["actual_owner_report"] is False
    assert coordinates(result, "actor") == (1, 1)
    assert coordinates(result, "action") == (0, 0)
    assert result["search"]["best_score"] == 19.0
    assert result["search"]["joint_score_margin"] == 1.0
    assert result["canonical_ir"]["rules"][0]["actor"] == "beta"
    assert result["canonical_ir"]["rules"][0]["action"] == "alpha"
    assert result["origin"] == "bounded_joint_source_span_selector"
    assert result["raw_output_repaired"] is False
    assert result["search"]["retained_domain_optimality_established"] is True
    assert result["search"]["full_domain_optimality_established"] is False


@pytest.mark.parametrize("field", ["object", "conditions", "exceptions", "temporal"])
def test_no_feasible_assignment_keeps_optional_presence_and_required_roles(field):
    scores = packet("alpha beta", present=(field,))
    result = subject.select_joint_spans("alpha beta", scores, top_k=16)
    assert result["reason"] == "no_compatible_assignment_in_retained_domain"
    assert result["canonical_ir"] is None and result["formal_outputs"] == []
    assert result["fixed_decisions"]["facets"][field]["present"] is True
    assert all(result["fixed_decisions"]["facets"][field]["required"] for field in ("actor", "action"))
    assert set(result["candidate_summary"]) == {"actor", "action", field}
    assert result["candidate_domain_truncated"] is False
    assert result["search"]["completed"] is True


def test_single_token_cannot_satisfy_both_required_roles():
    result = subject.select_joint_spans("alpha", packet("alpha"))
    assert result["reason"] == "no_compatible_assignment_in_retained_domain"
    assert result["independent_greedy"]["reason"] == "copied_spans_overlap"


def test_presence_cannot_be_overridden_for_actor_or_action():
    scores = packet()
    scores["presence_logits"]["actor"] = [3.0, -3.0]
    with pytest.raises(ValueError, match="presence_logits fields differ"):
        subject.select_joint_spans("alpha beta gamma", scores)


def test_joint_global_tie_rejected_even_with_deterministic_coordinate_order():
    scores = packet("alpha beta")
    for field in ("actor", "action"):
        scores["start_logits"][field] = [0.0, 0.0]
        scores["end_logits"][field] = [0.0, 0.0]
    first = subject.select_joint_spans("alpha beta", scores, top_k=16)
    second = subject.select_joint_spans("alpha beta", scores, top_k=16)
    assert first == second
    assert first["reason"] == "ambiguous_joint_scores"
    assert first["search"]["joint_score_margin"] == 0.0
    assert first["search"]["best_observed_spans"]["actor"]["text"] == "alpha"
    assert first["canonical_ir"] is None and first["search"]["unique_within_guard"] is False


def test_joint_near_tie_guard_uses_absolute_objective_margin():
    scores = packet("alpha beta")
    for field in ("actor", "action"):
        scores["start_logits"][field] = [0.0, 0.0]
        scores["end_logits"][field] = [0.0, 0.0]
    scores["start_logits"]["actor"][0] = 2.0 ** -24
    result = subject.select_joint_spans("alpha beta", scores, top_k=16)
    assert result["reason"] == "ambiguous_joint_scores"
    assert result["search"]["joint_score_margin"] == 2.0 ** -24


def test_completed_truncated_domain_cannot_claim_full_domain_optimality():
    result = subject.select_joint_spans("alpha beta gamma", packet(), top_k=1)
    assert result["status"] == "selected"
    assert result["candidate_domain_truncated"] is True
    assert result["search"]["completed"] is True
    assert result["search"]["retained_domain_optimality_established"] is True
    assert result["search"]["full_domain_optimality_established"] is False
    assert all(item["valid_span_count"] == 6 and item["retained_count"] == 1
               for item in result["candidate_summary"].values())


def test_budget_stop_retains_diagnostic_candidate_but_emits_no_proposal():
    result = subject.select_joint_spans("alpha beta gamma", packet(), top_k=8, max_search_nodes=2)
    assert result["reason"] == "search_budget_exhausted"
    assert result["search"]["visited_nodes"] == 2
    assert result["search"]["best_observed_spans"] is not None
    assert result["canonical_ir"] is None and result["formal_outputs"] == []
    assert result["search"]["completed"] is False
    assert result["search"]["retained_domain_optimality_established"] is False
    assert result["search"]["full_domain_optimality_established"] is False
    assert result["search"]["unique_within_guard"] is False


def test_completed_full_domain_selection_is_distinct_from_legal_qualification():
    result = subject.select_joint_spans("alpha beta gamma", packet(), top_k=16)
    assert result["status"] == "selected" and result["canonical_rule_valid"] is True
    assert result["search"]["full_domain_optimality_established"] is True
    assert all(result[field] is False for field in subject.FALSE)
    assert all(result["formal_outputs"][0][field] is False for field in subject.FALSE)
    assert owner.codec_module._rule(result["canonical_ir"]) == result["canonical_ir"]["rules"][0]


def test_all_six_present_facets_and_modality_are_preserved():
    source = "alpha beta gamma delta epsilon zeta"
    scores = packet(source, present=("object", "conditions", "exceptions", "temporal"))
    scores["modality_logits"] = [0.0, 3.0, 1.0]
    result = subject.select_joint_spans(source, scores, top_k=1)
    assert result["status"] == "selected"
    rule = result["canonical_ir"]["rules"][0]
    assert rule == {"modality": "P", "actor": "alpha", "action": "beta", "object": "gamma",
                    "conditions": ["delta"], "exceptions": ["epsilon"], "temporal": ["zeta"]}
    assert all(result["fixed_decisions"]["facets"][field]["present"] for field in subject.FIELDS)


def test_candidate_boundary_ties_are_disclosed_in_truncated_domain():
    result = subject.select_joint_spans("alpha beta gamma", packet(), top_k=2)
    assert result["status"] == "selected"
    assert result["candidate_summary"]["actor"]["boundary_tied_within_guard"] is True
    assert result["candidate_summary"]["actor"]["boundary_score_margin_float32"] == 0.0
    assert result["search"]["full_domain_optimality_established"] is False


def test_typed_codec_rejection_cannot_be_hidden_as_success(monkeypatch):
    def reject(ir):
        raise ValueError("explicit typed-codec diagnostic double refusal")
    monkeypatch.setattr(owner.codec_module, "_rule", reject)
    result = subject.select_joint_spans("alpha beta gamma", packet(), top_k=16)
    assert result["reason"] == "generated_ir_rejected"
    assert result["canonical_ir"] is None and result["formal_outputs"] == []
    assert result["canonical_rule_valid"] is False and result["family_syntax_checked"] is False


def test_unicode_character_and_utf8_byte_intervals_are_separate_and_exact():
    source = "État  archive\n文書"
    scores = packet(source, present=("object",))
    result = subject.select_joint_spans(source, scores, top_k=16)
    assert result["status"] == "selected"
    assert coordinates(result, "actor") == (0, 0)
    assert result["canonical_ir"]["rules"][0]["object"] == "文書"
    actor = result["span_diagnostics"]["actor"]["span"]
    assert actor["char_end"] == 4 and actor["utf8_byte_end"] == 5
    for field in ("actor", "action", "object"):
        span = result["span_diagnostics"][field]["span"]
        assert source[span["char_start"]:span["char_end"]] == span["text"]
        assert source.encode()[span["utf8_byte_start"]:span["utf8_byte_end"]].decode() == span["text"]
    assert result["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()


def test_multitoken_span_preserves_internal_whitespace_and_duplicate_occurrences():
    source = "alpha  beta\nalpha delta"
    scores = packet(source)
    scores["start_logits"]["actor"] = [-20.0, -20.0, 30.0, -20.0]
    scores["end_logits"]["actor"] = [-20.0, -20.0, 30.0, -20.0]
    scores["start_logits"]["action"] = [30.0, -20.0, -20.0, -20.0]
    scores["end_logits"]["action"] = [-20.0, 30.0, -20.0, -20.0]
    result = subject.select_joint_spans(source, scores, top_k=16)
    assert result["status"] == "selected"
    assert coordinates(result, "actor") == (2, 2)
    assert result["span_diagnostics"]["actor"]["span"]["char_start"] == 12
    assert result["canonical_ir"]["rules"][0]["action"] == "alpha  beta"


def test_no_free_actor_or_lexical_role_heuristic():
    source = "must clerk archive"
    scores = packet(source)
    point(scores, "actor", 0, 40.0)
    point(scores, "action", 2, 40.0)
    result = subject.select_joint_spans(source, scores, top_k=16)
    assert result["status"] == "selected"
    assert result["canonical_ir"]["rules"][0]["actor"] == "must"
    assert result["canonical_ir"]["rules"][0]["action"] == "archive"


@pytest.mark.parametrize("head,field", [("modality_logits", None), ("presence_logits", "object")])
def test_fixed_head_guard_prevents_search_or_silent_rechoice(head, field):
    scores = packet()
    values = [2.0 ** -24, 0.0, -2.0] if field is None else [0.0, 2.0 ** -24]
    if field is None:
        scores[head] = values
    else:
        scores[head][field] = values
    result = subject.select_joint_spans("alpha beta gamma", scores)
    assert result["reason"] == "ambiguous_fixed_head_decision"
    assert result["search"]["visited_nodes"] == 0
    assert result["canonical_ir"] is None


def test_float32_pair_addition_exposes_tie_hidden_by_python_float64():
    scores = packet("alpha beta")
    scores["start_logits"]["actor"] = [2.0 ** 24, 2.0 ** 24]
    scores["end_logits"]["actor"] = [0.0, 1.0]
    result = subject.select_joint_spans("alpha beta", scores, top_k=16)
    assert result["independent_greedy"]["reason"] == "ambiguous_decoder_scores"
    assert result["candidate_summary"]["actor"]["independent_best_span_margin_float32"] == 0.0


def test_branch_bound_best_and_runner_up_match_independent_exhaustive_oracle():
    source = "alpha beta gamma delta"
    scores = packet(source, present=("object",))
    for position, field in enumerate(("actor", "action", "object")):
        scores["start_logits"][field] = [float(-8 + ((i * 5 + position * 3) % 13)) for i in range(4)]
        scores["end_logits"][field] = [float(-6 + ((i * 7 + position * 2) % 11)) for i in range(4)]
    domains = {}
    for field in ("actor", "action", "object"):
        domains[field] = sorted([(struct.unpack("!f", struct.pack("!f", scores["start_logits"][field][a] +
            scores["end_logits"][field][b]))[0], a, b) for a in range(4) for b in range(a, 4)],
            key=lambda item: (-item[0], item[1], item[2]))
    assignments = []
    for combination in itertools.product(*(domains[field] for field in ("actor", "action", "object"))):
        locations = [set(range(item[1], item[2] + 1)) for item in combination]
        if any(a & b for a, b in itertools.combinations(locations, 2)):
            continue
        assignments.append((sum(item[0] for item in combination), tuple(item[1:] for item in combination)))
    assignments.sort(key=lambda item: (-item[0], item[1]))
    result = subject.select_joint_spans(source, scores, top_k=16)
    assert result["search"]["completed"] is True
    assert result["search"]["best_score"] == assignments[0][0]
    assert result["search"]["runner_up_score"] == assignments[1][0]
    assert result["search"]["visited_nodes"] <= 50000
    assert result["search"]["bound_pruned_nodes"] > 0


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"),
                                   0.1, 1e40, 10 ** 1000, "1", None])
def test_invalid_or_non_float32_scores_rejected(value):
    scores = packet()
    scores["start_logits"]["actor"][0] = value
    with pytest.raises(ValueError):
        subject.select_joint_spans("alpha beta gamma", scores)


@pytest.mark.parametrize("field", ["start_logits", "end_logits", "presence_logits"])
def test_missing_score_heads_are_not_defaulted(field):
    scores = packet()
    del scores[field][next(iter(scores[field]))]
    with pytest.raises(ValueError, match="fields differ"):
        subject.select_joint_spans("alpha beta gamma", scores)


@pytest.mark.parametrize("mutation", ["token_removed", "head_short", "wrong_offset", "bool_offset", "extra_token_field",
                                        "target", "required_presence", "wrong_schema"])
def test_source_or_closed_packet_mismatch_rejected(mutation):
    scores = packet()
    if mutation == "token_removed":
        scores["tokens"].pop()
    elif mutation == "head_short":
        scores["end_logits"]["temporal"].pop()
    elif mutation == "wrong_offset":
        scores["tokens"][0]["end"] = 4
    elif mutation == "bool_offset":
        scores["tokens"][0]["start"] = False
    elif mutation == "extra_token_field":
        scores["tokens"][0]["byte_ids"] = [1]
    elif mutation == "target":
        scores["canonical_ir"] = {"rules": []}
    elif mutation == "required_presence":
        scores["presence_logits"]["actor"] = [2.0, -2.0]
    else:
        scores["schema"] = "unversioned"
    with pytest.raises(ValueError):
        subject.select_joint_spans("alpha beta gamma", scores)


@pytest.mark.parametrize("option,value", [("top_k", 0), ("top_k", 17), ("top_k", True), ("top_k", 1.0),
                                         ("max_search_nodes", 0), ("max_search_nodes", 50001),
                                         ("max_search_nodes", True), ("max_search_nodes", 1.0)])
def test_search_limits_are_exact_bounded_integers(option, value):
    with pytest.raises(ValueError):
        subject.select_joint_spans("alpha beta gamma", packet(), **{option: value})


@pytest.mark.parametrize("source", ["", " \n", "word " * 257, "x" * 16385, "é" * 1025, "\ud800"])
def test_source_rejection_never_truncates_or_substitutes(source):
    with pytest.raises(ValueError):
        subject.select_joint_spans(source, {})


def test_float32_span_overflow_rejected():
    scores = packet()
    largest = struct.unpack("!f", bytes.fromhex("7f7fffff"))[0]
    point(scores, "actor", 0, largest)
    with pytest.raises(ValueError, match="overflows float32"):
        subject.select_joint_spans("alpha beta gamma", scores)


def test_absent_facet_scores_still_require_complete_finite_float32_heads():
    scores = packet()
    scores["end_logits"]["temporal"][2] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        subject.select_joint_spans("alpha beta gamma", scores)


def test_selection_never_constructs_or_invokes_legacy_models(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("model construction or numerical helper attempted")
    for name in ("SpanLegalFormulaDecoder", "_restore", "_batch", "_model"):
        monkeypatch.setattr(owner, name, denied)
    assert subject.select_joint_spans("alpha beta gamma", packet(), top_k=16)["status"] == "selected"


def test_module_import_and_selection_do_not_import_tensor_libraries(monkeypatch):
    original = builtins.__import__
    denied = {"torch", "tensorflow", "transformers", "sentence_transformers", "numpy"}
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in denied:
            raise AssertionError("numerical import attempted: " + name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    assert subject.select_joint_spans("alpha beta gamma", packet(), top_k=16)["status"] == "selected"
    path = Path(subject.__file__).resolve()
    program = """
import builtins, importlib.util, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch','tensorflow','transformers','sentence_transformers','numpy'}:
        raise AssertionError('numerical import attempted: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location('pure_joint_selector', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(root in sys.modules for root in ['torch','tensorflow','transformers','sentence_transformers','numpy'])
"""
    completed = subprocess.run([sys.executable, "-c", program, str(path)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
