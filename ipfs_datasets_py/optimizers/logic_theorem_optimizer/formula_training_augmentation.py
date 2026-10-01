"""Versioned source-only ``shall`` to ``must`` training augmentation.

Only the 24 training pairs in the fixed actor curriculum can be augmented.
This module supplies neither compiler labels nor semantic gold. Callers must
compile each variant separately, compare its rule and typed temporal sidecar
with its parent, and verify equal target vocabularies before a data ablation.
Tuning remains selection data; no evaluation formulas are needed here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from . import formula_curriculum as curriculum_module

SCHEMA = "authored-training-must-augmentation/v1"
MAX_BYTES = 128 * 1024
TRANSFORMATION = {"id": "shall_to_must_training_v1", "source": " shall ",
                  "replacement": " must ", "occurrences_per_parent": 1}
FALSE = {"admitted": False, "qualified": False, "formalized": False, "roundtrip_ok": False,
         "independent_legal_gold": False, "semantic_correctness_verified": False,
         "lake_executed": False, "model_predictions_executed": False,
         "evaluation_labels_used": False}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class AugmentationError(ValueError):
    """The source augmentation is not the exact declared training variant."""


def _require(condition, message):
    if not condition:
        raise AugmentationError(message)


def _raw(value):
    try:
        value = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError, OverflowError) as error:
        raise AugmentationError("augmentation must be finite strict JSON") from error
    _require(len(value) <= MAX_BYTES, "augmentation exceeds byte bound")
    return value


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), label + " requires lowercase SHA-256")


def _source(text):
    return " ".join(text.casefold().split())


def _parent(curriculum, expected):
    _pin(expected, "parent curriculum")
    _require(type(curriculum) is curriculum_module.PreparedCurriculum,
             "validated authored curriculum required")
    panel = curriculum.manifest
    _require(curriculum.manifest_sha256 == expected, "parent curriculum manifest SHA-256 differs")
    # A matching caller pin alone is not authority to add a different split or
    # to reinterpret an old fixture version. New authoring needs a new version.
    _require(_raw(panel) == _raw(curriculum_module.build_authored_panel()),
             "unsupported parent curriculum version or rows")
    training = curriculum.rows("training")
    _require(len(training) == 24, "exactly 24 original training pairs required")
    training_pairs = {(row["actor"], row["norm_template_id"]) for row in training}
    nontraining = [row for row in panel["rows"] if row["split"] != "training"]
    _require(not training_pairs & {(row["actor"], row["norm_template_id"]) for row in nontraining},
             "training pairs overlap another split")
    return panel, training


@dataclass(frozen=True)
class PreparedMustAugmentation:
    """Canonical bytes own the manifest; public dictionaries are fresh copies."""

    _manifest_json: bytes
    _receipt_json: bytes

    @property
    def manifest(self):
        return json.loads(self._manifest_json)

    @property
    def manifest_sha256(self):
        return _sha(self._manifest_json)

    @property
    def receipt(self):
        return json.loads(self._receipt_json)

    def rows(self):
        """Return the 24 paraphrases, excluding their original training parents."""
        return self.manifest["rows"]


def prepare_must_augmentation(curriculum, *, expected_curriculum_manifest_sha256):
    """Derive exactly one source variant for every original training pair.

    Parent pins establish caller-declared integrity, not authentication or
    semantic correctness. Source-only nontraining rows are checked for overlap;
    their formula targets and model predictions are never requested or read.
    """
    panel, training = _parent(curriculum, expected_curriculum_manifest_sha256)
    rows = []
    original_ids = {row["id"] for row in panel["rows"]}
    original_sources = {_source(row["text"]) for row in panel["rows"]}
    for parent in training:
        _require(parent["split"] == "training" and parent["corpus"] == "authored_fixture",
                 "only authored training parents may be augmented")
        _require(parent["text"].count(TRANSFORMATION["source"]) == 1,
                 "parent requires exactly one shall token")
        row = dict(parent, id=parent["id"] + "-must-v1",
                   text=parent["text"].replace(TRANSFORMATION["source"], TRANSFORMATION["replacement"]),
                   parent_id=parent["id"], parent_source_sha256=_sha(parent["text"].encode()))
        _require(row["id"] not in original_ids and _source(row["text"]) not in original_sources,
                 "augmentation overlaps an original source or ID")
        rows.append(row)
    _require(len({row["id"] for row in rows}) == len({_source(row["text"]) for row in rows}) == 24,
             "augmented sources or IDs are duplicated")
    manifest = {"schema": SCHEMA,
                "scope": "authored training-only source paraphrases; compile and screen labels separately",
                "parent_curriculum_manifest_sha256": expected_curriculum_manifest_sha256,
                "transformation": dict(TRANSFORMATION), "rows": rows, **FALSE}
    manifest_json = _raw(manifest)
    receipt = {"schema": "training-must-augmentation-preparation/v1",
               "manifest_sha256": _sha(manifest_json),
               "parent_curriculum_manifest_sha256": expected_curriculum_manifest_sha256,
               "parent_count": 24, "paraphrase_count": 24, "combined_training_count": 48,
               "training_actor_template_pairs_preserved": True, "nontraining_pairs_added": 0,
               "tuning_sources_augmented": False, "evaluation_sources_augmented": False,
               "compiler_labels_supplied": False, "compiler_consistency_checked": False,
               "target_vocabulary_equality_checked": False, "embeddings_supplied": False,
               "required_downstream_checks": ["separate verified semantic embeddings for each source",
                   "screen parent and paraphrase with pinned compiler", "exact canonical rule equality",
                   "exact typed temporal sidecar equality", "identical training target vocabularies"],
               "integrity_scope": "caller pins and deterministic derivation; not authentication", **FALSE}
    return PreparedMustAugmentation(manifest_json, _raw(receipt))


def load_must_augmentation(path, curriculum, *, expected_file_sha256, expected_curriculum_manifest_sha256):
    """Read an explicit bounded fixture and require the exact v1 derivation."""
    _pin(expected_file_sha256, "augmentation file")
    path = Path(path)
    _require(path.is_file() and 0 < path.stat().st_size <= MAX_BYTES, "bounded augmentation fixture required")
    content = path.read_bytes()
    _require(len(content) <= MAX_BYTES and _sha(content) == expected_file_sha256,
             "augmentation file SHA-256 differs")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "duplicate augmentation JSON key")
            value[key] = item
        return value
    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise AugmentationError("augmentation fixture is not valid JSON") from error
    prepared = prepare_must_augmentation(curriculum,
        expected_curriculum_manifest_sha256=expected_curriculum_manifest_sha256)
    _require(_raw(value) == prepared._manifest_json, "augmentation differs from the declared training derivation")
    return prepared


__all__ = ["SCHEMA", "AugmentationError", "PreparedMustAugmentation",
           "prepare_must_augmentation", "load_must_augmentation"]
