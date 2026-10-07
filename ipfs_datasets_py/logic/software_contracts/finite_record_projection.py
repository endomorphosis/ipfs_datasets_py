"""Bounded NDJSON copy/rename synthesis and independent record correspondence.

This closed data operator preserves every record, its position and all unrelated
fields.  A checker receipt describes the supplied finite byte strings only.  It
does not establish that a declaration matches natural-language intent, prove a
program correct, or authorize publication.  The caller owns reviewed intent,
path admission, immutable source capture and publication fencing.

No source is executed.  Nested containers are rejected by a nonrecursive scan
before JSON decoding.  The checker does not call the synthesizer, compare with
its serialized output, or accept a stored verdict in place of a fresh check.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import content

CONTRACT_SCHEMA = "finite-record-projection-contract@1"
CHECK_SCHEMA = "finite-record-projection-check@1"
CORRESPONDENCE_POLICY = "ordered-record-field-correspondence@1"
MAX_BYTES = 1_000_000
MAX_RECORDS = 4096
MAX_FIELDS = 128
MAX_KEY_BYTES = 256
MAX_STRING_BYTES = 16_384
MAX_LINE_BYTES = 131_072
MAX_SAFE_INTEGER = (1 << 53) - 1
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z", re.ASCII)
_SCOPE = (
    "Exact supplied finite NDJSON records under the declared field operation; "
    "no inferred intent alignment, universal program semantics, theorem proof, "
    "execution, publication or task completion authority."
)


class FiniteRecordProjectionError(ValueError):
    """Unsupported input, correspondence failure or stale receipt binding."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fail(reason: str) -> None:
    raise FiniteRecordProjectionError(reason)


def _exact_equal(value: Any, expected: Any) -> bool:
    """Compare only the finite shape of a trusted reference; reject subclasses."""
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return (all(type(key) is str for key in value)
                and value.keys() == expected.keys()
                and all(_exact_equal(value[key], item) for key, item in expected.items()))
    if type(expected) is list:
        return (len(value) == len(expected)
                and all(_exact_equal(left, right) for left, right in zip(value, expected)))
    return value == expected


@dataclass(frozen=True, slots=True)
class FiniteRecordProjectionContract:
    """An explicit operation with fixed, content-bound semantics and bounds.

    ``copy`` retains the source and adds the target. ``rename`` removes the
    source and adds the target. Both reject an absent source or existing target,
    including a target whose value is null. Record multiplicity is preserved;
    no particular field is implicitly designated a unique identifier.
    """

    mode: str
    source_field: str
    target_field: str

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in {"copy", "rename"}:
            _fail("unsupported_projection_mode")
        for field in (self.source_field, self.target_field):
            if type(field) is not str or not _FIELD.fullmatch(field):
                _fail("invalid_projection_field")
        if self.source_field == self.target_field:
            _fail("projection_fields_must_differ")

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "schema": CONTRACT_SCHEMA,
            "mode": self.mode,
            "source_field": self.source_field,
            "target_field": self.target_field,
            "correspondence_policy": CORRESPONDENCE_POLICY,
            "bounds": {
                "max_input_bytes": MAX_BYTES, "max_output_bytes": MAX_BYTES,
                "max_records": MAX_RECORDS, "max_fields_per_record": MAX_FIELDS,
                "max_key_utf8_bytes": MAX_KEY_BYTES,
                "max_string_utf8_bytes": MAX_STRING_BYTES,
                "max_line_bytes": MAX_LINE_BYTES,
                "max_integer_magnitude": MAX_SAFE_INTEGER,
            },
            "value_policy": "exact-null-bool-safe-integer-unicode-string@1",
            "record_policy": {
                "empty_input": "reject", "blank_lines": "reject",
                "duplicate_keys": "reject", "nested_containers": "reject",
                "absent_source": "reject", "existing_target": "reject",
                "unrelated_fields": "preserve", "order": "preserve",
                "cardinality": "preserve", "multiplicity": "preserve",
                "line_endings": "LF-or-CRLF-optional-final-newline",
                "object_key_order": "immaterial", "json_whitespace": "immaterial",
                "synthesis_encoding": "sorted-keys-compact-UTF8-NDJSON-final-LF",
            },
        }

    @classmethod
    def from_dict(cls, value: Any) -> FiniteRecordProjectionContract:
        if type(value) is not dict or not {"mode", "source_field", "target_field"} <= value.keys():
            _fail("invalid_projection_contract")
        contract = cls(value["mode"], value["source_field"], value["target_field"])
        if not _exact_equal(value, contract.to_dict()):
            _fail("invalid_projection_contract")
        return contract

    @property
    def cid(self) -> str:
        return content.cid_for_structured(self.to_dict())


def _contract(value: Any) -> FiniteRecordProjectionContract:
    if type(value) is not FiniteRecordProjectionContract:
        _fail("typed_projection_contract_required")
    value.__post_init__()
    return value


def _shallow_object_scan(text: str) -> None:
    """Refuse nested JSON before calling the recursive standard decoder."""
    quoted = escaped = opened = closed = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "[" or char == "]":
            _fail("nested_or_non_object_record")
        elif char == "{":
            if opened:
                _fail("nested_or_non_object_record")
            opened = True
        elif char == "}":
            if not opened or closed:
                _fail("invalid_json_record")
            closed = True
    if not opened or not closed or quoted:
        _fail("invalid_json_record")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if not 1 <= len(pairs) <= MAX_FIELDS:
        _fail("record_field_bound")
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _integer(text: str) -> int:
    if len(text.lstrip("-")) > 16:
        _fail("integer_bound")
    result = int(text)
    if abs(result) > MAX_SAFE_INTEGER:
        _fail("integer_bound")
    return result


def _non_integer(_: str) -> None:
    _fail("non_integer_number")


def _unicode_size(value: str, bound: int, reason: str) -> None:
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeError:
        _fail("non_scalar_unicode")
    if size > bound:
        _fail(reason)


def _records(raw: bytes) -> list[dict[str, Any]]:
    if type(raw) is not bytes:
        _fail("exact_bytes_required")
    if not 1 <= len(raw) <= MAX_BYTES:
        _fail("record_bytes_bound")
    # Count before split so even many tiny invalid records have bounded objects.
    count = raw.count(b"\n") + (not raw.endswith(b"\n"))
    if not 1 <= count <= MAX_RECORDS:
        _fail("record_count_bound")
    lines = raw.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    records = []
    for line in lines:
        if not 1 <= len(line) <= MAX_LINE_BYTES:
            _fail("record_line_bound")
        try:
            text = line.decode("utf-8", errors="strict")
        except UnicodeError:
            _fail("invalid_utf8")
        _shallow_object_scan(text)
        try:
            row = json.loads(text, object_pairs_hook=_pairs, parse_int=_integer,
                             parse_float=_non_integer, parse_constant=_non_integer)
        except (json.JSONDecodeError, RecursionError):
            _fail("invalid_json_record")
        if type(row) is not dict:
            _fail("nested_or_non_object_record")
        for key, value in row.items():
            _unicode_size(key, MAX_KEY_BYTES, "record_key_bound")
            if type(value) is str:
                _unicode_size(value, MAX_STRING_BYTES, "record_string_bound")
            elif value is not None and type(value) not in {bool, int}:
                _fail("non_scalar_record_value")
        records.append(row)
    return records


def _input_records(raw: bytes, contract: FiniteRecordProjectionContract) -> list[dict[str, Any]]:
    rows = _records(raw)
    for row in rows:
        if contract.source_field not in row:
            _fail("source_field_absent")
        if contract.target_field in row:
            _fail("target_field_already_present")
        if contract.mode == "copy" and len(row) == MAX_FIELDS:
            _fail("projected_record_field_bound")
    return rows


def synthesize_finite_record_projection(
    input_bytes: bytes, contract: FiniteRecordProjectionContract,
) -> bytes:
    """Return a bounded deterministic candidate; this performs no publication."""
    contract = _contract(contract)
    rows = _input_records(input_bytes, contract)
    result = bytearray()
    for row in rows:
        projected = dict(row)
        projected[contract.target_field] = row[contract.source_field]
        if contract.mode == "rename":
            del projected[contract.source_field]
        line = content.canonical_dag_json_bytes(projected) + b"\n"
        if len(line) - 1 > MAX_LINE_BYTES or len(result) + len(line) > MAX_BYTES:
            _fail("projected_record_bytes_bound")
        result.extend(line)
    return bytes(result)


def _checker_provenance() -> dict[str, Any]:
    rows = []
    for module, name in (
        (Path(__file__), "ipfs_datasets_py/logic/software_contracts/finite_record_projection.py"),
        (Path(content.__file__), "ipfs_datasets_py/logic/software_contracts/content.py"),
    ):
        try:
            with module.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except OSError:
            _fail("checker_provenance_unavailable")
        if not 1 <= len(raw) <= MAX_BYTES:
            _fail("checker_provenance_bound")
        rows.append({"module": name, "sha256": hashlib.sha256(raw).hexdigest(),
                     "source_cid": content.cid_for_bytes(raw)})
    return {
        "schema": "finite-record-native-checker@1",
        "implementation": "independent-positional-scalar-correspondence@1",
        "sources": rows,
        "identity_profile": content.PROFILE_ID,
        "dependency_scope": (
            "Exact checker and software-contract identity module source bytes; "
            "the Python runtime, standard library and multiformats dependencies "
            "are not transitively attested. The owner must pin loaded source."
        ),
    }


def check_finite_record_projection(
    input_bytes: bytes, output_bytes: bytes, contract: FiniteRecordProjectionContract,
) -> dict[str, Any]:
    """Independently check every record/field and return fully bound evidence.

    Whitespace and object-key order are immaterial to correspondence. Their
    original bytes still change the evidence identity. Record order, scalar
    types, values, multiplicity and all unrelated fields are checked exactly.
    """
    contract = _contract(contract)
    inputs = _input_records(input_bytes, contract)
    outputs = _records(output_bytes)
    if len(inputs) != len(outputs):
        _fail("record_cardinality_mismatch")
    checked_scalars = 0
    for source, target in zip(inputs, outputs):
        expected_keys = set(source)
        expected_keys.add(contract.target_field)
        if contract.mode == "rename":
            expected_keys.remove(contract.source_field)
        if set(target) != expected_keys:
            _fail("record_field_correspondence_mismatch")
        for key, actual in target.items():
            expected = source[contract.source_field if key == contract.target_field else key]
            if type(actual) is not type(expected) or actual != expected:
                _fail("record_scalar_correspondence_mismatch")
            checked_scalars += 1
    declaration = contract.to_dict()
    receipt = {
        "schema": CHECK_SCHEMA, "status": "checked", "evidence_kind": "finite_record_check",
        "correspondence_policy": CORRESPONDENCE_POLICY,
        "contract": declaration, "contract_cid": contract.cid,
        "contract_sha256": hashlib.sha256(content.canonical_dag_json_bytes(declaration)).hexdigest(),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "input_cid": content.cid_for_bytes(input_bytes), "input_size_bytes": len(input_bytes),
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "output_cid": content.cid_for_bytes(output_bytes), "output_size_bytes": len(output_bytes),
        "record_count": len(inputs), "checked_scalar_count": checked_scalars,
        "checker_provenance": _checker_provenance(), "scope": _SCOPE,
        "semantic_alignment_verified": False, "kernel_checked": False,
        "proof_authority": False, "execution_authority": False,
        "publication_authority": False, "completion_authority": False,
    }
    receipt["receipt_cid"] = content.cid_for_structured(receipt)
    return receipt


def verify_finite_record_check(
    receipt: Any, *, input_bytes: bytes, output_bytes: bytes,
    contract: FiniteRecordProjectionContract,
) -> dict[str, Any]:
    """Replay the check and require exact current bytes, declaration and checker.

    Receipts are ordinary untrusted data. No successful historical status or
    self-consistent CID can replace the fresh correspondence check.
    """
    fresh = check_finite_record_projection(input_bytes, output_bytes, contract)
    if not _exact_equal(receipt, fresh):
        _fail("finite_record_check_binding_mismatch")
    return fresh
