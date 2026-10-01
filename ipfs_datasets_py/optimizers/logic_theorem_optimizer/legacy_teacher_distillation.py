"""Prepare screened legacy weak formula labels for separately embedded students.

This seam checks a supplied teacher artifact's internal consistency. Caller
supplied digests are evidence references, not authentication, a new execution
receipt, or semantic ground truth. The teacher's 8D feature target is never
converted to or used as the current model's 384D input. Typed temporal sidecars
remain in the receipt because the existing formula head does not encode them.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from itertools import islice
import json
import re
from .autoencoder_lineages._contract import require_canonical_modules, validate_vector
from .autoencoder_lineages.current_v2 import LegalSample, DIMENSION, LINEAGE_ID
from .legal_modal_parser import LegalModalParser
from . import legal_formula_codec

SCHEMA = "legacy-teacher-current-student-preparation/v1"
MAX_ROWS = 256
MAX_ROW_BYTES = 4 * 1024 * 1024
MAX_BATCH_BYTES = 32 * 1024 * 1024
TEACHER_SCHEMA = "legacy-linguistic-teacher/v1"
TEACHER_POLICY = "single-direct-norm-compiler-supervision/v1"
ORIGIN = "canonical_compiler_supervision_not_neural_generation"
FALSE = {"admitted": False, "formalized": False, "roundtrip_ok": False,
         "semantic_qualification": False, "formula_fidelity_verified": False,
         "independent_formula_generation": False, "lake_executed": False}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ROW_KEYS = {"schema", "sample_id", "source_text", "source_binding", "feature_target",
             "formula_target", "formula_target_origin", "distillation_mask", "evidence", *FALSE}


class DistillationPreparationError(ValueError):
    """Invalid input, ambiguous joins or mutable prepared input were rejected."""


def _require(condition, message):
    if not condition:
        raise DistillationPreparationError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError) as error:
        raise DistillationPreparationError("value must be finite strict JSON") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash(value, name):
    _require(type(value) is str and _HASH.fullmatch(value), name + " requires a lowercase SHA-256")
    return value


def _bounded(values, name):
    rows = list(islice(iter(values), MAX_ROWS + 1))
    _require(len(rows) <= MAX_ROWS, name + " exceeds 256 rows")
    return rows


def _normalized(text):
    return " ".join(text.casefold().split())


def _sample_digest(sample):
    return _digest(sample.to_dict())


@dataclass(frozen=True)
class PreparedTeacherDistillation:
    """Immutable JSON receipts plus checked references to mutable student IR.

    Accessors return copies. Mutating a caller-owned sample after preparation
    invalidates the prepared result; no implicit re-preparation occurs.
    """

    _student_samples: tuple
    _sample_digests: tuple[str, ...]
    _targets_json: bytes
    _receipt_json: bytes

    def validate_inputs(self):
        for sample, expected in zip(self._student_samples, self._sample_digests):
            _require(_sample_digest(sample) == expected, "student sample changed after preparation")

    @property
    def student_samples(self):
        self.validate_inputs()
        return tuple(deepcopy(sample) for sample in self._student_samples)

    @property
    def formula_targets(self):
        return tuple(json.loads(self._targets_json))

    @property
    def receipt(self):
        return json.loads(self._receipt_json)

    def training_inputs(self):
        """Return checked copies for Autoencoder.train_generalizable_projection.

        Supply the targets as ``formula_targets``; the facade dispatches to
        ``modal_joint_formula.train`` with explicit tuning samples and targets.
        """
        return list(self.student_samples), list(self.formula_targets)


def _teacher_target(row, sample, *, expected_teacher_identity_sha256, expected_producer_sha256):
    _require(type(row) is dict and set(row) == _ROW_KEYS, "teacher row has unknown or missing fields")
    _require(row["schema"] == TEACHER_SCHEMA + "/distillation", "unsupported teacher schema")
    _require(row["sample_id"] == sample.sample_id and row["source_text"] == sample.text,
             "teacher target must join the exact student sample ID and text")
    evidence, source = row["evidence"], row["source_binding"]
    _require(type(evidence) is dict and type(source) is dict, "missing teacher evidence or source binding")
    _require(evidence.get("schema") == TEACHER_SCHEMA and evidence.get("policy") == TEACHER_POLICY,
             "unsupported teacher evidence policy")
    _require(evidence.get("sample_id") == sample.sample_id and evidence.get("source_binding") == source,
             "teacher evidence identity or source binding differs")
    _require(set(source) == {"sha256", "corpus", "citation", "producer_sha256", "sample_sha256"},
             "source provenance has unknown or missing fields")
    _require(source["sha256"] == _sha_text(sample.text), "teacher source SHA-256 differs")
    _require(source["citation"] == sample.citation, "teacher source citation differs")
    _require(source["producer_sha256"] == expected_producer_sha256, "teacher producer SHA-256 differs")
    _hash(source["sample_sha256"], "teacher sample digest")
    _require(source["corpus"] in {"authored_fixture", "us_code"}, "unsupported or Constitution source corpus")
    binding = evidence.get("model_binding")
    _require(type(binding) is dict and binding.get("lineage_id") == "legacy_hub_v1"
             and evidence.get("model_lineage") == "legacy_hub_v1", "teacher must identify the preserved 8D lineage")
    _require(type(binding.get("linguistic_identity")) is dict, "missing linguistic producer identity")
    _require(binding.get("linguistic_identity_sha256") == expected_teacher_identity_sha256
             and _digest(binding["linguistic_identity"]) == expected_teacher_identity_sha256,
             "teacher linguistic identity SHA-256 differs")
    _require(binding.get("current_weights_reverified") is False, "unexpected current weight authority")
    for payload in (row, evidence):
        _require(all(payload.get(key) is False for key in FALSE), "teacher row claims unsupported authority")
    _require(evidence.get("full_source_equivalence_proved") is False
             and evidence.get("semantic_embedding_verified") is False
             and evidence.get("sample_memory_used") is False, "teacher evidence claims unsupported qualification")
    mask = row["distillation_mask"]
    _require(type(mask) is dict and set(mask) == {"feature_vector", "historical_formula", "compiler_supervised_formula"}
             and mask.get("feature_vector") is True and mask.get("historical_formula") is False
             and type(mask.get("compiler_supervised_formula")) is bool
             and evidence.get("distillation_mask") == mask, "teacher masks are missing or inconsistent")
    # Inspect for consistency only. These values never enter the student.
    validate_vector(row["feature_target"], 8, "diagnostic legacy feature target")
    _require(row["feature_target"] == evidence.get("teacher_vector"), "legacy feature evidence differs")
    _require(row["formula_target_origin"] == evidence.get("corrected_ir_origin") == ORIGIN,
             "formula target has an unsupported origin")
    _require(mask["compiler_supervised_formula"] is True, "feature_only: no screened formula target")
    _require(evidence.get("status") == "compiler_supervised_candidate" and evidence.get("reasons") == [],
             "formula mask disagrees with screening disposition")
    target, compiler = row["formula_target"], evidence.get("compiler")
    _require(type(compiler) is dict, "missing compiler evidence")
    _require(target == evidence.get("corrected_ir") == {"rules": compiler.get("rules")},
             "formula target differs from compiler supervision")
    _require(compiler.get("status") == compiler.get("cycle_status") == "success"
             and compiler.get("cycle_equal") is True and compiler.get("origin") == "pinned_canonical_compiler"
             and compiler.get("vocabulary_source") == "parser_string_atoms"
             and compiler.get("cycle_vocabulary_source") == "same_original_parser_string_atoms",
             "compiler or exact-cycle evidence is incomplete")
    compile_receipt = compiler.get("receipt")
    _require(type(compile_receipt) is dict and compile_receipt.get("status") == "success"
             and compile_receipt.get("canonical_ir") == target
             and compile_receipt.get("unsupported_semantics") == [], "compiler receipt contradicts target")
    vocabulary = compiler.get("vocabulary")
    _require(type(vocabulary) is dict and set(vocabulary) == {"actors", "actions", "objects", "qualifiers"}
             and all(type(items) is list and all(type(atom) is str for atom in items) for items in vocabulary.values())
             and vocabulary["actors"] and vocabulary["actions"], "missing parser-supplied string vocabulary")
    # Validate the closed target before indexing its rule or temporal facets.
    # Actual training fits its own vocabulary on the training split only.
    legal_formula_codec.fit_codec([{"id": sample.sample_id, "source_text": "latent", "canonical_ir": target}])
    temporal = compiler.get("temporal_records")
    _require(type(temporal) is list and len(temporal) <= 1, "missing or unsupported temporal sidecar")
    _require(len(temporal) == len(target["rules"][0]["temporal"]),
             "temporal sidecar count differs from target atoms")
    for record in temporal:
        _require(type(record) is dict and set(record) == {"temporal_kind", "value", "quantity"}
                 and record["temporal_kind"] in {"minimum_duration", "within_duration", "before_duration", "after_duration", "duration"}
                 and type(record["value"]) is str and record["value"]
                 and (record["quantity"] is None or type(record["quantity"]) is int), "malformed temporal sidecar")
        # Canonical HEAD preserves the direction in a within-duration atom;
        # older producers emitted only its bare value. Do not strip arbitrary
        # temporal prefixes: minimum/after/before are different constraints.
        kind, value = record["temporal_kind"], record["value"]
        recognized_atoms = {value}
        if kind == "within_duration":
            recognized_atoms.add("within " + value)
        _require(any(atom in recognized_atoms for atom in target["rules"][0]["temporal"]),
                 "temporal sidecar differs from target atom")
        # A bare atom alone does not determine its temporal kind. Retain the
        # exact target but also check the kind against its bound source phrase.
        source_prefix = {"within_duration": r"within", "minimum_duration": r"(?:at\s+least|(?:a\s+)?minimum\s+of)",
                         "after_duration": r"after", "before_duration": r"before", "duration": r"for"}[kind]
        source_value = r"\s+".join(re.escape(part) for part in value.split())
        _require(re.search(r"\b" + source_prefix + r"\s+" + source_value + r"(?!\w)", sample.text, re.I) is not None,
                 "temporal sidecar kind or value contradicts source")
        if record["quantity"] is not None:
            number = re.match(r"^(\d+)\b", record["value"])
            _require(number is not None and int(number[1]) == record["quantity"],
                     "temporal quantity contradicts its retained atom")
    return target


def prepare_teacher_distillation(student_samples, teacher_rows, *, expected_teacher_identity_sha256,
                                  expected_producer_sha256, teacher_artifact_sha256, split,
                                  excluded_source_texts=(), excluded_sample_ids=()):
    """Join bounded explicit 384D samples to screened compiler weak labels.

    Teacher rows may be in any order. Extra or absent rows are rejected, never
    guessed. Tuning/holdout callers must supply sources from earlier splits;
    normalized source overlap or duplicate joins abort the batch. Artifact SHA
    membership is caller supplied and is not authenticated by this function.
    """
    for name, value in (("teacher identity", expected_teacher_identity_sha256),
                        ("producer", expected_producer_sha256), ("teacher artifact", teacher_artifact_sha256)):
        _hash(value, name)
    require_canonical_modules("ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder")
    _require(split in {"train", "tuning", "holdout"}, "split must be train, tuning or holdout")
    samples, rows = _bounded(student_samples, "student samples"), _bounded(teacher_rows, "teacher rows")
    _require(samples, "at least one student sample is required")
    excluded_sources = _bounded(excluded_source_texts, "excluded sources")
    excluded_ids = _bounded(excluded_sample_ids, "excluded sample IDs")
    _require(all(type(value) is str and value.strip() and len(value) <= 16384 for value in excluded_sources),
             "excluded sources require bounded text")
    _require(all(type(value) is str and value.strip() for value in excluded_ids), "excluded IDs require text")
    _require(split == "train" or excluded_sources, "tuning and holdout require excluded sources from earlier splits")
    blocked_sources, blocked_ids = {_normalized(value) for value in excluded_sources}, set(excluded_ids)
    normalizer, by_id, seen_sources, total_bytes = LegalModalParser(), {}, set(), 0
    for sample in samples:
        _require(type(sample) is LegalSample, "student requires the current_v2 LegalSample class")
        sample.validate()
        validate_vector(sample.embedding_vector, DIMENSION, "separately supplied current_v2 embedding")
        _require(type(sample.embedding_model) is str and sample.embedding_model.strip(), "student embedding model is required")
        _require(type(sample.sample_id) is str and sample.sample_id.strip() and sample.sample_id not in by_id,
                 "student sample IDs must be unique nonempty strings")
        _require(type(sample.text) is str and 0 < len(sample.text) <= 16384, "student source text exceeds bound")
        normalized = normalizer.normalize_text(sample.text)
        _require(sample.normalized_text == sample.modal_ir.normalized_text == normalized
                 and sample.modal_ir.document_id == sample.sample_id, "student parser features have inconsistent source binding")
        source_key = _normalized(sample.text)
        _require(source_key not in seen_sources, "duplicate normalized student source")
        _require(source_key not in blocked_sources and sample.sample_id not in blocked_ids, "source or ID overlaps an excluded split")
        raw = _raw(sample.to_dict())
        _require(len(raw) <= MAX_ROW_BYTES, "student sample exceeds byte bound")
        total_bytes += len(raw)
        _require(total_bytes <= MAX_BATCH_BYTES, "preparation exceeds byte bound")
        by_id[sample.sample_id], seen_sources = sample, seen_sources | {source_key}
    seen_ids, accepted, targets, accepted_receipts, rejected = set(), [], [], [], []
    for index, row in enumerate(rows):
        raw = _raw(row)
        _require(len(raw) <= MAX_ROW_BYTES, "teacher row exceeds byte bound")
        total_bytes += len(raw)
        _require(total_bytes <= MAX_BATCH_BYTES, "preparation exceeds byte bound")
        row_digest = hashlib.sha256(raw).hexdigest()
        identifier = row.get("sample_id") if type(row) is dict else None
        _require(identifier is None or type(identifier) is str, "teacher sample ID must be a string")
        _require(identifier is None or identifier not in seen_ids, "duplicate teacher sample ID")
        if identifier is not None:
            seen_ids.add(identifier)
        reference = {"teacher_row_index": index, "sample_id": identifier, "teacher_row_sha256": row_digest,
                     "teacher_artifact_sha256": teacher_artifact_sha256}
        try:
            _require(identifier in by_id, "teacher row has no student sample")
            sample = by_id[identifier]
            target = _teacher_target(row, sample,
                expected_teacher_identity_sha256=expected_teacher_identity_sha256,
                expected_producer_sha256=expected_producer_sha256)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            rejected.append({**reference, "reason": str(error), **FALSE})
            continue
        accepted.append(sample)
        targets.append({"id": identifier, "source_text": sample.text, "canonical_ir": target})
        evidence = row["evidence"]
        accepted_receipts.append({**reference, "student_sample_sha256": _sample_digest(sample),
            "student_embedding_model": sample.embedding_model, "source_binding": row["source_binding"],
            "teacher_model_binding": evidence["model_binding"], "distillation_mask": row["distillation_mask"],
            "formula_target_sha256": _digest(target), "formula_target_origin": ORIGIN,
            "temporal_records": evidence["compiler"]["temporal_records"],
            "feature_target_used": False, "teacher_feature_dimension": 8, "student_dimension": DIMENSION, **FALSE})
    for identifier in by_id:
        if identifier in seen_ids:
            continue
        rejected.append({"sample_id": identifier, "teacher_row_index": None, "teacher_row_sha256": None,
                         "teacher_artifact_sha256": teacher_artifact_sha256,
                         "reason": "student sample has no teacher row", **FALSE})
    receipt = {"schema": SCHEMA, "split": split, "student_lineage_id": LINEAGE_ID, "student_dimension": DIMENSION,
        "expected_teacher_identity_sha256": expected_teacher_identity_sha256,
        "expected_producer_sha256": expected_producer_sha256, "teacher_artifact_sha256": teacher_artifact_sha256,
        "integrity_scope": "internal consistency only; artifact membership and producer identity are caller supplied, not authenticated",
        "student_embedding_provenance_verified": False,
        "student_parser_features_independently_verified": False,
        "student_inputs_include_parser_features": True, "source_only_fidelity_evaluation": False,
        "current_teacher_weights_reverified": False, "feature_target_used": False,
        "target_kind": "screened canonical compiler weak supervision; not independent semantic gold",
        "projection_id": "typed_deontic_rule_v1", "temporal_sidecar_encoded_by_formula_head": False,
        "full_logic_floor_coverage": False, "excluded_source_count": len(blocked_sources),
        "excluded_sample_id_count": len(blocked_ids), "input_sample_count": len(samples),
        "input_teacher_row_count": len(rows), "accepted_count": len(accepted), "rejected_count": len(rejected),
        "accepted": accepted_receipts, "rejected": rejected, **FALSE}
    return PreparedTeacherDistillation(tuple(accepted), tuple(_sample_digest(row) for row in accepted),
                                       _raw(targets), _raw(receipt))


__all__ = ["prepare_teacher_distillation", "PreparedTeacherDistillation", "DistillationPreparationError"]
