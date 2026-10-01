"""Fixed authored actor/template splits for a bounded data ablation.

The panel contains source text and authoring metadata, never formula gold or
model predictions. Balanced marginals do not imply statistical independence:
withheld pairs deliberately leave holes in the training Cartesian product.
Prepare and save the manifest before fitting; evaluate sealed rows only after
selection. This module cannot enforce that process boundary on an external
caller and grants no semantic qualification or Lake admission.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "authored-actor-composition-panel/v1"
MAX_BYTES = 1024 * 1024
SPLITS = ("training", "tuning", "sealed_evaluation")
ACTORS = ("registrar", "board", "inspector", "administrator", "custodian", "clerk")
TEMPLATES = (
    ("report", "submit", "The {actor} shall submit reports."),
    ("prohibition", "disclose", "The {actor} shall not disclose records."),
    ("minimum", "retain", "The {actor} shall retain the file for at least 20 days."),
    ("deadline", "submit", "The {actor} shall submit backup report within 10 days unless emergency."),
    ("publication", "publish", "The {actor} shall publish notices."),
    ("review", "review", "The {actor} shall review applications."),
)
POLICY = {"training_offsets": [0, 1, 2, 3], "tuning_offsets": [4], "sealed_evaluation_offsets": [5],
          "offset_definition": "(template_index-actor_index)%6", "pair_key": ["actor", "norm_template_id"],
          "evaluation_labels_used_for_selection": False}
FALSE = {"admitted": False, "formalized": False, "roundtrip_ok": False, "qualified": False,
         "independent_legal_gold": False, "semantic_correctness_verified": False, "lake_executed": False}
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class CurriculumError(ValueError):
    """A panel is ambiguous, unbalanced, contaminated or not the pinned manifest."""


def _require(condition, message):
    if not condition:
        raise CurriculumError(message)


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise CurriculumError("curriculum must be finite strict JSON") from error
    _require(len(raw) <= MAX_BYTES, "curriculum exceeds byte bound")
    return raw


def manifest_digest(panel):
    """SHA-256 of sorted-key, compact, ASCII-escaped UTF-8 JSON, not file bytes."""
    return hashlib.sha256(_raw(panel)).hexdigest()


def _source(text):
    return " ".join(text.casefold().split())


def _actor(actor):
    return re.sub(r"^(?:the|a|an)\s+", "", _source(actor))


def build_authored_panel():
    """Return the fixed 36 sources without a parser, model or random sampling."""
    rows = []
    for actor_index, actor in enumerate(ACTORS):
        for template_index, (template_id, action, pattern) in enumerate(TEMPLATES):
            offset = (template_index - actor_index) % len(ACTORS)
            split = "training" if offset <= 3 else "tuning" if offset == 4 else "sealed_evaluation"
            rows.append({"id": f"composition-{actor}-{template_id}", "actor": actor,
                         "norm_template_id": template_id, "split": split,
                         "text": pattern.format(actor=actor), "corpus": "authored_fixture"})
    return {"schema": SCHEMA, "scope": "authored compositional diagnostic; not independently reviewed legal gold",
            "actors": list(ACTORS), "norm_templates": [dict(id=identifier, action_surface=action, text_template=pattern)
                                                       for identifier, action, pattern in TEMPLATES],
            "split_policy": json.loads(_raw(POLICY)), "rows": rows, **FALSE}


def _association(rows, feature):
    pairs = Counter((row["actor"], row[feature]) for row in rows)
    actors, values, total = Counter(), Counter(), len(rows)
    for (actor, value), count in pairs.items():
        actors[actor] += count
        values[value] += count
    information = sum(count / total * math.log2(count * total / (actors[actor] * values[value]))
                      for (actor, value), count in pairs.items())
    return {"pair_counts": [{"actor": actor, "value": value, "count": count}
                            for (actor, value), count in sorted(pairs.items())],
            "actor_counts": dict(sorted(actors.items())), "value_counts": dict(sorted(values.items())),
            "mutual_information_bits": information,
            "max_actor_fraction_given_value": max(count / values[value] for (actor, value), count in pairs.items()),
            "max_value_fraction_given_actor": max(count / actors[actor] for (actor, value), count in pairs.items()),
            "actor_deterministic_given_value": all(len({actor for actor, item in pairs if item == value}) == 1
                                                   for value in values),
            "independence_established": False}


def _statistics(rows, templates):
    enriched = [dict(row, action_surface=templates[row["norm_template_id"]]["action_surface"]) for row in rows]
    actors = sorted({row["actor"] for row in rows})
    template_ids = sorted({row["norm_template_id"] for row in rows})
    words = sorted({word.casefold() for row in rows for word in re.findall(r"\w+|[^\w\s]", row["text"])})
    return {"row_count": len(rows), "actors": actors, "norm_template_ids": template_ids,
            "surface_vocabulary_sha256": manifest_digest(words), "surface_vocabulary_size": len(words),
            "actor_template": _association(enriched, "norm_template_id"),
            "actor_action": _association(enriched, "action_surface")}


@dataclass(frozen=True)
class PreparedCurriculum:
    """Copy-safe source manifest and coverage receipt; no evaluation formulas."""

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

    def rows(self, split, *, training_subset="balanced"):
        _require(split in SPLITS, "unknown curriculum split")
        _require(training_subset in {"balanced", "confounded_diagonal"}, "unknown training subset")
        _require(split == "training" or training_subset == "balanced", "subsets apply only to training")
        panel = self.manifest
        rows = [row for row in panel["rows"] if row["split"] == split]
        if training_subset == "confounded_diagonal":
            actors = {value: index for index, value in enumerate(panel["actors"])}
            templates = {value["id"]: index for index, value in enumerate(panel["norm_templates"])}
            rows = [row for row in rows if actors[row["actor"]] == templates[row["norm_template_id"]]]
        return rows


def prepare_curriculum(panel, *, excluded_source_texts, excluded_evaluation_actor_actions,
                       expected_manifest_sha256=None):
    """Validate a fixed panel and caller-declared previously exposed sources.

    Exclusion lists and expected digests are explicit campaign inputs, not
    authenticated provenance. The returned receipt records their hashes/counts.
    There are no formula labels, embedding vectors or predictions in this API.
    """
    raw = _raw(panel)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_manifest_sha256 is not None:
        _require(type(expected_manifest_sha256) is str and _HASH.fullmatch(expected_manifest_sha256),
                 "expected manifest requires lowercase SHA-256")
        _require(digest == expected_manifest_sha256, "curriculum manifest SHA-256 differs")
    _require(type(panel) is dict and set(panel) == set(build_authored_panel()), "panel fields differ")
    _require(panel["schema"] == SCHEMA and panel["scope"] == build_authored_panel()["scope"], "unsupported panel schema or scope")
    _require(all(panel[name] is False for name in FALSE), "curriculum cannot assert qualification")
    _require(panel["actors"] == list(ACTORS) and panel["norm_templates"] == build_authored_panel()["norm_templates"],
             "v1 authoring actors or templates differ; create a new panel version")
    _require(_raw(panel["split_policy"]) == _raw(POLICY), "curriculum split policy differs")
    _require(type(excluded_source_texts) in (tuple, list) and 1 <= len(excluded_source_texts) <= 256
             and all(type(text) is str and text.strip() and len(text) <= 16384 for text in excluded_source_texts),
             "explicit bounded previously exposed source texts required")
    _require(type(excluded_evaluation_actor_actions) in (tuple, list) and 1 <= len(excluded_evaluation_actor_actions) <= 256,
             "explicit previously exposed evaluation actor/action pairs required")
    excluded_pairs = set()
    for pair in excluded_evaluation_actor_actions:
        _require(type(pair) in (tuple, list) and len(pair) == 2
                 and all(type(value) is str and value.strip() for value in pair), "malformed excluded actor/action pair")
        excluded_pairs.add((_actor(pair[0]), _source(pair[1])))
    excluded_sources = {_source(text) for text in excluded_source_texts}
    _require(type(panel["rows"]) is list and len(panel["rows"]) == 36, "v1 requires all 36 authored pairs")
    templates = {item["id"]: item for item in panel["norm_templates"]}
    expected_rows = {row["id"]: row for row in build_authored_panel()["rows"]}
    ids, sources, pairs = set(), set(), set()
    for row in panel["rows"]:
        _require(type(row) is dict and set(row) == {"id", "actor", "norm_template_id", "split", "text", "corpus"},
                 "curriculum row has unknown or missing fields")
        _require(all(type(value) is str for value in row.values()), "curriculum row fields require exact strings")
        _require(row["id"] in expected_rows and row == expected_rows[row["id"]], "row differs from deterministic source/split assignment")
        source, pair = _source(row["text"]), (row["actor"], row["norm_template_id"])
        _require(row["id"] not in ids and source not in sources and pair not in pairs,
                 "duplicate ID, normalized source or actor/template pair")
        _require(source not in excluded_sources, "source overlaps a previously exposed panel")
        action_pair = (_actor(row["actor"]), templates[row["norm_template_id"]]["action_surface"])
        _require(row["split"] != "sealed_evaluation" or action_pair not in excluded_pairs,
                 "evaluation actor/action pair overlaps previously exposed evaluation")
        ids.add(row["id"]); sources.add(source); pairs.add(pair)
    # Stable row ordering is part of the manifest and any future run identity.
    _require(panel["rows"] == build_authored_panel()["rows"], "curriculum row ordering differs")
    prepared = PreparedCurriculum(raw, b"{}")
    stats = {split: _statistics(prepared.rows(split), templates) for split in SPLITS}
    diagonal = _statistics(prepared.rows("training", training_subset="confounded_diagonal"), templates)
    for split, count in (("training", 4), ("tuning", 1), ("sealed_evaluation", 1)):
        _require(set(stats[split]["actor_template"]["actor_counts"].values()) == {count}
                 and set(stats[split]["actor_template"]["value_counts"].values()) == {count}, "split marginals are not balanced")
    _require(stats["training"]["actors"] == diagonal["actors"] and
             stats["training"]["norm_template_ids"] == diagonal["norm_template_ids"] and
             stats["training"]["surface_vocabulary_sha256"] == diagonal["surface_vocabulary_sha256"],
             "training variants do not share actor/template/surface coverage")
    receipt = {"schema": SCHEMA + "/preparation", "manifest_sha256": digest,
        "scope": "authored source design and split consistency; not teacher label accuracy or model evaluation",
        "source_row_count": 36, "pair_disjoint_splits": True, "normalized_source_disjoint_splits": True,
        "previous_source_count": len(excluded_sources), "previous_sources_sha256": manifest_digest(sorted(excluded_sources)),
        "previous_evaluation_pair_count": len(excluded_pairs), "previous_evaluation_pairs_sha256": manifest_digest(sorted(excluded_pairs)),
        "fixed_before_training_required": True, "evaluation_labels_used_for_selection": False,
        "evaluation_seal_enforcement": "required of caller; not enforced by this source-only library", "evaluation_labels_present": False,
        "compiler_label_coverage_verified": False, "formula_vocabulary_equality_verified": False,
        "actor_template_surface_coverage_equal": True, "splits": stats, "confounded_diagonal": diagonal,
        "ablation_scope": "training data ablation; equal optimizer steps do not imply equal distinct training examples",
        "limitation": "balanced marginals still have nonzero association from withheld pairs; no generalization guarantee",
        **FALSE}
    return PreparedCurriculum(raw, _raw(receipt))


def load_curriculum(path, *, expected_file_sha256=None, **options):
    """Read bounded JSON, rejecting duplicate keys before manifest validation."""
    path = Path(path)
    _require(path.stat().st_size <= MAX_BYTES, "curriculum file exceeds byte bound")
    raw = path.read_bytes()
    if expected_file_sha256 is not None:
        _require(type(expected_file_sha256) is str and _HASH.fullmatch(expected_file_sha256), "file pin requires lowercase SHA-256")
        _require(hashlib.sha256(raw).hexdigest() == expected_file_sha256, "curriculum file SHA-256 differs")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "duplicate curriculum JSON key")
            value[key] = item
        return value
    try:
        panel = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as error:
        raise CurriculumError("invalid curriculum JSON") from error
    return prepare_curriculum(panel, **options)


__all__ = ["build_authored_panel", "load_curriculum", "prepare_curriculum", "manifest_digest", "PreparedCurriculum", "CurriculumError"]
