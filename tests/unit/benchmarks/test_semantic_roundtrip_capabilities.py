"""Contract tests for the semantic round-trip capability receipt."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks import semantic_roundtrip_capabilities as capabilities


def _available(
    capability_id: str,
    *,
    effective: dict[str, Any] | None = None,
) -> capabilities.CapabilityRecord:
    identity = effective or {"implementation": capability_id, "version": "1"}
    return capabilities.CapabilityRecord.available(
        capability_id,
        {"requested": capability_id},
        identity,
        {"probe_completed": True},
    )


def _direct() -> capabilities.CapabilityRecord:
    return _available(
        "leanstral_direct",
        effective={
            "route": "direct_openai_compatible_http",
            "provider": capabilities.LEANSTRAL_PROVIDER,
            "endpoint": capabilities.LEANSTRAL_ENDPOINT,
            "model": capabilities.LEANSTRAL_MODEL,
            "backend": capabilities.LEANSTRAL_BACKEND,
        },
    )


def _symai() -> capabilities.CapabilityRecord:
    return _available(
        "symai_leanstral_route",
        effective={
            "route": "symai_router",
            "provider": capabilities.SYMAI_PROVIDER,
            "model_alias": capabilities.SYMAI_MODEL_ALIAS,
            "resolved_provider": capabilities.LEANSTRAL_PROVIDER,
            "resolved_endpoint": capabilities.LEANSTRAL_ENDPOINT,
            "resolved_model": capabilities.LEANSTRAL_MODEL,
            "resolved_backend": capabilities.LEANSTRAL_BACKEND,
        },
    )


def _injected_inventory(
    overrides: dict[str, capabilities.CapabilityRecord] | None = None,
) -> capabilities.CapabilityInventory:
    records = {
        item: _available(item)
        for item in capabilities.CAPABILITY_IDS
    }
    records["leanstral_direct"] = _direct()
    records["symai_leanstral_route"] = _symai()
    records.update(overrides or {})
    return capabilities.capture_capability_inventory(
        run_id="unit-capabilities",
        captured_at_utc="2026-07-26T00:00:00Z",
        probes={
            item: (lambda record=record: record)
            for item, record in records.items()
        },
    )


def test_frozen_requested_identities_cover_every_required_runtime() -> None:
    assert capabilities.SCHEMA_VERSION.endswith(
        "semantic-roundtrip-capability-inventory.v1"
    )
    assert capabilities.INTERFACE_VERSION == (
        "SemanticRoundTripCapabilityInventory@1"
    )
    assert capabilities.CAPABILITY_IDS == (
        "python",
        "multiformats",
        "spacy_pipeline",
        "autoencoder_state",
        "leanstral_direct",
        "symai_leanstral_route",
        "hammer_cvc5",
        "lean",
    )
    assert capabilities.SPACY_PIPELINE == (
        "tok2vec",
        "tagger",
        "parser",
        "attribute_ruler",
        "lemmatizer",
        "ner",
    )
    assert capabilities.LEANSTRAL_CAPACITY == 1
    assert capabilities.LEANSTRAL_ENDPOINT.endswith("/v1")
    assert "Leanstral-1.5-119B" in capabilities.LEANSTRAL_MODEL
    assert capabilities.AUTOENCODER_STATE_CID.startswith("bafkrei")


def test_unavailable_capability_requires_reason_and_forbids_substitute() -> None:
    with pytest.raises(capabilities.CapabilityProbeError, match="reason"):
        capabilities.CapabilityRecord(
            id="lean",
            status="unavailable",
            requested_identity={"toolchain": "Lean 4"},
            effective_identity=None,
            checks={},
        )
    with pytest.raises(capabilities.CapabilityProbeError, match="substitute"):
        capabilities.CapabilityRecord(
            id="spacy_pipeline",
            status="unavailable",
            requested_identity={"model": capabilities.SPACY_MODEL},
            effective_identity={"model": "blank:en"},
            checks={},
            reason="full pipeline absent",
            substitute_used=True,
            substitute_identity={"model": "blank:en"},
        )


def test_probe_exception_is_explicit_and_inventory_remains_complete() -> None:
    def explode() -> capabilities.CapabilityRecord:
        raise RuntimeError("secret token must not be serialized")

    inventory = _injected_inventory(
        {
            "hammer_cvc5": capabilities.CapabilityRecord.unavailable(
                "hammer_cvc5",
                {"solver": "cvc5"},
                reason="bounded smoke unavailable",
            )
        }
    )
    probes = {
        item: (lambda record=inventory.by_id[item]: record)
        for item in capabilities.CAPABILITY_IDS
    }
    probes["hammer_cvc5"] = explode
    captured = capabilities.capture_capability_inventory(
        run_id="probe-failure",
        captured_at_utc="2026-07-26T00:00:00Z",
        probes=probes,
    )

    assert tuple(record.id for record in captured.capabilities) == (
        capabilities.CAPABILITY_IDS
    )
    failed = captured.by_id["hammer_cvc5"]
    assert failed.status == "unavailable"
    assert failed.reason == "capability probe raised RuntimeError"
    assert "secret token" not in capabilities.canonical_inventory_json(captured)
    assert failed.substitute_used is False


class _FakeDoc:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()

    def has_annotation(self, name: str) -> bool:
        return name not in self.missing


class _FakeNlp:
    def __init__(
        self,
        pipeline: tuple[str, ...],
        *,
        missing: set[str] | None = None,
    ) -> None:
        self.pipe_names = pipeline
        self.lang = "en"
        self.missing = missing

    def __call__(self, text: str) -> _FakeDoc:
        assert text == capabilities.SPACY_SMOKE_TEXT
        return _FakeDoc(self.missing)


def _spacy_versions(name: str) -> str | None:
    return {
        "spacy": capabilities.SPACY_VERSION,
        capabilities.SPACY_MODEL_DISTRIBUTION: (
            capabilities.SPACY_MODEL_VERSION
        ),
    }.get(name)


def test_spacy_probe_loads_only_the_exact_full_pipeline() -> None:
    loaded: list[str] = []

    def load(name: str) -> _FakeNlp:
        loaded.append(name)
        return _FakeNlp(capabilities.SPACY_PIPELINE)

    record = capabilities.probe_spacy(
        version_getter=_spacy_versions,
        importer=lambda name: SimpleNamespace(load=load),
    )

    assert record.status == "available"
    assert loaded == [capabilities.SPACY_MODEL]
    assert record.requested_identity["fallback_allowed"] is False
    assert record.effective_identity
    assert record.effective_identity["pipeline"] == capabilities.SPACY_PIPELINE
    assert record.checks["fallback_used"] is False


def test_spacy_probe_reports_partial_pipeline_without_blank_fallback() -> None:
    partial = tuple(
        item for item in capabilities.SPACY_PIPELINE if item != "parser"
    )
    record = capabilities.probe_spacy(
        version_getter=_spacy_versions,
        importer=lambda name: SimpleNamespace(
            load=lambda model: _FakeNlp(partial, missing={"DEP"})
        ),
    )

    assert record.status == "unavailable"
    assert record.reason
    assert record.effective_identity
    assert record.effective_identity["model"] == capabilities.SPACY_MODEL
    assert record.checks["fallback_used"] is False
    assert record.substitute_identity is None


def _leanstral_get(url: str, timeout: float, max_bytes: int) -> Any:
    assert timeout > 0
    assert max_bytes > 0
    if url.endswith("/health"):
        return {"status": "ok"}
    if url.endswith("/v1/models"):
        return {
            "data": [
                {
                    "id": capabilities.LEANSTRAL_MODEL,
                    "owned_by": capabilities.LEANSTRAL_BACKEND_OWNER,
                    "meta": {"ftype": "NVFP4", "n_params": 118_972_826_624},
                }
            ]
        }
    if url.endswith("/props"):
        return {
            "build_info": "b1-test",
            "model_alias": capabilities.LEANSTRAL_MODEL,
            "model_path": "/models/leanstral.gguf",
            "model_ftype": "NVFP4",
            "total_slots": 1,
            "default_generation_settings": {"n_ctx": 8192},
        }
    raise AssertionError(url)


def test_direct_and_symai_routes_bind_one_exact_shared_model(tmp_path: Path) -> None:
    config = capabilities.ProbeConfig(repository_root=tmp_path)
    direct = capabilities.probe_leanstral_direct(
        config,
        http_getter=_leanstral_get,
    )
    assert direct.status == "available"
    assert direct.effective_identity
    assert direct.effective_identity["capacity"]["parallel_slots"] == 1
    assert direct.checks["model_inference_performed"] is False

    source = tmp_path / "router.py"
    source.write_text("# frozen route\n", encoding="utf-8")
    spec = SimpleNamespace(origin=str(source))
    symai = capabilities.probe_symai_leanstral_route(
        direct,
        version_getter=lambda name: capabilities.SYMAI_VERSION,
        module_finder=lambda name: spec,
    )
    assert symai.status == "available"
    assert symai.effective_identity
    assert symai.effective_identity["route"] == "symai_router"
    assert symai.effective_identity["resolved_model"] == (
        direct.effective_identity["model"]
    )
    assert symai.effective_identity["independent_model"] is False

    inventory = _injected_inventory(
        {
            "leanstral_direct": direct,
            "symai_leanstral_route": symai,
        }
    )
    assert inventory.bindings["same_effective_model"] is True
    assert inventory.bindings["same_effective_service"] is True
    assert inventory.bindings["shared_model_capacity"] == 1
    assert inventory.bindings["direct_leanstral"]["route"] == (
        "direct_openai_compatible_http"
    )
    assert inventory.bindings["symai_leanstral"]["route"] == "symai_router"


def test_leanstral_capacity_drift_is_unavailable() -> None:
    def two_slots(url: str, timeout: float, max_bytes: int) -> Any:
        value = _leanstral_get(url, timeout, max_bytes)
        if url.endswith("/props"):
            value["total_slots"] = 2
        return value

    record = capabilities.probe_leanstral_direct(
        capabilities.ProbeConfig(),
        http_getter=two_slots,
    )

    assert record.status == "unavailable"
    assert record.checks["one_slot_capacity"] is False
    assert record.substitute_used is False


def test_frozen_autoencoder_state_is_loaded_read_only() -> None:
    state_path = (
        capabilities.REPO_ROOT
        / capabilities.AUTOENCODER_STATE_RELATIVE_PATH
    )
    before = state_path.stat()
    seen: list[dict[str, Any]] = []

    def load(value: Any) -> Any:
        seen.append(dict(value))
        return SimpleNamespace(
            architecture_version=(
                capabilities.AUTOENCODER_EFFECTIVE_ARCHITECTURE
            )
        )

    record = capabilities.probe_autoencoder_state(
        capabilities.ProbeConfig(),
        state_loader=load,
    )
    after = state_path.stat()

    assert record.status == "available"
    assert len(seen) == 1
    assert record.effective_identity
    assert record.effective_identity["sha256"] == (
        capabilities.AUTOENCODER_STATE_SHA256
    )
    assert record.effective_identity["cid"] == (
        capabilities.AUTOENCODER_STATE_CID
    )
    assert record.checks["opened_read_only"] is True
    assert record.checks["write_attempted"] is False
    assert record.checks["state_unchanged_after_load"] is True
    assert (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def test_bounded_cvc5_smoke_is_exercised(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "cvc5"
    executable.write_bytes(b"test executable")
    calls: list[tuple[tuple[str, ...], bytes | None, float, int]] = []

    def run(
        arguments: Any,
        input_bytes: bytes | None,
        timeout: float,
        max_output: int,
    ) -> capabilities.CommandResult:
        calls.append((tuple(arguments), input_bytes, timeout, max_output))
        output = (
            b"This is cvc5 version 1.3.3"
            if "--version" in arguments
            else b"sat\n"
        )
        return capabilities.CommandResult(
            tuple(arguments), 0, output, False, False
        )

    monkeypatch.setattr(
        capabilities.shutil,
        "which",
        lambda command: str(executable) if command == "cvc5" else None,
    )
    record = capabilities.probe_hammer_cvc5(
        capabilities.ProbeConfig(),
        version_getter=lambda name: "0.2.0",
        module_finder=lambda name: SimpleNamespace(origin=__file__),
        command_runner=run,
    )

    assert record.status == "available"
    assert len(calls) == 2
    assert calls[1][1]
    assert b"(check-sat)" in calls[1][1]
    assert "--tlimit=1000" in calls[1][0]
    assert record.checks["bounded_smoke_passed"] is True


def test_bounded_lean_kernel_smoke_is_exercised(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "lean"
    executable.write_bytes(b"test executable")
    calls: list[tuple[str, ...]] = []

    def run(
        arguments: Any,
        input_bytes: bytes | None,
        timeout: float,
        max_output: int,
    ) -> capabilities.CommandResult:
        del input_bytes, timeout, max_output
        calls.append(tuple(arguments))
        output = (
            b"Lean (version 4.32.1, test)"
            if "--version" in arguments
            else b""
        )
        return capabilities.CommandResult(
            tuple(arguments), 0, output, False, False
        )

    monkeypatch.setattr(
        capabilities.shutil,
        "which",
        lambda command: str(executable) if command == "lean" else None,
    )
    record = capabilities.probe_lean(
        capabilities.ProbeConfig(),
        command_runner=run,
    )

    assert record.status == "available"
    assert len(calls) == 2
    assert calls[1][1].endswith("Smoke.lean")
    assert record.checks["bounded_smoke_passed"] is True


def test_inventory_round_trip_is_strict_and_deeply_immutable() -> None:
    inventory = _injected_inventory()
    restored = capabilities.CapabilityInventory.from_dict(
        json.loads(capabilities.canonical_inventory_json(inventory))
    )

    assert restored == inventory
    with pytest.raises(FrozenInstanceError):
        restored.run_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        restored.bindings["shared_model_capacity"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        restored.capabilities[0].requested_identity["version"] = "2"  # type: ignore[index]

    unknown = restored.to_dict()
    unknown["fallback"] = {"model": "blank:en"}
    with pytest.raises(capabilities.CapabilityProbeError, match="unknown"):
        capabilities.CapabilityInventory.from_dict(unknown)


def test_require_available_fails_closed_without_selecting_substitute() -> None:
    unavailable = capabilities.CapabilityRecord.unavailable(
        "spacy_pipeline",
        {"model": capabilities.SPACY_MODEL},
        reason="full pipeline missing",
    )
    inventory = _injected_inventory({"spacy_pipeline": unavailable})

    with pytest.raises(
        capabilities.CapabilityProbeError,
        match="no substitutes permitted",
    ):
        capabilities.require_available(inventory, ["spacy_pipeline"])


def test_captured_workspace_receipt_is_schema_valid_and_truthful() -> None:
    inventory = capabilities.load_inventory(capabilities.DEFAULT_OUTPUT)
    payload = inventory.to_dict()

    assert inventory.run_id == capabilities.DEFAULT_RUN_ID
    assert payload["probe_policy"]["allows_substitutes"] is False
    assert payload["probe_policy"]["full_spacy_pipeline_required"] is True
    assert payload["probe_policy"]["autoencoder_access"] == "read_only"
    assert inventory.bindings["shared_model_capacity"] == 1
    assert inventory.by_id["autoencoder_state"].requested_identity["cid"] == (
        capabilities.AUTOENCODER_STATE_CID
    )
    assert inventory.by_id["leanstral_direct"].requested_identity[
        "endpoint"
    ] == capabilities.LEANSTRAL_ENDPOINT
    assert inventory.by_id["symai_leanstral_route"].requested_identity[
        "resolved_model"
    ] == capabilities.LEANSTRAL_MODEL
    assert all(
        record.substitute_used is False
        and record.substitute_identity is None
        and (record.status == "available" or record.reason)
        for record in inventory.capabilities
    )
