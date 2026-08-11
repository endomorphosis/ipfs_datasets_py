"""Unit tests for Abby content → logical-action link schema (VOICE-ACTION-004)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.voice.action_links import (
    ACTION_LINK_DOC_PATH,
    ACTION_LINK_SCHEMA,
    ACTION_LINK_SCHEMA_VERSION,
    FORBIDDEN_CONTENT_FIELDS,
    NO_ACTION,
    OUTCOME_FRAME_KEYS,
    ROUTE_CLASSIFICATIONS,
    ActionLink,
    ActionLinkDocument,
    ActionLinkSchemaError,
    canonical_json,
    content_digest,
    golden_action_link_document,
    golden_action_link_vectors,
    parse_action_link,
    parse_action_link_document,
    reject_forbidden_content_fields,
    stable_action_link_id,
    validate_action_link,
    validate_action_link_document,
)

# ipfs_datasets_py/tests/unit/voice → parents[4] is the monorepo root.
REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_DOC = REPO_ROOT / "docs" / "voice_action_dag" / "schemas" / "action-link-v1.md"


def _proposal_payload(**overrides):
    payload = {
        "schema": ACTION_LINK_SCHEMA,
        "schema_version": ACTION_LINK_SCHEMA_VERSION,
        "route": "app_surface_navigation",
        "logical_action": "open_app_surface",
        "classification": "proposal-eligible",
        "confirmation_frame_id": "frame.action.confirm.open_app_surface.v1",
        "outcome_frame_ids": {
            "success": "frame.action.outcome.open_app_surface.success.v1",
            "denied": "frame.action.outcome.open_app_surface.denied.v1",
            "failed": "frame.action.outcome.open_app_surface.failed.v1",
        },
    }
    payload.update(overrides)
    return payload


def test_schema_doc_exists_and_matches_constants():
    assert ACTION_LINK_DOC_PATH == "docs/voice_action_dag/schemas/action-link-v1.md"
    assert SCHEMA_DOC.is_file()
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    assert ACTION_LINK_SCHEMA in text
    assert ACTION_LINK_SCHEMA_VERSION in text
    assert "confirmation_frame_id" in text
    assert "outcome_frame_ids" in text
    assert "logical_action" in text
    for name in ("command", "argv", "url", "import_path", "env"):
        assert name in text


def test_route_to_logical_action_and_frames_round_trip():
    link = validate_action_link(_proposal_payload())
    assert link.route == "app_surface_navigation"
    assert link.logical_action == "open_app_surface"
    assert link.confirmation_frame_id == (
        "frame.action.confirm.open_app_surface.v1"
    )
    assert link.outcome_frame_ids["success"].endswith("success.v1")
    assert link.may_propose is True
    assert link.is_no_action is False

    again = parse_action_link(link.to_dict())
    assert again == link
    assert again.content_digest() == link.content_digest()


def test_logical_action_id_synonym_normalizes_to_logical_action():
    payload = _proposal_payload()
    payload.pop("logical_action")
    payload["logical_action_id"] = "open_app_surface"
    link = parse_action_link(payload)
    assert link.logical_action == "open_app_surface"
    assert "logical_action_id" not in link.to_dict()


def test_content_only_requires_no_action_and_no_frames():
    link = ActionLink(
        route="clarifying_prompt",
        logical_action=NO_ACTION,
        classification="content-only",
    )
    assert link.is_no_action is True
    assert link.may_propose is False
    assert link.confirmation_frame_id is None
    assert dict(link.outcome_frame_ids) == {}

    with pytest.raises(ActionLinkSchemaError, match="no_action"):
        ActionLink(
            route="clarifying_prompt",
            logical_action="open_app_surface",
            classification="content-only",
        )

    with pytest.raises(ActionLinkSchemaError, match="confirmation_frame_id"):
        ActionLink(
            route="clarifying_prompt",
            logical_action=NO_ACTION,
            classification="content-only",
            confirmation_frame_id="frame.should.not.exist",
        )

    with pytest.raises(ActionLinkSchemaError, match="outcome_frame_ids"):
        ActionLink(
            route="clarifying_prompt",
            logical_action=NO_ACTION,
            classification="content-only",
            outcome_frame_ids={
                "success": "frame.should.not.exist",
            },
        )


def test_proposal_eligible_rejects_no_action():
    with pytest.raises(ActionLinkSchemaError, match="real catalog"):
        ActionLink(
            route="app_surface_navigation",
            logical_action=NO_ACTION,
            classification="proposal-eligible",
        )


@pytest.mark.parametrize("field_name", sorted(FORBIDDEN_CONTENT_FIELDS))
def test_rejects_forbidden_top_level_fields(field_name: str):
    payload = _proposal_payload(**{field_name: "/usr/bin/true"})
    with pytest.raises(ActionLinkSchemaError, match="forbidden"):
        parse_action_link(payload)


@pytest.mark.parametrize(
    "field_name",
    ["command", "argv", "url", "import_path", "env", "import", "Import_Path"],
)
def test_rejects_command_argv_url_import_env_fields(field_name: str):
    # Acceptance surface: command/argv/url/import/env (and close variants).
    payload = _proposal_payload()
    payload["outcome_frame_ids"] = {
        "success": "frame.ok",
        field_name: "smuggled",
    }
    # Nested forbidden keys under outcome_frame_ids fail closed (ban list or
    # case-folded match); unknown non-forbidden roles also fail closed.
    with pytest.raises(ActionLinkSchemaError):
        parse_action_link(payload)


def test_rejects_nested_forbidden_fields_and_path_suffix():
    with pytest.raises(ActionLinkSchemaError, match="forbidden"):
        reject_forbidden_content_fields(
            {"notes": {"command": "echo hi"}},
        )
    with pytest.raises(ActionLinkSchemaError, match="path"):
        reject_forbidden_content_fields({"binary_path": "/tmp/x"})
    with pytest.raises(ActionLinkSchemaError, match="path"):
        parse_action_link(_proposal_payload(**{"adapter_path": "/opt/tool"}))


def test_rejects_unknown_fields_and_outcome_roles():
    with pytest.raises(ActionLinkSchemaError, match="unknown"):
        parse_action_link(_proposal_payload(adapter="cli"))
    with pytest.raises(ActionLinkSchemaError, match="outcome role"):
        parse_action_link(
            _proposal_payload(
                outcome_frame_ids={"not_a_role": "frame.x"},
            )
        )


def test_document_sorts_routes_and_resolves_missing_as_no_action():
    doc = ActionLinkDocument(
        links=(
            ActionLink(
                route="wallet_document_support",
                logical_action="open_wallet_documents",
                classification="proposal-eligible",
            ),
            ActionLink(
                route="clarifying_prompt",
                logical_action=NO_ACTION,
                classification="content-only",
            ),
        ),
        source="unit-test",
    )
    assert [link.route for link in doc.links] == [
        "clarifying_prompt",
        "wallet_document_support",
    ]
    assert doc.logical_action_for("wallet_document_support") == (
        "open_wallet_documents"
    )
    assert doc.logical_action_for("missing_route") == NO_ACTION

    with pytest.raises(ActionLinkSchemaError, match="duplicate"):
        ActionLinkDocument(
            links=(
                ActionLink(
                    route="clarifying_prompt",
                    logical_action=NO_ACTION,
                    classification="content-only",
                ),
                ActionLink(
                    route="clarifying_prompt",
                    logical_action=NO_ACTION,
                    classification="content-only",
                ),
            )
        )


def test_document_content_digest_mismatch_fails_closed():
    good = golden_action_link_document()
    payload = good.to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(ActionLinkSchemaError, match="content_digest"):
        parse_action_link_document(payload)

    payload["content_digest"] = good.content_digest()
    again = validate_action_link_document(payload)
    assert again.document_id == good.document_id


def test_golden_vectors_are_deterministic():
    first = golden_action_link_vectors()
    second = golden_action_link_vectors()
    assert first == second

    digests = [content_digest(item) for item in first]
    assert digests == [content_digest(item) for item in second]
    assert len(set(digests)) == len(digests)

    # Key reordering must not change digest.
    for item in first:
        reordered = json.loads(canonical_json(item))
        assert content_digest(reordered) == content_digest(item)
        link = parse_action_link(reordered)
        assert link.link_id == stable_action_link_id(
            route=link.route,
            logical_action=link.logical_action,
            confirmation_frame_id=link.confirmation_frame_id,
            outcome_frame_ids=link.outcome_frame_ids,
        )

    doc_a = golden_action_link_document()
    doc_b = golden_action_link_document()
    assert doc_a.to_dict() == doc_b.to_dict()
    assert doc_a.content_digest() == doc_b.content_digest()
    assert doc_a.document_id == doc_b.document_id

    # Golden set covers route→logical_action, confirmation, and outcomes.
    routes = {item["route"] for item in first}
    assert "app_surface_navigation" in routes
    assert any(item.get("confirmation_frame_id") for item in first)
    assert any(item.get("outcome_frame_ids") for item in first)
    assert any(item["logical_action"] == NO_ACTION for item in first)
    assert any(item["logical_action"] == "handoff_live_agent" for item in first)


def test_link_id_mismatch_fails_closed():
    payload = _proposal_payload(link_id="action-link-deadbeefdeadbeefdeadbeef")
    with pytest.raises(ActionLinkSchemaError, match="link_id"):
        parse_action_link(payload)


def test_classification_and_outcome_constants_are_frozen():
    assert ROUTE_CLASSIFICATIONS == frozenset(
        {"content-only", "proposal-eligible", "safety-overlay"}
    )
    assert OUTCOME_FRAME_KEYS == frozenset(
        {"success", "denied", "failed", "cancelled", "unknown"}
    )
    for name in ("command", "argv", "url", "import", "import_path", "env"):
        assert name in FORBIDDEN_CONTENT_FIELDS


def test_json_round_trip_is_byte_stable():
    doc = golden_action_link_document()
    encoded = canonical_json(doc.to_dict())
    assert encoded == canonical_json(json.loads(encoded))
    restored = parse_action_link_document(json.loads(encoded))
    assert restored.content_digest() == doc.content_digest()
