"""Opt-in, zero-latent source-span argument custody for engineering consumers.

Eligibility and exposure are explicit declarations, not reviewed gold. This
module does not invoke a trainer, model, signature verifier or native compiler.
It leaves existing trainers unchanged. Its frozen snapshots protect ordinary
caller mutations; they are not a security boundary against malicious Python.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .checkpoint_content_guard import CheckpointContentGuard
from . import legal_ir_eval_splits as splits


SCHEMA = "source-span-consumer-binding/v1"
PROFILE = "zero-latent-declared-engineering-supervision/v1"
MAX_ROWS = 4096
MAX_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 40
MAX_NODES = 1_000_000
OPERATIONS = ("training", "hparam_selection")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROW_FIELDS = {"id", "source_text", "canonical_ir"}
_ELIGIBILITY_FIELDS = {"id", "source_text_sha256", "canonical_ir_sha256", "target_origin",
                       "status", "allowed_operations", "reason"}
_EXPOSURE_FIELDS = {"id", "source_text_sha256", "canonical_ir_sha256", "target_exposure", "provenance_ref"}
_REQUIRED_EXPOSURE = {"training": "declared_supervised_training",
                      "hparam_selection": "declared_validation_scoring"}
_SOURCE_AT_IMPORT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SPLIT_SOURCE_PATH = Path(splits.__file__)
_SPLIT_SOURCE_AT_IMPORT = hashlib.sha256(_SPLIT_SOURCE_PATH.read_bytes()).hexdigest()


class SourceSpanConsumerBindingError(ValueError):
    """Invalid integrity inputs, or a blocked opt-in dispatch with its receipt."""
    def __init__(self, message, *, receipt=None):
        super().__init__(message)
        self.receipt = None if receipt is None else json.loads(_wire(receipt))


def _require(condition, message):
    if not condition:
        raise SourceSpanConsumerBindingError(message)


def _sha256(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None,
             label + " requires an exact lowercase SHA256")


def _wire(value):
    # This encoder only detaches and bounds JSON. Digests/comparisons belong to
    # the existing CheckpointContentGuard canonical recipe.
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError("ordinary finite JSON required") from error


def _preflight(value):
    nodes, text_bytes, active = 0, 0, set()
    def visit(item, depth):
        nonlocal nodes, text_bytes
        nodes += 1
        _require(nodes <= MAX_NODES and depth <= MAX_DEPTH, "JSON node/depth bound exceeded")
        kind = type(item)
        _require(kind in (dict, list, str, int, float, bool, type(None)),
                 "ordinary built-in JSON only; custom mappings, subclasses and tuples are unsupported")
        if kind is str:
            try:
                text_bytes += len(item.encode("utf-8"))
            except UnicodeError as error:
                raise SourceSpanConsumerBindingError("valid UTF8 JSON strings required") from error
            _require(text_bytes <= MAX_BYTES, "JSON byte bound exceeded")
        elif kind is float:
            _require(math.isfinite(item), "finite JSON numbers required")
        elif kind in (dict, list):
            identity = id(item)
            _require(identity not in active, "cyclic JSON is unsupported")
            active.add(identity)
            if kind is dict:
                for key, child in item.items():
                    _require(type(key) is str, "ordinary JSON string keys required")
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)
    visit(value, 0)
    raw = _wire(value)
    _require(len(raw) <= MAX_BYTES, "canonical JSON byte bound exceeded")
    return raw


def _guard(value, expected=None):
    try:
        return CheckpointContentGuard(value, expected_sha256=expected)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError(str(error)) from error


def _check(guard, value, label):
    try:
        guard.check(value, message=label + " content changed")
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError(str(error)) from error


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == fields, label + " requires exact closed fields")


def _text(value, label, maximum):
    _require(type(value) is str and bool(value.strip()) and len(value) <= maximum,
             label + " requires bounded nonempty text")


def _implementation(span):
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_AT_IMPORT,
             "consumer binding source changed since import")
    _require(hashlib.sha256(_SPLIT_SOURCE_PATH.read_bytes()).hexdigest() == _SPLIT_SOURCE_AT_IMPORT,
             "split implementation changed since import")
    try:
        # Direct split-owner custody does not claim a universal source closure.
        return {"adapter_sha256": _SOURCE_AT_IMPORT, "span": span._implementation(),
                "legal_ir_eval_splits_sha256": _SPLIT_SOURCE_AT_IMPORT,
                "content_guard": CheckpointContentGuard({}).inference_implementation}
    except (ValueError, OSError) as error:
        raise SourceSpanConsumerBindingError(str(error)) from error


def _manifest(value, offered_guard):
    try:
        resolved = splits.LegalIRSplitManifest.from_mapping(value)
        regenerated = resolved.to_dict()
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise SourceSpanConsumerBindingError("invalid complete split manifest: " + str(error)) from error
    _check(offered_guard, regenerated, "complete split manifest roundtrip")
    _require(resolved.protected_splits == splits.PROTECTED_LEGAL_IR_SPLITS,
             "canonical protected_splits required")
    _require(resolved.partition_names == splits.LEGAL_IR_EVAL_SPLITS,
             "canonical partition_names required")
    examples = {example.sample_id: example for example in resolved.examples}
    _require(set(resolved.assignments) == set(examples),
             "split assignment population must exactly equal example IDs")
    return resolved, examples


@dataclass(frozen=True, slots=True, init=False)
class SourceSpanConsumerBinding:
    """Privately retained immutable input snapshots and preflight receipt."""
    _guards: tuple
    _implementation_guard: CheckpointContentGuard
    _operation: str
    _rows_json: bytes
    _receipt_json: bytes

    def __init__(self):
        raise TypeError("use prepare_source_span_consumer_binding")

    def receipt(self):
        """Return a detached complete-denominator preflight receipt."""
        return json.loads(self._receipt_json)


def prepare_source_span_consumer_binding(rows, *, expected_rows_sha256, split_manifest,
        expected_split_manifest_sha256, eligibility_records, expected_eligibility_sha256,
        exposure_records, expected_exposure_sha256, operation):
    """Bind a complete ordered engineering batch without training or filtering.

    Expected hashes use CheckpointContentGuard canonical JSON, not raw-file
    bytes. Source text hashes separately commit exact UTF8. A supported label
    or an ``eligible`` declaration supplies no semantic or gold authority.
    """
    _require(type(operation) is str and operation in OPERATIONS, "unsupported consumer operation")
    expected = (expected_rows_sha256, expected_split_manifest_sha256,
                expected_eligibility_sha256, expected_exposure_sha256)
    for name, digest in zip(("rows", "split manifest", "eligibility", "exposure"), expected):
        _sha256(digest, "expected " + name + " SHA256")
    originals = (rows, split_manifest, eligibility_records, exposure_records)
    raw = _preflight(list(originals))
    copies = json.loads(raw)
    guards = tuple(_guard(value, digest) for value, digest in zip(copies, expected))
    rows_copy, manifest_copy, eligibility, exposure = copies
    _require(type(rows_copy) is list and 1 <= len(rows_copy) <= MAX_ROWS,
             "row count bound requires one through 4096 rows")
    _require(type(manifest_copy) is dict, "complete split manifest mapping required")
    _require(type(eligibility) is list and type(exposure) is list
             and len(eligibility) == len(exposure) == len(rows_copy),
             "complete ordered eligibility and exposure populations required")
    manifest, examples = _manifest(manifest_copy, guards[1])
    records, identifiers, sources = [], set(), set()
    for index, (row, eligibility_row, exposure_row) in enumerate(zip(rows_copy, eligibility, exposure)):
        _closed(row, _ROW_FIELDS, "zero-latent span row")
        _text(row["id"], "row id", 512)
        _require(row["id"] not in identifiers, "unique row IDs required")
        _text(row["source_text"], "source_text", MAX_BYTES)
        _require(row["source_text"] not in sources, "distinct exact source_text required")
        identifiers.add(row["id"])
        sources.add(row["source_text"])
        _closed(eligibility_row, _ELIGIBILITY_FIELDS, "eligibility record")
        _closed(exposure_row, _EXPOSURE_FIELDS, "exposure record")
        source_sha = hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest()
        target_sha = _guard(row["canonical_ir"]).sha256
        for label, sidecar in (("eligibility", eligibility_row), ("exposure", exposure_row)):
            _sha256(sidecar["source_text_sha256"], label + " source SHA256")
            _sha256(sidecar["canonical_ir_sha256"], label + " target SHA256")
            _require(sidecar["id"] == row["id"] and type(sidecar["id"]) is str
                     and sidecar["source_text_sha256"] == source_sha
                     and sidecar["canonical_ir_sha256"] == target_sha,
                     label + " does not bind this exact ordered source/target row")
        _require(type(eligibility_row["target_origin"]) is str
                 and eligibility_row["target_origin"] in ("authored_engineering_fixture", "model_generated_weak"),
                 "unsupported declared target_origin")
        _require(type(eligibility_row["status"]) is str
                 and eligibility_row["status"] in ("eligible", "ineligible", "unknown"),
                 "explicit eligibility status required")
        allowed = eligibility_row["allowed_operations"]
        _require(type(allowed) is list and all(type(item) is str and item in OPERATIONS for item in allowed)
                 and len(allowed) == len(set(allowed)), "distinct explicit allowed_operations required")
        _text(eligibility_row["reason"], "eligibility reason", 8192)
        _require(type(exposure_row["target_exposure"]) is str and exposure_row["target_exposure"] in
                 ("declared_supervised_training", "declared_validation_scoring", "unknown"),
                 "explicit target_exposure required")
        _text(exposure_row["provenance_ref"], "exposure provenance_ref", 8192)
        example = examples.get(row["id"])
        if example is not None:
            _require(example.content_hash == splits._content_hash(row["source_text"]),
                     "source content_hash differs from split manifest example")
        blockers = []
        if eligibility_row["status"] != "eligible":
            blockers.append({"reason": "eligibility_" + eligibility_row["status"]})
        if operation not in allowed:
            blockers.append({"reason": "operation_not_declared_allowed"})
        if exposure_row["target_exposure"] != _REQUIRED_EXPOSURE[operation]:
            blockers.append({"reason": "exposure_declaration_does_not_match_operation"})
        records.append({"row_index": index, "id": row["id"], "input": row,
                        "source_text_sha256": source_sha, "canonical_ir_sha256": target_sha,
                        "eligibility": eligibility_row, "exposure": exposure_row, "blockers": blockers})
    global_blockers = []
    try:
        splits.authorize_legal_ir_split_use(manifest, operation=operation,
                                          items=[{"sample_id": row["id"]} for row in rows_copy])
    except splits.LegalIRSplitPolicyError as error:
        for diagnostic in error.disallowed:
            matching = [record for record in records if record["id"] == diagnostic.get("sample_id")]
            blocker = {"reason": "split_policy_disallowed", "diagnostic": diagnostic}
            if matching:
                for record in matching:
                    record["blockers"].append(blocker)
            else:
                global_blockers.append(blocker)
    except splits.LegalIRSplitLeakageError as error:
        global_blockers.append({"reason": "split_guard_failed", "details": error.result.to_dict()})
    from . import legal_span_formula as span
    implementation = _implementation(span)
    supported = True
    for row, record in zip(rows_copy, records):
        try:
            audit = span.audit_examples([row])
            rejected = audit["rejected_rows"]
            _require(audit["all_supported"] is True or bool(rejected), "incomplete span audit result")
            for rejected_row in rejected:
                record["blockers"].append({"reason": "span_target_unsupported", "detail": rejected_row["reason"]})
            supported = supported and not rejected
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            supported = False
            record["blockers"].append({"reason": "span_target_unsupported", "detail": str(error)})
    strict_records = False
    if supported:
        try:
            span._records(rows_copy, 0)
            strict_records = True
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            global_blockers.append({"reason": "span_strict_records_check_failed", "detail": str(error)})
    blockers = list(global_blockers)
    for record in records:
        record["status"] = "blocked" if global_blockers or record["blockers"] else "ready"
        blockers.extend({"row_index": record["row_index"], "id": record["id"], **item}
                        for item in record["blockers"])
    blocked_count = sum(record["status"] == "blocked" for record in records)
    receipt = {"schema": SCHEMA, "profile": PROFILE, "operation": operation,
        "status": "blocked" if blockers else "ready", "row_count": len(records),
        "ready_row_count": len(records) - blocked_count, "blocked_row_count": blocked_count,
        "rows": records, "blockers": blockers, "rows_discarded": 0,
        "input_sha256s": dict(zip(("rows", "split_manifest", "eligibility", "exposure"), expected)),
        "digest_recipe": "CheckpointContentGuard_canonical_JSON_ensure_ascii_true_sort_keys_compact/v1",
        "source_text_digest_recipe": "SHA256_of_exact_UTF8_source_text",
        "latent_dimension": 0, "strict_span_records_check_passed": strict_records,
        "implementation": implementation, "eligibility_declaration_only": True,
        "exposure_declaration_only": True, "semantic_authority": False,
        "training_gold_authority": False, "evaluation_gold_authority": False,
        "training_executed": False, "receipt_scope": "local_input_integrity_and_explicit_declarations_only",
        "consumer_scope": "opt_in_callback_arguments_only_not_all_process_reads"}
    receipt_raw = _preflight(receipt)
    implementation_guard = _guard(implementation)
    _check(implementation_guard, _implementation(span), "implementation")
    for guard, value, label in zip(guards, originals, ("rows", "split manifest", "eligibility", "exposure")):
        _check(guard, value, label)
    for guard, value, label in zip(guards, copies, ("rows", "split manifest", "eligibility", "exposure")):
        _check(guard, value, "prepared " + label)
    binding = object.__new__(SourceSpanConsumerBinding)
    for name, value in (("_guards", guards), ("_implementation_guard", implementation_guard),
                        ("_operation", operation), ("_rows_json", _wire(rows_copy)),
                        ("_receipt_json", receipt_raw)):
        object.__setattr__(binding, name, value)
    return binding


def validate_source_span_consumer_binding(binding, rows, *, split_manifest, eligibility_records, exposure_records):
    """Check the complete original inputs and source owners, then detach receipt."""
    _require(type(binding) is SourceSpanConsumerBinding, "prepared SourceSpanConsumerBinding required")
    inputs = (rows, split_manifest, eligibility_records, exposure_records)
    _preflight(list(inputs))
    for guard, value, label in zip(binding._guards, inputs, ("rows", "split manifest", "eligibility", "exposure")):
        _check(guard, value, label)
    from . import legal_span_formula as span
    _check(binding._implementation_guard, _implementation(span), "implementation")
    return binding.receipt()


def consume_source_span_binding(binding, rows, *, split_manifest, eligibility_records, exposure_records, consumer):
    """Opt in to one callback on detached exact rows; return its value unchanged.

    A blocked batch never reaches the callback. The callback may alter its
    private copy. Callback effects and other process reads are not attested;
    its return value or exception propagates directly without a late retry.
    """
    arguments = {"split_manifest": split_manifest, "eligibility_records": eligibility_records,
                 "exposure_records": exposure_records}
    receipt = validate_source_span_consumer_binding(binding, rows, **arguments)
    if receipt["status"] != "ready":
        raise SourceSpanConsumerBindingError("source-span consumer batch is blocked", receipt=receipt)
    _require(callable(consumer), "explicit callable consumer required")
    consumed_rows = json.loads(binding._rows_json)
    _check(binding._guards[0], consumed_rows, "detached consumer rows")
    return consumer(consumed_rows)


__all__ = ["SourceSpanConsumerBinding", "SourceSpanConsumerBindingError",
           "prepare_source_span_consumer_binding", "validate_source_span_consumer_binding",
           "consume_source_span_binding", "SCHEMA", "PROFILE", "MAX_ROWS", "MAX_BYTES", "MAX_DEPTH", "MAX_NODES"]
