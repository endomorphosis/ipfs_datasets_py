"""Focused tests for the exact-51 local production runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from ipfs_datasets_py.processors.legal_data import (
    state_laws_legacy_v2_adapter,
    state_laws_local_release,
    state_laws_production_orchestrator,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    DeviceFallbackPolicy,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    RUN_SEAL_SUFFIX,
    build_state_laws_run_seal,
    canonical_run_seal_bytes,
)

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "run_state_laws_production_release.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "run_state_laws_production_release_test_target", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cli
_SPEC.loader.exec_module(cli)

RELEASE_POINT = "state-laws-exact-51-2026-08-24"
SOURCE_REVISION = "4d62373051f2436296eb123d8c28819a91ea460a"


def _test_runner_source_software_version() -> str:
    return (
        "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
        + hashlib.sha256(b"runner-test-refresh-source").hexdigest()
    )


def _test_source_software_versions() -> dict[str, str]:
    return {
        code: (
            f"tests.state_scrapers.{code}@sha256:"
            f"{hashlib.sha256(f'{code}-current'.encode('ascii')).hexdigest()}"
        )
        for code in CANONICAL_JURISDICTION_ORDER
    }


def _source_receipt(
    code: str,
    *,
    artifact_sha256: str | None = None,
) -> SourceReceiptRecord:
    digest = artifact_sha256 or (
        code.lower().encode("ascii").hex() + "0" * 64
    )[:64]
    jurisdiction_release_point = hashlib.sha256(
        f"{code}-official-acquisition".encode("ascii")
    ).hexdigest()
    official_url = f"https://legislature.{code.lower()}.gov/code"
    return SourceReceiptRecord(
        receipt_id=f"source-{code.lower()}-sealed",
        jurisdiction=code,
        official_source_url=official_url,
        release_point=jurisdiction_release_point,
        observation_time="2026-08-24T00:00:00Z",
        source_authority_class=SourceAuthorityClass.OFFICIAL,
        source_checksum=digest,
        verification_result=VerificationResult.VERIFIED,
        discovered=1,
        fetched=1,
        excluded=0,
        quarantined=0,
        failed_final=0,
        frontier_closed=True,
        relative_path=f"receipts/scrape/{code.lower()}.json",
        source_software_version=_test_source_software_versions()[code],
        start_urls=(official_url,),
        content_hashes=(digest,),
        payload={
            "adapter_schema_version": (
                state_laws_legacy_v2_adapter.ADAPTER_SCHEMA_VERSION
            ),
            "adapter_input_sha256": digest,
            "adapter_input_row_count": 1,
            "admission_eligible": True,
            "qualification_reasons": [],
            "reported_canonical_row_count": 1,
            "requires_verified_transport_binding": False,
            "verified_transport_receipts": [],
            "verified_transport_receipts_trusted": False,
        },
    )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    states: dict[str, object] = {}
    for code in CANONICAL_JURISDICTION_ORDER:
        canonical = tmp_path / "canonical" / f"STATE-{code}.jsonld"
        receipt = tmp_path / "normalized" / f"{code}.normalized.json"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text("{}\n", encoding="utf-8")
        canonical_sha256 = hashlib.sha256(canonical.read_bytes()).hexdigest()
        source_receipt = _source_receipt(
            code,
            artifact_sha256=canonical_sha256,
        )
        receipt_bytes = json.dumps(
            source_receipt.to_dict(), sort_keys=True
        ).encode("utf-8")
        receipt.write_bytes(receipt_bytes)
        receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
        run_id = hashlib.sha256(f"runner-test-{code}".encode("ascii")).hexdigest()[:32]
        seal = build_state_laws_run_seal(
            run_id=run_id,
            created_at="2026-08-24T00:00:01Z",
            active_states=[code],
            start_identities={
                code: source_receipt.source_software_version,
            },
            end_identities={
                code: source_receipt.source_software_version,
            },
            runner_start_identity=_test_runner_source_software_version(),
            runner_end_identity=_test_runner_source_software_version(),
            worker_quiescence={
                code: {
                    "attested": True,
                    "quiescent": True,
                    "completion_mode": "test_worker_returned",
                }
            },
            states={
                code: {
                    "canonical_jsonld_sha256": canonical_sha256,
                    "normalized_source_receipt_sha256": receipt_sha256,
                    "source_software_version": (
                        source_receipt.source_software_version
                    ),
                }
            },
        )
        seal_path = receipt.parent / f"{run_id}{RUN_SEAL_SUFFIX}"
        seal_bytes = canonical_run_seal_bytes(seal)
        seal_path.write_bytes(seal_bytes)
        states[code] = {
            "canonical_jsonld_path": canonical.relative_to(tmp_path).as_posix(),
            "canonical_jsonld_sha256": canonical_sha256,
            "normalized_source_receipt_path": receipt.relative_to(tmp_path).as_posix(),
            "normalized_source_receipt_sha256": receipt_sha256,
            "run_seal_path": seal_path.relative_to(tmp_path).as_posix(),
            "run_seal_sha256": hashlib.sha256(seal_bytes).hexdigest(),
        }
    mapping: dict[str, object] = {
        "schema_version": cli.INPUT_MAP_SCHEMA_VERSION,
        "acquisition_evidence_roots": ["normalized"],
        "refresh_runner_source_software_version": (
            _test_runner_source_software_version()
        ),
        "states": states,
    }
    input_map = tmp_path / "input-map.json"
    input_map.write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")

    admitted_ids = [
        f"{code.lower()}-official-statutory-text"
        for code in CANONICAL_JURISDICTION_ORDER
    ]
    rights = {
        "admitted_record_ids": admitted_ids,
        "decisions": [
            {
                "admitted": True,
                "authorizing": True,
                "content_scope": "statutory_text",
                "record_id": record_id,
                "rights_disposition": "allowed",
            }
            for record_id in admitted_ids
        ],
        "catalog_digest_sha256": "b" * 64,
        "path": "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json",
        "prohibited_ids": [],
        "status": "passed",
        "unknown_ids": [],
    }
    rights["report_digest_sha256"] = hashlib.sha256(
        json.dumps(
            rights,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    rights_path = tmp_path / "rights.json"
    rights_path.write_text(json.dumps(rights, sort_keys=True), encoding="utf-8")
    return input_map, rights_path, mapping


class _FakeCheckpoint:
    def __init__(self, code: str) -> None:
        self.code = code
        self.next_source_index = 0

    def advance(self, event: object) -> _FakeCheckpoint:
        assert event == f"event-{self.code}"
        self.next_source_index += 1
        return self


class _FakeAdapter:
    created: ClassVar[list[str]] = []
    finalized: ClassVar[list[str]] = []
    ineligible_code: ClassVar[str | None] = None

    def __init__(
        self,
        *,
        input_path: Path,
        jurisdiction: str,
        release_point: str,
        source_receipt: SourceReceiptRecord,
    ) -> None:
        assert Path(input_path).name == f"STATE-{jurisdiction}.jsonld"
        assert isinstance(source_receipt, SourceReceiptRecord)
        assert source_receipt.jurisdiction == jurisdiction
        assert release_point == source_receipt.release_point
        assert release_point != RELEASE_POINT
        self.jurisdiction = jurisdiction
        self.source_receipt = SimpleNamespace(
            admission_eligible=jurisdiction != self.ineligible_code,
            expected_row_count=1,
            input_row_count=1,
            qualification_reasons=(
                ("fixture-ineligible",) if jurisdiction == self.ineligible_code else ()
            ),
            record=source_receipt,
        )
        self.created.append(jurisdiction)

    def new_checkpoint(self) -> _FakeCheckpoint:
        return _FakeCheckpoint(self.jurisdiction)

    def iter_events(self):
        yield f"event-{self.jurisdiction}"

    def finalize_checkpoint(self, checkpoint: _FakeCheckpoint) -> None:
        assert checkpoint.next_source_index == 1
        self.finalized.append(self.jurisdiction)


@pytest.fixture(autouse=True)
def _reset_fake_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAdapter.created = []
    _FakeAdapter.finalized = []
    _FakeAdapter.ineligible_code = None
    monkeypatch.setattr(
        cli,
        "registered_exact_51_source_software_versions",
        _test_source_software_versions,
    )
    monkeypatch.setattr(
        cli,
        "current_refresh_runner_source_software_version",
        lambda **_kwargs: _test_runner_source_software_version(),
    )
    def verifier(value):
        return dict(value)

    monkeypatch.setattr(cli, "require_live_source_rights_receipt", verifier)
    monkeypatch.setattr(
        state_laws_local_release,
        "require_live_source_rights_receipt",
        verifier,
    )


def test_runner_rejects_non_authoritative_rights_before_adapter_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_map, rights_path, _ = _write_inputs(tmp_path)

    def reject(_value):
        raise ValueError("stale policy_module_sha256")

    monkeypatch.setattr(cli, "require_live_source_rights_receipt", reject)
    monkeypatch.setattr(
        cli,
        "LegacyStateLawsV2Adapter",
        lambda **_kwargs: pytest.fail("rights must fail before adapter construction"),
    )
    with pytest.raises(
        cli.StateLawsProductionRunnerError,
        match="authoritative live verification.*policy_module",
    ):
        cli.prepare_exact_51_inputs(
            input_map_path=input_map,
            rights_receipt_path=rights_path,
        )
    assert _FakeAdapter.created == []


def test_runner_is_only_a_thin_adapter_orchestrator_composition() -> None:
    assert (
        cli.LegacyStateLawsV2Adapter
        is state_laws_legacy_v2_adapter.LegacyStateLawsV2Adapter
    )
    assert (
        cli.build_state_laws_production_release
        is state_laws_production_orchestrator.build_state_laws_production_release
    )
    assert cli.LOCAL_ONLY is True
    assert cli.AUTHORIZES_PUBLICATION is False
    assert cli.AUTHORIZES_HUB_UPLOAD is False
    assert cli.PERFORMS_NETWORK_IO is False


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_exact_51_inputs_flow_through_adapters_into_restartable_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    device: str,
) -> None:
    input_map, rights_path, _ = _write_inputs(tmp_path)
    output_root = tmp_path / "release"
    calls: list[dict[str, object]] = []

    def fake_build(events, **kwargs):
        calls.append({"events": list(events), **kwargs})
        return SimpleNamespace(
            authorizes_hub_upload=False,
            authorizes_publication=False,
            local_only=True,
            network_io_performed=False,
            output_root=str(output_root.resolve()),
            to_dict=lambda: {
                "authorizes_hub_upload": False,
                "authorizes_publication": False,
                "local_only": True,
                "network_io_performed": False,
            },
        )

    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    monkeypatch.setattr(cli, "device_is_available", lambda selected: selected == device)
    monkeypatch.setattr(cli, "build_state_laws_production_release", fake_build)

    result = cli.run_local_production_release(
        input_map_path=input_map,
        rights_receipt_path=rights_path,
        source_revision=SOURCE_REVISION,
        release_point=RELEASE_POINT,
        output_root=output_root,
        checkpoint_path="checkpoints/custom.json",
        embedding_device=device,
        embedding_batch_size=17,
        resume=True,
    )

    assert result["status"] == "complete"
    assert result["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert result["canonical_row_count"] == EXPECTED_JURISDICTION_COUNT
    assert result["aggregate_release_point"] == RELEASE_POINT
    assert result["source_revision"] == SOURCE_REVISION
    assert len(result["source_receipts_digest"]) == 64
    assert result["source_acquisition_release_points"] == {
        code: _source_receipt(code).release_point
        for code in CANONICAL_JURISDICTION_ORDER
    }
    assert result["local_only"] is True
    assert result["authorizes_publication"] is False
    assert result["authorizes_hub_upload"] is False
    assert result["network_io_performed"] is False
    assert len(calls) == 1
    call = calls[0]
    assert call["events"] == [f"event-{code}" for code in CANONICAL_JURISDICTION_ORDER]
    assert [item.jurisdiction for item in call["source_receipts"]] == list(
        CANONICAL_JURISDICTION_ORDER
    )
    config = call["embedding_config"]
    assert config.model_id == PINNED_MODEL_ID
    assert config.model_revision == PINNED_MODEL_REVISION
    assert config.dimension == PINNED_DIMENSION
    assert config.max_tokens == PINNED_MAX_TOKENS
    assert config.device == device
    assert config.device_fallback is DeviceFallbackPolicy.BLOCK
    assert config.batch_size == 17
    assert call["resume"] is True
    assert call["release_point"] == RELEASE_POINT
    assert call["source_revision"] == SOURCE_REVISION
    assert (
        call["checkpoint_path"]
        == (output_root / "checkpoints" / "custom.json").resolve()
    )
    assert _FakeAdapter.created == list(CANONICAL_JURISDICTION_ORDER)
    assert _FakeAdapter.finalized == list(CANONICAL_JURISDICTION_ORDER)


def test_preflight_only_validates_all_inputs_without_building_or_creating_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_map, rights_path, _ = _write_inputs(tmp_path)
    output_root = tmp_path / "must-not-exist"
    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    monkeypatch.setattr(cli, "device_is_available", lambda device: device == "cpu")
    monkeypatch.setattr(
        cli,
        "build_state_laws_production_release",
        lambda *args, **kwargs: pytest.fail(
            "preflight must not invoke the orchestrator"
        ),
    )

    result = cli.run_local_production_release(
        input_map_path=input_map,
        rights_receipt_path=rights_path,
        source_revision=SOURCE_REVISION,
        release_point=RELEASE_POINT,
        output_root=output_root,
        embedding_device="cpu",
        preflight_only=True,
    )

    assert result["status"] == "preflight_passed"
    assert result["source_receipt_count"] == EXPECTED_JURISDICTION_COUNT
    assert result["embedding"]["device"] == "cpu"
    assert result["source_provenance_verifier"] == (
        state_laws_local_release.state_laws_source_provenance_verifier_attestation()
    )
    provenance_path = Path(state_laws_local_release.__file__).with_name(
        "state_laws_source_provenance.py"
    )
    assert result["source_provenance_verifier"]["sha256"] == hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()
    assert not output_root.exists()
    assert _FakeAdapter.finalized == []


def test_current_source_software_gate_rejects_stale_release_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_map, rights_path, _ = _write_inputs(tmp_path)
    current_versions = _test_source_software_versions()
    stale_digest = hashlib.sha256(b"FL-new-current-source").hexdigest()
    current_versions["FL"] = f"tests.state_scrapers.FL@sha256:{stale_digest}"

    monkeypatch.setattr(
        cli,
        "registered_exact_51_source_software_versions",
        lambda: current_versions,
    )
    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    with pytest.raises(
        cli.StateLawsProductionRunnerError,
        match="FL=.*source_software_version mismatch",
    ):
        cli.run_local_production_release(
            input_map_path=input_map,
            rights_receipt_path=rights_path,
            source_revision=SOURCE_REVISION,
            release_point=RELEASE_POINT,
            output_root=tmp_path / "output",
            preflight_only=True,
        )
    assert not (tmp_path / "output").exists()


def test_missing_jurisdiction_fails_before_any_adapter_or_output_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_map, rights_path, mapping = _write_inputs(tmp_path)
    states = mapping["states"]
    assert isinstance(states, dict)
    states.pop("DC")
    input_map.write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")

    class AdapterMustNotRun:
        def __init__(self, **kwargs):
            pytest.fail("mapping cardinality must be checked before adapter work")

    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", AdapterMustNotRun)
    with pytest.raises(cli.StateLawsProductionRunnerError, match="exactly.*DC"):
        cli.run_local_production_release(
            input_map_path=input_map,
            rights_receipt_path=rights_path,
            source_revision=SOURCE_REVISION,
            release_point=RELEASE_POINT,
            output_root=tmp_path / "output",
            preflight_only=True,
        )
    assert not (tmp_path / "output").exists()


def test_duplicate_receipt_path_is_rejected_as_a_non_bijective_mapping(
    tmp_path: Path,
) -> None:
    input_map, _, mapping = _write_inputs(tmp_path)
    states = mapping["states"]
    assert isinstance(states, dict)
    al = states["AL"]
    ak = states["AK"]
    assert isinstance(al, dict) and isinstance(ak, dict)
    ak["normalized_source_receipt_path"] = al["normalized_source_receipt_path"]
    input_map.write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")

    with pytest.raises(
        cli.StateLawsProductionRunnerError, match="mapped more than once"
    ):
        cli.load_exact_51_input_bindings(input_map)


def test_legacy_handwritten_input_map_without_seal_bindings_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_map, rights_path, mapping = _write_inputs(tmp_path)
    states = mapping["states"]
    assert isinstance(states, dict)
    legacy_states = {
        code: {
            "canonical_jsonld_path": value["canonical_jsonld_path"],
            "normalized_source_receipt_path": value[
                "normalized_source_receipt_path"
            ],
        }
        for code, value in states.items()
    }
    input_map.write_text(
        json.dumps(
            {
                "schema_version": "state-laws-production-input-map/v1",
                "states": legacy_states,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "LegacyStateLawsV2Adapter",
        lambda **_kwargs: pytest.fail("legacy maps must fail before adapter work"),
    )

    with pytest.raises(
        cli.StateLawsProductionRunnerError,
        match="top-level fields|schema_version",
    ):
        cli.run_local_production_release(
            input_map_path=input_map,
            rights_receipt_path=rights_path,
            source_revision=SOURCE_REVISION,
            release_point=RELEASE_POINT,
            output_root=tmp_path / "legacy-output",
        )
    assert not (tmp_path / "legacy-output").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "input_map",
        "artifact",
        "receipt",
        "seal",
        "poison",
        "in_progress",
        "pending_receipt",
        "runner",
    ],
)
def test_preoutput_recheck_rejects_all_sealed_input_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    input_map, rights_path, mapping = _write_inputs(tmp_path)
    output = tmp_path / f"must-not-create-{mutation}"
    original_pinned = cli.pinned_embedding_config

    def mutate_after_prepare(**kwargs):
        config = original_pinned(**kwargs)
        states = mapping["states"]
        assert isinstance(states, dict)
        al = states["AL"]
        assert isinstance(al, dict)
        if mutation == "input_map":
            input_map.write_bytes(input_map.read_bytes() + b" ")
        elif mutation == "artifact":
            path = tmp_path / str(al["canonical_jsonld_path"])
            path.write_bytes(path.read_bytes() + b"\n")
        elif mutation == "receipt":
            path = tmp_path / str(al["normalized_source_receipt_path"])
            path.write_bytes(path.read_bytes() + b" ")
        elif mutation == "seal":
            path = tmp_path / str(al["run_seal_path"])
            path.write_bytes(path.read_bytes() + b" ")
        elif mutation == "poison":
            (tmp_path / "normalized" / cli.NONQUIESCENT_EVIDENCE_MARKER).write_text(
                "{}", encoding="utf-8"
            )
        elif mutation == "in_progress":
            (tmp_path / "normalized" / cli.IN_PROGRESS_EVIDENCE_MARKER).write_text(
                "{}", encoding="utf-8"
            )
        elif mutation == "pending_receipt":
            (tmp_path / "normalized" / "late.pending-normalized.json").write_text(
                "{}", encoding="utf-8"
            )
        else:
            stale_runner = (
                "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
                + hashlib.sha256(b"runner-drift-after-preflight").hexdigest()
            )
            monkeypatch.setattr(
                cli,
                "current_refresh_runner_source_software_version",
                lambda **_kwargs: stale_runner,
            )
        return config

    monkeypatch.setattr(cli, "pinned_embedding_config", mutate_after_prepare)
    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    monkeypatch.setattr(cli, "device_is_available", lambda device: device == "cpu")
    monkeypatch.setattr(
        cli,
        "build_state_laws_production_release",
        lambda *_args, **_kwargs: pytest.fail(
            "drift must fail before the output-capable orchestrator"
        ),
    )

    with pytest.raises(cli.StateLawsProductionRunnerError):
        cli.run_local_production_release(
            input_map_path=input_map,
            rights_receipt_path=rights_path,
            source_revision=SOURCE_REVISION,
            release_point=RELEASE_POINT,
            output_root=output,
        )
    assert not output.exists()


def test_ineligible_normalized_receipt_blocks_orchestration_after_full_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_map, rights_path, _ = _write_inputs(tmp_path)
    _FakeAdapter.ineligible_code = "GA"
    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    monkeypatch.setattr(
        cli,
        "build_state_laws_production_release",
        lambda *args, **kwargs: pytest.fail("ineligible receipts must block the build"),
    )

    with pytest.raises(
        cli.StateLawsProductionRunnerError, match="GA=.*not admission eligible"
    ):
        cli.run_local_production_release(
            input_map_path=input_map,
            rights_receipt_path=rights_path,
            source_revision=SOURCE_REVISION,
            release_point=RELEASE_POINT,
            output_root=tmp_path / "output",
            preflight_only=False,
        )
    assert _FakeAdapter.created == list(CANONICAL_JURISDICTION_ORDER)
    assert not (tmp_path / "output").exists()


def test_cuda_request_blocks_instead_of_silently_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "device_is_available", lambda device: False)
    with pytest.raises(cli.StateLawsProductionRunnerError, match="cuda.*unavailable"):
        cli.pinned_embedding_config(device="cuda")


def test_runner_refuses_if_orchestrator_safety_contract_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "ORCHESTRATOR_AUTHORIZES_PUBLICATION", True)
    with pytest.raises(cli.StateLawsProductionRunnerError, match="local-only"):
        cli.assert_local_only_contract()
