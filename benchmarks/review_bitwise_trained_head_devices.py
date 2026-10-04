"""Ordinary-byte audit of retained trained-head device qualification archives.

This reader imports no model or tensor library and never executes retained
Python. It establishes bounded artifact consistency and recomputes numeric and
timing joins, conditional on the externally pinned result and producer bytes.
Failed, safely closed partial qualification is accepted as a refusal archive;
it never receives a successful numerical or complete-call qualification.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics
import struct

SCHEMA = "retained-trained-head-bitwise-device-qualification/v1"
BENCHMARK_SHA = "29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110"
HISTORICAL_BENCHMARK_SHA = "48b80d72d4b92ccbcfa9d2949b342fd744b5533f1e60f602f25af6853828e86f"
HISTORICAL_FORMULA_SHA = "5e8e3144d82aaf5b79a6d3fe30d61523bd835e9a3fcf2492fae2dec4cfa1a134"
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
FIXED_SOURCES = {
    "benchmark": BENCHMARK_SHA,
    "cleanup_helper": "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c",
    "modal_latent_formula_bitwise_device_inference": "5b5631eb1cf779ea8b6fcf3073d074355f52ef8c74adea84fc595421dea85089",
    "legal_span_device_bitwise_inference": "d1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91",
    "owned_tensor_bitwise_guard": "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34",
}
FIXTURES = {
    "formula8_checkpoint": "09558c8db4455bf3caad1f287cea9448da47393fe0fae1c5c140f0ff00e0e466",
    "formula384_checkpoint": "7d8d0e60f7d644bed06e0a48ffc82c014c9ed697d89b9cdc2e4a5d55863885ce",
    "formula8_training_inputs": "212b4817fd074e9c3f9c76c53485774ad44083b65c691938bb80e2962723a30c",
    "formula384_training_inputs": "febf18138dbe1bc8480f06d43586a35453db55c3d8493c03a57ed848dab6093f",
    "span768_checkpoint": "9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b",
    "span768_sources": "eec38602f9d3c3b0c1511ab05b473bbcf2bb3647ac1c4854e899fb0200ad4e46",
    "span768_historical_encoder_outputs": "f728dab53925cd2f9d053d760dcafab756ed718197a8649f24c2000bfc73c221",
}
SOURCE_ROLES = {"benchmark", "cleanup_helper", "resource_scheduler", "modal_latent_formula",
    "modal_latent_formula_inference", "modal_latent_formula_device_inference",
    "modal_latent_formula_bitwise_device_inference", "legal_span_formula", "legal_span_dimensions",
    "legal_span_device_inference", "legal_span_device_batch_inference", "legal_span_device_bitwise_inference",
    "legal_formula_codec", "legal_ir_grammar_decoder", "legal_ir_family_evaluator", "snapshot_evaluator",
    "owned_tensor_value_guard", "owned_tensor_bitwise_guard", "checkpoint_content_guard",
    "runtime_telemetry", "proof_resource_safety", "tree_pin", "canonical_contracts", "cid_utils"}
FALSE_FLAGS = ("production_qualified", "proof_authority", "execution_attestation", "semantic_correctness_verified",
    "fresh_encoder_execution_qualified", "native_encoder_origin_authenticated", "kernel_resource_enforcement",
    "universal_speedup_claimed", "persistent_precision_policy_mutated", "foreign_process_actions")
COUNTS, LANES = (1, 16, 32), ("original_cpu_reference", "bitwise_cpu_opt_out", "original_cuda", "bitwise_cuda")
OUTPUTS = ("modality", "presence", "start", "end")
MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES = 8 * 1024**2, 64 * 1024**2, 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result
    def finite_float(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite JSON exponent")
        return parsed
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite_float,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))


AUTHORITY_FALSE = {"qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
    "semantic_correctness_verified", "promotion_performed", "publication_performed", "lake_executed",
    "source_semantics_verified", "execution_attestation", "production_admission", "native_cuda_qualified",
    "performance_qualified", "semantic_qualification", "kernel_resource_enforcement", "training_executed",
    "target_access", "teacher_forcing"}


def _authority(value):
    if type(value) is dict:
        for name, item in value.items():
            if name in AUTHORITY_FALSE:
                _require(item is False, "nested inference authority flag must be plain False: " + name)
            _authority(item)
    elif type(value) is list:
        for item in value:
            _authority(item)


def _directory_fd(path):
    path = Path(path).absolute()
    _require(path.parts[0] == "/" and ".." not in path.parts, "absolute canonical directory required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read(path):
    path = Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical ordinary input parent required")
    parent = _directory_fd(path.parent)
    try:
        parent_identity = os.fstat(parent)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_FILE_BYTES,
                 "bounded single-link ordinary input required")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size == before.st_size,
                     "opened ordinary file kind/size changed")
            raw = stream.read(MAX_FILE_BYTES + 1)
            after_open = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        current_parent = _directory_fd(path.parent)
        try:
            latest = os.fstat(current_parent)
            _require((latest.st_dev, latest.st_ino) == (parent_identity.st_dev, parent_identity.st_ino),
                     "ordinary file parent changed during read")
        finally:
            os.close(current_parent)
    finally:
        os.close(parent)
    identities = [(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
                  for s in (before, opened, after_open, after)]
    _require(all(item == identities[0] for item in identities[1:]) and len(raw) == before.st_size,
             "ordinary input identity changed while reading")
    return raw


def _inventory(root):
    """The fixed producer creates only two flat directories; cap each entry."""
    descriptor = _directory_fd(root)
    files, directories, entries = set(), set(), 0
    try:
        with os.scandir(descriptor) as listing:
            for item in listing:
                entries += 1
                _require(entries <= MAX_FILES + 2, "bounded archive entry count exceeded")
                info = item.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _require(item.name in {"producers", "fixtures"} and item.name not in directories,
                             "unknown archive directory or depth")
                    directories.add(item.name)
                    child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=descriptor)
                    try:
                        with os.scandir(child) as children:
                            for leaf in children:
                                entries += 1
                                _require(entries <= MAX_FILES + 2, "bounded archive entry count exceeded")
                                leaf_info = leaf.stat(follow_symlinks=False)
                                _require(stat.S_ISREG(leaf_info.st_mode) and leaf_info.st_nlink == 1,
                                         "flat ordinary archive leaves required")
                                files.add(str(root / item.name / leaf.name))
                    finally:
                        os.close(child)
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "ordinary archive files required")
                    files.add(str(root / item.name))
        _require(directories == {"producers", "fixtures"}, "exact bounded producer/fixture directories required")
        return files
    finally:
        os.close(descriptor)


def _pin(path, raw):
    return {"path": str(Path(path).absolute()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _pin_shape(pin):
    _require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
             and type(pin["path"]) is str and Path(pin["path"]).is_absolute()
             and type(pin["bytes"]) is int and 0 < pin["bytes"] <= MAX_FILE_BYTES
             and type(pin["sha256"]) is str and SHA.fullmatch(pin["sha256"]) is not None,
             "exact bounded artifact pin required")


class Archive:
    def __init__(self, root, result):
        self.root, self.result, self.pins, self.used = root, result, {}, set()
        self.public_reports = set()
        entries = result["evidence_files_except_result"]
        _require(type(entries) is list and len(entries) < MAX_FILES, "bounded archive manifest required")
        total = 0
        for pin in entries:
            _pin_shape(pin)
            path = Path(pin["path"])
            _require(path.is_relative_to(root) and path != root / "result.json", "contained unique manifest path required")
            _require(str(path) not in self.pins, "duplicate artifact manifest path")
            _require(path.parent.resolve(strict=True) == path.parent, "canonical artifact parent required")
            total += pin["bytes"]
            _require(total <= MAX_TOTAL_BYTES, "archive aggregate declared byte bound exceeded before read")
            _require(_pin(path, _read(path)) == pin, "retained artifact pin mismatch")
            self.pins[str(path)] = pin
        _require(total == result["evidence_bytes_except_result"] and total + (root / "result.json").stat().st_size <= MAX_TOTAL_BYTES,
                 "archive aggregate byte bound/accounting differs")
        _require(result["evidence_limits"] == {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES, "result_included_in_limits": True}, "archive limits differ")
        ordinary = _inventory(root)
        _require(ordinary == set(self.pins) | {str(root / "result.json")}, "unmanifested or missing archive file")

    def raw(self, pin):
        _pin_shape(pin)
        _require(self.pins.get(pin["path"]) == pin, "referenced artifact missing from exact manifest")
        raw = _read(pin["path"])
        _require(_pin(pin["path"], raw) == pin, "referenced artifact pin changed")
        self.used.add(pin["path"])
        return raw

    def value(self, pin):
        return _json(self.raw(pin))

    def finish(self, *, allow_partial=False):
        partial = []
        if allow_partial:
            pattern = re.compile(r"(formula8|formula384|span768)-(?:"
                r"(?:1|16|32)-pair[0-9]{2}-(?:original_cuda|bitwise_cuda)-(?:result|canonical|projected-vectors)|"
                r"(?:original_cpu_reference|bitwise_cpu_opt_out|original_cuda|bitwise_cuda)-(?:1|16|32|warmup)-(?:result|canonical|projected-vectors|logits)|"
                r"(?:1|16|32)-raw-paired-timings)\.json\Z")
            for path in sorted(set(self.pins) - self.used):
                match = pattern.fullmatch(Path(path).name)
                _require(match is not None and match[1] in self.result["families"], "unjoined artifact is not bounded partial evidence")
                _authority(_json(self.raw(self.pins[path])))
                partial.append({"pin": self.pins[path], "scope": "failed_partial_return_unjoined_no_numeric_or_timing_qualification"})
        _require(self.used == set(self.pins), "manifest contains unjoined evidence")
        for pin in self.pins.values():
            _require(_pin(pin["path"], _read(pin["path"])) == pin, "artifact changed during audit")
        _require(_inventory(self.root) == set(self.pins) | {str(self.root / "result.json")},
                 "archive inventory changed during audit")
        return partial


def _marker(value):
    if value is None:
        return None
    _require(type(value) is float and math.isfinite(value), "finite score diagnostic or None required")
    return {"known_finite_numeric_diagnostic_value_excluded": True}


def _decisions(report, family):
    result = deepcopy(report)
    excluded = (("inference_implementation",) if family == "formula" else
        ("execution_profile", "actual_forward_batches", "cuda_executed", "numerical_batching",
         "batch_memory_bound", "cpu_head_output_materializations", "device_to_cpu_head_transfers",
         "canonical_decision_device", "valid_source_count"))
    for name in excluded:
        result.pop(name, None)
    for row in result["rows"]:
        if "minimum_decision_logit_margin" in row:
            row["minimum_decision_logit_margin"] = _marker(row["minimum_decision_logit_margin"])
        if "span_diagnostics" in row:
            diagnostics = row["span_diagnostics"]
            if "modality_logits" in diagnostics:
                logits = diagnostics["modality_logits"]
                _require(type(logits) is list and len(logits) == 3 and None not in logits, "complete modality scores required")
                diagnostics["modality_logits"] = [_marker(value) for value in logits]
            for facet in diagnostics["facets"].values():
                for name in ("presence_logit_margin", "span_logit_margin"):
                    if name in facet:
                        facet[name] = _marker(facet[name])
    return result


def _numeric(expected, actual):
    if type(expected) is list:
        _require(type(actual) is list and len(expected) == len(actual) and len(expected) > 0,
                 "complete numeric nested shape differs")
        return max(_numeric(a, b) for a, b in zip(expected, actual))
    _require(type(expected) in (int, float) and type(actual) in (int, float)
             and math.isfinite(expected) and math.isfinite(actual), "finite complete numeric values required")
    error = abs(expected - actual)
    _require(error <= 5e-5, "complete numeric absolute5e-5 parity exceeded")
    return error


def _positive(value):
    _require(type(value) is float and math.isfinite(value) and value > 0, "positive finite timing required")
    return value


def _float32(value):
    _require(type(value) is float and math.isfinite(value), "finite plain-float float32 scalar required")
    packed = struct.pack("<f", value)
    _require(struct.unpack("<f", packed)[0] == value, "declared float32 value is not exactly representable")
    return packed


def _shape(value, dimensions, *, float32=False):
    if not dimensions:
        _require(type(value) in (float, int) and math.isfinite(value), "finite logit scalar required")
        if float32:
            _float32(value)
        return
    _require(type(value) is list and len(value) == dimensions[0], "complete four-logit shape differs")
    for item in value:
        _shape(item, dimensions[1:], float32=float32)


def _model_bytes(checkpoint):
    parts = []
    def append(value):
        if type(value) is list:
            _require(len(value) > 0, "nonempty checkpoint tensor shape required")
            for item in value:
                append(item)
        else:
            parts.append(_float32(value))
    for name in sorted(checkpoint["model_state"]):
        append(checkpoint["model_state"][name])
    raw = b"".join(parts)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "tensor_count": len(checkpoint["model_state"]), "byte_order": "little_endian_float32"}


def _sources(profile, family, bitwise, checkpoint, pins):
    if family == "formula":
        inherited = profile["inherited_device_implementation"] if bitwise else profile
        _require(inherited["schema"] == "modal-latent-formula-device-inference/v1"
                 and inherited["source_sha256"] == pins["modal_latent_formula_device_inference"]
                 and inherited["parent"]["schema"] == "modal-latent-formula-inference-implementation/v1"
                 and inherited["parent"]["source_sha256"] == pins["modal_latent_formula_inference"],
                 "formula inherited source provenance differs")
        files = checkpoint["implementation"]["files"]
        _require(all(files[name + ".py"] == pins[name] for name in
                     ("modal_latent_formula", "legal_formula_codec", "legal_ir_grammar_decoder", "canonical_contracts", "tree_pin")),
                 "native checkpoint producer source inventory differs")
        if bitwise:
            _require(profile["source_sha256"] == pins["modal_latent_formula_bitwise_device_inference"]
                     and profile["native_checkpoint_implementation"] == checkpoint["implementation"]
                     and profile["checkpoint_guard_source_sha256"] == pins["checkpoint_content_guard"]
                     and profile["resource_scheduler_source_sha256"] == pins["resource_scheduler"]
                     and profile["bitwise_guard_implementation"]["source_sha256"] == pins["owned_tensor_bitwise_guard"]
                     and profile["lineage_id"] == checkpoint["binding"]["lineage_id"]
                     and profile["adam_restoration_performed"] is True and profile["adam_restore_count"] == 1
                     and profile["optimizer_steps_executed"] == 0,
                     "new formula source/checkpoint/restoration provenance differs")
    else:
        expected_base = {"canonical": pins["canonical_contracts"], "codec": pins["legal_formula_codec"],
            "grammar": pins["legal_ir_grammar_decoder"], "span": pins["legal_span_formula"]}
        _require(checkpoint["implementation"] == {"base_span": expected_base, "dimensions_sha256": pins["legal_span_dimensions"]},
                 "native768 checkpoint producer inventory differs")
        resident = {"source_sha256": pins["legal_span_device_inference"], "native_checkpoint_producers": checkpoint["implementation"]}
        batch = {"source_sha256": pins["legal_span_device_batch_inference"],
            "resident_source_sha256": pins["legal_span_device_inference"], "native_checkpoint_producers": resident}
        _require(profile["implementation"] == resident and profile["batched_implementation"] == batch
                 and profile["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest()
                 and profile["optimizer_state_sha256"] == hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest(),
                 "native768 resident/batch/checkpoint/Adam provenance differs")
        if bitwise:
            implementation = profile["bitwise_session_implementation"]
            _require(implementation["source_sha256"] == pins["legal_span_device_bitwise_inference"]
                     and implementation["inherited_batched_implementation"] == batch
                     and implementation["bitwise_guard_implementation"]["source_sha256"] == pins["owned_tensor_bitwise_guard"]
                     and implementation["boundary_consolidation_performed"] is False
                     and implementation["source_verification_success_cached"] is False,
                     "new native768 bitwise source provenance differs")


def _tokens(text):
    return [{"text": match.group(), "start": match.start(), "end": match.end()}
            for match in re.finditer(r"\w+|[^\w\s]", text, re.UNICODE)]


def _row_inputs(report, family, count, inputs, checkpoint):
    if family == "formula":
        _require(_wire(report["binding"]) == _wire(checkpoint["binding"]), "formula report binding differs from fixed checkpoint")
        rows = inputs["rows"][:count]
    else:
        _require(report["lineage_id"] == checkpoint["lineage_id"] and report["input_dimension"] == 768
                 and report["source_parent_checkpoint_sha256"] == checkpoint["source_parent_checkpoint_sha256"]
                 and report["context_contract_sha256"] == checkpoint["context_contract_sha256"]
                 and report["latent_ablation"] == "none", "native768 public checkpoint/context binding differs")
        receipts = report["input_receipts"]
        _require(receipts["status"] == "externally_content_pinned" and receipts["signature_verified"] is False
                 and receipts["semantic_qualification"] is False
                 and receipts["receipt_sha256s"] == inputs["receipt_pins"][:count]
                 and receipts["context_producer_sha256"] == checkpoint["context_contract"]["producer_sha256"]
                 and receipts["profile_sha256s"] == [row["profile_sha256"] for row in inputs["receipts"][:count]],
                 "native768 public historical receipt content join differs")
        rows = [{"source_text": text, "latent": vector} for text, vector in
                zip(inputs["texts"][:count], inputs["vectors"][:count])]
    decoded = 0
    for returned, expected in zip(report["rows"], rows):
        _require(returned["source_sha256"] == hashlib.sha256(expected["source_text"].encode()).hexdigest()
                 and returned["latent_sha256"] == hashlib.sha256(_wire(expected["latent"])).hexdigest(),
                 "public row source/latent hash differs from exact reconstructed input")
        if family == "formula":
            _require(returned["id"] == expected["id"] and returned["projection_id"] == checkpoint["projection_id"],
                     "formula row id/projection binding differs")
        else:
            diagnostics = returned["span_diagnostics"]
            tokens = _tokens(expected["source_text"])
            _require(diagnostics["tokens"] == tokens, "span diagnostics tokens differ from exact source offsets")
            _shape(diagnostics["modality_logits"], (3,), float32=True)
            _require(type(diagnostics["facets"]) is dict, "closed span facet diagnostics required")
            for diagnostic in diagnostics["facets"].values():
                _require(type(diagnostic["present"]) is bool, "plain facet presence decision required")
                if diagnostic["present"]:
                    left, right = diagnostic["token_start"], diagnostic["token_end_inclusive"]
                    _require(type(left) is int and type(right) is int and 0 <= left <= right < len(tokens)
                             and diagnostic["char_start"] == tokens[left]["start"]
                             and diagnostic["char_end"] == tokens[right]["end"]
                             and diagnostic["text"] == expected["source_text"][tokens[left]["start"]:tokens[right]["end"]],
                             "selected facet token/character/text offsets differ from exact source")
                else:
                    _require(all(diagnostic[name] is None for name in
                        ("token_start", "token_end_inclusive", "char_start", "char_end", "text", "span_logit_margin")),
                        "absent facet has selected span metadata")
        decoded += returned["status"] == "decoded"
    _require(type(report["decoded_count"]) is int and report["decoded_count"] == decoded
             and report["status"] == ("decoded" if decoded == count else "partial" if decoded else "abstained"),
             "public decoded/status arithmetic differs")


def _round32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _span_decision(text, logits):
    """Independent scalar decision/offset join, with explicit float32 sums."""
    tokens, facets = _tokens(text), {}
    scores = logits["modality"][0]
    rank = sorted(range(3), key=lambda index: (-scores[index], index))
    minimum = _round32(scores[rank[0]] - scores[rank[1]])
    result = {"modality_logits": scores, "facets": facets, "minimum": None,
              "canonical_ir": None, "status": "abstained", "reason": "ambiguous_decoder_scores"}
    if minimum <= 1e-7:
        return result
    rule, occupied = {"modality": ("O", "P", "F")[rank[0]]}, set()
    fields, optional = ("actor", "action", "object", "conditions", "exceptions", "temporal"), ("object", "conditions", "exceptions", "temporal")
    for index, field in enumerate(fields):
        present, margin = True, None
        if field in optional:
            presence = logits["presence"][0][optional.index(field)]
            margin = abs(_round32(presence[1] - presence[0]))
            if margin <= 1e-7:
                return result
            minimum, present = min(minimum, margin), presence[1] > presence[0]
        diagnostic = {"present": present, "presence_logit_margin": margin, "token_start": None,
            "token_end_inclusive": None, "char_start": None, "char_end": None, "text": None, "span_logit_margin": None}
        atom = ""
        if present:
            values = [(_round32(logits["start"][0][index][left] + logits["end"][0][index][right]), left, right)
                      for left in range(len(tokens)) for right in range(left, len(tokens))]
            values.sort(key=lambda item: -item[0])  # stable row-major tie order
            span_margin = _round32(values[0][0] - values[1][0]) if len(values) > 1 else None
            if span_margin is not None and span_margin <= 1e-7:
                return result
            if span_margin is not None:
                minimum = min(minimum, span_margin)
            _, left, right = values[0]
            begin, end = tokens[left]["start"], tokens[right]["end"]
            atom = text[begin:end]
            diagnostic.update(token_start=left, token_end_inclusive=right, char_start=begin,
                char_end=end, text=atom, span_logit_margin=span_margin)
            positions = set(range(left, right + 1))
            if occupied & positions:
                facets[field] = diagnostic
                result["reason"] = "copied_spans_overlap"
                return result
            occupied.update(positions)
        rule[field] = ([atom] if present else []) if field in ("conditions", "exceptions", "temporal") else atom
        facets[field] = diagnostic
    result.update(status="decoded", reason=None, canonical_ir={"rules": [rule]}, minimum=minimum)
    return result


def _span_join(report, panels):
    _require(len(report["rows"]) == len(panels), "private/public span decision coverage differs")
    for row, panel in zip(report["rows"], panels):
        diagnostics = row["span_diagnostics"]
        _numeric(panel["modality_logits"], diagnostics["modality_logits"])
        _require(row["status"] == panel["status"] and row["reason"] == panel["reason"]
                 and _wire(row["canonical_ir"]) == _wire(panel["canonical_ir"])
                 and set(diagnostics["facets"]) == set(panel["facets"]), "private logits/public span decisions differ")
        for field, expected in panel["facets"].items():
            actual = diagnostics["facets"][field]
            _require(set(actual) == set(expected), "complete public facet diagnostic keys differ")
            for name, value in expected.items():
                if name in ("presence_logit_margin", "span_logit_margin") and value is not None:
                    _numeric(value, actual[name])
                else:
                    _require(actual[name] == value and type(actual[name]) is type(value), "private logits/public facet decision differs")
        if panel["minimum"] is not None:
            _numeric(panel["minimum"], row["minimum_decision_logit_margin"])
        if panel["canonical_ir"] is not None:
            _require(len(row["formal_outputs"]) == 1
                     and _wire(row["formal_outputs"][0]["payload"]) == _wire(panel["canonical_ir"]["rules"][0]),
                     "public formal payload differs from selected private logits")


def _span_numeric(archive, observation, count, token_lengths, *, label, stem):
    _require(observation["complete_four_logits"]["path"] == str(archive.root / (stem + "-logits.json")),
             "exact numeric panel filename required")
    rows = archive.value(observation["complete_four_logits"])
    _require(type(rows) is list and len(rows) == count, "complete four-logit row count differs")
    for index, row in enumerate(rows):
        _require(type(row) is dict and set(row) == set(OUTPUTS), "all four native768 heads required")
        _shape(row["modality"], (1, 3), float32=True)
        _shape(row["presence"], (1, 4, 2), float32=True)
        _require(type(row["start"]) is list and len(row["start"]) == 1
                 and type(row["start"][0]) is list and len(row["start"][0]) == 6,
                 "complete native768 span logit rank differs")
        width = len(row["start"][0][0])
        _require(1 <= width <= 256, "bounded complete source token logit width required")
        _require(width == token_lengths[index], "complete span logits do not cover exact source token width")
        _shape(row["start"], (1, 6, width), float32=True)
        _shape(row["end"], (1, 6, width), float32=True)
    scope = observation["numeric_snapshot_scope"]
    cuda = "cuda" in label
    device = f"cuda:{archive.result['hardware']['device_index']}" if cuda else "cpu"
    _require(type(scope["singletons"]) is bool and scope["singletons"] is (not cuda),
             "numeric singleton/batched scope differs from admitted lane")
    _require(scope["scope"] == "separate_checked_private_four_logit_forward_outside_public_timing"
             and scope["coverage"] == "one_snapshot_per_lane_per_count"
             and scope["entry_and_exit_owned_checks"] is True, "numeric snapshot guard scope differs")
    observations = scope["observations"]
    _require(len(observations) == (count if scope["singletons"] else 1), "numeric forward observation coverage differs")
    for index, forward in enumerate(observations):
        lengths = [token_lengths[index]] if scope["singletons"] else token_lengths
        _require(forward["rows"] == len(lengths) and forward["source_tokens"] == lengths
                 and forward["native_input_dimension"] == 768 and forward["output_dtype"] == "float32"
                 and forward["gru_executed"] is True and set(forward["output_devices"]) == set(OUTPUTS)
                 and all(value == forward["input_device"] for value in forward["output_devices"].values()),
                 "numeric observed device/token/forward coverage differs")
        _require(forward["input_device"] == device, "numeric snapshot device differs from lane")
        if forward["input_device"].startswith("cuda:"):
            precision = forward.get("gru_precision")
            _require(type(precision) is dict, "native768 numeric CUDA GRU scope missing")
            _require(precision["profile_id"] == "native-768-source-span-device-strict-cuda-float32/v2"
                     and precision["scoped_cudnn"] is True
                     and precision["effective_policy"]["cudnn"]["allow_tf32"] is False
                     and precision["synchronized_before_restore"] is True and precision["ambient_flags_restored"] is True,
                     "native768 numeric strict CUDA scope differs")
    return rows


def _four_errors(reference, actual):
    _require(len(reference) == len(actual), "native768 numeric row coverage differs")
    return {name: max(_numeric(left[name], right[name]) for left, right in zip(reference, actual)) for name in OUTPUTS}


def _observation(archive, observation, family, width, count, cp_sha, *, label, stem, inputs, checkpoint,
                 reference=None, reference_numeric=None):
    expected_report = str(archive.root / (stem + "-result.json"))
    _require(observation["result"]["path"] == expected_report
             and observation["canonical_projection"]["path"] == str(archive.root / (stem + "-canonical.json"))
             and expected_report not in archive.public_reports, "unique exact public-return filename required")
    archive.public_reports.add(expected_report)
    report = archive.value(observation["result"])
    _authority(report)
    canonical = archive.value(observation["canonical_projection"])
    _require(report["checkpoint_sha256"] == cp_sha and type(report["rows"]) is list and len(report["rows"]) == count,
             "retained public report checkpoint/row coverage differs")
    _require(report["training_executed"] is False and report["target_access"] is False
             and report["teacher_forcing"] is False and report["proof_authority"] is False,
             "public inference scope flags differ")
    _row_inputs(report, family, count, inputs, checkpoint)
    _require(_wire(canonical) == _wire(_decisions(report, family)), "canonical projection differs from raw report")
    _positive(observation["elapsed_seconds"])
    _require(observation["cpu_cuda_rng_unchanged"] is True, "RNG unchanged receipt missing")
    cuda, bitwise = "cuda" in label, label.startswith("bitwise")
    profile = report["inference_implementation"] if family == "formula" else report["execution_profile"]
    device = f"cuda:{archive.result['hardware']['device_index']}" if cuda else "cpu"
    _require(type(profile["dimension"]) is int and profile["dimension"] == width
             and profile["optimized"] is cuda and profile["device"] == device and profile["dtype"] == "float32",
             "public actual lane device/optimization/dimension differs")
    if family == "formula":
        _require(profile["cuda_selected"] is cuda and profile["cuda_executed"] is cuda
                 and profile["actual_forward_executed"] is True
                 and set(profile["actual_forward_calls"]) == {"projection_down", "projection_up", "output"}
                 and all(type(value) is int and value > 0 for value in profile["actual_forward_calls"].values()),
                 "actual formula projection/generation forward receipt differs")
    else:
        _require(report["cuda_executed"] is cuda and profile["profile_id"] ==
                 ("native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1" if bitwise and cuda else
                  "native-768-source-span-batched-device-float32-cpu-decisions/v1"),
                 "actual native768 execution profile differs")
        _require(len(report["actual_forward_batches"]) == (1 if cuda else count),
                 "public native768 actual forward batch coverage differs")
    _sources(profile, family, bitwise, checkpoint, archive.source_shas)
    if family == "span" or bitwise:
        child = archive.children[(family, width, bitwise, cuda)]
        observed_lease = profile["resource_lease"]
        _require(all(observed_lease[key] == child["admission"][key] for key in
            ("lease_id", "parent_lease_id", "owner_pid", "cpu_slots", "memory_mb", "gpu_memory_mb", "unified_memory_mb", "requires_gpu"))
                 and observed_lease["released"] is False and observed_lease["cancelled"] is False,
                 "public owned lease differs from exact admitted child")
    if bitwise:
        expected_profile = ("modal-latent-formula-bitwise-owned-device-float32/v1" if family == "formula" else
                            "native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1")
        _require(profile["profile_id" if family == "formula" else "session_profile_id"] == expected_profile,
                 "new session identity differs")
        guard, anchor = profile["owned_tensor_currentness"], profile["reference_byte_currentness"]
        _require(guard["mode"] == ("cuda_bitwise_single_host_decision" if cuda else "cpu_reference_checks")
                 and all(guard[key] is True for key in ("all_current_values_checked", "finite_values_checked", "signed_zero_checked"))
                 and guard["implementation"]["source_sha256"] == FIXED_SOURCES["owned_tensor_bitwise_guard"],
                 "new tensor-currentness guard receipt differs")
        origin = ("validated_cpu_checkpoint_model_before_reference_clone_and_upload" if family == "formula" else
                  "independently_restored_validated_cpu_checkpoint_model_before_upload")
        _require(anchor["checkpoint_sha256"] == cp_sha and anchor["origin"] == origin
                 and anchor["anchor_identity_checked"] is True and anchor["reference_device"] == profile["device"]
                 and anchor["device_to_cpu_reference_transfers"] == int(cuda)
                 and anchor["metadata_and_reservation_checked_before_allocation"] is True,
                 "new independent checkpoint byte anchor receipt differs")
        byte_plan = archive.model_byte_plans[cp_sha]
        _require(anchor["anchor_sha256"] == byte_plan["sha256"] and type(anchor["reference_bytes"]) is int
                 and anchor["reference_bytes"] == byte_plan["bytes"], "anchor differs from independently reconstructed checkpoint bytes")
        _require(guard["schema"] == "owned-tensor-bitwise-value-guard/v1"
                 and guard["implementation"]["schema"] == "owned-tensor-bitwise-guard-implementation/v1"
                 and guard["implementation"]["comparison"] == "finite-float32-exact-bits-with-reference-finiteness/v1"
                 and guard["comparison_device"] == device and type(guard["tensor_count"]) is int
                 and guard["tensor_count"] == byte_plan["tensor_count"]
                 and type(guard["state_and_reference_bytes"]) is int and guard["state_and_reference_bytes"] == 2 * byte_plan["bytes"]
                 and type(guard["host_decision_count"]) is int
                 and (guard["host_decision_count"] == 1 if cuda else guard["host_decision_count"] == 4 * byte_plan["tensor_count"]),
                 "current tensor guard metadata differs from checkpoint/lane")
    if reference is not None:
        _require(_wire(reference) == _wire(canonical), "exact canonical decisions differ from CPU reference")
        _require(observation["canonical_matches_original_cpu"] is True, "canonical parity receipt missing")
    projected = None
    if family == "formula":
        projected = archive.value(observation["projected_vectors"])
        _require(observation["projected_vectors"]["path"] == str(archive.root / (stem + "-projected-vectors.json")),
                 "exact complete formula projection filename required")
        _shape(projected, (count, width), float32=True)
        if reference_numeric is not None:
            error = _numeric(reference_numeric, projected)
            _require(observation["complete_projection_max_abs_error"] == error,
                     "complete formula numeric error arithmetic differs")
    return canonical, projected, report


def _inputs(archive, entry, role, fixtures):
    inputs = archive.value(entry["inputs"])
    width, family = entry["dimension"], entry["family"]
    _require(inputs["dimension"] == width and inputs["encoder_execution_performed"] is False,
             "inference input family scope differs")
    if family == "formula":
        _require(inputs["schema"] == "retained-trained-formula-inference-inputs/v1"
                 and inputs["target_fields_excluded"] is True and len(inputs["rows"]) == 32,
                 "formula inference input scope differs")
        saved = fixtures[role + "_training_inputs"]
        expected = [{"id": f"trained-formula{width}-inference-{index}",
            "source_text": saved[index % len(saved)]["source_text"],
            "latent": saved[index % len(saved)]["latent"]} for index in range(32)]
        _require(_wire(inputs["rows"]) == _wire(expected), "formula inference inputs differ from stripped retained fixture")
        for row in inputs["rows"]:
            _require(set(row) == {"id", "source_text", "latent"}, "formula inference target leakage")
            _shape(row["latent"], (width,))
    else:
        saved, sources = fixtures["span768_historical_encoder_outputs"], fixtures["span768_sources"]
        _require(inputs["schema"] == "retained-native768-historical-content-inference-inputs/v1"
                 and inputs["receipt_pin_authority"] == "historical_content_only", "historical receipt authority differs")
        _require(inputs["texts"] == [row["source_text"] for row in sources]
                 and inputs["vectors"] == saved["vectors"] and inputs["receipts"] == saved["receipts"],
                 "native768 source/vector/receipt retained joins differ")
        expected_pins = [hashlib.sha256(_wire(receipt)).hexdigest() for receipt in saved["receipts"]]
        _require(inputs["receipt_pins"] == expected_pins and len(inputs["texts"]) == 32,
                 "native768 historical receipt content digest differs")
        _shape(inputs["vectors"], (32, 768))
        context = fixtures["span768_checkpoint"]["context_contract"]
        for text, vector, receipt in zip(inputs["texts"], inputs["vectors"], inputs["receipts"]):
            _require(receipt["profile_id"] == context["representation_id"] and receipt["dimension"] == 768
                     and receipt["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
                     and receipt["embedding"] == vector and receipt["truncated"] is False and receipt["normalized"] is True
                     and receipt["embedding_sha256"] == hashlib.sha256(_wire(vector)).hexdigest()
                     and abs(math.sqrt(sum(value * value for value in vector)) - 1.) <= 2e-5
                     and type(receipt["token_count_including_special_tokens"]) is int
                     and 1 <= receipt["token_count_including_special_tokens"] <= 8192
                     and SHA.fullmatch(receipt["token_input_sha256"]) is not None
                     and receipt["proof_authority"] is False and receipt["source_semantics_verified"] is False,
                     "historical receipt source/context/vector/token content join differs")
    return inputs


def _controls(controls):
    labels = {"paired_finite_data_mutation", "paired_signed_zero_data_mutation", "equal_content_anchor_identity_replacement",
              "model_only_positive_subnormal_bits", "paired_finite_after_actual_forward_poll",
              "authored_input_mutation_after_forward_poll", "cancel_before_forward"}
    _require(type(controls) is list and len(controls) == len(labels)
             and {row["control"] for row in controls} == labels, "complete new-session refusal controls required")
    for row in controls:
        name = row["control"]
        if name == "paired_signed_zero_data_mutation" and row.get("applicable") is False:
            _require(row["reason"] == "no actual admitted signed zero tensor element", "signed-zero non-applicability differs")
            continue
        _require(row["refused"] is True and type(row["refusal"]) is str and len(row["refusal"]) > 0,
                 "native refusal receipt missing")
        if name == "cancel_before_forward":
            _require("cancel" in row["refusal"], "cancellation receipt differs")
            continue
        callback = name.endswith("after_actual_forward_poll") or name.endswith("after_forward_poll")
        _require(row["post_forward_callback_executed"] is callback
                 and row["before_forward_refusal"] is (not callback)
                 and type(row["actual_model_forward_calls"]) is int
                 and (row["actual_model_forward_calls"] > 0 if callback else row["actual_model_forward_calls"] == 0),
                 "native control forward-boundary receipt differs")


def _family(archive, role, entry, fixtures, *, complete):
    expected = {"formula8": ("formula", 8), "formula384": ("formula", 384), "span768": ("span", 768)}
    _require(role in expected and (entry["family"], entry["dimension"]) == expected[role], "exact three-family identity required")
    family, width = expected[role]
    cp = fixtures[role + "_checkpoint"]
    sha = FIXTURES[role + "_checkpoint"]
    _require(entry["checkpoint_sha256"] == sha and entry["retained_checkpoint_progress"] == cp["progress"]
             and cp["progress"]["optimizer_steps"] > 0, "retained trained checkpoint identity/progress differs")
    _require(entry["checkpoint_optimizer_sha256"] == hashlib.sha256(_wire(cp["optimizer_state"])).hexdigest(),
             "checkpoint Adam digest differs")
    model_raw = _wire(cp["model_state"])
    model_pin = {"bytes": len(model_raw), "sha256": hashlib.sha256(model_raw).hexdigest()}
    _require(entry["retained_checkpoint_model_pin"] == model_pin, "checkpoint tensor-content digest differs")
    inputs = _inputs(archive, entry, role, fixtures)
    token_lengths = ([len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE)) for text in inputs["texts"]]
                     if family == "span" else None)
    lanes = entry["lanes"]
    _require(set(lanes).issubset(LANES), "unknown lane")
    if complete:
        _require(set(lanes) == set(LANES) and entry["numerical_and_canonical_qualified"] is True,
                 "complete qualified family lanes missing")
    references, numerics, span_panels = {}, {}, {}
    reports, timed, projections, constructors, snapshots = 0, 0, 0, 0, 0
    for label in LANES:
        if label not in lanes:
            continue
        lane = lanes[label]
        constructor = lane["constructor"]
        _positive(constructor["elapsed_seconds"])
        _require(constructor["profiler_scope"] == "constructor_only"
                 and constructor["adam_constructor_calls"] == (1 if family == "formula" else 0),
                 "legitimate Adam constructor observation differs")
        constructors += constructor["adam_constructor_calls"]
        _require(lane["state_before"] == model_pin, "admitted tensor bytes differ from retained checkpoint")
        if "state_after" in lane:
            _require(lane["state_after"] == model_pin and lane["checkpoint_and_adam_unchanged"] is True,
                     "inference/control checkpoint, Adam or tensor closure differs")
        elif complete:
            raise ValueError("complete lane tensor/checkpoint closure missing")
        if "cpu" in label:
            _require(set(lane["counts"]).issubset({"1", "16", "32"}), "unknown CPU count")
            if complete:
                _require(set(lane["counts"]) == {"1", "16", "32"}, "complete CPU count coverage missing")
            for count in COUNTS:
                if str(count) not in lane["counts"]:
                    continue
                observation = lane["counts"][str(count)]
                stem = f"{role}-{label}-{count}"
                canonical, numeric, public = _observation(archive, observation, family, width, count, sha,
                    label=label, stem=stem, inputs=inputs, checkpoint=cp, reference=references.get(count),
                    reference_numeric=numerics.get(count) if family == "formula" else None)
                _require(observation["included_in_paired_timing"] is False, "CPU reference mistakenly in paired timing")
                reports += 1
                projections += family == "formula"
                if family == "span":
                    numeric = _span_numeric(archive, observation, count, token_lengths[:count], label=label, stem=stem)
                    span_panels[label, count] = [_span_decision(text, row) for text, row in zip(inputs["texts"][:count], numeric)]
                    _span_join(public, span_panels[label, count])
                    snapshots += 1
                    if count in numerics:
                        _require(observation["four_logit_max_abs_errors"] == _four_errors(numerics[count], numeric),
                                 "CPU four-logit error arithmetic differs")
                if label == "original_cpu_reference":
                    references[count], numerics[count] = canonical, numeric
        else:
            if "warmup" in lane:
                _, _, warmup_public = _observation(archive, lane["warmup"], family, width, 32, sha,
                             label=label, stem=f"{role}-{label}-warmup", inputs=inputs, checkpoint=cp, reference=references.get(32),
                             reference_numeric=numerics.get(32) if family == "formula" else None)
                _require(lane["warmup"]["included_in_paired_timing"] is False, "warmup mistakenly in paired timing")
                reports += 1
                projections += family == "formula"
            elif complete:
                raise ValueError("complete CUDA warmup coverage missing")
            if family == "span":
                for key, observation in lane["counts"].items():
                    _require(key in {"1", "16", "32"}, "unknown numeric snapshot count")
                    numeric = _span_numeric(archive, observation, int(key), token_lengths[:int(key)],
                                            label=label, stem=f"{role}-{label}-{key}")
                    span_panels[label, int(key)] = [_span_decision(text, row) for text, row in zip(inputs["texts"][:int(key)], numeric)]
                    snapshots += 1
                    _require(observation["four_logit_max_abs_errors"] == _four_errors(numerics[int(key)], numeric),
                             "CUDA four-logit error arithmetic differs")
                if complete:
                    _require(set(lane["counts"]) == {"1", "16", "32"}, "complete CUDA numeric snapshots missing")
                if "warmup" in lane and (label, 32) in span_panels:
                    _span_join(warmup_public, span_panels[label, 32])
    count_entries = entry["counts"]
    _require(set(count_entries).issubset({"1", "16", "32"}), "unknown paired count")
    if complete:
        _require(set(count_entries) == {"1", "16", "32"}, "complete paired count coverage missing")
        _require(entry["paired_admission"]["both_gpu_children_live"] is True,
                 "paired admitted child receipt missing")
    ratios = {}
    for key, count_entry in count_entries.items():
        count, trials = int(key), count_entry["trials"]
        _require(len(trials) == 12 and count_entry["sample_count_each_lane"] == 12
                 and count_entry["first_position_each_lane"] == 6, "twelve balanced paired trials required")
        raw_timing = archive.value(count_entry["raw_timing_evidence"])
        _require(raw_timing == {name: count_entry[name] for name in ("trials", "samples_seconds", "median_seconds")},
                 "raw paired timing evidence differs")
        samples = {"original_cuda": [], "bitwise_cuda": []}
        for index, trial in enumerate(trials):
            order = ["original_cuda", "bitwise_cuda"] if index % 2 == 0 else ["bitwise_cuda", "original_cuda"]
            _require(trial["trial"] == index and trial["order"] == order
                     and set(trial["observations"]) == set(samples), "balanced paired call order/coverage differs")
            for label, observation in trial["observations"].items():
                _, _, public = _observation(archive, observation, family, width, count, sha,
                             label=label, stem=f"{role}-{count}-pair{index:02d}-{label}", inputs=inputs, checkpoint=cp, reference=references[count],
                             reference_numeric=numerics[count] if family == "formula" else None)
                if family == "span":
                    _span_join(public, span_panels[label, count])
                _require(observation["included_in_paired_timing"] is True, "paired observation lacks completed timing")
                samples[label].append(observation["elapsed_seconds"])
                reports += 1
                timed += 1
                projections += family == "formula"
        medians = {label: statistics.median(values) for label, values in samples.items()}
        paired = [a / b for a, b in zip(samples["original_cuda"], samples["bitwise_cuda"])]
        ratio = medians["original_cuda"] / medians["bitwise_cuda"]
        _require(samples == count_entry["samples_seconds"] and medians == count_entry["median_seconds"]
                 and paired == count_entry["paired_original_over_bitwise_ratios"]
                 and ratio == count_entry["median_original_over_bitwise_ratio"], "complete-call timing arithmetic differs")
        ratios[key] = ratio
    if "new_cuda_controls" in entry:
        _controls(entry["new_cuda_controls"])
    elif complete:
        raise ValueError("qualified native mutation/boundary controls missing")
    return {"public_reports": reports, "paired_timed_reports": timed, "formula_projections": projections,
        "span_four_logit_snapshots": snapshots, "adam_constructor_calls": constructors,
        "median_original_over_bitwise_ratios": ratios}


def review(result_path, expected_result_sha256, *, check_current_sources=False):
    _require(type(check_current_sources) is bool and type(expected_result_sha256) is str
             and SHA.fullmatch(expected_result_sha256) is not None, "external result SHA and current-source boolean required")
    result_path = Path(result_path).absolute()
    _require(result_path.name == "result.json", "exact result.json archive entry required")
    raw = _read(result_path)
    result_pin = _pin(result_path, raw)
    _require(result_pin["sha256"] == expected_result_sha256, "external result pin differs")
    result = _json(raw)
    _require(result["schema"] == SCHEMA and type(result["qualified"]) is bool,
             "exact trained-head qualification schema required")
    _require(all(result[name] is False for name in FALSE_FLAGS), "archive exceeds ordinary numeric/measurement authority")
    _require(all(type(result[name]) is int and result[name] == 0 for name in
        ("encoder_calls", "training_calls", "optimizer_steps", "training_mode_true_calls")),
             "archive reports inference training/encoder execution")
    _require(type(result["paired_observations_per_lane_per_count"]) is int and result["paired_observations_per_lane_per_count"] == 12
             and type(result["max_seconds_after_root_admission"]) is int and result["max_seconds_after_root_admission"] == 120
             and type(result["admission_timeout_seconds"]) is int and 1 <= result["admission_timeout_seconds"] <= 60
             and type(result["numeric_tolerance_absolute"]) is float and result["numeric_tolerance_absolute"] == 5e-5,
             "qualification bounds/sample/tolerance differ")
    _require(result["qualified"] is (result["error"] is None)
             and result["complete_call_measurements_qualified"] is result["qualified"],
             "success/refusal qualification flags inconsistent")
    archive = Archive(result_path.parent, result)
    current_pins, verified_source_pins, fixtures = [], [], {}
    archive.source_shas = {pin["role"]: pin["current"]["sha256"] for pin in result["source_pins"]}
    sources = result["source_pins"]
    _require(type(sources) is list and len(sources) == len(SOURCE_ROLES)
             and {pin["role"] for pin in sources} == SOURCE_ROLES, "complete source pin roles required")
    benchmark_pin = next(pin["current"] for pin in sources if pin["role"] == "benchmark")
    historical = benchmark_pin["sha256"] == HISTORICAL_BENCHMARK_SHA
    _require(benchmark_pin["sha256"] in (BENCHMARK_SHA, HISTORICAL_BENCHMARK_SHA)
             and not (historical and result["qualified"]), "qualified current or unqualified historical producer required")
    fixed_source_pins = dict(FIXED_SOURCES)
    if historical:
        fixed_source_pins.update(benchmark=HISTORICAL_BENCHMARK_SHA,
                                modal_latent_formula_bitwise_device_inference=HISTORICAL_FORMULA_SHA)
    fixed = [*sources, result["shared_configuration"], *result["fixture_pins"]]
    _require(len(result["fixture_pins"]) == len(FIXTURES)
             and {pin["role"] for pin in result["fixture_pins"]} == set(FIXTURES), "exact seven fixture roles required")
    _require(result["shared_configuration"]["role"] == "shared_configuration", "configuration pin role differs")
    for pin in fixed:
        current, retained = pin["current"], pin["retained_copy"]
        _pin_shape(current)
        retained_raw = archive.raw(retained)
        _require((current["bytes"], current["sha256"]) == (retained["bytes"], retained["sha256"]),
                 "current/retained pin bytes differ")
        role = pin["role"]
        expected = CONFIG_SHA if role == "shared_configuration" else FIXTURES.get(role) or fixed_source_pins.get(role)
        if expected is not None:
            _require(current["sha256"] == expected, "fixed producer/configuration/fixture pin differs: " + role)
        if check_current_sources:
            if role in SOURCE_ROLES:
                package = Path(__file__).absolute().parent.parent
                special = {"benchmark": Path(__file__).with_name("qualify_bitwise_trained_head_devices.py").absolute(),
                    "cleanup_helper": Path(__file__).with_name("qualify_native_768_device.py").absolute(),
                    "tree_pin": package / "ipfs_datasets_py/logic/autoformal/tree_pin.py",
                    "canonical_contracts": package / "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
                    "cid_utils": package / "ipfs_datasets_py/utils/cid_utils.py"}
                expected_path = special.get(role, package / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / (role + ".py"))
                _require(current["path"] == str(expected_path), "current source path differs from checked repository source")
            verified_pin = _pin(current["path"], _read(current["path"]))
            _require(verified_pin == current, "current source/configuration/fixture pin changed")
            if role in SOURCE_ROLES:
                verified_source_pins.append(verified_pin)
        current_pins.append(current)
        if role in FIXTURES:
            fixtures[role] = _json(retained_raw)
    _require(result["retained_sources_fixtures_configuration_unchanged"] is True
             and result["currentness_after"] == current_pins, "producer final source/fixture/configuration closure differs")
    archive.model_byte_plans = {FIXTURES[role + "_checkpoint"]: _model_bytes(fixtures[role + "_checkpoint"])
                               for role in ("formula8", "formula384", "span768")}
    configuration = archive.value(result["shared_configuration"]["retained_copy"])
    _require(result["resources_after"]["state_path"] == configuration["state_path"], "scheduler/configuration state path differs")
    admitted = "admission" in result
    if admitted:
        _require(result["admission"]["cpu_slots"] == 2 and result["admission"]["memory_mb"] == 2048
                 and result["admission"]["gpu_memory_mb"] == 512 and result["admission"]["unified_memory_mb"] == 2560,
                 "root admission envelope differs")
        _require(all(type(result["admission"][key]) is int for key in
            ("cpu_slots", "memory_mb", "gpu_memory_mb", "unified_memory_mb")), "plain integer root resource policy required")
        _require(result["safe_owned_cleanup_established"] is True and result["root_release_observed"] is True
                 and result["cuda_cleanup_status"] == "owned_allocations_restored_to_baseline"
                 and result["gpu_allocated_before_producer_imports_bytes"] == 0
                 and result["gpu_allocated_before_owned_sessions_bytes"] == 0
                 and result["gpu_allocated_after_framework_workspace_clear_bytes"] == 0,
                 "root/zero-allocation owned cleanup not established")
        _require(all(type(result[key]) is int and result[key] == 0 for key in
            ("gpu_allocated_before_producer_imports_bytes", "gpu_allocated_before_owned_sessions_bytes",
             "gpu_allocated_after_framework_workspace_clear_bytes")), "plain zero GPU allocation cleanup counts required")
    else:
        _require(not result["qualified"] and result["owned_children"] == [] and result["families"] == {}
                 and result["optimizer_constructor_calls"] == 0 and result["root_release_observed"] is False
                 and result["safe_owned_cleanup_established"] is True,
                 "pre-admission refusal claims owned execution")
    _require(all(record["release_observed"] is True for record in result["owned_children"]), "owned child release missing")
    identities, combinations = set(), set()
    archive.children = {}
    for record in result["owned_children"]:
        admission = record["admission"]
        combination = (record["family"], record["dimension"], record["bitwise"], record["optimized"])
        _require(record["lease_id"] == admission["lease_id"] and record["lease_id"] not in identities
                 and combination not in combinations and type(record["bitwise"]) is bool and type(record["optimized"]) is bool,
                 "unique owned child identity/family combination required")
        _require((record["family"], record["dimension"]) in {("formula", 8), ("formula", 384), ("span", 768)},
                 "exact admitted child family/dimension required")
        _require(type(record["dimension"]) is int and admission["owner_pid"] == result["pid"],
                 "plain child dimension and declared owned worker PID required")
        _require(admission["cpu_slots"] == 1 and admission["memory_mb"] == 1024
                 and admission["gpu_memory_mb"] == (256 if record["optimized"] else 0)
                 and admission["unified_memory_mb"] == (1280 if record["optimized"] else 0)
                 and admission["requires_gpu"] is record["optimized"]
                 and admission["parent_lease_id"] == result["admission"]["lease_id"]
                 and admission["released"] is False and admission["cancelled"] is False,
                 "owned child admission envelope/parent/liveness differs")
        _require(all(type(admission[key]) is int for key in
            ("cpu_slots", "memory_mb", "gpu_memory_mb", "unified_memory_mb", "owner_pid")), "plain integer child resource policy required")
        identities.add(record["lease_id"])
        combinations.add(combination)
        archive.children[combination] = record
    _require(all(type(result["resources_after"][key]) is int and result["resources_after"][key] == 0 for key in
        ("active_lease_count", "active_root_lease_count", "active_child_lease_count", "waiting_request_count")),
        "final scheduler snapshot has active/waiting leases")
    final_resources = result["resources_after"]
    allocations = [final_resources["allocated"]["cpu_slots"], final_resources["allocated"]["memory_mb"],
        final_resources["allocated_gpu_memory_mb"], final_resources["allocated_unified_memory_mb"],
        final_resources["allocated_child_process_slots"]]
    _require(all(type(value) is int and value == 0 for value in allocations), "scheduler allocated resource envelope not plain zero")
    complete = result["qualified"]
    if complete:
        _require(result["precision_policy_unchanged"] is True
                 and result["precision_policy_before"] == result["precision_policy_after"]
                 and result["root_gpu_allocation_budget_observed"] is True
                 and result["gpu_peak_allocated_bytes"] <= 512 * 1024**2,
                 "qualified precision/allocation envelope differs")
        _require(set(result["families"]) == {"formula8", "formula384", "span768"}, "all three qualified families required")
        expected_children = {(family, width, bitwise, optimized) for family, width in
            (("formula", 8), ("formula", 384), ("span", 768)) for bitwise in (False, True) for optimized in (False, True)}
        _require(combinations == expected_children and len(archive.pins) == 696,
                 "exact three-family/four-lane children and697-file producer inventory required")
    families = {role: _family(archive, role, entry, fixtures, complete=complete)
                for role, entry in result["families"].items()}
    totals = {key: sum(family[key] for family in families.values()) for key in
              ("public_reports", "paired_timed_reports", "formula_projections", "span_four_logit_snapshots", "adam_constructor_calls")}
    _require(totals["adam_constructor_calls"] == result["optimizer_constructor_calls"], "constructor total arithmetic differs")
    if complete:
        _require(totals == {"public_reports": 240, "paired_timed_reports": 216,
            "formula_projections": 160, "span_four_logit_snapshots": 12, "adam_constructor_calls": 8},
            "complete archive report/projection/logit/constructor coverage differs")
        _require(len(result["owned_children"]) == 12, "complete child lease coverage differs")
        _require(len(archive.public_reports) == 240, "unique240 actual public return artifacts required")
    partial = archive.finish(allow_partial=not complete)
    _require(_pin(result_path, _read(result_path)) == result_pin, "result changed during audit")
    if check_current_sources:
        for pin in current_pins:
            _require(_pin(pin["path"], _read(pin["path"])) == pin, "current source changed during audit")
    return {"schema": "retained-trained-head-bitwise-device-archive-review/v1", "qualified": complete,
        "closed_artifacts_consistent": True, "error": None, "producer_refusal": result["error"],
        "result_pin": result_pin, "expected_result_sha256": expected_result_sha256,
        "retained_pins": [result_pin, *archive.pins.values()], "current_sources_verified": check_current_sources,
        "check_current_sources": check_current_sources, "current_source_pins": verified_source_pins,
        "root_admission_occurred": admitted,
        "constructor_count_scope": ("all_eight_successful_lane_adam_restores_no_failed_attempts" if complete else
                                    "completed_lane_constructor_returns_only_failed_attempts_not_claimed"),
        "retained_python_executed": False, "tensor_library_imported": False, "model_executed": False,
        "encoder_executed": False, "execution_attestation": False, "proof_authority": False,
        "production_qualified": False, "semantic_correctness_verified": False, "universal_speedup_claimed": False,
        "scope": "ordinary_pinned_archive_consistency_and_recomputed_numeric_timing_joins",
        "historical_receipt_scope": "exact_content_only_no_encoder_origin_attestation",
        "families": families, "coverage": totals, "bounded_archive_files": len(archive.pins) + 1,
        "unjoined_failed_partial_evidence": partial,
        "bounded_archive_bytes": sum(pin["bytes"] for pin in archive.pins.values()) + len(raw)}


def audit(root, expected_result_sha256, *, check_current_sources=False):
    """Compatibility entry point: a refusal is a structured reader result."""
    try:
        return review(Path(root).absolute() / "result.json", expected_result_sha256,
                      check_current_sources=check_current_sources)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError, AttributeError, IndexError) as error:
        return {"schema": "retained-trained-head-bitwise-device-archive-review/v1", "qualified": False,
            "closed_artifacts_consistent": False, "error": {"type": type(error).__name__, "detail": str(error)},
            "execution_attestation": False, "proof_authority": False, "production_qualified": False,
            "retained_python_executed": False, "tensor_library_imported": False, "model_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--check-current-sources", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    _require(args.result.name == "result.json", "exact requested result.json archive entry required")
    report = audit(args.result.absolute().parent, args.expected_result_sha256,
                   check_current_sources=args.check_current_sources)
    raw = _wire(report)
    if args.output is not None:
        output = args.output.absolute()
        _require(output.parent.resolve(strict=True) == output.parent, "canonical reader output parent required")
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        output.chmod(0o444)
    else:
        print(raw.decode(), flush=True)
    return 0 if report["closed_artifacts_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
