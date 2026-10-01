"""Closed routes for four native supplemental model interpretations.

The enclosing gate must first replay the full native report and typed source
inputs. These emitters expose supported declarations, not source translations
or a replacement for a live projection training/admission policy.
"""
from . import native_authorization_lean as authorization
from . import native_concurrency_lean as concurrency
from . import native_protocol_lean as protocol
from . import native_refinement_lean as refinement
from .native_family_lean_emitters import require

PRODUCERS = (authorization, concurrency, protocol, refinement)
ROUTES = {
    "authorization": ("authorization", "datalog", "authorization-ir/v1", authorization.emit_authorization),
    "concurrency": ("concurrency", "rely_guarantee", "concurrency-ir/v1", concurrency.emit_concurrency),
    "protocol": ("cryptographic_protocol", "dolev_yao", "protocol-ir/v1", protocol.emit_protocol),
    "refinement": ("refinement", "simulation", "refinement-ir/v1", refinement.emit_refinement),
}


def recognizes(row, domain):
    kinds = {"authorization"} if domain in ("intent_ir", "legal_ir", "ui_ux_ir") else set(ROUTES) if domain == "security_ir" else set()
    return any(row.get("projection_id") == domain + "/supplemental/" + kind + "/v2" for kind in kinds)


def emit_projection(row, *, domain):
    require(recognizes(row, domain), "known_native_supplemental_projection_required")
    kind = row["projection_id"].split("/")[2]
    family, profile, schema, emit = ROUTES[kind]
    require(row.get("logic_family") == family and row.get("profile") == profile,
            "native_supplemental_family_or_profile_differs")
    payload = row.get("payload")
    require(type(payload) is dict and set(payload) == {"bridge", "native_document", "typed_expression"},
            "exact_native_supplemental_bridge_envelope_required")
    document = payload["native_document"]
    require(type(document) is dict and document.get("schema_version") == schema,
            "native_supplemental_document_schema_differs")
    # The native owner regenerates bridge/expression identities in the enclosing
    # source replay. No unvalidated renderer or class name is loaded from input.
    source, details = emit(document)
    details.update(supplemental_kind=kind, native_family=family,
                   source_meaning_inferred=False, native_document_rewritten=False)
    return source, details


__all__ = ["PRODUCERS", "recognizes", "emit_projection"]
