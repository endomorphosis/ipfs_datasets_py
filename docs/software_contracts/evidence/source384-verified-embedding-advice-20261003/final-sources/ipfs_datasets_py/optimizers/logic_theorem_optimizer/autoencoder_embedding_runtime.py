"""Bounded, offline CPU inference from the already-cached immutable GTE snapshot.

This producer never downloads, chunks, trains, or writes a checkpoint. Its
reversible socket guard covers Python networking; it is not an OS sandbox or
cryptographic attestation of the runtime. Use a dedicated network-isolated
process when that stronger boundary is required. Token evidence records the
actual model inputs, separately from any source-text normalization hash.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import os
from pathlib import Path
import platform
import socket
import stat
import sys
import threading
from typing import Any, Sequence


PINNED_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"
DEFAULT_SNAPSHOT_PATH = (Path.home() / ".cache/huggingface/hub/models--thenlper--gte-small"
                         / "snapshots" / PINNED_REVISION)
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_TOKENS = 512
MAX_BATCH_SIZE = 16
# These are the complete inference assets observed in the pinned local snapshot.
# README.md is informational and is never loaded as model configuration.
_PINNED_ASSETS = {
    "1_Pooling/config.json": (190, "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23"),
    "config.json": (583, "00273cdfb3e05c7304d180270bdef8adae45023e7bdfc396338bdd815943dc59"),
    "model.safetensors": (66746168, "9a1eb90bbac323ea08aa5629b624fe6ae75db121b904799c2266a1e2c2de22d2"),
    "modules.json": (385, "73348a3d8f8ae4cc5f851dc6b98be3ea819390b814e83656d5eebbadf75fe43e"),
    "sentence_bert_config.json": (57, "948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529"),
    "special_tokens_map.json": (125, "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3"),
    "tokenizer.json": (711661, "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0"),
    "tokenizer_config.json": (394, "e1790949631401af1bfb6c9c7aeec7fcf612e274d73579d99f704faea40c8ba7"),
    "vocab.txt": (231508, "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
}
_OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                "CUDA_VISIBLE_DEVICES": "", "TOKENIZERS_PARALLELISM": "false",
                "PYTHONDONTWRITEBYTECODE": "1"}
_RUNTIME_LOCK = threading.RLock()
_LOADED_PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class EmbeddingRuntimeError(ValueError):
    """The cached model, actual tokens, or bounded runtime contract failed."""


@contextmanager
def _offline_guard():
    """Reversibly deny Python outbound sockets and restore caller settings.

    This process-wide guard should be used in a dedicated producer process.
    It does not intercept native-library syscalls or concurrent environment edits.
    """
    def denied(*args, **kwargs):
        raise EmbeddingRuntimeError("offline embedding runtime forbids networking")

    with _RUNTIME_LOCK:
        env = {name: os.environ.get(name) for name in _OFFLINE_ENV}
        old_bytecode = sys.dont_write_bytecode
        patches = [(socket, name, getattr(socket, name))
                   for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex")]
        patches += [(socket.socket, name, getattr(socket.socket, name))
                    for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg")
                    if hasattr(socket.socket, name)]
        try:
            os.environ.update(_OFFLINE_ENV)
            sys.dont_write_bytecode = True
            for owner, name, _ in patches:
                setattr(owner, name, denied)
            yield
        finally:
            for owner, name, old in reversed(patches):
                setattr(owner, name, old)
            sys.dont_write_bytecode = old_bytecode
            for name, old in env.items():
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old


def _asset_file_identity(info):
    if not stat.S_ISREG(info.st_mode):
        raise EmbeddingRuntimeError("model asset descriptor must be a regular file")
    # Reading may update atime; it cannot legitimately change these fields.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _snapshot_assets(snapshot_path: str | Path, *, release_verified_pages: bool = False) -> tuple[Path, list[dict[str, Any]]]:
    """Verify the complete pinned snapshot; optionally advise verified file pages.

    Advice is best effort and reports no freed-memory guarantee. The opt-in holds
    all nine descriptors until every asset passes, then advises those descriptors
    without rereading bodies. Default callers retain the existing read behavior.
    """
    if type(release_verified_pages) is not bool:
        raise EmbeddingRuntimeError("release_verified_pages must be a boolean")
    snapshot = Path(snapshot_path).expanduser()
    if not snapshot.is_absolute():
        raise EmbeddingRuntimeError("snapshot must be an absolute local path")
    if (snapshot.name != PINNED_REVISION or snapshot.parent.name != "snapshots"
            or snapshot.parent.parent.name != "models--thenlper--gte-small"
            or not snapshot.is_dir() or snapshot.is_symlink()):
        raise EmbeddingRuntimeError("snapshot must identify the exact cached GTE model and revision")
    # Bound enumeration as well as bytes; unexpected config files must not change loading.
    with os.scandir(snapshot) as entries:
        names = set()
        for entry in entries:
            names.add(entry.name)
            if len(names) > len(_PINNED_ASSETS) + 2:
                raise EmbeddingRuntimeError("unexpected snapshot entries")
    expected = {name for name in _PINNED_ASSETS if "/" not in name} | {"1_Pooling"}
    if not expected <= names or names - expected - {"README.md"}:
        raise EmbeddingRuntimeError("missing or unexpected model assets")
    pooling = snapshot / "1_Pooling"
    if pooling.is_symlink() or not pooling.is_dir():
        raise EmbeddingRuntimeError("pooling configuration must be a local directory")
    with os.scandir(pooling) as entries:
        if [entry.name for entry in entries] != ["config.json"]:
            raise EmbeddingRuntimeError("unexpected pooling assets")
    repository = snapshot.parent.parent.resolve()
    manifest = []
    total = 0
    held = []
    with ExitStack() as opened:
        for name, (expected_size, expected_hash) in sorted(_PINNED_ASSETS.items()):
            path = snapshot / name
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(repository) or not resolved.is_file():
                raise EmbeddingRuntimeError("asset must resolve inside the pinned model cache")
            initial = resolved.stat()
            size = initial.st_size
            total += size
            if size != expected_size or total > MAX_ASSET_BYTES:
                raise EmbeddingRuntimeError("model assets exceed pinned size or byte limit")
            digest = hashlib.sha256()
            read = 0
            # Retain verified descriptors only for the explicitly selected policy.
            with ExitStack() as current:
                handle = (opened if release_verified_pages else current).enter_context(path.open("rb"))
                if release_verified_pages:
                    before = _asset_file_identity(os.fstat(handle.fileno()))
                    if before != _asset_file_identity(initial):
                        raise EmbeddingRuntimeError("model asset changed before verification")
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    read += len(block)
                    if read > expected_size:
                        raise EmbeddingRuntimeError("model asset grew during verification")
                    digest.update(block)
                if read != size or digest.hexdigest() != expected_hash:
                    raise EmbeddingRuntimeError("model asset SHA-256 does not match pinned bytes")
                if release_verified_pages:
                    if _asset_file_identity(os.fstat(handle.fileno())) != before:
                        raise EmbeddingRuntimeError("model asset changed during verification")
                    held.append((handle, before))
            manifest.append({"name": name, "sha256": digest.hexdigest(), "bytes": read})
        if release_verified_pages:
            # Refuse a changed earlier asset before the first advice call.
            for handle, before in held:
                if _asset_file_identity(os.fstat(handle.fileno())) != before:
                    raise EmbeddingRuntimeError("model asset changed after verification")
            advise = getattr(os, "posix_fadvise", None)
            policy = getattr(os, "POSIX_FADV_DONTNEED", None)
            if advise is not None and policy is not None:
                for handle, _ in held:
                    try:
                        advise(handle.fileno(), 0, 0, policy)
                    except TimeoutError:
                        raise
                    except (OSError, NotImplementedError):
                        # Unsupported hints must not change verified asset validity.
                        pass
    return snapshot, manifest


def _validate_model(model, torch) -> None:
    if type(model.max_seq_length) is not int or model.max_seq_length != MAX_TOKENS:
        raise EmbeddingRuntimeError("model token ceiling must already be exactly 512")
    tokenizer_limit = getattr(model.tokenizer, "model_max_length", None)
    if type(tokenizer_limit) is not int or tokenizer_limit < MAX_TOKENS:
        raise EmbeddingRuntimeError("tokenizer token ceiling must not be below 512")
    # Some compatible loaders retain the cached tokenizer's unbounded sentinel.
    # Lowering it is safe only after the model's existing 512 ceiling is checked.
    if tokenizer_limit > MAX_TOKENS:
        model.tokenizer.model_max_length = MAX_TOKENS
    if getattr(model.tokenizer, "padding_side", None) != "right":
        raise EmbeddingRuntimeError("the qualified tokenizer must use right padding")
    modules = list(model._modules.values())
    if ([type(module).__name__ for module in modules] != ["Transformer", "Pooling", "Normalize"]
            or any(not type(module).__module__.startswith("sentence_transformers.") for module in modules)):
        raise EmbeddingRuntimeError("model must contain Transformer, mean Pooling, and Normalize")
    pooling = modules[1]
    pooling_mode = getattr(pooling, "pooling_mode", None)
    if ((pooling_mode is not None and pooling_mode != "mean")
            or (pooling_mode is None and getattr(pooling, "pooling_mode_mean_tokens", None) is not True)):
        raise EmbeddingRuntimeError("mean pooling is required")
    for name in ("pooling_mode_cls_token", "pooling_mode_max_tokens", "pooling_mode_mean_sqrt_len_tokens",
                 "pooling_mode_weightedmean_tokens", "pooling_mode_lasttoken"):
        if getattr(pooling, name, False):
            raise EmbeddingRuntimeError("additional pooling modes are forbidden")
    if model.get_sentence_embedding_dimension() != 384:
        raise EmbeddingRuntimeError("model must produce 384-dimensional embeddings")
    seen = False
    for parameter in model.parameters():
        seen = True
        if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
            raise EmbeddingRuntimeError("all model parameters must be CPU float32")
    if not seen or any(module.training for module in model.modules()):
        raise EmbeddingRuntimeError("model must have parameters and be in eval mode")


def _untruncated_tokens(model, text: str) -> dict[str, Any]:
    encoded = model.tokenizer(text, add_special_tokens=True, truncation=False,
                              padding=False, return_attention_mask=True, return_token_type_ids=True)
    result = {name: list(encoded[name]) if name in encoded else None
              for name in ("input_ids", "attention_mask", "token_type_ids")}
    ids, mask, types = result.values()
    if (not isinstance(ids, list) or not ids or not isinstance(mask, list) or len(ids) != len(mask)
            or any(type(value) is not int or value < 0 for value in ids)
            or any(type(value) is not int or value != 1 for value in mask)
            or (types is not None and (len(types) != len(ids)
                or any(type(value) is not int or value < 0 for value in types)))):
        raise EmbeddingRuntimeError("tokenizer returned malformed untruncated token evidence")
    return result


def _captured_tokens(features, row: int) -> dict[str, Any]:
    try:
        mask = features["attention_mask"][row].detach().cpu().tolist()
        ids = features["input_ids"][row].detach().cpu().tolist()
        types = (features["token_type_ids"][row].detach().cpu().tolist()
                 if "token_type_ids" in features else None)
    except (KeyError, IndexError, AttributeError, TypeError) as exc:
        raise EmbeddingRuntimeError("missing actual forward token tensors") from exc
    if (not isinstance(mask, list) or not mask or len(mask) != len(ids)
            or len(mask) > MAX_TOKENS or any(type(item) is not int or item not in (0, 1) for item in mask)
            or (types is not None and len(types) != len(mask))):
        raise EmbeddingRuntimeError("malformed forward attention mask")
    active = [index for index, value in enumerate(mask) if value]
    if not active or active != list(range(len(active))):
        raise EmbeddingRuntimeError("model attention mask must contain an active prefix and right padding")
    return {"input_ids": [ids[index] for index in active],
            "attention_mask": [mask[index] for index in active],
            "token_type_ids": [types[index] for index in active] if types is not None else None}


def _produce_results(inputs: Sequence, model, torch, *, batch_size: int, token_input_digest) -> list[dict[str, Any]]:
    """Internal tensor operation; alone it makes no native-producer claim."""
    results: list[dict[str, Any] | None] = [None] * len(inputs)
    pending = []

    def flush():
        if not pending:
            return
        features = model.tokenize([item.text for _, item, _ in pending])
        captures = [_captured_tokens(features, row) for row in range(len(pending))]
        for captured, (_, _, counted) in zip(captures, pending):
            if captured != counted:
                raise EmbeddingRuntimeError("actual forward tokens differ from untruncated tokenizer output")
        with torch.inference_mode():
            output = model(features)["sentence_embedding"]
        if (output.dtype != torch.float32 or output.device.type != "cpu"
                or tuple(output.shape) != (len(pending), 384)
                or not bool(torch.isfinite(output).all())):
            raise EmbeddingRuntimeError("model output must be finite CPU float32 with dimension 384")
        # Do not renormalize or coerce values: the receipt binds the actual Normalize output.
        vectors = output.detach().cpu().tolist()
        for row, ((index, item, _), captured, vector) in enumerate(zip(pending, captures, vectors)):
            if _captured_tokens(features, row) != captured:
                raise EmbeddingRuntimeError("forward altered the captured token inputs")
            results[index] = {"input_id": item.input_id, "status": "embedded", "tokens": captured, "vector": vector}
        pending.clear()

    for index, item in enumerate(inputs):
        if not item.text.strip():
            results[index] = {"input_id": item.input_id, "status": "missing_input", "tokens": None, "vector": None}
            continue
        tokens = _untruncated_tokens(model, item.text)
        if len(tokens["input_ids"]) > MAX_TOKENS:
            results[index] = {"input_id": item.input_id, "status": "token_limit_exceeded",
                              "tokens": token_input_digest(tokens), "vector": None}
            continue
        pending.append((index, item, tokens))
        if len(pending) == batch_size:
            flush()
    flush()
    return results


def produce_native_embedding_receipt(inputs: Sequence, *, resolver,
                                     snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
                                     batch_size: int = MAX_BATCH_SIZE):
    """Embed source-verified whole texts, rejecting oversize inputs without inference.

    The model is constructed internally from exact pinned bytes. There is no
    model-factory injection, network fallback, truncation, context expansion,
    input normalization, or checkpoint write. Requires a dedicated process if
    other threads depend on socket/environment/CPU-thread settings.
    """
    from . import autoencoder_embedding_production as codec

    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise EmbeddingRuntimeError("batch_size must be an integer from 1 through 16")
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if source_hash != _LOADED_PRODUCER_SHA256:
        raise EmbeddingRuntimeError("producer source changed after this runtime was loaded")
    with _offline_guard():
        selected = codec.validate_embedding_inputs(inputs, resolver=resolver)
        snapshot, before = _snapshot_assets(snapshot_path)
        import torch
        import transformers
        import sentence_transformers
        import tokenizers

        old_threads = torch.get_num_threads()
        try:
            torch.set_num_threads(1)
            # Inference has no sampling. Preserve the caller's RNG state around the loader.
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(0)
                model = sentence_transformers.SentenceTransformer(
                    str(snapshot), local_files_only=True, trust_remote_code=False, device="cpu")
                model.eval()
                _validate_model(model, torch)
                results = _produce_results(selected, model, torch, batch_size=batch_size,
                                           token_input_digest=codec.token_input_digest)
            _, after = _snapshot_assets(snapshot)
            if before != after:
                raise EmbeddingRuntimeError("model assets changed during production")
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_hash:
                raise EmbeddingRuntimeError("producer source changed during production")
            execution = codec.native_execution_profile(batch_size=batch_size)
            producer = {"code_sha256": source_hash, "runtime_versions": {
                "python": platform.python_version(), "torch": str(torch.__version__),
                "transformers": str(transformers.__version__),
                "tokenizers": str(tokenizers.__version__),
                "sentence_transformers": str(sentence_transformers.__version__)}}
            return codec.build_embedding_production_receipt(
                selected, results=results, execution=execution, model_assets=before,
                producer=producer, resolver=resolver)
        finally:
            torch.set_num_threads(old_threads)
