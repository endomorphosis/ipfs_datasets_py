#!/usr/bin/env python3
"""Build the exact-51 state-law production artifacts without publishing.

This command is the narrow operational bridge between the canonical refresh
artifacts and the existing production orchestrator.  It deliberately owns no
chunking, BM25, graph, embedding, centroid, upload, or publication logic.

The input map is a JSON object with this shape::

    {
      "schema_version": "state-laws-production-input-map/v2",
      "acquisition_evidence_roots": ["receipts"],
      "refresh_runner_source_software_version": "...@sha256:<digest>",
      "states": {
        "AL": {
          "canonical_jsonld_path": "canonical/STATE-AL.jsonld",
          "canonical_jsonld_sha256": "<digest>",
          "normalized_source_receipt_path": "receipts/al.normalized.json",
          "normalized_source_receipt_sha256": "<digest>",
          "run_seal_path": "receipts/run.state-laws-run-seal.json",
          "run_seal_sha256": "<digest>"
        }
      }
    }

All 50 states plus DC must appear exactly once.  Relative paths are resolved
against the input-map directory.  Before the output root is touched, every
JSON-LD file and serialized :class:`SourceReceiptRecord` is reopened through
``LegacyStateLawsV2Adapter`` using that jurisdiction receipt's own immutable
acquisition pin, and the shared source-rights gate is replayed.  The command's
``--release-point`` is a distinct aggregate release identity; the orchestrator
binds it to the exact source-receipt set and observed canonical corpus digest.

Restartability is owned by ``build_state_laws_production_release``.  The first
corpus stage is an atomic boundary, so this runner intentionally does not save
adapter cursors that could incorrectly claim individual events were durable.
After the corpus stage closes, the orchestrator resumes from its stage-bound
checkpoint without consuming the lazily supplied adapter stream again.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    require_live_source_rights_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    DEFAULT_BATCH_SIZE,
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    DeviceFallbackPolicy,
    OpenUsLawEmbeddingConfig,
    default_embedding_config,
    device_is_available,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_current_source_software import (
    normalize_exact_51_source_software_versions,
    registered_exact_51_source_software_versions,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    LegacyStateLawsV2Adapter,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    _validate_rights_receipt as validate_release_rights_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    state_laws_source_provenance_verifier_attestation,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    AUTHORIZES_HUB_UPLOAD as ORCHESTRATOR_AUTHORIZES_HUB_UPLOAD,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    AUTHORIZES_PUBLICATION as ORCHESTRATOR_AUTHORIZES_PUBLICATION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    LOCAL_ONLY as ORCHESTRATOR_LOCAL_ONLY,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    PERFORMS_NETWORK_IO as ORCHESTRATOR_PERFORMS_NETWORK_IO,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    _source_receipts_digest as production_source_receipts_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    build_state_laws_production_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SourceReceiptRecord,
    canonical_json_dumps,
    digest_mapping,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    IN_PROGRESS_EVIDENCE_MARKER,
    NONQUIESCENT_EVIDENCE_MARKER,
    PENDING_NORMALIZED_RECEIPT_SUFFIX,
    StateLawsRunSealError,
    validate_authorizing_transport_projection,
    validate_state_laws_run_seal,
)

SCHEMA_VERSION: Final = "state-laws-production-local-runner/v1"
INPUT_MAP_SCHEMA_VERSION: Final = "state-laws-production-input-map/v2"

LOCAL_ONLY: Final = True
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False

_STATE_ENTRY_KEYS: Final = frozenset(
    {
        "canonical_jsonld_path",
        "canonical_jsonld_sha256",
        "normalized_source_receipt_path",
        "normalized_source_receipt_sha256",
        "run_seal_path",
        "run_seal_sha256",
    }
)
_INPUT_MAP_KEYS: Final = frozenset(
    {
        "acquisition_evidence_roots",
        "refresh_runner_source_software_version",
        "schema_version",
        "states",
    }
)
_SUPPORTED_EMBEDDING_DEVICES: Final = frozenset({"cpu", "cuda"})
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class StateLawsProductionRunnerError(ValueError):
    """Fail-closed error raised before or around local production composition."""


def _load_exact_local_script_module(*, filename: str, module_name: str) -> Any:
    """Load a security-critical sibling from exact bytes at the local path."""

    expected_parent = Path(__file__).resolve().parent
    if Path(filename).name != filename:
        raise StateLawsProductionRunnerError(
            f"local script dependency name is not a basename: {filename}"
        )
    unresolved = expected_parent / filename
    if unresolved.is_symlink():
        raise StateLawsProductionRunnerError(
            f"local script dependency must not be a symlink: {unresolved}"
        )
    target = unresolved.resolve(strict=True)
    if target.parent != expected_parent or not target.is_file():
        raise StateLawsProductionRunnerError(
            f"local script dependency is not a safe regular file: {target}"
        )
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise StateLawsProductionRunnerError(
            f"local script dependency has no file loader: {target}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    loaded_path = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    after = hashlib.sha256(target.read_bytes()).hexdigest()
    if loaded_path != target or after != before:
        sys.modules.pop(module_name, None)
        raise StateLawsProductionRunnerError(
            f"local script dependency changed or resolved elsewhere: {target}"
        )
    return module


_LOCAL_REFRESH_RUNNER_MODULE = _load_exact_local_script_module(
    filename="refresh_state_laws_corpus.py",
    module_name="_state_laws_exact_local_refresh_runner_for_production",
)
current_refresh_runner_source_software_version = (
    _LOCAL_REFRESH_RUNNER_MODULE.runner_source_software_version
)


@dataclass(frozen=True, slots=True)
class StateInputBinding:
    """One canonical JSON-LD file and its normalized source receipt."""

    jurisdiction: str
    acquisition_evidence_roots: tuple[Path, ...]
    canonical_jsonld_path: Path
    canonical_jsonld_sha256: str
    normalized_source_receipt_path: Path
    normalized_source_receipt_sha256: str
    run_seal_path: Path
    run_seal_sha256: str
    refresh_runner_source_software_version: str
    normalized_source_receipt: SourceReceiptRecord | None = None


@dataclass(frozen=True, slots=True)
class PreparedStateLawsInputs:
    """Exact-51 adapter set validated before any build output is created."""

    input_map_path: Path
    input_map_sha256: str
    bindings: tuple[StateInputBinding, ...]
    adapters: tuple[LegacyStateLawsV2Adapter, ...]
    source_receipts: tuple[SourceReceiptRecord, ...]
    rights_receipt_path: Path
    rights_receipt_sha256: str
    rights_receipt: Mapping[str, Any]
    canonical_row_count: int
    current_source_software_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "rights_receipt", MappingProxyType(dict(self.rights_receipt))
        )
        object.__setattr__(
            self,
            "current_source_software_versions",
            MappingProxyType(dict(self.current_source_software_versions)),
        )


def _safe_regular_file(value: str | Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise StateLawsProductionRunnerError(
                f"{label} must not traverse a symlink: {component}"
            )
    try:
        target = raw.resolve(strict=True)
    except OSError as exc:
        raise StateLawsProductionRunnerError(f"{label} does not exist: {raw}") from exc
    if not target.is_file():
        raise StateLawsProductionRunnerError(
            f"{label} must be a regular file: {target}"
        )
    return target


def _safe_directory(value: str | Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise StateLawsProductionRunnerError(
                f"{label} must not traverse a symlink: {component}"
            )
    try:
        target = raw.resolve(strict=True)
    except OSError as exc:
        raise StateLawsProductionRunnerError(f"{label} does not exist: {raw}") from exc
    if not target.is_dir():
        raise StateLawsProductionRunnerError(f"{label} must be a directory: {target}")
    return target


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise StateLawsProductionRunnerError(
                f"JSON evidence contains duplicate key {key!r}"
            )
        payload[key] = value
    return payload


def _read_json_object_once(
    value: str | Path,
    *,
    label: str,
) -> tuple[Path, dict[str, Any], str]:
    """Read once, then derive both the digest and parsed object from those bytes."""

    target = _safe_regular_file(value, label=label)
    try:
        serialized = target.read_bytes()
        payload = json.loads(
            serialized.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except StateLawsProductionRunnerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsProductionRunnerError(
            f"{label} is not valid UTF-8 JSON: {target}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsProductionRunnerError(f"{label} must be a JSON object")
    return target, dict(payload), hashlib.sha256(serialized).hexdigest()


def _load_json_object(value: str | Path, *, label: str) -> tuple[Path, dict[str, Any]]:
    target, payload, _ = _read_json_object_once(value, label=label)
    return target, payload


def _sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").strip()
    if _SHA256_RE.fullmatch(digest) is None:
        raise StateLawsProductionRunnerError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return digest


def _source_identity(value: Any, *, label: str) -> str:
    identity = str(value or "").strip()
    prefix, marker, digest = identity.rpartition("@sha256:")
    if not prefix or not marker or _SHA256_RE.fullmatch(digest) is None:
        raise StateLawsProductionRunnerError(
            f"{label} must be a content-addressed source identity"
        )
    return identity


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def assert_evidence_roots_authorizing(
    roots: Sequence[str | Path],
) -> tuple[Path, ...]:
    """Reject poisoned or in-progress evidence roots and unsafe traversal."""

    if isinstance(roots, (str, bytes, bytearray, Path)):
        raise StateLawsProductionRunnerError("evidence roots must be a sequence")
    normalized = tuple(
        sorted(
            {
                _safe_directory(root, label="acquisition evidence root")
                for root in roots
            },
            key=str,
        )
    )
    if not normalized:
        raise StateLawsProductionRunnerError(
            "at least one acquisition evidence root is required"
        )
    for root in normalized:
        permanent_marker = root / NONQUIESCENT_EVIDENCE_MARKER
        if permanent_marker.exists() or permanent_marker.is_symlink():
            raise StateLawsProductionRunnerError(
                "acquisition evidence root is permanently non-authorizing after "
                f"a nonquiescent worker timeout: {root}"
            )
        in_progress_marker = root / IN_PROGRESS_EVIDENCE_MARKER
        if in_progress_marker.exists() or in_progress_marker.is_symlink():
            raise StateLawsProductionRunnerError(
                "acquisition evidence root has an unclosed acquisition run: "
                f"{root}"
            )
        for current, raw_dirnames, filenames in os.walk(root, followlinks=False):
            directory = Path(current)
            for name in raw_dirnames:
                if (directory / name).is_symlink():
                    raise StateLawsProductionRunnerError(
                        "acquisition evidence root contains an unsafe directory "
                        f"symlink: {directory / name}"
                    )
            for name in filenames:
                candidate = directory / name
                if candidate.is_symlink():
                    raise StateLawsProductionRunnerError(
                        "acquisition evidence root contains an unsafe file symlink: "
                        f"{candidate}"
                    )
                if name.endswith(PENDING_NORMALIZED_RECEIPT_SUFFIX):
                    raise StateLawsProductionRunnerError(
                        "acquisition evidence root has an in-progress normalized "
                        f"receipt: {candidate}"
                    )
    return normalized


def _resolve_mapped_file(
    value: Any,
    *,
    base_dir: Path,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise StateLawsProductionRunnerError(f"{label} must be a non-empty path")
    candidate = Path(value.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return _safe_regular_file(candidate, label=label)


def _resolve_mapped_directory(
    value: Any,
    *,
    base_dir: Path,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise StateLawsProductionRunnerError(f"{label} must be a non-empty path")
    candidate = Path(value.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return _safe_directory(candidate, label=label)


def _current_refresh_runner_identity() -> str:
    try:
        return _source_identity(
            current_refresh_runner_source_software_version(
                require_loaded_source_correspondence=True
            ),
            label="current refresh-runner source identity",
        )
    except StateLawsProductionRunnerError:
        raise
    except Exception as exc:
        raise StateLawsProductionRunnerError(
            "current refresh-runner loaded/source correspondence is not proven: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _read_file_sha256_once(path: Path, *, label: str) -> str:
    target = _safe_regular_file(path, label=label)
    try:
        serialized = target.read_bytes()
    except OSError as exc:
        raise StateLawsProductionRunnerError(f"cannot read {label}: {target}") from exc
    return hashlib.sha256(serialized).hexdigest()


def _reverify_state_input_binding(
    binding: StateInputBinding,
    *,
    current_runner_identity: str,
) -> SourceReceiptRecord:
    """Reopen and exactly verify one map binding from one read per evidence file."""

    code = binding.jurisdiction
    if binding.refresh_runner_source_software_version != current_runner_identity:
        raise StateLawsProductionRunnerError(
            f"states.{code} refresh-runner identity differs from current code"
        )
    canonical_sha256 = _read_file_sha256_once(
        binding.canonical_jsonld_path,
        label=f"states.{code} canonical JSON-LD",
    )
    if canonical_sha256 != binding.canonical_jsonld_sha256:
        raise StateLawsProductionRunnerError(
            f"states.{code} canonical JSON-LD SHA-256 mismatch"
        )
    _, receipt_payload, receipt_sha256 = _read_json_object_once(
        binding.normalized_source_receipt_path,
        label=f"states.{code} normalized source receipt",
    )
    if receipt_sha256 != binding.normalized_source_receipt_sha256:
        raise StateLawsProductionRunnerError(
            f"states.{code} normalized source-receipt SHA-256 mismatch"
        )
    try:
        validate_authorizing_transport_projection(receipt_payload)
        receipt = SourceReceiptRecord.from_mapping(receipt_payload)
    except (StateLawsRunSealError, TypeError, ValueError) as exc:
        raise StateLawsProductionRunnerError(
            f"states.{code} normalized source receipt is not authorizing: {exc}"
        ) from exc
    if receipt.jurisdiction != code:
        raise StateLawsProductionRunnerError(
            f"states.{code} receipt jurisdiction is {receipt.jurisdiction!r}"
        )
    receipt_input_sha256 = _sha256(
        receipt.payload.get("adapter_input_sha256"),
        label=f"states.{code} receipt adapter_input_sha256",
    )
    if receipt_input_sha256 != canonical_sha256:
        raise StateLawsProductionRunnerError(
            f"states.{code} receipt does not bind canonical JSON-LD bytes"
        )

    _, raw_seal, seal_sha256 = _read_json_object_once(
        binding.run_seal_path,
        label=f"states.{code} run-final seal",
    )
    if seal_sha256 != binding.run_seal_sha256:
        raise StateLawsProductionRunnerError(
            f"states.{code} run-final seal SHA-256 mismatch"
        )
    try:
        seal = validate_state_laws_run_seal(raw_seal)
    except (StateLawsRunSealError, TypeError, ValueError) as exc:
        raise StateLawsProductionRunnerError(
            f"states.{code} run-final seal is not authorizing: {exc}"
        ) from exc
    if seal["runner_start_identity"] != current_runner_identity:
        raise StateLawsProductionRunnerError(
            f"states.{code} run-final seal refresh-runner identity is stale"
        )
    state_seal = seal["states"].get(code)
    if not isinstance(state_seal, Mapping):
        raise StateLawsProductionRunnerError(
            f"states.{code} is absent from its run-final seal"
        )
    if (
        state_seal.get("canonical_jsonld_sha256") != canonical_sha256
        or state_seal.get("normalized_source_receipt_sha256") != receipt_sha256
        or state_seal.get("source_software_version")
        != receipt.source_software_version
    ):
        raise StateLawsProductionRunnerError(
            f"states.{code} run-final seal does not bind the selected evidence"
        )
    return receipt


def reverify_exact_51_input_bindings(
    bindings: Sequence[StateInputBinding],
) -> tuple[SourceReceiptRecord, ...]:
    """Fail closed on any root, runner, artifact, receipt, or seal drift."""

    if len(bindings) != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsProductionRunnerError(
            "input re-verification requires exactly 51 state bindings"
        )
    observed = tuple(binding.jurisdiction for binding in bindings)
    if observed != tuple(CANONICAL_JURISDICTION_ORDER):
        raise StateLawsProductionRunnerError(
            "input re-verification is not in canonical exact-51 order"
        )
    evidence_roots = [
        root
        for binding in bindings
        for root in binding.acquisition_evidence_roots
    ]
    assert_evidence_roots_authorizing(evidence_roots)
    current_runner_identity = _current_refresh_runner_identity()
    receipts: list[SourceReceiptRecord] = []
    failures: dict[str, str] = {}
    for binding in bindings:
        try:
            receipts.append(
                _reverify_state_input_binding(
                    binding,
                    current_runner_identity=current_runner_identity,
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            failures[binding.jurisdiction] = f"{type(exc).__name__}: {exc}"
    if failures:
        detail = "; ".join(f"{code}={failures[code]}" for code in sorted(failures))
        raise StateLawsProductionRunnerError(
            "exact-51 sealed-input verification failed for "
            f"{len(failures)} jurisdiction(s): {detail}"
        )
    end_runner_identity = _current_refresh_runner_identity()
    if end_runner_identity != current_runner_identity:
        raise StateLawsProductionRunnerError(
            "current refresh-runner identity changed during sealed-input "
            "verification"
        )
    # Bookend the selected-file reads.  The durable lease/poison markers must
    # remain absent throughout the whole validation window.
    assert_evidence_roots_authorizing(evidence_roots)
    return tuple(receipts)


def validate_exact_51_input_mapping(
    payload: Mapping[str, Any],
    *,
    base_dir: str | Path,
) -> tuple[StateInputBinding, ...]:
    """Validate the v2 exact-51 map and all of its sealed local evidence."""

    if not isinstance(payload, Mapping):
        raise StateLawsProductionRunnerError("input map must be a JSON object")
    mapping_base = Path(base_dir).expanduser().resolve()
    unexpected_top_level = sorted(set(payload).difference(_INPUT_MAP_KEYS))
    missing_top_level = sorted(_INPUT_MAP_KEYS.difference(payload))
    if unexpected_top_level or missing_top_level:
        raise StateLawsProductionRunnerError(
            "input map top-level fields are invalid; "
            f"missing={missing_top_level} unsupported={unexpected_top_level}"
        )
    if payload.get("schema_version") != INPUT_MAP_SCHEMA_VERSION:
        raise StateLawsProductionRunnerError(
            f"input map schema_version must be {INPUT_MAP_SCHEMA_VERSION!r}"
        )
    states = payload.get("states")
    if not isinstance(states, Mapping):
        raise StateLawsProductionRunnerError("input map states must be an object")
    map_runner_identity = _source_identity(
        payload.get("refresh_runner_source_software_version"),
        label="input map refresh_runner_source_software_version",
    )
    raw_evidence_roots = payload.get("acquisition_evidence_roots")
    if not isinstance(raw_evidence_roots, Sequence) or isinstance(
        raw_evidence_roots,
        (str, bytes, bytearray),
    ):
        raise StateLawsProductionRunnerError(
            "input map acquisition_evidence_roots must be an array"
        )
    map_evidence_roots = tuple(
        sorted(
            {
                _resolve_mapped_directory(
                    value,
                    base_dir=mapping_base,
                    label="input map acquisition_evidence_roots",
                )
                for value in raw_evidence_roots
            },
            key=str,
        )
    )
    if not map_evidence_roots:
        raise StateLawsProductionRunnerError(
            "input map acquisition_evidence_roots must not be empty"
        )
    if len(map_evidence_roots) != len(raw_evidence_roots):
        raise StateLawsProductionRunnerError(
            "input map acquisition_evidence_roots must be unique after path "
            "resolution"
        )

    expected = set(CANONICAL_JURISDICTION_ORDER)
    observed = set(states)
    missing = sorted(expected.difference(observed))
    extra = sorted(observed.difference(expected))
    if len(states) != EXPECTED_JURISDICTION_COUNT or missing or extra:
        raise StateLawsProductionRunnerError(
            "input map must contain exactly the 50 states plus DC; "
            f"count={len(states)} missing={missing} extra={extra}"
        )

    bindings: list[StateInputBinding] = []
    canonical_paths: dict[Path, str] = {}
    receipt_paths: dict[Path, str] = {}
    for code in CANONICAL_JURISDICTION_ORDER:
        raw = states.get(code)
        if not isinstance(raw, Mapping):
            raise StateLawsProductionRunnerError(f"states.{code} must be an object")
        unexpected = sorted(set(raw).difference(_STATE_ENTRY_KEYS))
        missing_fields = sorted(_STATE_ENTRY_KEYS.difference(raw))
        if unexpected or missing_fields:
            raise StateLawsProductionRunnerError(
                f"states.{code} fields are invalid; "
                f"missing={missing_fields} unsupported={unexpected}"
            )
        canonical = _resolve_mapped_file(
            raw.get("canonical_jsonld_path"),
            base_dir=mapping_base,
            label=f"states.{code}.canonical_jsonld_path",
        )
        if canonical.name != f"STATE-{code}.jsonld":
            raise StateLawsProductionRunnerError(
                f"states.{code}.canonical_jsonld_path must name "
                f"STATE-{code}.jsonld; got {canonical.name!r}"
            )
        receipt = _resolve_mapped_file(
            raw.get("normalized_source_receipt_path"),
            base_dir=mapping_base,
            label=f"states.{code}.normalized_source_receipt_path",
        )
        seal = _resolve_mapped_file(
            raw.get("run_seal_path"),
            base_dir=mapping_base,
            label=f"states.{code}.run_seal_path",
        )
        if not any(
            _path_is_within(receipt, root) for root in map_evidence_roots
        ) or not any(_path_is_within(seal, root) for root in map_evidence_roots):
            raise StateLawsProductionRunnerError(
                f"states.{code} receipt and run-final seal must be within the "
                "map's acquisition evidence roots"
            )
        prior_code = canonical_paths.get(canonical)
        if prior_code is not None:
            raise StateLawsProductionRunnerError(
                f"canonical JSON-LD path is mapped more than once: "
                f"{prior_code}/{code} -> {canonical}"
            )
        prior_code = receipt_paths.get(receipt)
        if prior_code is not None:
            raise StateLawsProductionRunnerError(
                f"normalized source-receipt path is mapped more than once: "
                f"{prior_code}/{code} -> {receipt}"
            )
        if canonical == receipt:
            raise StateLawsProductionRunnerError(
                f"states.{code} maps its JSON-LD and source receipt to one file"
            )
        canonical_paths[canonical] = code
        receipt_paths[receipt] = code
        bindings.append(
            StateInputBinding(
                jurisdiction=code,
                acquisition_evidence_roots=map_evidence_roots,
                canonical_jsonld_path=canonical,
                canonical_jsonld_sha256=_sha256(
                    raw.get("canonical_jsonld_sha256"),
                    label=f"states.{code}.canonical_jsonld_sha256",
                ),
                normalized_source_receipt_path=receipt,
                normalized_source_receipt_sha256=_sha256(
                    raw.get("normalized_source_receipt_sha256"),
                    label=f"states.{code}.normalized_source_receipt_sha256",
                ),
                run_seal_path=seal,
                run_seal_sha256=_sha256(
                    raw.get("run_seal_sha256"),
                    label=f"states.{code}.run_seal_sha256",
                ),
                refresh_runner_source_software_version=map_runner_identity,
            )
        )

    if set(canonical_paths).intersection(receipt_paths):
        raise StateLawsProductionRunnerError(
            "a mapped file cannot serve as both canonical JSON-LD and source receipt"
        )
    normalized_bindings = tuple(bindings)
    verified_receipts = reverify_exact_51_input_bindings(normalized_bindings)
    return tuple(
        replace(binding, normalized_source_receipt=receipt)
        for binding, receipt in zip(
            normalized_bindings,
            verified_receipts,
            strict=True,
        )
    )


def _load_exact_51_input_bindings_with_digest(
    input_map_path: str | Path,
) -> tuple[Path, tuple[StateInputBinding, ...], str]:
    manifest_path, payload, manifest_sha256 = _read_json_object_once(
        input_map_path,
        label="input map",
    )
    return (
        manifest_path,
        validate_exact_51_input_mapping(payload, base_dir=manifest_path.parent),
        manifest_sha256,
    )


def load_exact_51_input_bindings(
    input_map_path: str | Path,
) -> tuple[Path, tuple[StateInputBinding, ...]]:
    """Load and validate a bijective exact-51 path map before opening receipts."""

    manifest_path, bindings, _ = _load_exact_51_input_bindings_with_digest(
        input_map_path
    )
    return manifest_path, bindings


def prepare_exact_51_inputs(
    *,
    input_map_path: str | Path,
    rights_receipt_path: str | Path,
) -> PreparedStateLawsInputs:
    """Reverify current-bundle normalized receipts, without writes."""

    manifest_path, bindings, manifest_sha256 = (
        _load_exact_51_input_bindings_with_digest(input_map_path)
    )
    rights_path, rights_receipt, rights_sha256 = _read_json_object_once(
        rights_receipt_path, label="source-rights receipt"
    )
    try:
        rights_receipt = require_live_source_rights_receipt(rights_receipt)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsProductionRunnerError(
            f"source-rights receipt failed authoritative live verification: {exc}"
        ) from exc
    required_versions = normalize_exact_51_source_software_versions(
        registered_exact_51_source_software_versions()
    )

    adapters: list[LegacyStateLawsV2Adapter] = []
    source_receipts: list[SourceReceiptRecord] = []
    failures: dict[str, str] = {}
    for binding in bindings:
        code = binding.jurisdiction
        try:
            typed_receipt = binding.normalized_source_receipt
            if typed_receipt is None:
                raise StateLawsProductionRunnerError(
                    "sealed normalized source receipt was not retained"
                )
            required_version = required_versions.get(code)
            if (
                required_version is not None
                and typed_receipt.source_software_version != required_version
            ):
                raise StateLawsProductionRunnerError(
                    "source_software_version mismatch: receipt binds "
                    f"{typed_receipt.source_software_version!r}, current bundle is "
                    f"{required_version!r}"
                )
            adapter = LegacyStateLawsV2Adapter(
                input_path=binding.canonical_jsonld_path,
                jurisdiction=code,
                release_point=typed_receipt.release_point,
                source_receipt=typed_receipt,
            )
            normalized = adapter.source_receipt
            if normalized.admission_eligible is not True:
                reasons = ",".join(normalized.qualification_reasons) or "unknown"
                raise StateLawsProductionRunnerError(
                    f"normalized receipt is not admission eligible: {reasons}"
                )
            if normalized.qualification_reasons:
                raise StateLawsProductionRunnerError(
                    "normalized receipt retained qualification reasons"
                )
            if normalized.input_row_count < 1:
                raise StateLawsProductionRunnerError(
                    "canonical JSON-LD contains no statute rows"
                )
            if normalized.expected_row_count != normalized.input_row_count:
                raise StateLawsProductionRunnerError(
                    "normalized receipt row count does not match canonical JSON-LD"
                )
            adapters.append(adapter)
            source_receipts.append(normalized.record)
        except (OSError, TypeError, ValueError) as exc:
            failures[code] = f"{type(exc).__name__}: {exc}"

    if failures:
        detail = "; ".join(f"{code}={failures[code]}" for code in sorted(failures))
        raise StateLawsProductionRunnerError(
            f"exact-51 adapter preflight failed for {len(failures)} jurisdiction(s): "
            f"{detail}"
        )
    if len(adapters) != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsProductionRunnerError(
            "adapter preflight did not produce exactly 51 adapters"
        )

    receipt_ids = [item.receipt_id for item in source_receipts]
    receipt_paths = [item.relative_path for item in source_receipts]
    if len(receipt_ids) != len(set(receipt_ids)):
        raise StateLawsProductionRunnerError(
            "normalized source receipts contain duplicate receipt_id values"
        )
    if len(receipt_paths) != len(set(receipt_paths)):
        raise StateLawsProductionRunnerError(
            "normalized source receipts contain duplicate relative_path values"
        )
    try:
        validate_release_rights_receipt(
            rights_receipt,
            source_receipt_ids=receipt_ids,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsProductionRunnerError(
            f"source-rights receipt failed the shared local-release gate: {exc}"
        ) from exc

    return PreparedStateLawsInputs(
        input_map_path=manifest_path,
        input_map_sha256=manifest_sha256,
        bindings=bindings,
        adapters=tuple(adapters),
        source_receipts=tuple(source_receipts),
        rights_receipt_path=rights_path,
        rights_receipt_sha256=rights_sha256,
        rights_receipt=rights_receipt,
        canonical_row_count=sum(
            adapter.source_receipt.input_row_count for adapter in adapters
        ),
        current_source_software_versions=required_versions,
    )


def reverify_prepared_inputs(prepared: PreparedStateLawsInputs) -> None:
    """Perform the last no-write identity check before output construction."""

    _, _, input_map_sha256 = _read_json_object_once(
        prepared.input_map_path,
        label="input map precommit recheck",
    )
    if input_map_sha256 != prepared.input_map_sha256:
        raise StateLawsProductionRunnerError(
            "input map changed after exact-51 preflight"
        )
    _, _, rights_sha256 = _read_json_object_once(
        prepared.rights_receipt_path,
        label="source-rights receipt precommit recheck",
    )
    if rights_sha256 != prepared.rights_receipt_sha256:
        raise StateLawsProductionRunnerError(
            "source-rights receipt changed after exact-51 preflight"
        )
    current_versions = normalize_exact_51_source_software_versions(
        registered_exact_51_source_software_versions()
    )
    if current_versions != dict(prepared.current_source_software_versions):
        raise StateLawsProductionRunnerError(
            "current exact-51 scraper source identities changed after preflight"
        )
    verified_receipts = reverify_exact_51_input_bindings(prepared.bindings)
    if tuple(item.to_dict() for item in verified_receipts) != tuple(
        item.to_dict() for item in prepared.source_receipts
    ):
        raise StateLawsProductionRunnerError(
            "normalized source receipts changed after exact-51 preflight"
        )


def iter_exact_51_adapter_events(
    adapters: Sequence[LegacyStateLawsV2Adapter],
) -> Iterator[Any]:
    """Yield each adapter once and close its count/disposition contract."""

    if len(adapters) != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsProductionRunnerError(
            "event stream requires exactly 51 preflighted adapters"
        )
    observed = tuple(adapter.jurisdiction for adapter in adapters)
    if observed != tuple(CANONICAL_JURISDICTION_ORDER):
        raise StateLawsProductionRunnerError(
            "adapter event stream is not in canonical exact-51 order"
        )
    for adapter in adapters:
        checkpoint = adapter.new_checkpoint()
        for event in adapter.iter_events():
            yield event
            checkpoint = checkpoint.advance(event)
        adapter.finalize_checkpoint(checkpoint)


def pinned_embedding_config(
    *,
    device: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    probe_device: bool = True,
) -> OpenUsLawEmbeddingConfig:
    """Select real pinned GTE-small inference on an explicit CPU/CUDA device."""

    selected = str(device or "").strip().lower()
    if selected not in _SUPPORTED_EMBEDDING_DEVICES:
        raise StateLawsProductionRunnerError(
            "embedding device must be exactly 'cpu' or 'cuda'"
        )
    if probe_device and not device_is_available(selected):
        raise StateLawsProductionRunnerError(
            f"requested embedding device {selected!r} is unavailable; "
            "choose --embedding-device cpu or make CUDA available"
        )
    try:
        config = replace(
            default_embedding_config(),
            device=selected,
            device_fallback=DeviceFallbackPolicy.BLOCK,
            batch_size=batch_size,
        )
    except (TypeError, ValueError) as exc:
        raise StateLawsProductionRunnerError(
            f"invalid pinned embedding configuration: {exc}"
        ) from exc
    if (
        config.may_authorize_release is not True
        or config.model_id != PINNED_MODEL_ID
        or config.model_revision != PINNED_MODEL_REVISION
        or config.dimension != PINNED_DIMENSION
        or config.max_tokens != PINNED_MAX_TOKENS
    ):
        raise StateLawsProductionRunnerError(
            "embedding configuration drifted from the sealed real GTE-small pin"
        )
    return config


def assert_local_only_contract() -> None:
    """Refuse to run if the reused orchestrator ever gains mutation authority."""

    if not (
        LOCAL_ONLY
        and not AUTHORIZES_PUBLICATION
        and not AUTHORIZES_HUB_UPLOAD
        and not PERFORMS_NETWORK_IO
        and ORCHESTRATOR_LOCAL_ONLY
        and not ORCHESTRATOR_AUTHORIZES_PUBLICATION
        and not ORCHESTRATOR_AUTHORIZES_HUB_UPLOAD
        and not ORCHESTRATOR_PERFORMS_NETWORK_IO
    ):
        raise StateLawsProductionRunnerError(
            "local-only safety contract is not sealed; refusing to run"
        )


def _exact_aggregate_release_point(value: Any) -> str:
    """Apply the aggregate release-point contract used by the orchestrator."""

    text = str(value or "").strip()
    if (
        not text
        or "\x00" in text
        or text.lower()
        in {
            "head",
            "latest",
            "main",
            "master",
        }
    ):
        raise StateLawsProductionRunnerError(
            "release_point must be an exact immutable aggregate identity"
        )
    return text


def _preflight_payload(
    prepared: PreparedStateLawsInputs,
    *,
    embedding_config: OpenUsLawEmbeddingConfig,
    source_revision: str,
    aggregate_release_point: str,
) -> dict[str, Any]:
    return {
        "aggregate_release_point": aggregate_release_point,
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "canonical_row_count": prepared.canonical_row_count,
        "embedding": {
            "batch_size": embedding_config.batch_size,
            "device": embedding_config.device,
            "device_fallback": embedding_config.device_fallback.value,
            "dimension": embedding_config.dimension,
            "max_tokens": embedding_config.max_tokens,
            "model_id": embedding_config.model_id,
            "model_revision": embedding_config.model_revision,
        },
        "input_map_path": str(prepared.input_map_path),
        "jurisdiction_count": len(prepared.bindings),
        "jurisdictions": [item.jurisdiction for item in prepared.bindings],
        "local_only": True,
        "network_io_performed": False,
        "rights_receipt_path": str(prepared.rights_receipt_path),
        "schema_version": SCHEMA_VERSION,
        "source_acquisition_release_points": {
            item.jurisdiction: item.release_point for item in prepared.source_receipts
        },
        "source_receipts_digest": production_source_receipts_digest(
            prepared.source_receipts
        ),
        "source_receipt_count": len(prepared.source_receipts),
        "source_revision": source_revision,
        "source_provenance_verifier": (
            state_laws_source_provenance_verifier_attestation()
        ),
        "source_software_current_bundle_required": bool(
            prepared.current_source_software_versions
        ),
        "current_source_software_versions": dict(
            prepared.current_source_software_versions
        ),
        "current_source_software_versions_digest": (
            digest_mapping(dict(prepared.current_source_software_versions))
            if prepared.current_source_software_versions
            else None
        ),
        "status": "preflight_passed",
    }


def _resolved_checkpoint_path(
    output_root: str | Path,
    checkpoint_path: str | Path | None,
) -> Path | None:
    if checkpoint_path in (None, ""):
        return None
    selected = Path(checkpoint_path).expanduser()
    if not selected.is_absolute():
        selected = Path(output_root).expanduser() / selected
    return selected.resolve()


def run_local_production_release(
    *,
    input_map_path: str | Path,
    rights_receipt_path: str | Path,
    source_revision: str,
    release_point: str,
    output_root: str | Path,
    embedding_device: str = "cpu",
    embedding_batch_size: int = DEFAULT_BATCH_SIZE,
    checkpoint_path: str | Path | None = None,
    resume: bool = True,
    preflight_only: bool = False,
) -> dict[str, Any]:
    """Run one local build after an exact-51, no-write input preflight."""

    assert_local_only_contract()
    try:
        immutable_source_revision = require_immutable_revision(
            source_revision, name="source_revision"
        )
        aggregate_release_point = _exact_aggregate_release_point(release_point)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise StateLawsProductionRunnerError(
            f"build identity is not immutable: {exc}"
        ) from exc
    prepared = prepare_exact_51_inputs(
        input_map_path=input_map_path,
        rights_receipt_path=rights_receipt_path,
    )
    embedding_config = pinned_embedding_config(
        device=embedding_device,
        batch_size=embedding_batch_size,
    )
    preflight = _preflight_payload(
        prepared,
        embedding_config=embedding_config,
        source_revision=immutable_source_revision,
        aggregate_release_point=aggregate_release_point,
    )
    if preflight_only:
        return preflight

    # This is deliberately the final operation before the output-capable
    # orchestrator is invoked.  It reopens the map, roots, selected artifacts,
    # receipts, and seals and proves that the refresh runner is still the one
    # bound by every run-final seal.
    reverify_prepared_inputs(prepared)
    events: Iterable[Any] = iter_exact_51_adapter_events(prepared.adapters)
    result = build_state_laws_production_release(
        events,
        source_receipts=prepared.source_receipts,
        rights_receipt=prepared.rights_receipt,
        source_revision=immutable_source_revision,
        release_point=aggregate_release_point,
        output_root=output_root,
        embedding_config=embedding_config,
        checkpoint_path=_resolved_checkpoint_path(output_root, checkpoint_path),
        resume=resume,
    )
    if (
        result.local_only is not True
        or result.authorizes_publication is not False
        or result.authorizes_hub_upload is not False
        or result.network_io_performed is not False
    ):
        raise StateLawsProductionRunnerError(
            "orchestrator returned a result outside the local-only safety contract"
        )
    return {
        **preflight,
        "build": result.to_dict(),
        "output_root": result.output_root,
        "status": "complete",
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the exact-51 canonical state-law corpus, GTE-small vectors, "
            "BM25, BM25-bound graph, centroids, and local manifest. This command "
            "has no upload or publication operation."
        )
    )
    parser.add_argument(
        "--input-map",
        required=True,
        help=(
            "Exact-51 JSON mapping each jurisdiction to STATE-XX.jsonld and its "
            "normalized source-receipt JSON"
        ),
    )
    parser.add_argument(
        "--rights-receipt",
        required=True,
        help="Passed source-rights compliance receipt JSON",
    )
    parser.add_argument(
        "--source-revision",
        required=True,
        help="Immutable source revision (for example, an exact Git commit SHA)",
    )
    parser.add_argument(
        "--release-point",
        required=True,
        help=(
            "Exact immutable aggregate release identity. Each normalized source "
            "receipt retains its own jurisdiction-specific acquisition pin."
        ),
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Local production artifact root; no remote target is accepted",
    )
    parser.add_argument(
        "--checkpoint-path",
        default="",
        help=(
            "Optional orchestrator checkpoint below output-root. Relative paths "
            "are resolved below output-root; the canonical default is used when omitted."
        ),
    )
    parser.add_argument(
        "--embedding-device",
        choices=sorted(_SUPPORTED_EMBEDDING_DEVICES),
        default="cpu",
        help="Pinned GTE-small inference device (default: cpu; CUDA never silently falls back)",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Pinned GTE-small inference batch size (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        default=True,
        help=(
            "Require that no orchestrator checkpoint exists and disable stage "
            "resume; this never deletes prior artifacts"
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Reverify exact-51 files, receipts, rights, and device without creating output",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_local_production_release(
            input_map_path=args.input_map,
            rights_receipt_path=args.rights_receipt,
            source_revision=args.source_revision,
            release_point=args.release_point,
            output_root=args.output_root,
            embedding_device=args.embedding_device,
            embedding_batch_size=args.embedding_batch_size,
            checkpoint_path=args.checkpoint_path or None,
            resume=args.resume,
            preflight_only=args.preflight_only,
        )
    except KeyboardInterrupt:
        print(
            "state-law production run interrupted; rerun with resume enabled",
            file=sys.stderr,
        )
        return 130
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"state-law production run failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    print(canonical_json_dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
