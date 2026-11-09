"""Unsigned contextual correspondence with actual fictional source owners.

These tests reuse authored source and interpretation fixtures. They exercise
read-only correspondence, not independent legal review, signing, training,
network inference, or a Lean build. Context responses never become V1 reviews.
"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_binding_v2 as binding,
    legal_source_sampling_definition_review_v2 as owner,
    legal_source_sampling_context_definition_review_v2 as contextual,
)


def _fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_OLD = _fixture(
    "_context_correspondence_old_fixture",
    "test_legal_source_sampling_definition_review_v2.py",
)
_CONTEXT = _fixture(
    "_context_correspondence_binding_fixture",
    "test_legal_source_sampling_context_definition_binding_v2.py",
)
digest, sha, transport = _OLD.digest, _OLD.sha, _OLD.transport


def joined_case(family="fol", *, shape="opaque", split=False, responses=None):
    original = _OLD.joined_case(family, shape=shape, split=split)
    context_case = _CONTEXT.prepared(family=family, split=split)
    # The explicitly authored AST may differ, but the complete physical source
    # and its sampler population must already be identical. No prose is parsed
    # into a new interpretation here.
    assert context_case["case"]["raw"] == original["source"]["raw"]
    assert context_case["case"]["bundle"] == original["source"]["bundle"]
    context_case["case"] = original["source"]
    offered = [] if responses is None else responses(context_case)
    result = _CONTEXT.prepare(context_case, responses=offered)
    assert result["base_binding"] == original["binding"]
    replay = {
        "request_raw": original["source"]["request_raw"],
        "context": context_case["context"], "responses": offered,
        "sources": context_case["sources"], "attachments": context_case["attachments"],
        "expected_request_sha256": sha(original["source"]["request_raw"]),
        "expected_definition_bundle_sha256": digest(original["source"]["bundle"]),
        "expected_context_sha256": digest(context_case["context"]),
        "expected_response_sha256s": [digest(row) for row in offered],
        "expected_attachments_sha256": digest(context_case["attachments"]),
    }
    arguments = {
        key: value for key, value in original["args"].items()
        if key != "binding_replay_inputs"
    }
    arguments.update(
        expected_binding_sha256=digest(result), contextual_replay_inputs=replay,
    )
    return {
        "original": original, "context_case": context_case, "binding": result,
        "subject": original["subject"], "args": arguments,
    }


def prepare(case, *, result=None, subject=None, **overrides):
    return owner.prepare_contextual_definition_review_correspondence_v2(
        case["binding"] if result is None else result,
        case["subject"] if subject is None else subject,
        **{**case["args"], **overrides},
    )


def validate(case, result, **overrides):
    return owner.validate_contextual_definition_review_correspondence_v2(
        result, case["binding"], case["subject"],
        expected_correspondence_sha256=digest(result),
        **{**case["args"], **overrides},
    )


def assert_unsigned(result):
    assert result["schema"] == "legal-source-sampling-context-definition-review-correspondence/v1"
    assert set(result) == {"schema", "definition_correspondence", "contextual_correspondence"}
    _OLD.assert_unsigned(result["definition_correspondence"])
    metadata = result["contextual_correspondence"]
    assert metadata["schema"] == "legal-source-sampling-context-definition-review-metadata/v1"
    assert metadata["unsigned"] is True and metadata["assessment_created"] is False
    assert metadata["authority"] and all(value is False for value in metadata["authority"].values())
    for key in ("training_mask", "evaluation_gold_mask"):
        assert type(metadata[key]) is int and metadata[key] == 0
    for key in (
        "original_subject_covers_contextual_companion",
        "original_subject_covers_contextual_responses",
        "response_payloads_embedded", "related_declarations_close_definition_review",
    ):
        assert metadata[key] is False
    assert metadata["external_contextual_inputs_required"] is True


@pytest.fixture(scope="module")
def base_case():
    return joined_case()


@pytest.fixture(scope="module")
def base_link(base_case):
    return prepare(base_case)


@pytest.fixture(scope="module")
def declared_case():
    def responses(case):
        return [
            *[_CONTEXT.response(case, guide) for guide in case["required_guides"]],
            _CONTEXT.response(case, case["use_guide"], source_index=1),
        ]
    return joined_case(responses=responses)


@pytest.fixture(scope="module")
def declared_link(declared_case):
    return prepare(declared_case)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_real_owner_join_keeps_original_subject_and_complete_populations(family):
    case = joined_case(family)
    before = deepcopy(case)
    result = prepare(case)
    assert_unsigned(result)
    assert result["definition_correspondence"] == _OLD.prepare(case["original"])
    metadata, source = result["contextual_correspondence"], case["binding"]["contextual_binding"]
    population = case["binding"]["contextual_population"]
    for field in ("source_identity", "required_subjects", "required_support_nominations", "related_target_responses"):
        assert metadata[field] == source[field]
    assert metadata["contextual_population_counts"] == population["counts"]
    assert metadata["contextual_population_subject_count"] == population["subject_count"]
    assert metadata["contextual_population_response_count"] == 0
    assert metadata["context_counts"] == case["context_case"]["context"]["counts"]
    assert metadata["response_declarations"] == []
    assert metadata["direct_response_refs"] == []
    assert result["definition_correspondence"]["population_subjects"] == case["binding"]["base_binding"]["population"]["subjects"]
    assert owner.contextual_definition_review_correspondence_sha256(result) == digest(result)
    assert validate(case, result) == result
    assert case == before


def test_original_transport_bytes_keep_their_independent_namespaces(base_case, base_link):
    case = base_case
    original = base_link["definition_correspondence"]
    assert original["original_input_pins"] == case["args"]["expected_candidate_pin"]
    for field in ("candidate_raw", "sampling_report_raw", "descriptor_raw"):
        raw = case["args"]["candidate_inputs"][field]
        assert sha(raw) != digest(_OLD.json.loads(raw))
    assert original["expected_context_population"] == case["args"]["expected_context_population"]
    assert original["context_slot_ids"] == case["subject"]["context_slot_ids"]


def test_direct_and_related_declarations_keep_exact_roles_citations_and_exposure(declared_case, declared_link):
    case, result = declared_case, declared_link
    metadata, bound = result["contextual_correspondence"], case["binding"]["contextual_binding"]
    assert metadata["required_subjects"] == bound["required_subjects"]
    assert metadata["related_target_responses"] == bound["related_target_responses"]
    responses = case["args"]["contextual_replay_inputs"]["responses"]
    assert len(metadata["response_declarations"]) == len(responses)
    direct_cids = {
        ref["record_cid"] for row in bound["required_subjects"] for ref in row["direct_response_refs"]
    }
    assert {ref["record_cid"] for ref in metadata["direct_response_refs"]} == direct_cids
    for row, response in zip(metadata["response_declarations"], responses, strict=True):
        declaration = response["declaration"]
        assert row["response_ref"]["sha256"] == digest(response)
        assert row["response_ref"]["record_cid"] == response["record_cid"]
        assert row["declaration_sha256"] == digest(declaration)
        assert row["bundle_sha256"] == declaration["bundle_sha256"]
        assert row["subject_ref"] == declaration["subject_ref"]
        assert row["response_role"] == ("direct" if response["record_cid"] in direct_cids else "related")
        assert row["reviewer_declaration_ref"] == {"sha256": digest(declaration["reviewer_declaration"])}
        assert row["exposure_declaration_ref"] == {"sha256": digest(declaration["exposure_declaration"])}
        assert row["exposure_declaration"] == declaration["exposure_declaration"]
        assert row["exposure_declaration"]["candidate_interpretations_exposed"] is True
    assert all(row["state"] == "declarations_recorded" for row in metadata["required_subjects"])
    assert all(row["state"] == "pending" for row in result["definition_correspondence"]["required_subjects"])
    assert result["definition_correspondence"]["response_count"] == 0
    assert_unsigned(result)
    assert validate(case, result) == result


def test_related_norm_response_does_not_complete_a_definition_or_cover_signed_subject():
    case = joined_case(responses=lambda ctx: [_CONTEXT.response(ctx, ctx["use_guide"], source_index=1)])
    result = prepare(case)
    metadata = result["contextual_correspondence"]
    assert metadata["direct_response_refs"] == []
    assert len(metadata["related_target_responses"]) == 1
    assert len(metadata["response_declarations"]) == 1
    assert metadata["response_declarations"][0]["response_role"] == "related"
    assert all(row["state"] == "pending" for row in metadata["required_subjects"])
    related = metadata["related_target_responses"][0]
    assert related["direct_definition_review_credit"] is False
    assert related["required_support_links"][0]["cited_evidence_count"] == 1
    assert_unsigned(result)


@pytest.mark.parametrize("state", ["unsupported", "disputed"])
def test_unresolved_response_states_remain_unresolved_in_review_correspondence(state):
    def responses(case):
        guide = case["required_guides"][-1]
        if state == "unsupported":
            return [_CONTEXT.response(case, guide, unsupported=True)]
        return [
            _CONTEXT.response(case, guide, principal="fictional-a", unsupported=True, finding="First explicit fixture interpretation."),
            _CONTEXT.response(case, guide, principal="fictional-b", finding="Conflicting explicit fixture interpretation."),
        ]
    case = joined_case(responses=responses)
    result = prepare(case)
    metadata = result["contextual_correspondence"]
    assert metadata["source_declaration_status"] == state
    assert any(row["state"] == state for row in metadata["required_subjects"])
    assert result["definition_correspondence"]["source_declaration_status"] == "pending"
    assert_unsigned(result)


def test_different_prose_with_equal_dispositions_is_retained_without_interpretation():
    def responses(case):
        guide = case["required_guides"][-1]
        return [
            _CONTEXT.response(case, guide, principal="fictional-a", finding="First explicit fixture interpretation."),
            _CONTEXT.response(case, guide, principal="fictional-b", finding="Different explicit fixture interpretation."),
        ]
    case = joined_case(responses=responses)
    result = prepare(case)
    metadata = result["contextual_correspondence"]
    offered = case["args"]["contextual_replay_inputs"]["responses"]
    subject = case["context_case"]["required_guides"][-1]["subject_ref"]
    row = next(item for item in metadata["required_subjects"] if item["subject_ref"] == subject)
    assert row["state"] == "declarations_recorded"
    assert metadata["source_declaration_status"] == "pending"
    assert any(item["state"] == "pending" for item in metadata["required_subjects"])
    assert [ref["record_cid"] for ref in row["direct_response_refs"]] == [item["record_cid"] for item in offered]
    assert [item["response_ref"]["record_cid"] for item in metadata["response_declarations"]] == [item["record_cid"] for item in offered]
    assert offered[0]["declaration"]["meaning_proposals"][0]["finding"] != offered[1]["declaration"]["meaning_proposals"][0]["finding"]
    assert metadata["declaration_prose_interpreted"] is False
    assert_unsigned(result)


def test_split_scope_parent_and_shared_geometry_remain_required_in_correspondence():
    case = joined_case(shape="shared", split=True)
    result = prepare(case)
    original = result["definition_correspondence"]
    required, unrelated = _OLD._BINDING.split_parent_guides(case["original"]["source"])
    refs = [row["subject_ref"] for row in original["required_subjects"]]
    assert required["subject_ref"] in refs and unrelated["subject_ref"] not in refs
    population = original["population_subjects"]
    assert sum(row["subject_ref"]["kind"] == "withheld_context" for row in population) == 2
    assert any(len(row["source_role_bindings"]) > 1 for row in original["occurrence_context_links"])
    assert result["contextual_correspondence"]["required_subjects"] == case["binding"]["contextual_binding"]["required_subjects"]
    assert_unsigned(result)


def test_context_envelope_is_not_a_v1_correspondence_binding(base_case):
    args = dict(base_case["original"]["args"], expected_binding_sha256=digest(base_case["binding"]))
    with pytest.raises(ValueError):
        _OLD.prepare(base_case["original"], binding=base_case["binding"], **args)


def test_v1_response_cannot_be_injected_into_contextual_replay(base_case):
    args = deepcopy(base_case["args"])
    old = base_case["original"]["source"]
    offered = _OLD._BINDING.response(old, _OLD._BINDING.selected_guides(old)[0])
    replay = args["contextual_replay_inputs"]
    replay["responses"] = [offered]
    replay["expected_response_sha256s"] = [digest(offered)]
    with pytest.raises(ValueError):
        prepare(base_case, **args)


@pytest.mark.parametrize("field", ["expected_binding_sha256", "expected_subject_sha256", "expected_manifest_sha256"])
def test_wrong_independent_pin_refuses(base_case, field):
    with pytest.raises(ValueError):
        prepare(base_case, **{field: "0" * 64})


def test_wrong_output_pin_refuses(base_case, base_link):
    with pytest.raises(ValueError):
        owner.validate_contextual_definition_review_correspondence_v2(
            base_link, base_case["binding"], base_case["subject"],
            expected_correspondence_sha256="0" * 64, **base_case["args"],
        )


@pytest.mark.parametrize("change", [
    "extra_replay", "missing_replay", "tuple_responses", "wrong_request_bytes",
    "oversize_request", "invalid_pin", "extra_candidate_bytes", "candidate_text",
])
def test_closed_typed_preflight_precedes_operation_owners(base_case, change):
    args = deepcopy(base_case["args"])
    replay = args["contextual_replay_inputs"]
    if change == "extra_replay":
        replay["claimed_review_authority"] = True
    elif change == "missing_replay":
        replay.pop("sources")
    elif change == "tuple_responses":
        replay["responses"] = ()
    elif change == "wrong_request_bytes":
        replay["request_raw"] = "not-original-bytes"
    elif change == "oversize_request":
        replay["request_raw"] = b" " * (1024 * 1024 + 1)
        replay["expected_request_sha256"] = sha(replay["request_raw"])
    elif change == "invalid_pin":
        replay["expected_context_sha256"] = "not-a-sha256"
    elif change == "extra_candidate_bytes":
        args["candidate_inputs"]["unbound_raw"] = b"extra"
    else:
        args["candidate_inputs"]["raw_html"] = "not-bytes"
    with patch.object(contextual, "_owners", side_effect=AssertionError("owners reached before preflight")) as operation:
        with pytest.raises(ValueError):
            prepare(base_case, **args)
        operation.assert_not_called()


@pytest.mark.parametrize("bound", ["MAX_RECORD_BYTES", "MAX_OUTPUT_BYTES", "MAX_INPUT_BYTES"])
def test_lowered_complete_input_bounds_refuse_before_owners(base_case, bound):
    with patch.object(contextual, bound, 1):
        with patch.object(contextual, "_owners", side_effect=AssertionError("owners reached")) as operation:
            with pytest.raises(ValueError):
                prepare(base_case)
            operation.assert_not_called()


@pytest.mark.parametrize("field", ["report_raw", "candidate_raw", "sampling_report_raw", "descriptor_raw"])
def test_reserialized_transport_cannot_replace_independently_bound_original_bytes(base_case, field):
    args = deepcopy(base_case["args"])
    original = args["candidate_inputs"][field]
    changed = original + b"\n"
    assert _OLD.json.loads(changed) == _OLD.json.loads(original)
    args["candidate_inputs"][field] = changed
    with pytest.raises(ValueError):
        prepare(base_case, **args)


def test_repinned_pretty_report_cannot_change_the_existing_graph_transport(base_case):
    args = deepcopy(base_case["args"])
    pretty = transport(_OLD.json.loads(args["candidate_inputs"]["report_raw"]))
    assert pretty != args["candidate_inputs"]["report_raw"]
    args["candidate_inputs"]["report_raw"] = pretty
    args["expected_candidate_pin"]["report_sha256"] = sha(pretty)
    with pytest.raises(ValueError):
        prepare(base_case, **args)


def test_another_valid_ast_over_same_source_cannot_replace_the_original_review_subject(base_case):
    other = joined_case(shape="nested")
    assert other["original"]["source"]["raw"] == base_case["original"]["source"]["raw"]
    assert other["subject"]["native_binding"]["native_ast"] != base_case["subject"]["native_binding"]["native_ast"]
    args = dict(base_case["args"])
    for key in (
        "candidate_inputs", "expected_candidate_pin", "context_inputs", "expected_context_population",
        "dependency_manifest", "expected_manifest_sha256", "required_dependency_ids", "expected_subject_sha256",
    ):
        args[key] = other["args"][key]
    with pytest.raises(ValueError):
        prepare(base_case, subject=other["subject"], **args)


@pytest.mark.parametrize("change", ["missing_context", "reordered_context", "duplicated_context", "missing_dependency", "reordered_dependency", "changed_manifest"])
def test_complete_occurrence_and_manifest_closure_is_required(base_case, change):
    args = deepcopy(base_case["args"])
    if change in {"missing_context", "reordered_context", "duplicated_context"}:
        for field in ("context_inputs", "expected_context_population"):
            if change == "missing_context":
                args[field] = args[field][:-1]
            elif change == "reordered_context":
                args[field].reverse()
            else:
                args[field][-1] = deepcopy(args[field][0])
    elif change in {"missing_dependency", "reordered_dependency"}:
        ids = args["required_dependency_ids"]
        args["required_dependency_ids"] = ids[:-1] if change == "missing_dependency" else list(reversed(ids))
    else:
        args["dependency_manifest"]["artifacts"].pop()
    with pytest.raises(ValueError):
        prepare(base_case, **args)


@pytest.mark.parametrize("field,replacement", [
    ("source_geometry_replayed", 1),
    ("context_packet_population_complete", 1),
    ("source_semantics_verified", 0),
])
def test_resealed_subject_evidence_requires_canonical_types_not_python_equality(base_case, field, replacement):
    subject = deepcopy(base_case["subject"])
    native = subject["native_binding"]
    assert native[field] == replacement and type(native[field]) is bool
    native[field] = replacement
    subject["native_binding"] = _CONTEXT.reseal(native)
    with pytest.raises(ValueError):
        prepare(base_case, subject=subject, expected_subject_sha256=digest(subject))


@pytest.mark.parametrize("change", ["authority", "false_zero", "mask_false", "required_roles", "source_identity", "population_count", "old_context", "subject_covers_context"])
def test_resealed_output_does_not_replace_complete_typed_regeneration(base_case, base_link, change):
    offered = deepcopy(base_link)
    metadata = offered["contextual_correspondence"]
    if change in {"authority", "false_zero"}:
        metadata["authority"][next(iter(metadata["authority"]))] = True if change == "authority" else 0
    elif change == "mask_false":
        metadata["training_mask"] = False
    elif change == "required_roles":
        metadata["required_subjects"][0]["roles"] = []
    elif change == "source_identity":
        metadata["source_identity"]["normalized_view_id"] += "-other"
    elif change == "population_count":
        metadata["contextual_population_subject_count"] -= 1
    elif change == "old_context":
        old = offered["definition_correspondence"]
        old["context_slot_ids"].pop()
        offered["definition_correspondence"] = _CONTEXT.reseal(old)
    else:
        metadata["original_subject_covers_contextual_responses"] = True
    offered["contextual_correspondence"] = _CONTEXT.reseal(metadata)
    with pytest.raises(ValueError):
        validate(base_case, offered)


@pytest.mark.parametrize("change", ["exposure", "response_role", "citation", "response_order"])
def test_resealed_declarations_keep_exact_exposure_citations_and_response_roles(declared_case, declared_link, change):
    offered = deepcopy(declared_link)
    metadata = offered["contextual_correspondence"]
    if change == "exposure":
        metadata["response_declarations"][0]["exposure_declaration"]["candidate_interpretations_exposed"] = False
    elif change == "response_role":
        metadata["response_declarations"][-1]["response_role"] = "direct"
    elif change == "citation":
        metadata["related_target_responses"][0]["required_support_links"][0]["cited_evidence_refs"] = []
    else:
        metadata["response_declarations"].reverse()
    offered["contextual_correspondence"] = _CONTEXT.reseal(metadata)
    with pytest.raises(ValueError):
        validate(declared_case, offered)


def test_detached_snapshot_mutation_is_detected_without_mutating_the_caller(base_case):
    before = deepcopy(base_case)
    actual = binding.validate_contextual_definition_binding_v2

    def mutate_after_replay(result, *args, **kwargs):
        checked = actual(result, *args, **kwargs)
        result["contextual_binding"]["status"] = "mutation-after-owner-return"
        return checked

    with patch.object(binding, "validate_contextual_definition_binding_v2", side_effect=mutate_after_replay):
        with pytest.raises(ValueError):
            prepare(base_case)
    assert base_case == before


def test_changed_producer_pin_refuses_without_modifying_any_source(base_case):
    with patch.dict(contextual._IMPORTED_PURE_PINS, {str(contextual._SELF_PATH): "0" * 64}):
        with pytest.raises(ValueError):
            prepare(base_case)


def test_output_bound_refuses_instead_of_dropping_companions(base_case):
    with patch.object(contextual, "MAX_OUTPUT_BYTES", 1):
        with pytest.raises(ValueError):
            prepare(base_case)


def test_public_import_is_inert_and_exposes_both_explicit_domains():
    script = r"""
import builtins
import importlib.util
import sys

prefixes = ('ipfs_datasets_py', 'torch', 'transformers', 'tensorflow', 'symai')
original = builtins.__import__
def guarded(name, *args, **kwargs):
    assert not any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes), name
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location('isolated_correspondence_owner', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
expected = {
    'prepare_definition_review_correspondence_v2',
    'validate_definition_review_correspondence_v2',
    'definition_review_correspondence_sha256',
    'prepare_contextual_definition_review_correspondence_v2',
    'validate_contextual_definition_review_correspondence_v2',
    'contextual_definition_review_correspondence_sha256',
}
assert set(module.__all__) == expected
assert all(callable(getattr(module, name)) for name in expected)
assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules for prefix in prefixes)
print('inert-six-api-import')
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, owner.__file__],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "inert-six-api-import"
