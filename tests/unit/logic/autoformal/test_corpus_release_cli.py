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
    import stat
    original_source, source_sha, _ = snapshot_input
    # The existing C19 fixture still returns its original mapped case root.
    # Keep the original ordinary snapshot and use an exact private working copy.
    tmp_path = tmp_path / "work"
    tmp_path.mkdir(mode=0o700)
    snapshot_copy = tmp_path / original_source.name
    snapshot_copy.write_bytes(original_source.read_bytes())
    assert hashlib.sha256(snapshot_copy.read_bytes()).hexdigest() == source_sha
    source = snapshot_copy
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    parent_identity = lambda info: (info.st_dev, info.st_ino, info.st_uid, info.st_mode)
    leaf_identity = lambda info: (info.st_dev, info.st_ino, info.st_uid, info.st_gid,
        info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    parent = os.fstat(parent_fd)
    leaf = leaf_fd = created = expected_literal = None
    try:
        assert parent_identity(parent) == parent_identity(tmp_path.lstat())
        assert stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.geteuid()
        assert stat.S_IMODE(parent.st_mode) == 0o700
        if path_kind == "missing":
            source = tmp_path / "missing"
        elif path_kind == "directory":
            source = tmp_path
        elif path_kind == "symlink":
            link = tmp_path / "snapshot-link.json"
            link.symlink_to(source)
            leaf, expected_literal = link, str(source)
            source = link
        elif path_kind == "parent-symlink":
            link = tmp_path / "directory-link"
            link.symlink_to(tmp_path, target_is_directory=True)
            leaf, expected_literal = link, str(tmp_path)
            source = link / source.name
        else:
            source = tmp_path / "input-fifo"
            os.mkfifo(source)
            leaf = source
        if leaf is not None:
            # Immediate post-success observation of this TEST's actual creation.
            # O_PATH never opens a FIFO body; keep the inode held through teardown.
            leaf_fd = os.open(leaf.name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
            observed = os.fstat(leaf_fd)
            current = os.stat(leaf.name, dir_fd=parent_fd, follow_symlinks=False)
            assert leaf_identity(observed) == leaf_identity(current)
            assert observed.st_uid == os.geteuid() and observed.st_nlink == 1
            assert (stat.S_ISFIFO(observed.st_mode) if path_kind == "fifo" else stat.S_ISLNK(observed.st_mode))
            if expected_literal is not None:
                assert os.readlink(leaf.name, dir_fd=parent_fd) == expected_literal
            created = observed  # Cleanup token exists only after every creation observation passed.
        destination = tmp_path / "not-created"
        result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
            source_sha, "--output", str(destination)], cwd=tmp_path)
        assert result.returncode != 0
        assert receipt["status"] == "error"
        assert not destination.exists()
    finally:
        try:
            if leaf_fd is not None and created is not None:
                # Refuse changed/unobserved objects. Only this freshly authored
                # fixture is finalized, after the original refusal assertions.
                assert parent_identity(os.fstat(parent_fd)) == parent_identity(parent)
                assert parent_identity(tmp_path.lstat()) == parent_identity(parent)
                current = os.stat(leaf.name, dir_fd=parent_fd, follow_symlinks=False)
                assert leaf_identity(current) == leaf_identity(os.fstat(leaf_fd)) == leaf_identity(created)
                if expected_literal is not None:
                    assert os.readlink(leaf.name, dir_fd=parent_fd) == expected_literal
                for retained_source in (original_source, snapshot_copy):
                    with retained_source.open("rb") as retained_stream:
                        assert hashlib.sha256(retained_stream.read()).hexdigest() == source_sha
                        os.fsync(retained_stream.fileno())
                evidence = {"schema": "release-cli-authored-physical-fixture-observation/v1",
                    "path_kind": path_kind, "parent_identity": list(parent_identity(parent)),
                    "created_identity": list(leaf_identity(created)), "literal": expected_literal,
                    "snapshot_sha256": source_sha, "child_observed_actual_creation": True,
                    "atomic_creation_or_independent_SDK_sample_attested": False,
                    "Native_or_storage_release_authority": False}
                evidence_fd = os.open("authored-physical-fixture.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600, dir_fd=parent_fd)
                with os.fdopen(evidence_fd, "wb") as stream:
                    stream.write((json.dumps(evidence, sort_keys=True) + "\n").encode())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(parent_fd)
                # Recheck the same held inode/literal and anchored parent after
                # fsync, immediately before the one selected unlink.
                assert parent_identity(tmp_path.lstat()) == parent_identity(os.fstat(parent_fd)) == parent_identity(parent)
                assert leaf_identity(os.stat(leaf.name, dir_fd=parent_fd, follow_symlinks=False)) == leaf_identity(os.fstat(leaf_fd)) == leaf_identity(created)
                if expected_literal is not None:
                    assert os.readlink(leaf.name, dir_fd=parent_fd) == expected_literal
                os.unlink(leaf.name, dir_fd=parent_fd)
                removed = os.fstat(leaf_fd)
                assert (removed.st_dev, removed.st_ino) == (created.st_dev, created.st_ino)
                assert removed.st_nlink == 0
                with pytest.raises(FileNotFoundError):
                    os.stat(leaf.name, dir_fd=parent_fd, follow_symlinks=False)
                os.fsync(parent_fd)
        finally:
            if leaf_fd is not None:
                os.close(leaf_fd)
            os.close(parent_fd)


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


def _physical_source_material(directory, *, source_texts=None, shared_normative_row=False):
    import shutil
    from copy import deepcopy
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ipfs_datasets_py.logic.autoformal import corpus_source as source
    from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as payload
    from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
    from ipfs_datasets_py.logic.autoformal import span_cache, uscode_ingest as ingest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_dataset as dataset
    from tests.unit.logic.test_span_cache_paired_feed import source_row

    directory.mkdir()
    namespace = "physical-crosswalk"
    instrument = "fixture:" + namespace
    texts = [
        "For this fictional Act, a covered officer means an officer appointed by the Board. Café.",
        "Every covered officer must file a report unless the Board expressly excuses that officer.",
        "A covered officer may inspect the register.",
    ]
    if source_texts is not None:
        assert type(source_texts) is list and len(source_texts) == 3
        texts = list(source_texts)
    assert type(shared_normative_row) is bool
    # The two normative units share the complete second law row. Their
    # occurrence selectors, rather than document/IR labels, distinguish uses.
    law_texts = [texts[0], texts[1] + "\n\n" + texts[2]] if shared_normative_row else texts
    unit_document_ordinals = [0, 1, 1] if shared_normative_row else [0, 1, 2]
    units = []
    laws = []
    for index, text in enumerate(law_texts):
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
    if shared_normative_row:
        complete = law_texts[1]
        version = units[1]["source_version"]
        raw = complete.encode("utf-8")
        def selected(start, end):
            return source.build_source_occurrence(version,
                expected_raw_sha256=hashlib.sha256(raw).hexdigest(), extracted_text=complete,
                expected_extracted_sha256=hashlib.sha256(raw).hexdigest(),
                start_char=start, end_char=end,
                start_utf8=len(complete[:start].encode("utf-8")),
                end_utf8=len(complete[:end].encode("utf-8")))
        first_end = len(texts[1])
        units[1]["occurrence"] = selected(0, first_end)
        units.append(dict(unit_id=instrument + "/unit-3", source_version=deepcopy(version),
            occurrence=selected(first_end + 2, len(complete))))
    source_bindings = None
    if shared_normative_row:
        source_bindings = {unit["unit_id"]: dict(source_version=deepcopy(unit["source_version"]),
            occurrence=deepcopy(unit["occurrence"]),
            raw_bytes=law_texts[unit_document_ordinals[index]].encode("utf-8"),
            extracted_text=law_texts[unit_document_ordinals[index]])
            for index, unit in enumerate(units)}
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
        coordinate = coordinates["spans"][index]
        overlapping_units = [unit["unit_id"] for unit_index, unit in enumerate(units)
            if unit_document_ordinals[unit_index] == coordinate["input_document_ordinal"]
            and max(unit["occurrence"]["start_char"], coordinate["source_char_start"])
                < min(unit["occurrence"]["end_char"], coordinate["source_char_end"])]
        assert overlapping_units
        span_rows.append(dict(physical_identity_sha256=hashlib.sha256(_physical_wire(physical)).hexdigest(),
            row_sha256=row["row_sha256"], source_coordinate_span_index=index,
            unit_ids=overlapping_units))

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
        version_key = ("version", unit_document_ordinals[index])
        if version_key not in node_ids:
            node(version_key, "source_version", unit["source_version"]["record_cid"])
        node(("occurrence", index), "occurrence", unit["occurrence"]["record_cid"])
        node(("expression", index), "expression", identity + ":complete-IR")
        node(("assertion", index), "definition_assertion" if index == 0 else "norm_assertion", identity)
    node("term", "term_sense", units[0]["unit_id"] + ":CoveredOfficer")
    for index in range(len(units)):
        node(("cross-reference", index), "expression",
             "fixture:reviewed-" + namespace + ":cross-reference:" + str(index))
    for index in range(len(units)):
        edge(("version", unit_document_ordinals[index]), ("occurrence", index), "CONTAINS")
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
            document_revision=instrument + "/revision-1",
            input_document_ordinal=unit_document_ordinals[index],
            law_row_ordinal=unit_document_ordinals[index]) for index, unit in enumerate(units)],
        span_rows=span_rows, entity_rows=bindings)
    return dict(namespace=namespace, instrument=instrument, texts=texts, units=units,
        laws=laws, law_bytes=law_bytes, law_path=law_path, capture=capture, datasets=datasets,
        coordinate_report=coordinates, coordinate_pin=coordinate_pin, paired_location=location,
        paired_written=written, retained=retained, original_payload=original_payload,
        entity_bytes=entity_bytes, entity_path=entity_path, entity_rows=entity_rows, mapping=mapping,
        source_bindings=source_bindings, unit_document_ordinals=unit_document_ordinals,
        law_texts=law_texts)


def _physical_closure_request(material, *, map_damage=None, reviewed_version=2, return_control=False):
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
        source_texts=material["texts"], source_bindings=material.get("source_bindings"),
        cross_references=references, dependency_artifacts={map_id: map_raw})
    assert type(reviewed_version) is int and reviewed_version in (2, 3)
    if reviewed_version == 2:
        control = shared_fixture.reviewed_preservation_graph_fixture_v2(fixture, admission, case)
        control["preparation"] = shared_fixture.reviewed_preservation_prepare_fixture_v2(control)
    else:
        from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission_v3
        from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graphs
        from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as mixed_fixture
        case["declaration"]["schema"] = admission_v3.REVIEWED_DECLARATION_SCHEMA
        for unit in case["declaration"]["units"]:
            unit["relational_profile"] = mixed_fixture.relational.PROFILE
        mixed_fixture.set_mixed_ir(case)
        case["preparation"] = mixed_fixture.prepare(admission_v3, case)
        mixed_fixture.refresh_signed_reviews(case, admission_v3)
        mixed_fixture.assert_signatures_valid(case)
        args, kwargs = fixture.reviewed_assessment_arguments_v2(admission_v3, case)
        admitted = admission_v3.assess_reviewed_norm_admission_v3(*args, **kwargs)
        assert admitted["semantic_use_eligible"] is True and admitted["fixture_only"] is True
        admission_sha = admission_v3.norm_content_adjudication_sha256(admitted)
        graph = graphs.build_reviewed_norm_graph_v3(admitted, *args,
            expected_admission_sha256=admission_sha, **kwargs)
        assert graphs.validate_reviewed_norm_graph_v3(graph, admitted, *args,
            expected_admission_sha256=admission_sha,
            expected_graph_sha256=graphs.norm_definition_graph_sha256(graph), **kwargs) == graph
        control = dict(helper=fixture, mixed_helper=mixed_fixture, owner=admission_v3,
            case=case, args=args, kwargs=kwargs, admission=admitted, graph=graph,
            admission_sha=admission_sha, graph_sha=graphs.norm_definition_graph_sha256(graph),
            shared=shared_fixture.shared)
        control["preparation"] = shared_fixture.reviewed_preservation_prepare_fixture_v3(control)
        assert shared_fixture.reviewed_preservation_validate_fixture_v3(control) == control["preparation"]

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
    request = dict(schema="legal-uscode-release-closure-request/v2",
        profile="reviewed-norm-v2-physical-three-cache-replay/v1",
        datasets=material["datasets"], expected_artifact_ids=[row["artifact_id"] for row in artifacts],
        artifacts=artifacts, expected_unit_ids=[unit["unit_id"] for unit in case["declaration"]["units"]],
        component=component, pins=dict(admission=control["admission_sha"], graph=control["graph_sha"],
            preservation=shared_fixture.shared.reviewed_preservation_corpus_sha256(control["preparation"]),
            reviewed_crosswalk=map_pin), native=None,
        physical_inputs=dict(law_path=str(material["law_path"]), entity_path=str(material["entity_path"])))
    if reviewed_version == 3:
        request.update(schema="legal-uscode-release-closure-request/v3",
            profile="reviewed-norm-v3-physical-three-cache-replay/v1")
    return (request, control) if return_control else request


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


# V3 successors use the same physical owners and independently signed fiction.
# Authored compiler observations exercise contracts, never actual Lean/parent proof.
@pytest.fixture(scope="module")
def physical_closure_material_v3(tmp_path_factory):
    texts = [
        "For this fictional Act, a covered officer means an officer appointed by the Board. Café.",
        "Every covered officer must file a report unless the Board expressly excuses that officer.",
        "For every officer, supervisor, event, and time, if both people are covered officers, that officer may inspect the register under that supervisor at that event and time.",
    ]
    return _physical_source_material(tmp_path_factory.mktemp("mixed-physical-crosswalk") / "material", source_texts=texts)


@pytest.fixture(scope="module")
def physical_closure_control_v3(physical_closure_material_v3):
    return _physical_closure_request(physical_closure_material_v3, reviewed_version=3, return_control=True)


def replay_physical_closure_v3(request):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport
    raw = transport.encode_parent_replay_value_v1(request, max_bytes=release.MAX_CLOSURE_REQUEST_BYTES)
    return release.validate_uscode_release_closure_v3(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


def assert_release_v3_byte_authority_only(report):
    assert report["local_replay_complete"] is True
    for key in ("release_ready", "closure_complete", "admitted", "formalized", "proof_verified",
        "source_semantics_verified", "source_authenticity_verified", "source_metadata_arrow_bytes_verified",
        "original_native_parent_custody_verified", "remote_readback_verified", "model_or_compiler_execution_performed",
        "original_parent_handle_consumed", "native_receipt_authenticated", "release_eligible",
        "statutory_meaning_proved", "gold_verified", "original_success_authenticated",
        "source_kernel_receipt_authenticated"):
        assert report[key] is False, key
    for key in ("admission_mask", "release_mask", "gold_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0
    assert "original_admitted_native_parent_custody_not_established" in report["blockers"]
    assert "immutable_remote_Hub_readback_not_established" in report["blockers"]
    assert "statutory_meaning_and_full_corpus_qualification_not_established" in report["blockers"]


def test_mixed_physical_closure_v3_replays_complete_signed_three_cache_component(physical_closure_control_v3):
    request, control = physical_closure_control_v3
    report = replay_physical_closure_v3(request)
    assert_release_v3_byte_authority_only(report)
    assert report["schema"] == "legal-uscode-release-closure-report/v3"
    assert report["profile"] == "reviewed-norm-v3-physical-three-cache-replay/v1"
    manifest = control["preparation"].to_dict()
    assert report["signature_headers_by_unit"] == manifest["signature_headers_by_unit"]
    assert report["predicate_compatibility_ledger"] == manifest["predicate_compatibility_ledger"]
    assert report["definition_use_record_cids"] == manifest["definition_use_record_cids"]
    assert report["unit_preservation_bindings"] == manifest["units"]
    assert len(report["unit_ids"]) == len(manifest["units"]) == 3
    graph = control["graph"]["graph"]
    physical = report["physical_crosswalk"]
    assert physical["counts"]["graph_nodes"] == len(graph["nodes"])
    assert physical["counts"]["graph_edges"] == len(graph["edges"])
    assert {row["graph_record_cid"] for row in physical["entity_bindings"]} == {
        row["record_cid"] for row in graph["nodes"] + graph["edges"]}
    assert report["native_receipt_replayed"] is False and report["native_packet_transport"] is None


@pytest.mark.parametrize("damage", ["law_row_alias", "source_version_alias", "document_alias", "document_revision",
    "span_missing", "span_duplicate", "span_wrong_overlap", "entity_node_alias", "entity_endpoint", "entity_missing",
    "entity_row_digest", "dataset_revision"])
def test_mixed_physical_closure_v3_refuses_signed_crosswalk_damage(physical_closure_material_v3, damage):
    request = _physical_closure_request(physical_closure_material_v3, reviewed_version=3, map_damage=damage)
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)


@pytest.mark.parametrize("damage", ["unicode_geometry", "governing_scope", "review_revoked", "IR", "graph", "source"])
def test_mixed_physical_closure_v3_replays_original_current_subject(physical_closure_control_v3, damage):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from ipfs_datasets_py.logic.autoformal import legal_graph_review as reviews
    request = deepcopy(physical_closure_control_v3[0])
    replay_row = next(row for row in request["artifacts"] if row["artifact_id"] == request["component"]["replay"])
    replay = wire.decode_parent_replay_value_v1(replay_row["payload"], expected_payload_sha256=replay_row["sha256"])
    inputs = replay["admission_kwargs"]["preparation_inputs"]
    if damage == "unicode_geometry":
        occurrence = inputs["declaration"]["units"][0]["occurrence"]
        assert occurrence["end_utf8"] > occurrence["end_char"]
        occurrence["end_utf8"] = occurrence["end_char"]
    elif damage == "governing_scope":
        inputs["declaration"]["governing_context"]["governing_edition"] += ":other"
    elif damage == "review_revoked":
        registry = replay["admission_args"][1]
        registry["keys"][0]["revoked_at_utc"] = replay["admission_kwargs"]["at_time_utc"]
        replay["admission_kwargs"]["expected_registry_sha256"] = reviews.digest(registry)
    elif damage == "IR":
        unit = inputs["declaration"]["units"][-1]
        inputs["relational_inputs"][unit["unit_id"]]["request_raw"] += b" "
    elif damage == "source":
        unit = inputs["declaration"]["units"][-1]
        inputs["source_inputs"][unit["unit_id"]]["extracted_text"] += " changed"
    else:
        row = next(row for row in request["artifacts"] if row["artifact_id"] == request["component"]["graph"])
        value = json.loads(row["payload"]);value["graph"]["edges"].pop()
        raw = _physical_wire(value)
        row.update(payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    raw = wire.encode_parent_replay_value_v1(replay)
    replay_row.update(payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)


@pytest.mark.parametrize("legacy", [1, 2])
def test_mixed_physical_closure_v3_never_retags_legacy_request(physical_closure_control_v3, legacy):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    raw = wire.encode_parent_replay_value_v1(physical_closure_control_v3[0])
    validator = release.validate_uscode_release_closure_v1 if legacy == 1 else release.validate_uscode_release_closure_v2
    with pytest.raises(ValueError):
        validator(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.fixture(scope="module")
def authored_packet_transport_v3():
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    # Eighty-three fictional named file bytes exercise a four-chunk whole wire.
    # This is NOT the retained 3,974,918-byte actual compiler packet.
    packet = [["authored-file-" + str(i), (str(i) + ":").encode() + b"x" * 47_800] for i in range(83)]
    raw = wire.encode_parent_replay_value_v1(packet, max_bytes=release.MAX_CLOSURE_REQUEST_BYTES)
    prepared = release.prepare_reviewed_native_packet_transport_v3(raw, artifact_id_prefix="fixture:complete83")
    return raw, packet, prepared


def transport_boundary_v3(prepared, *, mutate=None):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    value = deepcopy(prepared)
    receipt = dict(artifact_id="fixture:transport-receipt", family="native_receipt",
        payload=b'{"transport_only":true}', bytes=23, sha256=hashlib.sha256(b'{"transport_only":true}').hexdigest())
    assert receipt["bytes"] == len(receipt["payload"])
    rows = [receipt, value["index"], *value["chunks"]]
    selection = dict(receipt=receipt["artifact_id"], packet_index=value["index"]["artifact_id"],
        expected_packet_sha256="a" * 64, expected_binary_sha256={}, observation_profile="fictional-authored-observation/v1")
    required = {"fixture:original-role"}
    if mutate:
        mutate(value, rows, selection, required)
    materials = {row["artifact_id"]: row for row in rows}
    result = release._release_native_packet_v3(selection, materials, required, contracts, wire)
    return result, required, rows


def test_native_packet_v3_publishes_and_reassembles_all_four_chunks(authored_packet_transport_v3, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    raw, packet, prepared = authored_packet_transport_v3
    assert len(prepared["chunks"]) == 4
    assert all(0 < row["bytes"] <= 1_000_000 for row in [prepared["index"], *prepared["chunks"]])
    refs = [release.publish_referenced_artifact(tmp_path, "packet/" + str(i), row["payload"], "candidate")
        for i, row in enumerate([prepared["index"], *prepared["chunks"]])]
    sealed = release.seal_coordinator_receipt(tmp_path, refs)
    assert sealed["remote_upload_executed"] is sealed["hub_readback_executed"] is False
    persisted = dict(prepared)
    persisted["index"] = dict(prepared["index"], payload=(tmp_path / "packet/0").read_bytes())
    persisted["chunks"] = [dict(row, payload=(tmp_path / ("packet/" + str(i + 1))).read_bytes())
        for i, row in enumerate(prepared["chunks"])]
    (receipt, decoded, observation), required, rows = transport_boundary_v3(persisted)
    assert decoded == packet and wire.encode_parent_replay_value_v1(decoded, max_bytes=8 * 1024**2) == raw
    assert observation["complete_wire_bytes"] == len(raw)
    assert observation["complete_wire_sha256"] == hashlib.sha256(raw).hexdigest()
    assert observation["complete_packet_file_count"] == 83 and observation["parent_or_release_authority"] is False
    assert {row["artifact_id"] for row in rows} <= required


@pytest.mark.parametrize("damage", ["index_schema", "index_profile", "codec", "wire_sha", "wire_length", "wire_bool",
    "ordinal", "ordinal_bool", "gap", "overlap", "chunk_bytes", "chunk_bool", "chunk_sha", "chunk_body", "reorder",
    "missing", "duplicate_id", "extra", "family", "role_alias", "unused_index", "observation", "parent_handle"])
def test_native_packet_v3_rejects_incomplete_reordered_aliased_and_resealed_transport(authored_packet_transport_v3, damage):
    def mutate(value, rows, selection, required):
        index = json.loads(value["index"]["payload"])
        first = index["chunks"][0]
        if damage in ("index_schema", "index_profile", "codec", "wire_sha", "wire_length", "wire_bool"):
            key = {"index_schema":"schema", "index_profile":"profile", "codec":"codec", "wire_sha":"wire_sha256",
                "wire_length":"wire_bytes", "wire_bool":"wire_bytes"}[damage]
            index[key] = True if damage == "wire_bool" else (index[key] + 1 if damage == "wire_length" else "wrong")
        elif damage == "ordinal": first["ordinal"] = 1
        elif damage == "ordinal_bool": first["ordinal"] = False
        elif damage == "gap": first["offset"] = 1
        elif damage == "overlap": index["chunks"][1]["offset"] -= 1
        elif damage == "chunk_bytes": first["bytes"] -= 1
        elif damage == "chunk_bool": first["bytes"] = True
        elif damage == "chunk_sha": first["sha256"] = "0" * 64
        elif damage == "chunk_body": rows[2]["payload"] = b"y" * rows[2]["bytes"]
        elif damage == "reorder": rows[2], rows[3] = rows[3], rows[2]
        elif damage == "missing": rows.pop()
        elif damage == "duplicate_id": index["chunks"][1]["artifact_id"] = first["artifact_id"]
        elif damage == "extra": rows.append(dict(rows[-1], artifact_id="fixture:extra-chunk"))
        elif damage == "family": rows[2]["family"] = "native_packet"
        elif damage == "role_alias": required.add(first["artifact_id"])
        elif damage == "unused_index": selection["packet_index"] = "fixture:missing-index"
        elif damage == "observation": selection["observation_profile"] = "verified-by-JSON"
        else: selection["original_parent_handle"] = {"verified":True}
        raw = _physical_wire(index)
        value["index"].update(payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        transport_boundary_v3(authored_packet_transport_v3[2], mutate=mutate)


@pytest.mark.parametrize("damage", ["artifact_limit", "request_limit", "schema", "profile", "codec"])
def test_native_packet_v3_literal_policy_cannot_be_widened_or_retagged(authored_packet_transport_v3, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    name = {"artifact_limit":"_MAX_ARTIFACT_BYTES", "request_limit":"MAX_CLOSURE_REQUEST_BYTES",
        "schema":"NATIVE_PACKET_INDEX_SCHEMA_V3", "profile":"CLOSURE_PROFILE_V3", "codec":"NATIVE_PACKET_CODEC_V3"}[damage]
    monkeypatch.setattr(release, name, 99_000_000 if damage.endswith("limit") else "wrong")
    with pytest.raises(ValueError):
        release.prepare_reviewed_native_packet_transport_v3(authored_packet_transport_v3[0], artifact_id_prefix="fixture:wrong")


@pytest.fixture(scope="module")
def authored_physical_native_v3(physical_closure_control_v3, tmp_path_factory):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from tests.unit.logic.autoformal import test_legal_corpus_definition_use_native_v2 as fixture
    request, control = physical_closure_control_v3
    tmp_path = tmp_path_factory.mktemp("matching-physical-native-v3")
    monkeypatch = pytest.MonkeyPatch()
    install = fixture.synthetic_compiler.__wrapped__(monkeypatch, tmp_path)
    def complete_outputs(outputs, compiled, sources):
        for i, path in enumerate(compiled):
            outputs[path] = b"fictional olean; no real proof:" + str(i).encode() + b"q" * 220_000
    executable, calls = install(control["preparation"], output_edit=complete_outputs,
        stdout=fixture.reviewed_native_stdout_v2(control["preparation"]))
    output = tmp_path / "authored-matching-physical-packet"
    try:
        receipt = fixture.reviewed_native_build_v3(control, executable, output)
    finally:
        monkeypatch.undo()
    assert len(calls) == 1 and receipt["build_passed"] is True
    native = fixture.native
    packet = tuple(sorted((path.relative_to(output).as_posix(), path.read_bytes())
        for path in output.rglob("*") if path.is_file()))
    assert len(packet) == 83
    packet_raw = wire.encode_parent_replay_value_v1([list(row) for row in packet], max_bytes=8 * 1024**2)
    prepared = release.prepare_reviewed_native_packet_transport_v3(packet_raw, artifact_id_prefix="fixture:physical-native")
    result = deepcopy(request)
    receipt_raw = native.reviewed_norm_preservation_receipt_bytes_v3(receipt)
    result["artifacts"].extend([dict(artifact_id="fixture:physical-native-receipt", family="native_receipt",
        payload=receipt_raw, bytes=len(receipt_raw), sha256=hashlib.sha256(receipt_raw).hexdigest()),
        prepared["index"], *prepared["chunks"]])
    result["expected_artifact_ids"] = [row["artifact_id"] for row in result["artifacts"]]
    result["native"] = dict(receipt="fixture:physical-native-receipt", packet_index=prepared["index"]["artifact_id"],
        expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
        expected_binary_sha256=receipt["binary_sha256"], observation_profile="fictional-authored-observation/v1")
    # Measure COMPLETE encoded request independently, before the production8MiB gate.
    full_wire = wire.encode_parent_replay_value_v1(result, max_bytes=64 * 1024**2)
    (tmp_path / "complete-authored-physical-request.wire").write_bytes(full_wire)
    (tmp_path / "complete-authored-physical-request-size.json").write_bytes(_physical_wire(dict(
        bytes=len(full_wire), sha256=hashlib.sha256(full_wire).hexdigest(), packet_bytes=len(packet_raw),
        artifacts=len(result["artifacts"]), all_files_retained=True, original_parent_authority=False)))
    assert len(full_wire) <= 8 * 1024**2 and len(result["artifacts"]) <= 64
    return result, control, receipt, packet, full_wire


def test_mixed_physical_native_v3_replays_matching_complete_authored_packet_without_authority(authored_physical_native_v3):
    request, control, receipt, packet, full_wire = authored_physical_native_v3
    report = replay_physical_closure_v3(request)
    assert_release_v3_byte_authority_only(report)
    assert report["native_receipt_replayed"] is True
    assert report["native_packet_transport"]["complete_packet_file_count"] == len(packet) == 83
    assert report["native_packet_transport"]["logical_packet_inventory_sha256"] == request["native"]["expected_packet_sha256"]
    assert report["admission_sha256"] == control["admission_sha"]


@pytest.mark.parametrize("damage", ["subject", "inventory", "binary", "actual_observation", "receipt", "unreferenced",
    "true_authority", "parent_handle", "oversize_artifact", "too_many_artifacts", "oversize_whole_request"])
def test_mixed_physical_native_v3_refuses_subject_and_transport_authority_substitution(authored_physical_native_v3, damage):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    request = deepcopy(authored_physical_native_v3[0])
    if damage == "subject":
        row = next(row for row in request["artifacts"] if row["artifact_id"] == request["native"]["receipt"])
        value = json.loads(row["payload"])
        value["reviewed_admission_sha256"] = "0" * 64
        raw = _physical_wire(value);row.update(payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    elif damage == "inventory": request["native"]["expected_packet_sha256"] = "0" * 64
    elif damage == "binary": request["native"]["expected_binary_sha256"] = {}
    elif damage == "actual_observation": request["native"]["observation_profile"] = "retained-native-observation/v1"
    elif damage == "receipt":
        row = next(row for row in request["artifacts"] if row["artifact_id"] == request["native"]["receipt"])
        row["payload"] += b" "
        row.update(bytes=len(row["payload"]), sha256=hashlib.sha256(row["payload"]).hexdigest())
    elif damage == "true_authority": request["release_ready"] = True
    elif damage == "parent_handle": request["native"]["original_parent_handle"] = {"verified":True}
    else:
        raw = b"x" * (1_000_001 if damage == "oversize_artifact" else 900_000 if damage == "oversize_whole_request" else 1)
        count = 65 if damage == "too_many_artifacts" else 10 if damage == "oversize_whole_request" else 1
        for i in range(count):
            request["artifacts"].append(dict(artifact_id="fixture:unreferenced:" + str(i), family="native_packet_chunk",
                payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        request["expected_artifact_ids"] = [row["artifact_id"] for row in request["artifacts"]]
    raw = wire.encode_parent_replay_value_v1(request, max_bytes=64 * 1024**2)
    with pytest.raises(ValueError):
        release.validate_uscode_release_closure_v3(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("direct", [False, True])
def test_mixed_physical_closure_v3_explicit_cli_preserves_default_domain(physical_closure_control_v3, tmp_path, direct):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    request = physical_closure_control_v3[0]
    raw = wire.encode_parent_replay_value_v1(request, max_bytes=8 * 1024**2)
    path = tmp_path / "mixed.request";path.write_bytes(raw)
    args = ["validate-closure", "--request", str(path), "--request-sha256", hashlib.sha256(raw).hexdigest()]
    result, refused = run_cli(args, cwd=tmp_path, direct=direct)
    assert result.returncode != 0 and refused["status"] == "error"
    result, accepted = run_cli(args + ["--profile", "reviewed-norm-v3-physical-three-cache-replay/v1"], cwd=tmp_path, direct=direct)
    assert result.returncode == 0 and accepted["status"] == "success"
    assert_release_v3_byte_authority_only(accepted["closure"])


def test_mixed_physical_closure_v3_refuses_independently_valid_foreign_review_packet(
        physical_closure_control_v3, tmp_path_factory, monkeypatch, tmp_path):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from tests.unit.logic.autoformal import test_legal_corpus_definition_use_native_v2 as fixture
    # Genuine different fictional review, with all original signatures/current
    # source/IR/graph/preparation replayed before its authored tool boundary.
    seed = fixture.reviewed_native_seed_v3.__wrapped__(tmp_path_factory)
    foreign = fixture.reviewed_native_control_v3.__wrapped__(seed)
    assert foreign["admission_sha"] != physical_closure_control_v3[1]["admission_sha"]
    install = fixture.synthetic_compiler.__wrapped__(monkeypatch, tmp_path)
    executable, calls = install(foreign["preparation"], stdout=fixture.reviewed_native_stdout_v2(foreign["preparation"]))
    output = tmp_path / "genuine-foreign-subject"
    receipt = fixture.reviewed_native_build_v3(foreign, executable, output)
    packet = tuple(sorted((path.relative_to(output).as_posix(), path.read_bytes())
        for path in output.rglob("*") if path.is_file()))
    own_replay = fixture.reviewed_native_reopen_v3(foreign, receipt, packet)
    assert own_replay["original_success_authenticated"] is False
    assert own_replay["retained_observations_consistent"] is True
    request = deepcopy(physical_closure_control_v3[0])
    raw = wire.encode_parent_replay_value_v1([list(row) for row in packet], max_bytes=8 * 1024**2)
    prepared = release.prepare_reviewed_native_packet_transport_v3(raw, artifact_id_prefix="fixture:foreign-native")
    receipt_raw = fixture.native.reviewed_norm_preservation_receipt_bytes_v3(receipt)
    request["artifacts"].extend([dict(artifact_id="fixture:foreign-receipt", family="native_receipt",
        payload=receipt_raw, bytes=len(receipt_raw), sha256=hashlib.sha256(receipt_raw).hexdigest()),
        prepared["index"], *prepared["chunks"]])
    request["expected_artifact_ids"] = [row["artifact_id"] for row in request["artifacts"]]
    request["native"] = dict(receipt="fixture:foreign-receipt", packet_index=prepared["index"]["artifact_id"],
        expected_packet_sha256=fixture.native.reviewed_norm_preservation_packet_sha256_v3(packet),
        expected_binary_sha256=receipt["binary_sha256"], observation_profile="fictional-authored-observation/v1")
    with pytest.raises(ValueError, match="retained receipt differs from current whole reviewed semantics or producers"):
        replay_physical_closure_v3(request)


@pytest.mark.parametrize("damage", ["empty", "mapping", "file_pair", "bytes_type", "noncanonical", "over_budget"])
def test_native_packet_transport_v3_refuses_nonpacket_or_oversize_wire_before_publication(damage):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    value = [] if damage == "empty" else {} if damage == "mapping" else [["file", "not-bytes"]] if damage == "file_pair" else [["file", b"source"]]
    raw = wire.encode_parent_replay_value_v1(value)
    if damage == "bytes_type": raw = bytearray(raw)
    elif damage == "noncanonical": raw += b" "
    elif damage == "over_budget": raw = b"x" * (8 * 1024**2 + 1)
    with pytest.raises(ValueError):
        release.prepare_reviewed_native_packet_transport_v3(raw, artifact_id_prefix="fixture:invalid")


@pytest.mark.parametrize("damage", ["profile", "core_callback"])
def test_mixed_physical_closure_v3_closes_original_policy_and_callback_generation(
        physical_closure_control_v3, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as entity
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    original = entity.iter_observed_rows
    observed = []
    def genuine_rows_then_mutate(*args, **kwargs):
        for row in original(*args, **kwargs):
            observed.append(row)
            yield row
        if damage == "profile":
            monkeypatch.setattr(release, "CLOSURE_PROFILE_V3", "retagged/v2")
        else:
            monkeypatch.setattr(release, "_validate_uscode_release_byte_closure_v3", lambda *a, **k: {})
    monkeypatch.setattr(entity, "iter_observed_rows", genuine_rows_then_mutate)
    with pytest.raises(ValueError):
        replay_physical_closure_v3(physical_closure_control_v3[0])
    assert observed


@pytest.mark.parametrize("damage", ["code", "defaults", "keyword_defaults"])
def test_mixed_byte_closure_v3_refuses_same_function_state_drift_after_genuine_prepare(
        physical_closure_control_v3, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
    target = native.validate_reviewed_norm_preservation_native_receipt_v3
    original = native.validate_reviewed_norm_preservation_native_v3
    changed = []
    def genuine_prepare_then_mutate(*args, **kwargs):
        prepared = original(*args, **kwargs)
        if damage == "code":
            def altered(*args, **kwargs): return {}
            monkeypatch.setattr(target, "__code__", altered.__code__)
        elif damage == "defaults":
            monkeypatch.setattr(target, "__defaults__", (None,))
        else:
            assert type(target.__kwdefaults__) is dict and "observation_profile" in target.__kwdefaults__
            monkeypatch.setitem(target.__kwdefaults__, "observation_profile", "different-default/v1")
        changed.append(target)
        return prepared
    monkeypatch.setattr(native, "validate_reviewed_norm_preservation_native_v3", genuine_prepare_then_mutate)
    with pytest.raises(ValueError, match="V3 callback function/code/default/keyword-default generation changed"):
        replay_physical_closure_v3(physical_closure_control_v3[0])
    assert changed == [target] and native.validate_reviewed_norm_preservation_native_receipt_v3 is target


@pytest.mark.parametrize("damage", ["code", "defaults", "keyword_defaults"])
def test_mixed_physical_closure_v3_refuses_same_core_function_state_drift_after_real_rows(
        physical_closure_control_v3, monkeypatch, damage):
    from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as entity
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    target = release._validate_uscode_release_byte_closure_v3
    original = entity.iter_observed_rows
    observed = []
    def genuine_rows_then_mutate(*args, **kwargs):
        for row in original(*args, **kwargs):
            observed.append(row)
            yield row
        if damage == "code":
            def altered(*args, **kwargs): return {}
            monkeypatch.setattr(target, "__code__", altered.__code__)
        elif damage == "defaults":
            monkeypatch.setattr(target, "__defaults__", (None,))
        else:
            monkeypatch.setattr(target, "__kwdefaults__", {"expected_request_sha256": "0" * 64})
    monkeypatch.setattr(entity, "iter_observed_rows", genuine_rows_then_mutate)
    with pytest.raises(ValueError, match="V3 callback function/code/default/keyword-default generation changed"):
        replay_physical_closure_v3(physical_closure_control_v3[0])
    assert observed and release._validate_uscode_release_byte_closure_v3 is target


@pytest.mark.parametrize("family", ["admission", "graph"])
@pytest.mark.parametrize("damage", ["duplicate_key", "nonfinite", "too_deep", "noncanonical"])
def test_mixed_physical_closure_v3_rejects_malformed_complete_legal_json(
        physical_closure_control_v3, family, damage):
    from copy import deepcopy
    request = deepcopy(physical_closure_control_v3[0])
    identity = request["component"][family]
    row = next(row for row in request["artifacts"] if row["artifact_id"] == identity)
    if damage == "duplicate_key":
        raw = b'{"same":0,"same":1}'
    elif damage == "nonfinite":
        raw = b'{"value":NaN}'
    elif damage == "too_deep":
        # The existing norm correspondence profile bounds JSON depth at96.
        value = None
        for _ in range(97):
            value = [value]
        raw = _physical_wire(value)
    else:
        raw = row["payload"] + b" "
    row.update(payload=raw,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    # Updated outer byte descriptors cannot replace independent subject pins.
    with pytest.raises(ValueError):
        replay_physical_closure_v3(request)


# Fictional shared-row integration: the complete law row and all emitted cache
# bytes are frozen before the mapping is added to the genuinely signed review.
@pytest.fixture(scope="module")
def shared_lawrow_physical_control_v3(tmp_path_factory):
    texts = [
        "For this fictional Act, a covered officer means an officer appointed by the Board. Café.",
        "Every\u00a0covered officer must file a report unless the Board expressly excuses that officer.",
        "For every officer, supervisor, event, and time, if both people are covered officers, that officer may inspect the register under that supervisor at that event and time.",
    ]
    material = _physical_source_material(
        tmp_path_factory.mktemp("shared-lawrow-v3") / "material",
        source_texts=texts, shared_normative_row=True)
    request, control = _physical_closure_request(material, reviewed_version=3, return_control=True)
    return request, control, material


def test_shared_lawrow_v3_replays_two_rows_three_units_and_complete_caches(
        shared_lawrow_physical_control_v3):
    request, control, material = shared_lawrow_physical_control_v3
    report = replay_physical_closure_v3(request)
    assert_release_v3_byte_authority_only(report)
    units = control["case"]["declaration"]["units"]
    definition, duty, permission = units
    source_inputs = control["case"]["source_inputs"]
    shared = material["law_texts"][1]
    assert material["capture"]["documents"][1]["text"] == shared
    assert "\u00a0" in shared  # Meaning-preserving whitespace, not an extra IR clause.
    assert len(material["laws"]) == len(material["capture"]["documents"]) == 2
    assert len(units) == len(report["unit_ids"]) == 3
    assert material["unit_document_ordinals"] == [0, 1, 1]
    assert duty["source_version"] == permission["source_version"]
    assert duty["source_version"]["record_cid"] != definition["source_version"]["record_cid"]
    assert duty["source_artifact_id"] != permission["source_artifact_id"]
    assert duty["ir_artifact_id"] != permission["ir_artifact_id"]
    assert duty["relational_request_sha256"] != permission["relational_request_sha256"]
    for unit in (duty, permission):
        value = source_inputs[unit["unit_id"]]
        assert value == {"raw_bytes": shared.encode("utf-8"), "extracted_text": shared}
        occurrence = unit["occurrence"]
        assert occurrence["span_text"] == shared[occurrence["start_char"]:occurrence["end_char"]]
        assert occurrence["start_utf8"] == len(shared[:occurrence["start_char"]].encode("utf-8"))
        assert occurrence["end_utf8"] == len(shared[:occurrence["end_char"]].encode("utf-8"))
    assert duty["occurrence"]["end_char"] + 2 == permission["occurrence"]["start_char"]
    assert permission["occurrence"]["start_utf8"] > permission["occurrence"]["start_char"]
    physical = report["physical_crosswalk"]
    assert physical["counts"]["law_rows"] == 2 and physical["counts"]["reviewed_units"] == 3
    assert [row["input_document_ordinal"] for row in physical["unit_bindings"]] == [0, 1, 1]
    assert [row["law_row_ordinal"] for row in physical["unit_bindings"]] == [0, 1, 1]
    graph = control["graph"]["graph"]
    assert len([node for node in graph["nodes"] if node["node_type"] == "source_version"]) == 2
    assert len(control["graph"]["source_versions"]) == 3
    assert {row["graph_record_cid"] for row in physical["entity_bindings"]} == {
        row["record_cid"] for row in graph["nodes"] + graph["edges"]}
    assert len(physical["entity_bindings"]) == len(material["entity_rows"])
    assert len(physical["span_bindings"]) == len(material["original_payload"]["rows"])
    for binding in physical["span_bindings"]:
        span = material["coordinate_report"]["spans"][binding["source_coordinate_span_index"]]
        expected = [unit["unit_id"] for index, unit in enumerate(units)
            if material["unit_document_ordinals"][index] == span["input_document_ordinal"]
            and max(unit["occurrence"]["start_char"], span["source_char_start"])
                < min(unit["occurrence"]["end_char"], span["source_char_end"])]
        assert binding["unit_ids"] == expected
    preserved = control["preparation"].to_dict()
    assert len(preserved["units"]) == 3
    assert report["unit_preservation_bindings"] == preserved["units"]
    assert report["native_receipt_replayed"] is False
    assert report["local_source_cache_entity_bindings_verified"] is True
    assert report["independent_reviewed_crosswalk_verified"] is True


@pytest.mark.parametrize("damage,reason", [
    ("duplicate", "physical occurrence"),
    ("overlap", "overlapping interpretations"),
])
def test_shared_lawrow_v3_original_source_replay_refuses_duplicate_or_overlapping_uses(
        shared_lawrow_physical_control_v3, damage, reason):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import corpus_source as source
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as transport

    original, control, material = shared_lawrow_physical_control_v3
    request = deepcopy(original)
    row = next(row for row in request["artifacts"]
        if row["artifact_id"] == request["component"]["replay"])
    replay = transport.decode_parent_replay_value_v1(row["payload"],
        expected_payload_sha256=row["sha256"], max_bytes=8 * 1024**2)
    inputs = replay["admission_kwargs"]["preparation_inputs"]
    duty, permission = inputs["declaration"]["units"][1:]
    current = permission["occurrence"]
    complete = inputs["source_inputs"][permission["unit_id"]]
    start = duty["occurrence"]["start_char"] if damage == "duplicate" else duty["occurrence"]["end_char"] - 1
    end = duty["occurrence"]["end_char"] if damage == "duplicate" else current["end_char"]
    text = complete["extracted_text"]
    occurrence = source.build_source_occurrence(permission["source_version"],
        expected_raw_sha256=hashlib.sha256(complete["raw_bytes"]).hexdigest(),
        extracted_text=text, expected_extracted_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        start_char=start, end_char=end, start_utf8=len(text[:start].encode("utf-8")),
        end_utf8=len(text[:end].encode("utf-8")))
    permission["occurrence"] = occurrence
    permission["coverage"] = [{"typed_path": mapped["typed_path"],
        **{key: occurrence[key] for key in ("start_char", "end_char", "start_utf8", "end_utf8")}}
        for mapped in inputs["relational_inputs"][permission["unit_id"]]["report"]["structural_mapping"]]
    for use in inputs["declaration"]["definition_uses"]:
        if use["use_unit_id"] == permission["unit_id"]:
            use["use_occurrence_cid"] = occurrence["record_cid"]
    inputs["expected_declaration_sha256"] = admission.norm_content_adjudication_sha256(inputs["declaration"])
    raw = transport.encode_parent_replay_value_v1(replay, max_bytes=8 * 1024**2)
    row.update(payload=raw, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    # Retain the genuine positive's final map, detached signatures and report
    # pins. No new accepted subject or fabricated review authorizes the bad uses.
    assert request["pins"] == original["pins"]
    mapping = request["component"]["reviewed_crosswalk"]
    assert next(r for r in request["artifacts"] if r["artifact_id"] == mapping) == next(
        r for r in original["artifacts"] if r["artifact_id"] == mapping)
    with pytest.raises(ValueError, match=reason):
        replay_physical_closure_v3(request)


# An A-issued capability is never constructed by these software controls.
# The actual same-thread original-parent consumer below is a separate explicit
# controller handoff; ordinary pytest cannot turn a dict/callback into success.
def test_original_parent_v3_omitted_and_explicit_none_keep_retained_default_exact(
        authored_physical_native_v3, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    request, _, _, _, raw = authored_physical_native_v3
    def forbidden(*args, **kwargs):
        pytest.fail("retained default tried to resolve an original parent owner")
    monkeypatch.setattr(release, "_release_original_parent_context_v3", forbidden)
    digest = hashlib.sha256(raw).hexdigest()
    omitted = release.validate_uscode_release_closure_v3(raw, expected_request_sha256=digest)
    explicit_none = release.validate_uscode_release_closure_v3(raw,
        expected_request_sha256=digest, original_parent_handle=None)
    assert omitted == explicit_none
    assert_release_v3_byte_authority_only(omitted)
    assert omitted["profile"] == "reviewed-norm-v3-physical-three-cache-replay/v1"
    assert "original_parent_evidence" not in omitted
    assert omitted["native_packet_transport"]["logical_packet_inventory_sha256"] == request["native"]["expected_packet_sha256"]


@pytest.mark.parametrize("offered", ["object", "mapping", "boolean", "json", "unissued"])
def test_original_parent_v3_rejects_unissued_before_wire_or_physical_replay(monkeypatch, offered):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    if offered == "object": value = object()
    elif offered == "mapping": value = {"original_success_authenticated": True}
    elif offered == "boolean": value = True
    elif offered == "json": value = json.loads('{"original_admitted_parent_custody_authenticated":true}')
    else:
        from ipfs_accelerate_py.agent_supervisor.rescue import repair_candidate_owners as owner
        value = object.__new__(owner.VerifiedReviewedPreservationParentSuccess)
    def forbidden(*args, **kwargs):
        pytest.fail("unissued handle reached wire/physical/native DATA")
    monkeypatch.setattr(wire, "decode_parent_replay_value_v1", forbidden)
    raw = b"not even a closure wire; the opaque boundary must refuse first"
    with pytest.raises(ValueError, match="(?i)(issued|handle)"):
        release.validate_uscode_release_closure_v3(raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(), original_parent_handle=value)


@pytest.mark.parametrize("claim", ["original_parent_handle", "native_receipt_authenticated", "original_success_authenticated", "profile"])
def test_original_parent_v3_serialized_claims_cannot_choose_the_authenticated_path(
        physical_closure_control_v3, claim):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    request = deepcopy(physical_closure_control_v3[0])
    request[claim] = (release.CLOSURE_PARENT_PROFILE_V3 if claim == "profile" else
        {"original_success_authenticated": True} if claim == "original_parent_handle" else True)
    raw = wire.encode_parent_replay_value_v1(request, max_bytes=release.MAX_CLOSURE_REQUEST_BYTES)
    with pytest.raises(ValueError):
        release.validate_uscode_release_closure_v3(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("callback", ["guard", "capability", "loader"])
def test_original_parent_v3_context_refuses_late_owner_callable_substitution_before_claims(monkeypatch, callback):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_accelerate_py.agent_supervisor.rescue import repair_candidate_owners as owner
    names = ("_reviewed_parent_guard", "_reviewed_parent_capability_entry",
             "load_parent_verified_reviewed_preservation_v3")
    callbacks = tuple(getattr(owner, name) for name in names)
    # Explicitly UNISSUED negative context, not a fabricated positive capability.
    context = (owner, object(), object(), release._release_callback_states_v3(callbacks))
    calls = []
    def false_claim(*args, **kwargs):
        calls.append(True)
        return {"original_success_authenticated": True, "native_execution_authenticated": True}
    monkeypatch.setattr(owner, names[("guard", "capability", "loader").index(callback)], false_claim)
    with pytest.raises(ValueError, match="callback.*changed"):
        release._release_original_parent_fence_v3(context)
    assert calls == []


def test_original_parent_v3_context_cannot_replace_a_missing_handle():
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    with pytest.raises(ValueError, match="context cannot replace"):
        release._validate_uscode_release_byte_closure_v3(b"", expected_request_sha256="0" * 64,
            _original_parent_context=("fictional callback state",))


def consume_actual_reviewed_release_parent_v3(handle, request, control, packet_files):
    """Existing-controller handoff AFTER A run_v3 returns, in that SAME thread.

    No runner, compiler, fixture admission, resource grant or capability is
    created here. ``request`` and ``control`` must be the SAME physical signed
    component used to prepare A's original public Native input. The actual
    original parent, not an authored compiler substitute, supplies the packet.
    This helper is deliberately not an ordinary collected pytest case.
    """
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
    from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
    assert request["schema"] == release.CLOSURE_REQUEST_SCHEMA_V3 and request["native"] is None
    packet = tuple(packet_files)
    assert len(packet) == 83
    contents = dict(packet)
    receipt_raw = contents["build-receipt.json"]
    packet_raw = wire.encode_parent_replay_value_v1([list(row) for row in packet], max_bytes=release.MAX_CLOSURE_REQUEST_BYTES)
    transport = release.prepare_reviewed_native_packet_transport_v3(packet_raw,
        artifact_id_prefix="fixture:original-parent-v3")
    closure = deepcopy(request)
    closure["artifacts"].extend([dict(artifact_id="fixture:original-parent-v3-receipt", family="native_receipt",
        payload=receipt_raw, bytes=len(receipt_raw), sha256=hashlib.sha256(receipt_raw).hexdigest()),
        transport["index"], *transport["chunks"]])
    closure["expected_artifact_ids"] = [row["artifact_id"] for row in closure["artifacts"]]
    receipt = json.loads(receipt_raw)
    closure["native"] = dict(receipt="fixture:original-parent-v3-receipt", packet_index=transport["index"]["artifact_id"],
        expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
        expected_binary_sha256=receipt["binary_sha256"], observation_profile="retained-native-observation/v1")
    raw = wire.encode_parent_replay_value_v1(closure, max_bytes=release.MAX_CLOSURE_REQUEST_BYTES)
    report = release.validate_uscode_release_closure_v3(raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest(), original_parent_handle=handle)
    assert report["profile"] == release.CLOSURE_PARENT_PROFILE_V3
    for field in ("original_parent_handle_consumed", "native_receipt_authenticated",
                  "original_native_parent_custody_verified", "original_success_authenticated"):
        assert report[field] is True
    evidence = report["original_parent_evidence"]
    assert evidence["packet_file_count"] == 83
    assert evidence["retained_receipt_sha256"] == hashlib.sha256(receipt_raw).hexdigest()
    assert evidence["retained_packet_sha256"] == closure["native"]["expected_packet_sha256"]
    assert evidence["preparation_sha256"] == shared.reviewed_preservation_corpus_sha256(control["preparation"])
    assert evidence["graph_sha256"] == control["graph_sha"]
    assert evidence["admission_sha256"] == control["admission_sha"]
    for field in ("parent_request_sha256", "parent_closeout_sha256", "parent_durability_sha256"):
        assert len(evidence[field]) == 64 and all(c in "0123456789abcdef" for c in evidence[field])
    for field in ("release_ready", "closure_complete", "release_eligible", "admitted", "formalized", "proof_verified",
                  "source_semantics_verified", "source_authenticity_verified", "statutory_meaning_proved",
                  "gold_verified", "source_kernel_receipt_authenticated", "model_or_compiler_execution_performed"):
        assert report[field] is False
    for field in ("admission_mask", "release_mask", "gold_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    assert "original_admitted_native_parent_custody_not_established" not in report["blockers"]
    assert "immutable_remote_Hub_readback_not_established" in report["blockers"]
    assert "statutory_meaning_and_full_corpus_qualification_not_established" in report["blockers"]
    return raw, report



@pytest.mark.parametrize("helper", ["context", "fence", "authentication", "states", "callback_fence", "entry_guard"])
@pytest.mark.parametrize("mutation", ["identity", "code"])
def test_original_parent_v3_entry_refuses_preexisting_helper_substitution(monkeypatch, helper, mutation):
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    names = {"context": "_release_original_parent_context_v3", "fence": "_release_original_parent_fence_v3",
        "authentication": "_release_original_parent_authentication_v3", "states": "_release_callback_states_v3",
        "callback_fence": "_release_callback_fence_v3", "entry_guard": "_release_original_parent_entry_guard_v3"}
    calls = []
    def false_claim(*args, _calls=calls, **kwargs):
        _calls.append(True)
        return {"original_success_authenticated": True, "native_execution_authenticated": True}
    name = names[helper]
    if mutation == "identity": monkeypatch.setattr(release, name, false_claim)
    else: monkeypatch.setattr(getattr(release, name), "__code__", false_claim.__code__)
    # No valid issued handle is fabricated: entry must reject changed local
    # claim machinery before it ever tries to resolve this unissued object.
    raw = b"unparsed DATA; no physical or native replay may be entered"
    with pytest.raises(ValueError, match="original-parent coordinator entry generation changed"):
        release.validate_uscode_release_closure_v3(raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(), original_parent_handle=object())
    assert calls == []


def test_prepare_original_parent_v3_same_physical_public_inputs(
        physical_closure_control_v3, tmp_path, monkeypatch, request):
    """One separately admitted preparation; no Native/compiler/capability.

    Keep the original signed three-unit control and physical source files.
    Encode public inputs ONCE for the later original A parent, and the exact
    D closure request for its same-thread consumer. This is not that run.
    """
    import importlib.util
    from ipfs_accelerate_py.agent_supervisor.rescue import repair_candidate_owners as owners
    from ipfs_datasets_py.logic.autoformal import legal_release_coordinator_v1 as release
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as wire
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
    closure, control = physical_closure_control_v3
    assert closure["native"] is None and control["admission"]["fixture_only"] is True
    assert control["admission"]["provenance_kind"] == "fictional_fixture"
    root = Path(owners.__file__).resolve().parents[3]
    unit_path = root / "test/api/test_agent_supervisor_productive_owner_v3.py"
    # Same fixed maintained-file loading pattern as the existing controller;
    # request/source owners independently pin this exact ordinary source.
    unit_sha = hashlib.sha256(unit_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("_reviewed_original_A_public_fixture_v3", unit_path)
    assert spec is not None and spec.origin == str(unit_path)
    unit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unit)
    assert unit.__file__ == str(unit_path)
    native_helper = unit.reviewed_parent_original_R_fixture_module_v1(ROOT)
    def forbidden(*args, **kwargs):
        pytest.fail("passive public fixture preparation tried to execute a native tool")
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native_helper.process.BoundedToolRunner, "run", forbidden)
    public_path = tmp_path / "same-physical-public-native-inputs-v3.json"
    record = unit.prepare_reviewed_parent_native_fixture_inputs_v3(public_path, control, datasets_root=ROOT)
    public_ref = record["native_inputs"]
    value = owners.json_object(owners.checked_descriptor(public_ref))
    public = {key: unit.reviewed_parent_fixture_tree_decode_v1(value[key])
              for key in ("graph", "admission", "args", "kwargs")}
    for key in public:
        assert owners.canonical(unit.reviewed_parent_fixture_tree_encode_v1(public[key])) == \
            owners.canonical(value[key]) == owners.canonical(unit.reviewed_parent_fixture_tree_encode_v1(control[key]))
    assert value["preparation"]["manifest_json"] == control["preparation"].manifest_json
    assert tuple((name, body) for name, body in value["preparation"]["files"]) == control["preparation"].files
    assert record["expected_graph_sha256"] == control["graph_sha"]
    assert record["expected_admission_sha256"] == control["admission_sha"]
    assert record["expected_preservation_sha256"] == control["shared"].reviewed_preservation_corpus_sha256(control["preparation"])
    raw = wire.encode_parent_replay_value_v1(closure, max_bytes=release.MAX_CLOSURE_REQUEST_BYTES)
    closure_path = tmp_path / "same-physical-closure-request-v3.wire"
    with closure_path.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    closure_path.chmod(0o400)
    replayed = release.validate_uscode_release_closure_v3(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())
    assert_release_v3_byte_authority_only(replayed)
    assert replayed["local_source_cache_entity_bindings_verified"] is True
    def reference(path):
        body = path.read_bytes()
        return dict(path=str(path), bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    lineage = {"schema": "same-physical-reviewed-V3-public-fixture-derivation/v1",
        "public_native_inputs": public_ref, "physical_closure_request": reference(closure_path),
        "expected_preservation_sha256": record["expected_preservation_sha256"],
        "expected_graph_sha256": record["expected_graph_sha256"],
        "expected_admission_sha256": record["expected_admission_sha256"], "toolchain": record["toolchain"],
        "A_fixture_owner": reference(unit_path), "D_fixture_owner": reference(Path(__file__).absolute()),
        "public_encoder_invocations": 1, "physical_control_fixture_generations": 1,
        "native_tools_run": 0, "parent_handles_issued": 0, "fixture_only": True,
        "legal_or_training_or_corpus_admission": False}
    lineage_path = tmp_path / "same-physical-public-fixture-lineage-v3.json"
    with lineage_path.open("xb") as stream:
        stream.write(owners.canonical(lineage) + b"\n"); stream.flush(); os.fsync(stream.fileno())
    lineage_path.chmod(0o400)
    with public_path.open("rb") as stream: os.fsync(stream.fileno())
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(directory)
    finally: os.close(directory)
    assert reference(public_path) == public_ref
    assert hashlib.sha256(unit_path.read_bytes()).hexdigest() == unit_sha
    assert reference(closure_path) == lineage["physical_closure_request"]
    request.node.user_properties.append(("same_physical_V3_derivation", owners.canonical(reference(lineage_path)).decode("utf-8")))
