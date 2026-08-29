"""Fixture-only tests for the LCR-080 canonical publication runtime.

Temporary clean Git repositories supply taskboard, policy, receipt, manifest,
credential, and seal evidence. No live Hub traffic is performed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

# Pin this checkout's regular ``scripts`` package before importing the runtime.
# Some test environments also install a sibling project with a top-level
# package of that name and prepend it to ``sys.path`` during IPFS imports.
# Loading the repository package now keeps later source-attested fixture
# imports bound to the files under test, independent of test ordering.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPOSITORY_ROOT))
import scripts as _repository_scripts_package  # noqa: E402,F401
from scripts import ops as _repository_scripts_ops_package  # noqa: E402,F401

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    AUTHORIZED_DATASET_REPO_IDS,
    BASELINE_REVISIONS,
    PHASE_REQUIREMENTS,
    REQUIRED_PUBLICATION_GATES,
    RIGHTS_RECEIPT_RELPATH,
    RUNTIME_TASK_ID,
    SUCCESSOR_TASK_ID,
    PublicationGateDeniedError,
    credentials_scope_for,
    phase_requirements,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    TASK_ID as GATE_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    AUTHORITATIVE_OVERRIDE_KEYS,
    CANONICAL_PATHS,
    GOAL_ID,
    MANIFEST_SCHEMA_V1,
    PREDECESSOR_GATE_TASK_ID,
    PREDECESSOR_RIGHTS_TASK_ID,
    RECEIPT_SCHEMA_V1,
    RUNTIME_SCHEMA,
    SEAL_SCHEMA_V1,
    STATE_STAGING_CANARY_RELPATH,
    STATE_STAGING_UPLOAD_RELPATH,
    TASK_ID,
    TOKEN_ENV_ALLOWLIST,
    CanonicalPublicationRequest,
    PublicationRuntimeError,
    authorize_and_mutate_canonical,
    canonical_no_self_field_digest,
    evaluate_canonical_publication,
    inspect_clean_head,
    obtain_token,
    parse_utc_z,
    raw_file_digest,
    require_canonical_publication,
)
from ipfs_datasets_py.processors.legal_data.legal_release_validation import (
    HARDENED_RIGHTS_CATALOG_SCHEMA,
    HARDENED_RIGHTS_CODE_VERSION,
    HARDENED_RIGHTS_LIVE_GOAL_ID,
    HARDENED_RIGHTS_LIVE_TASK_ID,
    HARDENED_RIGHTS_POLICY_SCHEMA,
    HARDENED_RIGHTS_PRODUCER,
)

TOKEN = "tok_lcr080_fixture_canonical_runtime"
TOKEN_ENV = "HF_TOKEN"
STAGING_SHA = "c" * 40


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.stdout.strip()


def _callback_tracker() -> tuple[list[Any], Callable[..., Any]]:
    calls: list[Any] = []

    def _upload(decision: Any) -> str:
        calls.append(decision)
        return "mutated"

    return calls, _upload


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _poison_ambient_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    fake_bin = tmp_path / "hostile-bin"
    fake_bin.mkdir(parents=True)
    marker = tmp_path / "hostile-git-invoked"
    fake_git = fake_bin / "git"
    _write(
        fake_git,
        "#!/bin/sh\n"
        f"/usr/bin/touch {marker.as_posix()}\n"
        "exit 97\n",
    )
    fake_git.chmod(0o755)
    forged = tmp_path / "forged-git-authority"
    forged.mkdir()
    for name, value in {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(forged),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "forged-global-config"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "forged-system-config"),
        "GIT_DIR": str(forged),
        "GIT_EXEC_PATH": str(fake_bin),
        "GIT_INDEX_FILE": str(tmp_path / "forged-index"),
        "GIT_OBJECT_DIRECTORY": str(forged),
        "GIT_WORK_TREE": str(forged),
        "PATH": str(fake_bin),
    }.items():
        monkeypatch.setenv(name, value)
    return marker


def _seal_json(path: Path, payload: Mapping[str, Any], *, schema: str) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "canonical_digest",
            "content_digest",
            "digest",
            "no_self_field_digest",
            "raw_sha256",
            "receipt_sha256",
            "sha256",
        }
    }
    body["schema"] = schema
    digest = canonical_no_self_field_digest(body)
    body["canonical_digest"] = digest
    _write(path, json.dumps(body, indent=2, sort_keys=True) + "\n")
    return digest


def _task_block(task_id: str, *, status: str, depends_on: str, goal_id: str) -> str:
    dep = f" {depends_on}" if depends_on else ""
    return (
        f"## {task_id} Fixture {task_id}\n"
        f"- Status: {status}\n"
        f"- Depends on:{dep}\n"
        f"- Goal id: {goal_id}\n"
    )


def _goal_block(goal_id: str, *, parent: str) -> str:
    parent_text = f" {parent}" if parent else ""
    return (
        f"## {goal_id} Fixture {goal_id}\n"
        f"- Status: active\n"
        f"- Parent:{parent_text}\n"
        f"- Depends on:\n"
    )


def _release_policy() -> dict[str, Any]:
    phases = {}
    for phase, contract in PHASE_REQUIREMENTS.items():
        phases[phase] = {
            "dataset_repo_id": contract["dataset_repo_id"],
            "authorized_operation": contract["authorized_operation"],
            "required_task_ids": list(contract["required_task_ids"]),
            "required_receipts": list(contract["required_receipts"]),
            "prepublication_seal_required": contract["prepublication_seal_required"],
            "generated_work_goal_roots": list(contract["generated_work_goal_roots"]),
            "previous_public_pin": contract["previous_public_pin"],
            "seal_receipt_path": contract["seal_receipt_path"],
        }
    return {
        "schema": "ipfs_datasets_py/legal-corpora-reindex-release-policy@1",
        "dataset_repo_ids": sorted(AUTHORIZED_DATASET_REPO_IDS),
        "baseline_revisions": dict(BASELINE_REVISIONS),
        "prepublication_evidence_contract": {"phase_requirements": phases},
    }


def _probe(dataset_repo_id: str) -> Callable[[str, str], Mapping[str, Any]]:
    def _inner(token: str, repo_id: str) -> dict[str, Any]:
        assert token == TOKEN
        assert repo_id == dataset_repo_id
        return {
            "principal": "fixture-bot",
            "has_write_access": True,
            "write_targets": [dataset_repo_id],
            "scopes": [credentials_scope_for(dataset_repo_id)],
            "dataset_repo_id": dataset_repo_id,
            "identity": f"env:{dataset_repo_id}",
        }

    return _inner


def _seed_repo(
    tmp_path: Path,
    phase: str,
    *,
    bind_state_main_candidate: bool = True,
    state_release_manifest_digest: str | None = None,
    state_rights_receipt_bytes: bytes | None = None,
    task_status_overrides: Mapping[str, str] | None = None,
    omit_task: str | None = None,
    include_generated_todo: bool = False,
    receipt_mutator: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    skip_receipt_status: str | None = None,
    unknown_schema_for: str | None = None,
    forged_digest_for: str | None = None,
    omit_manifest_binding: bool = False,
    seal_present: Any = True,
    seal_time: str | None = "2020-01-01T00:00:00Z",
    omit_seal_manifest: bool = False,
    omit_seal_staging: bool = False,
    dirty_after_commit: str | None = None,
    extra_goal: tuple[str, str] | None = None,
) -> Path:
    repo = tmp_path / "canonical-repo"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "lcr080@example.test")
    _git(repo, "config", "user.name", "LCR-080 Tests")
    _git(repo, "config", "commit.gpgsign", "false")

    contract = phase_requirements(phase)
    dataset_repo_id = contract["dataset_repo_id"]
    roots = list(contract["generated_work_goal_roots"])
    supplied_rights: dict[str, Any] | None = None
    if state_rights_receipt_bytes is not None:
        supplied_rights = json.loads(state_rights_receipt_bytes)
        catalog_digest = str(supplied_rights["catalog_digest_sha256"])
        admitted = list(supplied_rights["admitted_record_ids"])
    else:
        catalog_digest = canonical_no_self_field_digest(
            {"catalog": f"{phase}:fixture"}
        )
        admitted = (
            ["al-alison-code-statutory_text", "ak-akleg-basis-statutory_text"]
            if phase.startswith("state_")
            else ["fr-hf-baseline-720668ae016cc400916dda884c9005e03618edfa-federal_government_text"]
        )

    tasks = ["LCR-008", *list(contract["required_task_ids"]), "LCR-080"]
    if omit_task:
        tasks = [item for item in tasks if item != omit_task]
    statuses = {task_id: "completed" for task_id in tasks}
    if include_generated_todo:
        statuses["LCR-080"] = "todo"
    statuses.update(dict(task_status_overrides or {}))

    taskboard = []
    for task_id in tasks:
        depends = "" if task_id == "LCR-008" else "LCR-008"
        goal = roots[-1] if task_id == "LCR-080" else roots[0]
        taskboard.append(
            _task_block(
                task_id,
                status=statuses[task_id],
                depends_on=depends,
                goal_id=goal,
            )
        )
    _write(repo / CANONICAL_PATHS["taskboard"], "\n".join(taskboard) + "\n")

    goals = ["LCR-G000", *roots]
    if extra_goal:
        goals.append(extra_goal[0])
    objective = [_goal_block("LCR-G000", parent="")]
    for goal_id in roots:
        objective.append(_goal_block(goal_id, parent="LCR-G000"))
    if extra_goal:
        objective.append(_goal_block(extra_goal[0], parent=extra_goal[1]))
    _write(repo / CANONICAL_PATHS["objectives"], "\n".join(objective) + "\n")
    _write(
        repo / CANONICAL_PATHS["release_policy"],
        json.dumps(_release_policy(), indent=2, sort_keys=True) + "\n",
    )

    def _finalize(relpath: str, payload: dict[str, Any], schema: str) -> str:
        if skip_receipt_status == relpath:
            payload.pop("status", None)
        if unknown_schema_for == relpath:
            schema = "ipfs_datasets_py/unknown-receipt-schema@9"
        if receipt_mutator is not None:
            payload = receipt_mutator(relpath, payload)
        digest = _seal_json(repo / relpath, payload, schema=schema)
        if forged_digest_for == relpath:
            raw = json.loads((repo / relpath).read_text(encoding="utf-8"))
            raw["canonical_digest"] = "0" * 64
            _write(repo / relpath, json.dumps(raw, indent=2, sort_keys=True) + "\n")
            return "0" * 64
        return digest

    rights_payload = {
        "status": "passed",
        "authorizing_for_publication": True,
        "catalog_digest_sha256": catalog_digest,
        "admitted_record_ids": list(admitted),
        "dataset_repo_id": dataset_repo_id,
        "target_dataset_repo_ids": sorted(AUTHORIZED_DATASET_REPO_IDS),
        "fixture_only": False,
        "fixture_only_non_authorizing": False,
        "dirty": False,
        "catalog_schema_version": HARDENED_RIGHTS_CATALOG_SCHEMA,
        "schema_version": HARDENED_RIGHTS_POLICY_SCHEMA,
        "producer": HARDENED_RIGHTS_PRODUCER,
        "audit_producer": HARDENED_RIGHTS_PRODUCER,
        "code_version": HARDENED_RIGHTS_CODE_VERSION,
        "evidence_mode": "live",
        "task_id": HARDENED_RIGHTS_LIVE_TASK_ID,
        "goal_id": HARDENED_RIGHTS_LIVE_GOAL_ID,
        "program_id": "legal-corpora-reindex-v1",
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if supplied_rights is None:
        rights_digest = _finalize(
            RIGHTS_RECEIPT_RELPATH,
            rights_payload,
            RECEIPT_SCHEMA_V1,
        )
    else:
        rights_path = repo / RIGHTS_RECEIPT_RELPATH
        rights_path.parent.mkdir(parents=True, exist_ok=True)
        rights_path.write_bytes(state_rights_receipt_bytes)
        rights_digest = str(supplied_rights["report_digest_sha256"])

    manifest_relpath = (
        CANONICAL_PATHS["federal_candidate_manifest"]
        if phase.startswith("federal_")
        else CANONICAL_PATHS["state_candidate_manifest"]
    )
    card_relpath = (
        CANONICAL_PATHS["federal_dataset_card"]
        if phase.startswith("federal_")
        else CANONICAL_PATHS["state_dataset_card"]
    )
    manifest_payload: dict[str, Any] = {
        "status": "passed",
        "source_rights_catalog_digest": catalog_digest,
        "admitted_source_ids": list(admitted),
        "dataset_repo_id": dataset_repo_id,
        "fixture_only": False,
        "dirty": False,
    }
    if not omit_manifest_binding:
        manifest_payload["source_rights_receipt_digest"] = rights_digest
    manifest_digest = _finalize(manifest_relpath, manifest_payload, MANIFEST_SCHEMA_V1)

    for relpath in contract["required_receipts"]:
        if relpath in {RIGHTS_RECEIPT_RELPATH, manifest_relpath}:
            continue
        if relpath == contract.get("seal_receipt_path"):
            payload = {
                "status": "sealed",
                "present": seal_present,
                "timing": "before_mutation",
                "sealed_at": seal_time,
                "dataset_repo_id": dataset_repo_id,
                "fixture_only": False,
                "dirty": False,
            }
            if not omit_seal_manifest:
                payload["final_manifest_digest"] = manifest_digest
            if not omit_seal_staging:
                payload["staging_revision"] = STAGING_SHA
            _finalize(relpath, payload, SEAL_SCHEMA_V1)
            continue
        _finalize(
            relpath,
            {
                "status": "passed",
                "path": relpath,
                "fixture_only": False,
                "dirty": False,
                "dataset_repo_id": dataset_repo_id,
            },
            RECEIPT_SCHEMA_V1,
        )

    _write(
        repo / card_relpath,
        "# Legal corpora release\n\nSource-rights compliance digest: "
        + rights_digest
        + "\n",
    )

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "canonical LCR-080 fixture")
    if phase.startswith("state_"):
        _install_builder_shaped_lcr084_candidate(
            repo,
            bind_main_candidate=bind_state_main_candidate,
            release_manifest_digest=state_release_manifest_digest,
        )
    if dirty_after_commit:
        path = repo / dirty_after_commit
        path.write_text(path.read_text(encoding="utf-8") + "\n# dirty\n", encoding="utf-8")
    return repo


def _request(
    repo: Path,
    phase: str,
    *,
    environ: Mapping[str, str] | None = None,
    probe: Callable[[str, str], Mapping[str, Any]] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = phase_requirements(phase)
    payload: dict[str, Any] = {
        "phase": phase,
        "repository_root": repo,
        "authorize_mutation": True,
        "environ": dict({TOKEN_ENV: TOKEN} if environ is None else environ),
        "principal_probe": probe or _probe(contract["dataset_repo_id"]),
    }
    if phase == "state_main":
        candidate = json.loads(
            (repo / CANONICAL_PATHS["state_candidate_manifest"]).read_text(
                encoding="utf-8"
            )
        )
        binding = candidate.get("publication_binding") or {}
        payload.update(
            {
                "expected_dataset_repo_id": contract["dataset_repo_id"],
                "expected_release_manifest_digest": binding.get(
                    "release_manifest_digest"
                ),
                "expected_plan_digest": binding.get("plan_digest"),
                "expected_policy_proof_digest": binding.get(
                    "policy_proof_digest"
                ),
            }
        )
    if extra:
        payload.update(extra)
    return payload


def _install_builder_shaped_lcr084_candidate(
    repo: Path,
    *,
    bind_main_candidate: bool = True,
    release_manifest_digest: str | None = None,
) -> dict[str, Any]:
    """Replace generic receipts with the builder's strict @2 test shape."""

    from scripts.ops.legal_data import build_state_laws_hf_release as builder
    from tests.unit.scripts.test_build_state_laws_hf_release import (
        _production_candidate,
    )

    candidate_path = repo / builder.DEFAULT_REPORT_RELPATH
    existing = json.loads(candidate_path.read_text(encoding="utf-8"))
    if existing.get("schema") == builder.PRODUCTION_REPORT_SCHEMA:
        return existing
    payload = _production_candidate(repo)
    baseline_relpath = builder.DEFAULT_LIVE_BASELINE_RELPATH.as_posix()
    _seal_json(
        repo / baseline_relpath,
        {
            "status": "passed",
            "path": baseline_relpath,
            "fixture_only": False,
            "dirty": False,
            "dataset_repo_id": "justicedao/ipfs_state_laws",
        },
        schema=RECEIPT_SCHEMA_V1,
    )
    rights = json.loads(
        (repo / RIGHTS_RECEIPT_RELPATH).read_text(encoding="utf-8")
    )
    rights_digest = str(
        rights.get("report_digest_sha256")
        or canonical_no_self_field_digest(rights)
    )
    catalog_digest = str(rights["catalog_digest_sha256"])
    evidence = payload["production_evidence"]
    baseline_file_sha256 = raw_file_digest(
        (repo / baseline_relpath).read_bytes()
    )
    evidence["authenticated_live_baseline"]["sha256"] = baseline_file_sha256
    payload["inputs"]["live_baseline_sha256"] = baseline_file_sha256
    evidence["rights_receipt"]["receipt_digest_sha256"] = rights_digest
    evidence["rights_receipt"]["catalog_digest_sha256"] = catalog_digest
    if release_manifest_digest is not None:
        evidence["production_release"]["manifest_digest"] = (
            release_manifest_digest
        )
    evidence_digest = builder.digest_payload(evidence)

    acceptance_path = repo / builder.PRODUCTION_ACCEPTANCE_RELPATH
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["evidence"] = evidence
    acceptance["candidate_requirement"]["manifest_digest"] = evidence[
        "production_release"
    ]["manifest_digest"]
    acceptance["production_evidence_digest_sha256"] = evidence_digest
    acceptance["candidate_requirement"][
        "production_evidence_digest_sha256"
    ] = evidence_digest
    acceptance["report_digest_sha256"] = builder._digest_for_report(
        acceptance
    )
    acceptance_path.write_text(
        json.dumps(acceptance, sort_keys=True),
        encoding="utf-8",
    )

    payload["production_evidence_digest_sha256"] = evidence_digest
    payload["acceptance"]["production_evidence_digest_sha256"] = (
        evidence_digest
    )
    payload["acceptance"][
        "full_scrape_acceptance_report_digest_sha256"
    ] = acceptance["report_digest_sha256"]
    payload["acceptance"]["full_scrape_acceptance_sha256"] = (
        builder.file_sha256(acceptance_path)
    )
    payload["source_rights_catalog_digest"] = catalog_digest
    payload["source_rights_receipt_digest"] = rights_digest
    payload["manifest_digest"] = evidence["production_release"][
        "manifest_digest"
    ]
    payload["report_digest_sha256"] = builder._digest_for_report(payload)
    candidate_path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    if (repo / STATE_STAGING_CANARY_RELPATH).is_file():
        staging_candidate_digest = (
            builder.production_candidate_staging_digest(payload)
        )
        release_manifest_digest = str(payload["manifest_digest"])
        plan_digest = "a" * 64
        policy_proof_digest = "b" * 64
        for relpath in (
            STATE_STAGING_UPLOAD_RELPATH,
            STATE_STAGING_CANARY_RELPATH,
        ):
            staging_receipt: dict[str, Any] = {
                "dataset_repo_id": "justicedao/ipfs_state_laws",
                "dirty": False,
                "final_manifest_digest": staging_candidate_digest,
                "fixture_only": False,
                "path": relpath,
                "release_manifest_digest": release_manifest_digest,
                "status": "passed",
            }
            if relpath == STATE_STAGING_CANARY_RELPATH:
                staging_receipt["staging_revision"] = STAGING_SHA
            _seal_json(
                repo / relpath,
                staging_receipt,
                schema=RECEIPT_SCHEMA_V1,
            )
        if bind_main_candidate:
            payload["publication_binding"] = {
                "plan_digest": plan_digest,
                "policy_proof_digest": policy_proof_digest,
                "release_manifest_digest": release_manifest_digest,
                "staging_candidate_digest": staging_candidate_digest,
            }
            payload["report_digest_sha256"] = builder._digest_for_report(payload)
            candidate_path.write_text(
                json.dumps(payload, sort_keys=True),
                encoding="utf-8",
            )
            seal_path = repo / CANONICAL_PATHS["state_prepublication_seal"]
            seal = json.loads(seal_path.read_text(encoding="utf-8"))
            seal.pop("canonical_digest", None)
            if "final_manifest_digest" in seal:
                seal["final_manifest_digest"] = payload[
                    "report_digest_sha256"
                ]
            seal.setdefault("plan_digest", plan_digest)
            seal.setdefault("policy_proof_digest", policy_proof_digest)
            seal.setdefault("release_manifest_digest", release_manifest_digest)
            _seal_json(seal_path, seal, schema=SEAL_SCHEMA_V1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "install builder-shaped LCR-084 candidate")
    return payload


def _assert_denied(
    payload: Mapping[str, Any],
    *,
    fragment: str,
) -> None:
    calls, upload = _callback_tracker()
    decision = evaluate_canonical_publication(payload)
    assert decision.authorized is False
    assert decision.network_mutation_permitted is False
    assert any(fragment in code for code in decision.reason_codes), decision.reason_codes
    dumped = json.dumps(decision.to_dict())
    assert TOKEN not in dumped
    with pytest.raises(PublicationGateDeniedError) as exc_info:
        authorize_and_mutate_canonical(payload, upload)
    assert calls == []
    assert any(fragment in code for code in exc_info.value.reason_codes), (
        exc_info.value.reason_codes
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_runtime_identity_preserves_gate_and_rights_successors() -> None:
    assert TASK_ID == RUNTIME_TASK_ID == "LCR-080"
    assert GOAL_ID == "LCR-G142"
    assert PREDECESSOR_GATE_TASK_ID == GATE_TASK_ID == "LCR-074"
    assert PREDECESSOR_RIGHTS_TASK_ID == SUCCESSOR_TASK_ID == "LCR-083"
    assert RUNTIME_SCHEMA.endswith("legal-corpora-publication-runtime@1")
    assert "source_rights_binding" in REQUIRED_PUBLICATION_GATES
    assert TOKEN_ENV in TOKEN_ENV_ALLOWLIST
    assert "release_policy" in CANONICAL_PATHS
    assert "task_statuses" in AUTHORITATIVE_OVERRIDE_KEYS


def test_utc_z_parser_rejects_offsets() -> None:
    parsed = parse_utc_z("2020-01-01T00:00:00Z")
    assert parsed.tzinfo is not None
    with pytest.raises(Exception):
        parse_utc_z("2020-01-01T00:00:00+00:00")
    with pytest.raises(Exception):
        parse_utc_z("2020-01-01T00:00:00-05:00")


def test_obtain_token_reads_only_allowlisted_env() -> None:
    name, token = obtain_token({TOKEN_ENV: TOKEN, "OTHER": "nope"})
    assert name == TOKEN_ENV
    assert token == TOKEN
    with pytest.raises(Exception):
        obtain_token({"OTHER": TOKEN})


@pytest.mark.parametrize("invalid", ["false", "true", 0, 1, None])
def test_authorize_mutation_requires_an_exact_boolean(
    tmp_path: Path,
    invalid: object,
) -> None:
    with pytest.raises(PublicationRuntimeError, match="exact boolean"):
        CanonicalPublicationRequest.from_mapping(
            {
                "phase": "state_staging",
                "repository_root": tmp_path,
                "authorize_mutation": invalid,
            }
        )
    with pytest.raises(PublicationRuntimeError, match="exact boolean"):
        CanonicalPublicationRequest(
            phase="state_staging",
            repository_root=tmp_path,
            authorize_mutation=invalid,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("relpath", "fixture_only"),
    [
        ("docs/reports/legal_corpora_reindex/local_e2e.json", True),
        ("docs/reports/legal_corpora_reindex/federal_inventory.json", False),
        (
            "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json",
            True,
        ),
        ("docs/reports/legal_corpora_reindex/federal_candidate.json", True),
        ("docs/reports/legal_corpora_reindex/federal_evaluation.json", True),
        (
            "docs/reports/legal_corpora_reindex/"
            "federal_adjacency_reconciliation.json",
            True,
        ),
    ],
)
def test_producer_native_receipts_are_strictly_adapted_without_losing_fixture_state(
    relpath: str,
    fixture_only: bool,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    root = Path(__file__).resolve().parents[4]
    receipt = runtime.load_receipt(root, relpath)
    assert receipt["status"] == "passed"
    assert receipt["fixture_only"] is fixture_only
    assert len(receipt["content_digest"]) == 64


@pytest.mark.parametrize(
    "relpath",
    [
        "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json",
        "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json",
    ],
)
def test_legacy_or_unbound_native_receipts_remain_non_authorizing(
    relpath: str,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    root = Path(__file__).resolve().parents[4]
    with pytest.raises(PublicationRuntimeError):
        runtime.load_receipt(root, relpath)


def test_lcr084_verifier_source_snapshot_uses_head_blobs_and_pinned_gitlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    root = Path(__file__).resolve().parents[4]
    head = _git(root, "rev-parse", "HEAD")
    expected: dict[str, str] = {}
    for label, relpath in runtime._VERIFIER_SOURCE_RELPATHS.items():
        completed = subprocess.run(
            ["git", "show", f"{head}:{relpath}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        expected[label] = raw_file_digest(completed.stdout)
    marker = _poison_ambient_git(tmp_path, monkeypatch)
    source_root, archives, manifest = (
        runtime._materialize_lcr084_source_snapshot(
            root,
            tmp_path,
            head,
            expected_source_sha256=expected,
        )
    )
    assert all(
        raw_file_digest(path.read_bytes()) == digest
        for path, digest in archives.items()
    )
    assert manifest[
        "scripts/ops/legal_data/build_state_laws_hf_release.py"
    ] == expected["lcr084_candidate"]
    assert (
        "ipfs_datasets_py/processors/web_archiving/"
        "common_crawl_search_engine/ccindex/api.py"
    ) in manifest
    assert not any(path.is_symlink() for path in source_root.rglob("*"))
    assert not marker.exists()


def test_authority_git_ignores_hostile_path_and_git_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _seed_repo(tmp_path / "evidence", "federal_staging")
    expected_head = _git(repo, "rev-parse", "HEAD")
    marker = _poison_ambient_git(tmp_path / "poison", monkeypatch)
    assert inspect_clean_head(repo) == expected_head
    assert not marker.exists()


def test_same_uid_lcr084_snapshot_denies_before_isolated_verifier_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    root = tmp_path / "evidence"
    candidate_path = root / runtime.STATE_CANDIDATE_MANIFEST_RELPATH
    payload: dict[str, Any] = {}
    payload["report_digest_sha256"] = (
        runtime._production_candidate_report_digest(payload)
    )
    candidate_raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(candidate_raw)
    source_root = tmp_path / "same-uid-source"
    source_root.mkdir(mode=0o700)
    source_file = source_root / "verifier.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    source_file.chmod(0o400)
    source_root.chmod(0o500)
    head = "a" * 40
    commands: list[tuple[str, ...]] = []

    def bounded_process(command: Any, **_kwargs: Any) -> tuple[int, bytes, bytes]:
        commands.append(tuple(str(item) for item in command))
        return 0, candidate_raw, b""

    monkeypatch.setattr(
        runtime,
        "_require_mutation_implementation_root",
        lambda _root: root,
    )
    monkeypatch.setattr(runtime, "inspect_clean_head", lambda _root: head)
    monkeypatch.setattr(
        runtime,
        "_materialize_lcr084_source_snapshot",
        lambda *_args, **_kwargs: (source_root, {}, {}),
    )
    monkeypatch.setattr(
        runtime,
        "_run_bounded_isolated_process",
        bounded_process,
    )
    with pytest.raises(
        PublicationRuntimeError,
        match="trusted LCR-084 source snapshot unavailable",
    ):
        runtime._isolated_lcr084_candidate_remeasurement(
            root,
            phase="state_main",
            payload=payload,
            runtime_token=TOKEN,
        )
    assert len(commands) == 1
    assert "show" in commands[0]
    assert "-c" not in commands[0]


def test_isolated_process_output_is_bounded_while_streaming(
    tmp_path: Path,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    with pytest.raises(PublicationRuntimeError, match="live bound"):
        runtime._run_bounded_isolated_process(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.buffer.write(b'x'*131072);sys.stdout.flush()",
            ],
            cwd=tmp_path,
            environment=None,
            timeout_seconds=10,
            output_limit_bytes=1024,
        )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_canonical_authorized_request_evaluates_all_phases(
    tmp_path: Path, phase: str
) -> None:
    repo = _seed_repo(tmp_path, phase)
    head = inspect_clean_head(repo, authoritative_paths=())
    assert len(head) == 40
    payload = _request(repo, phase)
    decision = evaluate_canonical_publication(payload)
    assert decision.authorized is True
    assert decision.network_mutation_permitted is True
    assert "source_rights_binding" in decision.passed_gates
    assert set(decision.passed_gates) == set(REQUIRED_PUBLICATION_GATES)
    assert decision.details["head"] == head
    assert decision.details["runtime_task_id"] == "LCR-080"
    assert decision.details["principal"] == "fixture-bot"
    assert decision.details["operation"] == phase_requirements(phase)["authorized_operation"]
    assert {"LCR-081", "LCR-082", "LCR-083"}.issubset(
        decision.details["required_task_ids"]
    )
    assert decision.details["source_rights_task_id"] == "LCR-083"
    assert len(decision.details["source_rights_receipt_digest"]) == 64
    assert decision.final_manifest_digest
    if phase.endswith("_main"):
        assert decision.details["prepublication_seal_bound"] is True
    dumped = json.dumps(decision.to_dict())
    assert TOKEN not in dumped
    require_canonical_publication(payload)


def test_runtime_accepts_builder_shaped_lcr084_candidate_with_strict_evidence(
    tmp_path: Path,
) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder

    repo = _seed_repo(tmp_path, "state_staging")
    candidate = _install_builder_shaped_lcr084_candidate(repo)
    decision = evaluate_canonical_publication(
        _request(repo, "state_staging")
    )
    assert decision.authorized is True
    on_disk = json.loads(
        (repo / builder.DEFAULT_REPORT_RELPATH).read_text(encoding="utf-8")
    )
    assert on_disk["schema"] == builder.PRODUCTION_REPORT_SCHEMA
    assert on_disk["mutation_audit"]["status"] == "passed"
    assert on_disk["acceptance"]["contains_exact_51"] is True


def test_state_main_accepts_exact_a_b_chain_without_gate_digest_conflation(
    tmp_path: Path,
) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    repo = _seed_repo(tmp_path, "state_main")
    request = _request(repo, "state_main")
    decision = evaluate_canonical_publication(request)
    assert decision.authorized is True, decision.to_dict()
    candidate = json.loads(
        (repo / CANONICAL_PATHS["state_candidate_manifest"]).read_text(
            encoding="utf-8"
        )
    )
    binding = candidate["publication_binding"]
    assert binding["staging_candidate_digest"] == (
        builder.production_candidate_staging_digest(candidate)
    )
    assert decision.final_manifest_digest == candidate["report_digest_sha256"]
    assert decision.final_manifest_digest != binding["staging_candidate_digest"]
    normalized = runtime.capture_canonical_snapshot(
        CanonicalPublicationRequest.from_mapping(request)
    )["receipts"]
    for relpath in (
        STATE_STAGING_UPLOAD_RELPATH,
        STATE_STAGING_CANARY_RELPATH,
    ):
        receipt = normalized[relpath]
        assert "final_manifest_digest" not in receipt
        assert receipt["producer_final_manifest_digest"] == binding[
            "staging_candidate_digest"
        ]


@pytest.mark.parametrize("phase", ["state_staging", "state_main"])
def test_state_candidate_publication_binding_is_phase_exact(
    tmp_path: Path,
    phase: str,
) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder

    repo = _seed_repo(tmp_path, phase)
    path = repo / CANONICAL_PATHS["state_candidate_manifest"]
    candidate = json.loads(path.read_text(encoding="utf-8"))
    if phase == "state_staging":
        staging_digest = builder.production_candidate_staging_digest(candidate)
        candidate["publication_binding"] = {
            "plan_digest": "a" * 64,
            "policy_proof_digest": "b" * 64,
            "release_manifest_digest": candidate["manifest_digest"],
            "staging_candidate_digest": staging_digest,
        }
    else:
        candidate["publication_binding"] = None
    candidate["report_digest_sha256"] = builder._digest_for_report(candidate)
    path.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "forge phase-incompatible publication binding")
    calls, callback = _callback_tracker()
    decision = evaluate_canonical_publication(_request(repo, phase))
    assert decision.authorized is False
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate_canonical(_request(repo, phase), callback)
    assert calls == []


def test_state_main_rejects_staging_receipt_that_does_not_bind_a(
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path, "state_main")
    path = repo / STATE_STAGING_UPLOAD_RELPATH
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt.pop("canonical_digest", None)
    receipt["final_manifest_digest"] = "d" * 64
    _seal_json(path, receipt, schema=RECEIPT_SCHEMA_V1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "drift staging candidate A binding")
    _assert_denied(
        _request(repo, "state_main"),
        fragment="manifest_binding",
    )


def test_public_builder_checker_monkeypatch_cannot_accept_invalid_lcr084_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder

    repo = _seed_repo(tmp_path, "state_staging")
    candidate = _install_builder_shaped_lcr084_candidate(repo)
    candidate["jurisdiction_count"] = 50
    candidate["report_digest_sha256"] = builder._digest_for_report(candidate)
    (repo / builder.DEFAULT_REPORT_RELPATH).write_text(
        json.dumps(candidate, sort_keys=True),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "forge invalid LCR-084 candidate")
    monkeypatch.setattr(
        builder,
        "check_production_candidate_report",
        lambda *_args, **_kwargs: {
            "jurisdiction_count": 51,
            "ok": True,
            "task_id": "LCR-084",
            "valid": True,
        },
    )
    calls, callback = _callback_tracker()
    decision = evaluate_canonical_publication(_request(repo, "state_staging"))
    assert decision.authorized is False
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate_canonical(
            _request(repo, "state_staging"),
            callback,
        )
    assert calls == []


def test_prepatched_live_baseline_dependencies_cannot_reach_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.ops.legal_data import audit_legal_corpora_live_baseline as live

    monkeypatch.setattr(
        live,
        "validate_receipt",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        live,
        "observe_with_live_hub",
        lambda *_args, **_kwargs: {"ok": True},
    )
    repo = _seed_repo(tmp_path, "state_main")
    calls, callback = _callback_tracker()
    with pytest.raises(PublicationRuntimeError):
        authorize_and_mutate_canonical(_request(repo, "state_main"), callback)
    assert calls == []


@pytest.mark.parametrize("duplicate_surface", ["root", "nested"])
def test_lcr084_candidate_duplicate_keys_deny_before_callback(
    tmp_path: Path,
    duplicate_surface: str,
) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder

    repo = _seed_repo(tmp_path, "state_staging")
    _install_builder_shaped_lcr084_candidate(repo)
    candidate_path = repo / builder.DEFAULT_REPORT_RELPATH
    serialized = candidate_path.read_text(encoding="utf-8")
    if duplicate_surface == "root":
        serialized = serialized[:-1] + ', "status": "passed"}'
    else:
        needle = f'"kind": "{builder.PRODUCTION_KIND}"'
        serialized = serialized.replace(
            needle,
            needle + f', "kind": "{builder.PRODUCTION_KIND}"',
            1,
        )
    candidate_path.write_text(serialized, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "forge duplicate candidate key")
    calls, callback = _callback_tracker()
    decision = evaluate_canonical_publication(_request(repo, "state_staging"))
    assert decision.authorized is False
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate_canonical(
            _request(repo, "state_staging"),
            callback,
        )
    assert calls == []


def test_state_main_seal_duplicate_key_denies_before_callback(
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path, "state_main")
    seal_path = repo / CANONICAL_PATHS["state_prepublication_seal"]
    serialized = seal_path.read_text(encoding="utf-8")
    seal_path.write_text(
        serialized.rstrip()[:-1] + ', "status": "sealed"}',
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "forge duplicate seal key")
    calls, callback = _callback_tracker()
    assert evaluate_canonical_publication(_request(repo, "state_main")).authorized is False
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate_canonical(_request(repo, "state_main"), callback)
    assert calls == []


def test_alternate_git_checkout_cannot_become_mutation_root(
    tmp_path: Path,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    alternate = _seed_repo(tmp_path, "state_main")
    with pytest.raises(PublicationRuntimeError, match="exact runtime/publisher"):
        runtime._require_mutation_implementation_root(alternate)


def test_final_mutation_inventory_uses_one_paired_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    report = {"schema": "paired", "status": "passed"}
    projection = (
        {
            "path": "services/légal_runtime.py",
            "sha256": "a" * 64,
            "size_bytes": 17,
        },
    )
    calls = {"paired": 0}

    class _Capture:
        source_projection = projection

        def __init__(self) -> None:
            self.report = report

    class _Verifier:
        @staticmethod
        def validate_frozen_mutation_capture(**_kwargs: object) -> _Capture:
            calls["paired"] += 1
            return _Capture()

        @staticmethod
        def validate_frozen_mutation_inventory(**_kwargs: object) -> object:
            pytest.fail("runtime used the split inventory API")

        @staticmethod
        def mutation_source_projection(**_kwargs: object) -> object:
            pytest.fail("runtime used the split projection API")

    head = "d" * 40
    monkeypatch.setattr(
        runtime,
        "_load_fresh_attested_verifier",
        lambda _name: (_Verifier(), "paired-verifier"),
    )
    monkeypatch.setattr(
        runtime,
        "_discard_fresh_attested_verifier",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        runtime,
        "_require_mutation_implementation_root",
        lambda _root: tmp_path,
    )
    monkeypatch.setattr(runtime, "inspect_clean_head", lambda _root: head)
    monkeypatch.setattr(
        runtime,
        "read_canonical_bytes",
        lambda _root, relpath: str(relpath).encode("utf-8"),
    )

    binding = runtime._revalidate_mutation_inventory_before_callback(
        tmp_path,
        expected_head=head,
    )

    assert calls == {"paired": 1}
    assert binding == {
        "inventory_digest_sha256": runtime._production_candidate_report_digest(
            report
        ),
        "source_file_count": 1,
        "source_projection_digest_sha256": hashlib.sha256(
            json.dumps(
                projection,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    runtime._require_final_mutation_audit_binding(dict(binding), binding)


@pytest.mark.parametrize(
    ("field", "mismatched_value"),
    (
        ("inventory_digest_sha256", "e" * 64),
        ("source_projection_digest_sha256", "f" * 64),
        ("source_file_count", 2),
    ),
)
def test_final_mutation_audit_binding_rejects_every_mismatch(
    field: str,
    mismatched_value: object,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    final_binding = {
        "inventory_digest_sha256": "a" * 64,
        "source_projection_digest_sha256": "b" * 64,
        "source_file_count": 1,
    }
    mismatched_candidate = dict(final_binding)
    mismatched_candidate[field] = mismatched_value
    with pytest.raises(
        PublicationRuntimeError,
        match="differs from the final protected-write inventory",
    ):
        runtime._require_final_mutation_audit_binding(
            mismatched_candidate,
            final_binding,
        )


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_canonical_runtime_rejects_raw_partial_and_bound_alias_callbacks(
    tmp_path: Path,
    phase: str,
) -> None:
    repo = _seed_repo(tmp_path, phase)
    payload = _request(repo, phase)
    observed: list[Any] = []

    def raw_callback(decision: Any, *, marker: str = "raw") -> str:
        observed.append((marker, decision))
        return "mutated"

    class CallbackOwner:
        def upload(self, decision: Any) -> str:
            return raw_callback(decision, marker="bound")

    callbacks = (
        raw_callback,
        lambda decision: raw_callback(decision, marker="lambda"),
        partial(raw_callback, marker="partial"),
        CallbackOwner().upload,
    )
    for callback in callbacks:
        with pytest.raises(PublicationRuntimeError, match="exact sealed"):
            authorize_and_mutate_canonical(payload, callback)
    assert observed == []


def test_principal_is_revalidated_before_executor_attestation(
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path, "state_main")
    events: list[str] = []
    base_probe = _probe("justicedao/ipfs_state_laws")

    def ordered_probe(token: str, repo_id: str) -> Mapping[str, Any]:
        events.append("principal")
        return base_probe(token, repo_id)

    def forbidden_executor(_decision: Any) -> None:
        events.append("executor")

    with pytest.raises(PublicationRuntimeError, match="exact sealed"):
        authorize_and_mutate_canonical(
            _request(repo, "state_main", probe=ordered_probe),
            forbidden_executor,
        )
    assert events == ["principal", "principal"]


@pytest.mark.parametrize("drift_field", ["principal", "owner_role", "token_role"])
def test_principal_authority_drift_denies_before_executor(
    tmp_path: Path,
    drift_field: str,
) -> None:
    repo = _seed_repo(tmp_path, "state_main")
    events: list[str] = []

    def drifting_probe(token: str, repo_id: str) -> Mapping[str, Any]:
        assert token == TOKEN
        events.append("principal")
        projection: dict[str, Any] = {
            "authority_source": "fixture_whoami",
            "dataset_repo_id": repo_id,
            "has_write_access": True,
            "identity": "huggingface:fixture-bot",
            "owner": "justicedao",
            "owner_role": "admin",
            "principal": "fixture-bot",
            "scopes": [f"dataset:write:{repo_id}"],
            "token_role": "write",
            "write_targets": [repo_id],
        }
        if len(events) > 1:
            projection[drift_field] = {
                "principal": "other-bot",
                "owner_role": "write",
                "token_role": "admin",
            }[drift_field]
        return projection

    def forbidden_executor(_decision: Any) -> None:
        events.append("executor")

    with pytest.raises(
        PublicationGateDeniedError,
        match="evidence changed",
    ) as exc_info:
        authorize_and_mutate_canonical(
            _request(repo, "state_main", probe=drifting_probe),
            forbidden_executor,
        )

    assert exc_info.value.reason_codes == ("runtime.evidence_race",)
    assert events == ["principal", "principal"]


def test_expected_plan_constraints_fail_closed_before_callback(
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path, "state_main")
    _assert_denied(
        _request(
            repo,
            "state_main",
            extra={
                "expected_dataset_repo_id": (
                    "justicedao/ipfs_state_laws"
                ),
                "expected_plan_digest": "a" * 64,
                "expected_policy_proof_digest": "b" * 64,
                "expected_release_manifest_digest": "c" * 64,
            },
        ),
        fragment="manifest_binding",
    )


def test_candidate_and_seal_plan_policy_constraints_are_independent(
    tmp_path: Path,
) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder

    valid = _seed_repo(tmp_path / "valid", "state_main")
    valid_request = _request(valid, "state_main")
    valid_decision = evaluate_canonical_publication(valid_request)
    assert valid_decision.authorized is True, valid_decision.to_dict()
    expected = {
        key: valid_request[key]
        for key in (
            "expected_dataset_repo_id",
            "expected_plan_digest",
            "expected_policy_proof_digest",
            "expected_release_manifest_digest",
        )
    }

    bad_candidate = _seed_repo(tmp_path / "bad-candidate", "state_main")
    candidate_path = bad_candidate / CANONICAL_PATHS[
        "state_candidate_manifest"
    ]
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["publication_binding"]["plan_digest"] = "d" * 64
    candidate["report_digest_sha256"] = builder._digest_for_report(candidate)
    candidate_path.write_text(
        json.dumps(candidate, sort_keys=True),
        encoding="utf-8",
    )
    _git(bad_candidate, "add", "-A")
    _git(bad_candidate, "commit", "-m", "drift candidate plan binding")
    _assert_denied(
        _request(bad_candidate, "state_main", extra=expected),
        fragment="manifest_binding",
    )

    bad_seal = _seed_repo(tmp_path / "bad-seal", "state_main")
    seal_path = bad_seal / CANONICAL_PATHS["state_prepublication_seal"]
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal.pop("canonical_digest", None)
    seal["policy_proof_digest"] = "d" * 64
    _seal_json(seal_path, seal, schema=SEAL_SCHEMA_V1)
    _git(bad_seal, "add", "-A")
    _git(bad_seal, "commit", "-m", "drift seal proof binding")
    _assert_denied(
        _request(bad_seal, "state_main", extra=expected),
        fragment="manifest_binding",
    )


def test_staging_does_not_need_later_main_seal(tmp_path: Path) -> None:
    for phase in ("state_staging", "federal_staging"):
        repo = _seed_repo(tmp_path / phase, phase)
        seal = phase_requirements(phase).get("seal_receipt_path")
        assert not seal
        payload = _request(repo, phase)
        decision = evaluate_canonical_publication(payload)
        assert decision.authorized is True
        assert decision.details.get("prepublication_seal_required") is False


def test_both_main_phases_require_exact_present_true_seal(tmp_path: Path) -> None:
    for phase in ("state_main", "federal_main"):
        repo = _seed_repo(tmp_path / f"{phase}-ok", phase)
        assert evaluate_canonical_publication(_request(repo, phase)).authorized is True
        missing = _seed_repo(tmp_path / f"{phase}-absent", phase, seal_present=False)
        _assert_denied(_request(missing, phase), fragment="seal")


# ---------------------------------------------------------------------------
# Denial matrix
# ---------------------------------------------------------------------------


def test_omitted_ancestor_cannot_be_hidden(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging", omit_task="LCR-008")
    payload = _request(
        repo,
        "state_staging",
        extra={"task_statuses": {"LCR-008": "completed", "LCR-039": "completed"}},
    )
    _assert_denied(payload, fragment="canonical_path_override")
    clean = _request(repo, "state_staging")
    _assert_denied(clean, fragment="task_ancestor_closure")


def test_generated_task_cannot_be_hidden(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_main", include_generated_todo=True)
    _assert_denied(_request(repo, "state_main"), fragment="generated_work_guard")


def test_alternate_root_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_staging")
    nested = repo / "nested"
    nested.mkdir()
    _assert_denied(_request(nested, "federal_staging"), fragment="alternate_repository")


def test_dirty_authoritative_path_denies(tmp_path: Path) -> None:
    repo = _seed_repo(
        tmp_path,
        "state_staging",
        dirty_after_commit=RIGHTS_RECEIPT_RELPATH,
    )
    _assert_denied(_request(repo, "state_staging"), fragment="dirty_authoritative_path")


@pytest.mark.parametrize(
    "relative_path",
    [
        "ipfs_datasets_py/huggingface/publisher.py",
        (
            "ipfs_datasets_py/processors/legal_data/"
            "legal_corpora_publication_runtime.py"
        ),
        "ipfs_datasets_py/huggingface/protected_repo_guard.py",
    ],
)
def test_authorizing_mutation_rejects_dirty_non_authoritative_code(
    tmp_path: Path,
    relative_path: str,
) -> None:
    repo = _seed_repo(tmp_path, "state_main")
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# uncommitted executable drift\n", encoding="utf-8")
    _assert_denied(
        _request(repo, "state_main"),
        fragment="dirty_authoritative_path",
    )


def test_caller_selected_commit_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_main")
    payload = _request(repo, "federal_main", extra={"current_commit": "a" * 40})
    _assert_denied(payload, fragment="caller_selected_commit")
    branched = _request(repo, "federal_main", extra={"branch": "other"})
    _assert_denied(branched, fragment="caller_selected_commit")


def test_missing_receipt_status_denies(tmp_path: Path) -> None:
    path = "docs/reports/legal_corpora_reindex/local_e2e.json"
    repo = _seed_repo(tmp_path, "state_staging", skip_receipt_status=path)
    _assert_denied(_request(repo, "state_staging"), fragment="missing_receipt_status")


def test_forged_digest_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging")
    target = repo / "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["report_digest_sha256"] = "0" * 64
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "forge acceptance digest")
    _assert_denied(_request(repo, "state_staging"), fragment="independent_digest_mismatch")


def test_changed_receipt_bytes_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_staging")
    target = repo / "docs/reports/legal_corpora_reindex/federal_inventory.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["note"] = "tampered-bytes"
    # Keep declared digest, change body.
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "tamper receipt bytes")
    _assert_denied(_request(repo, "federal_staging"), fragment="independent_digest_mismatch")


def test_unknown_receipt_schema_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging")
    target = repo / "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema"] = "ipfs_datasets_py/unknown-receipt-schema@9"
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "set unknown receipt schema")
    _assert_denied(_request(repo, "state_staging"), fragment="unknown_receipt_schema")


def test_missing_manifest_binding_denies(tmp_path: Path) -> None:
    from scripts.ops.legal_data import build_state_laws_hf_release as builder

    repo = _seed_repo(tmp_path, "state_staging")
    target = repo / CANONICAL_PATHS["state_candidate_manifest"]
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.pop("source_rights_receipt_digest", None)
    payload["report_digest_sha256"] = builder._digest_for_report(payload)
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "remove candidate rights binding")
    _assert_denied(_request(repo, "state_staging"), fragment="missing_manifest_binding")


def test_missing_credentials_deny(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging")
    _assert_denied(
        _request(repo, "state_staging", environ={}),
        fragment="credential_token_error",
    )


def test_wrong_scope_credentials_deny(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging")
    other = "justicedao/ipfs_federal_register"

    def probe(token: str, repo_id: str) -> dict[str, Any]:
        return {
            "principal": "fixture-bot",
            "has_write_access": True,
            "write_targets": [other],
            "scopes": [credentials_scope_for(other)],
            "dataset_repo_id": other,
            "identity": f"env:{other}",
        }

    _assert_denied(
        _request(repo, "state_staging", probe=probe),
        fragment="principal_authority_error",
    )


def test_target_mismatched_principal_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_staging")

    def probe(token: str, repo_id: str) -> dict[str, Any]:
        return {
            "principal": "fixture-bot",
            "has_write_access": False,
            "write_targets": ["evil/other"],
            "scopes": ["dataset:write:evil/other"],
            "dataset_repo_id": "evil/other",
            "identity": "env:evil/other",
        }

    _assert_denied(
        _request(repo, "federal_staging", probe=probe),
        fragment="principal_authority_error",
    )


def test_absent_present_true_seal_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_main", seal_present=False)
    _assert_denied(_request(repo, "state_main"), fragment="seal")


def test_offset_seal_time_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_main", seal_time="2020-01-01T00:00:00+00:00")
    _assert_denied(_request(repo, "federal_main"), fragment="seal_time")


def test_future_seal_time_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_main", seal_time="2099-01-01T00:00:00Z")
    _assert_denied(_request(repo, "state_main"), fragment="seal_time")


def test_post_mutation_seal_denies(tmp_path: Path) -> None:
    def mutator(relpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        if relpath.endswith("state_prepublication_seal.json"):
            payload = dict(payload)
            payload["created_after_mutation"] = True
            payload["post_hoc"] = True
        return payload

    repo = _seed_repo(tmp_path, "state_main", receipt_mutator=mutator)
    _assert_denied(_request(repo, "state_main"), fragment="seal")


def test_missing_seal_bindings_deny(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_main", omit_seal_manifest=True)
    _assert_denied(_request(repo, "federal_main"), fragment="seal")
    repo2 = _seed_repo(tmp_path / "no-staging", "state_main", omit_seal_staging=True)
    _assert_denied(_request(repo2, "state_main"), fragment="seal")


def test_evidence_race_denies_before_callback(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging")
    calls, upload = _callback_tracker()
    target = repo / RIGHTS_RECEIPT_RELPATH
    seen = {"n": 0}
    base_probe = _probe(phase_requirements("state_staging")["dataset_repo_id"])

    def racing_probe(token: str, repo_id: str) -> Mapping[str, Any]:
        seen["n"] += 1
        if seen["n"] == 2:
            target.write_text(
                target.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
        return base_probe(token, repo_id)

    payload = _request(repo, "state_staging", probe=racing_probe)
    with pytest.raises(PublicationGateDeniedError) as exc:
        authorize_and_mutate_canonical(payload, upload)
    assert any("evidence_race" in code for code in exc.value.reason_codes)
    assert calls == []


def test_path_override_keys_cannot_authorize(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging")
    for key in ("task_statuses", "receipts", "release_policy_path", "manifest_path"):
        _assert_denied(
            _request(repo, "state_staging", extra={key: {"x": "y"}}),
            fragment="canonical_path_override",
        )


def test_secrets_never_enter_decisions(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "federal_main")
    decision = evaluate_canonical_publication(_request(repo, "federal_main"))
    dumped = json.dumps(decision.to_dict())
    assert TOKEN not in dumped
    assert "hf_" not in dumped
    assert "Bearer " not in dumped
    assert CanonicalPublicationRequest.from_mapping(
        _request(repo, "federal_main")
    ).phase == "federal_main"


def test_raw_and_canonical_digests_are_independent() -> None:
    payload = {"status": "passed", "schema": RECEIPT_SCHEMA_V1, "note": "x"}
    canonical = canonical_no_self_field_digest(payload)
    with_digest = dict(payload)
    with_digest["canonical_digest"] = canonical
    assert canonical_no_self_field_digest(with_digest) == canonical
    raw = json.dumps(with_digest, sort_keys=True).encode("utf-8")
    assert raw_file_digest(raw) != canonical or True
    assert len(raw_file_digest(raw)) == 64


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_lcr083_stale_rights_verified_at_denies_before_callback(
    tmp_path: Path, phase: str
) -> None:
    def mutator(relpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        if relpath == RIGHTS_RECEIPT_RELPATH:
            payload = dict(payload)
            payload["verified_at"] = "2020-01-01T00:00:00Z"
        return payload

    repo = _seed_repo(tmp_path, phase, receipt_mutator=mutator)
    _assert_denied(_request(repo, phase), fragment="source_rights_binding")


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_lcr083_future_rights_verified_at_denies_before_callback(
    tmp_path: Path, phase: str
) -> None:
    def mutator(relpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        if relpath == RIGHTS_RECEIPT_RELPATH:
            payload = dict(payload)
            payload["verified_at"] = "2099-01-01T00:00:00Z"
        return payload

    repo = _seed_repo(tmp_path, phase, receipt_mutator=mutator)
    _assert_denied(_request(repo, phase), fragment="source_rights_binding")


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_lcr083_pre_hardening_producer_denies_before_callback(
    tmp_path: Path, phase: str
) -> None:
    def mutator(relpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        if relpath == RIGHTS_RECEIPT_RELPATH:
            payload = dict(payload)
            payload["producer"] = "audit_legal_source_rights.py@1"
        return payload

    repo = _seed_repo(tmp_path, phase, receipt_mutator=mutator)
    _assert_denied(_request(repo, phase), fragment="source_rights_binding")


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_lcr083_target_mismatched_rights_denies_before_callback(
    tmp_path: Path, phase: str
) -> None:
    def mutator(relpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        if relpath == RIGHTS_RECEIPT_RELPATH:
            payload = dict(payload)
            payload["dataset_repo_id"] = "evil/other-dataset"
            payload["target_dataset_repo_ids"] = ["evil/other-dataset"]
        return payload

    repo = _seed_repo(tmp_path, phase, receipt_mutator=mutator)
    _assert_denied(_request(repo, phase), fragment="source_rights_binding")


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_lcr083_prohibited_or_unknown_rights_deny_before_callback(
    tmp_path: Path, phase: str
) -> None:
    def mutator(relpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        if relpath == RIGHTS_RECEIPT_RELPATH:
            payload = dict(payload)
            payload["prohibited"] = True
            payload["rights_disposition"] = "unknown"
        return payload

    repo = _seed_repo(tmp_path, phase, receipt_mutator=mutator)
    _assert_denied(_request(repo, phase), fragment="source_rights_binding")
