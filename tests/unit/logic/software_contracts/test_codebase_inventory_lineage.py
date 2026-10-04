"""Pure lineage compatibility/cache controls, not native qualification.

Private cache helpers use inert isolated stubs.  These tests do not open a
DuckDB owner, acquire a resource lease, fit weights, or launch a subprocess.
Native target replay, ancestry and final source fences have a separate finite
qualification fixture.
"""
import ast
from copy import deepcopy
import inspect
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import (
    DomainTargetEnvelope, build_target_envelope,
)
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_lineage as lineage
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training


def isolated_context(*, maximum=1024 * 1024):
    """Test only private cache mechanics; deliberately bypass native owners."""
    context = object.__new__(lineage.InventoryLineageContext)
    context.index, context.registry = object(), object()
    context.limits = training.CodebaseFeatureTrainingLimits()
    context.current_seal = None
    context.checkpoint = lambda: None
    context.max_cache_bytes = maximum
    context.counters = lineage.InventoryLineageCounters()
    context._candidates = {}
    context._targets = {}
    context._bindings = {}
    context._prepared = {}
    context._historical_seal = None
    return context


def inert_target(*, value=1):
    """Valid envelope shape with a stub declaration, never a native proof."""
    return build_target_envelope(domain_id="codebase_ir", source_digest="a" * 64,
        projections=[{"projection_id": "fixture-projection", "view_id": "fixture-view",
            "representation_kind": "fixture-structural", "producer_id": "isolated-test",
            "view_role": "fixture", "expression": {"constant": value}}],
        validation=[{"validator_id": "isolated-cache-stub", "status": "passed",
            "details": {"source_binding": {"head": {"repository_id": "fixture-repository"},
                "path": "fixture.py", "content_sha256": "b" * 64}, "authored_contracts": []}}])


def counting_adapter(monkeypatch, *, changed=False, refuse=False):
    calls = []
    def validate(target):
        calls.append(target.canonical_bytes)
        if refuse:
            raise training.CodebaseFeatureTrainingError("stub native replay refused")
        value = target.to_dict()
        if changed:
            value["projections"][0]["expression"]["constant"] = 999
        return DomainTargetEnvelope.from_dict(value)
    adapter = SimpleNamespace(validate_codebase_targets=validate)
    monkeypatch.setattr(training, "_targets_adapter", lambda: adapter)
    return calls


class NormalizeLineageHelpers(ast.NodeTransformer):
    """Undo only the reviewed explicit helper substitutions for AST parity."""

    def visit_Attribute(self, node):
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "training":
            return ast.Name(node.attr, ast.Load())
        if isinstance(node.value, ast.Name) and node.value.id == "context" and node.attr == "_pins":
            return ast.Call(ast.Name("_pins", ast.Load()), [], [])
        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if not (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "context"):
            return node
        name = node.func.attr
        helpers = {"batch": "_batch", "split_check": "_split_check",
                   "identity": "_identity", "binding": "_binding"}
        if name in helpers:
            node.func = ast.Name(helpers[name], ast.Load())
        elif name == "read_candidate":
            node.func = ast.Name("_read_candidate", ast.Load())
            node.args = [ast.Name("registry", ast.Load()), *node.args, ast.Name("limits", ast.Load())]
        elif name == "validate_runtime_candidate":
            node.func = ast.Attribute(ast.Name("runtimes", ast.Load()), "load_version", ast.Load())
            node.args = [ast.Name("registry", ast.Load()), ast.Name("current", ast.Load())]
            node.keywords = [ast.keyword("domain", ast.Constant("codebase_ir")),
                ast.keyword("version", ast.Attribute(ast.Name("runtimes", ast.Load()),
                                                     "CODEBASE_SOURCE_FEATURE_VERSION", ast.Load()))]
        elif name == "prepare":
            node.func = ast.Attribute(ast.Call(ast.Name("_targets_adapter", ast.Load()), [], []),
                                      "prepare_codebase_targets", ast.Load())
            node.args = [ast.Name("index", ast.Load())]
            node.keywords = [ast.keyword("expected_head", ast.Name("head", ast.Load())),
                ast.keyword("path", ast.Attribute(ast.Name("selection", ast.Load()), "path", ast.Load())),
                ast.keyword("contracts", ast.Attribute(ast.Name("selection", ast.Load()), "contracts", ast.Load()))]
        return node

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "context" and node.value.func.attr == "checkpoint"):
            return None
        return self.generic_visit(node)


def test_every_inherited_lineage_condition_and_body_matches_native_reference():
    reference = ast.parse(inspect.getsource(training._lineage)).body[0]
    optimized = ast.parse(inspect.getsource(lineage._lineage)).body[0]
    assert optimized.args.args[-1].arg == "context"
    optimized.args.args = optimized.args.args[:-1]
    reference = NormalizeLineageHelpers().visit(reference)
    optimized = NormalizeLineageHelpers().visit(optimized)
    assert ast.dump(optimized, include_attributes=False) == ast.dump(reference, include_attributes=False)
    conditions = [node for node in ast.walk(reference) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "_require"]
    assert len(conditions) == 17


def test_installed_reviewed_producer_guards_pass():
    counters = lineage.InventoryLineageCounters()
    lineage._reference_guard(counters)
    assert counters.reference_guard_file_hashes == 2


@pytest.mark.parametrize("producer", [training.__name__, lineage.runtimes.__name__])
def test_unreviewed_producer_guard_refuses_without_touching_source(monkeypatch, producer):
    monkeypatch.setitem(lineage.REFERENCE_SHA256, producer, "0" * 64)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="reviewed native reference"):
        lineage._reference_guard(lineage.InventoryLineageCounters())


def test_retention_overflow_refuses_before_mutating_accounting():
    context = isolated_context(maximum=9)
    context._retain(9)
    before = context.counters.to_dict()
    with pytest.raises(training.CodebaseFeatureTrainingError, match="serialized byte bound"):
        context._retain(1)
    assert context.counters.to_dict() == before


@pytest.mark.parametrize("size", [-1, True, 1.0, "1"])
def test_retention_requires_nonnegative_exact_integer(size):
    context = isolated_context()
    with pytest.raises(training.CodebaseFeatureTrainingError, match="retained cache byte"):
        context._retain(size)
    assert context.counters.cache_retained_bytes == 0


def test_identical_canonical_bytes_reuse_one_validation_and_bindings_are_detached(monkeypatch):
    calls = counting_adapter(monkeypatch)
    context = isolated_context()
    target = inert_target()
    checked = context.validated(target)
    equal_distinct_object = DomainTargetEnvelope.from_dict(deepcopy(target.to_dict()))
    assert equal_distinct_object is not target
    assert context.validated(equal_distinct_object) is checked
    binding = context.binding(equal_distinct_object)
    binding["head"]["repository_id"] = "changed-by-caller"
    binding["authored_contracts"].append({"injected": True})
    assert context.binding(target)["head"]["repository_id"] == "fixture-repository"
    assert context.binding(target)["authored_contracts"] == []
    assert calls == [target.canonical_bytes]
    assert context.counters.target_native_validations == 1
    assert context.counters.binding_cache_reads == 3


def test_equal_source_digest_with_different_complete_bytes_replays_each_target(monkeypatch):
    calls = counting_adapter(monkeypatch)
    context = isolated_context()
    first, second = inert_target(value=1), inert_target(value=2)
    assert first.source_digest == second.source_digest
    assert first.canonical_bytes != second.canonical_bytes
    context.validated(first)
    context.validated(second)
    assert calls == [first.canonical_bytes, second.canonical_bytes]
    assert context.counters.target_native_validations == 2
    assert context.counters.target_validation_cache_hits == 0


@pytest.mark.parametrize("failure", ["changed_replay", "native_refusal", "cache_overflow"])
def test_failed_target_replay_or_retention_never_populates_cache(monkeypatch, failure):
    calls = counting_adapter(monkeypatch, changed=failure == "changed_replay",
                             refuse=failure == "native_refusal")
    context = isolated_context(maximum=1 if failure == "cache_overflow" else 1024 * 1024)
    with pytest.raises(training.CodebaseFeatureTrainingError):
        context.validated(inert_target())
    assert len(calls) == 1
    assert context._targets == context._bindings == {}
    assert context.counters.cache_retained_bytes == 0


def test_cancelled_cache_lookup_does_not_invoke_validator(monkeypatch):
    calls = counting_adapter(monkeypatch)
    context = isolated_context()
    def cancelled():
        raise RuntimeError("isolated operation cancelled")
    context.checkpoint = cancelled
    with pytest.raises(RuntimeError, match="operation cancelled"):
        context.validated(inert_target())
    assert calls == []
    assert context._targets == context._bindings == {}


def stub_candidate_reader(monkeypatch):
    calls = []
    def read(registry, version_id, limits):
        calls.append(version_id)
        return {"version_id": version_id, "metadata": {"fixture": True}}, {"state": {"weights": [1, 2]}}
    monkeypatch.setattr(training, "_read_candidate", read)
    return calls


def test_candidate_reuse_retains_exact_wire_snapshot_and_one_native_read(monkeypatch):
    calls = stub_candidate_reader(monkeypatch)
    context = isolated_context()
    row, saved = context.read_candidate("fixture-version")
    again_row, again_saved = context.read_candidate("fixture-version")
    assert again_row is row and again_saved is saved
    assert calls == ["fixture-version"]
    assert context.counters.candidate_native_reads == context.counters.candidate_cache_hits == 1


@pytest.mark.parametrize("part", ["row", "saved"])
def test_mutated_cached_candidate_wire_refuses_reuse(monkeypatch, part):
    calls = stub_candidate_reader(monkeypatch)
    context = isolated_context()
    row, saved = context.read_candidate("fixture-version")
    if part == "row":
        row["metadata"]["fixture"] = False
    else:
        saved["state"]["weights"].append(3)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="snapshot was mutated"):
        context.read_candidate("fixture-version")
    assert calls == ["fixture-version"]


def test_candidate_cache_overflow_does_not_publish_a_snapshot(monkeypatch):
    calls = stub_candidate_reader(monkeypatch)
    context = isolated_context(maximum=1)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="serialized byte bound"):
        context.read_candidate("fixture-version")
    assert calls == ["fixture-version"]
    assert context._candidates == {}
    assert context.counters.cache_retained_bytes == 0


def fake_seal(head, size):
    return SimpleNamespace(head=head, counters=SimpleNamespace(manifest_bytes=size,
        publication_receipt_bytes=0, source_bytes=0, ast_bytes=0))


def test_historical_release_preserves_borrowed_current_seal():
    context = isolated_context()
    borrowed = fake_seal("current", 3)
    context.current_seal = borrowed
    context._historical_seal = fake_seal("past", 9)
    context.counters.historical_seal_retained_bytes = 9
    context.release_historical_seals()
    assert context.current_seal is borrowed
    assert context.seal("current") is borrowed
    assert context._historical_seal is None
    assert context.counters.historical_seal_retained_bytes == 0


def test_next_historical_inventory_releases_previous_before_read(monkeypatch):
    context = isolated_context()
    reads = []
    def seal(index, *, expected_head, checkpoint):
        assert context._historical_seal is None
        assert context.counters.historical_seal_retained_bytes == 0
        reads.append(expected_head)
        return fake_seal(expected_head, 7)
    monkeypatch.setattr(lineage, "seal_inventory", seal)
    first = context.seal("past-one")
    assert context.seal("past-one") is first
    assert context.seal("past-two").head == "past-two"
    assert reads == ["past-one", "past-two"]
    assert context.counters.historical_seal_reads == 2
    assert context.counters.historical_seal_reuses == 1
    assert context.counters.historical_seal_retained_bytes_high_water == 7


def test_oversized_historical_inventory_is_not_retained(monkeypatch):
    context = isolated_context()
    monkeypatch.setattr(lineage, "seal_inventory", lambda *args, **kwargs:
        fake_seal("past", lineage.MAX_HISTORICAL_SEAL_BYTES + 1))
    with pytest.raises(training.CodebaseFeatureTrainingError, match="historical inventory"):
        context.seal("past")
    assert context._historical_seal is None
    assert context.counters.historical_seal_retained_bytes == 0


def test_reviewed_8d_migration_refuses_runtime_file_drift(monkeypatch, tmp_path):
    changed = tmp_path / "runtime.py"
    changed.write_text("# unreviewed runtime replacement\n")
    monkeypatch.setattr(training.runtimes, "__file__", str(changed))
    with pytest.raises(training.CodebaseFeatureTrainingError, match="reviewed native reference runtime"):
        lineage._reference_guard(lineage.InventoryLineageCounters())


def test_reviewed_8d_migration_refuses_runtime_module_substitution(monkeypatch):
    monkeypatch.setattr(training.runtimes, "__name__", "foreign.runtime")
    with pytest.raises(training.CodebaseFeatureTrainingError, match="reviewed native reference runtime"):
        lineage._reference_guard(lineage.InventoryLineageCounters())
