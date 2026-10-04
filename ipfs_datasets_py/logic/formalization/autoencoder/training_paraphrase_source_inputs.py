"""Explicit TRAIN source preparation using the existing verified local encoders.

The inherited source shape and native execution validators are reused, but the
public plan/report and384 source metadata identify training augmentation. No
targets enter the producer, no preprocessing is fitted and no head is trained.
Caller-owned offline resource admission and frozen imports are mandatory.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import time

from . import fresh_scalar_source_inputs as native

SCHEMA = "training-paraphrase-source-plan/v1"
REPORT = "training-paraphrase-source-production/v1"
FALSE = dict(native.FALSE, fresh_holdout_claimed=False, lake_executed=False)
_require, digest = native._require, native.digest


def source_plan(source_rows, *, expected_source_rows_sha256, sealed_recipe_sha256):
    shape = native.source_plan(source_rows, expected_source_rows_sha256=expected_source_rows_sha256,
        sealed_comparison_sha256=sealed_recipe_sha256)
    result = dict(schema=SCHEMA, role="train_augmentation", shape_plan=shape,
        source_rows_sha256=expected_source_rows_sha256, sealed_recipe_sha256=sealed_recipe_sha256, **FALSE)
    result["plan_sha256"] = digest(result)
    return result


def _plan(plan):
    _require(type(plan) is dict and plan.get("schema") == SCHEMA, "explicit training source plan required")
    shape = plan.get("shape_plan")
    _require(type(shape) is dict, "complete target-free source shape required")
    expected = source_plan(shape.get("source_rows"), expected_source_rows_sha256=plan.get("source_rows_sha256"),
        sealed_recipe_sha256=plan.get("sealed_recipe_sha256"))
    _require(plan == expected, "training source plan changed")
    return expected


def _produce384(shape, config, directory, batch_size, deadline):
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    from ....optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as corpus
    pins = native._pins(runtime, codec, corpus)
    directory = Path(directory)
    _require(directory.is_absolute() and not directory.exists() and directory.parent.is_dir()
        and directory.parent.resolve() == directory.parent, "fresh owned TRAIN source artifact directory required")
    content, offsets = bytearray(), []
    for row in shape["source_inputs"]:
        start = len(content); content.extend(row["source_text"].encode()); end = len(content)
        offsets.append((start, end)); content.extend(b"\n\n")
    data = bytes(content); directory.mkdir(); path = directory/"training-source-texts.txt"
    with path.open("xb") as stream:
        stream.write(data)
    artifact = dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    source_artifact = corpus.SourceArtifact(artifact["sha256"], artifact["bytes"])
    inputs = []
    for row, (start, end) in zip(shape["source_inputs"], offsets):
        citation = "Authored TRAIN augmentation "+row["id"]
        span = corpus.SourceSpan(source_artifact, "diagnostic", shape["sealed_comparison_sha256"],
            row["id"], "en", citation, start, end)
        inputs.append(codec.EmbeddingInput(span, "authored-training-augmentation", row["id"], row["source_text"], citation))
    def resolve(ref):
        _require(ref == {k: artifact[k] for k in ("sha256", "bytes")}, "unexpected TRAIN source artifact request")
        return path
    native._checkpoint(deadline)
    receipt = runtime.produce_native_embedding_receipt(inputs, resolver=resolve,
        snapshot_path=config["snapshot_path"], batch_size=batch_size)
    native._checkpoint(deadline)
    payload = receipt.to_dict(); vectors = []
    _require(len(payload["results"]) == len(inputs), "native384 TRAIN coverage differs")
    for source, item, result in zip(shape["source_inputs"], inputs, payload["results"]):
        _require(result["input_id"] == item.input_id and result["status"] == "embedded",
            "native384 TRAIN source refused; no substitute")
        tokens = result["tokens"]["input_ids"]
        _require(1 <= len(tokens) <= 512, "native384 TRAIN token limit differs")
        vectors.append(dict(id=source["id"], source_sha256=native.authored.text_sha(source["source_text"]),
            vector=list(codec._decode_vector(result["vector"])), token_count=len(tokens), token_input_sha256=digest(tokens)))
    native._unchanged(pins)
    return dict(vectors=vectors, native_production=payload, producer_files=pins, source_artifact=artifact,
        representation=dict(kind="native_gte_small_semantic_embedding", dimension=384, semantic_embedding=True,
            model_id="thenlper/gte-small", revision=runtime.PINNED_REVISION, device="cpu", dtype="float32",
            experiment_token_limit=512, actual_forward_tokens_verified=True))


def produce_width(plan, *, dimension, asset_config, source_artifact_directory=None,
                  batch_size=4, max_seconds=600):
    _require(type(dimension) is int and dimension in (384, 768), "verified384/768 only; no fallback")
    owned = _plan(plan); shape = owned["shape_plan"]
    native._asset_config(dimension, asset_config)
    _require(type(batch_size) is int and batch_size == 4, "fixed batch size four required")
    _require(type(max_seconds) in (int, float) and 0 < max_seconds <= 600, "bounded native preparation deadline required")
    _require(dimension == 384 or source_artifact_directory is None, "unused source artifact directory forbidden")
    started = time.monotonic(); deadline = started+max_seconds
    own_path = Path(__file__).resolve(); own_sha = hashlib.sha256(own_path.read_bytes()).hexdigest()
    payload = {384:_produce384, 768:native._produce768}[dimension](
        shape, deepcopy(asset_config), source_artifact_directory, batch_size, deadline)
    native._checkpoint(deadline)
    result = dict(schema=REPORT, role="train_augmentation", complete=True, dimension=dimension,
        plan_sha256=owned["plan_sha256"], source_rows_sha256=owned["source_rows_sha256"],
        sealed_recipe_sha256=owned["sealed_recipe_sha256"], asset_config=deepcopy(asset_config),
        producer_files=dict(payload["producer_files"], **{str(own_path):own_sha}),
        producer_pin_scope="named producers; caller freezes full transitive closure",
        vectors=payload["vectors"], native_production=payload["native_production"],
        source_artifact=payload["source_artifact"], representation=payload["representation"],
        receipt_count=216, encoder_executed=True, batch_size=batch_size, max_seconds=max_seconds,
        elapsed_seconds=time.monotonic()-started, deadline_cooperative=True,
        native_forward_interruptible=False, **FALSE)
    result["production_sha256"] = digest(result)
    validate_report(owned, result)
    native._checkpoint(deadline)
    return result


def validate_report(plan, report):
    owned = _plan(plan); shape = owned["shape_plan"]
    _require(type(report) is dict and report.get("schema") == REPORT
        and report.get("role") == "train_augmentation" and report.get("complete") is True
        and report.get("plan_sha256") == owned["plan_sha256"]
        and report.get("source_rows_sha256") == owned["source_rows_sha256"]
        and report.get("sealed_recipe_sha256") == owned["sealed_recipe_sha256"]
        and report.get("production_sha256") == digest({k:v for k,v in report.items() if k != "production_sha256"}),
        "TRAIN production binding differs")
    dimension = report.get("dimension")
    _require(type(dimension) is int and dimension in (384, 768) and report.get("encoder_executed") is True
        and all(report.get(k) is False for k in FALSE), "TRAIN production authority or dimension differs")
    native._asset_config(dimension, report["asset_config"])
    rows = report.get("vectors")
    _require(type(rows) is list and len(rows) == report.get("receipt_count") == 216, "complete TRAIN vectors required")
    for row, source in zip(rows, shape["source_inputs"]):
        _require(type(row) is dict and set(row) == {"id", "source_sha256", "vector", "token_count", "token_input_sha256"}
            and row["id"] == source["id"] and row["source_sha256"] == native.authored.text_sha(source["source_text"]),
            "exact ordered TRAIN source identity required")
        native._vector(row["vector"], dimension)
        _require(type(row["token_count"]) is int and 1 <= row["token_count"] <= 512
            and type(row["token_input_sha256"]) is str and native.authored._SHA.fullmatch(row["token_input_sha256"]),
            "complete bounded native TRAIN token observation required")
    _require(type(report.get("producer_files")) is dict and report["producer_files"], "producer pins absent")
    native._unchanged(report["producer_files"])
    native._validate_native_binding(shape, report)
    if dimension == 384:
        _require(all(row["title"] == "authored-training-augmentation"
            for row in report["native_production"]["inputs"]), "native384 metadata must identify TRAIN augmentation")
    return dimension
