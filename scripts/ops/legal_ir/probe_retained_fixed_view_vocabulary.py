#!/usr/bin/env python3
"""Admitted, read-only repeated-tuning probe over two retained checkpoints.

Invoke only as a child of the existing run_owned_validation.py owner. This
controller acquires no resource grant and changes no target, state or objective.
Product imports and target hydration occur inside main, after input custody.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "retained-legal-ir-fixed-view-probe/v1"
SELECTED_CHECK = "retained-two-row-parent-structural-fixed-view-vocabulary"
MiB = 1024 * 1024
MAX_OUTPUT = 16 * MiB
PUBLISHED_SHA = "bd3599791fd6b9238c02226630639b3b499c723b348cf4e9535af4c5ccbe73db"
ROLES = (
    "published_observation", "head_report", "preparation_report", "support_audit",
    "head_owned_request", "head_driver", "constructor_receipt", "selected_inputs",
    "target_config", "parent_checkpoint", "structural_checkpoint", "embedding_receipt",
    "source_import_receipt", "tuning06_preparation", "tuning06_bundle",
    "tuning06_source_text", "tuning07_preparation", "tuning07_bundle", "tuning07_source_text",
)
BRIDGES = ("modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router")
AUTHORITY = {key: False for key in (
    "semantic_reconstruction_verified", "legal_meaning_verified", "source_authenticated",
    "review_performed", "gold_admitted", "proof_admitted", "model_promoted",
    "teacher_promoted", "execution_authority", "completion_authority",
)}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def parse(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            need(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def digest(value):
    need(type(value) is str and len(value) == 64
         and all(c in "0123456789abcdef" for c in value), "lowercase SHA256 required")
    return value


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def original_driver_constants(raw):
    """Read literal Path joins without importing or executing the old driver."""
    values = {}
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (str, int):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" \
                and len(node.args) == 1 and not node.keywords:
            return Path(value(node.args[0]))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = value(node.left), value(node.right)
            need(type(left) is type(Path("/")) and type(right) is str, "literal old Path join required")
            return left / right
        raise ValueError("not a literal retained driver constant")
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = value(node.value)
            except ValueError:
                pass
    return values


def open_regular(path):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts and path.name, "absolute input path required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open("/", flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                       dir_fd=parent)
    finally:
        os.close(parent)


def checked(path, expected, expected_bytes=None, maximum=4 * MiB, *, retain=False):
    descriptor = open_regular(path)
    try:
        before = os.fstat(descriptor)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and 0 < before.st_size <= maximum, "bounded single-link regular input required")
        need(expected_bytes is None or before.st_size == expected_bytes, "input byte length differs")
        hasher, chunks, count = hashlib.sha256(), [], 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            need(count <= maximum, "input grew beyond bound")
            hasher.update(chunk)
            if retain:
                chunks.append(chunk)
        need(count == before.st_size and hasher.hexdigest() == digest(expected)
             and fingerprint(os.fstat(descriptor)) == fingerprint(before), "input digest or identity changed")
        closing = open_regular(path)
        try:
            need(fingerprint(os.fstat(closing)) == fingerprint(before), "input path substituted")
        finally:
            os.close(closing)
        return (b"".join(chunks) if retain else None), fingerprint(before)
    finally:
        os.close(descriptor)


class Exports:
    def __init__(self, path):
        self.path = Path(path)
        need(self.path.name == "exports" and self.path.is_absolute()
             and self.path.resolve(strict=True) == self.path, "existing native attempt exports required")
        info = self.path.stat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and not list(self.path.iterdir()), "empty private0700 exports directory required")
        temporary = Path(os.environ.get("TMPDIR", ""))
        need(temporary.is_absolute() and temporary.resolve(strict=True).parent == self.path.parent
             and temporary.name == "tmp", "native attempt TMPDIR required")
        self.identity = fingerprint(info)[:5]
        self.rows, self.total = {}, 0

    def save(self, name, raw):
        need(type(name) is str and Path(name).name == name and name not in self.rows,
             "exclusive flat export name required")
        need(self.total + len(raw) <= MAX_OUTPUT, "aggregate output limit exceeded")
        fd = os.open(self.path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        self.total += len(raw)
        self.rows[name] = {"path": name, "bytes": len(raw), "sha256": sha(raw)}
        return self.rows[name]

    def json(self, name, value):
        return self.save(name, wire(value) + b"\n")

    def verify(self):
        need(fingerprint(self.path.stat())[:5] == self.identity, "exports directory substituted")
        need({p.name for p in self.path.iterdir()} == set(self.rows), "unlisted export appeared")
        for row in self.rows.values():
            checked(self.path / row["path"], row["sha256"], row["bytes"], MAX_OUTPUT)
        fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-descriptor", required=True)
    parser.add_argument("--expected-input-descriptor-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    options = parser.parse_args()
    os.umask(0o077)
    descriptor_raw, descriptor_identity = checked(options.input_descriptor,
        options.expected_input_descriptor_sha256, maximum=64 * 1024, retain=True)
    declaration = parse(descriptor_raw)
    need(type(declaration) is dict and set(declaration) == {"schema", "inputs", "tuning_rows"}
         and declaration["schema"] == "retained-legal-ir-fixed-view-inputs/v1", "closed descriptor required")
    need(type(declaration["inputs"]) is list and len(declaration["inputs"]) == len(ROLES), "complete19 inputs required")
    refs = {}
    for name, row in zip(ROLES, declaration["inputs"], strict=True):
        need(type(row) is dict and set(row) == {"name", "path", "bytes", "sha256"}
             and row["name"] == name and type(row["bytes"]) is int and row["bytes"] > 0,
             "closed ordered input reference required")
        digest(row["sha256"])
        refs[name] = {key: row[key] for key in ("path", "bytes", "sha256")}
    need(refs["published_observation"]["sha256"] == PUBLISHED_SHA, "immutable published observation differs")
    identities, calls = {}, []
    driver_raw = Path(__file__).read_bytes()
    exports = Exports(options.output_directory)

    def read(name):
        row = refs[name]
        raw, identity = checked(row["path"], row["sha256"], row["bytes"],
            16 * MiB if name.endswith("checkpoint") else 4 * MiB, retain=True)
        need(name not in identities or identities[name] == identity, "original input substituted")
        identities[name] = identity
        return raw

    def metadata(name):
        return parse(read(name))

    def ref_equal(offered, name):
        need(offered == refs[name], "historical receipt input reference differs: " + name)

    def custody():
        _, identity = checked(options.input_descriptor, options.expected_input_descriptor_sha256,
                              len(descriptor_raw), 64 * 1024)
        need(identity == descriptor_identity, "descriptor identity substituted")
        for name, row in refs.items():
            _, identity = checked(row["path"], row["sha256"], row["bytes"],
                                  16 * MiB if name.endswith("checkpoint") else 4 * MiB)
            need(name not in identities or identities[name] == identity, "retained input substituted")
            identities[name] = identity
        published = metadata("published_observation")
        for label, role in (("raw_head_worker_report", "head_report"),
                ("raw_target_preparation_report", "preparation_report"),
                ("actual_raw_view_support_audit", "support_audit"), ("head_owned_request", "head_owned_request")):
            ref_equal(published["evidence"][label], role)
        head, prep = metadata("head_report"), metadata("preparation_report")
        for label, role in (("checkpoint", "parent_checkpoint"), ("constructor_receipt", "constructor_receipt"),
                            ("selected_inputs", "selected_inputs"), ("preparation_report", "preparation_report")):
            ref_equal(head[label], role)
        ref_equal(prep["selected_inputs"], "selected_inputs")
        ref_equal(prep["target_config"], "target_config")
        need(head["bridge_names"] == list(BRIDGES) and head["legal_ir_evaluate_provers"] is False
             and head["use_sample_memory"] is False, "old head execution context differs")
        constructor = metadata("constructor_receipt")["effective_autoencoder_config"]
        need(constructor == head["effective_autoencoder_config"], "full original constructor differs")
        structural = next(a for a in head["arms"] if a["name"] == "structural")
        ref_equal(structural["candidate"], "structural_checkpoint")
        need(structural["optimizer_accepted_epochs"] == 1, "structural candidate lineage differs")
        for arm in head["arms"]:
            if arm["name"] in {"global_view", "feature_view"}:
                need(arm["optimizer_accepted_epochs"] == 0
                     and arm["candidate"]["sha256"] == refs["parent_checkpoint"]["sha256"]
                     and arm["candidate"]["bytes"] == refs["parent_checkpoint"]["bytes"],
                     "historical rejected arm is not retained parent rollback")
        request, source_driver = metadata("head_owned_request"), read("head_driver")
        need(request["source_sha256"][refs["head_driver"]["path"]] == refs["head_driver"]["sha256"],
             "original driver lacks independently retained request pin")
        constants = original_driver_constants(source_driver)
        for name, path_key, hash_key in (("embedding_receipt", "EMBEDDING_RECEIPT", "EMBEDDING_SHA"),
                                       ("source_import_receipt", "IMPORT_RECEIPT", "IMPORT_SHA")):
            need(constants[hash_key] == refs[name]["sha256"]
                 and str(constants[path_key]) == refs[name]["path"], "original driver receipt literal differs")
        selected, audit, imported = metadata("selected_inputs"), metadata("support_audit"), metadata("source_import_receipt")
        rows = declaration["tuning_rows"]
        need(type(rows) is list and [row["ordinal"] for row in rows] == [6, 7]
             and len(selected["records"]) == 8, "exact original two repeated-tuning rows required")
        total_expanded = 0
        for row in rows:
            need(type(row) is dict and set(row) == {
                "ordinal", "partition", "record_json_pointer", "physical_source_binding_json_pointer",
                "record_id", "sample_id", "sample_payload_sha256", "sample_payload_sha256_scope",
                "target_snapshot_id", "preparation_role", "bundle_role", "source_text_role",
                "expanded_target_bytes", "expanded_target_sha256", "target_view_support", "target_view_distribution"},
                "closed original tuning-row declaration required")
            index = row["ordinal"]
            need(row["record_json_pointer"] == f"/records/{index}"
                 and row["physical_source_binding_json_pointer"] == f"/physical_source_bindings/{index}"
                 and row["preparation_role"] == f"tuning{index:02d}_preparation"
                 and row["bundle_role"] == f"tuning{index:02d}_bundle"
                 and row["source_text_role"] == f"tuning{index:02d}_source_text", "tuning row role or pointer differs")
            record, physical = selected["records"][index], selected["physical_source_bindings"][index]
            complete, evidence = prep["targets"][index], metadata(row["preparation_role"])
            ref_equal(complete["evidence"], row["preparation_role"])
            ref_equal(complete["target_artifact"], row["bundle_role"])
            ref_equal(evidence["preparation"]["artifact"], row["bundle_role"])
            need(row["partition"] == "repeated_tuning" and complete["complete"] is True
                 and evidence["preparation"]["target_completeness"]["complete"] is True
                 and record["record_id"] == row["record_id"] == evidence["source_record_id"]
                 and complete["sample_id"] == row["sample_id"] == evidence["sample_id"]
                 and complete["target_snapshot_id"] == row["target_snapshot_id"] == evidence["target_snapshot_id"]
                 and complete["sample_payload_sha256"] == row["sample_payload_sha256"]
                 and record["embedding_provenance"]["artifact_sha256"] == refs["embedding_receipt"]["sha256"],
                 "retained row or singleton preparation identity differs")
            source = refs[row["source_text_role"]]
            need(physical["source_text_sha256"] == source["sha256"]
                 and record["sample"]["text"].encode("utf-8") == read(row["source_text_role"]), "original source text differs")
            matches = [value for value in imported["rows"] if value["extracted_text"] ==
                       {"bytes": source["bytes"], "sha256": source["sha256"]}]
            need(len(matches) == 1 and matches[0]["entry_cid"] == physical["entry_cid"]
                 and matches[0]["record_sha256"] == physical["source_record_sha256"]
                 and Path(source["path"]).name == f"source-{matches[0]['row_index']:06d}.txt",
                 "independently retained source-import row differs")
            observed = audit["rows"][index]
            need(observed["bundle"] == refs[row["bundle_role"]]
                 and observed["expanded_bytes"] == row["expanded_target_bytes"]
                 and observed["expanded_target_sha256"] == row["expanded_target_sha256"]
                 and observed["view_distribution"] == row["target_view_distribution"]
                 and observed["view_support"] == row["target_view_support"], "support-audit row differs")
            need(type(row["expanded_target_bytes"]) is int
                 and 0 < row["expanded_target_bytes"] <= 64 * MiB, "expanded target bound exceeded")
            total_expanded += row["expanded_target_bytes"]
        need(total_expanded <= 128 * MiB, "aggregate expanded target budget exceeded")
        need(Path(__file__).read_bytes() == driver_raw, "probe source changed")

    owner_sources = {}

    def owner_current():
        for path, reference in owner_sources.items():
            checked(path, reference["sha256"], reference["bytes"], 4 * MiB)

    def call(name, operation):
        custody()
        owner_current()
        started = time.monotonic()
        try:
            return operation()
        finally:
            custody()
            owner_current()
            calls.append({"operation": name, "seconds": time.monotonic() - started})

    custody()
    exports.save("retained-head-inputs.json", descriptor_raw)
    # Only imports from this fresh checkout are accepted; no nested gate or model provider.
    sys.path.insert(0, str(ROOT))
    prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
    names = ("autoencoder_corpus_manifest", "legal_samples", "legal_ir_target_snapshot",
             "legal_ir_target_bundle", "modal_autoencoder", "legal_ir_view_vocabulary_diagnostic")
    owners = call("import_current_product_owners", lambda: {name: importlib.import_module(prefix + name) for name in names})
    for name, owner in owners.items():
        path = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / (name + ".py")
        need(Path(owner.__file__).resolve() == path, "product owner imported from a foreign checkout")
        raw = path.read_bytes()
        owner_sources[str(path)] = {"bytes": len(raw), "sha256": sha(raw)}
    ma, diagnostic = owners["modal_autoencoder"], owners["legal_ir_view_vocabulary_diagnostic"]
    selected = metadata("selected_inputs")
    samples = []
    for row in declaration["tuning_rows"]:
        record = call("decode_original_source_record", lambda row=row:
            owners["autoencoder_corpus_manifest"].SourceSampleRecord.from_dict(selected["records"][row["ordinal"]]))
        sample = call("rebuild_original_legal_sample_without_encoder", lambda record=record:
            owners["legal_samples"].build_us_code_sample(**dataclasses.asdict(record.sample)))
        raw = call("serialize_original_legal_sample", lambda sample=sample: sample.to_json().encode("utf-8"))
        need(sample.sample_id == row["sample_id"] and sha(raw) == row["sample_payload_sha256"]
             and len(sample.embedding_vector) == 384, "same retained LegalSample payload or384 embedding differs")
        exports.save(f"sample-{row['ordinal']:02d}.json", raw)
        samples.append(sample)
    config_value = metadata("target_config")
    config = call("load_historical_target_config_without_current_source_scan", lambda:
        owners["legal_ir_target_snapshot"].TargetSnapshotConfig.from_dict(config_value))
    need(config.bridge_names == BRIDGES and config.evaluate_provers is False and config.parallel_workers == 1,
         "original target config execution settings differ")
    hydrated, readbacks = {}, []
    for sample, row in zip(samples, declaration["tuning_rows"], strict=True):
        reference = refs[row["bundle_role"]]
        # Inspect only the bounded plain manifest to pin the recorded expanded shard.
        raw = read(row["bundle_role"])
        magic, length = struct.unpack(">8sQ", raw[:16])
        need(magic == b"LIRTB01\n" and 0 < length <= 4 * MiB, "retained bundle manifest header differs")
        manifest = parse(raw[16:16 + length])
        need(manifest["config"] == config_value and len(manifest["shards"]) == 1,
             "complete retained target configuration or shard population differs")
        shard = manifest["shards"][0]
        need(shard["target_sha256"] == row["expanded_target_sha256"]
             and shard["uncompressed_bytes"] == row["expanded_target_bytes"], "expanded target commitment differs")
        del raw, manifest
        bundle = call("open_original_singleton_target_bundle", lambda reference=reference:
            owners["legal_ir_target_bundle"].load_target_bundle(reference["path"],
                expected_sha256=reference["sha256"], config=config, max_bytes=16 * MiB, max_shard_bytes=64 * MiB))
        try:
            need(bundle.snapshot_id == row["target_snapshot_id"] and bundle.sample_count == 1,
                 "singleton snapshot identity differs")
            targets = call("fully_exhaust_original_target_hydration", lambda:
                bundle.targets_for([sample], config=config))
            need(set(targets) == {sample.sample_id} and bundle.statuses == {sample.sample_id: "ready"}
                 and bundle.statistics["decompressed_shards"] == 1
                 and bundle.statistics["unique_decompressed_shards"] == 1
                 and bundle.statistics["decompressed_bytes"] == row["expanded_target_bytes"],
                 "full requested target is not ready")
            target = targets[sample.sample_id]
            need(target.accepted is True and tuple(target.bridge_names) == BRIDGES
                 and dict(target.view_distribution) == row["target_view_distribution"], "original target supervision differs")
            hydrated.update(targets)
            readbacks.append({"sample_id": sample.sample_id, "original_bundle": reference,
                "snapshot_id": bundle.snapshot_id, "statistics": bundle.statistics,
                "controller_observation": {"requested_targets_fully_exhausted": True,
                    "basis": "existing targets_for successfully returned dict after complete iterator exhaustion"}})
        finally:
            call("close_original_target_bundle", bundle.close)
    payload = call("reduce_supplied_retained_targets_without_bridge_generation", lambda:
        ma._legal_ir_target_payload(samples, bridge_names=BRIDGES, evaluate_provers=False,
                                   legal_ir_targets=hydrated, parallel_workers=1))
    target_rows = [{"sample_id": sample.sample_id, "distribution":
                   payload["target_view_distributions_by_sample"][sample.sample_id]} for sample in samples]
    need([len(row["distribution"]) for row in target_rows] == [4, 6], "original tuning support4/6 differs")
    target_sha = sha(wire(target_rows))
    loss_context = {"target_view_distributions_by_sample": payload["target_view_distributions_by_sample"],
                    "target_losses_by_sample": payload["target_losses_by_sample"],
                    "target_hashes": payload["target_hashes"], "target_count": payload["target_count"]}
    need(payload["target_count"] == 2, "complete retained target reduction required")
    exports.json("row-targets.json", target_rows)
    context_ref = exports.json("target-loss-context.json", loss_context)
    exports.json("target-readbacks.json", readbacks)
    del hydrated, payload, targets, target
    profile = call("build_declared_seven_lane_profile", diagnostic.build_bridge_contract_view_profile)
    profile_sha = call("hash_declared_profile", lambda: diagnostic.view_profile_sha256(profile))
    exports.json("fixed-view-profile.json", profile)
    need(len(profile["labels"]) == 7, "expected seven fixed lanes")
    constructor = metadata("constructor_receipt")["effective_autoencoder_config"]
    need(set(constructor) == set(inspect.signature(ma.AdaptiveModalAutoencoder.__init__).parameters) - {"self", "state"},
         "historical full constructor is incompatible with current ABI")
    need(constructor["compute_device"] == "python" and constructor["max_codec_feature_keys"] == 0
         and all(constructor[key] is None for key in ("feature_codec", "legacy_embedding_adapters", "legacy_distillation_adapters")),
         "historical constructor requires unsupported device, codec or adapter")
    results = []
    evaluator_context_sha256 = None
    for role in ("parent_checkpoint", "structural_checkpoint"):
        data = parse(read(role))
        need(set(data) <= ma.MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS
             and data.get("architecture_version") == "proof_aware_auxiliary_heads_v2"
             and data.get("decoded_embeddings") == {}, "unsupported checkpoint architecture, fields or sample memory")
        widths = set()
        def vector_widths(value):
            if type(value) is dict:
                for child in value.values():
                    vector_widths(child)
            elif type(value) is list:
                need(value and all(type(x) in (int, float) and math.isfinite(x) for x in value), "invalid embedding vector")
                widths.add(len(value))
            else:
                raise ValueError("unsupported embedding weight structure")
        for key, value in data.items():
            if key.endswith("embedding_weights"):
                vector_widths(value)
        need(widths == {384}, "retained checkpoint is not native384")
        state = call("load_exact_" + role, lambda: ma.ModalAutoencoderTrainingState.from_dict(data))
        del data
        model = call("construct_original_python_model_" + role, lambda:
            ma.AdaptiveModalAutoencoder(state=state, **constructor))
        need(model.compute_backend == "python" and model._torch is None and model.compute_device is None,
             "Python numerical backend required")
        call("prime_original_view_and_loss_caches_" + role, lambda:
            model._cache_legal_ir_targets(samples, loss_context["target_view_distributions_by_sample"],
                                         loss_context["target_losses_by_sample"]))
        state_identity = call("capture_state_identity_" + role, model.state.state_identity)
        checkpoint_context = {"ir_family": "legal_ir", "ir_schema_version": "historical-optimizer-bridge-targets/v1",
            "decoder_task": "raw-view-distribution-shadow-diagnostic", "embedding_dimensions": 384,
            "encoder_model": "thenlper/gte-small", "encoder_revision": "17e1f347d17fe144873b1201da91788898c639cd",
            "token_profile": "archived-gte-small-512-no-new-tokenization", "max_tokens": 512,
            "checkpoint_sha256": refs[role]["sha256"]}
        shadow = call("evaluate_fixed_seven_lane_" + role, lambda:
            diagnostic.evaluate_fixed_view_vocabulary(model, samples, target_rows, profile=profile,
                expected_profile_sha256=profile_sha, expected_state_identity=state_identity,
                checkpoint_context=checkpoint_context, expected_targets_sha256=target_sha))
        if evaluator_context_sha256 is None:
            evaluator_context_sha256 = shadow["evaluator_context_sha256"]
        need(shadow["evaluator_context_sha256"] == evaluator_context_sha256,
             "parent and structural retained view/loss contexts differ")
        official_rows = []
        for sample, target_row in zip(samples, target_rows, strict=True):
            prediction = call("existing_dynamic_support_readout_" + role, lambda:
                model._legal_ir_view_distribution(sample, target_row["distribution"], use_sample_memory=False))
            ce = call("existing_clamped_cross_entropy_" + role, lambda:
                ma.cross_entropy_distribution_loss(prediction, target_row["distribution"]))
            official_rows.append({"sample_id": sample.sample_id, "predicted_distribution": prediction,
                "observed_support": list(prediction), "observed_support_count": len(prediction),
                "target_support_count": len(target_row["distribution"]), "cross_entropy": ce,
                "source_namespace": "existing optimizer dynamic state/target support; not fixed-schema CE",
                "probability_floor": 1e-12, "use_sample_memory": False})
        need(call("close_state_identity_" + role, model.state.state_identity) == state_identity
             and model.state.decoded_embeddings == {}, "read-only probe mutated checkpoint or sample memory")
        report = {"schema": SCHEMA, "checkpoint_role": role, "original_checkpoint": refs[role],
            "state_identity": state_identity, "original_full_constructor": constructor,
            "target_rows_sha256": target_sha, "target_loss_context": context_ref,
            "fixed_seven_lane_unclamped": shadow, "existing_dynamic_support_clamped": official_rows,
            "fixed_mean_cross_entropy": shadow["metrics"]["cross_entropy"],
            "existing_mean_cross_entropy": math.fsum(r["cross_entropy"] for r in official_rows) / 2,
            "use_sample_memory": False, "authority": AUTHORITY}
        reference = exports.json(role.replace("_checkpoint", "") + "-shadow-report.json", report)
        results.append({"checkpoint_role": role, "report": reference, "state_identity": state_identity,
                        "fixed_metrics": shadow["metrics"], "existing_dynamic_support_rows": official_rows})
        del model, state, shadow
    custody()
    owner_current()
    exports.verify()
    receipt = {"schema": SCHEMA, "selected_check": SELECTED_CHECK, "all_checks_passed": True,
        "input_descriptor_sha256": options.expected_input_descriptor_sha256, "original_inputs": refs,
        "producer_sources": owner_sources, "driver_sha256": sha(driver_raw), "source_repository": str(ROOT),
        "profile_sha256": profile_sha, "fixed_lane_count": 7, "original_target_support_counts": [4, 6],
        "evaluator_context_sha256": evaluator_context_sha256,
        "target_rows_sha256": target_sha, "target_loss_context_sha256": sha(wire(loss_context)),
        "sample_count": 2, "tuning_ordinals": [6, 7], "partition": "repeated_tuning",
        "independent_holdout": False, "checkpoint_reports": results, "public_operation_calls": calls,
        "new_targets_compiled": 0, "encoder_calls": 0, "training_calls": 0,
        "full_decoder_calls": 0, "solver_or_compiler_calls": 0, "sample_memory_used": False,
        "historical_rejected_view_proposals_rescored": False, "acceptance_criteria_changed": False,
        "checkpoints_or_original_inputs_rewritten": False, "source_cohort_is_complete_import_closure": False,
        "authority": AUTHORITY, "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": ["Two repeatedly inspected tuning rows, not an independent holdout.",
            "Saved parent and accepted structural child only; rejected view candidates retain parent rollback.",
            "Current readout over historical unchanged targets; neither semantic reconstruction nor teacher qualification.",
            "Fixed CE uses log-sum-exp without probability clamping; existing CE retains its existing1e-12 floor.",
            "Declared legacy checkpoint context is not independently authenticated by the diagnostic adapter."],
        "output_byte_limit": MAX_OUTPUT, "outputs": list(exports.rows.values())}
    receipt_ref = exports.json("probe-receipt.json", receipt)
    index_ref = exports.json("file-index.json", {"schema": "retained-fixed-view-file-index/v1",
        "files": list(exports.rows.values()), "self_file": "file-index.json",
        "closed_export_names": sorted([*exports.rows, "file-index.json"]),
        "listed_bytes_excluding_self": exports.total, "aggregate_byte_limit": MAX_OUTPUT})
    exports.verify()
    custody()
    owner_current()
    print(json.dumps({"schema": SCHEMA, "selected_check": SELECTED_CHECK, "all_checks_passed": True,
        "receipt": receipt_ref, "file_index": index_ref, "export_files": len(exports.rows),
        "export_bytes": exports.total, "sample_count": 2, "checkpoint_count": 2,
        "independent_holdout": False, "training_calls": 0, "authority": AUTHORITY}, sort_keys=True))


if __name__ == "__main__":
    main()
