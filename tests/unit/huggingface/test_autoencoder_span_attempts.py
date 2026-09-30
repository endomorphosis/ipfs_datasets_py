"""Attempt transport fixtures do not run training, provers or Lake."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.huggingface import autoencoder_span_attempts as attempts
from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
from ipfs_datasets_py.logic.autoformal.span_cache_feed import source_records


def put(registry, directory, value):
    raw = value if isinstance(value, bytes) else attempts._json(value)
    path = directory / (hashlib.sha256(raw).hexdigest() + ".input")
    path.write_bytes(raw)
    return registry.stage_artifact(path)


@pytest.fixture
def case(tmp_path):
    with AutoencoderRegistry(
        tmp_path / "owner.duckdb", tmp_path / "artifacts"
    ) as registry:
        registry.register_variant(
            "variant-operation", "fixture", {"source_language": "en"}
        )
        artifact = put(registry, tmp_path, b"fixture-not-model-weights\n")
        version = registry.register_version("version-operation", "fixture", artifact)[
            "version_id"
        ]
        rows = []
        for index, days in enumerate((20, 30)):
            source = {
                "title": "5",
                "section": str(index),
                "text": f"The officer shall retain the file for at least {days} days.",
            }
            metric = {
                "passed": True,
                "embedding_cosine_similarity": 0.9,
                "reconstruction_loss": 0.1,
                "min_cosine": 0.72,
                "max_reconstruction_loss": 0.2,
            }
            rows.append(
                {
                    "sample_id": f"fixture-{index}",
                    "split": "training" if index == 0 else "heldout",
                    "source": source,
                    "source_sha256": hashlib.sha256(
                        source["text"].encode()
                    ).hexdigest(),
                    "metric_gate": metric,
                    "semantic_gate": {
                        "passed": False,
                        "reason": "unsupported_semantics",
                    },
                    "family_syntax_gate": {
                        "passed": False,
                        "reason": "fixture_no_family",
                    },
                    "family_coverage_gate": {"passed": False, "reason": "fixture_no_coverage"},
                    "lake_gate": {"passed": False, "reason": "fixture_no_lake"},
                    "compiler": {"compiler_status": "abstained"},
                    "admitted": False,
                    "formalized": False,
                    "qualified": False,
                }
            )
        gates = {
            gate: {"passed": gate in ("metric_gate", "heldout_gate")}
            for gate in attempts.GATES
        }
        todo = {
            "kind": "source_repair",
            "sample_id": rows[0]["sample_id"],
            "gate": "semantic_gate",
            "evidence": rows[0]["semantic_gate"],
            "acceptance": "Keep every unchanged gate; repair source meaning.",
            "admitted": False,
        }
        receipt = {
            "schema_version": "autoencoder-candidate-qualification/v1",
            "execution_mode": "native_candidate_qualification",
            "unit_test_transport_only": True,
            "candidate_version_id": version,
            "candidate_artifact": artifact,
            "materialized_checkpoint": artifact,
            "rows": rows,
            "sample_count": 1,
            "heldout_sample_count": 1,
            "gate_results": gates,
            **gates,
            "qualified": False,
            "admitted": False,
            "formalized": False,
            "repair_todos": [todo],
            "source_sha256": {"qualification": "f" * 64},
            "sample_set_sha256": "e" * 64,
            "qualification_scope": "embedding_model_and_deterministic_source_compiler_pipeline",
            "model_emits_text_or_formulas": False,
        }
        source_record = {
            "record_id": "sha256:" + "a" * 64,
            "source_span_id": "uscode-fixture-1",
            "source_text_sha256": rows[0]["source_sha256"],
            "text": rows[0]["source"]["text"],
            "sample": deepcopy(rows[0]["source"]),
            "legal_id": "usc:5:1",
            "observations": [{"provenance": "retained_original_fixture"}],
        }
        provenance = {
            "source_record": source_record,
            "canonical_generation": 1,
            "canonical_version_id": version,
            "canonical_artifact": artifact,
        }
        yield SimpleNamespace(
            registry=registry,
            root=tmp_path,
            version=version,
            artifact=artifact,
            receipt=receipt,
            provenance=provenance,
        )


def stage(case, **kwargs):
    ref = put(case.registry, case.root, case.receipt)
    return attempts.stage_span_attempt(
        case.registry,
        case.version,
        ref,
        case.root / "attempt",
        work_id="work-1",
        span_revision=case.provenance["source_record"]["record_id"],
        sample_id="fixture-0",
        source_provenance=case.provenance,
        disposition=kwargs.pop("disposition", "needs_repair"),
        attempt_index=0,
        agent_id="transport-test",
        **kwargs,
    )


class Hub:
    def __init__(self, lost_reply=False):
        self.sha = "1" * 40
        self.files = {}
        self.commits = 0
        self.lost_reply = lost_reply

    def repo_info(self, **kwargs):
        return SimpleNamespace(sha=self.sha)

    def get_paths_info(self, repository, paths, **kwargs):
        assert kwargs["revision"] == self.sha
        return [
            SimpleNamespace(
                path=path, lfs={"sha256": hashlib.sha256(self.files[path]).hexdigest()}
            )
            for path in paths
            if path in self.files
        ]

    def create_commit(self, **kwargs):
        assert kwargs["parent_commit"] == self.sha
        self.commits += 1
        for operation in kwargs["operations"]:
            self.files[operation.path_in_repo] = operation.path_or_fileobj
        self.sha = f"{self.commits + 1:040x}"
        if self.lost_reply:
            self.lost_reply = False
            raise OSError("simulated lost successful reply")
        return SimpleNamespace(oid=self.sha)


def test_failed_attempt_retains_source_receipt_and_real_exchange_goals(case):
    staged = stage(case)
    loaded = attempts.load_span_attempt(staged["report_path"])
    report, bundle = loaded["report"], loaded["bundle"]
    assert report["qualification"] == case.receipt
    assert report["repair_todos"] == case.receipt["repair_todos"]
    assert report["source_provenance"] == case.provenance
    assert len(bundle["repair_packets"]) == 4
    assert {item["packet"]["row"]["capture"]["failed_gate"] for item in bundle["repair_packets"]} == set(attempts.GATES[1:-1])
    assert not bundle["training_goals"]
    census = bundle["census_rows"][0]
    assert census["admitted"] is False and census["formalized"] is False
    assert census["autoencoder_text"] == "" and census["cross_entropy_loss"] is None
    assert census["cosine_similarity"] == 0.9
    assert census["compiler_roundtrip"] is False
    assert (
        len(
            source_records(
                bundle,
                repository_id=attempts.REPOSITORY,
                revision="1" * 40,
                manifest_in_repo=bundle["manifest"]["path_in_repo"],
            )
        )
        == 1
    )
    for packet in bundle["repair_packets"]:
        capture = packet["packet"]["row"]["capture"]
        assert capture["observation_evidence"] == attempts.exchange._observation_evidence(census)
        assert capture["qualification_artifact"] == report["qualification_artifact"]
        assert capture["qualification_gate_results"] == case.receipt["gate_results"]
        assert (
            capture["repair_todos"][0]["acceptance"]
            == case.receipt["repair_todos"][0]["acceptance"]
        )
    assert stage(case) == staged


def test_exhausted_metric_or_validation_attempt_gets_training_goal(case):
    case.receipt["gate_results"]["heldout_gate"]["passed"] = False
    staged = stage(case, disposition="training_exhausted")
    loaded = attempts.load_span_attempt(staged["report_path"])
    assert loaded["report"]["disposition"] == "training_exhausted"
    assert len(loaded["bundle"]["training_goals"]) == 1
    assert (
        loaded["bundle"]["training_goals"][0]["capture"]["qualification_gate_results"][
            "heldout_gate"
        ]["passed"]
        is False
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.receipt.update(qualified=True),
        lambda c: c.receipt["gate_results"]["semantic_gate"].update(passed=True),
        lambda c: c.receipt["rows"][0].update(source_sha256="0" * 64),
        lambda c: c.provenance.update(canonical_generation=0),
        lambda c: c.provenance["source_record"]["sample"].update(text="another source"),
        lambda c: c.receipt.update(candidate_version_id="another-candidate"),
        lambda c: c.receipt.update(admitted=True),
        lambda c: c.receipt.pop("repair_todos"),
    ],
)
def test_inconsistent_or_incomplete_evidence_rejected(case, mutation):
    mutation(case)
    with pytest.raises((ValueError, KeyError)):
        stage(case)


def test_constitution_failure_can_be_exported_but_roundtrip_is_refused(case):
    case.receipt["rows"][0]["source"]["title"] = "US Constitution"
    case.provenance["source_record"]["sample"]["title"] = "US Constitution"
    stage(case)
    case.receipt["rows"][0]["compiler"]["roundtrip"] = True
    with pytest.raises(attempts.SpanAttemptError, match="Constitution"):
        stage(case)


def test_atomic_publication_small_report_download_and_idempotent_retry(case, tmp_path):
    staged = stage(case)
    hub = Hub()
    published = attempts.publish_span_attempt(
        staged["report_path"], upload=True, api=hub
    )
    assert len(hub.files) == 4 and hub.commits == 1
    assert published["report_reference"]["bytes"] < 200_000
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        assert kwargs["revision"] == published["commit_sha"]
        path = tmp_path / "download.raw"
        path.write_bytes(hub.files[kwargs["filename"]])
        return path

    downloaded = attempts.download_span_attempt_report(
        published["report_reference"], tmp_path / "remote", downloader=download
    )
    assert downloaded["report"]["qualification"] == case.receipt
    assert downloaded["owner_requalification_required"] is True and len(calls) == 1
    replay = attempts.publish_span_attempt(staged["report_path"], upload=True, api=hub)
    assert (
        hub.commits == 1 and replay["report_reference"] == published["report_reference"]
    )


def test_report_download_rejects_mutable_revision_hash_mismatch_and_bound(case):
    staged = stage(case)
    hub = Hub()
    reference = attempts.publish_span_attempt(
        staged["report_path"], upload=True, api=hub
    )["report_reference"]
    with pytest.raises(attempts.SpanAttemptError):
        attempts.download_span_attempt_report(
            {**reference, "commit_sha": "main"}, case.root / "bad"
        )
    with pytest.raises(attempts.SpanAttemptError):
        attempts.download_span_attempt_report(reference, case.root / "bad", max_bytes=1)
    corrupt = case.root / "corrupt.json"
    corrupt.write_bytes(b"{}")
    with pytest.raises(ValueError):
        attempts.download_span_attempt_report(
            reference, case.root / "bad", downloader=lambda **kwargs: corrupt
        )


def test_outbox_lost_reply_recovery_and_dry_run_does_not_claim(case):
    staged = stage(case)
    queued = attempts.enqueue_span_attempt(case.registry, staged["report_path"])
    assert queued == attempts.enqueue_span_attempt(case.registry, staged["report_path"])
    assert (
        attempts.deliver_span_attempt(case.registry, queued["event_id"])["uploaded"]
        is False
    )
    assert (
        case.registry.get_outbox_event("huggingface", queued["event_id"])["status"]
        == "pending"
    )
    hub = Hub(lost_reply=True)
    with pytest.raises(OSError):
        attempts.deliver_span_attempt(
            case.registry, queued["event_id"], upload=True, api=hub
        )
    assert (
        case.registry.get_outbox_event("huggingface", queued["event_id"])["status"]
        == "leased"
    )
    done = attempts.deliver_span_attempt(
        case.registry, queued["event_id"], upload=True, api=hub
    )
    assert done["acknowledged"] and hub.commits == 1
    assert attempts.deliver_span_attempt(
        case.registry, queued["event_id"], upload=True, api=hub
    )["already_delivered"]


def test_failed_attempt_refuses_weight_reference(case):
    ref = {
        "kind": "anchor",
        "repository_id": attempts.REPOSITORY,
        "commit_sha": "1" * 40,
        "path_in_repo": "autoformal/uscode/weights/fixture.json",
        **case.artifact,
        "materialized_checkpoint": case.artifact,
    }
    with pytest.raises(attempts.SpanAttemptError, match="failed qualification"):
        stage(case, weight_publication=ref)


def test_qualified_transport_fixture_full_snapshot_binding_and_no_todos(case):
    # These booleans test transport consistency only. Remote promotion must rerun native qualification.
    for row in case.receipt["rows"]:
        for gate in attempts.GATES[:-1]:
            row[gate]["passed"] = True
        row["qualified"] = True
    for gate in attempts.GATES:
        case.receipt["gate_results"][gate]["passed"] = True
    case.receipt["qualified"] = True
    case.receipt["repair_todos"] = []
    ref = {
        "kind": "anchor",
        "repository_id": attempts.REPOSITORY,
        "commit_sha": "1" * 40,
        "path_in_repo": "autoformal/uscode/weights/fixture.json",
        **case.artifact,
        "materialized_checkpoint": case.artifact,
    }
    staged = stage(case, disposition="qualified", weight_publication=ref)
    loaded = attempts.load_span_attempt(staged["report_path"])
    assert loaded["report"]["weight_publication"] == ref
    assert not loaded["bundle"]["goal_rows"]
    assert loaded["report"]["admitted"] is False
    ref["materialized_checkpoint"] = {"sha256": "0" * 64, "bytes": 1}
    with pytest.raises(attempts.SpanAttemptError, match="materialized checkpoint"):
        stage(case, disposition="qualified", weight_publication=ref)


def test_census_mutation_is_detected(case):
    staged = stage(case)
    bundle = exchange.load_exchange_bundle(staged["exchange_manifest_path"])
    path = Path(bundle["census_path"])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        attempts.load_span_attempt(staged["report_path"])


def test_sparse_reference_uses_replayed_ancestor_not_manifest_hash(case):
    for row in case.receipt["rows"]:
        for gate in attempts.GATES[:-1]:
            row[gate]["passed"] = True
        row["qualified"] = True
    for gate in attempts.GATES:
        case.receipt["gate_results"][gate]["passed"] = True
    case.receipt["qualified"] = True
    case.receipt["repair_todos"] = []
    qualification_ref = put(case.registry, case.root, case.receipt)
    base = {
        "kind": "anchor",
        "repository_id": attempts.REPOSITORY,
        "commit_sha": "1" * 40,
        "path_in_repo": "autoformal/uscode/weights/base.json",
        **case.artifact,
        "materialized_checkpoint": case.artifact,
    }
    ancestor = {
        "kind": "sparse",
        "repository_id": attempts.REPOSITORY,
        "commit_sha": "2" * 40,
        "path_in_repo": "autoformal/uscode/weights/prior-update.json",
        "sha256": "b" * 64,
        "bytes": 10,
        "materialized_checkpoint": {"sha256": "c" * 64, "bytes": 100},
        "anchor_reference": base,
    }
    manifest = {
        "schema": attempts.incremental.SCHEMA,
        "path_in_repo": "autoformal/uscode/weights/update.json",
        "version": {"version_id": case.version},
        "checkpoint_artifact": case.artifact,
        "qualification_artifact": qualification_ref,
        "materialized_checkpoint": case.artifact,
        "qualified_candidate_only": True,
        "anchor_checkpoint": ancestor["materialized_checkpoint"],
    }
    manifest_ref = put(case.registry, case.root, manifest)
    reference = {
        "kind": "sparse",
        "repository_id": attempts.REPOSITORY,
        "commit_sha": "3" * 40,
        "path_in_repo": manifest["path_in_repo"],
        **manifest_ref,
        "materialized_checkpoint": case.artifact,
        "anchor_reference": ancestor,
    }
    staged = stage(case, disposition="qualified", weight_publication=reference)
    assert (
        attempts.load_span_attempt(staged["report_path"])["report"]["weight_manifest"]
        == manifest
    )
    reference["anchor_reference"] = {
        **ancestor,
        "materialized_checkpoint": {"sha256": "d" * 64, "bytes": 100},
    }
    with pytest.raises(attempts.SpanAttemptError, match="exact qualified attempt"):
        stage(case, disposition="qualified", weight_publication=reference)


def test_heldout_source_failure_still_exports_contextual_goal(case):
    for name in attempts.GATES[1:-1]:
        case.receipt["rows"][0][name]["passed"] = True
    case.receipt["rows"][0]["qualified"] = True
    staged = stage(case)
    loaded = attempts.load_span_attempt(staged["report_path"])
    assert len(loaded["bundle"]["training_goals"]) == 1
    capture = loaded["bundle"]["training_goals"][0]["capture"]
    assert (
        loaded["report"]["qualification"]["rows"][1]["semantic_gate"]["passed"] is False
    )
    assert capture["qualification_gate_results"]["semantic_gate"]["passed"] is False


def test_large_retained_provenance_is_referenced_in_bounded_goal_packets(case):
    case.provenance["source_record"]["observations"].append(
        {"large_retained_evidence": "x" * 600_000}
    )
    staged = stage(case)
    loaded = attempts.load_span_attempt(staged["report_path"])
    assert loaded["report"]["source_provenance"] == case.provenance
    for row in loaded["bundle"]["goal_rows"]:
        assert len(row["packet_json"].encode()) < 512 * 1024
        capture = json.loads(row["packet_json"])["row"]["capture"]
        assert capture["source_provenance_sha256"] == attempts.incremental._sha(
            attempts._json(case.provenance)
        )
        assert (
            capture["census_sha256"]
            == loaded["bundle"]["census_rows"][0]["census_sha256"]
        )


def test_family_coverage_failure_survives_census_goal_export(case):
    for row in case.receipt["rows"]:
        for name in attempts.GATES[1:-1]:
            row[name]["passed"] = name != "family_coverage_gate"
    for name in attempts.GATES:
        case.receipt["gate_results"][name]["passed"] = name != "family_coverage_gate"
    case.receipt["repair_todos"][0].update(gate="family_coverage_gate",
        evidence=case.receipt["rows"][0]["family_coverage_gate"])
    loaded = attempts.load_span_attempt(stage(case)["report_path"])
    assert not loaded["report"]["qualification"]["qualified"]
    assert len(loaded["bundle"]["repair_packets"]) == 1
    capture = loaded["bundle"]["repair_packets"][0]["packet"]["row"]["capture"]
    assert capture["failed_gate"] == "family_coverage_gate"
    assert capture["original_gate_evidence"] == case.receipt["rows"][0]["family_coverage_gate"]
    assert capture["observation_evidence"] == attempts.exchange._observation_evidence(loaded["bundle"]["census_rows"][0])


def test_historical_receipt_without_coverage_is_not_silently_upgraded(case):
    case.receipt["gate_results"].pop("family_coverage_gate")
    case.receipt.pop("family_coverage_gate")
    for row in case.receipt["rows"]:
        row.pop("family_coverage_gate")
    with pytest.raises(attempts.SpanAttemptError, match="gate evidence|qualification gate"):
        stage(case)
