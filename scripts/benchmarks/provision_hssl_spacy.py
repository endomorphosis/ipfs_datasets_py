#!/usr/bin/env python3
"""Provision and attest the artifact-pinned HSSL spaCy runtime.

This command is deliberately independent of benchmark execution.  It creates
or checks a dedicated virtual environment, verifies the locked wheel bytes,
loads the requested model with an isolated Python interpreter, and emits a
content-addressed, corpus-free smoke receipt.  It never imports benchmark
fixtures or writes to a benchmark result namespace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from typing import Final, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import venv


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATH: Final = (
    REPOSITORY_ROOT / "benchmarks/logic_pipeline/runtime_env/spacy.lock"
)
LOCK_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.spacy-runtime-lock.v1"
)
SMOKE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.spacy-runtime-smoke.v1"
)
RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.spacy-runtime-receipt.v1"
)
EVIDENCE_SYMBOL: Final = "HSSLEV1103A41"
MAX_LOCK_BYTES: Final = 64 * 1024
MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class SpacyProvisioningError(RuntimeError):
    """Raised when a lock, artifact, environment, or smoke probe drifts."""


def HSSLEV1103A41() -> str:
    """Return the AST-verifiable full-spaCy runtime evidence marker."""

    return (
        "artifact-pinned spaCy and en_core_web_sm load in a detached "
        "pre-run environment with requested equals effective, no fallback, "
        "and a bounded non-corpus smoke receipt"
    )


def canonical_json(value: object) -> str:
    """Serialize a receipt value deterministically."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def semantic_sha256(value: object) -> str:
    """Return the SHA-256 of a canonical JSON value."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash *path* without reading an artifact into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SpacyProvisioningError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise SpacyProvisioningError(f"non-finite JSON constant is forbidden: {value}")


def _strict_json(raw: str, *, source: str) -> object:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except SpacyProvisioningError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise SpacyProvisioningError(
            f"{source} is not strict JSON: {type(exc).__name__}"
        ) from exc


def _mapping(
    value: object,
    name: str,
    *,
    keys: set[str] | None = None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SpacyProvisioningError(f"{name} must be a JSON object")
    if keys is not None and set(value) != keys:
        missing = sorted(keys - set(value))
        unknown = sorted(set(value) - keys)
        raise SpacyProvisioningError(
            f"{name} fields do not match the lock schema "
            f"(missing={missing}, unknown={unknown})"
        )
    return value


def _string(value: object, name: str, *, safe: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise SpacyProvisioningError(f"{name} must be a nonempty string")
    if safe and _SAFE_NAME.fullmatch(value) is None:
        raise SpacyProvisioningError(f"{name} is not a safe identifier")
    return value


def _sha(value: object, name: str) -> str:
    value = _string(value, name)
    if _SHA256.fullmatch(value) is None:
        raise SpacyProvisioningError(f"{name} must be a lowercase SHA-256")
    return value


def _https_url(value: object, name: str) -> str:
    value = _string(value, name)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SpacyProvisioningError(
            f"{name} must be a credential-free HTTPS artifact URL"
        )
    return value


def _string_list(
    value: object,
    name: str,
    *,
    nonempty: bool = True,
) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise SpacyProvisioningError(f"{name} must be a nonempty string array")
    result = [_string(item, f"{name}[]", safe=True) for item in value]
    if len(result) != len(set(result)):
        raise SpacyProvisioningError(f"{name} contains duplicate values")
    return result


def _validate_artifact(
    value: object,
    name: str,
    *,
    runtime: bool,
) -> dict[str, object]:
    common = {"filename", "url", "size_bytes", "sha256"}
    runtime_keys = {
        "system",
        "machine",
        "python_tag",
        "abi_tag",
        "platform_tag",
    }
    keys = common | runtime_keys if runtime else common
    artifact = _mapping(value, name, keys=keys)
    filename = _string(artifact["filename"], f"{name}.filename", safe=True)
    if Path(filename).name != filename or not filename.endswith(".whl"):
        raise SpacyProvisioningError(f"{name}.filename must name one wheel")
    _https_url(artifact["url"], f"{name}.url")
    _sha(artifact["sha256"], f"{name}.sha256")
    size = artifact["size_bytes"]
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or not 1 <= size <= MAX_ARTIFACT_BYTES
    ):
        raise SpacyProvisioningError(
            f"{name}.size_bytes must be a positive bounded integer"
        )
    if runtime:
        for key in runtime_keys:
            _string(artifact[key], f"{name}.{key}", safe=True)
    return artifact


def validate_lock(value: object) -> dict[str, object]:
    """Validate and return a spaCy runtime lock.

    The schema is closed: unknown fields, loose versions, unpinned URLs,
    duplicate JSON members, and unsafe fallback policy all fail validation.
    """

    lock = _mapping(
        value,
        "lock",
        keys={"schema_version", "evidence", "runtime", "pipeline", "smoke", "safety"},
    )
    if lock["schema_version"] != LOCK_SCHEMA:
        raise SpacyProvisioningError("unsupported spaCy runtime lock schema")
    if lock["evidence"] != EVIDENCE_SYMBOL:
        raise SpacyProvisioningError("lock is not bound to HSSLEV1103A41")

    runtime = _mapping(
        lock["runtime"],
        "runtime",
        keys={"distribution", "version", "python", "prerequisites", "artifacts"},
    )
    if runtime["distribution"] != "spacy":
        raise SpacyProvisioningError("runtime distribution must be spacy")
    for key in ("version", "python"):
        _string(runtime[key], f"runtime.{key}", safe=True)
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(runtime["version"])):
        raise SpacyProvisioningError("runtime.version must be an exact release")
    if not re.fullmatch(r"\d+\.\d+", str(runtime["python"])):
        raise SpacyProvisioningError("runtime.python must pin one minor version")
    prerequisites = runtime["prerequisites"]
    if not isinstance(prerequisites, list) or not prerequisites:
        raise SpacyProvisioningError("runtime.prerequisites must not be empty")
    prerequisite_distributions: list[str] = []
    for index, item in enumerate(prerequisites):
        prerequisite = _mapping(
            item,
            f"runtime.prerequisites[{index}]",
            keys={"distribution", "version", "artifact"},
        )
        prerequisite_distributions.append(
            _string(
                prerequisite["distribution"],
                f"runtime.prerequisites[{index}].distribution",
                safe=True,
            )
        )
        version = _string(
            prerequisite["version"],
            f"runtime.prerequisites[{index}].version",
            safe=True,
        )
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise SpacyProvisioningError(
                f"runtime.prerequisites[{index}].version must be exact"
            )
        _validate_artifact(
            prerequisite["artifact"],
            f"runtime.prerequisites[{index}].artifact",
            runtime=False,
        )
    if len(prerequisite_distributions) != len(set(prerequisite_distributions)):
        raise SpacyProvisioningError(
            "runtime.prerequisites contains duplicate distributions"
        )
    artifacts = runtime["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise SpacyProvisioningError("runtime.artifacts must not be empty")
    validated_artifacts = [
        _validate_artifact(item, f"runtime.artifacts[{index}]", runtime=True)
        for index, item in enumerate(artifacts)
    ]
    selectors = [
        (
            item["system"],
            item["machine"],
            item["python_tag"],
            item["abi_tag"],
            item["platform_tag"],
        )
        for item in validated_artifacts
    ]
    if len(selectors) != len(set(selectors)):
        raise SpacyProvisioningError("runtime.artifacts contains duplicate selectors")

    pipeline = _mapping(
        lock["pipeline"],
        "pipeline",
        keys={
            "package",
            "distribution",
            "version",
            "language",
            "spacy_compatibility",
            "artifact",
            "meta_sha256",
            "pipeline",
            "disabled",
        },
    )
    if pipeline["package"] != "en_core_web_sm":
        raise SpacyProvisioningError("requested pipeline must be en_core_web_sm")
    if pipeline["distribution"] != "en-core-web-sm":
        raise SpacyProvisioningError(
            "pipeline distribution must be en-core-web-sm"
        )
    for key in ("version", "language", "spacy_compatibility"):
        _string(pipeline[key], f"pipeline.{key}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(pipeline["version"])):
        raise SpacyProvisioningError("pipeline.version must be an exact release")
    if pipeline["language"] != "en":
        raise SpacyProvisioningError("pipeline.language must be en")
    _validate_artifact(pipeline["artifact"], "pipeline.artifact", runtime=False)
    _sha(pipeline["meta_sha256"], "pipeline.meta_sha256")
    enabled = _string_list(pipeline["pipeline"], "pipeline.pipeline")
    disabled = _string_list(pipeline["disabled"], "pipeline.disabled", nonempty=False)
    required_components = {
        "tok2vec",
        "tagger",
        "parser",
        "attribute_ruler",
        "lemmatizer",
        "ner",
    }
    if set(enabled) != required_components:
        raise SpacyProvisioningError(
            "pipeline.pipeline does not describe the requested full pipeline"
        )
    if set(enabled) & set(disabled):
        raise SpacyProvisioningError("enabled and disabled components overlap")

    smoke = _mapping(
        lock["smoke"],
        "smoke",
        keys={
            "schema_version",
            "text",
            "text_sha256",
            "max_text_bytes",
            "required_annotations",
        },
    )
    if smoke["schema_version"] != SMOKE_SCHEMA:
        raise SpacyProvisioningError("unsupported smoke schema")
    text = _string(smoke["text"], "smoke.text")
    _sha(smoke["text_sha256"], "smoke.text_sha256")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != smoke["text_sha256"]:
        raise SpacyProvisioningError("smoke.text_sha256 does not match smoke.text")
    max_text_bytes = smoke["max_text_bytes"]
    if (
        not isinstance(max_text_bytes, int)
        or isinstance(max_text_bytes, bool)
        or not 1 <= max_text_bytes <= 1024
        or len(text.encode("utf-8")) > max_text_bytes
    ):
        raise SpacyProvisioningError("smoke text is not bounded by max_text_bytes")
    _string_list(smoke["required_annotations"], "smoke.required_annotations")

    safety = _mapping(
        lock["safety"],
        "safety",
        keys={
            "install_phase",
            "corpus_access",
            "changes_frozen_inputs",
            "allowed_effective_identity",
            "forbidden_effective_identities",
            "fallback_allowed",
        },
    )
    if safety != {
        "install_phase": "pre_run_only",
        "corpus_access": False,
        "changes_frozen_inputs": False,
        "allowed_effective_identity": "en_core_web_sm",
        "forbidden_effective_identities": [
            "spacy.blank:en",
            "regex-legal-parser-v1",
        ],
        "fallback_allowed": False,
    }:
        raise SpacyProvisioningError("lock safety policy permits benchmark drift")
    return lock


def load_lock(path: Path | str = DEFAULT_LOCK_PATH) -> dict[str, object]:
    """Load the bounded strict-JSON runtime lock at *path*."""

    lock_path = Path(path)
    try:
        raw = lock_path.read_bytes()
    except OSError as exc:
        raise SpacyProvisioningError(f"cannot read lock: {lock_path}") from exc
    if not raw or len(raw) > MAX_LOCK_BYTES:
        raise SpacyProvisioningError("spaCy runtime lock is empty or oversized")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpacyProvisioningError("spaCy runtime lock is not UTF-8") from exc
    return validate_lock(_strict_json(text, source=str(lock_path)))


def lock_sha256(lock: Mapping[str, object]) -> str:
    """Return the semantic identity of a validated lock."""

    return semantic_sha256(validate_lock(dict(lock)))


def select_runtime_artifact(
    lock: Mapping[str, object],
    *,
    system: str | None = None,
    machine: str | None = None,
    python_version: tuple[int, int] | None = None,
) -> dict[str, object]:
    """Select the single wheel locked for the current interpreter target."""

    validated = validate_lock(dict(lock))
    requested_system = system or platform.system()
    requested_machine = (machine or platform.machine()).lower()
    requested_machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(
        requested_machine, requested_machine
    )
    version = python_version or (sys.version_info.major, sys.version_info.minor)
    pinned_python = str(_mapping(validated["runtime"], "runtime")["python"])
    if f"{version[0]}.{version[1]}" != pinned_python:
        raise SpacyProvisioningError(
            f"lock requires Python {pinned_python}, got {version[0]}.{version[1]}"
        )
    python_tag = f"cp{version[0]}{version[1]}"
    artifacts = _mapping(validated["runtime"], "runtime")["artifacts"]
    assert isinstance(artifacts, list)
    matches = [
        dict(item)
        for item in artifacts
        if isinstance(item, dict)
        and item["system"] == requested_system
        and item["machine"] == requested_machine
        and item["python_tag"] == python_tag
    ]
    if len(matches) != 1:
        raise SpacyProvisioningError(
            "no unique locked spaCy wheel for "
            f"{requested_system}/{requested_machine}/{python_tag}"
        )
    return matches[0]


def _active_benchmark_run() -> str | None:
    for name in (
        "HSSL_BENCHMARK_RUN_ACTIVE",
        "HSSL_EVALUATION_RUN_ACTIVE",
    ):
        value = os.environ.get(name, "").strip().lower()
        if value and value not in {"0", "false", "no", "off"}:
            return name
    return None


def validate_destination(path: Path | str) -> Path:
    """Resolve a detached pre-run destination and reject result namespaces."""

    active_marker = _active_benchmark_run()
    if active_marker:
        raise SpacyProvisioningError(
            f"refusing provisioning during an active benchmark run ({active_marker})"
        )
    target = Path(path).expanduser()
    if target.exists() and target.is_symlink():
        raise SpacyProvisioningError("virtual environment destination is a symlink")
    target = target.resolve()
    if target == Path(sys.prefix).resolve():
        raise SpacyProvisioningError(
            "the detached runtime cannot be the current Python environment"
        )
    lowered_parts = [part.lower() for part in target.parts]
    if "results" in lowered_parts and "hammer-symai-spacy-leanstral" in lowered_parts:
        raise SpacyProvisioningError(
            "the runtime cannot be provisioned inside a frozen result namespace"
        )
    if target == REPOSITORY_ROOT or (
        REPOSITORY_ROOT in target.parents
        and ("workspace" in lowered_parts or "data" in lowered_parts)
    ):
        raise SpacyProvisioningError(
            "the runtime cannot be provisioned in benchmark evidence or data paths"
        )
    return target


def _artifact_cache_path(cache_dir: Path, artifact: Mapping[str, object]) -> Path:
    return cache_dir / str(artifact["filename"])


def fetch_artifact(
    artifact: Mapping[str, object],
    cache_dir: Path | str,
    *,
    offline: bool = False,
) -> Path:
    """Return a verified cached artifact, downloading atomically when allowed."""

    cache = Path(cache_dir).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    destination = _artifact_cache_path(cache, artifact)
    expected_sha = str(artifact["sha256"])
    expected_size = artifact.get("size_bytes")
    if destination.exists():
        if not destination.is_file():
            raise SpacyProvisioningError(
                f"artifact cache entry is not a file: {destination}"
            )
        if expected_size is not None and destination.stat().st_size != expected_size:
            raise SpacyProvisioningError(
                f"cached artifact size mismatch: {destination.name}"
            )
        if file_sha256(destination) != expected_sha:
            raise SpacyProvisioningError(
                f"cached artifact SHA-256 mismatch: {destination.name}"
            )
        return destination
    if offline:
        raise SpacyProvisioningError(
            f"offline artifact is not cached: {destination.name}"
        )

    request = Request(
        str(artifact["url"]),
        headers={"User-Agent": "ipfs-datasets-hssl-spacy-provisioner/1"},
    )
    partial: Path | None = None
    byte_count = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=cache,
            delete=False,
        ) as stream:
            partial = Path(stream.name)
            with urlopen(request, timeout=60) as response:
                final_url = urlsplit(response.geturl())
                if final_url.scheme != "https":
                    raise SpacyProvisioningError(
                        "artifact download redirected away from HTTPS"
                    )
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    if byte_count > MAX_ARTIFACT_BYTES:
                        raise SpacyProvisioningError("artifact exceeds download bound")
                    stream.write(chunk)
        if expected_size is not None and byte_count != expected_size:
            raise SpacyProvisioningError(
                f"downloaded artifact size mismatch: {destination.name}"
            )
        assert partial is not None
        if file_sha256(partial) != expected_sha:
            raise SpacyProvisioningError(
                f"downloaded artifact SHA-256 mismatch: {destination.name}"
            )
        partial.replace(destination)
        partial = None
        return destination
    except (OSError, SpacyProvisioningError) as exc:
        if isinstance(exc, SpacyProvisioningError):
            raise
        raise SpacyProvisioningError(
            f"artifact download failed for {destination.name}: {type(exc).__name__}"
        ) from exc
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts/python.exe"
    return environment / "bin/python"


def ensure_environment(environment: Path | str) -> tuple[Path, Path]:
    """Create or validate a dedicated virtual environment."""

    target = validate_destination(environment)
    if target.exists():
        if not (target / "pyvenv.cfg").is_file():
            if any(target.iterdir()):
                raise SpacyProvisioningError(
                    "destination exists and is not a virtual environment"
                )
            venv.EnvBuilder(with_pip=True).create(target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True).create(target)
    python = _venv_python(target)
    if not python.is_file():
        raise SpacyProvisioningError("virtual environment Python is unavailable")
    return target, python


def _run_checked(
    command: Sequence[str],
    *,
    offline: bool,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    try:
        return subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()[-1000:]
        suffix = f": {detail}" if detail else ""
        raise SpacyProvisioningError(
            f"runtime command failed ({type(exc).__name__}){suffix}"
        ) from exc


def install_locked_runtime(
    python: Path,
    runtime_artifact: Path,
    pipeline_artifact: Path,
    *,
    prerequisite_artifacts: Sequence[Path] = (),
    cache_dir: Path,
    offline: bool,
) -> None:
    """Install the verified wheels without resolving either locked identity."""

    common = [
        str(python),
        "-I",
        "-m",
        "pip",
        "install",
        "--no-input",
        "--only-binary=:all:",
        "--force-reinstall",
    ]
    if offline:
        common.extend(["--no-index", "--find-links", str(cache_dir)])
    if prerequisite_artifacts:
        _run_checked(
            [*common, "--no-deps", *(str(path) for path in prerequisite_artifacts)],
            offline=offline,
        )
    _run_checked([*common, str(runtime_artifact)], offline=offline)
    _run_checked(
        [*common, "--no-deps", str(pipeline_artifact)],
        offline=offline,
    )
    _run_checked(
        [str(python), "-I", "-m", "pip", "check"],
        offline=offline,
        timeout=120,
    )


_PROBE_SOURCE: Final = r"""
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

request = json.loads(sys.stdin.read())
import spacy
model_module = importlib.import_module(request["pipeline_package"])
model_meta_path = Path(model_module.__file__).resolve().with_name("meta.json")
model_meta_sha256 = hashlib.sha256(model_meta_path.read_bytes()).hexdigest()
nlp = spacy.load(request["pipeline_package"])
doc = nlp(request["smoke_text"])
annotations = {
    name: bool(doc.has_annotation(name))
    for name in request["required_annotations"]
}
sentences = list(doc.sents)
token_projection = [
    [token.text, token.lemma_, token.pos_, token.tag_, token.dep_, token.ent_iob_]
    for token in doc
]
smoke_projection = {
    "annotations": annotations,
    "entity_count": len(doc.ents),
    "sentence_count": len(sentences),
    "token_count": len(doc),
    "token_projection": token_projection,
}
effective_name = f"{nlp.meta.get('lang', '')}_{nlp.meta.get('name', '')}"
result = {
    "python": {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
    },
    "runtime": {
        "distribution": "spacy",
        "version": importlib.metadata.version("spacy"),
    },
    "pipeline": {
        "distribution": "en-core-web-sm",
        "distribution_version": importlib.metadata.version("en-core-web-sm"),
        "package": request["pipeline_package"],
        "effective_name": effective_name,
        "model_language": nlp.meta.get("lang"),
        "model_name": nlp.meta.get("name"),
        "model_version": nlp.meta.get("version"),
        "meta_sha256": model_meta_sha256,
        "pipeline": list(nlp.pipe_names),
        "disabled": list(nlp.disabled),
        "used_fallback_model": False,
    },
    "smoke": {
        "input_sha256": hashlib.sha256(
            request["smoke_text"].encode("utf-8")
        ).hexdigest(),
        "input_bytes": len(request["smoke_text"].encode("utf-8")),
        "annotations": annotations,
        "sentence_count": len(sentences),
        "token_count": len(doc),
        "entity_count": len(doc.ents),
        "output_sha256": hashlib.sha256(
            json.dumps(
                smoke_projection,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    },
}
print(json.dumps(result, separators=(",", ":"), sort_keys=True))
"""


def _validate_probe(
    lock: Mapping[str, object],
    probe: object,
) -> dict[str, object]:
    probe = _mapping(
        probe,
        "probe",
        keys={"python", "runtime", "pipeline", "smoke"},
    )
    runtime_lock = _mapping(lock["runtime"], "runtime")
    pipeline_lock = _mapping(lock["pipeline"], "pipeline")
    smoke_lock = _mapping(lock["smoke"], "smoke")
    python = _mapping(
        probe["python"],
        "probe.python",
        keys={"implementation", "version"},
    )
    runtime = _mapping(
        probe["runtime"],
        "probe.runtime",
        keys={"distribution", "version"},
    )
    pipeline = _mapping(
        probe["pipeline"],
        "probe.pipeline",
        keys={
            "distribution",
            "distribution_version",
            "package",
            "effective_name",
            "model_language",
            "model_name",
            "model_version",
            "meta_sha256",
            "pipeline",
            "disabled",
            "used_fallback_model",
        },
    )
    smoke = _mapping(
        probe["smoke"],
        "probe.smoke",
        keys={
            "input_sha256",
            "input_bytes",
            "annotations",
            "sentence_count",
            "token_count",
            "entity_count",
            "output_sha256",
        },
    )

    python_version = _string(python.get("version"), "probe.python.version")
    if (
        python.get("implementation") != "CPython"
        or ".".join(python_version.split(".")[:2]) != runtime_lock["python"]
    ):
        raise SpacyProvisioningError("probe Python version differs from lock")
    if (
        runtime.get("distribution") != runtime_lock["distribution"]
        or runtime.get("version") != runtime_lock["version"]
    ):
        raise SpacyProvisioningError("effective spaCy distribution differs from lock")
    if (
        pipeline.get("distribution") != pipeline_lock["distribution"]
        or pipeline.get("distribution_version") != pipeline_lock["version"]
        or pipeline.get("package") != pipeline_lock["package"]
        or pipeline.get("effective_name") != pipeline_lock["package"]
        or pipeline.get("model_language") != pipeline_lock["language"]
        or pipeline.get("model_version") != pipeline_lock["version"]
        or pipeline.get("meta_sha256") != pipeline_lock["meta_sha256"]
        or pipeline.get("pipeline") != pipeline_lock["pipeline"]
        or pipeline.get("disabled") != pipeline_lock["disabled"]
        or pipeline.get("used_fallback_model") is not False
    ):
        raise SpacyProvisioningError(
            "effective spaCy pipeline identity or components differ from lock"
        )
    annotations = smoke.get("annotations")
    required = smoke_lock["required_annotations"]
    if (
        smoke.get("input_sha256") != smoke_lock["text_sha256"]
        or not isinstance(smoke.get("input_bytes"), int)
        or smoke["input_bytes"] > smoke_lock["max_text_bytes"]
        or not isinstance(annotations, dict)
        or set(annotations) != set(required)
        or not all(annotations.values())
        or not isinstance(smoke.get("sentence_count"), int)
        or smoke["sentence_count"] < 1
        or not isinstance(smoke.get("token_count"), int)
        or smoke["token_count"] < 1
    ):
        raise SpacyProvisioningError(
            "bounded smoke did not produce all full-pipeline annotations"
        )
    _sha(smoke.get("output_sha256"), "probe.smoke.output_sha256")
    return probe


def probe_runtime(
    python: Path | str,
    lock: Mapping[str, object],
) -> dict[str, object]:
    """Run the fixed smoke in an isolated interpreter and validate its output."""

    validated = validate_lock(dict(lock))
    pipeline = _mapping(validated["pipeline"], "pipeline")
    smoke = _mapping(validated["smoke"], "smoke")
    request = {
        "pipeline_package": pipeline["package"],
        "required_annotations": smoke["required_annotations"],
        "smoke_text": smoke["text"],
    }
    try:
        completed = subprocess.run(
            [str(Path(python)), "-I", "-c", _PROBE_SOURCE],
            input=canonical_json(request),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ
            | {
                "PYTHONNOUSERSITE": "1",
                "PYTHONHASHSEED": "0",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()[-1000:]
        suffix = f": {detail}" if detail else ""
        raise SpacyProvisioningError(
            f"detached spaCy smoke failed ({type(exc).__name__}){suffix}"
        ) from exc
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(output_lines) != 1:
        raise SpacyProvisioningError("detached probe emitted unexpected output")
    decoded = _strict_json(output_lines[0], source="detached spaCy probe")
    return _validate_probe(validated, decoded)


def build_receipt(
    lock: Mapping[str, object],
    probe: Mapping[str, object],
    runtime_artifact: Mapping[str, object],
    *,
    installation_mode: str,
) -> dict[str, object]:
    """Build and self-validate a secret-free, content-addressed smoke receipt."""

    validated = validate_lock(dict(lock))
    validated_probe = _validate_probe(validated, dict(probe))
    pipeline = _mapping(validated["pipeline"], "pipeline")
    runtime = _mapping(validated["runtime"], "runtime")
    artifact = _mapping(pipeline["artifact"], "pipeline.artifact")
    receipt: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA,
        "evidence": EVIDENCE_SYMBOL,
        "status": "pass",
        "lock_sha256": lock_sha256(validated),
        "installation_mode": installation_mode,
        "requested_identity": {
            "implementation": runtime["distribution"],
            "runtime_version": runtime["version"],
            "model": pipeline["package"],
            "model_version": pipeline["version"],
        },
        "effective_identity": {
            "implementation": validated_probe["runtime"]["distribution"],
            "runtime_version": validated_probe["runtime"]["version"],
            "model": validated_probe["pipeline"]["effective_name"],
            "model_version": validated_probe["pipeline"]["model_version"],
        },
        "python": validated_probe["python"],
        "artifacts": {
            "runtime": {
                "filename": runtime_artifact["filename"],
                "sha256": runtime_artifact["sha256"],
            },
            "prerequisites": [
                {
                    "distribution": item["distribution"],
                    "version": item["version"],
                    "filename": item["artifact"]["filename"],
                    "sha256": item["artifact"]["sha256"],
                }
                for item in runtime["prerequisites"]
            ],
            "pipeline": {
                "filename": artifact["filename"],
                "sha256": artifact["sha256"],
            },
            "verified_before_install": installation_mode == "provisioned",
        },
        "pipeline": validated_probe["pipeline"],
        "smoke": validated_probe["smoke"],
        "safety": {
            "pre_run_only": True,
            "corpus_accessed": False,
            "frozen_inputs_changed": False,
            "fallback_used": False,
            "production_routing_changed": False,
        },
    }
    receipt["receipt_sha256"] = semantic_sha256(receipt)
    return validate_smoke_receipt(validated, receipt)


def validate_smoke_receipt(
    lock: Mapping[str, object],
    receipt: object,
) -> dict[str, object]:
    """Strictly bind a receipt to *lock* and recompute all identity claims."""

    validated = validate_lock(dict(lock))
    receipt = _mapping(
        receipt,
        "receipt",
        keys={
            "schema_version",
            "evidence",
            "status",
            "lock_sha256",
            "installation_mode",
            "requested_identity",
            "effective_identity",
            "python",
            "artifacts",
            "pipeline",
            "smoke",
            "safety",
            "receipt_sha256",
        },
    )
    if (
        receipt["schema_version"] != RECEIPT_SCHEMA
        or receipt["evidence"] != EVIDENCE_SYMBOL
        or receipt["status"] != "pass"
        or receipt["lock_sha256"] != lock_sha256(validated)
        or receipt["installation_mode"] not in {"provisioned", "verify_only"}
    ):
        raise SpacyProvisioningError("receipt header does not match the runtime lock")
    pipeline_lock = _mapping(validated["pipeline"], "pipeline")
    runtime_lock = _mapping(validated["runtime"], "runtime")
    identity_keys = {
        "implementation",
        "runtime_version",
        "model",
        "model_version",
    }
    requested = _mapping(
        receipt["requested_identity"],
        "requested_identity",
        keys=identity_keys,
    )
    effective = _mapping(
        receipt["effective_identity"],
        "effective_identity",
        keys=identity_keys,
    )
    expected_identity = {
        "implementation": runtime_lock["distribution"],
        "runtime_version": runtime_lock["version"],
        "model": pipeline_lock["package"],
        "model_version": pipeline_lock["version"],
    }
    if requested != expected_identity or effective != expected_identity:
        raise SpacyProvisioningError(
            "receipt requested/effective identities are not exact and equal"
        )
    probe = {
        "python": receipt["python"],
        "runtime": {
            "distribution": effective["implementation"],
            "version": effective["runtime_version"],
        },
        "pipeline": receipt["pipeline"],
        "smoke": receipt["smoke"],
    }
    _validate_probe(validated, probe)
    artifacts = _mapping(
        receipt["artifacts"],
        "artifacts",
        keys={
            "runtime",
            "prerequisites",
            "pipeline",
            "verified_before_install",
        },
    )
    artifact_receipt_keys = {"filename", "sha256"}
    runtime_artifact = _mapping(
        artifacts.get("runtime"),
        "artifacts.runtime",
        keys=artifact_receipt_keys,
    )
    pipeline_artifact = _mapping(
        artifacts.get("pipeline"),
        "artifacts.pipeline",
        keys=artifact_receipt_keys,
    )
    prerequisite_artifacts = artifacts.get("prerequisites")
    locked_runtime_artifacts = [
        {
            "filename": item["filename"],
            "sha256": item["sha256"],
        }
        for item in runtime_lock["artifacts"]
        if isinstance(item, dict)
    ]
    locked_pipeline_artifact = _mapping(
        pipeline_lock["artifact"], "pipeline.artifact"
    )
    expected_prerequisites = [
        {
            "distribution": item["distribution"],
            "version": item["version"],
            "filename": item["artifact"]["filename"],
            "sha256": item["artifact"]["sha256"],
        }
        for item in runtime_lock["prerequisites"]
        if isinstance(item, dict) and isinstance(item.get("artifact"), dict)
    ]
    if (
        runtime_artifact not in locked_runtime_artifacts
        or prerequisite_artifacts != expected_prerequisites
        or pipeline_artifact
        != {
            "filename": locked_pipeline_artifact["filename"],
            "sha256": locked_pipeline_artifact["sha256"],
        }
        or type(artifacts.get("verified_before_install")) is not bool
    ):
        raise SpacyProvisioningError("receipt artifact identities differ from lock")
    safety = _mapping(
        receipt["safety"],
        "receipt.safety",
        keys={
            "pre_run_only",
            "corpus_accessed",
            "frozen_inputs_changed",
            "fallback_used",
            "production_routing_changed",
        },
    )
    if safety != {
        "pre_run_only": True,
        "corpus_accessed": False,
        "frozen_inputs_changed": False,
        "fallback_used": False,
        "production_routing_changed": False,
    }:
        raise SpacyProvisioningError("receipt does not preserve the safety boundary")
    expected_digest = _sha(receipt["receipt_sha256"], "receipt.receipt_sha256")
    body = dict(receipt)
    del body["receipt_sha256"]
    if semantic_sha256(body) != expected_digest:
        raise SpacyProvisioningError("receipt SHA-256 does not match its content")
    return receipt


def write_receipt(path: Path | str, receipt: Mapping[str, object]) -> Path:
    """Atomically write a validated receipt as canonical JSON."""

    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(canonical_json(receipt) + "\n", encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def provision(
    *,
    lock_path: Path | str,
    environment: Path | str,
    cache_dir: Path | str,
    receipt_path: Path | str,
    offline: bool = False,
    verify_only: bool = False,
) -> dict[str, object]:
    """Provision or verify the detached runtime and return its smoke receipt."""

    lock = load_lock(lock_path)
    runtime_artifact = select_runtime_artifact(lock)
    target = validate_destination(environment)
    if verify_only:
        python = _venv_python(target)
        if not python.is_file() or not (target / "pyvenv.cfg").is_file():
            raise SpacyProvisioningError(
                "verify-only requires an existing detached virtual environment"
            )
        mode = "verify_only"
    else:
        target, python = ensure_environment(target)
        cache = Path(cache_dir).expanduser().resolve()
        runtime_wheel = fetch_artifact(runtime_artifact, cache, offline=offline)
        runtime = _mapping(lock["runtime"], "runtime")
        prerequisite_wheels = [
            fetch_artifact(
                _mapping(item, "runtime.prerequisite")["artifact"],
                cache,
                offline=offline,
            )
            for item in runtime["prerequisites"]
            if isinstance(item, dict)
        ]
        pipeline = _mapping(lock["pipeline"], "pipeline")
        pipeline_artifact = _mapping(pipeline["artifact"], "pipeline.artifact")
        pipeline_wheel = fetch_artifact(
            pipeline_artifact,
            cache,
            offline=offline,
        )
        install_locked_runtime(
            python,
            runtime_wheel,
            pipeline_wheel,
            prerequisite_artifacts=prerequisite_wheels,
            cache_dir=cache,
            offline=offline,
        )
        mode = "provisioned"
    probe = probe_runtime(python, lock)
    receipt = build_receipt(
        lock,
        probe,
        runtime_artifact,
        installation_mode=mode,
    )
    write_receipt(receipt_path, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Provision the artifact-pinned full spaCy pipeline in a detached "
            "pre-run virtual environment and emit a non-corpus smoke receipt."
        )
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument(
        "--venv",
        type=Path,
        help="dedicated virtual environment outside benchmark result/data paths",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="verified wheel cache (default: sibling hssl-spacy-artifacts)",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="receipt path (default: sibling hssl-spacy-smoke-receipt.json)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="require all wheels and dependencies to be available in cache",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="do not install; verify an existing detached environment",
    )
    parser.add_argument(
        "--print-lock-digest",
        action="store_true",
        help="validate the lock and print its semantic SHA-256 without provisioning",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        lock = load_lock(args.lock)
        if args.print_lock_digest:
            print(lock_sha256(lock))
            return 0
        if args.venv is None:
            parser.error("--venv is required unless --print-lock-digest is used")
        environment = args.venv.expanduser().resolve()
        cache_dir = (
            args.cache_dir.expanduser().resolve()
            if args.cache_dir is not None
            else environment.parent / "hssl-spacy-artifacts"
        )
        receipt_path = (
            args.receipt.expanduser().resolve()
            if args.receipt is not None
            else environment.parent / "hssl-spacy-smoke-receipt.json"
        )
        receipt = provision(
            lock_path=args.lock,
            environment=environment,
            cache_dir=cache_dir,
            receipt_path=receipt_path,
            offline=args.offline,
            verify_only=args.verify_only,
        )
    except SpacyProvisioningError as exc:
        parser.exit(2, f"spaCy provisioning failed: {exc}\n")
    print(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
