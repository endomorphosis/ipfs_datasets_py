"""Prepare bounded source-only native caches from exact physical occurrences.

The explicit produce384 lane calls only the fixed offline GTE-small owner.
Reuse performs no encoder work; its cache validators may import native owners
for metadata. Recorded native evidence grants no semantic or proof authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

CONFIG_SCHEMA = "prepare-arbitrary-native-legal-sources/v1"
SUMMARY_SCHEMA = "arbitrary-native-legal-source-preparation/v1"
MAX_SOURCE_ARTIFACT_BYTES = 8 * 1024**2
MAX_ALL_SOURCE_BYTES = 64 * 1024**2
_CONFIG_FIELDS = {"schema", "mode", "dimension", "source_requests_pin", "source_artifact_pins",
                  "native384_receipt_refs", "native768_report_refs", "snapshot_path", "batch_size"}
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FALSE = {name: False for name in ("target_access", "training_executed", "decoder_executed",
    "source_semantics_verified", "proof_authority", "admitted", "qualified", "formalized",
    "roundtrip_ok", "checkpoint_promoted", "default_promotion", "encoder_execution_attested")}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _cache():
    from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_source_cache
    return arbitrary_native_source_cache


def _producers():
    cache = _cache()
    path = str(Path(__file__).resolve())
    current = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    _require(current == _SELF_SHA, "preparation owner changed since import")
    return {**cache.producer_pins(), path: current}


class _SourceResolver:
    def __init__(self, pins):
        cache = _cache()
        _require(type(pins) is dict and 1 <= len(pins) <= cache.MAX_ROWS,
                 "one to64 exact source artifact pins required")
        self._pins = cache._parse(cache._wire(pins))
        self._identities = {}
        _require(all(type(key) is str and cache._SHA.fullmatch(key) is not None
                     and type(pin) is dict and pin.get("sha256") == key
                     for key, pin in self._pins.items()), "source artifact key must equal its SHA256")
        _require(all(type(pin.get("bytes")) is int for pin in self._pins.values())
                 and sum(pin["bytes"] for pin in self._pins.values()) <= MAX_ALL_SOURCE_BYTES,
                 "source artifact aggregate exceeds64MiB")
        for key, pin in self._pins.items():
            cache._read(pin, MAX_SOURCE_ARTIFACT_BYTES)
            self._identities[key] = self._identity(pin["path"])

    @staticmethod
    def _identity(path):
        info = os.lstat(path)
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)

    def __call__(self, artifact):
        cache = _cache()
        cache._closed(artifact, {"sha256", "bytes"}, "source artifact")
        _require(type(artifact["bytes"]) is int and type(artifact["sha256"]) is str,
                 "ordinary exact source artifact scalars required")
        key = artifact["sha256"]
        _require(key in self._pins and artifact["bytes"] == self._pins[key]["bytes"],
                 "source artifact has no exact configured pin")
        pin = self._pins[key]
        _require(self._identity(pin["path"]) == self._identities[key],
                 "source artifact generation changed")
        cache._read(pin, MAX_SOURCE_ARTIFACT_BYTES)
        _require(self._identity(pin["path"]) == self._identities[key],
                 "source artifact changed across read")
        # Both corpus and native-production validators consume an absolute
        # local path and independently reopen/hash it. Return that verified
        # locator rather than the bytes obtained by this stronger fence.
        return pin["path"]

    def fence(self):
        for key, pin in self._pins.items():
            self({"sha256": key, "bytes": pin["bytes"]})


def source_resolver(source_artifact_pins):
    """Return verified canonical paths with single-link generation fences.

    The callable follows the corpus/native producer resolver contract: its
    result is an absolute local path, not the source bytes themselves.
    """
    return _SourceResolver(source_artifact_pins)


def expand_embedding_inputs(requests, source_artifact_pins):
    """Expand physical paragraph/clause spans; deduplicate full input identities.

    Literal clause offsets are added to the parent's absolute byte selector.
    Different physical spans or provenance remain different embedding inputs,
    even when their source text is equal. Caller occurrence IDs are never used
    as encoder input identities.
    """
    cache = _cache()
    resolver = source_resolver(source_artifact_pins)
    checked, occurrences, _ = cache._requests(requests, resolver)
    _require({row["source"]["artifact"]["sha256"] for row in checked}
             == set(source_artifact_pins), "unused source artifact pins forbidden")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    inputs, aliases, selectors = {}, [], {}
    for request in checked:
        for occurrence in occurrences[request["id"]]:
            span = corpus.SourceSpan.from_dict(occurrence["source"])
            item = codec.EmbeddingInput(source=span, title=span.document_id, section=span.citation,
                                        text=occurrence["source_text"], citation=span.citation)
            payload = item.to_dict()
            if item.input_id in inputs:
                _require(cache._wire(inputs[item.input_id].to_dict()) == cache._wire(payload),
                         "embedding input identity collision")
            selector = (span.artifact.sha256, span.byte_start, span.byte_end)
            _require(selector not in selectors or selectors[selector] == item.input_id,
                     "same physical selector has contradictory source provenance")
            selectors[selector] = item.input_id
            inputs.setdefault(item.input_id, item)
            aliases.append({"request_id": request["id"], "role": occurrence["role"],
                            "slot": occurrence["slot"], "input_id": item.input_id,
                            "source_sha256": hashlib.sha256(item.text.encode("utf-8")).hexdigest(),
                            "source": asdict(span)})
    resolver.fence()
    return list(inputs.values()), aliases


def _config(value):
    cache = _cache()
    cache._closed(value, _CONFIG_FIELDS, "preparation config")
    value = cache._parse(cache._wire(value))
    _require(value["schema"] == CONFIG_SCHEMA and type(value["mode"]) is str
             and value["mode"] in ("produce384", "reuse"), "explicit preparation schema and mode required")
    _require(type(value["dimension"]) is int and value["dimension"] in (384, 768),
             "raw native384/768 only; no width substitution")
    _require(type(value["native384_receipt_refs"]) is list
             and type(value["native768_report_refs"]) is list, "explicit native reference lists required")
    if value["mode"] == "produce384":
        _require(value["dimension"] == 384 and not value["native384_receipt_refs"]
                 and not value["native768_report_refs"], "produce384 cannot mix existing native lanes")
        snapshot = value["snapshot_path"]
        _require(type(snapshot) is str and Path(snapshot).is_absolute()
                 and str(Path(snapshot).resolve(strict=True)) == snapshot and Path(snapshot).is_dir(),
                 "explicit canonical existing native384 snapshot required")
        _require(type(value["batch_size"]) is int and 1 <= value["batch_size"] <= 16,
                 "native384 batch size must be integer1..16")
    else:
        _require(value["snapshot_path"] is None and value["batch_size"] is None,
                 "reuse cannot configure an encoder")
        selected, unused = ((value["native384_receipt_refs"], value["native768_report_refs"])
                            if value["dimension"] == 384 else
                            (value["native768_report_refs"], value["native384_receipt_refs"]))
        _require(bool(selected) and not unused, "only the selected native reuse lane is permitted")
    return value


def _fresh_directory(path):
    _require(isinstance(path, (str, Path)), "explicit output directory required")
    selected = Path(path)
    _require(selected.is_absolute() and str(selected) == str(selected.resolve(strict=False))
             and selected.parent.is_dir()
             and str(selected.parent) == str(selected.parent.resolve(strict=True)),
             "canonical output path with existing parent required")
    os.mkdir(selected, 0o700)
    return selected


def _write(directory, name, raw):
    _require(type(raw) is bytes, "exact output bytes required")
    path = directory / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def prepare(config, *, output_directory):
    """Prepare/reuse a cache; only explicit produce384 executes native encoders.

    Call this inside the caller's admitted dedicated CPU1 process. No resource
    lease, optimizer, decoder, target lookup or network fallback is added here.
    Output creation is exclusive; failed production artifacts remain durable.
    """
    cache = _cache()
    config = _config(config)
    pins = _producers()
    request_bytes = cache._read(config["source_requests_pin"], cache.MAX_REQUEST_BYTES)
    requests = cache._parse(request_bytes)
    resolver = source_resolver(config["source_artifact_pins"])
    cache._requests(requests, resolver)
    _require({row["source"]["artifact"]["sha256"] for row in requests}
             == set(config["source_artifact_pins"]), "unused source artifact pins forbidden")
    inputs, aliases = (expand_embedding_inputs(requests, config["source_artifact_pins"])
                       if config["mode"] == "produce384" else ([], []))
    directory = _fresh_directory(output_directory)
    refs = list(config["native384_receipt_refs"] if config["dimension"] == 384
                else config["native768_report_refs"])
    producer_started = producer_calls = encoded = 0
    try:
        if config["mode"] == "produce384":
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
            for start in range(0, len(inputs), codec.MAX_RECORDS):
                producer_started += 1
                receipt = runtime.produce_native_embedding_receipt(inputs[start:start+codec.MAX_RECORDS],
                    resolver=resolver, snapshot_path=config["snapshot_path"], batch_size=config["batch_size"])
                producer_calls += 1
                _require(type(receipt) is codec.EmbeddingProductionReceipt and receipt.native_execution_profile,
                         "fixed native owner must return a native receipt; diagnostic fixtures refused")
                encoded += sum(row["status"] == "embedded" for row in receipt.to_dict()["results"])
                refs.append(_write(directory, "native384-receipt-" + str(producer_calls).zfill(3) + ".json",
                                   receipt.to_bytes()))
        kwargs = {"native384_receipt_refs": refs} if config["dimension"] == 384 else {"native768_report_refs": refs}
        result = cache.plan_arbitrary_native_source_cache(requests, dimension=config["dimension"],
                                                          source_resolver=resolver, **kwargs)
        _require(cache._read(config["source_requests_pin"], cache.MAX_REQUEST_BYTES) == request_bytes,
                 "source requests changed during preparation")
        resolver.fence()
        _require(_producers() == pins, "preparation producers changed")
        output = _write(directory, "source-cache.json", cache._wire(result) + b"\n")
        summary = {"schema": SUMMARY_SCHEMA, "status": "completed", "mode": config["mode"],
            "dimension": config["dimension"], "config_sha256": cache.digest(config),
            "source_requests_pin": config["source_requests_pin"],
            "source_artifact_pins": config["source_artifact_pins"], "source_cache": output,
            "source_cache_status": result["status"], "counts": result["counts"],
            "dispositions": result["dispositions"], "native_receipt_refs": refs,
            "expanded_encoder_input_aliases": aliases, "unique_native384_inputs_requested": len(inputs),
            "native384_producer_calls_started": producer_started,
            "native384_producer_calls_returned": producer_calls,
            "actual_native384_encoded_input_count": encoded,
            "encoded_input_count_scope": "embedded records in returned verified native receipts",
            "native384_production_executed_by_helper": producer_calls > 0,
            "native768_production_executed_by_helper": False,
            "encoder_executed_by_cache_adapter": False, "producer_evidence_is_record_consistency": True,
            "optimizer_calls": 0, "decoder_calls": 0, "admission_masks": {name: 0 for name in
                ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision",
                 "proof_supervision", "fidelity_evaluation")}, "formal_output": None,
            "producer_files": pins, **_FALSE}
        summary["summary_sha256"] = cache.digest(summary)
        _write(directory, "summary.json", cache._wire(summary) + b"\n")
        return summary
    except Exception as error:
        failure = {"schema": SUMMARY_SCHEMA, "status": "failed", "mode": config["mode"],
            "dimension": config["dimension"], "error_type": type(error).__name__,
            "native384_producer_calls_started": producer_started,
            "native_receipt_refs": refs, "native384_producer_calls_returned": producer_calls,
            "actual_native384_encoded_input_count": encoded if producer_started == producer_calls else None,
            "encoded_input_count_scope": "embedded records in returned verified native receipts; incomplete calls unknown",
            "optimizer_calls": 0, "decoder_calls": 0,
            "formal_output": None, **_FALSE}
        _write(directory, "failure-summary.json", cache._wire(failure) + b"\n")
        raise


def read_config(config_pin):
    """Authenticate a config file before the production function can execute."""
    cache = _cache()
    return _config(cache._parse(cache._read(config_pin, cache.MAX_REQUEST_BYTES)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--config-bytes", required=True, type=int)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args(argv)
    config = read_config({"path": args.config, "bytes": args.config_bytes, "sha256": args.config_sha256})
    summary = prepare(config, output_directory=args.output_directory)
    print(json.dumps({"status": summary["status"], "source_cache_status": summary["source_cache_status"],
                      "counts": summary["counts"], "source_cache": summary["source_cache"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
