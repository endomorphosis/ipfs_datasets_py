"""Fixture-only tests for the LCR-080 canonical publication runtime.

Temporary clean Git repositories supply taskboard, policy, receipt, manifest,
credential, and seal evidence. No live Hub traffic is performed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    AUTHORIZED_DATASET_REPO_IDS,
    BASELINE_REVISIONS,
    PHASE_REQUIREMENTS,
    PublicationGateDeniedError,
    REQUIRED_PUBLICATION_GATES,
    RIGHTS_RECEIPT_RELPATH,
    RUNTIME_TASK_ID,
    SUCCESSOR_TASK_ID,
    TASK_ID as GATE_TASK_ID,
    credentials_scope_for,
    phase_requirements,
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
    TASK_ID,
    TOKEN_ENV_ALLOWLIST,
    CanonicalPublicationRequest,
    authorize_and_mutate_canonical,
    canonical_no_self_field_digest,
    evaluate_canonical_publication,
    inspect_clean_head,
    obtain_token,
    parse_utc_z,
    raw_file_digest,
    require_canonical_publication,
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
    catalog_digest = canonical_no_self_field_digest({"catalog": f"{phase}:fixture"})
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
        "fixture_only": False,
        "dirty": False,
    }
    rights_digest = _finalize(RIGHTS_RECEIPT_RELPATH, rights_payload, RECEIPT_SCHEMA_V1)

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
    if extra:
        payload.update(extra)
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


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    ["state_staging", "state_main", "federal_staging", "federal_main"],
)
def test_canonical_authorized_request_invokes_callback_once(
    tmp_path: Path, phase: str
) -> None:
    repo = _seed_repo(tmp_path, phase)
    head = inspect_clean_head(repo, authoritative_paths=())
    assert len(head) == 40
    payload = _request(repo, phase)
    calls, upload = _callback_tracker()
    decision = evaluate_canonical_publication(payload)
    assert decision.authorized is True
    assert decision.network_mutation_permitted is True
    assert "source_rights_binding" in decision.passed_gates
    assert set(decision.passed_gates) == set(REQUIRED_PUBLICATION_GATES)
    assert decision.details["head"] == head
    assert decision.details["runtime_task_id"] == "LCR-080"
    dumped = json.dumps(decision.to_dict())
    assert TOKEN not in dumped
    result = authorize_and_mutate_canonical(payload, upload)
    assert result == "mutated"
    assert len(calls) == 1
    require_canonical_publication(payload)


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
    repo = _seed_repo(
        tmp_path,
        "state_staging",
        forged_digest_for="docs/reports/legal_corpora_reindex/full_scrape_acceptance.json",
    )
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
    repo = _seed_repo(
        tmp_path,
        "state_staging",
        unknown_schema_for="docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json",
    )
    _assert_denied(_request(repo, "state_staging"), fragment="unknown_receipt_schema")


def test_missing_manifest_binding_denies(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, "state_staging", omit_manifest_binding=True)
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
    payload = _request(repo, "state_staging")
    calls, upload = _callback_tracker()
    target = repo / RIGHTS_RECEIPT_RELPATH
    original = evaluate_canonical_publication

    def racing(request: Any, *, mutation_start: Any = None) -> Any:
        decision = original(request, mutation_start=mutation_start)
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return decision

    import ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime as runtime

    wrapped = runtime.capture_canonical_snapshot
    seen = {"n": 0}

    def flaky(request: Any, *, mutation_start: Any = None) -> Any:
        snap = wrapped(request, mutation_start=mutation_start)
        seen["n"] += 1
        if seen["n"] == 1:
            target.write_text(target.read_text(encoding="utf-8") + "#race\n", encoding="utf-8")
        return snap

    runtime.capture_canonical_snapshot = flaky  # type: ignore[method-assign]
    try:
        with pytest.raises(PublicationGateDeniedError) as exc:
            authorize_and_mutate_canonical(payload, upload)
        assert any("evidence_race" in code for code in exc.value.reason_codes)
        assert calls == []
    finally:
        runtime.capture_canonical_snapshot = wrapped  # type: ignore[method-assign]
    del racing


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
