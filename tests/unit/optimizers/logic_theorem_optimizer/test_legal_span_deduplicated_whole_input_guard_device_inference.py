"""Portable controls for exact owner/attribute inventory deduplication.

Only the root runs these model controls. Existing CG8 fixtures are imported
from their pinned current test source, without collecting its test functions.
No speed, native encoder, trained 4096D or production claim is established.
"""
from copy import deepcopy
import ast
import hashlib
import importlib.util
from pathlib import Path
import inspect
import sys

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_deduplicated_whole_input_guard_device_inference as subject

FIXTURE_SOURCE = Path(__file__).with_name("test_legal_span_whole_input_guard_device_inference.py")
assert hashlib.sha256(FIXTURE_SOURCE.read_bytes()).hexdigest() == "c5633ae0b122901323ee39d422a7cd3a985d169233d360bf6e2bc9037ccfc5b6"
_SPEC = importlib.util.spec_from_file_location("_cg9_held_cg8_fixture_support", FIXTURE_SOURCE)
support = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = support
_SPEC.loader.exec_module(support)
# Reuse fixture definitions/helpers only. Predecessor test functions are never
# rebound into this test module, so root collection runs only these controls.
one_thread, checkpoint, scheduler = support.one_thread, support.checkpoint, support.scheduler


def _duplicate_keys():
    seen, duplicates = set(), []
    for owner, name, _ in subject._BASE_METHODS_BEFORE_DEDUP:
        key = id(owner), name
        if key in seen:
            assert not any(owner is item and name == attribute for item, attribute in duplicates)
            duplicates.append((owner, name))
        seen.add(key)
    return tuple(duplicates)


DUPLICATES = _duplicate_keys()


def api(cp):
    return (subject.DeduplicatedWholeInputDeviceDimensionalSpanSession if support.dimension(cp) == 768
            else subject.DeduplicatedWholeInputDeviceLeanstral4096SpanSession)


def open_cpu(cp, scheduler, monkeypatch, *, optimized=True, **kwargs):
    if optimized:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    options = {"synthetic_unreceipted": True} if support.dimension(cp) == 4096 else {}
    return api(cp)(cp, expected_checkpoint_sha256=support.span.checkpoint_digest(cp),
                   scheduler=scheduler, optimized=optimized, **options, **kwargs)


def test_original_inventory_first_records_exact_keys_and_wrapped_checks_are_retained():
    old = support.subject
    before, after = subject._BASE_METHODS_BEFORE_DEDUP, subject._BASE_METHODS
    assert len(DUPLICATES) == 6 and len(before) - len(after) == 6
    assert len(before) == len(old._BASE_METHODS)
    assert all(owner is previous_owner and name == previous_name and subject._same(expected[0], previous)
               for (owner, name, expected), (previous_owner, previous_name, previous) in zip(before, old._BASE_METHODS))
    first = {}
    for record in before:
        first.setdefault((id(record[0]), record[1]), record)
    assert len(first) == len(after)
    assert all(record is original for record, original in zip(after, first.values()))
    assert tuple(first) == subject._BASE_METHOD_KEYS
    assert frozenset(first) == subject._BASE_METHOD_KEYSET
    assert len(subject._BASE_WRAPPED_METHODS) == len(old._BASE_WRAPPED_METHODS)
    for actual, expected in zip(subject._BASE_WRAPPED_METHODS, old._BASE_WRAPPED_METHODS):
        assert all(left is right for left, right in zip(actual[:3], expected[:3]))
        assert subject._same(actual[2], expected[3])
    subject._check_method_inventory()
    descriptor = subject.inference_implementation()["binding_inventory_deduplication"]
    assert descriptor == {"schema": "exact-owner-attribute-binding-inventory/v1",
        "key_policy": "exact_owner_object_identity_and_attribute_name", "original_record_count": len(before),
        "checked_record_count": len(after), "removed_duplicate_record_count": 6,
        "original_distinct_key_count": len(after), "checked_distinct_key_count": len(after),
        "first_record_preserved": True, "original_inventory_identity_checked": True,
        "expected_counts_keys_and_order_checked": True,
        "keyset_and_order_admission_scope": "initial_exact_keys_then_fresh_immutable_inventory_identity_and_counts",
        "wrapped_binding_inventory_deduplicated": False,
        "freshness_success_cached": False}


def test_identity_dedup_preserves_distinct_equal_owners_and_distinct_function_aliases():
    class EqualOwner(type):
        def __eq__(self, other): return isinstance(other, EqualOwner)
        __hash__ = None
    class First(metaclass=EqualOwner): pass
    class Second(metaclass=EqualOwner): pass
    function = lambda: None
    first = First, "decode", subject._fingerprint(function)
    duplicate = First, "decode", subject._fingerprint(function)
    alias = First, "infer", subject._fingerprint(function)
    other = Second, "decode", subject._fingerprint(function)
    assert First == Second and First is not Second
    result = subject._deduplicate_method_records((first, duplicate, alias, other))
    assert len(result) == 3 and all(left is right for left, right in zip(result, (first, alias, other)))


def test_conflicting_duplicate_snapshot_is_refused_instead_of_silently_discarded():
    first, other = lambda: None, lambda: 1
    owner = object()
    with pytest.raises(ValueError, match="fingerprints differ"):
        subject._deduplicate_method_records(((owner, "infer", subject._fingerprint(first)),
                                              (owner, "infer", subject._fingerprint(other))))


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("count", [1, 16, 32])
def test_complete_cpu_parity_four_logits_rng_and_every_poll_match_held_cg8(checkpoint, scheduler, monkeypatch, optimized, count):
    texts, vectors = support.inputs(checkpoint, count)
    original, rng = support.span._raw(checkpoint), torch.get_rng_state().clone()
    with support.open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized) as baseline:
        with support.observe(baseline) as previous:
            expected = baseline.infer(texts, vectors)
        expected_logits = support.guarded_logits(baseline, texts, vectors)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized) as owner:
        with support.observe(owner) as current:
            actual = owner.infer(texts, vectors)
        actual_logits = support.guarded_logits(owner, texts, vectors)
        for key in ("rows", "actual_forward_batches", "input_receipts", "schema", "checkpoint_sha256", "latent_ablation"):
            assert actual[key] == expected[key]
        assert set(actual_logits) == set(expected_logits) == {"modality", "presence", "start", "end"}
        assert all(torch.equal(actual_logits[key], expected_logits[key]) for key in actual_logits)
        assert current == previous
        assert current["poll"] == (4 + 2 * count if optimized else 2 + 2 * count)
        assert current["forward"] == (1 if optimized else count)
        assert current["input_guards"] == 1 and current["outer_checkpoint_guard"] == current["restores"] == 0
        profile = actual["execution_profile"]
        candidate = subject.PROFILE_768 if support.dimension(checkpoint) == 768 else subject.PROFILE_4096
        assert profile["whole_input_guard_profile_id"] == profile["session_profile_id"] == candidate
        assert profile["profile_id"] == (candidate if optimized else expected["execution_profile"]["profile_id"])
        assert profile["whole_input_guard_currentness"] == expected["execution_profile"]["whole_input_guard_currentness"]
        assert profile["whole_input_guard_implementation"]["binding_inventory_deduplication"]["removed_duplicate_record_count"] == 6
        assert owner.checkpoint == checkpoint and torch.equal(rng, torch.get_rng_state())
        assert "whole_input_guard_currentness" not in owner.describe()
    assert support.span._raw(checkpoint) == original and scheduler.active_leases() == []


@pytest.mark.parametrize("owner,attribute", DUPLICATES, ids=lambda value: value if isinstance(value, str) else value.__name__)
@pytest.mark.parametrize("phase", ["constructor", "after_forward"])
@pytest.mark.parametrize("optimized", [False, True])
def test_every_removed_duplicate_still_refuses_live_method_replacement(checkpoint, scheduler, monkeypatch, owner, attribute, phase, optimized):
    foreign = lambda *args, **kwargs: None
    if phase == "constructor":
        with monkeypatch.context() as patch:
            patch.setattr(owner, attribute, foreign)
            with support.observe() as counts:
                with pytest.raises(ValueError, match="changed"):
                    open_cpu(checkpoint, scheduler, patch, optimized=optimized)
            assert counts["restores"] == 0 and scheduler.active_leases() == []
        return
    texts, vectors = support.inputs(checkpoint, 1)
    cancel = support.Mutation(None, texts, vectors, phase="after_forward", action=lambda event: None)
    session = open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized, cancel_event=cancel)
    try:
        cancel.owner = session
        with monkeypatch.context() as patch:
            cancel.action = lambda event: patch.setattr(owner, attribute, foreign)
            with support.observe(session, cancellation=cancel) as counts:
                with pytest.raises(ValueError, match="changed"): session.infer(texts, vectors)
            assert cancel.triggered and counts["forward"] == 1 and not session._active and not session._observations
        session.describe()
    finally:
        session.close()
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("fault", ["function_body", "wrapped_body", "wrapper_link", "defaults", "closure", "inventory_helper", "private_namespace", "inherited_resolution"])
@pytest.mark.parametrize("phase", ["constructor", "after_forward"])
def test_code_defaults_closures_wrappers_namespace_and_resolution_remain_fresh(checkpoint, scheduler, monkeypatch, fault, phase):
    def mutate(patch, owner=None):
        foreign = lambda *args, **kwargs: None
        constructor = api(checkpoint).__init__
        if fault == "function_body":
            method = subject._deduplicate_method_records
            patch.setattr(method, "__code__", method.__code__.replace(co_consts=method.__code__.co_consts + (None,)))
        elif fault == "wrapped_body":
            method = constructor.__wrapped__
            patch.setattr(method, "__code__", method.__code__.replace(co_consts=method.__code__.co_consts + (None,)))
        elif fault == "wrapper_link": patch.setattr(constructor, "__wrapped__", foreign)
        elif fault == "defaults":
            patch.setattr(subject._check_method_inventory, "__kwdefaults__", {**subject._check_method_inventory.__kwdefaults__, "_counts": (0, 0, 0)})
        elif fault == "closure":
            cell = constructor.__closure__[constructor.__code__.co_freevars.index("verify")]
            patch.setattr(cell, "cell_contents", foreign)
        elif fault == "inventory_helper": patch.setattr(subject, "_check_method_inventory", foreign)
        elif fault == "private_namespace":
            decode = subject._DECODE_768 if support.dimension(checkpoint) == 768 else subject._DECODE_4096
            patch.setitem(decode.__globals__, "_INPUT_GUARD", object)
        else: patch.setattr(api(checkpoint) if owner is None else owner, "_decision", foreign)
    if phase == "constructor":
        with monkeypatch.context() as patch:
            mutate(patch)
            with support.observe() as counts:
                with pytest.raises(ValueError, match="changed"): open_cpu(checkpoint, scheduler, patch)
            assert counts["restores"] == 0 and scheduler.active_leases() == []
        return
    texts, vectors = support.inputs(checkpoint, 1)
    cancel = support.Mutation(None, texts, vectors, phase="after_forward", action=lambda event: None)
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancel) as owner:
        cancel.owner = owner
        with monkeypatch.context() as patch:
            cancel.action = lambda event: mutate(patch, event.owner)
            with support.observe(owner, cancellation=cancel) as counts:
                with pytest.raises(ValueError, match="changed"): owner.infer(texts, vectors)
            assert cancel.triggered and counts["forward"] == 1 and not owner._active and not owner._observations
        owner.describe()


@pytest.mark.parametrize("name", ["_BASE_METHODS", "_BASE_METHODS_BEFORE_DEDUP", "_BASE_METHOD_KEYS_BEFORE_DEDUP", "_BASE_METHOD_KEYS", "_BASE_METHOD_KEYSET", "_BASE_METHOD_COUNTS", "_BASE_FUNCTIONS", "_BASE_CLASSES"])
def test_inventory_alias_substitution_even_equal_values_refuses_before_restore(checkpoint, scheduler, monkeypatch, name):
    value = getattr(subject, name)
    replacement = frozenset(list(value)) if type(value) is frozenset else tuple(list(value))
    assert replacement == value and replacement is not value
    with monkeypatch.context() as patch:
        patch.setattr(subject, name, replacement)
        with support.observe() as counts:
            with pytest.raises(ValueError, match="inventory identity changed"): open_cpu(checkpoint, scheduler, patch)
        assert counts["restores"] == 0 and scheduler.active_leases() == []


def test_inherited_numerical_poll_anchor_cleanup_signatures_and_guards_are_identical():
    pairs = ((subject.DeduplicatedWholeInputDeviceDimensionalSpanSession, support.subject.WholeInputDeviceDimensionalSpanSession),
             (subject.DeduplicatedWholeInputDeviceLeanstral4096SpanSession, support.subject.WholeInputDeviceLeanstral4096SpanSession))
    for candidate, baseline in pairs:
        assert inspect.signature(candidate) == inspect.signature(baseline)
        for name in ("_poll", "_check", "_decision", "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor",
                     "_admit_batch_memory", "_operation", "_synchronize", "close"):
            assert getattr(candidate, name) is getattr(baseline, name)
    actual = subject.inference_implementation()
    expected = support.subject.inference_implementation()
    for key in expected:
        if key not in ("schema", "source_sha256", "profiles"):
            assert actual[key] == expected[key]
    assert all(actual[key] is False for key in ("performance_qualified", "production_qualified", "proof_authority",
        "execution_attestation", "source_verification_success_cached", "boundary_consolidation_performed"))


def test_source_ast_preserves_every_original_verifier_and_method_body():
    baseline_path = Path(support.subject.__file__)
    assert hashlib.sha256(baseline_path.read_bytes()).hexdigest() == "398611f204ce27194d6a0c5b739ad13d1387feeb626d250995ac97de42d17b20"
    original, candidate = ast.parse(baseline_path.read_text()), ast.parse(Path(subject.__file__).read_text())
    replacements = {"DeduplicatedWholeInputDeviceDimensionalSpanSession": "WholeInputDeviceDimensionalSpanSession",
                    "DeduplicatedWholeInputDeviceLeanstral4096SpanSession": "WholeInputDeviceLeanstral4096SpanSession"}
    class Normalize(ast.NodeTransformer):
        def visit_Name(self, node):
            node.id = replacements.get(node.id, node.id); return node
        def visit_ClassDef(self, node):
            node.name = replacements.get(node.name, node.name); return self.generic_visit(node)
    Normalize().visit(candidate)
    current = {node.name: node for node in candidate.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for old in original.body:
        if not isinstance(old, (ast.FunctionDef, ast.ClassDef)): continue
        new = deepcopy(current[old.name])
        if old.name == "inference_implementation": continue  # explicit new profile/metadata is checked above.
        if old.name == "_check_bindings":
            first = new.body.pop(0)
            assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call) and first.value.func.id == "_check_method_inventory"
        assert ast.dump(new, include_attributes=False) == ast.dump(old, include_attributes=False)


def test_cpu_opt_out_keeps_cuda_optimizer_and_fit_calls_forbidden(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("dedup CPU opt-out performed forbidden work")
    for attribute in ("is_available", "current_device"): monkeypatch.setattr(torch.cuda, attribute, forbidden)
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(support.span, "train_decoder", forbidden)
    monkeypatch.setattr(support.dims, "train_decoder", forbidden)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=False) as owner:
        assert owner.infer(*support.inputs(checkpoint))["training_executed"] is False
