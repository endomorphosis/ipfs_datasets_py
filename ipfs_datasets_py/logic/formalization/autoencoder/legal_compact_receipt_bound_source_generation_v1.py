"""Full-population native-receipt custody around the existing trained caller.

This adapter reuses an already supplied receipt. It does not run an encoder,
authenticate inference permission, change a conditioning vector or train a
model. Embedded-only inner selection is explicit and never changes the outer
denominator. Existing source-context and trained-generation reports are kept.
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

SCHEMA = "legal-compact-receipt-bound-trained-source-generation/v1"
PROFILE = "full-selected-native-receipt-trained-bos-generation-384/v1"
MAX_ROWS, MAX_NEW_TOKENS = 16, 12
MAX_POPULATION_BYTES = 128 * 1024
MAX_SOURCE_BYTES, MAX_CATALOG_BYTES = 65536, 524288
MAX_CHECKPOINT_BYTES = MAX_RECEIPT_BYTES = MAX_RECEIPT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES, MAX_REPORT_BYTES = 192 * 1024 * 1024, 96 * 1024 * 1024
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 12_000_000, 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ("conditioning", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_source_binding_v1",
     "logic/formalization/autoencoder/legal_compact_content_source_binding_v1.py",
     "7727ccc82edd771685831e97e614231190bc32a6229b442a1510bf7bc3f15955"),
    ("source", "ipfs_datasets_py.logic.autoformal.legal_compact_source_context_v1",
     "logic/autoformal/legal_compact_source_context_v1.py",
     "efaa7e3ccc73d572561569e05d02270625076ac9e5708fea2d62d60f7f294dc2"),
    ("trained_source", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_trained_source_generation_v2",
     "logic/formalization/autoencoder/legal_compact_trained_source_generation_v2.py",
     "e89a495993f998da7c61e549f708e69c6e38fd20dc86b6132e1d7d57dcb8c5e1"),
    ("generation", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_trained_runtime_v2",
     "logic/formalization/autoencoder/legal_compact_content_trained_runtime_v2.py",
     "43037fe64c58de0bcfc2072178eabe1276b4a020863e20b9498a634763b56e5a"),
    ("receipt", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production",
     "optimizers/logic_theorem_optimizer/autoencoder_embedding_production.py",
     "735ca0597186e094d736ef58435c82956c4ab805a68fc7a6adbfc0ee21ee889f"),
)
_AUTHORITY = dict.fromkeys((
    "source_encoder_authenticated", "runtime_cryptographically_attested", "runtime_computation_proven",
    "conditioning_space_training_compatibility_verified", "conditioning_producer_verified",
    "context_permission_verified", "context_independence_verified", "permitted_inference_context_verified",
    "source_semantics_verified", "source_authority_authenticated", "held_out_generation_verified",
    "legal_accuracy_established", "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted", "Lean_admitted",
), False)
_LIMITATIONS = [
    "The supplied complete outer population defines this custody window; completeness outside that population is not established.",
    "The existing native receipt conditioner checks exact physical input, source bytes, tokens and float32 vector consistency. A record-consistent receipt is not independent runtime or encoder authentication.",
    "This adapter reuses receipts and executes no encoder or optimizer. Stored checkpoint steps remain historical declarations; no native-space training compatibility follows from matching vector width.",
    "Catalogs and source nominations remain caller_supplied_unverified. Frozen pre-generation processing establishes this operation's ordering, not prior exposure, target independence or inference permission.",
    "All outer receipt and context dispositions are retained. Missing and over-limit conditioning stays null and never becomes a zero vector or a generated inner row.",
    "The unchanged trained caller performs original BOS generation and one mandatory adapter replay for nominated inner rows. An outer validator repeats that complete preparation; numerical counters from the original and validation operations are separate.",
    "Raw catalog/source-context identity and compact model-context identity are distinct. The nested decoder declaration retains encoder_sha256:null and no comparison credit.",
    "No target or reference bodies are inputs. Syntactic completion is not statutory correctness, held-out reconstruction, training eligibility, accepted meaning or Lean admission.",
    "Named source endpoints and input fences do not prove arbitrary preloaded bytecode, third-party binaries, an operating-system sandbox or mutable callback implementation identity.",
]
_PURE_FIELDS = ("population", "population_sha256", "checkpoint_sha256", "checkpoint_preflight",
    "receipt_inventory", "source_conditionings", "source_reports", "mapping", "inner_population",
    "inner_population_utf8", "inner_population_sha256", "pre_generation_sha256", "settings")


class ReceiptBoundTrainedSourceError(ValueError):
    """Whole input, receipt/source custody, bound or original replay refused."""


def _need(value, message):
    if not value:
        raise ReceiptBoundTrainedSourceError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _copy(value, maximum, *, allow_bytes=False):
    """Detach ordinary bounded values before serialization or owner callbacks."""
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()
    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "whole input/output byte bound exceeded")
    def text(item):
        _need(len(item) <= maximum, "bounded string required")
        charge(2)
        for character in item:
            code = ord(character)
            _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary NUL-free scalar UTF8 required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                charge(2)
            elif code < 32:
                charge(6)
            else:
                charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "whole input/output item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active and len(item) <= items, "cyclic or oversized ordinary container")
            active.add(id(item))
            charge(2)
            try:
                if type(item) is dict:
                    result = {}
                    for index, (key, child) in enumerate(item.items()):
                        _need(type(key) is str, "plain string keys required")
                        charge(1 + bool(index))
                        result[visit(key, depth + 1)] = visit(child, depth + 1)
                    return result
                result = []
                for index, child in enumerate(item):
                    if index: charge(1)
                    result.append(visit(child, depth + 1))
                return result
            finally:
                active.remove(id(item))
        if type(item) is bytes and allow_bytes:
            charge(len(item))
        elif type(item) is str:
            text(item)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            charge(len(str(item)))
        elif type(item) is float:
            _need(math.isfinite(item), "finite plain numbers required")
            charge(len(repr(item)))
        else:
            raise ReceiptBoundTrainedSourceError("ordinary JSON containers/primitives required")
        return item
    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise ReceiptBoundTrainedSourceError("stable bounded ordinary input required") from error


def _wire(value, maximum=MAX_REPORT_BYTES):
    checked = _copy(value, maximum)
    raw = json.dumps(checked, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    _need(len(raw) <= maximum, "complete serialized bound exceeded; truncation refused")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _detach(value, maximum=MAX_REPORT_BYTES):
    return json.loads(_wire(value, maximum))


def _fingerprint(value):
    result = hashlib.sha256()
    def visit(item):
        if type(item) is dict:
            result.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item): visit(key); visit(item[key])
        elif type(item) is list:
            result.update(b"l" + str(len(item)).encode() + b":")
            for child in item: visit(child)
        elif type(item) is bytes:
            result.update(b"b" + str(len(item)).encode() + b":" + item)
        else:
            result.update(b"j" + _wire(item, MAX_INPUT_BYTES))
    visit(value)
    return result.hexdigest()


def _read_identity(path, expected, size=None, maximum=4 * 1024 * 1024):
    _need(path.is_absolute() and path.resolve(strict=True) == path
          and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "canonical unaliased artifact/source path required")
    before = path.lstat()
    witness = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size,
                            row.st_mtime_ns, row.st_ctime_ns, row.st_nlink)
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum
          and (size is None or size == before.st_size), "bounded single-link regular artifact/source required")
    count, digest = 0, hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        _need(witness(os.fstat(stream.fileno())) == witness(before), "artifact/source changed before read")
        while True:
            block = stream.read(min(1024 * 1024, before.st_size - count + 1))
            if not block: break
            count += len(block)
            _need(count <= before.st_size, "artifact/source grew during read")
            digest.update(block)
        after = os.fstat(stream.fileno())
    _need(witness(before) == witness(after) == witness(path.lstat()) and count == before.st_size
          and digest.hexdigest() == expected, "artifact/source identity, size or raw hash changed")
    return {"path": str(path), "bytes": count, "sha256": expected}, witness(after)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][2]).is_file():
                _need(candidate.resolve(strict=True) == candidate, "canonical owner tree required")
                root = candidate
                break
        if root is not None: break
    _need(root is not None, "canonical public owners unavailable")
    return root, [_read_identity(_SELF_PATH, _SELF_SHA),
                  *[_read_identity(root / relative, sha) for _, _, relative, sha in _SPECS]]


def _owners():
    root, observed = _sources()
    modules, failure = {}, None
    try:
        for key, name, relative, _ in _SPECS:
            module = importlib.import_module(name)
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                  "canonical public owner origin required")
            modules[key] = module
        return root, observed, modules
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources() == (root, observed), "source changed during lazy imports")
        except BaseException:
            if failure is None: raise
            BaseException.add_note(failure, "A closing receipt-bound lazy-import source check also failed.")


def _closing(loaded):
    root, observed, modules = loaded
    _need(_sources() == (root, observed), "receipt-bound operation sources changed")
    for key, _, relative, _ in _SPECS:
        _need(type(modules[key].__file__) is str and Path(modules[key].__file__).absolute() == root / relative,
              "public owner module origin changed")


def _operation(original, source_resolver, work):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = _fingerprint(snapshot)
    loaded, failure = None, None
    references, source_checks, frozen = [], [], []
    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
              and _fingerprint(snapshot) == token, "original or detached operation inputs changed")
        if loaded is not None: _closing(loaded)
        for reference, witness in references:
            _need(_read_identity(Path(reference["path"]), reference["sha256"], reference["bytes"],
                MAX_RECEIPT_BYTES)[1] == witness, "receipt changed during outer operation")
        for value, raw in frozen:
            _need(_wire(value, MAX_REPORT_BYTES) == raw, "frozen pre-generation inventory changed")
    try:
        loaded = _owners()
        fence()
        result = work(snapshot, loaded, fence, references, source_checks, frozen)
        result = _detach(result, MAX_REPORT_BYTES)
        fence()
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            for check in source_checks: check()
            fence()
        except BaseException:
            if failure is None: raise
            BaseException.add_note(failure, "A closing receipt-bound original/source custody check also failed.")


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate population JSON field")
        result[key] = value
    return result


def _invalid_number(_):
    raise ReceiptBoundTrainedSourceError("population JSON floats/nonfinite numbers unsupported")


def _population(raw, expected):
    _hash(expected, "outer population")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_POPULATION_BYTES
          and hashlib.sha256(raw).hexdigest() == expected, "outer population raw commitment differs")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_invalid_number, parse_constant=_invalid_number)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ReceiptBoundTrainedSourceError("bounded duplicate-free population UTF8 JSON required") from error
    value = _copy(value, MAX_POPULATION_BYTES)
    _need(type(value) is dict and set(value) == {"schema", "partition", "selection_sha256", "rows"}
          and value["schema"] == "legal-relational-batch-population/v1"
          and type(value["partition"]) is str and 0 < len(value["partition"]) <= 128
          and bool(value["partition"].strip()) and type(value["rows"]) is list
          and 1 <= len(value["rows"]) <= MAX_ROWS, "closed complete outer population required")
    _hash(value["selection_sha256"], "outer selection")
    seen = set()
    for row in value["rows"]:
        _need(type(row) is dict and set(row) == {"id", "source_sha256", "context_sha256"},
              "closed outer occurrence required")
        _need(type(row["id"]) is str and bool(row["id"].strip()) and 0 < len(row["id"]) <= 256
              and row["id"] not in seen, "bounded unique occurrence IDs required")
        seen.add(row["id"])
        _hash(row["source_sha256"], "outer source")
        _hash(row["context_sha256"], "outer catalog")
    return value


def _rows(rows, population):
    fields = {"id", "source_raw", "catalog_raw", "expected_source_sha256", "expected_catalog_sha256",
              "source_request", "expected_source_request_sha256", "input_id", "receipt_ref"}
    _need(type(rows) is list and len(rows) == len(population["rows"]), "all ordered outer input rows required")
    references = {}
    for row, occurrence in zip(rows, population["rows"]):
        _need(type(row) is dict and set(row) == fields and row["id"] == occurrence["id"],
              "closed ordered outer row differs from original population")
        for name, maximum, key in (("source", MAX_SOURCE_BYTES, "source_sha256"),
                                   ("catalog", MAX_CATALOG_BYTES, "context_sha256")):
            raw, expected = row[name + "_raw"], row["expected_" + name + "_sha256"]
            _hash(expected, name)
            _need(type(raw) is bytes and 0 < len(raw) <= maximum
                  and hashlib.sha256(raw).hexdigest() == expected == occurrence[key],
                  "nonempty bounded original source/catalog raw commitment differs")
            try: raw.decode("utf-8")
            except UnicodeError as error:
                raise ReceiptBoundTrainedSourceError("strict source/catalog UTF8 required") from error
        _hash(row["expected_source_request_sha256"], "source request")
        request = row["source_request"]
        _need(type(request) is dict and set(request) == {"occurrence_id", "input"}
              and request["occurrence_id"] == row["id"] and type(request["input"]) is dict
              and type(request["input"].get("text")) is str
              and request["input"]["text"].encode("utf-8") == row["source_raw"]
              and request["input"].get("input_id") == row["input_id"],
              "exact occurrence/source-text/receipt-input join required")
        _need(_digest(request, 4 * 1024 * 1024) == row["expected_source_request_sha256"],
              "source request commitment differs")
        reference = row["receipt_ref"]
        _need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
              and type(reference["path"]) is str and 0 < len(reference["path"]) <= 4096
              and type(reference["bytes"]) is int and 0 < reference["bytes"] <= MAX_RECEIPT_BYTES,
              "closed bounded original receipt reference required")
        _hash(reference["sha256"], "receipt")
        old = references.setdefault(reference["path"], reference)
        _need(old == reference, "same receipt path has inconsistent original commitments")
    _need(sum(row["bytes"] for row in references.values()) <= MAX_RECEIPT_TOTAL_BYTES,
          "whole unique receipt-byte bound exceeded")
    return list(references.values())


def _checkpoint(checkpoint, expected, generation):
    _hash(expected, "complete trained checkpoint")
    _need(type(checkpoint) is dict and _digest(checkpoint, MAX_CHECKPOINT_BYTES) == expected,
          "complete trained checkpoint commitment differs")
    inspected = generation.inspect_compact_content_trained_checkpoint_v2(checkpoint,
        expected_checkpoint_sha256=expected)
    _need(_digest(inspected, MAX_CHECKPOINT_BYTES) == expected, "pure inspection changed original checkpoint")
    return {"checkpoint_sha256": expected, "checkpoint_schema": inspected["schema"],
        "checkpoint_profile": inspected["profile"], "current_weights_sha256": inspected["weights_sha256"],
        "initial_checkpoint_sha256": inspected["initial_checkpoint_sha256"],
        "initial_weights_sha256": inspected["initial_weights_sha256"],
        "parent_checkpoint_sha256": inspected["parent_checkpoint_sha256"],
        "training_progress": inspected["progress"], "compact_training_steps": inspected["progress"]["optimizer_steps"],
        "checkpoint_inspection_performed": True, "runtime_verified": False,
        "optimizer_constructed": False, "optimizer_state_restored": False}


def _prepare(data, loaded, fence, references, source_checks, frozen, source_resolver, offered=None):
    modules = loaded[2]
    conditioner, source, trained, generation, codec = (modules[key] for key in
        ("conditioning", "source", "trained_source", "generation", "receipt"))
    _need(callable(source_resolver), "source resolver required")
    _need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= MAX_NEW_TOKENS,
          "max_new_tokens must be a plain integer in 1..12")
    population = _population(data["population_raw"], data["expected_population_sha256"])
    reference_rows = _rows(data["rows"], population)
    checkpoint_preflight = _checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"], generation)
    fence()
    # Public receipt validation retains full producer input order and status
    # commitments, including unselected inputs; no producer/encoder is invoked.
    receipt_inventory, receipts_by_path = [], {}
    for reference in reference_rows:
        _, witness = _read_identity(Path(reference["path"]), reference["sha256"], reference["bytes"], MAX_RECEIPT_BYTES)
        references.append((reference, witness))
        receipt = codec.load_embedding_production_receipt(reference["path"], expected_sha256=reference["sha256"],
            expected_size_bytes=reference["bytes"], resolver=source_resolver)
        source_checks.append(lambda receipt=receipt: receipt.validate_sources(source_resolver))
        payload = _copy(receipt.to_dict(), MAX_RECEIPT_BYTES)
        _need(receipt.native_execution_profile, "native receipt execution profile required")
        receipts_by_path[reference["path"]] = payload
        receipt_inventory.append({"receipt": reference, "payload_sha256": _digest(payload, MAX_RECEIPT_BYTES),
            "input_count": len(payload["inputs"]), "inputs": payload["inputs"],
            "inputs_sha256": _digest(payload["inputs"], MAX_RECEIPT_BYTES), "status_counts": payload["status_counts"],
            "results": [{"index": index, "input_id": item["input_id"], "status": item["status"],
                "tokens_record_sha256": _digest(item["tokens"]), "vector_record_sha256": _digest(item["vector"])}
                for index, item in enumerate(payload["results"])],
            "native_execution_record_present": True, "encoder_executed_by_adapter": False})
        fence()
    conditionings, source_reports, outer_contexts, inner_rows = [], [], [], []
    outer_to_inner, inner_to_outer, inner_occurrences = [], [], []
    # Every outer occurrence is prepared/replayed before the single numerical
    # caller below, including unavailable-vector occurrences.
    for index, (row, occurrence) in enumerate(zip(data["rows"], population["rows"])):
        prepared = conditioner.prepare_compact_source_conditioning_v1(row["source_request"], row["receipt_ref"],
            expected_source_request_sha256=row["expected_source_request_sha256"], input_id=row["input_id"],
            source_resolver=source_resolver)
        prepared_sha = conditioner.compact_source_binding_sha256(prepared)
        # The public conditioner hash operation also rechecks its fixed mutable
        # nine-asset manifest; retain that fence through final serialization.
        source_checks.append(lambda prepared=prepared, prepared_sha=prepared_sha:
            _need(conditioner.compact_source_binding_sha256(prepared) == prepared_sha,
                  "public conditioning report/fixed asset profile changed during outer operation"))
        _need(prepared["occurrence_id"] == occurrence["id"] and prepared["input_id"] == row["input_id"]
              and prepared["input"] == row["source_request"]["input"]
              and prepared["source_span"] == row["source_request"]["input"]["source"]
              and prepared["source_sha256"] == occurrence["source_sha256"]
              and prepared["source_request_sha256"] == row["expected_source_request_sha256"]
              and prepared["receipt"] == row["receipt_ref"], "public conditioning original source join differs")
        payload = receipts_by_path[row["receipt_ref"]["path"]]
        selected = prepared["receipt_input_index"]
        _need(type(selected) is int and 0 <= selected < len(payload["inputs"])
              and prepared["input"] == payload["inputs"][selected]
              and prepared["receipt_input_count"] == len(payload["inputs"])
              and prepared["receipt_status_counts"] == payload["status_counts"]
              and prepared["status"] == payload["results"][selected]["status"],
              "public conditioning differs from complete receipt population")
        conditionings.append({"id": row["id"], "report": prepared, "report_sha256": prepared_sha})
        nominated = source.prepare_source_context_v1(row["source_raw"], row["catalog_raw"],
            expected_source_sha256=row["expected_source_sha256"], expected_catalog_sha256=row["expected_catalog_sha256"])
        report_sha = source.source_context_sha256(nominated)
        nominated = source.validate_source_context_v1(nominated, row["source_raw"], row["catalog_raw"],
            expected_report_sha256=report_sha, expected_source_sha256=row["expected_source_sha256"],
            expected_catalog_sha256=row["expected_catalog_sha256"])
        _need(source.source_context_sha256(nominated) == report_sha
              and nominated["status"] in ("nominated", "ambiguous", "unavailable"), "public source context replay differs")
        source_reports.append({"id": row["id"], "report": nominated, "report_sha256": report_sha})
        context_raw = _wire(nominated["context"], MAX_CATALOG_BYTES) if nominated["status"] == "nominated" else None
        outer_contexts.append({"id": row["id"], "catalog_sha256": row["expected_catalog_sha256"],
            "source_report_sha256": report_sha,
            "compact_context_raw_sha256": hashlib.sha256(context_raw).hexdigest() if context_raw is not None else None,
            "compact_context_sha256": nominated["context_sha256"]})
        if prepared["status"] == "embedded":
            _need(type(prepared["conditioning"]) is list and len(prepared["conditioning"]) == 384
                  and prepared["source_receipt_binding_verified"] is True
                  and prepared["source_bytes_verified"] is True,
                  "embedded public receipt vector/custody missing")
            # Preserve native vector values and their original JSON hash. The
            # existing trained caller's unchanged finite384 bound still applies.
            _need(all(type(number) is float and math.isfinite(number) and abs(number) <= 1e8
                      for number in prepared["conditioning"])
                  and _digest(prepared["conditioning"]) == prepared["conditioning_sha256"],
                  "native conditioning is outside unchanged trained caller profile")
            outer_to_inner.append(len(inner_rows)); inner_to_outer.append(index)
            inner_occurrences.append(occurrence)
            inner_rows.append({"id": row["id"], "source_raw": row["source_raw"], "catalog_raw": row["catalog_raw"],
                "expected_source_sha256": row["expected_source_sha256"],
                "expected_catalog_sha256": row["expected_catalog_sha256"],
                "conditioning": prepared["conditioning"], "expected_conditioning_sha256": prepared["conditioning_sha256"]})
        else:
            _need(prepared["status"] in ("missing_input", "token_limit_exceeded")
                  and prepared["conditioning"] is None and prepared["conditioning_sha256"] is None
                  and prepared["native_vector_bits_sha256"] is None
                  and prepared["source_receipt_binding_verified"] is False,
                  "unavailable receipt conditioning must stay null/unbound")
            outer_to_inner.append(None)
        fence()
    mapping = {"outer_to_inner": outer_to_inner, "inner_to_outer": inner_to_outer}
    inner_population, inner_raw = None, None
    if inner_rows:
        selection = {"schema": "legal-receipt-bound-inner-selection/v1",
            "outer_population_sha256": data["expected_population_sha256"],
            "outer_selection_sha256": population["selection_sha256"], "mapping": mapping,
            "conditioning_reports_sha256": _digest(conditionings), "source_reports_sha256": _digest(source_reports)}
        inner_population = {"schema": population["schema"], "partition": population["partition"],
                            "selection_sha256": _digest(selection), "rows": inner_occurrences}
        inner_raw = _wire(inner_population, MAX_POPULATION_BYTES)
    settings = {"max_new_tokens": data["max_new_tokens"], "max_new_tokens_limit": MAX_NEW_TOKENS,
        "max_selected_rows": MAX_ROWS, "prefix_ids": [1], "prefix_origin": "bos_seed",
        "context_origin": "caller_supplied_unverified", "conditioning_dimension": 384,
        "conditioning_space": "raw_native_gte_small384", "encoder_executed_by_adapter": False}
    pure = {"population": population, "population_sha256": data["expected_population_sha256"],
        "checkpoint_sha256": data["expected_checkpoint_sha256"], "checkpoint_preflight": checkpoint_preflight,
        "receipt_inventory": receipt_inventory, "source_conditionings": conditionings, "source_reports": source_reports,
        "mapping": mapping, "inner_population": inner_population,
        "inner_population_utf8": inner_raw.decode("utf-8") if inner_raw is not None else None,
        "inner_population_sha256": hashlib.sha256(inner_raw).hexdigest() if inner_raw is not None else None,
        "settings": settings}
    pure["pre_generation_sha256"] = _digest(pure)
    frozen.append((pure, _wire(pure, MAX_REPORT_BYTES)))
    # Mutable owner-call rows/vectors are independently sealed as well as the
    # serializable inventory; no callback may modify the committed inner map.
    inner_token = _fingerprint(_copy(inner_rows, MAX_INPUT_BYTES, allow_bytes=True))
    if offered is not None:
        _need(all(key in offered and _wire(offered[key]) == _wire(pure[key]) for key in _PURE_FIELDS),
              "offered report differs from original pre-generation inventory")
    fence()
    inner_report = None
    if inner_rows:
        inner_report = trained.prepare_trained_source_generation_v2(inner_raw, inner_rows, data["checkpoint"],
            expected_population_sha256=pure["inner_population_sha256"],
            expected_checkpoint_sha256=data["expected_checkpoint_sha256"], max_new_tokens=data["max_new_tokens"])
        _need(_fingerprint(_copy(inner_rows, MAX_INPUT_BYTES, allow_bytes=True)) == inner_token,
              "committed inner source/vector rows changed during numerical dispatch")
        _need(inner_report["population"] == inner_population
              and inner_report["population_sha256"] == pure["inner_population_sha256"]
              and inner_report["checkpoint_preflight"] == checkpoint_preflight
              and inner_report["checkpoint_sha256"] == data["expected_checkpoint_sha256"]
              and inner_report["predictions"]["generation"]["encoder_sha256"] is None
              and inner_report["training_executed"] is False
              and inner_report["compact_optimizer_executed"] is False,
              "unchanged trained source report contract differs")
        _need(len(inner_report["slots"]) == len(inner_rows)
              and len(inner_report["source_reports"]) == len(inner_rows), "complete inner result population required")
        for inner_index, outer_index in enumerate(inner_to_outer):
            _need(inner_report["source_reports"][inner_index] == source_reports[outer_index]
                  and inner_report["slots"][inner_index]["id"] == population["rows"][outer_index]["id"]
                  and inner_report["slots"][inner_index]["context_raw_sha256"]
                      == outer_contexts[outer_index]["compact_context_raw_sha256"]
                  and inner_report["context_inventory"]["rows"][inner_index]["content_context_sha256"]
                      == outer_contexts[outer_index]["compact_context_raw_sha256"],
                  "inner nominations/model contexts differ from frozen outer counterparts")
        trained.trained_source_generation_sha256(inner_report)
        fence()
    slots = []
    for index, (occurrence, conditioning, nominated, context) in enumerate(zip(
            population["rows"], conditionings, source_reports, outer_contexts)):
        inner_index = outer_to_inner[index]
        slot = inner_report["slots"][inner_index] if inner_index is not None else None
        slots.append({"index": index, "id": occurrence["id"], "embedding_status": conditioning["report"]["status"],
            "source_context_status": nominated["report"]["status"], "inner_index": inner_index,
            "status": slot["status"] if slot is not None else "unavailable",
            "reason": slot["reason"] if slot is not None else "source_conditioning_" + conditioning["report"]["status"],
            "source_conditioning_sha256": conditioning["report_sha256"], "source_report_sha256": nominated["report_sha256"],
            "compact_context_raw_sha256": context["compact_context_raw_sha256"],
            "compact_context_sha256": context["compact_context_sha256"], "inner_slot": slot})
    counters = ("original_numerical_forward_count", "adapter_replay_numerical_forward_count", "total_numerical_forward_count",
                "original_branching_score_count", "adapter_replay_branching_score_count", "total_branching_score_count")
    counts = {"selected": len(slots), "inner_selected": len(inner_rows),
        **{status: sum(row["embedding_status"] == status for row in slots)
           for status in ("embedded", "missing_input", "token_limit_exceeded")},
        **{"source_context_" + status: sum(row["source_context_status"] == status for row in slots)
           for status in ("nominated", "ambiguous", "unavailable")},
        **{"inner_" + status: sum(row["inner_index"] is not None and row["source_context_status"] == status
                                  for row in slots) for status in ("nominated", "ambiguous", "unavailable")},
        "generated": sum(row["status"] == "generated" for row in slots),
        "abstained": sum(row["status"] == "abstained" for row in slots),
        "conditioning_unavailable": sum(row["inner_index"] is None for row in slots),
        "complete": sum(row["inner_slot"] is not None and row["inner_slot"]["generation"] is not None
                        and row["inner_slot"]["generation"]["status"] == "complete" for row in slots),
        "comparison_eligible": 0, "comparison_credit": 0,
        "producer_receipts": len(receipt_inventory),
        "producer_receipt_inputs": sum(row["input_count"] for row in receipt_inventory),
        **{key: inner_report["counts"][key] if inner_report is not None else 0 for key in counters}}
    _need(counts["original_numerical_forward_count"] <= data["max_new_tokens"] * counts["generated"]
          and counts["total_numerical_forward_count"] == 2 * counts["original_numerical_forward_count"]
          and counts["adapter_replay_numerical_forward_count"] == counts["original_numerical_forward_count"],
          "original and mandatory replay accounting differs")
    result = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_outer_population", **pure,
        "trained_source_report": inner_report, "slots": slots, "counts": counts,
        "model_executed": counts["total_numerical_forward_count"] > 0,
        "encoder_executed_by_adapter": False, "training_executed": False, "compact_optimizer_executed": False,
        "optimizer_constructed": False, "optimizer_state_restored": False,
        "conditioning_producer_verified": False, "authority": dict(_AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
        "owner_pins": [row[0] for row in loaded[1]], "limitations": list(_LIMITATIONS)}
    fence()
    return result


def _inputs(population_raw, rows, checkpoint, expected_population_sha256, expected_checkpoint_sha256, max_new_tokens):
    return dict(population_raw=population_raw, rows=rows, checkpoint=checkpoint,
        expected_population_sha256=expected_population_sha256,
        expected_checkpoint_sha256=expected_checkpoint_sha256, max_new_tokens=max_new_tokens)


def prepare_receipt_bound_trained_source_generation_v1(population_raw, rows, checkpoint, *,
        expected_population_sha256, expected_checkpoint_sha256, max_new_tokens, source_resolver):
    """Freeze all outer receipt/context outcomes, then run the embedded inner map.

    Each nominated embedded row uses the existing caller's original generation
    and mandatory replay. Unavailable receipt rows remain outer null slots. An
    entirely unavailable population uses pure checkpoint inspection only.
    """
    original = _inputs(population_raw, rows, checkpoint, expected_population_sha256,
                       expected_checkpoint_sha256, max_new_tokens)
    return _operation(original, source_resolver, lambda data, loaded, fence, references, checks, frozen:
        _prepare(data, loaded, fence, references, checks, frozen, source_resolver))


def receipt_bound_trained_source_generation_sha256(report):
    """Bounded detached report hash only; no numerical or receipt replay."""
    def work(data, loaded, fence, references, checks, frozen):
        _need(type(data["report"]) is dict and data["report"].get("schema") == SCHEMA
              and data["report"].get("profile") == PROFILE, "versioned receipt-bound report required")
        return {"sha256": _digest(data["report"], MAX_REPORT_BYTES)}
    return _operation({"report": report}, None, work)["sha256"]


def validate_receipt_bound_trained_source_generation_v1(report, population_raw, rows, checkpoint, *,
        expected_report_sha256, expected_population_sha256, expected_checkpoint_sha256,
        max_new_tokens, source_resolver):
    """Pin the original report and regenerate using the same complete originals.

    Pure mapping/inventory or fixed-denial mismatches refuse before numerical
    dispatch. A positive validation performs another complete preparation; it
    does not trust a rehash or claim that replay was a new independent output.
    """
    original = _inputs(population_raw, rows, checkpoint, expected_population_sha256,
                       expected_checkpoint_sha256, max_new_tokens)
    original.update(report=report, expected_report_sha256=expected_report_sha256)
    def work(data, loaded, fence, references, checks, frozen):
        _hash(data["expected_report_sha256"], "original outer report")
        offered = data["report"]
        _need(type(offered) is dict and _digest(offered, MAX_REPORT_BYTES) == data["expected_report_sha256"],
              "original outer report commitment differs")
        authority = offered.get("authority")
        _need(offered.get("schema") == SCHEMA and offered.get("profile") == PROFILE
              and offered.get("status") == "complete_outer_population"
              and type(authority) is dict and set(authority) == set(_AUTHORITY)
              and all(value is False for value in authority.values())
              and type(offered.get("training_mask")) is int and offered["training_mask"] == 0
              and type(offered.get("evaluation_gold_mask")) is int and offered["evaluation_gold_mask"] == 0
              and all(offered.get(key) is False for key in ("encoder_executed_by_adapter", "training_executed",
                  "compact_optimizer_executed", "optimizer_constructed", "optimizer_state_restored",
                  "conditioning_producer_verified")), "fixed outer authority/mask/execution denials differ")
        regenerated = _prepare(data, loaded, fence, references, checks, frozen, source_resolver, offered=offered)
        _need(_wire(regenerated, MAX_REPORT_BYTES) == _wire(offered, MAX_REPORT_BYTES),
              "outer report differs from complete original-bound preparation replay")
        return regenerated
    return _operation(original, source_resolver, work)


__all__ = ["ReceiptBoundTrainedSourceError", "prepare_receipt_bound_trained_source_generation_v1",
           "receipt_bound_trained_source_generation_sha256", "validate_receipt_bound_trained_source_generation_v1"]
