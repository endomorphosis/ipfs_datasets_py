"""Architecture guards for shared state-law release validation."""

from __future__ import annotations

import ast
import inspect
import textwrap

from ipfs_datasets_py.processors.legal_data import federal_register_release_schema as federal
from ipfs_datasets_py.processors.legal_data import legal_release_validation
from ipfs_datasets_py.processors.legal_data import open_us_law_schema
from ipfs_datasets_py.processors.legal_data import state_laws_release_schema as state
from ipfs_datasets_py.retrieval.hf_graphrag import schema as artifact_schema


def test_state_identity_and_revision_validation_bind_existing_legal_schema() -> None:
    assert state._shared_validate_entry_cid is open_us_law_schema.validate_entry_cid
    assert (
        state._shared_reject_positional_identity
        is open_us_law_schema.reject_positional_durable_identity
    )
    assert (
        state._shared_is_immutable_revision
        is open_us_law_schema.is_immutable_revision
    )
    assert (
        state._shared_require_immutable_revision
        is open_us_law_schema.require_immutable_revision
    )


def test_state_artifact_path_validation_binds_shared_graphrag_schema() -> None:
    assert (
        state._shared_normalize_artifact_path
        is artifact_schema.normalize_relative_artifact_path
    )


def test_state_wrappers_preserve_dataset_specific_error_types() -> None:
    try:
        state.validate_entry_cid("row-12")
    except state.PositionalIdentityError:
        pass
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("positional identity must fail closed")

    try:
        state.normalize_relative_artifact_path("../escape.parquet")
    except state.ArtifactPathError:
        pass
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("artifact traversal must fail closed")


def test_state_and_prior_legal_schema_bind_shared_physical_primitives() -> None:
    for schema in (state, federal):
        assert schema._shared_normalize_sha256 is artifact_schema.normalize_sha256
        assert schema._shared_validate_digest is artifact_schema.validate_digest
        assert (
            schema._shared_validate_physical_row_count
            is artifact_schema.validate_physical_row_count
        )
        assert (
            schema._shared_validate_physical_pointer_count
            is artifact_schema.validate_physical_pointer_count
        )
        assert (
            schema._shared_validate_centroid_capacity
            is artifact_schema.validate_centroid_capacity
        )

    assert state.MAX_ROWS_PER_PHYSICAL_SHARD == artifact_schema.MAX_ROWS_PER_PHYSICAL_SHARD
    assert state.MAX_POSTING_POINTERS_PER_ROW == artifact_schema.MAX_POINTERS_PER_ROW
    assert state.MAX_ROWS_PER_VECTOR_CENTROID == artifact_schema.MAX_ROWS_PER_VECTOR_CENTROID
    assert state.MAX_VECTOR_SHARDS_PER_CENTROID == artifact_schema.MAX_VECTOR_SHARDS_PER_CENTROID


def test_state_and_federal_adapters_bind_record_agnostic_legal_policy() -> None:
    for schema in (state, federal):
        assert (
            schema._shared_validate_bound_declaration
            is legal_release_validation.validate_bound_declaration
        )
        assert (
            schema._shared_coerce_family_set
            is legal_release_validation.coerce_family_set
        )
        assert (
            schema._shared_validate_semantic_family_closure
            is legal_release_validation.validate_semantic_family_closure
        )
        assert (
            schema._shared_require_source_rights_binding
            is legal_release_validation.require_source_rights_binding
        )
        assert (
            schema._shared_physical_bounds_policy
            is legal_release_validation.physical_bounds_policy
        )

    assert state.BoundKind is federal.BoundKind is legal_release_validation.BoundKind
    assert (
        state.PHYSICAL_BOUND_FIELD_NAMES
        is federal.PHYSICAL_BOUND_FIELD_NAMES
        is legal_release_validation.PHYSICAL_BOUND_FIELD_NAMES
    )
    assert (
        state.AMBIGUOUS_4096_FIELD_NAMES
        is federal.AMBIGUOUS_4096_FIELD_NAMES
        is legal_release_validation.AMBIGUOUS_4096_FIELD_NAMES
    )


def test_state_high_level_wrappers_cannot_recopy_shared_policy_algorithms() -> None:
    wrappers = {
        state.validate_bound_declaration: "_shared_validate_bound_declaration",
        state.validate_semantic_family_closure: (
            "_shared_validate_semantic_family_closure"
        ),
        state.require_source_rights_binding: "_shared_require_source_rights_binding",
        state.physical_bounds_policy: "_shared_physical_bounds_policy",
    }
    for wrapper, shared_name in wrappers.items():
        source = textwrap.dedent(inspect.getsource(wrapper))
        tree = ast.parse(source)
        delegated_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert shared_name in delegated_calls
        assert not any(
            isinstance(node, (ast.If, ast.For, ast.While))
            for node in ast.walk(tree)
        )


def test_shared_release_validators_preserve_state_errors_and_sealed_results() -> None:
    digest = "a" * 64
    assert state.normalize_sha256(f"sha256:{digest}") == digest
    assert state.validate_digest(f"sha256:{digest}") == f"sha256:{digest}"
    assert state.validate_physical_row_count(4096) == 4096
    assert state.validate_physical_pointer_count(4096) == 4096
    assert state.validate_centroid_capacity(row_count=8192, shard_count=2) == (8192, 2)
    assert state.physical_bounds_policy() == federal.physical_bounds_policy()

    failures = (
        (lambda: state.validate_digest("not-a-digest"), state.InvalidDigestError),
        (lambda: state.validate_physical_row_count(4097), state.PhysicalBoundError),
        (
            lambda: state.validate_bound_declaration(
                field_name="chunk_size",
                value=4096,
            ),
            state.AmbiguousBoundError,
        ),
        (
            lambda: state.validate_semantic_family_closure(
                {state.ArtifactFamily.CORPUS}
            ),
            state.SemanticFamilyClosureError,
        ),
        (
            lambda: state.require_source_rights_binding({}, receipt_digest=digest),
            state.SourceRightsBindingError,
        ),
    )
    for invoke, error_type in failures:
        try:
            invoke()
        except error_type:
            pass
        else:  # pragma: no cover - fail-closed assertion
            raise AssertionError(f"{error_type.__name__} must be preserved")
