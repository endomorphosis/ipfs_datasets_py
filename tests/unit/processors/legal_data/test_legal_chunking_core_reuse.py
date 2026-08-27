"""Architecture guard for shared legal-chunk mechanics.

The U.S.-Code and state-law engines intentionally retain separate hierarchy,
identity, schema, and fixture policy.  Their corpus-neutral text mechanics
must remain bound to :mod:`legal_chunking_core` so a state release does not
silently grow a second tokenizer/windowing/content-address implementation.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_data import (
    legal_chunking_core,
    state_laws_chunker,
    uscode_chunker,
)

CHUNKER_MODULES = (uscode_chunker, state_laws_chunker)

# These functions need no corpus policy at all, so both public modules bind
# the exact same callable rather than defining wrappers or copied bodies.
DIRECT_SHARED_MECHANICS = {
    "canonical_json_bytes": legal_chunking_core.canonical_json_bytes,
    "chunk_cid_for_payload": legal_chunking_core.chunk_cid_for_payload,
    "content_sha256": legal_chunking_core.content_sha256,
    "reconstruct_text": legal_chunking_core.reconstruct_text,
    "token_index_covering_char": legal_chunking_core.token_index_covering_char,
    "_pack_pieces": legal_chunking_core.pack_pieces,
    "_piece_token_count": legal_chunking_core.token_count_in_span,
    "_sentence_spans": legal_chunking_core.sentence_spans,
}

# These mechanics need a local dataclass factory or exception class.  The
# corpus module retains only a thin adapter and binds the implementation under
# the listed local name.
DELEGATED_SHARED_MECHANICS = {
    "_assert_chunks_within_limit": legal_chunking_core.assert_chunks_within_limit,
    "_assert_exact_reconstruction": legal_chunking_core.assert_exact_reconstruction,
    "_normalize_chunk_text": legal_chunking_core.normalize_chunk_text,
    "_validate_model_token_limit": legal_chunking_core.validate_model_token_limit,
    "build_chunk_cid_seed": legal_chunking_core.build_chunk_cid_seed,
    "hard_token_windows": legal_chunking_core.hard_token_windows,
    "repair_coverage": legal_chunking_core.repair_coverage,
    "whitespace_token_rows": legal_chunking_core.whitespace_token_rows,
}

# This is the intentional, corpus-specific seam.  Pulling it into the core
# would mix state code/title/chapter/part/article paths and state identities
# with U.S.-Code title/section paths and identities.
STATE_POLICY_SEAM = {
    "assert_legal_boundaries_preserved",
    "chunk_corpus_row",
    "expand_per_jurisdiction_cases",
    "find_hierarchy_headings",
    "find_parenthetical_markers",
    "identity_cursor",
    "resolve_legal_identity",
}

SEALED_FIXTURE_RESULT_DIGESTS = {
    uscode_chunker: "fc01b5ef11933371648d295649bb53938271d73da0f258c8ee6a3fd65075080e",
    state_laws_chunker: "da08938c4ab9c9dc4586a815259dc15c4d4ec2c69adbaaa41c2e33abf4548ff4",
}


def _top_level_definitions(module: ModuleType) -> set[str]:
    source = inspect.getsource(module)
    tree = ast.parse(source, filename=str(module.__file__))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.parametrize("module", CHUNKER_MODULES)
def test_corpus_chunkers_bind_one_shared_mechanics_implementation(
    module: ModuleType,
) -> None:
    definitions = _top_level_definitions(module)
    for local_name, implementation in DIRECT_SHARED_MECHANICS.items():
        assert getattr(module, local_name) is implementation
        assert local_name not in definitions
    for local_name, implementation in DELEGATED_SHARED_MECHANICS.items():
        assert getattr(module, local_name) is implementation


def test_shared_core_stops_before_hierarchy_and_identity_policy() -> None:
    core_definitions = _top_level_definitions(legal_chunking_core)
    state_definitions = _top_level_definitions(state_laws_chunker)
    uscode_definitions = _top_level_definitions(uscode_chunker)

    assert STATE_POLICY_SEAM <= state_definitions
    assert STATE_POLICY_SEAM.isdisjoint(core_definitions)
    assert STATE_POLICY_SEAM.isdisjoint(uscode_definitions)

    # Structural recursion remains local because the state implementation
    # resets parenthetical nesting at explicit hierarchy headings, while the
    # U.S.-Code implementation has only title/section + parentheses.
    state_subdivide = inspect.getsource(state_laws_chunker._subdivide_unit)
    uscode_subdivide = inspect.getsource(uscode_chunker._subdivide_unit)
    assert "_HIERARCHY_KIND_TO_KEY" in state_subdivide
    assert "_HIERARCHY_KIND_TO_KEY" not in uscode_subdivide
    assert "resolve_legal_identity(" in inspect.getsource(
        state_laws_chunker.StateLawsChunker.chunk_statute
    )
    assert "LegalIdentity(" in inspect.getsource(
        uscode_chunker.UscodeChunker.chunk_section
    )


def test_module_local_value_types_remain_compatible_public_surfaces() -> None:
    """Keep public type/pickle paths local while sharing their mechanics."""

    assert tuple(mode.value for mode in state_laws_chunker.SplitMode) == tuple(
        mode.value for mode in uscode_chunker.SplitMode
    )
    assert tuple(state_laws_chunker.TokenSpan.__dataclass_fields__) == tuple(
        uscode_chunker.TokenSpan.__dataclass_fields__
    )
    assert tuple(state_laws_chunker.StructuralUnit.__dataclass_fields__) == tuple(
        uscode_chunker.StructuralUnit.__dataclass_fields__
    )
    assert state_laws_chunker.TokenSpan is not uscode_chunker.TokenSpan
    assert state_laws_chunker.StructuralUnit is not uscode_chunker.StructuralUnit


@pytest.mark.parametrize(
    ("module", "error_type"),
    (
        (uscode_chunker, uscode_chunker.UscodeChunkerError),
        (state_laws_chunker, state_laws_chunker.StateLawsChunkerError),
    ),
)
def test_shared_normalization_preserves_corpus_error_contract(
    module: ModuleType,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type, match="text must be a string"):
        module.normalize_chunk_text(None)  # type: ignore[arg-type]
    with pytest.raises(error_type, match="text must be a string"):
        module.tokenize(None)  # type: ignore[arg-type]
    with pytest.raises(error_type, match="text must not contain NUL"):
        module.normalize_chunk_text("valid prefix\x00invalid suffix")


@pytest.mark.parametrize(
    ("module", "expected_digest"),
    tuple(SEALED_FIXTURE_RESULT_DIGESTS.items()),
)
def test_shared_extraction_preserves_full_sealed_fixture_results(
    module: ModuleType,
    expected_digest: str,
) -> None:
    fixture = module.load_chunk_boundary_fixture_payload()
    results = [module.run_fixture_case(case).to_dict() for case in fixture["cases"]]
    encoded = json.dumps(
        results,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == expected_digest
