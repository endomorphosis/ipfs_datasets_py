"""Rights-admitted execution-trace corpus (SAWM-023)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.proof_corpus.program_trace_corpus import (
    IMPORT_DATABASE_PERFORMED,
    IMPORT_INSTALLER_PERFORMED,
    IMPORT_MODEL_LOAD_PERFORMED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_PERFORMED,
    IMPORT_SUBPROCESS_PERFORMED,
    IMPORT_WATCHER_PERFORMED,
    MIN_PROMOTION_ROWS,
    PARTITIONS,
    PROGRAM_TRACE_ADMISSION_INTERFACE,
    PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE,
    PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE,
    PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE,
    TRAINING_UNAVAILABLE,
    ProgramTraceAdmission,
    ProgramTraceCorpusError,
    ProgramTraceCorpusManifest,
    ProgramTraceLeakageAudit,
    ProgramTraceSplitManifest,
    admit_program_trace_row,
    audit_program_trace_leakage,
    build_program_trace_corpus,
    default_fixture_path,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    TraceCollectionPolicy,
    record_python_execution_trace,
)

_PACKAGE = "ipfs_datasets_py.logic.proof_corpus.program_trace_corpus"
_REPO_ROOT = Path(__file__).resolve().parents[5]
_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "program_world_trace_corpus.json"
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _groups(function: str, **overrides: str) -> dict[str, str]:
    payload = {
        "repository": "ipfs_datasets_py",
        "commit": "fixture-tree-v1",
        "task": "SAWM-023",
        "function": function,
        "failure": "none",
        "mutant": "none",
        "proof": "none",
        "procedure": f"{function}-return",
    }
    payload.update(overrides)
    return payload


def _row(row_id: str, partition: str, function: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "row_id": row_id,
        "origin": "hermetic",
        "partition": partition,
        "groups": _groups(function),
        "rights": "first-party-admitted",
        "privacy_class": "public",
        "source_kind": "first-party-hermetic",
        "event_kinds": ["call", "return"],
        "label_kind": "observed_event_sequence",
    }
    payload.update(overrides)
    return payload


def _add(left: int, right: int) -> int:
    return left + right


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE == "ProgramTraceCorpusManifest@1"
    assert PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE == "ProgramTraceSplitManifest@1"
    assert PROGRAM_TRACE_ADMISSION_INTERFACE == "ProgramTraceAdmission@1"
    assert PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE == "ProgramTraceLeakageAudit@1"
    assert callable(build_program_trace_corpus)
    assert callable(admit_program_trace_row)
    assert callable(audit_program_trace_leakage)
    assert ProgramTraceCorpusManifest.INTERFACE == PROGRAM_TRACE_CORPUS_MANIFEST_INTERFACE
    assert ProgramTraceSplitManifest.INTERFACE == PROGRAM_TRACE_SPLIT_MANIFEST_INTERFACE
    assert ProgramTraceAdmission.INTERFACE == PROGRAM_TRACE_ADMISSION_INTERFACE
    assert ProgramTraceLeakageAudit.INTERFACE == PROGRAM_TRACE_LEAKAGE_AUDIT_INTERFACE
    assert PARTITIONS == (
        "training",
        "development",
        "held_out",
        "adversarial",
        "cross_repository",
        "ood",
    )


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


def test_cold_import_is_hermetic() -> None:
    script = f"""\
import json, os, sys, threading
before = dict(os.environ)
before_modules = set(sys.modules)
effects = []
def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(name)
    return call
os.system = forbidden("os.system")
def _start(self, *args, **kwargs):
    effects.append("thread")
    raise AssertionError("thread")
threading.Thread.start = _start
def audit(event, args):
    if event == "open" and len(args) > 2:
        flags = args[2]
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = str(args[0])
            if "pycache" in path or path.endswith(".pyc"):
                return
            effects.append("write:" + path)
            raise AssertionError("write")
    if event in {{"socket.connect", "socket.getaddrinfo", "subprocess.Popen"}}:
        effects.append(event)
        raise AssertionError(event)
sys.addaudithook(audit)
import {_PACKAGE} as corpus
assert corpus.IMPORT_SIDE_EFFECTS_PERFORMED is False
assert os.environ == before
assert not effects, effects
banned = {{"torch", "transformers", "requests", "httpx", "duckdb", "watchdog", "aiohttp"}}
assert not ((set(sys.modules) - before_modules) & banned)
print(json.dumps({{"ok": True}}))
"""
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(_REPO_ROOT / "ipfs_datasets_py"),
            str(_REPO_ROOT / "ipfs_kit_py"),
            str(_REPO_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_fixture_build_admits_six_disjoint_partitions() -> None:
    assert default_fixture_path() == _FIXTURE
    corpus = build_program_trace_corpus()
    assert corpus.language == "python"
    assert corpus.contracts_unblocked is True
    assert corpus.baselines_unblocked is True
    assert corpus.training_unavailable is True
    assert corpus.learned_path_status == TRAINING_UNAVAILABLE
    assert corpus.checkpoint_lineage_present is False
    assert len(corpus.rows) < MIN_PROMOTION_ROWS
    assert {row.partition for row in corpus.rows} == set(PARTITIONS)
    assert len(corpus.splits) == 6
    seen: set[str] = set()
    for split in corpus.splits:
        overlap = seen.intersection(split.row_ids)
        assert not overlap
        seen.update(split.row_ids)
        rebuilt = corpus.split(split.partition)
        assert rebuilt.split_cid == split.split_cid
        assert list(rebuilt.row_ids) == sorted(rebuilt.row_ids)
    assert corpus.leakage_audit.passed is True
    assert not corpus.leakage_audit.violations
    encoded = json.dumps(corpus.to_dict())
    assert "password" not in encoded
    assert "must-not-enter-corpus" not in encoded
    assert "raw_bodies" not in encoded or '"includes_raw_bodies":false' in encoded.replace(" ", "")
    for row in corpus.rows:
        assert row.rights in {
            "first-party-admitted",
            "synthetic-admitted",
            "public-rights-cleared",
        }
        assert row.privacy_class == "public"
        assert row.includes_raw_bodies is False
        assert row.tree_cid == corpus.tree_cid or row.partition == "cross_repository"
        assert row.public_trace_cid
        assert row.source_cid
        assert row.label_kind != "model_nomination"


def test_each_row_has_rights_privacy_and_source_lineage() -> None:
    corpus = build_program_trace_corpus()
    for row in corpus.rows:
        admission = admit_program_trace_row(row.to_dict())
        assert admission.admitted is True
        assert admission.rights_status == row.rights
        assert admission.privacy_status == row.privacy_class
        assert admission.lineage_status == row.source_kind
        assert admission.tree_cid == row.tree_cid
        payload = row.identity_payload()
        assert payload["rights"]
        assert payload["privacy_class"]
        assert payload["source_kind"]
        assert payload["tree_cid"]
        assert "model_nomination" not in payload.values()


def test_exclusions_cover_secret_hidden_private_unadmitted_and_nominations() -> None:
    corpus = build_program_trace_corpus()
    excluded = {item.row_id: item for item in corpus.excluded}
    assert excluded["exclude:secret"].admitted is False
    assert excluded["exclude:hidden-test"].admitted is False
    assert excluded["exclude:private-reasoning"].admitted is False
    assert excluded["exclude:unadmitted-source"].admitted is False
    assert excluded["exclude:model-nomination"].admitted is False
    audit = corpus.leakage_audit
    assert "exclude:secret" in audit.secret_exclusions
    assert "exclude:hidden-test" in audit.hidden_test_exclusions
    assert "exclude:private-reasoning" in audit.private_reasoning_exclusions
    assert "exclude:unadmitted-source" in audit.unadmitted_source_exclusions
    nomination = admit_program_trace_row(
        _row("bad:nomination", "training", "predicted_call", label_kind="model_nomination")
    )
    assert nomination.admitted is False
    assert "model_nomination" in nomination.reason or "model_nomination" in nomination.excluded


def test_negative_examples_are_not_labels_or_admitted_rows() -> None:
    secret = admit_program_trace_row(
        _row("bad:secret", "training", "holder", password="nope")  # type: ignore[arg-type]
    )
    hidden = admit_program_trace_row(
        _row("bad:hidden", "training", "hidden_suite", source_kind="hidden-test")
    )
    private = admit_program_trace_row(
        _row("bad:private", "training", "reasoner", source_kind="private-reasoning")
    )
    unadmitted = admit_program_trace_row(
        _row(
            "bad:unadmitted",
            "training",
            "prod",
            rights="unknown-rights",
            source_kind="unadmitted-source",
        )
    )
    raw = admit_program_trace_row(_row("bad:raw", "training", "rawish", includes_raw_bodies=True))
    assert secret.admitted is False
    assert hidden.admitted is False
    assert private.admitted is False
    assert unadmitted.admitted is False
    assert raw.admitted is False
    assert all(item.training_unavailable is False for item in (secret, hidden, private, unadmitted, raw))


def test_absent_corpus_returns_training_unavailable_without_blocking() -> None:
    missing = build_program_trace_corpus(Path("/nonexistent/program_world_trace_corpus.json"))
    empty = build_program_trace_corpus({"schema": "x", "rows": [], "absent": True})
    for corpus in (missing, empty):
        assert corpus.training_unavailable is True
        assert corpus.learned_path_status == TRAINING_UNAVAILABLE
        assert corpus.contracts_unblocked is True
        assert corpus.baselines_unblocked is True
        assert corpus.rows == ()
        assert corpus.leakage_audit.passed is True


def test_related_families_cannot_leak_across_partitions() -> None:
    corpus = build_program_trace_corpus()
    leaked = dict(corpus.rows[0].to_dict())
    leaked["row_id"] = "leaked-clone"
    leaked["partition"] = "held_out"
    with pytest.raises(ProgramTraceCorpusError, match="cannot leak"):
        build_program_trace_corpus({"tree_identity": "leak", "rows": [corpus.rows[0].to_dict(), leaked]})
    audit = audit_program_trace_leakage([*corpus.rows, leaked], excluded=corpus.excluded)
    assert audit.passed is False
    assert any("function:" in item or "public_trace_cid:" in item for item in audit.violations)


def test_cross_repository_partition_uses_a_distinct_repository() -> None:
    corpus = build_program_trace_corpus()
    training_repos = {
        row.groups["repository"]
        for row in corpus.rows
        if row.partition == "training"
    }
    cross = [row for row in corpus.rows if row.partition == "cross_repository"]
    assert cross
    assert training_repos.isdisjoint({row.groups["repository"] for row in cross})


def test_hermetic_trace_record_is_admitted_without_raw_bodies() -> None:
    record = record_python_execution_trace(
        _add,
        args=(1, 2),
        policy=TraceCollectionPolicy(collect_line=False, max_events=16),
        environment_binding={"python": "3.12"},
    )
    public = record.to_public_dict()
    assert public["includes_raw_bodies"] is False
    admission = admit_program_trace_row(
        record,
        row_id="live:add",
        partition="training",
        groups=_groups("live_add"),
        origin="hermetic",
        rights="first-party-admitted",
        source_kind="first-party-hermetic",
        label_kind="observed_event_sequence",
    )
    assert admission.admitted is True
    assert admission.tree_cid == record.tree_cid
    assert admission.public_trace_cid == record.public_trace.execution_trace_cid
    assert "password" not in json.dumps(admission.to_dict())


def test_deterministic_rebuild_is_stable() -> None:
    first = build_program_trace_corpus()
    second = build_program_trace_corpus(_FIXTURE)
    assert first.corpus_cid == second.corpus_cid
    assert first.leakage_audit.leakage_audit_cid == second.leakage_audit.leakage_audit_cid
    assert [row.row_cid for row in first.rows] == [row.row_cid for row in second.rows]
