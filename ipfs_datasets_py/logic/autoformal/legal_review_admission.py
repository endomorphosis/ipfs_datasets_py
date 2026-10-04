"""Validate external legal review submissions without qualifying training data.

This is an intake gate: hashes establish byte identity, not a person's identity,
independence, legal competence, source authority, or correctness. The only
supported interpretation is a source-bound O/P/F annotation for one observation.
Duplicate text does not authorize sharing annotations between legal contexts.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCHEMA = "legal-review-structural-admission/v1"
PACKET_SCHEMA = "legal-decoder-independent-review-packet/v1"
# Exact schema emitted by build_legal_decoder_review_packet.py on 2026-10-02.
# Do not validate a submission against a schema the submitter can weaken.
SUBMISSION_SCHEMA_SHA256 = "1056634f5be4cb06dfac9e4bc1f9714f5725213612b61bfd5072bb0b5927d3b8"
SUPPORTED_FAMILY = "deontic"
SUPPORTED_PROFILE = "source-bound-deontic-review/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SUBMISSIONS = 1000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,191}\Z")


class ReviewAdmissionError(ValueError):
    """Submission lacks a supported, consistent source-bound structure."""


def sha256(raw: bytes | str) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewAdmissionError(message)


def read_json(path: Path, *, max_bytes: int = MAX_BYTES) -> tuple[dict, dict]:
    require(type(max_bytes) is int and 0 < max_bytes <= MAX_BYTES, "invalid byte budget")
    require(path.is_file() and path.stat().st_size <= max_bytes, "artifact exceeds byte budget")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    require(len(raw) <= max_bytes, "artifact exceeds byte budget")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def nonfinite(_):
        raise ReviewAdmissionError("nonfinite JSON constant")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ReviewAdmissionError(f"invalid bounded UTF-8 JSON: {error}") from error
    require(type(value) is dict, "artifact must be a JSON object")
    return value, {"path": str(path.resolve()), "sha256": sha256(raw), "bytes": len(raw)}


def _bounded(value: Any, *, max_bytes: int = MAX_BYTES) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise ReviewAdmissionError("bounded finite UTF-8 JSON required") from error
    require(len(encoded) <= max_bytes, "JSON value exceeds byte budget")


def _identifier(value: Any, label: str) -> str:
    require(type(value) is str and _ID.fullmatch(value) is not None,
            f"invalid {label}")
    return value.casefold()


def _unique(values: list, label: str) -> None:
    require(len(values) == len(set(values)), f"duplicate {label}")


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as error:
        raise ReviewAdmissionError("timestamp must be ISO 8601 with time zone") from error
    require(parsed.tzinfo is not None and "T" in value, "timestamp must include time and time zone")
    return parsed


def packet_index(packet: dict) -> tuple[dict, dict]:
    """Check the exact source identities needed by this importer, not legal facts."""
    _bounded(packet)
    require(packet.get("schema") == PACKET_SCHEMA and packet.get("training_qualified") is False
            and packet.get("status") == "unreviewed", "unreviewed review packet required")
    require(digest(packet.get("review_submission_schema")) == SUBMISSION_SCHEMA_SHA256,
            "packet submission schema differs from pinned schema")
    groups = packet.get("groups")
    require(type(groups) is list and 0 < len(groups) <= MAX_SUBMISSIONS,
            "bounded nonempty packet groups required")
    by_group, observations = {}, {}
    for group in groups:
        require(type(group) is dict, "packet group must be an object")
        text, text_hash = group.get("source_text"), group.get("source_text_sha256")
        require(type(text) is str and text and sha256(text) == text_hash, "packet source hash differs")
        identity = "source-text-sha256:" + text_hash
        require(group.get("text_group_id") == identity and identity not in by_group,
                "packet group identity differs or repeats")
        require(group.get("training_qualified") is False and group.get("gold_target") is None
                and group.get("review_status") == "unreviewed", "packet group already qualified or reviewed")
        rows = group.get("source_observations")
        require(type(rows) is list and rows, "packet observations required")
        for row in rows:
            require(type(row) is dict, "observation must be an object")
            source_id = row.get("source_span_id")
            _identifier(source_id, "source_span_id")
            require(source_id not in observations and row.get("source_text_variants") == [text],
                    "observation identity repeats or source differs")
            require(row.get("training_qualified") is False and row.get("gold_target") is None,
                    "observation already qualified")
            for occurrence in row.get("occurrences", []):
                producer = occurrence.get("producer_record", {})
                require(producer.get("source_span_id") == source_id and producer.get("source_text") == text,
                        "packet producer occurrence source differs")
            observations[source_id] = {"group": group, "observation": row}
        by_group[identity] = group
    require(len(observations) <= MAX_SUBMISSIONS, "packet observation bound exceeded")
    counts = packet.get("deduplication", {})
    require(counts.get("source_observations") == len(observations)
            and counts.get("unique_text_groups") == len(by_group)
            and counts.get("contexts_merged") is False, "packet counts or context policy differ")
    return by_group, observations


def _contexts(artifacts: list[tuple[dict, dict]], observations: dict) -> dict:
    """Verify local context bytes and exact slices, without asserting authority."""
    indexed = {}
    fields = {"schema", "source_span_id", "source_text_sha256", "source_text", "legal_ids",
              "document_version", "context_text", "span_start", "span_end", "source_locator"}
    for context, receipt in artifacts:
        require(type(context) is dict and set(context) == fields
                and context["schema"] == "legal-review-source-context/v1", "unsupported context artifact schema")
        key = receipt.get("sha256")
        require(type(key) is str and _HASH.fullmatch(key) is not None and key not in indexed,
                "invalid or duplicate context receipt")
        # Callers supply a real path receipt. A dictionary/hash assertion alone is not accepted.
        require(type(receipt.get("path")) is str, "local context artifact path required")
        reread, actual = read_json(Path(receipt["path"]))
        require(actual == receipt and reread == context, "context artifact bytes differ from receipt")
        identity = context["source_span_id"]
        require(identity in observations, "context refers to unknown source observation")
        source = observations[identity]
        require(context["source_text"] == source["group"]["source_text"]
                and context["source_text_sha256"] == source["group"]["source_text_sha256"],
                "context source binding differs")
        require(context["legal_ids"] == source["observation"].get("legal_ids", []),
                "context legal identities differ")
        for field in ("document_version", "context_text", "source_locator"):
            require(type(context[field]) is str and context[field].strip(), "context metadata must be nonempty")
        start, end, text = context["span_start"], context["span_end"], context["context_text"]
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                and text[start:end] == context["source_text"], "context source offset slice differs")
        indexed[key] = context
    return indexed


def _source_ref(ref: dict, *, source_id: str, group: dict, contexts: dict, declared: set) -> None:
    require(ref["source_span_id"] == source_id and ref["source_text_sha256"] == group["source_text_sha256"],
            "source reference identity or hash differs")
    start, end, text = ref["char_start"], ref["char_end"], group["source_text"]
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(text)
            and text[start:end] == ref["text"], "source reference character offset slice differs")
    context_hash = ref["context_artifact_sha256"]
    if context_hash is not None:
        require(context_hash in declared and context_hash in contexts
                and contexts[context_hash]["source_span_id"] == source_id,
                "source reference context binding differs")


def _interpretation(value: dict, *, source_id: str, group: dict, contexts: dict, declared: set) -> None:
    _identifier(value["interpretation_id"], "interpretation_id")
    require(value["family"] == SUPPORTED_FAMILY and value["profile"] == SUPPORTED_PROFILE,
            "unsupported interpretation family or profile")
    rules = value["rules"]
    rule_ids = [row["rule_id"] for row in rules]
    _unique([_identifier(identity, "rule_id") for identity in rule_ids], "rule identity")
    attachments = []
    for rule in rules:
        for field in ("actor", "action", "object"):
            grounded = rule[field]
            if grounded is None:
                continue
            require(grounded["value"].strip(), "empty grounded value")
            for ref in grounded["source_refs"]:
                _source_ref(ref, source_id=source_id, group=group, contexts=contexts, declared=declared)
        require(rule["quantifier_and_negation_scope"].strip(), "scope explanation required")
        _unique(rule["cross_references"], "cross reference")
        for kind in ("conditions", "exceptions", "temporal"):
            for item in rule[kind]:
                attachment = item["surface"] if kind == "temporal" else item
                targets = attachment["attachment_rule_ids"]
                _unique(targets, "attachment rule id")
                require(rule["rule_id"] in targets and set(targets) <= set(rule_ids),
                        "attachment refers to unknown rule or omits its owner")
                require(attachment["scope_explanation"].strip(), "attachment scope explanation required")
                for ref in attachment["source_refs"]:
                    _source_ref(ref, source_id=source_id, group=group, contexts=contexts, declared=declared)
                attachments.append((rule["rule_id"], kind, digest(item), targets))
                if kind == "temporal" and item["quantity"] is not None:
                    require(type(item["quantity"]) in (int, float) and item["quantity"] >= 0,
                            "temporal quantity must be nonnegative")
    # A shared attachment is recorded at every target rule; orphan references fail.
    for owner, kind, item_hash, targets in attachments:
        for target in targets:
            require(any(other == target and other_kind == kind and other_hash == item_hash
                        for other, other_kind, other_hash, _ in attachments),
                    "shared attachment missing from referenced rule")


def validate_submission(packet: dict, *, packet_receipt: dict, submission: dict,
                        context_artifacts: list[tuple[dict, dict]] | None = None) -> dict:
    """Return structural status only. Every authority/qualification flag is false."""
    import jsonschema

    groups, observations = packet_index(packet)
    _bounded(submission, max_bytes=4 * 1024 * 1024)
    require(type(packet_receipt.get("path")) is str, "local packet receipt required")
    reread, actual = read_json(Path(packet_receipt["path"]))
    require(actual == packet_receipt and reread == packet, "packet receipt differs from local bytes")
    try:
        jsonschema.Draft202012Validator(packet["review_submission_schema"]).validate(submission)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path)
        raise ReviewAdmissionError(f"submission schema violation at {location}: {error.message}") from error
    require(submission["packet_sha256"] == packet_receipt["sha256"], "submission packet hash differs")
    group = groups.get(submission["text_group_id"])
    require(group is not None and submission["source_text_sha256"] == group["source_text_sha256"],
            "submission text group or source hash differs")
    reviewed = submission["source_span_ids_reviewed"]
    require(len(reviewed) == 1, "one source observation per submission required; shared context scope unsupported")
    source_id = reviewed[0]
    require(source_id in observations and observations[source_id]["group"] is group,
            "submission observation is outside its text group")
    contexts = _contexts(context_artifacts or [], observations)
    declarations = submission["context_receipts"]
    _unique(declarations, "context declaration")
    require(all(value.startswith("sha256:") and _HASH.fullmatch(value[7:]) for value in declarations),
            "context receipt must use sha256:<local-artifact-hash>")
    declared = {value[7:] for value in declarations}
    require(declared <= contexts.keys(), "declared context artifact is unavailable")
    require(all(contexts[key]["source_span_id"] == source_id for key in declared),
            "declared context belongs to another observation")
    predictions = {item["prediction_id"] for seed in group.get("model_predictions_by_seed", [])
                   for item in seed["predictions"]}
    reviewers, reviews, interpretations, review_ids, times = [], submission["reviews"], {}, [], []
    require(2 <= len(reviews) <= 16, "reviewer count outside bound")
    for review in reviews:
        reviewers.append(_identifier(review["reviewer_id"], "reviewer identity"))
        times.append(_timestamp(review["reviewed_at"]))
        require(review["evidence_receipt"].strip() and review["reason"].strip(), "review evidence and reason required")
        considered = review["prediction_ids_considered"]
        _unique(considered, "considered prediction")
        require(set(considered) <= predictions, "review refers to unknown prediction")
        proposed = review["proposed_interpretations"]
        require(len(proposed) <= 64, "interpretation count outside bound")
        decision = review["decision"]
        if decision in ("accept", "correct"):
            require(bool(proposed), "positive review requires an interpretation")
        elif decision == "multiple_interpretations":
            require(len(proposed) >= 2, "multiple-interpretation decision requires alternatives")
        else:
            require(not proposed, "negative or pending review cannot propose accepted interpretations")
        identities = []
        for proposed_item in proposed:
            _interpretation(proposed_item, source_id=source_id, group=group, contexts=contexts, declared=declared)
            identity = proposed_item["interpretation_id"]
            identities.append(identity)
            require(identity not in interpretations or interpretations[identity] == proposed_item,
                    "same interpretation id contains conflicting content")
            interpretations[identity] = proposed_item
        _unique(identities, "proposed interpretation")
        review_ids.append(set(identities))
    _unique(reviewers, "reviewer identity (case insensitive)")
    require({review["role"] for review in reviews} == {"legal_semantic", "formal_methods"},
            "distinct legal-semantic and formal-method roles required")
    adjudication = submission["adjudication"]
    adjudicator = _identifier(adjudication["adjudicator_id"], "adjudicator identity")
    require(adjudicator not in reviewers, "adjudicator must be distinct from reviewers")
    require(_timestamp(adjudication["adjudicated_at"]) >= max(times), "adjudication predates a review")
    require(adjudication["evidence_receipt"].strip() and adjudication["reason"].strip(),
            "adjudication evidence and reason required")
    accepted = adjudication["accepted_interpretation_ids"]
    _unique(accepted, "accepted interpretation")
    require(set(accepted) <= interpretations.keys(), "adjudication refers to unknown interpretation")
    decision = adjudication["decision"]
    if decision == "accept":
        require(bool(accepted) and bool(declared), "accept requires an interpretation and bound local context")
        require(all(review["decision"] in ("accept", "correct") for review in reviews)
                and all(set(accepted) <= identities for identities in review_ids),
                "accepted interpretation lacks consistent support from all submitted reviewers")
        require(all(not interpretations[identity]["unrepresented_meaning"] for identity in accepted),
                "accepted interpretation has unresolved unrepresented meaning")
        use = "repair_candidate" if any(review["decision"] == "correct" for review in reviews) else "positive_candidate"
        require(adjudication["eligible_use"] == use, "adjudication candidate use contradicts review decisions")
    else:
        require(not accepted, "nonaccept adjudication cannot accept interpretations")
        uses = {"reject": "exclude", "abstain": "abstention_candidate", "needs_context": "pending", "unresolved": "pending"}
        require(adjudication["eligible_use"] == uses[decision], "adjudication use contradicts decision")
    return {
        "schema": SCHEMA, "status": "structurally_valid_pending_external_verification",
        "packet_sha256": packet_receipt["sha256"], "submission_content_sha256": digest(submission),
        "text_group_id": submission["text_group_id"], "source_span_ids_reviewed": reviewed,
        "source_text_sha256": group["source_text_sha256"], "source_character_offsets_verified": True,
        "bound_context_artifact_sha256": sorted(declared), "context_authority_verified": False,
        "reviewer_ids": [review["reviewer_id"] for review in reviews],
        "adjudicator_id": adjudication["adjudicator_id"], "declared_adjudication": decision,
        "declared_candidate_use": adjudication["eligible_use"], "accepted_interpretation_ids": accepted,
        "reviewer_identity_verified": False, "reviewer_independence_verified": False,
        "review_receipt_authenticity_verified": False, "semantic_correctness_verified": False,
        "family_compliance_verified": False, "lake_build_executed": False,
        "training_qualified": False, "admitted": False, "gold_target": None,
        "policy": "Structure and local byte bindings only; external human authentication, context authority, semantic review and independent downstream validation remain required.",
    }


def intake_report(packet_path: Path, *, submission_paths: list[Path] | None = None,
                  context_paths: list[Path] | None = None) -> dict:
    """Create a pending report even with no external submissions."""
    packet, receipt = read_json(packet_path)
    _, observations = packet_index(packet)
    submissions, paths = submission_paths or [], context_paths or []
    require(len(submissions) <= MAX_SUBMISSIONS and len(paths) <= MAX_SUBMISSIONS,
            "input artifact count exceeds bound")
    _unique([str(path.resolve()) for path in submissions], "submission path")
    contexts = [read_json(path) for path in paths]
    require(receipt["bytes"] + sum(context_receipt["bytes"] for _, context_receipt in contexts) <= MAX_BYTES,
            "total intake byte budget exceeded")
    _contexts(contexts, observations)
    results, coverage, seen_bytes = [], Counter(), set()
    remaining = MAX_BYTES - receipt["bytes"] - sum(item[1]["bytes"] for item in contexts)
    for path in submissions:
        submission_receipt = None
        try:
            submission, submission_receipt = read_json(path, max_bytes=min(remaining, 4 * 1024 * 1024))
            remaining -= submission_receipt["bytes"]
            require(submission_receipt["sha256"] not in seen_bytes, "duplicate submission bytes")
            seen_bytes.add(submission_receipt["sha256"])
            result = validate_submission(packet, packet_receipt=receipt, submission=submission,
                                         context_artifacts=contexts)
            require(not any(identity in coverage for identity in result["source_span_ids_reviewed"]),
                    "multiple submissions for one observation require a separate explicit revision/adjudication process")
            coverage.update(result["source_span_ids_reviewed"])
        except (ReviewAdmissionError, OSError) as error:
            result = {"status": "rejected_structurally", "reason": str(error),
                      "training_qualified": False, "admitted": False}
        results.append({"input": submission_receipt or {"path": str(path.resolve())}, "result": result})
    return {
        "schema": "legal-review-intake-report/v1", "packet": receipt,
        "validator": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).read_bytes())},
        "submission_schema_sha256": SUBMISSION_SCHEMA_SHA256,
        "status": "pending_external_review" if not submissions else "structural_intake_only",
        "counts": {"source_observations": len(observations), "unique_text_groups": len(packet["groups"]),
                   "submissions": len(submissions), "structurally_valid": sum(coverage.values()),
                   "rejected_structurally": len(submissions) - sum(coverage.values()),
                   "observations_with_structurally_valid_submission": len(coverage),
                   "independently_verified_observations": 0, "training_qualified_observations": 0},
        "observations": [{"source_span_id": identity, "source_text_sha256": value["group"]["source_text_sha256"],
                          "valid_submission_count": coverage[identity],
                          "status": "pending_external_verification" if coverage[identity] else "no_external_submission",
                          "training_qualified": False, "gold_target": None}
                         for identity, value in sorted(observations.items())],
        "submissions": results, "context_artifacts": [entry[1] for entry in contexts],
        "supported_scope": {"observations_per_submission": 1, "family": SUPPORTED_FAMILY,
                            "profile": SUPPORTED_PROFILE, "max_rules_per_interpretation": 64,
                            "offset_units": "Python Unicode characters, end exclusive"},
        "pending_requirements": ["Obtain external reviews and separate adjudication for each source observation.",
                                 "Authenticate the reviewer identities, independence and review receipts externally.",
                                 "Verify authoritative source version and sufficient context independently.",
                                 "Validate legal semantics, family translation and actual Lake output before a separate training admission decision."],
        "training_qualified": False, "admitted": False, "gold_targets_created": 0,
        "reviewers_contacted": False, "independence_verified": False,
    }
