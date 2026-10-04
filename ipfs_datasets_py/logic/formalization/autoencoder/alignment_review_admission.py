"""Record source-only review submissions without creating review authority.

Hash bindings establish artifact consistency, not reviewer identity, author
independence, or semantic correctness. No model, provider, or prover is used.
The organizer receipt is private: it includes submitted annotations and an
authored-reference diagnostic computed only after accepting those annotations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path

SCHEMA = "autoformal-alignment-review-admission/v1"
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
MAX_ITEMS = 40
MAX_SUBMISSIONS = 20
MAX_FILE_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
_RECIPE = "sha256_utf8_sorted_compact_json_ensure_ascii_false_no_nan_no_newline"
_AUTHORITY = {"independent_fidelity_available": False, "source_semantics_verified": False,
              "proof_authority": False, "reviewer_attestations_created": False, "qualified": False}
_PAYLOAD_FIELDS = {"schema", "evaluation_role", "source_provenance", "instructions", "preparation_status", "items"}
_ITEM_FIELDS = {"item_id", "group_pseudonym", "source_text", "source_sha256", "evaluation_role", "annotation"}
_ANNOTATION_FIELDS = {"facets", "notes", "ambiguity", "unsupported_meaning", "reviewer_id", "reviewed_at_utc"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("bounded finite ordinary JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _text(value, limit, label, canonical=False):
    _require(type(value) is str and bool(value.strip()) and len(value) <= limit, "bounded " + label + " required")
    if canonical:
        _require(value == value.strip(), label + " must not have surrounding whitespace")


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), label + " SHA256 required")


def _false_authority(value):
    _require(all(value.get(name) is False for name in _AUTHORITY), "review preparation cannot grant authority")


def _facets(value, *, allow_blank):
    _closed(value, set(FACETS), "seven-facet annotation")
    for facet, entry in value.items():
        if entry is None and allow_blank:
            continue
        if facet == "modality":
            _require(type(entry) is str and entry in ("O", "P", "F"), "review modality must be O, P, or F")
        elif facet in ("actor", "action", "object"):
            _text(entry, 4096, "review " + facet)
        else:
            _require(type(entry) is list and len(entry) <= 128, "review " + facet + " must be a bounded list")
            for token in entry:
                _text(token, 4096, "review qualifier")


def _annotation(value):
    _closed(value, _ANNOTATION_FIELDS, "review annotation")
    _facets(value["facets"], allow_blank=True)
    notes = value["notes"]
    _require(notes is None or (type(notes) is str and len(notes) <= 8192), "bounded text notes required")
    for flag in ("ambiguity", "unsupported_meaning"):
        _require(value[flag] is None or type(value[flag]) is bool, "explicit Boolean " + flag + " required")
    if value["reviewer_id"] is not None:
        _text(value["reviewer_id"], 256, "reviewer identity", canonical=True)
    timestamp = value["reviewed_at_utc"]
    if timestamp is not None:
        _require(type(timestamp) is str and _UTC.fullmatch(timestamp), "review timestamp must be explicit ISO UTC")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("invalid UTC review timestamp") from error
    missing = [facet for facet in FACETS if value["facets"][facet] is None]
    missing += [name for name in ("ambiguity", "unsupported_meaning", "reviewer_id", "reviewed_at_utc")
                if value[name] is None]
    return missing


def _item(value):
    _closed(value, _ITEM_FIELDS, "review item envelope")
    _text(value["item_id"], 256, "item identity", canonical=True)
    _text(value["group_pseudonym"], 256, "group pseudonym", canonical=True)
    _text(value["source_text"], 32768, "exact source")
    _sha(value["source_sha256"], "source")
    _require(hashlib.sha256(value["source_text"].encode("utf-8")).hexdigest() == value["source_sha256"],
             "source text digest mismatch")
    _require(value["evaluation_role"] == "exposed_development", "only exposed development review is accepted")
    return _annotation(value["annotation"])


def _payload(value):
    _closed(value, _PAYLOAD_FIELDS, "source reviewer payload")
    _require(value["schema"] == "autoformal-source-facet-reviewer/v1", "unknown reviewer payload schema")
    _require(value["evaluation_role"] == "exposed_development"
             and value["source_provenance"] == "synthetic_authored_unreviewed"
             and value["preparation_status"] == "pending_human_review", "reviewer preparation metadata differs")
    _text(value["instructions"], 8192, "review instructions")
    _require(type(value["items"]) is list and 1 <= len(value["items"]) <= MAX_ITEMS, "bounded reviewer items required")
    seen = set()
    for item in value["items"]:
        _item(item)
        _require(item["item_id"] not in seen, "duplicate item within reviewer payload")
        seen.add(item["item_id"])


def _source_bindings(value):
    _require(type(value) is dict and value and len(_raw(value)) <= 128 * 1024, "bounded source bindings required")
    def check(entry):
        if type(entry) is dict:
            _require(all(type(key) is str for key in entry), "source binding keys must be text")
            if "evaluation_role" in entry:
                _require(entry["evaluation_role"] == "exposed_development", "sealed source binding forbidden")
            if "split" in entry:
                _require(entry["split"] in ("train", "validation"), "sealed split binding forbidden")
            if "path" in entry:
                _text(entry["path"], 4096, "source binding path")
                _require(not any(re.search(r"(^|[-_])(sealed|holdout|heldout|final|test)([-_.]|$)", part.casefold())
                                 for part in entry["path"].split("/")), "sealed/final source binding forbidden")
            for child in entry.values():
                check(child)
        elif type(entry) is list:
            for child in entry:
                check(child)
    check(value)


def _manifest(value, payload, audience, source_digest, item_count):
    fields = {"schema", "audience", "payload_schema", "payload_sha256", "digest_recipe", "item_count",
              "source_bindings_sha256", "candidate_blind", "automatic_adjudication", "evaluation_role"} | set(_AUTHORITY)
    _closed(value, fields, audience + " manifest")
    _false_authority(value)
    _require(value["schema"] == "autoformal-source-facet-review-manifest/v1"
             and value["audience"] == audience and value["payload_schema"] == payload["schema"], "unknown review manifest identity")
    _require(value["digest_recipe"] == _RECIPE and value["payload_sha256"] == _digest(payload)
             and value["source_bindings_sha256"] == source_digest, "review payload/source binding digest mismatch")
    _require(type(value["item_count"]) is int and value["item_count"] == item_count
             and value["candidate_blind"] is (audience == "reviewer")
             and value["automatic_adjudication"] is False and value["evaluation_role"] == "exposed_development",
             "review manifest scope differs")


def _bundle(value):
    fields = {"schema", "status", "reviewer_payload", "organizer_payload", "reviewer_manifest", "organizer_manifest",
              "model_calls", "provider_calls", "encoder_calls", "prover_calls", "training_executed"} | set(_AUTHORITY)
    _closed(value, fields, "review bundle")
    _require(len(_raw(value)) <= MAX_FILE_BYTES, "review bundle exceeds byte bound")
    _false_authority(value)
    _require(value["schema"] == "autoformal-alignment-review-bundle/v1"
             and value["status"] == "prepared_pending_human_review", "unknown review preparation bundle")
    _require(value["training_executed"] is False and all(type(value[name]) is int and value[name] == 0
             for name in ("model_calls", "provider_calls", "encoder_calls", "prover_calls")), "review preparation execution scope differs")
    reviewer = value["reviewer_payload"]
    _payload(reviewer)
    for item in reviewer["items"]:
        annotation = item["annotation"]
        _require(all(entry is None for entry in annotation["facets"].values())
                 and all(entry is None for name, entry in annotation.items() if name != "facets"),
                 "original reviewer payload must contain only blank annotation slots")
    organizer = value["organizer_payload"]
    organizer_fields = {"schema", "do_not_send_to_reviewers", "source_bindings", "source_bindings_sha256",
                        "source_provenance", "reviewer_key", "sampling", "contrast_corpus"} | set(_AUTHORITY)
    _closed(organizer, organizer_fields, "organizer payload")
    _false_authority(organizer)
    _require(organizer["schema"] == "autoformal-source-facet-organizer/v1"
             and organizer["do_not_send_to_reviewers"] is True
             and organizer["source_provenance"] == "synthetic_authored_unreviewed", "organizer preparation scope differs")
    _source_bindings(organizer["source_bindings"])
    source_digest = _digest(organizer["source_bindings"])
    _require(organizer["source_bindings_sha256"] == source_digest, "organizer source binding digest mismatch")
    for audience, payload in (("reviewer", reviewer), ("organizer", organizer)):
        _manifest(value[audience + "_manifest"], payload, audience, source_digest, len(reviewer["items"]))
    items = {item["item_id"]: item for item in reviewer["items"]}
    _require(type(organizer["reviewer_key"]) is list and len(organizer["reviewer_key"]) == len(items),
             "organizer item accounting differs")
    key, originals = {}, set()
    key_fields = {"item_id", "group_pseudonym", "original_id", "original_group_id", "source_sha256", "split",
                  "wording_style", "synthetic_authored_reference_target", "reference_target_sha256", "reference_review_status"}
    for entry in organizer["reviewer_key"]:
        _closed(entry, key_fields, "organizer item key")
        identity = entry["item_id"]
        _require(type(identity) is str and identity in items and identity not in key, "unknown or duplicate organizer item")
        for name in ("group_pseudonym", "source_sha256"):
            _require(entry[name] == items[identity][name], "organizer item binding differs")
        for name in ("original_id", "original_group_id"):
            _text(entry[name], 512, "original source identity")
        _require(entry["original_id"] not in originals, "duplicate original source identity")
        originals.add(entry["original_id"])
        style = entry["wording_style"]
        _require(entry["split"] == "validation" and entry["reference_review_status"] == "unreviewed"
                 and (style is None or type(style) is int and 0 <= style <= 100), "organizer source/reference role differs")
        target = entry["synthetic_authored_reference_target"]
        _closed(target, {"rules"}, "authored reference")
        _require(type(target["rules"]) is list and len(target["rules"]) == 1, "one authored reference rule required")
        _facets(target["rules"][0], allow_blank=False)
        _require(entry["reference_target_sha256"] == _digest(target), "authored reference digest mismatch")
        key[identity] = entry
    _require(type(organizer["sampling"]) is dict and organizer["sampling"].get("selected_items") == len(items),
             "organizer sample accounting differs")
    contrasts = organizer["contrast_corpus"]
    _require(type(contrasts) is dict and contrasts.get("schema") == "autoformal-unreviewed-ir-contrasts/v1"
             and contrasts.get("not_ground_truth") is True and contrasts.get("encoded") is False
             and contrasts.get("excluded_from_training") is True and contrasts.get("excluded_from_evaluation_gold") is True
             and contrasts.get("proof_verified") is False, "contrast proposals must remain unreviewed and excluded")
    _false_authority(contrasts)
    return items, key


def _strict_object(pairs):
    value = {}
    for key, entry in pairs:
        _require(key not in value, "duplicate JSON key: " + key)
        value[key] = entry
    return value


def read_alignment_review_file(path: Path | str, expected_sha256: str, max_bytes: int = MAX_FILE_BYTES) -> dict:
    """Read a bounded SHA-pinned JSON object, rejecting duplicates/nonfinite values.

    The dictionary API cannot recover duplicate keys already discarded by a
    caller's JSON parser. Use this reader or an equally strict caller boundary.
    A pinned digest remains integrity evidence, not an identity attestation.
    """
    _sha(expected_sha256, "review file")
    _require(type(max_bytes) is int and 1 <= max_bytes <= MAX_FILE_BYTES, "bounded review file byte limit required")
    flags = os.O_RDONLY | getattr(os,"O_NONBLOCK",0) | getattr(os,"O_NOFOLLOW",0)
    descriptor = os.open(Path(path),flags)
    with os.fdopen(descriptor,"rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode),"regular review file required")
        _require(info.st_size <= max_bytes,"review file exceeds byte bound")
        raw = stream.read(max_bytes + 1)
        _require(len(raw)==info.st_size,"review file changed during reading")
    _require(len(raw) <= max_bytes, "review file exceeds byte bound")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "review file SHA256 mismatch")
    def reject_constant(value):
        raise ValueError("nonfinite JSON value: " + value)
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=reject_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("valid bounded UTF-8 review JSON required") from error
    _require(type(value) is dict, "review file must contain a JSON object")
    _require(len(_raw(value)) <= MAX_FILE_BYTES, "review JSON exceeds byte bound")
    return value


def admit_alignment_reviews(review_bundle: dict, reviewed_payloads: list[dict]) -> dict:
    """Validate submissions and record reviewer concordance, without adjudication.

    Item subsets and reordered items are allowed. Immutable source/envelope
    fields must equal the prepared payload. Incomplete, correctly typed slots
    stay pending; empty qualifier lists explicitly record reviewed absence.
    Conflicting complete reviews are never resolved against authored targets.
    """
    items, organizer_key = _bundle(review_bundle)
    _require(type(reviewed_payloads) is list and len(reviewed_payloads) <= MAX_SUBMISSIONS, "bounded review submissions required")
    _require(len(_raw(reviewed_payloads)) <= MAX_FILE_BYTES, "review submissions exceed byte bound")
    original = review_bundle["reviewer_payload"]
    submissions, received, seen_digests, reviewer_items = [], {identity: [] for identity in items}, set(), set()
    for index, payload in enumerate(reviewed_payloads):
        _payload(payload)
        _require(all(payload[name] == original[name] for name in _PAYLOAD_FIELDS - {"items"}), "reviewer payload metadata changed")
        digest = _digest(payload)
        _require(digest not in seen_digests, "duplicate review submission")
        seen_digests.add(digest)
        for item in payload["items"]:
            identity = item["item_id"]
            _require(identity in items, "unknown reviewed item")
            _require(all(item[name] == items[identity][name] for name in _ITEM_FIELDS - {"annotation"}),
                     "immutable reviewed source/item binding changed")
            annotation = item["annotation"]
            missing = _annotation(annotation)
            reviewer = annotation["reviewer_id"]
            if reviewer is not None:
                pair = (identity, reviewer)
                _require(pair not in reviewer_items, "duplicate reviewer for the same item")
                reviewer_items.add(pair)
            received[identity].append({"submission_index": index, "submission_sha256": digest,
                                       "annotation": deepcopy(annotation), "complete": not missing,
                                       "missing_fields": missing})
        submissions.append({"submission_index": index, "payload_sha256": digest, "item_count": len(payload["items"]),
                            "declared_reviewer_ids": sorted({item["annotation"]["reviewer_id"] for item in payload["items"]
                                                             if item["annotation"]["reviewer_id"] is not None}),
                            "identity_authenticated": False, "source_author_independence_authenticated": False})
    results = []
    for identity in sorted(items):
        complete = [entry for entry in received[identity] if entry["complete"]]
        signatures = {_digest({"facets": entry["annotation"]["facets"],
                               "ambiguity": entry["annotation"]["ambiguity"],
                               "unsupported_meaning": entry["annotation"]["unsupported_meaning"]}) for entry in complete}
        status = "pending"
        if complete:
            if len(signatures) != 1:
                status = "disputed"
            elif complete[0]["annotation"]["unsupported_meaning"]:
                status = "unsupported"
            elif complete[0]["annotation"]["ambiguity"]:
                status = "ambiguous"
            else:
                status = "agreed_multiple_reviews" if len(complete) >= 2 else "single_review"
        diagnostic = {"status": "unavailable", "value": None, "reason": "no_unambiguous_undisputed_completed_annotation",
                      "role": "authored_agreement_diagnostic", "reference_origin": "synthetic_authored_unreviewed",
                      "independent_fidelity": False}
        if status in ("single_review", "agreed_multiple_reviews"):
            # The annotation is accepted before the organizer-only reference is read for scoring.
            annotated = complete[0]["annotation"]["facets"]
            reference = organizer_key[identity]["synthetic_authored_reference_target"]["rules"][0]
            agreement = {facet: annotated[facet] == reference[facet] for facet in FACETS}
            diagnostic = {"status": "computed_after_annotation_acceptance", "value": all(agreement.values()),
                          "facet_agreement": agreement, "role": "authored_agreement_diagnostic",
                          "reference_origin": "synthetic_authored_unreviewed", "independent_fidelity": False}
        results.append({"item_id": identity, "group_pseudonym": items[identity]["group_pseudonym"],
                        "source_sha256": items[identity]["source_sha256"], "evaluation_role": "exposed_development",
                        "status": status, "complete_distinct_reviewer_count": len(complete),
                        "pending_submission_count": len(received[identity]) - len(complete),
                        "submissions": received[identity], "authored_reference_diagnostic": diagnostic,
                        "preliminary_independent_adjudication_candidate": status == "agreed_multiple_reviews",
                        "external_adjudication_status": "pending", **_AUTHORITY})
    counts = Counter(entry["status"] for entry in results)
    receipt = {"schema": SCHEMA, "status": "pending" if not any(entry["complete_distinct_reviewer_count"] for entry in results)
               else "submitted_reviews_recorded", "evaluation_role": "exposed_development", "organizer_private": True,
               "review_bundle_sha256": _digest(review_bundle), "reviewer_payload_sha256": _digest(original),
               "organizer_payload_sha256": _digest(review_bundle["organizer_payload"]),
               "reviewer_manifest_sha256": _digest(review_bundle["reviewer_manifest"]),
               "organizer_manifest_sha256": _digest(review_bundle["organizer_manifest"]),
               "source_bindings_sha256": review_bundle["organizer_payload"]["source_bindings_sha256"],
               "digest_recipe": _RECIPE, "submissions": submissions, "items": results,
               "status_counts": {name: counts[name] for name in ("pending", "single_review", "agreed_multiple_reviews",
                                                                "disputed", "ambiguous", "unsupported")},
               "preliminary_candidate_count": sum(entry["preliminary_independent_adjudication_candidate"] for entry in results),
               "reference_used_to_resolve_disputes": False, "automatic_adjudication": False,
               "reviewer_identity_evidence": {"status": "unavailable", "authenticated": False},
               "source_author_independence_evidence": {"status": "unavailable", "authenticated": False},
               "reviewer_attestation_evidence": {"status": "unavailable", "authenticated": False},
               "primary_independently_adjudicated_fidelity": {"status": "unavailable", "value": None},
               "native_useful_proof_coverage": {"status": "unrun", "value": None},
               "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
               "production_admitted": False, **_AUTHORITY}
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


__all__ = ["admit_alignment_reviews", "read_alignment_review_file"]
