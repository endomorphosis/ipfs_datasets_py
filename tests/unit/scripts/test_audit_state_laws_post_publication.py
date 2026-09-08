"""Current-contract tests for the canonical LCR-046 post-publication audit."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    canonical_no_self_field_digest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
for _name in tuple(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)
public = importlib.import_module("scripts.ops.legal_data.check_state_laws_public_release")
bench = importlib.import_module("scripts.ops.legal_data.benchmark_state_laws_public_release")
rollback = importlib.import_module("scripts.ops.legal_data.rehearse_state_laws_release_rollback")
audit = importlib.import_module("scripts.ops.legal_data.audit_state_laws_post_publication")
probe = importlib.import_module("scripts.ops.legal_data.state_laws_release_probe")


PREVIOUS = public.PREVIOUS_PUBLIC_PIN
PUBLIC = "3" * 40
STAGING = "2" * 40
CANDIDATE_DIGEST = "a" * 64
RELEASE_DIGEST = "b" * 64


def _queries() -> dict:
    return {
        name: {"passed": True}
        for name in ("bm25", "vector", "hybrid", "graph", "filters", "cache")
    } | {"jurisdictions": list(public.SORTED_JURISDICTIONS)} | _canary_provenance()


def _canary_provenance() -> dict:
    return {
        "measurement_source": probe.MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": "2026-08-29T12:00:00Z",
        "probe_bindings": probe.release_probe_bindings(
            repo_id=public.DEFAULT_DATASET_REPO,
            revision=PUBLIC,
            release_manifest_digest=RELEASE_DIGEST,
            parent_evidence_digest="e" * 64,
        ),
    }


def _viewer_probe() -> dict:
    semantics = {
        "is-valid": {
            "capabilities": {
                "filter": False,
                "preview": True,
                "search": False,
                "statistics": False,
                "viewer": True,
            }
        },
        "info": {"config": public.DEFAULT_CONFIG_NAME, "row_count": 51},
        "size": {"config": public.DEFAULT_CONFIG_NAME, "row_count": 51},
        "splits": {"config": public.DEFAULT_CONFIG_NAME, "split_count": 1},
    }
    return {
        "bounded": True,
        "passed": True,
        "dataset_viewer_api_passed": True,
        "default_config": public.DEFAULT_CONFIG_NAME,
        "ia_only": False,
        "jurisdictions": list(public.SORTED_JURISDICTIONS),
        "manifest_binding": {
            "default_config": public.DEFAULT_CONFIG_NAME,
            "default_config_sha256": "5" * 64,
            "default_data_files": [
                {
                    "path": (
                        f"data/state_laws/sha256-{RELEASE_DIGEST}/"
                        "data/corpus/part-*.parquet"
                    ),
                    "split": "train",
                }
            ],
            "default_matched_artifact_count": 5,
            "default_matched_artifacts_sha256": "7" * 64,
            "expected_rows": 51,
            "jurisdictions_sha256": "6" * 64,
            "key_parity_sha256": "f" * 64,
            "manifest_default_config_sha256": "8" * 64,
            "manifest_default_data_files": [
                {"path": "data/corpus/part-*.parquet", "split": "train"}
            ],
            "manifest_digest": RELEASE_DIGEST,
            "release_prefix": f"data/state_laws/sha256-{RELEASE_DIGEST}",
        },
        "pinned_revision": PUBLIC,
        "responses": [
            {
                "endpoint": endpoint,
                "response_bytes": 1,
                "response_sha256": str(index) * 64,
                "semantic": semantics[endpoint],
                "status": 200,
                "x_revision": PUBLIC,
            }
            for index, endpoint in enumerate(
                ("is-valid", "info", "size", "splits"), start=1
            )
        ],
    } | _canary_provenance()


def _public_canary() -> dict:
    key_digest = "f" * 64
    provenance = _canary_provenance()
    receipt = {
        "schema": public.CANONICAL_CANARY_SCHEMA,
        "receipt_kind": public.CANONICAL_CANARY_KIND,
        "task_id": public.TASK_ID,
        "goal_id": public.GOAL_ID,
        "program_id": public.PROGRAM_ID,
        "producer": public.PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": public.DEFAULT_DATASET_REPO,
        "public_revision": PUBLIC,
        "public_sha": PUBLIC,
        "previous_public_pin": PREVIOUS,
        "staging_revision": STAGING,
        "final_manifest_digest": CANDIDATE_DIGEST,
        "release_manifest_digest": RELEASE_DIGEST,
        "plan_digest": "c" * 64,
        "policy_proof_digest": "d" * 64,
        "publication_receipt_digest": "e" * 64,
        **provenance,
        "downloaded": [
            {"relative_path": "manifest.json", "sha256": "1" * 64, "size_bytes": 1}
        ],
        "downloaded_bytes": 1,
        "downloaded_file_count": 1,
        "exact_descriptor_match": True,
        "viewer": _viewer_probe(),
        "key_sets": {
            "passed": True,
            "canonical_keys_sha256": key_digest,
            "families": {
                name: key_digest
                for name in ("embeddings", "bm25", "vectors", "graph", "adjacency")
            },
            **provenance,
        },
        "query_canaries": _queries(),
        "jurisdictions": list(public.SORTED_JURISDICTIONS),
        "jurisdiction_count": 51,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = receipt["content_digest"] = digest
    return public.check_canonical_public_canary_receipt(receipt)


def _benchmark() -> dict:
    canary = _public_canary()
    measurements = {
        "cold": {"bytes": 1, "shards": 1, "latency_ms": 1.0, "cache_hits": 0},
        "warm": {"bytes": 0, "shards": 1, "latency_ms": 1.0, "cache_hits": 1},
        "warm_cache_hit_ratio": 1.0,
        "recall": {"dense_at_k": 1.0, "fused_at_k": 1.0},
        "jurisdiction_skew": 0.0,
        "jurisdictions": list(bench.SORTED_JURISDICTIONS),
        "local_ordered_cids_sha256": "2" * 64,
        "public_ordered_cids_sha256": "2" * 64,
        "local_explanations_sha256": "3" * 64,
        "public_explanations_sha256": "3" * 64,
        "route_justified": True,
        "complete_family_downloaded": False,
        "repair_tasks": [],
        "measurement_source": probe.MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": "2026-08-29T12:00:00Z",
        "probe_bindings": probe.release_probe_bindings(
            repo_id=canary["dataset_repo_id"],
            revision=canary["public_revision"],
            release_manifest_digest=canary["release_manifest_digest"],
            parent_evidence_digest=canary["canonical_digest"],
        ),
    }
    return bench.build_canonical_public_benchmark_receipt(
        public_canary=canary, measurements=measurements
    )


def _pin_probes() -> dict:
    canary = _public_canary()
    return {
        "new": {
            "revision": PUBLIC,
            "readable": True,
            "queryable": True,
            "bounded": True,
            "fixture_only": False,
        },
        "previous": {
            "revision": PREVIOUS,
            "readable": True,
            "queryable": True,
            "bounded": True,
            "fixture_only": False,
        },
        "switch": {
            "to_previous": True,
            "back_to_new": True,
            "bounded": True,
            "recoverable": True,
            "deletion_performed": False,
            "remote_mutation_performed": False,
        },
        "board_diagnostics": {"blocked": True, "idle": True, "stale": True},
        "measurement_source": probe.MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": "2026-08-29T12:00:00Z",
        "probe_bindings": probe.dual_pin_probe_bindings(
            repo_id=canary["dataset_repo_id"],
            new_revision=PUBLIC,
            previous_revision=PREVIOUS,
            release_manifest_digest=RELEASE_DIGEST,
            parent_evidence_digest=canary["canonical_digest"],
        ),
    }


def _rollback() -> dict:
    canary = _public_canary()
    pin_probes = _pin_probes()
    receipt = {
        "schema": rollback.CANONICAL_REHEARSAL_SCHEMA,
        "receipt_kind": rollback.CANONICAL_REHEARSAL_KIND,
        "task_id": rollback.TASK_ID,
        "goal_id": rollback.GOAL_ID,
        "program_id": rollback.PROGRAM_ID,
        "producer": rollback.PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": rollback.DEFAULT_DATASET_REPO,
        "public_revision": PUBLIC,
        "public_sha": PUBLIC,
        "previous_public_pin": PREVIOUS,
        "rollback_target": PREVIOUS,
        "final_manifest_digest": CANDIDATE_DIGEST,
        "release_manifest_digest": RELEASE_DIGEST,
        "publication_receipt_digest": "e" * 64,
        "public_canary_digest": canary["canonical_digest"],
        "pin_probes": pin_probes,
        "measurement_source": pin_probes["measurement_source"],
        "externally_supplied": pin_probes["externally_supplied"],
        "observed_at": pin_probes["observed_at"],
        "probe_bindings": pin_probes["probe_bindings"],
        "both_pins_queryable": True,
        "legacy_configuration": {"explicit": True},
        "legacy_configuration_explicit": True,
        "rollback_bounded": True,
        "rollback_recoverable": True,
        "public_advertisement_changed": False,
        "docs": {"ok": True},
        "operators_can_diagnose_blocked_idle_stale_boards": True,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = receipt["content_digest"] = digest
    return rollback.check_canonical_rollback_rehearsal(receipt)


def _measurements() -> dict:
    canary = _public_canary()
    benchmark = _benchmark()
    rehearsal = _rollback()
    return {
        "source_receipts": {
            "passed": True,
            "reconciled_through_public_files": True,
            "count": 51,
            "jurisdictions": list(audit.SORTED_JURISDICTIONS),
            "digest": "4" * 64,
        },
        "timestamps": {
            "passed": True,
            "as_of_disclaimers_present": True,
            "observation_time_not_currentness": True,
            "acquisition_time_not_currentness": True,
        },
        "update_checkpoints": {
            "passed": True,
            "completion_basis": "source_frontier",
            "atomic_per_jurisdiction": True,
            "partial_promoted": False,
            "count": 51,
            "jurisdictions": list(audit.SORTED_JURISDICTIONS),
        },
        "manifests": {
            "passed": True,
            "agree": True,
            "remote_manifest_digest": RELEASE_DIGEST,
            "local_manifest_digest": RELEASE_DIGEST,
        },
        "upstream_changes": [
            {
                "jurisdiction": "DC",
                "classified_as_delta_work": True,
                "mixed_into_this_release": False,
                "reason": "future official-source observation",
            }
        ],
        "delta_refill_findings_bounded": True,
        "max_delta_findings": 51,
        "update_plan": audit.build_update_plan(),
        "measurement_source": probe.MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": "2026-08-29T12:00:00Z",
        "probe_bindings": probe.release_probe_bindings(
            repo_id=canary["dataset_repo_id"],
            revision=canary["public_revision"],
            release_manifest_digest=canary["release_manifest_digest"],
            parent_evidence_digest=rehearsal["canonical_digest"],
        ),
        "dependency_digests": {
            "public_benchmark": benchmark["canonical_digest"],
            "public_canary": canary["canonical_digest"],
            "rollback_rehearsal": rehearsal["canonical_digest"],
        },
    }


def _receipt() -> dict:
    return audit.build_canonical_post_publication_audit(
        public_canary=_public_canary(),
        public_benchmark=_benchmark(),
        rollback_rehearsal=_rollback(),
        measurements=_measurements(),
    )


def test_identity_help_and_read_only_source() -> None:
    assert audit.TASK_ID == "LCR-046"
    assert audit.DEPENDS_ON == ("LCR-043", "LCR-044", "LCR-045")
    assert audit.main(["--help"]) == 0
    source = Path(audit.__file__).read_text(encoding="utf-8")
    for forbidden in ("HfApi", "upload_folder", "authorize_and_mutate"):
        assert forbidden not in source


def test_canonical_audit_closes_all_board_acceptance() -> None:
    receipt = _receipt()
    assert audit.check_canonical_post_publication_audit(receipt) == receipt
    assert receipt["public_revision"] == PUBLIC
    assert receipt["no_contradiction_remains"] is True
    assert receipt["source_receipts"]["count"] == 51
    assert receipt["manifests"]["agree"] is True
    assert receipt["upstream_changes"][0]["classified_as_delta_work"] is True
    assert receipt["upstream_changes_mixed_into_release"] is False
    assert receipt["update_plan"]["preserves_exact_51"] is True
    assert receipt["update_plan"]["preserves_transactional_gates"] is True


def test_audit_builder_and_checker_require_first_party_provenance() -> None:
    unsealed = _measurements()
    unsealed.pop("probe_bindings")
    with pytest.raises(
        audit.PostPublicationContradictionError, match="internally measured"
    ):
        audit.build_canonical_post_publication_audit(
            public_canary=_public_canary(),
            public_benchmark=_benchmark(),
            rollback_rehearsal=_rollback(),
            measurements=unsealed,
        )

    receipt = _receipt()
    receipt.pop("measurement_source")
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = receipt["content_digest"] = digest
    with pytest.raises(
        audit.PostPublicationContradictionError, match="first-party provenance"
    ):
        audit.check_canonical_post_publication_audit(receipt)


def test_rollback_checker_rejects_omitted_first_party_provenance() -> None:
    receipt = _rollback()
    receipt.pop("observed_at")
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = receipt["content_digest"] = digest
    with pytest.raises(rollback.RehearsalMismatchError, match="first-party provenance"):
        rollback.check_canonical_rollback_rehearsal(receipt)


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda value: value["source_receipts"].update(count=50), audit.PostPublicationContradictionError),
        (
            lambda value: value["timestamps"].update(as_of_disclaimers_present=False),
            audit.PostPublicationContradictionError,
        ),
        (
            lambda value: value["manifests"].update(remote_manifest_digest="5" * 64),
            audit.PostPublicationContradictionError,
        ),
        (
            lambda value: value["upstream_changes"][0].update(
                classified_as_delta_work=False
            ),
            audit.PostPublicationDeltaError,
        ),
        (
            lambda value: value["update_plan"].update(
                preserves_transactional_gates=False
            ),
            audit.PostPublicationContradictionError,
        ),
    ],
)
def test_measurement_contradictions_fail_closed(mutator, error) -> None:
    measured = _measurements()
    mutator(measured)
    with pytest.raises(error):
        audit.validate_canonical_post_publication_measurements(
            measured, release_manifest_digest=RELEASE_DIGEST
        )


def test_dependency_pin_or_digest_drift_fails_closed() -> None:
    changed = copy.deepcopy(_benchmark())
    changed["public_revision"] = "6" * 40
    digest = canonical_no_self_field_digest(changed)
    changed["canonical_digest"] = changed["content_digest"] = digest
    with pytest.raises(bench.PublicBenchmarkError):
        audit.build_canonical_post_publication_audit(
            public_canary=_public_canary(),
            public_benchmark=changed,
            rollback_rehearsal=_rollback(),
            measurements=_measurements(),
        )


def test_receipt_tampering_fails_closed() -> None:
    changed = copy.deepcopy(_receipt())
    changed["no_contradiction_remains"] = False
    with pytest.raises(audit.PostPublicationContradictionError):
        audit.check_canonical_post_publication_audit(changed)


def test_injected_auditor_is_bound_to_exact_public_pin() -> None:
    calls: list[tuple[str, str]] = []

    def runner(repo_id: str, revision: str) -> dict:
        calls.append((repo_id, revision))
        return _measurements()

    receipt = audit.run_canonical_post_publication_audit(
        public_canary=_public_canary(),
        public_benchmark=_benchmark(),
        rollback_rehearsal=_rollback(),
        audit_runner=runner,
    )
    assert receipt["status"] == "passed"
    assert calls == [(audit.DEFAULT_DATASET_REPO, PUBLIC)]


def test_check_cli_is_read_only(tmp_path: Path) -> None:
    target = tmp_path / "post_publication_audit.json"
    target.write_text(json.dumps(_receipt()), encoding="utf-8")
    before = target.read_bytes()
    assert audit.main(["--check", "--report", str(target)]) == 0
    assert target.read_bytes() == before
    assert audit.main(["--check", "--write", "--report", str(target)]) != 0


def test_generation_cli_rejects_external_measurement_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    external = tmp_path / "operator-audit-measurements.json"
    external.write_text(json.dumps(_measurements()), encoding="utf-8")
    assert audit.main(["--measurements", str(external)]) == 1
    assert "external --measurements cannot authorize" in capsys.readouterr().err
