"""Code-only learned AST index using the native modal reconstruction kernel.

The encoder/decoder and checkpoints belong to ``security-code@1``. Training
reuses the legal/modal engine's numerical reconstruction kernel and gradient
norm, never its LegalSample contract, LegalIR views or mutable state. An explicit
immutable lexical fork can initialize identically keyed shared token weights.
Reconstruction rank nominates work only. It does not infer a security contract
or constitute a proof, and it cannot exclude inputs from static analysis.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from types import SimpleNamespace

DOMAIN = "security-code@1"
SCHEMA = "supervisor-code-autoencoder-descriptor@1"
CHECKPOINT_SCHEMA = "supervisor-code-autoencoder-checkpoint@1"
FEATURE_SCHEMA = "python-ast-control-flow-features@1"
_CHECKPOINT_FIELDS = {"schema", "domain", "projection_family", "architecture", "input_width", "latent_width",
                      "weights", "feature_manifest_sha256", "implementation", "legal_ir_weights_loaded",
                      "legal_ir_views_loaded", "tla_projection"}
_RECEIPT_FIELDS = {"schema", "domain", "repository", "output", "source_hashes", "paths", "source_count",
                   "sample_count", "checkpoint_sha256", "features_sha256", "index_sha256", "implementation",
                   "metrics", "max_functions", "provider_calls", "download_calls", "authority",
                   "legal_state_mutated", "proof_authority", "formalization_authority"}
_TLA_PROJECTION = {"status": "unsupported", "reason": "no temporal specification inferred from reconstruction"}
NODE_FEATURES = (
    "FunctionDef", "AsyncFunctionDef", "ClassDef", "Call", "Attribute", "Name",
    "Constant", "Return", "Raise", "If", "IfExp", "Compare", "BoolOp", "BinOp",
    "UnaryOp", "Assign", "AnnAssign", "AugAssign", "Subscript", "List", "Tuple",
    "Dict", "Set", "ListComp", "DictComp", "GeneratorExp", "For", "While",
    "Try", "ExceptHandler", "With", "Await", "Yield", "Assert", "Global",
    "Nonlocal", "Import", "ImportFrom", "Lambda", "Match",
)
FEATURES = NODE_FEATURES + ("literal_cr", "literal_lf", "literal_nul", "argument_count")
_MAX_BYTES = 4_000_000
_HASH = re.compile(r"[a-f0-9]{64}")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _read(path: Path, limit=_MAX_BYTES) -> bytes:
    if path.resolve(strict=True) != path:
        raise ValueError("autoencoder input or artifact is not canonical")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("bounded regular autoencoder input required")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("autoencoder byte bound exceeded")
    return raw


def _ledger(source_hashes) -> dict:
    if type(source_hashes) is not dict or not 1 <= len(source_hashes) <= 256:
        raise ValueError("bounded independent source ledger required")
    result = {}
    for path, value in sorted(source_hashes.items()):
        relative = PurePosixPath(path)
        if (not path or relative.is_absolute() or str(relative) != path
                or any(part in {"..", ".git", ".runtime"} for part in relative.parts)):
            raise ValueError("autoencoder source path escapes input scope")
        digest = value.get("sha256") if type(value) is dict else value
        if type(digest) is not str or _HASH.fullmatch(digest) is None:
            raise ValueError("exact SHA256 source binding required")
        result[path] = digest
    return result


def _sources(repository: Path, ledger: dict) -> dict:
    if not repository.is_absolute() or repository.resolve(strict=True) != repository:
        raise ValueError("canonical repository required")
    result, total = {}, 0
    for path, digest in ledger.items():
        raw = _read(repository / path)
        total += len(raw)
        if _sha(raw) != digest or total > _MAX_BYTES:
            raise ValueError("autoencoder admitted source drift or byte bound")
        result[path] = raw
    return result


def _features(sources: dict, paths: list[str], maximum: int, weight_transfer=None) -> tuple[list[dict], list[dict]]:
    from ..source_screening import (
        PlanningAnalysisSecretError, _contains_secret, _credential_path_reason,
    )
    rows, unsupported = [], []
    for path in paths:
        if _credential_path_reason(path) or _contains_secret(sources[path]):
            raise PlanningAnalysisSecretError("code autoencoder input refused by native secret screen")
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(sources[path].decode("utf-8"))
        except (SyntaxError, UnicodeError, ValueError):
            unsupported.append({"path": path, "reason": "python_ast_unavailable"})
            continue
        def visit(node, prefix=""):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts = Counter(type(child).__name__ for child in ast.walk(node))
                literals = [child.value for child in ast.walk(node)
                            if isinstance(child, ast.Constant) and type(child.value) is str]
                values = [float(counts[name]) for name in NODE_FEATURES]
                values += [float(any(char in value for value in literals)) for char in ("\r", "\n", "\x00")]
                values += [float(len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs))]
                values = [math.log1p(value) for value in values]
                norm = math.sqrt(sum(value * value for value in values)) or 1.0
                values = [value / norm for value in values]
                body_hash = _sha(ast.dump(node, include_attributes=False).encode())
                identity = {"path": path, "symbol": prefix + node.name,
                            "line": node.lineno, "ast_sha256": body_hash}
                row = {**identity, "row_id": _sha(_json(identity)), "features": values}
                if weight_transfer is not None:
                    from .codebase_autoencoder_transfer import lexical_observation
                    row.update(lexical_observation(ast.get_source_segment(sources[path].decode("utf-8"), node) or "", weight_transfer))
                rows.append(row)
                prefix += node.name + "."
            elif isinstance(node, ast.ClassDef):
                prefix += node.name + "."
            for child in ast.iter_child_nodes(node):
                visit(child, prefix)
        visit(tree)
    if len(rows) > maximum:
        raise ValueError("code autoencoder function bound reached; no silently truncated training corpus")
    if not rows:
        raise ValueError("no admitted Python function features for code autoencoder")
    return rows, unsupported


def _dependencies():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as kernel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_batching as batching
    return torch, kernel, batching


def _implementation(torch, kernel, batching) -> dict:
    from .. import source_screening as screening
    return {"adapter_sha256": _sha(Path(__file__).read_bytes()),
            "torch_version": torch.__version__,
            "native_kernel_module": kernel.__name__, "native_kernel_sha256": _sha(Path(kernel.__file__).read_bytes()),
            "native_batching_module": batching.__name__, "native_batching_sha256": _sha(Path(batching.__file__).read_bytes()),
            "native_secret_screen_sha256": _sha(Path(screening.__file__).read_bytes()),
            "reused_functions": ["_loss_chunk", "_gradient_norm", "plan_gradient_accumulation"]}


def _forward(torch, data, parameters, lexical=None):
    encoder, encoder_bias, decoder, decoder_bias = parameters[:4]
    encoded = data @ encoder + encoder_bias
    if len(parameters) >= 5:
        if lexical is None:
            raise ValueError("forked lexical input missing")
        encoded = encoded + lexical @ parameters[4]
    latent = torch.tanh(encoded)
    return latent, latent @ decoder + decoder_bias


def _lexical_tensor(torch, rows, parameters):
    if len(parameters) < 5:
        return None
    values = torch.zeros((len(rows), parameters[4].shape[0]), dtype=parameters[0].dtype)
    for index, row in enumerate(rows):
        indices = row["lexical_indices"]
        if indices:
            values[index, indices] = 1.0 / math.sqrt(len(indices))
    return values


def _inference(torch, rows, parameters) -> dict:
    with torch.no_grad():
        data = torch.tensor([row["features"] for row in rows], dtype=parameters[0].dtype, device="cpu")
        latent, decoded = _forward(torch, data, parameters, _lexical_tensor(torch, rows, parameters))
        errors = (decoded - data).square().mean(dim=1).tolist()
        latents = latent.tolist()
    if not all(math.isfinite(float(value)) for row in latents for value in row) or not all(math.isfinite(value) for value in errors):
        raise ValueError("autoencoder inference produced nonfinite values")
    ranked = sorted(({
        "row_id": row["row_id"], "path": row["path"], "symbol": row["symbol"], "line": row["line"],
        "reconstruction_error": error, "latent": encoded,
    } for row, error, encoded in zip(rows, errors, latents)), key=lambda row: (-row["reconstruction_error"], row["row_id"]))
    return {"mean_reconstruction_error": sum(errors) / len(errors), "ranks": ranked,
            "authority": "unverified_candidate_only", "ranking_role": "nomination_order_only",
            "omission_authority": False, "formalization_authority": False, "proof_authority": False}


def _output_directory(repository: Path, output: Path, *, fresh: bool):
    if (not output.is_absolute() or output.resolve() != output or output.name != "code-autoencoder"
            or output.is_relative_to(repository) or (fresh and output.exists())
            or any(part.lower() in {"legal-ir", "legal_ir", "legalir", "shared-weights", "shared_weights"} for part in output.parts)):
        raise ValueError("a dedicated fresh external code-autoencoder namespace is required")


def _write(path: Path, value):
    raw = _json(value)
    with path.open("xb") as stream:
        stream.write(raw)
        os.fchmod(stream.fileno(), 0o444)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha(raw)


def train_codebase_autoencoder(*, repository: Path, paths, source_hashes: dict, output: Path,
                              epochs: int = 24, latent_dim: int = 8, seed: int = 1729,
                              max_functions: int = 1024, weight_transfer: dict | None = None,
                              canonical_cve_training: dict | None = None) -> dict:
    """Fit real code-only weights using the existing native reconstruction loss.

    Training is transductive over permitted source functions. No holdout or
    vulnerability-classification accuracy is claimed. All functions remain
    eligible for deterministic analysis regardless of their advisory rank.
    """
    started = time.monotonic()
    repository, output = Path(repository).absolute(), Path(output).absolute()
    _output_directory(repository, output, fresh=True)
    if (type(epochs) is not int or not 1 <= epochs <= 32 or type(latent_dim) is not int or not 2 <= latent_dim <= 16
            or type(seed) is not int or not 0 <= seed <= 2**31 - 1
            or type(max_functions) is not int or not 1 <= max_functions <= 1024):
        raise ValueError("closed code autoencoder training budget required")
    ledger = _ledger(source_hashes)
    if type(paths) not in (list, tuple) or not paths or len(set(paths)) != len(paths) or not set(paths) <= set(ledger):
        raise ValueError("exact admitted feature input paths required")
    paths = sorted(paths)
    sources = _sources(repository, ledger)
    initializer = None
    if weight_transfer is not None:
        from .codebase_autoencoder_transfer import validate_legal_shared_weight_fork
        initializer = validate_legal_shared_weight_fork(expected_receipt=weight_transfer)
        if latent_dim != initializer["embedding_width"]:
            raise ValueError("native transferred width must match latent dimension; no reshaping")
    rows, unsupported = _features(sources, paths, max_functions, initializer)
    if initializer is not None and not any(row["lexical_indices"] for row in rows):
        raise ValueError("zero code vocabulary overlap: transferred weights would have no input")
    security = None
    if canonical_cve_training is not None:
        if initializer is None:
            raise ValueError("canonical security training requires an explicit inherited weight fork")
        from .codebase_autoencoder_security import prepare_security_training, security_candidate_inference, security_candidate_report, task_security_candidate_nominations
        security = prepare_security_training(canonical_cve_training, initializer)
    torch, kernel, batching = _dependencies()
    implementation = _implementation(torch, kernel, batching)
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        generator = torch.Generator(device="cpu").manual_seed(seed)
        width = len(FEATURES)
        if initializer is not None:
            parameters = [torch.zeros(shape, dtype=torch.float64, requires_grad=True)
                          for shape in ((width, latent_dim), (latent_dim,), (latent_dim, width), (width,))]
            parameters.append(torch.tensor(initializer["weights"], dtype=torch.float64, requires_grad=True))
        else:
            parameters = [
                (torch.randn(width, latent_dim, generator=generator) * 0.1).requires_grad_(),
                torch.zeros(latent_dim, requires_grad=True),
                (torch.randn(latent_dim, width, generator=generator) * 0.1).requires_grad_(),
                torch.zeros(width, requires_grad=True),
            ]
        if security is not None:
            parameters.extend([torch.zeros((latent_dim, len(security["target_vocabulary"])), dtype=torch.float64, requires_grad=True),
                               torch.zeros(len(security["target_vocabulary"]), dtype=torch.float64, requires_grad=True)])
        initial_weights = _sha(_json([value.detach().tolist() for value in parameters]))
        data = torch.tensor([row["features"] for row in rows], dtype=parameters[0].dtype, device="cpu")
        lexical = _lexical_tensor(torch, rows, parameters)
        empty = torch.zeros((len(rows), 0), dtype=parameters[0].dtype)
        state = SimpleNamespace(torch=torch, device=torch.device("cpu"), embeddings=data)
        session = SimpleNamespace(blocks={}, parameters=parameters, parameter_count=sum(value.numel() for value in parameters))
        plan = batching.plan_gradient_accumulation(len(rows), microbatch_size=128)
        optimizer = torch.optim.Adam(parameters, lr=0.02)
        before = _inference(torch, rows, parameters)
        security_before = security_candidate_report(torch, parameters, security) if security is not None else None
        security_losses = []
        losses, gradients, kernel_calls = [], [], 0
        for _ in range(epochs):
            optimizer.zero_grad()
            _, decoded = _forward(torch, data, parameters, lexical)
            loss_total = 0.0
            for index, (start, stop) in enumerate(plan.ranges):
                loss, _, _ = kernel._loss_chunk(state, session, (decoded, empty, empty),
                    {"decoded_embedding"}, start, stop, len(rows), 0.1, 0.0, False)
                if not torch.isfinite(loss):
                    raise ValueError("native reconstruction loss is not finite")
                loss.backward(retain_graph=index + 1 < len(plan.ranges))
                loss_total += float(loss.detach())
                kernel_calls += 1
            if security is not None:
                _, candidate_loss = security_candidate_inference(torch, parameters, security)
                candidate_loss.backward()
                security_losses.append(float(candidate_loss.detach()))
            gradient = kernel._gradient_norm(torch, parameters)
            if not math.isfinite(gradient):
                raise ValueError("native gradient is not finite")
            gradients.append(gradient)
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            losses.append(loss_total)
        after = _inference(torch, rows, parameters)
        security_after = security_candidate_report(torch, parameters, security) if security is not None else None
        task_nominations = task_security_candidate_nominations(torch, rows, parameters, security) if security is not None else None
        weights = [value.detach().tolist() for value in parameters]
        final_weights = _sha(_json(weights))
        if initial_weights == final_weights or not any(value > 0 for value in gradients):
            raise ValueError("training produced no actual parameter update")
    finally:
        torch.set_num_threads(previous_threads)
    _sources(repository, ledger)
    feature_manifest = {"schema": FEATURE_SCHEMA, "domain": DOMAIN, "features": list(FEATURES),
        "source_hashes": ledger, "paths": paths, "rows": rows, "unsupported": unsupported,
        "normalization": "log1p counts, per-function L2 normalization", "source_text_retained": False}
    if security is not None:
        feature_manifest["security_candidate_training"] = security
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "domain": DOMAIN,
        "projection_family": "code-ast-control-flow-contract-advisory@1", "architecture": "tanh-linear-autoencoder@1",
        "input_width": len(FEATURES), "latent_width": latent_dim, "weights": weights,
        "feature_manifest_sha256": _sha(_json(feature_manifest)), "implementation": implementation,
        "legal_ir_weights_loaded": False, "legal_ir_views_loaded": False,
        "tla_projection": dict(_TLA_PROJECTION)}
    if initializer is not None:
        checkpoint.update(architecture="lexical-fork-tanh-code-autoencoder@1", legal_ir_weights_loaded=True,
                          weight_transfer=weight_transfer)
    if security is not None:
        checkpoint["security_candidate_projection"] = {"schema": security["schema"],
            "target_vocabulary": security["target_vocabulary"], "canonical_export": canonical_cve_training,
            "weight_tensor_positions": [5, 6], "output_role": "advisory_classification_candidates_only",
            "proof_authority": False, "formalization_authority": False, "execution_authority": False}
        after["security_candidate_projection"] = security_after
        after["security_candidate_nominations"] = task_nominations
    output.mkdir(parents=True, mode=0o700)
    feature_hash = _write(output / "features.json", feature_manifest)
    checkpoint_hash = _write(output / "checkpoint.json", checkpoint)
    index_hash = _write(output / "index.json", after)
    metrics = {"epochs": epochs, "seed": seed, "initial_weights_sha256": initial_weights,
        "final_weights_sha256": final_weights, "before_reconstruction_loss": before["mean_reconstruction_error"],
        "after_reconstruction_loss": after["mean_reconstruction_error"], "native_objective_losses": losses,
        "native_gradient_norms": gradients, "native_kernel_calls": kernel_calls,
        "microbatch_count": plan.accumulation_steps, "training_elapsed_seconds": time.monotonic() - started,
        "holdout_evaluated": False, "training_scope": "transductive_admitted_code_functions"}
    if initializer is not None:
        metrics["weight_transfer"] = {"initialization": "exact_native_lexical_rows_new_heads_zero",
            "transferred_parameters": len(initializer["keys"]) * latent_dim,
            "transferred_weights_sha256": _sha(_json(initializer["weights"])),
            "trained_transferred_weights_sha256": _sha(_json(weights[4])),
            "random_initialization": False, "new_projection_initialization": "zeros",
            "trained_heads": ["code_ast_reconstruction", "shared_lexical_embedding"],
            "coverage": [{"row_id": row["row_id"], **row["lexical_coverage"]} for row in rows]}
    if security is not None:
        metrics["security_candidate_training"] = {"sample_count": len(security["rows"]),
            "epochs": epochs, "objective": "binary_cross_entropy_with_logits",
            "before": security_before, "after": security_after, "losses": security_losses,
            "canonical_export_manifest_sha256": canonical_cve_training["manifest_sha256"],
            "trained_head": "security_ir_audit_cwe_polarity_candidates@1", "holdout_evaluated": False,
            "training_scope": "bounded_canonical_CVE_training_pairs_no_generalization_claim"}
        metrics["weight_transfer"]["trained_heads"].append("security_ir_audit_cwe_polarity_candidates@1")
    receipt = {"schema": "supervisor-code-autoencoder-training@1", "domain": DOMAIN,
        "repository": str(repository), "output": str(output), "source_hashes": ledger,
        "paths": paths, "source_count": len(ledger), "sample_count": len(rows),
        "checkpoint_sha256": checkpoint_hash, "features_sha256": feature_hash, "index_sha256": index_hash,
        "implementation": implementation, "metrics": metrics, "max_functions": max_functions,
        "provider_calls": 0, "download_calls": 0, "authority": "unverified_candidate_only",
        "legal_state_mutated": False, "proof_authority": False, "formalization_authority": False}
    if initializer is not None:
        receipt["weight_transfer"] = weight_transfer
        validate_legal_shared_weight_fork(expected_receipt=weight_transfer)
    if security is not None:
        receipt["canonical_cve_training"] = canonical_cve_training
        if prepare_security_training(canonical_cve_training, initializer) != security:
            raise ValueError("canonical CVE source changed during training")
    receipt_hash = _write(output / "receipt.json", receipt)
    _sources(repository, ledger)
    descriptor = {"schema": SCHEMA, "domain": DOMAIN, "repository": str(repository), "output": str(output),
        "receipt_sha256": receipt_hash, "checkpoint_sha256": checkpoint_hash,
        "source_hashes": ledger, "source_count": len(ledger), "sample_count": len(rows), "metrics": metrics,
        "epochs_completed": epochs, "training_elapsed_seconds": metrics["training_elapsed_seconds"],
        "authority": "unverified_candidate_only", "provider_calls": 0, "proof_authority": False,
        "ranks": [{key: row[key] for key in ("row_id", "path", "symbol", "line", "reconstruction_error")}
                           for row in after["ranks"]]}
    if initializer is not None:
        descriptor["weight_transfer"] = weight_transfer
    if security is not None:
        descriptor["canonical_cve_training"] = canonical_cve_training
        descriptor["security_candidate_nominations"] = after["security_candidate_nominations"]
    return descriptor


def validate_codebase_autoencoder(*, repository: Path, expected_receipt: dict) -> dict:
    """Reload exact inert weights and replay features and learned inference."""
    repository = Path(repository).absolute()
    if (type(expected_receipt) is not dict or expected_receipt.get("schema") != SCHEMA
            or expected_receipt.get("domain") != DOMAIN or expected_receipt.get("repository") != str(repository)):
        raise ValueError("exact code-domain training descriptor required")
    output = Path(expected_receipt["output"])
    _output_directory(repository, output, fresh=False)
    raw = _read(output / "receipt.json")
    if _sha(raw) != expected_receipt.get("receipt_sha256"):
        raise ValueError("training receipt changed")
    receipt = json.loads(raw)
    if (type(receipt) is not dict or set(receipt) != (_RECEIPT_FIELDS | ({"weight_transfer"} if "weight_transfer" in receipt else set()) | ({"canonical_cve_training"} if "canonical_cve_training" in receipt else set()))
            or receipt.get("schema") != "supervisor-code-autoencoder-training@1"
            or receipt.get("domain") != DOMAIN or receipt.get("repository") != str(repository) or receipt.get("output") != str(output)
            or receipt.get("authority") != "unverified_candidate_only"
            or any(receipt.get(key) is not False for key in ("legal_state_mutated", "proof_authority", "formalization_authority"))
            or any(type(receipt.get(key)) is not int or receipt[key] != 0 for key in ("provider_calls", "download_calls"))):
        raise ValueError("training receipt domain/source differs")
    artifacts = {}
    for name, key in (("checkpoint", "checkpoint_sha256"), ("features", "features_sha256"), ("index", "index_sha256")):
        raw = _read(output / (name + ".json"))
        if _sha(raw) != receipt.get(key):
            raise ValueError("autoencoder artifact digest changed")
        artifacts[name] = json.loads(raw)
    checkpoint, features, index = (artifacts[name] for name in ("checkpoint", "features", "index"))
    transfer = receipt.get("weight_transfer")
    initializer = None
    if transfer is not None:
        from .codebase_autoencoder_transfer import validate_legal_shared_weight_fork
        initializer = validate_legal_shared_weight_fork(expected_receipt=transfer)
    security = None
    if "canonical_cve_training" in receipt:
        if initializer is None:
            raise ValueError("security candidate head requires inherited weights")
        from .codebase_autoencoder_security import prepare_security_training, security_candidate_report, task_security_candidate_nominations
        security = prepare_security_training(receipt["canonical_cve_training"], initializer)
    if (type(checkpoint) is not dict or set(checkpoint) != (_CHECKPOINT_FIELDS | ({"weight_transfer"} if initializer else set()) | ({"security_candidate_projection"} if security else set()))
            or checkpoint.get("schema") != CHECKPOINT_SCHEMA or checkpoint.get("domain") != DOMAIN
            or checkpoint.get("projection_family") != "code-ast-control-flow-contract-advisory@1"
            or checkpoint.get("architecture") != ("lexical-fork-tanh-code-autoencoder@1" if initializer else "tanh-linear-autoencoder@1")
            or checkpoint.get("tla_projection") != _TLA_PROJECTION
            or checkpoint.get("legal_ir_weights_loaded") is not bool(initializer) or checkpoint.get("legal_ir_views_loaded") is not False
            or checkpoint.get("weight_transfer") != transfer):
        raise ValueError("foreign/legal checkpoint cannot populate the code namespace")
    torch, kernel, batching = _dependencies()
    if checkpoint.get("implementation") != _implementation(torch, kernel, batching) or receipt.get("implementation") != checkpoint["implementation"]:
        raise ValueError("autoencoder implementation or native kernel drift")
    ledger = _ledger(receipt["source_hashes"])
    sources = _sources(repository, ledger)
    rows, unsupported = _features(sources, receipt["paths"], receipt["max_functions"], initializer)
    if (features.get("schema") != FEATURE_SCHEMA or features.get("domain") != DOMAIN
            or features.get("features") != list(FEATURES) or features.get("rows") != rows
            or features.get("unsupported") != unsupported or features.get("source_hashes") != ledger
            or checkpoint.get("feature_manifest_sha256") != receipt["features_sha256"]
            or features.get("security_candidate_training") != security):
        raise ValueError("replayed source features differ from checkpoint binding")
    width, latent = checkpoint.get("input_width"), checkpoint.get("latent_width")
    if width != len(FEATURES) or type(latent) is not int or not 2 <= latent <= 16:
        raise ValueError("closed code autoencoder dimensions required")
    weights = checkpoint.get("weights")
    if type(weights) is not list or len(weights) != (7 if security else (5 if initializer else 4)):
        raise ValueError("closed code weight tensors required")
    parameters = [torch.tensor(value, dtype=torch.float64 if initializer else torch.float32, device="cpu") for value in weights]
    shapes = [(width, latent), (latent,), (latent, width), (width,)]
    if initializer:
        if latent != initializer["embedding_width"]:
            raise ValueError("forked latent width changed")
        shapes.append((len(initializer["keys"]), latent))
        if not any(row["lexical_indices"] for row in rows):
            raise ValueError("transferred weights have zero code vocabulary overlap")
        coverage = [{"row_id": row["row_id"], **row["lexical_coverage"]} for row in rows]
        transfer_metrics = receipt["metrics"].get("weight_transfer", {})
        if (transfer_metrics.get("coverage") != coverage
                or transfer_metrics.get("transferred_weights_sha256") != _sha(_json(initializer["weights"]))
                or transfer_metrics.get("trained_transferred_weights_sha256") != _sha(_json(weights[4]))):
            raise ValueError("weight transfer coverage or lineage differs")
    if security is not None:
        classes = len(security["target_vocabulary"])
        shapes += [(latent, classes), (classes,)]
        expected_projection = {"schema": security["schema"],
            "target_vocabulary": security["target_vocabulary"], "canonical_export": receipt["canonical_cve_training"],
            "weight_tensor_positions": [5, 6], "output_role": "advisory_classification_candidates_only",
            "proof_authority": False, "formalization_authority": False, "execution_authority": False}
        if checkpoint["security_candidate_projection"] != expected_projection:
            raise ValueError("security projection authority or target bindings differ")
    for value, shape in zip(parameters, shapes):
        if tuple(value.shape) != shape or not torch.isfinite(value).all():
            raise ValueError("finite exact code weight shapes required")
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        observed = _inference(torch, rows, parameters)
        if security is not None:
            observed["security_candidate_projection"] = security_candidate_report(torch, parameters, security)
            observed["security_candidate_nominations"] = task_security_candidate_nominations(torch, rows, parameters, security)
    finally:
        torch.set_num_threads(previous_threads)
    if observed != index:
        raise ValueError("learned inference differs from bound index")
    expected = {"schema": SCHEMA, "domain": DOMAIN, "repository": str(repository), "output": str(output),
        "receipt_sha256": expected_receipt["receipt_sha256"], "checkpoint_sha256": receipt["checkpoint_sha256"],
        "source_hashes": ledger, "source_count": receipt["source_count"], "sample_count": receipt["sample_count"], "metrics": receipt["metrics"],
        "epochs_completed": receipt["metrics"]["epochs"], "training_elapsed_seconds": receipt["metrics"]["training_elapsed_seconds"],
        "authority": "unverified_candidate_only", "provider_calls": 0, "proof_authority": False,
        "ranks": [{key: row[key] for key in ("row_id", "path", "symbol", "line", "reconstruction_error")}
                           for row in observed["ranks"]]}
    if initializer is not None:
        expected["weight_transfer"] = transfer
    if security is not None:
        expected["canonical_cve_training"] = receipt["canonical_cve_training"]
        expected["security_candidate_nominations"] = observed["security_candidate_nominations"]
    if expected != expected_receipt:
        raise ValueError("autoencoder descriptor differs from exact training receipt")
    _sources(repository, ledger)
    return {"status": "verified", "domain": DOMAIN, "receipt_sha256": expected_receipt["receipt_sha256"],
            "source_count": len(ledger), "sample_count": len(rows), "ranks": observed["ranks"],
            "authority": "unverified_candidate_only", "proof_authority": False,
            "formalization_authority": False, "omission_authority": False}
