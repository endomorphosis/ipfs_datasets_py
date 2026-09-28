"""Real owner catalog/leases; synthetic bytes test control, never model quality."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.autoencoder_quack import RegistryQuackGateway, RegistryTransportError, WorkerScope, _envelope
from ipfs_datasets_py.duckdb_control.autoencoder_span_campaign import (
    AutoencoderSpanCampaign, SpanCampaignError, SpanCampaignQuackGateway, SpanCampaignTransportClient,
)
from tests.unit.duckdb_control.test_autoencoder_registry import Clock, seed, staged
from tests.unit.duckdb_control.test_autoencoder_quack import native_available

REPOSITORY = "test-owner/span-campaign-fixture"


def reference(artifact):
    return {"kind": "anchor", "repository_id": REPOSITORY, "commit_sha": "a" * 40,
            "path_in_repo": "synthetic/" + artifact["sha256"] + ".json", **artifact,
            "materialized_checkpoint": artifact}


def record(text="The officer shall retain the file for at least 20 days."):
    return {"record_id": hashlib.sha256(text.encode()).hexdigest(), "sample": {"text": text},
            "provenance": {"fixture": True}}


def campaign(registry, tmp_path, *, policy=None):
    version = seed(registry, tmp_path)
    return AutoencoderSpanCampaign(registry, campaign_id="fixture", variant_id="english",
        base_version_id=version["version_id"], policy=policy or {"fixture": True}, result_repository=REPOSITORY,
        seed_weight_reference=reference(registry.get_version(version["version_id"])["artifact"]))


def ack(control, worker="worker-a"):
    weights = control.status()["weights"]
    return control.acknowledge_weights("ack-" + str(weights["generation"]), worker,
        **{key: weights[key] for key in ("generation", "version_id", "artifact")})


def remote_report(path="synthetic/report.json"):
    return {"repository": REPOSITORY, "revision": "b" * 40, "path": path, "sha256": "c" * 64, "bytes": 42}


def verify_fixture(registry, tmp_path, disposition="qualified"):
    artifact = staged(registry, tmp_path, "candidate")
    def verify(assignment, report):
        assert assignment["record"]["sample"]["text"]
        assert report["revision"] == "b" * 40
        return {"artifact": artifact, "result": {"admitted": False, "owner_verified": True,
                "span_disposition": disposition, "qualified": disposition == "qualified", "execution_mode": "injected_test"}}
    return verify


def test_registration_is_idempotent_and_census_observations_do_not_retrain(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        first = record()
        a = control.register_records([first])
        b = control.register_records([{**first, "provenance": {"revision": "changed"}, "observations": [1, 2]}])
        assert a == b
        assert control.status()["counts"] == {"queued": 1}
        changed = {**first, "sample": {"text": first["sample"]["text"] + " Updated source."}}
        assert control.register_records([changed]) != a
        assert control.status()["counts"] == {"queued": 2}
        with registry._transaction() as cx:
            assert cx.execute("SELECT count(*) FROM autoencoder_control.operations WHERE json_extract_string(receipt,'$.command')='ObserveSpanSource'").fetchone()[0] == 3


def test_large_observations_use_owner_cas_and_preserve_publisher_source_fields(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        first = record()
        text = first["sample"]["text"]
        first.update(source_span_id="uscode:42:1983:span1", text=text,
                     source_text_sha256=hashlib.sha256(text.encode()).hexdigest(), legal_id="42 USC 1983",
                     observations=[{"large_audit": "x" * 1200000}])
        work = control.register_records([first])[0]
        before = registry.get_run(work)["spec"]
        second = {**first, "observations": [{"large_audit": "y" * 1200000}]}
        assert control.register_records([second]) == [work]
        assert registry.get_run(work)["spec"] == before
        assert "observations" not in before["record"]
        ack(control)
        assignment = control.claim_next("claim", "worker-a")["assignment"]
        assert assignment["record"] == {key: first[key] for key in
                ("record_id", "sample", "source_span_id", "text", "source_text_sha256", "legal_id")}
        assert json.loads(registry.artifact_path(assignment["observation_artifact"]).read_bytes()) == first
        with registry._transaction() as cx:
            rows = cx.execute("SELECT receipt FROM autoencoder_control.operations WHERE json_extract_string(receipt,'$.command')='ObserveSpanSource'").fetchall()
        assert len(rows) == 2 and all(len(row[0]) < 2048 for row in rows)
        retained = [json.loads(registry.artifact_path(json.loads(row[0])["observation_artifact"]).read_bytes()) for row in rows]
        assert first in retained and second in retained


@pytest.mark.parametrize("field,value", [("source_span_id", "another-span"), ("legal_id", "another citation"),
                                         ("text", "contradictory text"), ("source_text_sha256", "0" * 64)])
def test_source_identity_corruption_rejected_without_retraining(tmp_path, field, value):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        first = {**record(), "source_span_id": "original-span", "legal_id": "42 USC 1983"}
        control.register_records([first])
        with pytest.raises(SpanCampaignError, match="source"):
            control.register_records([{**first, field: value}])
        assert control.status()["counts"] == {"queued": 1}


def test_bare_sample_derives_required_source_fields_and_observation_limit_is_bounded(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        first = record()
        work = control.register_records([first])[0]
        source = registry.get_run(work)["spec"]["record"]
        assert source["source_span_id"] == first["record_id"]
        assert source["text"] == first["sample"]["text"]
        assert source["source_text_sha256"] == hashlib.sha256(source["text"].encode()).hexdigest()
        with pytest.raises(SpanCampaignError, match="byte bound"):
            control.register_records([{**first, "observations": ["x" * (8 * 1024 * 1024)]}])


def test_assignment_preserves_bounded_original_hub_locators_and_observation_digest(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        observations = [{"repository_id": REPOSITORY, "revision": f"{index:040x}",
            "manifest_in_repo": f"autoformal/uscode/exchanges/source/exchange-{index:064x}.manifest.json",
            "fingerprint": f"{index:064x}", "manifest_sha256": f"{index + 10:064x}",
            "census_sha256": f"{index + 20:064x}", "census_row": {"huge": "x" * 200000},
            "input": {"private_arbitrary_payload": "retained only in full observation"}} for index in range(6)]
        original = {**record(), "observations": observations}
        work = control.register_records([original])[0]
        ack(control)
        assigned = control.claim_next("claim", "worker-a")["assignment"]
        portable = assigned["source_observation"]
        assert portable["artifact"] == assigned["observation_artifact"]
        assert portable["observation_count"] == portable["locator_count"] == 6
        assert portable["locators_truncated"] is True
        assert portable["source_authority_authenticated"] is False
        assert len(portable["hub_locators"]) == 4 and len(json.dumps(portable)) < 8192
        fields = {"repository_id", "revision", "manifest_in_repo", "fingerprint", "manifest_sha256", "census_sha256"}
        for locator in portable["hub_locators"]:
            assert set(locator) == fields
            assert locator in [{key: row[key] for key in fields} for row in observations]
        retained = json.loads(registry.artifact_path(portable["artifact"]).read_bytes())
        assert retained == original
        assert control.register_records([{**original, "observations": list(reversed(observations))}]) == [work]
        assert control.read(assigned["run_id"], worker_id="worker-a")["assignment"]["source_observation"] == portable


def test_invalid_or_moving_hub_source_locator_is_not_exported_as_immutable(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        invalid = {"repository_id": REPOSITORY, "revision": "main", "manifest_in_repo": "source/manifest.json",
                   "fingerprint": "a" * 64, "manifest_sha256": "b" * 64, "census_sha256": "c" * 64}
        with pytest.raises(SpanCampaignError, match="immutable Hub commit"):
            control.register_records([{**record(), "observations": [invalid]}])
        assert control.status()["counts"] == {}


def test_claim_requires_current_full_weight_ack_and_is_idempotent(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        work = control.register_records([record()])[0]
        with pytest.raises(SpanCampaignError, match="acknowledge current"):
            control.claim_next("claim", "worker-a")
        ack(control)
        claimed = control.claim_next("claim", "worker-a")
        assert claimed == control.claim_next("claim", "worker-a")
        assert claimed["assignment"]["work_id"] == work
        assert claimed["assignment"]["run_id"] != work
        assert claimed["weights"]["generation"] == 1
        assert registry.get_run(work)["base_version_id"] == control.seed["version_id"]
        ack(control, "worker-b")
        assert control.claim_next("empty", "worker-b")["status"] == "empty"
        with pytest.raises(RegistryError, match="different payload"):
            control.claim_next("claim", "worker-a", 999)


def test_two_workers_claim_disjoint_work_and_stale_lease_cannot_report(tmp_path):
    clock = Clock()
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts", clock=clock) as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record("Source A"), record("Source B")])
        ack(control, "worker-a")
        ack(control, "worker-b")
        with ThreadPoolExecutor(2) as pool:
            claimed = list(pool.map(lambda worker: control.claim_next("claim", worker, 10), ["worker-a", "worker-b"]))
        assert len({row["lease"]["run_id"] for row in claimed}) == 2
        clock.now += 11
        retry = control.claim_next("retry", "worker-b", 10)
        old = next(row for row in claimed if row["lease"]["run_id"] == retry["lease"]["run_id"])
        assert retry["lease"]["fence"] == old["lease"]["fence"] + 1
        if old["lease"]["worker_id"] != retry["lease"]["worker_id"]:
            observed = control.read(old["lease"]["run_id"], worker_id=old["lease"]["worker_id"])
            assert observed["lease_live"] is False and observed["lease"] is None
        with pytest.raises(RegistryError, match="stale"):
            control.report("old-report", old["lease"]["worker_id"], old["lease"], remote_report())


def test_renewal_keeps_source_and_attempt_leases_synchronized(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        work = control.register_records([record()])[0]
        ack(control)
        claimed = control.claim_next("claim", "worker-a")
        renewed = control.renew("renew", "worker-a", claimed["lease"], 400)
        assert renewed == control.renew("renew", "worker-a", claimed["lease"], 400)
        assert registry.get_run(work)["lease"] == registry.get_run(claimed["lease"]["run_id"])["lease"] == renewed["lease"]
        with pytest.raises(RegistryError, match="stale"):
            control.report("report", "worker-a", claimed["lease"], remote_report())


def test_remote_report_is_pending_evidence_until_owner_verifies(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record()])
        ack(control)
        claimed = control.claim_next("claim", "worker-a")
        pending = control.report("report", "worker-a", claimed["lease"], remote_report())
        assert pending["status"] == "awaiting_verification" and pending["qualified"] is False
        assert control.report("report", "worker-a", claimed["lease"], remote_report()) == pending
        assert registry.get_run_completion(claimed["lease"]["run_id"]) is None
        def broken(*args):
            raise ValueError("owner validation failed")
        with pytest.raises(ValueError, match="validation failed"):
            control.verify_reports(broken)
        assert control.status()["counts"] == {"awaiting_verification": 1}
        completed = control.verify_reports(verify_fixture(registry, tmp_path))
        assert completed[0]["span_disposition"] == "qualified"
        assert completed[0]["admitted"] is False
        assert control.status()["weights"]["generation"] == 1
        assert control.status()["counts"] == {"source_completed": 1}
        assert control.read(claimed["lease"]["run_id"], worker_id="worker-a")["status"] == "completed"


def test_pending_report_survives_owner_restart_and_is_not_reassigned(tmp_path):
    path, artifacts = tmp_path / "owner.db", tmp_path / "artifacts"
    with AutoencoderRegistry(path, artifacts) as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record()])
        ack(control)
        claimed = control.claim_next("claim", "worker-a", 1)
        control.report("report", "worker-a", claimed["lease"], remote_report())
    with AutoencoderRegistry(path, artifacts) as registry:
        control = campaign(registry, tmp_path)
        ack(control, "worker-b")
        assert control.claim_next("claim", "worker-b")["status"] == "empty"
        result = control.verify_reports(verify_fixture(registry, tmp_path))[0]
        assert registry.get_run_completion(result["run_id"])["candidate_version"]["version_id"] == result["version_id"]


def test_completion_response_loss_recovers_without_reverification(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record()])
        ack(control)
        claimed = control.claim_next("claim", "worker-a")
        control.report("report", "worker-a", claimed["lease"], remote_report())
        original = registry.complete_run
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("lost completion reply")
        monkeypatch.setattr(registry, "complete_run", lost)
        with pytest.raises(RuntimeError, match="lost completion"):
            control.verify_reports(verify_fixture(registry, tmp_path))
        def should_not_repeat(*args):
            pytest.fail("committed owner qualification must not repeat")
        result = control.verify_reports(should_not_repeat)
        assert result[0]["status"] == "completed"
        assert control.status()["counts"] == {"source_completed": 1}


def test_new_generation_requires_ack_and_stale_sibling_rebases_with_new_immutable_run(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record("Source A"), record("Source B")])
        ack(control, "worker-a")
        ack(control, "worker-b")
        first = control.claim_next("first", "worker-a")
        second = control.claim_next("second", "worker-b")
        control.report("report-a", "worker-a", first["lease"], remote_report())
        finished = control.verify_reports(verify_fixture(registry, tmp_path))[0]
        version = registry.get_version(finished["version_id"])
        old = control.status()["weights"]
        advance = control.advance_generation("advance", version["version_id"], expected_generation=1,
            expected_version_id=old["version_id"], weight_reference=reference(version["artifact"]))
        assert advance["generation"] == 2
        assert control.status()["acknowledged_current_workers"] == []
        with pytest.raises(SpanCampaignError, match="acknowledge current"):
            control.claim_next("next", "worker-a")
        control.report("report-b", "worker-b", second["lease"], remote_report("synthetic/second.json"))
        stale = control.verify_reports(verify_fixture(registry, tmp_path))[0]
        assert stale["span_disposition"] == "rebase_required"
        with pytest.raises(SpanCampaignError, match="CAS conflict"):
            control.advance_generation("stale-advance", stale["version_id"], expected_generation=1,
                expected_version_id=old["version_id"], weight_reference=reference(version["artifact"]))
        ack(control, "worker-b")
        retried = control.claim_next("new-generation", "worker-b")
        assert retried["assignment"]["work_id"] == second["assignment"]["work_id"]
        assert retried["lease"]["run_id"] != second["lease"]["run_id"]
        assert retried["assignment"]["base_version_id"] == version["version_id"]
        assert registry.get_run(second["lease"]["run_id"])["base_version_id"] == old["version_id"]


@pytest.mark.parametrize("disposition", ["needs_repair", "training_exhausted"])
def test_unqualified_candidate_cannot_advance_canonical_generation(tmp_path, disposition):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record()])
        ack(control)
        claimed = control.claim_next("claim", "worker-a")
        control.report("report", "worker-a", claimed["lease"], remote_report())
        done = control.verify_reports(verify_fixture(registry, tmp_path, disposition))[0]
        version = registry.get_version(done["version_id"])
        with pytest.raises(SpanCampaignError, match="qualified child"):
            control.advance_generation("advance", done["version_id"], expected_generation=1,
                expected_version_id=control.seed["version_id"], weight_reference=reference(version["artifact"]))


def test_scoped_gateway_rejects_remote_authority_and_generic_worker_bypass(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        work = control.register_records([record()])[0]
        gateway = SpanCampaignQuackGateway(control, "worker-a")
        envelope = SpanCampaignTransportClient._request_envelope
        with pytest.raises(SpanCampaignError, match="closed span"):
            gateway.dispatch(envelope("ReportSpan", {"lease": {}, "report_descriptor": remote_report(), "qualified": True}, "forged"))
        generic = RegistryQuackGateway(registry, WorkerScope("worker-a", frozenset({work})), enable_prototype=True)
        with pytest.raises(RegistryTransportError, match="owner-verified"):
            generic.dispatch(_envelope("ClaimRun", {"run_id": work}, "bypass"))
        ack(control)
        claimed = control.claim_next("claim", "worker-a")
        with pytest.raises(SpanCampaignError, match="another worker"):
            control.report("bad-worker", "worker-b", claimed["lease"], remote_report())
        with pytest.raises(SpanCampaignError, match="outside worker"):
            control.read(claimed["lease"]["run_id"], worker_id="worker-b")
        with pytest.raises(SpanCampaignError, match="immutable Hub commit"):
            control.report("main", "worker-a", claimed["lease"], {**remote_report(), "revision": "main"})


def test_native_publisher_reference_preserves_closed_descriptor_for_owner_downloader(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record()])
        ack(control)
        claim = control.claim_next("claim", "worker-a")
        ref = {"repository_id": REPOSITORY, "commit_sha": "b" * 40,
               "path_in_repo": "synthetic/report.json", "sha256": "c" * 64, "bytes": 42}
        result = control.report("report", "worker-a", claim["lease"], ref)
        assert result["report_descriptor"] == ref
        assert control.read(claim["lease"]["run_id"], worker_id="worker-a")["result"]["report_descriptor"] == ref


@pytest.mark.skipif(os.environ.get("IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE") != "1", reason="explicit isolated native Quack opt-in")
def test_native_quack_two_scoped_workers_share_owner_and_report_pending_only(tmp_path):
    native_available()
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        control = campaign(registry, tmp_path)
        control.register_records([record("Source A"), record("Source B")])
        gateways = [SpanCampaignQuackGateway(control, worker) for worker in ("worker-a", "worker-b")]
        clients = []
        try:
            for gateway in gateways:
                gateway.start()
                clients.append(SpanCampaignTransportClient(**gateway.connection_parameters()))
            def claim(client):
                status = client.request("ReadCampaign", {}, "read")
                weights = status["weights"]
                client.request("AcknowledgeWeights", {key: weights[key] for key in ("generation", "version_id", "artifact")}, "ack")
                return client.request("ClaimSpan", {"lease_seconds": 30}, "claim")
            with ThreadPoolExecutor(2) as pool:
                claimed = list(pool.map(claim, clients))
            assert len({row["lease"]["run_id"] for row in claimed}) == 2
            first = clients[0].request("ReportSpan", {"lease": claimed[0]["lease"], "report_descriptor": remote_report()}, "report")
            assert first["status"] == "awaiting_verification" and first["admitted"] is False
            assert clients[0].request("ReportSpan", {"lease": claimed[0]["lease"], "report_descriptor": remote_report()}, "report") == first
            result = control.verify_reports(verify_fixture(registry, tmp_path))
            assert result[0]["span_disposition"] == "qualified"
        finally:
            for client in clients:
                client.close()
            for gateway in gateways:
                gateway.close()
