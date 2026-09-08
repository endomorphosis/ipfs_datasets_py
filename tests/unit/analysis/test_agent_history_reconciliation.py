"""Deterministic tests for EAAEF-023 agent history reconciliation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.analysis.agent_history_reconciliation import (
    AGENT_HISTORY_RECONCILIATION_REPORT_INTERFACE,
    AGENT_HISTORY_RECONCILIATION_REPORT_SCHEMA,
    CONTRACT_VERSION,
    SCHEMA_VERSION,
    ClassificationReason,
    ComparisonMethod,
    FileSurface,
    HistoryReconciliationBoundsError,
    HistoryReconciliationError,
    HistoryReconciliationIdentityError,
    HistoryReconciliationReport,
    ImportedHistory,
    ProvenanceDomain,
    ReconstructedCommit,
    ReconstructedFile,
    ReconstructedPatch,
    ReconstructedTest,
    ReconstructedTruth,
    ReferencedCommit,
    ReferencedFile,
    ReferencedPatch,
    ReferencedTest,
    TrustClass,
    WorkClassification,
    WorkClassificationRecord,
    WorkKind,
    WorkProvenance,
    canonical_json_bytes,
    classify_referenced_work,
    content_identity,
    imported_provenance,
    reconcile_agent_history,
)


FIXED_MS = 1_700_000_000_000
SHA_HEAD = "sha256:" + ("a" * 64)
SHA_OLD = "sha256:" + ("b" * 64)
SHA_OTHER = "sha256:" + ("c" * 64)
SHA_FILE = "sha256:" + ("d" * 64)
SHA_FILE_NEW = "sha256:" + ("e" * 64)
SHA_FILE_HIST = "sha256:" + ("f" * 64)
SHA_PATCH = "sha256:" + ("1" * 64)
SHA_PATCH_OLD = "sha256:" + ("2" * 64)
SHA_TEST = "sha256:" + ("3" * 64)
SHA_TEST_NEW = "sha256:" + ("4" * 64)
SHA_SESSION = "sha256:" + ("5" * 64)
SHA_QUARANTINE = "sha256:" + ("6" * 64)
SHA_ORIGIN = "sha256:" + ("7" * 64)
SHA_STREAM = "sha256:" + ("8" * 64)
GIT_HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
GIT_OLD = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _claim(**changes: object) -> WorkProvenance:
    values: dict[str, object] = {
        "origin_record_id": SHA_ORIGIN,
        "source_family": "codex",
        "adapter_id": "codex@1",
        "captured_at_ms": FIXED_MS,
        "trust_class": TrustClass.IMPORTED_UNVERIFIED,
    }
    values.update(changes)
    return imported_provenance(**values)


def _history(**changes: object) -> ImportedHistory:
    values: dict[str, object] = {
        "session_id": SHA_SESSION,
        "stream_id": SHA_STREAM,
        "commits": (),
        "files": (),
        "patches": (),
        "tests": (),
    }
    values.update(changes)
    return ImportedHistory(**values)


def _truth(**changes: object) -> ReconstructedTruth:
    values: dict[str, object] = {
        "quarantine_receipt_id": SHA_QUARANTINE,
        "head_commit_id": SHA_HEAD,
        "refs": {"refs/heads/main": SHA_HEAD},
        "commits": (
            ReconstructedCommit(commit_id=SHA_HEAD, tree_id=SHA_FILE),
            ReconstructedCommit(commit_id=SHA_OLD, tree_id=SHA_FILE_HIST, parent_ids=()),
        ),
        "files": (
            ReconstructedFile(
                path="src/app.py",
                content_id=SHA_FILE,
                surface=FileSurface.HEAD_TREE,
                commit_id=SHA_HEAD,
            ),
        ),
        "patches": (),
        "tests": (),
    }
    values.update(changes)
    return ReconstructedTruth(**values)


def test_contract_version_and_schema_are_frozen() -> None:
    assert CONTRACT_VERSION == 1
    assert SCHEMA_VERSION == 1
    assert AGENT_HISTORY_RECONCILIATION_REPORT_INTERFACE == (
        "AgentHistoryReconciliationReport@1"
    )
    assert AGENT_HISTORY_RECONCILIATION_REPORT_SCHEMA.endswith(
        "agent-history-reconciliation-report@1"
    )


def test_present_commit_matching_head() -> None:
    report = reconcile_agent_history(
        _history(commits=(ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),)),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.PRESENT
    assert record.reason is ClassificationReason.CURRENT_HEAD_IDENTITY_MATCH
    assert record.reconstructed_surfaces == ("HEAD",)
    assert record.claim_provenance.origin_record_id == SHA_ORIGIN


def test_present_commit_matching_named_ref() -> None:
    report = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(
                    commit_id=SHA_HEAD,
                    ref_name="refs/heads/main",
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.PRESENT
    assert record.reason is ClassificationReason.CURRENT_REF_IDENTITY_MATCH
    assert record.locator == "refs/heads/main"


def test_stale_commit_named_ref_diverged() -> None:
    report = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(
                    commit_id=SHA_OLD,
                    ref_name="refs/heads/main",
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.STALE
    assert record.reason is ClassificationReason.CURRENT_REF_IDENTITY_DIVERGED
    assert record.reconstructed_identity == SHA_HEAD
    assert record.comparison is ComparisonMethod.LOCATOR_DIVERGENCE


def test_history_only_commit_not_current_tip() -> None:
    report = reconcile_agent_history(
        _history(commits=(ReferencedCommit(commit_id=SHA_OLD, provenance=_claim()),)),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.HISTORY_ONLY
    assert record.reason is ClassificationReason.HISTORY_IDENTITY_MATCH
    assert record.comparison is ComparisonMethod.HISTORY_OBJECT
    assert record.reconstructed_surfaces == ("history",)


def test_missing_commit() -> None:
    report = reconcile_agent_history(
        _history(commits=(ReferencedCommit(commit_id=SHA_OTHER, provenance=_claim()),)),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.MISSING
    assert record.reconstructed_identity == ""
    assert record.comparison is ComparisonMethod.ABSENT


def test_git_sha1_commit_identities_are_admitted() -> None:
    truth = _truth(
        head_commit_id=GIT_HEAD,
        refs={"HEAD": GIT_HEAD},
        commits=(
            ReconstructedCommit(commit_id=GIT_HEAD),
            ReconstructedCommit(commit_id=GIT_OLD),
        ),
    )
    report = reconcile_agent_history(
        _history(commits=(ReferencedCommit(commit_id=GIT_HEAD, provenance=_claim()),)),
        truth,
    )
    assert report.records[0].classification is WorkClassification.PRESENT


def test_present_file_matching_overlay() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE, provenance=_claim()
                ),
            )
        ),
        _truth(),
    )
    record = report.records[0]
    assert record.work_kind is WorkKind.FILE
    assert record.classification is WorkClassification.PRESENT
    assert record.reason is ClassificationReason.CURRENT_OVERLAY_IDENTITY_MATCH
    assert record.reconstructed_surfaces == (FileSurface.HEAD_TREE.value,)


def test_stale_file_same_path_different_identity() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE_HIST, provenance=_claim()
                ),
            )
        ),
        _truth(
            files=(
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE,
                    surface=FileSurface.HEAD_TREE,
                    commit_id=SHA_HEAD,
                ),
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE_HIST,
                    surface=FileSurface.HISTORY,
                    commit_id=SHA_OLD,
                ),
            )
        ),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.STALE
    assert record.reconstructed_identity == SHA_FILE
    assert record.reason is ClassificationReason.CURRENT_LOCATOR_IDENTITY_DIVERGED


def test_stale_takes_precedence_over_history_only_when_path_still_current() -> None:
    record = classify_referenced_work(
        ReferencedFile(path="src/app.py", content_id=SHA_FILE_HIST, provenance=_claim()),
        _truth(
            files=(
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE,
                    surface=FileSurface.WORKTREE,
                ),
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE_HIST,
                    surface=FileSurface.HISTORY,
                    commit_id=SHA_OLD,
                ),
            )
        ),
    )
    assert record.classification is WorkClassification.STALE
    assert record.classification is not WorkClassification.HISTORY_ONLY


def test_history_only_file_deleted_from_current_tree() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/legacy.py", content_id=SHA_FILE_HIST, provenance=_claim()
                ),
            )
        ),
        _truth(
            files=(
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE,
                    surface=FileSurface.HEAD_TREE,
                ),
                ReconstructedFile(
                    path="src/legacy.py",
                    content_id=SHA_FILE_HIST,
                    surface=FileSurface.HISTORY,
                    commit_id=SHA_OLD,
                ),
            )
        ),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.HISTORY_ONLY
    assert record.reconstructed_identity == SHA_FILE_HIST


def test_present_file_relocated_in_current_overlay() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/old_name.py", content_id=SHA_FILE, provenance=_claim()
                ),
            )
        ),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.PRESENT
    assert record.reason is ClassificationReason.CURRENT_RELOCATED_IDENTITY_MATCH
    assert record.relocated_path == "src/app.py"
    assert record.comparison is ComparisonMethod.RELOCATED_IDENTITY


def test_missing_file() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/absent.py", content_id=SHA_OTHER, provenance=_claim()
                ),
            )
        ),
        _truth(),
    )
    assert report.records[0].classification is WorkClassification.MISSING


def test_worktree_overlay_outranks_head_tree() -> None:
    truth = _truth(
        files=(
            ReconstructedFile(
                path="src/app.py",
                content_id=SHA_FILE,
                surface=FileSurface.HEAD_TREE,
            ),
            ReconstructedFile(
                path="src/app.py",
                content_id=SHA_FILE_NEW,
                surface=FileSurface.WORKTREE,
            ),
        )
    )
    present = classify_referenced_work(
        ReferencedFile(path="src/app.py", content_id=SHA_FILE_NEW, provenance=_claim()),
        truth,
    )
    stale = classify_referenced_work(
        ReferencedFile(path="src/app.py", content_id=SHA_FILE, provenance=_claim()),
        truth,
    )
    assert present.classification is WorkClassification.PRESENT
    assert stale.classification is WorkClassification.STALE
    assert stale.reconstructed_identity == SHA_FILE_NEW


def test_conflicting_same_surface_identities_fail_closed() -> None:
    with pytest.raises(HistoryReconciliationIdentityError, match="conflicting identities"):
        _truth(
            files=(
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE,
                    surface=FileSurface.WORKTREE,
                ),
                ReconstructedFile(
                    path="src/app.py",
                    content_id=SHA_FILE_NEW,
                    surface=FileSurface.WORKTREE,
                ),
            )
        )


def test_present_patch_matching_overlay_object() -> None:
    report = reconcile_agent_history(
        _history(
            patches=(
                ReferencedPatch(
                    patch_id=SHA_PATCH,
                    paths=("src/app.py",),
                    result_file_ids={"src/app.py": SHA_FILE},
                    provenance=_claim(),
                ),
            )
        ),
        _truth(
            patches=(
                ReconstructedPatch(
                    patch_id=SHA_PATCH,
                    current=True,
                    paths=("src/app.py",),
                    result_file_ids={"src/app.py": SHA_FILE},
                ),
            )
        ),
    )
    assert report.records[0].classification is WorkClassification.PRESENT


def test_present_patch_when_result_files_match_overlay() -> None:
    report = reconcile_agent_history(
        _history(
            patches=(
                ReferencedPatch(
                    patch_id=SHA_PATCH,
                    paths=("src/app.py",),
                    result_file_ids={"src/app.py": SHA_FILE},
                    claimed_applied=True,
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.PRESENT
    assert record.reason is ClassificationReason.CURRENT_OVERLAY_IDENTITY_MATCH


def test_claimed_applied_does_not_create_presence_without_truth() -> None:
    report = reconcile_agent_history(
        _history(
            patches=(
                ReferencedPatch(
                    patch_id=SHA_PATCH,
                    paths=("src/absent.py",),
                    claimed_applied=True,
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    assert report.records[0].classification is WorkClassification.MISSING


def test_stale_patch_result_files_diverged() -> None:
    report = reconcile_agent_history(
        _history(
            patches=(
                ReferencedPatch(
                    patch_id=SHA_PATCH,
                    paths=("src/app.py",),
                    result_file_ids={"src/app.py": SHA_FILE_HIST},
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.STALE
    assert record.reconstructed_identity == SHA_FILE


def test_history_only_patch() -> None:
    report = reconcile_agent_history(
        _history(
            patches=(
                ReferencedPatch(
                    patch_id=SHA_PATCH_OLD,
                    paths=("src/legacy.py",),
                    provenance=_claim(),
                ),
            )
        ),
        _truth(
            patches=(
                ReconstructedPatch(
                    patch_id=SHA_PATCH_OLD,
                    current=False,
                    paths=("src/legacy.py",),
                ),
            )
        ),
    )
    assert report.records[0].classification is WorkClassification.HISTORY_ONLY


def test_missing_patch() -> None:
    report = reconcile_agent_history(
        _history(patches=(ReferencedPatch(patch_id=SHA_OTHER, provenance=_claim()),)),
        _truth(),
    )
    assert report.records[0].classification is WorkClassification.MISSING


def test_patch_paths_without_result_ids_do_not_infer_staleness() -> None:
    report = reconcile_agent_history(
        _history(
            patches=(
                ReferencedPatch(
                    patch_id=SHA_OTHER,
                    paths=("src/app.py",),
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    assert report.records[0].classification is WorkClassification.MISSING


def test_present_test_matching_current_identity() -> None:
    report = reconcile_agent_history(
        _history(
            tests=(
                ReferencedTest(
                    test_id="tests/test_app.py::test_ok",
                    path="tests/test_app.py",
                    content_id=SHA_TEST,
                    provenance=_claim(),
                ),
            )
        ),
        _truth(
            tests=(
                ReconstructedTest(
                    test_id="tests/test_app.py::test_ok",
                    path="tests/test_app.py",
                    content_id=SHA_TEST,
                    current=True,
                    commit_id=SHA_HEAD,
                ),
            )
        ),
    )
    assert report.records[0].classification is WorkClassification.PRESENT


def test_stale_test_same_id_different_content() -> None:
    report = reconcile_agent_history(
        _history(
            tests=(
                ReferencedTest(
                    test_id="tests/test_app.py::test_ok",
                    path="tests/test_app.py",
                    content_id=SHA_TEST,
                    provenance=_claim(),
                ),
            )
        ),
        _truth(
            tests=(
                ReconstructedTest(
                    test_id="tests/test_app.py::test_ok",
                    path="tests/test_app.py",
                    content_id=SHA_TEST_NEW,
                    current=True,
                ),
            )
        ),
    )
    record = report.records[0]
    assert record.classification is WorkClassification.STALE
    assert record.reconstructed_identity == SHA_TEST_NEW


def test_history_only_test() -> None:
    report = reconcile_agent_history(
        _history(
            tests=(
                ReferencedTest(
                    test_id="tests/test_legacy.py::test_old",
                    path="tests/test_legacy.py",
                    content_id=SHA_TEST,
                    provenance=_claim(),
                ),
            )
        ),
        _truth(
            tests=(
                ReconstructedTest(
                    test_id="tests/test_legacy.py::test_old",
                    path="tests/test_legacy.py",
                    content_id=SHA_TEST,
                    current=False,
                    commit_id=SHA_OLD,
                ),
            )
        ),
    )
    assert report.records[0].classification is WorkClassification.HISTORY_ONLY


def test_missing_test() -> None:
    report = reconcile_agent_history(
        _history(
            tests=(
                ReferencedTest(
                    test_id="tests/test_absent.py::test_gone",
                    path="tests/test_absent.py",
                    content_id=SHA_OTHER,
                    provenance=_claim(),
                ),
            )
        ),
        _truth(),
    )
    assert report.records[0].classification is WorkClassification.MISSING


def test_mixed_classifications_are_counted_and_sorted() -> None:
    report = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),
                ReferencedCommit(commit_id=SHA_OLD, provenance=_claim()),
                ReferencedCommit(commit_id=SHA_OTHER, provenance=_claim()),
            ),
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE_NEW, provenance=_claim()
                ),
            ),
        ),
        _truth(),
    )
    assert report.counts == {
        "present": 1,
        "stale": 1,
        "missing": 1,
        "history_only": 1,
    }
    kinds_locators = [(item.work_kind.value, item.locator) for item in report.records]
    assert kinds_locators == sorted(kinds_locators)
    assert report.records_for(WorkClassification.PRESENT)[0].work_kind is WorkKind.COMMIT


def test_duplicate_references_collapse_deterministically() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE, provenance=_claim()
                ),
                ReferencedFile(
                    path="src/app.py",
                    content_id=SHA_FILE,
                    provenance=_claim(adapter_id="codex@2"),
                ),
            )
        ),
        _truth(),
    )
    assert len(report.records) == 1
    assert report.counts["present"] == 1


def test_same_path_distinct_identities_remain_separate() -> None:
    report = reconcile_agent_history(
        _history(
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE, provenance=_claim()
                ),
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE_NEW, provenance=_claim()
                ),
            )
        ),
        _truth(),
    )
    assert len(report.records) == 2
    classifications = {item.classification for item in report.records}
    assert classifications == {
        WorkClassification.PRESENT,
        WorkClassification.STALE,
    }


def test_empty_imported_history_is_zero_counts() -> None:
    report = reconcile_agent_history(_history(), _truth())
    assert report.records == ()
    assert report.counts == {
        "present": 0,
        "stale": 0,
        "missing": 0,
        "history_only": 0,
    }
    assert report.quarantine_receipt_id == SHA_QUARANTINE


def test_report_content_identity_is_stable_and_ignores_input_order() -> None:
    first = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(commit_id=SHA_OLD, provenance=_claim()),
                ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),
            )
        ),
        _truth(),
    )
    second = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),
                ReferencedCommit(commit_id=SHA_OLD, provenance=_claim()),
            )
        ),
        _truth(),
    )
    assert first.content_id == second.content_id
    assert first.content_id.startswith("sha256:")
    assert first.to_dict() == second.to_dict()


def test_report_roundtrip_preserves_classifications() -> None:
    report = reconcile_agent_history(
        _history(
            commits=(ReferencedCommit(commit_id=SHA_OLD, provenance=_claim()),),
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE, provenance=_claim()
                ),
            ),
        ),
        _truth(),
    )
    restored = HistoryReconciliationReport.from_dict(report.to_dict())
    assert restored.content_id == report.content_id
    assert restored.counts == report.counts
    assert restored.records[0].classification is WorkClassification.HISTORY_ONLY


def test_mapping_inputs_are_accepted() -> None:
    report = reconcile_agent_history(
        {
            "session_id": SHA_SESSION,
            "commits": [
                {
                    "commit_id": SHA_HEAD,
                    "provenance": {
                        "domain": "imported_history",
                        "trust_class": "imported_unverified",
                    },
                }
            ],
        },
        {
            "quarantine_receipt_id": SHA_QUARANTINE,
            "head_commit_id": SHA_HEAD,
            "commits": [{"commit_id": SHA_HEAD}],
        },
    )
    assert report.records[0].classification is WorkClassification.PRESENT


def test_imported_history_never_grants_completion_or_authority() -> None:
    report = reconcile_agent_history(
        _history(
            commits=(ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),),
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE, provenance=_claim()
                ),
            ),
            tests=(
                ReferencedTest(
                    test_id="tests/test_app.py::test_ok",
                    path="tests/test_app.py",
                    content_id=SHA_TEST,
                    provenance=_claim(trust_class=TrustClass.IMPORTED_EXPORTABLE),
                ),
            ),
        ),
        _truth(
            tests=(
                ReconstructedTest(
                    test_id="tests/test_app.py::test_ok",
                    path="tests/test_app.py",
                    content_id=SHA_TEST,
                    current=True,
                ),
            )
        ),
    )
    assert report.may_satisfy_completion is False
    assert report.imported_history_is_authority is False
    assert report.to_dict()["may_satisfy_completion"] is False
    assert report.to_dict()["imported_history_is_authority"] is False
    assert all(record.may_satisfy_completion is False for record in report.records)
    assert TrustClass.IMPORTED_UNVERIFIED.may_satisfy_completion is False
    assert TrustClass.IMPORTED_EXPORTABLE.may_satisfy_completion is False


def test_locally_reverified_trust_still_cannot_self_admit_via_report() -> None:
    report = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(
                    commit_id=SHA_HEAD,
                    provenance=_claim(trust_class=TrustClass.LOCALLY_REVERIFIED),
                ),
            )
        ),
        _truth(),
    )
    assert report.records[0].claim_provenance.trust_class is TrustClass.LOCALLY_REVERIFIED
    assert report.may_satisfy_completion is False


def test_canonical_json_rejects_floats() -> None:
    with pytest.raises(HistoryReconciliationError, match="floats"):
        canonical_json_bytes({"value": 1.5})


def test_provenance_rejects_float_timestamp() -> None:
    with pytest.raises(HistoryReconciliationError, match="nonnegative integer"):
        imported_provenance(captured_at_ms=1.0)  # type: ignore[arg-type]


def test_absolute_paths_are_rejected() -> None:
    with pytest.raises(HistoryReconciliationError, match="repository-relative"):
        ReferencedFile(path="/etc/passwd", content_id=SHA_FILE, provenance=_claim())
    with pytest.raises(HistoryReconciliationError, match="repository-relative"):
        ReferencedFile(path="../secret.py", content_id=SHA_FILE, provenance=_claim())


def test_hidden_chain_of_thought_is_rejected() -> None:
    with pytest.raises(HistoryReconciliationError, match="chain-of-thought"):
        ImportedHistory.from_dict(
            {
                "session_id": SHA_SESSION,
                "chain_of_thought": "secret reasoning",
            }
        )


def test_private_material_is_rejected() -> None:
    with pytest.raises(HistoryReconciliationError, match="private material"):
        WorkProvenance.from_dict(
            {
                "domain": "imported_history",
                "trust_class": "imported_unverified",
                "api_key": "k",
            }
        )


def test_malformed_identity_is_rejected() -> None:
    with pytest.raises(HistoryReconciliationIdentityError, match="sha256"):
        ReferencedCommit(commit_id="not-an-id", provenance=_claim())


def test_head_commit_must_exist_in_reconstructed_commits() -> None:
    with pytest.raises(HistoryReconciliationIdentityError, match="head_commit_id"):
        ReconstructedTruth(
            quarantine_receipt_id=SHA_QUARANTINE,
            head_commit_id=SHA_HEAD,
            commits=(),
        )


def test_ref_tips_must_exist_in_reconstructed_commits() -> None:
    with pytest.raises(HistoryReconciliationIdentityError, match="ref"):
        ReconstructedTruth(
            quarantine_receipt_id=SHA_QUARANTINE,
            head_commit_id="",
            refs={"refs/heads/main": SHA_HEAD},
            commits=(),
        )


def test_result_file_ids_must_be_listed_in_paths() -> None:
    with pytest.raises(HistoryReconciliationError, match="listed in paths"):
        ReferencedPatch(
            patch_id=SHA_PATCH,
            paths=("src/app.py",),
            result_file_ids={"src/other.py": SHA_FILE},
            provenance=_claim(),
        )


def test_records_are_frozen() -> None:
    record = classify_referenced_work(
        ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),
        _truth(),
    )
    with pytest.raises(FrozenInstanceError):
        record.classification = WorkClassification.MISSING  # type: ignore[misc]


def test_report_rejects_completion_flag_on_decode() -> None:
    report = reconcile_agent_history(_history(), _truth())
    payload = report.to_dict()
    payload["may_satisfy_completion"] = True
    with pytest.raises(HistoryReconciliationError, match="cannot satisfy completion"):
        HistoryReconciliationReport.from_dict(payload)


def test_report_rejects_imported_authority_flag_on_decode() -> None:
    report = reconcile_agent_history(_history(), _truth())
    payload = report.to_dict()
    payload["imported_history_is_authority"] = True
    with pytest.raises(HistoryReconciliationError, match="cannot be authority"):
        HistoryReconciliationReport.from_dict(payload)


def test_report_rejects_mismatched_counts() -> None:
    report = reconcile_agent_history(
        _history(commits=(ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),)),
        _truth(),
    )
    payload = report.to_dict()
    payload["counts"] = {
        "present": 9,
        "stale": 0,
        "missing": 0,
        "history_only": 0,
    }
    with pytest.raises(HistoryReconciliationIdentityError, match="counts"):
        HistoryReconciliationReport.from_dict(payload)


def test_item_bound_is_enforced() -> None:
    with pytest.raises(HistoryReconciliationBoundsError, match="item-count"):
        ImportedHistory(
            session_id=SHA_SESSION,
            files=tuple(
                ReferencedFile(
                    path=f"src/f{index}.py",
                    content_id=SHA_FILE,
                    provenance=_claim(),
                )
                for index in range(4_097)
            ),
        )


def test_content_identity_uses_sorted_canonical_bytes() -> None:
    left = content_identity({"b": 1, "a": True})
    right = content_identity({"a": True, "b": 1})
    assert left == right
    assert canonical_json_bytes({"b": 1, "a": True}) == b'{"a":true,"b":1}'


def test_classifications_are_mutually_exclusive_closed_set() -> None:
    assert {item.value for item in WorkClassification} == {
        "present",
        "stale",
        "missing",
        "history_only",
    }
    report = reconcile_agent_history(
        _history(
            commits=(
                ReferencedCommit(commit_id=SHA_HEAD, provenance=_claim()),
                ReferencedCommit(commit_id=SHA_OLD, provenance=_claim()),
                ReferencedCommit(commit_id=SHA_OTHER, provenance=_claim()),
            ),
            files=(
                ReferencedFile(
                    path="src/app.py", content_id=SHA_FILE_NEW, provenance=_claim()
                ),
            ),
        ),
        _truth(),
    )
    seen: set[tuple[str, str, str]] = set()
    for record in report.records:
        key = (record.work_kind.value, record.locator, record.referenced_identity)
        assert key not in seen
        seen.add(key)
        assert record.classification in WorkClassification
        if record.classification is WorkClassification.MISSING:
            assert record.reconstructed_identity == ""
        else:
            assert record.reconstructed_identity


def test_reconstructed_provenance_trust_is_required() -> None:
    with pytest.raises(HistoryReconciliationError, match="reconstructed_truth"):
        WorkProvenance(
            domain=ProvenanceDomain.RECONSTRUCTED_TRUTH,
            trust_class=TrustClass.IMPORTED_UNVERIFIED,
        )
