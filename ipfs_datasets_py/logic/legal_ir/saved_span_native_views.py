"""Alternate native parser views of an unchanged saved deontic proposal.

The authoritative legal route remains ``deontic``. ``tdfol`` and ``dcec`` here
name existing, bounded native parser views, not qualification of registered
temporal/event/cognitive families. Every operation first replays the unchanged
saved-span deontic adapter, then passes its exact request to the existing source
bridge. No temporal facets, qualifiers, source occurrences or declarations are
repaired, dropped or inferred. No model, tensor, compiler or backend is called.

Content digests use compact, sorted, finite UTF-8 JSON with ensure_ascii=False.
They do not authenticate files, checkpoints, model execution or legal meaning.
Callers retain and separately pin the original packet and declaration for replay.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import re

SCHEMA = "saved-span-native-parser-view/v1"
PROFILE = "saved-ground-deontic-native-parser-views/v1"
NATIVE_PARSER_PROFILES = ("tdfol", "dcec")
MAX_INPUT_BYTES = 32 * 1024**2
MAX_OUTPUT_BYTES = 32 * 1024**2
MAX_JSON_DEPTH = 128
_SHA = re.compile(r"[0-9a-f]{64}\Z")
FALSE = dict.fromkeys((
    "qualified", "admitted", "formalized", "proof_authority",
    "source_semantics_verified", "reviewer_authenticated", "semantic_gold",
    "training_masks_emitted", "training_executed", "model_executed",
    "encoder_executed", "Lake_executed", "backend_executed",
    "family_qualified", "registry_family_qualified", "all_logic_families_supported",
    "source_context_custody_verified", "target_access",
    "cross_family_equivalence_verified", "old_calendar_gate_equivalence_verified",
    "checkpoint_authenticated", "model_authenticated", "encoder_authenticated",
), False)
_FIELDS = set(FALSE) | {
    "schema", "profile", "packet_sha256", "declaration_sha256", "binding",
    "sealed_route", "sealed_legal_family", "native_parser_profile",
    "native_profile_scope", "native_report_family_metadata_scope",
    "original_deontic_output", "original_deontic_output_sha256", "request",
    "request_sha256", "native_view", "native_view_sha256", "canonical_ir",
    "canonical_roundtrip_exact", "native_ast_inversion_scope",
    "artifact_consistency_only", "native_parser_view_generated",
    "original_deontic_output_preserved", "native_request_preserved",
    "native_reports_preserved", "full_original_packet_required_for_replay",
    "native_syntax_checked", "lean_source_prepared", "backend_build_required",
    "declaration_scope", "raw_output_repaired", "physical_context_status",
    "producer_pins", "limitations", "output_sha256",
}


class SavedSpanNativeViewError(ValueError):
    """Malformed transport, unsupported native view, or failed exact replay."""


def _require(condition, message):
    if not condition:
        raise SavedSpanNativeViewError(message)


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def _json_shape(value, depth=0):
    _require(depth <= MAX_JSON_DEPTH, "JSON nesting bound exceeded")
    if value is None or type(value) in (str, bool, int, float):
        return
    if type(value) is list:
        for item in value:
            _json_shape(item, depth + 1)
        return
    if type(value) is dict:
        _require(all(type(key) is str for key in value), "JSON object keys must be strings")
        for item in value.values():
            _json_shape(item, depth + 1)
        return
    raise SavedSpanNativeViewError("exact inert JSON types required")


def _wire(value, *, bound=None):
    _json_shape(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise SavedSpanNativeViewError("finite bounded JSON required") from error
    _require(len(raw) <= (MAX_OUTPUT_BYTES if bound is None else bound), "JSON byte bound exceeded")
    return raw


def digest(value):
    """Canonical JSON content SHA256; not a file or authenticated checkpoint SHA."""
    return hashlib.sha256(_wire(value)).hexdigest()


def parse_json_bytes(raw):
    """Detach bounded finite JSON; duplicate keys and non-JSON objects are refused."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_INPUT_BYTES, "bounded JSON bytes required")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise SavedSpanNativeViewError("nonfinite JSON literal: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise SavedSpanNativeViewError("strict finite JSON bytes required") from error
    _wire(value, bound=MAX_INPUT_BYTES)
    return value


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None, label + " SHA256 required")


def _parser_profile(value):
    _require(type(value) is str and value in NATIVE_PARSER_PROFILES,
             "explicit native_parser_profile must be exactly tdfol or dcec; no family aliases")


def _owners():
    # Lazy pure owners. Their called APIs never construct models or run backends.
    return (importlib.import_module("ipfs_datasets_py.logic.legal_ir.saved_span_family_adapter"),
            importlib.import_module("ipfs_datasets_py.logic.autoformal.legal_source_family_bridge"))


def producer_pins():
    """Read producer endpoint hashes; these are not continuous or authenticated custody."""
    adapter, bridge = _owners()
    pins = bridge.producer_pins()
    for path in (Path(adapter.__file__).resolve(), Path(__file__).resolve()):
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(pins)


def prepare_native_view(packet, declaration, *, expected_packet_sha256, native_parser_profile):
    """Prepare one opt-in native view without changing the validated deontic request.

    TDFOL covers the existing ground Boolean/deontic subset. DCEC covers only
    qualifier-free ground O/P/F. Original temporal/null-context refusals apply.
    The original full packet is an external replay input, not truncated here.
    """
    _parser_profile(native_parser_profile)
    _sha(expected_packet_sha256, "expected packet content")
    _wire(packet, bound=MAX_INPUT_BYTES)
    _wire(declaration, bound=MAX_INPUT_BYTES)
    # Snapshot exact JSON before either owner is called. Caller inputs are never
    # handed to an owner, and the returned report has no mutable input aliases.
    packet_copy = json.loads(_wire(packet, bound=MAX_INPUT_BYTES))
    declaration_copy = json.loads(_wire(declaration, bound=MAX_INPUT_BYTES))
    pins = producer_pins()
    adapter, bridge = _owners()
    original = adapter.prepare_family(packet_copy, declaration_copy,
        expected_packet_sha256=expected_packet_sha256, family="deontic")
    _require(original["sealed_route"]["family_id"] == "deontic"
             and original["native_parser_profile"] == "deontic_fol",
             "unchanged sealed deontic output required")
    _require(all(original[key] is False for key in adapter.FALSE),
             "original deontic output authority differs")
    request = deepcopy(original["request"])
    if native_parser_profile == "dcec":
        _require(all(not rule["conditions"] and not rule["exceptions"]
                     for rule in request["candidate"]["canonical_ir"]["rules"]),
                 "DCEC native parser view requires qualifier-free original deontic request")
    native = bridge.prepare_source_family(**deepcopy(request), family=native_parser_profile)
    # Each parser owns its own full AST. DCEC zero-arity Object functions and
    # TDFOL constants are deliberately not compared as cross-parser ASTs.
    for report in (original["native_bridge"], native):
        _require(report["canonical_roundtrip_exact"] is True and report["source_bound"] is True
                 and report["canonical_roundtrip"] == original["canonical_ir"]
                 and report["source_sha256"] == request["candidate"]["source_sha256"]
                 and report["canonical_ir_sha256"] == bridge.digest(original["canonical_ir"])
                 and report["interpretation"] == request["interpretation"]
                 and report["occurrence_bindings"] == request["occurrence_bindings"],
                 "native parser source/canonical/declaration inverse differs")
        _require(all(report[key] is False for key in (
            "source_semantics_verified", "cross_family_equivalence_verified",
            "old_calendar_gate_equivalence_verified", "backend_executed",
            "proof_authority", "admitted", "formalized", "all_logic_families_supported")),
            "native report authority differs")
    _require(native["native_parser_profile"] == native_parser_profile,
             "requested native parser view differs")
    result = dict(schema=SCHEMA, profile=PROFILE, packet_sha256=expected_packet_sha256,
        declaration_sha256=adapter.digest(declaration_copy), binding=deepcopy(original["binding"]),
        sealed_route=deepcopy(original["sealed_route"]), sealed_legal_family="deontic",
        native_parser_profile=native_parser_profile, native_profile_scope=native["native_profile_scope"],
        native_report_family_metadata_scope="bounded native parser profile labels; not registered legal-family qualification",
        original_deontic_output=deepcopy(original), original_deontic_output_sha256=adapter.digest(original),
        request=deepcopy(request), request_sha256=bridge.digest(request), native_view=deepcopy(native),
        native_view_sha256=bridge.digest(native), canonical_ir=deepcopy(original["canonical_ir"]),
        canonical_roundtrip_exact=True,
        native_ast_inversion_scope="each parser independently: exact full AST roundtrip and original modal/action/argument spine plus ordered qualifier ledger",
        artifact_consistency_only=True, native_parser_view_generated=True,
        original_deontic_output_preserved=True, native_request_preserved=True, native_reports_preserved=True,
        full_original_packet_required_for_replay=True, native_syntax_checked=True, lean_source_prepared=True,
        backend_build_required="lake build legal", declaration_scope=original["declaration_scope"],
        raw_output_repaired=False, physical_context_status=original["physical_context_status"],
        producer_pins=pins,
        limitations=[
            "The sealed legal family remains deontic; native parser labels do not qualify registered TDFOL or DCEC/event-calculus families.",
            "Each native report is preserved unchanged; its family strings describe only the bounded native parser view.",
            "No cross-parser AST equality or cross-family interpretation equivalence is asserted.",
            "Source and saved-report consistency do not authenticate checkpoint bytes, model execution, reviews or legal meaning.",
            "Cue intervals and qualifier expressions remain explicit caller declarations, not semantic gold.",
            "TDFOL has no temporal operators or quantifiers here; DCEC has no qualifiers, cognitive operators, events or fluents.",
            "No clock, agent, modal context, event origin, owner or legal qualifier interpretation is inferred.",
            "The original full pending packet and declaration are required for replay and must be independently retained and pinned.",
            "Lean source preparation requires a separate actual lake build legal; this API executes no compiler or backend.",
            "Producer pins compare source endpoints during this operation; they do not establish continuous or authenticated custody.",
        ], **FALSE)
    result["output_sha256"] = digest(result)
    _closed(result, _FIELDS, "native parser view output")
    _require(producer_pins() == pins, "native parser view producer changed during preparation")
    return json.loads(_wire(result))


def validate_native_view(output, packet, declaration, *, expected_packet_sha256, native_parser_profile):
    """Regenerate every field from original inputs; repairing a seal confers no authority."""
    _wire(output)
    _closed(output, _FIELDS, "native parser view output")
    _sha(output["output_sha256"], "native view output content")
    body = {key: value for key, value in output.items() if key != "output_sha256"}
    _require(digest(body) == output["output_sha256"], "native parser view output content seal differs")
    expected = prepare_native_view(packet, declaration, expected_packet_sha256=expected_packet_sha256,
                                   native_parser_profile=native_parser_profile)
    _require(_wire(output) == _wire(expected), "native parser view authoritative replay differs")
    return True


__all__ = ["prepare_native_view", "validate_native_view", "producer_pins", "digest",
           "parse_json_bytes", "SavedSpanNativeViewError", "SCHEMA", "PROFILE",
           "NATIVE_PARSER_PROFILES", "FALSE"]
