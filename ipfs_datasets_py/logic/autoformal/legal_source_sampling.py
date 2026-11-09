"""Whole markup-block candidates with exact source custody and open context.

This is a deterministic input inventory, not a legal sentence splitter or a
definition parser. Existing official-view and source owners define every byte,
block and occurrence. All blocks survive; markup observations only distinguish
candidate statute paragraphs from retained structure and control inputs.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from . import corpus_source as sources
from . import legal_official_document_views as views
from . import legal_statutory_context as contexts
from .corpus_contracts import CorpusContractError, seal_record

SCHEMA = "legal-source-structured-sampling/v1"
UNIT_SCHEMA = "legal-source-structured-sample-unit/v1"
POLICY = "complete-official-markup-block-population/v1"
DEFAULT_LIMITS = {"max_units": 2048, "max_report_bytes": 32 * 1024 * 1024}
AUTHORITY = dict.fromkeys(
    (
        *views.AUTHORITY,
        "legal_hierarchy_verified",
        "definition_operator_interpreted",
        "semantic_graph_admitted",
        "training_gold_qualified",
        "Lean_admitted",
    ),
    False,
)


def _need(condition, message):
    if not condition:
        raise CorpusContractError(message)


def _wire(value):
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise CorpusContractError(
            "finite canonical UTF8 sampling JSON required"
        ) from error
    _need(
        len(raw) <= DEFAULT_LIMITS["max_report_bytes"],
        "complete sampling JSON exceeds hard byte bound; truncation refused",
    )
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _limits(value):
    _need(
        value is None or type(value) is dict and not (set(value) - set(DEFAULT_LIMITS)),
        "closed optional sampling limits required",
    )
    result = dict(DEFAULT_LIMITS, **(value or {}))
    for name, bound in result.items():
        _need(
            type(bound) is int and 0 < bound <= DEFAULT_LIMITS[name],
            "positive lowered sampling bound required: " + name,
        )
    return result


def _reference(record):
    return {
        "schema": record["schema"],
        "record_cid": record["record_cid"],
        "sha256": _digest(record),
    }


def _stratum(block, withheld):
    if block["region_kind"] == "statute":
        if block["block_kind"] == "paragraph" and not withheld:
            return "candidate_statute_paragraph"
        return "statute_structure_context"
    return "retained_context_control"


def _fragmented_paragraphs(blocks):
    """Recognize physical splits, never infer statutory paragraph hierarchy."""
    paths = {
        tuple(tuple(item) for item in b["dom_path"])
        for b in blocks
        if b["region_kind"] == "statute" and b["tag"] == "p"
    }
    result = []
    for path in sorted(paths):
        members = [
            b
            for b in blocks
            if tuple(tuple(item) for item in b["dom_path"][: len(path)]) == path
        ]
        # br/comments can flush one p into several pieces. Nested block text can
        # also leave one p prefix plus descendant blocks, even without a suffix.
        if len(members) > 1:
            result.append(members)
    return result


def _source_pair(version, doc, raw_sha, first, last):
    occurrence = sources.build_source_occurrence(
        version,
        expected_raw_sha256=raw_sha,
        extracted_text=doc["document_text"],
        expected_extracted_sha256=doc["document_text_sha256"],
        start_char=first["char_start"],
        end_char=last["char_end"],
        start_utf8=first["utf8_byte_start"],
        end_utf8=last["utf8_byte_end"],
    )
    context = sources.build_context_declaration(
        occurrence,
        expected_occurrence_cid=occurrence["record_cid"],
        availability="required_unavailable",
        reason="Whole source view is retained; legal context attachments and scope remain unreviewed.",
        context_references=[
            {
                "record_cid": version["record_cid"],
                "record_kind": "source_version",
                "purpose": "complete normalized source view retained, not dependency closure",
            }
        ],
        missing_requirements=list(contexts.DEPENDENCY_KINDS),
    )
    return occurrence, context


def prepare_source_sampling(
    raw,
    *,
    descriptor,
    expected_descriptor_sha256,
    expected_raw_sha256,
    expected_raw_bytes,
    view_limits=None,
    limits=None,
):
    """Prepare every whole DOM block once, without interpreting or dropping it.

    The official view is prepared exactly once. Missing bytes and unsupported
    markup retain that owner's explicit disposition and yield no candidates.
    Invalid independent pins and exceeded bounds raise without partial output.
    No I/O, random sampling, model, network, native compiler or trust action runs.
    """
    bounds = _limits(limits)
    view_report = views.prepare_official_document_view(
        raw,
        descriptor=descriptor,
        expected_descriptor_sha256=expected_descriptor_sha256,
        expected_raw_sha256=expected_raw_sha256,
        expected_raw_bytes=expected_raw_bytes,
        limits=view_limits,
    )
    # The full independent view and all comments/attributes stay in this report.
    # Its offsets never replace v1 extraction or historical Parquet coordinates.
    report = {
        "schema": SCHEMA,
        "policy": POLICY,
        "limits": bounds,
        "document_view_report": view_report,
        "document_view_report_sha256": views.document_view_report_sha256(view_report),
        "records": [],
        "unit_refs": [],
        "withheld_paragraph_contexts": [],
        "status": "source_view_unavailable",
        "issues": list(view_report["issues"]),
        "counts": {
            "blocks": 0,
            "units": 0,
            "records": 0,
            "strata": {},
            "region_kinds": {},
            "interblock_LF_separators": 0,
            "withheld_fragmented_paragraphs": 0,
        },
        "authority": dict(AUTHORITY),
        "limitations": [
            "Markup region, class, label and DOM order are observations, not reviewed legal roles or hierarchy.",
            "All candidate/control inputs have zero gold masks and unresolved context; notes can contain operative law.",
            "Full normalized view is retained; character/UTF8 selectors do not map raw HTML bytes.",
            "Whole DOM paragraphs can include multiple clauses or inline labels; no meaning-unit or definition completeness is inferred.",
            "This is a complete bounded input population, not a representative random sample or semantic graph.",
        ],
    }
    _need(
        len(_wire(report)) <= bounds["max_report_bytes"],
        "complete view exceeds sampling output bound; truncation refused",
    )
    if view_report["status"] == "comparison_view_extracted":
        doc = view_report["document"]
        blocks = doc["blocks"]
        _need(
            len(blocks) <= bounds["max_units"],
            "complete block population exceeds sampling bound; truncation refused",
        )
        text = doc["document_text"]
        version = sources.build_source_version(
            source_id=doc["legal_id"],
            release_id=f"govinfo-markup-v2-edition:{doc['edition']}",
            edition=str(doc["edition"]),
            provision_id=doc["legal_id"],
            raw_bytes=raw,
            expected_raw_sha256=expected_raw_sha256,
            extracted_text=text,
            expected_extracted_sha256=doc["document_text_sha256"],
            extraction_profile=views.DOCUMENT_SCHEMA,
            normalization_profile=views.NORMALIZATION_PROFILE,
            media_type="text/html",
        )
        records = [version]
        fragmented = _fragmented_paragraphs(blocks)
        withheld = {b["block_index"] for members in fragmented for b in members}
        # The view owner already bounded the input. This incremental accounting
        # refuses a too-large complete result before retaining its record list.
        used_bytes = len(_wire(report)) + len(_wire(version))
        strata = Counter()
        for block in blocks:
            occurrence, context = _source_pair(
                version, doc, expected_raw_sha256, block, block
            )
            is_withheld = block["block_index"] in withheld
            stratum = _stratum(block, is_withheld)
            unit = seal_record(
                {
                    "schema": UNIT_SCHEMA,
                    "ordinal": block["block_index"],
                    "source_version_ref": _reference(version),
                    "source_occurrence_ref": _reference(occurrence),
                    "context_ref": _reference(context),
                    "markup_block_ref": {
                        "block_id": block["block_id"],
                        "block_index": block["block_index"],
                        "sha256": _digest(block),
                    },
                    "normalized_view_id": view_report["normalized_view"]["view_id"],
                    "sampling_stratum": stratum,
                    "candidate_input": stratum == "candidate_statute_paragraph",
                    "paragraph_fragment_withheld": is_withheld,
                    "meaning_target": None,
                    "formal_outputs": [],
                    "semantic_assertions": [],
                    "training_mask": 0,
                    "evaluation_gold_mask": 0,
                    "authority": dict(AUTHORITY),
                }
            )
            triple = [occurrence, context, unit]
            reference = _reference(unit)
            used_bytes += (
                sum(len(_wire(row)) + 1 for row in triple) + len(_wire(reference)) + 1
            )
            _need(
                used_bytes <= bounds["max_report_bytes"],
                "complete sampling output byte bound exceeded; truncation refused",
            )
            records.extend(triple)
            report["unit_refs"].append(reference)
            strata[stratum] += 1
        for members in fragmented:
            occurrence, context = _source_pair(
                version, doc, expected_raw_sha256, members[0], members[-1]
            )
            retained = {
                "code": "split_or_nested_paragraph_requires_supported_assembly",
                "block_indices": [b["block_index"] for b in members],
                "source_occurrence_ref": _reference(occurrence),
                "context_ref": _reference(context),
                "candidate_input": False,
            }
            used_bytes += sum(
                len(_wire(r)) + 1 for r in (occurrence, context, retained)
            )
            _need(
                used_bytes <= bounds["max_report_bytes"],
                "complete paragraph context exceeds output bound; truncation refused",
            )
            # Identical nested parent ranges may share a physical source record.
            known = {r["record_cid"] for r in records}
            records.extend(
                r for r in (occurrence, context) if r["record_cid"] not in known
            )
            report["withheld_paragraph_contexts"].append(retained)
        report.update(
            status="whole_source_blocks_prepared",
            records=records,
            counts={
                "blocks": len(blocks),
                "units": len(blocks),
                "records": len(records),
                "strata": dict(strata),
                "region_kinds": dict(doc["region_kind_counts"]),
                "interblock_LF_separators": max(0, len(blocks) - 1),
                "withheld_fragmented_paragraphs": len(fragmented),
            },
        )
    report["sampling_report_sha256"] = _digest(report)
    _need(
        len(_wire(report)) <= bounds["max_report_bytes"],
        "complete sampling output byte bound exceeded; truncation refused",
    )
    return report


def source_sampling_report_sha256(report):
    """Full canonical report digest, including its internal payload digest."""
    _need(
        type(report) is dict and report.get("schema") == SCHEMA,
        "structured sampling report required",
    )
    bounds = _limits(report.get("limits"))
    raw = _wire(report)
    _need(
        len(raw) <= bounds["max_report_bytes"],
        "sampling report exceeds declared byte bound",
    )
    return hashlib.sha256(raw).hexdigest()


def validate_source_sampling(report, raw, *, expected_report_sha256, **trusted_inputs):
    """Replay the exact independently pinned source and complete population.

    Resealing a unit, changing zero masks or pruning/reordering controls cannot
    qualify a changed result. Validation regenerates one complete source view.
    """
    _need(
        type(expected_report_sha256) is str
        and len(expected_report_sha256) == 64
        and all(c in "0123456789abcdef" for c in expected_report_sha256),
        "independent lowercase full sampling report SHA256 required",
    )
    _need(
        source_sampling_report_sha256(report) == expected_report_sha256,
        "independent sampling report pin differs",
    )
    expected = prepare_source_sampling(raw, **trusted_inputs)
    _need(
        _wire(report) == _wire(expected),
        "sampling differs from complete independently pinned source regeneration",
    )
    return expected


__all__ = [
    "prepare_source_sampling",
    "validate_source_sampling",
    "source_sampling_report_sha256",
]
