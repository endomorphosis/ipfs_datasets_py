"""Offline source joins for saved native384 and derived conditioning vectors.

Raw vectors rejoin pinned native production records. Derived vectors additionally
require a separately pinned complete original bundle and saved package bytes;
this is custody of recorded projections, not numerical replay or attestation.
No encoder, package loader, numerical projection or target is invoked here.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-native384-context-verification/v1"
MAX_ROWS = 4096
MAX_RECEIPTS = 128
MAX_RECEIPT_BYTES = 64 * 1024**2
MAX_RECEIPTS_BYTES = 256 * 1024**2
MAX_BUNDLE_BYTES = 64 * 1024**2
MAX_SOURCE_BYTES = 16 * 1024**2
MAX_PACKAGE_BYTES = 96 * 1024**2
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FALSE = dict.fromkeys(("qualified", "admitted", "source_semantics_verified",
    "runtime_computation_proven", "runtime_cryptographically_attested", "proof_authority",
    "target_access", "encoder_executed", "model_loaded", "projection_reexecuted",
    "training_executed"), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _wire(value):
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        _need(depth <= 64 and count <= 8_000_000, "context JSON structure exceeds bound")
        if type(item) is dict:
            _need(all(type(key) is str for key in item), "context JSON keys must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        else:
            _need(type(item) in (str, int, float, bool, type(None))
                  and (type(item) is not float or math.isfinite(item)), "finite plain JSON required")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode("utf-8")
    _need(len(raw) <= MAX_BUNDLE_BYTES, "context JSON bytes exceed bound")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _path(value):
    _need(type(value) is str and 0 < len(value) <= 4096
          and "\x00" not in value, "bounded artifact path required")
    path = Path(value)
    _need(path.is_absolute() and str(path) == value and path.resolve() == path,
          "canonical unaliased absolute artifact path required")
    return path


def _pin(value, maximum):
    _keys(value, ("path", "bytes", "sha256"), "artifact pin")
    _path(value["path"])
    _need(type(value["bytes"]) is int and 0 < value["bytes"] <= maximum,
          "artifact byte bound differs")
    _need(type(value["sha256"]) is str and _SHA.fullmatch(value["sha256"]), "artifact SHA256 required")
    return dict(value)


def _read(pin, maximum, *, retain=False):
    pin = _pin(pin, maximum)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(pin["path"], flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_size == pin["bytes"],
              "artifact is not the declared regular file")
        digest, total, chunks = hashlib.sha256(), 0, []
        while chunk := stream.read(min(1024**2, maximum - total + 1)):
            total += len(chunk)
            _need(total <= maximum, "artifact grew beyond bound")
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
        after, current = os.fstat(stream.fileno()), os.stat(pin["path"], follow_symlinks=False)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size,
                                 item.st_mtime_ns, item.st_ctime_ns)
        _need(identity(before) == identity(after) == identity(current)
              and Path(pin["path"]).resolve() == Path(pin["path"]), "artifact changed during read")
        _need(total == pin["bytes"] and digest.hexdigest() == pin["sha256"], "artifact bytes or hash differ")
    return b"".join(chunks) if retain else None


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate context JSON field")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite context JSON constant: " + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    _wire(value)
    return value


def _owner():
    from . import legal_native_conditioning
    return legal_native_conditioning


def _owner_pin(owner):
    path = Path(owner.__file__).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _native_module_pins(owner):
    # Exact directly used receipt/source helpers and their static dependencies.
    # Importing these modules does not call their model or worker entrypoints.
    prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
    names = ("autoencoder_embedding_production", "autoencoder_embedding_runtime",
             "autoencoder_corpus_manifest", "autoencoder_training_worker",
             "autoencoder_native_pool", "modal_autoencoder_adaptive_optimizer")
    modules = [owner] + [importlib.import_module(prefix + name) for name in names]
    pins = {module.__name__: _owner_pin(module)["sha256"] for module in modules}
    runtime = modules[2]
    _need(pins[runtime.__name__] == runtime._LOADED_PRODUCER_SHA256
          and pins[owner.__name__] == owner._SELF_SHA, "native receipt producer changed since import")
    return pins


def _sources(sources):
    _need(type(sources) is list and 0 < len(sources) <= MAX_ROWS, "one to 4096 ordered sources required")
    seen, total = set(), 0
    for source in sources:
        _keys(source, ("id", "source_text"), "target-free source")
        _need(type(source["id"]) is str and 0 < len(source["id"]) <= 512
              and source["id"] not in seen, "unique bounded source ID required")
        _need(type(source["source_text"]) is str and source["source_text"].strip()
              and len(source["source_text"]) <= 16384, "bounded source text required")
        total += len(source["source_text"].encode("utf-8"))
        _need(total <= MAX_SOURCE_BYTES, "aggregate source text exceeds bound")
        seen.add(source["id"])


def verify_native384_contexts(evidence, *, sources, source_resolver=None):
    """Verify saved producer/source/vector custody without numerical execution.

    Evidence has exactly stage, embedding_receipts and bundle. Raw384 requires
    bundle=None. Derived stages require an independent path/bytes/sha256 bundle
    pin; all original source rows must be present in the same order. A caller's
    independently selected pins remain trust inputs, never proof of execution.
    At most 4096 sources, 16 MiB source text, 128 receipts/256 MiB total,
    64 MiB saved bundle and 96 MiB package are accepted per call.
    """
    original = {"evidence": evidence, "sources": sources}
    original_raw = _wire(original)
    saved = json.loads(original_raw)
    evidence, sources = saved["evidence"], saved["sources"]
    _keys(evidence, ("stage", "embedding_receipts", "bundle"), "native384 evidence")
    stage = evidence["stage"]
    _need(type(stage) is str and stage in ("raw384", "core384", "trained384"), "unsupported native384 stage")
    _sources(sources)
    _need(source_resolver is None or callable(source_resolver), "source resolver must be callable")
    references = evidence["embedding_receipts"]
    _need(type(references) is list and 0 < len(references) <= MAX_RECEIPTS, "bounded native receipt inventory required")
    pins = [_pin(reference, MAX_RECEIPT_BYTES) for reference in references]
    _need(len({pin["sha256"] for pin in pins}) == len(pins), "duplicate native receipt")
    _need(sum(pin["bytes"] for pin in pins) <= MAX_RECEIPTS_BYTES, "aggregate native receipts exceed bound")
    bundle_pin = evidence["bundle"]
    if stage == "raw384":
        _need(bundle_pin is None, "raw384 must not carry a derived bundle")
    else:
        bundle_pin = _pin(bundle_pin, MAX_BUNDLE_BYTES)
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA, "native384 verifier source changed")
    for pin in pins:
        _read(pin, MAX_RECEIPT_BYTES)
    owner = _owner()
    owner_pin = _owner_pin(owner)
    native_module_pins = _native_module_pins(owner)
    index = owner._native_index(pins, source_resolver)
    package_pin, bundle = None, None
    if bundle_pin is not None:
        bundle = _json(_read(bundle_pin, MAX_BUNDLE_BYTES, retain=True))
        selected = owner.stage_rows(bundle, stage=stage, sources=sources)
        package = bundle["package"]
        package_path = _path(package["path"])
        package_pin = _pin({"path": package["path"], "sha256": package["sha256"],
                            "bytes": package_path.stat(follow_symlinks=False).st_size}, MAX_PACKAGE_BYTES)
        _read(package_pin, MAX_PACKAGE_BYTES)
    contexts, joins = [], []
    for ordinal, source in enumerate(sources):
        source_sha = hashlib.sha256(source["source_text"].encode("utf-8")).hexdigest()
        matches = index.get((source_sha, source["source_text"]), [])
        _need(bool(matches), "source has no successful native384 receipt")
        if bundle is None:
            vector, native = matches[0]
        else:
            row = bundle["rows"][ordinal]
            raw = row["stages"]["raw384"]
            matching = [(vector, native) for vector, native in matches
                        if _wire(vector) == _wire(raw["vector"])
                        and _wire(native) == _wire(raw["receipt"]["evidence"]["native"])]
            _need(bool(matching), "saved projection does not rejoin exact native vector and evidence")
            _, native = matching[0]
            chosen = selected[ordinal]
            _need(chosen["id"] == source["id"] and chosen["source_sha256"] == source_sha
                  and chosen["stage"] == stage, "saved projection source/order/stage differs")
            vector = chosen["vector"]
        _need(type(vector) is list and len(vector) == 384
              and all(type(value) is float and math.isfinite(value) for value in vector), "finite native384 context required")
        contexts.append({"id": source["id"], "source_sha256": source_sha, "context": list(vector)})
        joins.append({"id": source["id"], "source_sha256": source_sha,
                      "context_sha256": _digest(vector), "native": native})
    for pin in pins:
        _read(pin, MAX_RECEIPT_BYTES)
    if bundle_pin is not None:
        _read(bundle_pin, MAX_BUNDLE_BYTES)
        _read(package_pin, MAX_PACKAGE_BYTES)
    _need(_wire(original) == original_raw, "native384 caller inputs changed during verification")
    _need(_owner_pin(owner) == owner_pin
          and _native_module_pins(owner) == native_module_pins
          and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA, "native384 verifier producer changed")
    scope = "saved_native_source_vector_rejoin" if bundle is None else "saved_derived_projection_custody_only"
    descriptions = {_wire({key: join["native"][key] for key in
        ("model", "model_assets_sha256", "producer", "execution")}) for join in joins}
    native_producers = [json.loads(raw) for raw in sorted(descriptions)]
    producer = {"verifiers": native_module_pins, "native_producers": native_producers,
                "package": None if package_pin is None else package_pin["sha256"], "stage": stage}
    result = {"schema": SCHEMA, "contexts": contexts,
        "representation": {"dimension": 384, "representation_id": "actual_frozen_legal_ir/" + stage + "/v1",
                           "producer_sha256": _digest(producer)},
        "provenance": {"stage": stage, "embedding_receipts": pins, "bundle": bundle_pin,
                       "package": package_pin, "row_joins": joins,
                       "conditioning_owner": owner_pin, "native_module_pins": native_module_pins,
                       "native_producers": native_producers, "verifier_sha256": _SELF_SHA},
        "inspection": {"verification_scope": scope, "native_source_vectors_rejoined": True,
                       "saved_package_bytes_verified": package_pin is not None,
                       "derived_projection_computation_verified": False, **_FALSE}}
    return json.loads(_wire(result))


__all__ = ["verify_native384_contexts", "SCHEMA"]
