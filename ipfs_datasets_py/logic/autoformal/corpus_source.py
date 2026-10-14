"""Pure source, extracted-occurrence and declared-context corpus records.

Supported source inputs are one raw byte artifact and one exact Unicode text
view produced by an explicitly named extractor/normalizer. All occurrence
coordinates address that extracted view, never the raw HTML/PDF artifact.
Character selectors are Python Unicode-codepoint offsets; byte selectors are
UTF-8 offsets. Both are half-open and must identify the same nonempty slice.

The callers supply expected digests from their source-intake boundary. Seals
and digest comparisons establish byte/record integrity, not source authenticity,
legal applicability, reviewed meaning, or correctness of an extraction profile.
Historical IDs remain caller-declared aliases, including unresolved and
unsupported IDs. Context references are declarations, not verified dependencies.
"""
from __future__ import annotations

import hashlib

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

from .corpus_contracts import (
    CorpusContractError,
    clone_json,
    require_cid,
    require_cid_sha256,
    require_int,
    require_keys,
    require_sha256,
    require_text,
    seal_record,
    validate_record,
)

SOURCE_VERSION_SCHEMA = "legal-corpus-source-version/v1"
SOURCE_OCCURRENCE_SCHEMA = "legal-corpus-source-occurrence/v1"
CONTEXT_DECLARATION_SCHEMA = "legal-corpus-context-declaration/v1"
COORDINATE_SYSTEM = "extracted-unicode-codepoints-and-utf8-half-open/v1"
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_RAW_BYTES = 64 * 1024 * 1024
_VERSION_FIELDS = {
    "source_id", "release_id", "edition", "provision_id", "raw_artifact",
    "extracted_view", "historical_aliases",
}
_OCCURRENCE_FIELDS = {
    "source_version_cid", "coordinate_system", "start_char", "end_char",
    "start_utf8", "end_utf8", "span_text", "span_sha256", "span_cid",
    "historical_aliases",
}
_CONTEXT_FIELDS = {
    "source_occurrence_cid", "availability", "context_references",
    "missing_requirements", "reason", "dependency_verification",
}


def _fail(message):
    raise CorpusContractError(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _text_bytes(text, field):
    require_text(text, field, allow_empty=True, max_bytes=MAX_TEXT_BYTES)
    return text.encode("utf-8")


def _aliases(value):
    if type(value) is not list or len(value) > 4096:
        _fail("historical_aliases must be a bounded JSON list")
    seen = set()
    for alias in value:
        require_keys(alias, {"alias_id", "status", "reason"}, "historical alias")
        require_text(alias["alias_id"], "alias_id")
        require_text(alias["reason"], "alias reason")
        if alias["status"] not in ("declared_alias", "unresolved", "unsupported"):
            _fail("historical alias status is unsupported")
        if alias["alias_id"] in seen:
            _fail("historical alias IDs must be unique within a record")
        seen.add(alias["alias_id"])
    return clone_json(value)


def _artifact(binding, label):
    require_keys(binding, {"cid", "sha256", "media_type"}, label)
    require_cid_sha256(binding["cid"], binding["sha256"], label, codecs=("raw",))
    require_text(binding["media_type"], f"{label}.media_type")


def _version_shape(record):
    result = validate_record(record, schema=SOURCE_VERSION_SCHEMA, fields=_VERSION_FIELDS)
    for field in ("source_id", "release_id", "edition", "provision_id"):
        require_text(result[field], field)
    _artifact(result["raw_artifact"], "raw_artifact")
    view = result["extracted_view"]
    require_keys(view, {
        "cid", "sha256", "byte_length", "character_length", "extraction_profile",
        "normalization_profile", "coordinate_system",
    }, "extracted_view")
    require_cid_sha256(view["cid"], view["sha256"], "extracted_view", codecs=("raw",))
    for field in ("byte_length", "character_length"):
        require_int(view[field], field, minimum=0, maximum=MAX_TEXT_BYTES)
    for field in ("extraction_profile", "normalization_profile"):
        require_text(view[field], field)
    if view["coordinate_system"] != COORDINATE_SYSTEM:
        _fail("source selectors must address the declared extracted-view coordinate system")
    _aliases(result["historical_aliases"])
    return result


def build_source_version(*, source_id, release_id, edition, provision_id,
                         raw_bytes, expected_raw_sha256, extracted_text,
                         expected_extracted_sha256, extraction_profile,
                         normalization_profile, media_type,
                         historical_aliases=None):
    """Bind one exact raw artifact and extracted view to caller-declared metadata.

    Use ``normalization_profile='identity/v1'`` explicitly when no text
    normalization occurred. No raw-to-extracted offset map is inferred.
    """
    if type(raw_bytes) is not bytes or len(raw_bytes) > MAX_RAW_BYTES:
        _fail("raw_bytes must be bounded immutable bytes")
    extracted_bytes = _text_bytes(extracted_text, "extracted_text")
    require_sha256(expected_raw_sha256, "expected_raw_sha256")
    require_sha256(expected_extracted_sha256, "expected_extracted_sha256")
    if _digest(raw_bytes) != expected_raw_sha256:
        _fail("raw artifact differs from independently expected SHA256")
    if _digest(extracted_bytes) != expected_extracted_sha256:
        _fail("extracted view differs from independently expected SHA256")
    record = seal_record({
        "schema": SOURCE_VERSION_SCHEMA,
        "source_id": source_id, "release_id": release_id, "edition": edition,
        "provision_id": provision_id,
        "raw_artifact": {"cid": cid_for_bytes(raw_bytes), "sha256": expected_raw_sha256,
                         "media_type": media_type},
        "extracted_view": {
            "cid": cid_for_bytes(extracted_bytes), "sha256": expected_extracted_sha256,
            "byte_length": len(extracted_bytes), "character_length": len(extracted_text),
            "extraction_profile": extraction_profile,
            "normalization_profile": normalization_profile,
            "coordinate_system": COORDINATE_SYSTEM,
        },
        "historical_aliases": [] if historical_aliases is None else historical_aliases,
    })
    return validate_source_version(record, expected_raw_sha256=expected_raw_sha256,
        extracted_text=extracted_text, expected_extracted_sha256=expected_extracted_sha256,
        raw_bytes=raw_bytes)


def validate_source_version(record, *, expected_raw_sha256, extracted_text,
                            expected_extracted_sha256, raw_bytes=None):
    """Validate a seal and independently expected bytes; raw retrieval is optional.

    Without raw bytes this checks its CID/SHA pair and external digest binding,
    not availability of that raw artifact. Extracted text is always required.
    """
    result = _version_shape(record)
    require_sha256(expected_raw_sha256, "expected_raw_sha256")
    require_sha256(expected_extracted_sha256, "expected_extracted_sha256")
    view = result["extracted_view"]
    encoded = _text_bytes(extracted_text, "extracted_text")
    if result["raw_artifact"]["sha256"] != expected_raw_sha256:
        _fail("raw artifact does not match independently expected SHA256")
    if (view["sha256"] != expected_extracted_sha256
            or _digest(encoded) != expected_extracted_sha256
            or cid_for_bytes(encoded) != view["cid"]
            or len(encoded) != view["byte_length"]
            or len(extracted_text) != view["character_length"]):
        _fail("extracted text/hash/CID/length binding is stale or inconsistent")
    if raw_bytes is not None:
        if type(raw_bytes) is not bytes or len(raw_bytes) > MAX_RAW_BYTES:
            _fail("raw_bytes must be bounded immutable bytes")
        if (_digest(raw_bytes) != expected_raw_sha256
                or cid_for_bytes(raw_bytes) != result["raw_artifact"]["cid"]):
            _fail("raw artifact bytes do not match expected binding")
    return result


def _occurrence_shape(record):
    result = validate_record(record, schema=SOURCE_OCCURRENCE_SCHEMA, fields=_OCCURRENCE_FIELDS)
    require_cid(result["source_version_cid"], "source_version_cid", codecs=("dag-json",))
    if result["coordinate_system"] != COORDINATE_SYSTEM:
        _fail("occurrence coordinates must address the extracted view")
    for field in ("start_char", "end_char", "start_utf8", "end_utf8"):
        require_int(result[field], field, minimum=0, maximum=MAX_TEXT_BYTES)
    if result["start_char"] >= result["end_char"] or result["start_utf8"] >= result["end_utf8"]:
        _fail("source occurrence must be a nonempty half-open interval")
    encoded = _text_bytes(result["span_text"], "span_text")
    require_sha256(result["span_sha256"], "span_sha256")
    require_cid(result["span_cid"], "span_cid", codecs=("raw",))
    if (_digest(encoded) != result["span_sha256"] or cid_for_bytes(encoded) != result["span_cid"]
            or len(result["span_text"]) != result["end_char"] - result["start_char"]
            or len(encoded) != result["end_utf8"] - result["start_utf8"]):
        _fail("occurrence text/hash/CID/selector lengths disagree")
    _aliases(result["historical_aliases"])
    return result


def build_source_occurrence(source_version, *, expected_raw_sha256, extracted_text,
                            expected_extracted_sha256, start_char, end_char,
                            start_utf8, end_utf8, historical_aliases=None):
    """Create a source-bound occurrence without matching by literal text search."""
    parent = validate_source_version(source_version, expected_raw_sha256=expected_raw_sha256,
        extracted_text=extracted_text, expected_extracted_sha256=expected_extracted_sha256)
    for field, value in (("start_char", start_char), ("end_char", end_char),
                         ("start_utf8", start_utf8), ("end_utf8", end_utf8)):
        require_int(value, field, minimum=0, maximum=MAX_TEXT_BYTES)
    encoded = extracted_text[start_char:end_char].encode("utf-8")
    record = seal_record({
        "schema": SOURCE_OCCURRENCE_SCHEMA, "source_version_cid": parent["record_cid"],
        "coordinate_system": COORDINATE_SYSTEM, "start_char": start_char,
        "end_char": end_char, "start_utf8": start_utf8, "end_utf8": end_utf8,
        "span_text": extracted_text[start_char:end_char], "span_sha256": _digest(encoded),
        "span_cid": cid_for_bytes(encoded),
        "historical_aliases": [] if historical_aliases is None else historical_aliases,
    })
    return validate_source_occurrence(record, source_version=parent,
        expected_raw_sha256=expected_raw_sha256, extracted_text=extracted_text,
        expected_extracted_sha256=expected_extracted_sha256)


def validate_source_occurrence(record, *, source_version, expected_raw_sha256,
                               extracted_text, expected_extracted_sha256):
    """Validate both record seals and exact character/UTF8 geometry against text."""
    result = _occurrence_shape(record)
    parent = validate_source_version(source_version, expected_raw_sha256=expected_raw_sha256,
        extracted_text=extracted_text, expected_extracted_sha256=expected_extracted_sha256)
    if result["source_version_cid"] != parent["record_cid"]:
        _fail("source occurrence belongs to a different source version")
    start, end = result["start_char"], result["end_char"]
    if (end > len(extracted_text) or extracted_text[start:end] != result["span_text"]
            or len(extracted_text[:start].encode("utf-8")) != result["start_utf8"]
            or len(extracted_text[:end].encode("utf-8")) != result["end_utf8"]):
        _fail("source occurrence selectors do not bind the exact extracted text")
    return result


def _context_shape(record):
    result = validate_record(record, schema=CONTEXT_DECLARATION_SCHEMA, fields=_CONTEXT_FIELDS)
    require_cid(result["source_occurrence_cid"], "source_occurrence_cid", codecs=("dag-json",))
    require_text(result["reason"], "context reason")
    if result["dependency_verification"] != "declaration_only":
        _fail("context declarations cannot claim authenticated dependencies")
    references = result["context_references"]
    if type(references) is not list or len(references) > 256:
        _fail("context_references must be a bounded JSON list")
    seen = set()
    for reference in references:
        require_keys(reference, {"record_cid", "record_kind", "purpose"}, "context reference")
        require_cid(reference["record_cid"], "context reference CID", codecs=("dag-json",))
        require_text(reference["purpose"], "context reference purpose")
        if reference["record_kind"] not in ("source_version", "source_occurrence"):
            _fail("unsupported context reference kind")
        identity = (reference["record_cid"], reference["record_kind"], reference["purpose"])
        if identity in seen:
            _fail("duplicate context reference declaration")
        seen.add(identity)
    missing = result["missing_requirements"]
    if type(missing) is not list or len(missing) > 256:
        _fail("missing_requirements must be a bounded JSON list")
    for item in missing:
        require_text(item, "missing context requirement")
    if len(set(missing)) != len(missing):
        _fail("missing context requirements must be unique")
    availability = result["availability"]
    if availability == "none_required":
        if references or missing:
            _fail("none_required cannot include context references or missing requirements")
    elif availability == "declared_context":
        if not references or missing:
            _fail("declared_context requires references and no missing requirements")
    elif availability == "required_unavailable":
        if not missing:
            _fail("required_unavailable requires explicit missing requirements")
    else:
        _fail("unsupported context availability declaration")
    return result


def build_context_declaration(source_occurrence, *, expected_occurrence_cid,
                              availability, reason, context_references=None,
                              missing_requirements=None):
    """Record a caller's context declaration, without guessing or resolving refs.

    The target seal and expected target identity are verified. Source-byte
    qualification remains the separate ``validate_source_occurrence`` operation.
    Referenced records are not fetched or authenticated by this API.
    """
    target = _occurrence_shape(source_occurrence)
    require_cid(expected_occurrence_cid, "expected_occurrence_cid", codecs=("dag-json",))
    if target["record_cid"] != expected_occurrence_cid:
        _fail("context target differs from independently expected occurrence CID")
    record = seal_record({
        "schema": CONTEXT_DECLARATION_SCHEMA,
        "source_occurrence_cid": target["record_cid"], "availability": availability,
        "context_references": [] if context_references is None else context_references,
        "missing_requirements": [] if missing_requirements is None else missing_requirements,
        "reason": reason, "dependency_verification": "declaration_only",
    })
    return validate_context_declaration(record, source_occurrence=target,
        expected_occurrence_cid=expected_occurrence_cid)


def validate_context_declaration(record, *, source_occurrence, expected_occurrence_cid):
    """Validate declared context custody; do not assert dependency authenticity."""
    result = _context_shape(record)
    target = _occurrence_shape(source_occurrence)
    require_cid(expected_occurrence_cid, "expected_occurrence_cid", codecs=("dag-json",))
    if (target["record_cid"] != expected_occurrence_cid
            or result["source_occurrence_cid"] != expected_occurrence_cid):
        _fail("context declaration binds a different occurrence")
    return result


__all__ = [
    "SOURCE_VERSION_SCHEMA", "SOURCE_OCCURRENCE_SCHEMA", "CONTEXT_DECLARATION_SCHEMA",
    "COORDINATE_SYSTEM", "build_source_version", "validate_source_version",
    "build_source_occurrence", "validate_source_occurrence",
    "build_context_declaration", "validate_context_declaration",
]
