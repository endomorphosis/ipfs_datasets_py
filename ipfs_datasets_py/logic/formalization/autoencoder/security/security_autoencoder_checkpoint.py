"""Portable seven-tensor security advisory model and source-bound frozen inference.

Only export opens the independently validated historical training bundle.
Loading and inference consume inert JSON, current admitted sources and installed
inference code. They never load the teacher, optimizer, original repository,
canonical CVE export or modal trainer. Scores confer no program authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time

from . import security_autoencoder_features as projection

DOMAIN = "security-code@1"
SCHEMA = "security-autoencoder-package-descriptor@1"
RELEASE_SCHEMA = "security-autoencoder-release@1"
INFERENCE_SCHEMA = "security-autoencoder-source-inference@1"
NATIVE_FEATURE_SCHEMA = "python-ast-control-flow-features-v1"
PACKAGE_FILES = frozenset({"checkpoint.json", "config.json", "vocabularies.json", "lineage.json",
    "checkpoint-manifest.json", "inference-fixture.json", "release-manifest.json", "README.md", "provenance-review.json"})
DESCRIPTOR_FIELDS = frozenset({"schema", "domain", "output", "manifest_sha256", "checkpoint_sha256",
    "checkpoint_id", "native_manifest_digest", "feature_schema_version", "authority", "mode",
    "training_steps", "provider_calls", "download_calls"})
TENSOR_NAMES = ("encoder_weight", "encoder_bias", "decoder_weight", "decoder_bias",
                "lexical_embedding", "security_head_weight", "security_head_bias")
MAX_BYTES = 8_000_000
MAX_SOURCE_BYTES = 4_000_000
AUTHORITY = {"authority": "unverified_candidate_only", "omission_authority": False,
    "proof_authority": False, "formalization_authority": False, "execution_authority": False,
    "completion_authority": False}
_HASH = re.compile(r"[a-f0-9]{64}")
_TOKEN = re.compile(r"token:[a-z0-9]{3,128}")
_CWE = re.compile(r"cwe:CWE-[1-9][0-9]{0,6}")
_PREFIX = ["effect:audit", "classification_only", "polarity:vulnerable", "unknown_cwe"]
_FORBIDDEN = {"legal-ir", "legal_ir", "legalir", "shared-weights", "shared_weights"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate security package JSON key")
        result[key] = value
    return result


def _decode(raw):
    def invalid(value):
        raise ValueError("nonfinite security package JSON number")
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=invalid)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid bounded security JSON") from error


def _read(path, maximum=MAX_BYTES):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("canonical security artifact path required")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError("bounded single-link regular security artifact required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    current = path.stat()
    if len(raw) > maximum or any(getattr(before, k) != getattr(after, k) or getattr(after, k) != getattr(current, k) for k in fields):
        raise ValueError("security artifact changed during read")
    return raw


def _namespace(path, *, fresh=False, excluded=()):
    path = Path(path)
    if (not path.is_absolute() or path.resolve() != path or (fresh and path.exists())
            or any(part.lower() in _FORBIDDEN for part in path.parts)
            or any(path == item or path.is_relative_to(item) for item in excluded)):
        raise ValueError("isolated canonical security namespace required")
    return path


def _write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        os.fchmod(stream.fileno(), 0o444)
        stream.flush()
        os.fsync(stream.fileno())


def _digest(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ValueError("exact security SHA256 digest required")
    return value


def _config(latent):
    return {"schema": "security-autoencoder-inference-config@1", "domain": DOMAIN,
        "architecture": "lexical-fork-tanh-code-autoencoder@1", "inference_version": "security-frozen-inference@1",
        "dtype": "float64", "input_width": len(projection.FEATURES), "latent_width": latent,
        "feature_schema_version": projection.FEATURE_SCHEMA,
        "normalization": "log1p counts, per-function L2 normalization", "tokenizer": projection.TOKENIZER,
        "inference_implementation_sha256": _sha(Path(__file__).read_bytes()),
        "feature_implementation_sha256": _sha(Path(projection.__file__).read_bytes()),
        "head": "security_ir_audit_cwe_polarity_candidates@1", "output_role": "advisory_classification_candidates_only",
        "scores_are_calibrated_probabilities": False, "learned_formula_head": False,
        "learned_premise_ranker": False, "tla_projection": "unsupported", "supported_modes": ["frozen_inference"],
        **AUTHORITY}


def _native_manifest(checkpoint_sha, config, vocabulary, lineage):
    from ipfs_datasets_py.logic.formalization.checkpoints import CheckpointManifest
    return CheckpointManifest(checkpoint_id="security:" + checkpoint_sha,
        domain="security", head_id="security:audit-cwe-polarity-candidates", model_id="security:lexical-code-advisory",
        model_version="security-frozen-inference-v1", weights_digest="sha256:" + checkpoint_sha,
        training_config_identity="sha256:" + _sha(_json(lineage["training"])),
        ontology_identity="sha256:" + _sha(_json(vocabulary["targets"])),
        view_registry_identity="sha256:" + _sha(_json({"head": config["head"], "formula_views": []})),
        feature_schema_version=NATIVE_FEATURE_SCHEMA, metadata={
            "runtime_domain_adapter": DOMAIN, "role": "advisory_classification_candidates_only",
            "runtime_feature_schema_adapter": projection.FEATURE_SCHEMA,
            "model_scope": "benchmark_informed_development", "holdout_evaluated": False,
            "proof_authority": False, "formalization_authority": False})


def _validate_payload(checkpoint, config, vocabulary, lineage):
    if (type(config) is not dict or type(config.get("latent_width")) is not int
            or not 2 <= config["latent_width"] <= 16 or not _numerically_equal(config, _config(config["latent_width"]))):
        raise ValueError("security inference architecture, implementation or namespace differs")
    if type(vocabulary) is not dict or set(vocabulary) != {"schema", "domain", "features", "lexical_keys", "targets"}:
        raise ValueError("closed security vocabularies required")
    keys, targets = vocabulary["lexical_keys"], vocabulary["targets"]
    if (vocabulary["schema"] != "security-autoencoder-vocabularies@1" or vocabulary["domain"] != DOMAIN
            or vocabulary["features"] != list(projection.FEATURES)
            or type(keys) is not list or not 1 <= len(keys) <= 8192
            or any(type(key) is not str or not _TOKEN.fullmatch(key) for key in keys)
            or keys != sorted(set(keys)) or type(targets) is not list or not 5 <= len(targets) <= 68
            or targets[:4] != _PREFIX or any(type(key) is not str or not _CWE.fullmatch(key) for key in targets[4:])
            or targets[4:] != sorted(set(targets[4:]))):
        raise ValueError("ordered security vocabulary identities differ")
    if (type(checkpoint) is not dict or set(checkpoint) != {"schema", "domain", "dtype", "tensors"}
            or checkpoint["schema"] != "security-autoencoder-portable-weights@1" or checkpoint["domain"] != DOMAIN
            or checkpoint["dtype"] != "float64" or type(checkpoint["tensors"]) is not dict
            or set(checkpoint["tensors"]) != set(TENSOR_NAMES)):
        raise ValueError("exact seven float64 security tensors required")
    width, latent = len(projection.FEATURES), config["latent_width"]
    shapes = ((width, latent), (latent,), (latent, width), (width,), (len(keys), latent), (latent, len(targets)), (len(targets),))
    def tensor(value, shape):
        if type(value) is not list or len(value) != shape[0]:
            raise ValueError("security tensor dimensions differ")
        if len(shape) > 1:
            for row in value:
                tensor(row, shape[1:])
        elif any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e100 for v in value):
            raise ValueError("finite bounded float64 tensor values required")
    for name, shape in zip(TENSOR_NAMES, shapes):
        tensor(checkpoint["tensors"][name], shape)
    fields = {"schema", "domain", "training_checkpoint_sha256", "training_receipt_sha256", "parent_initializer_sha256",
        "parent_initializer_manifest_sha256", "legal_source_checkpoint_sha256", "transferred_rows_sha256",
        "trained_lexical_rows_sha256", "canonical_export_manifest_sha256", "training", "parent_fit_metadata",
        "model_scope", "holdout_evaluated", "teacher_included", "optimizer_included", "task_source_included"}
    if (type(lineage) is not dict or set(lineage) != fields or lineage["schema"] != "security-autoencoder-lineage@1"
            or lineage["domain"] != DOMAIN or lineage["model_scope"] != "benchmark_informed_development"
            or lineage["parent_fit_metadata"] != "not available in parent checkpoint"
            or any(lineage[k] is not False for k in ("holdout_evaluated", "teacher_included", "optimizer_included", "task_source_included"))):
        raise ValueError("closed source-free development lineage required")
    for key in fields:
        if key.endswith("sha256"):
            _digest(lineage[key])
    if lineage["trained_lexical_rows_sha256"] != _sha(_json(checkpoint["tensors"]["lexical_embedding"])):
        raise ValueError("trained lexical lineage differs")
    training = lineage["training"]
    if (type(training) is not dict or set(training) != {"epochs", "seed", "sample_count", "security_pair_count",
            "max_functions", "before_reconstruction_loss", "after_reconstruction_loss", "before_security_bce",
            "after_security_bce", "historical_learning_rate", "scope", "holdout_evaluated"}
            or training["scope"] != "transductive_admitted_code_functions_and_bounded_CVE_pairs"
            or training["historical_learning_rate"] != "not recorded in training receipt"
            or training["holdout_evaluated"] is not False):
        raise ValueError("closed recorded training configuration required")
    for key, lower, upper in (("epochs", 1, 32), ("seed", 0, 2**31-1), ("sample_count", 1, 1024),
                              ("security_pair_count", 2, 8), ("max_functions", 1, 1024)):
        if type(training[key]) is not int or not lower <= training[key] <= upper:
            raise ValueError("recorded security training bound differs")
    for key in ("before_reconstruction_loss", "after_reconstruction_loss", "before_security_bce", "after_security_bce"):
        if type(training[key]) not in (int, float) or not math.isfinite(training[key]) or training[key] < 0:
            raise ValueError("finite recorded training metric required")


def _score(loaded, observations):
    """No initialization or training, including on empty/OOV lexical vectors."""
    import torch
    keys = loaded["vocabularies"]["lexical_keys"]
    if type(observations) is not list or not 1 <= len(observations) <= 1024:
        raise ValueError("bounded authored or source-bound observation list required")
    for row in observations:
        if type(row) is not dict or set(row) != {"features", "lexical_indices"}:
            raise ValueError("closed security numeric observation required")
        features, indices = row["features"], row["lexical_indices"]
        if (type(features) is not list or len(features) != len(projection.FEATURES)
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in features)
                or type(indices) is not list or len(indices) > 40
                or any(type(i) is not int or not 0 <= i < len(keys) for i in indices)
                or indices != sorted(set(indices))):
            raise ValueError("finite exact security features and lexical indices required")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        with torch.no_grad():
            parameters = [torch.tensor(loaded["checkpoint"]["tensors"][name], dtype=torch.float64, device="cpu") for name in TENSOR_NAMES]
            data = torch.tensor([row["features"] for row in observations], dtype=torch.float64)
            lexical = torch.zeros((len(observations), len(keys)), dtype=torch.float64)
            for index, row in enumerate(observations):
                if row["lexical_indices"]:
                    lexical[index, row["lexical_indices"]] = 1.0 / math.sqrt(len(row["lexical_indices"]))
            latent = torch.tanh(data @ parameters[0] + parameters[1] + lexical @ parameters[4])
            decoded = latent @ parameters[2] + parameters[3]
            logits = latent @ parameters[5] + parameters[6]
            scores = torch.sigmoid(logits)
            errors = (decoded - data).square().mean(dim=1)
            if any(not torch.isfinite(t).all() for t in (latent, logits, scores, errors)):
                raise ValueError("nonfinite security frozen inference")
            rows = [{"latent": z, "scores": s, "logits": l, "reconstruction_error": e}
                for z, s, l, e in zip(latent.tolist(), scores.tolist(), logits.tolist(), errors.tolist())]
    finally:
        torch.set_num_threads(previous)
    return {"rows": rows, "target_vocabulary": loaded["vocabularies"]["targets"],
        "source_binding": "not_established_by_vector_probe", "scores_are_calibrated_probabilities": False,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0, **AUTHORITY}


def _review(review, card, lineage, vocabulary):
    """Accept only explicit bounded documentation, never inferred clearance."""
    from ..source_screening import _contains_secret
    if (type(card) is not str or not card.strip() or len(card.encode()) > 32_768
            or "\0" in card or _contains_secret(card.encode())):
        raise ValueError("bounded screened explicit security model card required")
    if type(review) is not dict or len(_json(review)) > 32_768 or _contains_secret(_json(review)):
        raise ValueError("bounded screened source-free provenance review required")
    local = {"schema": "security-autoencoder-local-provenance@1", "status": "not_reviewed_for_publication",
        "publication_authority": False, "model_scope": "benchmark_informed_development"}
    if _numerically_equal(review, local):
        return
    fields = {"schema", "bottle_training_input", "formal_capabilities", "license_statement", "parent_initializer",
        "proposed_repository", "release_exclusions", "release_kind", "remote_evidence", "requested_visibility",
        "review_status", "security_training", "source_components"}
    if (set(review) != fields or review["schema"] != "security-autoencoder-public-provenance-review@1"
            or review["requested_visibility"] != "public" or review["review_status"] != "reviewed_with_explicit_lineage_limits"
            or review["release_kind"] != "experimental_benchmark_informed_development"):
        raise ValueError("closed explicit public provenance review required")
    parent, trained, source = review["parent_initializer"], review["security_training"], review["bottle_training_input"]
    if (type(parent) is not dict or set(parent) != {"initializer_sha256", "original_fit_history_known",
            "original_training_metadata_available", "source_checkpoint_sha256", "standalone_weight_license_declared", "transferred_component"}
            or parent["initializer_sha256"] != lineage["parent_initializer_sha256"]
            or parent["source_checkpoint_sha256"] != lineage["legal_source_checkpoint_sha256"]
            or any(parent[k] is not False for k in ("original_fit_history_known", "original_training_metadata_available", "standalone_weight_license_declared"))
            or type(trained) is not dict or set(trained) != {"canonical_export_manifest_sha256", "checkpoint_sha256",
                "dataset_family_exclusions", "epochs", "external_pairs", "head_target_vocabulary", "held_out_evaluation", "task_functions"}
            or trained["canonical_export_manifest_sha256"] != lineage["canonical_export_manifest_sha256"]
            or trained["checkpoint_sha256"] != lineage["training_checkpoint_sha256"]
            or trained["head_target_vocabulary"] != vocabulary["targets"] or trained["held_out_evaluation"] is not False
            or any(type(trained[k]) is not int or trained[k] != lineage["training"][other]
                   for k, other in (("epochs", "epochs"), ("external_pairs", "security_pair_count"), ("task_functions", "sample_count")))
            or type(source) is not dict or set(source) != {"header_copyright", "header_license", "raw_source_in_release", "source_sha256"}
            or source["raw_source_in_release"] is not False):
        raise ValueError("public provenance review differs from trained lineage or preserves unsupported claims")
    _digest(source["source_sha256"])
    # Descriptive review fields remain human-reviewed statements; their exact
    # bytes are pinned, and no remote license/clearance is inferred at load.
    def bounded(value, depth=0):
        if depth > 5:
            raise ValueError("provenance nesting exceeds bound")
        if type(value) is str:
            if len(value.encode()) > 4096 or "\0" in value:
                raise ValueError("provenance text exceeds bound")
        elif type(value) is list:
            if len(value) > 32:
                raise ValueError("provenance list exceeds bound")
            for row in value:
                bounded(row, depth + 1)
        elif type(value) is dict:
            if len(value) > 32 or any(type(k) is not str for k in value):
                raise ValueError("provenance mapping exceeds bound")
            for row in value.values():
                bounded(row, depth + 1)
        elif type(value) not in (bool, int) and value is not None:
            raise ValueError("unsupported provenance value")
    bounded(review)
    for row in review["remote_evidence"]:
        if (type(row) is not dict or set(row) not in ({"bytes", "name", "selected_license_lines", "sha256", "status", "url"},
                {"bytes", "name", "revision", "sha256", "status", "url"}) or row["status"] != "read"):
            raise ValueError("closed remote provenance reference required")
        _digest(row["sha256"])
    for row in review["source_components"]:
        if type(row) is not dict or set(row) != {"license_sha256", "observed_repository_license", "repository_url", "scope"}:
            raise ValueError("closed component attribution required")
        _digest(row["license_sha256"])


def _descriptor(package, manifest_raw, payloads, native):
    return {"schema": SCHEMA, "domain": DOMAIN, "output": str(package),
        "manifest_sha256": _sha(manifest_raw), "checkpoint_sha256": _sha(payloads["checkpoint.json"]),
        "checkpoint_id": native.checkpoint_id, "native_manifest_digest": native.digest,
        "feature_schema_version": projection.FEATURE_SCHEMA, "authority": "unverified_candidate_only",
        "mode": "frozen_inference", "training_steps": 0, "provider_calls": 0, "download_calls": 0}


def load_security_checkpoint(package: Path, *, expected_manifest_sha256: str) -> dict:
    """Load only a pinned, complete inert release; replay its numerical fixture."""
    package = _namespace(Path(package))
    _digest(expected_manifest_sha256)
    if {path.name for path in package.iterdir()} != PACKAGE_FILES:
        raise ValueError("security package contains missing or unapproved files")
    manifest_raw = _read(package / "release-manifest.json", 32_768)
    if _sha(manifest_raw) != expected_manifest_sha256:
        raise ValueError("security release manifest digest differs")
    manifest = _decode(manifest_raw)
    if (type(manifest) is not dict or set(manifest) != {"schema", "domain", "files", "authority", "model_scope", "holdout_evaluated"}
            or manifest["schema"] != RELEASE_SCHEMA or manifest["domain"] != DOMAIN
            or manifest["authority"] != "unverified_candidate_only" or manifest["model_scope"] != "benchmark_informed_development"
            or manifest["holdout_evaluated"] is not False or type(manifest["files"]) is not dict
            or set(manifest["files"]) != PACKAGE_FILES - {"release-manifest.json"}):
        raise ValueError("closed security release manifest required")
    raw, total = {}, len(manifest_raw)
    for name, entry in manifest["files"].items():
        if (type(entry) is not dict or set(entry) != {"sha256", "bytes"}
                or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= MAX_BYTES):
            raise ValueError("bounded exact security payload ledger required")
        _digest(entry["sha256"])
        raw[name] = _read(package / name)
        total += len(raw[name])
        if len(raw[name]) != entry["bytes"] or _sha(raw[name]) != entry["sha256"] or total > MAX_BYTES:
            raise ValueError("security payload digest or size differs")
    payload = {name: _decode(value) for name, value in raw.items() if name != "README.md"}
    card = raw["README.md"].decode("utf-8")
    checkpoint, config, vocabulary, lineage = (payload[name] for name in
        ("checkpoint.json", "config.json", "vocabularies.json", "lineage.json"))
    _validate_payload(checkpoint, config, vocabulary, lineage)
    _review(payload["provenance-review.json"], card, lineage, vocabulary)
    native = _native_manifest(_sha(raw["checkpoint.json"]), config, vocabulary, lineage)
    from ipfs_datasets_py.logic.formalization.checkpoints import CheckpointManifest
    observed = CheckpointManifest.from_dict(payload["checkpoint-manifest.json"])
    observed.require_compatible(domain="security", ontology_identity=native.ontology_identity,
        view_registry_identity=native.view_registry_identity, feature_schema_version=NATIVE_FEATURE_SCHEMA)
    if not _numerically_equal(observed.to_dict(), native.to_dict()):
        raise ValueError("security native manifest identity or lineage differs")
    loaded = {"descriptor": _descriptor(package, manifest_raw, raw, native), "manifest": manifest,
        "checkpoint": checkpoint, "config": config, "vocabularies": vocabulary, "lineage": lineage,
        "native_manifest": native.to_dict(), "inference_fixture": payload["inference-fixture.json"],
        "provenance_review": payload["provenance-review.json"], "model_card": card}
    fixture = loaded["inference_fixture"]
    if (type(fixture) is not dict or set(fixture) != {"schema", "observations", "results"}
            or fixture["schema"] != "security-autoencoder-numeric-fixture@1"
            or fixture["observations"] != _fixture_observations(len(vocabulary["lexical_keys"]))
            or not _numerically_equal(_score(loaded, fixture["observations"]), fixture["results"])):
        raise ValueError("security authored numerical inference fixture differs")
    # File replacement during CPU inference cannot silently change the package.
    if _read(package / "release-manifest.json", 32_768) != manifest_raw:
        raise ValueError("security manifest changed during validation")
    for name, value in raw.items():
        if _read(package / name) != value:
            raise ValueError("security payload changed during validation")
    return loaded


def _numerically_equal(actual, expected):
    if type(actual) is float and type(expected) in (int, float):
        return math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-14)
    if type(actual) is dict:
        return type(expected) is dict and set(actual) == set(expected) and all(_numerically_equal(v, expected[k]) for k, v in actual.items())
    if type(actual) is list:
        return type(expected) is list and len(actual) == len(expected) and all(_numerically_equal(a, b) for a, b in zip(actual, expected))
    return type(actual) is type(expected) and actual == expected


def _fixture_observations(lexical_size):
    width = len(projection.FEATURES)
    return [{"features": [0.0] * width, "lexical_indices": []},
            {"features": [1.0] + [0.0] * (width - 1), "lexical_indices": [0]},
            {"features": [1.0 / math.sqrt(width)] * width, "lexical_indices": sorted({0, lexical_size - 1})}]


def _load_descriptor(descriptor):
    if type(descriptor) is not dict or set(descriptor) != DESCRIPTOR_FIELDS:
        raise ValueError("closed independently selected security checkpoint descriptor required")
    loaded = load_security_checkpoint(Path(descriptor["output"]), expected_manifest_sha256=descriptor["manifest_sha256"])
    if not _numerically_equal(loaded["descriptor"], descriptor):
        raise ValueError("security checkpoint descriptor differs from pinned package")
    return loaded


def score_security_observations(*, checkpoint: dict, observations: list[dict]) -> dict:
    """Numerical availability probe; raw vectors establish no source identity."""
    return _score(_load_descriptor(checkpoint), observations)


def export_security_checkpoint(*, repository: Path, expected_receipt: dict, output: Path,
                               provenance_review: dict | None = None, model_card: str | None = None) -> dict:
    from . import codebase_autoencoder as training
    from .codebase_autoencoder_transfer import validate_legal_shared_weight_fork
    repository = Path(repository).absolute()
    old = Path(expected_receipt["output"])
    output = _namespace(Path(output), fresh=True, excluded=(repository, old))
    training.validate_codebase_autoencoder(repository=repository, expected_receipt=expected_receipt)
    original = {name: _read(old / name) for name in ("checkpoint.json", "features.json", "receipt.json", "index.json")}
    trained, receipt, features = (_decode(original[name]) for name in ("checkpoint.json", "receipt.json", "features.json"))
    if "security_candidate_projection" not in trained or len(trained["weights"]) != 7:
        raise ValueError("portable security export requires the independently validated supervised seven-tensor fork")
    initializer = validate_legal_shared_weight_fork(expected_receipt=expected_receipt["weight_transfer"])
    projection.assert_native_tokenizer_compatible()
    if tuple(training.FEATURES) != projection.FEATURES:
        raise ValueError("native AST feature vocabulary differs from portable projection")
    ledger = _ledger(receipt["source_hashes"])
    sources = _sources(repository, ledger)
    rows, unsupported = projection.source_features(sources, receipt["paths"], keys=initializer["keys"], max_functions=receipt["max_functions"])
    if rows != features["rows"] or [row for row in unsupported if row["reason"] != "non_python_source"] != features["unsupported"]:
        raise ValueError("portable source feature semantics differ from validated training observations")
    checkpoint = {"schema": "security-autoencoder-portable-weights@1", "domain": DOMAIN,
        "dtype": "float64", "tensors": dict(zip(TENSOR_NAMES, trained["weights"]))}
    config = _config(trained["latent_width"])
    vocabulary = {"schema": "security-autoencoder-vocabularies@1", "domain": DOMAIN,
        "features": list(projection.FEATURES), "lexical_keys": initializer["keys"],
        "targets": trained["security_candidate_projection"]["target_vocabulary"]}
    metrics, parent = receipt["metrics"], expected_receipt["weight_transfer"]
    security = metrics["security_candidate_training"]
    lineage = {"schema": "security-autoencoder-lineage@1", "domain": DOMAIN,
        "training_checkpoint_sha256": receipt["checkpoint_sha256"], "training_receipt_sha256": expected_receipt["receipt_sha256"],
        "parent_initializer_sha256": parent["initializer_sha256"], "parent_initializer_manifest_sha256": parent["manifest_sha256"],
        "legal_source_checkpoint_sha256": parent["source_checkpoint_sha256"],
        "transferred_rows_sha256": metrics["weight_transfer"]["transferred_weights_sha256"],
        "trained_lexical_rows_sha256": metrics["weight_transfer"]["trained_transferred_weights_sha256"],
        "canonical_export_manifest_sha256": expected_receipt["canonical_cve_training"]["manifest_sha256"],
        "training": {"epochs": metrics["epochs"], "seed": metrics["seed"], "sample_count": receipt["sample_count"],
            "security_pair_count": security["sample_count"], "max_functions": receipt["max_functions"],
            "before_reconstruction_loss": metrics["before_reconstruction_loss"], "after_reconstruction_loss": metrics["after_reconstruction_loss"],
            "before_security_bce": security["before"]["training_bce"], "after_security_bce": security["after"]["training_bce"],
            "historical_learning_rate": "not recorded in training receipt",
            "scope": "transductive_admitted_code_functions_and_bounded_CVE_pairs", "holdout_evaluated": False},
        "parent_fit_metadata": "not available in parent checkpoint", "model_scope": "benchmark_informed_development",
        "holdout_evaluated": False, "teacher_included": False, "optimizer_included": False, "task_source_included": False}
    _validate_payload(checkpoint, config, vocabulary, lineage)
    if (provenance_review is None) != (model_card is None):
        raise ValueError("explicit provenance review and model card must be supplied together")
    if provenance_review is None:
        provenance_review = {"schema": "security-autoencoder-local-provenance@1", "status": "not_reviewed_for_publication",
            "publication_authority": False, "model_scope": "benchmark_informed_development"}
        model_card = ("# Security advisory development checkpoint\n\n"
            "This benchmark-informed development model predicts uncalibrated audit/CWE/polarity candidates. "
            "It has no held-out evaluation, formula decoder, learned program semantics or proof authority. "
            "Original parent fit metadata is unavailable. This local package has not been reviewed for publication.\n")
    _review(provenance_review, model_card, lineage, vocabulary)
    loaded = {"checkpoint": checkpoint, "config": config, "vocabularies": vocabulary}
    observed = _score(loaded, [{"features": row["features"], "lexical_indices": row["lexical_indices"]} for row in rows])
    old_index = _decode(original["index.json"])
    ranks = {row["row_id"]: row for row in old_index["ranks"]}
    scores = {row["row_id"]: row["scores"] for row in old_index["security_candidate_nominations"]["rows"]}
    for row, value in zip(rows, observed["rows"]):
        if not _numerically_equal({"latent": value["latent"], "reconstruction_error": value["reconstruction_error"], "scores": value["scores"]},
                {"latent": ranks[row["row_id"]]["latent"], "reconstruction_error": ranks[row["row_id"]]["reconstruction_error"], "scores": scores[row["row_id"]]}):
            raise ValueError("portable numerical inference differs from independently validated training index")
    native = _native_manifest(_sha(_json(checkpoint)), config, vocabulary, lineage)
    fixture = _fixture_observations(len(initializer["keys"]))
    values = {"checkpoint.json": checkpoint, "config.json": config, "vocabularies.json": vocabulary,
        "lineage.json": lineage, "checkpoint-manifest.json": native.to_dict(),
        "provenance-review.json": provenance_review,
        "inference-fixture.json": {"schema": "security-autoencoder-numeric-fixture@1", "observations": fixture, "results": _score(loaded, fixture)}}
    payloads = {name: _json(value) for name, value in values.items()}
    payloads["README.md"] = model_card.encode()
    manifest = {"schema": RELEASE_SCHEMA, "domain": DOMAIN,
        "files": {name: {"sha256": _sha(raw), "bytes": len(raw)} for name, raw in payloads.items()},
        "authority": "unverified_candidate_only", "model_scope": "benchmark_informed_development", "holdout_evaluated": False}
    manifest_raw = _json(manifest)
    if sum(map(len, payloads.values())) + len(manifest_raw) > MAX_BYTES:
        raise ValueError("portable security package exceeds bound")
    training.validate_codebase_autoencoder(repository=repository, expected_receipt=expected_receipt)
    if any(_read(old / name) != raw for name, raw in original.items()):
        raise ValueError("original training bundle changed during export")
    output.mkdir(parents=True, mode=0o755)
    for name, raw in {**payloads, "release-manifest.json": manifest_raw}.items():
        _write(output / name, raw)
    return load_security_checkpoint(output, expected_manifest_sha256=_sha(manifest_raw))["descriptor"]


def _ledger(source_hashes):
    if type(source_hashes) is not dict or not 1 <= len(source_hashes) <= 256:
        raise ValueError("bounded independently admitted source ledger required")
    result = {}
    for name, value in sorted(source_hashes.items()):
        path = PurePosixPath(name)
        if (type(name) is not str or not name or path.is_absolute() or str(path) != name
                or any(part in {"..", ".git", ".runtime"} for part in path.parts) or "\x00" in name):
            raise ValueError("security inference source path escapes admitted scope")
        if type(value) is dict:
            if set(value) not in ({"sha256"}, {"sha256", "executable"}):
                raise ValueError("exact source hash entry required")
            value = value["sha256"]
        result[name] = _digest(value)
    return result


def _sources(repository, ledger):
    if not repository.is_absolute() or repository.resolve(strict=True) != repository:
        raise ValueError("canonical independently admitted repository required")
    sources, total = {}, 0
    for name, digest in ledger.items():
        raw = _read(repository / name, MAX_SOURCE_BYTES)
        total += len(raw)
        if _sha(raw) != digest or total > MAX_SOURCE_BYTES:
            raise ValueError("security inference admitted source drift or byte bound")
        sources[name] = raw
    return sources


def _infer(repository, paths, ledger, loaded, maximum):
    rows, unsupported = projection.source_features(_sources(repository, ledger), paths,
        keys=loaded["vocabularies"]["lexical_keys"], max_functions=maximum)
    scored = _score(loaded, [{"features": row["features"], "lexical_indices": row["lexical_indices"]} for row in rows]) if rows else {"rows": []}
    ranks = sorted(({"row_id": row["row_id"], "path": row["path"], "symbol": row["symbol"], "line": row["line"],
        "reconstruction_error": score["reconstruction_error"], "latent": score["latent"]}
        for row, score in zip(rows, scored["rows"])), key=lambda row: (-row["reconstruction_error"], row["row_id"]))
    return {"schema": "security-autoencoder-observations@1", "source_hashes": ledger, "paths": paths,
        "features": rows, "ranks": ranks, "unsupported": unsupported,
        "security_candidate_nominations": {"schema": "security-ir-candidate-projection@1",
            "target_vocabulary": loaded["vocabularies"]["targets"],
            "canonical_export_manifest_sha256": loaded["lineage"]["canonical_export_manifest_sha256"],
            "rows": [{"row_id": row["row_id"], "scores": score["scores"]} for row, score in zip(rows, scored["rows"])],
            "scope": "source_body_trained_head_applied_to_task_function_rows", "granularity_shift_validated": False,
            "scores_are_calibrated_probabilities": False, "holdout_evaluated": False, **AUTHORITY}, **AUTHORITY}


def _inference_descriptor(output, receipt, raw, observed):
    return {**receipt, "output": str(output), "receipt_sha256": _sha(raw), "ranks": observed["ranks"],
        "unsupported": observed["unsupported"], "security_candidate_nominations": observed["security_candidate_nominations"]}


def infer_security_checkpoint(*, repository: Path, paths, source_hashes: dict, checkpoint: dict,
                              output: Path, max_functions=1024) -> dict:
    started = time.monotonic()
    repository = Path(repository).absolute()
    loaded = _load_descriptor(checkpoint)
    output = _namespace(Path(output), fresh=True, excluded=(repository, Path(checkpoint["output"])))
    ledger = _ledger(source_hashes)
    if (type(paths) not in (list, tuple) or not paths or len(set(paths)) != len(paths) or not set(paths) <= set(ledger)
            or type(max_functions) is not int or not 1 <= max_functions <= 1024):
        raise ValueError("exact admitted inference paths and bounded function count required")
    paths = sorted(paths)
    observed = _infer(repository, paths, ledger, loaded, max_functions)
    raw = _json(observed)
    if len(raw) > MAX_BYTES:
        raise ValueError("source inference artifact exceeds bound")
    receipt = {"schema": INFERENCE_SCHEMA, "domain": DOMAIN, "repository": str(repository),
        "checkpoint": checkpoint, "source_hashes": ledger, "paths": paths, "sample_count": len(observed["features"]),
        "inference_sha256": _sha(raw), "max_functions": max_functions, "mode": "frozen_inference",
        "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "inference_elapsed_seconds": time.monotonic() - started, "python_version": sys.version.split()[0], **AUTHORITY}
    _sources(repository, ledger)
    _load_descriptor(checkpoint)
    output.mkdir(parents=True, mode=0o700)
    _write(output / "inference.json", raw)
    receipt_raw = _json(receipt)
    _write(output / "receipt.json", receipt_raw)
    _sources(repository, ledger)
    return _inference_descriptor(output, receipt, receipt_raw, observed)


def validate_security_inference(*, repository: Path, expected_receipt: dict) -> dict:
    repository = Path(repository).absolute()
    output = _namespace(Path(expected_receipt["output"]), excluded=(repository,))
    if {path.name for path in output.iterdir()} != {"inference.json", "receipt.json"}:
        raise ValueError("exact security observation artifact inventory required")
    receipt_raw, raw = _read(output / "receipt.json"), _read(output / "inference.json")
    if _sha(receipt_raw) != expected_receipt.get("receipt_sha256"):
        raise ValueError("security inference receipt differs")
    receipt = _decode(receipt_raw)
    fields = {"schema", "domain", "repository", "checkpoint", "source_hashes", "paths", "sample_count", "inference_sha256",
        "max_functions", "mode", "training_steps", "provider_calls", "download_calls", "inference_elapsed_seconds", "python_version"} | set(AUTHORITY)
    if (type(receipt) is not dict or set(receipt) != fields or receipt["schema"] != INFERENCE_SCHEMA
            or receipt["domain"] != DOMAIN or receipt["repository"] != str(repository) or receipt["mode"] != "frozen_inference"
            or receipt["python_version"] != sys.version.split()[0] or receipt["inference_sha256"] != _sha(raw)
            or any(type(receipt[k]) is not int or receipt[k] != 0 for k in ("training_steps", "provider_calls", "download_calls"))
            or any(type(receipt[k]) is not type(v) or receipt[k] != v for k, v in AUTHORITY.items())
            or type(receipt["inference_elapsed_seconds"]) not in (int, float)
            or not math.isfinite(receipt["inference_elapsed_seconds"]) or receipt["inference_elapsed_seconds"] < 0
            or type(receipt["sample_count"]) is not int or not 0 <= receipt["sample_count"] <= 1024):
        raise ValueError("security inference authority, mode or identity differs")
    ledger = _ledger(receipt["source_hashes"])
    paths, maximum = receipt["paths"], receipt["max_functions"]
    if (type(paths) is not list or not paths or paths != sorted(set(paths)) or not set(paths) <= set(ledger)
            or type(maximum) is not int or not 1 <= maximum <= 1024):
        raise ValueError("security inference source selection differs")
    loaded = _load_descriptor(receipt["checkpoint"])
    observed = _infer(repository, paths, ledger, loaded, maximum)
    if not _numerically_equal(observed, _decode(raw)) or receipt["sample_count"] != len(observed["features"]):
        raise ValueError("security inference differs from current source and frozen weights")
    if not _numerically_equal(_inference_descriptor(output, receipt, receipt_raw, _decode(raw)), expected_receipt):
        raise ValueError("security inference descriptor differs")
    _sources(repository, ledger)
    return expected_receipt
