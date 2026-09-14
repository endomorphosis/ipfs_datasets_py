"""Contract vectors for SPAR-005 model-pinned advisory projections."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.semantic_refactoring.projections import (
    DECLARED_SEMANTIC_VIEWS,
    DECLARED_SUBJECT_KINDS,
    LOCATION_INDEPENDENT_VIEWS,
    LOCATION_SENSITIVE_VIEWS,
    NEURAL_AVAILABLE,
    NEURAL_UNAVAILABLE,
    PROJECTION_UNAVAILABLE_INTERFACE,
    SEMANTIC_PROJECTION_INTERFACE,
    STRUCTURAL_FINGERPRINT_INTERFACE,
    NeuralCapability,
    ProjectionContractError,
    ProjectionModelPin,
    ProjectionSubject,
    ProjectionUnavailable,
    SemanticProjection,
    SemanticProjectionSet,
    StructuralFingerprint,
    VectorEncoding,
    canonical_projection_bytes,
    decode_vector_bytes,
    encode_vector_bytes,
    fingerprints_for_subject,
    project_declared_views,
)


TREE_ID = "34f495939cb73e1e40b3624acb6f0b7408834515"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _identity_cids(*, prefix: str = "id") -> dict[str, str]:
    return {view: _cid(f"{prefix}:{view}") for view in DECLARED_SEMANTIC_VIEWS}


def _unit(*components: float) -> list[float]:
    norm = math.sqrt(sum(item * item for item in components))
    return [item / norm for item in components]


def _vector_for_view(view: str) -> list[float]:
    index = DECLARED_SEMANTIC_VIEWS.index(view) + 1
    return _unit(float(index), 1.0, 2.0, 3.0)


def _vectors() -> dict[str, list[float]]:
    return {view: _vector_for_view(view) for view in DECLARED_SEMANTIC_VIEWS}


def _model_pin(**overrides: str) -> ProjectionModelPin:
    payload = {
        "model_id": "spar-minilm-l6",
        "model_revision": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "tokenizer_id": "spar-minilm-l6-tokenizer",
        "tokenizer_revision": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "preprocessor_id": "spar-bodyfree-chunker@1",
        "preprocessor_revision": "1",
        "profile_id": "spar-projection-profile@1",
    }
    payload.update(overrides)
    return ProjectionModelPin(**payload)


def _subject(
    *,
    kind: str = "function",
    module_path: str = "pkg/mod.py",
    qualified_name: str = "pkg.mod.answer",
    identity_cids: dict[str, str] | None = None,
    source_label: str = "source:answer",
    stable_label: str = "symbol:answer",
) -> ProjectionSubject:
    return ProjectionSubject(
        kind=kind,
        tree_id=TREE_ID,
        source_cid=_cid(source_label),
        stable_symbol_id=_cid(stable_label),
        module_path=module_path,
        qualified_name=qualified_name,
        identity_cids=identity_cids or _identity_cids(),
        capsule_cid=_cid(f"capsule:{kind}:{qualified_name}"),
    )


def test_declared_views_and_subject_kinds_are_closed() -> None:
    assert "function" in DECLARED_SUBJECT_KINDS
    assert "module" in DECLARED_SUBJECT_KINDS
    assert len(DECLARED_SEMANTIC_VIEWS) == len(set(DECLARED_SEMANTIC_VIEWS))
    assert LOCATION_SENSITIVE_VIEWS.isdisjoint(LOCATION_INDEPENDENT_VIEWS)
    assert LOCATION_SENSITIVE_VIEWS | LOCATION_INDEPENDENT_VIEWS == set(
        DECLARED_SEMANTIC_VIEWS
    )


def test_semantic_projection_interface_constants() -> None:
    assert SemanticProjection.INTERFACE == SEMANTIC_PROJECTION_INTERFACE == "SemanticProjection@1"
    assert (
        ProjectionUnavailable.INTERFACE
        == PROJECTION_UNAVAILABLE_INTERFACE
        == "ProjectionUnavailable@1"
    )
    assert StructuralFingerprint.INTERFACE == STRUCTURAL_FINGERPRINT_INTERFACE


def test_neural_projections_cover_every_declared_view_for_function_and_module() -> None:
    pin = _model_pin()
    for kind, module_path, qualified_name in (
        ("function", "pkg/mod.py", "pkg.mod.answer"),
        ("module", "pkg/mod.py", "pkg.mod"),
    ):
        subject = _subject(
            kind=kind,
            module_path=module_path,
            qualified_name=qualified_name,
        )
        bundle = project_declared_views(
            subject,
            neural_capability=NeuralCapability.AVAILABLE,
            model_pin=pin,
            vectors_by_view=_vectors(),
        )
        assert bundle.neural_capability == NEURAL_AVAILABLE
        assert bundle.semantic_authority is False
        assert len(bundle.projections) == len(DECLARED_SEMANTIC_VIEWS)
        assert {item.view for item in bundle.projections} == set(DECLARED_SEMANTIC_VIEWS)
        assert {item.view for item in bundle.fingerprints} == set(DECLARED_SEMANTIC_VIEWS)
        for view in DECLARED_SEMANTIC_VIEWS:
            projection = bundle.record_for_view(view)
            assert isinstance(projection, SemanticProjection)
            assert projection.view == view
            assert projection.subject.kind == kind
            assert projection.model_pin.pin_cid == pin.pin_cid
            assert projection.availability == NEURAL_AVAILABLE
            assert projection.authority["semantic_authority"] is False
            assert projection.authority["authorizes_transition"] is False
            assert projection.authority["suppresses_raw_source"] is False
            assert projection.authority["raw_source_required"] is True
            assert projection.vector.dimension == 4
            assert projection.vector.metric == "cosine"
            assert projection.vector.dtype == "float32"
            assert projection.vector.byte_order == "little"
            round_trip = SemanticProjection.from_dict(projection.to_dict())
            assert round_trip.projection_cid == projection.projection_cid


def test_unavailable_neural_capability_emits_typed_residuals_and_fingerprints() -> None:
    subject = _subject(kind="module")
    bundle = project_declared_views(
        subject,
        neural_capability=False,
    )
    assert bundle.neural_capability == NEURAL_UNAVAILABLE
    assert bundle.projections == ()
    assert len(bundle.unavailability) == len(DECLARED_SEMANTIC_VIEWS)
    assert len(bundle.fingerprints) == len(DECLARED_SEMANTIC_VIEWS)
    for view in DECLARED_SEMANTIC_VIEWS:
        residual = bundle.record_for_view(view)
        assert isinstance(residual, ProjectionUnavailable)
        assert residual.INTERFACE == "ProjectionUnavailable@1"
        assert residual.reason == "neural_capability_unavailable"
        assert residual.availability == NEURAL_UNAVAILABLE
        assert residual.authority["raw_source_required"] is True
        assert residual.authority["suppresses_raw_source"] is False
        assert residual.fingerprint.algorithm == "structural.sha2-256@1"
        assert residual.fingerprint.fingerprint_cid == bundle.fingerprint_for_view(view).fingerprint_cid
        rebuilt = ProjectionUnavailable.from_dict(residual.to_dict())
        assert rebuilt.unavailable_cid == residual.unavailable_cid


def test_unavailable_path_rejects_model_pin_and_vectors() -> None:
    subject = _subject()
    with pytest.raises(ProjectionContractError, match="rejects a model pin"):
        project_declared_views(
            subject,
            neural_capability=NEURAL_UNAVAILABLE,
            model_pin=_model_pin(),
        )
    with pytest.raises(ProjectionContractError, match="rejects neural vectors"):
        project_declared_views(
            subject,
            neural_capability=NEURAL_UNAVAILABLE,
            vectors_by_view=_vectors(),
        )


def test_available_path_requires_model_pin_and_complete_vectors() -> None:
    subject = _subject()
    with pytest.raises(ProjectionContractError, match="requires a model pin"):
        project_declared_views(subject, neural_capability=True)
    with pytest.raises(ProjectionContractError, match="requires vectors"):
        project_declared_views(
            subject,
            neural_capability=True,
            model_pin=_model_pin(),
        )
    incomplete = _vectors()
    incomplete.pop("ast")
    with pytest.raises(ProjectionContractError, match="missing"):
        project_declared_views(
            subject,
            neural_capability=True,
            model_pin=_model_pin(),
            vectors_by_view=incomplete,
        )


def test_unknown_view_and_unknown_fields_fail_closed() -> None:
    subject = _subject()
    with pytest.raises(ProjectionContractError, match="unknown fields"):
        SemanticProjection.from_dict({**SemanticProjection.create(
            subject=subject,
            view="ast",
            model_pin=_model_pin(),
            vector=_vector_for_view("ast"),
        ).to_dict(), "extra": True})
    with pytest.raises(ProjectionContractError, match="unsupported value"):
        SemanticProjection.create(
            subject=subject,
            view="not_a_view",
            model_pin=_model_pin(),
            vector=_vector_for_view("ast"),
        )
    extra_views = _vectors()
    extra_views["invented"] = _unit(1.0, 0.0, 0.0, 0.0)
    with pytest.raises(ProjectionContractError, match="unknown views"):
        project_declared_views(
            subject,
            neural_capability=True,
            model_pin=_model_pin(),
            vectors_by_view=extra_views,
        )


def test_nonfinite_and_mismatched_vectors_fail() -> None:
    with pytest.raises(ProjectionContractError, match="non-finite"):
        encode_vector_bytes([1.0, float("nan")], dtype="float32", byte_order="little")
    with pytest.raises(ProjectionContractError, match="non-finite"):
        encode_vector_bytes([1.0, float("inf")], dtype="float32", byte_order="little")
    with pytest.raises(ProjectionContractError, match="byte length"):
        decode_vector_bytes(
            encode_vector_bytes([1.0, 0.0], dtype="float32", byte_order="little"),
            dtype="float32",
            byte_order="little",
            dimension=4,
        )
    with pytest.raises(ProjectionContractError, match="L2-normalized"):
        VectorEncoding.from_values([1.0, 0.0, 0.0, 0.5], metric="cosine")
    with pytest.raises(ProjectionContractError, match="vector_cid does not verify"):
        payload = VectorEncoding.from_values(_unit(1.0, 0.0, 0.0, 0.0), metric="cosine").to_dict()
        payload["vector_cid"] = _cid("tampered")
        VectorEncoding.from_dict(payload)


def test_model_pin_is_part_of_projection_identity() -> None:
    subject = _subject()
    first = SemanticProjection.create(
        subject=subject,
        view="behavior_summary",
        model_pin=_model_pin(),
        vector=_vector_for_view("behavior_summary"),
    )
    second = SemanticProjection.create(
        subject=subject,
        view="behavior_summary",
        model_pin=_model_pin(model_revision="sha256:" + "c" * 64),
        vector=_vector_for_view("behavior_summary"),
    )
    assert first.projection_cid != second.projection_cid
    same = SemanticProjection.from_dict(first.to_dict())
    assert same.projection_cid == first.projection_cid
    assert canonical_projection_bytes(first) == canonical_projection_bytes(same)


def test_model_pin_mismatch_across_views_is_rejected() -> None:
    subject = _subject()
    pin = _model_pin()
    projections = [
        SemanticProjection.create(
            subject=subject,
            view=view,
            model_pin=pin if view != "effect_summary" else _model_pin(model_id="other-model"),
            vector=_vector_for_view(view),
        )
        for view in DECLARED_SEMANTIC_VIEWS
    ]
    with pytest.raises(ProjectionContractError, match="model pin mismatch"):
        SemanticProjectionSet(
            subject=subject,
            neural_capability=NEURAL_AVAILABLE,
            fingerprints=fingerprints_for_subject(subject),
            projections=tuple(projections),
        )


def test_authority_flags_cannot_self_authorize() -> None:
    subject = _subject()
    projection = SemanticProjection.create(
        subject=subject,
        view="source",
        model_pin=_model_pin(),
        vector=_vector_for_view("source"),
    )
    payload = projection.to_dict()
    payload["authority"] = {
        **payload["authority"],
        "semantic_authority": True,
    }
    with pytest.raises(ProjectionContractError, match="advisory only"):
        SemanticProjection.from_dict(payload)
    payload = projection.to_dict()
    payload["authority"] = {
        **payload["authority"],
        "suppresses_raw_source": True,
        "raw_source_required": False,
    }
    with pytest.raises(ProjectionContractError, match="advisory only"):
        SemanticProjection.from_dict(payload)


def test_identity_separation_on_move_preserves_implementation_not_binding() -> None:
    original = _subject(
        kind="function",
        module_path="pkg/old.py",
        qualified_name="pkg.old.answer",
    )
    moved_cids = dict(original.identity_cids)
    moved_cids["symbol_binding"] = _cid("id:symbol_binding:moved")
    moved_cids["public_compatibility"] = _cid("id:public_compatibility:moved")
    moved = original.relocated(
        module_path="pkg/new.py",
        qualified_name="pkg.new.answer",
        identity_cids={
            "symbol_binding": moved_cids["symbol_binding"],
            "public_compatibility": moved_cids["public_compatibility"],
        },
        stable_symbol_id=_cid("symbol:answer:moved"),
    )
    original_fps = {item.view: item for item in fingerprints_for_subject(original)}
    moved_fps = {item.view: item for item in fingerprints_for_subject(moved)}
    for view in LOCATION_INDEPENDENT_VIEWS:
        assert original_fps[view].features["identity_cid"] == moved_fps[view].features["identity_cid"]
        assert "module_path" not in original_fps[view].features
        assert "qualified_name" not in original_fps[view].features
    for view in LOCATION_SENSITIVE_VIEWS:
        assert original_fps[view].fingerprint_cid != moved_fps[view].fingerprint_cid
        assert original_fps[view].features["module_path"] != moved_fps[view].features["module_path"]
        assert original_fps[view].features["qualified_name"] != moved_fps[view].features["qualified_name"]
    pin = _model_pin()
    original_bundle = project_declared_views(
        original,
        neural_capability=True,
        model_pin=pin,
        vectors_by_view=_vectors(),
    )
    moved_bundle = project_declared_views(
        moved,
        neural_capability=True,
        model_pin=pin,
        vectors_by_view=_vectors(),
    )
    assert original_bundle.record_for_view("implementation_ir").projection_cid != (
        moved_bundle.record_for_view("implementation_ir").projection_cid
    )
    assert original.identity_cids["implementation_ir"] == moved.identity_cids["implementation_ir"]
    assert original.identity_cids["symbol_binding"] != moved.identity_cids["symbol_binding"]


def test_structural_fingerprints_are_deterministic_and_self_verifying() -> None:
    subject = _subject(kind="function")
    first = fingerprints_for_subject(subject)
    second = fingerprints_for_subject(subject)
    assert [item.fingerprint_cid for item in first] == [
        item.fingerprint_cid for item in second
    ]
    for item in first:
        rebuilt = StructuralFingerprint.from_dict(item.to_dict())
        assert rebuilt.fingerprint_cid == item.fingerprint_cid
        claimed = item.to_dict()
        claimed["fingerprint_cid"] = _cid("wrong")
        with pytest.raises(ProjectionContractError, match="does not verify"):
            StructuralFingerprint.from_dict(claimed)


def test_projection_set_round_trip_and_canonical_bytes() -> None:
    subject = _subject(kind="module")
    bundle = project_declared_views(
        subject,
        neural_capability=True,
        model_pin=_model_pin(),
        vectors_by_view=_vectors(),
    )
    rebuilt = SemanticProjectionSet.from_dict(bundle.to_dict())
    assert rebuilt.set_cid == bundle.set_cid
    assert canonical_projection_bytes(bundle) == canonical_projection_bytes(rebuilt)
    payload = bundle.to_dict()
    payload["extra"] = "nope"
    with pytest.raises(ProjectionContractError, match="unknown fields"):
        SemanticProjectionSet.from_dict(payload)


def test_vector_bytes_cid_matches_raw_bytes() -> None:
    values = _unit(0.0, 1.0, 0.0, 0.0)
    encoded = VectorEncoding.from_values(values, metric="cosine", dtype="float32")
    raw = bytes.fromhex(encoded.vector_bytes_hex)
    assert encoded.vector_cid == cid_for_bytes(raw)
    decoded = decode_vector_bytes(
        encoded.vector_bytes_hex,
        dtype="float32",
        byte_order="little",
        dimension=4,
    )
    assert decoded == pytest.approx(tuple(values), abs=1e-6)


def test_subject_rejects_local_paths_and_unknown_kinds() -> None:
    with pytest.raises(ProjectionContractError, match="relative POSIX"):
        _subject(module_path="../outside.py")
    with pytest.raises(ProjectionContractError, match="unsupported value"):
        _subject(kind="script")
    with pytest.raises(ProjectionContractError, match="lowercase hex"):
        ProjectionSubject(
            kind="function",
            tree_id="not-a-tree",
            source_cid=_cid("source"),
            stable_symbol_id=_cid("symbol"),
            module_path="pkg/mod.py",
            qualified_name="pkg.mod.answer",
            identity_cids=_identity_cids(),
        )


def test_complete_set_cid_is_content_addressed() -> None:
    subject = _subject()
    bundle = project_declared_views(
        subject,
        neural_capability=False,
    )
    expected = cid_for_structured(bundle.identity_payload())
    assert bundle.set_cid == expected
    cloned = deepcopy(bundle.to_dict())
    cloned["set_cid"] = _cid("forged")
    with pytest.raises(ProjectionContractError, match="set_cid does not verify"):
        SemanticProjectionSet.from_dict(cloned)


@pytest.mark.parametrize("kind", DECLARED_SUBJECT_KINDS)
def test_every_declared_subject_kind_accepts_structural_fingerprints(kind: str) -> None:
    subject = _subject(kind=kind, qualified_name=f"pkg.mod.{kind}")
    bundle = project_declared_views(subject, neural_capability=NEURAL_UNAVAILABLE)
    assert [item.subject_kind for item in bundle.fingerprints] == [kind] * len(
        DECLARED_SEMANTIC_VIEWS
    )
    assert all(item.reason == "neural_capability_unavailable" for item in bundle.unavailability)


def test_nested_model_pin_cid_verifies() -> None:
    pin = _model_pin()
    payload = pin.to_dict()
    assert payload["pin_cid"] == cid_for_structured(pin.identity_payload())
    payload["pin_cid"] = _cid("forged-pin")
    with pytest.raises(ProjectionContractError, match="pin_cid does not verify"):
        ProjectionModelPin.from_dict(payload)
