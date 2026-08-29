"""Generate an exact-51 LCR-084 candidate-selection manifest from LIVE roots.

This local-only command accepts exactly 51 explicit refresh output roots.  It
does not discover roots beneath a shared parent and performs no acquisition,
network, indexing, publication, or evidence mutation.  Each root must contain
its own direct ``state_refresh_progress.json`` for one fully closed live
jurisdiction acquisition.  The progress receipt is used only to locate the
canonical artifact, normalized source receipt, evidence root, and run seal;
all security-relevant bytes and identities are independently reverified.

The only output is an atomically written, assembler-compatible manifest::

    {
      "schema_version": "state-laws-production-input-map-candidate-selection/v2",
      "states": {
        "AL": {
          "canonical_jsonld_sha256": "<computed digest>",
          "normalized_source_receipt_sha256": "<computed serialized digest>",
          "run_seal_sha256": "<computed serialized digest>"
        }
      }
    }

Digest values are never accepted from the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_current_source_software import (
    normalize_exact_51_source_software_versions,
    registered_exact_51_source_software_versions,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    ADAPTER_SCHEMA_VERSION,
    LegacyStateLawsV2Adapter,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    PENDING_NORMALIZED_RECEIPT_SUFFIX,
    RUN_SEAL_SUFFIX,
    StateLawsRunSealError,
    canonical_run_seal_bytes,
    validate_authorizing_transport_projection,
    validate_state_laws_run_seal,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    inventory_registered_state_scraper_transport_bypasses,
)


def _load_exact_local_script_module(*, filename: str, module_name: str) -> Any:
    """Load one security-critical sibling script from its exact local path."""

    expected_parent = Path(__file__).resolve().parent
    if Path(filename).name != filename:
        raise RuntimeError(f"local dependency name is not a basename: {filename}")
    unresolved = expected_parent / filename
    if unresolved.is_symlink():
        raise RuntimeError(f"local dependency must not be a symlink: {unresolved}")
    target = unresolved.resolve(strict=True)
    if target.parent != expected_parent or not target.is_file():
        raise RuntimeError(f"local dependency is not a safe regular file: {target}")
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"local dependency has no file loader: {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    loaded = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    after = hashlib.sha256(target.read_bytes()).hexdigest()
    if loaded != target or before != after:
        sys.modules.pop(module_name, None)
        raise RuntimeError(f"local dependency changed or resolved elsewhere: {target}")
    return module


_LOCAL_PRODUCTION_RUNNER_MODULE = _load_exact_local_script_module(
    filename="run_state_laws_production_release.py",
    module_name="_state_laws_exact_local_candidate_manifest_runner",
)
assert_evidence_roots_authorizing = (
    _LOCAL_PRODUCTION_RUNNER_MODULE.assert_evidence_roots_authorizing
)
current_refresh_runner_source_software_version = (
    _LOCAL_PRODUCTION_RUNNER_MODULE.current_refresh_runner_source_software_version
)

SELECTION_MANIFEST_SCHEMA_VERSION: Final = (
    "state-laws-production-input-map-candidate-selection/v2"
)
PROGRESS_SCHEMA_VERSION: Final = "ipfs_datasets_py.state_laws_refresh.progress.v1"
LOCAL_MATERIALIZATION_SCHEMA_VERSION: Final = (
    "ipfs_datasets_py.state_laws_refresh.local_materialization.v1"
)
SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA_VERSION: Final = (
    "ipfs_datasets_py.state_laws_refresh.source_software_immutability.v1"
)
REGISTERED_TRANSPORT_INVENTORY_SCHEMA_VERSION: Final = (
    "state-laws-registered-transport-bypass-inventory-v1"
)
TRANSPORT_INVENTORY_SCHEMA_VERSION: Final = (
    "state-laws-transport-bypass-inventory-v1"
)
PROGRESS_FILENAME: Final = "state_refresh_progress.json"

LOCAL_ONLY: Final = True
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False

_CANONICAL_CODES: Final = frozenset(CANONICAL_JURISDICTION_ORDER)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_IDENTITY_RE: Final = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


class StateLawsCandidateSelectionError(ValueError):
    """A LIVE root cannot safely authorize a candidate selection."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    jurisdiction: str
    live_root: Path
    evidence_root: Path
    progress_path: Path
    materialization_receipt_path: Path
    canonical_jsonld_path: Path
    canonical_jsonld_sha256: str
    raw_receipt_path: Path
    normalized_receipt_path: Path
    normalized_receipt_sha256: str
    run_seal_path: Path
    run_seal_sha256: str


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise StateLawsCandidateSelectionError(
                f"JSON input contains duplicate key {key!r}"
            )
        payload[key] = value
    return payload


def _safe_directory(value: str | Path, *, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise StateLawsCandidateSelectionError(f"{label} must be an explicit path")
    if "\x00" in str(value):
        raise StateLawsCandidateSelectionError(f"{label} contains a NUL byte")
    raw = Path(value).expanduser()
    absolute = Path(os.path.abspath(os.fspath(raw)))
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise StateLawsCandidateSelectionError(
                f"{label} must not traverse a symlink: {component}"
            )
    try:
        target = absolute.resolve(strict=True)
    except OSError as exc:
        raise StateLawsCandidateSelectionError(
            f"{label} does not exist: {absolute}"
        ) from exc
    if not target.is_dir():
        raise StateLawsCandidateSelectionError(
            f"{label} must be a directory: {target}"
        )
    return target


def _safe_regular_file(value: str | Path, *, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise StateLawsCandidateSelectionError(f"{label} must be an explicit path")
    if "\x00" in str(value):
        raise StateLawsCandidateSelectionError(f"{label} contains a NUL byte")
    raw = Path(value).expanduser()
    absolute = Path(os.path.abspath(os.fspath(raw)))
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise StateLawsCandidateSelectionError(
                f"{label} must not traverse a symlink: {component}"
            )
    try:
        target = absolute.resolve(strict=True)
    except OSError as exc:
        raise StateLawsCandidateSelectionError(
            f"{label} does not exist: {absolute}"
        ) from exc
    if not target.is_file():
        raise StateLawsCandidateSelectionError(
            f"{label} must be a regular file: {target}"
        )
    return target


def _assert_tree_has_no_symlinks(root: Path, *, label: str) -> None:
    """Validate a root tree without using its contents for candidate discovery."""

    for current, raw_dirnames, filenames in os.walk(root, followlinks=False):
        directory = Path(current)
        retained_directories: list[str] = []
        for name in raw_dirnames:
            child = directory / name
            if child.is_symlink():
                raise StateLawsCandidateSelectionError(
                    f"{label} contains an unsafe directory symlink: {child}"
                )
            retained_directories.append(name)
        raw_dirnames[:] = retained_directories
        for name in filenames:
            child = directory / name
            if child.is_symlink():
                raise StateLawsCandidateSelectionError(
                    f"{label} contains an unsafe file symlink: {child}"
                )


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _declared_file(
    value: Any,
    *,
    base: Path,
    within: Path,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise StateLawsCandidateSelectionError(
            f"{label} must be a non-empty declared path"
        )
    raw = Path(value.strip()).expanduser()
    candidate = raw if raw.is_absolute() else base / raw
    target = _safe_regular_file(candidate, label=label)
    if not _path_is_within(target, within):
        raise StateLawsCandidateSelectionError(
            f"{label} escapes its authorized root: {target}"
        )
    return target


def _declared_directory(value: Any, *, base: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise StateLawsCandidateSelectionError(
            f"{label} must be a non-empty declared path"
        )
    raw = Path(value.strip()).expanduser()
    return _safe_directory(raw if raw.is_absolute() else base / raw, label=label)


def _read_json_object_once(
    path: Path,
    *,
    label: str,
) -> tuple[bytes, dict[str, Any], str]:
    target = _safe_regular_file(path, label=label)
    try:
        serialized = target.read_bytes()
        payload = json.loads(
            serialized.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except StateLawsCandidateSelectionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsCandidateSelectionError(
            f"{label} is not valid UTF-8 JSON: {target}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsCandidateSelectionError(
            f"{label} must contain a JSON object: {target}"
        )
    return serialized, dict(payload), hashlib.sha256(serialized).hexdigest()


def _file_sha256(path: Path, *, label: str) -> str:
    target = _safe_regular_file(path, label=label)
    digest = hashlib.sha256()
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StateLawsCandidateSelectionError(f"cannot read {label}: {target}") from exc
    return digest.hexdigest()


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StateLawsCandidateSelectionError(f"{label} must be an object")
    return value


def _exact_state_array(value: Any, *, code: str, label: str) -> None:
    if not isinstance(value, list) or value != [code]:
        raise StateLawsCandidateSelectionError(
            f"{label} must contain exactly the selected jurisdiction {code}"
        )


def _empty_array(value: Any, *, label: str) -> None:
    if not isinstance(value, list) or value:
        raise StateLawsCandidateSelectionError(f"{label} must be an empty array")


def _empty_object(value: Any, *, label: str) -> None:
    if not isinstance(value, Mapping) or value:
        raise StateLawsCandidateSelectionError(f"{label} must be an empty object")


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StateLawsCandidateSelectionError(f"{label} must be a positive integer")
    return value


def _exact_int(value: Any, expected: int, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise StateLawsCandidateSelectionError(f"{label} must equal {expected}")


def _sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").strip()
    if _SHA256_RE.fullmatch(digest) is None:
        raise StateLawsCandidateSelectionError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return digest


def _source_identity(value: Any, *, label: str) -> str:
    identity = str(value or "").strip()
    if _SOURCE_IDENTITY_RE.fullmatch(identity) is None:
        raise StateLawsCandidateSelectionError(
            f"{label} must be a content-addressed source identity"
        )
    return identity


def _same_path_declaration(
    summary: Mapping[str, Any],
    *,
    field: str,
    expected: Path,
    base: Path,
    within: Path,
    label: str,
) -> None:
    observed = _declared_file(
        summary.get(field),
        base=base,
        within=within,
        label=f"{label}.{field}",
    )
    if observed != expected:
        raise StateLawsCandidateSelectionError(
            f"{label}.{field} differs from the selected run seal"
        )


def _validate_run_seal_summary(
    value: Any,
    *,
    code: str,
    run_id: str,
    seal_path: Path,
    seal_sha256: str,
    evidence_root: Path,
    base: Path,
    label: str,
) -> None:
    summary = _mapping(value, label=label)
    if summary.get("status") != "sealed":
        raise StateLawsCandidateSelectionError(f"{label}.status must be sealed")
    if summary.get("authorizing_for_publication") is not True:
        raise StateLawsCandidateSelectionError(f"{label} is not authorizing")
    if str(summary.get("run_id") or "").strip() != run_id:
        raise StateLawsCandidateSelectionError(f"{label}.run_id mismatch")
    _exact_state_array(summary.get("active_states"), code=code, label=f"{label}.active_states")
    _same_path_declaration(
        summary,
        field="path",
        expected=seal_path,
        base=base,
        within=evidence_root,
        label=label,
    )
    if _sha256(summary.get("sha256"), label=f"{label}.sha256") != seal_sha256:
        raise StateLawsCandidateSelectionError(f"{label}.sha256 mismatch")


def _validate_source_immutability(
    value: Any,
    *,
    code: str,
    source_identity: str,
    runner_identity: str,
    run_id: str,
    seal_path: Path,
    seal_sha256: str,
    evidence_root: Path,
    live_root: Path,
) -> None:
    source = _mapping(value, label=f"{code} source_software_immutability")
    if source.get("schema") != SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA_VERSION:
        raise StateLawsCandidateSelectionError(
            f"{code} source software attestation schema is unsupported"
        )
    if str(source.get("run_id") or "").strip() != run_id:
        raise StateLawsCandidateSelectionError(
            f"{code} source software attestation run_id mismatch"
        )
    if source.get("status") != "verified":
        raise StateLawsCandidateSelectionError(
            f"{code} source software immutability is not verified"
        )
    if source.get("authorizing_for_publication") is not True:
        raise StateLawsCandidateSelectionError(
            f"{code} source software immutability is not authorizing"
        )
    _exact_state_array(source.get("active_states"), code=code, label=f"{code} source active_states")
    _exact_int(source.get("active_state_count"), 1, label=f"{code} source active_state_count")
    if source.get("identities_equal") is not True:
        raise StateLawsCandidateSelectionError(f"{code} producer identities differ")
    if source.get("runner_identity_equal") is not True:
        raise StateLawsCandidateSelectionError(f"{code} runner identities differ")
    starts = _mapping(source.get("start_identities"), label=f"{code} start identities")
    ends = _mapping(source.get("end_identities"), label=f"{code} end identities")
    if dict(starts) != {code: source_identity} or dict(ends) != {code: source_identity}:
        raise StateLawsCandidateSelectionError(
            f"{code} producer identity maps are stale or ambiguous"
        )
    if _source_identity(
        source.get("runner_start_identity"), label=f"{code} runner start identity"
    ) != runner_identity or _source_identity(
        source.get("runner_end_identity"), label=f"{code} runner end identity"
    ) != runner_identity:
        raise StateLawsCandidateSelectionError(f"{code} refresh-runner identity is stale")
    _empty_array(source.get("failed_states"), label=f"{code} failed source states")
    _empty_object(source.get("verification_errors"), label=f"{code} source verification errors")
    _empty_object(source.get("failure_reasons"), label=f"{code} source failure reasons")
    if source.get("runner_verification_error") not in (None, ""):
        raise StateLawsCandidateSelectionError(
            f"{code} refresh-runner identity carries a verification error"
        )
    _empty_array(
        source.get("worker_quiescence_failed_states"),
        label=f"{code} source worker failures",
    )
    _empty_array(
        source.get("run_finalization_failed_states"),
        label=f"{code} source finalization failures",
    )
    _empty_object(
        source.get("run_finalization_failure_reasons"),
        label=f"{code} source finalization failure reasons",
    )
    if source.get("permanent_nonauthorization_marker_path") is not None:
        raise StateLawsCandidateSelectionError(
            f"{code} source identity carries permanent fence evidence"
        )
    quiescence = _mapping(source.get("worker_quiescence"), label=f"{code} source worker quiescence")
    if set(quiescence) != {code}:
        raise StateLawsCandidateSelectionError(
            f"{code} source worker quiescence must bind exactly one state"
        )
    attestation = _mapping(quiescence.get(code), label=f"{code} source worker attestation")
    if not (attestation.get("attested") is True and attestation.get("quiescent") is True):
        raise StateLawsCandidateSelectionError(f"{code} worker is not quiescent")
    _validate_run_seal_summary(
        source.get("run_seal"),
        code=code,
        run_id=run_id,
        seal_path=seal_path,
        seal_sha256=seal_sha256,
        evidence_root=evidence_root,
        base=live_root,
        label=f"{code} source run_seal",
    )


def _require_complete_registered_transport_inventory(
    value: Any,
    *,
    code: str,
    label: str,
) -> Mapping[str, Any]:
    inventory = _mapping(value, label=label)
    if inventory.get("schema_version") != REGISTERED_TRANSPORT_INVENTORY_SCHEMA_VERSION:
        raise StateLawsCandidateSelectionError(f"{label} schema is unsupported")
    _exact_int(inventory.get("candidate_count"), 0, label=f"{label}.candidate_count")
    _exact_int(
        inventory.get("jurisdiction_count"),
        1,
        label=f"{label}.jurisdiction_count",
    )
    _exact_int(
        inventory.get("closure_projection_producer_count"),
        1,
        label=f"{label}.closure_projection_producer_count",
    )
    if inventory.get("complete") is not True or inventory.get(
        "publication_evidence_complete"
    ) is not True:
        raise StateLawsCandidateSelectionError(f"{label} is incomplete")
    _empty_array(
        inventory.get("gap_jurisdictions"),
        label=f"{label}.gap_jurisdictions",
    )
    _empty_array(
        inventory.get("closure_projection_missing_jurisdictions"),
        label=f"{label}.closure_projection_missing_jurisdictions",
    )
    jurisdictions = _mapping(
        inventory.get("jurisdictions"),
        label=f"{label}.jurisdictions",
    )
    if set(jurisdictions) != {code}:
        raise StateLawsCandidateSelectionError(
            f"{label} must bind exactly jurisdiction {code}"
        )
    jurisdiction = _mapping(
        jurisdictions.get(code),
        label=f"{label}.jurisdictions.{code}",
    )
    if jurisdiction.get("schema_version") != TRANSPORT_INVENTORY_SCHEMA_VERSION:
        raise StateLawsCandidateSelectionError(
            f"{label}.jurisdictions.{code} schema is unsupported"
        )
    if jurisdiction.get("complete") is not True or jurisdiction.get(
        "closure_projection_producer_present"
    ) is not True:
        raise StateLawsCandidateSelectionError(
            f"{label}.jurisdictions.{code} is incomplete"
        )
    _exact_int(
        jurisdiction.get("candidate_count"),
        0,
        label=f"{label}.jurisdictions.{code}.candidate_count",
    )
    _empty_array(
        jurisdiction.get("candidates"),
        label=f"{label}.jurisdictions.{code}.candidates",
    )
    return inventory


def _validate_registered_transport_inventory(value: Any, *, code: str) -> None:
    label = f"{code} registered transport inventory"
    stored = _require_complete_registered_transport_inventory(
        value,
        code=code,
        label=label,
    )
    try:
        recomputed_value = inventory_registered_state_scraper_transport_bypasses(
            [code]
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"{label} cannot be recomputed: {exc}"
        ) from exc
    recomputed = _require_complete_registered_transport_inventory(
        recomputed_value,
        code=code,
        label=f"{code} recomputed registered transport inventory",
    )
    if dict(stored) != dict(recomputed):
        raise StateLawsCandidateSelectionError(
            f"{label} differs from the current registered scraper inventory"
        )


def _validate_state_identity(
    value: Any,
    *,
    code: str,
    source_identity: str,
) -> None:
    identity = _mapping(value, label=f"{code} state source identity")
    if identity.get("run_gate_passed") is not True:
        raise StateLawsCandidateSelectionError(
            f"{code} state source identity gate did not pass"
        )
    if _source_identity(
        identity.get("start_identity"), label=f"{code} state source start identity"
    ) != source_identity:
        raise StateLawsCandidateSelectionError(f"{code} state source identity is stale")
    checks = identity.get("checks")
    if not isinstance(checks, list) or not checks:
        raise StateLawsCandidateSelectionError(
            f"{code} state source identity checks are missing"
        )
    for index, raw_check in enumerate(checks):
        check = _mapping(raw_check, label=f"{code} state source check {index}")
        if check.get("identities_equal") is not True or check.get("run_gate_passed") is not True:
            raise StateLawsCandidateSelectionError(
                f"{code} state source check {index} did not pass"
            )
        starts = _mapping(
            check.get("start_identities"), label=f"{code} state source check {index} starts"
        )
        ends = _mapping(
            check.get("end_identities"), label=f"{code} state source check {index} ends"
        )
        if dict(starts) != {code: source_identity} or dict(ends) != {code: source_identity}:
            raise StateLawsCandidateSelectionError(
                f"{code} state source check {index} identity mismatch"
            )
        _empty_object(
            check.get("verification_errors"),
            label=f"{code} state source check {index} verification errors",
        )


def _validate_uncovered_claims(value: Any, *, label: str) -> None:
    """Reject non-empty uncovered/gap claims without distrusting their digests."""

    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            child_label = f"{label}.{raw_key}"
            if (
                "uncovered" in key
                and not key.endswith(("_sha256", "_cid"))
                and child not in (0, False, None, "", [], {})
            ):
                raise StateLawsCandidateSelectionError(
                    f"{child_label} reports uncovered source material"
                )
            if "coverage_gap" in key and child not in (0, False, None, "", [], {}):
                raise StateLawsCandidateSelectionError(
                    f"{child_label} reports a coverage gap"
                )
            _validate_uncovered_claims(child, label=child_label)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_uncovered_claims(child, label=f"{label}[{index}]")


def _canonical_artifact_metadata(
    path: Path,
    *,
    code: str,
) -> tuple[str, int, int]:
    target = _safe_regular_file(path, label=f"{code} canonical JSON-LD")
    digest = hashlib.sha256()
    rows = 0
    size_bytes = 0
    try:
        with target.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                digest.update(raw_line)
                size_bytes += len(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    line = raw_line.decode("utf-8", errors="strict")
                    row = json.loads(
                        line,
                        object_pairs_hook=_json_object_without_duplicate_keys,
                    )
                except (
                    UnicodeError,
                    json.JSONDecodeError,
                    StateLawsCandidateSelectionError,
                ) as exc:
                    raise StateLawsCandidateSelectionError(
                        f"{code} canonical JSON-LD row {line_number} is invalid"
                    ) from exc
                if not isinstance(row, Mapping):
                    raise StateLawsCandidateSelectionError(
                        f"{code} canonical JSON-LD row {line_number} is not an object"
                    )
                if str(row.get("stateCode") or "").strip().upper() != code:
                    raise StateLawsCandidateSelectionError(
                        f"{code} canonical JSON-LD row {line_number} has mismatched stateCode"
                    )
                rows += 1
    except OSError as exc:
        raise StateLawsCandidateSelectionError(
            f"{code} canonical JSON-LD cannot be read"
        ) from exc
    if rows < 1:
        raise StateLawsCandidateSelectionError(
            f"{code} canonical JSON-LD contains no rows"
        )
    return digest.hexdigest(), rows, size_bytes


def _validate_materialization_receipt(
    path: Path,
    *,
    code: str,
    live_root: Path,
) -> tuple[Path, str, int, int, str]:
    _serialized, receipt, receipt_sha256 = _read_json_object_once(
        path, label=f"{code} local materialization receipt"
    )
    if receipt.get("schema") != LOCAL_MATERIALIZATION_SCHEMA_VERSION:
        raise StateLawsCandidateSelectionError(
            f"{code} local materialization receipt schema is unsupported"
        )
    if receipt.get("status") != "materialized" or receipt.get("jurisdiction") != code:
        raise StateLawsCandidateSelectionError(
            f"{code} local materialization receipt does not bind the jurisdiction"
        )
    if receipt.get("network_access_during_materialization") is not False or receipt.get(
        "huggingface_access_during_materialization"
    ) is not False:
        raise StateLawsCandidateSelectionError(
            f"{code} local materialization reports external access"
        )
    if receipt.get("authorizing_for_publication") is not False:
        raise StateLawsCandidateSelectionError(
            f"{code} local materialization receipt has an invalid authority projection"
        )
    scope = _mapping(receipt.get("scope"), label=f"{code} materialization scope")
    if scope.get("mode") != "full" or scope.get("max_statutes") is not None:
        raise StateLawsCandidateSelectionError(
            f"{code} materialization is bounded or partial"
        )
    if receipt.get("artifact_disposition") not in {
        "installed_callback_artifact",
        "replaced_invalid_prior_artifact",
    }:
        raise StateLawsCandidateSelectionError(
            f"{code} materialization reused a prior canonical artifact"
        )
    output = _mapping(
        receipt.get("output_artifact"), label=f"{code} materialization output artifact"
    )
    relative_value = output.get("relative_path")
    if not isinstance(relative_value, str) or not relative_value.strip():
        raise StateLawsCandidateSelectionError(
            f"{code} output artifact relative_path is missing"
        )
    relative = PurePosixPath(relative_value.strip())
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative_value:
        raise StateLawsCandidateSelectionError(
            f"{code} output artifact relative_path is unsafe"
        )
    artifact = _declared_file(
        relative.as_posix(),
        base=live_root,
        within=live_root,
        label=f"{code} canonical JSON-LD",
    )
    if artifact.name != f"STATE-{code}.jsonld":
        raise StateLawsCandidateSelectionError(
            f"{code} canonical artifact must be named STATE-{code}.jsonld"
        )
    if output.get("media_type") != "application/x-ndjson":
        raise StateLawsCandidateSelectionError(
            f"{code} canonical artifact media type is invalid"
        )
    artifact_sha256, rows, artifact_size = _canonical_artifact_metadata(
        artifact, code=code
    )
    if _sha256(output.get("sha256"), label=f"{code} output artifact SHA-256") != artifact_sha256:
        raise StateLawsCandidateSelectionError(
            f"{code} materialization output SHA-256 is stale"
        )
    if _positive_int(output.get("row_count"), label=f"{code} output row count") != rows:
        raise StateLawsCandidateSelectionError(
            f"{code} materialization output row count is stale"
        )
    if _positive_int(output.get("size_bytes"), label=f"{code} output size") != artifact_size:
        raise StateLawsCandidateSelectionError(
            f"{code} materialization output size is stale"
        )
    callback = _mapping(
        receipt.get("callback_artifact"),
        label=f"{code} materialization callback artifact",
    )
    if callback.get("installed_as_canonical") is not True:
        raise StateLawsCandidateSelectionError(
            f"{code} live callback was not installed as the canonical artifact"
        )
    if (
        _sha256(
            callback.get("sha256"),
            label=f"{code} materialization callback SHA-256",
        )
        != artifact_sha256
        or _positive_int(
            callback.get("row_count"),
            label=f"{code} materialization callback row count",
        )
        != rows
        or _positive_int(
            callback.get("size_bytes"),
            label=f"{code} materialization callback size",
        )
        != artifact_size
    ):
        raise StateLawsCandidateSelectionError(
            f"{code} materialization callback does not bind canonical bytes"
        )
    return artifact, artifact_sha256, rows, artifact_size, receipt_sha256


def _validate_normalized_receipt(
    path: Path,
    *,
    code: str,
    artifact_path: Path,
    artifact_sha256: str,
    row_count: int,
    source_identity: str,
    raw_receipt: Mapping[str, Any],
) -> tuple[bytes, str, SourceReceiptRecord]:
    if not path.name.endswith(".normalized.json") or path.name.endswith(
        PENDING_NORMALIZED_RECEIPT_SUFFIX
    ):
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt path is not final"
        )
    serialized, payload, serialized_sha256 = _read_json_object_once(
        path, label=f"{code} normalized source receipt"
    )
    try:
        validate_authorizing_transport_projection(payload)
        record = SourceReceiptRecord.from_mapping(payload)
    except (StateLawsRunSealError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized source receipt is not authorizing: {exc}"
        ) from exc
    if record.jurisdiction != code:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt jurisdiction mismatch"
        )
    if record.source_authority_class is not SourceAuthorityClass.OFFICIAL:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt is not an official-source receipt"
        )
    if record.verification_result is not VerificationResult.VERIFIED:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt is not verified"
        )
    if not record.frontier_closed or record.failed_final or record.quarantined:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt has an open, failed, or quarantined frontier"
        )
    if record.fetched < 1:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt fetched no source units"
        )
    if record.source_software_version != source_identity:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt producer identity is stale"
        )
    if record.source_checksum != artifact_sha256 or artifact_sha256 not in set(
        record.content_hashes
    ):
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt checksum set does not bind canonical bytes"
        )
    normalized = record.payload
    if normalized.get("adapter_schema_version") != ADAPTER_SCHEMA_VERSION:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt adapter schema is stale"
        )
    if normalized.get("admission_eligible") is not True or normalized.get(
        "qualification_reasons"
    ) not in ([], ()):
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt is not admission eligible"
        )
    if _sha256(
        normalized.get("adapter_input_sha256"),
        label=f"{code} normalized receipt adapter input SHA-256",
    ) != artifact_sha256:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt does not bind canonical bytes"
        )
    if _sha256(
        normalized.get("reported_input_sha256"),
        label=f"{code} normalized receipt reported input SHA-256",
    ) != artifact_sha256:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt reports stale canonical bytes"
        )
    if _positive_int(
        normalized.get("adapter_input_row_count"),
        label=f"{code} normalized receipt adapter row count",
    ) != row_count or _positive_int(
        normalized.get("reported_canonical_row_count"),
        label=f"{code} normalized receipt reported row count",
    ) != row_count:
        raise StateLawsCandidateSelectionError(
            f"{code} normalized receipt does not bind canonical row count"
        )
    _validate_uncovered_claims(payload, label=f"{code} normalized receipt")
    try:
        adapter = LegacyStateLawsV2Adapter(
            input_path=artifact_path,
            jurisdiction=code,
            release_point=record.release_point,
            source_receipt=raw_receipt,
        )
        reverified = adapter.source_receipt
    except (OSError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"{code} raw receipt normalization replay failed: {exc}"
        ) from exc
    recomputed_record = getattr(reverified, "record", None)
    if not isinstance(recomputed_record, SourceReceiptRecord):
        raise StateLawsCandidateSelectionError(
            f"{code} raw receipt normalization did not produce a source receipt"
        )
    if recomputed_record.to_dict() != payload:
        raise StateLawsCandidateSelectionError(
            f"{code} stored normalized receipt differs from raw receipt replay"
        )
    if (
        reverified.admission_eligible is not True
        or reverified.qualification_reasons
        or reverified.input_sha256 != artifact_sha256
        or reverified.input_row_count != row_count
        or reverified.expected_row_count != row_count
    ):
        raise StateLawsCandidateSelectionError(
            f"{code} adapter receipt re-verification did not preserve identity"
        )
    return serialized, serialized_sha256, record


def _progress_code(progress: Mapping[str, Any], *, root: Path) -> str:
    raw_states = progress.get("states")
    if not isinstance(raw_states, list) or len(raw_states) != 1:
        raise StateLawsCandidateSelectionError(
            f"{root} progress must describe exactly one requested jurisdiction"
        )
    raw_code = raw_states[0]
    if not isinstance(raw_code, str) or raw_code not in _CANONICAL_CODES:
        raise StateLawsCandidateSelectionError(
            f"{root} progress contains a non-canonical jurisdiction {raw_code!r}"
        )
    return raw_code


def _validate_progress_shape(
    progress: Mapping[str, Any],
    *,
    code: str,
) -> Mapping[str, Any]:
    if progress.get("schema") != PROGRESS_SCHEMA_VERSION:
        raise StateLawsCandidateSelectionError(f"{code} progress schema is unsupported")
    # A clean one-state refresh is intentionally partial only in the global
    # publication-set sense.  Its own state closure below must be complete.
    if progress.get("status") != "partial_success":
        raise StateLawsCandidateSelectionError(
            f"{code} progress is not the canonical isolated LIVE-run shape"
        )
    _exact_state_array(progress.get("states"), code=code, label=f"{code} requested states")
    _exact_state_array(progress.get("active_states"), code=code, label=f"{code} active states")
    _exact_state_array(progress.get("states_completed"), code=code, label=f"{code} completed states")
    _exact_int(progress.get("states_total"), 1, label=f"{code} states_total")
    _exact_int(progress.get("active_states_total"), 1, label=f"{code} active_states_total")
    _exact_int(progress.get("completed_count"), 1, label=f"{code} completed_count")
    _exact_int(progress.get("success_count"), 1, label=f"{code} success_count")
    _exact_int(progress.get("error_count"), 0, label=f"{code} error_count")
    _exact_int(progress.get("zero_statute_count"), 0, label=f"{code} zero_statute_count")
    _empty_array(progress.get("skipped_completed_states"), label=f"{code} skipped completed states")
    _empty_array(progress.get("scrape_gap_states"), label=f"{code} scrape gaps")
    _empty_array(progress.get("build_gap_states"), label=f"{code} build gaps")
    _empty_array(
        progress.get("worker_quiescence_failed_states"),
        label=f"{code} worker quiescence failures",
    )
    if progress.get("strict_acquisition_evidence") is not True:
        raise StateLawsCandidateSelectionError(f"{code} acquisition evidence is not strict")
    if progress.get("retained_replay_only") is not False:
        raise StateLawsCandidateSelectionError(f"{code} progress is retained replay")
    if progress.get("is_complete") is not False or progress.get(
        "exact_production_jurisdiction_set"
    ) is not False:
        raise StateLawsCandidateSelectionError(
            f"{code} isolated run has an invalid global exact-51 projection"
        )
    results = _mapping(progress.get("state_results"), label=f"{code} state results")
    if set(results) != {code}:
        raise StateLawsCandidateSelectionError(
            f"{code} progress state_results must bind exactly one state"
        )
    entry = _mapping(results.get(code), label=f"{code} state result")
    if entry.get("state_code") != code or entry.get("status") != "success":
        raise StateLawsCandidateSelectionError(f"{code} state result is not successful")
    if _positive_int(entry.get("statutes_count"), label=f"{code} statutes_count") < 1:
        raise AssertionError("unreachable")
    if entry.get("authorizing_for_publication") is not True:
        raise StateLawsCandidateSelectionError(f"{code} state result is not authorizing")
    if entry.get("incremental_materialization_status") != "success":
        raise StateLawsCandidateSelectionError(f"{code} canonical materialization failed")
    if str(entry.get("error") or "").strip():
        raise StateLawsCandidateSelectionError(f"{code} state result carries an error")
    worker = _mapping(entry.get("worker_quiescence"), label=f"{code} worker quiescence")
    if not (worker.get("attested") is True and worker.get("quiescent") is True):
        raise StateLawsCandidateSelectionError(f"{code} worker is not quiescent")
    return entry


def _validate_live_root(
    live_root: Path,
    *,
    current_versions: Mapping[str, str],
    current_runner_identity: str,
) -> tuple[_Candidate, dict[Path, str]]:
    _assert_tree_has_no_symlinks(live_root, label=f"{live_root} LIVE root")
    progress_path = _safe_regular_file(
        live_root / PROGRESS_FILENAME,
        label=f"{live_root} direct refresh progress",
    )
    progress_bytes, progress, progress_sha256 = _read_json_object_once(
        progress_path, label=f"{live_root} refresh progress"
    )
    code = _progress_code(progress, root=live_root)
    entry = _validate_progress_shape(progress, code=code)
    source_identity = current_versions[code]
    run_id = str(progress.get("acquisition_run_id") or "").strip()
    if not re.fullmatch(r"[0-9a-f-]{16,64}", run_id):
        raise StateLawsCandidateSelectionError(f"{code} acquisition_run_id is invalid")

    evidence_root = _declared_directory(
        progress.get("acquisition_evidence_root"),
        base=live_root,
        label=f"{code} acquisition evidence root",
    )
    acquisition = _mapping(
        progress.get("acquisition_evidence"), label=f"{code} acquisition evidence summary"
    )
    declared_evidence_root = _declared_directory(
        acquisition.get("evidence_root"),
        base=live_root,
        label=f"{code} acquisition evidence summary root",
    )
    if declared_evidence_root != evidence_root:
        raise StateLawsCandidateSelectionError(
            f"{code} progress names competing acquisition evidence roots"
        )
    try:
        assert_evidence_roots_authorizing([evidence_root])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"{code} acquisition evidence root is non-authorizing: {exc}"
        ) from exc

    if acquisition.get("authorizing_for_publication") is not True:
        raise StateLawsCandidateSelectionError(f"{code} acquisition evidence is not authorizing")
    if acquisition.get("strict") is not True or acquisition.get("retained_replay_only") is not False:
        raise StateLawsCandidateSelectionError(f"{code} acquisition is non-strict or replay-only")
    _exact_state_array(
        acquisition.get("aggregate_closed_states"),
        code=code,
        label=f"{code} closed acquisition states",
    )
    _exact_int(
        acquisition.get("aggregate_closed_count"),
        1,
        label=f"{code} aggregate closed count",
    )
    _empty_array(acquisition.get("evidence_gap_states"), label=f"{code} evidence gaps")
    _empty_array(
        acquisition.get("worker_quiescence_failed_states"),
        label=f"{code} acquisition worker failures",
    )
    _empty_array(
        acquisition.get("run_finalization_failed_states"),
        label=f"{code} acquisition finalization failures",
    )
    _empty_object(
        acquisition.get("run_finalization_failure_reasons"),
        label=f"{code} acquisition finalization failure reasons",
    )
    _empty_array(
        acquisition.get("nonquiescent_marker_paths"),
        label=f"{code} nonquiescent marker paths",
    )
    _empty_array(
        acquisition.get("permanent_nonauthorization_marker_paths"),
        label=f"{code} permanent fence paths",
    )
    if acquisition.get("source_software_immutability_verified") is not True:
        raise StateLawsCandidateSelectionError(f"{code} source immutability is unverified")
    _validate_registered_transport_inventory(
        acquisition.get("transport_bypass_inventory"),
        code=code,
    )

    top_seal_summary = _mapping(progress.get("run_seal"), label=f"{code} run seal summary")
    seal_path = _declared_file(
        top_seal_summary.get("path"),
        base=live_root,
        within=evidence_root,
        label=f"{code} run-final seal",
    )
    if not seal_path.name.endswith(RUN_SEAL_SUFFIX):
        raise StateLawsCandidateSelectionError(f"{code} run-final seal filename is invalid")
    seal_bytes, seal_payload, seal_sha256 = _read_json_object_once(
        seal_path, label=f"{code} run-final seal"
    )
    if canonical_run_seal_bytes(seal_payload) != seal_bytes:
        raise StateLawsCandidateSelectionError(
            f"{code} run-final seal serialization is not canonical"
        )
    try:
        seal = validate_state_laws_run_seal(seal_payload)
    except (StateLawsRunSealError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"{code} run-final seal is not authorizing: {exc}"
        ) from exc
    if seal["run_id"] != run_id or seal["active_states"] != [code]:
        raise StateLawsCandidateSelectionError(
            f"{code} run-final seal does not bind the isolated run"
        )
    if seal["runner_start_identity"] != current_runner_identity:
        raise StateLawsCandidateSelectionError(f"{code} run-final seal runner is stale")
    if seal["start_identities"] != {code: source_identity}:
        raise StateLawsCandidateSelectionError(f"{code} run-final seal producer is stale")
    _validate_run_seal_summary(
        top_seal_summary,
        code=code,
        run_id=run_id,
        seal_path=seal_path,
        seal_sha256=seal_sha256,
        evidence_root=evidence_root,
        base=live_root,
        label=f"{code} progress run_seal",
    )
    _validate_run_seal_summary(
        acquisition.get("run_seal"),
        code=code,
        run_id=run_id,
        seal_path=seal_path,
        seal_sha256=seal_sha256,
        evidence_root=evidence_root,
        base=live_root,
        label=f"{code} acquisition run_seal",
    )
    _same_path_declaration(
        entry,
        field="run_seal_path",
        expected=seal_path,
        base=live_root,
        within=evidence_root,
        label=f"{code} state result",
    )
    if _sha256(
        entry.get("run_seal_sha256"), label=f"{code} state result run-seal SHA-256"
    ) != seal_sha256:
        raise StateLawsCandidateSelectionError(
            f"{code} state result run-seal SHA-256 mismatch"
        )

    _validate_source_immutability(
        progress.get("source_software_immutability"),
        code=code,
        source_identity=source_identity,
        runner_identity=current_runner_identity,
        run_id=run_id,
        seal_path=seal_path,
        seal_sha256=seal_sha256,
        evidence_root=evidence_root,
        live_root=live_root,
    )
    _validate_state_identity(
        entry.get("source_software_immutability"),
        code=code,
        source_identity=source_identity,
    )

    materialization_path = _declared_file(
        entry.get("local_materialization_receipt"),
        base=live_root,
        within=live_root,
        label=f"{code} local materialization receipt",
    )
    (
        artifact_path,
        artifact_sha256,
        row_count,
        _artifact_size,
        materialization_sha256,
    ) = _validate_materialization_receipt(
        materialization_path,
        code=code,
        live_root=live_root,
    )
    if _sha256(entry.get("jsonld_sha256"), label=f"{code} progress JSON-LD SHA-256") != artifact_sha256:
        raise StateLawsCandidateSelectionError(f"{code} progress JSON-LD SHA-256 is stale")
    if _positive_int(entry.get("jsonld_row_count"), label=f"{code} progress JSON-LD row count") != row_count:
        raise StateLawsCandidateSelectionError(f"{code} progress JSON-LD row count is stale")
    if _positive_int(entry.get("statutes_count"), label=f"{code} statutes_count") != row_count:
        raise StateLawsCandidateSelectionError(
            f"{code} state result statute count differs from canonical row count"
        )

    state_evidence = _mapping(
        entry.get("acquisition_evidence"), label=f"{code} state acquisition evidence"
    )
    if state_evidence.get("enabled") is not True or state_evidence.get(
        "aggregate_eligible"
    ) is not True:
        raise StateLawsCandidateSelectionError(f"{code} acquisition ledger is ineligible")
    if state_evidence.get("strict") is not True or state_evidence.get(
        "retained_replay_only"
    ) is not False:
        raise StateLawsCandidateSelectionError(
            f"{code} state acquisition evidence is non-strict or replay-only"
        )
    if state_evidence.get("jurisdiction") != code:
        raise StateLawsCandidateSelectionError(
            f"{code} state acquisition evidence jurisdiction mismatch"
        )
    state_evidence_root = _declared_directory(
        state_evidence.get("evidence_root"),
        base=live_root,
        label=f"{code} state acquisition evidence root",
    )
    if state_evidence_root != evidence_root:
        raise StateLawsCandidateSelectionError(
            f"{code} state acquisition evidence names a competing root"
        )
    if state_evidence.get("all_fetch_coverage_claimed") is not True or state_evidence.get(
        "normalized_source_receipt_usable"
    ) is not True:
        raise StateLawsCandidateSelectionError(f"{code} acquisition coverage is incomplete")
    _empty_array(
        state_evidence.get("eligibility_blockers"),
        label=f"{code} acquisition eligibility blockers",
    )
    _validate_uncovered_claims(state_evidence, label=f"{code} state acquisition evidence")
    parser_coverage = _mapping(
        state_evidence.get("parser_output_coverage"),
        label=f"{code} parser-output coverage",
    )
    if parser_coverage.get("complete") is not True:
        raise StateLawsCandidateSelectionError(f"{code} parser-output coverage is incomplete")
    _exact_int(
        parser_coverage.get("uncovered_unit_count"),
        0,
        label=f"{code} uncovered parser-output count",
    )
    _empty_array(
        parser_coverage.get("uncovered_units"),
        label=f"{code} uncovered parser-output units",
    )
    aggregate = _mapping(
        state_evidence.get("aggregate"), label=f"{code} acquisition aggregate"
    )
    if aggregate.get("status") != "closed_and_normalized" or aggregate.get(
        "authorizing_for_publication"
    ) is not True:
        raise StateLawsCandidateSelectionError(f"{code} acquisition aggregate is not closed")
    if aggregate.get("byte_verification_ok") is not True or aggregate.get(
        "frontier_verification_ok"
    ) is not True:
        raise StateLawsCandidateSelectionError(f"{code} aggregate verification failed")
    if _sha256(
        aggregate.get("canonical_jsonld_sha256"),
        label=f"{code} aggregate canonical SHA-256",
    ) != artifact_sha256 or _positive_int(
        aggregate.get("canonical_jsonld_row_count"),
        label=f"{code} aggregate canonical row count",
    ) != row_count:
        raise StateLawsCandidateSelectionError(
            f"{code} acquisition aggregate does not bind canonical artifact"
        )
    raw_receipt_path = _declared_file(
        aggregate.get("receipt_path"),
        base=evidence_root,
        within=evidence_root,
        label=f"{code} raw acquisition receipt",
    )
    raw_receipt_bytes, raw_receipt, raw_receipt_sha256 = _read_json_object_once(
        raw_receipt_path,
        label=f"{code} raw acquisition receipt",
    )
    receipt_path = _declared_file(
        aggregate.get("normalized_source_receipt_path"),
        base=evidence_root,
        within=evidence_root,
        label=f"{code} normalized source receipt",
    )
    if raw_receipt_path == receipt_path:
        raise StateLawsCandidateSelectionError(
            f"{code} raw and normalized receipts must be distinct files"
        )
    _same_path_declaration(
        aggregate,
        field="run_seal_path",
        expected=seal_path,
        base=evidence_root,
        within=evidence_root,
        label=f"{code} acquisition aggregate",
    )
    if _sha256(
        aggregate.get("run_seal_sha256"), label=f"{code} aggregate run-seal SHA-256"
    ) != seal_sha256:
        raise StateLawsCandidateSelectionError(f"{code} aggregate run-seal SHA-256 mismatch")
    _validate_run_seal_summary(
        state_evidence.get("run_seal"),
        code=code,
        run_id=run_id,
        seal_path=seal_path,
        seal_sha256=seal_sha256,
        evidence_root=evidence_root,
        base=live_root,
        label=f"{code} state acquisition run_seal",
    )

    receipt_bytes, receipt_sha256, receipt = _validate_normalized_receipt(
        receipt_path,
        code=code,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        row_count=row_count,
        source_identity=source_identity,
        raw_receipt=raw_receipt,
    )
    seal_binding = _mapping(seal["states"].get(code), label=f"{code} run-seal binding")
    if (
        seal_binding.get("canonical_jsonld_sha256") != artifact_sha256
        or seal_binding.get("normalized_source_receipt_sha256") != receipt_sha256
        or seal_binding.get("source_software_version") != receipt.source_software_version
    ):
        raise StateLawsCandidateSelectionError(
            f"{code} run-final seal does not bind the selected artifact and receipt"
        )

    snapshots = {
        progress_path: progress_sha256,
        materialization_path: materialization_sha256,
        artifact_path: artifact_sha256,
        raw_receipt_path: raw_receipt_sha256,
        receipt_path: hashlib.sha256(receipt_bytes).hexdigest(),
        seal_path: hashlib.sha256(seal_bytes).hexdigest(),
    }
    if hashlib.sha256(raw_receipt_bytes).hexdigest() != raw_receipt_sha256:
        raise AssertionError("raw receipt digest bookkeeping failure")
    # Keep the captured progress bytes alive through this function's complete
    # validation window; the final bookend below reopens their exact path.
    if hashlib.sha256(progress_bytes).hexdigest() != progress_sha256:
        raise AssertionError("progress digest bookkeeping failure")
    return (
        _Candidate(
            jurisdiction=code,
            live_root=live_root,
            evidence_root=evidence_root,
            progress_path=progress_path,
            materialization_receipt_path=materialization_path,
            canonical_jsonld_path=artifact_path,
            canonical_jsonld_sha256=artifact_sha256,
            raw_receipt_path=raw_receipt_path,
            normalized_receipt_path=receipt_path,
            normalized_receipt_sha256=receipt_sha256,
            run_seal_path=seal_path,
            run_seal_sha256=seal_sha256,
        ),
        snapshots,
    )


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"):
        flags |= int(getattr(os, name, 0))
    return flags


def _open_directory_by_descriptor(
    path: Path,
    *,
    create_missing: bool,
) -> int:
    """Open an absolute directory one no-follow component at a time."""

    if not path.is_absolute():
        raise StateLawsCandidateSelectionError(
            f"output parent must be absolute: {path}"
        )
    flags = _directory_open_flags()
    descriptor = os.open(os.sep, flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_missing:
                    raise
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise StateLawsCandidateSelectionError(
                f"output parent is not a directory: {path}"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _directory_identity(descriptor: int) -> tuple[int, int]:
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        raise StateLawsCandidateSelectionError(
            "pinned output parent stopped being a directory"
        )
    return opened.st_dev, opened.st_ino


def _assert_named_parent_is_pinned(
    path: Path,
    *,
    identity: tuple[int, int],
) -> None:
    try:
        reopened = _open_directory_by_descriptor(path, create_missing=False)
    except (OSError, StateLawsCandidateSelectionError) as exc:
        raise StateLawsCandidateSelectionError(
            f"named output parent changed during atomic write: {path}"
        ) from exc
    try:
        if _directory_identity(reopened) != identity:
            raise StateLawsCandidateSelectionError(
                f"named output parent changed during atomic write: {path}"
            )
    finally:
        os.close(reopened)


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write while staging candidate-selection manifest")
        offset += written


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _atomic_write_manifest(target: Path, manifest: Mapping[str, Any]) -> None:
    """Install canonical JSON through a pinned, no-follow parent descriptor."""

    try:
        serialized = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        parent_descriptor = _open_directory_by_descriptor(
            target.parent,
            create_missing=True,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"cannot open the output parent safely: {target.parent}"
        ) from exc

    temporary_name: str | None = None
    try:
        parent_identity = _directory_identity(parent_descriptor)
        _assert_named_parent_is_pinned(
            target.parent,
            identity=parent_identity,
        )
        try:
            existing = os.stat(
                target.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise StateLawsCandidateSelectionError(
                f"output path must be a regular file or absent: {target}"
            )

        open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        for name in ("O_CLOEXEC", "O_NOFOLLOW"):
            open_flags |= int(getattr(os, name, 0))
        temporary_descriptor: int | None = None
        for _attempt in range(128):
            candidate_name = (
                f".state-laws-selector-{os.getpid()}-"
                f"{secrets.token_hex(16)}.tmp"
            )
            try:
                temporary_descriptor = os.open(
                    candidate_name,
                    open_flags,
                    0o600,
                    dir_fd=parent_descriptor,
                )
            except FileExistsError:
                continue
            temporary_name = candidate_name
            break
        if temporary_descriptor is None or temporary_name is None:
            raise StateLawsCandidateSelectionError(
                "cannot allocate a unique atomic output staging file"
            )
        try:
            temporary_stat = os.fstat(temporary_descriptor)
            if not stat.S_ISREG(temporary_stat.st_mode):
                raise StateLawsCandidateSelectionError(
                    "atomic output staging object is not a regular file"
                )
            _write_all(temporary_descriptor, serialized)
            os.fsync(temporary_descriptor)
        finally:
            os.close(temporary_descriptor)

        _assert_named_parent_is_pinned(
            target.parent,
            identity=parent_identity,
        )
        os.replace(
            temporary_name,
            target.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_name = None
        os.fsync(parent_descriptor)
        _assert_named_parent_is_pinned(
            target.parent,
            identity=parent_identity,
        )

        read_flags = os.O_RDONLY
        for name in ("O_CLOEXEC", "O_NOFOLLOW"):
            read_flags |= int(getattr(os, name, 0))
        installed_descriptor = os.open(
            target.name,
            read_flags,
            dir_fd=parent_descriptor,
        )
        try:
            installed = os.fstat(installed_descriptor)
            if not stat.S_ISREG(installed.st_mode) or _read_all(
                installed_descriptor
            ) != serialized:
                raise StateLawsCandidateSelectionError(
                    "installed candidate-selection manifest changed during write"
                )
        finally:
            os.close(installed_descriptor)
        _assert_named_parent_is_pinned(
            target.parent,
            identity=parent_identity,
        )
    except StateLawsCandidateSelectionError:
        raise
    except OSError as exc:
        raise StateLawsCandidateSelectionError(
            f"cannot atomically write candidate-selection manifest: {target}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


def _safe_output_path(
    value: str | Path,
    *,
    protected_roots: Sequence[Path],
    protected_files: Sequence[Path],
) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise StateLawsCandidateSelectionError("output path must be explicit")
    raw = Path(value).expanduser()
    absolute = Path(os.path.abspath(os.fspath(raw)))
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise StateLawsCandidateSelectionError(
                f"output path must not traverse a symlink: {component}"
            )
    target = absolute
    if target.exists() and not target.is_file():
        raise StateLawsCandidateSelectionError(
            f"output path must be a regular file or absent: {target}"
        )
    if target in set(protected_files) or any(
        _path_is_within(target, root) for root in protected_roots
    ):
        raise StateLawsCandidateSelectionError(
            "output path must be outside every LIVE and evidence root"
        )
    return target


def _normalize_live_roots(values: Sequence[str | Path]) -> tuple[Path, ...]:
    if isinstance(values, (str, bytes, bytearray, Path)):
        raise StateLawsCandidateSelectionError(
            "live_roots must be a repeatable sequence of explicit directories"
        )
    raw_values = list(values)
    if len(raw_values) != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsCandidateSelectionError(
            f"exactly {EXPECTED_JURISDICTION_COUNT} explicit LIVE roots are required"
        )
    lexical_seen: set[Path] = set()
    resolved_seen: set[Path] = set()
    roots: list[Path] = []
    for index, value in enumerate(raw_values):
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise StateLawsCandidateSelectionError(
                f"live_roots[{index}] must be an explicit path"
            )
        lexical = Path(os.path.normpath(os.path.abspath(os.fspath(Path(value).expanduser()))))
        if lexical in lexical_seen:
            raise StateLawsCandidateSelectionError(f"duplicate LIVE root: {lexical}")
        lexical_seen.add(lexical)
        resolved = _safe_directory(value, label=f"live_roots[{index}]")
        if resolved in resolved_seen:
            raise StateLawsCandidateSelectionError(
                f"LIVE roots have a symlink/path-alias collision: {resolved}"
            )
        resolved_seen.add(resolved)
        roots.append(resolved)
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if _path_is_within(left, right) or _path_is_within(right, left):
                raise StateLawsCandidateSelectionError(
                    f"nested LIVE roots are ambiguous: {left} and {right}"
                )
    return tuple(roots)


def generate_state_laws_candidate_selection_manifest(
    *,
    live_roots: Sequence[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    """Validate exact-51 explicit LIVE roots and atomically emit their digests."""

    roots = _normalize_live_roots(live_roots)
    try:
        current_versions = normalize_exact_51_source_software_versions(
            registered_exact_51_source_software_versions()
        )
        current_runner_identity = _source_identity(
            current_refresh_runner_source_software_version(
                require_loaded_source_correspondence=True
            ),
            label="current refresh-runner identity",
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"current source-software identity cannot be proven: {exc}"
        ) from exc

    by_code: dict[str, _Candidate] = {}
    snapshots: dict[Path, str] = {}
    selected_paths: dict[str, dict[Path, str]] = {
        "canonical": {},
        "raw_receipt": {},
        "receipt": {},
        "seal": {},
    }
    for root in roots:
        candidate, candidate_snapshots = _validate_live_root(
            root,
            current_versions=current_versions,
            current_runner_identity=current_runner_identity,
        )
        code = candidate.jurisdiction
        if code in by_code:
            raise StateLawsCandidateSelectionError(
                f"competing LIVE roots both claim jurisdiction {code}"
            )
        for kind, path in (
            ("canonical", candidate.canonical_jsonld_path),
            ("raw_receipt", candidate.raw_receipt_path),
            ("receipt", candidate.normalized_receipt_path),
            ("seal", candidate.run_seal_path),
        ):
            prior = selected_paths[kind].get(path)
            if prior is not None:
                raise StateLawsCandidateSelectionError(
                    f"{kind} path is shared by {prior} and {code}: {path}"
                )
            selected_paths[kind][path] = code
        for path, digest in candidate_snapshots.items():
            prior_digest = snapshots.get(path)
            if prior_digest is not None and prior_digest != digest:
                raise StateLawsCandidateSelectionError(
                    f"input path has competing observed bytes: {path}"
                )
            snapshots[path] = digest
        by_code[code] = candidate

    expected = set(CANONICAL_JURISDICTION_ORDER)
    observed = set(by_code)
    if len(by_code) != EXPECTED_JURISDICTION_COUNT or observed != expected:
        raise StateLawsCandidateSelectionError(
            "LIVE roots must contain exactly the 50 states plus DC; "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )

    try:
        end_versions = normalize_exact_51_source_software_versions(
            registered_exact_51_source_software_versions()
        )
        end_runner_identity = _source_identity(
            current_refresh_runner_source_software_version(
                require_loaded_source_correspondence=True
            ),
            label="ending refresh-runner identity",
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"ending source-software identity cannot be proven: {exc}"
        ) from exc
    if end_versions != current_versions or end_runner_identity != current_runner_identity:
        raise StateLawsCandidateSelectionError(
            "source-software identity changed during candidate selection"
        )

    evidence_roots = tuple(
        sorted({candidate.evidence_root for candidate in by_code.values()}, key=str)
    )
    try:
        assert_evidence_roots_authorizing(evidence_roots)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsCandidateSelectionError(
            f"evidence authorization changed during candidate selection: {exc}"
        ) from exc
    for root in roots:
        _safe_directory(root, label="bookend LIVE root")
        _assert_tree_has_no_symlinks(root, label="bookend LIVE root")
    for path, expected_digest in snapshots.items():
        observed_digest = _file_sha256(path, label="bookend selected input")
        if observed_digest != expected_digest:
            raise StateLawsCandidateSelectionError(
                f"selected input changed during candidate selection: {path}"
            )

    protected_roots = (*roots, *evidence_roots)
    target = _safe_output_path(
        output_path,
        protected_roots=protected_roots,
        protected_files=tuple(snapshots),
    )
    manifest = {
        "schema_version": SELECTION_MANIFEST_SCHEMA_VERSION,
        "states": {
            code: {
                "canonical_jsonld_sha256": by_code[code].canonical_jsonld_sha256,
                "normalized_source_receipt_sha256": by_code[
                    code
                ].normalized_receipt_sha256,
                "run_seal_sha256": by_code[code].run_seal_sha256,
            }
            for code in CANONICAL_JURISDICTION_ORDER
        },
    }
    _atomic_write_manifest(target, manifest)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the exact-51 LCR-084 candidate-selection manifest from "
            "51 explicit one-jurisdiction LIVE refresh roots."
        )
    )
    parser.add_argument(
        "--live-root",
        action="append",
        required=True,
        help=(
            "One explicit LIVE refresh output root containing a direct "
            "state_refresh_progress.json; repeat exactly 51 times."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the atomically written candidate-selection manifest.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = generate_state_laws_candidate_selection_manifest(
            live_roots=args.live_root,
            output_path=args.output,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"candidate selection rejected: {exc}", file=sys.stderr)
        return 2
    output = Path(args.output).expanduser().resolve(strict=True)
    serialized = output.read_bytes()
    print(
        json.dumps(
            {
                "jurisdiction_count": len(manifest["states"]),
                "output_path": str(output),
                "output_sha256": hashlib.sha256(serialized).hexdigest(),
                "schema_version": SELECTION_MANIFEST_SCHEMA_VERSION,
                "status": "written",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
