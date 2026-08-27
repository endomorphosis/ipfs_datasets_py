#!/usr/bin/env python3
"""Assemble the local exact-51 production input map from sealed evidence.

The command performs no acquisition, indexing, upload, publication, or network
operation.  It scans one or more explicit acquisition-evidence roots for serialized
``*.normalized.json`` :class:`SourceReceiptRecord` values and one or more
explicit canonical-output roots for ``STATE-XX.jsonld`` files.  A receipt and
artifact pair is eligible only when the receipt's adapter-input SHA-256 and row
count match the local JSON-LD bytes, its source-software identity matches the
currently registered scraper bundle, and ``LegacyStateLawsV2Adapter`` replays
the shared receipt admission checks.

Byte-identical duplicate candidates are collapsed without copying source data.
Distinct eligible pairs for one jurisdiction are a conflict.  The command
optionally accepts a schema-pinned, digest-bound selection manifest to resolve
specific conflicts without changing or narrowing the scanned roots.  Unlisted
jurisdictions retain the fail-closed unique-candidate rule.  The command writes
only the small schema-pinned map consumed by
``run_state_laws_production_release.py``, and only after the exact 50 states
plus DC close without conflicts, unsafe symlinks, malformed evidence, or extra
jurisdictions.  Incomplete scans remain useful as structured, read-only gap
reports and exit nonzero without creating the map.

Historical source-software comparison can be disabled only for a read-only
preflight.  That diagnostic mode cannot write an input map.

The optional manifest has exactly this shape (digest values abbreviated here)::

    {
      "schema_version": "state-laws-production-input-map-candidate-selection/v1",
      "states": {
        "IA": {
          "canonical_jsonld_sha256": "<64 lowercase hex characters>",
          "normalized_source_receipt_sha256": "<64 lowercase hex characters>"
        }
      }
    }

It may list only the jurisdictions that need explicit curation.  The receipt
digest binds the serialized normalized receipt file, not merely its adapter
input identity, so provenance-distinct receipts are never silently collapsed.
"""

# The repository root bootstrap must precede project imports when this file is
# executed directly as an operations script.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
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
    legacy_input_row_count,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    state_laws_source_provenance_verifier_attestation,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SourceReceiptRecord,
    canonical_json_dumps,
    digest_mapping,
    normalize_sha256,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    IN_PROGRESS_EVIDENCE_MARKER,
    NONQUIESCENT_EVIDENCE_MARKER,
    RUN_SEAL_SUFFIX,
    StateLawsRunSealError,
    validate_authorizing_transport_projection,
    validate_state_laws_run_seal,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_write_canonical_json,
    file_digest,
)


def _load_exact_local_script_module(*, filename: str, module_name: str) -> Any:
    """Load one security-critical sibling script from its exact local path."""

    expected_parent = Path(__file__).resolve().parent
    if Path(filename).name != filename:
        raise RuntimeError(
            f"local script dependency name is not a basename: {filename}"
        )
    unresolved_path = expected_parent / filename
    if unresolved_path.is_symlink():
        raise RuntimeError(
            f"local script dependency must not be a symlink: {unresolved_path}"
        )
    script_path = unresolved_path.resolve(strict=True)
    if script_path.parent != expected_parent or not script_path.is_file():
        raise RuntimeError(
            f"local script dependency is not a safe regular file: {script_path}"
        )
    before_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"local script dependency has no file loader: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    loaded_path = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    after_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    if loaded_path != script_path or after_sha256 != before_sha256:
        sys.modules.pop(module_name, None)
        raise RuntimeError(
            f"local script dependency changed or resolved elsewhere: {script_path}"
        )
    return module


_LOCAL_PRODUCTION_RUNNER_MODULE = _load_exact_local_script_module(
    filename="run_state_laws_production_release.py",
    module_name="_state_laws_exact_local_production_runner",
)
_LOCAL_REFRESH_RUNNER_MODULE = (
    _LOCAL_PRODUCTION_RUNNER_MODULE._LOCAL_REFRESH_RUNNER_MODULE
)
INPUT_MAP_SCHEMA_VERSION = _LOCAL_PRODUCTION_RUNNER_MODULE.INPUT_MAP_SCHEMA_VERSION
assert_evidence_roots_authorizing = (
    _LOCAL_PRODUCTION_RUNNER_MODULE.assert_evidence_roots_authorizing
)
load_exact_51_input_bindings = (
    _LOCAL_PRODUCTION_RUNNER_MODULE.load_exact_51_input_bindings
)
validate_exact_51_input_mapping = (
    _LOCAL_PRODUCTION_RUNNER_MODULE.validate_exact_51_input_mapping
)
current_refresh_runner_source_software_version = (
    _LOCAL_PRODUCTION_RUNNER_MODULE.current_refresh_runner_source_software_version
)

SCHEMA_VERSION: Final = "state-laws-production-input-map-assembly/v1"
SELECTION_MANIFEST_SCHEMA_VERSION: Final = (
    "state-laws-production-input-map-candidate-selection/v1"
)

LOCAL_ONLY: Final = True
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False

_CANONICAL_FILE_RE: Final = re.compile(r"^STATE-([A-Z]{2})\.jsonld$")
_NORMALIZED_RECEIPT_SUFFIX: Final = ".normalized.json"
_CANONICAL_CODES: Final = frozenset(CANONICAL_JURISDICTION_ORDER)
_EVIDENCE_ROOT_MARKERS: Final = (
    IN_PROGRESS_EVIDENCE_MARKER,
    NONQUIESCENT_EVIDENCE_MARKER,
)
_SELECTION_MANIFEST_FIELDS: Final = frozenset({"schema_version", "states"})
_SELECTION_FIELDS: Final = frozenset(
    {"canonical_jsonld_sha256", "normalized_source_receipt_sha256"}
)


class StateLawsInputMapAssemblyError(ValueError):
    """Fail-closed local input-map assembly error."""


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    """One manifest-pinned artifact/receipt digest pair."""

    jurisdiction: str
    canonical_jsonld_sha256: str
    normalized_source_receipt_sha256: str

    def summary(self) -> dict[str, str]:
        return {
            "canonical_jsonld_sha256": self.canonical_jsonld_sha256,
            "normalized_source_receipt_sha256": (self.normalized_source_receipt_sha256),
        }


@dataclass(frozen=True, slots=True)
class CandidateSelectionManifest:
    """Validated local manifest plus the digest of its exact serialized bytes."""

    path: Path
    file_sha256: str
    file_size_bytes: int
    selections: Mapping[str, CandidateSelection]

    def summary(self) -> dict[str, Any]:
        return {
            "file_sha256": self.file_sha256,
            "file_size_bytes": self.file_size_bytes,
            "listed_jurisdictions": [
                code for code in CANONICAL_JURISDICTION_ORDER if code in self.selections
            ],
            "path": str(self.path),
            "schema_version": SELECTION_MANIFEST_SCHEMA_VERSION,
            "selection_count": len(self.selections),
        }


@dataclass(frozen=True, slots=True)
class ReceiptCandidate:
    """One byte-distinct normalized receipt, possibly present at many paths."""

    jurisdiction: str
    paths: tuple[Path, ...]
    record: SourceReceiptRecord
    file_sha256: str
    file_size_bytes: int
    adapter_input_sha256: str
    adapter_input_row_count: int
    run_seal_path: Path
    run_seal_sha256: str

    @property
    def selected_path(self) -> Path:
        return self.paths[0]

    def summary(self) -> dict[str, Any]:
        return {
            "adapter_input_row_count": self.adapter_input_row_count,
            "adapter_input_sha256": self.adapter_input_sha256,
            "duplicate_path_count": len(self.paths) - 1,
            "file_sha256": self.file_sha256,
            "file_size_bytes": self.file_size_bytes,
            "paths": [str(path) for path in self.paths],
            "receipt_id": self.record.receipt_id,
            "release_point": self.record.release_point,
            "run_seal_path": str(self.run_seal_path),
            "run_seal_sha256": self.run_seal_sha256,
            "source_software_version": self.record.source_software_version,
        }


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    """One byte-distinct canonical JSON-LD artifact at one or more paths."""

    jurisdiction: str
    paths: tuple[Path, ...]
    file_sha256: str
    file_size_bytes: int
    row_count: int

    @property
    def selected_path(self) -> Path:
        return self.paths[0]

    def summary(self) -> dict[str, Any]:
        return {
            "duplicate_path_count": len(self.paths) - 1,
            "file_sha256": self.file_sha256,
            "file_size_bytes": self.file_size_bytes,
            "paths": [str(path) for path in self.paths],
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class EligiblePair:
    """One adapter-reverified normalized receipt / canonical artifact pair."""

    receipt: ReceiptCandidate
    artifact: ArtifactCandidate

    def summary(self) -> dict[str, Any]:
        return {
            "canonical_jsonld_path": str(self.artifact.selected_path),
            "canonical_jsonld_sha256": self.artifact.file_sha256,
            "canonical_row_count": self.artifact.row_count,
            "normalized_source_receipt_path": str(self.receipt.selected_path),
            "normalized_source_receipt_sha256": self.receipt.file_sha256,
            "receipt_id": self.receipt.record.receipt_id,
            "run_seal_path": str(self.receipt.run_seal_path),
            "run_seal_sha256": self.receipt.run_seal_sha256,
            "source_release_point": self.receipt.record.release_point,
        }


def _safe_directory(value: str | Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise StateLawsInputMapAssemblyError(
                f"{label} must not traverse a symlink: {component}"
            )
    try:
        root = raw.resolve(strict=True)
    except OSError as exc:
        raise StateLawsInputMapAssemblyError(f"{label} does not exist: {raw}") from exc
    if not root.is_dir():
        raise StateLawsInputMapAssemblyError(f"{label} must be a directory: {root}")
    return root


def _safe_regular_input_file(value: str | Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise StateLawsInputMapAssemblyError(
                f"{label} must not traverse a symlink: {component}"
            )
    try:
        path = raw.resolve(strict=True)
    except OSError as exc:
        raise StateLawsInputMapAssemblyError(f"{label} does not exist: {raw}") from exc
    if not path.is_file():
        raise StateLawsInputMapAssemblyError(f"{label} must be a regular file: {path}")
    return path


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise StateLawsInputMapAssemblyError(
                f"candidate selection manifest contains duplicate key {key!r}"
            )
        payload[key] = value
    return payload


def _require_exact_fields(
    payload: Mapping[str, Any],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    raise StateLawsInputMapAssemblyError(
        f"{label} fields must be exactly {sorted(expected)!r}; "
        f"missing={missing!r}, unexpected={unexpected!r}"
    )


def _load_candidate_selection_manifest(
    value: str | Path,
) -> CandidateSelectionManifest:
    path = _safe_regular_input_file(value, label="candidate selection manifest")
    try:
        serialized = path.read_bytes()
        text = serialized.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except StateLawsInputMapAssemblyError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsInputMapAssemblyError(
            f"candidate selection manifest is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsInputMapAssemblyError(
            "candidate selection manifest must contain a JSON object"
        )
    _require_exact_fields(
        payload,
        expected=_SELECTION_MANIFEST_FIELDS,
        label="candidate selection manifest",
    )
    if payload.get("schema_version") != SELECTION_MANIFEST_SCHEMA_VERSION:
        raise StateLawsInputMapAssemblyError(
            "candidate selection manifest schema_version must be "
            f"{SELECTION_MANIFEST_SCHEMA_VERSION!r}"
        )
    raw_states = payload.get("states")
    if not isinstance(raw_states, Mapping) or not raw_states:
        raise StateLawsInputMapAssemblyError(
            "candidate selection manifest states must be a non-empty JSON object"
        )

    selections: dict[str, CandidateSelection] = {}
    for code, raw_selection in raw_states.items():
        if not isinstance(code, str) or code not in _CANONICAL_CODES:
            raise StateLawsInputMapAssemblyError(
                f"candidate selection manifest contains unknown jurisdiction {code!r}"
            )
        if not isinstance(raw_selection, Mapping):
            raise StateLawsInputMapAssemblyError(
                f"candidate selection manifest states.{code} must be a JSON object"
            )
        _require_exact_fields(
            raw_selection,
            expected=_SELECTION_FIELDS,
            label=f"candidate selection manifest states.{code}",
        )
        try:
            selections[code] = CandidateSelection(
                jurisdiction=code,
                canonical_jsonld_sha256=normalize_sha256(
                    raw_selection.get("canonical_jsonld_sha256"),
                    name=f"candidate selection manifest states.{code}."
                    "canonical_jsonld_sha256",
                ),
                normalized_source_receipt_sha256=normalize_sha256(
                    raw_selection.get("normalized_source_receipt_sha256"),
                    name=f"candidate selection manifest states.{code}."
                    "normalized_source_receipt_sha256",
                ),
            )
        except (TypeError, ValueError) as exc:
            raise StateLawsInputMapAssemblyError(str(exc)) from exc
    return CandidateSelectionManifest(
        path=path,
        file_sha256=hashlib.sha256(serialized).hexdigest(),
        file_size_bytes=len(serialized),
        selections=selections,
    )


def _walk_candidate_files(
    root: Path,
    *,
    predicate: Callable[[str], bool],
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    """Walk without following links and report every unsafe link/special file."""

    candidates: list[Path] = []
    symlinks: list[Path] = []
    special_files: list[Path] = []
    for current, raw_dirnames, filenames in os.walk(root, followlinks=False):
        directory = Path(current)
        retained_directories: list[str] = []
        for name in sorted(raw_dirnames):
            child = directory / name
            if child.is_symlink():
                symlinks.append(child.absolute())
            else:
                retained_directories.append(name)
        raw_dirnames[:] = retained_directories
        for name in sorted(filenames):
            child = directory / name
            if child.is_symlink():
                symlinks.append(child.absolute())
                continue
            if not predicate(name):
                continue
            if not child.is_file():
                special_files.append(child.absolute())
                continue
            candidates.append(child.resolve(strict=True))
    return (
        tuple(sorted(set(candidates), key=str)),
        tuple(sorted(set(symlinks), key=str)),
        tuple(sorted(set(special_files), key=str)),
    )


def _parse_json_object_bytes(path: Path, serialized: bytes) -> dict[str, Any]:
    """Parse the exact receipt bytes that were hashed by discovery."""

    try:
        payload = json.loads(serialized.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsInputMapAssemblyError(
            f"normalized receipt is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsInputMapAssemblyError(
            f"normalized receipt must contain a JSON object: {path}"
        )
    return dict(payload)


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise StateLawsInputMapAssemblyError(
            f"normalized receipt must be a regular file: {path}"
        )
    try:
        serialized = path.read_bytes()
    except OSError as exc:
        raise StateLawsInputMapAssemblyError(
            f"normalized receipt is not valid UTF-8 JSON: {path}"
        ) from exc
    return _parse_json_object_bytes(path, serialized)


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StateLawsInputMapAssemblyError(f"{label} must be a positive integer")
    return value


def _discover_run_seals(
    evidence_roots: Sequence[Path],
    *,
    current_runner_source_software_version: str,
) -> tuple[
    dict[tuple[str, str, str, str], tuple[tuple[Path, str], ...]],
    list[dict[str, str]],
    tuple[Path, ...],
    tuple[Path, ...],
]:
    """Discover seals keyed by state/receipt/artifact/source identity."""

    paths: set[Path] = set()
    symlinks: set[Path] = set()
    special_files: set[Path] = set()
    for root in evidence_roots:
        found, links, specials = _walk_candidate_files(
            root,
            predicate=lambda name: name.endswith(RUN_SEAL_SUFFIX),
        )
        paths.update(found)
        symlinks.update(links)
        special_files.update(specials)
    by_binding: dict[
        tuple[str, str, str, str],
        list[tuple[Path, str]],
    ] = defaultdict(list)
    invalid: list[dict[str, str]] = []
    for path in sorted(paths, key=str):
        try:
            serialized = path.read_bytes()
            raw = json.loads(serialized.decode("utf-8", errors="strict"))
            seal = validate_state_laws_run_seal(raw)
            if (
                seal["runner_start_identity"]
                != current_runner_source_software_version
            ):
                raise StateLawsRunSealError(
                    "run seal refresh-runner identity differs from current code"
                )
            seal_sha256 = hashlib.sha256(serialized).hexdigest()
            for state, binding in seal["states"].items():
                key = (
                    state,
                    binding["normalized_source_receipt_sha256"],
                    binding["canonical_jsonld_sha256"],
                    binding["source_software_version"],
                )
                by_binding[key].append((path, seal_sha256))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            StateLawsRunSealError,
        ) as exc:
            invalid.append(
                {"path": str(path), "reason": f"{type(exc).__name__}: {exc}"}
            )
    return (
        {
            key: tuple(sorted(values, key=lambda item: (item[1], str(item[0]))))
            for key, values in by_binding.items()
        },
        sorted(invalid, key=lambda item: item["path"]),
        tuple(sorted(symlinks, key=str)),
        tuple(sorted(special_files, key=str)),
    )


def _discover_receipts(
    evidence_roots: Sequence[Path],
    *,
    current_runner_source_software_version: str,
) -> tuple[
    dict[str, tuple[ReceiptCandidate, ...]],
    list[dict[str, str]],
    list[dict[str, str]],
    tuple[Path, ...],
    tuple[Path, ...],
    tuple[str, ...],
]:
    (
        seals_by_binding,
        invalid_seals,
        seal_symlinks,
        seal_special_files,
    ) = _discover_run_seals(
        evidence_roots,
        current_runner_source_software_version=(
            current_runner_source_software_version
        ),
    )
    paths: set[Path] = set()
    symlinks: set[Path] = set()
    special_files: set[Path] = set()
    for root in evidence_roots:
        found, links, specials = _walk_candidate_files(
            root,
            predicate=lambda name: name.endswith(_NORMALIZED_RECEIPT_SUFFIX),
        )
        paths.update(found)
        symlinks.update(links)
        special_files.update(specials)
    byte_groups: dict[tuple[int, str], tuple[list[Path], bytes]] = {}
    invalid: list[dict[str, str]] = list(invalid_seals)
    ineligible: list[dict[str, str]] = []
    unexpected: set[str] = set()
    for path in sorted(paths, key=str):
        try:
            serialized = path.read_bytes()
            size = len(serialized)
            digest = hashlib.sha256(serialized).hexdigest()
        except OSError as exc:
            invalid.append(
                {"path": str(path), "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        group_paths, representative_bytes = byte_groups.setdefault(
            (size, digest),
            ([], serialized),
        )
        group_paths.append(path)

    by_code: dict[str, list[ReceiptCandidate]] = defaultdict(list)
    for (size, digest), (group_paths, representative_bytes) in sorted(
        byte_groups.items()
    ):
        ordered_paths = tuple(sorted(group_paths, key=str))
        representative = ordered_paths[0]
        try:
            payload = _parse_json_object_bytes(
                representative,
                representative_bytes,
            )
            raw_code = str(payload.get("jurisdiction") or "").strip().upper()
            if raw_code and raw_code not in _CANONICAL_CODES:
                unexpected.add(raw_code)
            record = SourceReceiptRecord.from_mapping(payload)
            validate_authorizing_transport_projection(payload)
            normalized_payload = record.payload
            if (
                normalized_payload.get("adapter_schema_version")
                != ADAPTER_SCHEMA_VERSION
            ):
                raise StateLawsInputMapAssemblyError(
                    "receipt is not a current LegacyStateLawsV2Adapter normalization"
                )
            input_sha256 = normalize_sha256(
                normalized_payload.get("adapter_input_sha256"),
                name="adapter_input_sha256",
            )
            input_rows = _positive_int(
                normalized_payload.get("adapter_input_row_count"),
                label="adapter_input_row_count",
            )
            reported_rows = _positive_int(
                normalized_payload.get("reported_canonical_row_count"),
                label="reported_canonical_row_count",
            )
            if reported_rows != input_rows:
                raise StateLawsInputMapAssemblyError(
                    "reported canonical row count differs from adapter input row count"
                )
            reasons = normalized_payload.get("qualification_reasons")
            if normalized_payload.get(
                "admission_eligible"
            ) is not True or reasons not in (
                [],
                (),
            ):
                ineligible.append(
                    {
                        "path": str(representative),
                        "reason": (
                            "serialized normalized receipt is not admission eligible"
                        ),
                    }
                )
                continue
            seal_candidates = seals_by_binding.get(
                (
                    record.jurisdiction,
                    digest,
                    input_sha256,
                    str(record.source_software_version or "").strip(),
                ),
                (),
            )
            if not seal_candidates:
                ineligible.append(
                    {
                        "path": str(representative),
                        "reason": (
                            "serialized normalized receipt lacks a matching "
                            "quiescent run-final seal"
                        ),
                    }
                )
                continue
            run_seal_path, run_seal_digest = seal_candidates[0]
            by_code[record.jurisdiction].append(
                ReceiptCandidate(
                    jurisdiction=record.jurisdiction,
                    paths=ordered_paths,
                    record=record,
                    file_sha256=digest,
                    file_size_bytes=size,
                    adapter_input_sha256=input_sha256,
                    adapter_input_row_count=input_rows,
                    run_seal_path=run_seal_path,
                    run_seal_sha256=run_seal_digest,
                )
            )
        except (OSError, TypeError, ValueError) as exc:
            invalid.append(
                {
                    "path": str(representative),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    return (
        {
            code: tuple(
                sorted(
                    candidates,
                    key=lambda item: (item.file_sha256, str(item.selected_path)),
                )
            )
            for code, candidates in by_code.items()
        },
        sorted(invalid, key=lambda item: item["path"]),
        sorted(ineligible, key=lambda item: item["path"]),
        tuple(sorted(symlinks.union(seal_symlinks), key=str)),
        tuple(sorted(special_files.union(seal_special_files), key=str)),
        tuple(sorted(unexpected)),
    )


def _discover_artifacts(
    canonical_roots: Sequence[Path],
) -> tuple[
    dict[str, tuple[ArtifactCandidate, ...]],
    list[dict[str, str]],
    tuple[Path, ...],
    tuple[Path, ...],
    tuple[str, ...],
]:
    paths: set[Path] = set()
    symlinks: set[Path] = set()
    special_files: set[Path] = set()
    unexpected: set[str] = set()
    for root in canonical_roots:
        found, links, specials = _walk_candidate_files(
            root,
            predicate=lambda name: _CANONICAL_FILE_RE.fullmatch(name) is not None,
        )
        paths.update(found)
        symlinks.update(links)
        special_files.update(specials)

    byte_groups: dict[tuple[str, int, str, int], list[Path]] = defaultdict(list)
    invalid: list[dict[str, str]] = []
    for path in sorted(paths, key=str):
        match = _CANONICAL_FILE_RE.fullmatch(path.name)
        assert match is not None
        code = match.group(1)
        if code not in _CANONICAL_CODES:
            unexpected.add(code)
            continue
        try:
            size, digest = file_digest(path)
            rows = legacy_input_row_count(path)
            if rows < 1:
                raise StateLawsInputMapAssemblyError(
                    "canonical JSON-LD contains zero rows"
                )
        except (OSError, TypeError, UnicodeError, ValueError) as exc:
            invalid.append(
                {"path": str(path), "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        byte_groups[(code, size, digest.hex(), rows)].append(path)

    by_code: dict[str, list[ArtifactCandidate]] = defaultdict(list)
    for (code, size, digest, rows), group_paths in sorted(byte_groups.items()):
        by_code[code].append(
            ArtifactCandidate(
                jurisdiction=code,
                paths=tuple(sorted(group_paths, key=str)),
                file_sha256=digest,
                file_size_bytes=size,
                row_count=rows,
            )
        )
    return (
        {
            code: tuple(
                sorted(
                    candidates,
                    key=lambda item: (item.file_sha256, str(item.selected_path)),
                )
            )
            for code, candidates in by_code.items()
        },
        sorted(invalid, key=lambda item: item["path"]),
        tuple(sorted(symlinks, key=str)),
        tuple(sorted(special_files, key=str)),
        tuple(sorted(unexpected)),
    )


def _eligible_pairs_for_code(
    code: str,
    receipts: Sequence[ReceiptCandidate],
    artifacts: Sequence[ArtifactCandidate],
    *,
    required_source_software_version: str | None = None,
) -> tuple[tuple[EligiblePair, ...], list[dict[str, str]]]:
    artifacts_by_identity = {
        (item.file_sha256, item.row_count): item for item in artifacts
    }
    eligible: list[EligiblePair] = []
    rejected: list[dict[str, str]] = []
    for receipt in receipts:
        artifact = artifacts_by_identity.get(
            (receipt.adapter_input_sha256, receipt.adapter_input_row_count)
        )
        if artifact is None:
            continue
        try:
            if (
                required_source_software_version is not None
                and receipt.record.source_software_version
                != required_source_software_version
            ):
                raise StateLawsInputMapAssemblyError(
                    "source_software_version mismatch: receipt binds "
                    f"{receipt.record.source_software_version!r}, current bundle is "
                    f"{required_source_software_version!r}"
                )
            adapter = LegacyStateLawsV2Adapter(
                input_path=artifact.selected_path,
                jurisdiction=code,
                release_point=receipt.record.release_point,
                source_receipt=receipt.record,
            )
            normalized = adapter.source_receipt
            if (
                normalized.admission_eligible is not True
                or normalized.qualification_reasons
            ):
                reasons = ",".join(normalized.qualification_reasons) or "ineligible"
                raise StateLawsInputMapAssemblyError(reasons)
            if (
                normalized.input_sha256 != artifact.file_sha256
                or normalized.input_row_count != artifact.row_count
                or normalized.expected_row_count != artifact.row_count
            ):
                raise StateLawsInputMapAssemblyError(
                    "adapter re-verification did not preserve SHA/row-count identity"
                )
        except (OSError, TypeError, ValueError) as exc:
            rejected.append(
                {
                    "artifact_path": str(artifact.selected_path),
                    "reason": f"{type(exc).__name__}: {exc}",
                    "receipt_path": str(receipt.selected_path),
                }
            )
            continue
        eligible.append(EligiblePair(receipt=receipt, artifact=artifact))
    return (
        tuple(
            sorted(
                eligible,
                key=lambda item: (
                    item.receipt.file_sha256,
                    item.artifact.file_sha256,
                    str(item.receipt.selected_path),
                    str(item.artifact.selected_path),
                ),
            )
        ),
        sorted(
            rejected, key=lambda item: (item["receipt_path"], item["artifact_path"])
        ),
    )


def _safe_output_path(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if not str(raw):
        raise StateLawsInputMapAssemblyError("output path must be explicit")
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise StateLawsInputMapAssemblyError(
                f"output path must not traverse a symlink: {component}"
            )
    target = raw.resolve(strict=False)
    if target.exists() and not target.is_file():
        raise StateLawsInputMapAssemblyError(
            f"output path must be a regular file or absent: {target}"
        )
    temporary = target.with_name(f".{target.name}.partial")
    if temporary.exists() or temporary.is_symlink():
        raise StateLawsInputMapAssemblyError(
            f"atomic output staging path already exists: {temporary}"
        )
    return target


def _base_report(
    *,
    evidence_roots: Sequence[Path],
    canonical_roots: Sequence[Path],
    output_path: Path,
    preflight_only: bool,
    selection_manifest: CandidateSelectionManifest | None,
    current_source_software_versions: Mapping[str, str] | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "canonical_output_roots": [str(path) for path in canonical_roots],
        "acquisition_evidence_roots": [str(path) for path in evidence_roots],
        # Additive compatibility for consumers of the original single-root
        # report.  A plural scan has no truthful singular root.
        "evidence_root": str(evidence_roots[0]) if len(evidence_roots) == 1 else None,
        "local_only": True,
        "network_io_performed": False,
        "output": {
            "path": str(output_path),
            "preflight_only": preflight_only,
            "written": False,
        },
        "performs_crawl": False,
        "performs_indexing": False,
        "schema_version": SCHEMA_VERSION,
        "source_provenance_verifier": (
            state_laws_source_provenance_verifier_attestation()
        ),
        "source_software_current_bundle_required": (
            current_source_software_versions is not None
        ),
    }
    if current_source_software_versions is not None:
        report["current_source_software_versions"] = {
            code: current_source_software_versions[code]
            for code in CANONICAL_JURISDICTION_ORDER
        }
    if selection_manifest is not None:
        report["candidate_selection_manifest"] = selection_manifest.summary()
    return report


def assemble_state_laws_production_input_map(
    *,
    acquisition_evidence_root: str | Path | None = None,
    acquisition_evidence_roots: Sequence[str | Path] | None = None,
    canonical_output_roots: Sequence[str | Path],
    output_path: str | Path,
    preflight_only: bool = False,
    candidate_selection_manifest_path: str | Path | None = None,
    allow_historical_source_software: bool = False,
) -> dict[str, Any]:
    """Discover, reverify, and optionally write one exact-51 local input map."""

    if not isinstance(allow_historical_source_software, bool):
        raise StateLawsInputMapAssemblyError(
            "allow_historical_source_software must be a boolean"
        )
    if allow_historical_source_software and not preflight_only:
        raise StateLawsInputMapAssemblyError(
            "historical source-software mode is read-only and requires "
            "preflight_only=True"
        )

    if isinstance(canonical_output_roots, (str, bytes, bytearray)):
        raise StateLawsInputMapAssemblyError(
            "canonical_output_roots must be a repeatable sequence of directories"
        )
    if isinstance(acquisition_evidence_roots, (str, bytes, bytearray, Path)):
        raise StateLawsInputMapAssemblyError(
            "acquisition_evidence_roots must be a repeatable sequence of directories"
        )
    raw_evidence_roots = list(acquisition_evidence_roots or ())
    if acquisition_evidence_root is not None:
        raw_evidence_roots.append(acquisition_evidence_root)
    if not raw_evidence_roots:
        raise StateLawsInputMapAssemblyError(
            "at least one acquisition evidence root is required"
        )
    evidence_roots = tuple(
        sorted(
            {
                _safe_directory(path, label="acquisition evidence root")
                for path in raw_evidence_roots
            },
            key=str,
        )
    )
    try:
        evidence_roots = assert_evidence_roots_authorizing(evidence_roots)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsInputMapAssemblyError(str(exc)) from exc
    if not canonical_output_roots:
        raise StateLawsInputMapAssemblyError(
            "at least one canonical output root is required"
        )
    canonical_roots = tuple(
        sorted(
            {
                _safe_directory(path, label="canonical output root")
                for path in canonical_output_roots
            },
            key=str,
        )
    )
    selection_manifest = (
        _load_candidate_selection_manifest(candidate_selection_manifest_path)
        if candidate_selection_manifest_path is not None
        else None
    )
    normalized_current_versions = None
    if not allow_historical_source_software:
        normalized_current_versions = normalize_exact_51_source_software_versions(
            registered_exact_51_source_software_versions()
        )
    try:
        current_runner_identity = (
            current_refresh_runner_source_software_version(
                require_loaded_source_correspondence=True
            )
        )
    except Exception as exc:
        raise StateLawsInputMapAssemblyError(
            "current refresh-runner source correspondence is not proven: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    target = _safe_output_path(output_path)
    report = _base_report(
        evidence_roots=evidence_roots,
        canonical_roots=canonical_roots,
        output_path=target,
        preflight_only=preflight_only,
        selection_manifest=selection_manifest,
        current_source_software_versions=normalized_current_versions,
    )

    (
        receipts_by_code,
        invalid_receipts,
        ineligible_receipts,
        receipt_symlinks,
        receipt_special_files,
        unexpected_receipt_codes,
    ) = _discover_receipts(
        evidence_roots,
        current_runner_source_software_version=current_runner_identity,
    )
    (
        artifacts_by_code,
        invalid_artifacts,
        artifact_symlinks,
        artifact_special_files,
        unexpected_artifact_codes,
    ) = _discover_artifacts(canonical_roots)

    symlink_paths = sorted(
        {str(path) for path in (*receipt_symlinks, *artifact_symlinks)}
    )
    special_paths = sorted(
        {str(path) for path in (*receipt_special_files, *artifact_special_files)}
    )
    unexpected_codes = sorted(
        set(unexpected_receipt_codes).union(unexpected_artifact_codes)
    )
    selected: dict[str, EligiblePair] = {}
    missing: list[str] = []
    conflicts: list[str] = []
    selection_unmatched: list[str] = []
    selection_ambiguous: list[str] = []
    source_software_mismatches: list[str] = []
    state_reports: dict[str, Any] = {}

    for code in CANONICAL_JURISDICTION_ORDER:
        receipts = receipts_by_code.get(code, ())
        artifacts = artifacts_by_code.get(code, ())
        required_source_version = (
            normalized_current_versions.get(code)
            if normalized_current_versions is not None
            else None
        )
        eligible, rejected = _eligible_pairs_for_code(
            code,
            receipts,
            artifacts,
            required_source_software_version=required_source_version,
        )
        if not eligible and any(
            "source_software_version mismatch" in str(item.get("reason") or "")
            for item in rejected
        ):
            source_software_mismatches.append(code)
        matching_receipt_identities = {
            (item.adapter_input_sha256, item.adapter_input_row_count)
            for item in receipts
        }
        unmatched_artifacts = [
            item.summary()
            for item in artifacts
            if (item.file_sha256, item.row_count) not in matching_receipt_identities
        ]
        artifact_identities = {(item.file_sha256, item.row_count) for item in artifacts}
        unmatched_receipts = [
            item.summary()
            for item in receipts
            if (item.adapter_input_sha256, item.adapter_input_row_count)
            not in artifact_identities
        ]
        selector = (
            selection_manifest.selections.get(code)
            if selection_manifest is not None
            else None
        )
        matching_selected_pairs = (
            tuple(
                item
                for item in eligible
                if item.artifact.file_sha256 == selector.canonical_jsonld_sha256
                and item.receipt.file_sha256
                == selector.normalized_source_receipt_sha256
            )
            if selector is not None
            else ()
        )
        if selector is not None and len(matching_selected_pairs) == 1:
            status = "selected"
            selected[code] = matching_selected_pairs[0]
        elif selector is not None and not matching_selected_pairs:
            status = "candidate_selection_unmatched"
            selection_unmatched.append(code)
        elif selector is not None:
            status = "candidate_selection_ambiguous"
            selection_ambiguous.append(code)
        elif len(eligible) == 1:
            status = "selected"
            selected[code] = eligible[0]
        elif len(eligible) > 1:
            status = "conflict"
            conflicts.append(code)
        else:
            status = "missing"
            missing.append(code)
        selected_pair = selected.get(code)
        selection_evidence: dict[str, Any] = {
            "manifest_listed": selector is not None,
            "manifest_provided": selection_manifest is not None,
            "mode": (
                "digest_bound_candidate_selection_manifest"
                if selector is not None
                else "automatic_unique_eligible_pair"
            ),
            "outcome": status,
            "selected_pair": selected_pair.summary() if selected_pair else None,
        }
        if selector is not None:
            selection_evidence.update(
                {
                    "matching_eligible_pair_count": len(matching_selected_pairs),
                    "matching_eligible_pairs": [
                        item.summary() for item in matching_selected_pairs
                    ],
                    "requested_digest_pair": selector.summary(),
                }
            )
        state_reports[code] = {
            "artifact_candidate_count": len(artifacts),
            "artifact_candidates": [item.summary() for item in artifacts],
            "eligible_pair_count": len(eligible),
            "eligible_pairs": [item.summary() for item in eligible],
            "receipt_candidate_count": len(receipts),
            "receipt_candidates": [item.summary() for item in receipts],
            "required_source_software_version": required_source_version,
            "rejected_matching_pairs": rejected,
            "selected": selected_pair.summary() if selected_pair else None,
            "selection_evidence": selection_evidence,
            "status": status,
            "unmatched_artifacts": unmatched_artifacts,
            "unmatched_receipts": unmatched_receipts,
        }

    blockers = {
        "conflict_jurisdictions": conflicts,
        "invalid_artifacts": invalid_artifacts,
        "invalid_receipts": invalid_receipts,
        "missing_jurisdictions": missing,
        "special_file_paths": special_paths,
        "source_software_mismatch_jurisdictions": source_software_mismatches,
        "symlink_paths": symlink_paths,
        "unexpected_jurisdictions": unexpected_codes,
    }
    if selection_manifest is not None:
        blockers.update(
            {
                "candidate_selection_ambiguous_jurisdictions": selection_ambiguous,
                "candidate_selection_unmatched_jurisdictions": selection_unmatched,
            }
        )
    ready = not any(blockers.values()) and len(selected) == EXPECTED_JURISDICTION_COUNT
    report.update(
        {
            "blockers": blockers,
            "exact_51_ready": ready,
            "ineligible_receipts": ineligible_receipts,
            "current_refresh_runner_source_software_version": (
                current_runner_identity
            ),
            "jurisdiction_count": len(selected),
            "jurisdictions": state_reports,
            "selected_jurisdictions": list(selected),
            "status": "ready" if ready else "blocked",
        }
    )
    if not ready:
        report["output"]["existing_output_preserved"] = target.exists()
        return report

    input_map = {
        "schema_version": INPUT_MAP_SCHEMA_VERSION,
        "acquisition_evidence_roots": [str(root) for root in evidence_roots],
        "refresh_runner_source_software_version": current_runner_identity,
        "states": {
            code: {
                "canonical_jsonld_path": str(selected[code].artifact.selected_path),
                "canonical_jsonld_sha256": selected[code].artifact.file_sha256,
                "normalized_source_receipt_path": str(
                    selected[code].receipt.selected_path
                ),
                "normalized_source_receipt_sha256": (
                    selected[code].receipt.file_sha256
                ),
                "run_seal_path": str(selected[code].receipt.run_seal_path),
                "run_seal_sha256": selected[code].receipt.run_seal_sha256,
            }
            for code in CANONICAL_JURISDICTION_ORDER
        },
    }
    selected_paths = {
        *(item.artifact.selected_path for item in selected.values()),
        *(item.receipt.selected_path for item in selected.values()),
        *(item.receipt.run_seal_path for item in selected.values()),
    }
    if selection_manifest is not None:
        selected_paths.add(selection_manifest.path)
    if target in selected_paths:
        raise StateLawsInputMapAssemblyError(
            "output path would overwrite selected input evidence or the candidate "
            "selection manifest"
        )
    try:
        validate_exact_51_input_mapping(input_map, base_dir=target.parent)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsInputMapAssemblyError(
            f"shared production input-map precommit gate failed: {exc}"
        ) from exc
    report["input_map_digest"] = digest_mapping(input_map)
    if preflight_only:
        return report

    target = _safe_output_path(target)
    atomic_write_canonical_json(target, input_map)
    loaded_path, bindings = load_exact_51_input_bindings(target)
    if loaded_path != target or len(bindings) != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsInputMapAssemblyError(
            "written input map failed the shared production-runner contract"
        )
    size, digest = file_digest(target)
    report["output"].update(
        {
            "file_sha256": digest.hex(),
            "size_bytes": size,
            "written": True,
        }
    )
    report["status"] = "written"
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the deterministic exact-51 local input map from normalized "
            "acquisition receipts and canonical STATE-XX.jsonld files."
        )
    )
    parser.add_argument(
        "--acquisition-evidence-root",
        action="append",
        required=True,
        help=(
            "Local root recursively containing typed *.normalized.json receipts; "
            "repeat for immutable evidence generations"
        ),
    )
    parser.add_argument(
        "--canonical-output-root",
        action="append",
        required=True,
        help=(
            "Local root recursively containing canonical STATE-XX.jsonld files; "
            "repeat for outputs from multiple runs"
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Explicit local destination for the small production input-map JSON",
    )
    parser.add_argument(
        "--candidate-selection-manifest",
        help=(
            "Optional local read-only JSON manifest pinned to schema "
            f"{SELECTION_MANIFEST_SCHEMA_VERSION!r}; each listed jurisdiction "
            "selects exactly one eligible pair by canonical artifact SHA-256 and "
            "normalized receipt-file SHA-256. Unlisted jurisdictions retain the "
            "fail-closed unique-candidate rule"
        ),
    )
    source_software_group = parser.add_mutually_exclusive_group()
    source_software_group.add_argument(
        "--require-current-source-software",
        dest="require_current_source_software",
        action="store_true",
        default=True,
        help=(
            "Reject a receipt/artifact pair unless its source_software_version "
            "equals the content-addressed bundle produced by the currently "
            "registered scraper for that jurisdiction (default)"
        ),
    )
    source_software_group.add_argument(
        "--allow-historical-source-software",
        dest="require_current_source_software",
        action="store_false",
        help=(
            "Disable the current-bundle comparison for a historical evidence "
            "audit; this mode requires --preflight-only and cannot write a map"
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Print the same structured closure report without writing the map",
    )
    return parser.parse_args(argv)


def _error_report(exc: BaseException) -> dict[str, Any]:
    return {
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "error": {"detail": str(exc), "type": type(exc).__name__},
        "exact_51_ready": False,
        "local_only": True,
        "network_io_performed": False,
        "performs_crawl": False,
        "performs_indexing": False,
        "schema_version": SCHEMA_VERSION,
        "status": "error",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = assemble_state_laws_production_input_map(
            acquisition_evidence_roots=args.acquisition_evidence_root,
            canonical_output_roots=args.canonical_output_root,
            output_path=args.output,
            preflight_only=args.preflight_only,
            candidate_selection_manifest_path=args.candidate_selection_manifest,
            allow_historical_source_software=(
                not args.require_current_source_software
            ),
        )
    except KeyboardInterrupt as exc:
        print(canonical_json_dumps(_error_report(exc)))
        return 130
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(canonical_json_dumps(_error_report(exc)))
        return 2
    print(canonical_json_dumps(report))
    return 0 if report.get("exact_51_ready") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
