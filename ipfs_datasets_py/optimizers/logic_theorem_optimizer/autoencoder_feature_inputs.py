"""Verify local semantic inputs for feature pretraining, without legal evaluation.

The historical diagnostic split remains globally ineligible. This adapter checks
its training and tuning selections only; it never opens canary JSONL or canary
source files. The existing embedding codec validates the complete receipt's
metadata, including its declared native execution profile. That declaration is
not cryptographic runtime attestation or permission to claim formalization.

Also accepts ``autoencoder-feature-inputs/v1`` with ``model``,
``embedding_production_receipt``, ``source_artifacts``, and ``artifacts``. Its
training/validation artifacts contain ``rows`` (path/SHA/bytes reference),
``count``, and ordered ``input_ids`` from the production receipt. Both schemas
use the existing receipt loader; this module does not expand its model support.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import stat
import struct
from typing import Any

from .autoencoder_embedding_production import (
    EmbeddingInput,
    load_embedding_production_receipt,
    validate_embedding_inputs,
)


SCHEMA = "autoencoder-feature-input-verification/v1"
DIAGNOSTIC_SCHEMA = "parallel-training-verified-embedding-split/v1"
INPUT_SCHEMA = "autoencoder-feature-inputs/v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 256
_SOURCE_FIELDS = ("title", "section", "citation", "text")


class FeatureInputError(ValueError):
    """Feature rows are not bound to the declared local embedding evidence."""


def _parse(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FeatureInputError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise FeatureInputError(f"nonfinite JSON value: {value}")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise FeatureInputError("invalid strict feature input JSON") from exc


def _read(path) -> tuple[bytes, dict]:
    path = Path(path).absolute()
    # Match the immutable receipt codec's regular-file contract. No network,
    # model loading, symlink following or unbounded file reads are necessary.
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_BYTES:
        raise FeatureInputError("feature artifact must be a bounded regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    after = path.lstat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise FeatureInputError("feature artifact changed during verification")
    return raw, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _reference(value) -> dict:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256", "bytes"}
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or type(value["bytes"]) is not int or not 1 <= value["bytes"] <= MAX_BYTES):
        raise FeatureInputError("invalid absolute artifact reference")
    return dict(value)


def _verified(value, *, supplied_path=None) -> tuple[bytes, dict]:
    ref = _reference(value)
    if supplied_path is not None and Path(supplied_path).absolute() != Path(ref["path"]):
        raise FeatureInputError("supplied input path differs from manifest row reference")
    raw, observed = _read(ref["path"])
    if observed != ref:
        raise FeatureInputError("artifact reference SHA-256 or byte size differs")
    return raw, observed


def _rows(raw: bytes) -> list[dict]:
    result = [_parse(line) for line in raw.splitlines() if line.strip()]
    if not 1 <= len(result) <= MAX_ROWS or any(not isinstance(row, dict) for row in result):
        raise FeatureInputError("feature JSONL must contain a bounded nonempty row list")
    return result


def _vector_bits(vector, dimension: int) -> str:
    """Compare exact finite float32 bits, including signed zero, at any dimension."""
    if type(dimension) is not int or not 1 <= dimension <= 65536:
        raise FeatureInputError("invalid semantic embedding dimension")
    if type(vector) is not list or len(vector) != dimension:
        raise FeatureInputError("semantic embedding dimension differs from model")
    parts = []
    for value in vector:
        if type(value) is not float or not math.isfinite(value):
            raise FeatureInputError("semantic vector values must be finite float32 values")
        try:
            packed = struct.pack(">f", value)
        except (OverflowError, struct.error) as exc:
            raise FeatureInputError("semantic vector value exceeds float32") from exc
        if struct.unpack(">f", packed)[0] != value:
            raise FeatureInputError("semantic vector value is not exact float32")
        parts.append(packed)
    return b"".join(parts).hex()


def _selected_ids(split, production, original) -> dict[str, list[str]]:
    if split["schema"] == INPUT_SCHEMA:
        selected = {}
        for role in ("training", "validation"):
            artifact = split["artifacts"][role]
            ids = artifact["input_ids"]
            if (type(ids) is not list or not 1 <= len(ids) <= MAX_ROWS
                    or any(not isinstance(value, str) for value in ids)
                    or type(artifact["count"]) is not int or artifact["count"] != len(ids)):
                raise FeatureInputError("invalid ordered feature input IDs")
            selected[role] = ids
        return selected

    statuses = split["statuses"]
    if (type(statuses) is not list or len(statuses) != len(production["inputs"])
            or any(item.get("role") not in {"training", "tuning", "canary"} for item in statuses)):
        raise FeatureInputError("diagnostic statuses must cover complete original selection")
    ids = [item["input_id"] for item in statuses]
    if len(set(ids)) != len(ids) or set(ids) != {item["input_id"] for item in production["inputs"]}:
        raise FeatureInputError("diagnostic status coverage differs from producer inputs")
    selected = {}
    for role in ("training", "tuning", "canary"):
        role_statuses = [item for item in statuses if item["role"] == role]
        identities = original["identities"][role]
        if len(role_statuses) != len(identities):
            raise FeatureInputError("diagnostic role identity coverage differs")
        for ordinal, (status, identity) in enumerate(zip(role_statuses, identities)):
            if (type(status["ordinal"]) is not int or status["ordinal"] != ordinal
                    or status["original_selection_preserved"] is not True
                    or any(status[key] != identity[key] for key in ("input_id", "group_id", "legal_id", "source_row_id", "text_sha256"))
                    or status["upstream_input_id"] != identity["input_id"]):
                raise FeatureInputError("diagnostic role, order or identity changed")
        # Canary identities are metadata only; do not open its rows or sources.
        if role != "canary":
            selected["validation" if role == "tuning" else role] = [item["input_id"] for item in role_statuses if item["status"] == "embedded"]
    return selected


def _verify_diagnostic_role(split, original, role, by_input, by_result) -> None:
    """Bind selected training/tuning rows and explicit oversized abstentions."""
    source_rows = _rows(_verified(original["artifacts"][role]["rows"])[0])
    statuses = [item for item in split["statuses"] if item["role"] == role]
    if len(source_rows) != len(statuses):
        raise FeatureInputError("original diagnostic source row count differs")
    embedded = 0
    for source, status in zip(source_rows, statuses):
        item, result = by_input[status["input_id"]], by_result[status["input_id"]]
        if (any(source.get(key) != item[key] for key in _SOURCE_FIELDS)
                or item["source"]["document_id"] != status["legal_id"]
                or hashlib.sha256(item["text"].encode()).hexdigest() != status["text_sha256"]
                or _verified(status["source_text_artifact"])[0] != item["text"].encode()
                or status["status"] != result["status"]):
            raise FeatureInputError("original source or producer disposition differs")
        if result["status"] == "embedded":
            embedded += 1
            if type(status.get("tokens")) is not int or status["tokens"] != len(result["tokens"]["input_ids"]):
                raise FeatureInputError("embedded token evidence differs")
        elif (role != "training" or result["status"] != "token_limit_exceeded"
              or status.get("token_evidence") != result["tokens"] or status.get("vector_absent") is not True):
            raise FeatureInputError("only explicit oversized training abstentions are allowed")
    expected = {"original_count": len(source_rows), "embedded_count": embedded,
                "abstention_count": len(source_rows) - embedded}
    artifact = split["artifacts"][role]
    if (split["coverage"][role] != expected or type(artifact["count"]) is not int
            or artifact["count"] != embedded or type(artifact["original_count"]) is not int
            or artifact["original_count"] != len(source_rows)):
        raise FeatureInputError("diagnostic coverage metadata differs")


def verify_feature_training_inputs(manifest_path, training_path, validation_path) -> dict:
    """Return bounded provenance after checking local training and tuning assets.

    No model, legal parser, autoencoder, network, or canary evaluation is invoked.
    Invalid or unsupported evidence raises ``FeatureInputError``. Global corpus
    eligibility and formal admission remain false, including for legacy splits.
    """
    try:
        return _verify_feature_training_inputs(manifest_path, training_path, validation_path)
    except FeatureInputError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        raise FeatureInputError(f"feature input verification failed: {exc}") from exc


def _verify_feature_training_inputs(manifest_path, training_path, validation_path) -> dict:
    raw, manifest_ref = _read(manifest_path)
    split = _parse(raw)
    if split["schema"] not in {INPUT_SCHEMA, DIAGNOSTIC_SCHEMA}:
        raise FeatureInputError("unsupported feature input manifest schema")
    legacy = split["schema"] == DIAGNOSTIC_SCHEMA
    if any(split.get(key, False) is not False for key in ("context_expanded", "chunked", "backfilled", "truncated", "admitted", "formalized")):
        raise FeatureInputError("unsupported transformation or qualification claim")

    receipt_ref = _reference(split["embedding_production_receipt"])
    # The existing loader checks complete receipt metadata. Do not give it a
    # resolver: that would read all sources, including the held-out canary.
    receipt = load_embedding_production_receipt(receipt_ref["path"],
        expected_sha256=receipt_ref["sha256"], expected_size_bytes=receipt_ref["bytes"])
    production = receipt.to_dict()
    if not receipt.native_execution_profile or production["model"] != split["model"]:
        raise FeatureInputError("verified native local embedding model receipt required")
    original = _parse(_verified(split["original_diagnostic_split"])[0]) if legacy else None
    by_input = {item["input_id"]: item for item in production["inputs"]}
    by_result = {item["input_id"]: item for item in production["results"]}
    selected = _selected_ids(split, production, original)
    all_ids = selected["training"] + selected["validation"]
    if not all(selected.values()) or len(all_ids) != len(set(all_ids)):
        raise FeatureInputError("training and validation selections must be nonempty and disjoint")

    if type(split["source_artifacts"]) is not list or not 1 <= len(split["source_artifacts"]) <= MAX_ROWS:
        raise FeatureInputError("source artifact reference count exceeds bound")
    source_refs = {}
    for value in split["source_artifacts"]:
        ref = _reference(value)
        if ref["sha256"] in source_refs:
            raise FeatureInputError("duplicate source artifact reference")
        source_refs[ref["sha256"]] = ref
    used_refs = {}
    def resolver(item):
        ref = source_refs[item["sha256"]]
        if ref["bytes"] != item["bytes"]:
            raise FeatureInputError("source artifact size differs from producer")
        used_refs[ref["sha256"]] = ref
        return ref["path"]

    checked = validate_embedding_inputs([EmbeddingInput.from_dict(by_input[key]) for key in all_ids], resolver=resolver)
    # Local disjointness is useful evidence, but cannot establish a global holdout.
    boundary = len(selected["training"])
    training, validation = checked[:boundary], checked[boundary:]
    documents = lambda values: {item.source.document_id for item in values}
    texts = lambda values: {" ".join(item.text.casefold().split()) for item in values}
    if documents(training) & documents(validation) or texts(training) & texts(validation):
        raise FeatureInputError("training and validation share document or normalized text")
    roles = {}
    for role, supplied in (("training", training_path), ("validation", validation_path)):
        manifest_role = "tuning" if legacy and role == "validation" else role
        artifact = split["artifacts"][manifest_role]
        row_raw, row_ref = _verified(artifact["rows"], supplied_path=supplied)
        rows = _rows(row_raw)
        if len(rows) != len(selected[role]):
            raise FeatureInputError("feature row count differs from selected producer inputs")
        if legacy:
            _verify_diagnostic_role(split, original, manifest_role, by_input, by_result)
        for row, input_id in zip(rows, selected[role]):
            item, result = by_input[input_id], by_result[input_id]
            if (set(row) != {*_SOURCE_FIELDS, "embedding_model", "embedding_vector"}
                    or any(row[key] != item[key] for key in _SOURCE_FIELDS)
                    or row["embedding_model"] != production["model"]["model_id"]
                    or result["status"] != "embedded"
                    or _vector_bits(row["embedding_vector"], production["model"]["dimension"]) != result["vector"]["bits"]):
                raise FeatureInputError("feature text, vector or model differs from verified producer receipt")
        roles[role] = {"rows": row_ref, "count": len(rows), "input_ids": selected[role]}

    return {"schema": SCHEMA, "manifest": manifest_ref, "input_schema": split["schema"],
            "training": roles["training"], "validation": roles["validation"],
            "embedding_production_receipt": receipt_ref, "model": production["model"],
            "original_diagnostic_split": split["original_diagnostic_split"] if legacy else None,
            "embedding_receipt_verification": receipt.verification_summary(),
            "source_artifacts": [used_refs[key] for key in sorted(used_refs)],
            "source_selectors_verified": len(checked), "local_embedding_verification": True,
            "selected_training_validation_disjoint": True, "canary_rows_read": False,
            "canary_evaluated": False, "global_holdout_verified": False,
            "corpus_training_eligible": False, "legacy_diagnostic_split": legacy,
            "admitted": False, "formalized": False}
