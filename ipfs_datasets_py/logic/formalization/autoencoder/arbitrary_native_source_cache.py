"""Source-only receipt reuse for new physical source occurrences at 384/768D.

No encoder, decoder, tensor library, target, download or fitted transform enters
this owner. Recorded producer consistency is not execution attestation. Every
paragraph and literal clause retains its caller-requested artifact occurrence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

SCHEMA = "arbitrary-native-source-cache/v1"
MAX_ROWS = 64
MAX_CLAUSES = 8
MAX_REFERENCE_BYTES = 64 * 1024**2
MAX_TOTAL_REFERENCE_BYTES = 256 * 1024**2
MAX_SOURCE_BYTES = 64 * 1024**2
MAX_REQUEST_BYTES = 1024**2
FALSE = {name: False for name in ("admitted", "qualified", "formalized", "roundtrip_ok", "proof_authority",
    "source_semantics_verified", "training_executed", "target_access", "teacher_qualified",
    "checkpoint_promoted", "runtime_qualified", "encoder_executed_by_adapter", "encoder_execution_attested")}
_SHA = re.compile(r"[0-9a-f]{64}")
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ArbitraryNativeSourceCacheError(ValueError):
    """Malformed evidence refuses, with a stable source-preparation disposition."""
    def __init__(self, message, disposition="invalid_source_evidence"):
        super().__init__(message)
        self.disposition = disposition


def _require(condition, message, disposition="invalid_source_evidence"):
    if not condition:
        raise ArbitraryNativeSourceCacheError(message, disposition)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ArbitraryNativeSourceCacheError("strict JSON required") from error


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda value:
            (_ for _ in ()).throw(ArbitraryNativeSourceCacheError("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ArbitraryNativeSourceCacheError("invalid strict JSON") from error


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(reference, maximum=MAX_REFERENCE_BYTES, *, retain=True, max_links=1):
    _closed(reference, {"path", "bytes", "sha256"}, "artifact reference")
    path, size, sha = reference["path"], reference["bytes"], reference["sha256"]
    _require(type(path) is str and Path(path).is_absolute() and str(Path(path).resolve(strict=True)) == path,
             "canonical absolute artifact path required")
    _require(type(size) is int and 0 < size <= maximum and type(sha) is str and _SHA.fullmatch(sha),
             "bounded exact artifact identity required")
    for part in (Path(path), *Path(path).parents):
        _require(not part.is_symlink(), "artifact path aliases refused")
    before = os.lstat(path)
    _require(stat.S_ISREG(before.st_mode) and 1 <= before.st_nlink <= max_links and before.st_size == size,
             "ordinary artifact with declared link policy and exact size required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    parts, count, checksum = [], 0, hashlib.sha256()
    try:
        _require(_identity(os.fstat(fd)) == _identity(before), "artifact changed before read")
        while True:
            block = os.read(fd, min(1024**2, size-count+1))
            if not block:
                break
            count += len(block)
            _require(count <= size, "artifact grew during read")
            checksum.update(block)
            if retain:
                parts.append(block)
        _require(_identity(os.fstat(fd)) == _identity(before) == _identity(os.lstat(path)),
                 "artifact changed during read")
    finally:
        os.close(fd)
    _require(count == size and checksum.hexdigest() == sha, "artifact bytes/SHA256 differ")
    return b"".join(parts) if retain else None


def producer_pins():
    directory = Path(__file__).resolve().parent
    optimizer = directory.parents[2] / "optimizers" / "logic_theorem_optimizer"
    paths = [Path(__file__).resolve()] + [directory / (name + ".py") for name in (
        "legal_native_conditioning", "source_embeddings_768", "source_embeddings_768_complete",
        "gte_multilingual_profile", "dimension_source_inputs")] + [optimizer / (name + ".py") for name in (
        "autoencoder_embedding_runtime", "autoencoder_embedding_production", "autoencoder_corpus_manifest")]
    pins = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    _require(pins[str(Path(__file__).resolve())] == _SELF_SHA, "resident cache owner changed")
    return pins


def _vector(values, dimension):
    _require(type(values) is list and len(values) == dimension, "exact native vector width required")
    for value in values:
        _require(type(value) is float and math.isfinite(value), "finite float32 vector scalars required")
        try:
            _require(struct.unpack(">f", struct.pack(">f", value))[0] == value, "exact float32 values required")
        except (OverflowError, struct.error) as error:
            raise ArbitraryNativeSourceCacheError("float32 vector exceeds range") from error
    _require(abs(math.sqrt(math.fsum(value*value for value in values))-1.0) <= 1e-5,
             "native L2 vector required; no normalization repair")


def _tokens(value, dimension):
    _closed(value, {"input_ids", "attention_mask", "token_type_ids"} if dimension == 384
            else {"input_ids", "attention_mask"}, "native token record")
    ids, mask = value["input_ids"], value["attention_mask"]
    _require(type(ids) is list and 1 <= len(ids) <= 512
        and all(type(v) is int and 0 <= v < 2**31 for v in ids), "complete512 native token IDs required")
    _require(type(mask) is list and len(mask) == len(ids) and all(type(v) is int and v == 1 for v in mask),
             "untruncated unpadded native attention mask required")
    if dimension == 384 and value["token_type_ids"] is not None:
        values = value["token_type_ids"]
        _require(type(values) is list and len(values) == len(ids)
            and all(type(v) is int and 0 <= v < 2**31 for v in values), "native token type IDs differ")


def _requests(rows, resolver):
    from ....optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as corpus
    _require(callable(resolver), "source resolver required")
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "one to64 physical source occurrences required",
             "source_count_exceeded")
    seen, total, artifacts, requests, occurrences = set(), 0, {}, [], {}
    for row in rows:
        _closed(row, {"id", "source_text", "source"}, "source request")
        identity, text = row["id"], row["source_text"]
        _require(type(identity) is str and identity.strip() and 0 < len(identity) <= 512 and "\x00" not in identity and identity not in seen,
                 "unique bounded source ID required")
        identity.encode("utf-8")
        _require(type(text) is str and text.strip() and "\x00" not in text, "nonempty exact source text required")
        raw = text.encode("utf-8"); total += len(raw)
        _require(total <= MAX_REQUEST_BYTES, "source requests exceed byte bound", "source_bytes_exceeded")
        _closed(row["source"], {"artifact", "source_kind", "release_id", "document_id", "language", "citation",
                               "byte_start", "byte_end", "normalization"}, "typed SourceSpan")
        _closed(row["source"]["artifact"], {"sha256", "bytes"}, "source artifact")
        _require(all(type(row["source"][key]) is str for key in
                     ("source_kind", "release_id", "document_id", "language", "citation", "normalization"))
                 and type(row["source"]["artifact"]["sha256"]) is str, "exact SourceSpan scalar types required")
        span = corpus.SourceSpan.from_dict(row["source"])
        _require(span.normalization == "identity", "identity source normalization required")
        source = asdict(span)
        _require(_wire(source) == _wire(row["source"]), "typed SourceSpan fields differ")
        ref = asdict(span.artifact)
        _require(ref["bytes"] <= MAX_SOURCE_BYTES, "source artifact exceeds byte bound")
        key = (ref["sha256"], ref["bytes"])
        if key not in artifacts:
            artifacts[key] = corpus._read_verified(resolver(dict(ref)), ref, MAX_SOURCE_BYTES)
            artifacts[key].decode("utf-8")
            _require(sum(len(value) for value in artifacts.values()) <= MAX_TOTAL_REFERENCE_BYTES,
                     "aggregate source artifacts exceed byte bound")
        _require(artifacts[key][span.byte_start:span.byte_end] == raw, "source occurrence differs from exact artifact span",
                 "source_origin_mismatch")
        pieces = text.split("\n\n")
        _require(1 <= len(pieces) <= MAX_CLAUSES and all(piece.strip() for piece in pieces),
                 "one to eight nonempty literal clauses required", "clause_count_exceeded")
        char, byte, items = 0, 0, []
        for slot, piece in enumerate(pieces):
            length = len(piece.encode("utf-8")); origin = deepcopy(source)
            origin.update(byte_start=span.byte_start+byte, byte_end=span.byte_start+byte+length)
            corpus.SourceSpan.from_dict(origin)
            items.append({"role": "clause", "slot": slot, "source_text": piece, "source": origin,
                          "char_start": char, "char_end": char+len(piece), "byte_start": byte, "byte_end": byte+length})
            char += len(piece)+2; byte += length+2
        requests.append({"id": identity, "source_text": text, "source": source})
        occurrences[identity] = [{"role": "paragraph", "slot": None, "source_text": text, "source": source}] + items
        seen.add(identity)
    return requests, occurrences, len(artifacts)


def _references(references):
    _require(type(references) is list and 1 <= len(references) <= 16, "one to16 exact native references required")
    for ref in references:
        _closed(ref, {"path", "bytes", "sha256"}, "native reference")
        _require(type(ref["bytes"]) is int and ref["bytes"] > 0, "ordinary native reference byte count required")
    _require(sum(ref["bytes"] for ref in references) <= MAX_TOTAL_REFERENCE_BYTES,
             "aggregate native reference byte bound exceeded")
    owned = deepcopy(references)
    _require(len({digest(ref) for ref in owned}) == len(owned), "duplicate native artifact reference")
    for ref in owned:
        _read(ref, retain=False)
    return owned


def _native384_records(references, resolver):
    from . import legal_native_conditioning as native
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    index = native._native_index(references, resolver)
    tokens, refused = {}, []
    for ref in references:
        receipt = codec.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"], expected_size_bytes=ref["bytes"])
        for item, result in zip(receipt.inputs, receipt.to_dict()["results"]):
            if result["status"] == "embedded":
                tokens[(receipt.sha256, result["input_id"])] = result["tokens"]
            else:
                refused.append(((item.text, digest(asdict(item.source))), {"disposition": result["status"],
                    "receipt": deepcopy(ref), "input_id": item.input_id}))
    result = {}
    for (_, text), candidates in index.items():
        for vector, evidence in candidates:
            token = tokens[(evidence["receipt"]["sha256"], evidence["input_id"])]
            _require(digest(token) == evidence["tokens_sha256"], "native384 complete token binding differs")
            record = {"vector": deepcopy(vector), "tokens": deepcopy(token), "producer_evidence": deepcopy(evidence),
                      "producer_source_span_present": True, "receipt": deepcopy(evidence["receipt"]), "input_id": evidence["input_id"]}
            result.setdefault((text, digest(evidence["source"])), []).append(record)
    for key, record in refused:
        result.setdefault(key, []).append(record)
    return result


def _native768_records(references, resolver):
    from . import source_embeddings_768_complete as complete
    from . import dimension_source_inputs as bounded
    profile = complete.reference._PROFILE
    records = {}
    for ref in references:
        report = _parse(_read(ref))
        schema = report.get("schema") if type(report) is dict else None
        fresh = schema == "fresh-bounded-native768-production/v1"
        fields = {"schema", "assets", "source_rows", "token_rows", "forward_observations", "complete_checkpoint_loading",
            "dense_path_verification", "implementation", "execution_profile", "historical_profile_token_limit",
            "experiment_token_limit", "cached_profile_relabelled", "forward_validation"}
        if fresh:
            fields.add("vectors")
        else:
            _require(schema == bounded.BOUNDED_SCHEMA, "native768 report lacks bounded source/token/forward evidence")
            fields |= {"plan_sha256", "status", "receipt_count", "receipts", "bounded_owner", "native_profile_id",
                "all_actual_forward_tokens_checked", "runtime_versions", "elapsed_seconds", "encoder_executed", *bounded.FALSE}
        _closed(report, fields, "bounded native768 report")
        _require(report["implementation"] == complete._implementation()
            and type(report["historical_profile_token_limit"]) is int and report["historical_profile_token_limit"] == 8192
            and type(report["experiment_token_limit"]) is int and report["experiment_token_limit"] == 512
            and report["cached_profile_relabelled"] is False, "native768 implementation/context profile differs")
        execution = report["execution_profile"]
        expected = dict(device="cpu", dtype="float32", pooling="cls", normalization="l2", attention_implementation="eager",
                        max_tokens_including_special_tokens=512)
        _closed(execution, {*expected, "batch_size"} if fresh else {*expected, "batch_size", "padding_side", "max_seconds", "deadline_cooperative"},
                "native768 execution profile")
        _require(all(type(execution[k]) is type(v) and execution[k] == v for k, v in expected.items())
            and type(execution["batch_size"]) is int and 1 <= execution["batch_size"] <= 16,
            "native768 actual CPU512 execution profile differs")
        if not fresh:
            _require(report["status"] == "completed" and report["encoder_executed"] is True
                and report["all_actual_forward_tokens_checked"] is True and all(report[k] is False for k in bounded.FALSE)
                and report["native_profile_id"] == complete.PROFILE_ID and type(report["plan_sha256"]) is str
                and _SHA.fullmatch(report["plan_sha256"]) and execution["padding_side"] == "right"
                and execution["deadline_cooperative"] is True and type(execution["max_seconds"]) in (int, float)
                and math.isfinite(execution["max_seconds"]) and 0 < execution["max_seconds"] <= 600,
                "native768 production status or authority differs")
            owner = report["bounded_owner"]
            _read(owner, retain=False, max_links=128)
            current_owner = Path(bounded.__file__).resolve()
            _require(owner["bytes"] == current_owner.stat().st_size
                and owner["sha256"] == hashlib.sha256(current_owner.read_bytes()).hexdigest(),
                "bounded native768 historical owner bytes differ from current implementation")
            _closed(report["runtime_versions"], {"python", "torch", "transformers", "tokenizers", "safetensors"}, "runtime version record")
            _require(all(type(v) is str and 0 < len(v) <= 128 for v in report["runtime_versions"].values())
                and type(report["elapsed_seconds"]) in (int, float) and math.isfinite(report["elapsed_seconds"])
                and report["elapsed_seconds"] >= 0, "native768 runtime/timing metadata differs")
        assets = report["assets"]
        _closed(assets, {"schema", "status", "profile_id", "model_revision", "code_revision", "model_directory", "code_directory",
            "manifest_sha256", "files", "model_numerics_verified", "proof_authority", "unavailable_reasons"}, "native768 assets")
        _require(assets["schema"] == profile.RECEIPT_SCHEMA and assets["status"] == "available"
            and assets["profile_id"] == profile.PROFILE_ID and assets["model_revision"] == profile.MODEL_REV
            and assets["code_revision"] == profile.CODE_REV and type(assets["manifest_sha256"]) is str
            and _SHA.fullmatch(assets["manifest_sha256"]) and assets["model_numerics_verified"] is False
            and assets["proof_authority"] is False and assets["unavailable_reasons"] == [], "native768 asset profile differs")
        _require(type(assets["files"]) is list and len(assets["files"]) == 7, "complete seven-asset native768 inventory required")
        inventory = {}
        for item in assets["files"]:
            _closed(item, {"relative_to", "path", "bytes", "sha256"}, "native768 asset")
            _require(type(item["relative_to"]) is str and type(item["path"]) is str, "typed native768 asset names required")
            key = (item["relative_to"], item["path"])
            _require(key in profile.PUBLISHED_ASSETS and key not in inventory
                and _wire({k:item[k] for k in ("bytes", "sha256")}) == _wire(profile.PUBLISHED_ASSETS[key]),
                "native768 published asset identity differs")
            root = assets["model_directory" if key[0] == "model" else "code_directory"]
            _require(type(root) is str and Path(root).is_absolute(), "native768 absolute asset root required")
            _read({"path": str(Path(root)/key[1]), "bytes": item["bytes"], "sha256": item["sha256"]},
                  maximum=1024**3, retain=False)
            inventory[key] = item
        loading = report["complete_checkpoint_loading"]
        _closed(loading, {"architecture", "tensor_count", "tensor_names", "missing_keys", "unexpected_keys", "mismatched_keys",
            "error_msgs", "classifier_loaded", "classifier_logits_used_for_dense_embedding"}, "complete native768 loading")
        names = loading["tensor_names"]
        _require(loading["architecture"] == "NewForTokenClassification" and type(loading["tensor_count"]) is int
            and loading["tensor_count"] == 138 and type(names) is list
            and all(type(name) is str and (name.startswith("new.") or name in {"classifier.weight", "classifier.bias"}) for name in names)
            and len(names) == len(set(names)) == 138
            and {"classifier.weight", "classifier.bias"} <= set(names) and loading["classifier_loaded"] is True
            and loading["classifier_logits_used_for_dense_embedding"] is False
            and all(loading[k] == [] for k in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")),
            "complete138 native768 encoder/classifier loading required")
        # Inspect only the authenticated safetensors header, never tensor values.
        weight_path = Path(assets["model_directory"]) / "model.safetensors"
        weight_before = os.lstat(weight_path)
        with weight_path.open("rb") as stream:
            header_size_raw = stream.read(8)
            _require(len(header_size_raw) == 8, "complete safetensors header required")
            header_size = struct.unpack("<Q", header_size_raw)[0]
            _require(0 < header_size <= 16*1024**2, "bounded safetensors header required")
            header = _parse(stream.read(header_size))
        _require(_identity(weight_before) == _identity(os.lstat(weight_path)) and type(header) is dict
            and set(names) == set(header)-{"__metadata__"}, "native768 loading names differ from authenticated checkpoint header")
        validation = bounded.validate_forward_observations(report)
        _require(_wire(report["forward_validation"]) == _wire(validation), "native768 forward validation differs")
        rows, tokens = report["source_rows"], report["token_rows"]
        _require(1 <= len(rows) <= 4096 and len(rows) == len(tokens), "bounded native768 source inventory required")
        for token in tokens:
            _tokens(token, 768)
        _require(_wire(report["dense_path_verification"]) == _wire(dict(encoder_and_complete_hidden_states_bitwise_equal=True,
            evaluation_mode=True, probe_tokens=len(tokens[0]["input_ids"]), scope="first admitted source; source used only, no targets")),
            "native768 dense path verification differs")
        if fresh:
            values = report["vectors"]
            _require(type(values) is list and len(values) == len(rows), "native768 vector coverage differs")
        else:
            _require(type(report["receipt_count"]) is int and report["receipt_count"] == len(rows)
                and type(report["receipts"]) is list and len(report["receipts"]) == len(rows), "native768 receipt coverage differs")
            values = []
            for row, token, receipt in zip(rows, tokens, report["receipts"]):
                _closed(receipt, {"schema", "id", "source_sha256", "profile_id", "dimension", "embedding",
                    "token_count_including_special_tokens", "token_input_sha256", "truncated", "normalized", "asset_manifest_sha256"}, "native768 receipt")
                _require(receipt["schema"] == complete.reference.RECEIPT_SCHEMA and receipt["id"] == row["id"]
                    and receipt["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
                    and receipt["profile_id"] == complete.PROFILE_ID and type(receipt["dimension"]) is int and receipt["dimension"] == 768
                    and type(receipt["token_count_including_special_tokens"]) is int
                    and receipt["token_count_including_special_tokens"] == len(token["input_ids"])
                    and receipt["token_input_sha256"] == complete.reference._digest(token["input_ids"])
                    and receipt["truncated"] is False and receipt["normalized"] is True
                    and receipt["asset_manifest_sha256"] == assets["manifest_sha256"], "native768 receipt source/token/vector profile differs")
                values.append(receipt["embedding"])
        for row, token, vector in zip(rows, tokens, values):
            _vector(vector, 768)
            record = {"vector": deepcopy(vector), "tokens": deepcopy(token), "receipt": deepcopy(ref), "input_id": row["id"],
                "producer_source_span_present": False, "producer_evidence": dict(profile_id=complete.PROFILE_ID,
                    asset_manifest_sha256=assets["manifest_sha256"], implementation=deepcopy(report["implementation"]),
                    complete_checkpoint_tensor_count=138, forward_validation=deepcopy(validation))}
            records.setdefault(row["source_text"], []).append(record)
    return records


def plan_arbitrary_native_source_cache(rows, *, dimension, native384_receipt_refs=None,
                                     native768_report_refs=None, source_resolver):
    """Reuse exact recorded vectors; keep ready occurrences and explicit refusals."""
    _require(type(dimension) is int and dimension in (384, 768), "native384/768 only; no8 or projected fallback",
             "unsupported_dimension")
    _require((native768_report_refs is None) if dimension == 384 else (native384_receipt_refs is None),
             "unused native lane references forbidden")
    pins = producer_pins()
    requests, occurrences, artifact_count = _requests(rows, source_resolver)
    references = _references(native384_receipt_refs if dimension == 384 else native768_report_refs)
    index = (_native384_records if dimension == 384 else _native768_records)(references, source_resolver)
    ready, contexts, origins, dispositions = [], {}, {}, []
    for request in requests:
        attached, unavailable = [], []
        for occurrence in occurrences[request["id"]]:
            text = occurrence["source_text"]
            key = (text, digest(occurrence["source"])) if dimension == 384 else text
            matches = index.get(key, [])
            reason = "missing_native_receipt" if not matches else None
            if not matches and dimension == 384 and any(k[0] == text for k in index):
                reason = "source_origin_mismatch"
            if matches and "disposition" in matches[0]:
                reason = matches[0]["disposition"]
            elif matches:
                record = deepcopy(matches[0]); _vector(record["vector"], dimension)
                ids = record["tokens"]["input_ids"]
                if not (type(ids) is list and 1 <= len(ids) <= 512):
                    reason = "token_limit_exceeded"
                else:
                    _tokens(record["tokens"], dimension)
                    attached.append({**deepcopy(occurrence), "native": record})
            if reason:
                unavailable.append({"role": occurrence["role"], "slot": occurrence["slot"], "source": deepcopy(occurrence["source"]),
                    "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "reason": reason})
        status = "refused" if unavailable else "ready"
        dispositions.append({"id": request["id"], "status": status, "unavailable_inputs": unavailable})
        if unavailable:
            continue
        ready.append({"id": request["id"], "source_text": request["source_text"], "input": attached[0]["native"]["vector"]})
        segments = [{k: item[k] for k in ("source_text", "char_start", "char_end", "byte_start", "byte_end")}
                    | {"source_sha256": hashlib.sha256(item["source_text"].encode()).hexdigest(),
                       "embedding_sha256": digest(item["native"]["vector"]), "vector": deepcopy(item["native"]["vector"])}
                    for item in attached[1:]]
        contexts[request["id"]] = {"source_sha256": hashlib.sha256(request["source_text"].encode()).hexdigest(), "segments": segments}
        origins[request["id"]] = attached
    for ref in references:
        _read(ref, retain=False)
    # A second resolver pass closes ordinary source changes during verification.
    _require(_wire(_requests(requests, source_resolver)[0]) == _wire(requests), "source requests changed")
    _require(producer_pins() == pins, "cache producers changed during operation")
    result = dict(schema=SCHEMA, dimension=dimension, source_requests=requests, source_requests_sha256=digest(requests),
        status="ready" if len(ready) == len(requests) else ("partial" if ready else "refused"), complete=len(ready) == len(requests),
        rows=ready, source_contexts=contexts, input_origins=origins, dispositions=dispositions,
        native_receipt_refs=references, producer_files=pins, receipt_consistency_only=True,
        input_contract=dict(max_clauses=8, actual_token_limit=512, representation="raw_native_semantic_embedding",
                            adapter_transforms_applied=False, source_origin_verified=True),
        counts=dict(requested_rows=len(requests), ready_rows=len(ready), refused_rows=len(requests)-len(ready),
            clause_occurrences=sum(len(items)-1 for items in occurrences.values()),
            ready_clause_occurrences=sum(len(value["segments"]) for value in contexts.values()), source_artifacts=artifact_count), **FALSE)
    result["cache_sha256"] = digest(result)
    return result


def validate_arbitrary_native_source_cache(cache, *, source_requests, native384_receipt_refs=None,
                                         native768_report_refs=None, source_resolver):
    """Rebuild against original caller requests; a newly resealed mutation refuses."""
    if type(cache) is bytes:
        _require(len(cache) <= MAX_REFERENCE_BYTES, "cache JSON exceeds bound")
        cache = _parse(cache)
    _require(type(cache) is dict and _wire(cache) and len(_wire(cache)) <= MAX_REFERENCE_BYTES, "bounded closed cache required")
    expected = plan_arbitrary_native_source_cache(source_requests, dimension=cache.get("dimension"),
        native384_receipt_refs=native384_receipt_refs, native768_report_refs=native768_report_refs, source_resolver=source_resolver)
    _require(_wire(cache) == _wire(expected), "cache differs from freshly verified original requests/receipts")
    return expected
