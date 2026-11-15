"""Bounded source nomination followed by the existing compact generation path.

All selected source/catalog dispositions are frozen before numerical dispatch.
The existing generator and its replaying batch adapter own numerical work. This
caller supplies no source encoder, target, reference, optimizer or permission.
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

SCHEMA = "legal-compact-source-generation/v1"
PROFILE = "full-selected-source-nomination-bos-generation-384/v1"
MAX_ROWS, MAX_NEW_TOKENS = 16, 8
MAX_POPULATION_BYTES = 128 * 1024
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MAX_INPUT_BYTES, MAX_REPORT_BYTES = 64 * 1024 * 1024, 64 * 1024 * 1024
MAX_CONTEXTS_BYTES = 4 * 1024 * 1024
MAX_PREDICTIONS_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ("source", "ipfs_datasets_py.logic.autoformal.legal_compact_source_context_v1",
     "logic/autoformal/legal_compact_source_context_v1.py",
     "efaa7e3ccc73d572561569e05d02270625076ac9e5708fea2d62d60f7f294dc2"),
    ("generation", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_generation_v1",
     "logic/formalization/autoencoder/legal_compact_content_generation_v1.py",
     "7509be744d274473e5691f136d48b232b42103b76bd0ddd11b4f065d03350c10"),
    ("tokens", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    (None, None, "logic/autoformal/legal_relational_batch_evaluation_v1.py",
     "663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138"),
    (None, None, "logic/autoformal/legal_relational_content_context_evaluation_v1.py",
     "9de4b5272c609c638354dac33e5ab3448d574663e1e6cd5b7d537b0fa9edf9c8"),
)
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_encoder_authenticated", "conditioning_producer_verified",
    "permitted_inference_context_verified", "context_origin_authenticated", "target_independence_verified",
    "held_out_generation_verified", "legal_roles_verified", "applicability_verified", "governing_use_verified",
    "accepted", "admitted", "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "legal_accuracy_established", "proof_authority", "Lean_admitted",
), False)
_LIMITATIONS = [
    "Every selected occurrence is retained; source/catalog hashes bind caller inputs, not selection completeness outside this supplied population.",
    "All context dispositions are computed and frozen before this caller dispatches generation; caller-supplied catalog provenance, earlier exposure and permission remain unverified.",
    "Conditioning is an unverified caller-supplied 384-vector. No source encoder or binding from source text to that vector is established.",
    "BOS-only generation uses the existing zero-compact-step head. No optimizer update, trained decoder, legal meaning or held-out quality follows.",
    "The existing batch adapter replays each original generation once. Original and adapter-replay numerical forwards are counted separately; replays are not extra independent predictions.",
    "decoder_declared encoder_sha256 stays null; existing batch evaluation therefore gives no source-generation comparison credit.",
    "The eight-new-token cap is a bounded engineering integration profile; short forced grammar prefixes do not demonstrate completed formalization.",
    "References are absent from this API. External callers can evaluate the returned full prediction/context inventories using the unchanged batch owners.",
    "Operational source/input/bound errors propagate without a successful partial report; no exceptions are converted into invented model outcomes.",
    "Source endpoint checks do not authenticate arbitrary loaded bytecode, third-party binaries, a source encoder or an operating-system sandbox.",
]


class SourceGenerationError(ValueError):
    """Whole population, input identity, source or bounded-output refusal."""


def _need(value, message):
    if not value:
        raise SourceGenerationError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
          "unaliased source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4 * 1024 * 1024,
              "bounded single-link regular source required")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size,
                            row.st_mtime_ns, row.st_ctime_ns, row.st_nlink)
    _need(identity(before) == identity(after) == identity(path.lstat())
          and len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected,
          "source identity or raw hash changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, identity(before)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical source root required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "source-generation owners unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA),
                  *[_source(root / relative, sha) for _, _, relative, sha in _SPECS]]


def _owners():
    root, snapshots = _sources()
    modules = {}
    for key, name, relative, _ in _SPECS:
        if key is not None:
            module = importlib.import_module(name)
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                  "canonical public owner origin required")
            modules[key] = module
    _need(_sources() == (root, snapshots), "owner source changed during import")
    return root, snapshots, modules


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate population JSON key")
        result[key] = value
    return result


def _reject_number(_):
    raise SourceGenerationError("population JSON floats/nonfinite values are unsupported")


def _population(raw, expected, generation):
    _hash(expected, "original population")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_POPULATION_BYTES
          and hashlib.sha256(raw).hexdigest() == expected, "original population raw pin differs")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise SourceGenerationError("bounded duplicate-free population UTF8 JSON required") from error
    value = generation._copy(value, MAX_POPULATION_BYTES)
    _need(type(value) is dict and set(value) == {"schema", "partition", "selection_sha256", "rows"}
          and value["schema"] == "legal-relational-batch-population/v1"
          and type(value["partition"]) is str and 0 < len(value["partition"]) <= 128
          and bool(value["partition"].strip()) and type(value["rows"]) is list
          and 1 <= len(value["rows"]) <= MAX_ROWS, "complete bounded existing population required")
    _hash(value["selection_sha256"], "population selection")
    seen = set()
    for row in value["rows"]:
        _need(type(row) is dict and set(row) == {"id", "source_sha256", "context_sha256"},
              "closed existing population row required")
        identity = row["id"]
        _need(type(identity) is str and 0 < len(identity) <= 256 and bool(identity.strip())
              and identity not in seen, "unique nonempty population IDs required")
        seen.add(identity)
        _hash(row["source_sha256"], "population source")
        _hash(row["context_sha256"], "population original catalog context")
    return value


def _rows(rows, population, generation):
    fields = {"id", "source_raw", "catalog_raw", "conditioning", "expected_source_sha256",
              "expected_catalog_sha256", "expected_conditioning_sha256"}
    _need(type(rows) is list and len(rows) == len(population["rows"]),
          "every population occurrence requires one ordered input row")
    for row, occurrence in zip(rows, population["rows"]):
        _need(type(row) is dict and set(row) == fields and row["id"] == occurrence["id"],
              "closed source rows must exactly match the whole population order")
        for label, maximum in (("source", 65536), ("catalog", 524288)):
            expected, raw = row["expected_" + label + "_sha256"], row[label + "_raw"]
            _hash(expected, label)
            population_pin = occurrence["source_sha256" if label == "source" else "context_sha256"]
            _need(type(raw) is bytes and 0 < len(raw) <= maximum
                  and hashlib.sha256(raw).hexdigest() == expected == population_pin,
                  "source/catalog bytes differ from original population binding")
        vector = row["conditioning"]
        _need(type(vector) is list and len(vector) == 384 and all(
            type(number) in (int, float) and math.isfinite(number) and abs(number) <= 1e8 for number in vector),
            "complete bounded plain384 conditioning required for every selected occurrence")
        _hash(row["expected_conditioning_sha256"], "conditioning")
        _need(generation._digest(vector) == row["expected_conditioning_sha256"],
              "conditioning identity differs")


def source_generation_sha256(report):
    """Bounded canonical report identity; this does not replay numerical work."""
    root, snapshots, modules = _owners()
    result = modules["generation"]._digest(report, MAX_REPORT_BYTES)
    _need(_sources() == (root, snapshots), "source changed during report hashing")
    return result


def prepare_source_generation_v1(population_raw, rows, checkpoint, *,
        expected_population_sha256, expected_checkpoint_sha256, max_new_tokens):
    """Nominate every context, then run/replay bounded BOS-only generation.

    Context ambiguity or absence retains an abstained slot and never calls the
    numerical head. No target/reference input or automatic eligibility exists.
    Callers retain admitted resource custody for the whole original plus replay.
    """
    loaded = _owners()
    root, snapshots, modules = loaded
    source, generation, tokens = (modules[key] for key in ("source", "generation", "tokens"))
    original = dict(population_raw=population_raw, rows=rows, checkpoint=checkpoint,
                    expected_population_sha256=expected_population_sha256,
                    expected_checkpoint_sha256=expected_checkpoint_sha256, max_new_tokens=max_new_tokens)
    snapshot = generation._copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    input_token = generation._fingerprint(snapshot)
    frozen = frozen_raw = None

    def fence():
        _need(generation._fingerprint(generation._copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == input_token
              and generation._fingerprint(snapshot) == input_token, "original or detached input changed")
        _need(_sources() == (root, snapshots), "source-generation owner source changed")
        for key, _, relative, _ in _SPECS:
            if key is not None:
                _need(Path(modules[key].__file__).absolute() == root / relative, "owner module origin changed")
        if frozen is not None:
            _need(generation._wire(frozen, MAX_REPORT_BYTES) == frozen_raw,
                  "frozen pre-generation source/context inventory changed")

    failure = None
    try:
        fence()
        _need(type(snapshot["max_new_tokens"]) is int and 1 <= snapshot["max_new_tokens"] <= MAX_NEW_TOKENS,
              "engineering profile requires max_new_tokens in 1..8")
        _hash(snapshot["expected_checkpoint_sha256"], "complete checkpoint")
        _need(type(snapshot["checkpoint"]) is dict
              and generation._digest(snapshot["checkpoint"], MAX_CHECKPOINT_BYTES) == snapshot["expected_checkpoint_sha256"],
              "complete checkpoint identity differs")
        population = _population(snapshot["population_raw"], snapshot["expected_population_sha256"], generation)
        _rows(snapshot["rows"], population, generation)
        codec = tokens.build_compact_content_token_codec_v1()
        codec_sha = tokens.compact_content_token_codec_sha256(codec)
        source_reports, context_rows = [], []
        # No generator/head invocation is permitted before this whole loop ends.
        for row, occurrence in zip(snapshot["rows"], population["rows"]):
            report = source.prepare_source_context_v1(row["source_raw"], row["catalog_raw"],
                expected_source_sha256=row["expected_source_sha256"], expected_catalog_sha256=row["expected_catalog_sha256"])
            report_sha = source.source_context_sha256(report)
            report = source.validate_source_context_v1(report, row["source_raw"], row["catalog_raw"],
                expected_report_sha256=report_sha, expected_source_sha256=row["expected_source_sha256"],
                expected_catalog_sha256=row["expected_catalog_sha256"])
            _need(report["status"] in ("nominated", "ambiguous", "unavailable")
                  and source.source_context_sha256(report) == report_sha, "replayed source disposition differs")
            source_reports.append({"id": row["id"], "report": report, "report_sha256": report_sha})
            available = report["status"] == "nominated"
            context_raw = generation._wire(report["context"], 524288) if available else None
            context_rows.append({**occurrence,
                "status": "available" if available else "unsupported" if report["status"] == "ambiguous" else "unavailable",
                "reason": None if available else "source_context_" + report["status"],
                "content_context_utf8": context_raw.decode("utf-8") if available else None,
                "content_context_sha256": hashlib.sha256(context_raw).hexdigest() if available else None,
                "content_context_origin": "caller_supplied_unverified" if available else None})
            fence()
        contexts = {"schema": "legal-relational-content-context-inventory/v1",
                    "population_sha256": snapshot["expected_population_sha256"], "rows": context_rows}
        # The existing companion's tighter transport bound applies before work.
        contexts_raw = generation._wire(contexts, MAX_CONTEXTS_BYTES)
        reports_sha = generation._digest(source_reports, MAX_REPORT_BYTES)
        contexts_sha = hashlib.sha256(contexts_raw).hexdigest()
        pre_generation = {"population_sha256": snapshot["expected_population_sha256"],
                          "source_reports_sha256": reports_sha, "context_inventory_sha256": contexts_sha}
        frozen = {"source_reports": source_reports, "context_inventory": contexts,
                  "pre_generation": pre_generation}
        frozen_raw = generation._wire(frozen, MAX_REPORT_BYTES)
        settings = {"max_new_tokens": snapshot["max_new_tokens"], "max_selected_rows": MAX_ROWS,
                    "max_new_tokens_limit": MAX_NEW_TOKENS, "prefix_ids": [1], "prefix_origin": "bos_seed",
                    "context_origin": "caller_supplied_unverified", "conditioning_dimension": 384}
        generation_settings = {"max_new_tokens": snapshot["max_new_tokens"], "max_total_ids": 512,
                               "prefix_origin": "bos_seed", "context_origin": "caller_supplied_unverified"}
        generation_declaration = {"kind": "decoder_declared", "population_sha256": snapshot["expected_population_sha256"],
            "latent_dimension": 384, "checkpoint_sha256": snapshot["expected_checkpoint_sha256"],
            "encoder_sha256": None, "settings_sha256": generation._digest(generation_settings),
            "teacher_forcing": False, "target_access": False}
        predictions = {"schema": "legal-relational-content-token-batch-predictions/v1", "codec": codec,
                       "codec_sha256": codec_sha, "generation": generation_declaration, "rows": []}
        slots = []
        for index, (row, occurrence, source_entry, context_row) in enumerate(zip(
                snapshot["rows"], population["rows"], source_reports, context_rows)):
            fence()
            source_status = source_entry["report"]["status"]
            slot = {"index": index, "id": row["id"], "source_context_status": source_status,
                "status": "abstained", "reason": "source_context_" + source_status,
                "source_report_sha256": source_entry["report_sha256"],
                "context_raw_sha256": context_row["content_context_sha256"],
                "generation_sha256": None, "generation": None, "batch_adapter": None,
                "original_numerical_forward_count": 0, "adapter_replay_numerical_forward_count": 0,
                "total_numerical_forward_count": 0}
            if source_status != "nominated":
                predictions["rows"].append({**occurrence, "status": "abstained", "reason": slot["reason"],
                    "teacher_forcing": False, "target_access": False, "generated_ids": None,
                    "generated_ids_sha256": None, "content_context_utf8": None,
                    "content_context_sha256": None, "content_context_origin": None})
            else:
                context_raw = context_row["content_context_utf8"].encode("utf-8")
                options = dict(expected_checkpoint_sha256=snapshot["expected_checkpoint_sha256"],
                    expected_context_sha256=context_row["content_context_sha256"], max_new_tokens=snapshot["max_new_tokens"],
                    prefix_origin="bos_seed", context_origin="caller_supplied_unverified")
                result = generation.generate_compact_content_v1(snapshot["checkpoint"], row["conditioning"], [1], context_raw, **options)
                fence()
                result_sha = generation.compact_content_generation_sha256(result)
                # This existing adapter performs exactly one complete replay.
                # Do not call validate_compact_content_generation_v1 separately.
                adapter = generation.prepare_compact_content_generation_batch_prediction_v1(result,
                    snapshot["checkpoint"], row["conditioning"], [1], context_raw, snapshot["population_raw"],
                    expected_generation_sha256=result_sha, expected_population_sha256=snapshot["expected_population_sha256"],
                    occurrence_id=row["id"], **options)
                fence()
                _need(generation.compact_content_generation_sha256(result) == result_sha,
                      "original generation changed across adapter replay")
                _need(adapter["generation_sha256"] == result_sha and adapter["occurrence_id"] == row["id"]
                      and adapter["population_sha256"] == snapshot["expected_population_sha256"]
                      and adapter["predictions"]["codec"] == codec and adapter["predictions"]["codec_sha256"] == codec_sha
                      and adapter["predictions"]["generation"] == generation_declaration
                      and adapter["predictions"]["rows"] == [adapter["prediction_row"]],
                      "existing batch adapter differs from original whole-population binding")
                count = result["numerical_forward_count"]
                _need(type(count) is int and 0 <= count <= snapshot["max_new_tokens"],
                      "bounded original numerical-forward count required")
                slot.update(status="generated", reason=result["reason"], generation_sha256=result_sha,
                    generation=result, batch_adapter=adapter, original_numerical_forward_count=count,
                    adapter_replay_numerical_forward_count=count, total_numerical_forward_count=2 * count)
                predictions["rows"].append(adapter["prediction_row"])
            slots.append(slot)
        fence()
        counts = {"selected": len(slots), **{status: sum(row["source_context_status"] == status for row in slots)
                  for status in ("nominated", "ambiguous", "unavailable")},
                  **{key: sum(row[key] for row in slots) for key in ("original_numerical_forward_count",
                      "adapter_replay_numerical_forward_count", "total_numerical_forward_count")}}
        result = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_selected_source_generation",
            "population": population, "population_sha256": snapshot["expected_population_sha256"],
            "checkpoint_sha256": snapshot["expected_checkpoint_sha256"], "settings": settings,
            "settings_sha256": generation._digest(settings),
            "generation_settings_sha256": generation_declaration["settings_sha256"],
            "source_reports": source_reports, "source_reports_sha256": reports_sha,
            "context_inventory": contexts, "context_inventory_sha256": contexts_sha,
            "pre_generation_sha256": generation._digest(pre_generation),
            "predictions": predictions,
            "predictions_sha256": generation._digest(predictions, MAX_PREDICTIONS_BYTES),
            "slots": slots, "counts": counts, "model_executed": counts["total_numerical_forward_count"] > 0,
            "training_executed": False, "compact_optimizer_executed": False,
            "owner_pins": [row[0] for row in snapshots], "authority": dict(_AUTHORITY),
            "training_mask": 0, "evaluation_gold_mask": 0, "limitations": list(_LIMITATIONS)}
        raw = generation._wire(result, MAX_REPORT_BYTES)
        fence()
        return json.loads(raw)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing source-generation input/source check also failed.")


__all__ = ["SourceGenerationError", "prepare_source_generation_v1", "source_generation_sha256"]
