"""Integration evidence for the artifact-pinned HSSL full-spaCy runtime."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts.benchmarks import provision_hssl_spacy as provisioning


LOCK_PATH = (
    Path(__file__).resolve().parents[4]
    / "benchmarks/logic_pipeline/runtime_env/spacy.lock"
)
LOCK_DIGEST = "f45945e4e8a24305b3ade669ed52da2df2b0af63267b9ef28823b9bac442d68d"


def _probe(lock: dict[str, object]) -> dict[str, object]:
    runtime = lock["runtime"]
    pipeline = lock["pipeline"]
    smoke = lock["smoke"]
    assert isinstance(runtime, dict)
    assert isinstance(pipeline, dict)
    assert isinstance(smoke, dict)
    annotations = {
        name: True for name in smoke["required_annotations"]
    }
    return {
        "python": {
            "implementation": "CPython",
            "version": f"{runtime['python']}.9",
        },
        "runtime": {
            "distribution": runtime["distribution"],
            "version": runtime["version"],
        },
        "pipeline": {
            "distribution": pipeline["distribution"],
            "distribution_version": pipeline["version"],
            "package": pipeline["package"],
            "effective_name": pipeline["package"],
            "model_language": pipeline["language"],
            "model_name": "core_web_sm",
            "model_version": pipeline["version"],
            "meta_sha256": pipeline["meta_sha256"],
            "pipeline": pipeline["pipeline"],
            "disabled": pipeline["disabled"],
            "used_fallback_model": False,
        },
        "smoke": {
            "input_sha256": smoke["text_sha256"],
            "input_bytes": len(smoke["text"].encode("utf-8")),
            "annotations": annotations,
            "sentence_count": 1,
            "token_count": 10,
            "entity_count": 2,
            "output_sha256": "d" * 64,
        },
    }


def test_objective_symbol_and_lock_pin_the_requested_full_pipeline() -> None:
    lock = provisioning.load_lock(LOCK_PATH)

    assert "artifact-pinned spaCy" in provisioning.HSSLEV1103A41()
    assert "requested equals effective" in provisioning.HSSLEV1103A41()
    assert lock["schema_version"] == provisioning.LOCK_SCHEMA
    assert lock["evidence"] == "HSSLEV1103A41"
    assert provisioning.lock_sha256(lock) == LOCK_DIGEST

    runtime = lock["runtime"]
    pipeline = lock["pipeline"]
    safety = lock["safety"]
    assert runtime["distribution"] == "spacy"
    assert runtime["version"] == "3.8.14"
    assert runtime["python"] == "3.12"
    assert runtime["prerequisites"] == [
        {
            "distribution": "click",
            "version": "8.3.2",
            "artifact": {
                "filename": "click-8.3.2-py3-none-any.whl",
                "url": (
                    "https://files.pythonhosted.org/packages/e4/20/"
                    "71885d8b97d4f3dde17b1fdb92dbd4908b00541c5a3379787137285f602e/"
                    "click-8.3.2-py3-none-any.whl"
                ),
                "size_bytes": 108379,
                "sha256": (
                    "1924d2c27c5653561cd2cae4548d1406039cb79b858b747cfea24924bbc1616d"
                ),
            },
        }
    ]
    assert {
        item["sha256"] for item in runtime["artifacts"]
    } == {
        "daeb64b048f12c059997281aed53eb8776d26416dd313cf17ad6f63124b2b564",
        "6d45715a24446f23b98ec3f09409a1d4111983d1d64613250ee38c3270e21853",
    }
    assert pipeline["package"] == "en_core_web_sm"
    assert pipeline["version"] == "3.8.0"
    assert pipeline["artifact"]["sha256"] == (
        "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
    )
    assert pipeline["meta_sha256"] == (
        "7456349002fa8cf31111051bd37fdbea67a1b7f7a0a60ce235466f98a6758125"
    )
    assert pipeline["pipeline"] == [
        "tok2vec",
        "tagger",
        "parser",
        "attribute_ruler",
        "lemmatizer",
        "ner",
    ]
    assert pipeline["disabled"] == ["senter"]
    assert safety["fallback_allowed"] is False
    assert safety["corpus_access"] is False
    assert safety["changes_frozen_inputs"] is False


def test_runtime_wheel_selection_is_exact_and_normalizes_machine_aliases() -> None:
    lock = provisioning.load_lock(LOCK_PATH)

    x86 = provisioning.select_runtime_artifact(
        lock,
        system="Linux",
        machine="AMD64",
        python_version=(3, 12),
    )
    arm = provisioning.select_runtime_artifact(
        lock,
        system="Linux",
        machine="arm64",
        python_version=(3, 12),
    )

    assert x86["machine"] == "x86_64"
    assert x86["filename"].endswith("manylinux_2_17_x86_64.whl")
    assert arm["machine"] == "aarch64"
    assert arm["filename"].endswith("manylinux_2_17_aarch64.whl")
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="requires Python 3.12",
    ):
        provisioning.select_runtime_artifact(
            lock,
            system="Linux",
            machine="x86_64",
            python_version=(3, 13),
        )
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="no unique locked spaCy wheel",
    ):
        provisioning.select_runtime_artifact(
            lock,
            system="Darwin",
            machine="arm64",
            python_version=(3, 12),
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda lock: lock["pipeline"].__setitem__(
                "version", "3.8"
            ),
            "exact release",
        ),
        (
            lambda lock: lock["smoke"].__setitem__("text", "changed"),
            "does not match",
        ),
        (
            lambda lock: lock["safety"].__setitem__("fallback_allowed", True),
            "permits benchmark drift",
        ),
        (
            lambda lock: lock.__setitem__("unregistered", True),
            "fields do not match",
        ),
    ],
)
def test_lock_validation_fails_closed_on_identity_or_policy_drift(
    mutate,
    message: str,
) -> None:
    lock = provisioning.load_lock(LOCK_PATH)
    changed = deepcopy(lock)
    mutate(changed)
    with pytest.raises(provisioning.SpacyProvisioningError, match=message):
        provisioning.validate_lock(changed)


def test_lock_loader_rejects_duplicate_members_and_nonfinite_json(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.lock"
    duplicate.write_text(
        '{"schema_version":"x","schema_version":"y"}',
        encoding="utf-8",
    )
    nonfinite = tmp_path / "nonfinite.lock"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")

    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="duplicate JSON key",
    ):
        provisioning.load_lock(duplicate)
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="non-finite",
    ):
        provisioning.load_lock(nonfinite)


def test_semantic_lock_digest_detects_a_well_formed_artifact_substitution() -> None:
    lock = provisioning.load_lock(LOCK_PATH)
    changed = deepcopy(lock)
    changed["pipeline"]["artifact"]["sha256"] = "0" * 64

    assert provisioning.lock_sha256(changed) != LOCK_DIGEST


def test_verified_artifact_cache_is_offline_safe_and_tamper_evident(
    tmp_path: Path,
) -> None:
    data = b"locked-wheel-bytes"
    artifact = {
        "filename": "locked-1.0-py3-none-any.whl",
        "url": "https://example.invalid/locked-1.0-py3-none-any.whl",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    cache = tmp_path / "cache"
    cache.mkdir()
    wheel = cache / artifact["filename"]
    wheel.write_bytes(data)

    assert provisioning.fetch_artifact(artifact, cache, offline=True) == wheel

    wheel.write_bytes(data + b"-tampered")
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="size mismatch",
    ):
        provisioning.fetch_artifact(artifact, cache, offline=True)

    wheel.unlink()
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="offline artifact is not cached",
    ):
        provisioning.fetch_artifact(artifact, cache, offline=True)


def test_detached_probe_uses_isolated_python_and_validates_full_annotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = provisioning.load_lock(LOCK_PATH)
    expected = _probe(lock)
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs["input"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=provisioning.canonical_json(expected) + "\n",
            stderr="",
        )

    monkeypatch.setattr(provisioning.subprocess, "run", fake_run)
    observed = provisioning.probe_runtime(
        Path("/detached/hssl-spacy/bin/python"),
        lock,
    )

    assert seen["command"][1:3] == ["-I", "-c"]
    assert lock["smoke"]["text"] not in seen["command"]
    assert json.loads(seen["input"])["smoke_text"] == lock["smoke"]["text"]
    assert observed["pipeline"]["effective_name"] == "en_core_web_sm"
    assert observed["pipeline"]["used_fallback_model"] is False
    assert all(observed["smoke"]["annotations"].values())


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("runtime", "version"), "3.8.13", "distribution differs"),
        (("pipeline", "effective_name"), "spacy.blank:en", "identity"),
        (("pipeline", "used_fallback_model"), True, "identity"),
        (("pipeline", "pipeline"), ["tok2vec"], "components"),
        (("smoke", "annotations", "DEP"), False, "annotations"),
    ],
)
def test_probe_fails_closed_on_version_identity_fallback_or_component_drift(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    lock = provisioning.load_lock(LOCK_PATH)
    probe = _probe(lock)
    target = probe
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(provisioning.SpacyProvisioningError, match=message):
        provisioning._validate_probe(lock, probe)


def test_smoke_receipt_binds_equal_identities_artifacts_and_safety() -> None:
    lock = provisioning.load_lock(LOCK_PATH)
    runtime_artifact = provisioning.select_runtime_artifact(
        lock,
        system="Linux",
        machine="x86_64",
        python_version=(3, 12),
    )
    receipt = provisioning.build_receipt(
        lock,
        _probe(lock),
        runtime_artifact,
        installation_mode="provisioned",
    )

    assert receipt["requested_identity"] == receipt["effective_identity"]
    assert receipt["effective_identity"]["model"] == "en_core_web_sm"
    assert receipt["python"] == {
        "implementation": "CPython",
        "version": "3.12.9",
    }
    assert receipt["artifacts"]["verified_before_install"] is True
    assert receipt["pipeline"]["used_fallback_model"] is False
    assert receipt["smoke"]["input_sha256"] == lock["smoke"]["text_sha256"]
    assert "text" not in receipt["smoke"]
    assert receipt["safety"] == {
        "pre_run_only": True,
        "corpus_accessed": False,
        "frozen_inputs_changed": False,
        "fallback_used": False,
        "production_routing_changed": False,
    }
    assert provisioning.validate_smoke_receipt(lock, receipt) == receipt

    tampered = deepcopy(receipt)
    tampered["effective_identity"]["model"] = "spacy.blank:en"
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="not exact and equal",
    ):
        provisioning.validate_smoke_receipt(lock, tampered)

    tampered = deepcopy(receipt)
    tampered["smoke"]["token_count"] += 1
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="receipt SHA-256",
    ):
        provisioning.validate_smoke_receipt(lock, tampered)


def test_provisioning_is_pre_run_detached_and_writes_a_valid_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = provisioning.load_lock(LOCK_PATH)
    runtime_artifact = provisioning.select_runtime_artifact(
        lock,
        system="Linux",
        machine="x86_64",
        python_version=(3, 12),
    )
    environment = tmp_path / "detached-spacy"
    python = environment / "bin/python"
    cache = tmp_path / "artifacts"
    receipt_path = tmp_path / "spacy-smoke-receipt.json"
    installed: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        provisioning,
        "select_runtime_artifact",
        lambda _lock: runtime_artifact,
    )
    monkeypatch.setattr(
        provisioning,
        "ensure_environment",
        lambda _environment: (environment, python),
    )
    monkeypatch.setattr(
        provisioning,
        "fetch_artifact",
        lambda artifact, _cache, offline=False: cache / artifact["filename"],
    )
    monkeypatch.setattr(
        provisioning,
        "install_locked_runtime",
        lambda _python, runtime_wheel, pipeline_wheel, **_kwargs: installed.append(
            (runtime_wheel, pipeline_wheel)
        ),
    )
    monkeypatch.setattr(
        provisioning,
        "probe_runtime",
        lambda _python, _lock: _probe(lock),
    )

    receipt = provisioning.provision(
        lock_path=LOCK_PATH,
        environment=environment,
        cache_dir=cache,
        receipt_path=receipt_path,
    )

    assert len(installed) == 1
    assert installed[0][0].name == runtime_artifact["filename"]
    assert installed[0][1].name == lock["pipeline"]["artifact"]["filename"]
    assert receipt["installation_mode"] == "provisioned"
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert provisioning.validate_smoke_receipt(lock, on_disk) == receipt

    monkeypatch.setenv("HSSL_BENCHMARK_RUN_ACTIVE", "1")
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="active benchmark run",
    ):
        provisioning.validate_destination(tmp_path / "another-runtime")


def test_destination_rejects_current_environment_results_and_evidence_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="current Python environment",
    ):
        provisioning.validate_destination(Path(provisioning.sys.prefix))
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="frozen result namespace",
    ):
        provisioning.validate_destination(
            tmp_path
            / "hammer-symai-spacy-leanstral"
            / "results"
            / "runtime"
        )
    with pytest.raises(
        provisioning.SpacyProvisioningError,
        match="evidence or data",
    ):
        provisioning.validate_destination(
            provisioning.REPOSITORY_ROOT / "data/spacy-runtime"
        )
