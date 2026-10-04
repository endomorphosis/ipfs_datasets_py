"""Explicit weak and authored pairs for bounded instruction/IntentIR training.

The public SkillCenter export does not contain reviewed semantic labels. This
module selects only simple clauses and records the precise extraction rule and
source spans. It does not execute skill text or interpret arbitrary prose. The
authored contrasts are development controls, not human-reviewed source labels.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA = "intent-roundtrip-paired-corpus/v1"
FRAME_SCHEMA = "intent-roundtrip-action-frame/v1"
MODALITIES = ("intended", "required", "prohibited", "permitted", "recommended")
_MODAL_TEXT = {"intended": "intends to", "required": "must", "prohibited": "must not",
               "permitted": "may", "recommended": "should"}
_ACTORS = ("agent", "developer", "operator", "system")
_ACTIONS = ("read", "update", "delete", "validate")
_OBJECTS = ("report", "cache", "fixture")
_SOURCE_ACTIONS = frozenset((
    "add build check compile configure create delete deploy document enable fix inspect install "
    "list load open pin read remove run save scan store test update validate verify write"
).split())
_SOURCE_ACTORS = frozenset((*_ACTORS, "user", "service", "administrator"))
_ACTOR_PATTERN = "|".join(sorted(_SOURCE_ACTORS))
_CLAUSE = re.compile(
    rf"^(?:(?:the )?(?P<actor>{_ACTOR_PATTERN}) )?"
    r"(?:(?P<modal>must not|shall not|do not|never|must|shall|should|may|intends to) )?"
    r"(?P<action>[a-z]+) (?P<object>[a-z][a-z0-9 _-]*?)[.]?$", re.IGNORECASE)
_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_OBJECT_BLOCKERS = frozenset((
    "if when unless until before after then without except otherwise because and or not never "
    "must may should shall to that whether while assuming all any every each"
).split())
_HEADING_FORCE = {
    "must do": "required", "must not do": "prohibited", "required": "required",
    "prohibited": "prohibited", "recommended": "recommended", "permitted": "permitted",
}


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_intent_text(frame: Mapping[str, str]) -> str:
    """Render a declared frame for training labels, never for model inference."""
    validate_intent_frame(frame)
    return f"{frame['actor']} {_MODAL_TEXT[frame['modality']]} {frame['action']} {frame['object']}."


def validate_intent_frame(frame: Mapping[str, str]) -> None:
    if not isinstance(frame, Mapping) or set(frame) != {"actor", "action", "object", "modality"}:
        raise ValueError("an exact four-slot Intent action frame is required")
    if any(not isinstance(v, str) or not v or len(v) > 160 for v in frame.values()):
        raise ValueError("Intent action frame fields require bounded nonempty text")
    if frame["modality"] not in MODALITIES:
        raise ValueError("unsupported Intent modality")
    if not re.fullmatch(r"[a-z]+", frame["actor"]) or not re.fullmatch(r"[a-z]+", frame["action"]):
        raise ValueError("actor and action must be lowercase lexical atoms")
    if not re.fullmatch(r"[a-z][a-z0-9 _-]*", frame["object"]):
        raise ValueError("object must be a bounded lowercase opaque atom phrase")
    if len(frame["object"].split()) > 12:
        raise ValueError("object phrase exceeds the 12-word bound")


def _split(group: str) -> str:
    # Freeze source-family membership before fitting. Modal contrasts and
    # paraphrases all remain inside one actor/action/object family.
    bucket = int(_sha(group.encode())[:8], 16) % 10
    return "test" if bucket == 0 else "validation" if bucket == 1 else "train"


def authored_intent_pairs() -> list[dict[str, Any]]:
    """Return 720 explicit development examples, with no public-source claims."""
    patterns = {
        "intended": ("please ask the {actor} to {action} the {object}.",
                     "the {actor} intends to {action} the {object}."),
        "required": ("the {actor} must {action} the {object}.",
                     "the {actor} is required to {action} the {object}."),
        "prohibited": ("the {actor} must not {action} the {object}.",
                       "the {actor} is forbidden to {action} the {object}."),
        "permitted": ("the {actor} may {action} the {object}.",
                      "the {actor} is allowed to {action} the {object}."),
        "recommended": ("the {actor} should {action} the {object}.",
                        "the {actor} is advised to {action} the {object}."),
    }
    result = []
    for actor in _ACTORS:
        for action in _ACTIONS:
            for object_ in _OBJECTS:
                group = f"authored-intent-v1:{actor}:{action}:{object_}"
                for modality in MODALITIES:
                    frame = {"actor": actor, "action": action, "object": object_, "modality": modality}
                    texts = [pattern.format(**frame) for pattern in patterns[modality]]
                    texts.append(canonical_intent_text(frame))
                    for variant, text in enumerate(texts):
                        result.append({"id": "authored:" + _sha(f"{group}:{modality}:{variant}".encode()),
                            "split": _split(group), "group_id": group, "instruction": text,
                            "frame": frame.copy(), "canonical_text": canonical_intent_text(frame),
                            "provenance": {"kind": "authored_development_control", "source_id": group,
                                "source_sha256": _sha(text.encode()), "spans": [],
                                "label_rule": "explicit_authored_action_modality_contrast/v1",
                                "human_reviewed": False, "gold_source_semantics": False}})
    return result


def _heading_blocked(headings: list[dict[str, Any]]) -> bool:
    return any(re.search(r"\b(?:example|examples|anti-pattern|antipattern|not to use|output templates)\b",
                         heading["text"].lower()) for heading in headings)


def extract_skillcenter_pairs(sample: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    """Select exact, simple, unfenced clauses; preserve all omission reasons.

    Opaque object phrases carry no claims about their internal semantics.
    Missing actors stay ``unspecified`` rather than acquiring user authority.
    The caller must first validate the original pinned SkillCenter export.
    """
    text = sample["instruction"]
    if _sha(text.encode()) != sample["source_sha256"]:
        raise ValueError("SkillCenter source bytes do not match their digest")
    if sample["split"] not in {"train", "validation", "test"}:
        raise ValueError("the source split must be preserved")
    pairs, omitted, headings = [], [], []
    fence = None
    offset = 0
    for line_number, raw in enumerate(text.splitlines(keepends=True), 1):
        body = raw.rstrip("\r\n")
        stripped = body.strip()
        span = {"start_char": offset, "end_char": offset + len(body)}
        offset += len(raw)
        if not stripped:
            continue
        observation = {"source_id": sample["id"], "split": sample["split"],
                       "line": line_number, "span": span}
        fence_match = _FENCE.match(body)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            omitted.append({**observation, "reason": "code_fence_delimiter"})
            continue
        if fence is not None:
            omitted.append({**observation, "reason": "code_fence_content"})
            continue
        heading = _HEAD.match(body)
        if heading:
            depth = len(heading.group(1))
            headings = [h for h in headings if h["depth"] < depth]
            headings.append({"depth": depth, "text": heading.group(2), "span": span,
                             "source_text": body})
            omitted.append({**observation, "reason": "heading_context"})
            continue
        if _heading_blocked(headings):
            omitted.append({**observation, "reason": "example_or_non_applicable_section"})
            continue
        listing = _LIST.match(body)
        clause = (listing.group(1) if listing else stripped).strip()
        match = _CLAUSE.fullmatch(clause)
        if not match or match["action"].lower() not in _SOURCE_ACTIONS:
            omitted.append({**observation, "reason": "outside_bounded_clause_grammar"})
            continue
        object_ = match["object"].strip()
        if object_ != object_.lower():
            omitted.append({**observation, "reason": "case_sensitive_or_proper_noun_object"})
            continue
        if (len(object_.split()) > 12 or set(object_.split()) & _OBJECT_BLOCKERS
                or len(clause.split()) > 40):
            omitted.append({**observation, "reason": "compound_or_conditional_object"})
            continue
        explicit = match["modal"].lower() if match["modal"] else None
        modality = {"must not": "prohibited", "shall not": "prohibited", "do not": "prohibited",
                    "never": "prohibited", "must": "required", "shall": "required",
                    "should": "recommended", "may": "permitted", "intends to": "intended"}.get(explicit)
        force_headings = [h for h in headings if h["text"].strip().lower() in _HEADING_FORCE]
        heading_force = (_HEADING_FORCE[force_headings[-1]["text"].strip().lower()]
                         if force_headings else None)
        if modality and heading_force and modality != heading_force:
            omitted.append({**observation, "reason": "conflicting_explicit_modalities"})
            continue
        # A named actor with no modal may simply be a descriptive sentence.
        if match["actor"] and not explicit:
            omitted.append({**observation, "reason": "descriptive_actor_clause"})
            continue
        frame = {"actor": (match["actor"] or "unspecified").lower(), "action": match["action"].lower(),
                 "object": object_, "modality": modality or heading_force or "intended"}
        validate_intent_frame(frame)
        prefix = (force_headings[-1]["text"].strip().lower() + ": "
                  if heading_force and not explicit else "")
        instruction = prefix + clause.lower()
        spans = ([force_headings[-1]["span"]] if prefix else []) + [span]
        source_fragments = [text[s["start_char"]:s["end_char"]] for s in spans]
        pair_id = _sha(_wire({"source": sample["id"], "spans": spans, "frame": frame}))
        pairs.append({"id": "skillcenter:" + pair_id, "split": sample["split"],
            "group_id": "skillcenter-source:" + sample["id"], "instruction": instruction,
            "frame": frame, "canonical_text": canonical_intent_text(frame),
            "provenance": {"kind": "skillcenter_weak_clause", "source_id": sample["id"],
                "source_sha256": sample["source_sha256"], "spans": spans,
                "source_fragments": source_fragments, "license_expression": sample["license_expression"],
                "source_url": sample["source_record"]["source_url"],
                "label_rule": "bounded_explicit_clause_and_modal_heading/v1",
                "instruction_normalization": "lowercase_strip_list_marker_join_explicit_modal_heading",
                "actor_default": "unspecified" if not match["actor"] else None,
                "object_semantics": "opaque_phrase", "human_reviewed": False,
                "gold_source_semantics": False}})
    return pairs, omitted


def _quarantine_collisions(samples: list[dict]) -> tuple[list[dict], list[dict]]:
    indexes = defaultdict(list)
    for sample in samples:
        indexes[(sample["instruction"],)].append(sample)
        indexes[("frame", _sha(_wire(sample["frame"])))].append(sample)
    blocked = set()
    for group in indexes.values():
        if len({r["split"] for r in group}) > 1:
            blocked.update(r["id"] for r in group)
    return ([r for r in samples if r["id"] not in blocked],
            [{"id": r["id"], "source_id": r["provenance"]["source_id"], "split": r["split"],
              "reason": "cross_split_instruction_or_frame_collision"}
             for r in samples if r["id"] in blocked])


def build_intent_roundtrip_corpus(skillcenter_descriptor: Mapping[str, Any] | None,
                                 include_authored: bool = True) -> dict[str, Any]:
    """Build reproducible paired examples while preserving native source splits."""
    if type(include_authored) is not bool:
        raise ValueError("include_authored must be a boolean")
    samples, omitted, source_manifest = [], [], None
    if skillcenter_descriptor is not None:
        from .skillcenter_training import load_skillcenter_training_corpus
        corpus = load_skillcenter_training_corpus(skillcenter_descriptor)
        source_manifest = {"descriptor": dict(skillcenter_descriptor),
            "dataset_repo_id": corpus["dataset_repo_id"], "release_revision": corpus["release_revision"],
            "release_manifest_sha256": corpus["release_manifest_sha256"],
            "selected_document_split_counts": corpus["selected_split_counts"],
            "split_manifest_sha256": _sha(_wire(corpus["split_manifest"]))}
        for sample in corpus["samples"]:
            selected, exclusions = extract_skillcenter_pairs(sample)
            samples.extend(selected)
            omitted.extend(exclusions)
    if include_authored:
        samples.extend(authored_intent_pairs())
    samples, quarantined = _quarantine_collisions(samples)
    counts = Counter(r["split"] for r in samples)
    source_counts = {kind: dict(Counter(r["split"] for r in samples if r["provenance"]["kind"] == kind))
                     for kind in ("authored_development_control", "skillcenter_weak_clause")}
    report = {"schema": SCHEMA, "frame_schema": FRAME_SCHEMA,
        "producer_sha256": _sha(Path(__file__).read_bytes()), "source_manifest": source_manifest,
        "include_authored": include_authored, "samples": sorted(samples, key=lambda r: r["id"]),
        "omitted": omitted, "quarantined": quarantined,
        "counts": {"pairs": len(samples), "splits": dict(counts), "by_source": source_counts,
                   "source_omission_reasons": dict(Counter(r["reason"] for r in omitted)),
                   "quarantined": len(quarantined)},
        "supervision": "explicit_authored_controls_and_unreviewed_bounded_public_clause_labels",
        "split_scope": "development_holdouts_with_fixed_public_source_family_membership",
        "semantic_generalization_evaluation": False, "human_reviewed_pair_count": 0,
        "unsupported": ["arbitrary_instruction_semantics", "conditionals", "preconditions", "effects",
                        "workflow_order", "nested_negation", "internal_object_phrase_semantics"],
        "source_content_executed": False, "provider_calls": 0, "qualified": False,
        "admitted": False, "semantic_correctness_verified": False}
    report["report_sha256"] = _sha(_wire(report))
    return report


def validate_intent_roundtrip_corpus(report: Mapping[str, Any]) -> None:
    """Replay source identities, labels, omissions, and development partitions."""
    if not isinstance(report, Mapping) or report.get("schema") != SCHEMA:
        raise ValueError("unsupported paired Intent corpus schema")
    manifest = report.get("source_manifest")
    descriptor = None if manifest is None else manifest["descriptor"]
    expected = build_intent_roundtrip_corpus(descriptor, include_authored=report["include_authored"])
    if _wire(report) != _wire(expected):
        raise ValueError("paired Intent corpus differs from its reproducible source replay")
