"""Source-bound lexical nominations for the existing compact LegalIR context.

This bridge selects a caller-supplied vocabulary by exact alias occurrences. It
does not infer legal meaning, certify context exposure, or create a training
target. A nominated context still requires the existing decoder's structural
checks and independently established permission before downstream use.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
import stat
import unicodedata

CATALOG_SCHEMA = "legal-compact-source-catalog/v1"
REPORT_SCHEMA = "legal-compact-source-context/v1"
CONTEXT_OWNER_SHA256 = "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"
MAX_SOURCE_BYTES = 65536
MAX_CATALOG_BYTES = 524288
MAX_SYMBOLS = 64
MAX_FORMS = 256
MAX_MATCHES = 4096
MAX_REPORT_BYTES = 1048576
_OWNER_MODULE = "ipfs_datasets_py.logic.autoformal.legal_compact_content_v1"
_OWNER_RELATIVE = "logic/autoformal/legal_compact_content_v1.py"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).resolve()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_MATCHING_POLICY = {
    "case_sensitive": True,
    "normalization": "none",
    "word_characters": "Unicode categories L,N,M,Pc and U+200C,U+200D",
    "unicode_database_version": unicodedata.unidata_version,
    "left_boundary": "required when the alias begins with a word character",
    "right_boundary": "required when the alias ends with a word character",
    "overlapping_occurrences": "preserve all",
    "match_order": "start_byte,end_byte,form",
    "ambiguity": "observed identical form assigned to multiple predicates",
}
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_gold_qualified",
    "evaluation_gold_qualified", "Lean_admitted", "proof_authority",
    "backend_executed", "model_executed", "training_executed",
    "permitted_inference_context_verified", "target_eligibility_verified",
    "source_context_origin_verified", "context_timing_verified",
    "training_permission_verified", "inference_permission_verified",
), False)
_LIMITATIONS = [
    "Exact case-sensitive lexical aliases nominate predicates; they do not establish source semantics or legal applicability.",
    "Catalog and source origin are caller_supplied_unverified; permission, target independence and pre-inference timing are not established.",
    "All selected predicates must still occur in the output under the inherited compact grammar; nomination does not establish optimal selection or completability.",
    "Overlapping aliases are retained. Only an observed identical form assigned to multiple predicates makes the result ambiguous.",
    "No target, AST, training label, model, solver, proof, or learned semantic mapping is supplied or executed by this bridge.",
]


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _word(character):
    category = unicodedata.category(character)
    return category[0] in "LNM" or category == "Pc" or character in ("\u200c", "\u200d")


def _source_pin(path, expected):
    """Small regular-source check, also used before importing the fixed owner."""
    try:
        before = path.lstat()
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 131072,
              "bounded regular source owner required")
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise ValueError("source owner is unavailable") from error
    identity = lambda row: (row.st_dev, row.st_ino, row.st_size,
                            row.st_mtime_ns, row.st_ctime_ns)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected,
          "source owner changed or does not match its fixed SHA256")


def _owner():
    _source_pin(_SELF_PATH, _SELF_SHA)
    owner_path = None
    for parent in _SELF_PATH.parents:
        for root in (parent / "ipfs_datasets_py",
                     parent / "external/ipfs_datasets/ipfs_datasets_py"):
            candidate = root / _OWNER_RELATIVE
            if candidate.is_file():
                _need(candidate.resolve() == candidate, "canonical owner path required")
                owner_path = candidate
                break
        if owner_path is not None:
            break
    _need(owner_path is not None, "existing compact context owner unavailable")
    _source_pin(owner_path, CONTEXT_OWNER_SHA256)
    owner = importlib.import_module(_OWNER_MODULE)
    _need(type(getattr(owner, "__file__", None)) is str
          and Path(owner.__file__).resolve() == owner_path,
          "loaded compact context owner has a different source origin")
    _source_pin(owner_path, CONTEXT_OWNER_SHA256)
    return owner


def _closing(owner):
    _need(_owner() is owner, "compact context owner changed during operation")


def source_context_sha256(report):
    """Canonical bounded JSON identity only, independently usable for replay.

    This hash does not validate a report or grant semantic or use authority.
    """
    owner = _owner()
    result = hashlib.sha256(owner._wire(report, MAX_REPORT_BYTES)).hexdigest()
    _closing(owner)
    return result


def _source_text(source_raw, expected):
    _need(type(expected) is str and _SHA.fullmatch(expected) is not None,
          "independent lowercase source SHA256 required")
    _need(type(source_raw) is bytes and 0 < len(source_raw) <= MAX_SOURCE_BYTES,
          "source must be nonempty bounded exact UTF8 bytes")
    _need(hashlib.sha256(source_raw).hexdigest() == expected,
          "source raw SHA256 mismatch")
    try:
        source = source_raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("source must be strict UTF8") from error
    _need("\x00" not in source, "NUL-free source required")
    return source


def _context(owner, signature, roles):
    signature_raw = owner._wire(signature, MAX_CATALOG_BYTES)
    roles_raw = owner._wire(roles, MAX_CATALOG_BYTES)
    return owner.prepare_context_v1(
        signature_raw, roles_raw,
        expected_signature_sha256=hashlib.sha256(signature_raw).hexdigest(),
        expected_argument_roles_sha256=hashlib.sha256(roles_raw).hexdigest())


def _catalog(owner, raw, expected):
    catalog = owner._parse(raw, expected, MAX_CATALOG_BYTES, "source catalog")
    owner._keys(catalog, {"schema", "signature", "argument_roles", "aliases"},
                "source catalog")
    _need(catalog["schema"] == CATALOG_SCHEMA, "unsupported source catalog schema")
    signature = catalog["signature"]
    _need(type(signature) is dict and type(signature.get("symbols")) is list
          and 1 <= len(signature["symbols"]) <= MAX_SYMBOLS,
          "catalog requires one to 64 declared predicates")
    # Validate the entire catalog, including unused declarations and all roles,
    # through the existing public owner before selecting any subset.
    complete = _context(owner, signature, catalog["argument_roles"])
    names = [row["name"] for row in complete["signature"]["symbols"]]
    aliases = catalog["aliases"]
    _need(type(aliases) is list and len(aliases) == len(names),
          "exactly one alias row per declared predicate required")
    seen_symbols, form_symbols, count = set(), {}, 0
    for row in aliases:
        owner._keys(row, {"symbol", "forms"}, "alias row")
        symbol, forms = row["symbol"], row["forms"]
        _need(type(symbol) is str and symbol in names and symbol not in seen_symbols,
              "alias symbols must be unique declared predicates")
        _need(type(forms) is list and len(forms) > 0,
              "nonempty alias forms list required")
        seen_symbols.add(symbol)
        seen_forms = set()
        for form in forms:
            _need(type(form) is str and len(form) > 0 and not form.isspace()
                  and form not in seen_forms,
                  "nonblank exact alias strings without within-symbol duplicates required")
            seen_forms.add(form)
            count += 1
            _need(count <= MAX_FORMS, "catalog alias form bound exceeded")
            form_symbols.setdefault(form, set()).add(symbol)
    _need(seen_symbols == set(names), "every catalog predicate needs an alias row")
    return catalog, complete, names, form_symbols, count


def _matches(source, names, form_symbols):
    # Prefix geometry is constructed once; indices always refer to unnormalized
    # original Unicode scalar positions and UTF8 bytes, with exclusive ends.
    byte_offsets = [0]
    for character in source:
        byte_offsets.append(byte_offsets[-1] + len(character.encode("utf-8")))
    matches, matched_forms = [], set()
    for form, symbols in form_symbols.items():
        position = 0
        while True:
            start = source.find(form, position)
            if start < 0:
                break
            end = start + len(form)
            position = start + 1  # Preserve every overlapping occurrence.
            left_ok = (not _word(form[0]) or start == 0 or not _word(source[start - 1]))
            right_ok = (not _word(form[-1]) or end == len(source) or not _word(source[end]))
            if not (left_ok and right_ok):
                continue
            _need(len(matches) < MAX_MATCHES, "source alias match bound exceeded")
            matches.append({"form": form,
                            "symbols": [name for name in names if name in symbols],
                            "start_char": start, "end_char": end,
                            "start_byte": byte_offsets[start], "end_byte": byte_offsets[end]})
            matched_forms.add(form)
    matches.sort(key=lambda row: (row["start_byte"], row["end_byte"], row["form"]))
    # Ambiguities follow first source occurrence order, not a set iteration.
    ambiguities, seen = [], set()
    for row in matches:
        if len(row["symbols"]) > 1 and row["form"] not in seen:
            ambiguities.append({"form": row["form"], "symbols": list(row["symbols"])})
            seen.add(row["form"])
    matched_symbols = {symbol for form in matched_forms for symbol in form_symbols[form]}
    return matches, ambiguities, [name for name in names if name in matched_symbols]


def prepare_source_context_v1(source_raw, catalog_raw, *, expected_source_sha256,
                              expected_catalog_sha256):
    """Nominate a context from independently hash-bound source and catalog bytes.

    A catalog contains only schema, full existing signature, argument_roles and
    aliases. Shared matching forms are ambiguous; no matches are unavailable.
    Both outcomes retain source observations but provide no decoder context.
    Bounds are refusals, never truncation. Every authority and mask stays false
    or zero, including for a structurally valid nominated context.
    """
    owner = _owner()
    source = _source_text(source_raw, expected_source_sha256)
    catalog, complete, names, form_symbols, form_count = _catalog(
        owner, catalog_raw, expected_catalog_sha256)
    matches, ambiguities, matched = _matches(source, names, form_symbols)
    status = "ambiguous" if ambiguities else "nominated" if matches else "unavailable"
    selected = list(matched) if status == "nominated" else []
    context = None
    if selected:
        signature = {**catalog["signature"],
                     "symbols": [row for row in catalog["signature"]["symbols"]
                                 if row["name"] in selected]}
        roles = [row for row in complete["argument_roles"] if row["symbol"] in selected]
        context = _context(owner, signature, roles)
    report = {
        "schema": REPORT_SCHEMA, "status": status,
        "origin": "caller_supplied_unverified",
        "source_sha256": expected_source_sha256,
        "catalog_sha256": expected_catalog_sha256,
        "producer_sha256": _SELF_SHA, "context_owner_sha256": CONTEXT_OWNER_SHA256,
        "source_geometry": {"encoding": "UTF-8", "byte_length": len(source_raw),
                            "character_length": len(source)},
        "matching_policy": dict(_MATCHING_POLICY),
        "catalog_symbol_count": len(names), "catalog_form_count": form_count,
        "aliases": catalog["aliases"], "matches": matches,
        "matched_symbols": matched, "selected_symbols": selected,
        "index_mapping": [{"symbol": name, "catalog_index": names.index(name),
                           "selected_index": index} for index, name in enumerate(selected)],
        "excluded_symbols": [name for name in names if name not in selected],
        "context": context,
        "context_sha256": owner.compact_context_sha256(context) if context is not None else None,
        "ambiguities": ambiguities, "authority": dict(_AUTHORITY),
        "masks": {"semantic": 0, "training": 0, "inference_permission": 0},
        "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": list(_LIMITATIONS),
    }
    result = json.loads(owner._wire(report, MAX_REPORT_BYTES))
    _closing(owner)
    return result


def validate_source_context_v1(report, source_raw, catalog_raw, *,
                               expected_report_sha256, expected_source_sha256,
                               expected_catalog_sha256):
    """Check an independently supplied report hash, then replay from raw inputs.

    Every field, occurrence, offset, disposition, context and denial is compared
    to a fresh preparation. A self-consistent edited report cannot substitute
    for source/catalog replay. Input mutable JSON is captured and checked again.
    """
    owner = _owner()
    owner._hash(expected_report_sha256, "source context report")
    original = owner._wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(original).hexdigest() == expected_report_sha256,
          "source context report SHA256 mismatch")
    expected = prepare_source_context_v1(
        source_raw, catalog_raw, expected_source_sha256=expected_source_sha256,
        expected_catalog_sha256=expected_catalog_sha256)
    _need(owner._wire(expected, MAX_REPORT_BYTES) == original,
          "source context report differs from independent raw-input replay")
    _need(owner._wire(report, MAX_REPORT_BYTES) == original,
          "source context report changed during validation")
    _closing(owner)
    return expected
