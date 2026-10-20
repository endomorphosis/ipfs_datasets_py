"""Unresolved batch members cannot bypass the standalone LegalIR split policy.

The manifest and examples are fictional, constructed directly. No trainer,
checkpoint, corpus artifact, model or historical test module is imported.
"""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits


OPERATIONS = (
    splits.TRAINING_OPERATION,
    splits.HPARAM_SELECTION_OPERATION,
    splits.REPRESENTATION_PROMOTION_OPERATION,
    splits.CODEX_TODO_PROJECTION_OPERATION,
)
PRIMARY = {
    "training": "train",
    "hparam_selection": "validation",
    "representation_promotion": "canary",
    "codex_todo_projection": "train",
}
ALLOWED = {
    "training": ["train"],
    "hparam_selection": ["validation"],
    "representation_promotion": ["canary"],
    "codex_todo_projection": ["train", "validation"],
}


@pytest.fixture
def manifest():
    examples = []
    assignments = {}
    for partition in ("train", "validation", "canary", "holdout"):
        for suffix, start in (("a", 10), ("b", 30)):
            sample_id = partition + "-" + suffix
            examples.append(splits.LegalIRSplitExample(
                sample_id=sample_id,
                content_hash=hashlib.sha256(("fictional " + sample_id).encode()).hexdigest(),
                citation_clusters=("authored:" + partition,),
                source_span_key=f"doc-{partition}:{start}:{start + 10}",
            ))
            assignments[sample_id] = partition
    result = splits.LegalIRSplitManifest(
        examples=tuple(examples), assignments=assignments,
        config_digest=hashlib.sha256(b"fictional-membership-policy-fixture").hexdigest(),
    )
    assert splits.validate_legal_ir_eval_splits(result).passed
    return result


def source_reference(partition):
    return {"source_document_id": "doc-" + partition, "span_start": 10, "span_end": 20}


def wrong_split(operation, sample_id="holdout-a"):
    return {"allowed_splits": ALLOWED[operation], "operation": operation,
            "sample_id": sample_id, "split": "holdout", "known_example": True}


def policy_error(manifest, operation, items):
    with pytest.raises(splits.LegalIRSplitPolicyError) as caught:
        splits.authorize_legal_ir_split_use(manifest, operation=operation, items=items)
    assert caught.value.operation == operation
    return caught.value.disallowed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_empty_items_preserve_manifest_only_validation(manifest, operation):
    expected = splits.validate_legal_ir_eval_splits(manifest)
    assert splits.authorize_legal_ir_split_use(manifest, operation=operation) == expected
    assert splits.authorize_legal_ir_split_use(manifest, operation=operation, items=()) == expected
    assert splits.authorize_legal_ir_split_use(manifest, operation=operation, items=[]) == expected


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("item", [
    pytest.param({}, id="empty-mapping"),
    pytest.param({"source_text": "Fictional text does not identify manifest membership."}, id="source-text-only"),
    pytest.param({"citation": "Unmatched fictional citation"}, id="unmatched-citation"),
    pytest.param({"source_document_id": "doc-unmatched", "span_start": 10, "span_end": 20}, id="unmatched-span"),
    pytest.param({"sample_id": " ", "id": "", "sample_ids": ["", None, "  "]}, id="blank-ids"),
    pytest.param(SimpleNamespace(), id="empty-object"),
    pytest.param(SimpleNamespace(source_text="Fictional unbound source"), id="object-source-text-only"),
    pytest.param(SimpleNamespace(citation="Unmatched fictional citation"), id="object-unmatched-citation"),
    pytest.param(SimpleNamespace(sample_id=" ", sample_ids=(), source_document_id="doc-unmatched",
                                 span_start=10, span_end=20), id="object-blank-ids-unmatched-span"),
],)
def test_every_unresolved_supplied_item_is_rejected(manifest, operation, item):
    assert policy_error(manifest, operation, [item]) == (
        {"reason": "sample_not_resolved_in_split_manifest", "item_index": 0},
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_mixed_batch_reports_every_invalid_member_in_original_order(manifest, operation):
    primary = PRIMARY[operation]
    valid = primary + "-a"
    items = [
        {"sample_id": valid},
        {},
        {"sample_ids": [valid, "missing-a", "missing-a"]},
        {"sample_id": "holdout-a"},
        {"source_text": "No declared identifier"},
        {"sample_id": valid},
        source_reference(primary),
        SimpleNamespace(citation="No matching citation"),
        {"sample_id": "missing-b", "citation": "Authored " + primary, **source_reference(primary)},
        {"citation": "Authored holdout"},
    ]
    before = deepcopy(items)
    assert policy_error(manifest, operation, items) == (
        {"reason": "sample_not_resolved_in_split_manifest", "item_index": 1},
        {"reason": "sample_not_in_split_manifest", "sample_id": "missing-a"},
        wrong_split(operation),
        {"reason": "sample_not_resolved_in_split_manifest", "item_index": 4},
        {"reason": "sample_not_resolved_in_split_manifest", "item_index": 7},
        {"reason": "sample_not_in_split_manifest", "sample_id": "missing-b"},
        wrong_split(operation, "holdout-a"),
        wrong_split(operation, "holdout-b"),
    )
    assert items == before


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("id_kind", ["sample_id", "id", "sample_ids", "object"])
def test_explicit_unknown_id_never_falls_back_to_matching_source(manifest, operation, id_kind):
    primary = PRIMARY[operation]
    item = {"citation": "Authored " + primary, **source_reference(primary)}
    if id_kind == "object":
        item = SimpleNamespace(**item, sample_id="missing-explicit")
    else:
        item[id_kind] = ["missing-explicit"] if id_kind == "sample_ids" else "missing-explicit"
    assert policy_error(manifest, operation, [item]) == (
        {"reason": "sample_not_in_split_manifest", "sample_id": "missing-explicit"},
    )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("as_object", [False, True])
def test_matching_citation_resolves_all_allowed_members_after_blank_ids(manifest, operation, as_object):
    item = {"sample_id": " ", "sample_ids": ["", None],
            "citation": "  Authored " + PRIMARY[operation].upper() + "  "}
    if as_object:
        item = SimpleNamespace(**item)
    result = splits.authorize_legal_ir_split_use(manifest, operation=operation, items=[item])
    assert result.passed and result.violations == ()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("as_object", [False, True])
def test_matching_span_resolves_without_an_id_or_citation(manifest, operation, as_object):
    primary = PRIMARY[operation]
    item = {"source_document_id": "doc-" + primary,
            "source_span": {"char_start": 10, "char_end": 20}, "sample_ids": ()}
    if as_object:
        item = SimpleNamespace(**item)
    assert splits.authorize_legal_ir_split_use(manifest, operation=operation, items=[item]).passed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_unmatched_citation_can_still_resolve_exact_source_span(manifest, operation):
    item = {"sample_id": "", "citation": "No match", **source_reference(PRIMARY[operation])}
    assert splits.authorize_legal_ir_split_use(manifest, operation=operation, items=[item]).passed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_valid_composite_ids_and_repeated_ids_remain_allowed(manifest, operation):
    primary = PRIMARY[operation]
    item = {"sample_ids": [primary + "-a", primary + "-b", primary + "-a"],
            "sample_id": primary + "-b", "citation": "Authored holdout",
            **source_reference("holdout")}
    before = deepcopy(item)
    assert splits.authorize_legal_ir_split_use(manifest, operation=operation, items=[item]).passed
    assert item == before


def test_codex_projection_accepts_declared_train_and_validation_composite(manifest):
    assert splits.authorize_legal_ir_split_use(manifest, operation="codex_todo_projection",
        items=[{"sample_ids": ["train-a", "validation-a", "train-a"]}]).passed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_composite_unknown_and_wrong_split_ids_are_deduplicated_per_item(manifest, operation):
    item = {"sample_ids": ["missing", "holdout-a", "missing", PRIMARY[operation] + "-a", "holdout-a"],
            "sample_id": "missing"}
    assert policy_error(manifest, operation, [item]) == (
        {"reason": "sample_not_in_split_manifest", "sample_id": "missing"},
        wrong_split(operation),
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_citation_fallback_keeps_every_wrong_split_diagnostic(manifest, operation):
    assert policy_error(manifest, operation, [{"citation": "Authored holdout"}]) == (
        wrong_split(operation, "holdout-a"), wrong_split(operation, "holdout-b"),
    )


@pytest.mark.parametrize("wrapper,operation", [
    (splits.require_training_split, "training"),
    (splits.require_hparam_selection_split, "hparam_selection"),
    (splits.require_representation_promotion_split, "representation_promotion"),
    (splits.require_codex_todo_projection_split, "codex_todo_projection"),
])
def test_public_operation_wrappers_preserve_unresolved_membership_failure(manifest, wrapper, operation):
    with pytest.raises(splits.LegalIRSplitPolicyError) as caught:
        wrapper(manifest, items=[{}])
    assert caught.value.operation == operation
    assert caught.value.disallowed == ({"reason": "sample_not_resolved_in_split_manifest", "item_index": 0},)
