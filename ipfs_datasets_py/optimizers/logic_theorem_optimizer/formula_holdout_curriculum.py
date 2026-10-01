"""Source-only authored curriculum with disjoint actor/action split pairs.

This new panel does not reuse the previously exposed actor curriculum. Its
eight actors occur in training, and all six syntax templates occur in every
split. The two submit templates stay together for each actor, so a held-out
actor/action cannot leak through a different object or temporal qualifier.
Only training rows have optional must variants. No compiler, embedding model,
formula labels, or model predictions are imported or generated here.

The caller must freeze candidates before compiling or evaluating the sealed
sources. Returning source text is not itself enforcement of that boundary.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "authored-action-disjoint-holdout-curriculum/v1"
MAX_BYTES = 256 * 1024
ACTORS = ("auditor", "coordinator", "delegate", "manager", "supervisor", "treasurer", "trustee", "secretary")
TEMPLATES = (
    ("report", "submit", "The {actor} shall submit reports."),
    ("prohibition", "disclose", "The {actor} shall not disclose records."),
    ("minimum", "retain", "The {actor} shall retain the file for at least 20 days."),
    ("deadline", "submit", "The {actor} shall submit backup report within 10 days unless emergency."),
    ("publication", "publish", "The {actor} shall publish notices."),
    ("review", "review", "The {actor} shall review applications."),
)
SPLITS = ("training", "tuning", "sealed_evaluation")
_TUNING = {"auditor": (), "coordinator": ("report", "deadline"), "delegate": ("minimum",),
           "manager": ("publication",), "supervisor": ("review",), "treasurer": ("prohibition",),
           "trustee": ("publication",), "secretary": ("review",)}
_SEALED = {"auditor": ("report", "deadline"), "coordinator": (), "delegate": ("prohibition",),
           "manager": ("minimum",), "supervisor": ("publication",), "treasurer": ("review",),
           "trustee": ("prohibition",), "secretary": ("minimum",)}
FALSE = {"admitted": False, "formalized": False, "roundtrip_ok": False, "qualified": False,
         "independent_legal_gold": False, "semantic_correctness_verified": False,
         "lake_executed": False, "compiler_labels_present": False, "model_predictions_present": False}
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class HoldoutCurriculumError(ValueError):
    """The authored version, split, source exclusions or integrity pin differs."""


def _require(condition, message):
    if not condition:
        raise HoldoutCurriculumError(message)


def _raw(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise HoldoutCurriculumError("curriculum requires strict finite JSON") from error
    _require(len(encoded) <= MAX_BYTES, "curriculum exceeds byte bound")
    return encoded


def manifest_digest(value):
    """Digest canonical JSON; fixture file bytes have a separate explicit pin."""
    return hashlib.sha256(_raw(value)).hexdigest()


def _source(text):
    return " ".join(text.casefold().split())


def build_authored_panel():
    """Build fixed source assignments without processing any formula labels."""
    rows = []
    for actor in ACTORS:
        for identifier, action, pattern in TEMPLATES:
            split = ("tuning" if identifier in _TUNING[actor] else
                     "sealed_evaluation" if identifier in _SEALED[actor] else "training")
            rows.append({"id": f"action-disjoint-v1-{actor}-{identifier}", "actor": actor,
                         "norm_template_id": identifier, "split": split,
                         "text": pattern.format(actor=actor), "corpus": "authored_fixture"})
    return {"schema": SCHEMA, "scope": "authored compositional source panel; no independent legal gold",
            "actors": list(ACTORS),
            "norm_templates": [{"id": name, "action_surface": action, "text_template": template}
                               for name, action, template in TEMPLATES],
            "split_policy": {"pair_keys": [["actor", "norm_template_id"], ["actor", "action_surface"]],
                "training_count": 32, "tuning_count": 8, "sealed_evaluation_count": 8,
                "submit_templates_co_located": True, "tuning_by_actor": {a: list(_TUNING[a]) for a in ACTORS},
                "sealed_by_actor": {a: list(_SEALED[a]) for a in ACTORS},
                "candidate_freeze_required_before_sealed_labels_or_predictions": True},
            "training_augmentation": {"id": "shall_to_must_training_v1", "source": " shall ",
                                      "replacement": " must ", "variants_per_training_parent": 1},
            "rows": rows, **FALSE}


def _variants(training):
    result = []
    for parent in training:
        _require(parent["split"] == "training", "only training sources may be expanded")
        _require(parent["text"].count(" shall ") == 1, "training parent requires one shall token")
        result.append(dict(parent, id=parent["id"] + "-must-v1", parent_id=parent["id"],
                           parent_source_sha256=hashlib.sha256(parent["text"].encode()).hexdigest(),
                           text=parent["text"].replace(" shall ", " must ")))
    return result


@dataclass(frozen=True)
class PreparedHoldoutCurriculum:
    """Canonical bytes own source data; returned dictionaries are fresh copies."""

    _manifest_json: bytes
    _receipt_json: bytes

    @property
    def manifest(self):
        return json.loads(self._manifest_json)

    @property
    def manifest_sha256(self):
        return hashlib.sha256(self._manifest_json).hexdigest()

    @property
    def receipt(self):
        return json.loads(self._receipt_json)

    def rows(self, split):
        _require(split in SPLITS, "unknown source split")
        return [row for row in self.manifest["rows"] if row["split"] == split]

    def training_variants(self):
        """Return only the 32 training paraphrases, each bound to its parent."""
        return _variants(self.rows("training"))

    def training_rows(self, *, include_must=False):
        _require(type(include_must) is bool, "include_must requires a boolean")
        return self.rows("training") + (self.training_variants() if include_must else [])

    def development_rows(self, *, include_must=False):
        """Return 40 or 72 training/tuning sources; sealed sources are excluded."""
        return self.training_rows(include_must=include_must) + self.rows("tuning")


def prepare_curriculum(panel, *, excluded_source_texts, expected_manifest_sha256):
    """Validate source design and caller-declared earlier exposures.

    The pin records integrity, not authentication. Exclusions cover all base
    sources and training variants. Callers own the provenance and completeness
    of the earlier-exposure list and the later candidate-freeze boundary.
    """
    _require(type(expected_manifest_sha256) is str and _SHA.fullmatch(expected_manifest_sha256),
             "explicit lowercase curriculum SHA-256 required")
    encoded = _raw(panel)
    digest = hashlib.sha256(encoded).hexdigest()
    _require(digest == expected_manifest_sha256, "curriculum manifest SHA-256 differs")
    _require(encoded == _raw(build_authored_panel()), "source fields, rows or split policy differ from v1")
    _require(type(excluded_source_texts) in (tuple, list) and 1 <= len(excluded_source_texts) <= 1024
             and all(type(text) is str and text.strip() and len(text) <= 16384 for text in excluded_source_texts),
             "explicit bounded previously exposed source texts required")
    excluded = {_source(text) for text in excluded_source_texts}
    prepared = PreparedHoldoutCurriculum(encoded, b"{}")
    variants = prepared.training_variants()
    all_rows = panel["rows"] + variants
    ids = [row["id"] for row in all_rows]
    sources = [_source(row["text"]) for row in all_rows]
    _require(len(ids) == len(set(ids)) == len(set(sources)) == 80, "source IDs or texts are duplicated")
    _require(not set(sources) & excluded, "source overlaps an earlier exposed corpus")
    actions = {name: action for name, action, _ in TEMPLATES}
    seen_templates, seen_actions, statistics = set(), set(), {}
    for split, expected in (("training", 32), ("tuning", 8), ("sealed_evaluation", 8)):
        rows = prepared.rows(split)
        templates = {(row["actor"], row["norm_template_id"]) for row in rows}
        action_pairs = {(row["actor"], actions[row["norm_template_id"]]) for row in rows}
        _require(len(rows) == len(templates) == expected, "source split count differs")
        _require(not seen_templates & templates and not seen_actions & action_pairs,
                 "actor/template or actor/action leaks across splits")
        seen_templates |= templates
        seen_actions |= action_pairs
        statistics[split] = {"row_count": len(rows), "actor_count": len({row["actor"] for row in rows}),
            "actor_counts": dict(sorted(Counter(row["actor"] for row in rows).items())),
            "template_counts": dict(sorted(Counter(row["norm_template_id"] for row in rows).items())),
            "actor_action_pair_count": len(action_pairs)}
        _require(set(statistics[split]["template_counts"]) == set(actions), "split does not cover all six templates")
    _require(statistics["training"]["actor_count"] == 8
             and statistics["tuning"]["actor_count"] == statistics["sealed_evaluation"]["actor_count"] == 7,
             "actor coverage differs from fixed action-group allocation")
    receipt = {"schema": SCHEMA + "/preparation", "manifest_sha256": digest,
        "source_row_count": 48, "training_variant_count": 32, "augmented_training_count": 64,
        "development_source_count": 72, "variant_manifest_sha256": manifest_digest(variants),
        "splits": statistics, "actor_template_disjoint_splits": True, "actor_action_disjoint_splits": True,
        "normalized_source_disjoint_splits": True, "all_actors_represented_in_training": True,
        "all_templates_represented_in_each_split": True, "nontraining_augmentation_count": 0,
        "earlier_exposed_source_count": len(excluded), "earlier_exposed_sources_sha256": manifest_digest(sorted(excluded)),
        "integrity_scope": "caller-declared pins and exclusions; not authentication",
        "sealed_label_boundary": "caller must freeze all scored candidates before generating or reading sealed labels/predictions",
        "compiler_label_consistency_checked": False, "target_vocabulary_coverage_checked": False,
        "independent_semantic_validation": False,
        "limitations": ["authored source composition, not sampled federal law or independent semantic gold",
                        "held-out rows are correlated: seven actors, with two submit templates sharing one actor/action",
                        "training covers all eight actors; this does not test unseen-actor vocabulary",
                        "label and prediction access separation is enforced by the experiment runner, not this source library"],
        **FALSE}
    return PreparedHoldoutCurriculum(encoded, _raw(receipt))


def load_curriculum(path, *, expected_file_sha256, **options):
    """Read one bounded source fixture, rejecting duplicate keys and drift."""
    _require(type(expected_file_sha256) is str and _SHA.fullmatch(expected_file_sha256),
             "explicit lowercase fixture SHA-256 required")
    path = Path(path)
    _require(path.is_file() and 0 < path.stat().st_size <= MAX_BYTES, "bounded source fixture required")
    content = path.read_bytes()
    _require(len(content) <= MAX_BYTES and hashlib.sha256(content).hexdigest() == expected_file_sha256,
             "fixture file SHA-256 differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate source JSON key")
            result[key] = value
        return result
    try:
        panel = json.loads(content, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise HoldoutCurriculumError("invalid source fixture JSON") from error
    return prepare_curriculum(panel, **options)


__all__ = ["SCHEMA", "ACTORS", "TEMPLATES", "SPLITS", "HoldoutCurriculumError", "PreparedHoldoutCurriculum",
           "manifest_digest", "build_authored_panel", "prepare_curriculum", "load_curriculum"]
