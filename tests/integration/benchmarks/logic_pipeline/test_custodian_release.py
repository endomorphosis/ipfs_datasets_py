from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import threading

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

import benchmarks.logic_pipeline.custodian_release as release
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.cases import (
    REPLACEMENT_HOLDOUT_PROTOCOL_KEYS,
    REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
    ReplacementHoldoutSeal,
    replacement_holdout_ledger_authority_cid,
)
from benchmarks.logic_pipeline.custodian_release import (
    G241_EXTERNAL_ARTIFACT_KEYS,
    G241_EXTERNAL_ARTIFACT_SET_SCHEMA_V1,
    G241_PARENT_KEYS,
    G241_PILOT_DECISION_SCHEMA_V1,
    G241_UPSTREAM_AUTHORITY_ROLES,
    G241_VALIDATOR_ATTESTATION_SCHEMA_V1,
    G241_VALIDATOR_SIGNED_PAYLOAD_SCHEMA_V1,
    CustodianReleaseError,
    G241CustodianReleaseRequestV1,
    G241CustodianTrustRootV1,
    G241ExternallyGovernedCustodianReleaseReceiptV1,
    G241G239ExternalProjectionV1,
    G241SourceDecisionIndexV1,
    G241SourceReplayResultV1,
    derive_g232_shortlist_from_validated_gates_v1,
    load_and_validate_g241_release_receipt_v1,
    load_g241_custodian_trust_root_v1,
    validate_g232_proposal_against_source_replay_v1,
)
from benchmarks.logic_pipeline.holdout_execution import (
    G232_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA,
    REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
    REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA,
    REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS,
    AuthorizedReplacementHoldoutPayload,
    G232ReplacementHoldoutAuthorization,
    HoldoutExecutionError,
    ReplacementHoldoutAccessReceipt,
    load_authorized_replacement_holdout,
    load_replacement_holdout_access_receipts,
)
from benchmarks.logic_pipeline.positive_gate_bundle import (
    G231_EVALUATED_CANDIDATE_IDS,
)
from benchmarks.logic_pipeline.replay_gate import g238_git_commit_cid


SOURCE_COMMIT = "1" * 40
GIT_EXECUTABLE = Path("/usr/bin/git")


def _cid(label: str) -> str:
    return cid_for_dag_json({"test_identity": label})


def _gate(label: str, **members: object) -> dict[str, object]:
    return {
        "complete": True,
        "passed": True,
        "status": "passed",
        "receipt_cid": _cid(label),
        **members,
    }


def _selection_sources() -> dict[str, object]:
    candidates = G231_EVALUATED_CANDIDATE_IDS
    semantic = _gate(
        "semantic",
        candidate_variant_ids=list(candidates),
        per_arm_metrics=[
            {
                "variant_id": variant_id,
                "semantic_quality_millionths": 900_000,
                "absolute_quality_passed": True,
                "complete": True,
                "metrics_cid": _cid(f"semantic-{variant_id}"),
            }
            for variant_id in ("A0", *candidates)
        ],
        holdout_accessed=False,
    )
    comparisons = [
        {
            "candidate_variant_id": candidate,
            "split": split,
            "cache_mode": cache,
            "scheduled_pair_count": 10,
            "measured_pair_count": 10,
            "net_verified_gain_count": 0,
            "baseline_only_verified_count": 0,
            "net_verified_delta": 0.0,
            "comparison_cid": _cid(
                f"efficacy-{candidate}-{split}-{cache}"
            ),
        }
        for candidate in candidates
        for split in ("pilot", "development")
        for cache in ("cold", "warm")
    ]
    efficacy = _gate(
        "efficacy",
        candidate_variant_ids=list(candidates),
        evidence={"comparisons": comparisons},
        holdout_accessed=False,
    )
    reliability = _gate(
        "reliability",
        candidate_variant_ids=list(candidates),
        holdout_accessed=False,
    )
    routing = _gate(
        "routing",
        candidate_variant_ids=list(candidates),
        holdout_accessed=False,
    )
    safety = _gate("safety", holdout_included=False)
    replay = _gate("replay", holdout_included=False)
    costs = [
        {
            "variant_id": variant_id,
            "metrics": {
                "wall_time_ms": (
                    70.0 if variant_id == "A1" else 100.0
                ),
                "model_calls": (
                    7.0 if variant_id == "A1" else 10.0
                ),
            },
        }
        for variant_id in ("A0", *candidates)
    ]
    pareto_rows = [
        {
            "variant_id": variant_id,
            "eligible": True,
            "safety_feasible": True,
            "on_frontier": variant_id in {"A0", "A1"},
            "dominated_by": (
                [] if variant_id in {"A0", "A1"} else ["A1"]
            ),
        }
        for variant_id in ("A0", *candidates)
    ]
    resources = _gate(
        "resources",
        candidate_variant_ids=list(candidates),
        cost_evidence=costs,
        pareto_evidence={
            "frontier_variant_ids": ["A0", "A1"],
            "candidates": pareto_rows,
        },
        holdout_included=False,
    )
    child_receipts = {
        "g235_semantic_quality": semantic["receipt_cid"],
        "g234_efficacy": efficacy["receipt_cid"],
        "g234_reliability": reliability["receipt_cid"],
        "g234_routing": routing["receipt_cid"],
        "g236_safety": safety["receipt_cid"],
        "g237_resource_statistics": resources["receipt_cid"],
        "g238_detached_replay": replay["receipt_cid"],
    }
    bundle = _gate(
        "g231",
        bundle_cid=_cid("g231-bundle"),
        candidate_variant_ids=list(candidates),
        child_gate_receipt_cids=child_receipts,
        source_recomputed=True,
        holdout_authorized=False,
        holdout_accessed=False,
        holdout_outcomes_inspected=False,
    )
    return {
        "g231_bundle": bundle,
        "semantic_quality_gate": semantic,
        "efficacy_gate": efficacy,
        "reliability_gate": reliability,
        "routing_gate": routing,
        "safety_gate": safety,
        "resource_statistics_gate": resources,
        "detached_replay_gate": replay,
    }


def _seal(
    access_ledger_path: Path | None = None,
) -> ReplacementHoldoutSeal:
    manifest_cid = cid_for_bytes(
        b"opaque synthetic manifest identity",
        codec="raw",
    )
    protocols = {
        key: _cid(f"protocol-{key}")
        for key in REPLACEMENT_HOLDOUT_PROTOCOL_KEYS
    }
    identity = {
        "schema": REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
        "sealed_manifest_cid": manifest_cid,
        "case_count": 2,
        "strata_counts": {"hard": 2},
        "protocol_cids": protocols,
        "access_ledger_authority_cid": (
            _cid("access-ledger-authority")
            if access_ledger_path is None
            else replacement_holdout_ledger_authority_cid(
                manifest_cid, access_ledger_path
            )
        ),
    }
    return ReplacementHoldoutSeal(
        **identity,
        seal_contract_cid=cid_for_dag_json(identity),
    )


def _pilot_decision(
    selection: dict[str, object] | object,
) -> dict[str, object]:
    selected = list(selection["selected_candidate_ids"])  # type: ignore[index]
    body = {
        "schema": G241_PILOT_DECISION_SCHEMA_V1,
        "g201_semantic_evidence_index_cid": _cid("g201"),
        "g202_freeze_cid": _cid("g202"),
        "g211_persisted_runtime_graph_cid": _cid("g211"),
        "g212_causal_resource_graph_cid": _cid("g212"),
        "g220_seal_contract_cid": _cid("g220"),
        "g231_positive_gate_bundle_cid": _cid("g231"),
        "shortlist_selection_cid": selection["selection_cid"],  # type: ignore[index]
        "selected_candidate_ids": selected,
        "authorized_variant_ids": ["A0", *selected],
        "complete": True,
        "passed": True,
        "holdout_accessed": False,
        "holdout_outcomes_inspected": False,
        "production_promotion_authorized": False,
        "source_recomputed": True,
    }
    return {**body, "pilot_decision_cid": cid_for_dag_json(body)}


def _proposal(
    decision: dict[str, object],
    seal: ReplacementHoldoutSeal,
    variants: list[str],
    *,
    source_commit: str = SOURCE_COMMIT,
) -> G232ReplacementHoldoutAuthorization:
    body = {
        "schema": G232_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA,
        "goal_id": "HSSL-G232",
        "pilot_artifact_cid": decision["pilot_decision_cid"],
        "seal_contract_cid": seal.seal_contract_cid,
        "sealed_manifest_cid": seal.sealed_manifest_cid,
        "protocol_cids": {
            key: seal.protocol_cids[key]
            for key in sorted(
                REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS
            )
        },
        "source_commit": source_commit,
        "authorized_variant_ids": variants,
        "cache_modes": ["cold", "warm"],
        "passed": True,
        "complete": True,
        "shortlist_frozen": True,
        "holdout_authorized": True,
        "outcomes_inspected": False,
        "tuning_permitted": False,
    }
    return G232ReplacementHoldoutAuthorization.from_dict(
        {
            **body,
            "authorization_cid": cid_for_dag_json(body),
        }
    )


def test_shortlist_is_derived_from_all_gate_sources_without_truncation() -> None:
    selection = derive_g232_shortlist_from_validated_gates_v1(
        **_selection_sources()
    )

    assert selection["selected_candidate_ids"] == ("A1",)
    assert selection["authorized_variant_ids"] == ("A0", "A1")
    assert selection["ranking_permitted"] is False
    assert selection["truncation_permitted"] is False
    assert selection["holdout_accessed"] is False
    assert len(selection["candidate_evidence"]) == len(
        G231_EVALUATED_CANDIDATE_IDS
    )


def test_one_to_four_arbitrary_arms_do_not_substitute_for_source_replay() -> None:
    selection = derive_g232_shortlist_from_validated_gates_v1(
        **_selection_sources()
    )
    decision = _pilot_decision(selection)
    seal = _seal()
    exact = _proposal(decision, seal, ["A0", "A1"])

    assert (
        validate_g232_proposal_against_source_replay_v1(
            proposal=exact,
            selection_evidence=selection,
            pilot_decision=decision,
            seal=seal,
            source_commit=SOURCE_COMMIT,
        ).authorization_cid
        == exact.authorization_cid
    )

    arbitrary = _proposal(decision, seal, ["A0", "A2"])
    with pytest.raises(
        CustodianReleaseError,
        match="deterministic source-derived",
    ):
        validate_g232_proposal_against_source_replay_v1(
            proposal=arbitrary,
            selection_evidence=selection,
            pilot_decision=decision,
            seal=seal,
            source_commit=SOURCE_COMMIT,
        )


def test_tampered_selection_or_pilot_identity_fails_closed() -> None:
    selection = dict(
        derive_g232_shortlist_from_validated_gates_v1(
            **_selection_sources()
        )
    )
    decision = _pilot_decision(selection)
    exact = _proposal(decision, _seal(), ["A0", "A1"])
    selection["selected_candidate_ids"] = ["A2"]

    with pytest.raises(CustodianReleaseError, match="CID changed"):
        validate_g232_proposal_against_source_replay_v1(
            proposal=exact,
            selection_evidence=selection,
            pilot_decision=decision,
            seal=_seal(),
            source_commit=SOURCE_COMMIT,
        )


def _upstream_authorities() -> dict[str, str]:
    return {
        role: _cid(f"upstream-{role}")
        for role in G241_UPSTREAM_AUTHORITY_ROLES
    }


def _source_index(
    current: object | None = None,
    *,
    access_ledger_authority_cid: str | None = None,
) -> G241SourceDecisionIndexV1:
    source_commit = (
        SOURCE_COMMIT
        if current is None
        else str(current.outer_commit)  # type: ignore[attr-defined]
    )
    return G241SourceDecisionIndexV1(
        source_commit=source_commit,
        source_commit_cid=g238_git_commit_cid(source_commit),
        source_tree_cid=(
            _cid("source-tree")
            if current is None
            else release.g241_git_tree_cid(  # type: ignore[attr-defined]
                current.outer_tree  # type: ignore[attr-defined]
            )
        ),
        recursive_gitlinks_cid=(
            _cid("gitlinks")
            if current is None
            else current.g240_recursive_gitlinks_cid  # type: ignore[attr-defined]
        ),
        run_plan_cid=_cid("run-plan"),
        capability_inventory_cid=_cid("capabilities"),
        environment_cid=_cid("environment"),
        namespace_identity_cids={
            "worktree": _cid("worktree"),
            "cache_policy": _cid("cache-policy"),
            "runtime_identity_policy": _cid("runtime-policy"),
            "execution_identities": _cid("execution-identities"),
            "runtime_orchestration_policy": _cid(
                "runtime-orchestration-policy"
            ),
            "runtime_namespace_policy_pilot": _cid(
                "runtime-namespace-policy-pilot"
            ),
            "runtime_namespace_policy_development": _cid(
                "runtime-namespace-policy-development"
            ),
            "runtime_namespace_evidence_pilot": _cid(
                "runtime-namespace-evidence-pilot"
            ),
            "runtime_namespace_evidence_development": _cid(
                "runtime-namespace-evidence-development"
            ),
            "source_orchestration_evidence_pilot": _cid(
                "source-orchestration-evidence-pilot"
            ),
            "source_orchestration_evidence_development": _cid(
                "source-orchestration-evidence-development"
            ),
        },
        upstream_authority_cids=_upstream_authorities(),
        parent_artifact_cids={
            key: _cid(f"parent-{key}") for key in G241_PARENT_KEYS
        },
        g211_batch_receipt_cids=(_cid("pilot-batch"), _cid("dev-batch")),
        g212_runtime_evidence_cids=tuple(
            sorted((_cid("runtime-a"), _cid("runtime-b")))
        ),
        shortlist_selection_cid=_cid("selection"),
        g232_pilot_decision_cid=_cid("decision"),
        access_ledger_authority_cid=(
            access_ledger_authority_cid or _cid("access")
        ),
    )


def test_source_index_requires_exact_parent_and_receipt_graphs() -> None:
    index = _source_index()
    assert tuple(index.parent_artifact_cids) == G241_PARENT_KEYS

    with pytest.raises(CustodianReleaseError, match="duplicated"):
        replace(
            index,
            g212_runtime_evidence_cids=(
                _cid("runtime-a"),
                _cid("runtime-a"),
            ),
            source_index_cid=None,
        )

    parents = dict(index.parent_artifact_cids)
    parents.pop("g211_persisted_runtime_graph")
    with pytest.raises(CustodianReleaseError, match="parent ledger"):
        replace(
            index,
            parent_artifact_cids=parents,
            source_index_cid=None,
        )


def test_source_replay_content_is_explicitly_non_authorizing() -> None:
    selection = derive_g232_shortlist_from_validated_gates_v1(
        **_selection_sources()
    )
    decision = _pilot_decision(selection)
    seal = _seal()
    proposal = _proposal(decision, seal, ["A0", "A1"])

    evidence = G241SourceReplayResultV1(
        source_index=_source_index(),
        selection_evidence=selection,
        pilot_decision=decision,
        authorization=proposal,
        external_artifact_cids={
            key: _cid(f"arbitrary-{key}")
            for key in G241_EXTERNAL_ARTIFACT_KEYS
        },
        parent_ledger_cid=_cid("arbitrary-parent-ledger"),
    )

    assert not hasattr(evidence, "release_authorized")
    assert "source_replay" not in inspect.signature(
        load_and_validate_g241_release_receipt_v1
    ).parameters


def _request(**overrides: object) -> G241CustodianReleaseRequestV1:
    artifacts = {
        key: _cid(f"request-artifact-{key}")
        for key in G241_EXTERNAL_ARTIFACT_KEYS
    }
    artifact_set_cid = cid_for_dag_json(
        {
            "schema": G241_EXTERNAL_ARTIFACT_SET_SCHEMA_V1,
            "ordered_artifact_cids": artifacts,
        }
    )
    seal_cid = _cid("seal")
    manifest_cid = cid_for_bytes(b"manifest", codec="raw")
    access_authority = _cid("access-authority")
    access_file_identity = _cid("access-file-identity")
    access_head = cid_for_dag_json(
        {
            "schema": release.G241_ACCESS_LEDGER_SNAPSHOT_SCHEMA_V1,
            "seal_contract_cid": seal_cid,
            "sealed_manifest_cid": manifest_cid,
            "access_ledger_authority_cid": access_authority,
            "event_count": 0,
            "last_receipt_cid": None,
            "ledger_file_identity_cid": access_file_identity,
        }
    )
    values: dict[str, object] = {
        "source_index_cid": _cid("source-index"),
        "source_commit": SOURCE_COMMIT,
        "source_tree_cid": _cid("source-tree"),
        "recursive_gitlinks_cid": _cid("recursive-gitlinks"),
        "source_identity_cid": _cid("source-identity"),
        "run_plan_cid": _cid("run-plan"),
        "parent_ledger_cid": _cid("parent-ledger"),
        "artifact_cids": artifacts,
        "artifact_set_cid": artifact_set_cid,
        "upstream_authority_cids": _upstream_authorities(),
        "g232_authorization_cid": _cid("authorization"),
        "seal_contract_cid": seal_cid,
        "sealed_manifest_cid": manifest_cid,
        "authorized_variant_ids": ("A0", "A1"),
        "g239_evaluation_cid": _cid("evaluation"),
        "g239_authority_cid": _cid("authority"),
        "g239_operational_receipt_cid": _cid("operational-receipt"),
        "g239_validator_claim_cid": _cid("validator-claim"),
        "g239_validator_attestation_cid": _cid(
            "validator-attestation"
        ),
        "g239_validator_key_id": _cid("validator-key"),
        "g239_observed_at": "2026-07-25T00:00:00+00:00",
        "g239_evaluated_at": "2026-07-25T00:01:00+00:00",
        "decision_producer_id": _cid("producer"),
        "external_validator_id": _cid("validator"),
        "custodian_id": _cid("custodian"),
        "executor_id": _cid("executor"),
        "trust_root_cid": _cid("trust-root"),
        "access_ledger_authority_cid": access_authority,
        "access_ledger_file_identity_cid": access_file_identity,
        "access_ledger_head_cid": access_head,
        "access_ledger_event_count": 0,
        "release_ledger_file_identity_cid": _cid(
            "release-file-identity"
        ),
        "ledger_sequence": 0,
        "previous_ledger_receipt_cid": _cid("genesis"),
    }
    values.update(overrides)
    return G241CustodianReleaseRequestV1(**values)  # type: ignore[arg-type]


def test_request_is_non_authorizing_and_rejects_ledger_activity_or_overlap() -> None:
    request = _request()
    assert request.to_dict()["release_authorized"] is False
    assert request.to_dict()["holdout_content_included"] is False

    with pytest.raises(CustodianReleaseError, match="invalidates"):
        _request(access_ledger_event_count=1)
    with pytest.raises(CustodianReleaseError, match="pairwise distinct"):
        _request(custodian_id=_cid("producer"))


def test_public_authorizers_expose_no_clock_or_activity_override() -> None:
    parameters = inspect.signature(
        release.authorize_g241_custodian_release_v1
    ).parameters
    assert "now" not in parameters
    assert "clock" not in parameters
    assert "pre_release_activity" not in parameters
    assert "g211_batch_sources" not in parameters


def test_custodian_release_public_exports_are_unique() -> None:
    assert len(release.__all__) == len(set(release.__all__))


def test_pinned_git_identity_binds_path_and_raw_executable(
    tmp_path: Path,
) -> None:
    copied_git = tmp_path / "configured-git"
    raw = GIT_EXECUTABLE.read_bytes()
    copied_git.write_bytes(raw)
    copied_git.chmod(0o755)

    expected = cid_for_dag_json(
        {
            "schema": release.G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1,
            "absolute_path": str(copied_git),
            "raw_executable_cid": cid_for_bytes(raw, codec="raw"),
        }
    )
    assert release.g241_git_executable_cid_v1(copied_git) == expected

    copied_git.write_bytes(raw + b"\n")
    copied_git.chmod(0o755)
    assert release.g241_git_executable_cid_v1(copied_git) != expected

    copied_git.chmod(0o777)
    with pytest.raises(CustodianReleaseError):
        release.g241_git_executable_cid_v1(copied_git)

    alias = tmp_path / "git-alias"
    alias.symlink_to(GIT_EXECUTABLE)
    with pytest.raises(CustodianReleaseError):
        release.g241_git_executable_cid_v1(alias)


def test_pinned_git_drops_ambient_injection_and_disables_fsmonitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _detached_repo(tmp_path / "repo")
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "malicious-fsmonitor"
    hook.write_text(
        "#!/bin/sh\n"
        f"printf invoked >> {marker}\n",
        encoding="utf-8",
    )
    hook.chmod(0o700)
    _run_git(repo, "config", "core.fsmonitor", str(hook))
    expected_commit = _run_git(repo, "rev-parse", "HEAD")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git_marker = tmp_path / "path-git-ran"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        f"printf invoked >> {fake_git_marker}\n"
        "exit 77\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o700)
    injected = {
        "PATH": str(fake_bin),
        "GIT_DIR": str(tmp_path / "foreign-git-dir"),
        "GIT_WORK_TREE": str(tmp_path / "foreign-worktree"),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "foreign-config"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": str(hook),
        "GIT_OBJECT_DIRECTORY": str(tmp_path / "foreign-objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(
            tmp_path / "foreign-alternates"
        ),
        "PYTHONPATH": str(tmp_path / "foreign-python"),
        "LD_LIBRARY_PATH": str(tmp_path / "foreign-libraries"),
        "LD_PRELOAD": str(tmp_path / "foreign-preload.so"),
    }
    for name, value in injected.items():
        monkeypatch.setenv(name, value)

    original_run = subprocess.run
    observed: list[tuple[list[str], dict[str, str], str]] = []

    def guarded_run(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[object]:
        environment = kwargs.get("env")
        executable = kwargs.get("executable")
        assert isinstance(environment, dict)
        assert isinstance(executable, str)
        observed.append((arguments, environment, executable))
        return original_run(arguments, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(release.subprocess, "run", guarded_run)
    git_cid = release.g241_git_executable_cid_v1(GIT_EXECUTABLE)
    current = release._inspect_current_source(
        repo,
        git_executable_path=GIT_EXECUTABLE,
        expected_git_executable_cid=git_cid,
    )

    assert current.outer_commit == expected_commit
    assert observed
    for arguments, environment, executable in observed:
        assert arguments[0] == str(GIT_EXECUTABLE)
        assert arguments[1] == "--no-replace-objects"
        assert arguments[2:8] == [
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "core.hooksPath=/dev/null",
        ]
        assert f"core.worktree={repo}" in arguments
        assert "core.symlinks=true" in arguments
        assert "core.fileMode=true" in arguments
        assert "core.ignoreCase=false" in arguments
        assert "core.attributesFile=/dev/null" in arguments
        assert "core.excludesFile=/dev/null" in arguments
        assert environment == dict(release._GIT_SAFE_ENV)
        for name, injected_value in injected.items():
            if name in environment:
                assert environment[name] != injected_value
        assert executable.startswith("/proc/self/fd/")
    assert not marker.exists()
    assert not fake_git_marker.exists()


@pytest.mark.parametrize(
    "index_flag",
    ("--assume-unchanged", "--skip-worktree"),
)
def test_current_source_rejects_index_hidden_tracked_change(
    tmp_path: Path,
    index_flag: str,
) -> None:
    repo = _detached_repo(tmp_path / "repo")
    _run_git(repo, "update-index", index_flag, "source.txt")
    (repo / "source.txt").write_text(
        "source changed behind the index\n",
        encoding="utf-8",
    )
    git_cid = release.g241_git_executable_cid_v1(GIT_EXECUTABLE)

    with pytest.raises(CustodianReleaseError, match="clean detached"):
        release._inspect_current_source(
            repo,
            git_executable_path=GIT_EXECUTABLE,
            expected_git_executable_cid=git_cid,
        )


def test_current_source_rejects_git_replacement_ref(
    tmp_path: Path,
) -> None:
    repo = _detached_repo(tmp_path / "repo")
    original = _run_git(repo, "rev-parse", "HEAD")
    _run_git(repo, "switch", "-q", "-c", "replacement-source")
    (repo / "source.txt").write_text("replacement source\n", encoding="utf-8")
    _run_git(repo, "add", "source.txt")
    _run_git(repo, "commit", "-q", "-m", "replacement source")
    replacement = _run_git(repo, "rev-parse", "HEAD")
    _run_git(repo, "checkout", "-q", "--detach", original)
    _run_git(repo, "replace", original, replacement)
    git_cid = release.g241_git_executable_cid_v1(GIT_EXECUTABLE)

    with pytest.raises(CustodianReleaseError, match="clean detached"):
        release._inspect_current_source(
            repo,
            git_executable_path=GIT_EXECUTABLE,
            expected_git_executable_cid=git_cid,
        )


def test_current_source_rejects_ignored_python_import(
    tmp_path: Path,
) -> None:
    repo = _detached_repo(tmp_path / "repo")
    _run_git(repo, "switch", "-q", "-c", "ignored-source-policy")
    (repo / ".gitignore").write_text("sitecustomize.py\n", encoding="utf-8")
    _run_git(repo, "add", ".gitignore")
    _run_git(repo, "commit", "-q", "-m", "ignore policy")
    _run_git(repo, "checkout", "-q", "--detach", "HEAD")
    (repo / "sitecustomize.py").write_text(
        "raise RuntimeError('must never import')\n",
        encoding="utf-8",
    )
    git_cid = release.g241_git_executable_cid_v1(GIT_EXECUTABLE)

    with pytest.raises(CustodianReleaseError, match="clean detached"):
        release._inspect_current_source(
            repo,
            git_executable_path=GIT_EXECUTABLE,
            expected_git_executable_cid=git_cid,
        )


def test_first_secure_file_creation_fsyncs_file_and_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "external" / "ledger.jsonl"
    destination.parent.mkdir(mode=0o700)
    observed_modes: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        observed_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(release.os, "fsync", recording_fsync)
    descriptor = release._open_secure_file(
        destination,
        repo_root=None,
        field_name="synthetic ledger",
        flags=os.O_RDWR | os.O_APPEND,
        create=True,
        private=True,
    )
    os.close(descriptor)

    assert len(observed_modes) == 2
    assert any(stat.S_ISREG(mode) for mode in observed_modes)
    assert any(stat.S_ISDIR(mode) for mode in observed_modes)


def test_external_projection_requires_exact_artifacts_and_authorities() -> None:
    artifacts = {
        key: _cid(f"artifact-{key}")
        for key in G241_EXTERNAL_ARTIFACT_KEYS
    }
    values = {
        "authority_cid": _cid("authority"),
        "requirement_cid": _cid("requirement"),
        "operational_receipt_cid": _cid("receipt"),
        "validator_claim_cid": _cid("validator-claim"),
        "validator_attestation_cid": _cid("validator-attestation"),
        "validator_key_id": _cid("validator-key"),
        "source_identity_cid": _cid("source"),
        "producer_id": _cid("producer"),
        "validator_id": _cid("validator"),
        "run_plan_cid": _cid("run-plan"),
        "parent_ledger_cid": _cid("parents"),
        "artifact_cids": artifacts,
        "artifact_set_cid": cid_for_dag_json(
            {
                "schema": G241_EXTERNAL_ARTIFACT_SET_SCHEMA_V1,
                "ordered_artifact_cids": artifacts,
            }
        ),
        "observed_at": "2026-07-25T00:00:00+00:00",
        "evaluated_at": "2026-07-25T00:01:00+00:00",
    }
    projection = G241G239ExternalProjectionV1(**values)
    assert projection.identity_payload()["valid"] is True

    incomplete = dict(values["artifact_cids"])
    incomplete.pop("g232_pilot_decision")
    with pytest.raises(CustodianReleaseError, match="exactly cover"):
        G241G239ExternalProjectionV1(
            **{**values, "artifact_cids": incomplete}
        )
    with pytest.raises(CustodianReleaseError, match="independent"):
        G241G239ExternalProjectionV1(
            **{**values, "validator_id": values["producer_id"]}
        )


def _trust_root(
    authority_cid: str,
    *,
    ledger_path: Path,
    private_key: Ed25519PrivateKey | None = None,
) -> tuple[G241CustodianTrustRootV1, Ed25519PrivateKey]:
    key = private_key or Ed25519PrivateKey.generate()
    public_key_base64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    validator_id = _cid("external-validator")
    validator_key_id = release._g241_validator_key_id(
        validator_id=validator_id,
        public_key_base64=public_key_base64,
    )
    monotonic_store_id = _cid("external-monotonic-store")
    monotonic_store_policy_cid = _cid(
        "external-monotonic-store-policy"
    )
    ledger_genesis_cid = _cid("genesis")
    return (
        G241CustodianTrustRootV1(
            g239_authority_cid=authority_cid,
            git_executable_path=str(GIT_EXECUTABLE),
            git_executable_cid=release.g241_git_executable_cid_v1(
                GIT_EXECUTABLE
            ),
            monotonic_store_id=monotonic_store_id,
            monotonic_store_policy_cid=monotonic_store_policy_cid,
            release_ledger_authority_cid=(
                release.g241_release_ledger_authority_cid_v1(
                    ledger_path=ledger_path,
                    ledger_genesis_cid=ledger_genesis_cid,
                    monotonic_store_id=monotonic_store_id,
                    monotonic_store_policy_cid=(
                        monotonic_store_policy_cid
                    ),
                )
            ),
            validator_id=validator_id,
            validator_key_id=validator_key_id,
            validator_public_key_base64=public_key_base64,
            custodian_id=_cid("custodian"),
            executor_id=_cid("executor"),
            ledger_genesis_cid=ledger_genesis_cid,
        ),
        key,
    )


def test_custodian_trust_root_requires_external_file_and_pin(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "source"
    repo.mkdir()
    authority = _cid("authority")
    root, _ = _trust_root(
        authority,
        ledger_path=tmp_path / "release.jsonl",
    )
    trust_path = tmp_path / "custodian-trust.json"
    trust_path.write_text(
        json.dumps(root.to_dict(), sort_keys=True),
        encoding="utf-8",
    )
    trust_path.chmod(0o600)

    loaded = load_g241_custodian_trust_root_v1(
        path=trust_path,
        trusted_trust_root_cid=root.trust_root_cid,
        repo_root=repo,
    )
    assert loaded == root
    with pytest.raises(CustodianReleaseError, match="out-of-band"):
        load_g241_custodian_trust_root_v1(
            path=trust_path,
            trusted_trust_root_cid=_cid("another-trust-root"),
            repo_root=repo,
        )

    alias_path = tmp_path / "hard-linked-trust.json"
    os.link(trust_path, alias_path)
    with pytest.raises(CustodianReleaseError, match="single-link"):
        load_g241_custodian_trust_root_v1(
            path=trust_path,
            trusted_trust_root_cid=root.trust_root_cid,
            repo_root=repo,
        )

    safe_directory = tmp_path / "safe"
    safe_directory.mkdir()
    safe_path = safe_directory / "trust.json"
    _write_external_json(safe_path, root.to_dict())
    alias_directory = tmp_path / "alias"
    alias_directory.symlink_to(safe_directory, target_is_directory=True)
    with pytest.raises(CustodianReleaseError, match="securely opened"):
        load_g241_custodian_trust_root_v1(
            path=alias_directory / "trust.json",
            trusted_trust_root_cid=root.trust_root_cid,
            repo_root=repo,
        )


def _run_git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _detached_repo(path: Path) -> Path:
    path.mkdir()
    _run_git(path, "init", "-q")
    _run_git(path, "config", "user.name", "G241 Test")
    _run_git(path, "config", "user.email", "g241@example.invalid")
    source = path / "source.txt"
    source.write_text("frozen source\n", encoding="utf-8")
    _run_git(path, "add", "source.txt")
    _run_git(path, "commit", "-q", "-m", "frozen source")
    _run_git(path, "checkout", "-q", "--detach", "HEAD")
    return path


def _write_external_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_dag_json_bytes(value))
    path.chmod(0o600)


def _operational_fixture(tmp_path: Path) -> dict[str, object]:
    repo = _detached_repo(tmp_path / "repo")
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    access_path = external / "access.jsonl"
    access_path.touch(mode=0o600)
    ledger_path = external / "release.jsonl"
    ledger_path.touch(mode=0o600)
    git_cid = release.g241_git_executable_cid_v1(GIT_EXECUTABLE)
    current = release._inspect_current_source(
        repo,
        git_executable_path=GIT_EXECUTABLE,
        expected_git_executable_cid=git_cid,
    )
    seal = _seal(access_path)
    selection = derive_g232_shortlist_from_validated_gates_v1(
        **_selection_sources()
    )
    decision = _pilot_decision(selection)
    authorization = _proposal(
        decision,
        seal,
        ["A0", "A1"],
        source_commit=current.outer_commit,
    )
    source_index = _source_index(
        current,
        access_ledger_authority_cid=(
            seal.access_ledger_authority_cid
        ),
    )
    artifacts = {
        key: _cid(f"operational-{key}")
        for key in G241_EXTERNAL_ARTIFACT_KEYS
    }
    artifacts["g220_replacement_holdout_seal"] = (
        seal.seal_contract_cid
    )
    artifacts["g232_authorization_proposal"] = (
        authorization.authorization_cid
    )
    artifacts["g232_pilot_decision"] = (
        authorization.pilot_artifact_cid
    )
    parent_ledger_cid = _cid("operational-parent-ledger")
    replay_evidence = G241SourceReplayResultV1(
        source_index=source_index,
        selection_evidence=selection,
        pilot_decision=decision,
        authorization=authorization,
        external_artifact_cids=artifacts,
        parent_ledger_cid=parent_ledger_cid,
    )
    artifact_set_cid = release._g241_artifact_set_cid(artifacts)
    producer_id = _cid("external-producer")
    validator_id = _cid("external-validator")
    private_key = Ed25519PrivateKey.generate()

    observed = datetime.now(timezone.utc)
    observed_at = observed.isoformat()
    source = {
        "schema": release.G239_EXTERNAL_SOURCE_SCHEMA,
        "outer_commit": current.outer_commit,
        "outer_tree": current.outer_tree,
        "clean": True,
        "recursive_gitlinks_complete": True,
        "recursive_gitlinks": [],
        "submodule_map_cid": current.submodule_map_cid,
        "source_identity_cid": current.source_identity_cid,
    }
    required_ids = sorted(
        release.g241_artifact_slot_cid(key)
        for key in G241_EXTERNAL_ARTIFACT_KEYS
    )
    requirement_body = {
        "schema": release.G239_EXTERNAL_REQUIREMENT_SCHEMA,
        "goal_id": release.G241_GOVERNED_GOAL_ID,
        "evidence_term": release.G241_GOVERNED_EVIDENCE_TERM,
        "source_identity_cid": current.source_identity_cid,
        "run_plan_cid": source_index.run_plan_cid,
        "parent_ledger_cid": parent_ledger_cid,
        "required_artifact_ids": required_ids,
        "expected_producer_id": producer_id,
        "expected_validator_id": validator_id,
    }
    requirement = {
        **requirement_body,
        "requirement_cid": cid_for_dag_json(requirement_body),
    }
    validator_claim_cid = release._g241_validator_claim_cid(
        validator_id=validator_id,
        source_identity_cid=current.source_identity_cid,
        run_plan_cid=source_index.run_plan_cid,
        parent_ledger_cid=parent_ledger_cid,
        artifact_set_cid=artifact_set_cid,
    )
    artifact_rows = sorted(
        (
            {
                "schema": release.G239_EXTERNAL_ARTIFACT_SCHEMA,
                "artifact_id": release.g241_artifact_slot_cid(key),
                "artifact_cid": artifacts[key],
            }
            for key in G241_EXTERNAL_ARTIFACT_KEYS
        ),
        key=lambda row: str(row["artifact_id"]),
    )
    operational_body = {
        "schema": release.G239_EXTERNAL_RECEIPT_SCHEMA,
        "goal_id": release.G241_GOVERNED_GOAL_ID,
        "evidence_term": release.G241_GOVERNED_EVIDENCE_TERM,
        "source": source,
        "run_plan_cid": source_index.run_plan_cid,
        "parent_ledger_cid": parent_ledger_cid,
        "artifacts": artifact_rows,
        "producer_id": producer_id,
        "validator_id": validator_id,
        "validator_receipt_cid": validator_claim_cid,
        "observed_at": observed_at,
        "fresh_until": (observed + timedelta(hours=1)).isoformat(),
        "status": "completed",
    }
    operational = {
        **operational_body,
        "receipt_cid": cid_for_dag_json(operational_body),
    }
    authority_body = {
        "schema": release.G239_EXTERNAL_AUTHORITY_SCHEMA,
        "requirements": [requirement],
        "receipts": [operational],
    }
    authority = {
        **authority_body,
        "authority_cid": cid_for_dag_json(authority_body),
    }
    trust_root, private_key = _trust_root(
        str(authority["authority_cid"]),
        ledger_path=ledger_path,
        private_key=private_key,
    )
    assert trust_root.validator_id == validator_id
    signed_payload = {
        "schema": G241_VALIDATOR_SIGNED_PAYLOAD_SCHEMA_V1,
        "authority_cid": authority["authority_cid"],
        "requirement_cid": requirement["requirement_cid"],
        "operational_receipt_cid": operational["receipt_cid"],
        "validator_id": validator_id,
        "validator_receipt_cid": validator_claim_cid,
        "source_identity_cid": current.source_identity_cid,
        "run_plan_cid": source_index.run_plan_cid,
        "parent_ledger_cid": parent_ledger_cid,
        "artifact_set_cid": artifact_set_cid,
        "observed_at": observed_at,
    }
    signature = private_key.sign(
        canonical_dag_json_bytes(signed_payload)
    )
    attestation_body = {
        "schema": G241_VALIDATOR_ATTESTATION_SCHEMA_V1,
        "signed_payload": signed_payload,
        "signed_payload_cid": cid_for_dag_json(signed_payload),
        "algorithm": "ed25519",
        "validator_key_id": trust_root.validator_key_id,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    attestation = {
        **attestation_body,
        "attestation_cid": cid_for_dag_json(attestation_body),
    }
    authority_path = external / "authority.json"
    attestation_path = external / "attestation.json"
    trust_path = external / "trust.json"
    _write_external_json(authority_path, authority)
    _write_external_json(attestation_path, attestation)
    _write_external_json(trust_path, trust_root.to_dict())

    projection = release._evaluate_g239_for_g241_v1(
        authority_path=authority_path,
        trusted_authority_cid=str(authority["authority_cid"]),
        validator_attestation_path=attestation_path,
        trusted_validator_attestation_cid=str(
            attestation["attestation_cid"]
        ),
        custodian_trust_root=trust_root,
        source_replay=replay_evidence,
        repo_root=repo,
        evaluated_at=observed,
        freshness_reference_at=observed,
    )
    access_descriptor = os.open(access_path, os.O_RDWR)
    try:
        access_head, access_count = (
            release._empty_access_ledger_snapshot(
                access_descriptor,
                seal=seal,
            )
        )
        access_file_identity_cid = (
            release._ledger_file_identity_cid(
                access_descriptor,
                ledger_role="replacement-access",
            )
        )
    finally:
        os.close(access_descriptor)
    ledger_descriptor = os.open(ledger_path, os.O_RDWR)
    try:
        release_file_identity_cid = release._ledger_file_identity_cid(
            ledger_descriptor,
            ledger_role="custodian-release",
        )
    finally:
        os.close(ledger_descriptor)
    request = G241CustodianReleaseRequestV1(
        source_index_cid=str(source_index.source_index_cid),
        source_commit=source_index.source_commit,
        source_tree_cid=source_index.source_tree_cid,
        recursive_gitlinks_cid=source_index.recursive_gitlinks_cid,
        source_identity_cid=projection.source_identity_cid,
        run_plan_cid=source_index.run_plan_cid,
        parent_ledger_cid=parent_ledger_cid,
        artifact_cids=artifacts,
        artifact_set_cid=artifact_set_cid,
        upstream_authority_cids=(
            source_index.upstream_authority_cids
        ),
        g232_authorization_cid=authorization.authorization_cid,
        seal_contract_cid=seal.seal_contract_cid,
        sealed_manifest_cid=seal.sealed_manifest_cid,
        authorized_variant_ids=authorization.authorized_variant_ids,
        g239_evaluation_cid=str(projection.evaluation_cid),
        g239_authority_cid=projection.authority_cid,
        g239_operational_receipt_cid=(
            projection.operational_receipt_cid
        ),
        g239_validator_claim_cid=projection.validator_claim_cid,
        g239_validator_attestation_cid=(
            projection.validator_attestation_cid
        ),
        g239_validator_key_id=projection.validator_key_id,
        g239_observed_at=projection.observed_at,
        g239_evaluated_at=projection.evaluated_at,
        decision_producer_id=projection.producer_id,
        external_validator_id=projection.validator_id,
        custodian_id=trust_root.custodian_id,
        executor_id=trust_root.executor_id,
        trust_root_cid=str(trust_root.trust_root_cid),
        access_ledger_authority_cid=(
            seal.access_ledger_authority_cid
        ),
        access_ledger_file_identity_cid=(
            access_file_identity_cid
        ),
        access_ledger_head_cid=access_head,
        access_ledger_event_count=access_count,
        release_ledger_file_identity_cid=(
            release_file_identity_cid
        ),
        ledger_sequence=0,
        previous_ledger_receipt_cid=trust_root.ledger_genesis_cid,
    )
    receipt = (
        G241ExternallyGovernedCustodianReleaseReceiptV1._from_request(
            request=request,
            recorded_at=observed,
        )
    )
    ledger_path.write_bytes(
        canonical_dag_json_bytes(receipt.to_dict()) + b"\n"
    )
    ledger_path.chmod(0o600)
    return {
        "repo": repo,
        "access_path": access_path,
        "ledger_path": ledger_path,
        "seal": seal,
        "authorization": authorization,
        "authority": authority,
        "authority_path": authority_path,
        "attestation": attestation,
        "attestation_path": attestation_path,
        "trust_root": trust_root,
        "trust_path": trust_path,
        "replay_evidence": replay_evidence,
        "receipt": receipt,
        "observed": observed,
        "private_key": private_key,
    }


def _consume_fixture(
    fixture: dict[str, object],
) -> G241ExternallyGovernedCustodianReleaseReceiptV1:
    receipt = fixture["receipt"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    authority = fixture["authority"]
    attestation = fixture["attestation"]
    trust_root = fixture["trust_root"]
    assert isinstance(authority, dict)
    assert isinstance(attestation, dict)
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    return load_and_validate_g241_release_receipt_v1(
        receipt_cid=str(receipt.receipt_cid),
        ledger_path=fixture["ledger_path"],  # type: ignore[arg-type]
        access_ledger_path=fixture["access_path"],  # type: ignore[arg-type]
        seal=fixture["seal"],  # type: ignore[arg-type]
        authorization=fixture["authorization"],  # type: ignore[arg-type]
        authority_path=fixture["authority_path"],  # type: ignore[arg-type]
        trusted_authority_cid=str(authority["authority_cid"]),
        validator_attestation_path=fixture[  # type: ignore[arg-type]
            "attestation_path"
        ],
        trusted_validator_attestation_cid=str(
            attestation["attestation_cid"]
        ),
        custodian_trust_root_path=fixture["trust_path"],  # type: ignore[arg-type]
        trusted_custodian_trust_root_cid=str(
            trust_root.trust_root_cid
        ),
        repo_root=fixture["repo"],  # type: ignore[arg-type]
    )


def test_durable_g241_consumer_validates_real_signed_temp_evidence(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)

    loaded = _consume_fixture(fixture)

    assert loaded.receipt_cid == fixture["receipt"].receipt_cid  # type: ignore[union-attr]
    assert loaded.access_ledger_event_count == 0
    assert loaded.g239_validator_attestation_cid == (
        fixture["attestation"]["attestation_cid"]  # type: ignore[index]
    )


class _PinnedTestCustodian:
    def __init__(
        self,
        *,
        custodian_id: str,
        expected_release_cid: str,
        payload: bytes,
    ) -> None:
        self.custodian_id = custodian_id
        self.expected_release_cid = expected_release_cid
        self.payload = payload
        self.calls = 0

    def release_sealed_manifest(
        self,
        sealed_manifest_path: Path,
        *,
        seal_contract_cid: str,
        authorization_cid: str,
        g241_release_receipt_cid: str,
        access_grant_receipt_cid: str,
    ) -> bytes:
        assert sealed_manifest_path.is_absolute()
        assert seal_contract_cid
        assert authorization_cid
        assert access_grant_receipt_cid
        assert g241_release_receipt_cid == self.expected_release_cid
        self.calls += 1
        return self.payload


def _g241_consumer_arguments(
    fixture: dict[str, object],
) -> dict[str, object]:
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    authority = fixture["authority"]
    attestation = fixture["attestation"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    assert isinstance(authority, dict)
    assert isinstance(attestation, dict)
    return {
        "receipt_cid": str(receipt.receipt_cid),
        "ledger_path": fixture["ledger_path"],
        "access_ledger_path": fixture["access_path"],
        "seal": fixture["seal"],
        "authorization": fixture["authorization"],
        "authority_path": fixture["authority_path"],
        "trusted_authority_cid": str(authority["authority_cid"]),
        "validator_attestation_path": fixture["attestation_path"],
        "trusted_validator_attestation_cid": str(
            attestation["attestation_cid"]
        ),
        "custodian_trust_root_path": fixture["trust_path"],
        "trusted_custodian_trust_root_cid": str(
            trust_root.trust_root_cid
        ),
        "repo_root": fixture["repo"],
        "purpose": "evaluation",
        "executor_id": trust_root.executor_id,
        "custodian_id": trust_root.custodian_id,
    }


def _g241_loader_arguments(
    fixture: dict[str, object],
    *,
    sealed_path: Path,
    custodian: _PinnedTestCustodian,
) -> dict[str, object]:
    consumer = _g241_consumer_arguments(fixture)
    return {
        "g241_release_receipt_cid": consumer["receipt_cid"],
        "g241_release_ledger_path": consumer["ledger_path"],
        "g241_authority_path": consumer["authority_path"],
        "trusted_g241_authority_cid": consumer[
            "trusted_authority_cid"
        ],
        "g241_validator_attestation_path": consumer[
            "validator_attestation_path"
        ],
        "trusted_g241_validator_attestation_cid": consumer[
            "trusted_validator_attestation_cid"
        ],
        "g241_custodian_trust_root_path": consumer[
            "custodian_trust_root_path"
        ],
        "trusted_g241_custodian_trust_root_cid": consumer[
            "trusted_custodian_trust_root_cid"
        ],
        "repo_root": consumer["repo_root"],
        "sealed_manifest_path": sealed_path,
        "tuning_worktree": consumer["repo_root"],
        "access_ledger_path": consumer["access_ledger_path"],
        "executor_id": consumer["executor_id"],
        "custodian": custodian,
    }


def test_signed_g241_receipt_drives_single_use_holdout_loader(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    authority = fixture["authority"]
    attestation = fixture["attestation"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    assert isinstance(authority, dict)
    assert isinstance(attestation, dict)
    sealed_bytes = b"opaque synthetic manifest identity"
    sealed_path = tmp_path / "external" / "sealed.bin"
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.chmod(0o600)
    custodian = _PinnedTestCustodian(
        custodian_id=trust_root.custodian_id,
        expected_release_cid=str(receipt.receipt_cid),
        payload=sealed_bytes,
    )
    arguments = {
        "g241_release_receipt_cid": str(receipt.receipt_cid),
        "g241_release_ledger_path": fixture["ledger_path"],
        "g241_authority_path": fixture["authority_path"],
        "trusted_g241_authority_cid": str(
            authority["authority_cid"]
        ),
        "g241_validator_attestation_path": fixture[
            "attestation_path"
        ],
        "trusted_g241_validator_attestation_cid": str(
            attestation["attestation_cid"]
        ),
        "g241_custodian_trust_root_path": fixture["trust_path"],
        "trusted_g241_custodian_trust_root_cid": str(
            trust_root.trust_root_cid
        ),
        "repo_root": fixture["repo"],
        "sealed_manifest_path": sealed_path,
        "tuning_worktree": fixture["repo"],
        "access_ledger_path": fixture["access_path"],
        "executor_id": trust_root.executor_id,
        "custodian": custodian,
    }

    payload = load_authorized_replacement_holdout(
        fixture["seal"],  # type: ignore[arg-type]
        fixture["authorization"],  # type: ignore[arg-type]
        **arguments,
    )

    assert payload.sealed_manifest_bytes == sealed_bytes
    assert payload.g241_release_receipt_cid == receipt.receipt_cid
    records = load_replacement_holdout_access_receipts(
        fixture["access_path"],  # type: ignore[arg-type]
        seal=fixture["seal"],  # type: ignore[arg-type]
    )
    assert [item.event for item in records] == [
        "access_granted",
        "manifest_released",
    ]
    assert {
        item.g241_release_receipt_cid for item in records
    } == {receipt.receipt_cid}
    assert custodian.calls == 1

    with pytest.raises(HoldoutExecutionError, match="premature"):
        load_authorized_replacement_holdout(
            fixture["seal"],  # type: ignore[arg-type]
            fixture["authorization"],  # type: ignore[arg-type]
            **arguments,
        )
    assert custodian.calls == 1


def test_custodian_object_is_untouched_until_grant_and_tombstone_are_durable(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    access_path = fixture["access_path"]
    ledger_path = fixture["ledger_path"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    assert isinstance(access_path, Path)
    assert isinstance(ledger_path, Path)
    sealed_bytes = b"opaque synthetic manifest identity"
    sealed_path = tmp_path / "external" / "sealed.bin"
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.chmod(0o600)

    class GuardedCustodian:
        def __init__(self) -> None:
            self.identity_reads = 0
            self.calls = 0

        @property
        def custodian_id(self) -> str:
            access_records = [
                json.loads(line)
                for line in access_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            release_records = [
                json.loads(line)
                for line in ledger_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            assert access_records[-1]["receipt"]["event"] == "access_granted"
            assert (
                release_records[-1]["schema"]
                == release.G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1
            )
            self.identity_reads += 1
            return trust_root.custodian_id

        def release_sealed_manifest(
            self,
            sealed_manifest_path: Path,
            **_: object,
        ) -> bytes:
            assert self.identity_reads == 1
            self.calls += 1
            return sealed_bytes

    custodian = GuardedCustodian()
    payload = load_authorized_replacement_holdout(
        fixture["seal"],  # type: ignore[arg-type]
        fixture["authorization"],  # type: ignore[arg-type]
        **_g241_loader_arguments(
            fixture,
            sealed_path=sealed_path,
            custodian=custodian,  # type: ignore[arg-type]
        ),
    )

    assert payload.sealed_manifest_bytes == sealed_bytes
    assert custodian.identity_reads == 1
    assert custodian.calls == 1


def test_consumption_tombstone_blocks_reuse_after_same_inode_access_rollback(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    access_path = fixture["access_path"]
    ledger_path = fixture["ledger_path"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    assert isinstance(access_path, Path)
    assert isinstance(ledger_path, Path)
    sealed_bytes = b"opaque synthetic manifest identity"
    sealed_path = tmp_path / "external" / "sealed.bin"
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.chmod(0o600)
    custodian = _PinnedTestCustodian(
        custodian_id=trust_root.custodian_id,
        expected_release_cid=str(receipt.receipt_cid),
        payload=sealed_bytes,
    )
    arguments = _g241_loader_arguments(
        fixture,
        sealed_path=sealed_path,
        custodian=custodian,
    )

    payload = load_authorized_replacement_holdout(
        fixture["seal"],  # type: ignore[arg-type]
        fixture["authorization"],  # type: ignore[arg-type]
        **arguments,
    )
    release_records = release._ledger_records(
        ledger_path.read_bytes(),
        genesis_cid=trust_root.ledger_genesis_cid,
    )
    assert len(release_records) == 2
    tombstone = release_records[-1]
    assert isinstance(
        tombstone, release.G241ReleaseConsumptionTombstoneV1
    )
    assert tombstone.release_receipt_cid == receipt.receipt_cid
    assert (
        tombstone.access_grant_receipt_cid
        == payload.grant_receipt.receipt_cid
    )
    assert (
        tombstone.access_ledger_file_identity_cid
        == receipt.access_ledger_file_identity_cid
    )
    assert (
        tombstone.monotonic_store_policy_cid
        == trust_root.monotonic_store_policy_cid
    )
    assert tombstone.previous_receipt_cid == receipt.receipt_cid

    before = access_path.stat()
    access_path.write_bytes(b"")
    after = access_path.stat()
    assert (before.st_dev, before.st_ino) == (
        after.st_dev,
        after.st_ino,
    )

    with pytest.raises(HoldoutExecutionError, match="premature"):
        load_authorized_replacement_holdout(
            fixture["seal"],  # type: ignore[arg-type]
            fixture["authorization"],  # type: ignore[arg-type]
            **arguments,
        )
    assert custodian.calls == 1
    durable = release._ledger_records(
        ledger_path.read_bytes(),
        genesis_cid=trust_root.ledger_genesis_cid,
    )
    assert isinstance(
        durable[-1], release.G241ReleaseConsumptionTombstoneV1
    )
    assert durable[-1].tombstone_cid == tombstone.tombstone_cid


def test_access_ledger_blocks_reuse_after_same_inode_tombstone_truncation(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    ledger_path = fixture["ledger_path"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    assert isinstance(ledger_path, Path)
    sealed_bytes = b"opaque synthetic manifest identity"
    sealed_path = tmp_path / "external" / "sealed.bin"
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.chmod(0o600)
    custodian = _PinnedTestCustodian(
        custodian_id=trust_root.custodian_id,
        expected_release_cid=str(receipt.receipt_cid),
        payload=sealed_bytes,
    )
    arguments = _g241_loader_arguments(
        fixture,
        sealed_path=sealed_path,
        custodian=custodian,
    )
    load_authorized_replacement_holdout(
        fixture["seal"],  # type: ignore[arg-type]
        fixture["authorization"],  # type: ignore[arg-type]
        **arguments,
    )
    first_record = ledger_path.read_bytes().splitlines(keepends=True)[0]
    before = ledger_path.stat()
    ledger_path.write_bytes(first_record)
    after = ledger_path.stat()
    assert (before.st_dev, before.st_ino) == (
        after.st_dev,
        after.st_ino,
    )

    with pytest.raises(HoldoutExecutionError, match="premature"):
        load_authorized_replacement_holdout(
            fixture["seal"],  # type: ignore[arg-type]
            fixture["authorization"],  # type: ignore[arg-type]
            **arguments,
        )
    assert custodian.calls == 1


def test_locked_g241_transaction_records_failure_before_unlock(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)

    with pytest.raises(RuntimeError, match="synthetic custody failure"):
        with release.consume_g241_release_for_access_v1(
            **_g241_consumer_arguments(fixture),  # type: ignore[arg-type]
        ) as transaction:
            records = release._parse_access_ledger(
                fixture["access_path"].read_bytes()  # type: ignore[union-attr]
            )
            assert [item.event for item in records] == [
                "access_granted"
            ]
            assert (
                records[0].receipt_cid
                == transaction.grant_receipt.receipt_cid
            )
            raise RuntimeError("synthetic custody failure")

    records = load_replacement_holdout_access_receipts(
        fixture["access_path"],  # type: ignore[arg-type]
        seal=fixture["seal"],  # type: ignore[arg-type]
    )
    assert [item.event for item in records] == [
        "access_granted",
        "custody_release_failed",
    ]


def test_concurrent_g241_loaders_allow_only_one_custodian_call(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    sealed_bytes = b"opaque synthetic manifest identity"
    sealed_path = tmp_path / "external" / "sealed.bin"
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.chmod(0o600)

    entered_custodian = threading.Event()
    permit_release = threading.Event()

    class BlockingCustodian(_PinnedTestCustodian):
        def release_sealed_manifest(
            self,
            sealed_manifest_path: Path,
            *,
            seal_contract_cid: str,
            authorization_cid: str,
            g241_release_receipt_cid: str,
            access_grant_receipt_cid: str,
        ) -> bytes:
            entered_custodian.set()
            if not permit_release.wait(timeout=5):
                raise RuntimeError("timed out waiting for test release")
            return super().release_sealed_manifest(
                sealed_manifest_path,
                seal_contract_cid=seal_contract_cid,
                authorization_cid=authorization_cid,
                g241_release_receipt_cid=g241_release_receipt_cid,
                access_grant_receipt_cid=access_grant_receipt_cid,
            )

    custodian = BlockingCustodian(
        custodian_id=trust_root.custodian_id,
        expected_release_cid=str(receipt.receipt_cid),
        payload=sealed_bytes,
    )
    arguments = _g241_loader_arguments(
        fixture,
        sealed_path=sealed_path,
        custodian=custodian,
    )

    def invoke_loader() -> AuthorizedReplacementHoldoutPayload:
        return load_authorized_replacement_holdout(
            fixture["seal"],  # type: ignore[arg-type]
            fixture["authorization"],  # type: ignore[arg-type]
            **arguments,
        )

    second_started = threading.Event()

    def invoke_second_loader() -> AuthorizedReplacementHoldoutPayload:
        second_started.set()
        return invoke_loader()

    pool = ThreadPoolExecutor(max_workers=2)
    first = pool.submit(invoke_loader)
    second = None
    try:
        assert entered_custodian.wait(timeout=5)
        during_custody = release._parse_access_ledger(
            fixture["access_path"].read_bytes()  # type: ignore[union-attr]
        )
        assert [item.event for item in during_custody] == [
            "access_granted"
        ]
        trust_root = fixture["trust_root"]
        assert isinstance(trust_root, G241CustodianTrustRootV1)
        release_records = release._ledger_records(
            fixture["ledger_path"].read_bytes(),  # type: ignore[union-attr]
            genesis_cid=trust_root.ledger_genesis_cid,
        )
        assert isinstance(
            release_records[-1],
            release.G241ReleaseConsumptionTombstoneV1,
        )
        assert (
            release_records[-1].access_grant_receipt_cid
            == during_custody[0].receipt_cid
        )

        second = pool.submit(invoke_second_loader)
        assert second_started.wait(timeout=5)
        with pytest.raises(TimeoutError):
            second.result(timeout=0.2)

        permit_release.set()
        payload = first.result(timeout=5)
        assert payload.sealed_manifest_bytes == sealed_bytes
        with pytest.raises(HoldoutExecutionError, match="premature"):
            second.result(timeout=5)
    finally:
        permit_release.set()
        pool.shutdown(wait=True)

    records = load_replacement_holdout_access_receipts(
        fixture["access_path"],  # type: ignore[arg-type]
        seal=fixture["seal"],  # type: ignore[arg-type]
    )
    assert sum(item.event == "access_granted" for item in records) == 1
    assert sum(item.event == "manifest_released" for item in records) == 1
    assert custodian.calls == 1


def test_noncooperating_source_change_cannot_record_manifest_success(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    receipt = fixture["receipt"]
    trust_root = fixture["trust_root"]
    repo = fixture["repo"]
    assert isinstance(
        receipt, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    assert isinstance(repo, Path)
    sealed_bytes = b"opaque synthetic manifest identity"
    sealed_path = tmp_path / "external" / "sealed.bin"
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.chmod(0o600)

    class DirtySourceCustodian(_PinnedTestCustodian):
        def release_sealed_manifest(
            self,
            sealed_manifest_path: Path,
            *,
            seal_contract_cid: str,
            authorization_cid: str,
            g241_release_receipt_cid: str,
            access_grant_receipt_cid: str,
        ) -> bytes:
            payload = super().release_sealed_manifest(
                sealed_manifest_path,
                seal_contract_cid=seal_contract_cid,
                authorization_cid=authorization_cid,
                g241_release_receipt_cid=g241_release_receipt_cid,
                access_grant_receipt_cid=access_grant_receipt_cid,
            )
            (repo / "source.txt").write_text(
                "noncooperating source mutation\n",
                encoding="utf-8",
            )
            return payload

    custodian = DirtySourceCustodian(
        custodian_id=trust_root.custodian_id,
        expected_release_cid=str(receipt.receipt_cid),
        payload=sealed_bytes,
    )
    with pytest.raises(HoldoutExecutionError, match="failed closed"):
        load_authorized_replacement_holdout(
            fixture["seal"],  # type: ignore[arg-type]
            fixture["authorization"],  # type: ignore[arg-type]
            **_g241_loader_arguments(
                fixture,
                sealed_path=sealed_path,
                custodian=custodian,
            ),
        )

    records = load_replacement_holdout_access_receipts(
        fixture["access_path"],  # type: ignore[arg-type]
        seal=fixture["seal"],  # type: ignore[arg-type]
    )
    assert [item.event for item in records] == [
        "access_granted",
        "custody_integrity_failure",
    ]
    assert not any(item.event == "manifest_released" for item in records)


@pytest.mark.parametrize("ledger_name", ["access_path", "ledger_path"])
def test_consumer_rejects_same_bytes_at_replacement_ledger_inode(
    tmp_path: Path,
    ledger_name: str,
) -> None:
    fixture = _operational_fixture(tmp_path)
    path = fixture[ledger_name]
    assert isinstance(path, Path)
    raw = path.read_bytes()
    displaced = path.with_suffix(".displaced")
    path.rename(displaced)
    path.write_bytes(raw)
    path.chmod(0o600)

    with pytest.raises(
        CustodianReleaseError,
        match="receipt differs|access-ledger head",
    ):
        _consume_fixture(fixture)


def test_consumer_rejects_in_place_release_ledger_truncation(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    ledger_path = fixture["ledger_path"]
    assert isinstance(ledger_path, Path)
    before = ledger_path.stat()
    ledger_path.write_bytes(b"")
    after = ledger_path.stat()
    assert (before.st_dev, before.st_ino) == (
        after.st_dev,
        after.st_ino,
    )

    with pytest.raises(CustodianReleaseError, match="durable current"):
        _consume_fixture(fixture)


def test_g239_rejects_tampered_validator_signature(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    attestation = dict(fixture["attestation"])  # type: ignore[arg-type]
    signature = bytearray(
        base64.b64decode(str(attestation["signature_base64"]))
    )
    signature[0] ^= 1
    attestation["signature_base64"] = base64.b64encode(
        bytes(signature)
    ).decode("ascii")
    body = {
        key: value
        for key, value in attestation.items()
        if key != "attestation_cid"
    }
    attestation["attestation_cid"] = cid_for_dag_json(body)
    _write_external_json(
        fixture["attestation_path"],  # type: ignore[arg-type]
        attestation,
    )
    authority = fixture["authority"]
    trust_root = fixture["trust_root"]
    assert isinstance(authority, dict)
    assert isinstance(trust_root, G241CustodianTrustRootV1)

    with pytest.raises(CustodianReleaseError, match="signature is invalid"):
        release._evaluate_g239_for_g241_v1(
            authority_path=fixture["authority_path"],  # type: ignore[arg-type]
            trusted_authority_cid=str(authority["authority_cid"]),
            validator_attestation_path=fixture[  # type: ignore[arg-type]
                "attestation_path"
            ],
            trusted_validator_attestation_cid=str(
                attestation["attestation_cid"]
            ),
            custodian_trust_root=trust_root,
            source_replay=fixture["replay_evidence"],
            repo_root=fixture["repo"],  # type: ignore[arg-type]
            evaluated_at=fixture["observed"],  # type: ignore[arg-type]
            freshness_reference_at=fixture["observed"],  # type: ignore[arg-type]
        )


def test_g239_rejects_authority_artifact_substitution(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    authority = json.loads(
        json.dumps(fixture["authority"])
    )
    operational = authority["receipts"][0]
    operational["artifacts"][0]["artifact_cid"] = _cid(
        "substituted-artifact"
    )
    operational_body = {
        key: value
        for key, value in operational.items()
        if key != "receipt_cid"
    }
    operational["receipt_cid"] = cid_for_dag_json(operational_body)
    authority_body = {
        key: value
        for key, value in authority.items()
        if key != "authority_cid"
    }
    authority["authority_cid"] = cid_for_dag_json(authority_body)
    _write_external_json(
        fixture["authority_path"],  # type: ignore[arg-type]
        authority,
    )
    trust_root, _ = _trust_root(
        str(authority["authority_cid"]),
        ledger_path=fixture["ledger_path"],  # type: ignore[arg-type]
        private_key=fixture["private_key"],  # type: ignore[arg-type]
    )
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)

    with pytest.raises(CustodianReleaseError, match="artifact CIDs differ"):
        release._evaluate_g239_for_g241_v1(
            authority_path=fixture["authority_path"],  # type: ignore[arg-type]
            trusted_authority_cid=str(authority["authority_cid"]),
            validator_attestation_path=fixture[  # type: ignore[arg-type]
                "attestation_path"
            ],
            trusted_validator_attestation_cid=str(
                attestation["attestation_cid"]
            ),
            custodian_trust_root=trust_root,
            source_replay=fixture["replay_evidence"],
            repo_root=fixture["repo"],  # type: ignore[arg-type]
            evaluated_at=fixture["observed"],  # type: ignore[arg-type]
            freshness_reference_at=fixture["observed"],  # type: ignore[arg-type]
        )


def test_consumer_rejects_any_prior_access_ledger_activity(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    seal = fixture["seal"]
    trust_root = fixture["trust_root"]
    assert isinstance(seal, ReplacementHoldoutSeal)
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    body = {
        "schema": REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA,
        "sequence": 0,
        "previous_receipt_cid": None,
        "event": "premature_access",
        "seal_contract_cid": seal.seal_contract_cid,
        "sealed_manifest_cid": seal.sealed_manifest_cid,
        "authorization_cid": None,
        "pilot_artifact_cid": None,
        "g241_release_receipt_cid": None,
        "purpose": "evaluation",
        "executor_id": trust_root.executor_id,
        "access_authorized": False,
        "manifest_released": False,
        "invalidates_seal": True,
    }
    receipt = ReplacementHoldoutAccessReceipt(
        **body,
        receipt_cid=cid_for_dag_json(body),
    )
    fixture["access_path"].write_bytes(  # type: ignore[union-attr]
        canonical_dag_json_bytes(
            {
                "schema": REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
                "receipt": receipt.to_dict(),
            }
        )
        + b"\n"
    )

    with pytest.raises(CustodianReleaseError, match="pre-release"):
        _consume_fixture(fixture)


def test_consumer_rejects_dirty_or_rebased_source(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    (fixture["repo"] / "source.txt").write_text(  # type: ignore[operator]
        "dirty source\n",
        encoding="utf-8",
    )

    with pytest.raises(CustodianReleaseError, match="clean detached"):
        _consume_fixture(fixture)


def test_release_ledger_rejects_nonmonotonic_clock(
    tmp_path: Path,
) -> None:
    fixture = _operational_fixture(tmp_path)
    first = fixture["receipt"]
    trust_root = fixture["trust_root"]
    assert isinstance(
        first, G241ExternallyGovernedCustodianReleaseReceiptV1
    )
    assert isinstance(trust_root, G241CustodianTrustRootV1)
    second_request = replace(
        first.as_request(),
        ledger_sequence=1,
        previous_ledger_receipt_cid=first.receipt_cid,
        request_cid=None,
    )
    second = (
        G241ExternallyGovernedCustodianReleaseReceiptV1._from_request(
            request=second_request,
            recorded_at=fixture["observed"],  # type: ignore[arg-type]
        )
    )
    raw = (
        canonical_dag_json_bytes(first.to_dict())
        + b"\n"
        + canonical_dag_json_bytes(second.to_dict())
        + b"\n"
    )

    with pytest.raises(CustodianReleaseError, match="monotonic"):
        release._ledger_records(
            raw,
            genesis_cid=trust_root.ledger_genesis_cid,
        )
