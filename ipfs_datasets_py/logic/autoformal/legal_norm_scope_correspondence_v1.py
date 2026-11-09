"""Unsigned source-anchor/typed-node correspondence for authored norm alternatives.

Replays the existing scope and relational owners without extending either
owner's signing or authority domain. Exhaustive accounting checks transport and
declared syntax, not whether an authored interpretation means what a law means.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

REQUEST_SCHEMA = "legal-norm-scope-correspondence-request/v1"
SCHEMA = "legal-norm-scope-correspondence-report/v1"
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 24 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_translation_performed", "source_bound",
    "legal_roles_verified", "applicability_verified", "context_closed",
    "governing_use_verified", "independently_reviewed", "accepted", "admitted",
    "semantic_graph_admitted", "training_gold_qualified", "evaluation_gold_qualified",
    "Lean_admitted", "proof_authority", "backend_executed", "model_executed",
    "training_executed",
), False)
_REPLAY_REQUIRED = {
    "sampling_report", "raw_html", "scope_request_raw", "scope_declaration_raw",
    "expected_sampling_report_sha256", "selected_unit_ref",
    "expected_scope_request_sha256", "expected_scope_declaration_sha256",
    "descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes",
}


def _need(value, message):
    if not value:
        raise ValueError(message)


def _keys(value, expected, label):
    _need(type(value) is dict and set(value) == set(expected), "closed exact fields required: " + label)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent SHA256 required: " + label)


def _scalar_wire(value, maximum):
    """Validate and encode one exact immutable JSON scalar once.

    Keep the scalar guards and bytes of the general encoder. In particular,
    reject oversized strings before allocating their escaped UTF8 encoding.
    """
    if type(value) is str:
        _need("\x00" not in value and len(value) + 2 <= maximum, "bounded UTF8 strings required")
        try:
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        except UnicodeError as error:
            raise ValueError("ordinary UTF8 strings required") from error
    elif value is None or type(value) is bool:
        raw = b"null" if value is None else (b"true" if value else b"false")
    elif type(value) is int:
        _need(-(1 << 63) < value < (1 << 63), "bounded JSON integer required")
        raw = str(value).encode("ascii")
    elif type(value) is float:
        _need(value == value and abs(value) != float("inf"), "finite JSON number required")
        raw = json.dumps(value).encode("ascii")
    else:
        raise ValueError("ordinary JSON values required")
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _wire(value, maximum):
    if type(value) not in (dict, list):
        return _scalar_wire(value, maximum)
    remaining = 500000
    byte_budget = maximum

    def charge(count):
        nonlocal byte_budget
        byte_budget -= count
        _need(byte_budget >= 0, "complete JSON byte bound exceeded")

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 96, "bounded ordinary JSON required")
        if type(item) is dict:
            charge(2 + max(0, len(item) - 1) + len(item))
            for key, child in item.items():
                _need(type(key) is str, "ordinary string JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            charge(2 + max(0, len(item) - 1))
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) + 2 <= byte_budget, "bounded UTF8 strings required")
            try:
                charge(len(json.dumps(item, ensure_ascii=False).encode("utf-8")))
            except UnicodeError as error:
                raise ValueError("ordinary UTF8 strings required") from error
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
            charge(len(str(item)))
        elif type(item) is float:
            # Source acquisition observations can contain finite timings.
            _need(item == item and abs(item) != float("inf"), "finite JSON number required")
            charge(len(json.dumps(item)))
        else:
            raise ValueError("ordinary JSON values required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _same(left, right):
    # Python equality alone would equate False/0 and 1/1.0.
    return _wire(left, MAX_REPORT_BYTES) == _wire(right, MAX_REPORT_BYTES)


def _raw(raw, expected, maximum, label):
    _sha(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent byte pin differs: " + label)


def _parse(raw, expected, *, request_schema=REQUEST_SCHEMA):
    _raw(raw, expected, MAX_REQUEST_BYTES, "mapping request")

    def pairs(entries):
        result = {}
        for key, value in entries:
            _need(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite JSON constant")

    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free ordinary UTF8 request required") from error
    _wire(request, MAX_REQUEST_BYTES)
    _keys(request, {"schema", "interpretation_status", "alternative_id", "scope_report_sha256",
                    "relational_report_sha256", "source_rows", "typed_rows"}, "mapping request")
    _need(request["schema"] == request_schema and
          request["interpretation_status"] == "authored_unreviewed_correspondence",
          "authored unreviewed correspondence required")
    _need(type(request["alternative_id"]) is str and _ID.fullmatch(request["alternative_id"]) is not None,
          "bounded alternative identity required")
    for key in ("scope_report_sha256", "relational_report_sha256"):
        _sha(request[key], key)
    for key in ("source_rows", "typed_rows"):
        rows = request[key]
        _need(type(rows) is list and 0 < len(rows) <= 2048, "bounded complete mapping rows required")
        for row in rows:
            fields = ({"anchor_mapping", "disposition", "targets", "rationale"} if key == "source_rows"
                      else {"target", "disposition", "source_paths", "rationale"})
            _keys(row, fields, key)
            _need(type(row["rationale"]) is str and len(row["rationale"]) <= 2048 and bool(row["rationale"].strip()),
                  "bounded nonempty authored rationale required")
            if key == "source_rows":
                _need(type(row["anchor_mapping"]) is dict and type(row["targets"]) is list and
                      len(row["targets"]) <= 1024 and all(type(item) is dict for item in row["targets"]),
                      "exact source anchor and typed mapping rows required")
                _need(type(row["disposition"]) is str and row["disposition"] in
                      {"proposed_mapping", "unresolved", "unsupported", "literal_accounting"},
                      "known source disposition required")
                _need(bool(row["targets"]) == (row["disposition"] == "proposed_mapping"),
                      "only proposed mappings have nonempty targets")
            else:
                _need(type(row["target"]) is dict and type(row["source_paths"]) is list and
                      len(row["source_paths"]) <= 2048 and
                      all(type(path) is str for path in row["source_paths"]), "exact typed target and source paths required")
                _need(type(row["disposition"]) is str and row["disposition"] in
                      {"source_linked", "authored_scaffolding"}, "known typed disposition required")
                _need(bool(row["source_paths"]) == (row["disposition"] == "source_linked"),
                      "only source-linked targets have source paths")
    return request


def _snapshot(scope_report, relational_report, replay):
    """Bound and detach all caller-owned structures before operation imports."""
    _need(type(replay) is dict and _REPLAY_REQUIRED <= set(replay) and
          not (set(replay) - _REPLAY_REQUIRED - {"view_limits", "limits"}),
          "closed original scope replay inputs required")
    detached, commitments, total = {}, {}, 0
    originals = {"scope_report": scope_report, "relational_report": relational_report, **replay}
    maxima = {"scope_report": 1024**2, "relational_report": 8 * 1024**2,
              "sampling_report": 32 * 1024**2, "raw_html": 8000000,
              "scope_request_raw": 65536, "scope_declaration_raw": 65536}
    byte_fields = {"raw_html", "scope_request_raw", "scope_declaration_raw"}
    for key, value in originals.items():
        maximum = maxima.get(key, 65536)
        if key in byte_fields:
            _need(type(value) is bytes and 0 < len(value) <= maximum, "bounded exact replay bytes required: " + key)
            raw = value
            detached[key] = value
        else:
            raw = _wire(value, maximum)
            detached[key] = json.loads(raw)
        commitments[key] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "encoding": "original_bytes" if key in byte_fields else "canonical_json"}
        total += len(raw)
    _need(total <= MAX_TOTAL_BYTES, "aggregate replay byte bound exceeded")
    return detached, commitments


def _owners():
    from . import legal_source_norm_scope_v1 as scope
    from . import legal_relational_norm_v1 as relational
    return scope, relational


def _pins(owners):
    global _OWNER_PINS
    scope, relational = owners
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "correspondence producer changed since import")
    pins = scope._pins(scope._owners())
    for path, value in relational._owners()[-1].items():
        _need(path not in pins or pins[path] == value, "inconsistent shared producer pins")
        pins[path] = value
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _OWNER_PINS is None:
        _OWNER_PINS = dict(pins)
    _need(_OWNER_PINS == pins, "correspondence operation owners changed since first use")
    return pins


def _at(value, path):
    for token in path.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if type(value) is list else value[key]
    return value


def _typed_contexts(relational):
    """Derive role, binder and ordered ancestry from the replayed existing AST."""
    expression = relational["typed_expression"]
    mapping = relational["structural_mapping"]
    roles = {row["symbol"]: row["roles"] for row in relational["argument_roles"]}
    contexts = []
    for target in mapping:
        path = target["typed_path"]
        value = _at(expression, path)
        ancestors, binders = [], []
        for parent in mapping:
            parent_path = parent["typed_path"]
            if path.startswith(parent_path + "/") and parent["kind"] not in {"binder", "variable"}:
                node = _at(expression, parent_path)
                entry = {"typed_path": parent_path, "kind": parent["kind"],
                         "relative_path": path[len(parent_path):]}
                if parent["kind"] == "legacy.deontic/v1":
                    entry["operator"] = parent["operator"]
                ancestors.append(entry)
                if parent["kind"] in {"forall", "exists"} and path.startswith(parent_path + "/arguments/0/"):
                    binders.append({"typed_path": parent_path + "/binders/0",
                                    "name": node["binders"][0]["name"], "quantifier": parent["kind"]})
        binding = None
        argument = None
        if target["kind"] == "variable":
            matches = [binder for binder in binders if binder["name"] == value["symbol"]]
            _need(len(matches) == 1, "exact governing binder required for variable occurrence")
            binding = matches[0]
            parent_path, index = path.rsplit("/arguments/", 1)
            parent = _at(expression, parent_path)
            _need(parent["kind"] == "predicate" and index.isdecimal(), "ordered predicate argument required")
            argument = {"predicate_path": parent_path, "symbol": parent["symbol"],
                        "index": int(index), "role": roles[parent["symbol"]][int(index)]}
        contexts.append({"target": target, "ancestry": ancestors, "binding": binding,
                         "argument": argument})
    return contexts


def _join(request, scope, relational):
    anchors, targets = scope["anchor_mappings"], relational["structural_mapping"]
    _need(len(request["source_rows"]) == len(anchors), "every original source anchor must be accounted for")
    _need(len(request["typed_rows"]) == len(targets), "every typed node and binder must be accounted for")
    target_by_path = {target["typed_path"]: target for target in targets}
    _need(len(target_by_path) == len(targets), "unique typed mapping paths required")
    inverse = {path: [] for path in target_by_path}
    for row, anchor in zip(request["source_rows"], anchors):
        _need(_same(row["anchor_mapping"], anchor), "ordered exact source anchor mapping differs")
        path = anchor["declaration_path"]
        if path.startswith("/coverage/"):
            _need(row["disposition"] == "literal_accounting", "coverage accounting cannot become semantic mapping")
        else:
            _need(row["disposition"] != "literal_accounting", "lexical occurrence or issue needs its own disposition")
        seen = set()
        for target in row["targets"]:
            typed_path = target.get("typed_path")
            _need(type(typed_path) is str and typed_path in target_by_path and typed_path not in seen,
                  "unique existing typed target required")
            _need(_same(target, target_by_path[typed_path]), "exact typed mapping target differs")
            seen.add(typed_path)
            inverse[typed_path].append(path)
            if path.startswith("/occurrences/"):
                occurrence = _at(scope["scope_declaration"], path.rsplit("/anchor", 1)[0])
                facet = occurrence["facet"]
                if facet == "modality":
                    _need(target["kind"] == "legacy.deontic/v1" and
                          target["operator"] == occurrence["canonical_symbol"],
                          "declared modality must match exact modal extension")
                elif facet in {"actor", "object"}:
                    _need(target["kind"] in {"variable", "binder"}, "declared participant needs variable or binder target")
                elif facet == "action":
                    _need(target["kind"] == "predicate", "declared action needs predicate target")
                else:
                    raise ValueError("unsupported lexical facet must remain unresolved or unsupported")
    for row, target in zip(request["typed_rows"], targets):
        _need(_same(row["target"], target), "ordered exact typed target differs")
        _need(row["source_paths"] == inverse[target["typed_path"]],
              "typed source paths must equal the exact inverse source mapping")
    return _typed_contexts(relational)


def prepare_norm_scope_correspondence_v1(
    scope_report, relational_report, mapping_request_raw, *,
    expected_scope_report_sha256, expected_relational_report_sha256,
    expected_mapping_request_sha256, scope_replay_inputs, relational_request_raw,
    expected_relational_request_sha256,
):
    """Check one declared alternative's correspondence; grant no meaning authority."""
    request = _parse(mapping_request_raw, expected_mapping_request_sha256)
    for pin, label in ((expected_scope_report_sha256, "scope report"),
                       (expected_relational_report_sha256, "relational report")):
        _sha(pin, label)
    _need(request["scope_report_sha256"] == expected_scope_report_sha256 and
          request["relational_report_sha256"] == expected_relational_report_sha256,
          "mapping must bind the independently pinned reports")
    _raw(relational_request_raw, expected_relational_request_sha256, 524288, "relational request")
    snapshot, commitments = _snapshot(scope_report, relational_report, scope_replay_inputs)
    _need(sum(item["bytes"] for item in commitments.values()) + len(mapping_request_raw) +
          len(relational_request_raw) <= MAX_TOTAL_BYTES, "aggregate complete input byte bound exceeded")
    _need(commitments["scope_report"]["sha256"] == expected_scope_report_sha256 and
          commitments["relational_report"]["sha256"] == expected_relational_report_sha256,
          "independent complete report pin differs")
    replay = {key: snapshot[key] for key in scope_replay_inputs}
    for key, pin in (("raw_html", "expected_raw_sha256"),
                     ("scope_request_raw", "expected_scope_request_sha256"),
                     ("scope_declaration_raw", "expected_scope_declaration_sha256")):
        _need(commitments[key]["sha256"] == replay[pin], "scope replay raw byte pin differs")
    _need(type(replay["expected_raw_bytes"]) is int and replay["expected_raw_bytes"] == len(replay["raw_html"]),
          "exact integer source byte count required")
    for key, pin in (("sampling_report", "expected_sampling_report_sha256"),
                     ("descriptor", "expected_descriptor_sha256")):
        _need(commitments[key]["sha256"] == replay[pin], "scope replay canonical pin differs")
    _keys(replay["selected_unit_ref"], {"schema", "record_cid", "sha256"}, "selected unit reference")
    _sha(replay["selected_unit_ref"]["sha256"], "selected unit")
    _need(type(replay["descriptor"]) is dict and type(replay["sampling_report"]) is dict,
          "original descriptor and sampling report objects required")
    # These public modules are standard-library-only. Reuse their pure request
    # parsers before _pins loads the actual source, AST and native route owners.
    owners = _owners()
    scope, relational = owners
    scope._load(replay["scope_request_raw"], replay["expected_scope_request_sha256"], "scope request")
    scope._load(replay["scope_declaration_raw"], replay["expected_scope_declaration_sha256"], "scope declaration")
    relational._parse(relational_request_raw, expected_relational_request_sha256)
    pins = _pins(owners)

    def fence():
        _need(_snapshot(scope_report, relational_report, scope_replay_inputs)[1] == commitments,
              "caller inputs changed during correspondence preparation")
        _need(_snapshot(snapshot["scope_report"], snapshot["relational_report"], replay)[1] == commitments,
              "detached replay inputs changed during correspondence preparation")
        _need(_pins(owners) == pins, "correspondence producers changed during preparation")

    fence()
    scope, relational = owners
    scope_validation = scope.validate_sampled_norm_scope_v1(
        snapshot["scope_report"], expected_report_sha256=expected_scope_report_sha256, **replay)
    fence()
    checked = relational.validate_relational_norm_v1(
        snapshot["relational_report"], relational_request_raw,
        expected_request_sha256=expected_relational_request_sha256,
        expected_report_sha256=expected_relational_report_sha256)
    fence()
    contexts = _join(request, snapshot["scope_report"], checked)
    report = {
        "schema": SCHEMA, "status": "unreviewed_correspondence_transport_checked",
        "request": request, "alternative_id": request["alternative_id"],
        "input_pins": {"scope_report_sha256": expected_scope_report_sha256,
                       "relational_report_sha256": expected_relational_report_sha256,
                       "mapping_request_raw_sha256": expected_mapping_request_sha256,
                       "mapping_request_raw_bytes": len(mapping_request_raw),
                       "relational_request_raw_sha256": expected_relational_request_sha256,
                       "replay_inputs": commitments},
        "source_scope": snapshot["scope_report"], "source_scope_validation": scope_validation,
        "relational_fragment": checked, "typed_context_inventory": contexts,
        "retained_unresolved": snapshot["scope_report"]["scope_declaration"]["unresolved"],
        "declared_semantic_coverage": snapshot["scope_report"]["declared_semantic_coverage"],
        "counts": {"source_anchors": len(request["source_rows"]), "typed_targets": len(contexts),
                   "proposed_links": sum(len(row["targets"]) for row in request["source_rows"]),
                   "authored_scaffolding": sum(row["disposition"] == "authored_scaffolding" for row in request["typed_rows"])},
        "transport_checked": True, "source_bound": False, "source_translation_performed": False,
        "selected_interpretation": None, "governing_definition_use": None,
        "original_signatures_cover_correspondence": False,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "authority": dict(AUTHORITY), "producer_pins": pins,
        "limitations": [
            "Declared lexical correspondences are nominations, not checked legal equivalences or reviewed source translations.",
            "Participant-to-variable labels do not establish agency, referent identity, legal sorts or applicability.",
            "Every source anchor and typed node is accounted for; this does not imply semantic completeness or exhaustive ambiguity detection.",
            "Original unresolved issues, partial coverage and open context remain; mapped issue anchors do not resolve those issues.",
            "Explicit formula structure preserves authored condition direction, modal scope and binding; their correctness for the source is unreviewed.",
            "Original report/signature domains are unchanged and do not authorize this unsigned alternative.",
            "No learned target, graph admission, model, training, solver or Lean execution is supplied.",
        ],
    }
    raw = _wire(report, MAX_REPORT_BYTES)
    fence()
    return json.loads(raw)


def norm_scope_correspondence_sha256(report):
    """Hash complete bounded ordinary JSON without loading operation owners."""
    return _digest(report)


def validate_norm_scope_correspondence_v1(report, *args, expected_report_sha256, **kwargs):
    """Require original inputs and exact regeneration, even for self-rehashed edits."""
    _sha(expected_report_sha256, "correspondence report")
    offered = _wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(offered).hexdigest() == expected_report_sha256, "independent correspondence report pin differs")
    regenerated = prepare_norm_scope_correspondence_v1(*args, **kwargs)
    _need(offered == _wire(regenerated, MAX_REPORT_BYTES), "correspondence report differs from complete replay")
    return regenerated




# Explicit parent-occurrence route; the HTML v1 replay and pin state are kept
# separate and the original relational fragment remains source_binding:null.
REQUEST_SCHEMA_V2 = "legal-norm-scope-correspondence-request/v2"
SCHEMA_V2 = "legal-norm-scope-correspondence-report/v2"
_PARENT_OWNER_PINS = None


def _parent_correspondence_pins(owners):
    global _PARENT_OWNER_PINS
    scope, relational = owners
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "parent correspondence producer changed since import")
    pins = scope._parent_pins()
    for path, value in relational._owners()[-1].items():
        _need(path not in pins or pins[path] == value, "inconsistent parent correspondence producers")
        pins[path] = value
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _PARENT_OWNER_PINS is None:
        _PARENT_OWNER_PINS = dict(pins)
    _need(pins == _PARENT_OWNER_PINS, "parent correspondence owners changed since first use")
    return dict(pins)


def _parent_correspondence_snapshot(scope_report, relational_report, replay, scope):
    detached_replay, original = scope._parent_snapshot(replay)
    detached, commitments = {}, {"parent_replay/" + key: value for key, value in original.items()}
    for key, value, maximum in (("scope_report", scope_report, scope.MAX_REPORT_BYTES),
                                ("relational_report", relational_report, 8 * 1024**2)):
        raw = _wire(value, maximum)
        detached[key] = json.loads(raw)
        commitments[key] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "encoding": "canonical_json"}
    _need(sum(row["bytes"] for row in commitments.values()) <= MAX_TOTAL_BYTES,
          "aggregate complete parent correspondence input bound exceeded")
    detached["scope_replay_inputs"] = detached_replay
    return detached, commitments


def prepare_norm_scope_correspondence_v2(
    scope_report, relational_report, mapping_request_raw, *,
    expected_scope_report_sha256, expected_relational_report_sha256,
    expected_mapping_request_sha256, scope_replay_inputs, relational_request_raw,
    expected_relational_request_sha256,
):
    """Check authored correspondence over exact original parent occurrence scope.

    This explicit request/report profile does not accept sampled HTML replay.
    Parent scope and the original null-source relational owner are regenerated
    at opening and closing; this establishes custody and syntax, not meaning.
    """
    request = _parse(mapping_request_raw, expected_mapping_request_sha256,
                     request_schema=REQUEST_SCHEMA_V2)
    for value, label in ((expected_scope_report_sha256, "parent scope report"),
                          (expected_relational_report_sha256, "relational report")):
        _sha(value, label)
    _need(request["scope_report_sha256"] == expected_scope_report_sha256
          and request["relational_report_sha256"] == expected_relational_report_sha256,
          "mapping must bind independently pinned parent scope and relational reports")
    _raw(relational_request_raw, expected_relational_request_sha256, 524288, "relational request")
    owners = _owners()  # These two public modules have standard-library-only imports.
    scope, relational = owners
    snapshot, commitments = _parent_correspondence_snapshot(scope_report, relational_report,
                                                           scope_replay_inputs, scope)
    _need(sum(row["bytes"] for row in commitments.values()) + len(mapping_request_raw)
          + len(relational_request_raw) <= MAX_TOTAL_BYTES,
          "aggregate parent correspondence input bound exceeded")
    _need(commitments["scope_report"]["sha256"] == expected_scope_report_sha256
          and commitments["relational_report"]["sha256"] == expected_relational_report_sha256,
          "independent complete parent scope or relational report pin differs")
    offered_scope = snapshot["scope_report"]
    _need(type(offered_scope) is dict and offered_scope.get("schema") == scope.PARENT_SCHEMA
          and offered_scope.get("profile") == scope.PARENT_PROFILE,
          "explicit parent literal occurrence scope required for correspondence v2")
    relational._parse(relational_request_raw, expected_relational_request_sha256)
    request_wire = _wire(request, MAX_REQUEST_BYTES)
    pins = _parent_correspondence_pins(owners)
    replay = snapshot["scope_replay_inputs"]
    opening_validation = opening_relational = None
    opening_validation_wire = opening_relational_wire = None
    checked = scope_validation = None
    report = serialized = None
    replay_started = False
    primary = None

    def fence():
        _need(_parent_correspondence_snapshot(scope_report, relational_report, scope_replay_inputs, scope)[1]
              == commitments, "original parent correspondence inputs changed during preparation")
        _need(_parent_correspondence_snapshot(snapshot["scope_report"], snapshot["relational_report"],
                                             replay, scope)[1] == commitments,
              "detached parent correspondence inputs changed during preparation")
        _need(_wire(request, MAX_REQUEST_BYTES) == request_wire,
              "parsed parent correspondence request changed during preparation")
        _need(_parent_correspondence_pins(owners) == pins,
              "parent correspondence sources changed during preparation")

    def returned_fence():
        if opening_validation_wire is not None:
            _need(_wire(opening_validation, MAX_REPORT_BYTES) == opening_validation_wire
                  and _wire(scope_validation, MAX_REPORT_BYTES) == opening_validation_wire,
                  "opening parent scope validation changed during correspondence")
        if opening_relational_wire is not None:
            _need(_wire(opening_relational, MAX_REPORT_BYTES) == opening_relational_wire
                  and _wire(checked, MAX_REPORT_BYTES) == opening_relational_wire,
                  "opening relational validation changed during correspondence")

    def closing_scope():
        if replay_started:
            closed = scope.validate_parent_norm_scope_v1(snapshot["scope_report"],
                expected_report_sha256=expected_scope_report_sha256, **replay)
            if opening_validation_wire is not None:
                _need(_wire(closed, MAX_REPORT_BYTES) == opening_validation_wire,
                      "closing original parent scope validation differs from opening")

    def closing_relational():
        if replay_started:
            closed = relational.validate_relational_norm_v1(snapshot["relational_report"],
                relational_request_raw, expected_request_sha256=expected_relational_request_sha256,
                expected_report_sha256=expected_relational_report_sha256)
            if opening_relational_wire is not None:
                _need(_wire(closed, MAX_REPORT_BYTES) == opening_relational_wire,
                      "closing relational validation differs from opening")

    def output_fence():
        if serialized is not None:
            scope._parent_serialized_fence(report, serialized, MAX_REPORT_BYTES, _wire)

    try:
        fence()
        replay_started = True
        opening_validation = scope.validate_parent_norm_scope_v1(snapshot["scope_report"],
            expected_report_sha256=expected_scope_report_sha256, **replay)
        opening_validation_wire = _wire(opening_validation, MAX_REPORT_BYTES)
        scope_validation = json.loads(opening_validation_wire)
        fence()
        opening_relational = relational.validate_relational_norm_v1(snapshot["relational_report"],
            relational_request_raw, expected_request_sha256=expected_relational_request_sha256,
            expected_report_sha256=expected_relational_report_sha256)
        opening_relational_wire = _wire(opening_relational, MAX_REPORT_BYTES)
        checked = json.loads(opening_relational_wire)
        fence()
        contexts = _join(request, snapshot["scope_report"], checked)
        report = {
            "schema": SCHEMA_V2, "profile": "parent-literal-occurrence-authored-correspondence/v2",
            "status": "unreviewed_correspondence_transport_checked",
            "request": request, "alternative_id": request["alternative_id"],
            "input_pins": {"scope_report_sha256": expected_scope_report_sha256,
                "relational_report_sha256": expected_relational_report_sha256,
                "mapping_request_raw_sha256": expected_mapping_request_sha256,
                "mapping_request_raw_bytes": len(mapping_request_raw),
                "relational_request_raw_sha256": expected_relational_request_sha256,
                "relational_request_raw_bytes": len(relational_request_raw), "replay_inputs": commitments},
            "source_scope": snapshot["scope_report"], "source_scope_validation": scope_validation,
            "relational_fragment": checked, "typed_context_inventory": contexts,
            "retained_unresolved": snapshot["scope_report"]["scope_declaration"]["unresolved"],
            "declared_semantic_coverage": snapshot["scope_report"]["declared_semantic_coverage"],
            "counts": {"source_anchors": len(request["source_rows"]), "typed_targets": len(contexts),
                "proposed_links": sum(len(row["targets"]) for row in request["source_rows"]),
                "authored_scaffolding": sum(row["disposition"] == "authored_scaffolding" for row in request["typed_rows"])},
            "transport_checked": True, "source_bound": False, "source_translation_performed": False,
            "selected_interpretation": None, "governing_definition_use": None,
            "original_signatures_cover_correspondence": False,
            "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
            "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": dict(AUTHORITY), "producer_pins": pins,
            "limitations": [
                "The source is one exact original literal occurrence; no paragraph, complete law, governing edition or classified source region is established.",
                "Declared correspondence and complete authored typed syntax are unreviewed nominations, not legal equivalence, source translation or complete source semantics.",
                "Exact original source and offset custody does not authorize the original null-source relational declaration or its signatures for governing use.",
                "Original unresolved issues, partial coverage and all six unavailable context obligations remain open; dependency and ambiguity inventories are not exhaustive.",
                "No interpretation selection, meaning review, learned target, graph admission, model, training, solver or Lean execution is supplied.",
            ],
        }
        serialized = _wire(report, MAX_REPORT_BYTES)
        report = json.loads(serialized)
        return report
    except BaseException as error:
        primary = error
        raise
    finally:
        scope._parent_finish((fence, returned_fence, closing_scope, closing_relational,
                              fence, returned_fence, output_fence, fence), primary)


def validate_norm_scope_correspondence_v2(report, *args, expected_report_sha256, **kwargs):
    """Validate only the explicit parent profile against complete original replay."""
    _sha(expected_report_sha256, "parent correspondence report")
    offered = _wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(offered).hexdigest() == expected_report_sha256,
          "independent parent correspondence report pin differs")
    _need(type(report) is dict and report.get("schema") == SCHEMA_V2
          and report.get("profile") == "parent-literal-occurrence-authored-correspondence/v2",
          "explicit parent correspondence report profile required")
    primary = None
    regenerated = serialized = None
    try:
        regenerated = prepare_norm_scope_correspondence_v2(*args, **kwargs)
        serialized = _wire(regenerated, MAX_REPORT_BYTES)
        _need(offered == serialized, "parent correspondence report differs from complete original replay")
        return regenerated
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_fence():
            scope._parent_serialized_fence(report, offered, MAX_REPORT_BYTES, _wire)
        def result_fence():
            if serialized is not None:
                scope._parent_serialized_fence(regenerated, serialized, MAX_REPORT_BYTES, _wire)
        from . import legal_source_norm_scope_v1 as scope
        scope._parent_finish((offered_fence, result_fence), primary)


__all__ = ["prepare_norm_scope_correspondence_v1", "norm_scope_correspondence_sha256",
           "validate_norm_scope_correspondence_v1", "prepare_norm_scope_correspondence_v2",
           "validate_norm_scope_correspondence_v2"]
