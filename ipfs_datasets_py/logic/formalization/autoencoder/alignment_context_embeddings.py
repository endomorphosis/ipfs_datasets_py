"""Two fixed role-marked input arms around the unchanged native encoders.

The outer profile preserves original source and separately declared assumptions.
The inner source-only compatibility record concerns the literal rendered JSON
text, not the original source corpus. Forwarding assumptions is observable input
transport, not contextual interpretation, semantic fidelity or proof evidence.
Import, preparation and validation load no encoder. Actual producers keep their
existing local CPU/offline and complete-checkpoint admission contracts.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from copy import deepcopy
from pathlib import Path

INPUT_SCHEMA = "alignment-context-embedding-inputs/v1"
SCHEMA = "alignment-context-embedding-lane/v1"
RENDER_SCHEMA = "role-marked-source-context/v1"
TRANSPORT_IDENTITY_SCHEMA = "alignment-context-transport-identity/v1"
INPUT_RECIPE = "role_marked_source_declared_context_two_arm/v1"
RENDERING_RECIPE = "sorted_compact_utf8_json_no_nan_no_newline/v1"
TRANSPORT_IDENTITY_RECIPE = "sha256_sorted_compact_utf8_json_arm_original_input_encoder_text/v1"
ARMS = ("source_frame_only", "declared_context")
DIMENSIONS = {"legacy8": 8, "native384": 384, "native768": 768}
MAX_ORIGINAL_ROWS = 34
MAX_ROWS = 68
MAX_TEXT_BYTES = 65536
MAX_TOTAL_ENCODER_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
_OWNER = "ipfs_datasets_py.logic.formalization.autoencoder."
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FALSE_FIELDS = ("training_executed", "download_executed", "context_semantics_applied",
                 "context_resolved", "source_fidelity_established", "source_semantics_verified",
                 "proof_authority", "qualified")
_INPUT_KEYS = {"schema", "input_recipe", "rendering_recipe", "transport_identity_recipe", "rows",
               "original_row_count", "row_count", "context_forwarded_rows", "payload_sha256", *_FALSE_FIELDS}
_ROW_KEYS = {"id", "arm_id", "original_input_sha256", "domain_id", "logic_family", "source_text",
             "source_sha256", "context", "encoder_text", "encoder_text_sha256", "context_forwarded",
             "context_semantics_applied", "transport_input_sha256", "transport_id"}
_LANE_KEYS = {"schema", "lane_id", "dimension", "status", "input_manifest_sha256", "input_recipe",
              "context_profile_id", "transport_inputs", "transport_lane", "receipts", "issues",
              "encoder_execution_executed", "model_inference_executed", "payload_sha256", *_FALSE_FIELDS}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("bounded finite UTF8 JSON required") from error
    _require(len(data) <= MAX_RESULT_BYTES, "context embedding JSON byte bound exceeded")
    return data


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _hash(value, label):
    _require(type(value) is str and _HASH.fullmatch(value), label + " requires lowercase SHA256")


def _text(value, label, *, blank=False, maximum=MAX_TEXT_BYTES):
    _require(type(value) is str and "\x00" not in value and (blank or bool(value.strip())),
             label + " requires bounded UTF8 text without NUL")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError(label + " requires valid UTF8") from error
    _require(size <= maximum, label + " exceeds UTF8 byte bound")
    return size


def _seal(value):
    value["payload_sha256"] = _digest({key: item for key, item in value.items() if key != "payload_sha256"})
    return value


def _integrity(value):
    _hash(value["payload_sha256"], "payload_sha256")
    _require(value["payload_sha256"] == _digest({key: item for key, item in value.items()
                                               if key != "payload_sha256"}), "context payload SHA256 mismatch")


def _producer():
    return importlib.import_module(_OWNER + "alignment_richer_embeddings")


def _context(value):
    _closed(value, {"role", "text", "sha256", "bindings"}, "original declared context")
    _require(type(value["role"]) is str and value["role"] in {"none_required", "explicit_assumptions"},
             "unknown original context role")
    _text(value["text"], "context.text", blank=True)
    _hash(value["sha256"], "context.sha256")
    _require(value["sha256"] == _text_sha(value["text"]), "original context SHA256 mismatch")
    bindings = value["bindings"]
    _require(type(bindings) is dict and len(bindings) <= 4, "bounded original context bindings required")
    for name, binding in bindings.items():
        _text(name, "context binding name", maximum=256)
        _closed(binding, {"kind", "value"}, "declared context binding")
        _require(binding["kind"] == "actor_atom", "unsupported declared binding kind")
        _text(binding["value"], "context binding value", maximum=256)
    if value["role"] == "none_required":
        _require(value["text"] == "" and bindings == {}, "no-context input cannot contain assumptions")
    else:
        _require(bool(value["text"].strip()) and bool(bindings), "explicit assumptions require text and bindings")


def _original_input_sha(row):
    return _digest({"schema": "alignment-richer-input/v1", "domain_id": row["domain_id"],
                    "logic_family": row["logic_family"], "source_text": row["source_text"],
                    "source_sha256": row["source_sha256"], "context": row["context"]})


def _render(row):
    forwarded = row["arm_id"] == "declared_context" and row["context"]["role"] == "explicit_assumptions"
    return _raw({"schema": RENDER_SCHEMA, "source": {"role": "source", "text": row["source_text"]},
                 "assumptions": {"role": "declared_assumptions", "text": row["context"]["text"] if forwarded else "",
                                 "bindings": row["context"]["bindings"] if forwarded else {}}}).decode("utf-8")


def _transport_sha(row):
    return _digest({"schema": TRANSPORT_IDENTITY_SCHEMA, "arm_id": row["arm_id"],
                    "original_input_sha256": row["original_input_sha256"],
                    "encoder_text_sha256": row["encoder_text_sha256"]})


def prepare_context_embedding_inputs(panel: dict) -> dict:
    """Create two input-only arms after owner admission; never forward labels.

    Both arms retain the entire original input for integrity. Only the declared
    context arm places explicit assumptions in encoder text. No arm, hash, ID,
    target, split or authored expectation appears in that text.
    """
    owner = importlib.import_module(_OWNER + "alignment_richer_panel")
    owner.validate_alignment_richer_panel(panel)
    _require(len(panel["rows"]) == MAX_ORIGINAL_ROWS, "fixed richer panel requires 34 original inputs")
    rows = []
    for original in panel["rows"]:
        for arm in ARMS:
            row = {"arm_id": arm, "original_input_sha256": original["input_sha256"],
                   "domain_id": original["domain_id"], "logic_family": original["logic_family"],
                   "source_text": original["source_text"], "source_sha256": original["source_sha256"],
                   "context": deepcopy(original["context"]), "context_semantics_applied": False}
            row["context_forwarded"] = arm == "declared_context" and row["context"]["role"] == "explicit_assumptions"
            row["encoder_text"] = _render(row)
            row["encoder_text_sha256"] = _text_sha(row["encoder_text"])
            row["transport_input_sha256"] = _transport_sha(row)
            row["id"] = row["transport_id"] = "sha256:" + row["transport_input_sha256"]
            rows.append(row)
    rows.sort(key=lambda row: row["id"])
    inputs = _seal({"schema": INPUT_SCHEMA, "input_recipe": INPUT_RECIPE, "rendering_recipe": RENDERING_RECIPE,
                    "transport_identity_recipe": TRANSPORT_IDENTITY_RECIPE, "rows": rows,
                    "original_row_count": MAX_ORIGINAL_ROWS, "row_count": len(rows),
                    "context_forwarded_rows": sum(row["context_forwarded"] for row in rows),
                    **dict.fromkeys(_FALSE_FIELDS, False)})
    validate_context_embedding_inputs(inputs)
    return inputs


def validate_context_embedding_inputs(inputs: dict) -> dict:
    """Recompute original bindings, exact rendering and both-arm linkage."""
    _raw(inputs)
    _closed(inputs, _INPUT_KEYS, "context embedding inputs")
    _require(inputs["schema"] == INPUT_SCHEMA and inputs["input_recipe"] == INPUT_RECIPE
             and inputs["rendering_recipe"] == RENDERING_RECIPE
             and inputs["transport_identity_recipe"] == TRANSPORT_IDENTITY_RECIPE, "context input profile changed")
    _require(all(inputs[field] is False for field in _FALSE_FIELDS), "input transport cannot grant semantic authority")
    rows = inputs["rows"]
    _require(type(rows) is list and len(rows) == MAX_ROWS, "fixed context profile requires 68 arm rows")
    identities, originals, total, forwarded = [], {}, 0, 0
    for row in rows:
        _closed(row, _ROW_KEYS, "context embedding input row")
        _require(type(row["arm_id"]) is str and row["arm_id"] in ARMS, "unknown context input arm")
        _require(row["domain_id"] == "legal_ir" and row["logic_family"] == "deontic", "context profile is legal deontic only")
        _text(row["source_text"], "original source")
        for field in ("original_input_sha256", "source_sha256", "encoder_text_sha256", "transport_input_sha256"):
            _hash(row[field], field)
        _require(row["source_sha256"] == _text_sha(row["source_text"]), "original source SHA256 mismatch")
        _context(row["context"])
        _require(row["original_input_sha256"] == _original_input_sha(row), "original source/context input SHA256 mismatch")
        expected_forwarded = row["arm_id"] == "declared_context" and row["context"]["role"] == "explicit_assumptions"
        _require(row["context_forwarded"] is expected_forwarded and row["context_semantics_applied"] is False,
                 "context forwarding cannot claim semantic interpretation")
        total += _text(row["encoder_text"], "rendered encoder text")
        _require(total <= MAX_TOTAL_ENCODER_BYTES, "total encoder text byte bound exceeded")
        _require(row["encoder_text"] == _render(row) and row["encoder_text_sha256"] == _text_sha(row["encoder_text"]),
                 "rendered source/context text differs from fixed serialization")
        _require(row["transport_input_sha256"] == _transport_sha(row)
                 and row["id"] == row["transport_id"] == "sha256:" + row["transport_input_sha256"],
                 "context transport identity mismatch")
        identities.append(row["id"])
        forwarded += expected_forwarded
        group = originals.setdefault(row["original_input_sha256"], {})
        _require(row["arm_id"] not in group, "duplicate input arm")
        group[row["arm_id"]] = row
    _require(identities == sorted(set(identities)), "context input IDs must be sorted and unique")
    _require(len(originals) == MAX_ORIGINAL_ROWS and all(set(group) == set(ARMS) for group in originals.values()),
             "each of 34 original inputs requires exactly two arms")
    for group in originals.values():
        first, second = (group[arm] for arm in ARMS)
        _require(_raw({key: first[key] for key in ("domain_id", "logic_family", "source_text", "source_sha256", "context")}) ==
                 _raw({key: second[key] for key in ("domain_id", "logic_family", "source_text", "source_sha256", "context")}),
                 "both arms must preserve the identical original input")
    _require(type(inputs["original_row_count"]) is int and inputs["original_row_count"] == len(originals)
             and type(inputs["row_count"]) is int and inputs["row_count"] == len(rows)
             and type(inputs["context_forwarded_rows"]) is int and inputs["context_forwarded_rows"] == forwarded,
             "context input counts mismatch")
    _integrity(inputs)
    return {"status": "validated", "input_manifest_sha256": inputs["payload_sha256"], "original_inputs": len(originals),
            "rows": len(rows), "context_forwarded_rows": forwarded, "encoder_utf8_bytes": total,
            "original_input_identity_recomputed": True, "context_semantics_applied": False,
            "qualified": False, "proof_authority": False}


def prepare_context_transport(inputs: dict) -> dict:
    """Return literal rendered text in the frozen producer's compatibility schema.

    Its source hashes concern JSON transport bytes. Inner context is empty; the
    outer manifest is the authority for original source/context relationships.
    This record must not be presented as the original source-only experiment.
    """
    validate_context_embedding_inputs(inputs)
    owner = _producer()
    rows = [{"id": row["transport_id"], "input_sha256": row["transport_input_sha256"],
             "source_text": row["encoder_text"], "source_sha256": row["encoder_text_sha256"],
             "context_role": "none_required", "context_applied": False} for row in inputs["rows"]]
    transport = _seal({"schema": owner.INPUT_SCHEMA, "input_recipe": owner.INPUT_RECIPE,
                       "identity_recipe": owner.IDENTITY_RECIPE, "rows": rows, "row_count": len(rows),
                       "context_unapplied_rows": 0, "all_context_unapplied": True,
                       "qualified": False, "proof_authority": False})
    owner.validate_richer_embedding_inputs(transport)
    return transport


def _outer_receipt(row, native, lane_id):
    return {"id": row["id"], "arm_id": row["arm_id"], "original_input_sha256": row["original_input_sha256"],
            "source_sha256": row["source_sha256"], "context_sha256": row["context"]["sha256"],
            "context_role": row["context"]["role"], "encoder_text_sha256": row["encoder_text_sha256"],
            "context_forwarded": row["context_forwarded"], "context_semantics_applied": False,
            "transport_input_sha256": row["transport_input_sha256"], "transport_id": row["transport_id"],
            "representation_profile_id": f"{RENDER_SCHEMA}:{lane_id}:arm={row['arm_id']}",
            "status": native["status"], "embedding": deepcopy(native["embedding"]),
            "embedding_sha256": native["embedding_sha256"], "token_count": native["token_count"],
            "token_input_sha256": native["token_input_sha256"], "backend_input_id": native["backend_input_id"],
            "normalized_encoder_text_sha256": native["normalized_source_sha256"]}


def _expected_lane(inputs, transport, native):
    lane_id = native["lane_id"]
    receipts = ([_outer_receipt(row, receipt, lane_id) for row, receipt in zip(inputs["rows"], native["receipts"], strict=True)]
                if native["receipts"] else [])
    return _seal({"schema": SCHEMA, "lane_id": lane_id, "dimension": native["dimension"], "status": native["status"],
                  "input_manifest_sha256": inputs["payload_sha256"], "input_recipe": INPUT_RECIPE,
                  "context_profile_id": f"{RENDER_SCHEMA}:{lane_id}:two_fixed_arms/v1",
                  "transport_inputs": deepcopy(transport), "transport_lane": deepcopy(native), "receipts": receipts,
                  "issues": deepcopy(native["issues"]), "encoder_execution_executed": native["encoder_execution_executed"],
                  "model_inference_executed": native["model_inference_executed"], **dict.fromkeys(_FALSE_FIELDS, False)})


def _wrap_context_lane(inputs: dict, transport_lane: dict) -> dict:
    """Pure wrapping also permits truthful, nonexecuted diagnostic test fixtures."""
    transport = prepare_context_transport(inputs)
    _producer().validate_embedding_lane(transport_lane, transport)
    result = _expected_lane(inputs, transport, transport_lane)
    validate_context_embedding_lane(result, inputs)
    return result


def run_context_lane(inputs: dict, lane_id: str, **ownerkwargs) -> dict:
    """Forward all 68 rendered texts once to the selected frozen native producer."""
    _require(type(lane_id) is str and lane_id in DIMENSIONS, "known native context lane required")
    allowed = {"legacy8": {"backend"}, "native384": {"snapshot_path", "batch_size"},
               "native768": {"manifest_path", "expected_manifest_sha256", "model_directory", "code_directory", "batch_size"}}
    _require(set(ownerkwargs) <= allowed[lane_id], "only native producer options are accepted")
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _LOADED_SHA256,
             "context wrapper source changed after import")
    transport = prepare_context_transport(inputs)
    owner = _producer()
    producer = {"legacy8": owner.run_spacy8, "native384": owner.run_gte384, "native768": owner.run_gte768}[lane_id]
    native = producer(transport, **ownerkwargs)
    _require(type(native) is dict and native.get("lane_id") == lane_id, "native producer returned another lane")
    return _wrap_context_lane(inputs, native)


def validate_context_embedding_lane(result: dict, inputs: dict) -> dict:
    """Replay outer linkage and frozen native receipt admission without inference."""
    _raw(result)
    _closed(result, _LANE_KEYS, "context embedding lane")
    transport = prepare_context_transport(inputs)
    _require(_raw(result["transport_inputs"]) == _raw(transport), "inner rendered-text transport manifest differs")
    validation = _producer().validate_embedding_lane(result["transport_lane"], transport)
    expected = _expected_lane(inputs, transport, result["transport_lane"])
    _require(_raw(result) == _raw(expected), "context lane differs from exact native transport replay")
    return {"status": "validated", "lane_id": result["lane_id"], "dimension": result["dimension"],
            "receipt_count": len(result["receipts"]), "embedded_count": validation["embedded_count"],
            "production_status": result["status"], "input_manifest_sha256": inputs["payload_sha256"],
            "context_forwarded_rows": inputs["context_forwarded_rows"], "runtime_cryptographically_attested": False,
            **dict.fromkeys(_FALSE_FIELDS, False)}


__all__ = ["prepare_context_embedding_inputs", "validate_context_embedding_inputs", "prepare_context_transport",
           "run_context_lane", "validate_context_embedding_lane"]
