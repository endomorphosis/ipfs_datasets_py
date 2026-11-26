"""Opt-in, zero-latent source-span argument custody for explicit consumers.

Eligibility and exposure are explicit declarations, not reviewed gold. This
module does not invoke a trainer, model, signature verifier or native compiler.
It leaves existing trainers unchanged. Its frozen snapshots protect ordinary
caller mutations; they are not a security boundary against malicious Python.
The separate v2 path replays complete reviewed admission and retains full typed
targets; review eligibility is separate from decoder support and proof validity.
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


REVIEWED_SCHEMA = "reviewed-source-span-consumer-binding/v2"
REVIEWED_PROFILE = "complete-reviewed-source-span-supervision/v2"
REVIEWED_V3_SCHEMA = "reviewed-source-span-consumer-binding/v3"
REVIEWED_V3_PROFILE = "complete-reviewed-mixed-sort-source-span-supervision/v3"
REVIEWED_TARGET_CODEC = "complete-relational-typed-ast/v1"
REVIEWED_HELDOUT_PURPOSE = "frozen-single-component-final-scoring/v1"
REVIEWED_HELDOUT_CONTEXT_PURPOSE = "frozen-single-component-with-reviewed-TRAIN-context/v1"
REVIEWED_HELDOUT_CONTEXT_PROFILE = "reviewed-rich-TRAIN-context-heldout/v1"
REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE = "frozen-single-mixed-sort-component-with-reviewed-TRAIN-context/v1"
REVIEWED_V3_HELDOUT_CONTEXT_PROFILE = "reviewed-mixed-sort-rich-TRAIN-context-heldout/v1"
REVIEWED_HELDOUT_EXPOSURE = "declared_frozen_heldout_scoring"
_REVIEWED_ROW_FIELDS = {"id", "unit_id", "source_text", "canonical_ir"}


def _reviewed_admission_owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1
    return legal_norm_content_adjudication_v1



def _reviewed_admission_owner_v3():
    from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3
    return legal_reviewed_norm_admission_v3


def _reviewed_contract(version):
    _require(type(version) is str and version in ("v2", "v3"), "closed reviewed admission contract required")
    if version == "v2":
        return (REVIEWED_SCHEMA, REVIEWED_PROFILE, "legal-reviewed-norm-admission-assessment/v2",
                "complete-reviewed-norm-admission/v2")
    return (REVIEWED_V3_SCHEMA, REVIEWED_V3_PROFILE, "legal-reviewed-mixed-sort-norm-admission-assessment/v3",
            "complete-reviewed-mixed-sort-norm-admission/v3")


def _reviewed_admission_for_version(version):
    _reviewed_contract(version)
    return _reviewed_admission_owner() if version == "v2" else _reviewed_admission_owner_v3()


def _reviewed_snapshot(value):
    # Admission replay contains exact source/request bytes. Never JSON-coerce
    # these to text, base64 or caller-supplied summaries.
    try:
        return _reviewed_admission_owner().norm._snapshot(value)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError("invalid complete admission replay inputs: " + str(error)) from error


def reviewed_admission_inputs_sha256(admission_inputs):
    """Bounded type-separated JSON/bytes commitment from the norm-review owner."""
    return _reviewed_snapshot(admission_inputs)[1]


def _reviewed_implementation():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_AT_IMPORT,
             "consumer binding source changed since import")
    _require(hashlib.sha256(_SPLIT_SOURCE_PATH.read_bytes()).hexdigest() == _SPLIT_SOURCE_AT_IMPORT,
             "split implementation changed since import")
    return {"adapter_sha256": _SOURCE_AT_IMPORT,
            "legal_ir_eval_splits_sha256": _SPLIT_SOURCE_AT_IMPORT,
            "content_guard": CheckpointContentGuard({}).inference_implementation,
            "target_codec": REVIEWED_TARGET_CODEC}


def _reviewed_assessment(admission_inputs):
    return _reviewed_assessment_for_version(admission_inputs, "v2")


def _reviewed_assessment_for_version(admission_inputs, version):
    _, _, assessment_schema, admission_profile = _reviewed_contract(version)
    owner = _reviewed_admission_for_version(version)
    _require(type(admission_inputs) is dict, "complete admission replay mapping required")
    try:
        if version == "v3" and "current_trust" in admission_inputs:
            _, report = owner._assess_reviewed_norm_admission_v3_with_current_trust(**admission_inputs)
        else:
            report = (owner.assess_reviewed_norm_admission_v2(**admission_inputs) if version == "v2"
                      else owner.assess_reviewed_norm_admission_v3(**admission_inputs))
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError("reviewed admission replay failed: " + str(error)) from error
    _preflight(report)
    _require(type(report) is dict
             and report.get("schema") == assessment_schema
             and report.get("profile") == admission_profile,
             "complete reviewed admission assessment profile required")
    _sha256(report.get("declaration_sha256"), "reviewed declaration SHA256")
    _sha256(admission_inputs.get("expected_preparation_sha256"), "reviewed preparation SHA256")
    _sha256(admission_inputs.get("expected_registry_sha256"), "reviewed trust registry SHA256")
    _sha256(admission_inputs.get("expected_policy_sha256"), "reviewed trust policy SHA256")
    _require(type(report.get("semantic_use_eligible")) is bool
             and type(report.get("blockers")) is list, "explicit admission disposition required")
    _require(report.get("provenance_kind") in ("fictional_fixture", "statutory"),
             "explicit reviewed provenance required")
    permitted = report.get("permitted_uses")
    _require(type(permitted) is list and all(type(item) is str for item in permitted)
             and len(permitted) == len(set(permitted)), "distinct reviewed permitted uses required")
    _require(type(report.get("producer_pins")) is dict, "reviewed producer pins required")
    units = report.get("units")
    _require(type(units) is list and 1 <= len(units) <= MAX_ROWS,
             "complete bounded reviewed unit population required")
    identifiers = set()
    for unit in units:
        _require(type(unit) is dict, "reviewed unit mapping required")
        _text(unit.get("unit_id"), "reviewed unit id", 512)
        _require(unit["unit_id"] not in identifiers, "unique reviewed unit IDs required")
        identifiers.add(unit["unit_id"])
        _text(unit.get("source_text"), "reviewed source text", MAX_BYTES)
        _text(unit.get("occurrence_cid"), "reviewed occurrence CID", 1024)
        _require("canonical_ir" in unit and "argument_roles" in unit and "relational_profile" in unit,
                 "complete reviewed typed target and roles required")
    for field in ("proof_authority", "Lean_admitted", "semantic_graph_admitted",
                  "lean_corpus_authority", "corpus_admitted"):
        _require(report.get(field, False) is False, "semantic review cannot confer proof/corpus authority")
    if report["provenance_kind"] == "fictional_fixture":
        for field in ("training_mask", "evaluation_gold_mask"):
            _require(type(report.get(field)) is int and report[field] == 0,
                     "fictional fixtures require zero production/gold masks")
    return report


def _reviewed_bound_component(bound_component_inputs, admission_inputs):
    """Replay an explicitly requested current corpus-source handoff."""
    if bound_component_inputs is None:
        return None, None
    _require(type(admission_inputs) is dict, "complete admission replay mapping required")
    _closed(bound_component_inputs, {"report", "expected_report_sha256", "preparation_inputs"},
            "complete bound component replay")
    detached, commitment = _reviewed_snapshot(bound_component_inputs)
    _sha256(detached["expected_report_sha256"], "expected bound component report SHA256")
    try:
        from ipfs_datasets_py.logic.autoformal import corpus_source_bindings
        checked = corpus_source_bindings.validate_bound_norm_component_v1(
            detached["report"], expected_report_sha256=detached["expected_report_sha256"],
            **detached["preparation_inputs"])
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError("bound component current replay failed: " + str(error)) from error
    _require(_guard(checked["norm_preparation"]).sha256
             == _guard(admission_inputs.get("preparation")).sha256,
             "bound component norm preparation differs from admission replay")
    preparation_sha = _reviewed_admission_owner().norm_content_adjudication_sha256(
        admission_inputs["preparation"])
    _require(checked["norm_preparation_sha256"] == preparation_sha
             == admission_inputs.get("expected_preparation_sha256"),
             "bound component norm preparation commitment differs from admission replay")
    _require(checked["norm_preparation_inputs_sha256"]
             == _reviewed_snapshot(admission_inputs.get("preparation_inputs"))[1],
             "bound component original norm preparation inputs differ from admission replay")
    identity = {key: checked[key] for key in ("schema", "profile", "binding_manifest_sha256",
        "source_history_manifest_ref", "current_epoch_id", "unit_bindings_sha256",
        "norm_preparation_inputs_sha256", "norm_preparation_sha256", "producer_pins")}
    identity["bound_component_report_sha256"] = detached["expected_report_sha256"]
    _require(_reviewed_snapshot(bound_component_inputs)[1] == commitment
             and _reviewed_snapshot(detached)[1] == commitment,
             "bound component replay inputs changed during validation")
    return identity, commitment


def _reviewed_stable_identity(report, admission_inputs, bound_component_identity=None):
    # Trust observations and the explicit evaluation time may advance. A new
    # registry/policy root requires a freshly prepared consumer binding, even
    # when that different authority would support the same target.
    result = {"profile": report["profile"], "declaration_sha256": report["declaration_sha256"],
            "preparation_sha256": admission_inputs["expected_preparation_sha256"],
            "registry_sha256": admission_inputs["expected_registry_sha256"],
            "policy_sha256": admission_inputs["expected_policy_sha256"],
            "provenance_kind": report["provenance_kind"], "producer_pins": report["producer_pins"],
            "units": report["units"]}
    if "current_trust" in admission_inputs:
        result["current_trust_input_sha256"] = report["current_trust"]["input_sha256"]
    if bound_component_identity is not None:
        result["bound_component_identity"] = bound_component_identity
    return result


@dataclass(frozen=True, slots=True, init=False)
class ReviewedSourceSpanConsumerBinding:
    """Exact complete targets and replay-bound admission for one consumer batch."""
    _guards: tuple
    _implementation_guard: CheckpointContentGuard
    _admission_identity_guard: CheckpointContentGuard
    _contract_guard: CheckpointContentGuard
    _admission_version: str
    _assessment_time_utc: str
    _operation: str
    _target_codec: str
    _allow_fictional_fixture: bool
    _allow_heldout_evaluation: bool
    _heldout_evaluation_purpose: str | None
    _bound_component_required: bool
    _rows_json: bytes
    _receipt_json: bytes

    def __init__(self):
        raise TypeError("use prepare_reviewed_source_span_consumer_binding_v2")

    def receipt(self):
        """Detached preparation-time receipt; consume always replays admission."""
        return json.loads(self._receipt_json)


def prepare_reviewed_source_span_consumer_binding_v2(rows, *, expected_rows_sha256,
        split_manifest, expected_split_manifest_sha256, admission_inputs,
        expected_admission_inputs_sha256, exposure_records, expected_exposure_sha256,
        operation, target_codec=REVIEWED_TARGET_CODEC, allow_fictional_fixture=False,
        allow_heldout_evaluation=False, heldout_evaluation_purpose=None, bound_component_inputs=None):
    """Bind reviewed V2 targets, optionally requiring a current bound-source handoff."""
    return _prepare_reviewed_source_span_consumer_binding(rows,
        expected_rows_sha256=expected_rows_sha256, split_manifest=split_manifest,
        expected_split_manifest_sha256=expected_split_manifest_sha256, admission_inputs=admission_inputs,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256, exposure_records=exposure_records,
        expected_exposure_sha256=expected_exposure_sha256, operation=operation, target_codec=target_codec,
        allow_fictional_fixture=allow_fictional_fixture, allow_heldout_evaluation=allow_heldout_evaluation,
        heldout_evaluation_purpose=heldout_evaluation_purpose, _admission_version="v2",
        bound_component_inputs=bound_component_inputs)


def prepare_reviewed_source_span_consumer_binding_v3(rows, *, expected_rows_sha256,
        split_manifest, expected_split_manifest_sha256, admission_inputs,
        expected_admission_inputs_sha256, exposure_records, expected_exposure_sha256,
        operation, target_codec=REVIEWED_TARGET_CODEC, allow_fictional_fixture=False,
        allow_heldout_evaluation=False, heldout_evaluation_purpose=None):
    """Explicitly bind full mixed-sort targets using independently reviewed V3 admission."""
    return _prepare_reviewed_source_span_consumer_binding(rows,
        expected_rows_sha256=expected_rows_sha256, split_manifest=split_manifest,
        expected_split_manifest_sha256=expected_split_manifest_sha256, admission_inputs=admission_inputs,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256, exposure_records=exposure_records,
        expected_exposure_sha256=expected_exposure_sha256, operation=operation, target_codec=target_codec,
        allow_fictional_fixture=allow_fictional_fixture, allow_heldout_evaluation=allow_heldout_evaluation,
        heldout_evaluation_purpose=heldout_evaluation_purpose, _admission_version="v3")


def _prepare_reviewed_source_span_consumer_binding(rows, *, expected_rows_sha256,
        split_manifest, expected_split_manifest_sha256, admission_inputs,
        expected_admission_inputs_sha256, exposure_records, expected_exposure_sha256,
        operation, target_codec=REVIEWED_TARGET_CODEC, allow_fictional_fixture=False,
        allow_heldout_evaluation=False, heldout_evaluation_purpose=None, _admission_version,
        bound_component_inputs=None):
    """Bind complete reviewed typed targets without projecting or training them.

    JSON commitments use CheckpointContentGuard. The admission-input commitment
    uses the norm owner's type-separated JSON/bytes snapshot recipe, exposed by
    reviewed_admission_inputs_sha256. Review eligibility is an explicit policy
    outcome, not machine proof of legal truth or a Lean/corpus acceptance.
    """
    schema, profile, _, _ = _reviewed_contract(_admission_version)
    _require(bound_component_inputs is None or _admission_version == "v2",
             "bound component handoff requires the explicit V2 consumer path")
    _require(_admission_version != "v3" or heldout_evaluation_purpose != REVIEWED_HELDOUT_CONTEXT_PURPOSE,
             "V3 rich TRAIN context requires its explicit V3 heldout purpose")
    _require(type(allow_heldout_evaluation) is bool, "explicit boolean heldout opt-in required")
    heldout = type(operation) is str and operation == "heldout_evaluation" and allow_heldout_evaluation
    _require(type(operation) is str and (operation in OPERATIONS or heldout),
             "unsupported reviewed consumer operation")
    _require(not allow_heldout_evaluation or heldout,
             "heldout opt-in cannot change training or hparam permissions")
    _require((heldout and type(heldout_evaluation_purpose) is str and heldout_evaluation_purpose in
              (REVIEWED_HELDOUT_PURPOSE, (REVIEWED_HELDOUT_CONTEXT_PURPOSE if _admission_version == "v2"
                                        else REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE)))
             or (not heldout and heldout_evaluation_purpose is None),
             "explicit supported frozen heldout purpose required")
    _require(type(target_codec) is str, "explicit target codec required")
    _require(type(allow_fictional_fixture) is bool, "explicit boolean fixture permission required")
    expected = (expected_rows_sha256, expected_split_manifest_sha256, expected_exposure_sha256)
    for name, digest in zip(("rows", "split manifest", "exposure"), expected):
        _sha256(digest, "expected " + name + " SHA256")
    _sha256(expected_admission_inputs_sha256, "expected admission input SHA256")
    originals = (rows, split_manifest, exposure_records)
    copies = json.loads(_preflight(list(originals)))
    guards = tuple(_guard(value, digest) for value, digest in zip(copies, expected))
    rows_copy, manifest_copy, exposure = copies
    admission_copy, admission_sha = _reviewed_snapshot(admission_inputs)
    _require(admission_sha == expected_admission_inputs_sha256, "complete admission replay input commitment differs")
    bound_identity, bound_inputs_sha = _reviewed_bound_component(bound_component_inputs, admission_copy)
    report = (_reviewed_assessment(admission_copy) if _admission_version == "v2"
              else _reviewed_assessment_for_version(admission_copy, "v3"))
    _require(type(rows_copy) is list and 1 <= len(rows_copy) <= MAX_ROWS,
             "row count bound requires one through 4096 rows")
    _require(type(exposure) is list and len(exposure) == len(rows_copy),
             "complete ordered exposure population required")
    manifest, examples = _manifest(manifest_copy, guards[1])
    split_fingerprint = None
    if "campaign_split_profile" in manifest.metadata or "unicode_data_version" in manifest.metadata:
        split_fingerprint = getattr(splits, "legal_ir_split_source_fingerprint", None)
        _require(callable(split_fingerprint), "reviewed split fingerprint profile is unavailable")
    global_blockers = []
    if report["semantic_use_eligible"] is not True or report["blockers"]:
        global_blockers.append({"reason": "semantic_admission_not_eligible", "details": report["blockers"]})
    if operation not in report["permitted_uses"]:
        global_blockers.append({"reason": "operation_not_reviewed_permitted"})
    if report["provenance_kind"] == "fictional_fixture" and not allow_fictional_fixture:
        global_blockers.append({"reason": "fictional_fixture_requires_explicit_opt_in"})
    if target_codec != REVIEWED_TARGET_CODEC:
        global_blockers.append({"reason": "complete_typed_target_codec_required", "offered_codec": target_codec})
    units = {unit["unit_id"]: unit for unit in report["units"]}
    records, identifiers, unit_ids = [], set(), set()
    for index, (row, exposure_row) in enumerate(zip(rows_copy, exposure)):
        _closed(row, _REVIEWED_ROW_FIELDS, "reviewed complete typed row")
        _text(row["id"], "row id", 512)
        _text(row["unit_id"], "row unit id", 512)
        _require(row["id"] not in identifiers and row["unit_id"] not in unit_ids,
                 "unique row and reviewed unit IDs required")
        identifiers.add(row["id"])
        unit_ids.add(row["unit_id"])
        unit = units.get(row["unit_id"])
        _require(unit is not None, "row unit is absent from reviewed admission")
        _require(type(row["source_text"]) is str and row["source_text"] == unit["source_text"],
                 "row source differs from exact reviewed source")
        target_sha = _guard(row["canonical_ir"]).sha256
        _require(target_sha == _guard(unit["canonical_ir"]).sha256,
                 "complete row target differs from reviewed typed target")
        source_sha = hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest()
        _closed(exposure_row, _EXPOSURE_FIELDS, "reviewed exposure record")
        _require(exposure_row["id"] == row["id"]
                 and exposure_row["source_text_sha256"] == source_sha
                 and exposure_row["canonical_ir_sha256"] == target_sha,
                 "exposure does not bind this exact ordered reviewed source/target row")
        _text(exposure_row["provenance_ref"], "exposure provenance_ref", 8192)
        allowed_exposures = ((REVIEWED_HELDOUT_EXPOSURE, "unknown") if heldout else
                             ("declared_supervised_training", "declared_validation_scoring", "unknown"))
        _require(type(exposure_row["target_exposure"]) is str and exposure_row["target_exposure"] in
                 allowed_exposures,
                 "explicit target_exposure required")
        example = examples.get(row["id"])
        if example is not None:
            if split_fingerprint is None:
                content_hash = splits._content_hash(row["source_text"])
            else:
                try:
                    content_hash, fingerprint = split_fingerprint(row["source_text"], metadata=manifest.metadata)
                except ValueError as error:
                    raise SourceSpanConsumerBindingError("invalid reviewed split fingerprint profile: " + str(error)) from error
                _require(example.token_fingerprint == fingerprint,
                         "reviewed source fingerprint differs from split manifest example")
            _require(example.content_hash == content_hash,
                     "reviewed source content differs from split manifest example")
        blockers = []
        required_exposure = REVIEWED_HELDOUT_EXPOSURE if heldout else _REQUIRED_EXPOSURE[operation]
        if exposure_row["target_exposure"] != required_exposure:
            blockers.append({"reason": "exposure_declaration_does_not_match_operation"})
        records.append({"row_index": index, "id": row["id"], "unit_id": row["unit_id"],
                        "occurrence_cid": unit["occurrence_cid"], "source_text_sha256": source_sha,
                        "canonical_ir_sha256": target_sha, "exposure": exposure_row, "blockers": blockers})
    try:
        splits.authorize_legal_ir_split_use(manifest, operation=operation,
                                          items=[{"sample_id": row["id"]} for row in rows_copy])
    except splits.LegalIRSplitPolicyError as error:
        for diagnostic in error.disallowed:
            matches = [record for record in records if record["id"] == diagnostic.get("sample_id")]
            blocker = {"reason": "split_policy_disallowed", "diagnostic": diagnostic}
            if matches:
                for record in matches:
                    record["blockers"].append(blocker)
            else:
                global_blockers.append(blocker)
    except splits.LegalIRSplitLeakageError as error:
        global_blockers.append({"reason": "split_guard_failed", "details": error.result.to_dict()})
    blockers = list(global_blockers)
    for record in records:
        record["status"] = "blocked" if global_blockers or record["blockers"] else "ready"
        blockers.extend({"row_index": record["row_index"], "id": record["id"], **item}
                        for item in record["blockers"])
    blocked = sum(record["status"] == "blocked" for record in records)
    implementation = _reviewed_implementation()
    identity_guard = _guard(_reviewed_stable_identity(report, admission_copy, bound_identity))
    receipt = {"schema": schema, "profile": profile, "operation": operation,
        "target_codec": target_codec, "status": "blocked" if blockers else "ready",
        "row_count": len(records), "ready_row_count": len(records) - blocked,
        "blocked_row_count": blocked, "rows_discarded": 0, "rows": records, "blockers": blockers,
        "declaration_sha256": report["declaration_sha256"], "admission_identity_sha256": identity_guard.sha256,
        "admission_assessment_sha256": _reviewed_admission_for_version(_admission_version).norm_content_adjudication_sha256(report),
        "admission_inputs_sha256": admission_sha,
        "admission_input_digest_recipe": "norm_review_type_separated_bounded_JSON_bytes_snapshot/v1",
        "input_sha256s": dict(zip(("rows", "split_manifest", "exposure"), expected)),
        "provenance_kind": report["provenance_kind"], "permitted_uses": report["permitted_uses"],
        "semantic_admission_replayed": True, "semantic_use_eligible": report["semantic_use_eligible"],
        "fictional_fixture_allowed": allow_fictional_fixture,
        "training_mask": report.get("training_mask", 0), "evaluation_gold_mask": report.get("evaluation_gold_mask", 0),
        "proof_authority": False, "lean_corpus_authority": False, "corpus_admitted": False,
        "training_executed": False, "implementation": implementation,
        "exposure_declaration_only": True,
        "receipt_scope": "exact_complete_typed_targets_and_replayed_review_policy_eligibility",
        "consumer_scope": "opt_in_callback_arguments_only_not_all_process_reads"}
    if bound_identity is not None:
        receipt["bound_component_identity"] = bound_identity
        receipt["bound_component_inputs_sha256"] = bound_inputs_sha
    if heldout:
        # This callback purpose never grants a training operation, even when
        # the separately replayed review also permits a training use.
        receipt["training_mask"] = 0
        receipt["heldout_evaluation"] = _reviewed_heldout_component(
            report, admission_copy, rows_copy, manifest, expected_split_manifest_sha256, heldout_evaluation_purpose)
    receipt_raw = _preflight(receipt)
    implementation_guard = _guard(implementation)
    _check(implementation_guard, _reviewed_implementation(), "reviewed implementation")
    for guard, value, label in zip(guards, originals, ("rows", "split manifest", "exposure")):
        _check(guard, value, label)
    _require(_reviewed_snapshot(admission_inputs)[1] == admission_sha
             and _reviewed_snapshot(admission_copy)[1] == admission_sha,
             "admission replay inputs changed during preparation")
    if bound_identity is not None:
        _require(_reviewed_snapshot(bound_component_inputs)[1] == bound_inputs_sha,
                 "bound component replay inputs changed during consumer preparation")
    binding = object.__new__(ReviewedSourceSpanConsumerBinding)
    for name, value in (("_guards", guards), ("_implementation_guard", implementation_guard),
            ("_admission_identity_guard", identity_guard),
            ("_contract_guard", _guard({"version": _admission_version, "schema": schema, "profile": profile})),
            ("_admission_version", _admission_version),
            ("_assessment_time_utc", admission_copy["at_time_utc"]), ("_operation", operation),
            ("_target_codec", target_codec), ("_allow_fictional_fixture", allow_fictional_fixture),
            ("_allow_heldout_evaluation", allow_heldout_evaluation),
            ("_heldout_evaluation_purpose", heldout_evaluation_purpose),
            ("_bound_component_required", bound_identity is not None),
            ("_rows_json", _wire(rows_copy)), ("_receipt_json", receipt_raw)):
        object.__setattr__(binding, name, value)
    return binding


def validate_reviewed_source_span_consumer_binding_v2(binding, rows, *, split_manifest,
        admission_inputs, exposure_records, bound_component_inputs=None):
    """Replay the original V2 domain; V3 bindings cannot be relabeled."""
    return _validate_reviewed_source_span_consumer_binding(binding, rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records,
        _admission_version="v2", bound_component_inputs=bound_component_inputs)


def validate_reviewed_source_span_consumer_binding_v3(binding, rows, *, split_manifest,
        admission_inputs, exposure_records):
    """Replay the explicit V3 domain and present trust before reusing a binding."""
    return _validate_reviewed_source_span_consumer_binding(binding, rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records,
        _admission_version="v3")


def _validate_reviewed_source_span_consumer_binding(binding, rows, *, split_manifest,
        admission_inputs, exposure_records, _admission_version, bound_component_inputs=None):
    """Replay admission at the binding’s assessment time or later."""
    from ipfs_datasets_py.logic.autoformal import legal_graph_review

    _require(_reviewed_binding_version(binding) == _admission_version, "reviewed binding admission contract differs")
    _require(not binding._bound_component_required or bound_component_inputs is not None,
             "current bound component replay is required for this consumer binding")
    _require(binding._bound_component_required or bound_component_inputs is None,
             "fresh consumer preparation is required to add a bound component handoff")
    inputs = (rows, split_manifest, exposure_records)
    _preflight(list(inputs))
    for guard, value, label in zip(binding._guards, inputs, ("rows", "split manifest", "exposure")):
        _check(guard, value, label)
    _check(binding._implementation_guard, _reviewed_implementation(), "reviewed implementation")
    fresh = _prepare_reviewed_source_span_consumer_binding(rows,
        expected_rows_sha256=binding._guards[0].sha256, split_manifest=split_manifest,
        expected_split_manifest_sha256=binding._guards[1].sha256, admission_inputs=admission_inputs,
        expected_admission_inputs_sha256=reviewed_admission_inputs_sha256(admission_inputs),
        exposure_records=exposure_records, expected_exposure_sha256=binding._guards[2].sha256,
        operation=binding._operation, target_codec=binding._target_codec,
        allow_fictional_fixture=binding._allow_fictional_fixture,
        allow_heldout_evaluation=binding._allow_heldout_evaluation,
        heldout_evaluation_purpose=binding._heldout_evaluation_purpose, _admission_version=_admission_version,
        bound_component_inputs=bound_component_inputs)
    receipt = fresh.receipt()
    if receipt["admission_identity_sha256"] != binding._admission_identity_guard.sha256:
        receipt["status"] = "blocked"
        receipt["ready_row_count"] = 0
        receipt["blocked_row_count"] = receipt["row_count"]
        receipt["blockers"].append({"reason": "reviewed_admission_identity_changed"})
        for record in receipt["rows"]:
            record["status"] = "blocked"
        raise SourceSpanConsumerBindingError(
            "reviewed source/target/declaration/preparation/producer/trust identity changed", receipt=receipt)
    current_time = legal_graph_review._time(fresh._assessment_time_utc)
    prepared_time = legal_graph_review._time(binding._assessment_time_utc)
    _require(current_time >= prepared_time, "review evaluation time rollback")
    return receipt


def consume_reviewed_source_span_binding_v2(binding, rows, *, split_manifest, admission_inputs,
        exposure_records, consumer, bound_component_inputs=None):
    """Dispatch once; explicit bound-source snapshots remain current at callback exit."""
    receipt = validate_reviewed_source_span_consumer_binding_v2(binding, rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records,
        bound_component_inputs=bound_component_inputs)
    if receipt["status"] != "ready":
        raise SourceSpanConsumerBindingError("reviewed source-span consumer batch is blocked", receipt=receipt)
    _require(callable(consumer), "explicit callable consumer required")
    consumed_rows = json.loads(binding._rows_json)
    _check(binding._guards[0], consumed_rows, "detached complete reviewed consumer rows")
    if not binding._bound_component_required:
        return consumer(consumed_rows)
    try:
        return consumer(consumed_rows)
    finally:
        # Rejecting a stale result cannot undo callback side effects.
        current = validate_reviewed_source_span_consumer_binding_v2(binding, rows,
            split_manifest=split_manifest, admission_inputs=admission_inputs,
            exposure_records=exposure_records, bound_component_inputs=bound_component_inputs)
        if current["status"] != "ready":
            raise SourceSpanConsumerBindingError("reviewed source-span consumer batch is blocked", receipt=current)
        _check(binding._guards[0], consumed_rows, "detached complete reviewed consumer rows")


def consume_reviewed_source_span_binding_v3(binding, rows, *, split_manifest, admission_inputs,
        exposure_records, consumer):
    """Dispatch full V3 rows once, checking current admission on every callback exit."""
    receipt = validate_reviewed_source_span_consumer_binding_v3(binding, rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
    if receipt["status"] != "ready":
        raise SourceSpanConsumerBindingError("reviewed source-span consumer batch is blocked", receipt=receipt)
    _require(callable(consumer), "explicit callable consumer required")
    consumed_rows = json.loads(binding._rows_json)
    _check(binding._guards[0], consumed_rows, "detached complete reviewed consumer rows")
    try:
        return consumer(consumed_rows)
    finally:
        current = validate_reviewed_source_span_consumer_binding_v3(binding, rows,
            split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
        if current["status"] != "ready":
            raise SourceSpanConsumerBindingError("reviewed source-span consumer batch is blocked", receipt=current)
        _check(binding._guards[0], consumed_rows, "detached complete reviewed consumer rows")


def _reviewed_binding_version(binding):
    _require(type(binding) is ReviewedSourceSpanConsumerBinding, "prepared reviewed consumer binding required")
    version = binding._admission_version
    schema, profile, _, _ = _reviewed_contract(version)
    _check(binding._contract_guard, {"version": version, "schema": schema, "profile": profile},
           "reviewed admission contract")
    return version


def _reviewed_binding_dispatch(binding):
    """Select only fixed operations from the guarded prepared-binding contract."""
    if _reviewed_binding_version(binding) == "v2":
        return validate_reviewed_source_span_consumer_binding_v2, consume_reviewed_source_span_binding_v2
    return validate_reviewed_source_span_consumer_binding_v3, consume_reviewed_source_span_binding_v3


__all__ += ["ReviewedSourceSpanConsumerBinding", "prepare_reviewed_source_span_consumer_binding_v2",
            "validate_reviewed_source_span_consumer_binding_v2", "consume_reviewed_source_span_binding_v2",
            "prepare_reviewed_source_span_consumer_binding_v3", "validate_reviewed_source_span_consumer_binding_v3",
            "consume_reviewed_source_span_binding_v3", "REVIEWED_V3_SCHEMA", "REVIEWED_V3_PROFILE",
            "reviewed_admission_inputs_sha256", "REVIEWED_SCHEMA", "REVIEWED_PROFILE", "REVIEWED_TARGET_CODEC",
            "REVIEWED_HELDOUT_PURPOSE", "REVIEWED_HELDOUT_EXPOSURE",
            "REVIEWED_HELDOUT_CONTEXT_PURPOSE", "REVIEWED_HELDOUT_CONTEXT_PROFILE",
            "REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE", "REVIEWED_V3_HELDOUT_CONTEXT_PROFILE"]


def _reviewed_dependency_closure(admission_inputs):
    """Extract the exact dependency closure from replayed reviewed admission."""
    prepared = admission_inputs.get("preparation")
    original = admission_inputs.get("preparation_inputs")
    _require(type(prepared) is dict and type(original) is dict,
             "complete replayed preparation required for heldout dependencies")
    subject = prepared.get("subject")
    _require(type(subject) is dict, "replayed dependency signing subject required")
    # V2 and V3 explicitly share this unchanged dependency owner, without admission dispatch.
    dependency_owner = _reviewed_admission_owner()._reviewed_owners()[-1]
    try:
        dependency_manifest = dependency_owner.validate_dependency_manifest(
            original["dependency_manifest"], expected_manifest_sha256=original["expected_manifest_sha256"])
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError("invalid heldout dependency manifest: " + str(error)) from error
    required = subject.get("required_dependency_ids")
    _require(type(required) is list and len(required) == len(set(required))
             and set(required) == {item["artifact_id"] for item in dependency_manifest["artifacts"]}
             and subject.get("dependency_manifest_sha256") == original["expected_manifest_sha256"],
             "dependencies must equal the full reviewed root closure")
    return subject, dependency_manifest


def _reviewed_legal_dependency_pins(dependency_manifest):
    return [{"kind": kind, **pin} for item in dependency_manifest["artifacts"]
            for kind in ("root", "source", "revision", "context", "definition")
            for pin in item["dependency_pins"][kind]]


def _reviewed_provision_identity(declaration, unit):
    context = declaration["governing_context"]
    return (context["jurisdiction"], context["instrument_id"], unit["source_version"]["provision_id"])


def _reviewed_heldout_component(report, admission_inputs, rows, manifest, manifest_sha256, purpose):
    """Describe the full heldout component and its signed dependency closure."""
    _require({row["unit_id"] for row in rows} == {unit["unit_id"] for unit in report["units"]},
             "heldout evaluation requires the complete admitted component")
    identifiers = {row["id"] for row in rows}
    rich_context = purpose in (REVIEWED_HELDOUT_CONTEXT_PURPOSE, REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE)
    training_ids = []
    if rich_context:
        partitions = manifest.samples_by_split
        training_ids = partitions[splits.TRAIN_SPLIT]
        _require(training_ids and set(partitions[splits.HOLDOUT_SPLIT]) == identifiers
                 and set(manifest.assignments) == identifiers.union(training_ids),
                 "rich heldout manifest requires the complete holdout and a separate TRAIN population")
    else:
        _require(set(manifest.assignments) == identifiers
                 and {example.sample_id for example in manifest.examples} == identifiers,
                 "heldout manifest population must exactly equal the complete admitted component")
        _require(all(partition == splits.HOLDOUT_SPLIT for partition in manifest.assignments.values()),
                 "complete admitted dependency component must remain in holdout")
    subject, dependency_manifest = _reviewed_dependency_closure(admission_inputs)
    prepared = admission_inputs["preparation"]
    declaration = prepared["declaration"]
    declaration_units = {unit["unit_id"]: unit for unit in declaration["units"]}
    admitted_units = {unit["unit_id"]: unit for unit in report["units"]}
    source_units = [{"id": row["id"], "unit_id": row["unit_id"],
        "source_version_cid": admitted_units[row["unit_id"]]["source_version_cid"],
        "occurrence_cid": admitted_units[row["unit_id"]]["occurrence_cid"],
        "source_artifact_id": declaration_units[row["unit_id"]]["source_artifact_id"],
        "ir_artifact_id": declaration_units[row["unit_id"]]["ir_artifact_id"]} for row in rows]
    group = {"component_id": subject["graph_id"], "declaration_sha256": report["declaration_sha256"],
        "dependency_manifest_sha256": subject["dependency_manifest_sha256"],
        "required_dependency_ids": subject["required_dependency_ids"], "dependencies": [
            {"artifact_id": item["artifact_id"], "artifact_sha256": item["artifact_sha256"]}
            for item in dependency_manifest["artifacts"]], "source_units": source_units}
    if rich_context:
        group["legal_dependency_pins"] = _reviewed_legal_dependency_pins(dependency_manifest)
        for source_unit in source_units:
            declared = declaration_units[source_unit["unit_id"]]
            source_unit.update(source_raw_sha256=declared["source_version"]["raw_artifact"]["sha256"],
                               provision_identity=list(_reviewed_provision_identity(declaration, declared)),
                               source_identity={key: declared["source_version"][key] for key in
                                   ("source_id", "release_id", "edition", "provision_id")},
                               source_extracted_sha256=declared["source_version"]["extracted_view"]["sha256"])
    return {"schema": "reviewed-single-component-heldout/v1", "purpose": purpose,
        "split_manifest_sha256": manifest_sha256, "partition": splits.HOLDOUT_SPLIT,
        "dependency_group": group, "dependency_group_sha256": _guard(group).sha256,
        "population_scope": "exact_complete_admitted_component_only",
        "inference_context_profile": ((REVIEWED_V3_HELDOUT_CONTEXT_PROFILE
            if purpose == REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE else REVIEWED_HELDOUT_CONTEXT_PROFILE)
            if rich_context else "declared_source_only_empty_retrieval_context"),
        "inference_context_enforced": False,
        "retrieved_example_ids": [], "training_example_ids": training_ids,
        "external_training_exposure_verified": False, "model_pretraining_exposure_verified": False,
        "external_retrieval_exclusion_verified": False, "global_dependency_grouping_verified": False,
        "preregistration_time_authenticated": False, "producer_authenticity_verified": False,
        "generalization_established": False, "proof_authority": False}
