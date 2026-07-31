"""Software-contract CIDv1 content identity (CID profile v1).

This module is the sole owner of the software-contract content-addressing
profile used by symbolic contract analysis (DSCON-G040). It adapts the strict
encoding path from ``ipfs_datasets_py.utils.cid_utils`` and deliberately does
**not** copy permissive helpers such as ``canonical_json_bytes`` (which applies
``default=repr``) or floating-point DAG-JSON values.

Domain separation:

* **Source bytes** use CIDv1 / lowercase base32 / ``raw`` / ``sha2-256``.
* **Structured analysis artifacts** use CIDv1 / lowercase base32 /
  ``dag-json`` / ``sha2-256`` over the strict canonical encoding defined here.

Structured identity accepts only reviewed JSON/IPLD scalar and container types
(``null``, ``bool``, ``int``, ``str``, ``list``, ``dict`` with string keys).
It rejects floats, bytes, sets, paths, NaN/infinity, host objects, and any
repr-based fallback.

Every read path must call :func:`decode_and_recompute_source` or
:func:`decode_and_recompute_structured` so identity is verified by recomputing
the CID rather than trusting a stored string alone.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Final, Iterable

# ---------------------------------------------------------------------------
# Profile constants (normative; mirrored in CID_PROFILE_V1.md)
# ---------------------------------------------------------------------------

PROFILE_ID: Final[str] = "software-contract-cid-profile-v1"
PROFILE_VERSION: Final[str] = "1.0.0"
PROFILE_DOC: Final[str] = "CID_PROFILE_V1.md"

CID_VERSION: Final[int] = 1
CID_BASE: Final[str] = "base32"
MULTIHASH_TYPE: Final[str] = "sha2-256"
SOURCE_CODEC: Final[str] = "raw"
STRUCTURED_CODEC: Final[str] = "dag-json"

# Durable golden-vector fixture path relative to the ipfs_datasets_py package
# root (the directory that contains ``docs/`` and ``tests/``).
CID_VECTORS_FIXTURE_RELPATH: Final[str] = (
    "tests/fixtures/software_contracts/cid_vectors.json"
)

_ALLOWED_SOURCE_CODECS: Final[frozenset[str]] = frozenset({SOURCE_CODEC})
_ALLOWED_STRUCTURED_CODECS: Final[frozenset[str]] = frozenset(
    {STRUCTURED_CODEC}
)
_ALLOWED_READ_CODECS: Final[frozenset[str]] = frozenset(
    {SOURCE_CODEC, STRUCTURED_CODEC}
)

class ContentIdentityError(ValueError):
    """Raised when content fails the software-contract CID profile."""


class StructuredIdentityError(ContentIdentityError, TypeError):
    """Raised when a value is not a reviewed structured-identity type."""


def profile_descriptor() -> dict[str, Any]:
    """Return the machine-readable CID profile identity for receipts."""

    return {
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "profile_doc": PROFILE_DOC,
        "cid_version": CID_VERSION,
        "base": CID_BASE,
        "multihash": MULTIHASH_TYPE,
        "source_codec": SOURCE_CODEC,
        "structured_codec": STRUCTURED_CODEC,
        "structured_accepted_types": [
            "null",
            "bool",
            "int",
            "str",
            "list",
            "map(str -> value)",
        ],
        "structured_rejected_types": [
            "float",
            "bytes",
            "bytearray",
            "memoryview",
            "set",
            "frozenset",
            "tuple",
            "path",
            "complex",
            "host_object",
            "nan",
            "infinity",
            "repr_fallback",
        ],
        "cid_vectors_fixture": CID_VECTORS_FIXTURE_RELPATH,
    }


def _require_bytes(data: Any, *, path: str = "data") -> bytes:
    if type(data) is not bytes:
        raise TypeError(f"{path} must be exact bytes, got {type(data).__name__}")
    return data


def validate_structured_value(value: Any, *, path: str = "$") -> None:
    """Require one reviewed structured-identity value recursively.

    Accepted types: ``None``, ``bool``, ``int`` (non-bool), ``str``, ``list``,
    and ``dict`` with exclusively ``str`` keys.  Floats (including finite
    floats), bytes, sets, tuples, paths, host objects, and any other type are
    rejected.  Non-finite numbers are impossible for ``int``; the float check
    is kept for clear error messages if a float slips through.
    """

    value_type = type(value)

    if value is None or value_type is str:
        return

    if value_type is bool:
        return

    if value_type is int:
        # Reject bool masquerading if called with a subclass; bool is handled.
        return

    if value_type is float:
        if not math.isfinite(value):
            raise StructuredIdentityError(
                f"{path} rejects non-finite float ({value!r})"
            )
        raise StructuredIdentityError(
            f"{path} rejects float; use int or encode as a reviewed string"
        )

    if value_type is list:
        for index, item in enumerate(value):
            validate_structured_value(item, path=f"{path}[{index}]")
        return

    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise StructuredIdentityError(
                    f"{path} map keys must be str, got {type(key).__name__}"
                )
            validate_structured_value(item, path=f"{path}.{key}")
        return

    # Explicit high-signal rejections (also covered by the generic branch).
    if value_type in {bytes, bytearray, memoryview}:
        raise StructuredIdentityError(
            f"{path} rejects binary types; use source-byte identity instead"
        )
    if value_type in {set, frozenset, tuple}:
        raise StructuredIdentityError(
            f"{path} rejects {value_type.__name__}; use list or map"
        )
    if isinstance(value, Path):
        raise StructuredIdentityError(
            f"{path} rejects Path host objects; use a string path or CID"
        )

    raise StructuredIdentityError(
        f"{path} is not a reviewed structured-identity type: "
        f"{value_type.__name__}"
    )


def canonical_dag_json_bytes(obj: Any) -> bytes:
    """Serialize a structured value to deterministic UTF-8 DAG-JSON bytes.

    Rules:

    * fail closed on unreviewed types (no ``default=`` / repr fallback);
    * sort object keys lexicographically by Unicode code point;
    * compact separators ``(",", ":")``;
    * ``ensure_ascii=False`` so non-ASCII strings are UTF-8 in the byte stream
      (compatible with JS ``JSON.stringify`` after key sorting);
    * ``allow_nan=False`` (defense in depth; floats are already rejected).
    """

    validate_structured_value(obj)
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def _cid_from_digest_bytes(
    data: bytes,
    *,
    codec: str,
) -> str:
    from multiformats import CID, multihash

    if codec not in _ALLOWED_READ_CODECS:
        raise ContentIdentityError(
            f"codec {codec!r} is outside the software-contract CID profile"
        )
    digest = multihash.digest(data, MULTIHASH_TYPE)
    return str(CID(CID_BASE, CID_VERSION, codec, digest))


def cid_for_bytes(data: bytes) -> str:
    """Return the source-byte CIDv1 (raw / sha2-256 / base32)."""

    payload = _require_bytes(data)
    return _cid_from_digest_bytes(payload, codec=SOURCE_CODEC)


def cid_for_obj(obj: Any) -> str:
    """Return the structured CIDv1 (dag-json / sha2-256 / base32).

    Alias of the structured path; named ``cid_for_obj`` for AST/symbol parity
    with existing content-identity call sites and the objective AST query.
    """

    return cid_for_structured(obj)


def cid_for_structured(obj: Any) -> str:
    """Return the structured-artifact CIDv1 for a reviewed value."""

    return _cid_from_digest_bytes(
        canonical_dag_json_bytes(obj),
        codec=STRUCTURED_CODEC,
    )


def validate_cid(
    value: Any,
    *,
    codecs: Iterable[str] | None = None,
) -> str:
    """Validate and return one canonical lowercase profile CID string."""

    if not isinstance(value, str) or not value:
        raise ContentIdentityError("CID must be a nonempty string")
    if value != value.lower():
        raise ContentIdentityError("CID must be lowercase (canonical base32)")

    allowed = frozenset(codecs) if codecs is not None else _ALLOWED_READ_CODECS
    if not allowed or not allowed.issubset(_ALLOWED_READ_CODECS):
        raise ContentIdentityError(
            "CID validation codecs must be a non-empty subset of "
            f"{sorted(_ALLOWED_READ_CODECS)}"
        )

    from multiformats import CID, multihash

    try:
        parsed = CID.decode(value)
    except Exception as exc:  # multiformats raises varied errors
        raise ContentIdentityError("CID is not decodable") from exc

    expected_digest_size = multihash.get(MULTIHASH_TYPE).max_digest_size
    if (
        parsed.version != CID_VERSION
        or parsed.codec.name not in allowed
        or parsed.hashfun.name != MULTIHASH_TYPE
        or (
            expected_digest_size is not None
            and len(parsed.raw_digest) != expected_digest_size
        )
        or parsed.base.name != CID_BASE
        or str(parsed) != value
    ):
        raise ContentIdentityError(
            "CID must use CIDv1 / base32 / sha2-256 and an allowed codec "
            f"from {sorted(allowed)}"
        )
    return value


def decode_and_recompute_source(claimed_cid: str, data: bytes) -> str:
    """Verify source bytes against a claimed CID by decode-and-recompute.

    Validates the claimed CID under the source (raw) codec, recomputes the CID
    from ``data``, and requires an exact match.  Returns the canonical CID.
    """

    canonical_claim = validate_cid(claimed_cid, codecs=_ALLOWED_SOURCE_CODECS)
    recomputed = cid_for_bytes(data)
    if recomputed != canonical_claim:
        raise ContentIdentityError(
            "source CID does not match recomputed identity: "
            f"claimed={canonical_claim} recomputed={recomputed}"
        )
    return recomputed


def decode_and_recompute_structured(claimed_cid: str, obj: Any) -> str:
    """Verify a structured value against a claimed CID by decode-and-recompute.

    Validates the claimed CID under the structured (dag-json) codec, recomputes
    the CID from the canonical encoding of ``obj``, and requires an exact
    match.  Returns the canonical CID.
    """

    canonical_claim = validate_cid(
        claimed_cid,
        codecs=_ALLOWED_STRUCTURED_CODECS,
    )
    recomputed = cid_for_structured(obj)
    if recomputed != canonical_claim:
        raise ContentIdentityError(
            "structured CID does not match recomputed identity: "
            f"claimed={canonical_claim} recomputed={recomputed}"
        )
    return recomputed


def verify_source_read(claimed_cid: str, data: bytes) -> bytes:
    """Read-path helper: recompute source identity, then return the bytes."""

    decode_and_recompute_source(claimed_cid, data)
    return data


def verify_structured_read(claimed_cid: str, obj: Any) -> Any:
    """Read-path helper: recompute structured identity, then return the value."""

    decode_and_recompute_structured(claimed_cid, obj)
    return obj


def cid_vectors_document() -> dict[str, Any]:
    """Build the normative golden-vector document for cross-runtime parity.

    This is the authoritative payload for
    ``tests/fixtures/software_contracts/cid_vectors.json``.  Python unit tests
    and any JavaScript consumer must produce the same ``expected_cid`` values
    for each case.  Vectors are computed live from the profile implementation
    so the document cannot drift from the encoder.
    """

    source_cases: list[dict[str, Any]] = [
        {
            "id": "source.empty",
            "description": "Empty source blob",
            "bytes_hex": "",
        },
        {
            "id": "source.hello",
            "description": "ASCII hello",
            "bytes_hex": b"hello".hex(),
        },
        {
            "id": "source.unicode_utf8",
            "description": "UTF-8 café bytes",
            "bytes_hex": "café".encode("utf-8").hex(),
        },
        {
            "id": "source.binary_null",
            "description": "Binary with embedded NUL",
            "bytes_hex": b"a\x00b\xff".hex(),
        },
    ]

    structured_inputs: list[tuple[str, str, Any]] = [
        ("structured.null", "JSON null", None),
        ("structured.bool_true", "JSON true", True),
        ("structured.bool_false", "JSON false", False),
        ("structured.int_zero", "Integer zero", 0),
        ("structured.int_neg", "Negative integer", -42),
        ("structured.empty_list", "Empty list", []),
        ("structured.empty_map", "Empty map", {}),
        (
            "structured.simple_map",
            "Map with lexicographic key order",
            {"b": 1, "a": 2},
        ),
        (
            "structured.key_order_independent",
            "Same map written with opposite key insertion order",
            {"a": 2, "b": 1},
        ),
        (
            "structured.nested_unicode",
            "Nested map/list with non-ASCII string",
            {"z": {"y": [1, "x", None, True]}, "a": "unicode-café"},
        ),
        (
            "structured.list_mixed",
            "Heterogeneous reviewed list",
            [None, False, True, 0, 1, "s", [], {}],
        ),
    ]

    source_vectors: list[dict[str, Any]] = []
    for case in source_cases:
        data = bytes.fromhex(case["bytes_hex"])
        expected = cid_for_bytes(data)
        source_vectors.append(
            {
                "id": case["id"],
                "description": case["description"],
                "domain": "source",
                "codec": SOURCE_CODEC,
                "multihash": MULTIHASH_TYPE,
                "base": CID_BASE,
                "version": CID_VERSION,
                "bytes_hex": case["bytes_hex"],
                "expected_cid": expected,
                "python": {"api": "cid_for_bytes"},
                "javascript": {
                    "api": "cidForBytes",
                    "note": (
                        "Hash the exact byte sequence; do not UTF-8 round-trip "
                        "binary payloads."
                    ),
                },
            }
        )

    structured_vectors: list[dict[str, Any]] = []
    for case_id, description, value in structured_inputs:
        encoded = canonical_dag_json_bytes(value)
        expected = cid_for_structured(value)
        structured_vectors.append(
            {
                "id": case_id,
                "description": description,
                "domain": "structured",
                "codec": STRUCTURED_CODEC,
                "multihash": MULTIHASH_TYPE,
                "base": CID_BASE,
                "version": CID_VERSION,
                "value": value,
                "canonical_utf8": encoded.decode("utf-8"),
                "canonical_hex": encoded.hex(),
                "expected_cid": expected,
                "python": {"api": "cid_for_obj"},
                "javascript": {
                    "api": "cidForObj",
                    "canonicalization": (
                        "JSON.stringify with recursively sorted object keys, "
                        "no whitespace, UTF-8 bytes (not ASCII-escaped), then "
                        "CIDv1 dag-json sha2-256 base32"
                    ),
                },
            }
        )

    # Key-order independence: both insertion orders must share one CID.
    simple_cids = {
        item["expected_cid"]
        for item in structured_vectors
        if item["id"]
        in {
            "structured.simple_map",
            "structured.key_order_independent",
        }
    }
    if len(simple_cids) != 1:
        raise RuntimeError(
            "profile invariant broken: key order must not affect structured CID"
        )

    return {
        "schema": "ipfs-datasets.software-contract-cid-vectors.v1",
        "profile": profile_descriptor(),
        "notes": [
            (
                "Python and JavaScript must produce identical expected_cid "
                "values for every case."
            ),
            (
                "Structured identity rejects floats, bytes, sets, paths, "
                "NaN, host objects, and repr fallbacks."
            ),
            (
                "Every consumer read must decode-and-recompute: compare the "
                "claimed CID to cid_for_bytes / cid_for_obj over the payload."
            ),
        ],
        "vectors": source_vectors + structured_vectors,
    }


def load_cid_vectors(
    fixture_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load golden vectors from the fixture path, or build them if absent.

    When ``fixture_path`` exists it is the durable authority and must match the
    live :func:`cid_vectors_document` payload (byte-identical JSON after
    canonical dump).  When absent, the live document is returned so unit tests
    remain hermetic before the fixture file is materialized.
    """

    live = cid_vectors_document()
    if fixture_path is None:
        return live

    path = Path(fixture_path)
    if not path.is_file():
        return live

    loaded = json.loads(path.read_text(encoding="utf-8"))
    live_bytes = canonical_dag_json_bytes(live)
    loaded_bytes = canonical_dag_json_bytes(loaded)
    if loaded_bytes != live_bytes:
        raise ContentIdentityError(
            f"cid vectors fixture {path} does not match the live CID profile "
            f"encoder (fixture_cid={cid_for_bytes(loaded_bytes)} "
            f"live_cid={cid_for_bytes(live_bytes)})"
        )
    return loaded


def materialize_cid_vectors_fixture(package_root: Path | str) -> Path:
    """Write the golden-vector fixture under an ipfs_datasets_py package root.

    Intended for maintainers and optional test bootstrap.  Implementation tasks
    with exact edit allow-lists may keep vectors embedded via
    :func:`cid_vectors_document` until the fixture path is writable.
    """

    root = Path(package_root)
    target = root / CID_VECTORS_FIXTURE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    document = cid_vectors_document()
    # Stable on-disk encoding matches structured identity (sorted keys, UTF-8).
    payload = canonical_dag_json_bytes(document).decode("utf-8") + "\n"
    target.write_text(payload, encoding="utf-8")
    return target


__all__ = [
    "CID_BASE",
    "CID_VECTORS_FIXTURE_RELPATH",
    "CID_VERSION",
    "ContentIdentityError",
    "MULTIHASH_TYPE",
    "PROFILE_DOC",
    "PROFILE_ID",
    "PROFILE_VERSION",
    "SOURCE_CODEC",
    "STRUCTURED_CODEC",
    "StructuredIdentityError",
    "canonical_dag_json_bytes",
    "cid_for_bytes",
    "cid_for_obj",
    "cid_for_structured",
    "cid_vectors_document",
    "decode_and_recompute_source",
    "decode_and_recompute_structured",
    "load_cid_vectors",
    "materialize_cid_vectors_fixture",
    "profile_descriptor",
    "validate_cid",
    "validate_structured_value",
    "verify_source_read",
    "verify_structured_read",
]
