"""Versioned UI structural readout with complete interface-binding records.

This additive head leaves native_formal_decoder v1 and the legal 8D/384D
lineages unchanged. It reads learned reconstruction scores, not original target
values. Original targets enter only the separate typed fidelity measurement.
It does not implement a text/React-to-UI decoder or verify a predicted CID's
preimage; the projected records do not contain that complete preimage.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import native_formal_decoder as base
from . import autoencoder_projection_features as features
from ...logic.formalization.autoencoder import ui_training_inputs as inputs
from ...logic.ui_ux_ir.model import bindings
from ...logic.ui_ux_ir.runtime import idl_projection
from ...logic.ui_ux_ir.source_adapters import mcp_idl_identity as identity

VERSION = "ui_native_bindings_v2"
HEAD_SCHEMA = "ui-native-formal-decoder/v2"
RESULT_SCHEMA = "ui-native-formal-decoding/v2"
FIDELITY_SCHEMA = "ui-compiler-target-decoder-fidelity/v1"
_require = base._require
_plain = base._plain
_PINS = {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
         for module in (base, features, inputs, bindings, idl_projection, identity)}
_PINS[__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_DESCRIPTOR = {"logic_family": "frame_logic", "profile": "ui-verified-interface-bindings/v1",
    "properties": [], "view_role": "interface_method_contracts",
    "representation_kind": "native_verified_binding_records", "producer_id": "ui-bound-training-inputs/v1"}


def _guard():
    import sys
    for name, digest in _PINS.items():
        module = sys.modules[name]
        _require(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == digest,
                 "UI decoder producer changed after import")


def validate_interface_expression(descriptor, expression):
    """Reuse the local input, binding, identity and inline-schema owners.

    Syntax of a CID is checked. Full descriptor identity, DOM affordance
    membership and observed runtime effects are explicitly unknown here.
    """
    _guard()
    _require(descriptor == _DESCRIPTOR, "UI interface projection descriptor differs")
    inputs._wire(expression)
    inputs._object(expression, {"identity_profile", "interface_cid", "bindings"},
        {"identity_profile", "interface_cid", "bindings"}, "predicted interface expression")
    _require(expression["identity_profile"] == identity.INTERFACE_IDENTITY_PROFILE,
             "predicted interface identity profile differs")
    cid = expression["interface_cid"]
    _require(identity.is_verified_interface_cid_string(cid), "predicted interface CID syntax is invalid")
    rows = inputs._array(expression["bindings"], inputs.MAX_BINDINGS, "predicted bindings", nonempty=True)
    fields = {"binding_id", "action_id", "component_id", "dom_action", "method_name", "risk_class",
              "confirmation_class", "idempotency", "interface_cid", "method_contract"}
    ids, actions, joins, methods = set(), set(), set(), {}
    for row in rows:
        inputs._object(row, fields, fields, "predicted binding")
        for name in ("binding_id", "action_id", "component_id", "dom_action", "method_name"):
            inputs._text(row[name], "predicted binding." + name, identifier=True)
        _require(row["interface_cid"] == cid, "predicted binding interface CID differs from envelope")
        key = (row["component_id"], row["dom_action"])
        _require(row["binding_id"] not in ids and row["action_id"] not in actions and key not in joins,
                 "duplicate or ambiguous predicted binding/action/component join")
        ids.add(row["binding_id"]); actions.add(row["action_id"]); joins.add(key)
        method = inputs._object(row["method_contract"], set(identity.METHOD_IDENTITY_AFFECTING_FIELDS),
            {"name", "input_schema", "output_schema"}, "predicted method contract")
        _require(method["name"] == row["method_name"], "predicted method name differs from binding")
        if "streaming" in method:
            inputs._boolean(method["streaming"], "predicted method.streaming")
            _require(not method["streaming"], "streaming requires a separate typed training profile")
        for name in ("input_schema", "output_schema"):
            schema = method[name]
            _require(type(schema) is dict and type(schema.get("type")) is str
                     and schema["type"] in {"object", "array", "string", "number", "integer", "boolean", "null"},
                     "predicted method schema requires explicit supported JSON type")
            idl_projection._schema_validator(schema)
        _require(method["input_schema"]["type"] == "object", "predicted method input must be an object")
        if method["name"] in methods:
            _require(inputs._wire(methods[method["name"]]) == inputs._wire(method),
                     "predicted contracts for the same method disagree")
        methods[method["name"]] = method
        reference = bindings.UIProgramRef(target_kind=bindings.ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid=cid, mcp_idl_method_name=row["method_name"])
        bindings.validate_action_binding(bindings.UIActionBinding(binding_id=row["binding_id"],
            action_id=row["action_id"], program_ref=reference, risk_class=bindings.RiskClass(row["risk_class"]),
            confirmation_class=bindings.ConfirmationClass(row["confirmation_class"]),
            idempotency=bindings.IdempotencyClass(row["idempotency"])))
    return {"validator": "ui-local-interface-binding-record/v2", "typed_expression": None,
        "readable_notation": inputs._wire(expression).decode(),
        "notation_kind": "complete_native_binding_record_not_backend_formula",
        "validation_scope": "closed_binding_fields_local_inline_schema_and_identity_string_syntax",
        "interface_preimage_status": "unknown_missing_complete_descriptor",
        "dom_affordance_membership_status": "unknown_without_source_dom",
        "runtime_authenticity_status": "unknown_without_observation"}


def train_ui_formal_decoder(space, training_targets):
    """Fit training-only fixed shapes over the original learned feature basis."""
    _guard()
    _require(space["domain_id"] == "ui_ux_ir", "UI modality required")
    head = {"schema": HEAD_SCHEMA, "version": VERSION, "producer_pins": dict(_PINS),
        "base_head": base.train_formal_decoder(space, training_targets),
        "independent_text_to_logic": False, "new_neural_decoder_trained": False}
    validate_ui_decoder(space, head)
    return head


def validate_ui_decoder(space, head):
    _guard()
    _require(type(head) is dict and set(head) == {"schema", "version", "producer_pins", "base_head",
        "independent_text_to_logic", "new_neural_decoder_trained"}, "closed versioned UI decoder required")
    _require(head["schema"] == HEAD_SCHEMA and head["version"] == VERSION and head["producer_pins"] == _PINS,
             "UI decoder version or producers differ")
    _require(head["independent_text_to_logic"] is False and head["new_neural_decoder_trained"] is False,
             "UI structural head cannot claim neural source decoding")
    _require(space["domain_id"] == "ui_ux_ir", "UI modality required")
    base.validate_decoder(space, head["base_head"])
    return features.digest(head)


def decode_ui_formal_features(space, head, inference_result):
    """Decode every selected projection without access to expected targets."""
    head_sha = validate_ui_decoder(space, head)
    result = base.decode_formal_features(space, head["base_head"], inference_result)
    name = inputs.INTERFACE_PROJECTION
    if name in space["projection_ids"]:
        basis, _ = base._basis(space)
        record = head["base_head"]["projections"][name]
        for row, prediction in zip(result["rows"], inference_result["rows"]):
            selected = next(item for item in row["projections"] if item["projection_id"] == name)
            # All score/vector/shape refusal behavior belongs to the unchanged
            # base owner. Only its missing interface validator is extended.
            if selected["reason"] != "decoded_native_validation_failed":
                continue
            vector = prediction["reconstructed_projection_features"][name]
            leaves = {path: max(((vector[index], -index, value) for index, value in candidates),
                                key=lambda item: (item[0], item[1]))[2]
                      for path, candidates in basis[name].items()}
            expression = base._rebuild(record["shape"], leaves)
            try:
                validation = validate_interface_expression(space["projections"][name], expression)
            except (ValueError, TypeError, KeyError) as exc:
                selected["validation_error"] = str(exc)[:1000]
            else:
                selected.update(validation, status="decoded_candidate", reason=None, expression=expression)
                selected.pop("validation_error", None)
    decoded = sum(p["status"] == "decoded_candidate" for row in result["rows"] for p in row["projections"])
    total = sum(len(row["projections"]) for row in result["rows"])
    result.update(schema=RESULT_SCHEMA, decoder_sha256=head_sha, base_decoder_sha256=features.digest(head["base_head"]),
        decoder_version=VERSION, decoded_projection_count=decoded, abstained_projection_count=total-decoded,
        status="decoded" if total == decoded else "partial" if decoded else "abstained",
        # Every route in this version produces a locally validated native
        # record. Readable notation is not an executable backend formula.
        decoded_native_record_count=decoded, decoded_backend_formula_count=0,
        decoded_formulas_generated=False)
    _guard()
    return result


def typed_fidelity(expected, actual):
    """Compare all JSON fields, scalar types, array lengths and array order.

    This is compiler-target equality, not natural-language entailment. Missing
    values never disappear from the denominator; differences are diagnostic.
    """
    inputs._wire(expected); inputs._wire(actual)
    differences = []
    count = 0

    def compare(left, right, path):
        nonlocal count
        count += 1
        if type(left) is not type(right):
            differences.append({"path": path, "kind": "type_or_missing_value"})
        elif type(left) is dict:
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    count += 1
                    differences.append({"path": [*path, key], "kind": "missing_or_extra_field"})
                else:
                    compare(left[key], right[key], [*path, key])
        elif type(left) is list:
            if len(left) != len(right):
                differences.append({"path": path, "kind": "array_length"})
            for index in range(max(len(left), len(right))):
                if index >= len(left) or index >= len(right):
                    count += 1
                    differences.append({"path": [*path, index], "kind": "missing_or_extra_element"})
                else:
                    compare(left[index], right[index], [*path, index])
        elif left != right:
            differences.append({"path": path, "kind": "value"})
    compare(expected, actual, [])
    return {"exact": not differences, "compared_nodes": count, "difference_count": len(differences),
        "differences": differences[:256], "differences_truncated": len(differences) > 256,
        "expected_sha256": features.digest(expected), "actual_sha256": features.digest(actual)}


def evaluate_ui_decoded_fidelity(space, head, inference_result, original_targets):
    """Replay score-only decoding before inspecting separate expected targets."""
    decoded = decode_ui_formal_features(space, head, inference_result)
    targets = [features._target(target) for target in original_targets]
    _require(len(targets) == len(decoded["rows"]), "decoder/target row count differs")
    _, sources, descriptors = features._rows(targets, "ui_ux_ir", space["projection_ids"])
    _require(descriptors == space["projections"], "fidelity target projection descriptors differ")
    _require(sources == [row["source_digest"] for row in decoded["rows"]], "fidelity target source order differs")
    rows = []
    for row, target in zip(decoded["rows"], targets):
        expected = {p["projection_id"]: p["expression"] for p in target["projections"]}
        for projection in row["projections"]:
            comparison = typed_fidelity(expected[projection["projection_id"]], projection["expression"])
            rows.append({"source_digest": row["source_digest"], "projection_id": projection["projection_id"],
                "decode_status": projection["status"], "abstention_reason": projection["reason"], **comparison})
    total, exact = len(rows), sum(row["exact"] for row in rows)
    return {"schema": FIDELITY_SCHEMA, "decoder_sha256": decoded["decoder_sha256"],
        "feature_space_sha256": decoded["feature_space_sha256"], "state_sha256": decoded["state_sha256"],
        "projection_count": total, "exact_projection_count": exact, "exact_projection_fraction": exact / total,
        "abstained_projection_count": decoded["abstained_projection_count"], "rows": rows,
        "coverage": decoded["coverage"], "scope": "exact_all_selected_compiler_target_fields_not_source_text_fidelity",
        "source_semantics_verified": False, "qualified": False, "admitted": False,
        "training_executed": False, "independent_text_to_logic": False}


__all__ = ["VERSION", "HEAD_SCHEMA", "RESULT_SCHEMA", "FIDELITY_SCHEMA", "train_ui_formal_decoder",
    "validate_ui_decoder", "decode_ui_formal_features", "evaluate_ui_decoded_fidelity", "typed_fidelity"]
