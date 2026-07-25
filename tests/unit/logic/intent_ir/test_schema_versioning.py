import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.canonicalize import (
    canonical_intent_ir_json,
    intent_ir_sha256,
)
from ipfs_datasets_py.logic.intent_ir.decoder import (
    INTENT_IR_SCHEMA_REGISTRY,
    IntentIRDecodeError,
    decode_intent_ir,
    migrate_intent_ir,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    INTENT_IR_COLLECTION_SCHEMA,
    INTENT_IR_COLLECTION_SEMANTICS,
    INTENT_IR_SCHEMA_VERSION,
    LEGACY_INTENT_IR_SCHEMA_VERSION,
    CollectionSemantics,
    NodeGrounding,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity


def _v1_payload() -> dict:
    return {
        "schema_version": INTENT_IR_SCHEMA_VERSION,
        "document_id": "intent:canonical-vector",
        "title": "Canonical vector",
        "intent_kind": "procedure",
        "sources": [
            {
                "ref_id": "source:fixture",
                "source_uri": "https://example.test/fixture",
                "source_id": "fixture",
                "source_revision": "revision-1",
                "content_sha256": "a" * 64,
                "review_status": "trusted_fixture",
            }
        ],
        "statements": [
            {
                "statement_id": "statement:goal",
                "kind": "goal",
                "modality": "intended",
                "normalized_text": "Preserve ordered arguments.",
                "source_ref_ids": ["source:fixture"],
                "predicate": "preserve",
                "arguments": ["first", "second", "first"],
                "review_status": "trusted_fixture",
                "grounding": "grounded",
            }
        ],
        "actions": [
            {
                "action_id": "action:preserve",
                "actor": "agent",
                "verb": "preserve",
                "object_refs": ["arguments"],
                "source_ref_ids": ["source:fixture"],
                "grounding": "grounded",
            }
        ],
        "control_edges": [],
        "entry_action_ids": ["action:preserve"],
        "terminal_action_ids": ["action:preserve"],
        "tags": ["vector", "canonical"],
    }


def _legacy_payload() -> dict:
    payload = _v1_payload()
    payload["schema_version"] = LEGACY_INTENT_IR_SCHEMA_VERSION
    for collection in ("statements", "actions", "control_edges"):
        for node in payload[collection]:
            del node["grounding"]
    return payload


def test_v1_canonical_vector_is_pinned() -> None:
    document = decode_intent_ir(_v1_payload())

    assert canonical_intent_ir_json(document) == (
        '{"actions":[{"action_id":"action:preserve","actor":"agent",'
        '"effect_ids":[],"grounding":"grounded","input_refs":[],'
        '"object_refs":["arguments"],"output_refs":[],"precondition_ids":[],'
        '"source_ref_ids":["source:fixture"],"tool_refs":[],"verb":"preserve",'
        '"verification_ids":[]}],"control_edges":[],"document_id":'
        '"intent:canonical-vector","entry_action_ids":["action:preserve"],'
        '"intent_kind":"procedure","schema_version":"intent-ir/v1","sources":'
        '[{"container_sha256":"","container_uri":"","content_cid":"",'
        '"content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"license_expression":"","ref_id":"source:fixture","review_status":'
        '"trusted_fixture","source_id":"fixture","source_revision":"revision-1",'
        '"source_uri":"https://example.test/fixture","span":null}],'
        '"statements":[{"arguments":["first","second","first"],"confidence":1.0,'
        '"grounding":"grounded","kind":"goal","modality":"intended",'
        '"normalized_text":"Preserve ordered arguments.","predicate":"preserve",'
        '"review_status":"trusted_fixture","source_ref_ids":["source:fixture"],'
        '"statement_id":"statement:goal"}],"tags":["canonical","vector"],'
        '"terminal_action_ids":["action:preserve"],"title":"Canonical vector"}'
    )
    assert intent_ir_sha256(document) == (
        "sha256:768c506e3a8311eb5919a811033b77ddcd6603ea19dc5d780837946fd8a98d0d"
    )
    shared_identity = canonical_identity(
        document.to_dict(),
        domain="intent-ir",
        schema_version=INTENT_IR_SCHEMA_VERSION,
        collection_schema=INTENT_IR_COLLECTION_SCHEMA,
    )
    assert shared_identity.digest == (
        "sha256:4a7e98fc3787f2b664cc026bb5ece8350268a9340d3a50838f4ba0097c9de231"
    )
    assert shared_identity.cid == (
        "bafkreickp2mpyn4h6k3gjtacno26z2bvajuksnanhjiihd2luaexzhpcge"
    )


@pytest.mark.parametrize(
    "version",
    [
        None,
        "",
        LEGACY_INTENT_IR_SCHEMA_VERSION,
        "intent-ir/v0",
        "intent-ir/v2",
        1,
    ],
)
def test_decoder_rejects_missing_or_unknown_versions(version: object) -> None:
    payload = _v1_payload()
    if version is None:
        del payload["schema_version"]
    else:
        payload["schema_version"] = version

    with pytest.raises(IntentIRDecodeError, match="schema_version"):
        decode_intent_ir(payload)


def test_decoder_rejects_unknown_fields_and_duplicate_json_keys() -> None:
    payload = _v1_payload()
    payload["statements"][0]["future_field"] = True
    with pytest.raises(IntentIRDecodeError, match="unknown fields"):
        decode_intent_ir(payload)

    duplicate_version = json.dumps(_v1_payload()).replace(
        '{"schema_version":',
        '{"schema_version":"intent-ir/v1","schema_version":',
        1,
    )
    with pytest.raises(IntentIRDecodeError, match="Duplicate JSON object key"):
        decode_intent_ir(duplicate_version)


@pytest.mark.parametrize(
    ("path", "missing_id"),
    [
        (("statements", 0, "source_ref_ids"), "source:missing"),
        (("actions", 0, "source_ref_ids"), "source:missing"),
        (("entry_action_ids",), "action:missing"),
        (("terminal_action_ids",), "action:missing"),
    ],
)
def test_decoder_rejects_every_dangling_internal_reference(
    path: tuple, missing_id: str
) -> None:
    payload = _v1_payload()
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = [missing_id]

    with pytest.raises(IntentIRDecodeError, match="unknown ids"):
        decode_intent_ir(payload)


def test_grounded_and_inferred_nodes_are_explicit() -> None:
    payload = _v1_payload()
    statement = payload["statements"][0]
    statement["grounding"] = "inferred"
    statement["source_ref_ids"] = []
    document = decode_intent_ir(payload)
    assert document.statements[0].grounding is NodeGrounding.INFERRED

    statement["grounding"] = "grounded"
    with pytest.raises(IntentIRDecodeError, match="requires source_ref_ids"):
        decode_intent_ir(payload)


def test_collection_semantics_are_declared_and_enforced() -> None:
    assert (
        INTENT_IR_COLLECTION_SEMANTICS["IntentStatement.arguments"]
        is CollectionSemantics.ORDERED
    )
    assert (
        INTENT_IR_COLLECTION_SEMANTICS["IntentIRDocument.tags"]
        is CollectionSemantics.SET_LIKE
    )
    with pytest.raises(TypeError):
        INTENT_IR_COLLECTION_SEMANTICS["IntentIRDocument.tags"] = (  # type: ignore[index]
            CollectionSemantics.ORDERED
        )

    payload = _v1_payload()
    payload["tags"].append("vector")
    with pytest.raises(IntentIRDecodeError, match="Duplicate"):
        decode_intent_ir(payload)

    document = decode_intent_ir(_v1_payload())
    assert document.statements[0].arguments == ("first", "second", "first")


def test_v0_1_migration_is_auditable_and_classifies_nodes() -> None:
    payload = _legacy_payload()
    payload["control_edges"] = [
        {
            "edge_id": "edge:self",
            "source_action_id": "action:preserve",
            "target_action_id": "action:preserve",
            "kind": "retry",
            "source_ref_ids": [],
        }
    ]

    result = migrate_intent_ir(payload)

    assert result.source_version == LEGACY_INTENT_IR_SCHEMA_VERSION
    assert result.target_version == INTENT_IR_SCHEMA_VERSION
    assert not result.is_lossless
    assert result.loss_diagnostics[0].code == "legacy_grounding_ambiguity"
    assert result.document.statements[0].grounding is NodeGrounding.GROUNDED
    assert result.document.actions[0].grounding is NodeGrounding.GROUNDED
    assert result.document.control_edges[0].grounding is NodeGrounding.INFERRED
    assert {item.code for item in result.diagnostics} == {
        "legacy_grounding_ambiguity",
        "node_grounding_classified",
        "schema_version_upgraded",
    }
    assert result.receipt is not None
    assert result.receipt.loss_report.lossy
    assert result.receipt.verifies(payload, result.document.to_dict())
    assert (
        INTENT_IR_SCHEMA_REGISTRY.negotiate(
            LEGACY_INTENT_IR_SCHEMA_VERSION, INTENT_IR_SCHEMA_VERSION
        ).requires_migration
    )


def test_v0_1_migration_reports_and_can_reject_loss() -> None:
    payload = _legacy_payload()
    payload["tags"] = ["canonical", "canonical"]

    result = migrate_intent_ir(payload)
    assert not result.is_lossless
    duplicate_loss = next(
        item
        for item in result.loss_diagnostics
        if item.code == "duplicate_set_members_removed"
    )
    assert duplicate_loss.path == "$.tags"
    assert result.document.tags == ("canonical",)

    with pytest.raises(IntentIRDecodeError, match="would be lossy"):
        migrate_intent_ir(payload, allow_lossy=False)


def test_migration_rejects_unknown_references_and_versions() -> None:
    payload = _legacy_payload()
    payload["actions"][0]["effect_ids"] = ["statement:missing"]
    with pytest.raises(IntentIRDecodeError, match="unknown ids"):
        migrate_intent_ir(payload)

    payload["schema_version"] = "intent-ir/v0.2"
    with pytest.raises(IntentIRDecodeError, match="Unsupported"):
        migrate_intent_ir(payload)


def test_decoded_document_is_deeply_immutable_and_detached_from_input() -> None:
    payload = _v1_payload()
    document = decode_intent_ir(payload)
    payload["tags"].append("mutated")
    payload["statements"][0]["arguments"][0] = "mutated"

    assert document.tags == ("vector", "canonical")
    assert document.statements[0].arguments == ("first", "second", "first")
    with pytest.raises(FrozenInstanceError):
        document.title = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        document.statements[0].arguments[0] = "mutated"  # type: ignore[index]


def test_json_schema_declares_closed_v1_and_collection_semantics() -> None:
    schema_path = (
        Path(__file__).parents[4]
        / "ipfs_datasets_py"
        / "logic"
        / "intent_ir"
        / "intent_ir.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == INTENT_IR_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert schema["x-extension-policy"] == "closed"
    assert schema["properties"]["actions"]["x-collection-semantics"] == "set-like"
    assert (
        schema["$defs"]["statement"]["properties"]["arguments"][
            "x-collection-semantics"
        ]
        == "ordered"
    )
    assert set(schema["$defs"]["grounding"]["enum"]) == {"grounded", "inferred"}
