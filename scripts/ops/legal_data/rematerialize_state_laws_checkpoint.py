#!/usr/bin/env python3
"""Rematerialize one completed state-law scrape checkpoint without network I/O.

This command is deliberately narrower than ``refresh_state_laws_corpus.py``:
it accepts exactly one ``scrape_all:complete`` partial checkpoint, validates
the checkpoint's jurisdiction and closed progress counters, structurally
filters unusable rows, and writes the scraper's standard per-state JSON-LD.
It never scrapes, uploads, publishes, or merges an older corpus.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import (
    get_canonical_legal_corpus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    assess_text_quality,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    _fixture_reasons as _legacy_fixture_reasons,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    _row_source_url as _legacy_row_source_url,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    validate_jurisdiction,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    US_STATES,
    _has_quality_legal_signal,
    _is_scaffold_or_navigation_record,
    _write_state_jsonld_files,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_staging,
    atomic_write_canonical_json,
    confine_path,
    file_digest,
    resolve_release_root,
)

RECEIPT_SCHEMA_VERSION = (
    "ipfs_datasets_py.state_laws.checkpoint_rematerialization_receipt.v1"
)
JSONLD_SCHEMA_VERSION = "ipfs_datasets_py.state_laws.refresh_jsonld.v1"
FILTER_POLICY_VERSION = (
    "structural_nonempty_non_scaffold_non_navigation_non_placeholder.v1"
)
MINIMUM_TEXT_CHARACTERS = 1
JSONLD_DIR_NAME = get_canonical_legal_corpus("state_laws").jsonld_dir_name


class CheckpointRematerializationError(RuntimeError):
    """A checkpoint or staged artifact failed closed validation."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _mapping_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _load_json_object(path: Path, *, noun: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            payload = json.load(
                handle,
                object_pairs_hook=_mapping_without_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CheckpointRematerializationError(
            f"cannot parse {noun} as strict JSON: {path}"
        ) from exc
    if type(payload) is not dict:
        raise CheckpointRematerializationError(f"{noun} root must be a JSON object")
    return payload


def _require_exact_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CheckpointRematerializationError(
            f"checkpoint {field} must be an integer >= {minimum}"
        )
    return value


def _validate_updated_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise CheckpointRematerializationError("checkpoint updated_at is required")
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise CheckpointRematerializationError(
            "checkpoint updated_at must be an ISO-8601 timestamp"
        ) from exc
    return text


def _validate_checkpoint(
    payload: Mapping[str, Any],
    *,
    checkpoint_path: Path,
    jurisdiction: str,
) -> tuple[str, list[dict[str, Any]], dict[str, int], str]:
    expected_name = f"STATE-{jurisdiction}-partial.json"
    if checkpoint_path.name != expected_name:
        raise CheckpointRematerializationError(
            f"checkpoint filename mismatch: expected {expected_name!r}, "
            f"observed {checkpoint_path.name!r}"
        )
    if payload.get("stage_label") != "scrape_all:complete":
        raise CheckpointRematerializationError(
            "checkpoint stage_label must be exactly 'scrape_all:complete'"
        )
    if payload.get("code_name") != "scrape_all":
        raise CheckpointRematerializationError(
            "checkpoint code_name must be exactly 'scrape_all'"
        )
    if payload.get("state_code") != jurisdiction:
        raise CheckpointRematerializationError(
            f"checkpoint state_code mismatch for {jurisdiction}"
        )

    expected_state_name = str(US_STATES[jurisdiction])
    if payload.get("state_name") != expected_state_name:
        raise CheckpointRematerializationError(
            f"checkpoint state_name mismatch for {jurisdiction}: "
            f"expected {expected_state_name!r}"
        )

    progress = payload.get("progress")
    if type(progress) is not dict:
        raise CheckpointRematerializationError("checkpoint progress must be an object")
    codes_completed = _require_exact_int(
        progress.get("codes_completed"), field="progress.codes_completed"
    )
    codes_total = _require_exact_int(
        progress.get("codes_total"), field="progress.codes_total", minimum=1
    )
    latest_code_statutes_raw = progress.get("latest_code_statutes")
    latest_code_statutes = (
        _require_exact_int(
            latest_code_statutes_raw,
            field="progress.latest_code_statutes",
        )
        if latest_code_statutes_raw is not None
        else None
    )
    if codes_completed != codes_total:
        raise CheckpointRematerializationError(
            "checkpoint progress is not closed: "
            f"codes_completed={codes_completed}, codes_total={codes_total}"
        )

    statutes = payload.get("statutes")
    if type(statutes) is not list:
        raise CheckpointRematerializationError("checkpoint statutes must be an array")
    statutes_count = _require_exact_int(
        payload.get("statutes_count"), field="statutes_count"
    )
    if statutes_count != len(statutes):
        raise CheckpointRematerializationError(
            "checkpoint statutes_count does not match the statutes array: "
            f"declared={statutes_count}, observed={len(statutes)}"
        )
    if statutes_count == 0:
        raise CheckpointRematerializationError(
            "checkpoint contains zero statutes and cannot be rematerialized"
        )
    if (
        codes_total == 1
        and latest_code_statutes is not None
        and statutes_count != latest_code_statutes
    ):
        raise CheckpointRematerializationError(
            "checkpoint row snapshot does not match the completed single-code "
            "result: "
            f"statutes_count={statutes_count}, "
            f"progress.latest_code_statutes={latest_code_statutes}"
        )

    checked_statutes: list[dict[str, Any]] = []
    for index, statute in enumerate(statutes):
        if type(statute) is not dict:
            raise CheckpointRematerializationError(
                f"checkpoint statutes[{index}] must be an object"
            )
        if statute.get("state_code") != jurisdiction:
            raise CheckpointRematerializationError(
                f"checkpoint statutes[{index}].state_code mismatch for {jurisdiction}"
            )
        if statute.get("state_name") != expected_state_name:
            raise CheckpointRematerializationError(
                f"checkpoint statutes[{index}].state_name mismatch for {jurisdiction}"
            )
        structured_data = statute.get("structured_data")
        if structured_data is not None and type(structured_data) is not dict:
            raise CheckpointRematerializationError(
                f"checkpoint statutes[{index}].structured_data must be an object or null"
            )
        if isinstance(structured_data, Mapping):
            embedded = structured_data.get("jsonld")
            if embedded is not None and type(embedded) is not dict:
                raise CheckpointRematerializationError(
                    f"checkpoint statutes[{index}].structured_data.jsonld must be an object"
                )
            if isinstance(embedded, Mapping):
                embedded_state = str(embedded.get("stateCode") or "").strip().upper()
                if embedded_state and embedded_state != jurisdiction:
                    raise CheckpointRematerializationError(
                        f"checkpoint statutes[{index}] embedded JSON-LD state mismatch"
                    )
        checked_statutes.append(statute)

    updated_at = _validate_updated_at(payload.get("updated_at"))
    return (
        expected_state_name,
        checked_statutes,
        {
            "codes_completed": codes_completed,
            "codes_total": codes_total,
            **(
                {"latest_code_statutes": latest_code_statutes}
                if latest_code_statutes is not None
                else {}
            ),
        },
        updated_at,
    )


def _structural_rejection_reasons(
    statute: Mapping[str, Any],
    *,
    checkpoint_path: Path,
) -> tuple[str, ...]:
    reasons: list[str] = []
    text_value = statute.get("full_text")
    if not isinstance(text_value, str):
        return ("missing_or_non_string_full_text",)
    text = unicodedata.normalize("NFC", text_value).replace("\x00", "").strip()
    if not text:
        return ("empty_full_text",)

    source_url = _legacy_row_source_url(statute)
    parsed_url = urlparse(source_url)
    if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.hostname:
        reasons.append("missing_or_invalid_source_url")

    reasons.extend(
        _legacy_fixture_reasons(
            statute,
            input_path=checkpoint_path,
            text=text,
            source_url=source_url,
        )
    )
    if _is_scaffold_or_navigation_record(statute):
        reasons.append("scaffold_or_navigation_record")

    quality = assess_text_quality(text, min_usable_chars=MINIMUM_TEXT_CHARACTERS)
    if quality.placeholder_detected:
        reasons.append("placeholder_text")
    if quality.navigation_detected:
        reasons.append("navigation_chrome")
    if quality.footer_detected:
        reasons.append("footer_chrome")
    if not _has_quality_legal_signal(statute):
        reasons.append("missing_statutory_or_section_signal")
    return tuple(dict.fromkeys(reasons))


def _validate_staged_jsonld(
    path: Path,
    *,
    jurisdiction: str,
    expected_rows: int,
) -> int:
    row_count = 0
    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD has a blank line at {line_number}"
                    )
                try:
                    row = json.loads(
                        line,
                        object_pairs_hook=_mapping_without_duplicate_keys,
                        parse_constant=_reject_json_constant,
                    )
                except (json.JSONDecodeError, ValueError) as exc:
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} is malformed"
                    ) from exc
                if type(row) is not dict:
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} must be an object"
                    )
                if row.get("@type") != "Legislation":
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} is not Legislation"
                    )
                state_code = str(row.get("stateCode") or "").strip().upper()
                if state_code and state_code != jurisdiction:
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} stateCode mismatch"
                    )
                jurisdiction_value = (
                    str(row.get("legislationJurisdiction") or "").strip().upper()
                )
                if jurisdiction_value and jurisdiction_value != f"US-{jurisdiction}":
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} jurisdiction mismatch"
                    )

                text_value = row.get("text")
                if not isinstance(text_value, str) or not text_value.strip():
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} has no statutory text"
                    )
                quality = assess_text_quality(
                    text_value, min_usable_chars=MINIMUM_TEXT_CHARACTERS
                )
                if (
                    quality.placeholder_detected
                    or quality.navigation_detected
                    or quality.footer_detected
                    or _is_scaffold_or_navigation_record(row)
                ):
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} failed structural text validation"
                    )
                output_url = str(
                    row.get("sourceUrl") or row.get("url") or row.get("sameAs") or ""
                ).strip()
                parsed_url = urlparse(output_url)
                if (
                    parsed_url.scheme.lower() not in {"http", "https"}
                    or not parsed_url.hostname
                ):
                    raise CheckpointRematerializationError(
                        f"staged JSON-LD row {line_number} has no valid source URL"
                    )
                row_count += 1
    except (OSError, UnicodeError) as exc:
        raise CheckpointRematerializationError(
            f"cannot validate staged JSON-LD: {path}"
        ) from exc

    if row_count != expected_rows:
        raise CheckpointRematerializationError(
            "standard JSON-LD writer row-count mismatch: "
            f"expected={expected_rows}, observed={row_count}"
        )
    return row_count


def _same_artifact(left: Path, right: Path) -> bool:
    return file_digest(left) == file_digest(right)


def _preflight_destination(staged: Path, destination: Path) -> bool:
    """Return whether a staged artifact needs installation."""

    if destination.is_symlink():
        raise CheckpointRematerializationError(
            f"destination artifact must not be a symlink: {destination}"
        )
    if not destination.exists():
        return True
    if not destination.is_file() or not _same_artifact(staged, destination):
        raise CheckpointRematerializationError(
            f"refusing to overwrite a different existing artifact: {destination}"
        )
    return False


def _source_artifact_descriptor(
    path: Path,
    *,
    root: Path,
    row_count: int,
    jurisdiction: str,
) -> dict[str, Any]:
    """Describe raw acquisition output without query-shard row constraints.

    ``ArtifactDescriptor`` is intentionally bounded for physical retrieval
    shards.  A state's source JSON-LD is a pre-sharding acquisition artifact,
    so its receipt retains the shared digest and CID identities without
    misclassifying it as a physical query shard.
    """

    if type(row_count) is not int or row_count < 1:
        raise CheckpointRematerializationError(
            "source artifact row_count must be a positive integer"
        )
    root_path = resolve_release_root(root, must_exist=True)
    if path.is_symlink():
        raise CheckpointRematerializationError(
            f"source artifact must not be a symlink: {path}"
        )
    try:
        resolved = path.resolve(strict=True)
        relative_path = resolved.relative_to(root_path).as_posix()
        size_bytes, digest = file_digest(resolved)
    except (OSError, ValueError) as exc:
        raise CheckpointRematerializationError(
            f"source artifact is not a regular file under its release root: {path}"
        ) from exc
    content_cid = cid_v1_from_digest(digest)
    return {
        "relative_path": relative_path,
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
        "row_count": row_count,
        "media_type": "application/x-ndjson",
        "schema_id": JSONLD_SCHEMA_VERSION,
        "family": "source_artifact",
        "content_cid": content_cid,
        "cid": content_cid,
        "metadata": {
            "jurisdiction": jurisdiction,
            "jsonld": True,
            "physical_query_shard": False,
        },
    }


def rematerialize_checkpoint(
    *,
    checkpoint_path: str | Path,
    jurisdiction: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """Validate and locally rematerialize one completed state checkpoint."""

    code = validate_jurisdiction(jurisdiction)
    raw_checkpoint = Path(checkpoint_path).expanduser()
    if raw_checkpoint.is_symlink():
        raise CheckpointRematerializationError(
            f"checkpoint must not be a symlink: {raw_checkpoint}"
        )
    try:
        source_size, source_digest = file_digest(raw_checkpoint)
        checkpoint = raw_checkpoint.resolve(strict=True)
    except Exception as exc:
        raise CheckpointRematerializationError(
            f"checkpoint must be a regular, non-symlink file: {raw_checkpoint}"
        ) from exc

    payload = _load_json_object(checkpoint, noun="state-law checkpoint")
    source_size_after, source_digest_after = file_digest(checkpoint)
    if (source_size, source_digest) != (source_size_after, source_digest_after):
        raise CheckpointRematerializationError(
            "checkpoint changed while it was being parsed"
        )

    state_name, statutes, progress, updated_at = _validate_checkpoint(
        payload,
        checkpoint_path=checkpoint,
        jurisdiction=code,
    )

    accepted: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    source_hosts: set[str] = set()
    for statute in statutes:
        reasons = _structural_rejection_reasons(
            statute,
            checkpoint_path=checkpoint,
        )
        if reasons:
            rejection_counts.update(reasons)
            continue
        accepted.append(statute)
        hostname = urlparse(_legacy_row_source_url(statute)).hostname
        if hostname:
            source_hosts.add(hostname.lower())

    if not accepted:
        raise CheckpointRematerializationError(
            "checkpoint has no structurally valid statutes after filtering"
        )

    root = resolve_release_root(output_root, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    root = resolve_release_root(root, must_exist=True)
    output_relative = f"{JSONLD_DIR_NAME}/STATE-{code}.jsonld"
    receipt_relative = f"receipts/STATE-{code}-rematerialization-receipt.json"
    output_path = confine_path(root, output_relative)
    receipt_path = confine_path(root, receipt_relative)

    created_destinations: list[Path] = []
    try:
        with atomic_staging(
            root, prefix=f".state-laws-{code.lower()}-rematerialize-"
        ) as stage:
            staged_jsonld_dir = stage.confine(JSONLD_DIR_NAME)
            staged_jsonld_dir.mkdir(parents=True, exist_ok=True)
            written = _write_state_jsonld_files(
                [
                    {
                        "state_code": code,
                        "state_name": state_name,
                        "statutes": accepted,
                        "statutes_count": len(accepted),
                    }
                ],
                staged_jsonld_dir,
            )
            staged_output = stage.confine(output_relative)
            if written != [str(staged_output)] or not staged_output.is_file():
                raise CheckpointRematerializationError(
                    "standard state-law JSON-LD writer did not emit the expected artifact"
                )
            output_rows = _validate_staged_jsonld(
                staged_output,
                jurisdiction=code,
                expected_rows=len(accepted),
            )
            output_descriptor = _source_artifact_descriptor(
                staged_output,
                root=stage.path,
                row_count=output_rows,
                jurisdiction=code,
            )
            receipt: dict[str, Any] = {
                "schema": RECEIPT_SCHEMA_VERSION,
                "status": "materialized",
                "jurisdiction": code,
                "state_name": state_name,
                "operation": "offline_checkpoint_rematerialization",
                "network_access": False,
                "authorizing_for_publication": False,
                "authorizing_hub_upload": False,
                "source_lineage": {
                    "kind": "state_laws_scraper_partial_checkpoint",
                    "checkpoint_file": checkpoint.name,
                    "checkpoint_sha256": source_digest.hex(),
                    "checkpoint_size_bytes": source_size,
                    "checkpoint_stage_label": "scrape_all:complete",
                    "checkpoint_updated_at": updated_at,
                    "checkpoint_statutes_count": len(statutes),
                    "scraper_code_name": "scrape_all",
                    "progress": progress,
                    "source_hosts": sorted(source_hosts),
                },
                "filtering": {
                    "policy": FILTER_POLICY_VERSION,
                    "minimum_text_characters": MINIMUM_TEXT_CHARACTERS,
                    "input_rows": len(statutes),
                    "accepted_rows": len(accepted),
                    "rejected_rows": len(statutes) - len(accepted),
                    "rejection_counts": dict(sorted(rejection_counts.items())),
                },
                "output_artifact": output_descriptor,
            }
            staged_receipt = stage.confine(receipt_relative)
            atomic_write_canonical_json(staged_receipt, receipt)

            install_output = _preflight_destination(staged_output, output_path)
            install_receipt = _preflight_destination(staged_receipt, receipt_path)
            if install_output:
                created_destinations.append(
                    stage.commit_file(output_relative, overwrite=False)
                )
            if install_receipt:
                created_destinations.append(
                    stage.commit_file(receipt_relative, overwrite=False)
                )
    except Exception:
        for created in reversed(created_destinations):
            try:
                created.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    receipt_size, receipt_digest = file_digest(receipt_path)
    return {
        "status": "materialized",
        "jurisdiction": code,
        "checkpoint_path": str(checkpoint),
        "checkpoint_sha256": source_digest.hex(),
        "input_rows": len(statutes),
        "accepted_rows": len(accepted),
        "rejected_rows": len(statutes) - len(accepted),
        "output_path": str(output_path),
        "output_sha256": str(output_descriptor["sha256"]),
        "output_row_count": output_rows,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_digest.hex(),
        "receipt_size_bytes": receipt_size,
        "network_access": False,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline-rematerialize one exact scrape_all:complete state-law "
            "checkpoint into standard per-state JSON-LD"
        )
    )
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument(
        "--state", required=True, help="one two-letter jurisdiction code"
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = rematerialize_checkpoint(
            checkpoint_path=args.checkpoint,
            jurisdiction=args.state,
            output_root=args.output_root,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with one diagnostic
        sys.stderr.write(f"rematerialize_state_laws_checkpoint: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "rematerialize_state_laws_checkpoint: MATERIALIZED "
            f"state={result['jurisdiction']} rows={result['output_row_count']} "
            f"rejected={result['rejected_rows']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
