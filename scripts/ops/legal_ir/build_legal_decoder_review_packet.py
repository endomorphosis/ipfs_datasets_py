#!/usr/bin/env python3
"""Build an unreviewed, source-bound annotation packet from existing artifacts.

No inference, downloads, expert judgments, or training qualification occur.
Equal text is grouped for review workload, while distinct legal source contexts
remain separate observations. Predictions are associated by exact text hash,
never by position or an invented source-span identity.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA = "legal-decoder-independent-review-packet/v1"
MAX_BYTES = 16 * 1024 * 1024
MAX_OBSERVATIONS = 1000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")


class ReviewPacketError(ValueError):
    """The packet cannot be created without losing identity or review status."""


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _read(path: Path, remaining: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if remaining <= 0 or not path.is_file() or path.stat().st_size > remaining:
        raise ReviewPacketError(f"input exceeds remaining byte budget: {path}")
    with path.open("rb") as stream:
        raw = stream.read(remaining + 1)
    if len(raw) > remaining:
        raise ReviewPacketError("input exceeds remaining byte budget")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewPacketError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ReviewPacketError(f"nonfinite JSON constant: {value}")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ReviewPacketError("input must be a JSON object")
    return value, {"path": str(path.resolve()), "bytes": len(raw), "sha256": _sha(raw)}


def triage_text(text: str) -> dict[str, Any]:
    """Surface cues only: every label is a question for independent review."""
    patterns = {
        "normative_word": r"\b(?:shall|must|may)\b",
        "weak_modal_word": r"\bshould\b",
        "amendment_editorial_word": r"\b(?:redesignated|added|struck out|as amended)\b",
        "citation_note_word": r"\b(?:Pub\.|Subsec\.|div\.|set out as a note|note preceding)\b",
        "heading_word": r"\b(?:Requirements Relating to|Definitions|Effective Date|Applicability)\b",
        "condition_scope_word": r"\b(?:if|when|provided that|in carrying out|to the maximum extent practicable)\b",
        "exception_word": r"\b(?:unless|except|exempt|waivers?)\b",
        "temporal_word": r"\b(?:days?|years?|before|after|within|delayed implementation|effective|Jan|Feb|Mar|Apr|June|July|Aug|Sept|Oct|Nov|Dec)\b",
        "coordination_word": r"\b(?:and|or)\b|;",
    }
    cues = [
        {"kind": kind, "char_start": match.start(), "char_end": match.end(), "text": match.group()}
        for kind, expression in patterns.items()
        for match in re.finditer(expression, text, flags=re.IGNORECASE)
    ]
    kinds = Counter(cue["kind"] for cue in cues)
    fragment = bool(re.fullmatch(r"(?:L\.|Pub\.|Subsec\.|(?:\([A-Za-z0-9]+\)[,. ]*)+)", text.strip()))
    categories: list[str] = []
    if fragment:
        categories.append("citation_or_subsection_fragment_candidate")
    if kinds["amendment_editorial_word"] or kinds["citation_note_word"]:
        categories.append("editorial_or_nonoperative_candidate")
    if kinds["heading_word"]:
        categories.append("heading_or_mixed_fragment_candidate")
    if kinds["normative_word"]:
        categories.append("operative_clause_candidate")
    if kinds["condition_scope_word"]:
        categories.append("condition_attachment_review_needed")
    if kinds["exception_word"]:
        categories.append("exception_attachment_review_needed")
    if kinds["temporal_word"]:
        categories.append("temporal_context_review_needed")
    if kinds["coordination_word"] or kinds["normative_word"] > 1:
        categories.append("coordination_and_rule_count_review_needed")
    if not categories:
        categories.append("fragment_or_context_review_needed")
    return {
        "status": "unreviewed", "method": "lexical_surface_cues_only",
        "categories": categories, "evidence_spans": sorted(cues, key=lambda c: (c["char_start"], c["kind"])),
        "rule_count": None, "multi_rule_assessment": "unresolved",
        "context_required": True, "legal_classification_confirmed": False,
        "note": "Cues can occur in quotations, citations, and headings; they do not establish a norm, exception, temporal constraint, or number of rules.",
    }


def review_submission_schema() -> dict[str, Any]:
    """Interchange schema for independent annotations, including rejection.

    Schema validation is necessary but insufficient for qualification. An
    importer must additionally verify exact source ranges, observation context,
    reviewer independence, signatures/receipts, and adjudication decisions.
    """
    def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": properties,
                "required": list(properties) if required is None else required}

    text = {"type": "string", "minLength": 1}
    nullable_text = {"type": ["string", "null"]}
    source_ref = obj({
        "source_span_id": text, "source_text_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "char_start": {"type": "integer", "minimum": 0}, "char_end": {"type": "integer", "minimum": 1},
        "text": text, "context_artifact_sha256": {"type": ["string", "null"]},
    })
    grounded = obj({"value": text, "source_refs": {"type": "array", "minItems": 1,
                                                   "items": {"$ref": "#/$defs/source_ref"}}})
    attachment = obj({
        "value": text, "source_refs": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/source_ref"}},
        "attachment_rule_ids": {"type": "array", "minItems": 1, "items": text},
        "scope_explanation": text,
    })
    temporal = obj({
        "kind": {"enum": ["deadline", "duration", "effective_date", "before", "after", "recurrence", "other"]},
        "surface": {"$ref": "#/$defs/attachment"}, "anchor": nullable_text,
        "quantity": {"type": ["number", "null"]}, "unit": nullable_text,
        "endpoint_interpretation": nullable_text,
    })
    rule = obj({
        "rule_id": text, "modality": {"enum": ["O", "P", "F"]},
        "actor": {"$ref": "#/$defs/grounded"}, "action": {"$ref": "#/$defs/grounded"},
        "object": {"anyOf": [{"$ref": "#/$defs/grounded"}, {"type": "null"}]},
        "conditions": {"type": "array", "items": {"$ref": "#/$defs/attachment"}},
        "exceptions": {"type": "array", "items": {"$ref": "#/$defs/attachment"}},
        "temporal": {"type": "array", "items": {"$ref": "#/$defs/temporal"}},
        "quantifier_and_negation_scope": text, "cross_references": {"type": "array", "items": text},
    })
    interpretation = obj({
        "interpretation_id": text, "family": text, "profile": text,
        "rules": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"$ref": "#/$defs/rule"}},
        "coverage_explanation": text, "unrepresented_meaning": {"type": "array", "items": text},
    })
    reviewer = obj({
        "reviewer_id": text, "role": {"enum": ["legal_semantic", "formal_methods"]},
        "independent_of_model_and_annotation_author": {"const": True},
        "reviewed_at": text, "evidence_receipt": text,
        "decision": {"enum": ["accept", "correct", "reject", "abstain", "needs_context", "multiple_interpretations"]},
        "reason": text, "prediction_ids_considered": {"type": "array", "items": text},
        "proposed_interpretations": {"type": "array", "items": {"$ref": "#/$defs/interpretation"}},
    })
    adjudication = obj({
        "adjudicator_id": text, "independent_of_model_and_annotation_author": {"const": True},
        "adjudicated_at": text, "evidence_receipt": text,
        "decision": {"enum": ["accept", "reject", "abstain", "needs_context", "unresolved"]},
        "reason": text, "accepted_interpretation_ids": {"type": "array", "items": text},
        "eligible_use": {"enum": ["positive_candidate", "repair_candidate", "abstention_candidate", "exclude", "pending"]},
    })
    schema = obj({
        "schema": {"const": "legal-decoder-independent-review-submission/v1"},
        "packet_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "text_group_id": text, "source_text_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "source_span_ids_reviewed": {"type": "array", "minItems": 1, "uniqueItems": True, "items": text},
        "context_receipts": {"type": "array", "items": text},
        "reviews": {"type": "array", "minItems": 2, "items": {"$ref": "#/$defs/reviewer"},
                    "allOf": [{"contains": {"properties": {"role": {"const": role}}, "required": ["role"]}}
                              for role in ("legal_semantic", "formal_methods")]},
        "adjudication": {"$ref": "#/$defs/adjudication"},
        "training_qualified": {"const": False},
    })
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": {
        "source_ref": source_ref, "grounded": grounded, "attachment": attachment,
        "temporal": temporal, "rule": rule, "interpretation": interpretation,
        "reviewer": reviewer, "adjudication": adjudication}})
    return schema


def build_packet(queue_path: Path, transfers: Mapping[int, Path], *, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    if not transfers or len(transfers) > 16 or any(type(seed) is not int or seed < 0 for seed in transfers):
        raise ReviewPacketError("provide 1..16 nonnegative integer seed labels")
    queue, queue_receipt = _read(queue_path, max_bytes)
    remaining = max_bytes - queue_receipt["bytes"]
    if queue.get("schema") != "legal-decoder-pilot-review-queue/v1" or not _REVISION.fullmatch(queue.get("revision", "")):
        raise ReviewPacketError("versioned pinned review queue required")
    entries = queue.get("entries")
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_OBSERVATIONS:
        raise ReviewPacketError("bounded nonempty queue entries required")
    groups: dict[str, dict[str, Any]] = {}
    source_ids: set[str] = set()
    for entry in entries:
        identity = entry.get("source_span_id")
        variants = entry.get("source_text_variants")
        if not isinstance(identity, str) or not identity or identity in source_ids:
            raise ReviewPacketError("unique source_span_id required")
        source_ids.add(identity)
        if not isinstance(variants, list) or len(variants) != 1 or not isinstance(variants[0], str) or not variants[0]:
            raise ReviewPacketError("each observation needs one unambiguous exact source text")
        source, sha = variants[0], _sha(variants[0])
        for occurrence in entry.get("occurrences", []):
            producer = occurrence["producer_record"]
            if producer.get("source_span_id") != identity or producer.get("source_text") != source:
                raise ReviewPacketError("producer occurrence source binding differs")
            if not isinstance(producer.get("formula_text"), str) or _sha(producer["formula_text"]) != producer.get("formula_sha256"):
                raise ReviewPacketError("producer formula hash differs")
        if entry.get("training_qualified") is not False or entry.get("gold_target") is not None:
            raise ReviewPacketError("this builder accepts only unreviewed queue entries")
        group = groups.setdefault(sha, {
            "text_group_id": "source-text-sha256:" + sha, "source_text_sha256": sha,
            "source_text": source, "source_observations": [], "model_predictions_by_seed": [],
        })
        if group["source_text"] != source:
            raise ReviewPacketError("text hash collision")
        group["source_observations"].append(entry)
    manifests, seed_metrics = [], {}
    for seed, path in sorted(transfers.items()):
        transfer, receipt = _read(path, remaining)
        remaining -= receipt["bytes"]
        generation = transfer.get("generation", {})
        rows, reports = generation.get("rows"), generation.get("reports")
        if generation.get("generation_inputs_contained_references") is not False:
            raise ReviewPacketError("transfer must declare references absent during generation")
        if not isinstance(rows, list) or not isinstance(reports, list) or not reports:
            raise ReviewPacketError("transfer generation rows and reports required")
        flattened = [row for report in reports for row in report.get("rows", [])]
        if rows != flattened:
            raise ReviewPacketError("transfer rows differ from complete producer reports")
        expected_counts = Counter({sha: len(group["source_observations"]) for sha, group in groups.items()})
        if Counter(row.get("source_sha256") for row in rows) != expected_counts:
            raise ReviewPacketError("prediction source hash coverage or multiplicity differs from source observations")
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        row_index = 0
        for report_index, report in enumerate(reports):
            for local_index, row in enumerate(report["rows"]):
                if (row.get("target_access") is not False or row.get("teacher_forcing") is not False
                        or row.get("latent_input_enabled") is not False or row.get("source_input_conditioned") is not True):
                    raise ReviewPacketError("prediction is not declared source-only free generation")
                if any(row.get(flag) is not False for flag in ("qualified", "admitted", "semantic_correctness_verified")):
                    raise ReviewPacketError("prediction contains unsupported qualification claims")
                sha = row["source_sha256"]
                source = groups[sha]["source_text"]
                for token in row.get("span_diagnostics", {}).get("tokens", []):
                    start, end = token.get("start"), token.get("end")
                    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source)
                            or source[start:end] != token.get("text")):
                        raise ReviewPacketError("prediction token offsets differ from source text")
                by_source[sha].append({
                    "prediction_id": f"seed-{seed}:row-{row_index}", "generation_row_index": row_index,
                    "producer_report_index": report_index, "producer_report_row_index": local_index,
                    "prediction": row, "review_status": "unreviewed",
                })
                row_index += 1
        for sha, group in groups.items():
            group["model_predictions_by_seed"].append({
                "seed_label": seed, "artifact_sha256": receipt["sha256"], "predictions": by_source[sha],
                "observation_id_assignment": "unavailable; producer records bind text hashes only",
            })
        manifests.append({"seed_label": seed, "seed_label_source": "explicit builder input; not independently rederived",
                          **receipt, "producer_report_metadata": [{key: value for key, value in report.items() if key != "rows"} for report in reports],
                          "producer_metrics": transfer.get("metrics")})
        seed_metrics[str(seed)] = {"observations": len(rows), "unique_source_texts": len(by_source),
                                  "statuses": dict(sorted(Counter(row.get("status", "missing") for row in rows).items()))}
    for group in groups.values():
        documented = any(observation.get("documented_span_issues") for observation in group["source_observations"])
        decoded = any(entry["prediction"].get("status") == "decoded" for seed in group["model_predictions_by_seed"] for entry in seed["predictions"])
        group.update({
            "priority": 1 if documented else 2 if decoded else 3,
            "priority_reason": "documented_prior_failure" if documented else "decoded_output_requires_review" if decoded else "context_and_abstention_review",
            "triage": triage_text(group["source_text"]), "review_status": "unreviewed",
            "independent_reviews": [], "adjudication": None, "gold_target": None, "training_qualified": False,
            "review_work_items": [
                "Obtain source document version, complete subsection and relevant definitions for each distinct observation.",
                "Classify operative content, heading, amendment history or incomplete fragment using recovered context.",
                "Annotate all rules and source spans; record condition, exception, temporal, negation and quantifier scope.",
                "Inspect every seed's predictions and recorded abstentions; accept, correct, reject, request context or retain alternatives.",
                "Have independent legal-semantic and formal-method reviewers submit source-bound receipts and resolve disagreements through adjudication.",
            ],
            "context_inheritance_policy": "Identical text is a workload group, not proof of identical legal meaning; each source_span_id requires its own context assessment.",
        })
    ordered = sorted(groups.values(), key=lambda group: (group["priority"], group["source_text_sha256"]))
    return {
        "schema": SCHEMA, "repository": queue["repository"], "revision": queue["revision"],
        "scope": queue["scope"], "status": "unreviewed", "training_qualified": False,
        "input_artifacts": {"review_queue": queue_receipt, "prediction_transfers": manifests},
        "builder_sha256": _sha(Path(__file__).read_bytes()),
        "deduplication": {"key": "SHA-256 of exact source text UTF-8 bytes", "normalization": "none",
                          "source_observations": len(entries), "unique_text_groups": len(ordered),
                          "contexts_merged": False, "prediction_join": "exact source text hash with multiplicity verification"},
        "prediction_summary_by_seed": seed_metrics,
        "triage_counts": dict(sorted(Counter(category for group in ordered for category in group["triage"]["categories"]).items())),
        "qualification_policy": "This packet is an annotation request. Lexical triage, model outputs, agreement, source hashes and syntax checks are not expert-reviewed gold. No corrections or semantic labels are supplied by the builder.",
        "review_submission_schema": review_submission_schema(),
        "review_acceptance_requirements": [
            "Check JSON schema, exact source hashes, UTF-8 text, offset slices and original observation identities.",
            "Verify the submitters and independent review receipts; self-declared independence is not verification.",
            "Require distinct legal-semantic and formal-method reviewers and a recorded adjudication decision.",
            "Resolve context separately for every source_span_id; do not transfer annotations across duplicate text automatically.",
            "Resolve all rule attachments and scope, retain rejected candidates and explain unsupported or omitted meaning.",
            "Training qualification remains false in submissions; a separate reviewed admission process is required.",
        ],
        "groups": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-queue", type=Path, required=True)
    parser.add_argument("--transfer", action="append", required=True, metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = parser.parse_args()
    try:
        transfers: dict[int, Path] = {}
        for spec in args.transfer:
            seed_label, path = spec.split("=", 1)
            seed = int(seed_label)
            if seed in transfers:
                raise ReviewPacketError("duplicate seed label")
            transfers[seed] = Path(path)
        packet = build_packet(args.review_queue, transfers, max_bytes=args.max_bytes)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(packet, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except (ReviewPacketError, OSError, ValueError) as exc:
        parser.exit(1, f"review packet failed: {exc}\n")
    print(_json({"output": str(args.output.resolve()), "deduplication": packet["deduplication"],
                 "predictions": packet["prediction_summary_by_seed"], "status": packet["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
