#!/usr/bin/env python3
"""Provision and verify the pinned HSSL SyMAI existing-router runtime.

The checked-in lock is the only source of package, provider, and model
identity.  Verification is side-effect free.  Installation, noninteractive
SyMAI configuration, and the bounded live smoke call are separate opt-in
actions.  Receipts never contain credential values or model output.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from typing import Callable, Iterator, Mapping, Sequence


LOCK_SCHEMA = "ipfs-datasets.logic-pipeline-benchmark.symai-router-lock.v1"
RECEIPT_SCHEMA = "ipfs-datasets.logic-pipeline-benchmark.symai-router-runtime.v1"
TASK_ID = "HSSL-BENCH-032"
EVIDENCE_ID = "HSSLEV1118B52"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT_TEXT = str(REPOSITORY_ROOT)
if _REPOSITORY_ROOT_TEXT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT_TEXT)
DEFAULT_LOCK_PATH = (
    REPOSITORY_ROOT
    / "benchmarks"
    / "logic_pipeline"
    / "runtime_env"
    / "symai-router.lock"
)
DEFAULT_LEANSTRAL_LOCK_PATH = (
    REPOSITORY_ROOT
    / "benchmarks"
    / "logic_pipeline"
    / "runtime_env"
    / "leanstral.lock"
)
SMOKE_TEXT = (
    "Every runtime identity receipt names exactly one configured provider and model."
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET_NAME_RE = re.compile(r"(?:API[_-]?KEY|TOKEN|PASSWORD|CREDENTIAL)", re.I)
_RECURSIVE_PROVIDERS = frozenset(
    {"symai", "symbolicai", "symbolic_ai", "ipfs_symai", "symai_ipfs_engine"}
)


class ProvisioningError(RuntimeError):
    """A fail-closed, externally safe provisioning failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SymaiRouterLock:
    """Validated immutable runtime identity loaded from the checked-in lock."""

    raw: Mapping[str, object]
    canonical_json: str
    sha256: str
    distribution: str
    import_name: str
    version: str
    requirement: str
    metadata_sha256: str
    router_module: str
    router_source: str
    engine: str
    provider: str
    model: str
    symai_config_model: str
    credential_environment: tuple[str, ...]
    timeout_seconds: int
    max_calls: int
    max_retries: int
    max_input_bytes: int
    max_output_bytes: int


def HSSLEV1118B52() -> str:
    """Return the AST-verifiable pinned SyMAI runtime evidence marker."""

    return (
        "pinned SymbolicAI through the existing llm_router with identical "
        "requested and effective provider/model identities, secret-safe "
        "receipts, disabled fallback, and one bounded non-corpus smoke call"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _strict_json(text: str) -> object:
    def pairs(items: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ProvisioningError("duplicate_lock_key")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs)
    except ProvisioningError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProvisioningError("invalid_lock_json") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProvisioningError(f"invalid_{field}")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise ProvisioningError(f"invalid_{field}_keys")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProvisioningError(f"invalid_{field}")
    return value


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
    ):
        raise ProvisioningError(f"invalid_{field}")
    return value


def load_lock(path: Path | str = DEFAULT_LOCK_PATH) -> SymaiRouterLock:
    """Load and strictly validate the complete lock schema."""

    lock_path = Path(path)
    try:
        decoded = _strict_json(lock_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProvisioningError("lock_unreadable") from exc
    root = _mapping(decoded, "lock")
    _exact_keys(
        root,
        {
            "credentials",
            "evidence",
            "identity",
            "package",
            "router",
            "safety",
            "schema",
            "smoke",
            "task_id",
        },
        "lock",
    )
    if root["schema"] != LOCK_SCHEMA:
        raise ProvisioningError("unsupported_lock_schema")
    if root["task_id"] != TASK_ID or root["evidence"] != EVIDENCE_ID:
        raise ProvisioningError("wrong_lock_objective")

    package = _mapping(root["package"], "package")
    _exact_keys(
        package,
        {
            "distribution",
            "import",
            "metadata_sha256",
            "requirement",
            "version",
        },
        "package",
    )
    distribution = _string(package["distribution"], "distribution")
    import_name = _string(package["import"], "import")
    version = _string(package["version"], "version")
    requirement = _string(package["requirement"], "requirement")
    metadata_sha256 = _string(package["metadata_sha256"], "metadata_sha256")
    if requirement != f"{distribution}=={version}":
        raise ProvisioningError("package_is_not_exactly_pinned")
    if not _SHA256_RE.fullmatch(metadata_sha256):
        raise ProvisioningError("invalid_metadata_sha256")

    router = _mapping(root["router"], "router")
    _exact_keys(router, {"engine", "module", "source"}, "router")
    router_module = _string(router["module"], "router_module")
    router_source = _string(router["source"], "router_source")
    engine = _string(router["engine"], "engine")
    if (
        router_module != "ipfs_datasets_py.llm_router"
        or engine
        != (
            "ipfs_datasets_py.utils.symai_ipfs_engine."
            "IPFSSyMAINeurosymbolicEngine"
        )
        or Path(router_source).is_absolute()
        or ".." in Path(router_source).parts
    ):
        raise ProvisioningError("unapproved_router_identity")

    identity = _mapping(root["identity"], "identity")
    _exact_keys(identity, {"model", "provider", "symai_config_model"}, "identity")
    provider = _string(identity["provider"], "provider")
    model = _string(identity["model"], "model")
    symai_config_model = _string(
        identity["symai_config_model"], "symai_config_model"
    )
    if not _SAFE_ID_RE.fullmatch(provider) or not _SAFE_ID_RE.fullmatch(model):
        raise ProvisioningError("unsafe_provider_or_model")
    if _normalized_provider(provider) in _RECURSIVE_PROVIDERS:
        raise ProvisioningError("recursive_provider")
    if symai_config_model != f"ipfs:{model}":
        raise ProvisioningError("symai_config_model_drift")

    safety = _mapping(root["safety"], "safety")
    required_safety = {
        "allow_local_fallback": False,
        "allow_model_fallback": False,
        "allow_provider_fallback": False,
        "noninteractive": True,
        "recursive_routing": False,
        "reuse_existing_model_service": True,
        "starts_model_manager": False,
        "starts_model_server": False,
    }
    _exact_keys(safety, set(required_safety), "safety")
    if dict(safety) != required_safety:
        raise ProvisioningError("unsafe_routing_policy")

    credentials = _mapping(root["credentials"], "credentials")
    _exact_keys(credentials, {"environment", "receipt"}, "credentials")
    environment = credentials["environment"]
    if (
        not isinstance(environment, list)
        or not environment
        or not all(
            isinstance(item, str) and _SAFE_ID_RE.fullmatch(item)
            for item in environment
        )
        or len(set(environment)) != len(environment)
        or environment != sorted(environment)
        or credentials["receipt"] != "presence-and-contextual-sha256-only"
    ):
        raise ProvisioningError("invalid_credential_policy")

    smoke = _mapping(root["smoke"], "smoke")
    _exact_keys(
        smoke,
        {
            "max_calls",
            "max_input_bytes",
            "max_output_bytes",
            "max_retries",
            "response_format",
            "timeout_seconds",
        },
        "smoke",
    )
    max_calls = _positive_int(smoke["max_calls"], "max_calls")
    max_retries = _positive_int(
        smoke["max_retries"], "max_retries", allow_zero=True
    )
    max_input_bytes = _positive_int(smoke["max_input_bytes"], "max_input_bytes")
    max_output_bytes = _positive_int(
        smoke["max_output_bytes"], "max_output_bytes"
    )
    timeout_seconds = _positive_int(smoke["timeout_seconds"], "timeout_seconds")
    if (
        max_calls != 1
        or max_retries != 0
        or smoke["response_format"] != "json_schema"
        or max_input_bytes > 1024
        or max_output_bytes > 4096
        or timeout_seconds > 60
    ):
        raise ProvisioningError("unbounded_smoke_policy")

    canonical = _canonical_json(root)
    return SymaiRouterLock(
        raw=dict(root),
        canonical_json=canonical,
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        distribution=distribution,
        import_name=import_name,
        version=version,
        requirement=requirement,
        metadata_sha256=metadata_sha256,
        router_module=router_module,
        router_source=router_source,
        engine=engine,
        provider=provider,
        model=model,
        symai_config_model=symai_config_model,
        credential_environment=tuple(environment),
        timeout_seconds=timeout_seconds,
        max_calls=max_calls,
        max_retries=max_retries,
        max_input_bytes=max_input_bytes,
        max_output_bytes=max_output_bytes,
    )


def _normalized_provider(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def provisioning_command(
    lock: SymaiRouterLock,
    *,
    python_executable: str = sys.executable,
) -> tuple[str, ...]:
    """Return the exact noninteractive installer command without executing it."""

    if not python_executable:
        raise ProvisioningError("missing_python_executable")
    return (
        python_executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        lock.requirement,
    )


def install_locked_package(
    lock: SymaiRouterLock,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: int = 600,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Install the exact locked distribution without exposing subprocess text."""

    command = provisioning_command(lock, python_executable=python_executable)
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProvisioningError("package_install_failed") from exc
    if completed.returncode != 0:
        raise ProvisioningError("package_install_failed")


def pinned_environment(
    lock: SymaiRouterLock,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an isolated environment with all four HSSL identities aligned."""

    result = dict(os.environ if base is None else base)
    result.update(
        {
            "HSSL_SYMAI_PROVIDER": lock.provider,
            "HSSL_SYMAI_MODEL": lock.model,
            "HSSL_LLM_ROUTER_PROVIDER": lock.provider,
            "HSSL_LLM_ROUTER_PROVIDERS": lock.provider,
            "HSSL_LLM_ROUTER_MODEL": lock.model,
            "IPFS_DATASETS_PY_LLM_PROVIDER": lock.provider,
            "IPFS_DATASETS_PY_LLM_MODEL": lock.model,
            "IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE": "1",
            "IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER": "1",
            "IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI": "0",
            "IPFS_DATASETS_PY_DISABLE_CODEX_FOR_SYMAI": "1",
            "IPFS_DATASETS_PY_SYMAI_BACKEND": lock.provider,
            "IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_MODEL": (
                lock.symai_config_model
            ),
            "IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE": "0",
            "IPFS_DATASETS_PY_SYMAI_ROUTER_CACHE": "0",
            "NEUROSYMBOLIC_ENGINE_MODEL": lock.symai_config_model,
            # SymbolicAI requires a nonempty value. "ipfs" is a routing sentinel,
            # not a provider credential; real provider credentials remain in env.
            "NEUROSYMBOLIC_ENGINE_API_KEY": "ipfs",
        }
    )
    return result


@contextmanager
def temporary_environment(values: Mapping[str, str]) -> Iterator[None]:
    """Temporarily apply an exact environment and restore it afterwards."""

    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def configure_symai(
    lock: SymaiRouterLock,
    config_root: Path | str,
) -> str:
    """Write the minimal locked SyMAI config and return only its digest."""

    from ipfs_datasets_py.utils.symai_config import ensure_symai_config

    root = Path(config_root)
    expected_path = root / ".symai" / "symai.config.json"
    if expected_path.exists():
        path = expected_path
    else:
        path = ensure_symai_config(
            neurosymbolic_model=lock.symai_config_model,
            neurosymbolic_api_key="ipfs",
            force=True,
            apply_engine_router=True,
            config_root=root,
        )
        if path is None:
            raise ProvisioningError("symai_configuration_failed")
    try:
        raw = path.read_bytes()
        decoded = _strict_json(raw.decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ProvisioningError("symai_configuration_failed") from exc
    config = _mapping(decoded, "symai_configuration")
    if (
        config.get("NEUROSYMBOLIC_ENGINE_MODEL") != lock.symai_config_model
        or config.get("NEUROSYMBOLIC_ENGINE_API_KEY") != "ipfs"
        or config.get("SYMBOLIC_ENGINE") != "ipfs"
    ):
        raise ProvisioningError("symai_configuration_drift")
    for key, value in config.items():
        if not _SECRET_NAME_RE.search(str(key)):
            continue
        allowed = (
            key == "NEUROSYMBOLIC_ENGINE_API_KEY" and value == "ipfs"
        ) or value == "" or value is None
        if not allowed:
            raise ProvisioningError("symai_configuration_contains_secret")
    try:
        path.chmod(0o600)
    except OSError as exc:
        raise ProvisioningError("symai_configuration_failed") from exc
    return hashlib.sha256(raw).hexdigest()


def prepare_symai_import(
    lock: SymaiRouterLock,
    config_root: Path | str,
    *,
    importer: Callable[[str], object] = importlib.import_module,
) -> None:
    """Import SyMAI against the isolated prefix without invoking its wizard.

    SymbolicAI 1.14 discovers configuration from ``sys.prefix/.symai`` and
    unconditionally creates that directory during import.  The prefix is
    changed only for the import and restored even if SymbolicAI exits.
    """

    root = Path(config_root).resolve()
    config_path = root / ".symai" / "symai.config.json"
    if not config_path.is_file():
        raise ProvisioningError("symai_configuration_missing")
    original_prefix = sys.prefix
    try:
        sys.prefix = str(root)
        module = importer(lock.import_name)
    except (Exception, SystemExit) as exc:
        sys.modules.pop(lock.import_name, None)
        raise ProvisioningError("symai_import_failed") from exc
    finally:
        sys.prefix = original_prefix
    if getattr(module, "__version__", None) != lock.version:
        raise ProvisioningError("symai_import_version_mismatch")


def _credential_receipts(
    lock: SymaiRouterLock,
    environ: Mapping[str, str],
) -> dict[str, dict[str, object]]:
    receipts: dict[str, dict[str, object]] = {}
    for name in lock.credential_environment:
        value = environ.get(name)
        present = bool(value)
        item: dict[str, object] = {"present": present}
        if present:
            item["sha256"] = hashlib.sha256(
                (
                    f"{EVIDENCE_ID}\0credential-receipt\0{name}\0{value}"
                ).encode("utf-8")
            ).hexdigest()
        receipts[name] = item
    return receipts


def _module_present(
    name: str,
    finder: Callable[[str], object | None],
) -> bool:
    try:
        return finder(name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
        return False


def _distribution_metadata(
    name: str,
    getter: Callable[[str], object],
) -> tuple[str | None, str | None]:
    try:
        distribution = getter(name)
        version = getattr(distribution, "version", None)
        read_text = getattr(distribution, "read_text", None)
        metadata_text = read_text("METADATA") if callable(read_text) else None
    except (ImportError, importlib.metadata.PackageNotFoundError):
        return None, None
    if not isinstance(version, str) or not isinstance(metadata_text, str):
        return None, None
    return version, hashlib.sha256(metadata_text.encode("utf-8")).hexdigest()


def probe_runtime(
    lock: SymaiRouterLock,
    *,
    repository_root: Path | str = REPOSITORY_ROOT,
    environ: Mapping[str, str] | None = None,
    distribution_getter: Callable[[str], object] = importlib.metadata.distribution,
    spec_finder: Callable[[str], object | None] = importlib.util.find_spec,
    config_sha256: str | None = None,
    smoke: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a canonical, secret-safe availability and identity receipt."""

    environment = os.environ if environ is None else environ
    effective_version, metadata_sha256 = _distribution_metadata(
        lock.distribution, distribution_getter
    )
    package_present = _module_present(lock.import_name, spec_finder)
    router_present = _module_present(lock.router_module, spec_finder)
    source_present = (Path(repository_root) / lock.router_source).is_file()
    configured_identity = {
        "symai_provider": environment.get("HSSL_SYMAI_PROVIDER"),
        "symai_model": environment.get("HSSL_SYMAI_MODEL"),
        "router_provider": environment.get("HSSL_LLM_ROUTER_PROVIDER"),
        "router_model": environment.get("HSSL_LLM_ROUTER_MODEL"),
        "top_level_provider": environment.get("IPFS_DATASETS_PY_LLM_PROVIDER"),
        "top_level_model": environment.get("IPFS_DATASETS_PY_LLM_MODEL"),
    }
    expected_identity = {
        "symai_provider": lock.provider,
        "symai_model": lock.model,
        "router_provider": lock.provider,
        "router_model": lock.model,
        "top_level_provider": lock.provider,
        "top_level_model": lock.model,
    }
    errors: list[str] = []
    if effective_version != lock.version:
        errors.append("symbolicai_version_mismatch")
    if metadata_sha256 != lock.metadata_sha256:
        errors.append("symbolicai_artifact_mismatch")
    if not package_present:
        errors.append("symai_import_unavailable")
    if not router_present or not source_present:
        errors.append("existing_router_unavailable")
    if configured_identity != expected_identity:
        errors.append("configured_identity_mismatch")
    if smoke is not None and smoke.get("identity_verified") is not True:
        errors.append("smoke_identity_unverified")

    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "evidence": EVIDENCE_ID,
        "lock_sha256": lock.sha256,
        "status": "ready" if not errors else "unavailable",
        "package": {
            "distribution": lock.distribution,
            "import": lock.import_name,
            "requested_version": lock.version,
            "effective_version": effective_version,
            "requested_metadata_sha256": lock.metadata_sha256,
            "effective_metadata_sha256": metadata_sha256,
            "module_present": package_present,
        },
        "router": {
            "module": lock.router_module,
            "source": lock.router_source,
            "engine": lock.engine,
            "module_present": router_present,
            "source_present": source_present,
            "existing_router": True,
        },
        "identity": {
            "requested_provider": lock.provider,
            "requested_model": lock.model,
            "configured": configured_identity,
            "effective_provider": (
                smoke.get("effective_provider") if smoke is not None else None
            ),
            "effective_model": (
                smoke.get("effective_model") if smoke is not None else None
            ),
            "smoke_verified": bool(
                smoke is not None and smoke.get("identity_verified") is True
            ),
        },
        "configuration": {
            "noninteractive": True,
            "configured": config_sha256 is not None,
            "sha256": config_sha256,
        },
        "credentials": _credential_receipts(lock, environment),
        "safety": dict(_mapping(lock.raw["safety"], "safety")),
        "smoke": dict(smoke) if smoke is not None else None,
        "errors": errors,
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        _canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    return receipt


@contextmanager
def _deadline(seconds: int) -> Iterator[None]:
    """Enforce a wall-clock deadline for the one-call smoke on POSIX."""

    if not hasattr(signal, "setitimer") or not hasattr(signal, "SIGALRM"):
        yield
        return

    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    except TimeoutError as exc:
        raise ProvisioningError("smoke_timeout") from exc
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def run_structured_smoke(
    lock: SymaiRouterLock,
    *,
    engine_factory: Callable[[object, str], object] | None = None,
    trace_getter: Callable[[], Mapping[str, object]] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, object]:
    """Run one non-corpus structured call and return a raw-output-free receipt."""

    from benchmarks.logic_pipeline import adapters, contracts

    if len(SMOKE_TEXT.encode("utf-8")) > lock.max_input_bytes:
        raise ProvisioningError("smoke_input_bound_exceeded")
    try:
        leanstral_lock = _mapping(
            _strict_json(
                DEFAULT_LEANSTRAL_LOCK_PATH.read_text(encoding="utf-8")
            ),
            "leanstral_lock",
        )
        resolved_identity = _mapping(
            leanstral_lock["identity"], "leanstral_identity"
        )
    except (OSError, KeyError, UnicodeError, ProvisioningError) as exc:
        raise ProvisioningError("smoke_resolved_identity_missing") from exc
    config = adapters.SymaiAdapterConfig(
        provider=lock.provider,
        model=lock.model,
        max_retries=lock.max_retries,
        cache_enabled=False,
        max_text_bytes=lock.max_input_bytes,
        max_raw_output_bytes=lock.max_output_bytes,
        expected_inner_provider=str(resolved_identity.get("provider") or ""),
        expected_inner_model=str(resolved_identity.get("model") or ""),
        expected_inner_endpoint=str(resolved_identity.get("endpoint") or ""),
        expected_inner_backend="existing_leanstral_service",
    )
    kwargs: dict[str, object] = {"config": config, "cache": {}}
    if engine_factory is not None:
        kwargs["engine_factory"] = engine_factory
    if trace_getter is not None:
        kwargs["trace_getter"] = trace_getter
    adapter = adapters.SymaiAdapter(**kwargs)
    request = adapters.StageRequest(
        run_id="hssl-symai-router-runtime-smoke",
        case_id="non-corpus-runtime-identity",
        case_manifest_sha256=hashlib.sha256(
            b"HSSL-BENCH-032/non-corpus-smoke"
        ).hexdigest(),
        variant_id="A4",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={"text": SMOKE_TEXT},
        requested_identity={
            "implementation": "symai",
            "provider": lock.provider,
            "model": lock.model,
            "routing_stack": ["hssl_runtime", "llm_router"],
        },
        environment_sha256=lock.sha256,
    )
    with _deadline(timeout_seconds or lock.timeout_seconds):
        record = adapter.run(request)
    if record.status is not contracts.StageStatus.SUCCESS:
        raise ProvisioningError("structured_smoke_failed")
    provenance = record.data.get("backend_provenance")
    if not isinstance(provenance, Mapping):
        raise ProvisioningError("smoke_provenance_missing")
    requested_provider = provenance.get("requested_provider")
    effective_provider = provenance.get("effective_provider")
    requested_model = provenance.get("requested_model")
    effective_model = provenance.get("effective_model")
    if (
        requested_provider != lock.provider
        or effective_provider != lock.provider
        or requested_model != lock.model
        or effective_model != lock.model
    ):
        raise ProvisioningError("smoke_identity_mismatch")
    router_metadata = provenance.get("router_metadata")
    if not isinstance(router_metadata, Mapping):
        raise ProvisioningError("smoke_resolved_identity_missing")
    resolved_provider = router_metadata.get("resolved_provider_name")
    resolved_model = router_metadata.get("resolved_model_name")
    service_endpoint = router_metadata.get("service_endpoint")
    routing_backend = router_metadata.get("routing_backend")
    if (
        resolved_provider != resolved_identity.get("provider")
        or resolved_model != resolved_identity.get("model")
        or service_endpoint != resolved_identity.get("endpoint")
        or routing_backend != "existing_leanstral_service"
    ):
        raise ProvisioningError("smoke_resolved_identity_mismatch")
    if (
        provenance.get("starts_model_server") is not False
        or provenance.get("reuses_existing_model_service") is not True
        or record.telemetry.model_calls != lock.max_calls
        or record.telemetry.retries != lock.max_retries
    ):
        raise ProvisioningError("smoke_routing_policy_mismatch")
    raw_output = record.data.get("raw_output")
    if (
        not isinstance(raw_output, str)
        or len(raw_output.encode("utf-8")) > lock.max_output_bytes
    ):
        raise ProvisioningError("smoke_output_bound_exceeded")
    return {
        "input_kind": "authored-non-corpus",
        "input_sha256": hashlib.sha256(SMOKE_TEXT.encode("utf-8")).hexdigest(),
        "output_sha256": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
        "candidate_ir_sha256": record.data.get("candidate_ir_sha256"),
        "requested_provider": requested_provider,
        "effective_provider": effective_provider,
        "requested_model": requested_model,
        "effective_model": effective_model,
        "resolved_provider": resolved_provider,
        "resolved_model": resolved_model,
        "service_endpoint": service_endpoint,
        "routing_backend": routing_backend,
        "identity_verified": True,
        "structured_contract_validated": True,
        "calls": record.telemetry.model_calls,
        "retries": record.telemetry.retries,
        "timeout_seconds": timeout_seconds or lock.timeout_seconds,
        "starts_model_server": False,
        "starts_model_manager": False,
        "reuses_existing_model_service": True,
        "allow_local_fallback": False,
        "allow_model_fallback": False,
        "allow_provider_fallback": False,
    }


def write_receipt(path: Path | str, receipt: Mapping[str, object]) -> None:
    """Create a canonical receipt without replacing prior run evidence."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(receipt))
            handle.write("\n")
    except FileExistsError as exc:
        raise ProvisioningError("receipt_already_exists") from exc
    try:
        destination.chmod(0o600)
    except OSError as exc:
        raise ProvisioningError("receipt_permission_failed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the lock/runtime (the default action)",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="noninteractively install the exact locked SymbolicAI version",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="write the minimal SyMAI config under --config-root",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="make one bounded live structured call through the existing router",
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        help="isolated writable prefix for SyMAI config (required for config/smoke)",
    )
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lock = load_lock(args.lock)
        if args.timeout is not None and not 1 <= args.timeout <= lock.timeout_seconds:
            raise ProvisioningError("invalid_timeout")
        if (args.configure or args.smoke) and args.config_root is None:
            raise ProvisioningError("config_root_required")
        if args.install:
            install_locked_package(lock)

        environment = pinned_environment(lock)
        config_sha256: str | None = None
        smoke: Mapping[str, object] | None = None
        with temporary_environment(environment):
            if args.configure or args.smoke:
                config_sha256 = configure_symai(lock, args.config_root)
            if args.smoke:
                prepare_symai_import(lock, args.config_root)
                smoke = run_structured_smoke(
                    lock,
                    timeout_seconds=args.timeout or lock.timeout_seconds,
                )
            receipt = probe_runtime(
                lock,
                environ=environment,
                config_sha256=config_sha256,
                smoke=smoke,
            )
        if receipt["status"] != "ready":
            raise ProvisioningError("runtime_unavailable")
        if args.receipt is not None:
            write_receipt(args.receipt, receipt)
        sys.stdout.write(_canonical_json(receipt) + "\n")
        return 0
    except ProvisioningError as exc:
        failure = {
            "schema": RECEIPT_SCHEMA,
            "task_id": TASK_ID,
            "evidence": EVIDENCE_ID,
            "status": "failed",
            "error_code": exc.code,
        }
        sys.stderr.write(_canonical_json(failure) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
