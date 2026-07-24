"""Frozen A0 baseline validation and execution.

The A0 arm is deliberately smaller than the later ablation runner.  It records
and replays the exact production modal-codec entry point that existed when the
benchmark protocol was frozen.  Validation is dependency-free and read-only;
the production codec is imported only when an operator requests execution.
"""

from __future__ import annotations

if __package__ in {None, ""}:  # Support the documented ``python path/to/file`` CLI.
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
from dataclasses import dataclass
import hashlib
from importlib import metadata as distribution_metadata
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence

from benchmarks.logic_pipeline import BENCHMARK_ID, DEFAULT_BENCHMARK_ROOT
from benchmarks.logic_pipeline.adapters import (
    CompilerAdapter,
    StageOutput,
    StageRequest,
)
from benchmarks.logic_pipeline.cases import (
    BenchmarkCase,
    FROZEN_SPLIT_SHA256,
    Split,
    build_split_integrity_manifest,
    load_reviewed_corpus,
)
from benchmarks.logic_pipeline.contracts import (
    BASELINE_VARIANT,
    CASE_RESULT_SCHEMA,
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    CacheMode,
    CacheScope,
    CaseResultRecord,
    FailureCode,
    ResourceLane,
    RunContract,
    StageName,
    StageStatus,
    TELEMETRY_SCHEMA,
    TelemetryRecord,
    canonical_json,
)
from benchmarks.logic_pipeline.ablation import (
    ABLATION_PLAN_SCHEMA,
    ABLATION_RESULT_SCHEMA,
    ORDERING_ALGORITHM,
    AblationCase,
    AblationPlan,
    AblationRunResult,
    AblationRunnerError,
    AblationValidationError,
    ResourceLimits,
    ScheduledCase,
    build_ablation_plan,
    execute_ablation,
)
from benchmarks.logic_pipeline.capabilities import (
    BoundedProcessResult,
    ResourceClass,
    ResourceLease,
    ResourceLeaseCancelled,
    ResourceLeaseError,
    ResourceLeaseReceipt,
    ResourceLeaseRequest,
    ResourceLeaseTimeout,
    ResourcePolicy,
    ResourceScheduler,
    run_bounded_process_group,
)


BASELINE_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.frozen-baseline-manifest.v1"
)
BASELINE_EXECUTION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.baseline-execution.v1"
)
BASELINE_CODEC_OUTPUT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.current-codec-output.v1"
)
BASELINE_ID: Final = "a0-current-effective-v1"
BASELINE_RUN_ID: Final = "a0-baseline-v1"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
FROZEN_BASELINE_ROOT: Final = DEFAULT_BENCHMARK_ROOT / BASELINE_RUN_ID
DEFAULT_BASELINE_MANIFEST_PATH: Final = (
    FROZEN_BASELINE_ROOT / "state" / "baseline-manifest.json"
)
CURRENT_ROUTE: Final = (
    "ipfs_datasets_py.logic.modal.codec.DeterministicModalLogicCodec.encode",
)
CURRENT_ROUTE_COMPONENTS: Final = (
    "deterministic_modal_compiler",
    "spacy_linguistic_encoder",
    "bm25_frame_selector",
    "flogic_consistency_check",
    "deterministic_modal_decompiler",
)
OUT_OF_ROUTE_COMPONENTS: Final = ("symai", "hammer", "leanstral")
SOURCE_SNAPSHOT_FILES: Final = (
    "ipfs_datasets_py/logic/modal/codec.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
)
TELEMETRY_FIELDS: Final = tuple(TelemetryRecord.__dataclass_fields__)
FROZEN_BASELINE_MANIFEST_SHA256: Final = (
    "6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156"
)

_HEX_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class BaselineValidationError(ValueError):
    """Raised when the frozen A0 snapshot or an execution violates its contract."""


def HSSLEV0404E6E() -> str:
    """Return the AST-verifiable evidence for the frozen A0 baseline."""

    return (
        "frozen measured A0 baseline with immutable cases, isolated cold and "
        "warm caches, complete telemetry, and explicit spaCy fallback identity"
    )


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BaselineValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _decode_json(text: str, context: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except BaselineValidationError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise BaselineValidationError(f"{context} is not strict JSON: {exc}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise BaselineValidationError(f"{field} must be a JSON object")
    return value


def _array(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise BaselineValidationError(f"{field} must be an array")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise BaselineValidationError(
            f"{field} fields invalid: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(value[key]) for key in sorted(value)}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class FrozenBaselineManifest:
    """Deeply immutable, canonically serialized A0 snapshot."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        validate_baseline_manifest_payload(self.payload)
        object.__setattr__(self, "payload", _freeze(self.payload))

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())

    @property
    def run_contracts(self) -> tuple[RunContract, ...]:
        raw = _array(self.payload["run_contracts"], "run_contracts")
        return tuple(RunContract.from_dict(item) for item in raw)

    @property
    def pilot_case_ids(self) -> tuple[str, ...]:
        corpus = _mapping(self.payload["corpus"], "corpus")
        cases = _array(corpus["cases"], "corpus.cases")
        return tuple(
            str(_mapping(item, "corpus.cases[]")["case_id"]) for item in cases
        )

    def to_dict(self) -> dict[str, object]:
        value = _thaw(self.payload)
        if not isinstance(value, dict):  # pragma: no cover - guarded at creation
            raise BaselineValidationError("manifest payload is not an object")
        return value


def _validate_source_snapshot(source: Mapping[str, object]) -> None:
    _exact_keys(source, {"repository_commit", "submodules", "files"}, "source")
    revision = source["repository_commit"]
    if not isinstance(revision, str) or not _HEX_REVISION.fullmatch(revision):
        raise BaselineValidationError("source.repository_commit is not a full revision")

    submodules = _array(source["submodules"], "source.submodules")
    frozen_submodules: list[tuple[str, str]] = []
    previous_path = ""
    for item in submodules:
        record = _mapping(item, "source.submodules[]")
        _exact_keys(record, {"path", "commit"}, "source.submodules[]")
        path, commit = record["path"], record["commit"]
        if (
            not isinstance(path, str)
            or not path
            or path <= previous_path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise BaselineValidationError(
                "source.submodules must use unique sorted relative paths"
            )
        if not isinstance(commit, str) or not _HEX_REVISION.fullmatch(commit):
            raise BaselineValidationError("submodule commit is not a full revision")
        frozen_submodules.append((path, commit))
        previous_path = path

    files = _array(source["files"], "source.files")
    paths: list[str] = []
    for item in files:
        record = _mapping(item, "source.files[]")
        _exact_keys(record, {"path", "sha256"}, "source.files[]")
        path, digest = record["path"], record["sha256"]
        if not isinstance(path, str) or not isinstance(digest, str):
            raise BaselineValidationError("source file identity must be strings")
        if not _SHA256.fullmatch(digest):
            raise BaselineValidationError("source file digest is not SHA-256")
        paths.append(path)
        local_path = REPOSITORY_ROOT / path
        try:
            actual = _sha256_bytes(local_path.read_bytes())
        except OSError as exc:
            raise BaselineValidationError(
                f"cannot read pinned source file {path}: {exc}"
            ) from exc
        if actual != digest:
            raise BaselineValidationError(f"pinned source file drifted: {path}")
    if tuple(paths) != SOURCE_SNAPSHOT_FILES:
        raise BaselineValidationError("source.files does not bind the exact A0 route")

    try:
        commit_check = subprocess.run(
            ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        gitlinks = subprocess.run(
            ["git", "ls-tree", "-r", "-z", revision],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BaselineValidationError(
            f"cannot verify pinned Git identities: {exc}"
        ) from exc
    if commit_check.returncode:
        raise BaselineValidationError(
            "source.repository_commit is not available in this repository"
        )
    actual_submodules: list[tuple[str, str]] = []
    for entry in gitlinks.stdout.split("\0"):
        if not entry:
            continue
        header, separator, path = entry.partition("\t")
        fields = header.split()
        if not separator or len(fields) != 3:
            raise BaselineValidationError(
                "Git returned a malformed entry for the pinned source commit"
            )
        mode, object_type, object_id = fields
        if mode == "160000":
            if object_type != "commit" or not _HEX_REVISION.fullmatch(object_id):
                raise BaselineValidationError(
                    "pinned source commit has a malformed submodule gitlink"
                )
            actual_submodules.append((path, object_id))
    if frozen_submodules != actual_submodules:
        raise BaselineValidationError("recorded submodule gitlinks drifted")


def _validate_corpus_snapshot(corpus_value: Mapping[str, object]) -> None:
    _exact_keys(
        corpus_value,
        {
            "corpus_id",
            "manifest_sha256",
            "split",
            "split_sha256",
            "cases",
        },
        "corpus",
    )
    if corpus_value["split"] != Split.PILOT.value:
        raise BaselineValidationError("frozen baseline corpus must be the pilot split")
    reviewed = load_reviewed_corpus()
    integrity = build_split_integrity_manifest(reviewed)
    if corpus_value["corpus_id"] != reviewed.manifest.corpus_id:
        raise BaselineValidationError("frozen corpus id drifted")
    if corpus_value["manifest_sha256"] != reviewed.manifest_sha256:
        raise BaselineValidationError("frozen corpus manifest digest drifted")
    pilot = next(item for item in integrity.splits if item.split is Split.PILOT)
    if corpus_value["split_sha256"] != pilot.split_sha256:
        raise BaselineValidationError("frozen pilot split digest drifted")
    if corpus_value["split_sha256"] != FROZEN_SPLIT_SHA256[Split.PILOT]:
        raise BaselineValidationError("pilot split is not revision 1")

    actual_cases = tuple(
        case for case in reviewed.cases if case.split is Split.PILOT
    )
    frozen_cases = _array(corpus_value["cases"], "corpus.cases")
    expected = [
        {
            "case_id": case.case_id,
            "case_sha256": next(
                entry.case_sha256
                for entry in reviewed.manifest.cases
                if entry.case_id == case.case_id
            ),
            "source_sha256": case.source_sha256,
        }
        for case in actual_cases
    ]
    if list(frozen_cases) != expected:
        raise BaselineValidationError(
            "pilot case membership, order, or content identity drifted"
        )


def _validate_configuration(configuration: Mapping[str, object]) -> None:
    _exact_keys(
        configuration,
        {
            "requested_variant_id",
            "effective_variant_id",
            "requested",
            "effective",
            "route",
            "configuration_sha256",
        },
        "configuration",
    )
    if (
        configuration["requested_variant_id"] != BASELINE_VARIANT
        or configuration["effective_variant_id"] != BASELINE_VARIANT
    ):
        raise BaselineValidationError("baseline cannot silently substitute an arm")
    requested = _mapping(configuration["requested"], "configuration.requested")
    effective = _mapping(configuration["effective"], "configuration.effective")
    route = _mapping(configuration["route"], "configuration.route")
    _exact_keys(
        route,
        {"entrypoints", "components", "components_not_invoked"},
        "configuration.route",
    )
    if tuple(_array(route["entrypoints"], "route.entrypoints")) != CURRENT_ROUTE:
        raise BaselineValidationError("A0 entrypoint is not the frozen current route")
    if tuple(_array(route["components"], "route.components")) != CURRENT_ROUTE_COMPONENTS:
        raise BaselineValidationError("A0 component allowlist drifted")
    if tuple(
        _array(route["components_not_invoked"], "route.components_not_invoked")
    ) != OUT_OF_ROUTE_COMPONENTS:
        raise BaselineValidationError("A0 out-of-route component list drifted")
    if set(route["components"]) & set(route["components_not_invoked"]):  # type: ignore[arg-type]
        raise BaselineValidationError("a component is both enabled and forbidden")

    expected_requested = {
        "embedding_dimensions": 8,
        "flogic_similarity_threshold": 0.0,
        "frame_domain": None,
        "ontology_name": "modal_legal_ontology",
        "parser_backend": "spacy",
        "spacy_model_name": "en_core_web_sm",
        "top_k_frames": 3,
        "use_flogic": True,
    }
    if dict(requested) != expected_requested:
        raise BaselineValidationError("requested A0 codec configuration drifted")
    _exact_keys(
        effective,
        {
            "parser_backend",
            "spacy_requested_model",
            "spacy_effective_model",
            "spacy_mode",
            "spacy_pipeline",
            "spacy_version",
            "spacy_used_fallback_model",
            "llm_call_count",
        },
        "configuration.effective",
    )
    if (
        effective["parser_backend"] != "spacy"
        or effective["spacy_requested_model"] != requested["spacy_model_name"]
        or effective["spacy_effective_model"] != "spacy.blank:en"
        or effective["spacy_mode"] != "blank_model"
        or effective["spacy_pipeline"] != ["sentencizer"]
        or effective["spacy_version"] != "3.8.14"
        or effective["spacy_used_fallback_model"] is not True
        or effective["llm_call_count"] != 0
    ):
        raise BaselineValidationError(
            "effective A0 spaCy identity or fallback observation drifted"
        )
    identity = {
        "requested": dict(requested),
        "effective": dict(effective),
        "route": dict(route),
    }
    if configuration["configuration_sha256"] != _sha256_json(identity):
        raise BaselineValidationError("configuration digest does not match contents")


def _validate_run_contracts(
    raw_contracts: Sequence[object],
    *,
    corpus_manifest_sha256: str,
    configuration_sha256: str,
) -> None:
    contracts = tuple(RunContract.from_dict(item) for item in raw_contracts)
    if tuple(contract.cache_mode for contract in contracts) != (
        CacheMode.COLD,
        CacheMode.WARM,
    ):
        raise BaselineValidationError("A0 must freeze cold then warm cache modes")
    for contract in contracts:
        if (
            contract.run_id != BASELINE_RUN_ID
            or contract.protocol_sha256 != DEFAULT_PROTOCOL_SHA256
            or contract.requested_variant_id != BASELINE_VARIANT
            or contract.effective_variant_id != BASELINE_VARIANT
            or contract.split is not Split.PILOT
            or contract.case_manifest_sha256 != corpus_manifest_sha256
            or contract.configuration_sha256 != configuration_sha256
            or not contract.prompts_frozen
            or not contract.policy_frozen
            or not contract.model_identities_frozen
            or not contract.thresholds_frozen
            or contract.tuning_permitted
        ):
            raise BaselineValidationError("frozen A0 run contract drifted")
        expected_namespace = CacheScope(
            BASELINE_RUN_ID,
            DEFAULT_PROTOCOL_SHA256,
            BASELINE_VARIANT,
            Split.PILOT,
            contract.cache_mode,
        ).namespace
        if contract.cache_namespace != expected_namespace:
            raise BaselineValidationError("A0 cache namespace is not isolated")
    if contracts[0].cache_namespace == contracts[1].cache_namespace:
        raise BaselineValidationError("cold and warm cache namespaces collide")


def validate_baseline_manifest_payload(value: object) -> None:
    """Validate every frozen identity without importing an optional backend."""

    payload = _mapping(value, "baseline manifest")
    _exact_keys(
        payload,
        {
            "schema",
            "benchmark_id",
            "baseline_id",
            "evidence",
            "frozen",
            "source",
            "protocol",
            "corpus",
            "configuration",
            "capability_snapshot",
            "run_contracts",
            "telemetry_contract",
            "execution_contract",
            "safety",
        },
        "baseline manifest",
    )
    if payload["schema"] != BASELINE_MANIFEST_SCHEMA:
        raise BaselineValidationError("unsupported baseline-manifest schema")
    if payload["benchmark_id"] != BENCHMARK_ID or payload["baseline_id"] != BASELINE_ID:
        raise BaselineValidationError("baseline identity drifted")
    if payload["evidence"] != HSSLEV0404E6E() or payload["frozen"] is not True:
        raise BaselineValidationError("baseline evidence is absent or not frozen")

    _validate_source_snapshot(_mapping(payload["source"], "source"))
    protocol = _mapping(payload["protocol"], "protocol")
    _exact_keys(protocol, {"protocol_id", "sha256"}, "protocol")
    if (
        protocol["protocol_id"] != DEFAULT_PROTOCOL.protocol_id
        or protocol["sha256"] != DEFAULT_PROTOCOL_SHA256
    ):
        raise BaselineValidationError("baseline protocol identity drifted")

    corpus = _mapping(payload["corpus"], "corpus")
    _validate_corpus_snapshot(corpus)
    configuration = _mapping(payload["configuration"], "configuration")
    _validate_configuration(configuration)

    capability = _mapping(payload["capability_snapshot"], "capability_snapshot")
    _exact_keys(
        capability,
        {"requested", "effective", "status", "provenance", "sha256"},
        "capability_snapshot",
    )
    capability_body = {
        key: capability[key]
        for key in ("requested", "effective", "status", "provenance")
    }
    if capability["sha256"] != _sha256_json(capability_body):
        raise BaselineValidationError("capability snapshot digest is invalid")
    if capability["status"] != "degraded":
        raise BaselineValidationError("blank fallback must remain explicit degradation")

    _validate_run_contracts(
        _array(payload["run_contracts"], "run_contracts"),
        corpus_manifest_sha256=str(corpus["manifest_sha256"]),
        configuration_sha256=str(configuration["configuration_sha256"]),
    )

    telemetry = _mapping(payload["telemetry_contract"], "telemetry_contract")
    _exact_keys(
        telemetry,
        {
            "schema",
            "required_fields",
            "spacy_identity_fields",
            "per_stage",
        },
        "telemetry_contract",
    )
    if (
        telemetry["schema"] != TELEMETRY_SCHEMA
        or telemetry["per_stage"] is not True
        or tuple(_array(telemetry["required_fields"], "required_fields"))
        != TELEMETRY_FIELDS
        or tuple(
            _array(telemetry["spacy_identity_fields"], "spacy_identity_fields")
        )
        != (
            "spacy_requested_model",
            "spacy_effective_model",
            "spacy_used_fallback_model",
        )
    ):
        raise BaselineValidationError("baseline telemetry contract is incomplete")

    execution = _mapping(payload["execution_contract"], "execution_contract")
    _exact_keys(
        execution,
        {
            "case_result_schema",
            "eligible_case_count_per_cache_mode",
            "expected_result_count",
            "result_cardinality",
            "executed_stage",
        },
        "execution_contract",
    )
    case_count = len(_array(corpus["cases"], "corpus.cases"))
    if (
        execution["case_result_schema"] != CASE_RESULT_SCHEMA
        or execution["eligible_case_count_per_cache_mode"] != case_count
        or execution["expected_result_count"] != case_count * 2
        or execution["result_cardinality"] != "one_per_case_per_cache_mode"
        or execution["executed_stage"] != StageName.COMPILER.value
    ):
        raise BaselineValidationError("baseline result-cardinality contract drifted")

    safety = _mapping(payload["safety"], "safety")
    _exact_keys(
        safety,
        {
            "shadow_only",
            "network_enabled",
            "model_calls_enabled",
            "auto_merge",
            "production_routing_changes",
        },
        "safety",
    )
    if dict(safety) != {
        "shadow_only": True,
        "network_enabled": False,
        "model_calls_enabled": False,
        "auto_merge": False,
        "production_routing_changes": False,
    }:
        raise BaselineValidationError("A0 safety boundary drifted")


def load_baseline_manifest(
    path: str | Path = DEFAULT_BASELINE_MANIFEST_PATH,
) -> FrozenBaselineManifest:
    """Load the exact canonical checked-in A0 manifest."""

    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineValidationError(
            f"cannot read baseline manifest {manifest_path}: {exc}"
        ) from exc
    if not text.endswith("\n") or not text.strip():
        raise BaselineValidationError(
            "baseline manifest must be nonempty and newline-terminated"
        )
    value = _decode_json(text, "baseline manifest")
    manifest = FrozenBaselineManifest(_mapping(value, "baseline manifest"))
    expected_bytes = (canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
    if raw != expected_bytes:
        raise BaselineValidationError("baseline manifest is not canonical JSON")
    if manifest.digest != FROZEN_BASELINE_MANIFEST_SHA256:
        raise BaselineValidationError(
            "baseline manifest digest does not match the code pin"
        )
    return manifest


def _serialize(value: object) -> object:
    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        return serializer()
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _current_codec_handler(
    codec: object,
    expected_effective: Mapping[str, object],
) -> Callable[[StageRequest], StageOutput]:
    def handler(request: StageRequest) -> StageOutput:
        input_data = _mapping(request.input_data, "stage input")
        text = input_data.get("text")
        if not isinstance(text, str) or not text:
            raise BaselineValidationError("baseline stage requires source text")
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        encode = getattr(codec, "encode", None)
        if not callable(encode):
            raise BaselineValidationError("codec does not expose encode")
        result = encode(
            text,
            document_id=request.case_id,
            source="logic_pipeline_benchmark",
        )
        encoding = getattr(result, "encoding", None)
        metadata = getattr(result, "metadata", {})
        if encoding is None or not isinstance(metadata, Mapping):
            raise BaselineValidationError("current codec result lacks identity telemetry")
        requested_model = str(getattr(encoding, "model_name", ""))
        fallback = bool(getattr(encoding, "used_fallback_model", False))
        effective_model = "spacy.blank:en" if fallback else requested_model
        try:
            spacy_version = distribution_metadata.version("spacy")
        except distribution_metadata.PackageNotFoundError:
            spacy_version = "unavailable"
        modal_ir = _serialize(getattr(result, "modal_ir", {}))
        output = {
            "schema": BASELINE_CODEC_OUTPUT_SCHEMA,
            "source_sha256": _sha256_bytes(text.encode("utf-8")),
            "parser_name": str(getattr(result, "parser_name", "")),
            "modal_ir_sha256": _sha256_json(modal_ir),
            "formula_count": len(getattr(getattr(result, "modal_ir", None), "formulas", ())),
            "token_count": len(getattr(encoding, "tokens", ())),
            "selected_frame": getattr(result, "selected_frame", None),
            "llm_call_count": int(metadata.get("llm_call_count", 0)),
            "spacy_requested_model": requested_model,
            "spacy_effective_model": effective_model,
            "spacy_used_fallback_model": fallback,
        }
        output_bytes = len(canonical_json(output).encode("utf-8"))
        after_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB and macOS bytes.  The benchmark environment is
        # Linux; retain a conservative bounded byte value elsewhere.
        peak_rss = max(before_rss, after_rss)
        if sys.platform != "darwin":
            peak_rss *= 1024
        telemetry = TelemetryRecord(
            wall_time_ms=round((time.perf_counter() - started_wall) * 1000, 6),
            cpu_time_ms=round((time.process_time() - started_cpu) * 1000, 6),
            peak_memory_bytes=int(peak_rss),
            input_items=1,
            output_items=1,
            model_calls=int(output["llm_call_count"]),
            cache_hits=0,
            cache_misses=0,
            retries=0,
            bytes_in=request.input_bytes,
            bytes_out=output_bytes,
            resource_lane=ResourceLane.CPU,
        )
        effective_identity = {
            "entrypoint": CURRENT_ROUTE[0],
            "parser_backend": "spacy",
            "spacy_requested_model": requested_model,
            "spacy_effective_model": effective_model,
            "spacy_used_fallback_model": fallback,
            "spacy_version": spacy_version,
        }
        if (
            requested_model != expected_effective["spacy_requested_model"]
            or effective_model != expected_effective["spacy_effective_model"]
            or fallback is not expected_effective["spacy_used_fallback_model"]
            or spacy_version != expected_effective["spacy_version"]
        ):
            return StageOutput(
                status=StageStatus.UNAVAILABLE,
                effective_identity=effective_identity,
                failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
                failure_detail=(
                    "runtime spaCy identity does not reproduce the frozen A0 "
                    "effective configuration"
                ),
                telemetry=telemetry,
            )
        return StageOutput(
            data=output,
            effective_identity=effective_identity,
            telemetry=telemetry,
        )

    return handler


def _load_current_codec() -> object:
    """Import the frozen production entry point only for a real execution."""

    from ipfs_datasets_py.logic.modal.codec import (  # noqa: PLC0415
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
    )

    return DeterministicModalLogicCodec(ModalLogicCodecConfig())


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise BaselineValidationError(
            f"refusing to overwrite existing baseline output: {path}"
        ) from exc


def _cases_for_manifest(
    manifest: FrozenBaselineManifest,
) -> tuple[BenchmarkCase, ...]:
    reviewed = load_reviewed_corpus()
    by_id = {case.case_id: case for case in reviewed.cases}
    return tuple(by_id[case_id] for case_id in manifest.pilot_case_ids)


def execute_baseline(
    manifest: FrozenBaselineManifest,
    *,
    output_root: str | Path | None = None,
    codec_factory: Callable[[], object] = _load_current_codec,
    cache_modes: Sequence[CacheMode] = (CacheMode.COLD, CacheMode.WARM),
) -> Mapping[str, object]:
    """Execute A0 and emit one strict result per pilot case and cache mode.

    The route consists of one adapter invocation around the existing composite
    modal-codec entry point.  This avoids double-running its internal spaCy
    encoder and, by construction, never invokes SyMAI, Hammer, or Leanstral.
    """

    if manifest.digest != FROZEN_BASELINE_MANIFEST_SHA256:
        raise BaselineValidationError("execution requires the frozen manifest")
    selected_modes = tuple(cache_modes)
    if (
        not selected_modes
        or len(set(selected_modes)) != len(selected_modes)
        or any(mode not in {CacheMode.COLD, CacheMode.WARM} for mode in selected_modes)
    ):
        raise BaselineValidationError("cache_modes must be unique cold/warm values")
    contracts = {
        contract.cache_mode: contract for contract in manifest.run_contracts
    }
    cases = _cases_for_manifest(manifest)
    codec = codec_factory()
    configuration = _mapping(manifest.payload["configuration"], "configuration")
    effective = _mapping(
        configuration["effective"], "configuration.effective"
    )
    adapter = CompilerAdapter(
        _current_codec_handler(codec, effective),
        adapter_id="a0-current-modal-codec",
        source=(CURRENT_ROUTE[0],),
    )
    results: list[CaseResultRecord] = []
    for cache_mode in selected_modes:
        contract = contracts[cache_mode]
        for case in cases:
            request = StageRequest(
                run_id=contract.run_id,
                case_id=case.case_id,
                case_manifest_sha256=contract.case_manifest_sha256,
                variant_id=BASELINE_VARIANT,
                split=Split.PILOT,
                cache_mode=cache_mode,
                input_data={
                    "text": case.source_text,
                    "source_sha256": case.source_sha256,
                },
                requested_identity=configuration["requested"],  # type: ignore[arg-type]
                source=("frozen_corpus", case.case_id),
            )
            stage = adapter.run(request)
            result = CaseResultRecord.from_stages((stage,))
            # Reparse before persistence so malformed output cannot become a
            # durable "measured" baseline record.
            result = CaseResultRecord.from_dict(result.to_dict())
            results.append(result)

    expected = len(cases) * len(selected_modes)
    identities = {(item.case_id, item.cache_mode) for item in results}
    if len(results) != expected or len(identities) != expected:
        raise BaselineValidationError("baseline result cardinality is incomplete")

    destination = (
        Path(output_root)
        if output_root is not None
        else REPOSITORY_ROOT / FROZEN_BASELINE_ROOT
    )
    result_path = destination / "results" / "case-results.jsonl"
    summary_path = destination / "results" / "summary.json"
    encoded_results = "".join(
        canonical_json(result.to_dict()) + "\n" for result in results
    ).encode("utf-8")
    outcome_counts: dict[str, int] = {}
    fallback_observations: set[bool] = set()
    for result in results:
        outcome_counts[result.status.value] = (
            outcome_counts.get(result.status.value, 0) + 1
        )
        stage_data = result.stages[0].data
        if isinstance(stage_data, Mapping) and "spacy_used_fallback_model" in stage_data:
            fallback_observations.add(
                bool(stage_data["spacy_used_fallback_model"])
            )
    summary = {
        "schema": BASELINE_EXECUTION_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "baseline_id": BASELINE_ID,
        "run_id": BASELINE_RUN_ID,
        "variant_id": BASELINE_VARIANT,
        "split": Split.PILOT.value,
        "baseline_manifest_sha256": manifest.digest,
        "cache_modes": [mode.value for mode in selected_modes],
        "case_count_per_cache_mode": len(cases),
        "result_count": len(results),
        "case_results_sha256": _sha256_bytes(encoded_results),
        "result_sha256s": [result.digest for result in results],
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "spacy_fallback_observations": sorted(fallback_observations),
        "components_invoked": list(CURRENT_ROUTE_COMPONENTS),
        "components_not_invoked": list(OUT_OF_ROUTE_COMPONENTS),
    }
    _write_exclusive(result_path, encoded_results)
    try:
        _write_exclusive(
            summary_path, (canonical_json(summary) + "\n").encode("utf-8")
        )
    except Exception:
        # Preserve the case records rather than deleting evidence after a
        # partial durable write; an operator can diagnose and choose a new
        # isolated output root.
        raise
    return MappingProxyType(
        {
            **summary,
            "case_results_path": result_path.as_posix(),
            "summary_path": summary_path.as_posix(),
        }
    )


def HSSLEV0501F2F() -> str:
    """Return the AST-verifiable stage-aware ablation-runner evidence."""

    return (
        "stage-aware A0 through A12 and S1 paired ablations with bounded "
        "resources, seeded block order, isolated caches, and immutable resume"
    )


CACHE_ISOLATION_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.cache-isolation-report.v1"
)


class CacheIsolationError(ValueError):
    """Raised when cache-mode comparison could confound backend or order."""


def HSSLEV0717A46() -> str:
    """Return AST-verifiable evidence for cache and drift isolation."""

    return (
        "run protocol variant split and mode bound cache scopes, pinned "
        "environment drift rejection, and recorded counterbalanced order"
    )


@dataclass(frozen=True, slots=True)
class CacheModePair:
    """Digest-bound cold/warm observations for one case and requested arm."""

    case_id: str
    variant_id: str
    cold_result_sha256: str
    warm_result_sha256: str

    def __post_init__(self) -> None:
        for name in ("case_id", "variant_id"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value
                )
                or value in {".", ".."}
            ):
                raise CacheIsolationError(
                    f"{name} must be a safe benchmark identifier"
                )
        for name in ("cold_result_sha256", "warm_result_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise CacheIsolationError(
                    f"{name} must be a lowercase SHA-256 digest"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name) for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> "CacheModePair":
        if not isinstance(value, Mapping):
            raise CacheIsolationError("cache-mode pair must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise CacheIsolationError(
                "cache-mode pair fields are missing or unknown"
            )
        try:
            return cls(**value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise CacheIsolationError("invalid cache-mode pair") from exc


@dataclass(frozen=True, slots=True)
class CacheIsolationReport:
    """Immutable eligibility receipt for cache-mode comparisons."""

    schema: str
    plan_sha256: str
    environment_sha256: str
    cache_namespaces: tuple[str, ...]
    execution_order: tuple[str, ...]
    position_counts: Mapping[str, tuple[int, ...]]
    pairs: tuple[CacheModePair, ...]

    def __post_init__(self) -> None:
        if self.schema != CACHE_ISOLATION_REPORT_SCHEMA:
            raise CacheIsolationError(
                "unsupported cache-isolation report schema"
            )
        for name in ("plan_sha256", "environment_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise CacheIsolationError(
                    f"{name} must be a lowercase SHA-256 digest"
                )
        namespaces = tuple(self.cache_namespaces)
        if (
            not namespaces
            or any(not isinstance(item, str) or not item for item in namespaces)
            or len(namespaces) != len(set(namespaces))
        ):
            raise CacheIsolationError(
                "cache namespaces must be nonempty and unique"
            )
        object.__setattr__(self, "cache_namespaces", namespaces)
        order = tuple(self.execution_order)
        if (
            not order
            or any(not isinstance(item, str) or not item for item in order)
            or len(order) != len(set(order))
        ):
            raise CacheIsolationError(
                "execution order must contain distinct recorded jobs"
            )
        object.__setattr__(self, "execution_order", order)
        frozen_counts: dict[str, tuple[int, ...]] = {}
        for variant, counts in sorted(self.position_counts.items()):
            if (
                not isinstance(variant, str)
                or not variant
                or not isinstance(counts, (list, tuple))
                or not counts
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or item < 0
                    for item in counts
                )
                or max(counts) - min(counts) > 1
            ):
                raise CacheIsolationError(
                    "position counts must prove counterbalanced arm order"
                )
            frozen_counts[variant] = tuple(counts)
        object.__setattr__(
            self, "position_counts", MappingProxyType(frozen_counts)
        )
        pairs = tuple(self.pairs)
        if not pairs or any(not isinstance(item, CacheModePair) for item in pairs):
            raise CacheIsolationError(
                "cache report must contain cold/warm pairs"
            )
        identities = {(item.case_id, item.variant_id) for item in pairs}
        if len(identities) != len(pairs):
            raise CacheIsolationError(
                "cache report must not contain duplicate cold/warm pairs"
            )
        object.__setattr__(self, "pairs", pairs)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "plan_sha256": self.plan_sha256,
            "environment_sha256": self.environment_sha256,
            "cache_namespaces": list(self.cache_namespaces),
            "execution_order": list(self.execution_order),
            "position_counts": {
                key: list(value)
                for key, value in self.position_counts.items()
            },
            "pairs": [item.to_dict() for item in self.pairs],
        }

    @classmethod
    def from_dict(cls, value: object) -> "CacheIsolationReport":
        if not isinstance(value, Mapping):
            raise CacheIsolationError(
                "cache-isolation report must be an object"
            )
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise CacheIsolationError(
                "cache-isolation report fields are missing or unknown"
            )
        namespaces = value["cache_namespaces"]
        order = value["execution_order"]
        counts = value["position_counts"]
        pairs = value["pairs"]
        if (
            not isinstance(namespaces, (list, tuple))
            or not isinstance(order, (list, tuple))
            or not isinstance(counts, Mapping)
            or not isinstance(pairs, (list, tuple))
        ):
            raise CacheIsolationError(
                "cache-isolation report collections are invalid"
            )
        try:
            return cls(
                schema=value["schema"],  # type: ignore[arg-type]
                plan_sha256=value["plan_sha256"],  # type: ignore[arg-type]
                environment_sha256=value["environment_sha256"],  # type: ignore[arg-type]
                cache_namespaces=tuple(namespaces),  # type: ignore[arg-type]
                execution_order=tuple(order),  # type: ignore[arg-type]
                position_counts=counts,  # type: ignore[arg-type]
                pairs=tuple(CacheModePair.from_dict(item) for item in pairs),
            )
        except TypeError as exc:
            raise CacheIsolationError(
                "invalid cache-isolation report"
            ) from exc

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()


def validate_cache_isolation(
    execution: AblationRunResult,
) -> CacheIsolationReport:
    """Reject cache comparisons with missing pairs, drift, or order bias.

    The check deliberately requires a pinned environment.  Cache namespaces
    alone cannot distinguish a changed model, solver, or backend operating
    under the same requested arm.
    """

    if not isinstance(execution, AblationRunResult) or not execution.complete:
        raise CacheIsolationError(
            "execution must be a complete AblationRunResult"
        )
    plan = execution.plan
    if plan.environment_sha256 is None:
        raise CacheIsolationError(
            "cache comparison requires a pinned environment identity"
        )
    if set(plan.cache_modes) != {CacheMode.COLD, CacheMode.WARM}:
        raise CacheIsolationError(
            "cache comparison requires separate cold and warm modes"
        )
    namespaces = tuple(
        contract.cache_namespace for contract in execution.contracts
    )
    if len(namespaces) != len(set(namespaces)):
        raise CacheIsolationError("cache namespaces collide")
    expected_namespaces = {
        CacheScope(
            plan.run_id,
            plan.protocol_sha256,
            variant,
            plan.split,
            mode,
        ).namespace
        for variant in plan.variant_ids
        for mode in plan.cache_modes
    }
    if set(namespaces) != expected_namespaces:
        raise CacheIsolationError(
            "cache namespaces do not bind the complete execution identity"
        )

    jobs_by_identity = {
        (job.case.case_id, job.variant_id, job.cache_mode): job
        for job in plan.jobs
    }
    results_by_identity = {
        (result.case_id, result.variant_id, result.cache_mode): result
        for result in execution.results
    }
    if set(jobs_by_identity) != set(results_by_identity):
        raise CacheIsolationError(
            "cache results do not match the recorded schedule"
        )
    pairs: list[CacheModePair] = []
    for case_id in plan.case_ids:
        for variant in plan.variant_ids:
            cold = results_by_identity[(case_id, variant, CacheMode.COLD)]
            warm = results_by_identity[(case_id, variant, CacheMode.WARM)]
            if (
                cold.receipt is None
                or warm.receipt is None
                or cold.receipt.environment_sha256
                != plan.environment_sha256
                or warm.receipt.environment_sha256
                != plan.environment_sha256
            ):
                raise CacheIsolationError(
                    "result environment drifted from the pinned plan"
                )
            cold_route = tuple(stage.stage for stage in cold.stages)
            warm_route = tuple(stage.stage for stage in warm.stages)
            if cold_route != warm_route:
                raise CacheIsolationError(
                    "cold and warm results executed different routes"
                )
            for cold_stage, warm_stage in zip(cold.stages, warm.stages):
                if (
                    cold_stage.provenance.requested_identity
                    != warm_stage.provenance.requested_identity
                    or cold_stage.provenance.effective_identity
                    != warm_stage.provenance.effective_identity
                ):
                    raise CacheIsolationError(
                        "backend, model, or solver identity drifted across modes"
                    )
            pairs.append(
                CacheModePair(
                    case_id,
                    variant,
                    cold.digest,
                    warm.digest,
                )
            )

    position_counts = {
        variant: [0 for _ in plan.variant_ids]
        for variant in plan.variant_ids
    }
    for block in plan.blocks:
        for position, job in enumerate(block):
            position_counts[job.variant_id][position] += 1
    if any(
        max(counts) - min(counts) > 1
        for counts in position_counts.values()
    ):
        raise CacheIsolationError(
            "recorded execution order is not counterbalanced"
        )
    return CacheIsolationReport(
        schema=CACHE_ISOLATION_REPORT_SCHEMA,
        plan_sha256=plan.digest,
        environment_sha256=plan.environment_sha256,
        cache_namespaces=namespaces,
        execution_order=tuple(job.job_id for job in plan.jobs),
        position_counts=position_counts,
        pairs=tuple(pairs),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or execute the frozen logic-pipeline A0 baseline"
    )
    parser.add_argument("--variant", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPOSITORY_ROOT / DEFAULT_BASELINE_MANIFEST_PATH,
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--cache-mode",
        choices=("both", CacheMode.COLD.value, CacheMode.WARM.value),
        default="both",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.variant != BASELINE_VARIANT:
            raise BaselineValidationError(
                "this frozen runner accepts only baseline variant A0"
            )
        if args.split != Split.PILOT.value:
            raise BaselineValidationError(
                "this frozen baseline contains only the pilot split"
            )
        manifest = load_baseline_manifest(args.manifest)
        if args.validate_only:
            print(
                canonical_json(
                    {
                        "baseline_id": BASELINE_ID,
                        "baseline_manifest_sha256": manifest.digest,
                        "cache_modes": [
                            contract.cache_mode.value
                            for contract in manifest.run_contracts
                        ],
                        "case_count": len(manifest.pilot_case_ids),
                        "status": "valid",
                        "variant_id": BASELINE_VARIANT,
                        "split": Split.PILOT.value,
                    }
                )
            )
            return 0
        modes = (
            (CacheMode.COLD, CacheMode.WARM)
            if args.cache_mode == "both"
            else (CacheMode(args.cache_mode),)
        )
        summary = execute_baseline(
            manifest,
            output_root=args.output_root,
            cache_modes=modes,
        )
        print(canonical_json(dict(summary)))
        return 0
    except (BaselineValidationError, ValueError, OSError) as exc:
        print(f"baseline runner failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
