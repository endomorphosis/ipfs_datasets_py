"""Carry the exact normative scope declaration as an unaccepted bridge view.

The fixed extension name and schema do not impersonate the flat canonical IR.
This adapter checks the complete view's byte/depth limits, including its
wrapper, and establishes no semantic interpretation or projection authority.
"""
from __future__ import annotations

from . import canonical_statement_scope as scope
from .canonical_contracts import BridgeRepresentationKind, BridgeView

VIEW_NAME = "statement_scope_v1"
VALIDATION_SCHEMA = "canonical-normative-scope-bridge-validation/v1"
MAX_VIEW_BYTES = 65536
MAX_VIEW_DEPTH = 20


def _view_wire(view):
    """Use ordinary bounded JSON for the complete serialized bridge view."""
    value = view.to_dict()
    data = scope._raw(value)
    scope._require(len(data) <= MAX_VIEW_BYTES, "scope bridge view exceeds byte limit; no truncation")
    return value, data


def prepare_scope_bridge_view(request, declaration, *, expected_input_sha256):
    """Return a frozen lossless extension view joined to an external input pin."""
    validated = scope.validate_scope_declaration(request, declaration,
                                                 expected_input_sha256=expected_input_sha256)
    view = BridgeView(name=VIEW_NAME, kind=BridgeRepresentationKind.FAMILY_EXTENSION,
                      schema_id=scope.SCHEMA, family_id="deontic", payload=validated["declaration"])
    value, _ = _view_wire(view)
    scope._require(scope._raw(value["payload"]) == scope._raw(declaration),
                   "scope bridge serialization changed the declaration")
    return view


def validate_scope_bridge_view(view, request, *, expected_input_sha256):
    """Validate a serialized or native view; return only diagnostic authority."""
    if type(view) is dict:
        supplied_wire = scope._raw(view)
        view = BridgeView.from_dict(view)
        scope._require(scope._raw(view.to_dict()) == supplied_wire,
                       "serialized scope bridge view differs after reconstruction")
    scope._require(type(view) is BridgeView, "exact BridgeView or closed serialized view required")
    value, data = _view_wire(view)
    scope._require(view.name == VIEW_NAME and view.kind is BridgeRepresentationKind.FAMILY_EXTENSION
                   and view.family_id == "deontic" and view.schema_id == scope.SCHEMA,
                   "scope bridge view name/kind/family/schema differs")
    validated = scope.validate_scope_declaration(request, value["payload"],
                                                 expected_input_sha256=expected_input_sha256)
    # The existing BridgeView rechecks its CID on deserialization. This also
    # confirms ordinary serialization and detached reconstruction are lossless.
    replay = BridgeView.from_dict(value)
    scope._require(scope._raw(replay.to_dict()) == data, "scope bridge view differs after exact replay")
    result = {
        "schema": VALIDATION_SCHEMA, "status": "validated_scope_bridge_transport_only",
        "view_name": VIEW_NAME, "view_kind": BridgeRepresentationKind.FAMILY_EXTENSION.value,
        "family": "deontic", "profile": scope.PROFILE, "declaration_schema": scope.SCHEMA,
        "input_sha256": expected_input_sha256,
        "declaration_content_sha256": validated["declaration_content_sha256"],
        "view_payload_cid": view.payload_cid, "serialized_view_bytes": len(data),
        "view_byte_limit": MAX_VIEW_BYTES, "view_depth_limit": MAX_VIEW_DEPTH,
        "limits_scope": "complete_serialized_view_including_wrapper",
        "declaration_preserved_exactly": True, "truncation_performed": False,
        "coverage_scope": "canonical_deontic_declared_profile_only_not_all_catalog_families",
        "typed_bridge_created": False, "domain_logic_slice_projected": False,
        "context_resolved": False, "verification_status": "pending", "admission_status": "pending",
        "masks": dict.fromkeys(scope.MASKS, 0), "model_calls": 0, "prover_calls": 0,
        "content_sha256_scope": "complete_summary_without_content_sha256", **scope._FALSE,
    }
    result["content_sha256"] = scope._digest(result)
    return result


__all__ = ["prepare_scope_bridge_view", "validate_scope_bridge_view"]
