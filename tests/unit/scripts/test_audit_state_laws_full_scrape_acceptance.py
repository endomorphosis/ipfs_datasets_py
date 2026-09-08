"""Fail-closed LCR-084 full-scrape acceptance tests."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import scripts.ops.legal_data.audit_state_laws_full_scrape_acceptance as audit
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 8, 28, 2, 0, tzinfo=UTC)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _current_public_parent_provenance() -> dict[str, object]:
    parent_audit = audit.candidate_builder.current_public_parent_audit
    return {
        "authorizes_exact_51_acceptance": False,
        "authorizes_hub_mutation": False,
        "authorizes_publication": False,
        "current_corpus_accepted": False,
        "current_corpus_non_acceptance": copy.deepcopy(
            audit.candidate_builder.EXPECTED_CURRENT_CORPUS_NON_ACCEPTANCE
        ),
        "current_public_parent_pin": parent_audit.CURRENT_PUBLIC_PARENT_PIN,
        "current_public_parent_role": "optimistic_parent_and_rollback_only",
        "current_public_parent_tree_oid": parent_audit.CURRENT_PUBLIC_PARENT_TREE_OID,
        "evidence_only": True,
        "goal_id": "LCR-G146",
        "historical_baseline_pin": parent_audit.HISTORICAL_BASELINE_PIN,
        "historical_baseline_role": "sealed_historical_evidence_only",
        "historical_baseline_tree_oid": parent_audit.HISTORICAL_BASELINE_TREE_OID,
        "identity_sha256": "1" * 64,
        "observed_at_utc": _stamp(NOW - timedelta(seconds=1)),
        "path": audit.CURRENT_PUBLIC_PARENT_RELPATH.as_posix(),
        "receipt_file_sha256": "2" * 64,
        "receipt_sha256": "3" * 64,
        "satisfies_lcr084_acceptance": False,
        "schema": parent_audit.REPORT_SCHEMA,
        "task_id": "LCR-084",
    }


def _production_evidence(tmp_path: Path) -> dict[str, object]:
    jurisdictions: list[dict[str, object]] = []
    official_replay: list[dict[str, object]] = []
    per_rows: list[dict[str, object]] = []
    baseline_parts: list[dict[str, object]] = []
    comparisons: list[dict[str, object]] = []
    union_rows: list[dict[str, str]] = []
    union_keys: list[str] = []
    source_receipts: list[dict[str, object]] = []
    source_versions: list[dict[str, object]] = []
    runner_identity = f"refresh@sha256:{'9' * 64}"
    for code in CANONICAL_JURISDICTION_ORDER:
        canonical = tmp_path / "canonical" / f"STATE-{code}.jsonld"
        receipt_path = tmp_path / "receipts" / f"{code}.normalized.json"
        seal_path = tmp_path / "receipts" / f"{code}.run-seal.json"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(json.dumps({"jurisdiction": code}) + "\n", encoding="utf-8")
        canonical_sha = _sha(canonical.read_bytes())
        receipt = {
            "content_hashes": [canonical_sha],
            "discovered": 1,
            "duplicates": 0,
            "excluded": 0,
            "failed_final": 0,
            "fetched": 1,
            "frontier_closed": True,
            "jurisdiction": code,
            "observation_time": _stamp(NOW - timedelta(minutes=2)),
            "official_source_url": f"https://official.example/{code}",
            "payload": {
                "attempts_exhausted": True,
                "checkpoint_complete": True,
                "qualification_reasons": [],
            },
            "quarantined": 0,
            "receipt_id": f"{code.lower()}-official-live",
            "release_point": f"official-{code}-20260828",
            "source_software_version": f"scraper-{code}@sha256:{_sha(code.encode())}",
        }
        receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        seal_path.write_text(
            json.dumps({"created_at": _stamp(NOW - timedelta(minutes=1))}),
            encoding="utf-8",
        )
        release_receipt = tmp_path / "release" / "receipts" / f"{code}.json"
        release_receipt.parent.mkdir(parents=True, exist_ok=True)
        release_receipt.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        shard = (
            tmp_path
            / "release"
            / "data"
            / "corpus"
            / "jurisdiction"
            / code
            / "part-00000.parquet"
        )
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_bytes(f"sealed-{code}-corpus-shard".encode())
        entry_cid = f"sha256:{_sha(f'entry-{code}'.encode())}"
        corpus_row = {"entry_cid": entry_cid, "jurisdiction": code}
        entry_digest = audit.candidate_builder.digest_payload(
            {"entry_cids": [entry_cid]}
        )
        row_digest = audit.candidate_builder.digest_payload([corpus_row])
        shard_projection = {
            "first_key": entry_cid,
            "last_key": entry_cid,
            "relative_path": shard.relative_to(tmp_path / "release").as_posix(),
            "row_count": 1,
            "sha256": _sha(shard.read_bytes()),
        }
        receipt_digest = audit.candidate_builder.digest_payload(receipt)
        jurisdictions.append(
            {
                "canonical_jsonld_path": str(canonical),
                "canonical_jsonld_sha256": canonical_sha,
                "canonical_row_count": 1,
                "content_hashes_digest_sha256": audit.candidate_builder.digest_payload(
                    [canonical_sha]
                ),
                "discovered": 1,
                "duplicates": 0,
                "excluded": 0,
                "failed_final": 0,
                "fetched": 1,
                "frontier_closed": True,
                "jurisdiction": code,
                "normalized_source_receipt_path": str(receipt_path),
                "normalized_source_receipt_sha256": _sha(receipt_path.read_bytes()),
                "observation_time": receipt["observation_time"],
                "official_source_url": receipt["official_source_url"],
                "quarantined": 0,
                "receipt_id": receipt["receipt_id"],
                "release_point": receipt["release_point"],
                "release_source_receipt_digest_sha256": receipt_digest,
                "release_source_receipt_path": release_receipt.relative_to(
                    tmp_path / "release"
                ).as_posix(),
                "release_source_receipt_sha256": _sha(
                    release_receipt.read_bytes()
                ),
                "run_seal_created_at": _stamp(NOW - timedelta(minutes=1)),
                "run_seal_path": str(seal_path),
                "run_seal_sha256": _sha(seal_path.read_bytes()),
                "source_software_version": receipt["source_software_version"],
            }
        )
        per_rows.append(
            {
                "adapter_dispositions": {
                    "admitted": 1,
                    "quarantined": 0,
                    "rejected": 0,
                },
                "admitted_row_count": 1,
                "input_corpus_rows_digest_sha256": row_digest,
                "input_entry_cids_digest_sha256": entry_digest,
                "jurisdiction": code,
                "release_corpus_rows_digest_sha256": row_digest,
                "release_corpus_shards": [shard_projection],
                "release_corpus_shards_digest_sha256": (
                    audit.candidate_builder.digest_payload([shard_projection])
                ),
                "release_entry_cids_digest_sha256": entry_digest,
            }
        )
        source_versions.append(
            {
                "jurisdiction": code,
                "source_software_version": receipt["source_software_version"],
            }
        )
        official_replay.append(
            {
                "acquisition_path_ids": [f"official-{code.lower()}"],
                "canonical_row_count": 1,
                "content_body_hashes_digest_sha256": _sha(
                    f"bodies-{code}".encode()
                ),
                "corpus_entry_cids_digest_sha256": entry_digest,
                "corpus_rows_digest_sha256": row_digest,
                "jurisdiction": code,
                "official_source_url": receipt["official_source_url"],
                "request_ledger_sha256": _sha(f"requests-{code}".encode()),
                "response_ledger_sha256": _sha(f"responses-{code}".encode()),
                "response_projection_digest_sha256": _sha(
                    f"response-projection-{code}".encode()
                ),
                "runner_identity_binding": {
                    "runner_end_identity": runner_identity,
                    "runner_start_identity": runner_identity,
                    "source_software_version": receipt["source_software_version"],
                },
                "selected_evidence": {
                    "canonical_jsonld_sha256": canonical_sha,
                    "closure_input_sha256": _sha(f"closure-{code}".encode()),
                    "legacy_receipt_sha256": _sha(f"legacy-{code}".encode()),
                    "normalized_source_receipt_sha256": _sha(
                        receipt_path.read_bytes()
                    ),
                    "run_seal_canonical_jsonld_sha256": canonical_sha,
                    "run_seal_normalized_source_receipt_sha256": _sha(
                        receipt_path.read_bytes()
                    ),
                    "run_seal_sha256": _sha(seal_path.read_bytes()),
                    "selected_corpus_rows_digest_sha256": row_digest,
                    "selected_entry_cids_digest_sha256": entry_digest,
                },
                "source_software_version": receipt["source_software_version"],
                "start_urls": [receipt["official_source_url"]],
                "terminal_projection_digest_sha256": _sha(
                    f"terminal-{code}".encode()
                ),
            }
        )
        union_rows.append(corpus_row)
        union_keys.append(entry_cid)
        source_receipts.append(receipt)
        baseline_parts.append(
            {
                "content_sha256": _sha(f"baseline-{code}".encode()),
                "footer_sha256": _sha(f"footer-{code}".encode()),
                "jurisdiction": code,
                "noncomparable_recovery_manifest_count": 0,
                "noncomparable_recovery_manifest_multiset_sha256": (
                    audit.candidate_builder.digest_payload([])
                ),
                "num_rows": 1,
                "path": f"state_laws_parquet_cid/STATE-{code}.parquet",
                "source_identity_count": 1,
                "source_identity_multiset_sha256": (
                    audit.candidate_builder.digest_payload(
                        [f"urn:test:{code}:one"]
                    )
                ),
            }
        )
        comparisons.append(
            {
                "acquired_row_count": 1,
                "acquired_source_identity_count": 1,
                "acquired_source_identity_multiset_sha256": (
                    audit.candidate_builder.digest_payload(
                        [f"urn:test:{code}:one"]
                    )
                ),
                "added_source_identity_count": 0,
                "added_source_identity_multiset_sha256": (
                    audit.candidate_builder.digest_payload([])
                ),
                "baseline_noncomparable_recovery_manifest_count": 0,
                "baseline_noncomparable_recovery_manifest_disposition": (
                    "authenticated_baseline_recovery_manifest"
                ),
                "baseline_noncomparable_recovery_manifest_multiset_sha256": (
                    audit.candidate_builder.digest_payload([])
                ),
                "baseline_row_count": 1,
                "baseline_source_identity_count": 1,
                "baseline_source_identity_multiset_sha256": (
                    audit.candidate_builder.digest_payload(
                        [f"urn:test:{code}:one"]
                    )
                ),
                "delta_from_baseline": 0,
                "disposition": "exact_match",
                "duplicate_count": 0,
                "excluded_count": 0,
                "explained_delta_count": 0,
                "jurisdiction": code,
                "quarantined_count": 0,
                "removed_source_identity_count": 0,
                "removed_source_identity_multiset_sha256": (
                    audit.candidate_builder.digest_payload([])
                ),
            }
        )
    artifact = {
        "family": "corpus",
        "relative_path": "data/corpus/part-000.parquet",
        "row_count": 51,
        "sha256": "a" * 64,
        "size_bytes": 123,
    }
    evidence: dict[str, object] = {
        "authenticated_live_baseline": {
            "live_replay_request_count": 123,
            "observed_at": _stamp(NOW - timedelta(minutes=1)),
            "partitions": baseline_parts,
            "partitions_digest_sha256": audit.candidate_builder.digest_payload(
                baseline_parts
            ),
            "path": str(tmp_path / "baseline.json"),
            "receipt_digest_sha256": "b" * 64,
            "remote_projection_digest_sha256": "a" * 64,
            "sha256": "c" * 64,
            "source_identity_closure_digest_sha256": (
                audit.candidate_builder.digest_payload(
                    [
                        {
                            "jurisdiction": item["jurisdiction"],
                            "noncomparable_recovery_manifest_count": item[
                                "noncomparable_recovery_manifest_count"
                            ],
                            "noncomparable_recovery_manifest_multiset_sha256": item[
                                "noncomparable_recovery_manifest_multiset_sha256"
                            ],
                            "source_identity_count": item[
                                "source_identity_count"
                            ],
                            "source_identity_multiset_sha256": item[
                                "source_identity_multiset_sha256"
                            ],
                        }
                        for item in baseline_parts
                    ]
                )
            ),
            "source_identity_closure_schema": (
                audit.candidate_builder.BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA
            ),
            "state_revision": "d" * 40,
            "verifier_owned_live_reobservation": True,
        },
        "baseline_reconciliation": comparisons,
        "current_public_parent_provenance": _current_public_parent_provenance(),
        "input_map": {
            "path": str(tmp_path / "input-map.json"),
            "schema_version": "state-laws-production-input-map/v2",
            "sha256": "e" * 64,
        },
        "jurisdictions": jurisdictions,
        "official_frontier_reobservation": {
            "copied_file_count": 0,
            "derivation_reverified_with_current_code": True,
            "hardlinked_file_count": 102,
            "jurisdiction_count": 51,
            "jurisdictions": official_replay,
            "jurisdictions_digest_sha256": (
                audit.candidate_builder.digest_payload(official_replay)
            ),
            "network_io_performed": False,
            "origin_reauthentication_performed": False,
            "provenance_trust_root": "verified-retained-acquisition-bytes",
            "retained_replay_completed": True,
            "schema_version": "state-laws-verifier-retained-replay/v1",
            "verifier_owned": True,
        },
        "production_release": {
            "artifact_count": 1,
            "artifact_descriptors_digest_sha256": audit.candidate_builder.digest_payload(
                [artifact]
            ),
            "artifacts": [artifact],
            "counts": [
                {"name": "corpus_documents", "value": 51},
                {"name": "searchable_chunks", "value": 51},
            ],
            "dataset_repo_id": "justicedao/ipfs_state_laws",
            "key_parity": {
                "chunk_cid_count": 51,
                "chunk_cids_exact": True,
                "chunk_cids_sha256": "f" * 64,
                "document_chunk_mapping_exact": True,
                "document_chunk_mapping_sha256": "1" * 64,
                "exact": True,
                "parent_entry_cid_count": 51,
                "parent_entry_cids_sha256": (
                    audit.candidate_builder.digest_payload(
                        {"parent_entry_cids": sorted(union_keys)}
                    )
                ),
            },
            "manifest_digest": "3" * 64,
            "manifest_file_sha256": "4" * 64,
            "manifest_path": str(tmp_path / "release" / "manifest.json"),
            "manifest_size_bytes": 100,
            "output_root": str(tmp_path / "release"),
            "release_point": "exact-release-20260828",
            "source_revision": "5" * 40,
        },
        "rights_receipt": {
            "catalog_digest_sha256": "6" * 64,
            "path": str(tmp_path / "rights.json"),
            "receipt_digest_sha256": "7" * 64,
            "sha256": "8" * 64,
            "status": "passed",
        },
        "source_bundle": {
            "current_source_software_versions": source_versions,
            "current_source_software_versions_digest_sha256": (
                audit.candidate_builder.digest_payload(source_versions)
            ),
            "refresh_runner_source_software_version": runner_identity,
        },
        "source_control": {
            "clean_at_seal": True,
            "excluded_evidence_paths": [
                str(tmp_path / "baseline.json"),
                audit.CURRENT_PUBLIC_PARENT_RELPATH.as_posix(),
                "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json",
                "docs/reports/legal_corpora_reindex/release_candidate.json",
            ],
            "revision": "5" * 40,
            "tree": "a" * 40,
        },
        "source_receipts_digest_sha256": audit.candidate_builder.digest_payload(
            {"source_receipts": source_receipts}
        ),
        "union": {
            "deduped_corpus_rows_digest_sha256": (
                audit.candidate_builder.digest_payload(union_rows)
            ),
            "deduped_entry_cids_digest_sha256": (
                audit.candidate_builder.digest_payload(
                    {"parent_entry_cids": sorted(union_keys)}
                )
            ),
            "deduped_union_count": 51,
            "duplicate_row_count": 0,
            "input_source_receipts_digest_sha256": (
                audit.candidate_builder.digest_payload(
                    {"source_receipts": source_receipts}
                )
            ),
            "per_jurisdiction": per_rows,
            "release_source_receipts_digest_sha256": (
                audit.candidate_builder.digest_payload(
                    {"source_receipts": source_receipts}
                )
            ),
            "shard_sum_before_dedup": 51,
        },
    }
    return evidence


def _refresh_baseline_digests(evidence: dict[str, object]) -> None:
    baseline = evidence["authenticated_live_baseline"]
    assert isinstance(baseline, dict)
    partitions = baseline["partitions"]
    assert isinstance(partitions, list)
    baseline["partitions_digest_sha256"] = (
        audit.candidate_builder.digest_payload(partitions)
    )
    baseline["source_identity_closure_digest_sha256"] = (
        audit.candidate_builder.digest_payload(
            [
                {
                    "jurisdiction": item["jurisdiction"],
                    "noncomparable_recovery_manifest_count": item[
                        "noncomparable_recovery_manifest_count"
                    ],
                    "noncomparable_recovery_manifest_multiset_sha256": item[
                        "noncomparable_recovery_manifest_multiset_sha256"
                    ],
                    "source_identity_count": item["source_identity_count"],
                    "source_identity_multiset_sha256": item[
                        "source_identity_multiset_sha256"
                    ],
                }
                for item in partitions
            ]
        )
    )


def _seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence: dict[str, object],
) -> dict[str, object]:
    monkeypatch.setattr(audit, "_verifier_now", lambda: NOW)
    monkeypatch.setattr(
        audit.candidate_builder,
        "collect_production_evidence",
        lambda **_kwargs: copy.deepcopy(evidence),
    )
    return audit.seal_full_scrape_acceptance(
        input_map_path=tmp_path / "input-map.json",
        rights_receipt_path=tmp_path / "rights.json",
        production_output_root=tmp_path / "release",
        live_baseline_path=tmp_path / "baseline.json",
        source_revision="5" * 40,
        candidate_path=REPO_ROOT / audit.CANDIDATE_RELPATH,
        repository_root=REPO_ROOT,
    )


def test_current_synthetic_union_cannot_satisfy_live_official() -> None:
    try:
        audit.inspect_full_scrape_acceptance(
            require_live_official=True,
            require_jurisdictions=51,
            require_production_candidate=True,
        )
    except audit.ScrapeAcceptanceError as exc:
        message = str(exc)
        assert "two-row" in message or "LCR-023" in message or "fixture" in message
        return
    raise AssertionError("synthetic LCR-023 union must not pass live official")


def test_inspect_without_live_flags_reports_blocked() -> None:
    report = audit.inspect_full_scrape_acceptance(
        require_live_official=False,
        require_jurisdictions=51,
        require_production_candidate=False,
    )
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["status"] == "blocked"
    assert report["two_row_cohorts"]["F"]
    assert report["two_row_cohorts"]["I"]


def test_cli_require_live_official_exits_nonzero() -> None:
    assert (
        audit.main(
            [
                "--require-live-official",
                "--require-jurisdictions",
                "51",
                "--require-production-candidate",
                "--check",
            ]
        )
        == 1
    )


def test_production_seal_is_exact51_schema_valid_and_verifier_timed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _production_evidence(tmp_path)
    report = _seal(tmp_path, monkeypatch, evidence)
    audit._schema_validate(report, repository_root=REPO_ROOT)
    assert report["sealed_at"] == _stamp(NOW)
    assert report["jurisdiction_codes"] == list(CANONICAL_JURISDICTION_ORDER)
    assert report["jurisdiction_count"] == 51
    assert report["local_only"] is False
    assert report["production_generation_local_only"] is True
    assert report["network_io_performed"] is True
    assert report["read_only_live_verification"] is True
    assert report["hub_mutation_performed"] is False
    parent = report["evidence"]["current_public_parent_provenance"]
    assert parent["historical_baseline_pin"].startswith("42f0546")
    assert parent["current_public_parent_pin"].startswith("78cba0e")
    assert parent["current_corpus_accepted"] is False
    assert parent["satisfies_lcr084_acceptance"] is False
    assert parent["authorizes_exact_51_acceptance"] is False
    assert parent["authorizes_publication"] is False
    assert report["report_digest_sha256"] == audit._report_digest(report)


def test_current_public_parent_cli_defaults_to_canonical_receipt() -> None:
    args = audit.build_parser().parse_args(["--check"])
    assert args.current_public_parent == (
        REPO_ROOT / audit.CURRENT_PUBLIC_PARENT_RELPATH
    )


@pytest.mark.parametrize(
    "mutation",
    ["current_pin", "acceptance_authority", "corpus_acceptance", "blockers"],
)
def test_current_parent_provenance_cannot_gain_acceptance_authority(
    tmp_path: Path,
    mutation: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    parent = evidence["current_public_parent_provenance"]
    assert isinstance(parent, dict)
    if mutation == "current_pin":
        parent["current_public_parent_pin"] = "0" * 40
    elif mutation == "acceptance_authority":
        parent["authorizes_exact_51_acceptance"] = True
    elif mutation == "corpus_acceptance":
        parent["current_corpus_accepted"] = True
    else:
        parent["current_corpus_non_acceptance"]["blocking_findings"] = []  # type: ignore[index]
    with pytest.raises(
        audit.ScrapeAcceptanceError,
        match="current-public-parent|current corpus",
    ):
        audit._check_evidence_semantics(
            evidence,
            repository_root=REPO_ROOT,
            now=NOW,
        )


def test_current_parent_receipt_alone_never_satisfies_exact51_acceptance() -> None:
    evidence = {
        "current_public_parent_provenance": _current_public_parent_provenance()
    }
    with pytest.raises(
        audit.ScrapeAcceptanceError,
        match="jurisdictions",
    ):
        audit._check_evidence_semantics(
            evidence,
            repository_root=REPO_ROOT,
            now=NOW,
        )


def test_authenticated_baseline_anchor_survives_live_replay_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _production_evidence(tmp_path)
    evidence["authenticated_live_baseline"]["observed_at"] = _stamp(  # type: ignore[index]
        NOW - timedelta(hours=2)
    )
    report = _seal(tmp_path, monkeypatch, evidence)
    assert report["status"] == "passed"

    evidence["authenticated_live_baseline"]["observed_at"] = _stamp(  # type: ignore[index]
        NOW - timedelta(days=31)
    )
    with pytest.raises(audit.ScrapeAcceptanceError, match="baseline is stale"):
        _seal(tmp_path, monkeypatch, evidence)


def test_candidate_binding_bookends_candidate_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _production_evidence(tmp_path)
    evidence_digest = audit.candidate_builder.digest_payload(evidence)
    acceptance_path = tmp_path / audit.ACCEPTANCE_RELPATH
    candidate_path = tmp_path / audit.CANDIDATE_RELPATH
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text("{}\n", encoding="utf-8")
    acceptance_sha256 = _sha(acceptance_path.read_bytes())
    sealed_at = _stamp(NOW)
    report_digest = "a" * 64
    payload = {
        "candidate_requirement": {
            "candidate_path": audit.CANDIDATE_RELPATH.as_posix(),
            "candidate_schema": audit.candidate_builder.PRODUCTION_REPORT_SCHEMA,
            "manifest_digest": evidence["production_release"]["manifest_digest"],
            "production_evidence_digest_sha256": evidence_digest,
        },
        "report_digest_sha256": report_digest,
        "sealed_at": sealed_at,
    }
    candidate = {
        "acceptance": {
            "full_scrape_acceptance_path": audit.ACCEPTANCE_RELPATH.as_posix(),
            "full_scrape_acceptance_report_digest_sha256": report_digest,
            "full_scrape_acceptance_sealed_at": sealed_at,
            "full_scrape_acceptance_sha256": acceptance_sha256,
            "production_evidence_digest_sha256": evidence_digest,
        },
        "production_evidence": copy.deepcopy(evidence),
        "report_digest_sha256": "b" * 64,
        "sealed_at": sealed_at,
    }
    candidate_path.write_text(
        json.dumps(candidate, sort_keys=True), encoding="utf-8"
    )

    def mutate_during_check(*_args: object, **_kwargs: object) -> None:
        candidate_path.write_bytes(candidate_path.read_bytes() + b"\n")

    monkeypatch.setattr(
        audit.candidate_builder,
        "check_production_candidate_report",
        mutate_during_check,
    )
    with pytest.raises(
        audit.ScrapeAcceptanceError, match="changed during verification"
    ):
        audit._validate_candidate_binding(
            payload,
            acceptance_path=acceptance_path,
            acceptance_file_sha256=acceptance_sha256,
            evidence=evidence,
            repository_root=tmp_path,
        )


def test_inspect_bookends_acceptance_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _production_evidence(tmp_path)
    report = _seal(tmp_path, monkeypatch, evidence)
    acceptance_path = tmp_path / audit.ACCEPTANCE_RELPATH
    candidate_path = tmp_path / audit.CANDIDATE_RELPATH
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    candidate = {"report_digest_sha256": "b" * 64}
    candidate_path.write_text(
        json.dumps(candidate, sort_keys=True), encoding="utf-8"
    )
    candidate_sha256 = _sha(candidate_path.read_bytes())
    monkeypatch.setattr(
        audit,
        "_remeasure_report_evidence",
        lambda *_args, **_kwargs: copy.deepcopy(evidence),
    )
    monkeypatch.setattr(
        audit, "_schema_validate", lambda *_args, **_kwargs: None
    )

    def mutate_acceptance(*_args: object, **_kwargs: object) -> object:
        acceptance_path.write_bytes(acceptance_path.read_bytes() + b"\n")
        return candidate_path, copy.deepcopy(candidate), candidate_sha256

    monkeypatch.setattr(audit, "_validate_candidate_binding", mutate_acceptance)
    with pytest.raises(
        audit.ScrapeAcceptanceError,
        match="acceptance report changed during verification",
    ):
        audit.inspect_full_scrape_acceptance(
            require_live_official=True,
            require_jurisdictions=51,
            require_production_candidate=True,
            repository_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("age", "message"),
    [
        (timedelta(days=31), "stale"),
        (timedelta(seconds=-1), "future"),
    ],
)
def test_receipt_freshness_uses_zero_skew_verifier_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    age: timedelta,
    message: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    evidence["jurisdictions"][0]["observation_time"] = _stamp(NOW - age)  # type: ignore[index]
    with pytest.raises(audit.ScrapeAcceptanceError, match=message):
        _seal(tmp_path, monkeypatch, evidence)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("fixture", "fixture/sample/cohort/gap"),
        ("continuation", "open continuation"),
        ("missing_hash", "lacks response/content hashes"),
        ("hash_drift", "hash drifted"),
    ],
)
def test_receipt_adversarial_classes_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    first = evidence["jurisdictions"][0]  # type: ignore[index]
    receipt_path = Path(first["normalized_source_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "fixture":
        receipt["receipt_id"] = "fixture-live"
    elif mutation == "continuation":
        receipt["payload"]["next_token"] = "still-open"
    elif mutation == "missing_hash":
        receipt["content_hashes"] = []
    else:
        receipt["payload"]["new"] = "changed"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    if mutation != "hash_drift":
        first["normalized_source_receipt_sha256"] = _sha(receipt_path.read_bytes())
        selected = evidence["official_frontier_reobservation"]["jurisdictions"][0][  # type: ignore[index]
            "selected_evidence"
        ]
        selected["normalized_source_receipt_sha256"] = first[
            "normalized_source_receipt_sha256"
        ]
        selected["run_seal_normalized_source_receipt_sha256"] = first[
            "normalized_source_receipt_sha256"
        ]
        replay_rows = evidence["official_frontier_reobservation"][  # type: ignore[index]
            "jurisdictions"
        ]
        evidence["official_frontier_reobservation"][  # type: ignore[index]
            "jurisdictions_digest_sha256"
        ] = audit.candidate_builder.digest_payload(replay_rows)
        release_receipt_path = (
            Path(evidence["production_release"]["output_root"])  # type: ignore[index]
            / first["release_source_receipt_path"]
        )
        release_receipt_path.write_text(
            json.dumps(receipt, sort_keys=True), encoding="utf-8"
        )
        first["release_source_receipt_sha256"] = _sha(
            release_receipt_path.read_bytes()
        )
        first["release_source_receipt_digest_sha256"] = (
            audit.candidate_builder.digest_payload(receipt)
        )
    with pytest.raises(audit.ScrapeAcceptanceError, match=message):
        _seal(tmp_path, monkeypatch, evidence)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_authenticated_baseline_must_be_exact51(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    baseline = evidence["authenticated_live_baseline"]  # type: ignore[assignment]
    partitions = baseline["partitions"]
    if mutation == "missing":
        partitions.pop()
    else:
        extra = dict(partitions[-1])
        extra["jurisdiction"] = "PR"
        partitions.append(extra)
    baseline["partitions_digest_sha256"] = audit.candidate_builder.digest_payload(
        partitions
    )
    with pytest.raises(audit.ScrapeAcceptanceError, match="baseline.*exact-51"):
        _seal(tmp_path, monkeypatch, evidence)


def test_aggregate_only_baseline_underfill_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _production_evidence(tmp_path)
    baseline = evidence["authenticated_live_baseline"]  # type: ignore[assignment]
    baseline["partitions"][0]["num_rows"] = 2
    baseline["partitions"][0]["source_identity_count"] = 2
    baseline["partitions"][0]["source_identity_multiset_sha256"] = "f" * 64
    baseline["partitions_digest_sha256"] = audit.candidate_builder.digest_payload(
        baseline["partitions"]
    )
    baseline["source_identity_closure_digest_sha256"] = (
        audit.candidate_builder.digest_payload(
            [
                {
                    "jurisdiction": item["jurisdiction"],
                    "noncomparable_recovery_manifest_count": item[
                        "noncomparable_recovery_manifest_count"
                    ],
                    "noncomparable_recovery_manifest_multiset_sha256": item[
                        "noncomparable_recovery_manifest_multiset_sha256"
                    ],
                    "source_identity_count": item["source_identity_count"],
                    "source_identity_multiset_sha256": item[
                        "source_identity_multiset_sha256"
                    ],
                }
                for item in baseline["partitions"]
            ]
        )
    )
    comparison = evidence["baseline_reconciliation"][0]  # type: ignore[index]
    evidence["jurisdictions"][0]["discovered"] = 2  # type: ignore[index]
    evidence["jurisdictions"][0]["excluded"] = 1  # type: ignore[index]
    comparison.update(
        {
            "baseline_row_count": 2,
            "baseline_source_identity_count": 2,
            "baseline_source_identity_multiset_sha256": "f" * 64,
            "delta_from_baseline": -1,
            "disposition": "exact_match",
            "excluded_count": 1,
            "explained_delta_count": 1,
        }
    )
    with pytest.raises(audit.ScrapeAcceptanceError, match="disposition arithmetic"):
        _seal(tmp_path, monkeypatch, evidence)


def test_baseline_disposition_arithmetic_cannot_be_caller_authored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _production_evidence(tmp_path)
    evidence["baseline_reconciliation"][0]["disposition"] = (  # type: ignore[index]
        "current_official_growth"
    )
    with pytest.raises(audit.ScrapeAcceptanceError, match="disposition arithmetic"):
        _seal(tmp_path, monkeypatch, evidence)


@pytest.mark.parametrize(
    "mutation",
    ["recovery_count", "recovery_digest", "explained_count", "removed_digest"],
)
def test_recovery_manifest_and_removed_multiset_arithmetic_is_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    baseline = evidence["authenticated_live_baseline"]
    assert isinstance(baseline, dict)
    partitions = baseline["partitions"]
    assert isinstance(partitions, list)
    comparison = evidence["baseline_reconciliation"][0]  # type: ignore[index]
    if mutation == "recovery_count":
        partitions[0]["noncomparable_recovery_manifest_count"] = 1
        _refresh_baseline_digests(evidence)
    elif mutation == "recovery_digest":
        partitions[0][
            "noncomparable_recovery_manifest_multiset_sha256"
        ] = "f" * 64
        _refresh_baseline_digests(evidence)
    elif mutation == "explained_count":
        comparison["explained_delta_count"] = 1
    else:
        comparison["removed_source_identity_multiset_sha256"] = "f" * 64
    with pytest.raises(
        audit.ScrapeAcceptanceError,
        match="disposition arithmetic|identit(?:y|ies)|closure",
    ):
        _seal(tmp_path, monkeypatch, evidence)


@pytest.mark.parametrize("mutation", ["artifact", "union"])
def test_manifest_descriptor_and_deduped_union_drift_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    if mutation == "artifact":
        evidence["production_release"]["artifacts"][0]["sha256"] = "0" * 64  # type: ignore[index]
        message = "artifact descriptor"
    else:
        evidence["union"]["deduped_union_count"] = 50  # type: ignore[index]
        message = "deduped union"
    with pytest.raises(audit.ScrapeAcceptanceError, match=message):
        _seal(tmp_path, monkeypatch, evidence)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_state", "official retained replay"),
        ("swapped_states", "official retained replay"),
        ("copied_bytes", "official retained replay binding drifted"),
        ("selected_mismatch", "official replay/input/source binding drifted"),
        ("nested_extra", "Additional properties"),
    ],
)
def test_official_retained_replay_adversarial_mutations_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    evidence = _production_evidence(tmp_path)
    replay = evidence["official_frontier_reobservation"]  # type: ignore[assignment]
    rows = replay["jurisdictions"]
    if mutation == "missing_state":
        rows.pop()
    elif mutation == "swapped_states":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "copied_bytes":
        replay["copied_file_count"] = 1
    elif mutation == "selected_mismatch":
        rows[0]["selected_evidence"]["canonical_jsonld_sha256"] = "0" * 64
    else:
        rows[0]["selected_evidence"]["caller_claim"] = True
    replay["jurisdictions_digest_sha256"] = audit.candidate_builder.digest_payload(
        rows
    )
    with pytest.raises(audit.ScrapeAcceptanceError, match=message):
        _seal(tmp_path, monkeypatch, evidence)


def test_schema_rejects_every_unknown_property(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _seal(tmp_path, monkeypatch, _production_evidence(tmp_path))
    report["caller_claim"] = True
    with pytest.raises(audit.ScrapeAcceptanceError, match="Additional properties"):
        audit._schema_validate(report, repository_root=REPO_ROOT)


def test_audit_loader_rejects_nested_duplicate_keys(tmp_path: Path) -> None:
    receipt = tmp_path / "candidate.json"
    receipt.write_text('{"evidence":{"sha":"a","sha":"b"}}', encoding="utf-8")
    with pytest.raises(audit.ScrapeAcceptanceError, match="duplicate key"):
        audit._load(receipt)
