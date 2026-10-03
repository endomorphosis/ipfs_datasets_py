"""Pinned, domain-bound distribution of the shared 384D inference packages.

Importing this module performs no model loading or network access. The four
IR packages opt in through ``open_autoencoder``; their symbolic compilers keep
their existing contracts. A generated candidate never acquires proof authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA = "ir-384-hub-package/v1"
DESCRIPTOR_SCHEMA = "ir-384-hub-descriptor/v1"
DOMAINS = ("security_ir", "ui_ux_ir", "intent_ir", "legal_ir")
RUNTIMES = {"legal_ir": "legal_current_v2", **{
    domain: "domain_384_v1" for domain in DOMAINS if domain != "legal_ir"}}
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
EMBEDDING = {"model_id": "thenlper/gte-small",
             "revision": "17e1f347d17fe144873b1201da91788898c639cd", "dimension": 384}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _read(path, expected_sha=None):
    path = Path(path)
    _require(path.is_file() and path.stat().st_size <= MAX_FILE_BYTES, "missing or oversized package file")
    raw = path.read_bytes()
    _require(len(raw) <= MAX_FILE_BYTES, "package file grew past limit")
    if expected_sha is not None:
        _require(SHA.fullmatch(expected_sha) and hashlib.sha256(raw).hexdigest() == expected_sha,
                 "package file SHA256 mismatch")
    return raw


def _name(value):
    _require(type(value) is str and 0 < len(value) <= 256 and "\\" not in value,
             "invalid package path")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and all(part not in {"", ".", ".."} for part in value.split("/")),
             "package paths must be relative without traversal")
    return value


def validate_descriptor(value, *, domain):
    _require(domain in DOMAINS, "unknown IR domain")
    fields = {"schema", "domain_id", "repository_id", "revision", "release_prefix", "manifest_sha256"}
    _require(type(value) is dict and set(value) == fields and value["schema"] == DESCRIPTOR_SCHEMA,
             "closed pinned Hub descriptor required")
    _require(value["domain_id"] == domain, "checkpoint domain mismatch")
    _require(type(value["repository_id"]) is str and re.fullmatch(r"[\w.-]+/[\w.-]+", value["repository_id"]),
             "invalid model repository ID")
    _require(type(value["revision"]) is str and COMMIT.fullmatch(value["revision"]),
             "an immutable full Hub commit is required")
    _require(type(value["manifest_sha256"]) is str and SHA.fullmatch(value["manifest_sha256"]),
             "manifest SHA256 required")
    _require(type(value["release_prefix"]) is str and
             re.fullmatch(r"releases/[a-z0-9][a-z0-9._-]{0,95}", value["release_prefix"]),
             "immutable release prefix required")
    return dict(value)


def validate_manifest(value, *, domain):
    required = {"schema", "domain_id", "dimension", "runtime", "checkpoint_file", "files",
                "embedding", "provenance", "validation", "release_stage", "proof_authority"}
    _require(type(value) is dict and set(value) == required and value["schema"] == SCHEMA,
             "closed 384D package manifest required")
    _require(domain in DOMAINS and value["domain_id"] == domain, "checkpoint domain mismatch")
    _require(type(value["dimension"]) is int and value["dimension"] == 384 and
             value["runtime"] == RUNTIMES[domain], "incompatible architecture or dimension")
    _require(value["embedding"] == EMBEDDING, "incompatible embedding producer")
    _require(value["release_stage"] == "development" and value["proof_authority"] is False,
             "development weights cannot grant proof authority")
    _require(type(value["provenance"]) is dict and type(value["validation"]) is dict,
             "provenance and validation are required")
    files = value["files"]
    _require(type(files) is dict and 1 <= len(files) <= 64 and value["checkpoint_file"] in files,
             "bounded checkpoint file inventory required")
    total = 0
    for name, entry in files.items():
        _name(name)
        _require(name != "manifest.json" and type(entry) is dict and set(entry) == {"sha256", "bytes"},
                 "invalid file inventory")
        _require(type(entry["sha256"]) is str and SHA.fullmatch(entry["sha256"]) and
                 type(entry["bytes"]) is int and 0 < entry["bytes"] <= MAX_FILE_BYTES,
                 "invalid file digest or byte size")
        total += entry["bytes"]
    _require(total <= MAX_PACKAGE_BYTES, "package exceeds byte limit")
    return value


def build_package(domain, checkpoint_path, output_dir, *, provenance, validation, extra_files=None):
    """Create an isolated release; never alter the source checkpoint or a release."""
    _require(domain in DOMAINS, "unknown IR domain")
    destination = Path(output_dir)
    _require(not destination.exists(), "release directory must be new")
    contents = {"checkpoint.json": _read(checkpoint_path)}
    for name, path in (extra_files or {}).items():
        _name(name)
        _require(name not in contents and name != "manifest.json", "duplicate reserved package file")
        contents[name] = _read(path)
    manifest = {"schema": SCHEMA, "domain_id": domain, "dimension": 384,
        "runtime": RUNTIMES[domain], "checkpoint_file": "checkpoint.json",
        "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                  for name, raw in sorted(contents.items())},
        "embedding": dict(EMBEDDING), "provenance": provenance, "validation": validation,
        "release_stage": "development", "proof_authority": False}
    validate_manifest(manifest, domain=domain)
    destination.mkdir(parents=True)
    for name, raw in contents.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (destination / "manifest.json").write_bytes(_raw(manifest))
    return manifest


def verify_package(directory, *, domain, manifest_sha256):
    directory = Path(directory)
    manifest = validate_manifest(json.loads(_read(directory / "manifest.json", manifest_sha256)), domain=domain)
    for name, entry in manifest["files"].items():
        raw = _read(directory / name, entry["sha256"])
        _require(len(raw) == entry["bytes"], "package file byte size mismatch")
    return manifest


def _instantiate(manifest, paths):
    checkpoint = manifest["checkpoint_file"]
    kwargs = {"expected_sha256": manifest["files"][checkpoint]["sha256"]}
    if manifest["runtime"] == "legal_current_v2":
        from .legal_384_package import load_package
        return load_package(paths[checkpoint].resolve(strict=True), **kwargs)
    from ....optimizers.logic_theorem_optimizer.domain_384_autoencoder import load_checkpoint
    return load_checkpoint(paths[checkpoint].resolve(strict=True), expected_domain=manifest["domain_id"], **kwargs)


def open_local_autoencoder(domain, directory, *, manifest_sha256):
    """Load every weight from an integrity-checked, complete local package."""
    manifest = verify_package(directory, domain=domain, manifest_sha256=manifest_sha256)
    paths = {name: Path(directory) / name for name in manifest["files"]}
    return HubAutoencoder(domain, _instantiate(manifest, paths), manifest, None)


def default_descriptor(domain):
    from .published_384_checkpoints import PUBLISHED_384_CHECKPOINTS
    _require(domain in PUBLISHED_384_CHECKPOINTS, "no published checkpoint registered for domain")
    return validate_descriptor(PUBLISHED_384_CHECKPOINTS[domain], domain=domain)


def open_autoencoder(domain, *, descriptor=None, cache_dir=None, local_files_only=False):
    """Load the registered immutable release, optionally entirely from HF cache."""
    selection = validate_descriptor(descriptor if descriptor is not None else default_descriptor(domain), domain=domain)
    from huggingface_hub import hf_hub_download
    def fetch(name):
        return Path(hf_hub_download(repo_id=selection["repository_id"], repo_type="model",
            revision=selection["revision"], filename=selection["release_prefix"] + "/" + name,
            cache_dir=cache_dir, local_files_only=local_files_only))
    manifest = validate_manifest(json.loads(_read(fetch("manifest.json"), selection["manifest_sha256"])), domain=domain)
    paths = {}
    for name, entry in manifest["files"].items():
        path = fetch(name)
        _require(len(_read(path, entry["sha256"])) == entry["bytes"], "package byte size mismatch")
        paths[name] = path
    return HubAutoencoder(domain, _instantiate(manifest, paths), manifest, selection)


class HubAutoencoder:
    """A real loaded runtime, with its release identity exposed to callers."""
    def __init__(self, domain, runtime, manifest, descriptor):
        self.domain = domain
        self.runtime = runtime
        self.manifest = manifest
        self.descriptor = descriptor

    def describe(self):
        return {"domain_id": self.domain, "dimension": 384, "checkpoint": self.descriptor,
                "runtime": self.runtime.describe(), "release_stage": "development", "proof_authority": False}

    def infer(self, rows, **options):
        """Run loaded numerical weights; rows carry explicit 384D embeddings."""
        return self.runtime.infer(rows, **options)

    def infer_texts(self, texts, *, snapshot_path=None, **options):
        """Source → pinned GTE-small → loaded domain decoder; no LLM fallback."""
        from .source_embeddings_384 import embed_texts
        vectors = embed_texts(texts, snapshot_path=snapshot_path)
        rows = [{"id": "input-" + str(index), "source_text": text, "embedding": vector}
                for index, (text, vector) in enumerate(zip(texts, vectors))]
        return self.infer(rows, **options)


def publish_package(directory, *, domain, repository_id, release_id, model_card):
    """Publish a new public development release and return a full-commit pin.

    Calling this is an explicit publication action; no import/inference path
    invokes it. Release files are append-only and an existing prefix is refused.
    """
    prefix = "releases/" + release_id
    descriptor = {"schema": DESCRIPTOR_SCHEMA, "domain_id": domain, "repository_id": repository_id,
                  "revision": "0" * 40, "release_prefix": prefix,
                  "manifest_sha256": hashlib.sha256(_read(Path(directory) / "manifest.json")).hexdigest()}
    validate_descriptor(descriptor, domain=domain)
    manifest = verify_package(directory, domain=domain, manifest_sha256=descriptor["manifest_sha256"])
    # Validate inference loading before any external write.
    open_local_autoencoder(domain, directory, manifest_sha256=descriptor["manifest_sha256"])
    _require(type(model_card) is str and model_card.strip(), "model card required")
    from huggingface_hub import HfApi, CommitOperationAdd
    api = HfApi()
    api.create_repo(repository_id, repo_type="model", private=False, exist_ok=True)
    info = api.model_info(repository_id)
    _require(info.private is False, "repository visibility differs from authorized public release")
    existing = api.list_repo_files(repository_id, repo_type="model", revision=info.sha)
    _require(not any(name == prefix or name.startswith(prefix + "/") for name in existing),
             "release prefix already exists; use a new release ID")
    operations = [CommitOperationAdd(path_in_repo=prefix + "/" + name,
                  path_or_fileobj=str(Path(directory) / name)) for name in ["manifest.json", *manifest["files"]]]
    operations.append(CommitOperationAdd(path_in_repo=prefix + "/README.md", path_or_fileobj=model_card.encode()))
    # Preserve an existing repository card, which may describe older architectures.
    if "README.md" not in existing:
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=model_card.encode()))
    commit = api.create_commit(repository_id, repo_type="model", parent_commit=info.sha,
        commit_message="Publish " + domain + " 384D development checkpoint " + release_id, operations=operations)
    descriptor["revision"] = commit.oid
    return validate_descriptor(descriptor, domain=domain)


def open_ir_cell_autoencoder(directory_plan_pin, inventory_pins, request, *, package_manifest_pin,
                            cache_split, row_ids, max_reference_bytes=512 * 1024 * 1024):
    """Opt in to exact-cell experimental cached replay, without Hub/default lookup.

    All bindings and target-free cached inputs authenticate before fixed existing
    runtime loading. Loading may execute the Legal package fixture; numerical
    qualification and runtime release admission remain separate operations.
    """
    from .ir_cell_runtime import _open_ir_cell_autoencoder
    return _open_ir_cell_autoencoder(directory_plan_pin, inventory_pins, request,
        package_manifest_pin=package_manifest_pin, cache_split=cache_split,
        row_ids=row_ids, max_reference_bytes=max_reference_bytes)


def preflight_ir_cell_cached_targets(directory_plan_pin, inventory_pins, request, *, package_manifest_pin,
                                    cache_split, row_ids, max_reference_bytes=512 * 1024 * 1024):
    """Evaluate stored canonical target coverage without loading a model.

    Explicit original asset/row bindings are required. Targets stay inside the
    evaluator; lexical coverage grants no grammar, quality or teacher status.
    """
    from .ir_cell_target_compatibility import preflight_ir_cell_cached_targets as preflight
    return preflight(directory_plan_pin, inventory_pins, request,
        package_manifest_pin=package_manifest_pin, cache_split=cache_split,
        row_ids=row_ids, max_reference_bytes=max_reference_bytes)


def open_ir_original_corpus_autoencoder(directory_plan_pin, inventory_pins, request, *, package_manifest_pin,
        corpus_pin, corpus_split, row_ids, max_reference_bytes=512 * 1024 * 1024):
    """Opt in to exact original Intent/Security package corpus replay.

    Fixed checkpoint fitting manifests and original source/vector identities
    authenticate before loading. Targets and native evidence are never inputs.
    """
    from .ir_original_corpus_runtime import _open_ir_original_corpus_autoencoder
    return _open_ir_original_corpus_autoencoder(directory_plan_pin, inventory_pins, request,
        package_manifest_pin=package_manifest_pin, corpus_pin=corpus_pin,
        corpus_split=corpus_split, row_ids=row_ids, max_reference_bytes=max_reference_bytes)
