"""Conservative, replayable weak targets from the existing SkillCenter spans.

This adapter never rewrites the pinned sentence inventory.  Complete explicit
conditions and two-action sequences remain structured candidates; they cannot
be silently reduced to labels for the older single-action training codec.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ...formalization import text_spans
from . import skillcenter_spans, skillcenter_training

SCHEMA = "intent-rich-span-targets/v1"
DESCRIPTOR_SCHEMA = "intent-rich-span-targets-descriptor/v1"
LABEL_RULE = "bounded_explicit_skillcenter_span_target/v1"
MAX_TARGETS = 4096
MAX_BYTES = 32 * 1024 * 1024

# Additions were selected using only the original TRAIN partition.  The frozen
# old adapter is deliberately not modified, so its previous receipts replay.
_ACTIONS = frozenset((
    "add build check compile configure create delete deploy document enable fix inspect install "
    "list load open pin read remove run save scan store test update validate verify write "
    "generate reuse confirm review use search report suggest stop"
).split())
_ACTORS = frozenset(("agent", "developer", "operator", "system", "user", "service", "administrator"))
_CLAUSE = re.compile(
    r"^(?:(?:the )?(?P<actor>" + "|".join(sorted(_ACTORS)) + r") )?"
    r"(?:(?P<modal>must not|shall not|do not|never|must|shall|should|may|intends to) )?"
    r"(?P<action>[a-z]+) (?P<object>[A-Za-z][A-Za-z0-9 _-]*?)[.]?$", re.I)
_MODALITIES = {"must not": "prohibited", "shall not": "prohibited", "do not": "prohibited",
               "never": "prohibited", "must": "required", "shall": "required",
               "should": "recommended", "may": "permitted", "intends to": "intended"}
_HEADING_FORCE = {"must do": "required", "must not do": "prohibited", "required": "required",
                  "prohibited": "prohibited", "recommended": "recommended", "permitted": "permitted"}
_OBJECT_BLOCKERS = frozenset((
    "if when unless until before after then without except otherwise because and or not never "
    "must may should shall to that whether while assuming all any every each either both no none "
    "it its they them their this these those former latter above below previous next there such "
    "here your our whose is are was were be been being comes come works work only always instead rather"
).split())
_GUARD_BLOCKERS = _OBJECT_BLOCKERS - {"is", "are"}
_GUARD = re.compile(
    r"^(?:the )?[A-Za-z][A-Za-z0-9 _-]* "
    r"(?:(?:is|are) [A-Za-z][A-Za-z0-9 _-]*|(?:fails?|pass(?:es)?|exists?)|selects [A-Za-z][A-Za-z0-9 _-]*)$",
    re.I)
_LIST_MARKER = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_EXAMPLE_HEADING = re.compile(r"\b(?:examples?|samples?|demonstrations?|templates?|anti-pattern|not to use)\b", re.I)
_MODAL_HEADING = re.compile(r"\b(?:must|shall|should|required|prohibited|permitted|recommended|forbidden|never|do not|allowed)\b", re.I)


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pins() -> dict[str, str]:
    from . import structured_target_bridge
    return {module.__name__: _sha(Path(module.__file__).read_bytes())
            for module in (skillcenter_spans, skillcenter_training, text_spans, structured_target_bridge)} | {
                __name__: _sha(Path(__file__).read_bytes())}


def _selector(parent: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    text = parent["instruction"]
    expected = text_spans.source_selector(text, row["start_char"], row["end_char"])
    if any(row.get(key) != expected[key] for key in ("start_byte", "end_byte", "normalized_text")):
        raise ValueError("rich target source selector differs from source bytes")
    if "text" in row and row["text"] != expected["text"]:
        raise ValueError("rich target source fragment differs from source bytes")
    return expected


def _heading_force(span: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    forces = []
    for heading in span["heading_context"]:
        title = heading["title"].strip().casefold()
        if any(character.isalpha() and not character.isascii() for character in title):
            return None, None, "unsupported_heading_language"
        if _EXAMPLE_HEADING.search(title):
            return None, None, "example_or_non_applicable_heading"
        if skillcenter_spans._context_reasons(title):
            return None, None, "external_heading_scope"
        if title in _HEADING_FORCE:
            forces.append((title, _HEADING_FORCE[title]))
        elif _MODAL_HEADING.search(title):
            return None, None, "unsupported_heading_modality"
    if len({force for _, force in forces}) > 1:
        return None, None, "conflicting_heading_modalities"
    return (*forces[-1][::-1], None) if forces else (None, None, None)


def _clause(text: str, heading_force: str | None) -> tuple[dict[str, str] | None, dict[str, bool], str | None]:
    match = _CLAUSE.fullmatch(text)
    flags = {"explicit_actor": False, "explicit_modality": False}
    if not match or match["action"].lower() not in _ACTIONS:
        return None, flags, "outside_bounded_action_grammar"
    actor, action = match["actor"], match["action"].lower()
    modal = match["modal"].lower() if match["modal"] else None
    object_ = match["object"].strip()
    flags = {"explicit_actor": bool(actor), "explicit_modality": bool(modal)}
    if actor and not modal:
        return None, flags, "descriptive_actor_clause"
    if len(object_) > 160 or len(object_.split()) > 12:
        return None, flags, "object_phrase_bound"
    if set(object_.casefold().split()) & _OBJECT_BLOCKERS:
        return None, flags, "unsupported_object_scope_or_compound"
    if action == "search" and not object_.casefold().startswith("for "):
        return None, flags, "ambiguous_search_noun_phrase"
    modality = _MODALITIES.get(modal)
    if modality and heading_force and modality != heading_force:
        return None, flags, "conflicting_explicit_modalities"
    return {"actor": actor.lower() if actor else "unspecified", "action": action,
            "object": object_, "modality": modality or heading_force or "intended"}, flags, None


def _target(text: str, heading_force: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if re.match(r"^if\b", text, re.I):
        parts = text.split(",")
        if len(parts) != 2:
            return None, "conditional_requires_one_complete_guard_and_action"
        guard = parts[0][3:].strip()
        if (not guard or len(guard) > 256 or len(guard.split()) > 32
                or not _GUARD.fullmatch(guard)
                or set(guard.casefold().split()) & _GUARD_BLOCKERS):
            return None, "outside_bounded_explicit_guard"
        action, _, reason = _clause(parts[1].strip(), heading_force)
        return (None, reason) if action is None else (
            {"kind": "conditional", "actions": [action], "condition": guard}, None)
    if re.search(r"\bthen\b", text, re.I):
        body = re.sub(r"^first\s+", "", text, flags=re.I)
        parts = re.split(r",?\s+then\s+", body, flags=re.I)
        if len(parts) != 2:
            return None, "sequence_requires_exactly_two_explicit_actions"
        actions, flags = [], []
        for part in parts:
            action, metadata, reason = _clause(part.strip(), heading_force)
            if action is None:
                return None, reason
            actions.append(action)
            flags.append(metadata)
        if flags[0]["explicit_actor"] != flags[1]["explicit_actor"]:
            return None, "ambiguous_sequence_actor_scope"
        if not heading_force and flags[0]["explicit_modality"] != flags[1]["explicit_modality"]:
            return None, "ambiguous_sequence_modal_scope"
        return {"kind": "sequence", "actions": actions, "condition": None}, None
    action, _, reason = _clause(text, heading_force)
    return (None, reason) if action is None else ({"kind": "action", "actions": [action], "condition": None}, None)


def extract_rich_span_target(span: Mapping[str, Any], parent: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return a source-bound weak candidate or one explicit omission reason.

    The public builder first replays the complete pinned source inventory.
    This helper additionally checks exact character/byte selectors and refuses
    context-required singles or partial blocks of structured instructions.
    """
    if (_sha(parent["instruction"].encode()) != parent["source_sha256"]
            or any(span[key] != parent[key] for key in ("source_id", "source_sha256", "split"))):
        raise ValueError("rich target differs from parent source identity")
    selector = _selector(parent, span)
    headings = [_selector(parent, row) for row in span["heading_context"]]
    if span["status"] not in {"candidate", "context_required"}:
        return None, span["reason"] or span["status"]
    force, force_title, reason = _heading_force(span)
    if reason:
        return None, reason
    block = span["block_context"]
    block_selector = _selector(parent, block)
    if block["kind"] not in {"paragraph", "list_item"}:
        return None, "unsupported_markdown_block"
    if block.get("parent_list_context") or block.get("leadin_context"):
        return None, "external_list_or_preceding_scope"
    target, reason = _target(selector["normalized_text"], force)
    if target is None:
        return None, reason
    if span["status"] == "context_required":
        if target["kind"] == "action":
            return None, "context_required_single_action"
        whole = block_selector["normalized_text"]
        if block["kind"] == "list_item":
            whole = _LIST_MARKER.sub("", whole, count=1)
        if whole != selector["normalized_text"]:
            return None, "structured_target_requires_complete_block"
        # Context is accepted only when entirely represented by this target.
        allowed = {"conditional_context"} if target["kind"] == "conditional" else {"anaphoric_context"}
        if set(block.get("context_reasons", [])) - allowed:
            return None, "unrepresented_structured_context"
    elif not span["eligible_for_pairing"]:
        return None, "source_inventory_not_eligible"
    instruction = ((force_title + ": ") if force_title else "") + selector["normalized_text"]
    source_selectors = headings + [selector]
    provenance = {
        "kind": "skillcenter_weak_rich_span", "label_rule": LABEL_RULE,
        "source_sha256": parent["source_sha256"], "source_id": parent["source_id"],
        "source_identity": parent.get("source_identity"), "source_family": parent.get("source_family"),
        "source_url": parent.get("source_url", ""), "license_expression": parent.get("license_expression", ""),
        "spans": [{key: row[key] for key in ("start_char", "end_char", "start_byte", "end_byte")}
                  for row in source_selectors],
        "source_fragments": [row["text"] for row in source_selectors],
        "heading_context": span["heading_context"], "block_context": block,
        "source_inventory_status": span["status"], "source_inventory_reason": span["reason"],
        "instruction_normalization": "whitespace_only_with_exact_modal_heading_prefix_case_preserved",
        "instruction_sha256": _sha(instruction.encode()), "object_semantics": "opaque_phrase",
        "condition_semantics": "opaque_uninterpreted_source_guard" if target["condition"] else None,
        "actor_default": "unspecified", "human_reviewed": False, "gold_source_semantics": False,
    }
    return {"instruction": instruction, "target": target, "provenance": provenance}, None


def _compact_qualification(report: Mapping[str, Any]) -> dict[str, Any]:
    projections = report["projections"]
    return {"schema": report["schema"], "report_sha256": report["report_sha256"],
            "training_supported": report["training_supported"], "unsupported": report["unsupported"],
            "source_ir_sha256": report["source_ir_sha256"],
            "native_targets_ready_for_training": projections["native_targets"]["ready_for_training"],
            "family_statuses": [{key: row.get(key) for key in ("family_id", "profile_id", "status")}
                                for row in projections["projections"]],
            "proof_authority": False, "semantic_correctness_verified": False}


def build_skillcenter_rich_span_targets(span_descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Replay the old inventory, preserve all omissions, and qualify candidates."""
    from .structured_target_bridge import (
        MAX_INSTRUCTION_CHARS, qualify_structured_target, validate_structured_target,
    )
    inventory = skillcenter_spans.load_skillcenter_span_corpus(span_descriptor)
    sources = {row["source_id"]: row for row in inventory["sources"]}
    candidates, omitted = [], []
    for span in inventory["spans"]:
        origin = {"span_id": span["id"], "source_id": span["source_id"], "split": span["split"]}
        target, reason = extract_rich_span_target(span, sources[span["source_id"]])
        if target is None:
            omitted.append({**origin, "reason": reason, "source_status": span["status"],
                            "source_reason": span["reason"]})
        else:
            # The source grammar is a superset of the native lexical codec:
            # e.g. a digit-leading object word is valid prose but not a slot.
            # Such bounds are an explicit source gap, not a batch failure.
            # Qualification failures below deliberately remain fatal: a
            # semantic regression must never be disguised as missing data.
            try:
                validate_structured_target(target["target"])
                if len(target["instruction"]) > MAX_INSTRUCTION_CHARS:
                    raise ValueError("native structured instruction bound")
            except ValueError:
                omitted.append({**origin, "reason": "outside_native_structured_target_bounds",
                                "source_status": span["status"], "source_reason": span["reason"]})
                continue
            identity = {**origin, "instruction": target["instruction"], "target": target["target"]}
            candidates.append({"id": "intent-rich-span-target:" + _sha(_wire(identity)), **origin, **target})
    if len(candidates) > MAX_TARGETS:
        raise ValueError("rich target candidates exceed the 4096-target development bound")
    indexes = defaultdict(list)
    for row in candidates:
        indexes[("instruction", row["instruction"].casefold())].append(row)
        indexes[("target", _sha(_wire(row["target"])))].append(row)
    blocked = {row["id"] for group in indexes.values() if len({r["split"] for r in group}) > 1 for row in group}
    quarantined = [{**row, "reason": "cross_partition_instruction_or_semantic_target_collision"}
                   for row in candidates if row["id"] in blocked]
    targets = []
    for row in candidates:
        if row["id"] in blocked:
            continue
        qualification = qualify_structured_target(row["target"], instruction=row["instruction"])
        targets.append({**row, "native_intent_ir": qualification["native_intent_ir"],
                        "qualification": _compact_qualification(qualification)})
    report = {
        "schema": SCHEMA, "label_rule": LABEL_RULE, "span_corpus_descriptor": dict(span_descriptor),
        "producer_sha256": _pins(), "dataset_repo_id": inventory["dataset_repo_id"],
        "release_revision": inventory["release_revision"], "targets": sorted(targets, key=lambda r: r["id"]),
        "omitted": omitted, "quarantined": quarantined,
        "counts": {"targets": len(targets), "source_spans": len(inventory["spans"]),
                   "by_kind": dict(Counter(row["target"]["kind"] for row in targets)),
                   "splits": dict(Counter(row["split"] for row in targets)),
                   "training_supported": sum(row["qualification"]["training_supported"] for row in targets),
                   "omission_reasons": dict(Counter(row["reason"] for row in omitted)),
                   "quarantined": len(quarantined)},
        "split_scope": "inherited_parent_source_families_with_cross_partition_collisions_excluded",
        "holdout_status": inventory["holdout_status"],
        "grammar_development_scope": "original_train_partition_only",
        "supervision": "unreviewed_bounded_source_span_structured_weak_labels",
        "human_reviewed_pair_count": 0, "gold_formal_target_count": 0,
        "provider_calls": 0, "source_content_executed": False, "training_executed": False,
        "semantic_correctness_verified": False, "proof_authority": False, "qualified": False, "admitted": False,
        "unsupported": ["arbitrary_instruction_semantics", "unresolved_scope_or_anaphora",
                        "implicit_order_or_conjunction", "interpreted_guard_truth", "conditional_modal_logic",
                        "structured_target_training_in_single_action_codec"],
    }
    report["report_sha256"] = _sha(_wire(report))
    if len(_wire(report)) > MAX_BYTES:
        raise ValueError("rich target corpus exceeds the 32 MiB bound")
    return report


def validate_skillcenter_rich_span_targets(report: Mapping[str, Any]) -> None:
    """Reject changed targets, selectors, splits, authority, or producer code."""
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("rich span target corpus required")
    expected = build_skillcenter_rich_span_targets(report["span_corpus_descriptor"])
    if _wire(report) != _wire(expected):
        raise ValueError("rich span target corpus differs from pinned source replay")


def export_skillcenter_rich_span_targets(span_descriptor: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    """Export into a fresh directory; existing exports and weights stay intact."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("a fresh output directory is required")
    report = build_skillcenter_rich_span_targets(span_descriptor)
    raw = _wire(report)
    output.mkdir(parents=True)
    path = output / "targets.json"
    path.write_bytes(raw)
    descriptor = {"schema": DESCRIPTOR_SCHEMA, "path": str(path), "sha256": _sha(raw)}
    (output / "descriptor.json").write_bytes(_wire(descriptor))
    return descriptor


def load_skillcenter_rich_span_targets(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Hash-check and exactly replay target labels against the pinned sources."""
    if type(descriptor) is not dict or set(descriptor) != {"schema", "path", "sha256"} or descriptor["schema"] != DESCRIPTOR_SCHEMA:
        raise ValueError("exact rich span target descriptor required")
    path = Path(descriptor["path"])
    if not path.is_absolute():
        raise ValueError("absolute rich span target path required")
    raw = skillcenter_training._file(path.parent, path.name, digest=descriptor["sha256"])
    report = json.loads(raw)
    validate_skillcenter_rich_span_targets(report)
    return report
