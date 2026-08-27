"""Focused tests for deterministic state-law production input-map assembly."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import pytest

from ipfs_datasets_py.processors.legal_data import (
    state_laws_legacy_v2_adapter,
    state_laws_local_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    ADAPTER_SCHEMA_VERSION,
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
    / "assemble_state_laws_production_input_map.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "assemble_state_laws_production_input_map_test_target", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cli
_SPEC.loader.exec_module(cli)
runner = cli._LOCAL_PRODUCTION_RUNNER_MODULE

_EXACT_51_SELECTION_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "state_laws_exact51_candidate_selection_v1.json"
)
_EXACT_51_CURATED_SELECTIONS = {
    "CT": {
        "canonical_jsonld_sha256": (
            "6293dcfc4284b91899dca0bc3a8cf1a10f7423617bed85d3a3b3d79ca85628eb"
        ),
        "normalized_source_receipt_sha256": (
            "0eee8649893dda8e8871564fb08fd5057713957a98e678731013f431b6c88a43"
        ),
    },
    "ND": {
        "canonical_jsonld_sha256": (
            "ce227e4f8b1c19413e4904f0d2ba03063f5b4663c25e9c4d4ee5ba275791d0d5"
        ),
        "normalized_source_receipt_sha256": (
            "40f6342e7b1e6d460607bea388b71f45d3e59121d562aa0a358d86d2d516c219"
        ),
    },
    "OR": {
        "canonical_jsonld_sha256": (
            "25efec0acb64b2adbcda5448dd84b57823e9575f371587017a8a2dd403dea3e6"
        ),
        "normalized_source_receipt_sha256": (
            "ab8a213f0798a2865088170c003beb0532a66ea945000eec8393cd1d30b3f911"
        ),
    },
    "SC": {
        "canonical_jsonld_sha256": (
            "55946b062e92e5ccf85dcff01d0cc54feedba2e7abb0170ca00cec97b75519b1"
        ),
        "normalized_source_receipt_sha256": (
            "8fe8a4b22d465f1e01269c821888e88ca8aab2b37148c9fbe275a5a0633420a3"
        ),
    },
    "SD": {
        "canonical_jsonld_sha256": (
            "da4317a0d7aae80f5b025c2b661dc54ffc923b2eacdea9bd0585204350d4f53d"
        ),
        "normalized_source_receipt_sha256": (
            "8ff9086ab514282afcb7e4f8c4d05122429da0b603cca2b5e184e0f73f03baab"
        ),
    },
    "VA": {
        "canonical_jsonld_sha256": (
            "472a9e7f7268bb45fdb0f7bfc0454f01558d6ce571df22655727341b4a6e2f04"
        ),
        "normalized_source_receipt_sha256": (
            "2c83d28a3c483f9cf729331ab49fa6f6f0851263180d81893c3d73026dfef358"
        ),
    },
}


def _test_source_software_versions() -> dict[str, str]:
    return {
        code: (
            f"tests.state_scrapers.{code}@sha256:"
            f"{hashlib.sha256(f'{code}-current'.encode('ascii')).hexdigest()}"
        )
        for code in CANONICAL_JURISDICTION_ORDER
    }


def _test_runner_source_software_version() -> str:
    return (
        "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
        + hashlib.sha256(b"current-test-refresh-runner").hexdigest()
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_row(code: str, *, variant: str = "primary") -> dict[str, str]:
    return {
        "@id": f"urn:state:{code.lower()}:statute:1-{variant}",
        "@type": "Legislation",
        "sectionNumber": f"1-{variant}",
        "sourceUrl": f"https://legislature.{code.lower()}.gov/code/{variant}",
        "stateCode": code,
        "text": f"{code} public law {variant}. The agency shall preserve records.",
    }


def _write_canonical(path: Path, code: str, *, variant: str = "primary") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_canonical_row(code, variant=variant), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _receipt_for_artifact(
    code: str,
    artifact: Path,
    *,
    variant: str = "primary",
    source_software_version: str | None = None,
) -> SourceReceiptRecord:
    digest = _sha256_file(artifact)
    release_point = hashlib.sha256(
        f"{code}-{variant}-official-acquisition".encode("ascii")
    ).hexdigest()
    official_url = f"https://legislature.{code.lower()}.gov/code/{variant}"
    return SourceReceiptRecord(
        receipt_id=f"source-{code.lower()}-{variant}-sealed",
        jurisdiction=code,
        official_source_url=official_url,
        release_point=release_point,
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
        relative_path=f"receipts/scrape/{code.lower()}-{variant}.json",
        source_software_version=(
            source_software_version or _test_source_software_versions()[code]
        ),
        start_urls=(official_url,),
        content_hashes=(digest,),
        payload={
            "adapter_input_row_count": 1,
            "adapter_input_sha256": digest,
            "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
            "admission_eligible": True,
            "qualification_reasons": [],
            "reported_canonical_row_count": 1,
            "reported_input_sha256": digest,
            "reported_source_authority_class": "official",
            "reported_verification_result": "verified",
            "requires_verified_transport_binding": False,
            "verified_transport_receipts": [],
            "verified_transport_receipts_trusted": False,
        },
    )


def _write_receipt(
    evidence_root: Path,
    code: str,
    artifact: Path,
    *,
    variant: str = "primary",
    filename: str | None = None,
    source_software_version: str | None = None,
) -> Path:
    receipt = _receipt_for_artifact(
        code,
        artifact,
        variant=variant,
        source_software_version=source_software_version,
    )
    path = (
        evidence_root / code / (filename or f"{code.lower()}-{variant}.normalized.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(receipt.to_dict(), sort_keys=True).encode("utf-8")
    path.write_bytes(serialized)
    receipt_sha256 = hashlib.sha256(serialized).hexdigest()
    artifact_sha256 = _sha256_file(artifact)
    source_identity = str(receipt.source_software_version)
    run_id = hashlib.sha256(
        f"{code}:{variant}:{receipt_sha256}".encode("ascii")
    ).hexdigest()[:32]
    seal = build_state_laws_run_seal(
        run_id=run_id,
        created_at="2026-08-24T00:00:01Z",
        active_states=[code],
        start_identities={code: source_identity},
        end_identities={code: source_identity},
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
                "canonical_jsonld_sha256": artifact_sha256,
                "normalized_source_receipt_sha256": receipt_sha256,
                "source_software_version": source_identity,
            }
        },
    )
    seal_path = path.parent / f"{run_id}{RUN_SEAL_SUFFIX}"
    seal_path.write_bytes(canonical_run_seal_bytes(seal))
    return path


def _write_exact_51(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    evidence_root = tmp_path / "evidence"
    canonical_root = tmp_path / "canonical-a"
    artifacts: dict[str, Path] = {}
    for code in CANONICAL_JURISDICTION_ORDER:
        artifact = canonical_root / f"STATE-{code}.jsonld"
        _write_canonical(artifact, code)
        _write_receipt(evidence_root, code, artifact)
        artifacts[code] = artifact
    return evidence_root, canonical_root, artifacts


def _write_selection_manifest(
    path: Path,
    selections: dict[str, tuple[str, str]],
) -> Path:
    payload = {
        "schema_version": cli.SELECTION_MANIFEST_SCHEMA_VERSION,
        "states": {
            code: {
                "canonical_jsonld_sha256": artifact_sha256,
                "normalized_source_receipt_sha256": receipt_sha256,
            }
            for code, (artifact_sha256, receipt_sha256) in selections.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


class _FakeAdapter:
    calls: ClassVar[list[tuple[str, Path, str]]] = []

    def __init__(
        self,
        *,
        input_path: Path,
        jurisdiction: str,
        release_point: str,
        source_receipt: SourceReceiptRecord,
    ) -> None:
        target = Path(input_path)
        assert target.name == f"STATE-{jurisdiction}.jsonld"
        assert source_receipt.jurisdiction == jurisdiction
        assert release_point == source_receipt.release_point
        digest = _sha256_file(target)
        assert source_receipt.payload["adapter_input_sha256"] == digest
        self.source_receipt = SimpleNamespace(
            admission_eligible=True,
            expected_row_count=1,
            input_row_count=1,
            input_sha256=digest,
            qualification_reasons=(),
        )
        self.calls.append((jurisdiction, target.resolve(), release_point))


@pytest.fixture(autouse=True)
def _fake_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAdapter.calls = []
    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    monkeypatch.setattr(
        cli,
        "registered_exact_51_source_software_versions",
        _test_source_software_versions,
    )
    monkeypatch.setattr(
        cli,
        "current_refresh_runner_source_software_version",
        lambda **kwargs: _test_runner_source_software_version(),
    )
    monkeypatch.setattr(
        runner,
        "current_refresh_runner_source_software_version",
        lambda **kwargs: _test_runner_source_software_version(),
    )


def test_assembler_reuses_shared_adapter_and_runner_map_contract() -> None:
    assert state_laws_legacy_v2_adapter.LegacyStateLawsV2Adapter is not _FakeAdapter
    assert Path(runner.__file__).resolve() == (
        _SCRIPT_PATH.parent / "run_state_laws_production_release.py"
    ).resolve()
    assert Path(cli._LOCAL_REFRESH_RUNNER_MODULE.__file__).resolve() == (
        _SCRIPT_PATH.parent / "refresh_state_laws_corpus.py"
    ).resolve()
    assert cli.INPUT_MAP_SCHEMA_VERSION == runner.INPUT_MAP_SCHEMA_VERSION
    assert cli.validate_exact_51_input_mapping is runner.validate_exact_51_input_mapping
    assert cli.load_exact_51_input_bindings is runner.load_exact_51_input_bindings
    assert cli.LOCAL_ONLY is True
    assert cli.AUTHORIZES_PUBLICATION is False
    assert cli.AUTHORIZES_HUB_UPLOAD is False
    assert cli.PERFORMS_NETWORK_IO is False


def test_exact_local_runner_load_ignores_ambiguous_scripts_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poison_package = ModuleType("scripts.ops.legal_data")
    poison_runner = ModuleType(
        "scripts.ops.legal_data.run_state_laws_production_release"
    )
    local_module_name = "_state_laws_test_exact_local_production_runner"
    monkeypatch.setitem(sys.modules, "scripts.ops.legal_data", poison_package)
    monkeypatch.setitem(
        sys.modules,
        "scripts.ops.legal_data.run_state_laws_production_release",
        poison_runner,
    )
    monkeypatch.setitem(sys.modules, local_module_name, ModuleType(local_module_name))

    loaded = cli._load_exact_local_script_module(
        filename="run_state_laws_production_release.py",
        module_name=local_module_name,
    )

    assert loaded is not poison_runner
    assert Path(loaded.__file__).resolve() == (
        _SCRIPT_PATH.parent / "run_state_laws_production_release.py"
    ).resolve()
    assert loaded.INPUT_MAP_SCHEMA_VERSION == cli.INPUT_MAP_SCHEMA_VERSION


def test_exact_local_refresh_runner_proves_loaded_source_correspondence() -> None:
    identity = cli._LOCAL_REFRESH_RUNNER_MODULE.runner_source_software_version(
        require_loaded_source_correspondence=True,
    )

    assert identity.startswith(
        "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
    )
    assert len(identity.rpartition("@sha256:")[-1]) == 64


def test_writes_deterministic_map_and_collapses_byte_identical_candidates(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_a, artifacts = _write_exact_51(tmp_path)
    evidence_generation_b = tmp_path / "evidence-generation-b"
    canonical_b = tmp_path / "canonical-b"
    canonical_b.mkdir()
    duplicate_artifact = canonical_b / "STATE-AL.jsonld"
    shutil.copyfile(artifacts["AL"], duplicate_artifact)
    original_receipt = evidence_root / "AL" / "al-primary.normalized.json"
    duplicate_receipt = evidence_generation_b / "duplicates" / "al-copy.normalized.json"
    duplicate_receipt.parent.mkdir(parents=True)
    shutil.copyfile(original_receipt, duplicate_receipt)
    output = tmp_path / "maps" / "exact-51-input-map.json"

    first = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_roots=[evidence_generation_b, evidence_root],
        canonical_output_roots=[canonical_b, canonical_a],
        output_path=output,
    )
    first_bytes = output.read_bytes()
    second = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_roots=[evidence_root, evidence_generation_b],
        canonical_output_roots=[canonical_a, canonical_b],
        output_path=output,
    )

    assert first["status"] == "written"
    assert first["exact_51_ready"] is True
    assert first["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert first["input_map_digest"] == second["input_map_digest"]
    assert first["acquisition_evidence_roots"] == sorted(
        [str(evidence_root.resolve()), str(evidence_generation_b.resolve())]
    )
    assert first["evidence_root"] is None
    assert first_bytes == output.read_bytes()
    assert first["jurisdictions"]["AL"]["artifact_candidate_count"] == 1
    assert (
        first["jurisdictions"]["AL"]["artifact_candidates"][0]["duplicate_path_count"]
        == 1
    )
    assert first["jurisdictions"]["AL"]["receipt_candidate_count"] == 1
    assert (
        first["jurisdictions"]["AL"]["receipt_candidates"][0]["duplicate_path_count"]
        == 1
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == runner.INPUT_MAP_SCHEMA_VERSION
    assert payload["acquisition_evidence_roots"] == sorted(
        [str(evidence_root.resolve()), str(evidence_generation_b.resolve())]
    )
    assert payload["refresh_runner_source_software_version"] == (
        _test_runner_source_software_version()
    )
    assert payload["states"]["AL"]["canonical_jsonld_path"] == str(
        artifacts["AL"].resolve()
    )
    al_receipt = duplicate_receipt
    al_seal = next((evidence_root / "AL").glob(f"*{RUN_SEAL_SUFFIX}"))
    assert payload["states"]["AL"] == {
        "canonical_jsonld_path": str(artifacts["AL"].resolve()),
        "canonical_jsonld_sha256": _sha256_file(artifacts["AL"]),
        "normalized_source_receipt_path": str(al_receipt.resolve()),
        "normalized_source_receipt_sha256": _sha256_file(al_receipt),
        "run_seal_path": str(al_seal.resolve()),
        "run_seal_sha256": _sha256_file(al_seal),
    }
    _, bindings = runner.load_exact_51_input_bindings(output)
    assert len(bindings) == EXPECTED_JURISDICTION_COUNT
    assert len(_FakeAdapter.calls) == EXPECTED_JURISDICTION_COUNT * 2


def test_complete_preflight_is_read_only(tmp_path: Path) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    output = tmp_path / "maps" / "must-not-be-written.json"

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_root=evidence_root,
        canonical_output_roots=[canonical_root],
        output_path=output,
        preflight_only=True,
    )

    assert report["status"] == "ready"
    assert report["exact_51_ready"] is True
    assert report["output"]["written"] is False
    assert report["source_provenance_verifier"] == (
        state_laws_local_release.state_laws_source_provenance_verifier_attestation()
    )
    provenance_path = Path(state_laws_local_release.__file__).with_name(
        "state_laws_source_provenance.py"
    )
    assert report["source_provenance_verifier"]["sha256"] == hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()
    assert not output.exists()


def test_normalized_receipt_without_run_final_seal_is_nonauthorizing(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    al_seals = list((evidence_root / "AL").glob(f"*{RUN_SEAL_SUFFIX}"))
    assert len(al_seals) == 1
    al_seals[0].unlink()

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_root=evidence_root,
        canonical_output_roots=[canonical_root],
        output_path=tmp_path / "maps" / "missing-seal.json",
        preflight_only=True,
    )

    assert report["status"] == "blocked"
    assert "AL" in report["blockers"]["missing_jurisdictions"]
    assert any(
        "lacks a matching quiescent run-final seal" in item["reason"]
        for item in report["ineligible_receipts"]
    )


def test_run_seal_from_stale_refresh_runner_is_nonauthorizing(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    al_seal_path = next((evidence_root / "AL").glob(f"*{RUN_SEAL_SUFFIX}"))
    seal = json.loads(al_seal_path.read_text(encoding="utf-8"))
    stale_runner = (
        "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
        + hashlib.sha256(b"stale-refresh-runner").hexdigest()
    )
    seal["runner_start_identity"] = stale_runner
    seal["runner_end_identity"] = stale_runner
    al_seal_path.write_bytes(canonical_run_seal_bytes(seal))

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_root=evidence_root,
        canonical_output_roots=[canonical_root],
        output_path=tmp_path / "maps" / "stale-runner-seal.json",
        preflight_only=True,
    )

    assert report["status"] == "blocked"
    assert "AL" in report["blockers"]["missing_jurisdictions"]
    assert any(
        "refresh-runner identity differs from current code" in item["reason"]
        for item in report["blockers"]["invalid_receipts"]
    )


def test_nonquiescent_poison_marker_rejects_entire_evidence_root(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    marker = evidence_root / cli.NONQUIESCENT_EVIDENCE_MARKER
    marker.write_text(
        json.dumps({"permanently_nonauthorizing": True}),
        encoding="utf-8",
    )

    with pytest.raises(
        cli.StateLawsInputMapAssemblyError,
        match="permanently non-authorizing",
    ):
        cli.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[canonical_root],
            output_path=tmp_path / "maps" / "poisoned-root.json",
            preflight_only=True,
        )


def test_in_progress_marker_rejects_entire_evidence_root(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    marker = evidence_root / cli.IN_PROGRESS_EVIDENCE_MARKER
    marker.write_text(json.dumps({"run_id": "still-live"}), encoding="utf-8")

    with pytest.raises(
        cli.StateLawsInputMapAssemblyError,
        match="unclosed acquisition run",
    ):
        cli.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[canonical_root],
            output_path=tmp_path / "maps" / "in-progress-root.json",
            preflight_only=True,
        )


@pytest.mark.parametrize(
    "mutation",
    ["artifact", "receipt", "seal", "poison", "in_progress", "runner"],
)
def test_precommit_gate_rejects_selected_evidence_or_root_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    evidence_root, canonical_root, artifacts = _write_exact_51(tmp_path)
    output = tmp_path / "maps" / f"precommit-{mutation}.json"
    original_validate = cli.validate_exact_51_input_mapping

    def mutate_then_validate(payload, *, base_dir):
        if mutation == "artifact":
            artifacts["AL"].write_bytes(artifacts["AL"].read_bytes() + b"\n")
        elif mutation == "receipt":
            receipt = evidence_root / "AL" / "al-primary.normalized.json"
            receipt.write_bytes(receipt.read_bytes() + b" ")
        elif mutation == "seal":
            seal = next((evidence_root / "AL").glob(f"*{RUN_SEAL_SUFFIX}"))
            seal.write_bytes(seal.read_bytes() + b" ")
        elif mutation == "poison":
            (evidence_root / cli.NONQUIESCENT_EVIDENCE_MARKER).write_text(
                "{}", encoding="utf-8"
            )
        elif mutation == "in_progress":
            (evidence_root / cli.IN_PROGRESS_EVIDENCE_MARKER).write_text(
                "{}", encoding="utf-8"
            )
        else:
            stale = (
                "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
                + hashlib.sha256(b"changed-before-map-commit").hexdigest()
            )
            monkeypatch.setattr(
                runner,
                "current_refresh_runner_source_software_version",
                lambda **_kwargs: stale,
            )
        return original_validate(payload, base_dir=base_dir)

    monkeypatch.setattr(cli, "validate_exact_51_input_mapping", mutate_then_validate)

    with pytest.raises(
        cli.StateLawsInputMapAssemblyError,
        match="precommit gate failed",
    ):
        cli.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[canonical_root],
            output_path=output,
        )
    assert not output.exists()


def test_receipt_discovery_hashes_and_parses_one_read_of_same_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root, _, _ = _write_exact_51(tmp_path)
    target = (evidence_root / "AL" / "al-primary.normalized.json").resolve()
    original_read_bytes = Path.read_bytes
    reads = 0

    def counted_read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path.resolve() == target:
            reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    receipts, *_ = cli._discover_receipts(
        [evidence_root.resolve()],
        current_runner_source_software_version=(
            _test_runner_source_software_version()
        ),
    )

    assert receipts["AL"][0].record.jurisdiction == "AL"
    assert reads == 1


def test_historical_source_software_mode_cannot_write_an_input_map(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    output = tmp_path / "maps" / "historical-must-not-be-written.json"

    with pytest.raises(
        cli.StateLawsInputMapAssemblyError,
        match="historical source-software mode is read-only",
    ):
        cli.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[canonical_root],
            output_path=output,
            allow_historical_source_software=True,
        )

    assert not output.exists()


def test_repeatable_evidence_roots_union_split_generations_in_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    delta_root = tmp_path / "evidence-delta"
    dc_receipt = evidence_root / "DC" / "dc-primary.normalized.json"
    delta_receipt = delta_root / "DC" / dc_receipt.name
    delta_receipt.parent.mkdir(parents=True)
    dc_receipt.replace(delta_receipt)
    output = tmp_path / "maps" / "split-generation-map.json"

    exit_code = cli.main(
        [
            "--acquisition-evidence-root",
            str(evidence_root),
            "--acquisition-evidence-root",
            str(delta_root),
            "--canonical-output-root",
            str(canonical_root),
            "--output",
            str(output),
            "--allow-historical-source-software",
            "--preflight-only",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["status"] == "ready"
    assert report["exact_51_ready"] is True
    assert report["jurisdictions"]["DC"]["receipt_candidate_count"] == 1
    assert report["jurisdictions"]["DC"]["selected"][
        "normalized_source_receipt_path"
    ] == str(delta_receipt.resolve())
    assert not output.exists()


def test_unmatched_old_generation_does_not_override_one_matching_generation(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    old_evidence_root = tmp_path / "old-evidence"
    old_artifact = tmp_path / "old-canonical" / "STATE-IA.jsonld"
    _write_canonical(old_artifact, "IA", variant="old-parser-generation")
    old_receipt = _write_receipt(
        old_evidence_root,
        "IA",
        old_artifact,
        variant="old-parser-generation",
    )
    output = tmp_path / "maps" / "one-matching-generation.json"

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_roots=[old_evidence_root, evidence_root],
        canonical_output_roots=[canonical_root],
        output_path=output,
        preflight_only=True,
    )

    assert report["exact_51_ready"] is True
    assert report["jurisdictions"]["IA"]["eligible_pair_count"] == 1
    assert report["jurisdictions"]["IA"]["status"] == "selected"
    assert report["jurisdictions"]["IA"]["unmatched_receipts"][0]["paths"] == [
        str(old_receipt.resolve())
    ]


def test_hash_mismatch_is_a_structured_missing_gap_and_cli_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root, canonical_root, artifacts = _write_exact_51(tmp_path)
    _write_canonical(artifacts["DC"], "DC", variant="changed-after-receipt")
    output = tmp_path / "maps" / "blocked.json"

    exit_code = cli.main(
        [
            "--acquisition-evidence-root",
            str(evidence_root),
            "--canonical-output-root",
            str(canonical_root),
            "--output",
            str(output),
            "--allow-historical-source-software",
            "--preflight-only",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["status"] == "blocked"
    assert report["exact_51_ready"] is False
    assert report["blockers"]["missing_jurisdictions"] == ["DC"]
    assert report["jurisdictions"]["DC"]["unmatched_artifacts"]
    assert report["jurisdictions"]["DC"]["unmatched_receipts"]
    assert report["output"]["written"] is False
    assert not output.exists()


def test_current_source_software_gate_rejects_stale_unique_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root, canonical_root, _artifacts = _write_exact_51(tmp_path)
    current_versions = _test_source_software_versions()
    stale_digest = hashlib.sha256(b"FL-stale").hexdigest()
    stale_identity = f"tests.state_scrapers.FL@sha256:{stale_digest}"
    _write_receipt(
        evidence_root,
        "FL",
        _artifacts["FL"],
        source_software_version=stale_identity,
    )

    monkeypatch.setattr(
        cli,
        "registered_exact_51_source_software_versions",
        lambda: current_versions,
    )
    output = tmp_path / "maps" / "exact-51-input-map.json"
    blocked = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_roots=[evidence_root],
        canonical_output_roots=[canonical_root],
        output_path=output,
        preflight_only=True,
    )

    assert blocked["status"] == "blocked"
    assert blocked["exact_51_ready"] is False
    assert blocked["source_software_current_bundle_required"] is True
    assert blocked["blockers"]["source_software_mismatch_jurisdictions"] == [
        "FL"
    ]
    assert "FL" in blocked["blockers"]["missing_jurisdictions"]
    assert blocked["jurisdictions"]["FL"]["eligible_pair_count"] == 0
    assert "source_software_version mismatch" in blocked["jurisdictions"]["FL"][
        "rejected_matching_pairs"
    ][0]["reason"]
    assert not output.exists()


def test_distinct_eligible_pairs_are_a_conflict_not_an_arbitrary_selection(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_a, _ = _write_exact_51(tmp_path)
    canonical_b = tmp_path / "canonical-b"
    conflicting_artifact = canonical_b / "STATE-GA.jsonld"
    _write_canonical(conflicting_artifact, "GA", variant="newer-distinct-bytes")
    conflicting_evidence_root = tmp_path / "conflicting-evidence"
    _write_receipt(
        conflicting_evidence_root,
        "GA",
        conflicting_artifact,
        variant="newer-distinct-bytes",
    )
    output = tmp_path / "maps" / "conflict.json"

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_roots=[evidence_root, conflicting_evidence_root],
        canonical_output_roots=[canonical_a, canonical_b],
        output_path=output,
    )

    assert report["exact_51_ready"] is False
    assert report["blockers"]["conflict_jurisdictions"] == ["GA"]
    assert report["jurisdictions"]["GA"]["eligible_pair_count"] == 2
    assert report["jurisdictions"]["GA"]["selected"] is None
    assert not output.exists()


def test_checked_in_exact_51_manifest_pins_curated_evidence_pairs() -> None:
    manifest = cli._load_candidate_selection_manifest(
        _EXACT_51_SELECTION_MANIFEST
    )

    assert {
        code: selection.summary()
        for code, selection in manifest.selections.items()
    } == _EXACT_51_CURATED_SELECTIONS


def test_ct_digest_selection_selects_v12_and_retains_v11_as_unselected_evidence(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_v11_root, artifacts = _write_exact_51(tmp_path)
    v11_artifact = artifacts["CT"]
    v11_receipt = evidence_root / "CT" / "ct-primary.normalized.json"
    v11_artifact_bytes = v11_artifact.read_bytes()
    v11_receipt_bytes = v11_receipt.read_bytes()

    canonical_v12_root = tmp_path / "canonical-ct-v12"
    v12_artifact = canonical_v12_root / "STATE-CT.jsonld"
    _write_canonical(v12_artifact, "CT", variant="row-bound-v12")
    v12_evidence_root = tmp_path / "evidence-ct-v12"
    v12_receipt = _write_receipt(
        v12_evidence_root,
        "CT",
        v12_artifact,
        variant="row-bound-v12",
    )
    selection = _write_selection_manifest(
        tmp_path / "ct-selection.json",
        {"CT": (_sha256_file(v12_artifact), _sha256_file(v12_receipt))},
    )

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_roots=[evidence_root, v12_evidence_root],
        canonical_output_roots=[canonical_v11_root, canonical_v12_root],
        candidate_selection_manifest_path=selection,
        output_path=tmp_path / "maps" / "ct-v12-selected.json",
        preflight_only=True,
    )

    ct_report = report["jurisdictions"]["CT"]
    assert report["exact_51_ready"] is True
    assert report["blockers"]["conflict_jurisdictions"] == []
    assert ct_report["eligible_pair_count"] == 2
    assert ct_report["status"] == "selected"
    assert ct_report["selected"]["canonical_jsonld_path"] == str(
        v12_artifact.resolve()
    )
    assert ct_report["selected"]["normalized_source_receipt_path"] == str(
        v12_receipt.resolve()
    )
    assert any(
        pair["canonical_jsonld_path"] == str(v11_artifact.resolve())
        and pair["normalized_source_receipt_path"] == str(v11_receipt.resolve())
        for pair in ct_report["eligible_pairs"]
    )
    assert v11_artifact.read_bytes() == v11_artifact_bytes
    assert v11_receipt.read_bytes() == v11_receipt_bytes


def test_digest_manifest_preserves_provenance_distinct_receipts_via_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root, canonical_a, artifacts = _write_exact_51(tmp_path)
    conflicting_evidence_root = tmp_path / "conflicting-evidence"
    _write_receipt(
        conflicting_evidence_root,
        "IA",
        artifacts["IA"],
        variant="distinct-observation-and-software-provenance",
    )
    primary_receipt = evidence_root / "IA" / "ia-primary.normalized.json"
    manifest = _write_selection_manifest(
        tmp_path / "selection.json",
        {
            "IA": (
                _sha256_file(artifacts["IA"]),
                _sha256_file(primary_receipt),
            )
        },
    )
    output = tmp_path / "maps" / "curated.json"

    exit_code = cli.main(
        [
            "--acquisition-evidence-root",
            str(evidence_root),
            "--acquisition-evidence-root",
            str(conflicting_evidence_root),
            "--canonical-output-root",
            str(canonical_a),
            "--candidate-selection-manifest",
            str(manifest),
            "--output",
            str(output),
            "--allow-historical-source-software",
            "--preflight-only",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["exact_51_ready"] is True
    assert report["status"] == "ready"
    assert report["candidate_selection_manifest"] == {
        "file_sha256": _sha256_file(manifest),
        "file_size_bytes": manifest.stat().st_size,
        "listed_jurisdictions": ["IA"],
        "path": str(manifest.resolve()),
        "schema_version": cli.SELECTION_MANIFEST_SCHEMA_VERSION,
        "selection_count": 1,
    }
    ia_report = report["jurisdictions"]["IA"]
    assert ia_report["artifact_candidate_count"] == 1
    assert ia_report["eligible_pair_count"] == 2
    assert ia_report["receipt_candidate_count"] == 2
    assert ia_report["selected"]["canonical_jsonld_sha256"] == _sha256_file(
        artifacts["IA"]
    )
    assert ia_report["selected"]["normalized_source_receipt_sha256"] == (
        _sha256_file(primary_receipt)
    )
    assert ia_report["selection_evidence"]["manifest_listed"] is True
    assert ia_report["selection_evidence"]["matching_eligible_pair_count"] == 1
    assert report["jurisdictions"]["AL"]["selection_evidence"]["mode"] == (
        "automatic_unique_eligible_pair"
    )
    assert not output.exists()


def test_unmatched_manifest_digest_pair_is_a_blocker_and_preserves_output(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, artifacts = _write_exact_51(tmp_path)
    manifest = _write_selection_manifest(
        tmp_path / "unmatched-selection.json",
        {"IA": (_sha256_file(artifacts["IA"]), "f" * 64)},
    )
    output = tmp_path / "existing-map.json"
    output.write_bytes(b"existing-map-must-survive\n")

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_root=evidence_root,
        canonical_output_roots=[canonical_root],
        candidate_selection_manifest_path=manifest,
        output_path=output,
    )

    assert report["exact_51_ready"] is False
    assert report["status"] == "blocked"
    assert report["blockers"]["candidate_selection_unmatched_jurisdictions"] == ["IA"]
    assert report["blockers"]["candidate_selection_ambiguous_jurisdictions"] == []
    evidence = report["jurisdictions"]["IA"]["selection_evidence"]
    assert evidence["outcome"] == "candidate_selection_unmatched"
    assert evidence["matching_eligible_pair_count"] == 0
    assert report["output"]["existing_output_preserved"] is True
    assert output.read_bytes() == b"existing-map-must-survive\n"


def test_ambiguous_manifest_digest_pair_is_a_structured_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root, canonical_root, artifacts = _write_exact_51(tmp_path)
    receipt = evidence_root / "CT" / "ct-primary.normalized.json"
    manifest = _write_selection_manifest(
        tmp_path / "ambiguous-selection.json",
        {"CT": (_sha256_file(artifacts["CT"]), _sha256_file(receipt))},
    )
    original = cli._eligible_pairs_for_code

    def duplicate_selected_pair(
        code: str,
        receipts: tuple[cli.ReceiptCandidate, ...],
        artifacts: tuple[cli.ArtifactCandidate, ...],
        *,
        required_source_software_version: str | None = None,
    ) -> tuple[tuple[cli.EligiblePair, ...], list[dict[str, str]]]:
        eligible, rejected = original(
            code,
            receipts,
            artifacts,
            required_source_software_version=required_source_software_version,
        )
        if code == "CT":
            return (eligible[0], eligible[0]), rejected
        return eligible, rejected

    monkeypatch.setattr(cli, "_eligible_pairs_for_code", duplicate_selected_pair)
    output = tmp_path / "ambiguous-map.json"

    report = cli.assemble_state_laws_production_input_map(
        acquisition_evidence_root=evidence_root,
        canonical_output_roots=[canonical_root],
        candidate_selection_manifest_path=manifest,
        output_path=output,
    )

    assert report["blockers"]["candidate_selection_ambiguous_jurisdictions"] == ["CT"]
    evidence = report["jurisdictions"]["CT"]["selection_evidence"]
    assert evidence["outcome"] == "candidate_selection_ambiguous"
    assert evidence["matching_eligible_pair_count"] == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "unversioned", "states": {}},
        {
            "schema_version": cli.SELECTION_MANIFEST_SCHEMA_VERSION,
            "states": {"PR": {}},
        },
        {
            "schema_version": cli.SELECTION_MANIFEST_SCHEMA_VERSION,
            "states": {
                "IA": {
                    "canonical_jsonld_sha256": "not-a-sha256",
                    "normalized_source_receipt_sha256": "f" * 64,
                }
            },
        },
        {
            "schema_version": cli.SELECTION_MANIFEST_SCHEMA_VERSION,
            "states": {},
            "unexpected": True,
        },
    ],
)
def test_rejects_malformed_selection_manifests(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    manifest = tmp_path / "malformed.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(cli.StateLawsInputMapAssemblyError):
        cli._load_candidate_selection_manifest(manifest)


def test_rejects_selection_manifest_symlinks_and_special_files(
    tmp_path: Path,
) -> None:
    target = _write_selection_manifest(
        tmp_path / "target.json",
        {"IA": ("e" * 64, "f" * 64)},
    )
    link = tmp_path / "manifest-link.json"
    link.symlink_to(target)
    fifo = tmp_path / "manifest.fifo"
    fifo.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(fifo)

    with pytest.raises(cli.StateLawsInputMapAssemblyError, match="symlink"):
        cli._load_candidate_selection_manifest(link)
    with pytest.raises(cli.StateLawsInputMapAssemblyError, match="regular file"):
        cli._load_candidate_selection_manifest(fifo)


def test_selection_manifest_is_never_an_output_target(tmp_path: Path) -> None:
    evidence_root, canonical_root, artifacts = _write_exact_51(tmp_path)
    receipt = evidence_root / "IA" / "ia-primary.normalized.json"
    manifest = _write_selection_manifest(
        tmp_path / "read-only-selection.json",
        {"IA": (_sha256_file(artifacts["IA"]), _sha256_file(receipt))},
    )
    original_bytes = manifest.read_bytes()

    with pytest.raises(
        cli.StateLawsInputMapAssemblyError,
        match="overwrite selected input evidence or the candidate selection manifest",
    ):
        cli.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[canonical_root],
            candidate_selection_manifest_path=manifest,
            output_path=manifest,
        )

    assert manifest.read_bytes() == original_bytes


def test_symlinks_and_non_exact_jurisdictions_block_an_otherwise_complete_map(
    tmp_path: Path,
) -> None:
    evidence_root, canonical_root, _ = _write_exact_51(tmp_path)
    extra = canonical_root / "STATE-PR.jsonld"
    _write_canonical(extra, "PR")
    unsafe_link = evidence_root / "unsafe-link"
    unsafe_link.symlink_to(evidence_root / "AL", target_is_directory=True)
    output = tmp_path / "maps" / "unsafe.json"

    with pytest.raises(
        cli.StateLawsInputMapAssemblyError,
        match="unsafe directory symlink",
    ):
        cli.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[canonical_root],
            output_path=output,
        )

    assert not output.exists()
