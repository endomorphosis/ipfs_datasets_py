"""Unit tests for the rights-admitted execution-trace corpus (SAWM-023)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    decode_and_recompute_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.proof_corpus.program_trace_corpus import (
    ADMITTED_PRIVACY_CLASSES,
    ADMITTED_RIGHTS_CLASSES,
    CORPUS_ADMISSION_EVIDENCE,
    DEVELOPMENT_PARTITIONS,
    EVALUATION_PARTITIONS,
    EXECUTION_TRACE_CORPUS_INTERFACE,
    EXECUTION_TRACE_CORPUS_SCHEMA,
    GROUPING_KEYS,
    IMPORT_DATABASE_PERFORMED,
    IMPORT_INSTALLER_PERFORMED,
    IMPORT_MODEL_LOAD_PERFORMED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_PERFORMED,
    IMPORT_SUBPROCESS_PERFORMED,
    IMPORT_WATCHER_PERFORMED,
    LABEL_AUTHORITIES,
    LEAKAGE_GROUPING_KEYS,
    PARTITIONS,
    PROGRAM_TRACE_ADMISSION_INTERFACE,
    PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE,
    PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE,
    PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE,
    SPLIT_LEAKAGE_EVIDENCE,
    TRAINING_UNAVAILABLE,
    AdmissionVerdict,
    LabelAuthority,
    ProgramTraceAdmission,
    ProgramTraceCorpusError,
    ProgramTraceCorpusLeakageError,
    ProgramTraceCorpusManifest,
    QueryFamily,
    SplitRole,
    TracePartition,
    admit_program_trace_row,
    audit_program_trace_leakage,
    build_program_trace_corpus,
    default_program_trace_corpus_path,
    load_program_trace_corpus_fixture,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "program_world_trace_corpus.json"
)
NEGATIVE_REASON = {
    "neg-unknown-rights": "unknown_rights",
    "neg-hidden-test": "hidden_test",
    "neg-private-reasoning": "private_reasoning",
    "neg-credentials": "credentials",
    "neg-unadmitted-production": "unadmitted_source",
    "neg-tenant-private": "tenant_private",
    "neg-private-witness": "private_witness",
    "neg-arbitrary-transcript": "arbitrary_transcript",
    "neg-model-nomination": "model_nomination_label",
    "neg-missing-tree": "missing_exact_tree_binding",
    "neg-restricted-privacy": "privacy_not_admitted",
}


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _clone_row(row_id: str, **overrides: Any) -> dict[str, Any]:
    row = dict(next(item for item in _fixture()["rows"] if item["row_id"] == row_id))
    grouping = dict(row["grouping"])
    grouping.update(overrides.pop("grouping", {}))
    row["grouping"] = grouping
    row.update(overrides)
    return row


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert EXECUTION_TRACE_CORPUS_INTERFACE == "ExecutionTraceCorpus@1"
    assert EXECUTION_TRACE_CORPUS_SCHEMA == "sawm/trace-corpus@1"
    assert PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE == "ProgramTraceCorpusManifest@1"
    assert PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE == "ProgramTraceSplitManifest@1"
    assert PROGRAM_TRACE_ADMISSION_INTERFACE == "ProgramTraceAdmission@1"
    assert PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE == "ProgramTraceLeakageAudit@1"
    assert CORPUS_ADMISSION_EVIDENCE == "sawm/corpus-admission@1"
    assert SPLIT_LEAKAGE_EVIDENCE == "sawm/split-leakage@1"
    assert callable(build_program_trace_corpus)
    assert callable(admit_program_trace_row)
    assert callable(audit_program_trace_leakage)
    assert ProgramTraceCorpusManifest.INTERFACE == PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
    assert ProgramTraceAdmission.INTERFACE == PROGRAM_TRACE_ADMISSION_INTERFACE
    assert tuple(item.value for item in TracePartition) == PARTITIONS


def test_import_flags_record_no_side_effects() -> None:
    assert IMPORT_NETWORK_PERFORMED is False
    assert IMPORT_SOCKET_PERFORMED is False
    assert IMPORT_INSTALLER_PERFORMED is False
    assert IMPORT_SUBPROCESS_PERFORMED is False
    assert IMPORT_DATABASE_PERFORMED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_PERFORMED is False
    assert IMPORT_MODEL_LOAD_PERFORMED is False
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False


def test_fixture_is_compact_recipe_not_full_envelopes() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    payload = _fixture()
    assert len(raw.encode("utf-8")) < 32_768
    assert "event_cids" not in raw
    assert "raw_execution_state" not in raw
    assert payload["interface"] == EXECUTION_TRACE_CORPUS_INTERFACE
    assert payload["schema_version"] == EXECUTION_TRACE_CORPUS_SCHEMA
    assert payload["partitions"] == list(PARTITIONS)
    assert payload["grouping_keys"] == list(GROUPING_KEYS)
    assert payload["leakage_keys"] == list(LEAKAGE_GROUPING_KEYS)
    assert payload["rows"], "fixture must include admitted recipes"
    assert payload["negative_examples"], "fixture must include exclusion recipes"
    for row in payload["rows"]:
        assert "events" not in row
        assert "payload" not in row
        assert set(row["grouping"]) <= set(GROUPING_KEYS)


def test_default_fixture_path_matches_declared_output() -> None:
    assert default_program_trace_corpus_path() == FIXTURE_PATH
    loaded = load_program_trace_corpus_fixture()
    assert loaded is not None
    assert loaded["corpus_id"] == "program-world-trace-corpus-v1"


def test_build_default_fixture_admits_every_row() -> None:
    manifest = build_program_trace_corpus()
    assert manifest.availability == "admitted"
    assert manifest.training_unavailable is False
    assert manifest.contracts_unblocked is True
    assert manifest.baselines_unblocked is True
    assert manifest.language == "python"
    assert manifest.task_id == "SAWM-023"
    assert {row["row_id"] for row in manifest.rows} == {
        item["row_id"] for item in _fixture()["rows"]
    }
    assert all(row["language"] == "python" for row in manifest.rows)
    encoded = manifest.to_dict()
    assert encoded["interface"] == PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
    assert CORPUS_ADMISSION_EVIDENCE in encoded["evidence"]
    assert SPLIT_LEAKAGE_EVIDENCE in encoded["evidence"]
    round_trip = ProgramTraceCorpusManifest.from_dict(encoded)
    assert round_trip.corpus_cid == manifest.corpus_cid
    decode_and_recompute_structured(manifest.corpus_cid, manifest.identity_payload())


def test_every_admitted_row_is_rights_privacy_and_exact_tree_bound() -> None:
    manifest = build_program_trace_corpus(FIXTURE_PATH)
    assert manifest.leakage_audit is not None
    assert manifest.leakage_audit.passed is True
    source_classes = {row["source_class"] for row in manifest.rows}
    rights_classes = {row["rights_class"] for row in manifest.rows}
    assert "first_party_hermetic" in source_classes
    assert "synthetic_program" in source_classes
    assert "adversarial_mutant" in source_classes
    assert "observed" in source_classes
    assert rights_classes <= ADMITTED_RIGHTS_CLASSES
    assert len(manifest.rows) == len(manifest.admissions)
    for row, admission in zip(manifest.rows, manifest.admissions):
        assert row["rights_admitted"] is True
        assert row["privacy_admitted"] is True
        assert row["exact_tree_bound"] is True
        assert row["privacy_class"] in ADMITTED_PRIVACY_CLASSES
        assert row["rights_class"] in ADMITTED_RIGHTS_CLASSES
        assert row["label_authority"] in LABEL_AUTHORITIES
        assert row["label_authority"] != "model_nomination"
        assert "model_nomination" not in row
        validate_cid(row["tree_cid"])
        validate_cid(row["source_cid"])
        validate_cid(row["environment_binding_cid"])
        validate_cid(row["execution_trace_cid"])
        assert admission.verdict == AdmissionVerdict.ADMITTED.value
        assert admission.rights_admitted is True
        assert admission.privacy_admitted is True
        assert admission.exact_tree_bound is True
        assert admission.model_nomination_is_label is False
        assert admission.lineage["tree_cid"] == row["tree_cid"]
        assert admission.lineage["rights_class"] == row["rights_class"]
        assert admission.lineage["privacy_class"] == row["privacy_class"]
        assert admission.lineage["model_nomination_is_label"] is False
        for key in GROUPING_KEYS:
            assert key in row


def test_six_disjoint_partitions_are_nonempty_and_role_bound() -> None:
    manifest = build_program_trace_corpus()
    assert set(manifest.splits) == set(PARTITIONS)
    seen: set[str] = set()
    for name in PARTITIONS:
        split = manifest.splits[name]
        assert split.partition == name
        assert split.row_ids, f"{name} must be nonempty"
        expected_role = (
            SplitRole.DEVELOPMENT.value
            if name in DEVELOPMENT_PARTITIONS
            else SplitRole.EVALUATION.value
        )
        assert split.role == expected_role
        overlap = seen.intersection(split.row_ids)
        assert not overlap, f"row leaked across partitions: {sorted(overlap)}"
        seen.update(split.row_ids)
    assert seen == {row["row_id"] for row in manifest.rows}
    assert DEVELOPMENT_PARTITIONS.isdisjoint(EVALUATION_PARTITIONS)
    assert DEVELOPMENT_PARTITIONS | EVALUATION_PARTITIONS == set(PARTITIONS)


def test_related_families_do_not_leak_across_partitions() -> None:
    manifest = build_program_trace_corpus()
    audit = audit_program_trace_leakage(manifest)
    assert audit.passed is True
    assert audit.leaked_families == ()
    assert audit.findings == ()
    family_to_partition: dict[str, str] = {}
    key_to_partition: dict[tuple[str, str], str] = {}
    for row in manifest.rows:
        family = row["family_id"]
        partition = row["partition"]
        previous = family_to_partition.get(family)
        assert previous in (None, partition), family
        family_to_partition[family] = partition
        for key in LEAKAGE_GROUPING_KEYS:
            value = row.get(key) or ""
            if not value:
                continue
            seen = key_to_partition.get((key, value))
            assert seen in (None, partition), (key, value)
            key_to_partition[(key, value)] = partition
    intra = {
        row["repository"]
        for row in manifest.rows
        if row["partition"] in {"training", "development", "held_out"}
    }
    cross = {
        row["repository"]
        for row in manifest.rows
        if row["partition"] == "cross_repository"
    }
    assert intra.isdisjoint(cross)


def test_family_leakage_fails_closed() -> None:
    leaked = [
        _clone_row("train-hermetic-add"),
        _clone_row("train-hermetic-add", row_id="held-hermetic-add", partition="held_out"),
    ]
    admitted = [admit_program_trace_row(row) for row in leaked]
    assert all(
        item.verdict == AdmissionVerdict.ADMITTED.value and item.row is not None
        for item in admitted
    )
    audit = audit_program_trace_leakage([item.row for item in admitted])
    assert audit.passed is False
    assert "family:hermetic-add" in audit.leaked_families
    with pytest.raises(ProgramTraceCorpusLeakageError, match="related families"):
        build_program_trace_corpus(leaked)


def test_related_function_cannot_leak_across_partitions() -> None:
    leaked = [
        _clone_row("train-synthetic-mul"),
        _clone_row(
            "held-static-edge",
            row_id="held-synthetic-mul-leak",
            family_id="family:held-mul-leak",
            grouping={"function": "mul", "task": "task:held-mul-leak"},
        ),
    ]
    admitted = [admit_program_trace_row(row) for row in leaked]
    assert all(
        item.verdict == AdmissionVerdict.ADMITTED.value and item.row is not None
        for item in admitted
    )
    audit = audit_program_trace_leakage([item.row for item in admitted])
    assert audit.passed is False
    assert "function" in audit.leaked_keys
    with pytest.raises(ProgramTraceCorpusLeakageError):
        build_program_trace_corpus(leaked)


def test_model_nominations_are_never_labels() -> None:
    admitted = admit_program_trace_row(_clone_row("train-hermetic-add"))
    assert admitted.verdict == AdmissionVerdict.ADMITTED.value
    assert admitted.row is not None
    assert admitted.row["label_authority"] == LabelAuthority.RUNTIME.value
    assert "model_nomination" not in admitted.row

    rejected = admit_program_trace_row(
        _clone_row(
            "train-hermetic-add",
            row_id="neg-inline-model-label",
            label_authority="model_nomination",
            label="model_guess",
            model_nomination="model_guess",
        )
    )
    assert rejected.verdict == AdmissionVerdict.REJECTED.value
    assert "model_nomination_label" in rejected.reason_codes
    assert rejected.model_nomination_is_label is True

    advisory = admit_program_trace_row(
        _clone_row(
            "train-hermetic-add",
            row_id="advisory-nomination",
            model_nomination="ignored_guess",
        )
    )
    assert advisory.verdict == AdmissionVerdict.ADMITTED.value
    assert advisory.row is not None
    assert advisory.row["label"] != "ignored_guess"
    assert "model_nomination" not in advisory.row
    assert advisory.model_nomination_is_label is False


def test_negative_examples_are_excluded_from_the_corpus() -> None:
    fixture = _fixture()
    manifest = build_program_trace_corpus(fixture)
    admitted_ids = {row["row_id"] for row in manifest.rows}
    for example in fixture["negative_examples"]:
        assert example["row_id"] not in admitted_ids
        admission = admit_program_trace_row(example)
        assert admission.verdict == AdmissionVerdict.REJECTED.value
        expected = NEGATIVE_REASON[example["row_id"]]
        assert expected in admission.reason_codes, (
            example["row_id"],
            admission.reason_codes,
        )
        assert admission.model_nomination_is_label is (
            example["row_id"] == "neg-model-nomination"
        )


@pytest.mark.parametrize(
    ("row_id", "needle"),
    [
        ("neg-unknown-rights", "unknown_rights"),
        ("neg-hidden-test", "hidden_test"),
        ("neg-private-reasoning", "private_reasoning"),
        ("neg-credentials", "forbidden_private_content"),
        ("neg-unadmitted-production", "unadmitted_source"),
        ("neg-tenant-private", "tenant_private"),
        ("neg-private-witness", "private_witness"),
        ("neg-arbitrary-transcript", "arbitrary_transcript"),
        ("neg-missing-tree", "missing_exact_tree_binding"),
        ("neg-restricted-privacy", "privacy_not_admitted"),
    ],
)
def test_secret_hidden_private_and_unadmitted_sources_fail_closed(
    row_id: str, needle: str
) -> None:
    example = next(
        item for item in _fixture()["negative_examples"] if item["row_id"] == row_id
    )
    admission = admit_program_trace_row(example)
    assert admission.verdict == AdmissionVerdict.REJECTED.value
    assert needle in admission.reason_codes
    assert admission.row is None


def test_absent_corpus_returns_training_unavailable_without_blocking() -> None:
    missing = build_program_trace_corpus(
        Path("/tmp/sawm-023-absent-program-world-trace-corpus.json")
    )
    empty = build_program_trace_corpus([])
    declared = build_program_trace_corpus(
        {"availability": TRAINING_UNAVAILABLE, "rows": []}
    )
    absent_row = admit_program_trace_row(None)
    for manifest in (missing, empty, declared):
        assert manifest.availability == TRAINING_UNAVAILABLE
        assert manifest.training_unavailable is True
        assert TRAINING_UNAVAILABLE in manifest.reason_codes
        assert manifest.rows == ()
        assert manifest.contracts_unblocked is True
        assert manifest.baselines_unblocked is True
        assert set(manifest.splits) == set(PARTITIONS)
        assert manifest.leakage_audit is not None
        assert manifest.leakage_audit.passed is True
    assert absent_row.verdict == AdmissionVerdict.TRAINING_UNAVAILABLE.value
    assert TRAINING_UNAVAILABLE in absent_row.reason_codes


def test_training_unavailable_does_not_raise_for_contracts_or_baselines() -> None:
    manifest = build_program_trace_corpus({"rows": []})
    assert manifest.contracts_unblocked is True
    assert manifest.baselines_unblocked is True
    with pytest.raises(ProgramTraceCorpusError, match="must not block"):
        ProgramTraceCorpusManifest(
            availability=TRAINING_UNAVAILABLE,
            contracts_unblocked=False,
            baselines_unblocked=True,
        )


def test_unknown_fields_and_non_python_language_are_rejected() -> None:
    unknown = admit_program_trace_row(
        _clone_row("train-hermetic-add", row_id="neg-unknown-field", embedding="x")
    )
    assert unknown.verdict == AdmissionVerdict.REJECTED.value
    assert "unknown_fields" in unknown.reason_codes
    language = admit_program_trace_row(
        _clone_row("train-hermetic-add", row_id="neg-rust", language="rust")
    )
    assert language.verdict == AdmissionVerdict.REJECTED.value
    assert "language_unavailable" in language.reason_codes


def test_query_family_vocabulary_is_closed() -> None:
    assert QueryFamily.NEXT_CALL.value == "next_call"
    rejected = admit_program_trace_row(
        _clone_row(
            "train-hermetic-add",
            row_id="neg-knn",
            query_family="nearest_call",
        )
    )
    assert rejected.verdict == AdmissionVerdict.REJECTED.value
    assert "normalization_failed" in rejected.reason_codes


def test_malformed_source_fails_closed() -> None:
    with pytest.raises(ProgramTraceCorpusError, match="must be a mapping"):
        admit_program_trace_row(["not-a-row"])  # type: ignore[arg-type]
    with pytest.raises(ProgramTraceCorpusError, match="not a mapping"):
        build_program_trace_corpus(3)  # type: ignore[arg-type]


def test_duplicate_row_ids_fail_closed() -> None:
    with pytest.raises(ProgramTraceCorpusError, match="duplicate row_id"):
        build_program_trace_corpus(
            [_clone_row("train-hermetic-add"), _clone_row("train-hermetic-add")]
        )
