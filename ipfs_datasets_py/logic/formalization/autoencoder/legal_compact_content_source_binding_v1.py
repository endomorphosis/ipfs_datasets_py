"""Exact source/receipt/vector custody for the existing unbound generator.

This version wraps, rather than promotes, qualified v1 generation and batch
reports. A consistent native-profile receipt is not inference attestation,
independent context permission, source semantics, training or legal authority.
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
import struct

CONDITIONING_SCHEMA = "legal-compact-source-conditioning/v1"
CONDITIONING_PROFILE = "exact-native-gte-small384-receipt-reuse/v1"
SCHEMA = "legal-compact-content-generation-source-binding/v1"
PROFILE = "exact-source-receipt-to-compact-generation/v1"
ENCODER_BINDING_SCHEMA = "legal-compact-source-encoder-binding/v1"
MAX_SOURCE_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES = 192 * 1024 * 1024
MAX_REPORT_BYTES = 96 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_POPULATION_BYTES = 128 * 1024
PINNED_ASSET_MANIFEST_SHA256 = "def8d7e04c05560b1d0dd1fa9317be7a59a1ba8399ca725be0ac807a9a264edc"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_INPUT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SOURCE_SPECS = (
    ("generation", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_generation_v1",
     "logic/formalization/autoencoder/legal_compact_content_generation_v1.py",
     "7509be744d274473e5691f136d48b232b42103b76bd0ddd11b4f065d03350c10"),
    ("conditioning", "ipfs_datasets_py.logic.formalization.autoencoder.legal_native_conditioning",
     "logic/formalization/autoencoder/legal_native_conditioning.py",
     "48709fa4a521046ad753c87afe2732d17968e33d51ab2f43e4c4fefe2182059f"),
    ("codec", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production",
     "optimizers/logic_theorem_optimizer/autoencoder_embedding_production.py",
     "735ca0597186e094d736ef58435c82956c4ab805a68fc7a6adbfc0ee21ee889f"),
    ("runtime", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime",
     "optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py",
     "ce80ed6294009e04580051e6eb06a817d74a8a56f04814ad0a698e3d27dd0d41"),
    (None, None, "optimizers/logic_theorem_optimizer/autoencoder_corpus_manifest.py",
     "b067f05b3cfc28cb213a83519530f7148b2a5fa7d5b25809e87e1f7c286f9a5d"),
    (None, None, "optimizers/logic_theorem_optimizer/autoencoder_training_worker.py",
     "bde3bd327df59f2e7557eac8aa2e0989ceb1128bc39918bf8cf46011e7bd9415"),
)
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_encoder_authenticated",
    "runtime_computation_proven", "runtime_cryptographically_attested", "source_authority_authenticated",
    "model_revision_authenticated", "conditioning_space_training_compatibility_verified",
    "context_permission_verified", "context_independence_verified", "prefix_origin_verified",
    "held_out_generation_verified", "training_qualified", "evaluation_gold_qualified",
    "legal_accuracy_established", "convergence_proved", "accepted", "admitted", "Lean_admitted"), False)
_LIMITATIONS = [
    "Exact source, native-profile receipt, token and float32-vector consistency is not cryptographic runtime attestation or legal-source semantic equivalence.",
    "This adapter reuses recorded vectors and never executes an encoder, changes a vector, trains a model or establishes compact-head training compatibility.",
    "Caller-supplied independent original pins define this custody window. Replacing all original artifacts and expected pins cannot be distinguished from a different authorized operation.",
    "Named source fences do not attest arbitrary preloaded bytecode, mutable third-party globals or native binaries; qualified checked-source execution supplies its separate finite evidence.",
    "Source context and compact signature/role context are distinct identities. Context permission, independence, target absence and statutory interpretation remain unverified.",
    "The existing unbound v1 generation and batch transport remain unchanged, including encoder_sha256:null and their no-credit disposition.",
]


class CompactContentSourceBindingError(ValueError):
    """Exact source, receipt, whole bound or original-bound replay refused."""


def _need(ok, message):
    if not ok:
        raise CompactContentSourceBindingError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent SHA256 required: " + label)


def _witness(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_identity(path, expected_sha, expected_size=None, *, maximum=MAX_SOURCE_BYTES):
    _need(type(path) is Path or isinstance(path, Path), "ordinary filesystem path required")
    _need(path.is_absolute() and path.resolve(strict=True) == path
          and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents), "canonical unaliased artifact path required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= maximum and (expected_size is None or before.st_size == expected_size),
          "bounded single-link artifact with exact size required")
    digest, count = hashlib.sha256(), 0
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        _need(_witness(os.fstat(stream.fileno())) == _witness(before), "artifact changed before read")
        while True:
            block = stream.read(min(1024 * 1024, before.st_size - count + 1))
            if not block:
                break
            count += len(block)
            _need(count <= before.st_size, "artifact grew during read")
            digest.update(block)
        after = os.fstat(stream.fileno())
    _need(_witness(before) == _witness(after) == _witness(path.lstat()) and count == before.st_size
          and digest.hexdigest() == expected_sha, "artifact source witness, bytes or SHA256 differ")
    return {"path": str(path), "bytes": count, "sha256": expected_sha}, _witness(after)


def _source_snapshot():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SOURCE_SPECS[0][2]).is_file():
                _need(candidate.resolve(strict=True) == candidate, "canonical dependency tree required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical source dependencies unavailable")
    observed = [_read_identity(_SELF_PATH, _SELF_SHA)]
    observed += [_read_identity(root / relative, sha) for _, _, relative, sha in _SOURCE_SPECS]
    return root, observed


def _owners():
    root, observed = _source_snapshot()
    modules, failure = {}, None
    try:
        for key, name, relative, _ in _SOURCE_SPECS:
            if key is not None:
                module = importlib.import_module(name)
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                      "canonical public owner origin required")
                modules[key] = module
        modules["generation"]._sources()
        return root, observed, modules
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_source_snapshot() == (root, observed), "source changed during lazy imports")
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing source-binding lazy-import check also failed.")


def _operation(original, source_resolver, work):
    loaded, failure, snapshot, token = None, None, None, None
    references, source_checks = [], []

    def fence():
        if loaded is None:
            return
        root, observed, modules = loaded
        generation = modules["generation"]
        if snapshot is not None:
            _need(generation._fingerprint(generation._copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
                  and generation._fingerprint(snapshot) == token, "original or detached operation inputs changed")
        _need(_source_snapshot() == (root, observed), "source-binding operation sources changed")
        for key, _, relative, _ in _SOURCE_SPECS:
            if key is not None:
                _need(type(modules[key].__file__) is str and Path(modules[key].__file__).absolute() == root / relative,
                      "public owner origin changed")
        generation._sources()
        _fixed_asset_manifest(modules)
        for reference, witness in references:
            _need(_read_identity(Path(reference["path"]), reference["sha256"], reference["bytes"],
                maximum=MAX_RECEIPT_BYTES)[1] == witness, "receipt changed during source-binding operation")

    try:
        loaded = _owners()
        generation = loaded[2]["generation"]
        snapshot = generation._copy(original, MAX_INPUT_BYTES, allow_bytes=True)
        token = generation._fingerprint(snapshot)
        result = work(snapshot, loaded, fence, references, source_checks)
        raw = generation._wire(result, MAX_REPORT_BYTES)
        fence()
        return json.loads(raw)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            for check in source_checks:
                check()
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing source-binding source/input custody check also failed.")


def _request(value, modules):
    generation, codec = modules["generation"], modules["codec"]
    checked = generation._copy(value, MAX_SOURCE_REQUEST_BYTES)
    _need(type(checked) is dict and set(checked) == {"occurrence_id", "input"}, "closed source request required")
    identity = checked["occurrence_id"]
    _need(type(identity) is str and identity.strip() and 0 < len(identity) <= 256, "bounded occurrence ID required")
    item = checked["input"]
    _need(type(item) is dict and set(item) == {"input_id", "source", "title", "section", "text", "citation"},
          "closed public EmbeddingInput required")
    _need(type(item["input_id"]) is str and _INPUT_ID.fullmatch(item["input_id"]) is not None,
          "derived receipt input ID required")
    _need(all(type(item[name]) is str for name in ("title", "section", "text", "citation")),
          "plain embedding input strings required")
    source = item["source"]
    _need(type(source) is dict and set(source) == {"artifact", "source_kind", "release_id", "document_id",
          "language", "citation", "byte_start", "byte_end", "normalization"}, "closed typed source span required")
    _need(all(type(source[name]) is str for name in ("source_kind", "release_id", "document_id", "language",
          "citation", "normalization")) and all(type(source[name]) is int for name in ("byte_start", "byte_end")),
          "plain source span scalar types required")
    artifact = source["artifact"]
    _need(type(artifact) is dict and set(artifact) == {"sha256", "bytes"}
          and type(artifact["bytes"]) is int and 0 < artifact["bytes"] <= MAX_RECEIPT_BYTES,
          "closed bounded source artifact required")
    _hash(artifact["sha256"], "source artifact")
    parsed = codec.EmbeddingInput.from_dict(item)
    _need(generation._wire(parsed.to_dict(), MAX_SOURCE_REQUEST_BYTES) == generation._wire(item, MAX_SOURCE_REQUEST_BYTES),
          "source request differs from exact public input reconstruction")
    return checked, parsed


def _reference(value):
    _need(type(value) is dict and set(value) == {"path", "sha256", "bytes"}, "closed receipt reference required")
    _hash(value["sha256"], "receipt")
    _need(type(value["path"]) is str and 0 < len(value["path"]) <= 4096
          and type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_RECEIPT_BYTES,
          "bounded exact receipt reference required")
    return value


def _fixed_asset_manifest(modules):
    generation, runtime = modules["generation"], modules["runtime"]
    assets = runtime._PINNED_ASSETS
    _need(type(assets) is dict and len(assets) == 9
          and all(type(name) is str and type(value) is tuple and len(value) == 2
          and type(value[0]) is int and type(value[1]) is str for name, value in assets.items()),
          "exact native encoder asset profile required")
    expected = [{"name": name, "bytes": size, "sha256": sha} for name, (size, sha) in sorted(assets.items())]
    _need(generation._digest(expected) == PINNED_ASSET_MANIFEST_SHA256,
          "mutable native encoder asset profile differs from fixed manifest")
    return expected


def _asset_profile(modules, payload):
    generation = modules["generation"]
    _fixed_asset_manifest(modules)
    _need(generation._digest(payload["model_assets"]) == PINNED_ASSET_MANIFEST_SHA256,
          "native encoder assets differ from fixed nine-asset profile")
    _need(payload["producer"]["code_sha256"] == _SOURCE_SPECS[3][3], "native encoder producer implementation differs")
    _need(payload["execution"]["kind"] == "native", "injected fixtures are not native encoder outputs")
    binding = {"schema": ENCODER_BINDING_SCHEMA, "conditioning_space": "raw_native_gte_small384",
               "model": payload["model"], "model_assets": payload["model_assets"],
               "producer": payload["producer"], "execution": payload["execution"]}
    return binding, generation._digest(binding)


def _bits(vector):
    _need(type(vector) is list and len(vector) == 384
          and all(type(value) is float and math.isfinite(value) for value in vector), "exact native float32 vector required")
    try:
        result = b"".join(struct.pack(">f", value) for value in vector)
    except (OverflowError, struct.error) as error:
        raise CompactContentSourceBindingError("native float32 vector exceeds range") from error
    _need(list(struct.unpack(">384f", result)) == vector, "native vector scalars are not exact float32 values")
    return result


def _prepare(data, loaded, fence, references, source_checks, source_resolver):
    _, observed, modules = loaded
    generation, codec = modules["generation"], modules["codec"]
    _need(callable(source_resolver), "source verification requires a resolver")
    request, item = _request(data["source_request"], modules)
    _hash(data["expected_source_request_sha256"], "source request")
    _need(generation._digest(request, MAX_SOURCE_REQUEST_BYTES) == data["expected_source_request_sha256"],
          "source request commitment differs")
    _need(type(data["input_id"]) is str and data["input_id"] == item.input_id, "explicit input ID differs from source request")
    reference = _reference(data["receipt_ref"])
    _, witness = _read_identity(Path(reference["path"]), reference["sha256"], reference["bytes"], maximum=MAX_RECEIPT_BYTES)
    references.append((reference, witness))
    receipt = codec.load_embedding_production_receipt(reference["path"], expected_sha256=reference["sha256"],
        expected_size_bytes=reference["bytes"], resolver=source_resolver)
    source_checks.append(lambda: receipt.validate_sources(source_resolver))
    fence()
    payload = receipt.to_dict()
    _need(receipt.native_execution_profile, "injected fixtures are not native encoder outputs")
    encoder_binding, encoder_sha = _asset_profile(modules, payload)
    selected = [(index, candidate, payload["results"][index]) for index, candidate in enumerate(receipt.inputs)
                if candidate.input_id == data["input_id"]]
    _need(len(selected) == 1, "one explicit receipt input required")
    index, candidate, result = selected[0]
    _need(generation._wire(candidate.to_dict(), MAX_SOURCE_REQUEST_BYTES)
          == generation._wire(item.to_dict(), MAX_SOURCE_REQUEST_BYTES), "receipt input source or metadata differs")
    if result["status"] != "missing_input":
        codec.validate_embedding_inputs([item], resolver=source_resolver)
        source_checks.append(lambda: codec.validate_embedding_inputs([item], resolver=source_resolver))
        fence()
    conditioning, vector_sha, conditioning_sha = None, None, None
    if result["status"] == "embedded":
        bits = bytes.fromhex(result["vector"]["bits"])
        conditioning = list(struct.unpack(">384f", bits))
        reused = modules["conditioning"].embedding_rows(
            [{"id": request["occurrence_id"], "source_text": item.text}],
            embedding_receipts=[reference], source_resolver=source_resolver)
        fence()
        _need(type(reused) is list and len(reused) == 1 and type(reused[0]) is dict
              and set(reused[0]) == {"id", "source_text", "embedding"}
              and reused[0]["id"] == request["occurrence_id"] and reused[0]["source_text"] == item.text,
              "public native conditioning row differs")
        _need(_bits(reused[0]["embedding"]) == bits == _bits(conditioning),
              "selected receipt vector differs from exact public native reuse bits")
        vector_sha, conditioning_sha = hashlib.sha256(bits).hexdigest(), generation._digest(conditioning)
    _need(result["status"] in ("embedded", "missing_input", "token_limit_exceeded"), "unsupported receipt status")
    _asset_profile(modules, payload)
    fence()
    return {"schema": CONDITIONING_SCHEMA, "profile": CONDITIONING_PROFILE, "status": result["status"],
        "occurrence_id": request["occurrence_id"], "input_id": item.input_id, "input": item.to_dict(),
        "source_request_sha256": data["expected_source_request_sha256"],
        "source_sha256": hashlib.sha256(item.text.encode("utf-8")).hexdigest(), "source_span": item.to_dict()["source"],
        "receipt": reference, "receipt_input_index": index, "receipt_input_count": len(payload["inputs"]),
        "receipt_status_counts": payload["status_counts"], "encoder_binding": encoder_binding,
        "encoder_binding_sha256": encoder_sha, "tokens": result["tokens"],
        "tokens_record_sha256": generation._digest(result["tokens"]), "native_vector": result["vector"],
        "native_vector_bits_sha256": vector_sha, "conditioning": conditioning, "conditioning_sha256": conditioning_sha,
        "source_bytes_verified": result["status"] != "missing_input", "source_receipt_binding_verified": result["status"] == "embedded",
        "native_execution_record_present": True, "encoder_executed_by_adapter": False,
        "runtime_computation_proven": False, "source_encoder_authenticated": False,
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "owner_pins": [row[0] for row in observed], "limitations": list(_LIMITATIONS)}


def prepare_compact_source_conditioning_v1(source_request, receipt_ref, *, expected_source_request_sha256,
                                          input_id, source_resolver):
    """Reuse one explicit receipt row; unavailable rows retain null conditioning."""
    original = dict(source_request=source_request, receipt_ref=receipt_ref,
        expected_source_request_sha256=expected_source_request_sha256, input_id=input_id)
    return _operation(original, source_resolver, lambda data, loaded, fence, references, source_checks:
        _prepare(data, loaded, fence, references, source_checks, source_resolver))


def compact_source_request_sha256(source_request):
    """Hash a closed reconstructed source request, without source authentication."""
    def work(data, loaded, fence, references, source_checks):
        request, _ = _request(data["source_request"], loaded[2])
        fence()
        return {"sha256": loaded[2]["generation"]._digest(request, MAX_SOURCE_REQUEST_BYTES)}
    return _operation({"source_request": source_request}, None, work)["sha256"]


def compact_source_binding_sha256(report):
    """Hash the explicit new conditioning/outer report; hashing grants no authority."""
    def work(data, loaded, fence, references, source_checks):
        value = data["report"]
        _need(type(value) is dict and value.get("schema") in (CONDITIONING_SCHEMA, SCHEMA), "versioned source-binding report required")
        fence()
        return {"sha256": loaded[2]["generation"]._digest(value, MAX_REPORT_BYTES)}
    return _operation({"report": report}, None, work)["sha256"]


def _population(raw, expected, modules):
    _hash(expected, "original whole population")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_POPULATION_BYTES
          and hashlib.sha256(raw).hexdigest() == expected, "whole population commitment differs")
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate population JSON key")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(CompactContentSourceBindingError("finite population JSON required")))
    value = modules["generation"]._copy(value, MAX_POPULATION_BYTES)
    _need(type(value) is dict and set(value) == {"schema", "partition", "selection_sha256", "rows"}
          and value["schema"] == "legal-relational-batch-population/v1" and type(value["rows"]) is list
          and 1 <= len(value["rows"]) <= 64, "existing complete population transport required")
    _need(type(value["partition"]) is str and 0 < len(value["partition"]) <= 128, "bounded population partition required")
    _hash(value["selection_sha256"], "population selection")
    seen = set()
    for row in value["rows"]:
        _need(type(row) is dict and set(row) == {"id", "source_sha256", "context_sha256"}, "closed existing population row required")
        identity = row["id"]
        _need(type(identity) is str and identity.strip() and 0 < len(identity) <= 256 and identity not in seen,
              "bounded unique population occurrence required")
        for key in ("source_sha256", "context_sha256"):
            _hash(row[key], key)
        seen.add(identity)
    return value


def _bind(data, loaded, fence, references, source_checks, source_resolver):
    generation = loaded[2]["generation"]
    source = _prepare(data, loaded, fence, references, source_checks, source_resolver)
    _need(source["status"] == "embedded", "source conditioning unavailable: " + source["status"])
    _need(type(data["occurrence_id"]) is str and data["occurrence_id"] == source["occurrence_id"],
          "generation occurrence differs from source request")
    population = _population(data["population_raw"], data["expected_population_sha256"], loaded[2])
    selected = [row for row in population["rows"] if row["id"] == data["occurrence_id"]]
    _need(len(selected) == 1 and selected[0]["source_sha256"] == source["source_sha256"],
          "population occurrence source differs from exact source span")
    options = {key: data[key] for key in ("expected_checkpoint_sha256", "expected_context_sha256",
               "max_new_tokens", "prefix_origin", "context_origin")}
    # The public adapter performs full original-bound numerical generation replay.
    # Its output is preserved verbatim, including the deliberately null encoder.
    adapter = generation.prepare_compact_content_generation_batch_prediction_v1(
        data["report"], data["checkpoint"], source["conditioning"], data["prefix_ids"], data["context_raw"],
        data["population_raw"], expected_generation_sha256=data["expected_generation_sha256"],
        expected_population_sha256=data["expected_population_sha256"], occurrence_id=data["occurrence_id"], **options)
    fence()
    _need(adapter["predictions"]["generation"]["encoder_sha256"] is None
          and adapter["predictions"]["generation"]["kind"] == "decoder_declared", "unbound v1 batch transport changed")
    _need(adapter["prediction_row"]["source_sha256"] == source["source_sha256"]
          and adapter["prediction_row"]["context_sha256"] == selected[0]["context_sha256"], "batch occurrence identities differ")
    report = data["report"]
    _asset_profile(loaded[2], {"model": source["encoder_binding"]["model"],
        "model_assets": source["encoder_binding"]["model_assets"], "producer": source["encoder_binding"]["producer"],
        "execution": source["encoder_binding"]["execution"]})
    fence()
    return {"schema": SCHEMA, "profile": PROFILE, "status": "source_receipt_bound_unqualified_generation",
        "source_conditioning": source, "source_conditioning_sha256": generation._digest(source, MAX_REPORT_BYTES),
        "source_request_sha256": data["expected_source_request_sha256"], "generation_report": report,
        "generation_report_sha256": data["expected_generation_sha256"], "population_sha256": data["expected_population_sha256"],
        "population_row": selected[0], "occurrence_id": data["occurrence_id"],
        "source_context_sha256": selected[0]["context_sha256"],
        "compact_context_raw_sha256": report["context_raw_sha256"], "compact_context_sha256": report["context_sha256"],
        "encoder_binding_sha256": source["encoder_binding_sha256"], "batch_adapter": adapter, "exposure": report["exposure"],
        "source_receipt_binding_verified": True, "source_bytes_verified": True, "native_execution_record_present": True,
        "encoder_executed_by_adapter": False, "source_encoder_authenticated": False, "runtime_computation_proven": False,
        "model_executed": report["model_executed"], "training_executed": False, "compact_optimizer_executed": False,
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "owner_pins": [row[0] for row in loaded[1]], "limitations": list(_LIMITATIONS)}


def _binding_inputs(report, checkpoint, prefix_ids, context_raw, population_raw, source_request, receipt_ref,
        expected_generation_sha256, expected_population_sha256, expected_source_request_sha256, input_id,
        occurrence_id, expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    return dict(report=report, checkpoint=checkpoint, prefix_ids=prefix_ids, context_raw=context_raw,
        population_raw=population_raw, source_request=source_request, receipt_ref=receipt_ref,
        expected_generation_sha256=expected_generation_sha256, expected_population_sha256=expected_population_sha256,
        expected_source_request_sha256=expected_source_request_sha256, input_id=input_id, occurrence_id=occurrence_id,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)


def bind_compact_content_generation_to_source_v1(report, checkpoint, prefix_ids, context_raw, population_raw,
        source_request, receipt_ref, *, expected_generation_sha256, expected_population_sha256,
        expected_source_request_sha256, input_id, occurrence_id, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin, source_resolver):
    """Wrap one replayed generation in an exact explicit source/receipt binding."""
    original = _binding_inputs(report, checkpoint, prefix_ids, context_raw, population_raw, source_request, receipt_ref,
        expected_generation_sha256, expected_population_sha256, expected_source_request_sha256, input_id,
        occurrence_id, expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    return _operation(original, source_resolver, lambda data, loaded, fence, references, source_checks:
        _bind(data, loaded, fence, references, source_checks, source_resolver))


def validate_compact_content_generation_source_binding_v1(outer_report, report, checkpoint, prefix_ids,
        context_raw, population_raw, source_request, receipt_ref, *, expected_report_sha256,
        expected_generation_sha256, expected_population_sha256, expected_source_request_sha256, input_id,
        occurrence_id, expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin,
        context_origin, source_resolver):
    """Require an independent outer pin and full replay against the same originals."""
    original = _binding_inputs(report, checkpoint, prefix_ids, context_raw, population_raw, source_request, receipt_ref,
        expected_generation_sha256, expected_population_sha256, expected_source_request_sha256, input_id,
        occurrence_id, expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    original.update(outer_report=outer_report, expected_report_sha256=expected_report_sha256)
    def work(data, loaded, fence, references, source_checks):
        generation = loaded[2]["generation"]
        _hash(data["expected_report_sha256"], "original outer report")
        _need(generation._digest(data["outer_report"], MAX_REPORT_BYTES) == data["expected_report_sha256"],
              "source-binding report commitment differs")
        regenerated = _bind(data, loaded, fence, references, source_checks, source_resolver)
        fence()
        _need(generation._wire(regenerated, MAX_REPORT_BYTES) == generation._wire(data["outer_report"], MAX_REPORT_BYTES),
              "source binding differs from complete original-bound replay")
        return regenerated
    return _operation(original, source_resolver, work)


__all__ = ["CompactContentSourceBindingError", "prepare_compact_source_conditioning_v1",
    "compact_source_request_sha256", "compact_source_binding_sha256",
    "bind_compact_content_generation_to_source_v1", "validate_compact_content_generation_source_binding_v1"]
