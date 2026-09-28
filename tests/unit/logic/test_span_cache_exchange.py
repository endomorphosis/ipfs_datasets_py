"""Census and supervisor goals are appended to the span-cache dataset, not a queue."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import json

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.joint_benchmark import packet_schema_gaps
from ipfs_datasets_py.logic.autoformal.span_cache_exchange import (
    CENSUS_SCHEMA,
    GOAL_EXPORT_SCHEMA,
    load_goal_export,
    publish_compiled_exchange,
    write_exchange_pair,
    compiled_rows_from_evidence,
    load_exchange_bundle,
    pending_exchange_manifests,
    publish_exchange_manifest,
    upload_exchange_files,
)
from ipfs_datasets_py.logic.autoformal.span_evidence import SpanEvidenceError
from ipfs_datasets_py.logic.autoformal.supervisor_queue import SCHEMA as REPAIR_SCHEMA
from ipfs_datasets_py.logic.autoformal.supervisor_todo import SCHEMA as TODO_SCHEMA

_GOOD_SCORES = {
    "cosine_similarity": 0.9,
    "cross_entropy_loss": 1.0,
    "reconstruction_loss": 0.1,
}
_LOW_SCORES = {
    "cosine_similarity": 0.2,
    "cross_entropy_loss": 1.0,
    "reconstruction_loss": 0.1,
}


def _span(
    text: str, autoencoder_text: str, scores: dict, span_id: str = "span-1"
) -> dict:
    return {
        "agrees": False,
        "autoencoder_text": autoencoder_text,
        "census": {"consensus": "disagree"},
        "decompiled": "",
        "legal_id": "usc:10:1",
        "source_span_id": span_id,
        "text": text,
        **scores,
    }


def test_agreement_is_census_without_a_repair_goal(tmp_path: Path):
    text = "The officer shall retain records."
    receipt = publish_compiled_exchange(
        [{**_span(text, text, _GOOD_SCORES), "agrees": True}],
        tmp_path,
        upload=False,
        agent_id="compile-test",
        code_identity="sha256:test",
    )
    assert receipt["enqueued"] is False
    assert receipt["uploaded"] is False
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["full_checkpoint_uploaded"] is False
    assert receipt["census_rows"] == 1
    assert receipt["repair_packets"] == 0
    census = pq.read_table(receipt["census"]["path"]).to_pylist()
    assert census[0]["schema_version"] == CENSUS_SCHEMA
    assert census[0]["agrees"] is None
    assert census[0]["strict_compiler_agreement"] is True
    assert census[0]["autoencoder_text"] == text
    assert census[0]["source_text"] == text
    assert census[0]["admitted"] is False
    assert census[0]["formalized"] is False


def test_disagreement_uploads_census_and_reloadable_goals(tmp_path: Path):
    uploads: list[str] = []

    class Api:
        def repo_info(self, **kwargs):
            return SimpleNamespace(sha="a" * 40)

        def get_paths_info(self, *args, **kwargs):
            return []

        def create_commit(self, **kwargs):
            assert kwargs["parent_commit"] == "a" * 40
            assert len(kwargs["operations"]) == 3
            assert all(
                isinstance(op.path_or_fileobj, bytes) for op in kwargs["operations"]
            )
            uploads.extend(op.path_in_repo for op in kwargs["operations"])
            return SimpleNamespace(oid="b" * 40)

    receipt = publish_compiled_exchange(
        [_span("The officer shall retain records.", "5, 1990, 104 Stat.", _LOW_SCORES)],
        tmp_path,
        upload=True,
        agent_id="compile-test",
        code_identity="sha256:test",
        api=Api(),
    )
    assert receipt["uploaded"] is True
    assert receipt["enqueued"] is False
    assert receipt["repair_packets"] == 1
    assert receipt["training_goals"] >= 1
    assert uploads[0].startswith("autoformal/uscode/census/compile-test/census-")
    assert uploads[1].startswith("autoformal/uscode/goals/compile-test/goals-")
    assert "sealed-spans.parquet" not in "".join(uploads)
    assert "resume-checkpoint.parquet" not in "".join(uploads)
    loaded = load_goal_export(receipt["goals"]["path"])
    assert loaded["enqueued"] is False
    assert loaded["admitted"] is False
    packet = loaded["repair_packets"][0]
    assert packet["packet"]["schema"] == REPAIR_SCHEMA
    assert packet["packet"]["admitted"] is False
    assert packet["packet"]["formalized"] is False
    assert packet["task"]["schema"] == TODO_SCHEMA
    assert packet_schema_gaps(packet["packet"]) == []
    assert loaded["training_goals"][0]["admitted"] is False
    goals = pq.read_table(receipt["goals"]["path"]).to_pylist()
    assert {row["schema_version"] for row in goals} == {GOAL_EXPORT_SCHEMA}
    assert {row["handoff_status"] for row in goals} == {"dataset"}
    assert all(row["enqueued"] is False for row in goals)
    again = publish_compiled_exchange(
        [_span("The officer shall retain records.", "5, 1990, 104 Stat.", _LOW_SCORES)],
        tmp_path,
        upload=True,
        agent_id="compile-test",
        code_identity="sha256:test",
        api=Api(),
    )
    assert again["skipped"] == "already_uploaded"
    assert again["uploaded"] is True
    assert len(uploads) == 3


def test_exchange_refuses_sealed_span_and_resume_names(tmp_path: Path):
    rows = [
        _span(
            "The officer shall retain records.",
            "The officer shall retain records.",
            _GOOD_SCORES,
        )
    ]
    with pytest.raises(SpanEvidenceError):
        write_exchange_pair(
            rows,
            tmp_path / "sealed-spans.parquet",
            tmp_path / "goals.parquet",
            code_identity="sha256:test",
        )
    with pytest.raises(SpanEvidenceError):
        write_exchange_pair(
            rows,
            tmp_path / "census.parquet",
            tmp_path / "resume-checkpoint.parquet",
            code_identity="sha256:test",
        )


def test_corpus_ingest_does_not_append_goals_to_a_supervisor_queue():
    source = (
        Path(__file__).resolve().parents[3]
        / "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    ).read_text(encoding="utf-8")
    assert "upsert_failure_goals_through_quack" not in source
    assert "publish_compiled_exchange" in source


def _observed(span_id="observed-1"):
    return {
        **_span(
            "The agency shall retain records.",
            "The agency shall retain records.",
            _GOOD_SCORES,
            span_id,
        ),
        "reason": "unsupported custom parser case",
        "compiler_result": {"compiler_status": "abstained", "decompiled": ""},
        "comparison": {
            "agrees": True,
            "reason": "",
            "decompiled": "New projection text.",
            "capture": {
                "replicated": True,
                "selected_families": ["deontic"],
                "below_threshold": [],
            },
        },
    }


class _MemoryHub:
    def __init__(self):
        self.remote = {}
        self.commits = []
        self.fail_before = False
        self.ambiguous = False
        self.head = "a" * 40

    def repo_info(self, **kwargs):
        return SimpleNamespace(sha=self.head)

    def get_paths_info(self, repo_id, paths, **kwargs):
        assert kwargs["revision"] == self.head
        return [
            SimpleNamespace(
                path=path,
                lfs=SimpleNamespace(
                    sha256=hashlib.sha256(self.remote[path]).hexdigest()
                ),
            )
            for path in paths
            if path in self.remote
        ]

    def create_commit(self, **kwargs):
        self.commits.append(kwargs)
        if self.fail_before:
            raise ConnectionError("offline")
        assert kwargs["parent_commit"] == self.head
        for operation in kwargs["operations"]:
            assert isinstance(operation.path_or_fileobj, bytes)
            self.remote[operation.path_in_repo] = operation.path_or_fileobj
        self.head = "b" * 40
        if self.ambiguous:
            raise ConnectionError("server committed but response lost")
        return SimpleNamespace(oid=self.head)


def test_strict_abstention_survives_new_family_agreement_with_full_original_evidence(
    tmp_path,
):
    observed = {
        **_observed(),
        "autoencoder_capture": {"modal_ir": {"nested": "x" * (2 * 1024 * 1024)}},
    }
    receipt = publish_compiled_exchange([observed], tmp_path, upload=False)
    bundle = load_exchange_bundle(receipt["manifest"]["path"])
    row = bundle["census_rows"][0]
    assert row["agrees"] is False and row["strict_compiler_agreement"] is False
    assert row["compiler_decompiled"] == ""
    assert json.loads(row["comparison_json"])["decompiled"] == "New projection text."
    assert json.loads(row["input_json"]) == observed
    assert len(bundle["repair_packets"]) == 1
    assert (
        bundle["repair_packets"][0]["packet"]["row"]["capture"][
            "observed_strict_reason"
        ]
        == observed["reason"]
    )


def test_evidence_top_level_training_request_exports_training_and_source_repair(
    tmp_path,
):
    original = {
        **_observed(),
        "train": True,
        "census_agree": False,
        "consensus": "disagree",
    }
    rows = compiled_rows_from_evidence([original])
    receipt = publish_compiled_exchange(rows, tmp_path)
    bundle = load_exchange_bundle(receipt["manifest"]["path"])
    assert len(bundle["repair_packets"]) == len(bundle["training_goals"]) == 1
    assert bundle["training_goals"][0]["capture"]["original_training_requested"] is True
    assert json.loads(bundle["census_rows"][0]["input_json"])["train"] is True


def test_raw_missing_losses_remain_unknown_instead_of_legacy_zero(tmp_path):
    row = {
        **_observed(),
        "agrees": True,
        "cosine_similarity": 0.0,
        "autoencoder_capture": {
            "codec_observation": {"raw_losses": {"cross_entropy_loss": 0.4}}
        },
    }
    receipt = publish_compiled_exchange([row], tmp_path)
    bundle = load_exchange_bundle(receipt["manifest"]["path"])
    assert bundle["census_rows"][0]["cosine_similarity"] is None
    assert bundle["census_rows"][0]["reconstruction_loss"] is None
    assert bundle["census_rows"][0]["agrees"] is False
    assert len(bundle["training_goals"]) == 1


def test_input_permutation_is_same_immutable_bundle_and_metric_change_is_new(tmp_path):
    rows = [_observed("one"), _observed("two")]
    first = publish_compiled_exchange(rows, tmp_path)
    second = publish_compiled_exchange(list(reversed(rows)), tmp_path)
    assert first["fingerprint"] == second["fingerprint"]
    assert first["census"]["sha256"] == second["census"]["sha256"]
    changed = publish_compiled_exchange(
        [{**rows[0], "cross_entropy_loss": 0.2}, rows[1]], tmp_path
    )
    assert changed["fingerprint"] != first["fingerprint"]


def test_dry_run_outbox_retries_failure_without_rebuilding_and_commits_all_three(
    tmp_path,
):
    staged = publish_compiled_exchange([_observed()], tmp_path, upload=False)
    manifest = Path(staged["manifest"]["path"])
    assert pending_exchange_manifests(tmp_path) == [manifest]
    api = _MemoryHub()
    api.fail_before = True
    failed = publish_exchange_manifest(manifest, upload=True, api=api)
    assert failed["uploaded"] is False and failed["error"] == "ConnectionError"
    assert pending_exchange_manifests(tmp_path) == [manifest]
    api.fail_before = False
    uploaded = publish_exchange_manifest(manifest, upload=True, api=api)
    assert uploaded["uploaded"] is True and uploaded["commit_sha"] == api.head
    assert len(api.commits[-1]["operations"]) == 3
    assert pending_exchange_manifests(tmp_path) == []
    repeated = publish_exchange_manifest(manifest, upload=True, api=api)
    assert repeated["skipped"] == "already_uploaded" and len(api.commits) == 2


def test_ambiguous_hub_success_recovers_exact_remote_bytes_without_second_commit(
    tmp_path,
):
    staged = publish_compiled_exchange([_observed()], tmp_path)
    api = _MemoryHub()
    api.ambiguous = True
    failed = publish_exchange_manifest(staged["manifest"]["path"], upload=True, api=api)
    assert failed["uploaded"] is False and len(api.commits) == 1
    recovered = publish_exchange_manifest(
        staged["manifest"]["path"], upload=True, api=api
    )
    assert recovered["uploaded"] is True and recovered["remote_already_present"] is True
    assert len(api.commits) == 1 and pending_exchange_manifests(tmp_path) == []


def test_remote_conflicting_content_is_never_overwritten(tmp_path):
    staged = publish_compiled_exchange([_observed()], tmp_path)
    api = _MemoryHub()
    api.remote[staged["census_path_in_repo"]] = b"different content"
    result = publish_exchange_manifest(staged["manifest"]["path"], upload=True, api=api)
    assert result["uploaded"] is False and result["error"] == "SpanEvidenceError"
    assert api.commits == [] and pending_exchange_manifests(tmp_path)


def test_pair_publisher_uses_original_custom_destination_and_rejects_retarget(tmp_path):
    options = {
        "census_path_in_repo": "custom/batch/census.parquet",
        "goals_path_in_repo": "custom/batch/goals.parquet",
    }
    staged = write_exchange_pair(
        [_observed()],
        tmp_path / "census.parquet",
        tmp_path / "goals.parquet",
        **options,
    )
    api = _MemoryHub()
    result = upload_exchange_files(
        staged["census"]["path"],
        staged["goals"]["path"],
        upload=True,
        api=api,
        **options,
    )
    assert result["uploaded"] is True and result["fingerprint"] == staged["fingerprint"]
    assert staged["census_path_in_repo"].startswith("custom/batch/census-")
    with pytest.raises(SpanEvidenceError, match="destination differs"):
        upload_exchange_files(
            staged["census"]["path"],
            staged["goals"]["path"],
            census_path_in_repo="different/census.parquet",
            goals_path_in_repo="different/goals.parquet",
        )


@pytest.mark.parametrize("bad_field", ["parent", "commit"])
def test_publication_requires_full_immutable_commit_identities(tmp_path, bad_field):
    staged = publish_compiled_exchange([_observed()], tmp_path)
    api = _MemoryHub()
    if bad_field == "parent":
        api.head = "main"
    else:
        api.create_commit = lambda **kwargs: SimpleNamespace(oid="main")
    result = publish_exchange_manifest(staged["manifest"]["path"], upload=True, api=api)
    assert result["uploaded"] is False and result["error"] == "SpanEvidenceError"
    assert pending_exchange_manifests(tmp_path)


def test_publication_uploads_verified_snapshots_even_if_local_path_changes_later(
    tmp_path,
):
    staged = publish_compiled_exchange([_observed()], tmp_path)
    local = Path(staged["census"]["path"])
    verified = local.read_bytes()
    api = _MemoryHub()

    def mutate_after_snapshot(**kwargs):
        local.write_bytes(b"changed after publication snapshot")
        return SimpleNamespace(sha=api.head)

    api.repo_info = mutate_after_snapshot
    result = publish_exchange_manifest(staged["manifest"]["path"], upload=True, api=api)
    assert result["uploaded"] is True
    assert api.remote[staged["census_path_in_repo"]] == verified
    assert api.remote[staged["census_path_in_repo"]] != local.read_bytes()


def test_invalid_goal_retains_data_without_committing_an_outbox_manifest(tmp_path):
    from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange

    built = exchange.exchange_from_compiled([_observed()], agent_id="test")
    built["goal_rows"][0]["task_json"] = "{}"
    census_path, goals_path = (
        tmp_path / "invalid-census.parquet",
        tmp_path / "invalid-goals.parquet",
    )
    with pytest.raises(SpanEvidenceError, match="digest mismatch"):
        exchange._save_bundle(
            built,
            census_path,
            goals_path,
            repository_id="justicedao/uscode-autoformal-span-cache",
            agent_id="test",
        )
    assert census_path.is_file() and goals_path.is_file()
    retained_bytes = {path: path.read_bytes() for path in (census_path, goals_path)}
    assert not list(tmp_path.glob("exchange-*.manifest.json"))
    assert not list(tmp_path.glob(".exchange-validation-*"))
    assert pending_exchange_manifests(tmp_path) == []
    valid = publish_compiled_exchange([_observed("later-valid")], tmp_path)
    assert pending_exchange_manifests(tmp_path) == [Path(valid["manifest"]["path"])]
    assert all(path.read_bytes() == raw for path, raw in retained_bytes.items())
