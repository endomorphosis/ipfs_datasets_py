"""Distributed orchestration boundaries; fixtures never claim native model/Lake success."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    autoencoder_distributed_training as work,
)


def raw_ref(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def generation(raw, number=1):
    artifact = raw_ref(raw)
    return {
        "generation": number,
        "version_id": "sha256:" + str(number) * 64,
        "artifact": artifact,
        "weight_reference": {
            "kind": "anchor",
            "repository_id": work.REPOSITORY,
            "commit_sha": "a" * 40,
            "path_in_repo": f"autoformal/uscode/anchors/{number}.json",
            **artifact,
            "materialized_checkpoint": artifact,
        },
    }


def checkpoint_downloader(raw, calls):
    def download(reference, target):
        calls.append(deepcopy(reference))
        target.mkdir(parents=True, exist_ok=True)
        path = target / "checkpoint.json"
        path.write_bytes(raw)
        return {
            "materialized_checkpoint_path": str(path),
            "downloaded_bytes": len(raw),
            "native_execution_performed": False,
        }

    return download


def test_installed_generation_hashes_full_bytes_and_resume_reuses_verified_cache(
    tmp_path,
):
    raw = b"complete checkpoint transport fixture\n"
    expected = generation(raw)
    calls = []
    installed = work.install_generation(
        expected, tmp_path, downloader=checkpoint_downloader(raw, calls)
    )
    assert installed["binding"]["artifact"] == raw_ref(raw)
    assert installed["full_weights_verified"] is True
    assert work._read(tmp_path / "current.json") == installed
    replay = work.install_generation(
        expected, tmp_path, downloader=lambda *args: pytest.fail("cache redownload")
    )
    assert (
        replay["cache_hit"] is True
        and replay["downloaded_bytes"] == 0
        and len(calls) == 1
    )


def test_feature_generation_uses_separate_downloader_and_verifies_full_bytes(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_exchange as exchange
    from ipfs_datasets_py.huggingface import autoencoder_incremental_download as qualified
    old = work.install_generation(generation(b"feature parent"), tmp_path,
        downloader=checkpoint_downloader(b"feature parent", []))
    next_generation = generation(b"feature candidate", 2)
    next_generation["weight_reference"]["kind"] = "feature_sparse"
    next_generation["weight_reference"]["anchor_reference"] = old["binding"]["weight_reference"]
    observed = []
    def download(reference, target, *, local_parent_resolver):
        assert reference == next_generation["weight_reference"]
        assert local_parent_resolver(old["materialized_checkpoint"]) == Path(old["checkpoint_path"])
        observed.append(reference)
        path = target / "candidate.json"
        path.write_bytes(b"feature candidate")
        return {"materialized_checkpoint_path": str(path), "downloaded_bytes": 5,
                "qualified": False, "admitted": False}
    monkeypatch.setattr(exchange, "download_feature_update", download)
    monkeypatch.setattr(qualified, "download_sparse_update", lambda *a, **k: pytest.fail("qualified route"))
    installed = work.install_generation(next_generation, tmp_path)
    assert installed["full_weights_verified"] is True
    assert len(observed) == 1
    work.install_generation(next_generation, tmp_path)
    assert len(observed) == 1


def test_install_resume_recovers_crash_between_installed_and_current_writes(tmp_path):
    raw = b"complete transport fixture"
    expected = generation(raw)
    work.install_generation(
        expected, tmp_path, downloader=checkpoint_downloader(raw, [])
    )
    (tmp_path / "current.json").unlink()
    resumed = work.install_generation(
        expected,
        tmp_path,
        downloader=lambda *args: pytest.fail("must reuse complete bytes"),
    )
    assert (tmp_path / "current.json").exists()
    assert work._read(tmp_path / "current.json")["binding"] == resumed["binding"]


def test_corrupt_cached_full_weights_are_not_acknowledged_or_replaced(tmp_path):
    raw = b"checkpoint-v1"
    expected = generation(raw)
    installed = work.install_generation(
        expected, tmp_path, downloader=checkpoint_downloader(raw, [])
    )
    before = (tmp_path / "current.json").read_bytes()
    Path(installed["checkpoint_path"]).write_bytes(b"checkpoint-v2")
    with pytest.raises(work.DistributedTrainingError, match="hash"):
        work.install_generation(
            expected,
            tmp_path,
            downloader=lambda *args: pytest.fail(
                "corruption cannot silently replace bytes"
            ),
        )
    assert (tmp_path / "current.json").read_bytes() == before


def test_failed_new_generation_install_keeps_old_advertised_generation(tmp_path):
    old = work.install_generation(
        generation(b"old"), tmp_path, downloader=checkpoint_downloader(b"old", [])
    )
    with pytest.raises(work.DistributedTrainingError):
        work.install_generation(
            generation(b"expected", 2),
            tmp_path,
            downloader=checkpoint_downloader(b"corrupt!", []),
        )
    assert work._read(tmp_path / "current.json") == old
    assert not (tmp_path / "2" / "installed.json").exists()
    assert Path(old["checkpoint_path"]).read_bytes() == b"old"


def test_same_generation_number_cannot_replace_immutable_binding(tmp_path):
    work.install_generation(
        generation(b"old"), tmp_path, downloader=checkpoint_downloader(b"old", [])
    )
    with pytest.raises(work.DistributedTrainingError, match="immutable"):
        work.install_generation(
            generation(b"new"),
            tmp_path,
            downloader=lambda *args: pytest.fail("binding conflict before download"),
        )


def test_symlink_checkpoint_is_not_a_verified_complete_generation(tmp_path):
    real = tmp_path / "real"
    real.write_bytes(b"fixture")
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(work.DistributedTrainingError):
        work.verify_complete_checkpoint(link, raw_ref(b"fixture"))


class LostReplyControl:
    """Injected network boundary, persisting an applied command before timeout."""

    def __init__(self):
        self.calls = []
        self.committed = {}
        self.drop = True

    def request(self, command, payload, operation_id, timeout):
        assert timeout == 30
        self.calls.append((command, deepcopy(payload), operation_id))
        result = self.committed.setdefault(
            operation_id, {"operation_id": operation_id, "mutation_count": 1}
        )
        if self.drop:
            self.drop = False
            raise TimeoutError("reply lost after owner commit")
        return result


def test_durable_control_replay_reuses_exact_operation_after_lost_reply_and_restart(
    tmp_path,
):
    transport = LostReplyControl()
    first = work.DurableCampaignClient(transport, tmp_path)
    payload = {"generation": 7, "version_id": "fixture-version"}
    with pytest.raises(TimeoutError):
        first.request(["ack", 7], "AcknowledgeWeights", payload)
    restarted = work.DurableCampaignClient(transport, tmp_path)
    result = restarted.request(["ack", 7], "AcknowledgeWeights", payload)
    assert len(transport.committed) == 1 and len(transport.calls) == 2
    assert transport.calls[0] == transport.calls[1]
    assert restarted.request(["ack", 7], "AcknowledgeWeights", payload) == result
    assert len(transport.calls) == 2
    with pytest.raises(work.DistributedTrainingError, match="slot changed"):
        restarted.request(
            ["ack", 7], "AcknowledgeWeights", {**payload, "generation": 8}
        )
    assert len(transport.calls) == 2


@pytest.fixture
def cli():
    path = work.ROOT / "scripts/ops/legal_ir/run_distributed_autoencoders.py"
    spec = importlib.util.spec_from_file_location("distributed_training_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_source_updates_preserve_span_identity_but_change_revision(
    tmp_path, cli
):
    source = {"title": "5", "section": "1", "text": "The officer shall retain records."}
    rows = [
        {"source_span_id": "usc:5:1:clause-a", "sample": source},
        {
            "source_span_id": "usc:5:1:clause-a",
            "sample": {**source, "text": "The officer shall retain files."},
        },
    ]
    path = tmp_path / "source.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    raw = work.records_from_jsonl(path)
    records = cli.normalize(raw)
    assert records[0]["source_span_id"] == records[1]["source_span_id"]
    assert records[0]["record_id"] != records[1]["record_id"]
    assert cli.normalize(raw) == records
    for row in records:
        assert (
            row["source_text_sha256"]
            == hashlib.sha256(row["sample"]["text"].encode()).hexdigest()
        )
        assert row["text"] == row["sample"]["text"]
    path.write_text(
        json.dumps(source)
        + "\n"
        + json.dumps(dict(reversed(list(source.items()))))
        + "\n"
    )
    bare = work.records_from_jsonl(path)
    assert bare[0]["record_id"] == bare[1]["record_id"]
    assert bare[0]["source_span_id"].startswith("local-content:")


def test_source_input_limits_and_symlinks_fail_before_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(
        work,
        "local_cli",
        lambda: SimpleNamespace(MAX_INPUT_BYTES=100, MAX_INPUT_ROWS=1),
    )
    path = tmp_path / "too-large"
    path.write_bytes(b"x" * 101)
    with pytest.raises(work.DistributedTrainingError):
        work.records_from_jsonl(path)
    path.write_bytes(b"{}\n{}\n")
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(work.DistributedTrainingError):
        work.records_from_jsonl(link)


@pytest.mark.parametrize(
    "option,value",
    [
        ("--storage-bytes", "0"),
        ("--storage-bytes", "50000000001"),
        ("--worker-storage-bytes", "-1"),
        ("--max-seconds", "nan"),
        ("--sync-interval", "inf"),
        ("--cycle-timeout", "nan"),
        ("--cycle-timeout", "-1"),
        ("--max-training-rounds", "0"),
        ("--lake-timeout-seconds", "601"),
    ],
)
def test_owner_cli_rejects_invalid_resources_before_owner_execution(
    tmp_path, cli, monkeypatch, option, value
):
    monkeypatch.setattr(
        cli, "owner", lambda args: pytest.fail("invalid CLI reached owner side effects")
    )
    argv = [
        "owner",
        "--state-directory",
        str(tmp_path / "state"),
        "--campaign-id",
        "test",
        "--worker-id",
        "worker-1",
        "--input-jsonl",
        str(tmp_path / "source.jsonl"),
        "--validation-jsonl",
        str(tmp_path / "validation.jsonl"),
        option,
        value,
    ]
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--lease-seconds", "nan"],
        ["--lease-seconds", "1"],
        ["--polls", "-1"],
        ["--max-jobs", "-1"],
        ["--storage-bytes", "50000000001"],
    ],
)
def test_worker_cli_rejects_invalid_resource_shapes(tmp_path, cli, monkeypatch, extra):
    monkeypatch.setattr(
        cli,
        "worker",
        lambda args: pytest.fail("invalid CLI reached worker side effects"),
    )
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "worker",
                "--state-directory",
                str(tmp_path / "state"),
                "--connection-file",
                str(tmp_path / "connection.json"),
                *extra,
            ]
        )
    assert error.value.code == 2


def test_cli_reservation_does_not_use_uncovered_state_directory(tmp_path, cli):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"roots": [{"path": str(tmp_path / "covered")}]}))
    args = SimpleNamespace(
        resource_ledger=ledger, state_directory=tmp_path / "outside", storage_bytes=100
    )
    with pytest.raises(work.DistributedTrainingError, match="outside resource ledger"):
        cli._reserve(args)


def test_feature_owner_requires_verified_inputs_before_any_execution(tmp_path, cli, monkeypatch):
    monkeypatch.setattr(cli, "owner", lambda args: pytest.fail("unverified feature owner"))
    with pytest.raises(SystemExit) as error:
        cli.main(["owner", "--training-purpose", "feature_pretraining", "--state-directory", str(tmp_path),
            "--campaign-id", "features", "--worker-id", "one", "--input-jsonl", "input.jsonl",
            "--validation-jsonl", "validation.jsonl"])
    assert error.value.code == 2


def test_feature_sync_only_needs_no_training_inputs(tmp_path, cli, monkeypatch):
    observed = []
    monkeypatch.setattr(cli, "worker", observed.append)
    assert cli.main(["worker", "--training-purpose", "feature_pretraining", "--state-directory", str(tmp_path),
        "--connection-file", "connection.json", "--sync-only"]) == 0
    assert len(observed) == 1 and observed[0].sync_only


def test_feature_owner_policy_options_are_explicit_and_bounded(tmp_path, cli, monkeypatch):
    observed = []
    monkeypatch.setattr(cli, "owner", observed.append)
    args = ["owner", "--training-purpose", "feature_pretraining", "--state-directory", str(tmp_path),
        "--campaign-id", "features", "--worker-id", "one", "--input-jsonl", "input.jsonl",
        "--validation-jsonl", "validation.jsonl", "--feature-input-manifest", "manifest.json",
        "--shared-targets", "targets.bundle", "--target-snapshot-id", "sha256:" + "1" * 64]
    assert cli.main(args) == 0
    assert observed[0].projection_optimizer_mode == "productive_adaptive"
    assert observed[0].epochs == 3
    with pytest.raises(SystemExit):
        cli.main([*args, "--learning-rate", "nan"])
    with pytest.raises(SystemExit):
        cli.main([*args, "--repository-id", work.REPOSITORY])
    for invalid in (["--epochs", "33"], ["--line-search-attempts", "1"],
                    ["--projection-momentum", "0.99"], ["--projection-optimizer-mode", "fixed"]):
        with pytest.raises(SystemExit):
            cli.main([*args, *invalid])
    assert len(observed) == 1


def qualification_receipt(version, artifact, *, passed, training=None, validation=None):
    training = training or [
        {
            "title": "5",
            "section": "1",
            "text": "The officer shall retain the file for at least 20 days.",
        }
    ]
    validation = validation or [
        {
            "title": "5",
            "section": "2",
            "text": "The officer shall retain the file for at least 30 days.",
        }
    ]
    names = (
        "metric_gate",
        "semantic_gate",
        "family_syntax_gate",
        "lake_gate",
        "heldout_gate",
    )
    gates = {name: {"passed": passed} for name in names}
    rows = []
    for split, samples in (("training", training), ("heldout", validation)):
        for index, sample in enumerate(samples):
            rows.append(
                {
                    "sample_id": split + "-" + str(index),
                    "split": split,
                    "source": sample,
                    "source_sha256": hashlib.sha256(
                        sample["text"].encode()
                    ).hexdigest(),
                    **{name: {"passed": passed} for name in names[:-1]},
                    "qualified": passed,
                    "admitted": False,
                    "formalized": False,
                }
            )
    return {
        "schema_version": "autoencoder-candidate-qualification/v1",
        "execution_mode": "native_candidate_qualification",
        "unit_test_transport_only": True,
        "candidate_version_id": version,
        "candidate_artifact": artifact,
        "qualified": passed,
        "gate_results": gates,
        **gates,
        "rows": rows,
        "repair_todos": [],
        "sample_count": len(training),
        "heldout_sample_count": len(validation),
        "source_sha256": {"fixture": "f" * 64},
        "requested_model_config": {"compute_device": "python"},
        "sample_set_sha256": work.inc._sha(
            {"training": training, "heldout": validation}
        ),
        "qualification_scope": "embedding_model_and_deterministic_source_compiler_pipeline",
        "model_emits_text_or_formulas": False,
        "admitted": False,
        "formalized": False,
    }


@pytest.fixture
def selection(tmp_path, monkeypatch):
    """Real immutable artifacts; injected completed-run lookup and promotion boundary."""
    with AutoencoderRegistry(
        tmp_path / "owner.duckdb", tmp_path / "artifacts"
    ) as registry:
        registry.register_variant("variant", "test-variant", {"source_language": "en"})
        source = tmp_path / "candidate"
        source.write_bytes(b"not-a-model-test-candidate")
        artifact = registry.stage_artifact(source)
        base = registry.register_version("base", "test-variant", artifact)["version_id"]
        candidate = registry.register_version(
            "candidate",
            "test-variant",
            artifact,
            metadata={"fixture": True},
            parent_version_id=base,
        )["version_id"]
        proof = qualification_receipt(candidate, artifact, passed=True)
        promotions = []
        campaign = SimpleNamespace(
            registry=registry,
            campaign_id="test-campaign",
            binding={"policy": {"source_identity": {"fixture": "transport-only"}}},
            status=lambda: {"weights": {"version_id": base, "generation": 1}},
            advance_generation=lambda *args, **kwargs: promotions.append(
                (args, kwargs)
            ),
        )

        @contextmanager
        def transaction():
            yield SimpleNamespace(
                execute=lambda *args: SimpleNamespace(fetchall=lambda: [("run-1",)])
            )

        yield SimpleNamespace(
            registry=registry,
            artifact=artifact,
            candidate=candidate,
            proof=proof,
            campaign=campaign,
            promotions=promotions,
            transaction=transaction,
            directory=tmp_path,
            monkeypatch=monkeypatch,
        )


def set_selection_receipt(case, proof):
    path = case.directory / "qualification.json"
    path.write_text(json.dumps(proof))
    artifact = case.registry.stage_artifact(path)
    completion = {
        "run": {
            "result": {
                "owner_qualification_artifact": artifact,
                "qualification_version_id": case.candidate,
                "weight_reference": {"fixture": True},
            }
        },
        "candidate_version": {"version_id": case.candidate, "artifact": case.artifact},
    }
    case.monkeypatch.setattr(case.registry, "_transaction", case.transaction)
    case.monkeypatch.setattr(
        case.registry, "get_run_completion", lambda run: completion
    )
    # Isolate selector policy from the independently tested native proof engine.
    from ipfs_datasets_py.huggingface import autoencoder_incremental as native

    case.monkeypatch.setattr(native, "_qualified", lambda *args: None)
    case.monkeypatch.setattr(native, "_proofs", lambda *args, **kwargs: ([], {}))
    case.monkeypatch.setattr(work, "_owner_producer_binding", lambda *args: None)
    case.monkeypatch.setattr(
        case.registry,
        "get_version",
        lambda version: {"version_id": version, "artifact": case.artifact},
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda q: q.update(gate_results={}),
        lambda q: q["gate_results"].pop("lake_gate"),
        lambda q: q["gate_results"]["lake_gate"].update(passed=False),
        lambda q: q["gate_results"]["lake_gate"].update(passed=1),
        lambda q: q.update(candidate_version_id="foreign-candidate"),
        lambda q: q.update(candidate_artifact={"sha256": "0" * 64, "bytes": 10}),
        lambda q: q.update(qualified=False),
    ],
)
def test_canonical_selection_rejects_incomplete_false_or_mismatched_owner_evidence(
    selection, change
):
    proof = deepcopy(selection.proof)
    change(proof)
    set_selection_receipt(selection, proof)
    with pytest.raises((ValueError, KeyError)):
        work.advance_verified_generation(selection.campaign)
    assert not selection.promotions


def test_canonical_selector_reaches_native_boundary_only_after_complete_consistent_receipt(
    selection,
):
    set_selection_receipt(selection, selection.proof)
    work.advance_verified_generation(selection.campaign)
    assert len(selection.promotions) == 1
    assert selection.promotions[0][1]["expected_generation"] == 1


def remote_producer_fixture():
    paths, hashes, identity = {}, {}, {}
    for role, relative in work._remote_producer_paths().items():
        paths[role] = ('/remote/lift_coding/' if role == 'statement_lock'
                       else '/remote/lift_coding/external/ipfs_datasets/') + relative
        hashes[role] = hashlib.sha256(role.encode()).hexdigest()
        key = 'native:' + role if role in {'compiler','decompiler','parser','autoencoder','samples'} else relative
        identity[key] = hashes[role]
    return paths, hashes, identity


@pytest.mark.parametrize('partial_attempt', [False, 'directory', 'truncated'])
def test_owner_requalifies_remote_success_and_retains_independent_failure(
    tmp_path, monkeypatch, partial_attempt
):
    from ipfs_datasets_py.huggingface import autoencoder_span_attempts as transport
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_candidate_qualification as qualification,
    )

    with AutoencoderRegistry(
        tmp_path / "owner.duckdb", tmp_path / "artifacts"
    ) as registry:
        registry.register_variant("variant", "test-variant", {"source_language": "en"})
        source = tmp_path / "candidate-bytes"
        source.write_bytes(b"owner-local-candidate-transport-fixture")
        artifact = registry.stage_artifact(source)
        base = registry.register_version("base", "test-variant", artifact)["version_id"]
        sample = {
            "title": "5",
            "section": "1",
            "text": "The officer shall retain the file for at least 20 days.",
        }
        validation = {
            "title": "5",
            "section": "2",
            "text": "The officer shall retain the file for at least 30 days.",
        }
        assignment = {
            "run_id": "run-1",
            "generation": 1,
            "base_version_id": base,
            "variant_id": "test-variant",
            "record": {"record_id": "revision-1", "sample": sample},
        }
        producer_paths, producer_hashes, producer_identity = remote_producer_fixture()
        policy = {
            "source_identity": producer_identity,
            "validation_samples": [validation],
            "lake_timeout_seconds": 1,
        }
        report = {
            "work_id": "run-1",
            "span_revision": "revision-1",
            "candidate_version_id": "remote-candidate",
            "disposition": "qualified",
            "weight_publication": {"kind": "injected-transport"},
            "source_provenance": {
                "source_record": assignment["record"],
                "canonical_generation": 1,
                "canonical_version_id": base,
                "canonical_artifact": artifact,
                "source_identity": policy["source_identity"],
            },
            "qualification": {
                'source_files': producer_paths, 'source_sha256': producer_hashes,
                'sample_set_sha256': work.inc._sha({'training':[sample], 'heldout':[validation]}),
                'requested_model_config': {'compute_device':'python'},
                "rows": [
                    {"split": "training", "source": sample},
                    {"split": "heldout", "source": validation},
                ],
                "materialized_checkpoint": artifact,
            },
        }
        monkeypatch.setattr(
            transport, "download_span_attempt_report", lambda *args: {"report": report}
        )
        monkeypatch.setattr(work, "identity", lambda: policy["source_identity"])
        monkeypatch.setattr(
            work,
            "install_generation",
            lambda *args, **kwargs: {"checkpoint_path": str(source)},
        )
        producer_checks, evaluations = [], []
        monkeypatch.setattr(
            work, "_owner_producer_binding", lambda *args: producer_checks.append(args)
        )

        def requalify(candidate, version, samples, directory, **kwargs):
            evaluations.append((version, samples, kwargs))
            evidence = qualification_receipt(
                version,
                artifact,
                passed=False,
                training=samples,
                validation=kwargs["heldout_samples"],
            )
            directory.mkdir(parents=True)
            work._write(directory / "qualification.json", evidence)
            return evidence

        monkeypatch.setattr(qualification, "qualify_candidate", requalify)
        descriptor = {"sha256": "b" * 64, "bytes": 123}
        verifier = work.owner_verifier(registry, policy, tmp_path / "verify")
        if partial_attempt:
            partial = tmp_path / 'verify' / descriptor['sha256'] / 'owner-qualification'
            partial.mkdir(parents=True)
            (partial / 'partial-proof.log').write_text('Interrupted, not a qualification.')
            if partial_attempt == 'truncated':
                (partial / 'qualification.json').write_text('{"candidate_version_id":')
        result = verifier(assignment, descriptor)
        assert result["result"]["qualified"] is False
        assert result["result"]["span_disposition"] == "needs_repair"
        assert len(evaluations) == 1 and len(producer_checks) == 1
        if partial_attempt:
            retained_partial = list((tmp_path/'verify'/descriptor['sha256']).glob('owner-qualification-incomplete-*'))
            assert len(retained_partial) == 1
            assert (retained_partial[0]/'partial-proof.log').read_text() == 'Interrupted, not a qualification.'
            if partial_attempt == 'truncated':
                assert (retained_partial[0]/'qualification.json').read_text() == '{"candidate_version_id":'
        # Failed remote results receive the same producer/model/sample binding
        # before the early return; transport fixtures never become admissions.
        report['disposition'] = 'needs_repair'
        assert verifier(assignment, descriptor)['result']['span_disposition'] == 'needs_repair'
        report['qualification']['source_sha256']['parser'] = '0' * 64
        with pytest.raises(work.DistributedTrainingError, match='producer hash'):
            verifier(assignment, descriptor)
        report['qualification']['source_sha256']['parser'] = producer_identity['native:parser']
        report['disposition'] = 'qualified'
        retained = (
            tmp_path
            / "verify"
            / descriptor["sha256"]
            / "owner-qualification"
            / "qualification.json"
        )
        forged = work._read(retained)
        forged["qualified"] = True
        work._write(retained, forged)
        with pytest.raises(ValueError, match="qualified summary"):
            verifier(assignment, descriptor)
        assert (
            len(evaluations) == 1
        )  # Cached forged success must not bypass retained gate validation.
        report["source_provenance"]["canonical_generation"] = 2
        with pytest.raises(work.DistributedTrainingError, match="exact assigned"):
            verifier(assignment, descriptor)


def test_changed_heartbeat_fence_is_rejected_before_thread_or_network(tmp_path):
    path = tmp_path / "heartbeat.json"
    work._write(path, {"lease": {"run_id": "run-1", "fence": 1}, "renewal": 4})
    control = SimpleNamespace(
        request=lambda *args: pytest.fail("stale fence must not contact owner")
    )
    with pytest.raises(work.DistributedTrainingError, match="different assignment"):
        with work.renewable_assignment(
            control, {"lease": {"run_id": "run-1", "fence": 2}}, path
        ):
            pytest.fail("stale heartbeat must not yield assignment")


def test_heartbeat_replays_lost_renewal_before_cached_result_can_report(tmp_path):
    original = {'run_id':'run-1','attempt':1,'fence':1,'owner_generation':1,
                'worker_id':'worker','expires_at':100.0}
    renewed = {**original, 'expires_at':400.0}
    class LostRenewal:
        def __init__(self):
            self.committed, self.calls = {}, []
        def request(self, command, payload, operation_id, timeout):
            self.calls.append((command, deepcopy(payload), operation_id))
            assert command == 'RenewSpan' and payload['lease'] == original
            if operation_id not in self.committed:
                self.committed[operation_id] = {'lease': renewed}
                raise TimeoutError('renewal committed before reply was lost')
            return self.committed[operation_id]
    transport = LostRenewal()
    client = work.DurableCampaignClient(transport, tmp_path/'journal')
    slot = ['renew','run-1',1,1]
    with pytest.raises(TimeoutError):
        client.request(slot, 'RenewSpan', {'lease':original,'lease_seconds':300})
    heartbeat_path = tmp_path/'heartbeat.json'
    work._write(heartbeat_path, {'lease':original,'renewal':0})
    with work.renewable_assignment(client, {'lease':original}, heartbeat_path) as heartbeat:
        # An already finished local result can now report immediately without
        # waiting for the periodic heartbeat to repair an obsolete lease.
        assert heartbeat['lease'] == renewed and heartbeat['renewal'] == 1
        assert work._read(heartbeat_path)['lease'] == renewed
    assert len(transport.calls) == 2 and transport.calls[0] == transport.calls[1]
    assert len(transport.committed) == 1


@pytest.mark.parametrize('corruption', ['missing','extra','hash','suffix','tree','statement','sample','model'])
def test_portable_remote_qualification_binding_fails_closed(corruption):
    paths, hashes, identity = remote_producer_fixture()
    sample = {'title':'5','section':'1','text':'Fixture only.'}
    policy = {'source_identity':identity,'validation_samples':[]}
    receipt = {'source_files':paths,'source_sha256':hashes,
               'sample_set_sha256':work.inc._sha({'training':[sample],'heldout':[]}),
               'requested_model_config':{'compute_device':'python'}}
    work._remote_qualification_binding(receipt, policy, [sample])
    if corruption == 'missing': paths.pop('parser')
    elif corruption == 'extra': paths['worker'] = '/remote/worker.py'
    elif corruption == 'hash': hashes['parser'] = '0' * 64
    elif corruption == 'suffix': paths['parser'] = '/foreign/wrong-parser.py'
    elif corruption == 'tree': paths['parser'] = paths['parser'].replace('/remote/', '/other/')
    elif corruption == 'statement': paths['statement_lock'] = paths['statement_lock'].replace('/remote/', '/other/')
    elif corruption == 'sample': receipt['sample_set_sha256'] = '0' * 64
    else: receipt['requested_model_config'] = {'compute_device':'cuda'}
    with pytest.raises(work.DistributedTrainingError):
        work._remote_qualification_binding(receipt, policy, [sample])


def test_explicit_source_metadata_and_exact_usc_citation_are_retained(tmp_path):
    sample = {'title':'5','section':'8410','text':'Fixture text only.','citation':'usc:us:5:8410'}
    source = tmp_path/'source.jsonl'
    source.write_text(json.dumps({'source_span_id':'source-a','sample':sample,
                                  'legal_id':'explicit-legal-id','document_id':'document-a'})+'\n')
    explicit = work.records_from_jsonl(source)[0]
    assert explicit['legal_id'] == 'explicit-legal-id' and explicit['document_id'] == 'document-a'
    source.write_text(json.dumps({'source_span_id':'source-a','sample':sample})+'\n')
    inferred = work.records_from_jsonl(source)[0]
    assert inferred['legal_id'] == sample['citation']
    assert inferred['record_id'] == explicit['record_id']
    source.write_text(json.dumps({**sample,'citation':'5 U.S.C. section 8410'})+'\n')
    assert 'legal_id' not in work.records_from_jsonl(source)[0]


def test_provided_embedding_samples_remain_identical_across_json_and_quack_boundaries(
    tmp_path, cli
):
    sample = {
        "title": "5",
        "section": "1",
        "text": "The agency shall retain records.",
        "embedding_model": "provided:fixture",
        "embedding_vector": [0.2, 0.4, 0.6],
    }
    path = tmp_path / "source.jsonl"
    path.write_text(
        json.dumps({"source_span_id": "usc:5:1:a", "sample": sample}) + "\n"
    )
    records = work.records_from_jsonl(path)
    normalized = cli.normalize(records)
    assert normalized == json.loads(json.dumps(normalized))
    assert records == json.loads(json.dumps(records))
    assert normalized[0]["sample"]["embedding_vector"] == [0.2, 0.4, 0.6]


def test_transient_hub_conflict_retries_boundedly_but_gate_failure_does_not(
    monkeypatch,
):
    calls, sleeps = [], []
    monkeypatch.setattr(work.time, "sleep", lambda seconds: sleeps.append(seconds))

    def upload():
        calls.append(True)
        if len(calls) < 3:
            error = RuntimeError("injected concurrent parent conflict")
            error.response = SimpleNamespace(status_code=409)
            raise error
        return {"uploaded": True, "transport_fixture_only": True}

    assert work.retry_publication(upload)["uploaded"] is True
    assert len(calls) == 3 and len(sleeps) == 2
    calls.clear()

    def invalid_gate():
        calls.append(True)
        raise ValueError("failed unchanged qualification gate")

    with pytest.raises(ValueError, match="qualification gate"):
        work.retry_publication(invalid_gate)
    assert len(calls) == 1


@pytest.mark.parametrize("old_generation_cached", [False, True])
def test_pending_old_assignment_verifies_weights_without_rewinding_current_generation(
    tmp_path, old_generation_cached
):
    old_bytes, current_bytes = b"assigned-older-weights", b"current-canonical-weights"
    old_generation = generation(old_bytes, 1)
    if old_generation_cached:
        work.install_generation(
            old_generation, tmp_path, downloader=checkpoint_downloader(old_bytes, [])
        )
    current = work.install_generation(
        generation(current_bytes, 2),
        tmp_path,
        downloader=checkpoint_downloader(current_bytes, []),
    )
    current_record = (tmp_path / "current.json").read_bytes()
    downloads = []
    installed_for_assignment = work.install_generation(
        old_generation,
        tmp_path,
        downloader=checkpoint_downloader(old_bytes, downloads),
        advertise_current=False,
    )
    assert installed_for_assignment["binding"]["generation"] == 1
    assert installed_for_assignment["materialized_checkpoint"] == raw_ref(old_bytes)
    assert installed_for_assignment["full_weights_verified"] is True
    assert Path(installed_for_assignment["checkpoint_path"]).read_bytes() == old_bytes
    assert len(downloads) == (0 if old_generation_cached else 1)
    assert (tmp_path / "current.json").read_bytes() == current_record
    assert work._read(tmp_path / "current.json") == current
    assert work._read(tmp_path / "1" / "installed.json")["binding"] == old_generation


def test_private_old_assignment_install_still_checks_complete_cached_hash(tmp_path):
    old = work.install_generation(
        generation(b"old-weight-v1", 1),
        tmp_path,
        downloader=checkpoint_downloader(b"old-weight-v1", []),
    )
    work.install_generation(
        generation(b"latest", 2),
        tmp_path,
        downloader=checkpoint_downloader(b"latest", []),
    )
    current_record = (tmp_path / "current.json").read_bytes()
    Path(old["checkpoint_path"]).write_bytes(b"old-weight-v2")
    with pytest.raises(work.DistributedTrainingError, match="hash"):
        work.install_generation(
            generation(b"old-weight-v1", 1),
            tmp_path,
            downloader=lambda *args: pytest.fail(
                "corruption cannot bypass verification"
            ),
            advertise_current=False,
        )
    assert (tmp_path / "current.json").read_bytes() == current_record


@pytest.mark.parametrize("prior_generation_is_current", [True, False])
def test_sparse_install_reuses_exact_complete_local_anchor_without_network(
    tmp_path, monkeypatch, prior_generation_is_current
):
    from ipfs_datasets_py.huggingface import (
        autoencoder_incremental_download as downloads,
    )

    old_bytes, new_bytes = b"previous-complete-weights", b"updated-complete-weights"
    previous = generation(old_bytes, 1)
    old = work.install_generation(
        previous, tmp_path, downloader=checkpoint_downloader(old_bytes, [])
    )
    if not prior_generation_is_current:
        work.install_generation(
            generation(b"another-installed-generation", 2),
            tmp_path,
            downloader=checkpoint_downloader(b"another-installed-generation", []),
        )
    updated = generation(new_bytes, 3)
    updated["weight_reference"].update(
        kind="sparse",
        sha256="f" * 64,
        bytes=123,
        path_in_repo="autoformal/uscode/updates/new-manifest.json",
        anchor_reference=previous["weight_reference"],
    )
    calls = []

    def sparse_download(repository_id, commit, path, digest, destination, **kwargs):
        calls.append((repository_id, commit, path, digest))
        assert kwargs["anchor_reference"] == previous["weight_reference"]
        resolver = kwargs["local_anchor_resolver"]
        assert resolver(previous["artifact"]) == Path(old["checkpoint_path"])
        assert resolver(raw_ref(b"not-installed-anywhere")) is None
        checkpoint = destination / "replayed-complete.json"
        checkpoint.write_bytes(new_bytes)
        return {
            "materialized_checkpoint_path": str(checkpoint),
            "downloaded_bytes": 123,
            "native_execution_performed": False,
        }

    monkeypatch.setattr(downloads, "download_sparse_update", sparse_download)
    monkeypatch.setattr(
        downloads,
        "download_seed_checkpoint",
        lambda *args, **kwargs: pytest.fail("existing complete anchor must stay local"),
    )
    installed = work.install_generation(updated, tmp_path)
    assert len(calls) == 1
    assert installed["binding"] == updated
    assert installed["full_weights_verified"] is True
    assert Path(installed["checkpoint_path"]).read_bytes() == new_bytes
    assert Path(old["checkpoint_path"]).read_bytes() == old_bytes
    assert work._read(tmp_path / "current.json")["binding"]["generation"] == 3


def test_sparse_install_corrupt_cached_anchor_fails_before_advertising_new_generation(
    tmp_path, monkeypatch
):
    from ipfs_datasets_py.huggingface import (
        autoencoder_incremental_download as downloads,
    )

    previous = generation(b"checkpoint-v1", 1)
    old = work.install_generation(
        previous, tmp_path, downloader=checkpoint_downloader(b"checkpoint-v1", [])
    )
    current_bytes = (tmp_path / "current.json").read_bytes()
    # Preserve byte length: only a complete SHA check detects this corruption.
    Path(old["checkpoint_path"]).write_bytes(b"checkpoint-v2")
    updated = generation(b"next-full-checkpoint", 2)
    updated["weight_reference"].update(
        kind="sparse", anchor_reference=previous["weight_reference"]
    )

    def sparse_download(*args, **kwargs):
        kwargs["local_anchor_resolver"](previous["artifact"])
        pytest.fail("a corrupt matching local anchor must not silently redownload")

    monkeypatch.setattr(downloads, "download_sparse_update", sparse_download)
    with pytest.raises(work.DistributedTrainingError, match="hash"):
        work.install_generation(updated, tmp_path)
    assert not (tmp_path / "2" / "installed.json").exists()
    assert (tmp_path / "current.json").read_bytes() == current_bytes


@pytest.mark.parametrize("corrupt_external_anchor", [False, True])
def test_sparse_install_rechecks_full_hash_of_external_owner_anchor(
    tmp_path, monkeypatch, corrupt_external_anchor
):
    from ipfs_datasets_py.huggingface import (
        autoencoder_incremental_download as downloads,
    )

    original, candidate = b"external-anchor-v1", b"replayed-next-generation"
    external = tmp_path / "owner-cas-anchor"
    external.write_bytes(b"external-anchor-v2" if corrupt_external_anchor else original)
    parent = generation(original, 1)
    updated = generation(candidate, 2)
    updated["weight_reference"].update(
        kind="sparse", anchor_reference=parent["weight_reference"]
    )
    requests = []

    def external_resolver(expected):
        requests.append(expected)
        assert expected == parent["artifact"]
        return external

    def sparse_download(*args, **kwargs):
        resolved = kwargs["local_anchor_resolver"](parent["artifact"])
        assert resolved == external
        assert not corrupt_external_anchor  # A same-size wrong SHA must fail first.
        path = args[4] / "replayed.json"
        path.write_bytes(candidate)
        return {
            "materialized_checkpoint_path": str(path),
            "downloaded_bytes": 123,
            "native_execution_performed": False,
        }

    monkeypatch.setattr(downloads, "download_sparse_update", sparse_download)
    state = tmp_path / "installed"
    if corrupt_external_anchor:
        with pytest.raises(work.DistributedTrainingError, match="hash"):
            work.install_generation(updated, state, anchor_resolver=external_resolver)
        assert not (state / "2" / "installed.json").exists()
        assert not (state / "current.json").exists()
    else:
        installed = work.install_generation(
            updated, state, anchor_resolver=external_resolver
        )
        assert installed["materialized_checkpoint"] == raw_ref(candidate)
        assert installed["full_weights_verified"] is True
    assert requests == [parent["artifact"]]


@pytest.mark.parametrize('defer_phase', ['reservation', 'dispatch', 'retry'])
def test_capacity_deferral_does_not_cache_incomplete_training_result(tmp_path, monkeypatch, defer_phase):
    monkeypatch.setattr(work, 'identity', lambda: {'fixture': 'source'})
    monkeypatch.setattr(work, 'training_config', lambda *args: {'fixture': True})
    policy = {'source_identity': {'fixture': 'source'}, 'validation_samples': []}
    assignment = {'record': {'sample': {'text': 'Bounded transport fixture'}}}
    def execute(config):
        if defer_phase == 'reservation':
            return {'deferred': True}
        receipt = tmp_path / 'cycle.json'
        receipt.write_text(json.dumps({'training': {'completed': ([{'round': 1, 'qualification_status': 'pending'}] if defer_phase == 'retry' else []), 'batch_status_counts': {'pending': 1}, 'capacity_deferred': True}}))
        return {'receipt': str(receipt)}
    job = tmp_path / 'job'
    with pytest.raises(work.CapacityDeferred):
        work.execute_assignment(assignment, policy, {'checkpoint_path': 'fixture'}, job, execute_cycle=execute)
    assert not (job / 'training-result.json').exists()
    assert not (job / 'result.json').exists()
