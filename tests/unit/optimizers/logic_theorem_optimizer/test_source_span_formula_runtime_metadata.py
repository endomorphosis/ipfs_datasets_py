"""Explicit source-span metadata discovery without numerical execution.

This companion covers the descriptor used by retained-target eligibility.
It does not qualify list/open/factory/inference integration or a checkpoint.
"""
import ast
import builtins
import hashlib
import inspect
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as registry

VERSION = "source_span_formula_v1"


def test_explicit_span_descriptor_binds_actual_declared_files():
    description = registry.describe_runtime("legal_ir", VERSION)
    assert registry.SPAN_FORMULA_VERSION == VERSION
    assert description["runtime_id"] == "legal_ir:" + VERSION
    assert description["lineage_id"] == VERSION
    assert description["dimension"] is None
    assert description["supported_latent_dimensions"] == [0, 384]
    assert description["latent_ablation_modes"] == ["none", "zero", "rotate", "disabled"]
    assert description["state_schema"] == "span-legal-formula-checkpoint/v1"
    assert description["output_schema"] == "span-legal-formula-inference/v1"
    assert description["capabilities"] == ["load_checkpoint", "infer", "decode_formal_logic"]
    assert description["formal_decoder"]["scope"] == "single_canonical_deontic_rule_with_one_copied_span_per_facet"
    assert description["all_family_requirements_satisfied"] is False
    assert description["source_semantics_verified"] is description["proof_ready"] is False
    assert all(description[key] is False for key in registry.features.FALSE)
    identity = description["source_identity"]
    assert identity["scope"] == "listed_runtime_files_only_not_transitive_dependency_provenance"
    root = Path(registry.__file__).resolve().parent
    names = ["autoencoder_runtime_registry.py", "autoencoder_logic_requirements.py",
             "legal_span_formula.py", "legal_formula_codec.py"]
    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    assert identity["files"] == expected
    assert identity["sha256"] == registry.features.digest(expected)


@pytest.mark.parametrize("domain,version", [
    ("intent_ir", VERSION), ("security_ir", VERSION), ("ui_ux_ir", VERSION),
    ("codebase_ir", VERSION), ("legal_ir", "source_span_formula_v2"),
    ("legal_ir", "warm_start_source_span_formula_v1"), ("legal_ir", "384"),
])
def test_unknown_or_cross_domain_descriptor_is_refused(domain, version):
    with pytest.raises(registry.RuntimeVersionError, match="unknown"):
        registry.describe_runtime(domain, version)


def test_description_never_imports_or_dispatches_a_numerical_owner(monkeypatch):
    original_import = builtins.__import__
    forbidden_imports = []
    forbidden_names = ("torch", "tensorflow", "transformers")

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        targets = [name, *(fromlist or ())]
        if any(target == "legal_span_formula" or target.endswith(".legal_span_formula") or any(
                target == prefix or target.startswith(prefix + ".") for prefix in forbidden_names)
                for target in targets):
            forbidden_imports.append(name)
            raise AssertionError("metadata description attempted numerical-owner import")
        return original_import(name, globals, locals, fromlist, level)

    def forbidden_dispatch(*args, **kwargs):
        raise AssertionError("metadata description attempted runtime dispatch")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", guarded_import)
        patch.setattr(registry, "open_runtime", forbidden_dispatch)
        patch.setattr(registry, "open_formal_decoder", forbidden_dispatch)
        description = registry.describe_runtime("legal_ir", VERSION)
    assert description["runtime_version"] == VERSION
    assert forbidden_imports == []


def test_neighbor_profiles_preserve_their_distinct_metadata():
    learned = registry.describe_runtime("legal_ir", registry.LEARNED_FORMULA_VERSION)
    grouped = registry.describe_runtime("legal_ir", registry.GROUPED_FORMULA_VERSION)
    assert learned["state_schema"] == "learned-legal-formula-checkpoint/v1"
    assert grouped["state_schema"] == "legal-grouped-span-decoder-checkpoint/v2"
    assert grouped["numeric_vector_conditioning"] is False
    assert learned["runtime_version"] != grouped["runtime_version"] != VERSION


@pytest.mark.parametrize("factory_name", ["open_runtime", "open_formal_decoder"])
def test_span_catalog_and_factory_route_exist_before_checkpoint_restore(factory_name):
    # The catalog symbol is a static declaration; full catalog execution and a
    # successful runtime construction remain outside this metadata cohort.
    tree = ast.parse(Path(registry.__file__).read_bytes())
    catalog = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "list_runtimes")
    assert any(isinstance(node, ast.Name) and node.id == "SPAN_FORMULA_VERSION"
               for node in ast.walk(catalog))
    assert "SPAN_FORMULA_VERSION" in registry.__all__
    assert "SourceSpanFormulaRuntime" in registry.__all__
    assert callable(registry.SourceSpanFormulaRuntime)
    signature = inspect.signature(registry.SourceSpanFormulaRuntime)
    assert list(signature.parameters) == ["checkpoint_path", "checkpoint_sha256"]
    assert all(parameter.kind == inspect.Parameter.KEYWORD_ONLY
               for parameter in signature.parameters.values())
    factory = getattr(registry, factory_name)
    # The actual route reaches its existing argument guard before importing
    # the span owner or attempting any checkpoint read/model construction.
    with pytest.raises(registry.RuntimeVersionError, match="local path"):
        factory("legal_ir", VERSION, checkpoint_path=None, checkpoint_sha256="0" * 64)
