"""Focused regressions for the exact-51 LIVE candidate manifest generator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

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
    IN_PROGRESS_EVIDENCE_MARKER,
    RUN_SEAL_SUFFIX,
    build_state_laws_run_seal,
    canonical_run_seal_bytes,
)

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "generate_state_laws_candidate_selection_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "generate_state_laws_candidate_selection_manifest_test_target", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cli
_SPEC.loader.exec_module(cli)

_ASSEMBLER_PATH = _SCRIPT_PATH.with_name("assemble_state_laws_production_input_map.py")
_ASSEMBLER_SPEC = importlib.util.spec_from_file_location(
    "candidate_manifest_assembler_contract_test_target", _ASSEMBLER_PATH
)
assert _ASSEMBLER_SPEC is not None and _ASSEMBLER_SPEC.loader is not None
assembler = importlib.util.module_from_spec(_ASSEMBLER_SPEC)
sys.modules[_ASSEMBLER_SPEC.name] = assembler
_ASSEMBLER_SPEC.loader.exec_module(assembler)


def _test_source_versions() -> dict[str, str]:
    return {
        code: (
            f"tests.state_scrapers.{code}@sha256:"
            f"{hashlib.sha256(f'{code}-live-source'.encode('ascii')).hexdigest()}"
        )
        for code in CANONICAL_JURISDICTION_ORDER
    }


def _test_runner_identity() -> str:
    return (
        "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
        + hashlib.sha256(b"test-live-refresh-runner").hexdigest()
    )


def _test_transport_inventory(code: str) -> dict[str, Any]:
    return {
        "candidate_count": 0,
        "closure_projection_missing_jurisdictions": [],
        "closure_projection_producer_count": 1,
        "complete": True,
        "gap_jurisdictions": [],
        "jurisdiction_count": 1,
        "jurisdictions": {
            code: {
                "candidate_count": 0,
                "candidates": [],
                "closure_projection_producer_present": True,
                "complete": True,
                "schema_version": cli.TRANSPORT_INVENTORY_SCHEMA_VERSION,
            }
        },
        "publication_evidence_complete": True,
        "schema_version": cli.REGISTERED_TRANSPORT_INVENTORY_SCHEMA_VERSION,
    }


def _normalized_record_from_raw(
    raw: Mapping[str, Any],
    *,
    artifact_sha256: str,
    row_count: int,
) -> SourceReceiptRecord:
    canonical_raw = json.dumps(
        dict(raw),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SourceReceiptRecord(
        receipt_id=str(raw["receipt_id"]),
        jurisdiction=str(raw["jurisdiction"]),
        official_source_url=str(raw["official_source_url"]),
        release_point=str(raw["release_point"]),
        observation_time=str(raw["observation_time"]),
        source_authority_class=SourceAuthorityClass.OFFICIAL,
        source_checksum=artifact_sha256,
        verification_result=VerificationResult.VERIFIED,
        discovered=1,
        fetched=1,
        excluded=0,
        quarantined=0,
        failed_final=0,
        frontier_closed=True,
        relative_path=str(raw["relative_path"]),
        source_software_version=str(raw["source_software_version"]),
        start_urls=(str(raw["official_source_url"]),),
        content_hashes=(artifact_sha256,),
        payload={
            "adapter_input_row_count": row_count,
            "adapter_input_sha256": artifact_sha256,
            "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
            "admission_eligible": True,
            "legacy_receipt_sha256": hashlib.sha256(canonical_raw).hexdigest(),
            "qualification_reasons": [],
            "reported_canonical_row_count": row_count,
            "reported_input_sha256": artifact_sha256,
            "reported_source_authority_class": "official",
            "reported_verification_result": "verified",
            "requires_verified_transport_binding": False,
            "verified_transport_receipts": [],
            "verified_transport_receipts_trusted": False,
        },
    )


def _canonical_bytes(code: str, *, embedded_code: str | None = None) -> bytes:
    row = {
        "@id": f"urn:state:{code.lower()}:statute:1-1",
        "@type": "Legislation",
        "sectionNumber": "1-1",
        "sourceUrl": f"https://legislature.{code.lower()}.gov/code/1-1",
        "stateCode": embedded_code or code,
        "text": f"{code} public law. The agency shall preserve public records.",
    }
    return (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_live_root(
    parent: Path,
    code: str,
    *,
    label: str | None = None,
    embedded_code: str | None = None,
) -> Path:
    token = label or code
    live_root = parent / "live" / token
    evidence_root = parent / "evidence" / token
    artifact = live_root / "state_laws_jsonld" / f"STATE-{code}.jsonld"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact_bytes = _canonical_bytes(code, embedded_code=embedded_code)
    artifact.write_bytes(artifact_bytes)
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    row_count = 1
    source_identity = _test_source_versions()[code]
    runner_identity = _test_runner_identity()
    official_url = f"https://legislature.{code.lower()}.gov/code"
    release_point = hashlib.sha256(f"{token}-release".encode("ascii")).hexdigest()
    raw_receipt = {
        "jurisdiction": code,
        "observation_time": "2026-08-29T12:00:00Z",
        "official_source_url": official_url,
        "receipt_id": f"source-{token.lower()}-live-sealed",
        "relative_path": f"{code}/frontiers/{token.lower()}.json",
        "release_point": release_point,
        "source_software_version": source_identity,
        "test_acquisition_nonce": token,
    }
    raw_receipt_path = (
        evidence_root / code / "frontiers" / f"{token.lower()}.json"
    )
    _write_json(raw_receipt_path, raw_receipt)
    normalized = _normalized_record_from_raw(
        raw_receipt,
        artifact_sha256=artifact_sha256,
        row_count=row_count,
    )
    normalized_path = evidence_root / code / "frontiers" / f"{token.lower()}.normalized.json"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_bytes = (
        json.dumps(normalized.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    normalized_path.write_bytes(normalized_bytes)
    normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()

    run_id = hashlib.sha256(f"{token}-run".encode("ascii")).hexdigest()[:32]
    worker = {
        "attested": True,
        "completion_mode": "worker_returned",
        "quiescent": True,
    }
    seal = build_state_laws_run_seal(
        run_id=run_id,
        created_at="2026-08-29T12:00:01Z",
        active_states=[code],
        start_identities={code: source_identity},
        end_identities={code: source_identity},
        runner_start_identity=runner_identity,
        runner_end_identity=runner_identity,
        worker_quiescence={code: worker},
        states={
            code: {
                "canonical_jsonld_sha256": artifact_sha256,
                "normalized_source_receipt_sha256": normalized_sha256,
                "source_software_version": source_identity,
            }
        },
    )
    seal_path = evidence_root / "run-seals" / f"{run_id}{RUN_SEAL_SUFFIX}"
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_bytes = canonical_run_seal_bytes(seal)
    seal_path.write_bytes(seal_bytes)
    seal_sha256 = hashlib.sha256(seal_bytes).hexdigest()
    seal_summary = {
        "active_states": [code],
        "authorizing_for_publication": True,
        "path": str(seal_path.resolve()),
        "run_id": run_id,
        "sha256": seal_sha256,
        "size_bytes": len(seal_bytes),
        "status": "sealed",
    }

    materialization_path = (
        live_root / "receipts" / f"STATE-{code}-incremental-local-materialization.json"
    )
    materialization = {
        "schema": cli.LOCAL_MATERIALIZATION_SCHEMA_VERSION,
        "status": "materialized",
        "jurisdiction": code,
        "state_name": code,
        "operation": "incremental_local_jsonld_materialization",
        "materialized_at": "2026-08-29T12:00:00Z",
        "network_access_during_materialization": False,
        "huggingface_access_during_materialization": False,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "authorizing_coordinator_reuse": False,
        "coordinator_reuse_requires_independent_receipt": True,
        "scope": {"max_statutes": None, "mode": "full"},
        "artifact_disposition": "installed_callback_artifact",
        "callback_artifact": {
            "installed_as_canonical": True,
            "row_count": row_count,
            "sha256": artifact_sha256,
            "size_bytes": len(artifact_bytes),
        },
        "output_artifact": {
            "media_type": "application/x-ndjson",
            "relative_path": f"state_laws_jsonld/STATE-{code}.jsonld",
            "row_count": row_count,
            "sha256": artifact_sha256,
            "size_bytes": len(artifact_bytes),
        },
    }
    _write_json(materialization_path, materialization)

    state_check = {
        "authorizing_for_publication": True,
        "drift_states": [],
        "end_identities": {code: source_identity},
        "identities_equal": True,
        "phase": "state_completion_before_materialization",
        "run_gate_passed": True,
        "schema": "ipfs_datasets_py.state_laws_refresh.source_software_immutability.v1",
        "start_identities": {code: source_identity},
        "state_checks": {
            code: {
                "end_identity": source_identity,
                "identities_equal": True,
                "start_identity": source_identity,
            }
        },
        "state_count": 1,
        "states": [code],
        "status": "verified",
        "verification_errors": {},
    }
    state_source = {
        "checks": [state_check],
        "run_gate_passed": True,
        "schema": "ipfs_datasets_py.state_laws_refresh.source_software_immutability.v1",
        "start_identity": source_identity,
    }
    parser_coverage = {
        "complete": True,
        "covered_row_count": row_count,
        "jurisdiction": code,
        "output_row_count": row_count,
        "uncovered_unit_count": 0,
        "uncovered_units": [],
        "uncovered_units_sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    aggregate = {
        "authorizing_for_publication": True,
        "byte_verification_ok": True,
        "canonical_jsonld_row_count": row_count,
        "canonical_jsonld_sha256": artifact_sha256,
        "frontier_verification_ok": True,
        "normalized_source_receipt_path": str(normalized_path.resolve()),
        "receipt_path": str(raw_receipt_path.resolve()),
        "run_seal_path": str(seal_path.resolve()),
        "run_seal_sha256": seal_sha256,
        "status": "closed_and_normalized",
    }
    state_evidence = {
        "aggregate": aggregate,
        "aggregate_eligible": True,
        "all_fetch_coverage_claimed": True,
        "attached_before_scrape_all": True,
        "eligibility_blockers": [],
        "enabled": True,
        "evidence_root": str(evidence_root.resolve()),
        "jurisdiction": code,
        "normalized_source_receipt_usable": True,
        "parser_name": f"{code}Scraper",
        "parser_output_coverage": parser_coverage,
        "retained_replay_only": False,
        "run_seal": seal_summary,
        "strict": True,
    }
    state_entry = {
        "acquisition_evidence": state_evidence,
        "authorizing_coordinator_reuse": False,
        "authorizing_for_publication": True,
        "completed_at": "2026-08-29T12:00:00Z",
        "incremental_materialization_status": "success",
        "jsonld_row_count": row_count,
        "jsonld_sha256": artifact_sha256,
        "local_materialization_receipt": str(materialization_path.resolve()),
        "run_seal_path": str(seal_path.resolve()),
        "run_seal_sha256": seal_sha256,
        "source_software_immutability": state_source,
        "state_code": code,
        "state_name": code,
        "status": "success",
        "statutes_count": row_count,
        "worker_quiescence": worker,
    }
    source_immutability = {
        "active_state_count": 1,
        "active_states": [code],
        "authorizing_for_publication": True,
        "end_identities": {code: source_identity},
        "failed_states": [],
        "failure_reasons": {},
        "identities_equal": True,
        "permanent_nonauthorization_marker_path": None,
        "run_finalization_failed_states": [],
        "run_finalization_failure_reasons": {},
        "run_id": run_id,
        "run_seal": seal_summary,
        "runner_end_identity": runner_identity,
        "runner_identity_equal": True,
        "runner_start_identity": runner_identity,
        "runner_verification_error": None,
        "schema": "ipfs_datasets_py.state_laws_refresh.source_software_immutability.v1",
        "start_identities": {code: source_identity},
        "status": "verified",
        "verification_errors": {},
        "worker_quiescence": {code: worker},
        "worker_quiescence_failed_states": [],
    }
    acquisition_summary = {
        "aggregate_closed_count": 1,
        "aggregate_closed_states": [code],
        "authorizing_for_publication": True,
        "evidence_gap_states": [],
        "evidence_root": str(evidence_root.resolve()),
        "nonquiescent_marker_paths": [],
        "permanent_nonauthorization_marker_paths": [],
        "retained_replay_only": False,
        "run_finalization_failed_states": [],
        "run_finalization_failure_reasons": {},
        "run_seal": seal_summary,
        "source_software_immutability_verified": True,
        "strict": True,
        "transport_bypass_inventory": _test_transport_inventory(code),
        "worker_quiescence_failed_states": [],
    }
    progress = {
        "schema": cli.PROGRESS_SCHEMA_VERSION,
        "acquisition_run_id": run_id,
        "status": "partial_success",
        "states": [code],
        "active_states": [code],
        "states_total": 1,
        "active_states_total": 1,
        "skipped_completed_states": [],
        "state_results": {code: state_entry},
        "states_completed": [code],
        "completed_count": 1,
        "success_count": 1,
        "error_count": 0,
        "zero_statute_count": 0,
        "acquisition_evidence_root": str(evidence_root.resolve()),
        "strict_acquisition_evidence": True,
        "retained_replay_only": False,
        "source_software_immutability": source_immutability,
        "scrape_gap_states": [],
        "build_gap_states": [],
        "is_complete": False,
        "exact_production_jurisdiction_set": False,
        "acquisition_evidence": acquisition_summary,
        "run_seal": seal_summary,
        "worker_quiescence_failed_states": [],
    }
    _write_json(live_root / cli.PROGRESS_FILENAME, progress)
    return live_root


def _write_exact_51(parent: Path) -> list[Path]:
    return [_write_live_root(parent, code) for code in CANONICAL_JURISDICTION_ORDER]


def _progress(root: Path) -> dict[str, Any]:
    return json.loads((root / cli.PROGRESS_FILENAME).read_text(encoding="utf-8"))


def _mutate_progress(root: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    payload = _progress(root)
    mutation(payload)
    _write_json(root / cli.PROGRESS_FILENAME, payload)


class _FakeAdapter:
    calls: ClassVar[list[str]] = []

    def __init__(
        self,
        *,
        input_path: Path,
        jurisdiction: str,
        release_point: str,
        source_receipt: Mapping[str, Any],
    ) -> None:
        serialized = Path(input_path).read_bytes()
        digest = hashlib.sha256(serialized).hexdigest()
        rows = sum(1 for line in serialized.splitlines() if line.strip())
        assert source_receipt["jurisdiction"] == jurisdiction
        assert source_receipt["release_point"] == release_point
        record = _normalized_record_from_raw(
            source_receipt,
            artifact_sha256=digest,
            row_count=rows,
        )
        self.source_receipt = SimpleNamespace(
            admission_eligible=True,
            qualification_reasons=(),
            input_sha256=digest,
            input_row_count=rows,
            expected_row_count=rows,
            record=record,
        )
        self.calls.append(jurisdiction)


@pytest.fixture(autouse=True)
def _stable_current_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAdapter.calls = []
    monkeypatch.setattr(cli, "LegacyStateLawsV2Adapter", _FakeAdapter)
    monkeypatch.setattr(
        cli,
        "registered_exact_51_source_software_versions",
        _test_source_versions,
    )
    monkeypatch.setattr(
        cli,
        "current_refresh_runner_source_software_version",
        lambda **_kwargs: _test_runner_identity(),
    )
    monkeypatch.setattr(
        cli,
        "inventory_registered_state_scraper_transport_bypasses",
        lambda states: _test_transport_inventory(next(iter(states))),
    )


def test_generates_deterministic_exact_51_manifest_from_isolated_live_runs(
    tmp_path: Path,
) -> None:
    roots = _write_exact_51(tmp_path)
    output = tmp_path / "manifests" / "exact-51-selection.json"

    first = cli.generate_state_laws_candidate_selection_manifest(
        live_roots=list(reversed(roots)),
        output_path=output,
    )
    first_bytes = output.read_bytes()
    second = cli.generate_state_laws_candidate_selection_manifest(
        live_roots=roots,
        output_path=output,
    )

    assert first == second == json.loads(output.read_text(encoding="utf-8"))
    assert output.read_bytes() == first_bytes
    assert first["schema_version"] == cli.SELECTION_MANIFEST_SCHEMA_VERSION
    assert set(first) == {"schema_version", "states"}
    assert set(first["states"]) == set(CANONICAL_JURISDICTION_ORDER)
    assert len(first["states"]) == EXPECTED_JURISDICTION_COUNT
    assert all(
        set(selection)
        == {
            "canonical_jsonld_sha256",
            "normalized_source_receipt_sha256",
            "run_seal_sha256",
        }
        for selection in first["states"].values()
    )
    loaded_by_assembler = assembler._load_candidate_selection_manifest(output)
    assert loaded_by_assembler.file_sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert set(loaded_by_assembler.selections) == set(CANONICAL_JURISDICTION_ORDER)
    assert _FakeAdapter.calls == list(reversed(CANONICAL_JURISDICTION_ORDER)) + list(
        CANONICAL_JURISDICTION_ORDER
    )


def test_requires_51_distinct_explicit_nonaliased_roots(tmp_path: Path) -> None:
    roots = _write_exact_51(tmp_path)
    output = tmp_path / "manifests" / "selection.json"

    with pytest.raises(cli.StateLawsCandidateSelectionError, match="exactly 51"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots[:-1], output_path=output
        )
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="duplicate LIVE root"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=[*roots[:-1], roots[0]], output_path=output
        )
    alias = tmp_path / "aliased-live-root"
    alias.symlink_to(roots[-1], target_is_directory=True)
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="symlink"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=[*roots[:-1], alias], output_path=output
        )
    alias.unlink()
    nested_alias = roots[0] / "unsafe-alias"
    nested_alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="directory symlink"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots, output_path=output
        )
    assert not output.exists()


def test_requires_raw_receipt_and_exact_normalization_replay(tmp_path: Path) -> None:
    roots = _write_exact_51(tmp_path)
    al_root = roots[list(CANONICAL_JURISDICTION_ORDER).index("AL")]
    progress = _progress(al_root)
    aggregate = progress["state_results"]["AL"]["acquisition_evidence"]["aggregate"]
    raw_path = Path(aggregate["receipt_path"])
    normalized_path = Path(aggregate["normalized_source_receipt_path"])
    raw_bytes = raw_path.read_bytes()
    normalized_bytes = normalized_path.read_bytes()
    output = tmp_path / "manifests" / "selection.json"

    raw_path.unlink()
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="does not exist"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )
    raw_path.write_bytes(raw_bytes)

    raw_payload = json.loads(raw_bytes)
    raw_payload["test_acquisition_nonce"] = "tampered-after-normalization"
    _write_json(raw_path, raw_payload)
    with pytest.raises(
        cli.StateLawsCandidateSelectionError,
        match="stored normalized receipt differs from raw receipt replay",
    ):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )
    raw_path.write_bytes(raw_bytes)

    normalized_payload = json.loads(normalized_bytes)
    normalized_payload["receipt_id"] = "source-al-mismatched-normalization"
    _write_json(normalized_path, normalized_payload)
    with pytest.raises(
        cli.StateLawsCandidateSelectionError,
        match="stored normalized receipt differs from raw receipt replay",
    ):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )
    normalized_path.write_bytes(normalized_bytes)
    assert not output.exists()


def test_requires_complete_recomputed_registered_transport_inventory(
    tmp_path: Path,
) -> None:
    roots = _write_exact_51(tmp_path)
    al_root = roots[list(CANONICAL_JURISDICTION_ORDER).index("AL")]
    progress_path = al_root / cli.PROGRESS_FILENAME
    original = progress_path.read_bytes()
    output = tmp_path / "manifests" / "selection.json"

    progress = json.loads(original)
    progress["acquisition_evidence"].pop("transport_bypass_inventory")
    _write_json(progress_path, progress)
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="transport inventory"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )

    progress = json.loads(original)
    progress["acquisition_evidence"]["transport_bypass_inventory"]["complete"] = False
    _write_json(progress_path, progress)
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="inventory is incomplete"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )
    progress_path.write_bytes(original)
    assert not output.exists()


def test_requires_source_attestation_schema_and_matching_run_id(
    tmp_path: Path,
) -> None:
    roots = _write_exact_51(tmp_path)
    al_root = roots[list(CANONICAL_JURISDICTION_ORDER).index("AL")]
    output = tmp_path / "manifests" / "selection.json"

    _mutate_progress(
        al_root,
        lambda payload: payload["source_software_immutability"].__setitem__(
            "run_id",
            "f" * 32,
        ),
    )
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="run_id mismatch"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )
    assert not output.exists()


def test_atomic_output_rejects_named_parent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _write_exact_51(tmp_path)
    output_parent = tmp_path / "manifests"
    output_parent.mkdir()
    displaced_parent = tmp_path / "displaced-manifests"
    output = output_parent / "selection.json"
    original_replace = cli.os.replace
    replaced = False

    def replace_after_parent_swap(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal replaced
        if not replaced:
            output_parent.rename(displaced_parent)
            output_parent.mkdir()
            replaced = True
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(cli.os, "replace", replace_after_parent_swap)

    with pytest.raises(
        cli.StateLawsCandidateSelectionError,
        match="named output parent changed",
    ):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots,
            output_path=output,
        )

    assert replaced is True
    assert not output.exists()


def test_rejects_replay_or_jurisdiction_local_partiality_without_overwrite(
    tmp_path: Path,
) -> None:
    roots = _write_exact_51(tmp_path)
    al_root = roots[list(CANONICAL_JURISDICTION_ORDER).index("AL")]
    progress_path = al_root / cli.PROGRESS_FILENAME
    original = progress_path.read_bytes()
    output = tmp_path / "manifests" / "selection.json"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing-curation\n")
    mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        (
            "retained replay",
            lambda payload: payload.__setitem__("retained_replay_only", True),
        ),
        (
            "skipped/reused input",
            lambda payload: payload["skipped_completed_states"].append("AL"),
        ),
        (
            "scrape gap",
            lambda payload: payload["scrape_gap_states"].append("AL"),
        ),
        (
            "uncovered parser output",
            lambda payload: payload["state_results"]["AL"]["acquisition_evidence"][
                "parser_output_coverage"
            ].update({"complete": False, "uncovered_unit_count": 1}),
        ),
        (
            "bounded materialization",
            lambda payload: None,
        ),
    ]
    for label, mutation in mutations:
        progress_path.write_bytes(original)
        if label == "bounded materialization":
            materialization_path = Path(
                _progress(al_root)["state_results"]["AL"]["local_materialization_receipt"]
            )
            materialization_original = materialization_path.read_bytes()
            materialization = json.loads(materialization_original)
            materialization["scope"] = {"max_statutes": 10, "mode": "bounded"}
            _write_json(materialization_path, materialization)
        else:
            mutation_payload = _progress(al_root)
            mutation(mutation_payload)
            _write_json(progress_path, mutation_payload)
            materialization_path = None
            materialization_original = b""
        with pytest.raises(cli.StateLawsCandidateSelectionError):
            cli.generate_state_laws_candidate_selection_manifest(
                live_roots=roots,
                output_path=output,
            )
        assert output.read_bytes() == b"existing-curation\n", label
        if materialization_path is not None:
            materialization_path.write_bytes(materialization_original)
    progress_path.write_bytes(original)


def test_rejects_stale_hashes_and_forbidden_evidence_markers(tmp_path: Path) -> None:
    roots = _write_exact_51(tmp_path)
    al_root = roots[list(CANONICAL_JURISDICTION_ORDER).index("AL")]
    progress = _progress(al_root)
    al_entry = progress["state_results"]["AL"]
    materialization = json.loads(
        Path(al_entry["local_materialization_receipt"]).read_text(encoding="utf-8")
    )
    artifact = al_root / materialization["output_artifact"]["relative_path"]
    artifact_original = artifact.read_bytes()
    output = tmp_path / "manifests" / "selection.json"

    artifact.write_bytes(artifact_original + b" \n")
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="stale"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots, output_path=output
        )
    artifact.write_bytes(artifact_original)

    receipt = Path(
        al_entry["acquisition_evidence"]["aggregate"]["normalized_source_receipt_path"]
    )
    receipt_original = receipt.read_bytes()
    receipt.write_bytes(receipt_original + b" ")
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="run-final seal"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots, output_path=output
        )
    receipt.write_bytes(receipt_original)

    evidence_root = Path(progress["acquisition_evidence_root"])
    (evidence_root / IN_PROGRESS_EVIDENCE_MARKER).write_text("{}", encoding="utf-8")
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="non-authorizing"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=roots, output_path=output
        )
    assert not output.exists()


def test_rejects_competing_jurisdictions_and_canonical_row_mismatch(
    tmp_path: Path,
) -> None:
    roots = _write_exact_51(tmp_path)
    output = tmp_path / "manifests" / "selection.json"
    duplicate_al = _write_live_root(tmp_path, "AL", label="AL-second")
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="both claim jurisdiction AL"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=[*roots[:-1], duplicate_al], output_path=output
        )

    mismatched_parent = tmp_path / "mismatched"
    mismatched_roots = [
        _write_live_root(
            mismatched_parent,
            code,
            embedded_code="AK" if code == "AL" else None,
        )
        for code in CANONICAL_JURISDICTION_ORDER
    ]
    with pytest.raises(cli.StateLawsCandidateSelectionError, match="mismatched stateCode"):
        cli.generate_state_laws_candidate_selection_manifest(
            live_roots=mismatched_roots,
            output_path=output,
        )
    assert not output.exists()


def test_cli_has_no_caller_supplied_digest_channel() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(
            [
                "--live-root",
                "/tmp/live",
                "--canonical-jsonld-sha256",
                "0" * 64,
                "--output",
                "/tmp/output.json",
            ]
        )
