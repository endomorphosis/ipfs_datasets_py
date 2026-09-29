"""Modality identity isolation; fixture declarations are not qualification."""
from dataclasses import FrozenInstanceError, replace
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import (
    EmbeddingIdentity, ImplementationIdentity, ModalityAdapterRegistry, ModalityContract,
    ModalityContractError, ProjectionSpec, ValidatorRequirement, require_compatible_contracts,
)


def implementation(name="fixture.native", digest="a"):
    return ImplementationIdentity(name, "v1", digest * 64)


def contract(**changes):
    values = dict(domain="ui_ux_ir", ir_schema="ui-ux-ir/v1", source_language="en",
                  input_schema="native-projection-features/v1",
                  embedding=EmbeddingIdentity("native-projection-features", "v1", 12, "b" * 64),
                  projections=(ProjectionSpec("navigation", "transition_system", "navigation/v1",
                                              property_ids=("reachability", "safety")),),
                  target_codec=implementation("fixture.targets"), state_codec=implementation("fixture.state"),
                  optimizer=implementation("fixture.optimizer"), objective_id="raw-reconstruction/v1",
                  objective_sha256="c" * 64,
                  validators=(ValidatorRequirement("fixture.check", "advisory", "candidate", ("navigation",)),),
                  adapter=implementation())
    return ModalityContract(**(values | changes))


def test_closed_roundtrip_and_stable_native_identity():
    original = contract()
    restored = ModalityContract.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored == original
    assert restored.sha256 == original.digest
    assert len(original.sha256) == 64
    require_compatible_contracts(original, restored)
    manifest = original.registry_manifest()
    assert manifest["modality_contract_sha256"] == original.sha256
    assert manifest["modality_contract"] == original.to_dict()
    assert manifest["model_variant"] == original.variant_id
    assert all(manifest[key] is False for key in ("qualified", "admitted", "formalized", "promotion_performed"))
    assert original.sha256 in original.publication_namespace
    assert original.publication_namespace.startswith("autoencoders/ui_ux_ir/")


@pytest.mark.parametrize("identifier", ["intent-route/facts/v1", "program.program_ir/v1", "ui/view@2",
                                       "native-projection-feature-autoencoder/v1"])
def test_native_versioned_identifiers_are_preserved(identifier):
    projection = ProjectionSpec(identifier, "first_order", "native/v1")
    validator = ValidatorRequirement(identifier, "advisory", "candidate", (identifier,))
    value = contract(projections=(projection,), validators=(validator,), adapter=implementation(identifier))
    assert value.projections[0].projection_id == identifier
    assert ModalityContract.from_dict(value.to_dict()) == value


@pytest.mark.parametrize("identifier", ["../escape", "x/../../y", "/absolute", "x//y", "x/./y", "x\\y", "space id"])
def test_native_identifiers_reject_traversal_or_whitespace(identifier):
    with pytest.raises(ModalityContractError):
        ProjectionSpec(identifier, "first_order", "native/v1")
    with pytest.raises(ModalityContractError):
        implementation(identifier)


@pytest.mark.parametrize("changed", [
    {"domain": "security_ir"}, {"ir_schema": "ui-ux-ir/v2"}, {"source_language": "de"},
    {"input_schema": "different-source/v1"},
    {"embedding": EmbeddingIdentity("different-model", "v1", 12, "b" * 64)},
    {"embedding": EmbeddingIdentity("native-projection-features", "v2", 12, "b" * 64)},
    {"embedding": EmbeddingIdentity("native-projection-features", "v1", 12, "d" * 64)},
    {"target_codec": implementation("fixture.other-targets")},
    {"state_codec": implementation("fixture.other-layout")},
    {"optimizer": implementation("fixture.other-optimizer")},
    {"optimizer": implementation("fixture.optimizer", "d")},
    {"objective_id": "safety-projected/v1"}, {"objective_sha256": "d" * 64},
    {"adapter": implementation("fixture.other-adapter")},
    {"projections": (ProjectionSpec("navigation", "temporal", "navigation/v1"),)},
    {"projections": (ProjectionSpec("navigation", "transition_system", "navigation/v2"),)},
    {"validators": (ValidatorRequirement("fixture.other", "bounded", "trace", ("navigation",)),)},
])
def test_same_dimensions_cannot_alias_different_modality_semantics(changed):
    original, different = contract(), contract(**changed)
    assert original.embedding.dimension == different.embedding.dimension
    assert original.variant_id != different.variant_id
    assert original.publication_namespace != different.publication_namespace
    with pytest.raises(ModalityContractError, match="incompatible modality contracts"):
        require_compatible_contracts(original, different)


def test_canonical_named_head_order_does_not_change_identity():
    extra = ProjectionSpec("accessibility", "first_order", "accessibility/v1")
    original = contract(projections=(extra, *contract().projections))
    reversed_contract = replace(original, projections=tuple(reversed(original.projections)))
    assert original.sha256 == reversed_contract.sha256
    assert original.projections[1].property_ids == ("reachability", "safety")


@pytest.mark.parametrize("family", ["fol", "lean", "information_flow", "temporal_first_order", "ui_ux", "other"])
def test_notations_profiles_providers_and_unknown_labels_are_not_families(family):
    with pytest.raises(ModalityContractError, match="canonical family"):
        ProjectionSpec("example", family, "example/v1")


@pytest.mark.parametrize("family,composition", [("tdfol", "tdfol_composition_v1"), ("dcec", "dcec_composition_v1")])
def test_composed_families_bind_explicit_full_composition(family, composition):
    with pytest.raises(ModalityContractError, match="explicit composition"):
        ProjectionSpec("example", family, "example/v1")
    projection = ProjectionSpec("example", family, "example/v1", composition_id=composition)
    payload = projection.to_dict()
    assert payload["catalog_binding"]["composition"]["family_id"] == family
    assert payload["catalog_binding"]["composition"]["metadata"]["component_family_ids"]
    assert ProjectionSpec.from_dict(payload) == projection
    with pytest.raises(ModalityContractError, match="does not belong"):
        ProjectionSpec("example", "first_order", "example/v1", composition_id=composition)


def test_profile_property_and_view_names_have_separate_roles():
    accepted = ProjectionSpec("trace", "hyperproperty", "trace/v1", profile_id="hyperltl",
                              property_ids=("noninterference",), view_role="verification_condition")
    assert accepted.to_dict()["catalog_binding"]["profile_sha256"]
    with pytest.raises(ModalityContractError, match="profile/family"):
        replace(accepted, family_id="deontic")
    with pytest.raises(ModalityContractError):
        replace(accepted, property_ids=("hyperltl",))
    with pytest.raises(ModalityContractError):
        replace(accepted, view_role="lean")


def test_native_profiles_and_view_roles_are_bound_without_becoming_taxonomy_ids():
    projection = ProjectionSpec("program.program_ir/v1", "program", "native_typed_document",
                                native_profile_id="program_ir", native_view_role="source_code")
    original = contract(projections=(projection,), validators=(
        ValidatorRequirement("native.check", "advisory", "candidate", (projection.projection_id,)),))
    assert projection.profile_id is None
    assert projection.to_dict()["catalog_binding"]["profile_sha256"] is None
    assert projection.native_profile_id == "program_ir"
    assert ModalityContract.from_dict(original.to_dict()) == original
    for changes in ({"native_profile_id": "dynamic_hoare"}, {"native_view_role": "verification_condition"}):
        different = replace(original, projections=(replace(projection, **changes),))
        assert different.sha256 != original.sha256
        with pytest.raises(ModalityContractError, match="projections"):
            require_compatible_contracts(original, different)
    with pytest.raises(ModalityContractError):
        replace(projection, profile_id="program_ir")
    with pytest.raises(ModalityContractError):
        replace(projection, view_role="source_code")


@pytest.mark.parametrize("field", ["schema", "domain", "embedding", "projections", "adapter", "validators"])
def test_required_wire_fields_cannot_disappear(field):
    payload = contract().to_dict()
    del payload[field]
    with pytest.raises(ModalityContractError):
        ModalityContract.from_dict(payload)


def test_untrusted_metadata_cannot_select_dynamic_import_or_change_catalog_binding():
    payload = contract().to_dict()
    payload["python_module"] = "os"
    with pytest.raises(ModalityContractError, match="fields differ"):
        ModalityContract.from_dict(payload)
    payload = contract().to_dict()
    payload["adapter"]["callable"] = "system"
    with pytest.raises(ModalityContractError, match="fields differ"):
        ModalityContract.from_dict(payload)
    payload = contract().to_dict()
    payload["projections"][0]["catalog_binding"]["family_sha256"] = "f" * 64
    with pytest.raises(ModalityContractError, match="catalog binding changed"):
        ModalityContract.from_dict(payload)


def test_duplicates_missing_coverage_and_unknown_projection_references_fail_closed():
    original = contract()
    invalid = [
        {"projections": (*original.projections, *original.projections)},
        {"projections": ()},
        {"projections": (replace(original.projections[0], required=False),)},
        {"validators": ()},
        {"validators": (*original.validators, *original.validators)},
        {"validators": (replace(original.validators[0], required=False),)},
        {"validators": (replace(original.validators[0], projection_ids=("undeclared",)),)},
        {"training_purpose": "formalization"},
    ]
    for changes in invalid:
        with pytest.raises(ModalityContractError):
            replace(original, **changes)


def test_contract_and_collections_are_immutable():
    projection = ProjectionSpec("navigation", "transition_system", "navigation/v1", property_ids=["safety"])
    original = contract(projections=[projection])
    with pytest.raises(FrozenInstanceError):
        original.domain = "security_ir"
    detached = original.to_dict()
    detached["embedding"]["model_id"] = "changed"
    detached["projections"][0]["property_ids"].append("secrecy")
    assert original.embedding.model_id == "native-projection-features"
    assert original.projections[0].property_ids == ("safety",)


def test_native_capabilities_must_be_explicitly_registered_for_exact_contract():
    original, registry = contract(), ModalityAdapterRegistry()
    with pytest.raises(ModalityContractError, match="no local adapter"):
        registry.resolve(original, required_capabilities=("train",))
    calls = []
    adapter = SimpleNamespace(prepare_targets=lambda: calls.append("prepare"), train=lambda: calls.append("train"))
    registered = registry.register(original, adapter, capabilities=("prepare_targets",))
    assert registered.implementation == original.adapter
    assert registry.resolve(original, required_capabilities=("prepare_targets",)) is adapter
    assert calls == []  # Neither registration nor resolution executes a capability.
    with pytest.raises(ModalityContractError, match="lacks required"):
        registry.resolve(original, required_capabilities=("train",))
    with pytest.raises(ModalityContractError, match="no local adapter"):
        registry.resolve(replace(original, objective_sha256="d" * 64))
    with pytest.raises(ModalityContractError, match="already registered"):
        registry.register(original, adapter, capabilities=("train",))
    with pytest.raises(TypeError):
        registry.registrations["new"] = registered


def test_registry_rejects_unimplemented_or_unknown_capabilities_without_partial_registration():
    registry, original = ModalityAdapterRegistry(), contract()
    for capabilities in (("os.system",), ("train",), ("train", "train"), (), "train"):
        with pytest.raises(ModalityContractError):
            registry.register(original, object(), capabilities=capabilities)
    assert not registry.registrations
    with pytest.raises(ModalityContractError):
        registry.resolve(original, required_capabilities=("os.system",))


@pytest.mark.parametrize("changes", [{"dimension": True}, {"dimension": 0}, {"dimension": 1_000_001},
                                     {"revision": "main"}, {"provenance_sha256": "unknown"}])
def test_embedding_identity_requires_bounded_shape_and_immutable_provenance(changes):
    with pytest.raises(ModalityContractError):
        replace(contract().embedding, **changes)


def test_new_metadata_does_not_bypass_existing_legal_worker():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import ModelVariant, TrainingJobValidationError
    with pytest.raises(TrainingJobValidationError):
        ModelVariant.from_dict(contract().model_variant_metadata())
    assert ModelVariant().target_formal_language == "typed_deontic_ir"
