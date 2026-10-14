"""Bounded candidate joins from paired observations to pinned stored source text.

The caller supplies independently expected input hashes and the complete ordered
population of source sections. This in-memory owner performs no file access,
downloads, official-source authentication, HTML extraction, or legal review.
The original producer receipt constrains a physical Parquet row; its historical
ordinal is never interpreted as a character offset. Every exact stored-text
match is retained, including overlaps, or the operation refuses its bounds.

Source records reuse ``corpus_source`` with the retained text bytes themselves
as the text/plain raw artifact. The larger Parquet artifact remains a separate
provenance reference. These coordinates are not GovInfo normalized-view v2
selectors. Even one exact match is only a candidate, never attestation of the
producer's original occurrence. No occurrence is selected automatically.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

from .corpus_contracts import (
    CorpusContractError,
    clone_json,
    load_record_bytes,
    require_cid,
    require_int,
    require_keys,
    require_sha256,
    require_text,
    seal_record,
    validate_record,
)
from .corpus_source import (
    build_context_declaration,
    build_source_occurrence,
    build_source_version,
)
from .legal_statutory_context import DEPENDENCY_KINDS

SCHEMA = "legal-corpus-legacy-source-join/v1"
SOURCE_PROFILE = "pinned-parquet-text-column-as-stored/v1"
UNDECLARED_EDITION = "not_declared_in_source_artifact"
MAX_ROWS = 64
MAX_SECTIONS = 64
MAX_SECTION_BYTES = 128 * 1024
MAX_SOURCE_TEXT_BYTES = 512 * 1024
MAX_PAIRED_INPUT_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_NODES = 2_000_000
MAX_RECEIPT_DEPTH = 48
MAX_RECEIPT_ROWS = 4096
MAX_OCCURRENCES_PER_ROW = 256
MAX_TOTAL_OCCURRENCES = 512
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_POINTER = re.compile(r"/rows/(0|[1-9][0-9]*)/logic_target_observation\Z")
_POPULATION_FIELDS = {"row_sha256", "source_span_id", "text_sha256", "source_revision"}
_SECTION_FIELDS = {
    "repository_id",
    "revision",
    "path_in_repo",
    "artifact_sha256",
    "artifact_bytes",
    "release_id",
    "parquet_row_index",
    "entry_cid",
    "legal_id",
    "text_sha256",
}
_FIELDS = {
    "profile",
    "expected_population",
    "expected_source_sections",
    "producer_receipt",
    "source_sections",
    "rows",
    "counts",
    "population_complete",
    "coverage_scope",
    "selected_occurrence",
    "original_producer_occurrence_attested",
    "source_authenticity_verified",
    "source_semantics_verified",
    "official_html_view_mapping_verified",
    "context_closure_verified",
    "admitted",
    "formalized",
    "proof_authority",
}


def _fail(message):
    raise CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _receipt(raw, expected_sha256):
    """Read a separately bounded large receipt, never enlarging corpus records."""
    require_sha256(expected_sha256, "expected_producer_receipt_sha256")
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RECEIPT_BYTES:
        _fail("producer receipt requires bounded immutable bytes")
    if _sha(raw) != expected_sha256:
        _fail("producer receipt differs from independently expected SHA256")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate producer receipt JSON key")
            result[key] = value
        return result

    def constant(_):
        _fail("non-finite producer receipt JSON")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("invalid producer receipt JSON") from error
    stack, remaining = [(value, 0)], MAX_RECEIPT_NODES
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        if remaining < 0 or depth > MAX_RECEIPT_DEPTH:
            _fail("producer receipt exceeds JSON node/depth bounds")
        if type(item) is dict:
            for key, child in item.items():
                require_text(key, "producer receipt JSON key", max_bytes=4096)
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            require_text(
                item, "producer receipt JSON string", allow_empty=True, max_bytes=MAX_RECEIPT_BYTES
            )
        elif type(item) is float:
            if not math.isfinite(item):
                _fail("non-finite producer receipt JSON")
        elif type(item) is int:
            require_int(item, "producer receipt integer", minimum=-(1 << 63) + 1)
        elif item is not None and type(item) is not bool:
            _fail("ordinary producer receipt JSON required")
    if type(value) is not dict or type(value.get("rows")) is not list:
        _fail("producer receipt requires an explicit rows list")
    if len(value["rows"]) > MAX_RECEIPT_ROWS:
        _fail("producer receipt row count exceeds bound")
    require_text(value.get("schema_version"), "producer receipt schema_version")
    return value


def _provenance(value):
    require_keys(value, _SECTION_FIELDS, "expected source section")
    if value["repository_id"] != "justicedao/ipfs_uscode":
        _fail("supported legacy source repository required")
    if type(value["revision"]) is not str or not _REVISION.fullmatch(value["revision"]):
        _fail("source revision requires an immutable complete commit")
    if value["path_in_repo"] != "uscode_parquet/laws.parquet":
        _fail("supported legacy source Parquet path required")
    require_sha256(value["artifact_sha256"], "source artifact SHA256")
    require_int(
        value["artifact_bytes"], "source artifact bytes", minimum=1, maximum=512 * 1024 * 1024
    )
    require_text(value["release_id"], "source release_id", max_bytes=256)
    require_int(value["parquet_row_index"], "physical Parquet row", maximum=2_000_000)
    require_cid(value["entry_cid"], "declared entry CID")
    require_text(value["legal_id"], "source legal_id", max_bytes=1024)
    require_sha256(value["text_sha256"], "complete stored section text SHA256")
    return value


def _sections(source_sections, expected):
    if type(source_sections) is not list or type(expected) is not list:
        _fail("ordered source section and expected section lists required")
    if len(source_sections) != len(expected) or len(expected) > MAX_SECTIONS:
        _fail("exact bounded expected source section population required")
    # Validate aggregate ordinary JSON before copying or deriving any records.
    sections, expected = clone_json(source_sections), clone_json(expected)
    result, seen, total = [], set(), 0
    for supplied, pin in zip(sections, expected, strict=True):
        _provenance(pin)
        require_keys(supplied, _SECTION_FIELDS | {"text"}, "full stored source section")
        if {key: supplied[key] for key in _SECTION_FIELDS} != pin:
            _fail("source section differs from independently expected population")
        text = require_text(
            supplied["text"], "complete stored section text", max_bytes=MAX_SECTION_BYTES
        )
        raw = text.encode("utf-8")
        total += len(raw)
        if total > MAX_SOURCE_TEXT_BYTES:
            _fail("aggregate complete source text exceeds byte bound")
        if _sha(raw) != pin["text_sha256"]:
            _fail("complete stored source section text differs from expected SHA256")
        physical = tuple(
            pin[key]
            for key in (
                "repository_id",
                "revision",
                "path_in_repo",
                "artifact_sha256",
                "parquet_row_index",
            )
        )
        if physical in seen:
            _fail("duplicate physical source section")
        seen.add(physical)
        source_id = (
            f"{pin['repository_id']}@{pin['revision']}/{pin['path_in_repo']}"
            f"#artifact_sha256={pin['artifact_sha256']};row={pin['parquet_row_index']}"
            f";entry_cid={pin['entry_cid']}"
        )
        version = build_source_version(
            source_id=source_id,
            release_id=pin["release_id"],
            edition=UNDECLARED_EDITION,
            provision_id=pin["legal_id"],
            raw_bytes=raw,
            expected_raw_sha256=pin["text_sha256"],
            extracted_text=text,
            expected_extracted_sha256=pin["text_sha256"],
            extraction_profile=SOURCE_PROFILE,
            normalization_profile="identity/v1",
            media_type="text/plain",
            historical_aliases=[
                {
                    "alias_id": pin["legal_id"],
                    "status": "declared_alias",
                    "reason": "Historical Parquet metadata; no official identity or edition authentication.",
                }
            ],
        )
        result.append({"provenance": pin, "source_version": version, "extracted_text": text})
    return result, expected


def _population(paired_row_bytes, expected_population):
    if type(paired_row_bytes) is not list or type(expected_population) is not list:
        _fail("ordered paired bytes and independent expected population required")
    if not 1 <= len(paired_row_bytes) == len(expected_population) <= MAX_ROWS:
        _fail("exact bounded nonempty paired row population required")
    if any(type(raw) is not bytes for raw in paired_row_bytes):
        _fail("paired rows require immutable bytes")
    if sum(map(len, paired_row_bytes)) > MAX_PAIRED_INPUT_BYTES:
        _fail("aggregate paired input bytes exceed bound")
    expected = clone_json(expected_population)
    result, seen = [], set()
    for raw, pin in zip(paired_row_bytes, expected, strict=True):
        require_keys(pin, _POPULATION_FIELDS, "expected paired population row")
        for field in ("row_sha256", "text_sha256"):
            require_sha256(pin[field], field)
        require_text(pin["source_span_id"], "expected source span ID")
        require_text(pin["source_revision"], "expected source release")
        if pin["row_sha256"] in seen:
            _fail("duplicate paired row commitment")
        seen.add(pin["row_sha256"])
        row = load_record_bytes(raw, expected_sha256=pin["row_sha256"])
        schema = require_text(row.get("schema_version"), "paired schema_version")
        if schema not in {"uscode-paired-span-census/v1", "uscode-paired-span-census/v2"}:
            _fail("supported paired span schema required")
        source = row.get("source")
        if type(source) is not dict:
            _fail("paired source object required")
        require_text(source.get("text"), "paired source text", max_bytes=MAX_SECTION_BYTES)
        require_text(source.get("legal_id"), "paired source legal_id")
        require_text(row.get("observation_id"), "historical observation ID")
        if (
            source.get("span_id") != pin["source_span_id"]
            or source.get("revision") != pin["source_revision"]
            or source.get("text_sha256") != pin["text_sha256"]
            or _sha(source["text"].encode("utf-8")) != pin["text_sha256"]
        ):
            _fail("paired source differs from independently expected population")
        result.append(row)
    return result, expected


def _producer_link(row, receipt, receipt_sha):
    reference, pointer = (
        row.get("source_target_artifact_sha256"),
        row.get("source_target_artifact_pointer"),
    )
    if receipt is None or reference is None:
        return {
            "status": "producer_source_unavailable",
            "producer_row_index": None,
            "pointer": pointer,
            "producer_record": None,
        }
    if (
        reference != receipt_sha
        or type(pointer) is not str
        or not (match := _POINTER.fullmatch(pointer))
    ):
        _fail("paired producer pointer differs from independently bound receipt")
    index = int(match[1])
    if index >= len(receipt["rows"]):
        _fail("paired producer pointer is outside receipt population")
    observed = receipt["rows"][index]
    if type(observed) is not dict or "logic_target_observation" not in observed:
        _fail("paired producer pointer does not resolve")
    source = row["source"]
    if (
        observed.get("source_span_id") != source["span_id"]
        or observed.get("text") != source["text"]
        or observed.get("source_sha256") != source["text_sha256"]
        or observed.get("legal_id") != source["legal_id"]
    ):
        _fail("exact referenced producer row differs from paired source")
    parent = observed.get("source_parent")
    if parent is None:
        return {
            "status": "producer_source_unavailable",
            "producer_row_index": index,
            "pointer": pointer,
            "producer_record": None,
        }
    if type(parent) is not dict:
        _fail("producer source parent must be an object")
    required = {"repository_id", "revision", "path_in_repo", "sha256", "bytes", "release_id"}
    if not required <= set(parent):
        _fail("complete producer parent descriptors required")
    projection = {
        "source_span_id": observed["source_span_id"],
        "text": observed["text"],
        "source_sha256": observed["source_sha256"],
        "legal_id": observed["legal_id"],
        "entry_cid": observed.get("entry_cid"),
        "source_section_offset": observed.get("source_section_offset"),
        "source_parent": clone_json(parent),
        "historical_metadata": {
            key: observed[key]
            for key in (
                "historical_document_batch_index",
                "historical_document_batch_size",
                "historical_span_ordinal",
                "identity_reconstruction",
                "source_identity_match",
                "title",
                "section",
                "citation",
            )
            if key in observed
        },
    }
    provenance = {
        "repository_id": parent["repository_id"],
        "revision": parent["revision"],
        "path_in_repo": parent["path_in_repo"],
        "artifact_sha256": parent["sha256"],
        "artifact_bytes": parent["bytes"],
        "release_id": parent["release_id"],
        "parquet_row_index": projection["source_section_offset"],
        "entry_cid": projection["entry_cid"],
        "legal_id": projection["legal_id"],
        "text_sha256": source["text_sha256"],
    }
    _provenance(provenance)
    if parent["release_id"] != source["revision"]:
        _fail("paired source release differs from exact producer parent")
    return {
        "status": "exact_producer_row_bound",
        "producer_row_index": index,
        "pointer": pointer,
        "producer_record": projection,
    }


def build_legacy_source_join(
    paired_row_bytes,
    *,
    expected_population,
    producer_receipt_bytes,
    expected_producer_receipt_sha256,
    source_sections,
    expected_source_sections,
):
    """Build a declared-population candidate ledger from independent exact inputs.

    ``expected_population`` rows have row_sha256, source_span_id, text_sha256,
    source_revision. Expected source sections have exactly the provenance fields
    listed in ``_SECTION_FIELDS``; supplied sections add the complete ``text``.
    Empty source inventories or an explicitly unavailable receipt (both receipt
    arguments None) retain unresolved rows. Expectations must originate outside
    incoming records; this API does not authenticate that external boundary.
    """
    rows, expected = _population(paired_row_bytes, expected_population)
    sections, expected_sections = _sections(source_sections, expected_source_sections)
    if producer_receipt_bytes is None or expected_producer_receipt_sha256 is None:
        if producer_receipt_bytes is not None or expected_producer_receipt_sha256 is not None:
            _fail("unavailable producer receipt requires both arguments to be null")
        receipt = None
    else:
        receipt = _receipt(producer_receipt_bytes, expected_producer_receipt_sha256)
    outputs, total_occurrences, counts = [], 0, {}
    for row, pin in zip(rows, expected, strict=True):
        link = _producer_link(row, receipt, expected_producer_receipt_sha256)
        candidates, disposition = [], "producer_source_unavailable"
        if link["status"] == "exact_producer_row_bound":
            producer = link["producer_record"]
            parent = producer["source_parent"]
            physical = [
                index
                for index, section in enumerate(sections)
                if all(
                    section["provenance"][key] == value
                    for key, value in {
                        "repository_id": parent["repository_id"],
                        "revision": parent["revision"],
                        "path_in_repo": parent["path_in_repo"],
                        "artifact_sha256": parent["sha256"],
                        "parquet_row_index": producer["source_section_offset"],
                    }.items()
                )
            ]
            disposition = "source_section_unavailable"
            if physical:
                index = physical[0]
                section = sections[index]
                provenance, text, version = (
                    section["provenance"],
                    section["extracted_text"],
                    section["source_version"],
                )
                if (
                    provenance["entry_cid"] != producer["entry_cid"]
                    or provenance["legal_id"] != producer["legal_id"]
                    or provenance["artifact_bytes"] != parent["bytes"]
                    or provenance["release_id"] != parent["release_id"]
                ):
                    disposition = "producer_parent_mismatch"
                else:
                    position, target = 0, row["source"]["text"]
                    while (start := text.find(target, position)) >= 0:
                        if (
                            len(candidates) >= MAX_OCCURRENCES_PER_ROW
                            or total_occurrences >= MAX_TOTAL_OCCURRENCES
                        ):
                            _fail("exact occurrence bound exceeded; candidate inventory incomplete")
                        end = start + len(target)
                        occurrence = build_source_occurrence(
                            version,
                            expected_raw_sha256=provenance["text_sha256"],
                            extracted_text=text,
                            expected_extracted_sha256=provenance["text_sha256"],
                            start_char=start,
                            end_char=end,
                            start_utf8=len(text[:start].encode("utf-8")),
                            end_utf8=len(text[:end].encode("utf-8")),
                            historical_aliases=[
                                {
                                    "alias_id": row["source"]["span_id"],
                                    "status": "unresolved",
                                    "reason": "Exact stored-text candidate; original producer character occurrence remains unattested.",
                                }
                            ],
                        )
                        context = build_context_declaration(
                            occurrence,
                            expected_occurrence_cid=occurrence["record_cid"],
                            availability="required_unavailable",
                            missing_requirements=list(DEPENDENCY_KINDS),
                            reason="Physical stored-text geometry supplies no reviewed governing context.",
                        )
                        candidates.append(
                            {
                                "source_section_index": index,
                                "source_occurrence": occurrence,
                                "context_declaration": context,
                            }
                        )
                        total_occurrences += 1
                        position = start + 1
                    disposition = (
                        "no_exact_occurrence"
                        if not candidates
                        else "unique_exact_candidate"
                        if len(candidates) == 1
                        else "ambiguous_exact_candidates"
                    )
        counts[disposition] = counts.get(disposition, 0) + 1
        outputs.append(
            {
                **pin,
                "observation_id": row["observation_id"],
                "legal_id": row["source"]["legal_id"],
                "producer_link": link,
                "disposition": disposition,
                "occurrence_count": len(candidates),
                "candidates": candidates,
                "selected_occurrence": None,
                "original_producer_occurrence_attested": False,
                "context_status": "required_unresolved",
            }
        )
    record = seal_record(
        {
            "schema": SCHEMA,
            "profile": SOURCE_PROFILE,
            "expected_population": expected,
            "expected_source_sections": expected_sections,
            "producer_receipt": None
            if receipt is None
            else {
                "sha256": expected_producer_receipt_sha256,
                "bytes": len(producer_receipt_bytes),
                "schema_version": receipt["schema_version"],
                "row_count": len(receipt["rows"]),
            },
            "source_sections": sections,
            "rows": outputs,
            "counts": {
                "paired_rows": len(rows),
                "source_sections": len(sections),
                "candidate_occurrences": total_occurrences,
                "dispositions": counts,
            },
            "population_complete": True,
            "coverage_scope": "exact_supplied_paired_and_source_population_only",
            "selected_occurrence": None,
            "original_producer_occurrence_attested": False,
            "source_authenticity_verified": False,
            "source_semantics_verified": False,
            "official_html_view_mapping_verified": False,
            "context_closure_verified": False,
            "admitted": False,
            "formalized": False,
            "proof_authority": False,
        }
    )
    return record


def validate_legacy_source_join(record, paired_row_bytes, **independent_inputs):
    """Check the seal and regenerate every candidate from independent inputs."""
    checked = validate_record(record, schema=SCHEMA, fields=_FIELDS)
    expected = build_legacy_source_join(paired_row_bytes, **independent_inputs)
    if checked != expected:
        _fail("legacy source join differs from exact independent regeneration")
    return checked


__all__ = [
    "SCHEMA",
    "SOURCE_PROFILE",
    "UNDECLARED_EDITION",
    "build_legacy_source_join",
    "validate_legacy_source_join",
]
