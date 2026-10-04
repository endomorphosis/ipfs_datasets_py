"""Pinned, non-executing cross-repository resolution tests for DSCON-G130."""

from __future__ import annotations

import builtins
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)
from ipfs_datasets_py.logic.software_contracts.resolver import (
    ModuleAlias,
    RepositoryComposition,
    RepositoryPin,
    RepositoryResolution,
    ResolutionValidationError,
    STATUS_DEFINITE,
    STATUS_FINITE_MAY,
    STATUS_MISSING,
    STATUS_OPTIONAL,
    STATUS_REVISION_MISMATCH,
    STATUS_UNRESOLVED,
    SymbolResolver,
)


REVISIONS = {
    "repository:swissknife": "swissknife-r1",
    "repository:hallucinate": "hallucinate-r1",
    "repository:datasets": "datasets-r1",
    "repository:kit": "kit-r1",
}


def ast(
    source: str,
    path: str,
    repository_id: str,
    *,
    revision: str | None = None,
):
    return PythonASTExtractor().extract(
        source,
        path=path,
        repository_id=repository_id,
        revision=revision or REVISIONS[repository_id],
    )


def composition(*, aliases=(), optional_modules=()) -> RepositoryComposition:
    return RepositoryComposition(
        repositories=(
            RepositoryPin(
                "repository:swissknife",
                REVISIONS["repository:swissknife"],
                ("swissknife",),
            ),
            RepositoryPin(
                "repository:hallucinate",
                REVISIONS["repository:hallucinate"],
                ("hallucinate_app",),
            ),
            RepositoryPin(
                "repository:datasets",
                REVISIONS["repository:datasets"],
                ("ipfs_datasets_py",),
            ),
            RepositoryPin(
                "repository:kit",
                REVISIONS["repository:kit"],
                ("ipfs_kit_py",),
            ),
        ),
        aliases=aliases,
        optional_modules=optional_modules,
    )


def edge_by_local(resolver: SymbolResolver, local_name: str):
    return next(
        edge for edge in resolver.resolve_imports() if edge.local_name == local_name
    )


def test_cross_repository_imports_aliases_and_reexports_bind_pinned_revisions() -> None:
    datasets_api = ast(
        """\
__all__ = ["load_dataset"]
def load_dataset(value):
    return value
""",
        "ipfs_datasets_py/api.py",
        "repository:datasets",
    )
    datasets_package = ast(
        """\
from .api import load_dataset
__all__ = ["load_dataset"]
""",
        "ipfs_datasets_py/__init__.py",
        "repository:datasets",
    )
    hallucinate = ast(
        """\
from ipfs_datasets_py import load_dataset as load
__all__ = ["load"]
""",
        "hallucinate_app/runtime.py",
        "repository:hallucinate",
    )
    swissknife = ast(
        """\
from datasets_public import load_dataset as dataset_load
from hallucinate_app.runtime import load as hallucinate_load
""",
        "swissknife/bridge.py",
        "repository:swissknife",
    )
    resolver = SymbolResolver(
        composition(
            aliases=(
                ModuleAlias(
                    "datasets_public",
                    ("ipfs_datasets_py",),
                ),
            )
        ),
        (datasets_api, datasets_package, hallucinate, swissknife),
    )

    dataset_edge = edge_by_local(resolver, "dataset_load")
    hallucinate_edge = edge_by_local(resolver, "hallucinate_load")
    assert dataset_edge.requested_module == "datasets_public"
    assert dataset_edge.resolution.status == STATUS_DEFINITE
    assert dataset_edge.resolution.candidates[0].qualified_name == (
        "ipfs_datasets_py.api.load_dataset"
    )
    assert dataset_edge.resolution.candidates[0].revision == "datasets-r1"
    assert hallucinate_edge.resolution.status == STATUS_DEFINITE
    assert hallucinate_edge.resolution.candidates[0].revision == "datasets-r1"

    package_export = next(
        edge
        for edge in resolver.resolve_exports()
        if edge.source_module == "ipfs_datasets_py"
        and edge.exported_name == "load_dataset"
    )
    assert package_export.via_import_id is not None
    assert package_export.resolution.status == STATUS_DEFINITE
    assert package_export.resolution.candidates[0].module == "ipfs_datasets_py.api"


def test_distinct_definite_finite_may_optional_missing_and_unresolved_results() -> None:
    backend_a = ast(
        "def run():\n    return 'a'\n",
        "ipfs_datasets_py/backend_a.py",
        "repository:datasets",
    )
    backend_b = ast(
        "def run():\n    return 'b'\n",
        "ipfs_datasets_py/backend_b.py",
        "repository:datasets",
    )
    consumer = ast(
        """\
import ipfs_datasets_py.backend_a as exact
import selected_backend as selected
import absent_required as missing
import optional_gpu as gpu
dynamic = __import__(name)
""",
        "swissknife/consumer.py",
        "repository:swissknife",
    )
    resolver = SymbolResolver(
        composition(
            aliases=(
                ModuleAlias(
                    "selected_backend",
                    (
                        "ipfs_datasets_py.backend_a",
                        "ipfs_datasets_py.backend_b",
                    ),
                ),
                ModuleAlias(
                    "optional_gpu",
                    ("ipfs_datasets_py.optional_gpu",),
                    optional=True,
                ),
            ),
            optional_modules=("optional_gpu",),
        ),
        (backend_a, backend_b, consumer),
    )

    assert edge_by_local(resolver, "exact").resolution.status == STATUS_DEFINITE
    selected = edge_by_local(resolver, "selected").resolution
    assert selected.status == STATUS_FINITE_MAY
    assert {item.module for item in selected.candidates} == {
        "ipfs_datasets_py.backend_a",
        "ipfs_datasets_py.backend_b",
    }
    assert edge_by_local(resolver, "missing").resolution.status == STATUS_MISSING
    optional = edge_by_local(resolver, "gpu").resolution
    assert optional.status == STATUS_OPTIONAL
    assert optional.is_optional

    assert resolver.resolve_module(
        "....outside",
        source=consumer,
    ).status == STATUS_UNRESOLVED


def test_incomplete_alias_may_set_is_unknown_not_guessed() -> None:
    backend = ast(
        "value = 1\n",
        "ipfs_datasets_py/backend_a.py",
        "repository:datasets",
    )
    resolver = SymbolResolver(
        composition(
            aliases=(
                ModuleAlias(
                    "selected_backend",
                    (
                        "ipfs_datasets_py.backend_a",
                        "ipfs_datasets_py.not_scanned",
                    ),
                ),
            )
        ),
        (backend,),
    )
    result = resolver.resolve_module("selected_backend")
    assert result.status == STATUS_UNRESOLVED
    assert [item.module for item in result.candidates] == [
        "ipfs_datasets_py.backend_a"
    ]


def test_package_mirror_is_ignored_and_stale_authority_is_revision_mismatch() -> None:
    authoritative = ast(
        "def load():\n    return 'current'\n",
        "ipfs_datasets_py/core.py",
        "repository:datasets",
        revision="old-datasets-revision",
    )
    mirror = ast(
        "def load():\n    return 'mirror'\n",
        "ipfs_datasets_py/core.py",
        "repository:hallucinate",
        revision="hallucinate-r1",
    )
    consumer = ast(
        "from ipfs_datasets_py.core import load\n",
        "swissknife/consumer.py",
        "repository:swissknife",
    )
    resolver = SymbolResolver(
        composition(),
        (authoritative, mirror, consumer),
    )

    result = edge_by_local(resolver, "load").resolution
    assert result.status == STATUS_REVISION_MISMATCH
    assert {item.repository_id for item in result.candidates} == {
        "repository:datasets"
    }
    graph = resolver.resolve()
    assert mirror.cid in graph.ignored_mirror_record_cids
    assert authoritative.cid in graph.stale_record_cids


def test_relative_import_alias_reference_and_submodule_resolution() -> None:
    helper = ast(
        """\
class Client:
    def fetch(self):
        return 1
client = Client()
""",
        "ipfs_datasets_py/pkg/helpers.py",
        "repository:datasets",
    )
    consumer = ast(
        """\
from .helpers import client as api
value = api.fetch()
""",
        "ipfs_datasets_py/pkg/consumer.py",
        "repository:datasets",
    )
    resolver = SymbolResolver(composition(), (helper, consumer))
    imported = edge_by_local(resolver, "api")
    assert imported.requested_module == "ipfs_datasets_py.pkg.helpers"
    assert imported.resolution.status == STATUS_DEFINITE

    api_fetch = next(
        item
        for item in consumer.references
        if item.name == "api.fetch" and item.context == "call"
    )
    # The imported object is a variable and its runtime class is not encoded in
    # lexical AST facts, so the method target remains explicitly missing.
    assert resolver.resolve_reference(consumer, api_fetch).status == STATUS_MISSING


def test_js_family_relative_specifier_resolves_without_a_module_loader() -> None:
    target_base = ast(
        "value = 1\n",
        "swissknife/src/client.py",
        "repository:swissknife",
    )
    source_base = ast(
        "import ipfs_datasets_py as client\n",
        "swissknife/src/app.py",
        "repository:swissknife",
    )
    target = replace(
        target_base,
        provenance=replace(target_base.provenance, path="swissknife/src/client.ts"),
        frontend=replace(
            target_base.frontend,
            language="typescript",
            language_version="5.6.3",
            source_extensions=(".ts",),
        ),
        module=replace(target_base.module, name="swissknife.src.client"),
    )
    source = replace(
        source_base,
        provenance=replace(source_base.provenance, path="swissknife/src/app.ts"),
        frontend=replace(
            source_base.frontend,
            language="typescript",
            language_version="5.6.3",
            source_extensions=(".ts",),
        ),
        module=replace(source_base.module, name="swissknife.src.app"),
        imports=tuple(
            replace(item, module="./client.js") for item in source_base.imports
        ),
    )
    resolver = SymbolResolver(composition(), (source, target))
    edge = edge_by_local(resolver, "client")
    assert edge.requested_module == "swissknife.src.client"
    assert edge.resolution.status == STATUS_DEFINITE
    assert edge.resolution.candidates[0].module == "swissknife.src.client"


def test_explicit_and_structural_protocol_implementations_are_conservative() -> None:
    protocols = ast(
        """\
from typing import Protocol
class Runner(Protocol):
    def run(self, value):
        ...
""",
        "ipfs_datasets_py/protocols.py",
        "repository:datasets",
    )
    implementations = ast(
        """\
from ipfs_datasets_py.protocols import Runner
class ExplicitRunner(Runner):
    def run(self, value):
        return value
class DerivedRunner(ExplicitRunner):
    pass
class StructuralRunner:
    def run(self, value):
        return value
class NotRunner:
    pass
""",
        "ipfs_kit_py/runners.py",
        "repository:kit",
    )
    resolver = SymbolResolver(composition(), (protocols, implementations))
    relations = resolver.resolve_protocols()

    explicit = next(
        item
        for item in relations
        if item.implementation.qualified_name == "ipfs_kit_py.runners.ExplicitRunner"
        and item.protocol.qualified_name == "ipfs_datasets_py.protocols.Runner"
    )
    assert explicit.kind == "explicit"
    assert explicit.certainty == STATUS_DEFINITE
    inherited = next(
        item
        for item in relations
        if item.implementation.qualified_name == "ipfs_kit_py.runners.DerivedRunner"
        and item.protocol.qualified_name == "ipfs_datasets_py.protocols.Runner"
    )
    assert inherited.kind == "inherited"
    assert inherited.certainty == STATUS_DEFINITE
    structural = next(
        item
        for item in relations
        if item.implementation.qualified_name
        == "ipfs_kit_py.runners.StructuralRunner"
        and item.protocol.qualified_name == "ipfs_datasets_py.protocols.Runner"
    )
    assert structural.kind == "structural"
    assert structural.certainty == STATUS_FINITE_MAY
    assert structural.required_members == ("run",)
    assert not [
        item
        for item in relations
        if item.implementation.qualified_name == "ipfs_kit_py.runners.NotRunner"
    ]


def test_resolution_is_deterministic_closed_and_never_imports_target_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ast(
        "value = 1\n",
        "ipfs_datasets_py/target.py",
        "repository:datasets",
    )
    consumer = ast(
        "from ipfs_datasets_py.target import value\n",
        "swissknife/consumer.py",
        "repository:swissknife",
    )
    resolver = SymbolResolver(composition(), (consumer, target))

    imported_names: list[str] = []
    real_import = builtins.__import__

    def observed_import(name, *args, **kwargs):
        imported_names.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", observed_import)
    first = resolver.resolve()
    second = resolver.resolve()
    assert isinstance(first, RepositoryResolution)
    assert first.canonical_bytes == second.canonical_bytes
    assert first.cid == second.cid
    assert "ipfs_datasets_py.target" not in imported_names
    assert RepositoryResolution.from_dict(first.to_dict()) == first


def test_composition_rejects_duplicate_owners_and_round_trips() -> None:
    with pytest.raises(ResolutionValidationError, match="exactly one"):
        RepositoryComposition(
            repositories=(
                RepositoryPin("repository:a", "rev-a", ("shared",)),
                RepositoryPin("repository:b", "rev-b", ("shared",)),
            )
        )

    original = composition(
        aliases=(ModuleAlias("public", ("ipfs_datasets_py",)),),
        optional_modules=("optional_gpu",),
    )
    restored = RepositoryComposition.from_dict(original.to_dict())
    assert restored == original
    assert restored.cid == original.cid
