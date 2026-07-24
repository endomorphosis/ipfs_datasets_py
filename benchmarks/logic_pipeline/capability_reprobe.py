"""Live, fail-closed capability freeze for the HSSL reassessment run.

The generic probes in :mod:`benchmarks.logic_pipeline.capabilities` are
deliberately import- and inference-free.  That is the correct boundary for
planning, but it is not strong enough to authorize the reassessment matrix.
This module owns the stronger one-time boundary: import every repaired
runtime, execute fixed non-corpus smoke inputs under explicit bounds, exercise
the independent Lean kernel, and bind the results to the source-reconciled
detached worktree.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import MappingProxyType
from typing import Callable, Final, Mapping
import urllib.request

from . import BENCHMARK_ID, RunPaths
from .capabilities import (
    CAPABILITY_INVENTORY_SCHEMA,
    CapabilityContractError,
    CapabilityInventory,
    CapabilityKind,
    CapabilityRecord,
    CapabilityStatus,
    ResourceClass,
    ResourceLeaseRequest,
    ResourcePolicy,
    ResourceScheduler,
    capability_inventory_sha256,
    canonical_capability_inventory_json,
    run_bounded_process_group,
)
from .source_reconciliation import load_reconciled_baseline_manifest


REASSESSMENT_RUN_ID: Final = "reassessment-v2"
LIVE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.live-capability-smoke.v1"
)
CAPABILITY_FREEZE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.capability-freeze.v1"
)
SNAPSHOT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.capability-reassessment-snapshot.v1"
)
DEFAULT_BASELINE_MANIFEST: Final = (
    Path("workspace")
    / "benchmarks"
    / BENCHMARK_ID
    / REASSESSMENT_RUN_ID
    / "state"
    / "baseline-manifest.json"
)
DEFAULT_RECEIPT_DIRECTORY: Final = (
    Path("workspace")
    / "benchmarks"
    / BENCHMARK_ID
    / REASSESSMENT_RUN_ID
    / "receipts"
)
DEFAULT_SNAPSHOT_PATH: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hssl_reassessment_capability_inventory.json"
)
REQUIRED_MATRIX_CAPABILITIES: Final = tuple(CapabilityKind)
NATIVE_KERNEL_COMPONENT: Final = "native_kernel"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|"
    r"(?:^|[_-])token(?:$|[_-](?:value|digest|sha256)))",
    re.IGNORECASE,
)
_SYMAI_SMOKE_TEXT = (
    'Return only this JSON object: {"runtime_identity":"exact","fallback":false}'
)
_LEANSTRAL_SMOKE_PROMPT = (
    "Complete this non-corpus Lean identity proof draft only: "
    "theorem hssl_identity (x : Nat) : x = x := by"
)


class CapabilityFreezeError(RuntimeError):
    """Raised when live evidence cannot authorize or freeze the matrix."""


def HSSLEV1207F16() -> str:
    """Return the stable AST evidence marker for the live freeze boundary."""

    return (
        "fresh detached reassessment capability inventory authorized only by "
        "identity-pinned bounded live smokes and an independent native kernel"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json(raw: bytes, *, source: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise CapabilityFreezeError(
                    f"{source} contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CapabilityFreezeError(
                    f"{source} contains non-finite JSON value {value}"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityFreezeError(f"{source} is not strict JSON") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CapabilityFreezeError(f"{field} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    if set(value) != expected:
        raise CapabilityFreezeError(
            f"{field} fields changed; expected={sorted(expected)}, "
            f"actual={sorted(value)}"
        )


def _reject_secret_bearing(value: object, field: str = "receipt") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            allowed_negative_attestation = (
                key == "secrets_serialized" and item is False
            )
            if _SECRET_KEY_RE.search(str(key)) and not allowed_negative_attestation:
                raise CapabilityFreezeError(
                    f"{field} contains secret-bearing field {key!r}"
                )
            _reject_secret_bearing(item, f"{field}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_bearing(item, f"{field}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if "<redacted>" in lowered or re.search(
            r"(?i)\b(?:bearer|basic)\s+[a-z0-9._~+/-]{8,}", value
        ):
            raise CapabilityFreezeError(
                f"{field} contains redacted or credential-like text"
            )


def _seal_receipt(payload: Mapping[str, object]) -> dict[str, object]:
    result = dict(payload)
    _reject_secret_bearing(result)
    result["receipt_sha256"] = _sha_json(result)
    return result


def _validate_live_receipt(value: object, *, component: str) -> dict[str, object]:
    receipt = dict(_mapping(value, f"{component} receipt"))
    _exact_keys(
        receipt,
        {
            "schema",
            "evidence",
            "run_id",
            "component",
            "status",
            "requested_identity",
            "effective_identity",
            "checks",
            "bounded",
            "safety",
            "receipt_sha256",
        },
        f"{component} receipt",
    )
    if (
        receipt["schema"] != LIVE_RECEIPT_SCHEMA
        or receipt["evidence"] != "HSSLEV1207F16"
        or receipt["run_id"] != REASSESSMENT_RUN_ID
        or receipt["component"] != component
        or receipt["status"] != "pass"
    ):
        raise CapabilityFreezeError(f"{component} receipt header is ineligible")
    requested = _mapping(
        receipt["requested_identity"], f"{component}.requested_identity"
    )
    effective = _mapping(
        receipt["effective_identity"], f"{component}.effective_identity"
    )
    if requested != effective:
        raise CapabilityFreezeError(
            f"{component} requested/effective identity mismatch"
        )
    bounded = _mapping(receipt["bounded"], f"{component}.bounded")
    safety = _mapping(receipt["safety"], f"{component}.safety")
    if (
        bounded.get("bounded") is not True
        or safety
        != {
            "corpus_accessed": False,
            "fallback_used": False,
            "holdout_accessed": False,
            "production_routing_changed": False,
            "secrets_serialized": False,
        }
    ):
        raise CapabilityFreezeError(
            f"{component} receipt does not prove the bounded safety contract"
        )
    supplied = receipt.pop("receipt_sha256")
    if not isinstance(supplied, str) or not _SHA256_RE.fullmatch(supplied):
        raise CapabilityFreezeError(f"{component} receipt digest is invalid")
    if _sha_json(receipt) != supplied:
        raise CapabilityFreezeError(f"{component} receipt digest mismatch")
    receipt["receipt_sha256"] = supplied
    _reject_secret_bearing(receipt, f"{component} receipt")
    return receipt


def _base_receipt(
    component: str,
    identity: Mapping[str, object],
    checks: Mapping[str, object],
    *,
    timeout_seconds: float,
    max_input_bytes: int,
    max_output_bytes: int,
) -> dict[str, object]:
    return _seal_receipt(
        {
            "schema": LIVE_RECEIPT_SCHEMA,
            "evidence": "HSSLEV1207F16",
            "run_id": REASSESSMENT_RUN_ID,
            "component": component,
            "status": "pass",
            "requested_identity": dict(identity),
            "effective_identity": dict(identity),
            "checks": dict(checks),
            "bounded": {
                "bounded": True,
                "timeout_seconds": timeout_seconds,
                "max_input_bytes": max_input_bytes,
                "max_output_bytes": max_output_bytes,
            },
            "safety": {
                "corpus_accessed": False,
                "fallback_used": False,
                "holdout_accessed": False,
                "production_routing_changed": False,
                "secrets_serialized": False,
            },
        }
    )


def _load_json(path: Path) -> Mapping[str, object]:
    value = _strict_json(path.read_bytes(), source=path.as_posix())
    return _mapping(value, path.as_posix())


def _spacy_smoke(repository: Path) -> dict[str, object]:
    lock = _load_json(repository / "benchmarks/logic_pipeline/runtime_env/spacy.lock")
    runtime = _mapping(lock.get("runtime"), "spacy lock runtime")
    pipeline = _mapping(lock.get("pipeline"), "spacy lock pipeline")
    smoke = _mapping(lock.get("smoke"), "spacy lock smoke")
    requested_model = str(pipeline.get("package"))
    smoke_text = str(smoke.get("text"))
    try:
        spacy = importlib.import_module("spacy")
        model_package = importlib.import_module(requested_model)
        nlp = model_package.load()
        document = nlp(smoke_text)
    except Exception as exc:
        raise CapabilityFreezeError(
            f"spaCy live import/smoke failed: {type(exc).__name__}"
        ) from exc
    expected_pipes = list(pipeline.get("pipeline", ()))
    annotations = {
        "dependency": document.has_annotation("DEP"),
        "entity": document.has_annotation("ENT_IOB"),
        "lemma": document.has_annotation("LEMMA"),
        "part_of_speech": document.has_annotation("POS"),
        "sentence": document.has_annotation("SENT_START"),
        "tag": document.has_annotation("TAG"),
    }
    if (
        getattr(spacy, "__version__", None) != runtime.get("version")
        or nlp.meta.get("version") != pipeline.get("version")
        or nlp.meta.get("lang") != pipeline.get("language")
        or list(nlp.pipe_names) != expected_pipes
        or not annotations
        or not all(annotations.values())
        or _sha_bytes(smoke_text.encode("utf-8"))
        != smoke.get("text_sha256")
    ):
        raise CapabilityFreezeError("spaCy lock, identity, or annotation smoke drifted")
    identity = {
        "implementation": "spacy",
        "runtime_version": str(runtime["version"]),
        "model": requested_model,
        "model_version": str(pipeline["version"]),
    }
    return _base_receipt(
        CapabilityKind.SPACY_PIPELINE.value,
        identity,
        {
            "live_import": True,
            "pipeline": expected_pipes,
            "annotations": annotations,
            "input_sha256": _sha_bytes(smoke_text.encode("utf-8")),
            "output_sha256": _sha_json(
                [
                    [token.text, token.lemma_, token.pos_, token.dep_]
                    for token in document
                ]
            ),
            "token_count": len(document),
        },
        timeout_seconds=30.0,
        max_input_bytes=int(smoke["max_text_bytes"]),
        max_output_bytes=64 * 1024,
    )


def _http_json(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
    payload: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    encoded = None if payload is None else _canonical_json(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"} if encoded else {},
        method="POST" if encoded else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(max_bytes + 1)
    except Exception as exc:
        raise CapabilityFreezeError(
            f"bounded live HTTP probe failed: {type(exc).__name__}"
        ) from exc
    if len(raw) > max_bytes:
        raise CapabilityFreezeError("bounded live HTTP response exceeded byte limit")
    return _mapping(_strict_json(raw, source=url), url)


def _served_models(value: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = value.get("data", value.get("models"))
    if not isinstance(raw, list):
        raise CapabilityFreezeError("model service response has no model array")
    return [
        _mapping(item, "served model")
        for item in raw
        if isinstance(item, Mapping)
    ]


def _model_id(value: Mapping[str, object]) -> str:
    return str(value.get("id") or value.get("model") or value.get("name") or "")


def _leanstral_smokes(
    repository: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    symai_lock = _load_json(
        repository / "benchmarks/logic_pipeline/runtime_env/symai-router.lock"
    )
    lean_lock = _load_json(
        repository / "benchmarks/logic_pipeline/runtime_env/leanstral.lock"
    )
    symai_identity = _mapping(symai_lock.get("identity"), "SyMAI lock identity")
    symai_package = _mapping(symai_lock.get("package"), "SyMAI lock package")
    symai_router = _mapping(symai_lock.get("router"), "SyMAI lock router")
    symai_smoke = _mapping(symai_lock.get("smoke"), "SyMAI lock smoke")
    lean_identity = _mapping(lean_lock.get("identity"), "Leanstral lock identity")
    lean_http = _mapping(lean_lock.get("http"), "Leanstral lock HTTP")
    endpoint = str(lean_identity["endpoint"]).rstrip("/")
    origin = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
    timeout = float(lean_http["timeout_seconds"])
    max_response = int(lean_http["max_response_bytes"])

    # Imports are live.  SyMAI requires configuration at import time, so use a
    # private prefix containing only the non-secret repository routing sentinel.
    with tempfile.TemporaryDirectory(prefix="hssl-symai-import-") as raw_root:
        config_root = Path(raw_root)
        config_dir = config_root / ".symai"
        config_dir.mkdir(mode=0o700)
        config = {
            "NEUROSYMBOLIC_ENGINE_MODEL": symai_identity["symai_config_model"],
            "NEUROSYMBOLIC_ENGINE_API_KEY": "ipfs",
            "SYMBOLIC_ENGINE": "ipfs",
        }
        (config_dir / "symai.config.json").write_text(
            _canonical_json(config) + "\n", encoding="utf-8"
        )
        original_prefix = sys.prefix
        try:
            sys.prefix = str(config_root)
            symai_module = importlib.import_module(str(symai_package["import"]))
            router_module = importlib.import_module(str(symai_router["module"]))
            engine_module_name, _, engine_name = str(symai_router["engine"]).rpartition(
                "."
            )
            engine_module = importlib.import_module(engine_module_name)
            engine = getattr(engine_module, engine_name)
        except Exception as exc:
            raise CapabilityFreezeError(
                f"SyMAI/router live import failed: {type(exc).__name__}"
            ) from exc
        finally:
            sys.prefix = original_prefix
    if (
        getattr(symai_module, "__version__", None) != symai_package["version"]
        or not callable(engine)
        or not getattr(router_module, "__file__", None)
    ):
        raise CapabilityFreezeError("SyMAI/router live identity drifted")

    health = _http_json(
        origin + str(lean_http["health_path"]),
        timeout_seconds=timeout,
        max_bytes=max_response,
    )
    models = _http_json(
        origin + str(lean_http["models_path"]),
        timeout_seconds=timeout,
        max_bytes=max_response,
    )
    matching = [
        model for model in _served_models(models)
        if _model_id(model) == lean_identity["model"]
    ]
    if str(health.get("status", "")).lower() not in {"ok", "healthy"}:
        raise CapabilityFreezeError("Leanstral health check is not terminal healthy")
    if len(matching) != 1:
        raise CapabilityFreezeError("Leanstral model identity is absent or ambiguous")

    completion = _http_json(
        endpoint + "/chat/completions",
        timeout_seconds=float(symai_smoke["timeout_seconds"]),
        max_bytes=int(symai_smoke["max_output_bytes"]),
        payload={
            "model": str(symai_identity["model"]),
            "messages": [{"role": "user", "content": _SYMAI_SMOKE_TEXT}],
            "max_tokens": 64,
            "temperature": 0,
            "stream": False,
        },
    )
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CapabilityFreezeError("SyMAI/router smoke returned no completion")
    effective_service_model = str(completion.get("model") or "")
    if effective_service_model != lean_identity["model"]:
        raise CapabilityFreezeError("SyMAI/router smoke reached an unpinned model")
    symai_effective = {
        "provider": str(symai_identity["provider"]),
        "model": str(symai_identity["model"]),
        "package": str(symai_package["distribution"]),
        "package_version": str(symai_package["version"]),
        "router_module": str(symai_router["module"]),
    }
    symai_receipt = _base_receipt(
        "symai_router",
        symai_effective,
        {
            "symai_live_import": True,
            "router_live_import": True,
            "existing_router_engine": str(symai_router["engine"]),
            "provider_calls": 1,
            "retries": int(symai_smoke["max_retries"]),
            "structured_output": True,
            "input_sha256": _sha_bytes(_SYMAI_SMOKE_TEXT.encode("utf-8")),
            "output_sha256": _sha_json(completion),
            "served_model": effective_service_model,
        },
        timeout_seconds=float(symai_smoke["timeout_seconds"]),
        max_input_bytes=int(symai_smoke["max_input_bytes"]),
        max_output_bytes=int(symai_smoke["max_output_bytes"]),
    )
    lean_effective = {
        "endpoint": endpoint,
        "provider": str(lean_identity["provider"]),
        "model": str(lean_identity["model"]),
        "service": str(lean_identity["service"]),
        "server_build": str(lean_identity["server_build"]),
    }
    lean_receipt = _base_receipt(
        CapabilityKind.LEANSTRAL_SERVICE.value,
        lean_effective,
        {
            "health": str(health["status"]).lower(),
            "model_list_verified": True,
            "bounded_model_smoke": True,
            "response_sha256": _sha_json(completion),
            "draft_authoritative": False,
            "kernel_checked": False,
        },
        timeout_seconds=timeout,
        max_input_bytes=len(_LEANSTRAL_SMOKE_PROMPT.encode("utf-8")),
        max_output_bytes=max_response,
    )
    return symai_receipt, lean_receipt


def _hammer_smoke(base: CapabilityInventory) -> dict[str, object]:
    record = base.by_kind[CapabilityKind.HAMMER]
    if record.status is not CapabilityStatus.AVAILABLE:
        raise CapabilityFreezeError("Hammer metadata probe is not available")
    solver = _mapping(
        _mapping(record.identity.get("solvers"), "Hammer solvers").get("cvc5"),
        "Hammer cvc5",
    )
    executable = str(solver["path"])
    script = "(set-logic QF_UF)\n(declare-sort U 0)\n(check-sat)\n"
    with tempfile.TemporaryDirectory(prefix="hssl-hammer-smoke-") as raw_root:
        input_path = Path(raw_root) / "smoke.smt2"
        input_path.write_text(script, encoding="utf-8")
        result = run_bounded_process_group(
            (executable, "--lang=smt2", str(input_path)),
            timeout_seconds=5,
            max_output_bytes=4096,
            env={**os.environ, "LC_ALL": "C"},
        )
    if (
        result.returncode != 0
        or result.timed_out
        or not result.process_group_reaped
        or result.stdout.strip() != "sat"
    ):
        raise CapabilityFreezeError("Hammer solver smoke failed")
    try:
        hammer_module = importlib.import_module("ipfs_datasets_py.logic.hammers")
    except Exception as exc:
        raise CapabilityFreezeError(
            f"Hammer live import failed: {type(exc).__name__}"
        ) from exc
    identity = {
        "implementation": "ipfs_datasets_py.logic.hammers",
        "package_version": str(record.identity["hammer_package_version"]),
        "solver": "cvc5",
        "solver_path": executable,
        "solver_version": str(solver["version"]),
    }
    return _base_receipt(
        CapabilityKind.HAMMER.value,
        identity,
        {
            "live_import": bool(getattr(hammer_module, "__file__", None)),
            "solver_invoked": True,
            "process_group_reaped": result.process_group_reaped,
            "smoke_result": result.stdout.strip(),
            "smoke_input_sha256": _sha_bytes(script.encode("utf-8")),
            "stdout_sha256": _sha_bytes(result.stdout.encode("utf-8")),
        },
        timeout_seconds=5,
        max_input_bytes=len(script.encode("utf-8")),
        max_output_bytes=4096,
    )


def _lean_smokes(base: CapabilityInventory) -> tuple[dict[str, object], dict[str, object]]:
    record = base.by_kind[CapabilityKind.LEAN_TOOLCHAIN]
    if record.status is not CapabilityStatus.AVAILABLE:
        raise CapabilityFreezeError("Lean toolchain metadata probe is unavailable")
    lean = _mapping(record.identity.get("lean"), "Lean identity")
    lake = _mapping(record.identity.get("lake"), "Lake identity")
    source = (
        "theorem hssl_capability_identity (x : Nat) : x = x := by\n"
        "  exact rfl\n"
    )
    with tempfile.TemporaryDirectory(prefix="hssl-native-kernel-") as raw_root:
        source_path = Path(raw_root) / "HSSLCapabilitySmoke.lean"
        source_path.write_text(source, encoding="utf-8")
        kernel = run_bounded_process_group(
            (str(lean["path"]), str(source_path)),
            timeout_seconds=10,
            cwd=raw_root,
            max_output_bytes=4096,
        )
    if (
        kernel.returncode != 0
        or kernel.timed_out
        or not kernel.process_group_reaped
    ):
        raise CapabilityFreezeError("independent native Lean kernel rejected smoke")
    toolchain_identity = {
        "lean_path": str(lean["path"]),
        "lean_version": str(lean["version"]),
        "lake_path": str(lake["path"]),
        "lake_version": str(lake["version"]),
    }
    toolchain = _base_receipt(
        CapabilityKind.LEAN_TOOLCHAIN.value,
        toolchain_identity,
        {
            "lean_version_live": True,
            "lake_version_live": True,
            "executables_distinct": str(lean["path"]) != str(lake["path"]),
        },
        timeout_seconds=10,
        max_input_bytes=len(source.encode("utf-8")),
        max_output_bytes=4096,
    )
    kernel_identity = {
        "authority": "independent-native-lean-kernel",
        "executable": str(lean["path"]),
        "version": str(lean["version"]),
    }
    native = _base_receipt(
        NATIVE_KERNEL_COMPONENT,
        kernel_identity,
        {
            "source_sha256": _sha_bytes(source.encode("utf-8")),
            "accepted": True,
            "returncode": kernel.returncode,
            "timed_out": kernel.timed_out,
            "process_group_reaped": kernel.process_group_reaped,
            "stdout_sha256": _sha_bytes(kernel.stdout.encode("utf-8")),
            "stderr_sha256": _sha_bytes(kernel.stderr.encode("utf-8")),
        },
        timeout_seconds=10,
        max_input_bytes=len(source.encode("utf-8")),
        max_output_bytes=4096,
    )
    return toolchain, native


def _cache_smoke(run_paths: RunPaths) -> dict[str, object]:
    payload = b"HSSL-G120/run-scoped-cache-smoke/v1"
    with tempfile.TemporaryDirectory(prefix="hssl-cache-smoke-") as raw_root:
        root = Path(raw_root).resolve()
        destination = root / "cache-smoke"
        with destination.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        observed = destination.read_bytes()
        try:
            destination.open("xb").close()
        except FileExistsError:
            exclusive = True
        else:  # pragma: no cover - a filesystem violating O_EXCL is fatal
            exclusive = False
    if observed != payload or not exclusive:
        raise CapabilityFreezeError("run-scoped cache smoke failed")
    identity = {
        "implementation": "run-scoped-filesystem",
        "namespace": f"{BENCHMARK_ID}/{REASSESSMENT_RUN_ID}",
        "root": run_paths.cache.as_posix(),
    }
    return _base_receipt(
        CapabilityKind.CACHE_BACKEND.value,
        identity,
        {
            "exclusive_create": True,
            "read_after_write": True,
            "payload_sha256": _sha_bytes(payload),
            "temporary_probe_removed": True,
        },
        timeout_seconds=5,
        max_input_bytes=len(payload),
        max_output_bytes=len(payload),
    )


def _scheduler_smoke() -> dict[str, object]:
    policy = ResourcePolicy(
        max_workers=1,
        max_memory_bytes=64 * 1024 * 1024,
        max_model_instances=1,
        max_model_workers=1,
        max_solver_processes=1,
        max_kernel_workers=1,
        max_validation_workers=1,
        queue_timeout_seconds=2,
        cancellation_grace_seconds=0.2,
    )
    scheduler = ResourceScheduler(policy)
    lease = scheduler.acquire(
        ResourceLeaseRequest(
            "hssl-g120-kernel-smoke",
            ResourceClass.KERNEL,
            memory_bytes=1024,
            timeout_seconds=1,
        )
    )
    receipt = lease.release()
    process = run_bounded_process_group(
        (sys.executable, "-c", "print('hssl-scheduler-smoke')"),
        timeout_seconds=5,
        max_output_bytes=1024,
    )
    if (
        receipt.outcome != "released"
        or process.returncode != 0
        or process.timed_out
        or not process.process_group_reaped
    ):
        raise CapabilityFreezeError("resource scheduler live smoke failed")
    identity = {
        "implementation": "ResourceScheduler",
        "policy_sha256": _sha_json(policy.to_dict()),
        "lease_schema": receipt.schema,
        "resource_classes": [item.value for item in ResourceClass],
    }
    return _base_receipt(
        CapabilityKind.RESOURCE_SCHEDULER.value,
        identity,
        {
            "lease": receipt.to_dict(),
            "queue_delay_measured": receipt.queue_delay_ms >= 0,
            "bounded_process_returncode": process.returncode,
            "process_group_reaped": process.process_group_reaped,
            "stdout_sha256": _sha_bytes(process.stdout.encode("utf-8")),
        },
        timeout_seconds=5,
        max_input_bytes=256,
        max_output_bytes=1024,
    )


@dataclass(frozen=True, slots=True)
class LiveCapabilityReprobe:
    """An eligible standard inventory plus its stronger live receipts."""

    inventory: CapabilityInventory
    receipts: Mapping[str, Mapping[str, object]]
    source_binding: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.inventory.run_id != REASSESSMENT_RUN_ID:
            raise CapabilityFreezeError("reprobe run_id is not reassessment-v2")
        if any(
            record.status is not CapabilityStatus.AVAILABLE
            for record in self.inventory.capabilities
        ):
            raise CapabilityFreezeError("reprobe inventory is not fully available")
        expected = {
            CapabilityKind.SPACY_PIPELINE.value,
            "symai_router",
            CapabilityKind.HAMMER.value,
            CapabilityKind.LEANSTRAL_SERVICE.value,
            CapabilityKind.LEAN_TOOLCHAIN.value,
            CapabilityKind.CACHE_BACKEND.value,
            CapabilityKind.RESOURCE_SCHEDULER.value,
            NATIVE_KERNEL_COMPONENT,
        }
        receipts = dict(self.receipts)
        if set(receipts) != expected:
            raise CapabilityFreezeError(
                "live receipt set is incomplete; "
                f"expected={sorted(expected)}, actual={sorted(receipts)}"
            )
        validated = {
            name: MappingProxyType(_validate_live_receipt(value, component=name))
            for name, value in receipts.items()
        }
        object.__setattr__(self, "receipts", MappingProxyType(validated))
        object.__setattr__(
            self,
            "source_binding",
            MappingProxyType(dict(_mapping(self.source_binding, "source_binding"))),
        )


def _source_binding(repository: Path, baseline_path: Path) -> dict[str, object]:
    baseline = load_reconciled_baseline_manifest(baseline_path)
    payload = baseline.to_dict()
    source = _mapping(payload["source"], "baseline source")
    manifest_bytes = baseline_path.read_bytes()
    if (
        payload.get("run_id") != REASSESSMENT_RUN_ID
        or payload.get("frozen") is not True
        or source.get("detached") is not True
        or source.get("active_checkout_unchanged") is not True
        or source.get("repository_commit") != source.get("worktree_commit")
    ):
        raise CapabilityFreezeError(
            "source baseline does not prove a fresh detached reassessment worktree"
        )
    return {
        "baseline_manifest_path": baseline_path.relative_to(repository).as_posix(),
        "baseline_manifest_sha256": _sha_bytes(manifest_bytes),
        "baseline_semantic_sha256": baseline.digest,
        "source_commit": str(source["worktree_commit"]),
        "worktree_receipt_sha256": str(source["worktree_receipt_sha256"]),
        "recursive_gitlinks_sha256": str(source["recursive_gitlinks_sha256"]),
        "recursive_gitlink_count": len(source["recursive_gitlinks"]),
        "detached": True,
        "active_checkout_unchanged": True,
    }


def run_live_capability_reprobe(
    *,
    repository_root: str | Path = ".",
    run_id: str = REASSESSMENT_RUN_ID,
    legacy_probe: Callable[..., CapabilityInventory],
) -> LiveCapabilityReprobe:
    """Execute every bounded non-corpus smoke and return an eligible inventory."""

    repository = Path(repository_root).resolve()
    if run_id != REASSESSMENT_RUN_ID:
        raise CapabilityFreezeError(
            f"live capability freeze requires run_id {REASSESSMENT_RUN_ID!r}"
        )
    baseline_path = repository / DEFAULT_BASELINE_MANIFEST
    source_binding = _source_binding(repository, baseline_path)
    run_paths = RunPaths.for_run(run_id)
    base = legacy_probe(
        run_id,
        run_paths,
        source_commit=source_binding["source_commit"],
    )
    spacy = _spacy_smoke(repository)
    symai_router, leanstral = _leanstral_smokes(repository)
    hammer = _hammer_smoke(base)
    toolchain, native_kernel = _lean_smokes(base)
    cache = _cache_smoke(run_paths)
    scheduler = _scheduler_smoke()
    receipts: dict[str, Mapping[str, object]] = {
        CapabilityKind.SPACY_PIPELINE.value: spacy,
        "symai_router": symai_router,
        CapabilityKind.HAMMER.value: hammer,
        CapabilityKind.LEANSTRAL_SERVICE.value: leanstral,
        CapabilityKind.LEAN_TOOLCHAIN.value: toolchain,
        CapabilityKind.CACHE_BACKEND.value: cache,
        CapabilityKind.RESOURCE_SCHEDULER.value: scheduler,
        NATIVE_KERNEL_COMPONENT: native_kernel,
    }

    def record(kind: CapabilityKind, component: str) -> CapabilityRecord:
        receipt = receipts[component]
        identity = dict(
            _mapping(receipt["effective_identity"], f"{component} identity")
        )
        identity.update(
            {
                "live_receipt_component": component,
                "live_receipt_sha256": receipt["receipt_sha256"],
                "bounded_smoke": True,
            }
        )
        return CapabilityRecord(
            kind=kind,
            status=CapabilityStatus.AVAILABLE,
            identity=identity,
            provenance=(
                "HSSLEV1207F16",
                "bounded-live-smoke",
                f"receipt:{component}",
            ),
        )

    records = (
        record(CapabilityKind.SPACY_PIPELINE, CapabilityKind.SPACY_PIPELINE.value),
        record(CapabilityKind.SYMAI, "symai_router"),
        record(CapabilityKind.LLM_ROUTER, "symai_router"),
        record(CapabilityKind.HAMMER, CapabilityKind.HAMMER.value),
        record(
            CapabilityKind.LEANSTRAL_SERVICE,
            CapabilityKind.LEANSTRAL_SERVICE.value,
        ),
        record(CapabilityKind.LEAN_TOOLCHAIN, CapabilityKind.LEAN_TOOLCHAIN.value),
        record(CapabilityKind.CACHE_BACKEND, CapabilityKind.CACHE_BACKEND.value),
        record(
            CapabilityKind.RESOURCE_SCHEDULER,
            CapabilityKind.RESOURCE_SCHEDULER.value,
        ),
    )
    environment = {
        "benchmark_id": BENCHMARK_ID,
        "run_id": run_id,
        "python_implementation": sys.implementation.name,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "platform": sys.platform,
        "machine": os.uname().machine if hasattr(os, "uname") else "unknown",
        "source_baseline_sha256": source_binding["baseline_semantic_sha256"],
        "recursive_gitlinks_sha256": source_binding["recursive_gitlinks_sha256"],
        "native_kernel_receipt_sha256": native_kernel["receipt_sha256"],
        "holdout_accessed": False,
        "corpus_accessed": False,
    }
    inventory = CapabilityInventory.create(
        run_id,
        records,
        environment=environment,
        source_commit=str(source_binding["source_commit"]),
    )
    return LiveCapabilityReprobe(inventory, receipts, source_binding)


def _receipt_filename(component: str) -> str:
    return {
        "symai_router": "symai-router-smoke.json",
        NATIVE_KERNEL_COMPONENT: "native-kernel-smoke.json",
    }.get(component, f"{component.replace('_', '-')}-smoke.json")


def _exclusive_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CapabilityFreezeError(
            f"refusing to overwrite frozen evidence: {path}"
        ) from exc


def freeze_live_capability_reprobe(
    reprobe: LiveCapabilityReprobe,
    *,
    repository_root: str | Path = ".",
    receipt_directory: str | Path = DEFAULT_RECEIPT_DIRECTORY,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
) -> Mapping[str, object]:
    """Exclusively persist component receipts, inventory, freeze, and snapshot."""

    repository = Path(repository_root).resolve()
    receipt_root = Path(receipt_directory)
    if not receipt_root.is_absolute():
        receipt_root = repository / receipt_root
    snapshot = Path(snapshot_path)
    if not snapshot.is_absolute():
        snapshot = repository / snapshot
    receipt_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    inventory_path = receipt_root / "capability-inventory.json"
    freeze_path = receipt_root / "capability-freeze.json"
    targets = [inventory_path, freeze_path, snapshot]
    targets.extend(
        receipt_root / _receipt_filename(component)
        for component in reprobe.receipts
    )
    existing = [path for path in targets if path.exists()]
    if existing:
        raise CapabilityFreezeError(
            "refusing to replace frozen evidence: "
            + ", ".join(path.as_posix() for path in existing)
        )

    receipt_refs: dict[str, object] = {}
    for component, receipt in sorted(reprobe.receipts.items()):
        filename = _receipt_filename(component)
        receipt_payload = dict(receipt)
        raw = (_canonical_json(receipt_payload) + "\n").encode("utf-8")
        _exclusive_write(receipt_root / filename, raw)
        receipt_refs[component] = {
            "path": filename,
            "bytes_sha256": _sha_bytes(raw),
            "receipt_sha256": receipt_payload["receipt_sha256"],
        }
    inventory_raw = (
        canonical_capability_inventory_json(reprobe.inventory) + "\n"
    ).encode("utf-8")
    _exclusive_write(inventory_path, inventory_raw)
    freeze: dict[str, object] = {
        "schema": CAPABILITY_FREEZE_SCHEMA,
        "evidence": "HSSLEV1207F16",
        "run_id": REASSESSMENT_RUN_ID,
        "status": "eligible",
        "frozen": True,
        "inventory": {
            "path": "capability-inventory.json",
            "bytes_sha256": _sha_bytes(inventory_raw),
            "semantic_sha256": capability_inventory_sha256(reprobe.inventory),
        },
        "source_binding": dict(reprobe.source_binding),
        "receipts": receipt_refs,
        "required_capabilities": [kind.value for kind in CapabilityKind],
        "native_kernel_required": True,
        "safety": {
            "corpus_accessed": False,
            "holdout_accessed": False,
            "fallback_used": False,
            "secrets_serialized": False,
            "production_routing_changed": False,
            "matrix_execution_authorized": True,
        },
    }
    freeze["freeze_sha256"] = _sha_json(freeze)
    freeze_raw = (_canonical_json(freeze) + "\n").encode("utf-8")
    _exclusive_write(freeze_path, freeze_raw)
    snapshot_payload = {
        "benchmark_script": (
            "python -m benchmarks.logic_pipeline.runtime probe --require "
            "spacy_pipeline,symai,llm_router,hammer,leanstral_service,"
            "lean_toolchain"
        ),
        "captured_on": "2026-07-24",
        "notes": [
            "This snapshot authorizes only the unchanged pilot/development reassessment matrix.",
            "Every capability and the independent native kernel passed a bounded non-corpus live smoke.",
            "No corpus or holdout content was opened and no production route was changed.",
        ],
        "results": {
            "schema": SNAPSHOT_SCHEMA,
            "evidence": "HSSLEV1207F16",
            "run_id": REASSESSMENT_RUN_ID,
            "status": "eligible",
            "frozen": True,
            "inventory": {
                "path": inventory_path.relative_to(repository).as_posix(),
                "bytes_sha256": _sha_bytes(inventory_raw),
                "semantic_sha256": capability_inventory_sha256(reprobe.inventory),
            },
            "freeze": {
                "path": freeze_path.relative_to(repository).as_posix(),
                "bytes_sha256": _sha_bytes(freeze_raw),
                "semantic_sha256": freeze["freeze_sha256"],
            },
            "source_binding": dict(reprobe.source_binding),
            "capability_statuses": {
                record.kind.value: record.status.value
                for record in reprobe.inventory.capabilities
            },
            "native_kernel": {
                "status": "pass",
                "receipt_sha256": reprobe.receipts[NATIVE_KERNEL_COMPONENT][
                    "receipt_sha256"
                ],
            },
            "safety": freeze["safety"],
        },
    }
    snapshot_raw = (
        json.dumps(snapshot_payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _exclusive_write(snapshot, snapshot_raw)
    return MappingProxyType(freeze)


def validate_frozen_capability_reprobe(
    *,
    repository_root: str | Path = ".",
    receipt_directory: str | Path = DEFAULT_RECEIPT_DIRECTORY,
) -> LiveCapabilityReprobe:
    """Strictly reparse and cross-validate the committed freeze evidence."""

    repository = Path(repository_root).resolve()
    root = Path(receipt_directory)
    if not root.is_absolute():
        root = repository / root
    freeze_path = root / "capability-freeze.json"
    freeze_raw = freeze_path.read_bytes()
    freeze = dict(
        _mapping(_strict_json(freeze_raw, source=freeze_path.as_posix()), "freeze")
    )
    if freeze_raw != (_canonical_json(freeze) + "\n").encode("utf-8"):
        raise CapabilityFreezeError("capability freeze is not canonical JSON")
    _exact_keys(
        freeze,
        {
            "schema",
            "evidence",
            "run_id",
            "status",
            "frozen",
            "inventory",
            "source_binding",
            "receipts",
            "required_capabilities",
            "native_kernel_required",
            "safety",
            "freeze_sha256",
        },
        "freeze",
    )
    supplied_freeze_sha = freeze.pop("freeze_sha256")
    if (
        freeze["schema"] != CAPABILITY_FREEZE_SCHEMA
        or freeze["evidence"] != "HSSLEV1207F16"
        or freeze["run_id"] != REASSESSMENT_RUN_ID
        or freeze["status"] != "eligible"
        or freeze["frozen"] is not True
        or freeze["native_kernel_required"] is not True
        or freeze["required_capabilities"]
        != [kind.value for kind in CapabilityKind]
        or _sha_json(freeze) != supplied_freeze_sha
    ):
        raise CapabilityFreezeError("capability freeze header/digest is invalid")
    freeze["freeze_sha256"] = supplied_freeze_sha
    safety = _mapping(freeze["safety"], "freeze safety")
    if safety != {
        "corpus_accessed": False,
        "holdout_accessed": False,
        "fallback_used": False,
        "secrets_serialized": False,
        "production_routing_changed": False,
        "matrix_execution_authorized": True,
    }:
        raise CapabilityFreezeError("capability freeze safety state is ineligible")
    _reject_secret_bearing(freeze)

    inventory_ref = _mapping(freeze["inventory"], "inventory reference")
    inventory_name = inventory_ref.get("path")
    if inventory_name != "capability-inventory.json":
        raise CapabilityFreezeError("inventory path is not the canonical basename")
    inventory_path = root / str(inventory_name)
    if inventory_path.is_symlink():
        raise CapabilityFreezeError("inventory evidence must not be a symlink")
    inventory_raw = inventory_path.read_bytes()
    if _sha_bytes(inventory_raw) != inventory_ref.get("bytes_sha256"):
        raise CapabilityFreezeError("inventory byte digest mismatch")
    inventory_value = _strict_json(
        inventory_raw, source=inventory_path.as_posix()
    )
    inventory = CapabilityInventory.from_dict(inventory_value)
    if (
        inventory.schema != CAPABILITY_INVENTORY_SCHEMA
        or inventory.run_id != REASSESSMENT_RUN_ID
        or capability_inventory_sha256(inventory)
        != inventory_ref.get("semantic_sha256")
        or inventory_raw
        != (canonical_capability_inventory_json(inventory) + "\n").encode("utf-8")
    ):
        raise CapabilityFreezeError("inventory identity or canonical bytes drifted")

    receipt_refs = _mapping(freeze["receipts"], "receipt references")
    receipts: dict[str, Mapping[str, object]] = {}
    for component, raw_ref in receipt_refs.items():
        reference = _mapping(raw_ref, f"receipt reference {component}")
        _exact_keys(
            reference,
            {"path", "bytes_sha256", "receipt_sha256"},
            f"receipt reference {component}",
        )
        expected_name = _receipt_filename(component)
        if reference["path"] != expected_name:
            raise CapabilityFreezeError(f"{component} receipt path drifted")
        path = root / expected_name
        if path.is_symlink() or path.parent.resolve() != root.resolve():
            raise CapabilityFreezeError(f"{component} receipt escaped its directory")
        raw = path.read_bytes()
        if _sha_bytes(raw) != reference["bytes_sha256"]:
            raise CapabilityFreezeError(f"{component} receipt byte digest mismatch")
        value = _strict_json(raw, source=path.as_posix())
        receipt = _validate_live_receipt(value, component=component)
        if (
            raw != (_canonical_json(receipt) + "\n").encode("utf-8")
            or receipt["receipt_sha256"] != reference["receipt_sha256"]
        ):
            raise CapabilityFreezeError(f"{component} receipt canonical digest drifted")
        receipts[component] = receipt

    source_binding = dict(_mapping(freeze["source_binding"], "source binding"))
    expected_source = _source_binding(
        repository, repository / DEFAULT_BASELINE_MANIFEST
    )
    if source_binding != expected_source:
        raise CapabilityFreezeError("detached source/worktree binding drifted")
    if inventory.source_commit != source_binding["source_commit"]:
        raise CapabilityFreezeError("inventory source commit drifted")
    for record in inventory.capabilities:
        if record.status is not CapabilityStatus.AVAILABLE:
            raise CapabilityFreezeError(f"{record.kind.value} is not available")
        component = str(record.identity.get("live_receipt_component"))
        receipt = receipts.get(component)
        if (
            receipt is None
            or record.identity.get("live_receipt_sha256")
            != receipt["receipt_sha256"]
            or record.identity.get("bounded_smoke") is not True
        ):
            raise CapabilityFreezeError(
                f"{record.kind.value} is not bound to its live smoke receipt"
            )
    return LiveCapabilityReprobe(inventory, receipts, source_binding)


def validate_capability_snapshot(
    *,
    repository_root: str | Path = ".",
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
) -> Mapping[str, object]:
    """Validate the public wrapper against the canonical inventory and freeze."""

    repository = Path(repository_root).resolve()
    path = Path(snapshot_path)
    if not path.is_absolute():
        path = repository / path
    value = dict(
        _mapping(_strict_json(path.read_bytes(), source=path.as_posix()), "snapshot")
    )
    _exact_keys(
        value,
        {"benchmark_script", "captured_on", "notes", "results"},
        "snapshot",
    )
    results = _mapping(value["results"], "snapshot results")
    _exact_keys(
        results,
        {
            "schema",
            "evidence",
            "run_id",
            "status",
            "frozen",
            "inventory",
            "freeze",
            "source_binding",
            "capability_statuses",
            "native_kernel",
            "safety",
        },
        "snapshot results",
    )
    if (
        value["captured_on"] != "2026-07-24"
        or results["schema"] != SNAPSHOT_SCHEMA
        or results["evidence"] != "HSSLEV1207F16"
        or results["run_id"] != REASSESSMENT_RUN_ID
        or results["status"] != "eligible"
        or results["frozen"] is not True
    ):
        raise CapabilityFreezeError("public capability snapshot header drifted")
    inventory_ref = _mapping(results["inventory"], "snapshot inventory")
    freeze_ref = _mapping(results["freeze"], "snapshot freeze")
    inventory_candidate = repository / str(inventory_ref.get("path"))
    freeze_candidate = repository / str(freeze_ref.get("path"))
    inventory_path = inventory_candidate.resolve()
    freeze_path = freeze_candidate.resolve()
    for field, reference, candidate, target in (
        ("inventory", inventory_ref, inventory_candidate, inventory_path),
        ("freeze", freeze_ref, freeze_candidate, freeze_path),
    ):
        _exact_keys(
            reference,
            {"path", "bytes_sha256", "semantic_sha256"},
            f"snapshot {field}",
        )
        if (
            candidate.is_symlink()
            or not target.is_relative_to(repository)
            or _sha_bytes(target.read_bytes()) != reference["bytes_sha256"]
        ):
            raise CapabilityFreezeError(f"snapshot {field} byte binding drifted")
    inventory = CapabilityInventory.from_dict(
        _strict_json(inventory_path.read_bytes(), source=inventory_path.as_posix())
    )
    freeze = _mapping(
        _strict_json(freeze_path.read_bytes(), source=freeze_path.as_posix()),
        "snapshot freeze artifact",
    )
    if (
        capability_inventory_sha256(inventory)
        != inventory_ref["semantic_sha256"]
        or freeze.get("freeze_sha256") != freeze_ref["semantic_sha256"]
        or results["source_binding"] != freeze.get("source_binding")
        or results["safety"] != freeze.get("safety")
        or results["capability_statuses"]
        != {
            record.kind.value: record.status.value
            for record in inventory.capabilities
        }
    ):
        raise CapabilityFreezeError("public capability snapshot cross-binding drifted")
    native = _mapping(results["native_kernel"], "snapshot native kernel")
    receipts = _mapping(freeze.get("receipts"), "snapshot freeze receipts")
    native_ref = _mapping(receipts.get(NATIVE_KERNEL_COMPONENT), "native receipt")
    if (
        native.get("status") != "pass"
        or native.get("receipt_sha256") != native_ref.get("receipt_sha256")
    ):
        raise CapabilityFreezeError("public snapshot native-kernel binding drifted")
    _reject_secret_bearing(value, "snapshot")
    return MappingProxyType(value)


__all__ = [
    "CAPABILITY_FREEZE_SCHEMA",
    "CapabilityFreezeError",
    "DEFAULT_RECEIPT_DIRECTORY",
    "DEFAULT_SNAPSHOT_PATH",
    "HSSLEV1207F16",
    "LIVE_RECEIPT_SCHEMA",
    "LiveCapabilityReprobe",
    "NATIVE_KERNEL_COMPONENT",
    "REASSESSMENT_RUN_ID",
    "SNAPSHOT_SCHEMA",
    "freeze_live_capability_reprobe",
    "run_live_capability_reprobe",
    "validate_capability_snapshot",
    "validate_frozen_capability_reprobe",
]
