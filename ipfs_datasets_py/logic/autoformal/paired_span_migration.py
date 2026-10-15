"""One explicit historical paired-v2 layout to current-v2 evidence migration.

This stages new immutable files only. It never opens a campaign database,
executes a compiler/model, publishes, enqueues goals, or removes old evidence.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat

from . import paired_span_census as paired

HISTORICAL_EXPORTER = "93a5b6c4fafabf45f84cd12b53347e7e8e96686592b489a6a7ea036d88d5b2e9"
MIGRATION_SCHEMA = "paired-census-seven-field-migration/v1"
_AE_ADDED = ("learned_formula_capture_verified", "learned_formula_observation_artifact_sha256")
SOURCE_RELATIVES = (
    "ipfs_datasets_py/logic/autoformal/paired_span_migration.py",
    "ipfs_datasets_py/logic/autoformal/paired_span_census.py",
    "ipfs_datasets_py/logic/autoformal/tree_pin.py",
    "ipfs_datasets_py/logic/autoformal/family_supervision.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_queue.py",
    "ipfs_datasets_py/logic/autoformal/span_cache_exchange.py",
    "ipfs_datasets_py/logic/autoformal/repair_intake.py",
    "ipfs_datasets_py/logic/autoformal/learned_formula_observation.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "scripts/ops/legal_ir/run_legacy_span_cuda.py",
)


def _need(condition, message):
    if not condition:
        raise paired.PairedCensusError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _snapshot(path, maximum):
    path = Path(path)
    for parent in (path.parent, *path.parent.parents):
        _need(stat.S_ISDIR(parent.lstat().st_mode), "input parent must be an existing nonsymlink directory")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and 0 < before.st_size <= maximum, "bounded unaliased regular input required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    _need(len(raw) == before.st_size and identity(before) == identity(after)
          and identity(after) == identity(path.lstat()), "input changed while reading")
    return raw


def _manifest(path, expected_sha256):
    _need(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256),
          "explicit original manifest SHA256 required")
    raw = _snapshot(path, 64 * 1024)
    _need(_sha(raw) == expected_sha256, "original manifest hash differs")
    manifest = json.loads(raw)
    _need(paired._json(manifest) == raw, "historical manifest must retain exact canonical JSON")
    _need(manifest.get("schema") == paired.MANIFEST_SCHEMA
          and manifest.get("repository_id") == paired.REPOSITORY
          and manifest.get("exporter_sha256") == HISTORICAL_EXPORTER
          and set(manifest.get("tables", {})) == set(paired.TABLE_NAMES),
          "unsupported historical producer/layout manifest")
    _need(all(manifest.get(key) is False for key in ("admitted", "formalized", "enqueued")),
          "historical bundle cannot grant authority")
    _need(manifest.get("fingerprint") == _sha(paired._json({k: v for k, v in manifest.items()
          if k not in {"fingerprint", "path_in_repo"}})), "historical manifest fingerprint differs")
    _need(type(manifest.get("agent_id")) is str and bool(manifest["agent_id"]), "historical agent required")
    prefix = paired.REPO_PREFIX + "/"
    for kind, entry in manifest["tables"].items():
        filename, remote = entry.get("filename"), entry.get("path_in_repo")
        _need(type(filename) is str and Path(filename).name == filename and filename.endswith(".parquet")
              and type(remote) is str and remote.startswith(prefix + kind + "/")
              and Path(remote).name == filename and ".." not in Path(remote).parts and "\\" not in remote,
              "invalid historical table path")
        _need(type(entry.get("bytes")) is int and 0 < entry["bytes"] <= paired.MAX_BYTES
              and type(entry.get("row_count")) is int and 0 <= entry["row_count"] <= paired.MAX_ROWS * 8
              and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))), "invalid historical table bound")
    _need(0 < manifest["tables"]["paired_spans"]["row_count"] <= paired.MAX_ROWS,
          "historical observation count exceeds bound")
    return manifest, raw


def _read_historical(path, expected_sha256):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = Path(path)
    manifest, raw = _manifest(path, expected_sha256)
    schemas = paired.arrow_schemas(paired.LEGACY_SCHEMA)
    files, tables, compressed, allocated = {"manifest": raw}, {}, len(raw), 0
    for kind in paired.TABLE_NAMES:
        entry = manifest["tables"][kind]
        body = _snapshot(path.parent / entry["filename"], paired.MAX_BYTES)
        compressed += len(body)
        _need(len(body) == entry["bytes"] and _sha(body) == entry["sha256"], "historical table hash/size differs")
        _need(compressed <= paired.MAX_BYTES, "historical compressed bundle exceeds bound")
        parquet = pq.ParquetFile(pa.BufferReader(body))
        _need(parquet.schema_arrow == schemas[kind] and parquet.metadata.num_rows == entry["row_count"],
              "unsupported historical Arrow layout or row count")
        allocated += sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.metadata.num_row_groups))
        _need(allocated <= paired.MAX_BYTES, "historical Arrow allocation exceeds bound")
        tables[kind] = parquet.read().to_pylist()
        files[kind] = body
    artifacts, decoded = {}, 0
    for artifact in tables["artifacts"]:
        body = paired.decode_artifact(artifact, max_bytes=paired.MAX_BYTES - decoded)
        decoded += len(body)
        identity = artifact["artifact_sha256"]
        _need(identity not in artifacts, "duplicate historical artifact identity")
        artifacts[identity] = artifact
    receipt_id = manifest.get("original_receipt_artifact_sha256")
    _need(receipt_id in artifacts and artifacts[receipt_id]["kind"] == "original_producer_receipt",
          "historical original receipt artifact missing")
    receipt_raw = paired.decode_artifact(artifacts[receipt_id])
    receipt = json.loads(receipt_raw)
    _need(paired._json(receipt) == receipt_raw, "original receipt is not the exact canonical JSON artifact")
    return manifest, tables, files, artifacts, receipt, receipt_raw


def _observations(receipt, runner):
    _need(receipt.get("schema_version") == "legacy-span-cuda-diagnostic/v1"
          and receipt.get("mode") == "legacy_mock_diagnostic"
          and all(receipt.get(k) is False for k in ("admitted", "formalized", "semantic_qualified", "training_executed")),
          "unsupported or qualified producer receipt")
    _need(type(receipt.get("rows")) is list and 0 < len(receipt["rows"]) <= paired.MAX_ROWS,
          "original receipt row bound differs")
    batch_id = receipt.get("campaign", {}).get("batch_id")
    _need(type(batch_id) is str and 0 < len(batch_id) <= 128, "original receipt batch identity missing")
    observations = runner.exchange_rows(receipt)
    for observation, original in zip(observations, receipt["rows"]):
        _need(original.get("learned_formula_generation") is False
              and "learned_formula_observation" not in original, "historical layout cannot infer a learned capture")
        guided = original.get("guided_compiler_observation")
        required = {"guided_formal_outputs", "direct_formal_outputs",
                    "model_formal_output_provenance", "direct_formal_output_provenance"}
        _need(type(guided) is dict and required <= set(guided), "original guided/direct evidence is incomplete")
        for target, source in (("model_formal_outputs", "guided_formal_outputs"),
                               ("direct_formal_outputs", "direct_formal_outputs"),
                               ("model_formal_output_provenance", "model_formal_output_provenance"),
                               ("direct_formal_output_provenance", "direct_formal_output_provenance")):
            observation[target] = copy.deepcopy(guided[source])
    return observations


def _historical_view(current):
    value = copy.deepcopy(current)
    for key in _AE_ADDED:
        value["autoencoder"].pop(key)
    value["comparison"] = paired._compare_formal_outputs_v1(value["autoencoder"], value["compiler"])
    value.pop("observation_id")
    value["goal_ids"] = []
    value["observation_id"] = _sha(paired._json(value))
    return value


def _runner(root):
    path = root / "scripts/ops/legal_ir/run_legacy_span_cuda.py"
    spec = importlib.util.spec_from_file_location("paired_migration_source_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _need(Path(module.ROOT).resolve() == root.resolve(), "receipt adapter escaped selected canonical source")
    return module


def migrate_historical_paired_bundle(manifest_path, output_directory, *, expected_manifest_sha256,
                                     expected_sources, receipt_path=None):
    """Stage current evidence from one pinned historical layout; never publish.

    Old goal packets bind old observation IDs. Preserve their original tables,
    artifact bytes and descriptive goal records; never relabel their sealed IDs.
    """
    root = Path(__file__).resolve().parents[3]
    _need(root == Path("/home/barberb/lift_coding/external/ipfs_datasets"), "migration requires canonical workspace source")
    _need(type(expected_sources) is dict and bool(expected_sources), "explicit reviewed source pins required")
    required = {str(root / relative) for relative in SOURCE_RELATIVES}
    _need(required <= set(expected_sources), "migration/paired/adapter source pins required")
    def guard():
        for source, digest in expected_sources.items():
            _need(_sha(_snapshot(source, 4 * 1024 * 1024)) == digest, "migration producer source changed")
    guard()
    from .tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    manifest, historical, files, old_artifacts, receipt, receipt_raw = _read_historical(manifest_path, expected_manifest_sha256)
    if receipt_path is not None:
        _need(_snapshot(receipt_path, paired.MAX_BYTES) == receipt_raw, "retained receipt file differs from original artifact")
    model = "legacy-mock-diagnostic:sha256:" + receipt["checkpoint"]["sha256"]
    code = "sha256:" + receipt["producer_source"]["sha256"]
    built = paired.build_paired_census(_observations(receipt, _runner(root)), original_receipt=receipt,
        agent_id=manifest["agent_id"], repository_id=manifest["repository_id"], code_identity=code, model_identity=model)
    old_spans = {span["source"]["span_id"]: span for span in historical["paired_spans"]}
    new_spans = {span["source"]["span_id"]: span for span in built["paired_spans"]}
    _need(len(old_spans) == len(historical["paired_spans"]) and set(old_spans) == set(new_spans), "historical source coverage differs")
    links = {}
    for span_id, current in new_spans.items():
        prior = copy.deepcopy(old_spans[span_id])
        _need(prior["admitted"] is prior["formalized"] is prior["lake"]["admitted"] is False,
              "historical observation grants authority")
        _need(not prior["source"]["constitution"] or prior["compiler"]["roundtrip_ok"] is False,
              "Constitution cannot be marked roundtrip_ok")
        prior["goal_ids"] = []
        _need(_historical_view(current) == prior, "receipt does not exactly reproduce historical observation")
        _need(current["autoencoder"]["learned_formula_capture_verified"] is False
              and current["autoencoder"]["learned_formula_observation_artifact_sha256"] is None
              and current["comparison"]["independent"] is False, "migration cannot create learned or independent evidence")
        links[prior["observation_id"]] = current["observation_id"]
    artifact_rows = {row["artifact_sha256"]: row for row in built["artifacts"]}
    for identity, artifact in old_artifacts.items():
        if identity in artifact_rows:
            existing = artifact_rows[identity]
            _need(existing["kind"] == artifact["kind"]
                  and paired.decode_artifact(existing) == paired.decode_artifact(artifact),
                  "historical artifact identity conflicts")
        artifact_rows[identity] = artifact
    archive = paired._Artifacts(paired.MAX_BYTES)
    for kind, body in files.items():
        archive.add({"schema": "historical-paired-file/v1", "kind": kind, "sha256": _sha(body),
                     "bytes": len(body), "payload_base64": base64.b64encode(body).decode("ascii")}, "historical_paired_file")
    old_goal_ids, historical_goal_links = set(), []
    recorded_goal_ids = {goal["goal_id"] for goal in historical["goals"]}
    _need(all(goal_id in recorded_goal_ids for span in historical["paired_spans"]
              for goal_id in span["goal_ids"]), "historical observation goal missing")
    old_observations = {row["observation_id"]: row for row in historical["paired_spans"]}
    for old in historical["goals"]:
        _need(old["goal_id"] not in old_goal_ids and old["enqueued"] is old["admitted"] is False,
              "historical goal identity or authority differs")
        old_goal_ids.add(old["goal_id"])
        _need(old["observation_ids"] and all(x in links for x in old["observation_ids"]), "historical goal observation missing")
        _need(old["source_span_ids"] == [old_observations[x]["source"]["span_id"] for x in old["observation_ids"]]
              and all(old["goal_id"] in old_observations[x]["goal_ids"] for x in old["observation_ids"]),
              "historical goal source links differ")
        for kind in ("packet", "task"):
            reference = old[kind + "_artifact_sha256"]
            _need(reference is None or reference == old[kind + "_sha256"] and reference in old_artifacts,
                  "historical goal artifact missing")
        if old["packet_artifact_sha256"] is not None:
            _need(old["task_artifact_sha256"] is not None and len(old["observation_ids"]) == 1,
                  "historical portable goal requires one observation and task artifact")
            packet = json.loads(paired.decode_artifact(old_artifacts[old["packet_artifact_sha256"]]))
            task = json.loads(paired.decode_artifact(old_artifacts[old["task_artifact_sha256"]]))
            source = packet.get("row", {})
            capture = source.get("capture", {})
            original_span = old_observations[old["observation_ids"][0]]
            _need(source.get("source_span_id") == original_span["source"]["span_id"]
                  and source.get("text") == original_span["source"]["text"]
                  and capture.get("source_text_sha256") == original_span["source"]["text_sha256"]
                  and capture.get("census_sha256") == original_span["observation_id"]
                  and task.get("task_id") == old["goal_id"]
                  and old["code_identity"] == original_span["provenance"]["code_identity"]
                  and old["model_identity"] == original_span["provenance"]["model_identity"],
                  "historical portable goal differs from its original sealed source")
        historical_id = "HISTORICAL-" + _sha(paired._json({"manifest": expected_manifest_sha256, "goal": old["goal_id"]}))
        descriptive = paired._goal_base(historical_id, issue=old["issue"], work_kind=old["work_kind"],
            kind="historical_goal_record", code=old["code_identity"], model=old["model_identity"])
        descriptive.update(source_span_ids=list(old["source_span_ids"]),
            observation_ids=[links[x] for x in old["observation_ids"]], status="historical_deferred",
            legacy_census_sha256=old.get("legacy_census_sha256"))
        built["goals"].append(descriptive)
        for source in old["source_span_ids"]:
            new_spans[source]["goal_ids"].append(historical_id)
        historical_goal_links.append({"old_goal_id": old["goal_id"], "historical_description_id": historical_id,
                                     "sealed_packet_relabelled": False})
    lineage = {"schema": MIGRATION_SCHEMA, "old_manifest_sha256": expected_manifest_sha256,
        "old_fingerprint": manifest["fingerprint"], "original_receipt_sha256": _sha(receipt_raw),
        "old_exporter_sha256": manifest["exporter_sha256"], "current_exporter_sha256": paired.EXPORTER_SOURCE_SHA256,
        "observation_id_map": links, "historical_goal_links": historical_goal_links,
        "historical_goals": historical["goals"], "producer_source_pins": expected_sources,
        "exact_historical_observations_reproduced": True,
        "new_comparison_scope": "current canonical-core representation diagnostic, not independent validation",
        "learned_capture_created": False, "compiler_rerun": False, "model_rerun": False,
        "old_files_modified": False, "admitted": False, "formalized": False, "enqueued": False}
    lineage_id = archive.add(lineage, "paired_census_schema_migration")
    for identity, artifact in archive.rows.items():
        _need(identity not in artifact_rows, "migration artifact identity conflicts")
        artifact_rows[identity] = artifact
    built["artifacts"] = list(artifact_rows.values())
    decoded = sum(row["decoded_bytes"] for row in built["artifacts"])
    total = decoded + sum(len(paired._json(row)) for row in built["paired_spans"] + built["goals"])
    _need(total <= paired.MAX_BYTES and len(built["goals"]) <= paired.MAX_ROWS * 8
          and len(built["artifacts"]) <= paired.MAX_ROWS * 8, "complete migrated evidence exceeds unchanged bounds")
    guard()
    staged = paired.write_paired_census_bundle(built, output_directory)
    checked = paired.load_paired_census_bundle(staged["manifest"]["path"])
    _need(checked["original_receipt"] == receipt
          and checked["manifest"]["original_receipt_artifact_sha256"] == _sha(receipt_raw),
          "current loader did not preserve original receipt")
    _need(_snapshot(manifest_path, 64 * 1024) == files["manifest"], "historical manifest changed during migration")
    for kind in paired.TABLE_NAMES:
        _need(_snapshot(Path(manifest_path).parent / manifest["tables"][kind]["filename"], paired.MAX_BYTES) == files[kind],
              "historical table changed during migration")
    guard()
    return {"schema": MIGRATION_SCHEMA, "old_manifest_sha256": expected_manifest_sha256,
        "old_fingerprint": manifest["fingerprint"], "new_fingerprint": staged["fingerprint"],
        "new_manifest": staged["manifest"], "lineage_artifact_sha256": lineage_id,
        "batch_id": receipt.get("campaign", {}).get("batch_id"),
        "staged": staged,
        "supersedes": {"manifest": {"path": str(Path(manifest_path)),
            "path_in_repo": manifest["path_in_repo"], "sha256": expected_manifest_sha256,
            "bytes": len(files["manifest"])}, "fingerprint": manifest["fingerprint"],
            "tables": copy.deepcopy(manifest["tables"]),
            "original_receipt_sha256": _sha(receipt_raw)},
        "owner_handoff": {"expected_status": "needs_schema_migration", "staged_status": "staged",
            "database_changed": False, "work_rows_changed": False, "completion_counts_changed": False},
        "historical_goal_count": len(historical["goals"]), "current_goal_count": len(built["goals"]),
        "paired_span_count": len(built["paired_spans"]), "decoded_evidence_bytes": total,
        "original_receipt_sha256": _sha(receipt_raw), "old_files_modified": False,
        "compiler_rerun": False, "model_rerun": False, "uploaded": False, "enqueued": False,
        "admitted": False, "formalized": False, "Lean_admitted": False}


def fetch_historical_bundle(*, revision, manifest_path_in_repo, expected_manifest_sha256, directory, api=None):
    """Fetch only four pinned dataset metadata files, never checkpoint weights.

    Remote revision must be an immutable Git commit. Size inspection precedes
    downloads; exact bytes and SHA256 are checked before migration can use them.
    The caller owns native resource/storage admission for this finite worker.
    """
    from huggingface_hub import HfApi, hf_hub_download

    _need(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision), "immutable dataset revision required")
    prefix = paired.REPO_PREFIX + "/manifests/"
    remote = manifest_path_in_repo
    _need(type(remote) is str and remote.startswith(prefix) and ".." not in Path(remote).parts
          and "\\" not in remote and re.fullmatch(r"manifest-[0-9a-f]{64}\.json", Path(remote).name),
          "explicit paired manifest repository path required")
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=False)
    api = api or HfApi()
    def download(name, maximum, expected_digest=None, expected_bytes=None):
        metadata = list(api.get_paths_info(repo_id=paired.REPOSITORY, repo_type="dataset", revision=revision, paths=[name]))
        _need(len(metadata) == 1, "remote immutable metadata file missing")
        info = metadata[0]
        field = lambda key: info.get(key) if isinstance(info, dict) else getattr(info, key, None)
        _need(field("path") == name and type(field("size")) is int and 0 < field("size") <= maximum
              and (expected_bytes is None or field("size") == expected_bytes), "remote metadata file exceeds bound")
        cached = Path(hf_hub_download(repo_id=paired.REPOSITORY, repo_type="dataset", revision=revision, filename=name)).resolve()
        body = _snapshot(cached, maximum)
        _need(len(body) == field("size") and (expected_digest is None or _sha(body) == expected_digest),
              "downloaded immutable metadata file differs")
        local = target / Path(name).name
        paired._write_immutable(local, body)
        return local
    local = download(remote, 64 * 1024, expected_manifest_sha256)
    manifest, _ = _manifest(local, expected_manifest_sha256)
    _need(sum(row["bytes"] for row in manifest["tables"].values()) <= paired.MAX_BYTES,
          "remote historical bundle exceeds aggregate bound")
    for entry in manifest["tables"].values():
        download(entry["path_in_repo"], paired.MAX_BYTES, entry["sha256"], entry["bytes"])
    return local
