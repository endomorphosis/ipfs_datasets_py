"""Unit tests for schema-governed extensions (LFP2-006).

Acceptance coverage:

* unknown or malformed extension payloads fail with stable diagnostics
* registered nodes participate in algebra, elaboration, codecs, and semantic hashing
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.syntax_core.algebra import (
    free_variables,
    semantic_identity,
    substitute,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
    elaborate,
    mk_constant,
    mk_extension,
    mk_predicate,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.codec import (
    CodecError,
    CodecKind,
    TypedLogicCodec,
)
from ipfs_datasets_py.logic.syntax_core.elaboration import (
    ElaborationStatus,
    LogicElaborator,
)
from ipfs_datasets_py.logic.syntax_core.extensions import (
    CODE_EXTENSION_CHILD_ARITY,
    CODE_EXTENSION_FEATURE_MISMATCH,
    CODE_EXTENSION_REQUIRED_KEY,
    CODE_MALFORMED_EXTENSION_PAYLOAD,
    CODE_UNKNOWN_EXTENSION_SCHEMA,
    DEFAULT_EXTENSION_REGISTRY,
    EXTENSION_SCHEMA_REGISTRY_INTERFACE,
    EXTENSIONS_MODULE_VERSION,
    DuplicateExtensionSchemaError,
    ExtensionPosition,
    ExtensionPositionKind,
    ExtensionSchemaDescriptor,
    ExtensionSchemaRegistry,
    MalformedExtensionPayloadError,
    UnknownExtensionSchemaError,
    UnsupportedExtensionError,
    empty_extension_registry,
    modal_box_descriptor,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    atomic_sort,
    propositional_signature,
)


def _prop_signature():
    return propositional_signature("sig:prop:ext", ("P", "Q"))


def _registry() -> ExtensionSchemaRegistry:
    registry = empty_extension_registry("registry:test:ext")
    registry.register(modal_box_descriptor())
    return registry


# ---------------------------------------------------------------------------
# Registry basics
# ---------------------------------------------------------------------------


def test_module_and_interface_identities() -> None:
    assert EXTENSION_SCHEMA_REGISTRY_INTERFACE == "ExtensionSchemaRegistry@1"
    assert EXTENSIONS_MODULE_VERSION
    assert DEFAULT_EXTENSION_REGISTRY.interface == EXTENSION_SCHEMA_REGISTRY_INTERFACE


def test_register_and_lookup() -> None:
    registry = _registry()
    descriptor = registry.get("modal.box/v1")
    assert descriptor.payload_schema == "modal.box/v1"
    assert "modal.box" in descriptor.features
    assert descriptor.min_children == 1
    assert "modal.box/v1" in registry


def test_duplicate_registration_rejected() -> None:
    registry = _registry()
    with pytest.raises(DuplicateExtensionSchemaError, match="already registered"):
        registry.register(modal_box_descriptor())


def test_unknown_schema_stable_diagnostic() -> None:
    registry = _registry()
    report = registry.validate_payload(
        "temporal.next/v1",
        {"kind": "next", "schema_version": "1"},
    )
    assert report.ok is False
    assert any(d.code == CODE_UNKNOWN_EXTENSION_SCHEMA for d in report.diagnostics)
    with pytest.raises(UnknownExtensionSchemaError, match="unknown extension"):
        report.raise_if_failed()


def test_malformed_payload_missing_required_key() -> None:
    registry = _registry()
    report = registry.validate_payload(
        "modal.box/v1",
        {"agent": "a1", "schema_version": "1"},  # missing kind
    )
    assert report.ok is False
    assert any(d.code == CODE_EXTENSION_REQUIRED_KEY for d in report.diagnostics)


def test_malformed_payload_validator_failure() -> None:
    registry = _registry()
    report = registry.validate_payload(
        "modal.box/v1",
        {"kind": "diamond", "schema_version": "1"},
    )
    assert report.ok is False
    assert any(d.code == CODE_MALFORMED_EXTENSION_PAYLOAD for d in report.diagnostics)


def test_child_arity_diagnostic() -> None:
    registry = _registry()
    node = mk_extension(
        "n:box",
        family="modal",
        profile="s5",
        features=("modal.box", "modal.kripke"),
        payload_schema="modal.box/v1",
        payload={"kind": "box", "schema_version": "1"},
        children=(),  # missing body
    )
    report = registry.validate_extension(node)
    assert report.ok is False
    assert any(d.code == CODE_EXTENSION_CHILD_ARITY for d in report.diagnostics)


def test_feature_mismatch_diagnostic() -> None:
    registry = _registry()
    node = mk_extension(
        "n:box",
        family="modal",
        profile="s5",
        features=("modal.kripke",),  # missing modal.box
        payload_schema="modal.box/v1",
        payload={"kind": "box", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    )
    report = registry.validate_extension(node)
    assert report.ok is False
    assert any(d.code == CODE_EXTENSION_FEATURE_MISMATCH for d in report.diagnostics)


def test_require_unsupported_extension() -> None:
    registry = empty_extension_registry()
    with pytest.raises(UnsupportedExtensionError, match="lacks extension"):
        registry.require("modal.box/v1", consumer="translator")


def test_build_node_validates() -> None:
    registry = _registry()
    node = registry.build_node(
        "n:box",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    )
    assert node.kind is NodeKind.EXTENSION
    assert node.extension is not None
    assert node.extension.payload_schema == "modal.box/v1"


def test_build_node_rejects_malformed() -> None:
    registry = _registry()
    with pytest.raises(MalformedExtensionPayloadError):
        registry.build_node(
            "n:box",
            "modal.box/v1",
            {"kind": "diamond"},
            children=(mk_predicate("n:p", "P"),),
        )


def test_freeze_round_trip() -> None:
    registry = _registry()
    frozen = registry.freeze()
    thawed = frozen.thaw()
    assert thawed.get("modal.box/v1").schema_id == "ext:modal.box/v1"
    assert frozen.to_dict()["interface"] == EXTENSION_SCHEMA_REGISTRY_INTERFACE


def test_descriptor_serialization() -> None:
    descriptor = modal_box_descriptor()
    restored = ExtensionSchemaDescriptor.from_dict(descriptor.to_dict())
    assert restored.payload_schema == descriptor.payload_schema
    assert restored.child_positions[0].name == "body"


# ---------------------------------------------------------------------------
# Algebra / elaboration / codec / semantic hashing participation
# ---------------------------------------------------------------------------


def test_registered_extension_elaborates_with_registry() -> None:
    registry = _registry()
    body = mk_predicate("n:p", "P")
    node = registry.build_node(
        "n:box",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1"},
        children=(body,),
    )
    sig = _prop_signature()
    typed = elaborate(node, sig, extension_registry=registry)
    assert typed.kind is NodeKind.EXTENSION
    assert typed.extension is not None
    assert typed.extension.children[0].kind is NodeKind.PREDICATE


def test_elaborator_rejects_unknown_extension_with_stable_code() -> None:
    registry = _registry()
    node = mk_extension(
        "n:next",
        family="temporal",
        profile="ltl",
        features=("temporal.next",),
        payload_schema="temporal.next/v1",
        payload={"kind": "next", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    )
    elaborator = LogicElaborator(
        signature=_prop_signature(),
        extension_registry=registry,
    )
    result = elaborator.elaborate(node)
    assert result.status is ElaborationStatus.FAILED
    assert result.backend_ready is False
    assert any(d.code == CODE_UNKNOWN_EXTENSION_SCHEMA for d in result.diagnostics)


def test_elaborator_rejects_malformed_extension() -> None:
    registry = _registry()
    node = mk_extension(
        "n:box",
        family="modal",
        profile="s5",
        features=("modal.box", "modal.kripke"),
        payload_schema="modal.box/v1",
        payload={"kind": "box", "schema_version": "1"},
        children=(),
    )
    elaborator = LogicElaborator(
        signature=_prop_signature(),
        extension_registry=registry,
    )
    result = elaborator.elaborate(node)
    assert result.status is ElaborationStatus.FAILED
    assert any(d.code == CODE_EXTENSION_CHILD_ARITY for d in result.diagnostics)


def test_registered_extension_backend_ready() -> None:
    registry = _registry()
    node = registry.build_node(
        "n:box",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    )
    elaborator = LogicElaborator(
        signature=_prop_signature(),
        extension_registry=registry,
    )
    result = elaborator.elaborate(node, expression_id="expr:box")
    assert result.status is ElaborationStatus.OK
    assert result.backend_ready is True
    assert result.typed_expression is not None


def test_algebra_free_vars_and_substitute_on_extension_children() -> None:
    person = atomic_sort("Person")
    body = mk_predicate(
        "n:human-x",
        "Human",
        (mk_variable("n:x", "x", person),),
    )
    node = mk_extension(
        "n:box",
        family="modal",
        profile="s5",
        features=("modal.box", "modal.kripke"),
        payload_schema="modal.box/v1",
        payload={"kind": "box", "schema_version": "1"},
        children=(body,),
    )
    free = free_variables(node)
    assert "x" in free

    alice = mk_constant("n:alice", "alice", person)
    replaced = substitute(node, "x", alice)
    assert replaced.extension is not None
    assert replaced.extension.children[0].arguments[0].symbol == "alice"


def test_semantic_identity_stable_for_registered_payload() -> None:
    registry = _registry()
    node_a = registry.build_node(
        "n:box-a",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1", "agent": "a1"},
        children=(mk_predicate("n:p", "P"),),
    )
    node_b = registry.build_node(
        "n:box-b",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1", "agent": "a1"},
        children=(mk_predicate("n:p2", "P"),),
    )
    # Algebra semantic identity ignores surface node ids.
    assert semantic_identity(node_a) == semantic_identity(node_b)
    digest = registry.semantic_identity(node_a.extension)  # type: ignore[arg-type]
    assert len(digest) == 64
    assert digest == registry.semantic_identity(node_b.extension)  # type: ignore[arg-type]


def test_codec_round_trip_extension_node_with_registry() -> None:
    registry = _registry()
    node = registry.build_node(
        "n:box",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    )
    assert node.extension is not None
    codec = TypedLogicCodec(extension_registry=registry)
    envelope = codec.encode_extension_node(node.extension)
    assert envelope.kind is CodecKind.LOGIC_EXTENSION_NODE
    restored = codec.decode(envelope)
    assert isinstance(restored, type(node.extension))
    assert restored.payload_schema == "modal.box/v1"
    assert restored.payload["kind"] == "box"


def test_codec_rejects_unknown_extension_payload() -> None:
    registry = _registry()
    codec = TypedLogicCodec(extension_registry=registry)
    # Build a valid extension node then swap schema via raw dict path.
    ext = mk_extension(
        "n:next",
        family="temporal",
        profile="ltl",
        features=("temporal.next",),
        payload_schema="temporal.next/v1",
        payload={"kind": "next", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    ).extension
    assert ext is not None
    with pytest.raises(CodecError, match="extension payload encode failed"):
        codec.encode_extension_node(ext)


def test_typed_expression_with_registered_extension() -> None:
    registry = _registry()
    node = registry.build_node(
        "n:box",
        "modal.box/v1",
        {"kind": "box", "schema_version": "1"},
        children=(mk_predicate("n:p", "P"),),
    )
    sig = _prop_signature()
    # elaborate_on_init without registry still accepts structure-valid extensions.
    expr = TypedExpression(
        expression_id="expr:box",
        root=elaborate(node, sig, extension_registry=registry),
        signature=sig,
        elaborate_on_init=False,
    )
    assert expr.root.extension is not None
    assert expr.content_digest


def test_binder_position_descriptor() -> None:
    person = atomic_sort("Person")
    descriptor = ExtensionSchemaDescriptor(
        schema_id="ext:modal.knows/v1",
        payload_schema="modal.knows/v1",
        family="modal",
        profile="s5",
        features=("modal.knows",),
        child_positions=(
            ExtensionPosition(
                name="body",
                kind=ExtensionPositionKind.CHILD,
                required=True,
            ),
        ),
        binder_positions=(
            ExtensionPosition(
                name="agent",
                kind=ExtensionPositionKind.BINDER,
                required=True,
                sort=person,
            ),
        ),
        required_keys=("kind",),
    )
    registry = empty_extension_registry()
    registry.register(descriptor)
    body = mk_predicate(
        "n:human",
        "Human",
        (mk_variable("n:a", "a", person),),
    )
    node = LogicNode(
        node_id="n:knows",
        kind=NodeKind.EXTENSION,
        binders=(Binder(name="a", sort=person),),
        extension=mk_extension(
            "n:knows-inner",
            family="modal",
            profile="s5",
            features=("modal.knows",),
            payload_schema="modal.knows/v1",
            payload={"kind": "knows", "schema_version": "1"},
            children=(body,),
        ).extension,
    )
    report = registry.validate_extension(node)
    assert report.ok is True
    # Binder scopes over children for free-variable collection.
    assert "a" not in node.free_variable_names()


def test_registry_to_dict_round_trip() -> None:
    registry = _registry()
    restored = ExtensionSchemaRegistry.from_dict(registry.to_dict())
    assert "modal.box/v1" in restored
    assert restored.registry_id == registry.registry_id


def test_empty_payload_rejected() -> None:
    registry = _registry()
    report = registry.validate_payload("modal.box/v1", {})
    assert report.ok is False
    assert any(d.code == CODE_MALFORMED_EXTENSION_PAYLOAD for d in report.diagnostics)
