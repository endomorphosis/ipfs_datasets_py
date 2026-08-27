"""Behavior and structural reuse guards for legal query edge authority."""

from __future__ import annotations

import inspect
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_data import (
    federal_register_sparse_query as federal,
)
from ipfs_datasets_py.processors.legal_data import legal_query_authority_core as core
from ipfs_datasets_py.processors.legal_data import open_us_law_query as open_us_law
from ipfs_datasets_py.processors.legal_data import state_laws_query as state_laws
from ipfs_datasets_py.processors.legal_data import uscode_query as uscode

ADAPTERS = (state_laws, open_us_law, uscode, federal)
SHARED_WRAPPERS = (
    "annotate_edge_authority",
    "assert_no_similarity_as_legal_authority",
    "classify_edge_authority",
    "edge_class_for_type",
    "is_legal_edge_type",
    "is_similarity_edge_type",
    "similarity_edge_semantics",
)


def _similarity_type(module: ModuleType) -> str:
    return min(module.SIMILARITY_EDGE_TYPE_NAMES)


@pytest.mark.parametrize("module", ADAPTERS, ids=lambda item: item.__name__)
def test_public_adapters_preserve_dataset_errors_and_enum_bindings(
    module: ModuleType,
) -> None:
    bindings = module._EDGE_AUTHORITY_BINDINGS
    assert isinstance(bindings, core.LegalQueryAuthorityBindings)
    assert bindings.edge_type is module.GraphEdgeType
    assert bindings.edge_class is module.GraphEdgeClass
    assert bindings.input_error is module.__dict__[f"{_input_error_prefix(module)}InputError"]
    assert bindings.collision_error is module.LegalAuthorityCollisionError

    with pytest.raises(bindings.input_error, match="edge must be a mapping"):
        module.annotate_edge_authority([])
    with pytest.raises(
        module.LegalAuthorityCollisionError,
        match="cannot claim legal/proof authority",
    ):
        module.annotate_edge_authority(
            {
                "edge_type": _similarity_type(module),
                "legal_authority": True,
            }
        )


def _input_error_prefix(module: ModuleType) -> str:
    return {
        federal: "FederalRegisterQuery",
        open_us_law: "OpenUsLawQuery",
        state_laws: "StateLawsQuery",
        uscode: "UscodeQuery",
    }[module]


@pytest.mark.parametrize("module", ADAPTERS, ids=lambda item: item.__name__)
def test_similarity_packages_remain_byte_shape_compatible(module: ModuleType) -> None:
    edge_type = _similarity_type(module)
    classified = module.classify_edge_authority(edge_type)
    assert classified == {
        "authority": module.AUTHORITY_NON_AUTHORITATIVE,
        "edge_class": module.GraphEdgeClass.SIMILARITY.value,
        "edge_type": edge_type,
        "legal_authority": False,
        "proof_authority": bool(
            module._EDGE_AUTHORITY_BINDINGS.similarity_proof_authority
        ),
        "retrieval_hint": True,
    }
    assert module.annotate_edge_authority(
        {"edge_type": edge_type, "payload": {"preserved": True}}
    ) == {
        **classified,
        "payload": {"preserved": True},
    }


def test_dataset_specific_similarity_semantics_are_preserved() -> None:
    state_semantics = state_laws.similarity_edge_semantics()
    federal_semantics = federal.similarity_edge_semantics()
    open_semantics = open_us_law.similarity_edge_semantics()
    uscode_semantics = uscode.similarity_edge_semantics()

    assert state_semantics == federal_semantics
    assert state_semantics["notes"] == (
        core.SIMILARITY_NOTES_BM25_EMBEDDING_CORRECTION
    )
    assert state_semantics["overlay_edge_type"] == (
        state_laws.EDGE_TYPE_BM25_NEIGHBOR
    )
    assert "overlay_edge_type" not in open_semantics
    assert "overlay_edge_type" not in uscode_semantics
    assert open_semantics["notes"] == (
        core.SIMILARITY_NOTES_BM25_EMBEDDING_AMENDMENT
    )
    assert uscode_semantics["notes"] == core.SIMILARITY_NOTES_BM25_AMENDMENT


@pytest.mark.parametrize("module", ADAPTERS, ids=lambda item: item.__name__)
def test_public_wrappers_cannot_reintroduce_authority_algorithms(
    module: ModuleType,
) -> None:
    for name in SHARED_WRAPPERS:
        source = inspect.getsource(getattr(module, name))
        assert "_authority_core." in source
        assert "for edge in edges" not in source
        assert "claimed_authority" not in source
        assert "GraphEdgeType.coerce" not in source
