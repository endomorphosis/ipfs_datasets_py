#!/usr/bin/env python3
"""Authenticate retained published component files without parsing tensors.

Run only inside the existing owned-validation attempt.  The resulting publisher
receipt shapes are explicitly derived from historical publication evidence;
this program makes no Hub request and invokes no publisher or model runtime.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

SCHEMA = "legal-ir-published-components-provenance/v1"
AUTH_SCHEMA = "legal-ir-missing-source-components-authentication/v1"
CUSTODY = Path("/home/barberb/lift_coding/artifacts/normative-checkpoint-availability-20261006/registration/custody.py")
CUSTODY_SHA = "c3b355c2b3e4743a839a721b61c1d2868fe25c609b8da562a6b302fbe0cb6864"
MAX_METADATA = 4 * 1024 * 1024
MAX_CHECKPOINT = 32 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
REV = re.compile(r"[0-9a-f]{40}\Z")
LABELS = ("F15", "F17", "F18")
FILES = tuple(label.lower() + "-hub-publication-receipt.json" for label in LABELS)
AUTH_FILE = "published-components-authentication.json"
FALSE = dict(network_verified_current=False, model_loaded=False,
             inference_executed=False, training_executed=False,
             runtime_admitted=False, teacher_qualified=False, proof_authority=False)
BLOCKED = {"ipfs_datasets_py", "ipfs_accelerate_py", "ipfs_kit_py", "torch",
           "transformers", "tensorflow", "sentence_transformers", "huggingface_hub",
           "requests", "httpx", "aiohttp", "boto3", "symai"}


def need(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "duplicate metadata field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite metadata")))


def witness(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def bootstrap_read(path, maximum):
    """Only the descriptor and trusted custody source need this bootstrap read."""
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path,
         "canonical absolute bootstrap file required")
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
         and 0 < before.st_size <= maximum, "bounded regular bootstrap file required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        need(witness(os.fstat(fd)) == witness(before), "bootstrap open changed")
        pieces, total = [], 0
        while True:
            part = os.read(fd, min(65536, maximum + 1 - total))
            if not part:
                break
            pieces.append(part)
            total += len(part)
            need(total <= maximum, "bootstrap grew beyond bound")
        need(total == before.st_size and witness(os.fstat(fd)) == witness(before),
             "bootstrap descriptor changed")
    finally:
        os.close(fd)
    need(witness(path.lstat()) == witness(before) and path.resolve(strict=True) == path,
         "bootstrap path changed")
    raw = b"".join(pieces)
    return {"path": str(path), "bytes": len(raw), "sha256": digest(raw)}, raw, witness(before)


def pin(value, maximum):
    need(type(value) is dict and set(value) == {"path", "bytes", "sha256"}, "closed file pin required")
    need(type(value["path"]) is str and Path(value["path"]).is_absolute()
         and ".." not in Path(value["path"]).parts, "absolute pinned path required")
    need(type(value["bytes"]) is int and 0 < value["bytes"] <= maximum
         and type(value["sha256"]) is str and SHA.fullmatch(value["sha256"]), "bounded file identity required")
    return value


class Output:
    def __init__(self, directory):
        self.path = Path(directory)
        temporary = Path(os.environ.get("TMPDIR", ""))
        need(temporary.is_absolute() and temporary.name == "tmp"
             and temporary.resolve(strict=True) == temporary, "native private TMPDIR required")
        need(self.path == temporary.parent / "exports" and self.path.resolve(strict=True) == self.path,
             "output must be this native attempt's existing exports")
        info = self.path.lstat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and info.st_uid == os.getuid() and not list(self.path.iterdir()), "empty owned0700 exports required")
        self.identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
        self.allowed = {str(self.path / name) for name in (*FILES, AUTH_FILE)}

    def save(self, name, value):
        path = self.path / name
        raw = wire(value)
        need(str(path) in self.allowed and len(raw) <= MAX_OUTPUT, "bounded declared output required")
        info = self.path.lstat()
        need((info.st_dev, info.st_ino, info.st_mode, info.st_uid) == self.identity
             and self.path.resolve(strict=True) == self.path, "output parent changed")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            remaining = memoryview(raw)
            while remaining:
                count = os.write(fd, remaining)
                need(count > 0, "output write made no progress")
                remaining = remaining[count:]
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            after = os.fstat(directory)
            need((after.st_dev, after.st_ino, after.st_mode, after.st_uid) == self.identity,
                 "output parent descriptor changed")
            os.fsync(directory)
        finally:
            os.close(directory)
        return {"path": str(path), "bytes": len(raw), "sha256": digest(raw)}


def install_audit(output):
    need(not any(name.split(".")[0] in BLOCKED for name in sys.modules), "unexpected preloaded product/model")
    def audit(event, args):
        if event == "import" and args[0].split(".")[0] in BLOCKED:
            raise ValueError("product/model/provider import forbidden")
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.fork", "os.forkpty", "os.posix_spawn"}:
            raise ValueError("network or child operation forbidden")
        if event == "open":
            path, mode, flags = args
            writing = ((type(flags) is int and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
                       or (type(mode) is str and any(c in mode for c in "wax+")))
            if writing:
                need(type(path) is str and path in output.allowed, "write outside declared exports forbidden")
    sys.addaudithook(audit)
    sys.dont_write_bytecode = True


def run(provenance_path, expected_sha, output_directory):
    output = Output(output_directory)
    install_audit(output)
    need(type(expected_sha) is str and SHA.fullmatch(expected_sha), "independent provenance SHA required")
    provenance_pin, raw, initial = bootstrap_read(provenance_path, MAX_METADATA)
    need(provenance_pin["sha256"] == expected_sha, "provenance differs from independent pin")
    declaration = parse(raw)
    need(type(declaration) is dict and set(declaration) == {
        "schema", "method", "custody_source", "components", "bounds", "scope", "authority"}
        and declaration["schema"] == SCHEMA and declaration["method"] == "historical-receipt-derivation",
        "closed provenance contract required")
    need(declaration["bounds"] == {"metadata_bytes": MAX_METADATA, "checkpoint_bytes": MAX_CHECKPOINT,
                                  "output_bytes": MAX_OUTPUT} and declaration["authority"] == FALSE,
         "exact bounds and false authority required")
    helper_pin = pin(declaration["custody_source"], MAX_METADATA)
    need(helper_pin["path"] == str(CUSTODY) and helper_pin["sha256"] == CUSTODY_SHA,
         "original trusted custody source required")
    actual, helper_raw, helper_initial = bootstrap_read(CUSTODY, MAX_METADATA)
    need(actual == helper_pin, "custody source differs")
    custody = types.ModuleType("retained_components_checked_custody")
    custody.__file__ = str(CUSTODY)
    exec(compile(helper_raw, str(CUSTODY), "exec", dont_inherit=True), custody.__dict__)
    observed = {str(provenance_path): (provenance_pin, initial), str(CUSTODY): (helper_pin, helper_initial)}
    metadata_pins = []

    def capture(expected, *, retain=False):
        maximum = MAX_METADATA if retain else MAX_CHECKPOINT
        pin(expected, maximum)
        path = Path(expected["path"])
        before = custody.witness(path.lstat())
        result = custody.capture(path, maximum=maximum, retain=retain)
        actual, body = result if retain else (result, None)
        need(actual == expected and custody.witness(path.lstat()) == before, "pinned input changed")
        prior = observed.get(str(path))
        need(prior is None or prior == (actual, before), "conflicting or changed repeated input")
        observed[str(path)] = (actual, before)
        if retain:
            metadata_pins.append(actual)
        return body

    def close_fence():
        for path, (expected, original) in observed.items():
            need(custody.witness(Path(path).lstat()) == original
                 and Path(path).resolve(strict=True) == Path(path), "closing input/source witness changed")
        for expected in metadata_pins:
            need(custody.capture(expected["path"], maximum=MAX_METADATA, retain=False) == expected,
                 "closing metadata/source SHA changed")
        need(custody.capture(provenance_path, maximum=MAX_METADATA, retain=False) == provenance_pin
             and custody.capture(CUSTODY, maximum=MAX_METADATA, retain=False) == helper_pin,
             "closing provenance/custody source changed")

    driver_pin = custody.capture(Path(__file__).resolve(), maximum=MAX_METADATA, retain=False)
    observed[driver_pin["path"]] = (driver_pin, custody.witness(Path(driver_pin["path"]).lstat()))
    metadata_pins.append(driver_pin)
    components = declaration["components"]
    need(type(components) is list and len(components) == 3
         and [c.get("name") for c in components if type(c) is dict] == list(LABELS), "exact ordered three components required")
    prepared = []
    fields = {"name", "checkpoint", "retained_readback", "repository_id", "revision", "path_in_repo",
              "remote_identity", "remote_pointer_blob_sha1", "metadata", "loader_source", "loader_path_in_repo",
              "checkpoint_serialization_schema", "source_parent_checkpoint", "source_parent_model_state_sha256", "classification"}
    for component in components:
        need(set(component) == fields and component["repository_id"] == "Publicus/legal-ir-autoencoder"
             and type(component["revision"]) is str and REV.fullmatch(component["revision"]), "closed immutable component required")
        checkpoint = pin(component["checkpoint"], MAX_CHECKPOINT)
        readback = pin(component["retained_readback"], MAX_CHECKPOINT)
        need((checkpoint["bytes"], checkpoint["sha256"]) == (readback["bytes"], readback["sha256"])
             and checkpoint["path"] != readback["path"], "distinct original/readback of same payload required")
        remote_path = component["path_in_repo"]
        need(type(remote_path) is str and not remote_path.startswith("/") and "\\" not in remote_path
             and all(part not in ("", ".", "..") for part in remote_path.split("/")), "safe relative remote path required")
        need(component["remote_identity"] == {"scheme": "lfs-payload-sha256", "sha256": checkpoint["sha256"],
                                               "bytes": checkpoint["bytes"]}, "exact retained LFS identity required")
        need(type(component["remote_pointer_blob_sha1"]) is str and REV.fullmatch(component["remote_pointer_blob_sha1"]),
             "retained LFS pointer blob identity required")
        metadata = component["metadata"]
        need(type(metadata) is dict and set(metadata) == {"release_manifest", "verification", "independent_review",
                                                         "immutable_snapshot", "training_plan"}, "closed metadata roles required")
        decoded = {role: None if value is None else parse(capture(value, retain=True))
                   for role, value in metadata.items()}
        manifest, verification, review = (decoded[name] for name in ("release_manifest", "verification", "independent_review"))
        need(verification["repo"] == component["repository_id"] and verification["revision"] == component["revision"]
             and verification["all_downloads_byte_exact"] is True and review["passed"] is True
             and review["repository"] == component["repository_id"], "historical publication/readback review differs")
        review_revision = review.get("revision", review.get("immutable_revision", review.get("final_revision")))
        need(review_revision == component["revision"], "independent immutable review revision differs")
        publication_ref = review.get("actual_publication", review.get("publication", review.get("verification")))
        need(publication_ref == metadata["verification"], "review does not bind actual verification bytes")
        rows = [row for row in manifest["files"] if row["destination"] == remote_path]
        need(len(rows) == 1 and rows[0]["source"] == checkpoint
             and verification["downloads"][remote_path] == readback, "original manifest/readback joins differ")
        snapshot = decoded["immutable_snapshot"]
        if snapshot is not None:
            need(component["name"] == "F15" and snapshot["requested_revision"] == snapshot["returned_revision"] == component["revision"]
                 and review["immutable_independent_snapshot"] == metadata["immutable_snapshot"], "independent remote snapshot differs")
            remote = snapshot["files"][remote_path]
        else:
            need(component["name"] in ("F17", "F18"), "F15 independent remote snapshot required")
            remote = verification["final_file_identities"][remote_path]
        need(remote["size"] == remote["lfs"]["size"] == checkpoint["bytes"]
             and remote["lfs"]["sha256"] == checkpoint["sha256"]
             and remote["blob_id"] == component["remote_pointer_blob_sha1"], "raw retained remote identity differs")
        source = pin(component["loader_source"], MAX_METADATA)
        source_raw = capture(source, retain=True)
        source_rows = [row for row in manifest["files"] if row["destination"] == component["loader_path_in_repo"]]
        source_download = verification["downloads"][component["loader_path_in_repo"]]
        need(len(source_rows) == 1 and source_rows[0]["source"] == source
             and (source_download["bytes"], source_download["sha256"]) == (source["bytes"], source["sha256"]),
             "loader source publication join differs")
        constants = [node.value.value for node in ast.parse(source_raw).body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "SCHEMA" for target in node.targets)
                     and isinstance(node.value, ast.Constant)]
        need(constants == [component["checkpoint_serialization_schema"]], "reported loader serialization schema differs")
        parent = decoded["training_plan"] if component["name"] == "F18" else manifest
        parent_key = "source_checkpoint" if component["name"] == "F18" else "source_parent_checkpoint"
        state_key = "source_model_state_sha256" if component["name"] == "F18" else "source_parent_model_state_sha256"
        need(parent[parent_key] == component["source_parent_checkpoint"]
             and parent[state_key] == component["source_parent_model_state_sha256"], "reported parent lineage differs")
        need(component["classification"] == dict(ir_family_id="legal_ir", dimension=None, dimension_role="source_tokens",
            external_lane_binding=None, native_ir_schema_version=None, decoder_profile_id=None, decoder_format_id=None,
            codec_sha256=None, configured_latent_dimension=384, latent_conditioning_enabled=False,
            runtime_ready=False, teacher_qualified=False, proof_authority=False), "detached source-token classification required")
        # These are the only checkpoint-body operations: opaque bounded SHA streams.
        capture(checkpoint, retain=False)
        capture(readback, retain=False)
        prepared.append(component)
    close_fence()
    results = []
    for component, filename in zip(prepared, FILES):
        checkpoint, readback = component["checkpoint"], component["retained_readback"]
        receipt = {"schema": "ir-model-hub-publication-receipt/v1", "repository_id": component["repository_id"],
            "revision": component["revision"], "manifest_pin": component["metadata"]["release_manifest"],
            "files_verified": True, "files": [{"path_in_repo": component["path_in_repo"], "file_pin": readback,
                "bytes": readback["bytes"], "sha256": readback["sha256"], "verified": True,
                "remote_identity": component["remote_identity"]}], "method": "historical-receipt-derivation",
            "provenance_pin": provenance_pin, "historical_metadata_pins": component["metadata"],
            "original_checkpoint_pin": checkpoint, "publisher_invoked": False, "network_verified_current": False,
            "repository_supplied_python_executed": False, "model_restored": False, "checkpoint_tensor_json_parsed": False,
            "verification_scope": "Current opaque original/readback SHA and length, joined to independently pinned historical immutable LFS/publication records; no current HTTP or publisher call.",
            "authority": dict(FALSE)}
        receipt_pin = output.save(filename, receipt)
        results.append({"label": component["name"], "checkpoint_pin": checkpoint, "verified_download_pin": readback,
            "publication_receipt_pin": receipt_pin, "release": {"repository_id": component["repository_id"],
                "revision": component["revision"], "path_in_repo": component["path_in_repo"], "checkpoint_sha256": checkpoint["sha256"]},
            "checkpoint_serialization_schema": component["checkpoint_serialization_schema"], "loader_source_pin": component["loader_source"],
            "source_parent_checkpoint": component["source_parent_checkpoint"],
            "source_parent_model_state_sha256": component["source_parent_model_state_sha256"],
            "configured_latent_dimension": 384, "latent_conditioning_enabled": False,
            "serialization_schema_scope": "Expected by the original pinned loader source; current tensor JSON intentionally not parsed."})
    close_fence()
    authentication = {"schema": AUTH_SCHEMA, "status": "pass", "completed": True,
        "method": "historical-receipt-derivation", "provenance_pin": provenance_pin,
        "custody_source_pin": helper_pin, "driver_pin": driver_pin, "components": results,
        "all_six_payloads_opaque_sha256_verified": True, "opaque_checkpoint_files": 6,
        "opaque_checkpoint_bytes": sum(c[role]["bytes"] for c in prepared for role in ("checkpoint", "retained_readback")),
        "all_closing_witnesses_unchanged": True, "source_and_metadata_pins": metadata_pins,
        "file_witnesses": [{"pin": item[0], "opening_witness": list(item[1]), "closing_witness": list(custody.witness(Path(path).lstat()))}
                           for path, item in sorted(observed.items())],
        "model_restored": False, "checkpoint_tensor_json_parsed": False, "authority": dict(FALSE),
        "scope": "Three retained source-token components only. No live ModelManager import, model/runtime qualification, current Hub refresh, semantic review, teacher promotion, training or Lean. Parent checkpoints are metadata references, not newly authenticated bodies."}
    close_fence()
    output.save(AUTH_FILE, authentication)
    need({p.name for p in output.path.iterdir()} == {*FILES, AUTH_FILE}, "unexpected export population")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--expected-provenance-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args()
    try:
        return run(Path(args.provenance), args.expected_provenance_sha256, Path(args.output_directory))
    except Exception as error:
        print("Published-component authentication refused: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
