"""Unit tests for the rights-admitted execution-trace corpus (SAWM-023).

Acceptance:

* Every row is rights/privacy admitted and exact-tree bound.
* Related families cannot leak across the six disjoint partitions.
* Model nominations are never labels.
* Absent corpus returns training_unavailable without blocking contracts
  or deterministic baselines.
* Secrets, hidden tests, private reasoning, and unadmitted sources are
  excluded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.proof_corpus.program_trace_corpus import (
    ADMITTED_SOURCE_KINDS,
    EXECUTION_TRACE_CORPUS_INTERFACE,
    GROUND_TRUTH_KINDS,
    PROGRAM_TRACE_ADMISSION_INTERFACE,
    PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE,
    PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE,
    PROGRAM_TRACE_PARTITIONS,
    PROGRAM_TRACE_RECIPE_SCHEMA_VERSION,
    PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE,
    TRAINING_UNAVAILABLE,
    ProgramTraceAdmission,
    ProgramTraceAdmissionError,
    ProgramTraceAdmissionStatus,
    ProgramTraceCorpusError,
    ProgramTraceCorpusManifest,
    ProgramTraceCorpusStatus,
    ProgramTraceLeakageAudit,
    ProgramTraceLeakageError,
    ProgramTraceLeakageStatus,
    ProgramTracePartition,
    ProgramTraceRow,
    admit_program_trace_row,
    audit_program_trace_leakage,
    build_program_trace_corpus,
    default_program_trace_corpus_fixture_path,
    expand_program_trace_recipe,
    load_program_trace_reject_recipes,
    training_unavailable_program_trace_corpus,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "program_world_trace_corpus.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _expand(recipe: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload = dict(recipe)
    payload.update(overrides)
    defaults = _fixture()["defaults"]
    return expand_program_trace_recipe(
        payload, defaults=defaults, corpus_id="program-world-trace-corpus-v1"
    )


def _admitted_recipe(**overrides: Any) -> dict[str, Any]:
    recipe = {
        "row_id": "train-hermetic-add",
        "partition": "training",
        "source_kind": "first_party_hermetic",
        "family_id": "fam-arith-add",
        "task_id": "task-arith-add",
        "function_id": "fn-add",
        "ground_truth_kind": "runtime",
        "labels": {"expected_symbol": "add", "expected_outcome": "return"},
    }
    recipe.update(overrides)
    return _expand(recipe)


# ---------------------------------------------------------------------------
# Interface / fixture identity
# ---------------------------------------------------------------------------


def test_interface_and_schema_versions_are_pinned() -> None:
    unavailable = training_unavailable_program_trace_corpus()
    assert EXECUTION_TRACE_CORPUS_INTERFACE == "ExecutionTraceCorpus@1"
    assert PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE == "ProgramTraceCorpusManifest@1"
    assert PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE == "ProgramTraceSplitManifest@1"
    assert PROGRAM_TRACE_ADMISSION_INTERFACE == "ProgramTraceAdmission@1"
    assert PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE == "ProgramTraceLeakageAudit@1"
    assert unavailable.interface == PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
    assert unavailable.schema_version == "program-trace-corpus/v1"
    assert tuple(PROGRAM_TRACE_PARTITIONS) == (
        "training",
        "development",
        "held_out",
        "adversarial",
        "cross_repository",
        "ood",
    )


def test_compact_fixture_is_a_recipe_not_a_bulk_envelope_dump() -> None:
    fixture = _fixture()
    assert fixture["schema"] == PROGRAM_TRACE_RECIPE_SCHEMA_VERSION
    assert fixture["interface"] == EXECUTION_TRACE_CORPUS_INTERFACE
    assert fixture["task_id"] == "SAWM-023"
    assert "recipes" in fixture
    assert "rows" not in fixture
    assert default_program_trace_corpus_fixture_path() == FIXTURE_PATH
    for recipe in fixture["recipes"]:
        assert "content_cid" not in recipe
        assert "trace_cid" not in recipe
        assert "tree_cid" not in recipe


def test_import_has_no_network_or_model_side_effects() -> None:
    import ipfs_datasets_py.logic.proof_corpus.program_trace_corpus as module

    assert module.IMPORT_NETWORK_PERFORMED is False
    assert module.IMPORT_SOCKET_PERFORMED is False
    assert module.IMPORT_MODEL_LOAD_PERFORMED is False
    assert module.IMPORT_SIDE_EFFECTS_PERFORMED is False
    source = Path(module.__file__).read_text(encoding="utf-8")
    for banned in (
        "socket.create_connection",
        "urllib.request",
        "requests.get",
        "torch.load",
        "transformers",
    ):
        assert banned not in source


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------


def test_admit_valid_hermetic_row() -> None:
    admission, row = admit_program_trace_row(_admitted_recipe())
    assert admission.status is ProgramTraceAdmissionStatus.ADMITTED
    assert row is not None
    assert admission.rights_admitted is True
    assert admission.privacy_admitted is True
    assert admission.exact_tree_bound is True
    assert admission.source_lineage_bound is True
    assert admission.labels_are_ground_truth is True
    assert row.partition is ProgramTracePartition.TRAINING
    assert row.tree_cid.startswith("b")
    assert row.language == "python"
    assert row.ground_truth_kind in GROUND_TRUTH_KINDS
    round_trip = ProgramTraceRow.from_dict(row.to_dict())
    assert round_trip.content_cid == row.content_cid
    assert ProgramTraceAdmission.from_dict(admission.to_dict()).content_cid == (
        admission.content_cid
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"rights_class": "unknown", "source_kind": "unknown_rights"}, "unknown_rights"),
        ({"privacy_class": "private"}, "privacy_not_admitted"),
        ({"tree_cid": ""}, "missing_tree_cid"),
        ({"tree_cid": "latest"}, "invalid_tree_cid"),
        ({"source_kind": "hidden_test"}, "hidden_test"),
        ({"source_kind": "private_chain_of_thought"}, "private_reasoning"),
        ({"source_kind": "unadmitted_production"}, "unadmitted_source"),
        ({"source_kind": "tenant_private"}, "tenant_private"),
        ({"ground_truth_kind": "model_nomination"}, "model_nomination_label"),
        (
            {"labels": {"expected_outcome": "password=super-secret-value"}},
            "secret_material",
        ),
    ],
)
def test_admit_rejects_excluded_material(
    overrides: dict[str, Any], reason: str
) -> None:
    admission, row = admit_program_trace_row(_admitted_recipe(**overrides))
    assert row is None
    assert admission.status is ProgramTraceAdmissionStatus.REJECTED
    assert reason in admission.reasons


def test_admit_rejects_model_nomination_label_keys() -> None:
    payload = _admitted_recipe()
    payload["labels"] = {"model_nomination": "call_target"}
    admission, row = admit_program_trace_row(payload)
    assert row is None
    assert "model_nomination_label" in admission.reasons


def test_admit_raise_on_reject() -> None:
    with pytest.raises(ProgramTraceAdmissionError, match="unknown_rights"):
        admit_program_trace_row(
            _admitted_recipe(rights_class="unknown"), raise_on_reject=True
        )


def test_reject_recipes_from_fixture_are_excluded() -> None:
    recipes = load_program_trace_reject_recipes(FIXTURE_PATH)
    assert recipes
    for recipe in recipes:
        admission, row = admit_program_trace_row(recipe)
        assert row is None
        assert admission.status is ProgramTraceAdmissionStatus.REJECTED
        expected = set(recipe["expect_reasons"])
        assert expected.issubset(set(admission.reasons)), (
            f"{recipe['row_id']} expected {expected} in {admission.reasons}"
        )


# ---------------------------------------------------------------------------
# Build / splits / leakage
# ---------------------------------------------------------------------------


def test_build_fixture_corpus_admits_every_row_and_all_partitions() -> None:
    corpus = build_program_trace_corpus(FIXTURE_PATH)
    assert corpus.status is ProgramTraceCorpusStatus.ADMITTED
    assert corpus.training_available is True
    assert corpus.contracts_available is True
    assert corpus.baselines_available is True
    assert corpus.language == "python"
    assert corpus.task_id == "SAWM-023"
    assert corpus.row_count == len(_fixture()["recipes"])
    partitions = {row.partition_value for row in corpus.rows}
    assert partitions == set(PROGRAM_TRACE_PARTITIONS)
    source_kinds = {row.source_kind for row in corpus.rows}
    for required in (
        "first_party_hermetic",
        "synthetic_program",
        "adversarial_mutant",
        "instrumented_test",
    ):
        assert required in source_kinds
    assert source_kinds <= ADMITTED_SOURCE_KINDS
    polarities = {row.polarity for row in corpus.rows}
    assert "negative" in polarities
    assert corpus.leakage_audit is not None
    assert corpus.leakage_audit.status is ProgramTraceLeakageStatus.PASS
    assert corpus.splits is not None
    assert corpus.splits.disjoint is True
    round_trip = ProgramTraceCorpusManifest.from_dict(corpus.to_dict())
    assert round_trip.content_cid == corpus.content_cid


def test_every_admitted_row_is_rights_privacy_and_tree_bound() -> None:
    corpus = build_program_trace_corpus(FIXTURE_PATH)
    for row in corpus.rows:
        admission, admitted = admit_program_trace_row(row)
        assert admitted is not None
        assert admission.rights_admitted is True
        assert admission.privacy_admitted is True
        assert admission.exact_tree_bound is True
        assert admission.labels_are_ground_truth is True
        assert row.privacy_class == "public"
        assert row.rights_class in {
            "first_party_hermetic",
            "synthetic_generated",
            "adversarial_generated",
            "observed_first_party",
            "admitted_public",
            "rights_cleared_review",
        }
        assert row.tree_cid.startswith("b")
        assert "latest" not in row.tree_cid
        assert row.ground_truth_kind in GROUND_TRUTH_KINDS
        assert "model_nomination" not in row.labels
        grouping = row.grouping_values()
        for axis in (
            "repository_id",
            "commit_id",
            "family_id",
            "function_id",
        ):
            assert grouping[axis]


def test_grouping_axes_and_negative_examples_are_present() -> None:
    corpus = build_program_trace_corpus(FIXTURE_PATH)
    axes = {
        "failure_id": False,
        "mutant_id": False,
        "proof_id": False,
        "procedure_id": False,
        "task_id": False,
    }
    negatives = 0
    for row in corpus.rows:
        grouping = row.grouping_values()
        for axis in axes:
            if grouping[axis]:
                axes[axis] = True
        if row.polarity == "negative":
            negatives += 1
            assert row.ground_truth_kind in {"negative", "test"}
    assert negatives >= 1
    assert all(axes.values()), f"missing grouping axes: {axes}"


def test_leakage_audit_passes_on_admitted_fixture() -> None:
    corpus = build_program_trace_corpus(FIXTURE_PATH)
    audit = audit_program_trace_leakage(corpus.rows)
    assert audit.status is ProgramTraceLeakageStatus.PASS
    assert audit.disjoint is True
    assert audit.leaked_families == ()
    assert audit.leaked_grouping == ()
    assert audit.cross_repository_overlap == ()
    assert ProgramTraceLeakageAudit.from_dict(audit.to_dict()).content_cid == (
        audit.content_cid
    )


def test_related_family_cannot_leak_across_partitions() -> None:
    left = ProgramTraceRow.from_dict(_admitted_recipe())
    right_payload = _admitted_recipe(
        row_id="held-leaked-add",
        partition="held_out",
        family_id="fam-arith-add",
        function_id="fn-add",
        task_id="task-arith-add",
    )
    right = ProgramTraceRow.from_dict(right_payload)
    audit = audit_program_trace_leakage((left, right))
    assert audit.status is ProgramTraceLeakageStatus.FAIL
    assert audit.disjoint is False
    assert "fam-arith-add" in audit.leaked_families
    assert any(item.startswith("function_id:fn-add") for item in audit.leaked_grouping)
    with pytest.raises(ProgramTraceLeakageError, match="leak"):
        build_program_trace_corpus((left.to_dict(), right_payload))


def test_cross_repository_rows_cannot_share_repository_with_training() -> None:
    train = ProgramTraceRow.from_dict(_admitted_recipe())
    leaked = ProgramTraceRow.from_dict(
        _admitted_recipe(
            row_id="cross-leaked-repo",
            partition="cross_repository",
            source_kind="admitted_public",
            rights_class="admitted_public",
            repository_id="ipfs_datasets_py",
            family_id="fam-ext-overlap",
            function_id="fn-ext-overlap",
            task_id="task-ext-overlap",
            tree_seed="sawm-023-cross-leak-tree",
        )
    )
    audit = audit_program_trace_leakage((train, leaked))
    assert audit.status is ProgramTraceLeakageStatus.FAIL
    assert "ipfs_datasets_py" in audit.cross_repository_overlap


def test_unknown_row_fields_fail_closed() -> None:
    payload = _admitted_recipe()
    payload["unexpected"] = "nope"
    with pytest.raises(ProgramTraceCorpusError, match="unknown row field"):
        ProgramTraceRow.from_dict(payload)


def test_duplicate_row_id_fails_closed() -> None:
    row = _admitted_recipe()
    with pytest.raises(ProgramTraceCorpusError, match="duplicate row_id"):
        build_program_trace_corpus((row, dict(row)))


# ---------------------------------------------------------------------------
# Absent corpus
# ---------------------------------------------------------------------------


def test_default_fixture_path_builds_admitted_corpus() -> None:
    corpus = build_program_trace_corpus()
    assert corpus.status is ProgramTraceCorpusStatus.ADMITTED
    assert corpus.row_count == len(_fixture()["recipes"])


def test_empty_source_returns_training_unavailable_without_blocking_contracts() -> None:
    corpus = build_program_trace_corpus([])
    assert corpus.status is ProgramTraceCorpusStatus.TRAINING_UNAVAILABLE
    assert corpus.training_status == TRAINING_UNAVAILABLE
    assert corpus.training_available is False
    assert corpus.contracts_available is True
    assert corpus.baselines_available is True
    assert corpus.row_count == 0
    assert corpus.reason == "absent_corpus"


def test_missing_fixture_returns_training_unavailable() -> None:
    missing = FIXTURE_PATH.parent / "absent-program-world-trace-corpus.json"
    assert not missing.exists()
    corpus = build_program_trace_corpus(path=missing)
    assert corpus.status is ProgramTraceCorpusStatus.TRAINING_UNAVAILABLE
    assert corpus.contracts_available is True
    assert corpus.baselines_available is True
    assert corpus.training_available is False


def test_training_unavailable_round_trip() -> None:
    corpus = training_unavailable_program_trace_corpus()
    restored = ProgramTraceCorpusManifest.from_dict(corpus.to_dict())
    assert restored.content_cid == corpus.content_cid
    assert restored.training_status == TRAINING_UNAVAILABLE
    assert restored.contracts_available is True
    assert restored.baselines_available is True


def test_training_unavailable_cannot_claim_training_or_drop_contracts() -> None:
    with pytest.raises(ProgramTraceCorpusError, match="contracts or baselines"):
        ProgramTraceCorpusManifest(
            status=ProgramTraceCorpusStatus.TRAINING_UNAVAILABLE,
            contracts_available=False,
            baselines_available=True,
        )
    with pytest.raises(ProgramTraceCorpusError, match="training_available"):
        ProgramTraceCorpusManifest(
            status=ProgramTraceCorpusStatus.TRAINING_UNAVAILABLE,
            training_available=True,
            reason="absent_corpus",
        )
