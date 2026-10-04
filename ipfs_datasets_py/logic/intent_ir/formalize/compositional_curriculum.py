"""Additive authored role/copy curriculum with fixed, disjoint lexical banks.

These labels come from declared templates, not from interpreting public prose.
Opaque action/actor/object atoms exercise role selection and source copying;
success does not establish natural-language or code semantics. Existing source
and codec producers remain unchanged. No diagnostic examples are imported.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

SCHEMA = "intent-compositional-paired-corpus/v1"
POLICY = "authored-intent-copy-composition/v1"
KIND = "authored_compositional_curriculum"
MAX_EXAMPLES = 4096
_PARTITIONS = ("train", "validation", "test")
_MODALITIES = ("intended", "required", "prohibited", "permitted", "recommended")
_FAMILIAR_TRAIN_ACTIONS = ("read", "update", "validate", "write")
_MODALS = {"intended": "intends to", "required": "must", "prohibited": "must not",
           "permitted": "may", "recommended": "should"}
_SIZES = {"train": (4, 8, (1, 2, 3, 4)),
          "validation": (2, 3, (2, 3)), "test": (2, 3, (2, 3))}
_IMPERATIVES = {
    "intended": ("{action} {object}.", "please {action} {object}."),
    "required": ("must {action} {object}.", "required: {action} {object}."),
    "prohibited": ("do not {action} {object}.", "prohibited: {action} {object}."),
    "permitted": ("may {action} {object}.", "permitted: {action} {object}."),
    "recommended": ("should {action} {object}.", "recommended: {action} {object}."),
}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _atom(split, role, ordinal):
    # A new namespace independent of any public or diagnostic vocabulary.
    digest = _sha(_wire([POLICY, "lexical-bank", split, role, ordinal]))[:16]
    return "cx" + role + digest


def lexical_banks():
    """Return fixed authored banks; no data-derived vocabulary or random state."""
    result = {}
    for split, (actors, verbs, lengths) in _SIZES.items():
        result[split] = {
            "actors": [_atom(split, "actor", n) for n in range(actors)],
            "actions": (list(_FAMILIAR_TRAIN_ACTIONS) + [_atom(split, "verb", n) for n in range(4)]
                        if split == "train" else [_atom(split, "verb", n) for n in range(verbs)]),
            "objects": [" ".join(_atom(split, "object", n * 4 + k) for k in range(length))
                        for n, length in enumerate(lengths)],
        }
    all_atoms = [set(bank["actors"] + bank["actions"] +
                     [token for obj in bank["objects"] for token in obj.split()])
                 for bank in result.values()]
    if any(left & right for i, left in enumerate(all_atoms) for right in all_atoms[i + 1:]):
        raise ValueError("authored lexical partitions overlap")
    return result


def _pins():
    from . import roundtrip, rich_span_training
    from .. import schema, decoder
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_text
    modules = (roundtrip, rich_span_training, schema, decoder, autoencoder_paired_text)
    return {__name__: _sha(Path(__file__).read_bytes()), **{
        module.__name__: _sha(Path(module.__file__).read_bytes()) for module in modules}}


def authored_compositional_pairs():
    """Generate 1600/180/180 exact template pairs and their native IR labels."""
    from .roundtrip import canonical_frame_text, frame_to_intent_ir, intent_ir_to_frame
    rows = []
    for split, bank in lexical_banks().items():
        for actor in [*bank["actors"], "unspecified"]:
            for action in bank["actions"]:
                for obj in bank["objects"]:
                    family = {"split": split, "actor": actor, "action": action, "object": obj}
                    group = "authored-composition-family:" + _sha(_wire(family))
                    for modality in _MODALITIES:
                        frame = {"actor": actor, "action": action, "object": obj, "modality": modality}
                        if actor == "unspecified":
                            shapes = _IMPERATIVES[modality]
                            kind = "actor_absent_imperative"
                        else:
                            shapes = ("{actor} {modal} {action} {object}.",
                                      "the {actor} {modal} {action} {object}.")
                            kind = "actor_present_declarative"
                        for variant, template in enumerate(shapes):
                            instruction = template.format(**frame, modal=_MODALS[modality])
                            identity = {"policy": POLICY, "family": group, "modality": modality,
                                        "variant": variant, "instruction": instruction, "frame": frame}
                            document = frame_to_intent_ir(frame, instruction=instruction)
                            if intent_ir_to_frame(document) != frame:
                                raise ValueError("authored native IR does not preserve declared slots")
                            rows.append({
                                "id": "authored-curriculum:" + _sha(_wire(identity)),
                                "group_id": group, "split": split, "instruction": instruction,
                                "frame": frame, "canonical_text": canonical_frame_text(frame),
                                "native_intent_ir": document.to_dict(),
                                "provenance": {"kind": KIND, "source_id": group,
                                    "source_sha256": _sha(instruction.encode()), "label_rule": POLICY,
                                    "template_family": kind, "template_variant": variant,
                                    "template": template, "actor_default": "unspecified" if actor == "unspecified" else None,
                                    "lexical_bank_partition": split, "lexical_semantics": "authored_role_atoms",
                                    "action_origin": "familiar_train_action" if action in _FAMILIAR_TRAIN_ACTIONS else "generated_action_atom",
                                    "modality_semantics": "explicit_template_declaration",
                                    "actor_article_removed_by_template": actor != "unspecified" and variant == 1,
                                    "object_phrase_preserved_exactly": True,
                                    "human_reviewed": False, "gold_source_semantics": False,
                                    "public_source_derived": False, "diagnostic_example_derived": False},
                            })
    return sorted(rows, key=lambda row: row["id"])


def _collision_groups(rows):
    """Locate source-family, literal, model-token, and semantic collisions."""
    from .roundtrip import frame_to_sequence
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize
    indexes = defaultdict(list)
    for row in rows:
        text = " ".join(row["instruction"].lower().split())
        indexes[("source_family", row["group_id"])].append(row)
        indexes[("normalized_input", text)].append(row)
        indexes[("tokenized_input", tuple(tokenize(text)))].append(row)
        indexes[("semantic_frame", frame_to_sequence(row["frame"]))].append(row)
    conflicts = []
    for (kind, _), group in indexes.items():
        cross_partition = len({row["split"] for row in group}) > 1
        incompatible = (kind in {"normalized_input", "tokenized_input"}
                        and len({frame_to_sequence(row["frame"]) for row in group}) > 1)
        if cross_partition or incompatible:
            conflicts.append((kind, "cross_partition" if cross_partition else "conflicting_labels", group))
    return conflicts


def _combine(base_rows, curriculum_rows):
    """Quarantine new conflicting families while preserving every base row."""
    from .roundtrip import validate_frame, canonical_frame_text
    base_ids = {row["id"] for row in base_rows}
    if len(base_ids) != len(base_rows) or _collision_groups(base_rows):
        raise ValueError("existing paired corpus has duplicate identities or split/label conflicts")
    rows = [*base_rows, *curriculum_rows]
    if len(rows) > MAX_EXAMPLES or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("combined curriculum exceeds row bounds or repeats sample IDs")
    for row in rows:
        validate_frame(row["frame"])
        if row["split"] not in _PARTITIONS or row["canonical_text"] != canonical_frame_text(row["frame"]):
            raise ValueError("paired partition or inverse target is malformed")
    blocked, reasons = set(), defaultdict(set)
    for kind, reason, group in _collision_groups(rows):
        for row in group:
            if row["id"] not in base_ids:
                blocked.add(row["group_id"])
                reasons[row["group_id"]].add((kind, reason))
    quarantine = [{"id": row["id"], "group_id": row["group_id"], "split": row["split"],
                   "reason": "authored_family_collides_with_existing_or_other_partition",
                   "collision_categories": [f"{kind}:{reason}" for kind, reason in sorted(reasons[row["group_id"]])]}
                  for row in curriculum_rows if row["group_id"] in blocked]
    kept = [row for row in rows if row["id"] in base_ids or row["group_id"] not in blocked]
    if _collision_groups(kept):
        raise ValueError("curriculum quarantine failed to preserve source/input/frame fences")
    return sorted(kept, key=lambda row: row["id"]), quarantine


def build_compositional_corpus(rich_target_descriptor):
    """Replay existing weak sources and controls, then add authored composition."""
    from .rich_span_training import build_rich_span_pairs
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize, MAX_TOKENS
    from .roundtrip import frame_to_sequence
    base = build_rich_span_pairs(rich_target_descriptor, include_authored=True)
    curriculum = authored_compositional_pairs()
    rows, quarantine = _combine(base["samples"], curriculum)
    for row in rows:
        if (len(row["instruction"]) > 4096 or len(row["instruction"].split()) > 48
                or len(tokenize(row["instruction"])) >= MAX_TOKENS
                or len(tokenize(frame_to_sequence(row["frame"]))) >= 96
                or len(tokenize(row["canonical_text"])) >= 96):
            raise ValueError("combined curriculum exceeds the unchanged codec input bounds")
    base_by_id = {row["id"]: row for row in base["samples"]}
    if any(_wire(row) != _wire(base_by_id[row["id"]]) for row in rows if row["id"] in base_by_id):
        raise ValueError("a preexisting source/control row changed")
    kinds = sorted({row["provenance"]["kind"] for row in rows})
    report = {"schema": SCHEMA, "policy": POLICY, "rich_target_descriptor": dict(rich_target_descriptor),
        "base_corpus_report_sha256": base["report_sha256"], "include_authored_controls": True,
        "producer_sha256": _pins(), "lexical_banks_sha256": _sha(_wire(lexical_banks())),
        "samples": rows, "quarantined": quarantine,
        "base_omitted": base["omitted"], "base_quarantined": base["quarantined"],
        "counts": {"pairs": len(rows), "base_pairs": len(base["samples"]),
            "curriculum_generated": len(curriculum), "curriculum_quarantined": len(quarantine),
            "splits": dict(Counter(row["split"] for row in rows)),
            "by_source": {kind: dict(Counter(row["split"] for row in rows if row["provenance"]["kind"] == kind))
                          for kind in kinds}},
        "supervision": "weak_public_spans_plus_legacy_controls_and_explicit_authored_composition",
        "curriculum_test_scope": "authored_development_holdout_separate_from_any_sealed_external_suite",
        "lexical_bank_policy": {"familiar_train_actions": list(_FAMILIAR_TRAIN_ACTIONS),
            "generated_atoms_disjoint_across_partitions": True,
            "common_grammar_words_shared_across_partitions": True,
            "familiar_actions_may_overlap_existing_training_vocabulary": True},
        "source_content_executed": False, "provider_calls": 0, "diagnostic_examples_used": False,
        "base_rows_and_partitions_preserved": True, "lexical_bank_partitions_disjoint": True,
        "human_reviewed_pair_count": 0, "semantic_correctness_verified": False,
        "conditional_or_sequence_training": False, "qualified": False, "admitted": False}
    report["report_sha256"] = _sha(_wire(report))
    return report


def validate_compositional_corpus(report):
    """Rebuild source decisions, deterministic labels, quarantine, and pins."""
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("compositional authored corpus required")
    expected = build_compositional_corpus(report["rich_target_descriptor"])
    if _wire(report) != _wire(expected):
        raise ValueError("compositional corpus differs from deterministic source/template replay")
