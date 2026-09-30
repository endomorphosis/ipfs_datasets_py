"""A bounded inverse of native v1 projection features, driven by model scores.

The fitted readout stores training tree shapes (including empty containers),
not target expressions or a table of target answers. Scalar candidates are
already in the autoencoder's exact path/value vocabulary. Every decoded leaf
must be selected by positive, unambiguous reconstructed scores. This is a
deterministic structural readout over learned features, not a newly pretrained
sequence decoder or an independent text-to-logic model.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from . import autoencoder_projection_features as features


HEAD_SCHEMA = "native-projection-formula-decoder/v1"
RESULT_SCHEMA = "native-projection-formula-decoding/v1"
MAX_HEAD_BYTES = 8 * 1024 * 1024
MINIMUM_SCORE = 1e-8
MINIMUM_MARGIN = 1e-8
_FALSE = {**features.FALSE, "source_semantics_verified": False, "source_binding_verified": False,
          "proof_authority": False, "execution_authority": False, "lake_executed": False}
_DESCRIPTOR_KEYS = {"logic_family", "profile", "properties", "view_role", "representation_kind", "producer_id"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class FormulaDecoderError(ValueError):
    """Malformed or mismatched decoder/feature-space identity."""


def _require(condition, message):
    if not condition:
        raise FormulaDecoderError(message)


def _plain(value):
    return json.loads(features._raw(value))


def _implementation_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _validator_sources(domain, *, space_schema):
    root = Path(features.__file__).resolve().parents[2]
    names = ["optimizers/logic_theorem_optimizer/autoencoder_projection_features.py",
             "optimizers/logic_theorem_optimizer/autoencoder_modality_contracts.py",
             "logic/formalization/autoencoder/domain_targets.py"]
    if space_schema == "native-projection-feature-space/v2":
        names.append("optimizers/logic_theorem_optimizer/autoencoder_projection_features_v2.py")
    if domain == "intent_ir":
        names += ["logic/intent_ir/decoder.py", "logic/intent_ir/schema.py",
                  "logic/intent_ir/formalize/typed_compiler.py", "logic/intent_ir/formalize/compiler.py"]
    elif domain == "ui_ux_ir":
        names += ["logic/ui_ux_ir/formalize/" + name + ".py"
                  for name in ("flogic", "event_calculus", "tdfol", "dcec")]
    else:
        names += ["logic/security_ir/code_logic_projection.py"]
        names += ["logic/software_verification/" + name + ".py" for name in
                  ("program", "contracts", "transitions", "temporal", "heap", "separation", "hyperproperties", "syntax_bridge")]
        names += ["logic/syntax_core/" + name + ".py" for name in ("ast", "contracts", "signatures")]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def decoder_digest(head):
    return features.digest(head)


def _shape(value, path=(), depth=0):
    _require(depth <= 32, "native decoder tree depth exceeded")
    if type(value) is dict:
        return {"kind": "object", "children": [[key, _shape(child, path + (key,), depth + 1)]
                                               for key, child in sorted(value.items())]}
    if type(value) is list:
        return {"kind": "array", "children": [_shape(child, path + (index,), depth + 1)
                                               for index, child in enumerate(value)]}
    return {"kind": "leaf", "path": list(path)}


def _shape_paths(shape, path=(), depth=0):
    _require(type(shape) is dict and depth <= 32, "malformed bounded decoder shape")
    if shape.get("kind") == "leaf":
        _require(set(shape) == {"kind", "path"} and shape["path"] == list(path), "decoder leaf path mismatch")
        yield path
    elif shape.get("kind") == "object":
        _require(set(shape) == {"kind", "children"} and type(shape["children"]) is list,
                 "malformed decoder object shape")
        keys = []
        for item in shape["children"]:
            _require(type(item) is list and len(item) == 2 and type(item[0]) is str, "malformed object child")
            keys.append(item[0])
            yield from _shape_paths(item[1], path + (item[0],), depth + 1)
        _require(keys == sorted(set(keys)), "decoder object keys are not canonical")
    else:
        _require(shape.get("kind") == "array" and set(shape) == {"kind", "children"}
                 and type(shape["children"]) is list, "malformed decoder array shape")
        for index, child in enumerate(shape["children"]):
            yield from _shape_paths(child, path + (index,), depth + 1)


def _basis(space):
    _require(type(space) is dict and space.get("schema") in (features.SPACE_SCHEMA, "native-projection-feature-space/v2"),
             "formula decoder requires an explicit native feature space version")
    if space["schema"].endswith("/v2"):
        from . import autoencoder_projection_features_v2 as streamed
        streamed._validate_space(space)
    _require(space.get("domain_id") in {"security_ir", "intent_ir", "ui_ux_ir"}, "unsupported native domain")
    ids = space.get("projection_ids")
    _require(type(ids) is list and ids and ids == sorted(set(ids)), "canonical projection IDs required")
    _require(type(space.get("projections")) is dict and set(space["projections"]) == set(ids),
             "projection descriptor coverage differs")
    _require(space.get("normalization") == "log1p_then_l2_per_projection"
             and all(space.get(key) is False for key in features.FALSE), "feature policy or authority differs")
    columns = space.get("columns")
    _require(type(columns) is list and 1 <= len(columns) <= features.MAX_FEATURES,
             "bounded native columns required")
    result = {name: defaultdict(list) for name in ids}
    offsets = {name: 0 for name in ids}
    canonical = []
    for column in columns:
        _require(type(column) is list and len(column) == 2 and column[0] in result
                 and type(column[1]) is str, "malformed projection feature column")
        name, token = column
        parsed = json.loads(token)
        _require(type(parsed) is list and len(parsed) == 2 and type(parsed[0]) is list,
                 "feature token is not a path/value pair")
        path, value = parsed
        _require(path and len(path) <= 32 and all(type(key) is str or type(key) is int and key >= 0 for key in path),
                 "invalid feature token path")
        _require(value is None or type(value) in (str, bool, int, float), "feature token is not a scalar")
        _require(type(value) is not float or math.isfinite(value), "nonfinite feature atom")
        _require(features._raw(parsed).decode() == token, "feature token is not canonical")
        result[name][tuple(path)].append((offsets[name], value))
        offsets[name] += 1
        canonical.append((name, token))
    _require(canonical == sorted(set(canonical)), "feature columns must be canonical and unique")
    for name, descriptor in space["projections"].items():
        _require(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_KEYS,
                 "closed projection descriptor required")
        features._native_projection_spec(name, descriptor)
        _require(result[name], "projection has no feature leaves")
    return result, offsets


def train_formal_decoder(space, training_targets):
    """Fit training-only shape metadata; this fits zero new neural parameters.

    Mixed shapes need a learned presence/length head and are explicitly
    unsupported. No validation or inference targets may be used to fit shapes.
    """
    space = _plain(space)
    basis, _ = _basis(space)
    v2 = space["schema"].endswith("/v2")
    maximum = 32768 if v2 else 1024
    source_ids, shapes, mixed = set(), {}, set()
    target_digest = hashlib.sha256()
    if not v2:
        target_digest.update(b"[")
    for count, target in enumerate(training_targets, 1):
        _require(count <= maximum, "decoder training target bound exceeded")
        row = features._target(target)
        _, sources, descriptors = features._rows([row], space["domain_id"], space["projection_ids"])
        _require(descriptors == space["projections"] and sources[0] not in source_ids,
                 "decoder training source or projection identity differs")
        source_ids.add(sources[0])
        if not v2 and count > 1:
            target_digest.update(b",")
        target_digest.update(features._raw(row))
        if v2:
            target_digest.update(b"\n")
        for projection in row["projections"]:
            name = projection["projection_id"]
            if name not in basis or name in mixed:
                continue
            shape = _shape(projection["expression"])
            if name in shapes and shape != shapes[name]:
                mixed.add(name)
            else:
                shapes[name] = shape
    if not v2:
        target_digest.update(b"]")
    _require(source_ids and sorted(source_ids) == space["training_sources"], "decoder training sources differ from fitted basis")
    _require(target_digest.hexdigest() == space["training_targets_sha256"], "decoder training targets differ from fitted basis")
    projections = {}
    for name in space["projection_ids"]:
        if name in mixed:
            projections[name] = {"status": "unsupported", "reason": "variable_shape_requires_presence_head", "shape": None}
        else:
            shape = shapes[name]
            _require(set(_shape_paths(shape)) == set(basis[name]), "shape leaf paths differ from training vocabulary")
            projections[name] = {"status": "ready", "reason": None, "shape": shape}
    head = {"schema": HEAD_SCHEMA, "domain_id": space["domain_id"],
            "feature_space_sha256": features.digest(space), "implementation_sha256": _implementation_sha(),
            "validator_sources": _validator_sources(space["domain_id"], space_schema=space["schema"]),
            "training_targets_sha256": space["training_targets_sha256"], "training_source_count": len(source_ids),
            "fit_method": "training_fixed_shape_and_existing_path_value_vocabulary",
            "trainable_parameter_count": 0, "new_neural_decoder_trained": False,
            "score_policy": {"minimum_score": MINIMUM_SCORE, "minimum_margin": MINIMUM_MARGIN},
            "projections": projections, **_FALSE}
    validate_decoder(space, head)
    return head


def validate_decoder(space, head):
    """Validate bounded JSON metadata against an exact feature basis and source."""
    basis, _ = _basis(space)
    _require(type(head) is dict and len(features._raw(head)) <= MAX_HEAD_BYTES, "bounded decoder mapping required")
    expected = {"schema", "domain_id", "feature_space_sha256", "implementation_sha256", "validator_sources", "training_targets_sha256",
                "training_source_count", "fit_method", "trainable_parameter_count", "new_neural_decoder_trained",
                "score_policy", "projections", *_FALSE}
    _require(set(head) == expected and head["schema"] == HEAD_SCHEMA, "closed decoder head schema required")
    _require(head["domain_id"] == space["domain_id"] and head["feature_space_sha256"] == features.digest(space),
             "decoder belongs to a different feature space")
    _require(head["implementation_sha256"] == _implementation_sha(), "decoder implementation changed")
    _require(head["validator_sources"] == _validator_sources(space["domain_id"], space_schema=space["schema"]),
             "listed native validator sources changed")
    _require(head["training_targets_sha256"] == space["training_targets_sha256"]
             and type(head["training_source_count"]) is int
             and head["training_source_count"] == len(space["training_sources"]), "decoder training provenance differs")
    _require(head["fit_method"] == "training_fixed_shape_and_existing_path_value_vocabulary"
             and type(head["trainable_parameter_count"]) is int and head["trainable_parameter_count"] == 0
             and head["new_neural_decoder_trained"] is False, "decoder fit method differs")
    _require(head["score_policy"] == {"minimum_score": MINIMUM_SCORE, "minimum_margin": MINIMUM_MARGIN}
             and all(head[key] is False for key in _FALSE), "decoder score policy or authority differs")
    _require(type(head["projections"]) is dict and set(head["projections"]) == set(basis), "decoder projection coverage differs")
    for name, record in head["projections"].items():
        _require(type(record) is dict and set(record) == {"status", "reason", "shape"}, "closed decoder projection required")
        if record["status"] == "ready":
            _require(record["reason"] is None and set(_shape_paths(record["shape"])) == set(basis[name]),
                     "decoder shape paths differ from vocabulary")
        else:
            _require(record == {"status": "unsupported", "reason": "variable_shape_requires_presence_head", "shape": None},
                     "invalid unsupported decoder projection")
    return decoder_digest(head)


def _rebuild(shape, leaves):
    if shape["kind"] == "leaf":
        return leaves[tuple(shape["path"])]
    if shape["kind"] == "object":
        return {key: _rebuild(child, leaves) for key, child in shape["children"]}
    return [_rebuild(child, leaves) for child in shape["children"]]


def _text(value):
    _require(type(value) is str and bool(value), "nonempty native string required")
    return value


def _strings(value):
    _require(type(value) is list and all(type(item) is str for item in value), "native string list required")
    return value


def _closed(value, keys):
    _require(type(value) is dict and set(value) == set(keys), "native formula fields differ")


def _quoted(value):
    return json.dumps(_text(value), ensure_ascii=False)


def _atom(predicate, arguments):
    _text(predicate)
    name = predicate if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", predicate) else "predicate[" + _quoted(predicate) + "]"
    return name + "(" + ", ".join(_quoted(value) for value in _strings(arguments)) + ")"


def _ui_expression(name, expression):
    field = "facts" if name == "ui_ux_ir:flogic" else "formulas"
    _closed(expression, {field})
    rows = expression[field]
    _require(type(rows) is list and rows, "nonempty UI formula list required")
    text = []
    for row in rows:
        if name == "ui_ux_ir:flogic":
            _closed(row, {"predicate", "args", "source_ref_ids"})
            text.append(_atom(row["predicate"], row["args"]) + ".")
        elif name == "ui_ux_ir:event_calculus":
            _closed(row, {"kind", "args", "source_ref_ids"})
            _require(row["kind"] in {"fluent", "initiates", "terminates", "holds_at", "happens"}, "unknown UI event-calculus kind")
            _require(len(_strings(row["args"])) >= 1, "event record lacks arguments")
            text.append(_atom(row["kind"], row["args"]))
        elif name == "ui_ux_ir:tdfol":
            _closed(row, {"operator", "proposition", "strength", "source_ref_ids"})
            _require(row["operator"] in {"obligation", "permission", "prohibition"}
                     and row["strength"] in {"strict", "weak"}, "unknown UI deontic operator or strength")
            text.append(row["operator"] + "(proposition=" + _quoted(row["proposition"]) + ", strength=" + _quoted(row["strength"]) + ")")
        elif name == "ui_ux_ir:dcec":
            _closed(row, {"kind", "actor", "content", "source_ref_ids"})
            _require(row["kind"] in {"knows", "believes", "intends", "observes", "delegates"}, "unknown UI cognitive operator")
            text.append(row["kind"] + "(" + _quoted(row["actor"]) + ", content=" + _quoted(row["content"]) + ")")
        else:
            raise FormulaDecoderError("unsupported UI projection")
        _strings(row["source_ref_ids"])
    return {"validator": "native-ui-record-shape/v1", "typed_expression": None,
            "readable_notation": "\n".join(text), "notation_kind": "native_ui_record_not_backend_formula",
            "validation_scope": "native_record_fields_and_closed_operators"}


def _intent_body(body):
    from ...logic.intent_ir.schema import IntentModality, StatementKind, NodeGrounding, ReviewStatus, _IDENTIFIER_RE
    _closed(body, {"arguments", "confidence", "grounding", "modality", "predicate", "review_status", "statement_kind", "text"})
    _text(body["text"])
    _require(type(body["predicate"]) is str and _IDENTIFIER_RE.fullmatch(body["predicate"]),
             "Intent predicate must be a stable identifier")
    _strings(body["arguments"])
    _require(type(body["confidence"]) in (int, float) and math.isfinite(body["confidence"])
             and 0 <= body["confidence"] <= 1, "invalid predicted statement confidence")
    IntentModality(body["modality"]); StatementKind(body["statement_kind"])
    NodeGrounding(body["grounding"]); ReviewStatus(body["review_status"])
    return _atom(body["predicate"], body["arguments"])


def _intent_expression(name, expression):
    from ...logic.intent_ir.decoder import _decode_action, _decode_statement, _decode_edge
    _require(type(expression) is list and expression, "nonempty Intent formula list required")
    text = []
    for row in expression:
        kind = row.get("kind") if type(row) is dict else None
        if name == "intent-route/facts/v1" and kind == "typed_fact":
            _closed(row, {"kind", "arguments", "confidence", "grounding", "modality", "predicate", "review_status", "statement_kind", "text"})
            text.append(_intent_body({key: value for key, value in row.items() if key != "kind"}))
        elif name == "intent-route/facts/v1" and kind == "typed_action_fact":
            _closed(row, {"kind", "action"})
            _decode_action(row["action"], "action").validate()
            text.append("action(" + _quoted(row["action"]["action_id"]) + ", " + _quoted(row["action"]["verb"]) + ")")
        elif name in {"intent-route/intentions/v1", "intent-route/norms/v1"}:
            _closed(row, {"kind", "body", "operator"})
            _require(kind == "intention_deontic_formula", "wrong Intent modal kind")
            body = _intent_body(row["body"])
            expected = row["body"]["modality"]
            if row["body"]["statement_kind"] == "goal" and expected == "asserted":
                expected = "intended"
            _require(row["operator"] == expected, "predicted operator disagrees with body modality")
            _require((row["operator"] == "intended") == (name == "intent-route/intentions/v1"), "Intent operator belongs to another family")
            text.append(row["operator"] + "(" + body + ")")
        elif name in {"intent-route/safety/v1", "intent-route/liveness/v1"}:
            _closed(row, {"kind", "body", "operator"})
            expected = ("safety_invariant", "always") if name.endswith("safety/v1") else ("failure_condition", "avoid")
            _require((kind, row["operator"]) == expected, "wrong Intent temporal operator")
            text.append(row["operator"] + "(" + _intent_body(row["body"]) + ")")
        elif name == "intent-route/action-hoare/v1":
            _closed(row, {"kind", "action", "precondition", "postcondition", "effects", "verification"})
            _require(kind == "hoare_action_contract", "wrong Intent action kind")
            _decode_action(row["action"], "action").validate()
            for field in ("precondition", "postcondition", "effects", "verification"):
                _require(type(row[field]) is list, "Intent condition list required")
                for item in row[field]:
                    _decode_statement(item, field).validate()
            _require(row["postcondition"] == row["effects"], "predicted postcondition differs from effects")
            def conditions(items):
                return " and ".join(_atom(item["predicate"], item["arguments"]) for item in items) or "true"
            action = row["action"]
            text.append("{" + conditions(row["precondition"]) + "} "
                        + _atom(action["verb"], [action["actor"], *action["object_refs"]])
                        + " {" + conditions(row["postcondition"]) + "}; verification["
                        + conditions(row["verification"]) + "]")
        elif name == "intent-route/workflow-temporal/v1" and kind == "workflow_boundary":
            _closed(row, {"kind", "entry_action_ids", "terminal_action_ids"})
            _strings(row["entry_action_ids"]); _strings(row["terminal_action_ids"])
            text.append("workflow_boundary(entry=" + json.dumps(row["entry_action_ids"]) + ", terminal=" + json.dumps(row["terminal_action_ids"]) + ")")
        elif name == "intent-route/workflow-temporal/v1" and kind == "workflow_temporal_transition":
            _closed(row, {"kind", "edge", "guard", "operator"})
            edge = _decode_edge(row["edge"], "edge"); edge.validate()
            _require(row["operator"] == row["edge"]["kind"], "predicted transition operator differs from edge")
            if row["guard"] is not None:
                _decode_statement(row["guard"], "guard").validate()
            text.append(row["operator"] + "(" + _quoted(row["edge"]["source_action_id"]) + ", " + _quoted(row["edge"]["target_action_id"]) + ")")
        else:
            raise FormulaDecoderError("unsupported Intent projection or record kind")
    return {"validator": "native-intent-record-shape/v1", "typed_expression": None,
            "readable_notation": "\n".join(text), "notation_kind": "native_intent_record_not_backend_formula",
            "validation_scope": "native_record_fields_and_operators_not_source_entailment"}


def _security_expression(name, descriptor, expression):
    from ...logic.security_ir import code_logic_projection as native
    from ...logic.software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge
    bridge = SoftwareVerificationSyntaxBridge()
    kinds = [kind for kind in native.SUPPORTED_KINDS if bridge.route_for(kind).payload_schema == name]
    _require(len(kinds) == 1, "unsupported Security projection")
    kind = kinds[0]
    route = bridge.route_for(kind)
    _require(route.family_id == descriptor["logic_family"] and (route.profile_id or None) == descriptor["profile"],
             "Security family/profile differs from native route")
    published = bridge.publish(expression, kind=kind)
    consumed = bridge.consume(published.expression, kind=kind)
    _require(published.exact and consumed.exact and consumed.document.to_dict() == expression,
             "predicted native document fails exact typed replay")
    return {"validator": bridge.INTERFACE, "typed_expression": published.expression.to_dict(),
            "readable_notation": None, "notation_kind": None,
            "validation_scope": "native_typed_document_and_exact_syntax_extension_replay"}


def _validate_expression(domain, name, descriptor, expression):
    if domain == "security_ir":
        return _security_expression(name, descriptor, expression)
    if domain == "intent_ir":
        from ...logic.intent_ir.formalize.typed_compiler import resolve_intent_route
        labels = {"intent-route/facts/v1": "facts", "intent-route/intentions/v1": "intentions",
                  "intent-route/norms/v1": "norms", "intent-route/safety/v1": "safety",
                  "intent-route/liveness/v1": "liveness", "intent-route/action-hoare/v1": "action_hoare",
                  "intent-route/workflow-temporal/v1": "workflows"}
        _require(name in labels, "unsupported Intent projection")
        route = resolve_intent_route(labels[name])
        _require(descriptor == {"logic_family": route.family_id, "profile": route.profile_id or None,
                 "properties": [route.property_id] if route.property_id else [], "view_role": route.view_role_id or None,
                 "representation_kind": "domain_structured_formula", "producer_id": "intent-formalization-compiler"},
                 "Intent projection descriptor differs from native route")
        return _intent_expression(name, expression)
    ui_routes = {"ui_ux_ir:flogic": ("frame_logic", "ui-flogic-compilation/v1", "structural_components", "ui-ux-ir/flogic@1"),
                 "ui_ux_ir:event_calculus": ("event_calculus", "ui-event-calculus-compilation/v1", "behavior_transitions", "ui-ux-ir/event-calculus@1"),
                 "ui_ux_ir:tdfol": ("tdfol", "ui-tdfol-compilation/v1", "action_norms", "ui-ux-ir/tdfol@1"),
                 "ui_ux_ir:dcec": ("dcec", "ui-dcec-compilation/v1", "interaction_cognition", "ui-ux-ir/dcec@1")}
    _require(name in ui_routes, "unsupported UI projection")
    family, profile, role, producer = ui_routes[name]
    _require(descriptor == {"logic_family": family, "profile": profile, "properties": [], "view_role": role,
             "representation_kind": "domain_structured_formula", "producer_id": producer},
             "UI projection descriptor differs from native route")
    return _ui_expression(name, expression)


def decode_formal_features(space, head, inference_result):
    """Decode only the supplied model reconstruction, never inference targets.

    The native v1 inference receipt supplies scores plus state/basis/source
    identifiers. Unknown shape, nonpositive score, ties, malformed records and
    typed replay failures abstain per projection. No fallback copies the input.
    """
    head_sha = validate_decoder(space, head)
    basis, widths = _basis(space)
    _require(type(inference_result) is dict
             and inference_result.get("schema") == "native-projection-feature-inference/" + space["schema"].rsplit("/", 1)[1]
             and inference_result.get("feature_space_sha256") == features.digest(space), "native inference basis/schema differs")
    _require(type(inference_result.get("state_sha256")) is str and _SHA.fullmatch(inference_result["state_sha256"])
             and inference_result.get("training_executed") is False
             and all(inference_result.get(key) is False for key in features.FALSE), "native inference identity or authority differs")
    raw_rows = inference_result.get("rows")
    _require(type(raw_rows) is list and 1 <= len(raw_rows) <= 1024, "bounded inference rows required")
    rows = []
    for row in raw_rows:
        _require(type(row) is dict and type(row.get("source_digest")) is str and _SHA.fullmatch(row["source_digest"]),
                 "inference source digest required")
        scores = row.get("reconstructed_projection_features")
        _require(type(scores) is dict and set(scores) == set(basis), "reconstructed projection coverage differs")
        projections = []
        for name in space["projection_ids"]:
            descriptor = space["projections"][name]
            result = {"projection_id": name, **_plain(descriptor), "status": "abstained", "reason": None,
                      "expression": None, "typed_expression": None, "readable_notation": None,
                      "notation_kind": None, "family_syntax_checked": False, "source_provenance": "predicted_fields_unverified",
                      "validator": None, "validation_scope": None, **_FALSE}
            vector = scores[name]
            _require(type(vector) is list and len(vector) == widths[name]
                     and all(type(value) in (int, float) and math.isfinite(value) for value in vector),
                     "invalid reconstructed projection score vector")
            record = head["projections"][name]
            if record["status"] != "ready":
                result["reason"] = record["reason"]
                projections.append(result)
                continue
            leaves = {}
            for path, candidates in basis[name].items():
                ranked = sorted(((vector[index], index, value) for index, value in candidates),
                                key=lambda item: (-item[0], item[1]))
                if ranked[0][0] <= MINIMUM_SCORE:
                    result["reason"] = "nonpositive_or_insufficient_leaf_score"
                    break
                if len(ranked) > 1 and ranked[0][0] - ranked[1][0] <= MINIMUM_MARGIN:
                    result["reason"] = "ambiguous_leaf_scores"
                    break
                leaves[path] = ranked[0][2]
            if result["reason"] is None:
                expression = _rebuild(record["shape"], leaves)
                try:
                    validation = _validate_expression(space["domain_id"], name, descriptor, expression)
                except (ValueError, TypeError, KeyError) as exc:
                    result["reason"] = "decoded_native_validation_failed"
                    result["validation_error"] = str(exc)[:1000]
                else:
                    result.update(validation)
                    result["status"] = "decoded_candidate"
                    result["expression"] = expression
            projections.append(result)
        rows.append({"source_digest": row["source_digest"], "projections": projections})
    decoded = sum(item["status"] == "decoded_candidate" for row in rows for item in row["projections"])
    total = sum(len(row["projections"]) for row in rows)
    return {"schema": RESULT_SCHEMA, "domain_id": space["domain_id"], "decoder_sha256": head_sha,
            "feature_space_sha256": features.digest(space), "state_sha256": inference_result["state_sha256"],
            "rows": rows, "decoded_projection_count": decoded,
            "abstained_projection_count": total - decoded,
            "status": "decoded" if decoded == total else "partial" if decoded else "abstained",
            "decoded_formulas_generated": decoded > 0,
            "coverage": _plain(inference_result.get("coverage", [])),
            "input_representation": "native_compiler_projection_features_not_raw_text",
            "decoder_kind": "deterministic_structural_readout_of_model_reconstruction",
            "source_input_conditioned": True,
            "trained_neural_decoder": False, "independent_text_to_logic": False,
            "training_executed": False, **_FALSE}


def infer_and_decode_native_v2(space, state, head, targets):
    """Read a validated streamed v2 state without changing its backend module.

    The backend returns exact float64 latents but omits reconstructed columns.
    Apply its saved decoder matrix/bias to those latents, then the same readout.
    This helper adds no v2 training, registry or transport integration.
    """
    from . import autoencoder_projection_features_v2 as streamed
    space, state, head = _plain(space), _plain(state), _plain(head)
    _require(space.get("schema") == streamed.SPACE_SCHEMA, "v2 inference requires v2 feature space")
    validate_decoder(space, head)
    inference = streamed.infer_streamed_projection_features(space, state, targets)
    import torch
    with torch.no_grad():
        latent = torch.tensor([row["latent"] for row in inference["rows"]], dtype=torch.float64)
        decoded = latent @ torch.tensor(state["parameters"][2], dtype=torch.float64) + torch.tensor(state["parameters"][3], dtype=torch.float64)
        _require(bool(torch.isfinite(decoded).all()), "nonfinite v2 reconstruction")
        scores = decoded.tolist()
    enriched = _plain(inference)
    for row, values in zip(enriched["rows"], scores):
        row["reconstructed_projection_features"] = {
            name: [values[index] for index, (projection, _) in enumerate(space["columns"]) if projection == name]
            for name in space["projection_ids"]}
    result = decode_formal_features(space, head, enriched)
    result["model_inference"] = inference
    return result


__all__ = ["HEAD_SCHEMA", "RESULT_SCHEMA", "FormulaDecoderError", "decoder_digest",
           "train_formal_decoder", "validate_decoder", "decode_formal_features", "infer_and_decode_native_v2"]
