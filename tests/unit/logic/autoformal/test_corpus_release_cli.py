"""Exercise actual public imports in direct-script and module subprocesses."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record
from ipfs_datasets_py.logic.autoformal.corpus_graph import (
    build_edge,
    build_graph_snapshot,
    build_node,
)
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/ops/legal_ir/validate_uscode_corpus_release.py"
MODULE = "scripts.ops.legal_ir.validate_uscode_corpus_release"


def cid(label):
    return seal_record({"schema": "cli-fixture/v1", "label": label})["record_cid"]


@pytest.fixture
def snapshot_input(tmp_path):
    rule = build_node(node_type="norm_assertion", stable_id="1 USC 2(a):rule:0",
        content_cid=cid("assertion"), source_occurrence_cids=[cid("occurrence")],
        interpretation_cids=[cid("interpretation")])
    actor = build_node(node_type="entity", stable_id="1 USC 2(a):actor:clerk",
                       content_cid=cid("clerk"))
    edge = build_edge(src_cid=rule["record_cid"], dst_cid=actor["record_cid"],
                      relation="HAS_ACTOR", ordinal=0, evidence_cids=[cid("binding")])
    snapshot = build_graph_snapshot([rule, actor], [edge])
    raw = canonical_dag_json_bytes(snapshot)
    path = tmp_path / "snapshot.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), snapshot


def run_cli(arguments, *, cwd, direct=False):
    environment = dict(os.environ)
    environment["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    environment["PYTHONPATH"] = str(ROOT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    entrypoint = [str(SCRIPT)] if direct else ["-m", MODULE]
    result = subprocess.run([sys.executable, *entrypoint, *arguments], cwd=cwd,
        env=environment, capture_output=True, text=True, timeout=45)
    lines = result.stdout.splitlines()
    assert len(lines) == 1, (result.stdout, result.stderr)
    receipt = json.loads(lines[0])
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False
    assert receipt["source_semantics_verified"] is False
    assert receipt["source_authenticity_verified"] is False
    assert receipt["proof_verified"] is False
    return result, receipt


@pytest.mark.parametrize("direct", [False, True])
def test_actual_cli_export_validate_and_readable_graph(tmp_path, snapshot_input, direct):
    source, source_sha, snapshot = snapshot_input
    bundle = tmp_path / "bundle"
    result, exported = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(bundle)], cwd=tmp_path, direct=direct)
    assert result.returncode == 0, exported
    assert exported["status"] == "success"
    assert (exported["node_count"], exported["edge_count"]) == (2, 1)
    assert exported["snapshot_cid"] == snapshot["record_cid"]
    manifest_raw = (bundle / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == exported["manifest_sha256"]
    result, validated = run_cli(["validate", "--bundle", str(bundle), "--manifest-sha256",
        exported["manifest_sha256"]], cwd=tmp_path, direct=not direct)
    assert result.returncode == 0, validated
    assert validated["snapshot_cid"] == exported["snapshot_cid"]
    assert validated["manifest_cid"] == exported["manifest_cid"]
    wrong, refused = run_cli(["validate", "--bundle", str(bundle), "--manifest-sha256",
        "0" * 64], cwd=tmp_path, direct=direct)
    assert wrong.returncode != 0
    assert refused["status"] == "error"
    import pyarrow.parquet as parquet
    nodes = parquet.read_table(bundle / "nodes.parquet").to_pylist()
    assert len(nodes) == 2
    assert {row["stable_id"] for row in nodes} == {node["stable_id"] for node in snapshot["nodes"]}
    edges = parquet.read_table(bundle / "edges.parquet").to_pylist()
    assert len(edges) == 1
    assert edges[0]["src_cid"] == snapshot["edges"][0]["src_cid"]
    assert edges[0]["dst_cid"] == snapshot["edges"][0]["dst_cid"]


@pytest.mark.parametrize("arguments", [[], ["unknown"], ["export"],
    ["validate", "--bundle", "missing"], ["export", "--bad-option"]])
def test_usage_failures_are_one_json_error_record(tmp_path, arguments):
    result, receipt = run_cli(arguments, cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert receipt["error_type"] == "CLIError"


@pytest.mark.parametrize("direct", [False, True])
def test_help_is_a_json_receipt(tmp_path, direct):
    result, receipt = run_cli(["export", "--help"], cwd=tmp_path, direct=direct)
    assert result.returncode == 0
    assert receipt["status"] == "help"
    assert len(receipt["usage"]) == 2


@pytest.mark.parametrize("bad_sha", ["", "bad", "f" * 64])
def test_export_requires_exact_external_snapshot_digest(tmp_path, snapshot_input, bad_sha):
    source, _, _ = snapshot_input
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        bad_sha, "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert not destination.exists()


@pytest.mark.parametrize("path_kind", ["missing", "directory", "symlink", "parent-symlink", "fifo"])
def test_snapshot_paths_must_be_regular_and_never_follow_symlinks(tmp_path, snapshot_input, path_kind):
    source, source_sha, _ = snapshot_input
    if path_kind == "missing":
        source = tmp_path / "missing"
    elif path_kind == "directory":
        source = tmp_path
    elif path_kind == "symlink":
        link = tmp_path / "snapshot-link.json"
        link.symlink_to(source)
        source = link
    elif path_kind == "parent-symlink":
        link = tmp_path / "directory-link"
        link.symlink_to(tmp_path, target_is_directory=True)
        source = link / source.name
    else:
        source = tmp_path / "input-fifo"
        os.mkfifo(source)
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert not destination.exists()


@pytest.mark.parametrize("raw", [b"{broken", b"{}", b'{"schema":"x","schema":"y"}',
                                  b'{"bad":NaN}'])
def test_malformed_or_unsealed_snapshot_refuses_before_export(tmp_path, raw):
    source = tmp_path / "malformed.json"
    source.write_bytes(raw)
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        hashlib.sha256(raw).hexdigest(), "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert not destination.exists()


def test_snapshot_byte_bound_is_enforced_before_json_parsing(tmp_path):
    from ipfs_datasets_py.logic.autoformal.corpus_contracts import MAX_RECORD_BYTES
    raw = b" " * (MAX_RECORD_BYTES + 1)
    source = tmp_path / "oversized.json"
    source.write_bytes(raw)
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        hashlib.sha256(raw).hexdigest(), "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert "bounded regular file" in receipt["error"]
    assert not destination.exists()


def test_cli_never_overwrites_existing_bundle(tmp_path, snapshot_input):
    source, source_sha, _ = snapshot_input
    bundle = tmp_path / "existing"
    bundle.mkdir()
    marker = bundle / "keep.txt"
    marker.write_text("retain original")
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(bundle)], cwd=tmp_path, direct=True)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert marker.read_text() == "retain original"
    assert sorted(path.name for path in bundle.iterdir()) == ["keep.txt"]


def test_validate_missing_and_bad_manifest_digest_fail(tmp_path):
    for manifest_sha in ("bad", "0" * 64):
        result, receipt = run_cli(["validate", "--bundle", str(tmp_path / "missing"),
            "--manifest-sha256", manifest_sha], cwd=tmp_path)
        assert result.returncode != 0
        assert receipt["status"] == "error"


def test_validate_corrupted_snapshot_in_existing_bundle_fails(tmp_path, snapshot_input):
    source, source_sha, _ = snapshot_input
    bundle = tmp_path / "bundle"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(bundle)], cwd=tmp_path)
    assert result.returncode == 0, receipt
    (bundle / "snapshot.json").write_bytes(b"{}")
    result, invalid = run_cli(["validate", "--bundle", str(bundle), "--manifest-sha256",
        receipt["manifest_sha256"]], cwd=tmp_path)
    assert result.returncode != 0
    assert invalid["status"] == "error"


# Complete structural component; all source text, signers and review decisions
# are the existing fictional fixture. No native runner or fake compiler is used.
@pytest.fixture(scope="module")
def closure_component(tmp_path_factory):
    from dataclasses import fields
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as join
    from ipfs_datasets_py.processors.legal_data import uscode_hf_release as hf
    from tests.unit.logic.autoformal import test_legal_corpus_definition_use_native_v2 as native_fixture
    from tests.unit.logic.autoformal import test_legal_source_span_entity_coordinate_join_v2 as join_fixture

    control = native_fixture.reviewed_native_fixture_v2()
    coordinate = join_fixture.coordinate_join.__wrapped__(
        tmp_path_factory.mktemp("closure-coordinates"), SimpleNamespace(param={}))
    coordinate = join_fixture.wire_coordinate_join.__wrapped__(coordinate)
    source_request = json.loads(coordinate["source_raw"])
    package = hf.build_uscode_hf_release(hf.fixture_family_rows(),
        legacy_files=hf.fixture_legacy_files(), dry_run=True,
        source_revision=source_request["expected_release_identity"]["source_revision"],
        metadata_profile=hf.WIRE_METADATA_PROFILE)
    # Reuse the genuine opt-in producer. Every metadata body, descriptor,
    # measured Arrow byte count and root is sealed by its existing owner.
    assert hf.validate_uscode_hf_release(package)["metadata_profile"] == hf.WIRE_METADATA_PROFILE
    metadata = {name: package.artifact(name).content for name in coordinate["metadata"]}
    package_manifest = json.loads(metadata["manifest.json"])
    source_request["expected_release_identity"] = {key: package_manifest[key]
        for key in source_request["expected_release_identity"]}
    source_request["files"] = [dict(path_in_repo=name,bytes=len(metadata[name]),
        sha256=hashlib.sha256(metadata[name]).hexdigest()) for name in coordinate["metadata"]]
    coordinate["source_raw"] = join_fixture.wire(source_request)
    coordinate["metadata"] = metadata
    coordinate["request"]["source_request_sha256"] = join_fixture.sha(coordinate["source_raw"])
    joined = join_fixture.prepare_wire_join(coordinate)
    law = joined["source_repository"]
    def plain(value):
        if type(value) in (tuple, list):
            return [plain(item) for item in value]
        if type(value) is dict:
            return {key: plain(item) for key, item in value.items()}
        return value
    package_wire = {
        "metadata": {field.name: plain(getattr(package, field.name)) for field in fields(package)
                     if field.name not in ("configs", "artifacts")},
        "configs": [{field.name: plain(getattr(config, field.name)) for field in fields(config)}
                    for config in package.configs],
        "artifacts": [{field.name: plain(getattr(artifact, field.name)) for field in fields(artifact)}
                      for artifact in package.artifacts],
    }
    encode = transport.encode_parent_replay_value_v1
    wire = lambda value: json.dumps(value,sort_keys=True,separators=(",", ":"),ensure_ascii=False,allow_nan=False).encode()
    replay = {"admission_args": list(control["args"]), "admission_kwargs": control["kwargs"],
        "join_args": [join_fixture.wire(coordinate["request"]), coordinate["source_raw"],
            coordinate["metadata"], join_fixture.wire(coordinate["paired_request"]),
            coordinate["manifests"], coordinate["info_raw"]],
        "join_kwargs": {"expected_request_sha256": join_fixture.sha(join_fixture.wire(coordinate["request"]))},
        "toolchain": native_fixture.TOOLCHAIN}
    component = {role: "fixture:closure:" + role for role in
        ("admission", "graph", "dependency", "preservation", "replay", "hf_package", "source_span_entity_join")}
    artifacts = []
    def add(name, family, payload):
        artifacts.append(dict(artifact_id=name,family=family,payload=payload,
            bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest()))
    add(component["admission"],"admission",wire(control["admission"]))
    add(component["graph"],"graph",canonical_dag_json_bytes(control["graph"]))
    declaration = replay["admission_kwargs"]["preparation_inputs"]["declaration"]
    dependency = replay["admission_kwargs"]["preparation_inputs"]["dependency_manifest"]
    add(component["dependency"],"dependency",wire(dependency))
    add(component["preservation"],"preservation",encode({
        "manifest_json": control["preparation"].manifest_json,
        "files": [list(row) for row in control["preparation"].files]}))
    add(component["replay"],"replay",encode(replay))
    add(component["hf_package"],"hf_package",encode(package_wire))
    add(component["source_span_entity_join"],"source_span_entity_join",wire(joined))
    for unit in declaration["units"]:
        add(unit["source_artifact_id"],"source_version",wire(unit["source_version"]))
        add(unit["ir_artifact_id"],"ir",replay["admission_kwargs"]["preparation_inputs"]["relational_inputs"][unit["unit_id"]]["request_raw"])
    request = {"schema":release.CLOSURE_REQUEST_SCHEMA,"profile":release.CLOSURE_PROFILE,
        "datasets":[dict(role=role,repository_id=body["repository_id"],revision=body["revision"])
            for role,body in zip(("law","span","entity"),
                (law,joined["span_inventory"],joined["entity_metadata"]))],
        "expected_artifact_ids":[row["artifact_id"] for row in artifacts],"artifacts":artifacts,
        "expected_unit_ids":[unit["unit_id"] for unit in declaration["units"]],
        "component":component,"pins":{"admission":control["admission_sha"],"graph":control["graph_sha"],
            "preservation":control["shared"].reviewed_preservation_corpus_sha256(control["preparation"])},
        "native":None}
    return request


def replay_closure(request):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw=transport.encode_parent_replay_value_v1(request)
    return release.validate_uscode_release_closure_v1(raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest())


def test_closure_replays_real_fictional_component_without_native_or_release_claim(closure_component):
    report=replay_closure(closure_component)
    assert report["local_replay_complete"] is True
    assert len(report["unit_ids"])==3 and len(report["artifacts"])==13
    assert report["fixture_only"] is True and report["provenance_kind"]=="fictional_fixture"
    assert report["hf_package"]["valid"] is True
    assert report["hf_package"]["metadata_profile"] == "hf-default-parquet-envelope/v1"
    assert "production_packaging_to_wire_profile_adapter_not_established" not in report["blockers"]
    assert report["closure_complete"] is report["release_ready"] is report["proof_verified"] is False
    assert report["native_receipt_replayed"] is report["model_or_compiler_execution_performed"] is False
    assert "independent_law_span_entity_to_reviewed_source_crosswalk_missing" in report["blockers"]
    assert "retained_native_receipt_and_packet_not_provided" in report["blockers"]


@pytest.mark.parametrize("mutation",["source_bytes","ir_link","graph_link","preservation_link",
    "dependency_link","dataset_revision","omitted","duplicate","profile","verified_boolean","unit_population",
    "stale_review","observed_dependency_changed","disconnected_valid_package","unsubstantiated_native"])
def test_closure_rejects_changed_or_missing_links_even_with_new_outer_digest(closure_component,mutation):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    request=deepcopy(closure_component)
    by_id={row["artifact_id"]:row for row in request["artifacts"]}
    role=request["component"]
    def replace(row,payload):
        row.update(payload=payload,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
    if mutation=="source_bytes":
        row=by_id[role["replay"]]
        replay=transport.decode_parent_replay_value_v1(row["payload"],expected_payload_sha256=row["sha256"])
        sources=replay["admission_kwargs"]["preparation_inputs"]["source_inputs"]
        sources[next(iter(sources))]["raw_bytes"]+=b"changed"
        replace(row,transport.encode_parent_replay_value_v1(replay))
    elif mutation=="graph_link":
        from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graphs
        graph=json.loads(by_id[role["graph"]]["payload"])
        graph["counts"]["nodes"]+=1
        graph=seal_record({key:value for key,value in graph.items() if key not in ("record_cid","cid_scope")})
        replace(by_id[role["graph"]],canonical_dag_json_bytes(graph))
        request["pins"]["graph"]=graphs.norm_definition_graph_sha256(graph)
    elif mutation in {"ir_link","preservation_link","dependency_link"}:
        family={"ir_link":"ir","graph_link":"graph","preservation_link":"preservation","dependency_link":"dependency"}[mutation]
        row=next(row for row in request["artifacts"] if row["family"]==family)
        replace(row,row["payload"]+b" ")
    elif mutation in {"stale_review","observed_dependency_changed"}:
        row=by_id[role["replay"]]
        replay=transport.decode_parent_replay_value_v1(row["payload"],expected_payload_sha256=row["sha256"])
        if mutation=="stale_review":replay["admission_kwargs"]["at_time_utc"]="2027-01-01T00:00:00Z"
        else:
            observed=replay["admission_kwargs"]["observed_artifact_sha256s"]
            observed[next(iter(observed))]="0"*64
        replace(row,transport.encode_parent_replay_value_v1(replay))
    elif mutation=="disconnected_valid_package":
        from dataclasses import fields
        from ipfs_datasets_py.processors.legal_data import uscode_hf_release as hf
        original=transport.decode_parent_replay_value_v1(by_id[role["hf_package"]]["payload"],
            expected_payload_sha256=by_id[role["hf_package"]]["sha256"])
        other=hf.build_uscode_hf_release(hf.fixture_family_rows(),legacy_files=hf.fixture_legacy_files(),
            dry_run=True,source_revision=original["metadata"]["source_revision"],max_rows_per_shard=1)
        assert hf.validate_uscode_hf_release(other)["valid"] is True
        def plain(value):
            if type(value) in (list,tuple):return [plain(item) for item in value]
            if type(value) is dict:return {key:plain(item) for key,item in value.items()}
            return value
        packed={"metadata":{field.name:plain(getattr(other,field.name)) for field in fields(other)
                    if field.name not in ("configs","artifacts")},
            "configs":[{field.name:plain(getattr(item,field.name)) for field in fields(item)} for item in other.configs],
            "artifacts":[{field.name:plain(getattr(item,field.name)) for field in fields(item)} for item in other.artifacts]}
        replace(by_id[role["hf_package"]],transport.encode_parent_replay_value_v1(packed))
    elif mutation=="unsubstantiated_native":
        receipt={"artifact_id":"fixture:unsubstantiated-receipt","family":"native_receipt"}
        packet={"artifact_id":"fixture:unsubstantiated-packet","family":"native_packet"}
        replace(receipt,b"{}");replace(packet,transport.encode_parent_replay_value_v1({}))
        request["artifacts"].extend([receipt,packet]);request["expected_artifact_ids"].extend([receipt["artifact_id"],packet["artifact_id"]])
        request["native"]={"receipt":receipt["artifact_id"],"packet":packet["artifact_id"],
            "expected_packet_sha256":"0"*64,"expected_binary_sha256":{}}
    elif mutation=="dataset_revision":request["datasets"][0]["revision"]="f"*40
    elif mutation=="omitted":
        request["artifacts"].pop();request["expected_artifact_ids"].pop()
    elif mutation=="duplicate":
        request["artifacts"].append(deepcopy(request["artifacts"][0]));request["expected_artifact_ids"].append(request["expected_artifact_ids"][0])
    elif mutation=="profile":request["profile"]="reviewed-norm-v3/local"
    elif mutation=="verified_boolean":request["verified"]=True
    elif mutation=="unit_population":request["expected_unit_ids"].pop()
    with pytest.raises((ValueError,TypeError,KeyError)):
        replay_closure(request)


def test_closure_command_emits_one_json_receipt_without_changing_candidate_commands(tmp_path,closure_component,capsys):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from scripts.ops.legal_ir import validate_uscode_corpus_release as cli
    raw=transport.encode_parent_replay_value_v1(closure_component);path=tmp_path/"closure.request";path.write_bytes(raw)
    code=cli.main(["validate-closure","--request",str(path),"--request-sha256",hashlib.sha256(raw).hexdigest()])
    lines=capsys.readouterr().out.splitlines();assert code==0 and len(lines)==1
    receipt=json.loads(lines[0]);assert receipt["status"]=="success" and receipt["closure"]["release_ready"] is False
    assert receipt["admitted"] is receipt["proof_verified"] is False
    code=cli.main(["validate-closure","--request",str(path),"--request-sha256","0"*64])
    lines=capsys.readouterr().out.splitlines();assert code==1 and len(lines)==1 and json.loads(lines[0])["status"]=="error"


@pytest.mark.parametrize("direct",[False,True])
def test_closure_actual_entrypoint_receipt(tmp_path,closure_component,direct):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw=transport.encode_parent_replay_value_v1(closure_component)
    path=tmp_path/"entrypoint.request";path.write_bytes(raw)
    result,receipt=run_cli(["validate-closure","--request",str(path),"--request-sha256",
        hashlib.sha256(raw).hexdigest()],cwd=tmp_path,direct=direct)
    assert result.returncode==0 and receipt["status"]=="success"
    assert receipt["closure"]["local_replay_complete"] is True
    assert receipt["closure"]["release_ready"] is False
    assert "production_packaging_to_wire_profile_adapter_not_established" not in receipt["closure"]["blockers"]
    assert "independent_law_span_entity_to_reviewed_source_crosswalk_missing" in receipt["closure"]["blockers"]
    assert receipt["closure"]["source_metadata_arrow_bytes_verified"] is False


def test_closure_help_keeps_one_json_and_does_not_change_legacy_general_help(capsys):
    from scripts.ops.legal_ir import validate_uscode_corpus_release as cli
    assert cli.main(["validate-closure","--help"])==0
    lines=capsys.readouterr().out.splitlines();assert len(lines)==1
    receipt=json.loads(lines[0]);assert receipt["status"]=="help"
    assert receipt["usage"]==["validate-closure --request PATH --request-sha256 SHA"]


# Successor profile: one shared fictional source population, real Parquet
# capture/coordinates/paired transport, and a map signed BEFORE final review.
def _physical_wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _physical_source_material(directory, *, reviewed_version=2):
    import shutil
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ipfs_datasets_py.logic.autoformal import corpus_source as source
    from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as payload
    from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
    from ipfs_datasets_py.logic.autoformal import span_cache, uscode_ingest as ingest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_dataset as dataset
    from tests.unit.logic.test_span_cache_paired_feed import source_row

    directory.mkdir()
    assert type(reviewed_version) is int and reviewed_version in (2, 3)
    namespace = "physical-crosswalk" if reviewed_version == 2 else "physical-crosswalk-v3"
    instrument = "fixture:" + namespace
    texts = [
        "For this fictional Act, a covered officer means an officer appointed by the Board. Café.",
        "Every covered officer must file a report unless the Board expressly excuses that officer.",
        "A covered officer may inspect the register.",
    ]
    if reviewed_version == 3:
        # Exact fictional prose already exercised by the current V3 fixture.
        texts[2] = (
            "For every officer, supervisor, event, and time, if both people are covered officers, "
            "that officer may inspect the register under that supervisor at that event and time.")
    units = []
    laws = []
    for index, text in enumerate(texts):
        identity = instrument + "/unit-" + str(index + 1)
        source_raw = text.encode("utf-8")
        version = source.build_source_version(source_id=identity, release_id=instrument,
            edition="fictional-edition-1", provision_id=identity, raw_bytes=source_raw,
            expected_raw_sha256=hashlib.sha256(source_raw).hexdigest(), extracted_text=text,
            expected_extracted_sha256=hashlib.sha256(source_raw).hexdigest(),
            extraction_profile="identity/v1", normalization_profile="identity/v1",
            media_type="text/plain")
        occurrence = source.build_source_occurrence(version,
            expected_raw_sha256=hashlib.sha256(source_raw).hexdigest(), extracted_text=text,
            expected_extracted_sha256=hashlib.sha256(source_raw).hexdigest(),
            start_char=0, end_char=len(text), start_utf8=0, end_utf8=len(source_raw))
        units.append(dict(unit_id=identity, source_version=version, occurrence=occurrence))
        laws.append(dict(ipfs_cid=identity, title_number="999", title_name="Fictional engineering title",
            section_number=str(index + 1), law_name="Entirely fictional provision",
            source_url="fixture:physical-law-row:" + str(index),
            text=text, citation_text="Fictional engineering source",
            normalized_citation="fictional:" + str(index + 1)))
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(laws), sink)
    law_bytes = sink.getvalue().to_pybytes()
    law_path = directory / "laws.parquet"
    law_path.write_bytes(law_bytes)
    law_revision, span_revision, entity_revision = "a" * 40, "b" * 40, "c" * 40
    artifact_path = "uscode_parquet/laws.parquet"
    capture = dataset.capture_uscode_source_documents_from_parquet(law_path,
        source_revision=law_revision, source_path_in_repo=artifact_path,
        expected_sha256=hashlib.sha256(law_bytes).hexdigest(), expected_bytes=len(law_bytes),
        limit=len(laws), offset=0, release_id=instrument)
    coordinates = ingest.inventory_uscode_source_coordinates(capture["documents"],
        query="fictional-complete-physical-crosswalk", release_id=instrument)
    coordinate_pin = ingest.uscode_source_coordinates_sha256(coordinates)
    _, spans = span_cache._coordinate_replay(coordinates, coordinate_pin)
    observations = []
    for index, span in enumerate(spans):
        reference = span_cache._coordinate_wire(
            span_cache._coordinate_reference(coordinates, spans, coordinate_pin, index),
            span_cache.MAX_SOURCE_COORDINATE_REFERENCE_BYTES).decode("utf-8")
        observed = source_row(span["source_span_id"], text=span["text"],
                              release=instrument, guided=False)
        observed.update(legal_id=span["legal_id"], source_provenance_json=reference)
        observations.append(observed)
    bundle = paired.build_paired_census(observations, agent_id="fictional-physical-crosswalk",
        code_identity="authored:physical-crosswalk", model_identity="diagnostic:test",
        release_id=instrument, source_coordinate_report=coordinates,
        expected_source_coordinate_report_sha256=coordinate_pin)
    written = paired.write_paired_census_bundle(bundle, directory / "producer")
    retained = directory / "retained" / span_revision
    for kind in (*paired.TABLE_NAMES, "manifest"):
        entry = written[kind]
        destination = retained / entry["path_in_repo"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry["path"], destination)
    location = dict(repository_root=retained, repository_id=paired.REPOSITORY,
        revision=span_revision, manifest_path_in_repo=written["manifest"]["path_in_repo"],
        expected_manifest_sha256=written["manifest"]["sha256"],
        expected_source_coordinate_report_sha256=coordinate_pin)
    original_payload = payload.prepare_paired_payload_intake_v2(**location)
    table = original_payload["tables"]["paired_spans"]
    span_rows = []
    for row in original_payload["rows"]:
        physical = dict(repository_id=paired.REPOSITORY, revision=span_revision,
            path_in_repo=table["path_in_repo"], file_sha256=table["sha256"],
            row_ordinal=row["row_ordinal"])
        index = row["source_coordinate_span_index"]
        unit = units[coordinates["spans"][index]["input_document_ordinal"]]
        span_rows.append(dict(physical_identity_sha256=hashlib.sha256(_physical_wire(physical)).hexdigest(),
            row_sha256=row["row_sha256"], source_coordinate_span_index=index,
            unit_ids=[unit["unit_id"]]))

    # Semantic selectors and arbitrary physical IDs are known before review.
    # Scope/admission-dependent graph CIDs are deliberately absent here.
    entity_rows, bindings, node_ids = [], [], {}
    def node(key, node_type, stable_id):
        identity = "fixture:entity:node:" + str(len(node_ids))
        node_ids[key] = identity
        raw_row = dict(record_kind="node", meta_category="reviewed-graph-node",
            graph_kind=node_type, label=stable_id or "scope",
            legal_id=instrument, node_id=identity, src="", dst="", logic_role=node_type,
            in_formula=False, admitted=False, formalized=False)
        ordinal = len(entity_rows); entity_rows.append(raw_row)
        bindings.append(dict(row_ordinal=ordinal,
            row_sha256=hashlib.sha256(_physical_wire(raw_row)).hexdigest(),
            selector=dict(kind="node", node_type=node_type, stable_id=stable_id)))
    def edge(left, right, relation, ordinal=None):
        raw_row = dict(record_kind="edge", meta_category="reviewed-graph-edge",
            graph_kind=relation, label=relation, legal_id=instrument, node_id="",
            src=node_ids[left], dst=node_ids[right], logic_role=relation,
            in_formula=False, admitted=False, formalized=False)
        row_ordinal = len(entity_rows); entity_rows.append(raw_row)
        bindings.append(dict(row_ordinal=row_ordinal,
            row_sha256=hashlib.sha256(_physical_wire(raw_row)).hexdigest(),
            selector=dict(kind="edge", src_node_id=node_ids[left], dst_node_id=node_ids[right],
                          relation=relation, ordinal=ordinal)))
    node("scope", "scope", None)
    node("interpretation", "interpretation", instrument + "/selected-interpretation")
    for index, unit in enumerate(units):
        identity = unit["unit_id"]
        node(("version", index), "source_version", unit["source_version"]["record_cid"])
        node(("occurrence", index), "occurrence", unit["occurrence"]["record_cid"])
        node(("expression", index), "expression", identity + ":complete-IR")
        node(("assertion", index), "definition_assertion" if index == 0 else "norm_assertion", identity)
    node("term", "term_sense", units[0]["unit_id"] + ":CoveredOfficer")
    for index in range(len(units)):
        node(("cross-reference", index), "expression",
             "fixture:reviewed-" + namespace + ":cross-reference:" + str(index))
    for index in range(len(units)):
        edge(("version", index), ("occurrence", index), "CONTAINS")
        edge(("assertion", index), ("occurrence", index), "HAS_SOURCE")
        edge(("assertion", index), ("expression", index), "DERIVED_FROM")
        edge(("assertion", index), "scope", "APPLIES_WITHIN")
        edge("interpretation", ("assertion", index), "CONTAINS")
    edge(("assertion", 0), "term", "DEFINES")
    for index in range(1, len(units)):
        edge(("assertion", index), ("assertion", 0), "USES_DEFINITION", index - 1)
    for index in range(len(units)):
        edge(("assertion", index), ("cross-reference", index), "CITES", index)
    entity_schema = pa.schema([(key, pa.bool_() if key in ("in_formula", "admitted", "formalized")
                                else pa.string()) for key in entity_rows[0]])
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(entity_rows, schema=entity_schema), sink)
    entity_bytes = sink.getvalue().to_pybytes()
    entity_path = directory / "entity-index.parquet"; entity_path.write_bytes(entity_bytes)
    datasets = [dict(role=role, repository_id=repository, revision=revision)
        for role, repository, revision in (
            ("law", "justicedao/ipfs_uscode", law_revision),
            ("span", "justicedao/uscode-autoformal-span-cache", span_revision),
            ("entity", "justicedao/uscode-autoformal-entity-cache", entity_revision))]
    mapping = dict(schema="legal-reviewed-physical-source-crosswalk/v1",
        profile="identity-text-complete-reviewed-graph/v1", datasets=datasets,
        law=dict(artifact_path=artifact_path, file_sha256=hashlib.sha256(law_bytes).hexdigest(),
            file_bytes=len(law_bytes), row_offset=0, rows=len(laws), release_id=instrument,
            coordinate_report_sha256=coordinate_pin),
        entity=dict(file_sha256=hashlib.sha256(entity_bytes).hexdigest(), file_bytes=len(entity_bytes),
            rows=len(entity_rows), projection="complete_reviewed_norm_graph_nodes_and_edges/v1"),
        units=[dict(unit_id=unit["unit_id"], source_version_cid=unit["source_version"]["record_cid"],
            source_occurrence_cid=unit["occurrence"]["record_cid"],
            document_revision=instrument + "/revision-1", input_document_ordinal=index,
            law_row_ordinal=index) for index, unit in enumerate(units)],
        span_rows=span_rows, entity_rows=bindings)
    return dict(namespace=namespace, instrument=instrument, texts=texts, units=units,
        laws=laws, law_bytes=law_bytes, law_path=law_path, capture=capture, datasets=datasets,
        coordinate_report=coordinates, coordinate_pin=coordinate_pin, paired_location=location,
        paired_written=written, retained=retained, original_payload=original_payload,
        entity_bytes=entity_bytes, entity_path=entity_path, entity_rows=entity_rows, mapping=mapping)


def _physical_closure_request(material, *, map_damage=None, reviewed_version=2):
    from copy import deepcopy
    from dataclasses import fields
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    from ipfs_datasets_py.logic.autoformal import legal_source_package_intake_v1 as source
    from ipfs_datasets_py.logic.autoformal import legal_paired_manifest_inventory_v1 as inventory
    from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as join
    from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as entity
    from ipfs_datasets_py.processors.legal_data import uscode_hf_release as hf
    from tests.unit.logic.autoformal import test_legal_norm_content_adjudication_v1 as fixture
    from tests.unit.logic.autoformal import test_legal_corpus_shared_lake as shared_fixture

    assert type(reviewed_version) is int and reviewed_version in (2, 3)
    mapping = deepcopy(material["mapping"])
    if map_damage == "law_row_alias":
        mapping["units"][0]["law_row_ordinal"] = mapping["units"][1]["law_row_ordinal"]
    elif map_damage == "source_version_alias":
        mapping["units"][0]["source_version_cid"] = mapping["units"][1]["source_version_cid"]
    elif map_damage == "document_alias":
        mapping["units"][0]["input_document_ordinal"] = mapping["units"][1]["input_document_ordinal"]
    elif map_damage == "document_revision":
        mapping["units"][0]["document_revision"] += ":other"
    elif map_damage == "span_missing":
        mapping["span_rows"].pop()
    elif map_damage == "span_duplicate":
        mapping["span_rows"][1] = deepcopy(mapping["span_rows"][0])
    elif map_damage == "span_wrong_overlap":
        mapping["span_rows"][0]["unit_ids"] = [mapping["units"][1]["unit_id"]]
    elif map_damage == "entity_node_alias":
        mapping["entity_rows"][3]["selector"] = deepcopy(mapping["entity_rows"][2]["selector"])
    elif map_damage == "entity_endpoint":
        row = next(row for row in mapping["entity_rows"] if row["selector"]["kind"] == "edge")
        row["selector"]["src_node_id"] = material["entity_rows"][0]["node_id"]
    elif map_damage == "entity_missing":
        mapping["entity_rows"].pop()
    elif map_damage == "entity_row_digest":
        mapping["entity_rows"][0]["row_sha256"] = "0" * 64
    elif map_damage == "dataset_revision":
        mapping["datasets"][2]["revision"] = "d" * 40
    elif map_damage is not None:
        raise AssertionError("unknown authored map mutation")
    map_raw = _physical_wire(mapping)
    map_pin = hashlib.sha256(map_raw).hexdigest()
    map_id = "fixture:physical-crosswalk-map"
    process_raw = b"Fictional independent review process record. No actual statutory or human-review claim."
    process_ref = dict(artifact_id=fixture.REVIEWED_PROCESS_ID,
                       sha256=hashlib.sha256(process_raw).hexdigest())
    references = [dict(from_unit_id=unit["unit_id"], dependency_artifact_id=map_id,
        dependency_sha256=map_pin, version=mapping["profile"],
        evidence_refs=[dict(process_ref)]) for unit in material["units"]]
    # This is the ONLY review construction. The final map/file/selector
    # dependency is already frozen before preparation and detached signatures.
    case = fixture.reviewed_norm_fixture_v2(admission, fixture_namespace=material["namespace"],
        source_texts=material["texts"], cross_references=references,
        dependency_artifacts={map_id: map_raw})
    if reviewed_version == 2:
        control = shared_fixture.reviewed_preservation_graph_fixture_v2(fixture, admission, case)
        control["preparation"] = shared_fixture.reviewed_preservation_prepare_fixture_v2(control)
    else:
        from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as mixed
        from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graphs
        from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
        from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as mixed_fixture
        # The crosswalk is already a frozen reviewed dependency. Reuse the
        # current fictional signers only after the complete mixed target exists.
        case["declaration"]["schema"] = mixed.REVIEWED_DECLARATION_SCHEMA
        for unit in case["declaration"]["units"]:
            unit["relational_profile"] = mixed_fixture.relational.PROFILE
        mixed_fixture.set_mixed_ir(case)
        case["preparation"] = mixed_fixture.prepare(mixed, case)
        mixed_fixture.refresh_signed_reviews(case, mixed)
        mixed_fixture.assert_signatures_valid(case)
        args, kwargs = fixture.reviewed_assessment_arguments_v2(mixed, case)
        checked = mixed.assess_reviewed_norm_admission_v3(*args, **kwargs)
        assert checked["semantic_use_eligible"] is True and checked["fixture_only"] is True
        assert checked["blockers"] == []
        admission_pin = mixed.norm_content_adjudication_sha256(checked)
        graph = graphs.build_reviewed_norm_graph_v3(checked, *args,
            expected_admission_sha256=admission_pin, **kwargs)
        graph_pin = graphs.norm_definition_graph_sha256(graph)
        preparation = shared.prepare_reviewed_norm_preservation_corpus_v3(graph, checked, *args,
            expected_graph_sha256=graph_pin, expected_admission_sha256=admission_pin,
            toolchain=shared_fixture.TOOLCHAIN, **kwargs)
        control = dict(args=args, kwargs=kwargs, admission=checked, graph=graph,
            admission_sha=admission_pin, graph_sha=graph_pin, preparation=preparation)

    corpus_rows = [dict(entry_cid=law["ipfs_cid"], legal_id=document["legal_id"], text=law["text"],
        source_cid=unit["source_version"]["raw_artifact"]["cid"],
        release_point=hf.DEFAULT_APPROVED_RELEASE_POINT)
        for law, document, unit in zip(material["laws"], material["capture"]["documents"], material["units"])]
    family_rows = dict(corpus=corpus_rows,
        graph_nodes=[dict(entry_cid=node["record_cid"], legal_id=material["instrument"],
                         semantic_graph_node=node) for node in control["graph"]["graph"]["nodes"]],
        graph_edges=[dict(entry_cid=edge["record_cid"], legal_id=material["instrument"],
                         semantic_graph_edge=edge) for edge in control["graph"]["graph"]["edges"]])
    legacy = hf.fixture_legacy_files()
    legacy["uscode_parquet/laws.parquet"] = material["law_bytes"]
    package = hf.build_uscode_hf_release(family_rows, legacy_files=legacy, dry_run=True,
        source_revision="d" * 40, metadata_profile=hf.WIRE_METADATA_PROFILE)
    metadata = {name: package.artifact(name).content for name in source.FILES}
    manifest = package.manifest_dict()
    source_request = dict(schema=source.REQUEST_SCHEMA_V2, repository_id=source.REPOSITORY,
        revision=material["datasets"][0]["revision"], metadata_profile=source.METADATA_PROFILE_V2,
        expected_release_identity={key: manifest[key] for key in (
            "release_profile", "release_point", "release_root_cid", "source_revision",
            "manifest_digest", "graph_ontology_version", "producer")},
        expected_graph_population={family: dict(
            files=sum(item["family"] == family for item in manifest["artifacts"]),
            rows=sum(item["row_count"] for item in manifest["artifacts"] if item["family"] == family))
            for family in ("graph_nodes", "graph_edges")},
        files=[dict(path_in_repo=name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
               for name, body in metadata.items()])
    source_raw = _physical_wire(source_request)
    location = material["paired_location"]
    paired_manifest = Path(location["repository_root"]) / location["manifest_path_in_repo"]
    paired_raw = paired_manifest.read_bytes()
    paired_request = dict(schema=inventory.REQUEST_SCHEMA_V2, repository_id=inventory.REPOSITORY,
        revision=location["revision"], selection_scope=inventory.SELECTION_SCOPE,
        manifests=[dict(path_in_repo=location["manifest_path_in_repo"], bytes=len(paired_raw),
            sha256=hashlib.sha256(paired_raw).hexdigest(),
            source_coordinate_report_sha256=material["coordinate_pin"])])
    info_raw = _physical_wire(dict(partial=False, dataset_info=dict(
        dataset_name="uscode-autoformal-entity-cache", config_name="autoformal_uscode",
        features={name: dict(_type="Value", dtype="bool" if name in entity.BOOLEAN_FIELDS else "string")
                  for name in entity.FIELDS},
        splits=dict(train=dict(num_examples=len(material["entity_rows"]))))))
    join_request = dict(schema=join.REQUEST_SCHEMA_V3,
        source_request_sha256=hashlib.sha256(source_raw).hexdigest(),
        paired_inventory_request_sha256=hashlib.sha256(_physical_wire(paired_request)).hexdigest(),
        paired_bundles=[dict(manifest_path_in_repo=location["manifest_path_in_repo"],
                            repository_root=str(location["repository_root"]))],
        legacy_joins={}, entity=dict(repository_id=material["datasets"][2]["repository_id"],
            revision=material["datasets"][2]["revision"], configuration="autoformal_uscode",
            info_sha256=hashlib.sha256(info_raw).hexdigest()))
    join_args = [_physical_wire(join_request), source_raw, metadata, _physical_wire(paired_request),
                 {location["manifest_path_in_repo"]: paired_raw}, info_raw]
    join_kwargs = dict(expected_request_sha256=hashlib.sha256(join_args[0]).hexdigest())
    joined = join.prepare_source_span_entity_join_manifest_v3(*join_args, **join_kwargs)
    def plain(value):
        if type(value) in (tuple, list):
            return [plain(child) for child in value]
        if type(value) is dict:
            return {key: plain(child) for key, child in value.items()}
        return value
    package_wire = dict(
        metadata={field.name: plain(getattr(package, field.name)) for field in fields(package)
                  if field.name not in ("configs", "artifacts")},
        configs=[{field.name: plain(getattr(config, field.name)) for field in fields(config)}
                 for config in package.configs],
        artifacts=[{field.name: plain(getattr(artifact, field.name)) for field in fields(artifact)}
                   for artifact in package.artifacts])
    replay = dict(admission_args=list(control["args"]), admission_kwargs=control["kwargs"],
        join_args=join_args, join_kwargs=join_kwargs, toolchain=shared_fixture.TOOLCHAIN)
    roles = ("admission", "graph", "dependency", "preservation", "replay", "hf_package",
             "source_span_entity_join", "reviewed_crosswalk", "entity_parquet")
    component = {role: map_id if role == "reviewed_crosswalk" else "fixture:physical:" + role for role in roles}
    artifacts = []
    def add(identity, family, payload):
        artifacts.append(dict(artifact_id=identity, family=family, payload=payload,
            bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))
    add(component["admission"], "admission", _physical_wire(control["admission"]))
    add(component["graph"], "graph", canonical_dag_json_bytes(control["graph"]))
    add(component["dependency"], "dependency", _physical_wire(case["manifest"]))
    add(component["preservation"], "preservation", transport.encode_parent_replay_value_v1(dict(
        manifest_json=control["preparation"].manifest_json,
        files=[list(row) for row in control["preparation"].files])))
    add(component["replay"], "replay", transport.encode_parent_replay_value_v1(replay))
    add(component["hf_package"], "hf_package", transport.encode_parent_replay_value_v1(package_wire))
    add(component["source_span_entity_join"], "source_span_entity_join", _physical_wire(joined))
    add(component["reviewed_crosswalk"], "reviewed_crosswalk", map_raw)
    add(component["entity_parquet"], "entity_parquet", material["entity_bytes"])
    for unit in case["declaration"]["units"]:
        add(unit["source_artifact_id"], "source_version", _physical_wire(unit["source_version"]))
        add(unit["ir_artifact_id"], "ir", case["relational_inputs"][unit["unit_id"]]["request_raw"])
    return dict(schema=("legal-uscode-release-closure-request/v2" if reviewed_version == 2
                        else "legal-uscode-release-closure-request/v3"),
        profile=("reviewed-norm-v2-physical-three-cache-replay/v1" if reviewed_version == 2
                 else "reviewed-norm-v3-physical-three-cache-replay/v1"),
        datasets=material["datasets"], expected_artifact_ids=[row["artifact_id"] for row in artifacts],
        artifacts=artifacts, expected_unit_ids=[unit["unit_id"] for unit in case["declaration"]["units"]],
        component=component, pins=dict(admission=control["admission_sha"], graph=control["graph_sha"],
            preservation=shared_fixture.shared.reviewed_preservation_corpus_sha256(control["preparation"]),
            reviewed_crosswalk=map_pin), native=None,
        physical_inputs=dict(law_path=str(material["law_path"]), entity_path=str(material["entity_path"])))


@pytest.fixture(scope="module")
def physical_closure_material(tmp_path_factory):
    return _physical_source_material(tmp_path_factory.mktemp("shared-physical-crosswalk") / "material")


@pytest.fixture(scope="module")
def physical_closure_component(physical_closure_material):
    return _physical_closure_request(physical_closure_material)


def replay_physical_closure(request):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw = transport.encode_parent_replay_value_v1(request)
    return release.validate_uscode_release_closure_v2(raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest())


def test_physical_closure_shared_reviewed_sources_span_coordinates_and_complete_entity_graph(
        physical_closure_component, physical_closure_material):
    report = replay_physical_closure(physical_closure_component)
    assert report["local_replay_complete"] is True
    assert report["fixture_only"] is True and report["provenance_kind"] == "fictional_fixture"
    assert report["closure_complete"] is report["release_ready"] is report["proof_verified"] is False
    assert "independent_law_span_entity_to_reviewed_source_crosswalk_missing" not in report["blockers"]
    assert "original_admitted_native_parent_custody_not_established" in report["blockers"]
    assert "immutable_remote_Hub_readback_not_established" in report["blockers"]
    assert report["native_receipt_replayed"] is report["model_or_compiler_execution_performed"] is False
    assert report["local_source_cache_entity_bindings_verified"] is True
    assert report["independent_reviewed_crosswalk_verified"] is True
    physical = report["physical_crosswalk"]
    assert physical["counts"] == dict(law_rows=3, reviewed_units=3, paired_cache_rows=4,
                                     entity_rows=39, graph_nodes=18, graph_edges=21)
    assert physical["candidate_formal_outputs_semantically_reviewed"] is False
    assert physical["surface_labels_used_as_semantic_identity"] is False
    assert physical["legacy_boolean_flags_used_as_admission"] is False
    assert physical["remote_revision_authenticated"] is False
    assert any(row["exact_unspanned_whitespace"] for row in physical["unit_bindings"])
    assert len({row["graph_record_cid"] for row in physical["entity_bindings"]}) == 39
    assert all("semantic_companion_record_cid" in row or "semantic_companion_record_cids" in row
               for row in physical["entity_bindings"])
    assert len(physical_closure_material["texts"]) == 3
    assert len(physical_closure_material["mapping"]["span_rows"]) == 4
    assert len(physical_closure_material["mapping"]["entity_rows"]) == 39


@pytest.mark.parametrize("damage", [
    "law_row_alias", "source_version_alias", "document_alias", "document_revision",
    "span_missing", "span_duplicate", "span_wrong_overlap", "entity_node_alias",
    "entity_endpoint", "entity_missing", "entity_row_digest", "dataset_revision",
])
def test_physical_closure_rejects_genuinely_signed_wrong_crosswalk(physical_closure_material, damage):
    request = _physical_closure_request(physical_closure_material, map_damage=damage)
    with pytest.raises(ValueError):
        replay_physical_closure(request)


@pytest.mark.parametrize("damage", ["unicode_geometry", "governing_scope", "review_revoked"])
def test_physical_closure_replays_original_geometry_scope_and_review_after_mapping(
        physical_closure_component, damage):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_graph_review as authority
    request = deepcopy(physical_closure_component)
    row = next(row for row in request["artifacts"] if row["artifact_id"] == request["component"]["replay"])
    replay = transport.decode_parent_replay_value_v1(row["payload"], expected_payload_sha256=row["sha256"])
    kwargs = replay["admission_kwargs"]
    if damage == "unicode_geometry":
        declaration = kwargs["preparation_inputs"]["declaration"]
        occurrence = declaration["units"][0]["occurrence"]
        assert occurrence["end_utf8"] > occurrence["end_char"]
        occurrence["end_utf8"] = occurrence["end_char"]
    elif damage == "governing_scope":
        kwargs["preparation_inputs"]["declaration"]["governing_context"]["governing_edition"] += ":other"
    else:
        registry = replay["admission_args"][1]
        registry["keys"][0]["revoked_at_utc"] = kwargs["at_time_utc"]
        kwargs["expected_registry_sha256"] = authority.digest(registry)
    raw = transport.encode_parent_replay_value_v1(replay)
    row.update(payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        replay_physical_closure(request)


@pytest.mark.parametrize("direct", [False, True])
def test_physical_closure_actual_explicit_successor_cli(physical_closure_component, tmp_path, direct):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw = transport.encode_parent_replay_value_v1(physical_closure_component)
    path = tmp_path / "physical-closure.request"; path.write_bytes(raw)
    result, receipt = run_cli(["validate-closure", "--profile", release.CLOSURE_PROFILE_V2,
        "--request", str(path), "--request-sha256", hashlib.sha256(raw).hexdigest()],
        cwd=tmp_path, direct=direct)
    assert result.returncode == 0 and receipt["status"] == "success"
    assert "independent_law_span_entity_to_reviewed_source_crosswalk_missing" not in receipt["closure"]["blockers"]
    assert receipt["closure"]["release_ready"] is False



def test_physical_closure_equal_text_does_not_replace_reviewed_physical_law_artifact(
        physical_closure_component, physical_closure_material, tmp_path):
    from copy import deepcopy
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = deepcopy(physical_closure_material["laws"])
    for row in rows:
        row["title_name"] += " -- independently different physical row metadata"
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows), sink)
    replacement = sink.getvalue().to_pybytes()
    assert [row["text"] for row in rows] == physical_closure_material["texts"]
    assert replacement != physical_closure_material["law_bytes"]
    path = tmp_path / "equal-text-different-artifact.parquet"
    path.write_bytes(replacement)
    request = deepcopy(physical_closure_component)
    request["physical_inputs"]["law_path"] = str(path)
    with pytest.raises(ValueError):
        replay_physical_closure(request)


def test_physical_closure_late_equal_byte_entity_replacement_cannot_change_held_generation(
        physical_closure_component, tmp_path, monkeypatch):
    from copy import deepcopy
    import os
    from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as entities
    request = deepcopy(physical_closure_component)
    row = next(row for row in request["artifacts"]
               if row["artifact_id"] == request["component"]["entity_parquet"])
    physical = tmp_path / "owned-entity.parquet"
    physical.write_bytes(row["payload"])
    request["physical_inputs"]["entity_path"] = str(physical)
    old_identity = (physical.stat().st_dev, physical.stat().st_ino)
    original = entities.iter_observed_rows
    observed = dict(rows=0, replacement_performed=False)
    def replace_after_genuine_scan(path, **kwargs):
        for record in original(path, **kwargs):
            observed["rows"] += 1
            yield record
        replacement = tmp_path / "replacement.parquet"
        replacement.write_bytes(row["payload"])
        os.replace(replacement, physical)
        observed["replacement_performed"] = True
    monkeypatch.setattr(entities, "iter_observed_rows", replace_after_genuine_scan)
    with pytest.raises(ValueError):
        replay_physical_closure(request)
    assert observed == dict(rows=39, replacement_performed=True)
    assert physical.read_bytes() == row["payload"]
    assert (physical.stat().st_dev, physical.stat().st_ino) != old_identity


# The successor exercises the existing mixed-sort admission and physical cache
# owners. Every source, review and signer here is explicitly fictional.
@pytest.fixture(scope="module")
def physical_closure_material_v3(tmp_path_factory):
    return _physical_source_material(
        tmp_path_factory.mktemp("reviewed-v3-physical-crosswalk") / "material", reviewed_version=3)


@pytest.fixture(scope="module")
def physical_closure_component_v3(physical_closure_material_v3):
    return _physical_closure_request(physical_closure_material_v3, reviewed_version=3)


def replay_physical_closure_v3(request):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    validator = getattr(release, "validate_uscode_release_closure_v3", None)
    assert callable(validator), (
        "complete reviewed mixed-sort V3 artifacts have no physical release-closure consumer")
    raw = transport.encode_parent_replay_value_v1(request)
    return validator(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


def test_physical_closure_v3_replays_complete_mixed_component_without_release_authority(
        physical_closure_component_v3, physical_closure_material_v3):
    request = physical_closure_component_v3
    report = replay_physical_closure_v3(request)
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    rows = {row["artifact_id"]: row for row in request["artifacts"]}
    component = request["component"]
    replay_row = rows[component["replay"]]
    replay = transport.decode_parent_replay_value_v1(
        replay_row["payload"], expected_payload_sha256=replay_row["sha256"])
    admission = json.loads(rows[component["admission"]]["payload"])
    graph = json.loads(rows[component["graph"]]["payload"])
    assert graph["counts"]["units"] == 3 and graph["counts"]["norms"] == 2
    assert graph["counts"]["definitions"] == 1 and graph["counts"]["definition_uses"] == 2
    declaration = replay["admission_kwargs"]["preparation_inputs"]["declaration"]
    for unit, admitted, ast_record in zip(declaration["units"], admission["units"],
            graph["ast_records"], strict=True):
        complete = admitted["canonical_ir"]
        assert set(complete) == {"profile", "typed_expression", "argument_roles", "assumptions",
            "governing_context", "interpretation_id", "source_binding", "definition_uses",
            "cross_references"}
        assert canonical_dag_json_bytes(json.loads(ast_record["ast_json"])) == canonical_dag_json_bytes(complete)
        assert complete["source_binding"]["source_version_cid"] == unit["source_version"]["record_cid"]
        assert complete["source_binding"]["occurrence_cid"] == unit["occurrence"]["record_cid"]
    mixed = admission["units"][2]["canonical_ir"]
    assert {item["name"] for item in mixed["typed_expression"]["signature"]["sorts"]} >= {
        "Object", "EventFrame", "TimeFrame"}
    assert len(mixed["definition_uses"][0]["target_typed_paths"]) == 2
    assert report["schema"] == "legal-uscode-release-closure-report/v3"
    assert report["profile"] == "reviewed-norm-v3-physical-three-cache-replay/v1"
    assert report["local_replay_complete"] is True
    assert report["local_source_cache_entity_bindings_verified"] is True
    assert report["independent_reviewed_crosswalk_verified"] is True
    assert report["fixture_only"] is True and report["provenance_kind"] == "fictional_fixture"
    assert report["physical_crosswalk"]["counts"] == dict(
        law_rows=3, reviewed_units=3, paired_cache_rows=4,
        entity_rows=len(physical_closure_material_v3["entity_rows"]),
        graph_nodes=len(graph["graph"]["nodes"]), graph_edges=len(graph["graph"]["edges"]))
    assert "independent_law_span_entity_to_reviewed_source_crosswalk_missing" not in report["blockers"]
    assert "original_admitted_native_parent_custody_not_established" in report["blockers"]
    assert "immutable_remote_Hub_readback_not_established" in report["blockers"]
    assert "retained_native_receipt_and_packet_not_provided" in report["blockers"]
    assert all(report[key] is False for key in (
        "release_ready", "closure_complete", "admitted", "formalized", "proof_verified",
        "source_semantics_verified", "source_authenticity_verified",
        "original_native_parent_custody_verified", "remote_readback_verified",
        "native_receipt_replayed", "model_or_compiler_execution_performed"))


def test_reviewed_v3_json_depth_is_explicit_bounded_and_preserves_legacy_envelopes():
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts

    assert (contracts.MAX_RECORD_BYTES, contracts.MAX_JSON_NODES,
            contracts.MAX_JSON_DEPTH, contracts.MAX_INTEGER) == (
                1024 * 1024, 25_000, 20, (1 << 63) - 1)
    value = {"profile": "fixture:bounded-deep-json"}
    for _ in range(22):
        value = [value]
    raw = _physical_wire(value)
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="node/depth"):
        contracts.load_json_bytes(raw, expected_sha256=digest)
    assert contracts.load_json_bytes(raw, expected_sha256=digest, max_depth=96) == value
    # The old record loader also retains its original depth fence.
    with pytest.raises(ValueError, match="node/depth"):
        contracts.load_record_bytes(raw, expected_sha256=digest)
    deeper = None
    for _ in range(97):
        deeper = [deeper]
    beyond = _physical_wire(deeper)
    with pytest.raises(ValueError, match="node/depth"):
        contracts.load_json_bytes(beyond,
            expected_sha256=hashlib.sha256(beyond).hexdigest(), max_depth=96)
    for invalid in (True, -1, 97):
        with pytest.raises(ValueError):
            contracts.load_json_bytes(b"null",
                expected_sha256=hashlib.sha256(b"null").hexdigest(), max_depth=invalid)


@pytest.mark.parametrize("damage", [
    "source_bytes", "ir_link", "graph_generation", "dependency_observation",
    "toolchain", "review_revoked", "source_version_link", "unit_population",
    "unsupported_profile", "wrong_schema", "unrecognized_authority_flag",
])
def test_physical_closure_v3_rejects_changed_component_with_resealed_outer_hash(
        physical_closure_component_v3, damage):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graphs
    from ipfs_datasets_py.logic.autoformal import legal_graph_review as authority

    request = deepcopy(physical_closure_component_v3)
    rows = {row["artifact_id"]: row for row in request["artifacts"]}
    component = request["component"]
    def replace(row, body):
        row.update(payload=body, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    if damage in {"source_bytes", "dependency_observation", "toolchain", "review_revoked"}:
        row = rows[component["replay"]]
        replay = transport.decode_parent_replay_value_v1(
            row["payload"], expected_payload_sha256=row["sha256"])
        kwargs = replay["admission_kwargs"]
        if damage == "source_bytes":
            inputs = kwargs["preparation_inputs"]["source_inputs"]
            inputs[next(iter(inputs))]["raw_bytes"] += b"changed"
        elif damage == "dependency_observation":
            observed = kwargs["observed_artifact_sha256s"]
            observed[next(iter(observed))] = "0" * 64
        elif damage == "toolchain":
            replay["toolchain"] = "leanprover/lean4:v4.99.0"
        else:
            registry = replay["admission_args"][1]
            registry["keys"][0]["revoked_at_utc"] = kwargs["at_time_utc"]
            kwargs["expected_registry_sha256"] = authority.digest(registry)
        replace(row, transport.encode_parent_replay_value_v1(replay))
    elif damage == "ir_link":
        ir = [row for row in request["artifacts"] if row["family"] == "ir"]
        assert ir[0]["payload"] != ir[1]["payload"]
        replace(ir[0], ir[1]["payload"])
    elif damage == "graph_generation":
        row = rows[component["graph"]]
        graph = json.loads(row["payload"])
        graph["counts"]["nodes"] += 1
        graph = seal_record({key: value for key, value in graph.items()
            if key not in ("record_cid", "cid_scope")})
        replace(row, canonical_dag_json_bytes(graph))
        request["pins"]["graph"] = graphs.norm_definition_graph_sha256(graph)
    elif damage == "source_version_link":
        versions = [row for row in request["artifacts"] if row["family"] == "source_version"]
        assert versions[0]["payload"] != versions[1]["payload"]
        replace(versions[0], versions[1]["payload"])
    elif damage == "unit_population":
        request["expected_unit_ids"].pop()
    elif damage == "unsupported_profile":
        request["profile"] = "reviewed-norm-v3-physical-three-cache-replay/v999"
    elif damage == "wrong_schema":
        request["schema"] = "legal-uscode-release-closure-request/v2"
    else:
        request["verified"] = True
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)


@pytest.mark.parametrize("field", [
    "profile", "typed_expression", "argument_roles", "assumptions",
    "governing_context", "interpretation_id", "source_binding",
    "definition_uses", "cross_references",
])
def test_physical_closure_v3_rejects_omitted_complete_canonical_target_field(
        physical_closure_component_v3, field):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission

    request = deepcopy(physical_closure_component_v3)
    row = next(row for row in request["artifacts"]
        if row["artifact_id"] == request["component"]["admission"])
    offered = json.loads(row["payload"])
    del offered["units"][2]["canonical_ir"][field]
    body = _physical_wire(offered)
    row.update(payload=body, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    request["pins"]["admission"] = admission.norm_content_adjudication_sha256(offered)
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)


@pytest.mark.parametrize("damage", ["span_wrong_overlap", "entity_endpoint"])
def test_physical_closure_v3_checks_signed_crosswalk_against_actual_complete_population(
        physical_closure_material_v3, damage):
    # Existing fictional signers sign the final authored dependency, including
    # its deliberate mismatch. Signatures do not replace physical replay.
    request = _physical_closure_request(physical_closure_material_v3,
        reviewed_version=3, map_damage=damage)
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)


@pytest.mark.parametrize("legacy_name", [
    "validate_uscode_release_closure_v1", "validate_uscode_release_closure_v2",
])
def test_physical_closure_v3_cannot_be_consumed_by_legacy_domains(
        physical_closure_component_v3, legacy_name):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw = transport.encode_parent_replay_value_v1(physical_closure_component_v3)
    with pytest.raises(ValueError):
        getattr(release, legacy_name)(raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest())


def test_physical_closure_v3_requires_its_own_domain_for_v2_component(physical_closure_component):
    with pytest.raises(ValueError):
        replay_physical_closure_v3(physical_closure_component)


@pytest.mark.parametrize("direct", [False, True])
def test_physical_closure_v3_actual_explicit_cli_keeps_authority_false(
        physical_closure_component_v3, tmp_path, direct):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw = transport.encode_parent_replay_value_v1(physical_closure_component_v3)
    path = tmp_path / "physical-closure-v3.request"
    path.write_bytes(raw)
    result, receipt = run_cli([
        "validate-closure", "--profile", "reviewed-norm-v3-physical-three-cache-replay/v1",
        "--request", str(path), "--request-sha256", hashlib.sha256(raw).hexdigest()],
        cwd=tmp_path, direct=direct)
    assert result.returncode == 0 and receipt["status"] == "success"
    assert receipt["closure"]["independent_reviewed_crosswalk_verified"] is True
    assert receipt["closure"]["original_native_parent_custody_verified"] is False
    assert receipt["closure"]["remote_readback_verified"] is False
    assert receipt["admitted"] is receipt["formalized"] is receipt["proof_verified"] is False
    assert receipt["closure"]["release_ready"] is receipt["closure"]["closure_complete"] is False
    # Default selection remains the existing local V2 profile.
    rejected, error = run_cli(["validate-closure", "--request", str(path),
        "--request-sha256", hashlib.sha256(raw).hexdigest()], cwd=tmp_path, direct=direct)
    assert rejected.returncode != 0 and error["status"] == "error"



@pytest.mark.parametrize("role", ["graph", "preservation"])
def test_physical_closure_v3_refuses_complete_valid_v2_graph_or_preparation(
        physical_closure_component_v3, physical_closure_component, role):
    from copy import deepcopy
    # Establish the V2 material as a valid complete independent control; it
    # cannot be retagged as mixed V3 merely by changing the outer byte pins.
    assert replay_physical_closure(physical_closure_component)["local_replay_complete"] is True
    request = deepcopy(physical_closure_component_v3)
    other = physical_closure_component
    original = next(row for row in other["artifacts"]
        if row["artifact_id"] == other["component"][role])
    selected = next(row for row in request["artifacts"]
        if row["artifact_id"] == request["component"][role])
    selected.update(payload=original["payload"], bytes=original["bytes"], sha256=original["sha256"])
    request["pins"][role] = other["pins"][role]
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)



# Transport-only controls deliberately carry an invalid Native receipt. Reaching
# its genuine validator is not an actual Lean execution or proof qualification.
def _untrusted_large_native_closure(request, *, padding_files=1):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
    request = deepcopy(request)
    receipt = b"{}"
    packet = tuple(sorted([("build-receipt.json", receipt)] + [
        ("untrusted-padding-" + str(i) + ".bin", b"x" * 1_000_001)
        for i in range(padding_files)]))
    packet_raw = transport.encode_parent_replay_value_v1(
        [[name, raw] for name, raw in packet], max_bytes=64 * 1024**2)
    receipt_id, packet_id = "fixture:untrusted-large-receipt", "fixture:untrusted-large-packet"
    for identity, family, raw in ((receipt_id, "native_receipt", receipt),
                                  (packet_id, "native_packet", packet_raw)):
        request["artifacts"].append(dict(artifact_id=identity, family=family,
            payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        request["expected_artifact_ids"].append(identity)
    request["native"] = dict(receipt=receipt_id, packet=packet_id,
        expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
        expected_binary_sha256={})
    return request, packet_raw


@pytest.mark.parametrize("padding_files", [1, 9])
def test_physical_closure_v3_large_native_transport_reaches_real_authentication(
        physical_closure_component_v3, padding_files):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    request, packet_raw = _untrusted_large_native_closure(
        physical_closure_component_v3, padding_files=padding_files)
    assert len(packet_raw) > 1_000_000
    raw = transport.encode_parent_replay_value_v1(request, max_bytes=64 * 1024**2)
    if padding_files == 9:
        assert len(packet_raw) > 8 * 1024**2 and len(raw) > 8 * 1024**2
    # No Native callback is replaced: this exact refusal comes from the actual
    # V3 receipt validator, after physical/core/packet transport has succeeded.
    with pytest.raises(ValueError, match="closed complete mixed aggregate receipt required"):
        release.validate_uscode_release_closure_v3(
            raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("direct", [False, True])
def test_physical_closure_v3_large_native_cli_transport_grants_no_authenticity(
        physical_closure_component_v3, tmp_path, direct):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    request, _ = _untrusted_large_native_closure(
        physical_closure_component_v3, padding_files=9)
    raw = transport.encode_parent_replay_value_v1(request, max_bytes=64 * 1024**2)
    assert 8 * 1024**2 < len(raw) < 12 * 1024**2
    path = tmp_path / "large-untrusted-native.request"
    try:
        path.write_bytes(raw)
        result, receipt = run_cli([
            "validate-closure", "--profile", "reviewed-norm-v3-physical-three-cache-replay/v1",
            "--request", str(path), "--request-sha256", hashlib.sha256(raw).hexdigest()],
            cwd=tmp_path, direct=direct)
        assert result.returncode != 0 and receipt["status"] == "error"
        assert receipt["error_type"] == "ValueError"
        assert receipt["error"] == "closed complete mixed aggregate receipt required"
        assert all(receipt[key] is False for key in (
            "admitted", "formalized", "source_semantics_verified",
            "source_authenticity_verified", "proof_verified"))
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.parametrize("legacy_name", [
    "validate_uscode_release_closure_v1", "validate_uscode_release_closure_v2"])
def test_large_native_transport_does_not_widen_legacy_artifact_limits(
        closure_component, physical_closure_component, legacy_name):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    base = (closure_component if legacy_name.endswith("_v1")
            else physical_closure_component)
    request, _ = _untrusted_large_native_closure(base)
    raw = transport.encode_parent_replay_value_v1(request)
    with pytest.raises(ValueError, match="bounded.*artifact"):
        getattr(release, legacy_name)(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("family", ["native_receipt", "replay", "graph", "admission"])
def test_v3_large_native_allowance_does_not_widen_other_artifact_families(
        physical_closure_component_v3, family):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    request, _ = _untrusted_large_native_closure(physical_closure_component_v3)
    row = next(row for row in request["artifacts"]
               if row["artifact_id"] == request["native"]["packet"])
    row["family"] = family
    raw = transport.encode_parent_replay_value_v1(request)
    with pytest.raises(ValueError, match="unique bounded physical artifact"):
        release.validate_uscode_release_closure_v3(
            raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("profile", [
    None, "reviewed-norm-v2-local-replay/v1", "reviewed-norm-v2-physical-three-cache-replay/v1"])
def test_legacy_closure_cli_request_file_limit_remains_eight_mib(tmp_path, capsys, profile):
    from scripts.ops.legal_ir import validate_uscode_corpus_release as cli
    raw = b" " * (8 * 1024**2 + 1)
    path = tmp_path / "oversized-legacy.request"
    arguments = ["validate-closure", "--request", str(path),
                 "--request-sha256", hashlib.sha256(raw).hexdigest()]
    if profile is not None:
        arguments += ["--profile", profile]
    try:
        path.write_bytes(raw)
        assert cli.main(arguments) == 1
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 1
        receipt = json.loads(lines[0])
        assert receipt["error_type"] == "CLIError"
        assert receipt["error"] == "snapshot must be a bounded regular file"
    finally:
        path.unlink(missing_ok=True)


def test_v3_large_wire_retains_existing_expanded_input_budget_per_occurrence():
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    # Reusing one immutable byte object must not discount repeated expanded
    # occurrences. The existing codec refuses before emitting a giant wire.
    payload = b"x" * 1_000_000
    rows = [dict(artifact_id="fixture:budget:" + str(i), family="native_packet",
                 payload=payload, bytes=len(payload),
                 sha256=hashlib.sha256(payload).hexdigest()) for i in range(64)]
    with pytest.raises(ValueError, match="complete parent Lake input budget exceeded"):
        transport.encode_parent_replay_value_v1(
            {"artifacts": rows}, max_bytes=64 * 1024**2)


def _replay_physical_with_runtime_observer_v3(request, observer):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    raw = transport.encode_parent_replay_value_v1(request, max_bytes=64 * 1024**2)
    return release._validate_uscode_release_physical_closure(
        raw, expected_request_sha256=hashlib.sha256(raw).hexdigest(),
        reviewed_version=3, _observe_checked_context=observer)


def test_physical_v3_runtime_observer_is_once_non_authoritative_and_keeps_wire_blocker(
        physical_closure_component_v3):
    observed = []
    def observer(context):
        observed.append(context)
        assert context["reviewed_version"] == 3 and context["native"] is None
        assert context["pins"] == {
            name: physical_closure_component_v3["pins"][name]
            for name in ("graph", "admission", "preservation")}
        # An arbitrary callback's flags cannot establish parent custody.
        return {"original_native_parent_custody_verified": True,
                "original_success_authenticated": True, "admitted": True}
    report = _replay_physical_with_runtime_observer_v3(
        physical_closure_component_v3, observer)
    assert len(observed) == 1
    assert report["local_replay_complete"] is True
    assert report["original_native_parent_custody_verified"] is False
    assert "original_admitted_native_parent_custody_not_established" in report["blockers"]
    assert all(report[name] is False for name in (
        "release_ready", "closure_complete", "admitted", "formalized", "proof_verified",
        "source_semantics_verified", "source_authenticity_verified"))


@pytest.mark.parametrize("raises", [False, True])
def test_physical_v3_runtime_observer_refuses_current_source_only_mutation_on_each_exit(
        physical_closure_component_v3, raises):
    def observer(context):
        before = (context["pins"]["graph"], context["pins"]["admission"],
                  context["pins"]["preservation"])
        observations = context["kwargs"]["observed_artifact_sha256s"]
        key = next(iter(observations))
        observations[key] = "0" * 64 if observations[key] != "0" * 64 else "1" * 64
        assert before == (context["pins"]["graph"], context["pins"]["admission"],
                          context["pins"]["preservation"])
        if raises:
            raise RuntimeError("observer exception after current observation mutation")
    with pytest.raises(ValueError, match="complete current replay inputs changed"):
        _replay_physical_with_runtime_observer_v3(
            physical_closure_component_v3, observer)


def test_physical_v3_runtime_observer_preserves_unchanged_original_exception(
        physical_closure_component_v3):
    sentinel = RuntimeError("unchanged observer exception")
    observed = []
    def observer(context):
        observed.append(context)
        raise sentinel
    with pytest.raises(RuntimeError) as caught:
        _replay_physical_with_runtime_observer_v3(
            physical_closure_component_v3, observer)
    assert caught.value is sentinel and len(observed) == 1


# These private authored modules exercise cold code binding, not Native proof.
@pytest.fixture
def joined_loaded_owner_guard_case(tmp_path):
    import importlib.util
    import sys
    name = "fictional_joined_owner_" + tmp_path.name.replace("-", "_")
    path = tmp_path / "joined_guard_fixture.py"
    path.write_text("import json\nfrom pathlib import Path\nfrom contextlib import contextmanager\nfrom dataclasses import dataclass\nfrom ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts\n\nLIMITS = {\"rows\": [3]}\ndef entry(value=None, *, enabled=True):\n    return value\nentry.__defaults__ = ([],)\n\n@contextmanager\ndef wrapped():\n    yield 3\n\ndef closure_factory():\n    def leaf(value=3):\n        return value\n    def wrapper():\n        return leaf()\n    return wrapper, leaf\nclosure, _leaf = closure_factory()\n\ndef external(value=3):\n    return value\n\n@dataclass(frozen=True)\nclass Row:\n    value: int = 3\n    @classmethod\n    def from_row(cls, value):\n        return cls(value)\n\n_JOIN_LOADED_OWNER_GUARD_V1 = contracts._capture_loaded_owner_guard_v1(\n    globals(), value_names=(\"LIMITS\",), class_names=(\"Row\",),\n    imported_function_names=(\"external\",), alias_names=(\"Path\", \"json\"))\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        guard = module._JOIN_LOADED_OWNER_GUARD_V1
        assert guard() is None
        yield module.contracts, vars(module), guard, module._leaf
    finally:
        sys.modules.pop(name, None)
@pytest.mark.parametrize("mutation", [
    "code", "defaults", "nested_default", "kwdefaults", "nested_literal",
    "class_method_code", "generated_init_code", "field_metadata",
    "wrapped_generator", "closure_function", "imported_binding",
    "new_global_shadow", "path_alias", "module_alias", "checker_binding",
])
def test_join_loaded_owner_guard_refuses_current_binding_mutations(
        mutation, joined_loaded_owner_guard_case):
    contracts, namespace, guard, leaf = joined_loaded_owner_guard_case
    def replacement(value=None, *, enabled=True):
        return None
    if mutation == "code":
        namespace["entry"].__code__ = replacement.__code__
    elif mutation == "defaults":
        namespace["entry"].__defaults__ = (None,)
    elif mutation == "nested_default":
        namespace["entry"].__defaults__[0].append("changed")
    elif mutation == "kwdefaults":
        namespace["entry"].__kwdefaults__["enabled"] = False
    elif mutation == "nested_literal":
        namespace["LIMITS"]["rows"].append(4)
    elif mutation == "class_method_code":
        namespace["Row"].__dict__["from_row"].__func__.__code__ = replacement.__code__
    elif mutation == "generated_init_code":
        original = namespace["Row"].__init__.__code__
        namespace["Row"].__init__.__code__ = original.replace(
            co_filename=original.co_filename + ":authored-code-change")
    elif mutation == "field_metadata":
        namespace["Row"].__dataclass_fields__["value"].default = 4
    elif mutation == "wrapped_generator":
        namespace["wrapped"].__wrapped__.__code__ = replacement.__code__
    elif mutation == "closure_function":
        leaf.__code__ = replacement.__code__
    elif mutation == "imported_binding":
        namespace["external"] = replacement
    elif mutation == "new_global_shadow":
        namespace["type"] = object
    elif mutation == "path_alias":
        from pathlib import PurePosixPath
        namespace["Path"] = PurePosixPath
    elif mutation == "module_alias":
        import math
        namespace["json"] = math
    else:
        namespace["_JOIN_LOADED_OWNER_GUARD_V1"] = replacement
    with pytest.raises(contracts.CorpusContractError, match="loaded-owner"):
        guard()


def test_join_loaded_owner_guard_cold_checker_identity_detects_baseline_replacement(
        joined_loaded_owner_guard_case):
    contracts, _namespace, guard, _leaf = joined_loaded_owner_guard_case
    initial = contracts._loaded_owner_guard_identity_v1(guard)
    cells = dict(zip(guard.__code__.co_freevars, guard.__closure__))
    # The issuing owner compares this identity material BEFORE using a checker;
    # this unit test never treats the changed checker as an authority.
    original = cells["expected"].cell_contents
    cells["expected"].cell_contents = ("forged",)
    assert contracts._loaded_owner_guard_identity_v1(guard) != initial
    cells["expected"].cell_contents = original
    assert contracts._loaded_owner_guard_identity_v1(guard) == initial
    assert guard() is None



def _import_joined_guard_control(tmp_path, body):
    import importlib.util
    import sys
    name = "fictional_join_control_" + tmp_path.name.replace("-", "_")
    path = tmp_path / "joined_guard_control.py"
    path.write_text(body, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(name, None)


def test_join_loaded_owner_guard_tracks_literal_cycles_without_properties(tmp_path):
    module = _import_joined_guard_control(tmp_path, "from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts\ncalls = []\nclass Trap:\n    @property\n    def danger(self):\n        calls.append(\"property executed\")\n        raise AssertionError(\"guard must not invoke properties\")\nSTATE = []\nSTATE.append(STATE)\n_JOIN_LOADED_OWNER_GUARD_V1 = contracts._capture_loaded_owner_guard_v1(\n    globals(), value_names=(\"STATE\",), class_names=(\"Trap\",))\n")
    guard = module._JOIN_LOADED_OWNER_GUARD_V1
    assert guard() is None and module.calls == []
    module.STATE.append(None)
    with pytest.raises(module.contracts.CorpusContractError, match="loaded-owner"):
        guard()
    assert module.calls == []


@pytest.mark.parametrize("damage", ["depth", "nodes", "literal_bytes"])
def test_join_loaded_owner_guard_bounds_snapshot_population(damage, tmp_path):
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    declarations = {
        "depth": "STATE = None\nfor _index in range(60):\n    STATE = [STATE]\n",
        "nodes": "STATE = [None] * (contracts._LOADED_OWNER_MAX_NODES_V1 + 1)\n",
        "literal_bytes": "STATE = b'x' * (contracts._LOADED_OWNER_MAX_LITERAL_BYTES_V1 + 1)\n",
    }
    body = ("from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts\n"
            + declarations[damage]
            + "_JOIN_LOADED_OWNER_GUARD_V1 = contracts._capture_loaded_owner_guard_v1("
              "globals(), value_names=('STATE',))\n")
    with pytest.raises(contracts.CorpusContractError, match="bound"):
        _import_joined_guard_control(tmp_path, body)


def test_join_loaded_owner_guard_refuses_unknown_objects_without_repr_or_properties(tmp_path):
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    with pytest.raises(contracts.CorpusContractError, match="unsupported"):
        _import_joined_guard_control(tmp_path, "from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts\nclass Unknown:\n    def __repr__(self):\n        raise AssertionError(\"guard must not invoke repr\")\n    @property\n    def danger(self):\n        raise AssertionError(\"guard must not invoke properties\")\nSTATE = Unknown()\n_JOIN_LOADED_OWNER_GUARD_V1 = contracts._capture_loaded_owner_guard_v1(\n    globals(), value_names=(\"STATE\",))\n")


def test_join_loaded_owner_guard_refuses_callback_reregistration(joined_loaded_owner_guard_case):
    contracts, namespace, guard, _leaf = joined_loaded_owner_guard_case
    del namespace["_JOIN_LOADED_OWNER_GUARD_V1"]
    try:
        with pytest.raises(contracts.CorpusContractError, match="genuine module import"):
            contracts._capture_loaded_owner_guard_v1(
                namespace, value_names=("LIMITS",), class_names=("Row",),
                imported_function_names=("external",))
    finally:
        namespace["_JOIN_LOADED_OWNER_GUARD_V1"] = guard
    assert guard() is None


def test_join_loaded_owner_guard_refuses_same_filename_exec_reseed(joined_loaded_owner_guard_case):
    contracts, namespace, guard, _leaf = joined_loaded_owner_guard_case
    original_code = namespace["entry"].__code__
    def replacement(value=None, *, enabled=True):
        return "changed without Source edits"
    namespace["entry"].__code__ = replacement.__code__
    del namespace["_JOIN_LOADED_OWNER_GUARD_V1"]
    registration = (
        "_JOIN_LOADED_OWNER_GUARD_V1 = contracts._capture_loaded_owner_guard_v1("
        "globals(), value_names=('LIMITS',), class_names=('Row',),"
        "imported_function_names=('external',), alias_names=('Path','json'))")
    try:
        # The fake module frame has the SAME real filename/spec/globals. The
        # private original-import registry must refuse to bless changed code.
        with pytest.raises(contracts.CorpusContractError, match="already registered"):
            exec(compile(registration, namespace["__file__"], "exec"), namespace)
        namespace["_JOIN_LOADED_OWNER_GUARD_V1"] = guard
        with pytest.raises(contracts.CorpusContractError, match="binding differs"):
            guard()
    finally:
        namespace["entry"].__code__ = original_code
        namespace["_JOIN_LOADED_OWNER_GUARD_V1"] = guard
    assert guard() is None


@pytest.mark.parametrize("location", ["selected_value", "dataclass_metadata"])
def test_join_loaded_owner_verifier_refuses_mapping_proxy_without_callbacks(
        location, joined_loaded_owner_guard_case):
    from collections.abc import Mapping
    from types import MappingProxyType
    contracts, namespace, guard, _leaf = joined_loaded_owner_guard_case
    calls = []
    class TrapMapping(Mapping):
        def __len__(self):
            calls.append("__len__")
            raise AssertionError("mapping proxy delegated __len__")
        def __iter__(self):
            calls.append("__iter__")
            raise AssertionError("mapping proxy delegated __iter__")
        def __getitem__(self, key):
            calls.append("__getitem__")
            raise AssertionError("mapping proxy delegated __getitem__")
        def items(self):
            calls.append("items")
            raise AssertionError("mapping proxy delegated items")
    proxy = MappingProxyType(TrapMapping())
    assert calls == []
    field = namespace["Row"].__dataclass_fields__["value"]
    original = namespace["LIMITS"] if location == "selected_value" else field.metadata
    try:
        if location == "selected_value":
            namespace["LIMITS"] = proxy
        else:
            field.metadata = proxy
        with pytest.raises(contracts.CorpusContractError, match="mapping proxy"):
            guard()
        assert calls == []
    finally:
        if location == "selected_value":
            namespace["LIMITS"] = original
        else:
            field.metadata = original
    assert guard() is None and calls == []


def test_join_loaded_owner_shape_refuses_untrusted_even_plain_mapping_proxy():
    from types import MappingProxyType
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    # A proxy's exact native type does not prove its backing mapping is native.
    with pytest.raises(contracts.CorpusContractError, match="mapping proxy"):
        contracts._loaded_owner_shape_v1(
            (("value", "untrusted_proxy", MappingProxyType({})),))


@pytest.mark.parametrize("primary_present", [False, True])
@pytest.mark.parametrize("failures", [(0, 2), (1,), (2,)])
def test_physical_closing_checks_attempt_every_fence_and_keep_error_context(primary_present, failures):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    seen = []
    errors = [ValueError("closing refusal " + str(index)) for index in range(3)]
    primary = RuntimeError("original observer") if primary_present else None
    def check(index):
        seen.append(index)
        if index in failures:
            raise errors[index]
    with pytest.raises(ValueError) as caught:
        release._physical_complete_checks_v1(tuple(
            (str(index), lambda index=index: check(index)) for index in range(3)),
            primary=primary)
    assert seen == [0, 1, 2]
    assert caught.value is errors[failures[0]]
    if primary is not None:
        assert caught.value.__cause__ is primary
    if len(failures) > 1:
        assert any("additional closing failure" in note
                   for note in caught.value.__notes__)


def test_physical_closing_checks_do_not_replace_a_pending_unchanged_error():
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    sentinel = RuntimeError("unchanged pending observer")
    seen = []
    assert release._physical_complete_checks_v1((
        ("first", lambda: seen.append("first")),
        ("second", lambda: seen.append("second"))), primary=sentinel) is None
    assert seen == ["first", "second"] and sentinel.__cause__ is None


@pytest.mark.parametrize("raises", [False, True])
def test_physical_observer_replaced_law_delegate_is_refused_before_invocation(
        physical_closure_component_v3, monkeypatch, raises):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_dataset as law
    called = []
    def replacement(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("replaced law delegate must never run")
    def observe(context):
        monkeypatch.setattr(law, "capture_uscode_source_documents_from_parquet", replacement)
        if raises:
            raise RuntimeError("observer changed a loaded delegate")
    with pytest.raises(ValueError, match="binding|callback changed"):
        _replay_physical_with_runtime_observer_v3(physical_closure_component_v3, observe)
    assert called == []


def test_physical_observer_replaced_join_guard_is_refused_before_invocation(
        physical_closure_component_v3, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    called = []
    def replacement():
        called.append(True)
    def observe(context):
        monkeypatch.setattr(release, "_joined_release_guard", replacement)
    with pytest.raises(ValueError, match="joined guard changed"):
        _replay_physical_with_runtime_observer_v3(physical_closure_component_v3, observe)
    assert called == []


@pytest.mark.parametrize("change", ["bytes", "full9_only"])
def test_physical_postclose_byte_fence_refuses_changed_private_file(
        physical_closure_component_v3, tmp_path, change):
    import os
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    observed = []
    _replay_physical_with_runtime_observer_v3(
        physical_closure_component_v3, lambda context: observed.append(context))
    # This isolates the byte-fence contract. It is not a parent capability,
    # signed target substitution, or authority claim from a caller context.
    context = dict(observed[0])
    path = tmp_path / "private-physical-generation.bin"
    raw = b"same bounded private bytes"
    path.write_bytes(raw)
    keys = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
            "st_size", "st_mtime_ns", "st_ctime_ns")
    original = path.stat()
    row = (str(path), tuple(getattr(original, key) for key in keys), raw)
    context["physical_files"] = (row, row)
    release._physical_postclose_fence_v1(context)
    if change == "bytes":
        path.write_bytes(b"different private bytes")
    else:
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
        assert path.read_bytes() == raw
    with pytest.raises(ValueError, match="physical file generation|physical bytes or generation"):
        release._physical_postclose_fence_v1(context)


@pytest.mark.parametrize("primary_present", [False, True])
def test_physical_inner_and_postclose_batches_keep_first_refusal_without_rendering_errors(primary_present):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    seen = []
    class HostileError(ValueError):
        def __str__(self):
            raise AssertionError("closing custody rendered an arbitrary exception")
    first, second, later = HostileError(), HostileError(), HostileError()
    observer = HostileError() if primary_present else None
    failures = []
    def check(label, error=None):
        seen.append(label)
        if error is not None:
            raise error
    with pytest.raises(HostileError) as inner:
        release._physical_complete_checks_v1((
            ("inner-first", lambda: check("inner-first", first)),
            ("inner-second", lambda: check("inner-second", second)),
            ("inner-last", lambda: check("inner-last"))),
            primary=observer, _closing_failures=failures)
    assert inner.value is first
    with pytest.raises(HostileError) as final:
        release._physical_complete_checks_v1((
            ("postclose-first", lambda: check("postclose-first", later)),
            ("postclose-last", lambda: check("postclose-last"))),
            primary=inner.value, _closing_failures=failures)
    assert final.value is first
    assert seen == ["inner-first", "inner-second", "inner-last", "postclose-first", "postclose-last"]
    if observer is not None:
        assert final.value.__cause__ is observer
    assert any("postclose-first" in note for note in final.value.__notes__)



def test_joined_release_error_class_replacement_is_refused_before_invocation(monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    called = []
    def replacement(*args, **kwargs):
        called.append(True)
        return ValueError("caller supplied error constructor")
    monkeypatch.setattr(release, "ReleaseCoordinatorError", replacement)
    with pytest.raises(ValueError, match="ordinary selected class|implementation binding"):
        release._joined_release_guard()
    assert called == []


def test_physical_descriptor_closes_when_initial_fstat_fails(
        physical_closure_component_v3, monkeypatch):
    import os
    import sys
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    original_open, original_fstat, original_close = os.open, os.fstat, os.close
    live, opened, closed = set(), [], []
    failure = OSError("injected first physical descriptor stat failure")
    injected = []
    def opened_fd(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        caller = sys._getframe(1)
        if caller.f_code.co_name == "held_file" and caller.f_code.co_filename == release.__file__:
            live.add(fd)
            opened.append(fd)
        return fd
    def stat_fd(fd):
        if fd in live and not injected:
            injected.append(fd)
            raise failure
        return original_fstat(fd)
    def closed_fd(fd):
        if fd in live:
            live.remove(fd)
            closed.append(fd)
        return original_close(fd)
    monkeypatch.setattr(os, "open", opened_fd)
    monkeypatch.setattr(os, "fstat", stat_fd)
    monkeypatch.setattr(os, "close", closed_fd)
    with pytest.raises(OSError) as caught:
        _replay_physical_with_runtime_observer_v3(physical_closure_component_v3, lambda context: None)
    assert caught.value is failure and len(injected) == len(opened) == 1
    assert closed == opened and not live
    with pytest.raises(OSError):
        original_fstat(opened[0])


def test_physical_final_descriptor_failure_wins_over_observer_without_exception_hooks(
        physical_closure_component_v3, monkeypatch):
    import os
    import sys
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    original_open, original_fstat, original_close = os.open, os.fstat, os.close
    live, opened, closed = {}, [], []
    hooks = []
    class ObserverError(RuntimeError):
        def __str__(self):
            hooks.append("str")
            raise AssertionError("closing custody rendered observer")
        def add_note(self, note):
            hooks.append("add_note")
            raise AssertionError("closing custody delegated an observer hook")
    observer = ObserverError()
    failure = OSError("injected final physical descriptor stat failure")
    injected = []
    law_path = physical_closure_component_v3["physical_inputs"]["law_path"]
    def opened_fd(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        caller = sys._getframe(1)
        if caller.f_code.co_name == "held_file" and caller.f_code.co_filename == release.__file__:
            live[fd] = str(path)
            opened.append(fd)
        return fd
    def stat_fd(fd):
        # Inject only at the held-file contextmanager's exit fence. Earlier
        # replay/fence reads must pass so this detects final-custody suppression.
        caller = sys._getframe(1)
        parent = caller.f_back
        generator = None if parent is None else parent.f_back
        if (live.get(fd) == law_path and not injected
                and caller.f_code.co_name == "check"
                and generator is not None and generator.f_code.co_name == "held_file"
                and generator.f_locals.get("primary") is observer):
            injected.append(fd)
            raise failure
        return original_fstat(fd)
    def closed_fd(fd):
        if fd in live:
            del live[fd]
            closed.append(fd)
        return original_close(fd)
    def observe(context):
        raise observer
    monkeypatch.setattr(os, "open", opened_fd)
    monkeypatch.setattr(os, "fstat", stat_fd)
    monkeypatch.setattr(os, "close", closed_fd)
    with pytest.raises(OSError) as caught:
        _replay_physical_with_runtime_observer_v3(physical_closure_component_v3, observe)
    assert caught.value is failure and failure.__cause__ is observer
    assert len(injected) == 1 and len(opened) == len(closed) == 2 and not live
    assert set(opened) == set(closed) and hooks == []
    for fd in opened:
        with pytest.raises(OSError):
            original_fstat(fd)



def test_registry_factory_closure_has_source_origin_real_native_guard_and_no_reset(monkeypatch):
    import types
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
    namespace = vars(contracts)
    guard = contracts._JOIN_LOADED_OWNER_GUARD_V1
    before = contracts._loaded_owner_guard_binding_v1(namespace, guard)
    guard()
    native._live_success_guard(native._owners(), reviewed_version=3)
    source_path = Path(contracts.__file__)
    compiled = compile(source_path.read_bytes(), str(source_path), "exec", dont_inherit=True,
                       optimize=sys.flags.optimize)
    pending, codes = [compiled], {}
    while pending:
        code = pending.pop()
        codes[code.co_qualname] = code
        pending.extend(value for value in code.co_consts if type(value) is types.CodeType)
    prefix = "_new_loaded_owner_registry_v1.<locals>."
    for name in ("_capture_loaded_owner_guard_v1", "_loaded_owner_guard_binding_v1",
                 "_loaded_owner_registry_binding_v1"):
        function = namespace[name]
        assert function.__globals__ is namespace
        assert function.__code__ == codes[prefix + name]
    assert guard.__code__ == codes[prefix + "_capture_loaded_owner_guard_v1.<locals>.verifier"]
    assert "_new_loaded_owner_registry_v1" not in namespace
    # Same-file module execution cannot reseed the real original namespace.
    with monkeypatch.context() as local:
        local.delitem(namespace, "_JOIN_LOADED_OWNER_GUARD_V1")
        with pytest.raises(ValueError, match="already registered"):
            exec(compile("_capture_loaded_owner_guard_v1(globals())",
                         str(source_path), "exec"), namespace)
    assert contracts._loaded_owner_guard_binding_v1(namespace, guard)[0] == before[0]
    guard()
    # Returned closures stay in the independent cold module checker.
    def changed_factory_body():
        registrations = None
        def changed(*args, **kwargs):
            _ = registrations
            raise AssertionError("changed returned closure must not be invoked")
        return changed
    replacement = changed_factory_body()
    current = contracts._capture_loaded_owner_guard_v1
    assert current.__code__.co_freevars == replacement.__code__.co_freevars
    with monkeypatch.context() as local:
        local.setattr(current, "__code__", replacement.__code__)
        with pytest.raises(ValueError, match="implementation binding"):
            guard()
    guard()
    native._live_success_guard(native._owners(), reviewed_version=3)
