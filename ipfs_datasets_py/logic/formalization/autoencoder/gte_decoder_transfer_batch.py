"""Recover decoder-preservation batches from the donors' original cached inputs.

All complete files and donor source files are byte-authenticated by the caller.
This contract rechecks all archived training rows before selecting a bounded
prefix batch. Its reference-prefix records are experimental numerical replay
inputs; no token is admitted as qualified knowledge-distillation supervision.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re


SCHEMA = "gte-decoder-transfer-batch/v1"
FLAGS = {"archived_inputs_reused": True, "raw_8d_latents_reconstructed_from_original_cache": True,
    "encoder_inference_executed": False, "teacher_qualified": False, "production_kd_eligible": False,
    "training_executed": False, "distillation_executed": False, "proof_authority": False}
_ROW_FIELDS = {"id", "source_sha256", "input_vector", "input_sha256", "reference_sha256", "token_ids",
    "prefix_ids", "next_token_ids", "reference_token_mask", "kd_token_mask", "reference_prefix_sha256", "row_sha256"}
_HEAD_FIELDS = {"input_dimension", "codec_sha256", "target_vocabulary", "available_row_count",
    "selected_row_count", "rows", "input_origin", "original_training_manifest_sha256", "selected_rows_sha256"}
_INPUT_FIELDS = {"citation", "embedding_model", "embedding_vector", "frame_candidates", "losses", "modal_ir",
    "normalized_text", "parser_trace", "sample_id", "section", "selected_frame", "source", "text", "title"}
_PRIMARY_ROW_FIELDS = {"embedding", "embedding_sha256", "embedding_token_ids_sha256", "group_id", "id",
    "proof_authority", "reference_metadata", "source_semantics_verified", "source_sha256", "source_text",
    "split", "target", "wording_style"}
_INFERENCE_FIELDS = {"admitted", "binding", "checkpoint_sha256", "decoded_count", "decoded_embeddings",
    "decoded_formulas_generated", "formalized", "independent_text_to_logic", "joint_profile", "lake_executed",
    "latent_input_conditioned", "learned_formula_generation", "promotion_performed", "proof_authority",
    "publication_performed", "qualified", "reconstruction_loss", "reconstruction_scope", "roundtrip_ok", "rows",
    "sample_memory_used", "schema", "semantic_correctness_verified", "source_text_is_neural_input", "status",
    "target_access", "teacher_forcing", "training_executed"}
_INFERENCE_ROW_FIELDS = {"admitted", "canonical_ir", "family_syntax_checked", "formal_outputs", "formalized",
    "formula_text", "generated_token_ids", "id", "independent_text_to_logic", "lake_executed", "latent_input_conditioned",
    "latent_sha256", "learned_formula_generation", "minimum_decision_logit_margin", "projection_id",
    "promotion_performed", "proof_authority", "publication_performed", "qualified", "reason", "roundtrip_ok",
    "sample_memory_used", "semantic_correctness_verified", "source_sha256", "source_text_is_neural_input",
    "status", "syntax_scope", "target_access", "teacher_forcing", "temperature", "training_executed"}
_FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_transfer_batch_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load decoder-transfer dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_REUSE = _helper("gte_decoder_reuse")
_TEACHER = _helper("gte_bridge_teacher")
_LEGACY = _REUSE._LEGACY


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("finite canonical JSON required") from None


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha(value, label):
    _require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None,
             "full lowercase " + label + " SHA256 required")


def _text(value, label):
    _require(type(value) is str and 0 < len(value) <= 16384 and value.strip(), "bounded " + label + " required")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("valid UTF8 " + label + " required") from None


def _vector(value, dimension, *, unit=False):
    _require(type(value) is list and len(value) == dimension, "exact cached vector width required")
    for number in value:
        _require(type(number) in (int, float), "finite numeric cached vector required")
        try:
            good = math.isfinite(number) and abs(number) <= 1e8
        except OverflowError:
            good = False
        _require(good, "finite bounded cached vector required")
    if unit:
        _require(abs(math.hypot(*value) - 1.) <= 1e-4, "unit-normalized original 384D cache required")


def _limit(value):
    _require(type(value) is int and 1 <= value <= 64, "max_rows_per_head must be an integer from 1 to 64")


def _rule(value):
    _closed(value, {"rules"}, "canonical reference")
    _require(type(value["rules"]) is list and len(value["rules"]) == 1, "one canonical reference rule required")
    rule = value["rules"][0]
    _closed(rule, set(_FACETS), "reference facets")
    _require(rule["modality"] in ("O", "P", "F"), "reference modality differs")
    for field in _FACETS[1:4]:
        _text(rule[field], "reference " + field)
    for field in _FACETS[4:]:
        values = rule[field]
        _require(type(values) is list and len(values) <= 4
                 and all(type(item) is str and 0 < len(item) <= 4096 for item in values)
                 and values == sorted(set(values)), "sorted bounded reference qualifiers required")
    return rule


def _json_tokens(value):
    if type(value) is dict:
        result = ["{"]
        for index, key in enumerate(sorted(value)):
            if index:
                result.append(",")
            result.extend([_raw(key).decode(), ":", *_json_tokens(value[key])])
        return result + ["}"]
    if type(value) is list:
        result = ["["]
        for index, child in enumerate(value):
            if index:
                result.append(",")
            result.extend(_json_tokens(child))
        return result + ["]"]
    return [_raw(value).decode()]


def _encode(reference, vocabulary, kind):
    rule = _rule(reference)
    if kind == "primary384":
        pieces = ["<bos>", *_json_tokens(reference), "<eos>"]
    else:
        pieces = ["<bos>"]
        for field in _FACETS:
            pieces.append(json.dumps(["field", field], separators=(",", ":"), ensure_ascii=False))
            for atom in rule[field] if field in _FACETS[4:] else [rule[field]]:
                pieces.append(json.dumps(["atom", field, atom], separators=(",", ":"), ensure_ascii=False))
            if field in _FACETS[4:]:
                pieces.append(json.dumps(["end", field], separators=(",", ":"), ensure_ascii=False))
        pieces.append("<eos>")
    _require(all(piece in vocabulary for piece in pieces), "reference token outside exact donor vocabulary")
    positions = {token: index for index, token in enumerate(vocabulary)}
    return [positions[piece] for piece in pieces]


def _decode(tokens, vocabulary, kind):
    if kind == "primary384":
        try:
            reference = json.loads("".join(vocabulary[index] for index in tokens[1:-1]))
        except (ValueError, IndexError):
            raise ValueError("invalid typed JSON reference sequence") from None
    else:
        cursor, rule = 1, {}
        for field in _FACETS:
            _require(cursor < len(tokens) - 1 and vocabulary[tokens[cursor]] == _raw(["field", field]).decode(),
                     "grammar reference field order differs")
            cursor += 1
            atoms = []
            if field in _FACETS[4:]:
                ending = _raw(["end", field]).decode()
                while cursor < len(tokens) - 1 and vocabulary[tokens[cursor]] != ending:
                    atoms.append(vocabulary[tokens[cursor]])
                    cursor += 1
                _require(cursor < len(tokens) - 1, "grammar reference end marker absent")
                cursor += 1
            else:
                _require(cursor < len(tokens) - 1, "grammar reference scalar absent")
                atoms.append(vocabulary[tokens[cursor]])
                cursor += 1
            values = []
            for token in atoms:
                atom = json.loads(token)
                _require(type(atom) is list and len(atom) == 3 and atom[:2] == ["atom", field],
                         "grammar reference typed atom differs")
                values.append(atom[2])
            rule[field] = values if field in _FACETS[4:] else values[0]
        _require(cursor == len(tokens) - 1, "grammar reference has trailing tokens")
        reference = {"rules": [rule]}
    _rule(reference)
    _require(_encode(reference, vocabulary, kind) == tokens, "reference sequence is not canonical")
    return reference


def _originals(initialization, pins, primary, legacy):
    _REUSE.inspect_dual_decoder(initialization, expected_donor_pins=pins)
    _TEACHER._fields(primary, _TEACHER._CHECKPOINT_FIELDS, "original primary checkpoint")
    _require(primary["schema"] == _TEACHER.CHECKPOINT_SCHEMA and primary["domain_id"] == "legal_ir"
             and primary["dimension"] == 384 and primary["architecture"] == _TEACHER.ARCHITECTURE,
             "original primary checkpoint schema differs")
    _TEACHER._config(primary)
    _TEACHER._codec(primary)
    _TEACHER._transform(primary)
    _TEACHER._provenance(primary)
    _require(all(primary[name] is False for name in _TEACHER._FLAGS), "original primary authority claims differ")
    inherited = initialization["primary"]
    _require(primary["weights_sha256"] == digest(primary["model_state"]) == pins["teacher384_weights_sha256"]
             and digest(primary["codec"]) == pins["teacher384_codec_sha256"]
             and primary["codec"] == inherited["codec"] and primary["input_transform"] == inherited["input_transform"],
             "original primary weights, codec or transform differ")
    _require(digest(primary["implementation"]) == inherited["donor"]["implementation_sha256"],
             "original primary implementation declaration differs")
    _require(all(primary["config"][key] == inherited["config"][key] for key in inherited["config"]),
             "original primary architecture configuration differs")
    _require(primary["model_state"] == {name: value for name, value in inherited["model_state"].items()
             if not name.startswith("input_adapter.")}, "original primary tensors differ from learned copies")
    _LEGACY._validate(legacy)
    copied = initialization["legacy8"]
    _require(digest(legacy["model_state"]) == pins["legacy8_weights_sha256"]
             and digest(legacy["codec"]) == pins["legacy8_codec_sha256"]
             and all(legacy[key] == copied[key] for key in ("binding", "config", "codec", "model_state"))
             and legacy["implementation"] == copied["source_implementation"],
             "original legacy8 checkpoint differs from learned copies")


def _primary_training(primary, archive):
    _closed(archive, {"rows", "source_embeddings"}, "original primary training archive")
    rows = archive["rows"]
    _require(type(rows) is list and len(rows) == 180, "complete original 180-row primary training archive required")
    manifest, output, seen = [], [], set()
    for row in rows:
        _closed(row, _PRIMARY_ROW_FIELDS, "original primary training row")
        _text(row["id"], "training row ID")
        _text(row["source_text"], "training source")
        _require(row["id"] not in seen and row["split"] == "train" and row["proof_authority"] is False
                 and row["source_semantics_verified"] is False, "training identities, split or evidence differ")
        seen.add(row["id"])
        _vector(row["embedding"], 384, unit=True)
        _rule(row["target"])
        _encode(row["target"], primary["codec"]["target_vocabulary"], "primary384")
        source_sha = hashlib.sha256(row["source_text"].encode()).hexdigest()
        vector_sha = digest(row["embedding"])
        _require(source_sha == row["source_sha256"] and vector_sha == row["embedding_sha256"],
                 "original primary source or vector SHA differs")
        _sha(row["embedding_token_ids_sha256"], "archived token IDs")
        manifest.append({"id": row["id"], "source_sha256": source_sha,
            "normalized_source_sha256": hashlib.sha256(" ".join(row["source_text"].casefold().split()).encode()).hexdigest(),
            "embedding_sha256": vector_sha, "target_sha256": digest(row["target"])})
        output.append({"id": row["id"], "source_text": row["source_text"],
                       "embedding": row["embedding"], "target": row["target"]})
    _require(manifest == primary["training_manifest"], "complete original primary training manifest differs")
    _require(_raw(archive["source_embeddings"]) == _raw(primary["config"]["embedding_provenance"]),
             "original cached primary model provenance differs")
    return output, digest(manifest)


def _legacy_training(legacy, inputs, inference, pins):
    _require(type(inputs) is list and len(inputs) == 2, "both original legacy8 cached input rows required")
    _closed(inference, _INFERENCE_FIELDS, "original legacy8 inference archive")
    _require(inference["schema"] == "modal-latent-formula-inference/v1" and inference["status"] == "decoded"
             and inference["binding"] == legacy["binding"] and inference["checkpoint_sha256"] == pins["legacy8_checkpoint_sha256"]
             and type(inference["decoded_count"]) is int and inference["decoded_count"] == 2
             and type(inference["rows"]) is list and len(inference["rows"]) == 2,
             "original legacy8 inference checkpoint or core binding differs")
    for name in ("teacher_forcing", "target_access", "training_executed", "qualified", "admitted", "formalized",
                 "roundtrip_ok", "proof_authority", "semantic_correctness_verified", "source_text_is_neural_input", "sample_memory_used"):
        _require(inference[name] is False, "legacy8 inference has unsupported evidence or target access")
    observed = {}
    for row in inference["rows"]:
        _closed(row, _INFERENCE_ROW_FIELDS, "original legacy8 inference row")
        _text(row["id"], "legacy8 inference ID")
        _require(row["id"] not in observed, "duplicate legacy8 inference row")
        observed[row["id"]] = row
    training = []
    for cached in inputs:
        _closed(cached, _INPUT_FIELDS, "original legacy8 cached schema input")
        _text(cached["sample_id"], "legacy8 sample ID")
        _text(cached["text"], "legacy8 original source")
        _require(cached["embedding_model"] == "test:explicit-synthetic-vector-not-semantic"
                 and cached["normalized_text"] == cached["text"] and cached["source"] == "us_code",
                 "original legacy8 synthetic embedding/source profile required")
        _vector(cached["embedding_vector"], 8)
        modal = cached["modal_ir"]
        _require(type(modal) is dict and modal.get("document_id") == cached["sample_id"]
                 and modal.get("normalized_text") == cached["text"] and type(modal.get("formulas")) is list
                 and len(modal["formulas"]) == 1, "original modal input source binding differs")
        formula = modal["formulas"][0]
        _require(type(formula) is dict and type(formula.get("operator")) is dict
                 and type(formula.get("predicate")) is dict, "original modal formula required")
        predicate = formula["predicate"]
        arguments = predicate.get("arguments")
        _require(type(arguments) is list and len(arguments) == 2 and formula.get("conditions") == []
                 and formula.get("exceptions") == [], "original single modal rule facets required")
        reference = {"rules": [{"modality": formula["operator"].get("symbol"), "actor": arguments[0],
            "action": predicate.get("name"), "object": arguments[1], "conditions": [], "exceptions": [], "temporal": []}]}
        _rule(reference)
        latent = []
        vector = cached["embedding_vector"]
        for index in range(0, 8, 2):
            left, right = float(vector[index]), float(vector[index + 1])
            latent.extend([(.02 * left) + (.1 * right), (.02 * right) - (.1 * left)])
        row = observed.get(cached["sample_id"])
        _require(row is not None and row["latent_sha256"] == digest(latent)
                 and row["source_sha256"] == hashlib.sha256(cached["text"].encode()).hexdigest()
                 and row["canonical_ir"] == reference, "original legacy8 raw latent, source or reference differs")
        token_ids = _encode(reference, legacy["codec"]["target_vocabulary"], "legacy8")
        _require(row["generated_token_ids"] == token_ids and row["projection_id"] == "typed_deontic_rule_v1"
                 and row["status"] == "decoded", "original legacy8 reference grammar differs")
        training.append({"id": cached["sample_id"], "source_text": cached["text"], "latent": latent,
                         "embedding": list(vector), "canonical_ir": reference})
    _require(len({row["id"] for row in training}) == 2 and legacy["training_count"] == 2 and legacy["tuning_count"] == 2,
             "original legacy8 training counts differ")
    tuning = [{**row, "id": "tuning-" + row["id"], "source_text": row["source_text"].replace("shall", "must")}
              for row in training]
    _require(digest(training) == legacy["training_manifest_sha256"] and digest(tuning) == legacy["tuning_manifest_sha256"],
             "original legacy8 whole training or tuning manifest differs")
    return training


def _batch_row(row, vector, reference, vocabulary, kind):
    ids = _encode(reference, vocabulary, kind)
    result = {"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
        "input_vector": deepcopy(vector), "input_sha256": digest(vector), "reference_sha256": digest(reference),
        "token_ids": ids, "prefix_ids": ids[:-1], "next_token_ids": ids[1:],
        "reference_token_mask": [True] * (len(ids) - 1), "kd_token_mask": [False] * (len(ids) - 1),
        "reference_prefix_sha256": digest(ids[:-1])}
    result["row_sha256"] = digest(result)
    return result


def prepare_decoder_transfer_batch(initialization, *, expected_donor_pins, primary_checkpoint, primary_archive,
                                   legacy8_checkpoint, legacy8_inputs, legacy8_inference, max_rows_per_head=16):
    """Prepare original donor inputs and reference prefixes without model imports."""
    _limit(max_rows_per_head)
    _originals(initialization, expected_donor_pins, primary_checkpoint, legacy8_checkpoint)
    primary, primary_manifest = _primary_training(primary_checkpoint, primary_archive)
    legacy = _legacy_training(legacy8_checkpoint, legacy8_inputs, legacy8_inference, expected_donor_pins)
    heads = {}
    for kind, rows, width, codec, manifest, origin in (
        ("primary384", primary, 384, primary_checkpoint["codec"], primary_manifest, "original_cached_384d_training_input"),
        ("legacy8", legacy, 8, legacy8_checkpoint["codec"], legacy8_checkpoint["training_manifest_sha256"],
         "reconstructed_original_raw8_training_latent")):
        selected = sorted(rows, key=lambda row: row["id"])[:max_rows_per_head]
        vocabulary = codec["target_vocabulary"]
        batch_rows = [_batch_row(row, row["embedding"] if width == 384 else row["latent"],
            row["target"] if width == 384 else row["canonical_ir"], vocabulary, kind) for row in selected]
        heads[kind] = {"input_dimension": width, "codec_sha256": digest(codec), "target_vocabulary": deepcopy(vocabulary),
            "available_row_count": len(rows), "selected_row_count": len(selected), "rows": batch_rows, "input_origin": origin,
            "original_training_manifest_sha256": manifest, "selected_rows_sha256": digest(batch_rows)}
    result = {"schema": SCHEMA, "initialization_representation_id": initialization["representation_id"],
        "donor_pins": deepcopy(expected_donor_pins), "max_rows_per_head": max_rows_per_head, "heads": heads, **FLAGS}
    result["batch_sha256"] = digest(result)
    inspect_decoder_transfer_batch(result, initialization, expected_donor_pins=expected_donor_pins)
    return result


def inspect_decoder_transfer_batch(batch, initialization, *, expected_donor_pins):
    """Inspect a byte-admitted batch; content hashes are not archive authenticity."""
    _REUSE.inspect_dual_decoder(initialization, expected_donor_pins=expected_donor_pins)
    _closed(batch, {"schema", "initialization_representation_id", "donor_pins", "max_rows_per_head", "heads", "batch_sha256", *FLAGS},
            "decoder transfer batch")
    _limit(batch["max_rows_per_head"])
    _require(batch["schema"] == SCHEMA and batch["donor_pins"] == expected_donor_pins
             and batch["initialization_representation_id"] == initialization["representation_id"],
             "decoder transfer initialization or donor binding differs")
    _require(all(batch[name] is value for name, value in FLAGS.items()), "decoder transfer flags differ")
    _closed(batch["heads"], {"primary384", "legacy8"}, "independent transfer heads")
    counts = {}
    for kind, width, nested, available, origin in (
        ("primary384", 384, initialization["primary"], 180, "original_cached_384d_training_input"),
        ("legacy8", 8, initialization["legacy8"], 2, "reconstructed_original_raw8_training_latent")):
        head = batch["heads"][kind]
        _closed(head, _HEAD_FIELDS, "decoder transfer head")
        _require(type(head["input_dimension"]) is int and head["input_dimension"] == width
                 and head["codec_sha256"] == digest(nested["codec"])
                 and head["target_vocabulary"] == nested["codec"]["target_vocabulary"]
                 and head["input_origin"] == origin, "decoder transfer head codec or input origin differs")
        _sha(head["original_training_manifest_sha256"], "original training manifest")
        _require(type(head["available_row_count"]) is int and head["available_row_count"] == available
                 and type(head["selected_row_count"]) is int
                 and head["selected_row_count"] == min(available, batch["max_rows_per_head"])
                 and type(head["rows"]) is list and len(head["rows"]) == head["selected_row_count"],
                 "decoder transfer head row accounting differs")
        identifiers = []
        for row in head["rows"]:
            _closed(row, _ROW_FIELDS, "decoder transfer row")
            _text(row["id"], "selected training row ID")
            identifiers.append(row["id"])
            _vector(row["input_vector"], width, unit=width == 384)
            for name in ("source_sha256", "input_sha256", "reference_sha256", "reference_prefix_sha256", "row_sha256"):
                _sha(row[name], name)
            _require(row["input_sha256"] == digest(row["input_vector"]), "selected input vector digest differs")
            ids = row["token_ids"]
            _require(type(ids) is list and 3 <= len(ids) <= nested["config"]["max_target_tokens"]
                     and all(type(item) is int and 0 < item < len(head["target_vocabulary"]) for item in ids)
                     and ids[0] == 1 and ids[-1] == 2 and all(item not in (1, 2) for item in ids[1:-1]),
                     "canonical bounded target token IDs required")
            reference = _decode(ids, head["target_vocabulary"], kind)
            _require(type(row["prefix_ids"]) is list and type(row["next_token_ids"]) is list
                     and all(type(item) is int for item in row["prefix_ids"] + row["next_token_ids"])
                     and row["reference_sha256"] == digest(reference) and row["prefix_ids"] == ids[:-1]
                     and row["next_token_ids"] == ids[1:] and row["reference_prefix_sha256"] == digest(ids[:-1]),
                     "selected reference target or prefix binding differs")
            for name, expected in (("reference_token_mask", True), ("kd_token_mask", False)):
                _require(type(row[name]) is list and len(row[name]) == len(ids) - 1
                         and all(item is expected for item in row[name]), "explicit experimental token mask differs")
            _require(row["row_sha256"] == digest({key: value for key, value in row.items() if key != "row_sha256"}),
                     "selected decoder row digest differs")
        _require(identifiers == sorted(set(identifiers)), "selected decoder rows must have sorted unique IDs")
        _require(head["selected_rows_sha256"] == digest(head["rows"]), "selected decoder head digest differs")
        counts[kind] = head["selected_row_count"]
    _require(batch["batch_sha256"] == digest({key: value for key, value in batch.items() if key != "batch_sha256"}),
             "decoder transfer batch digest differs")
    return {"schema": SCHEMA, "status": "prepared_unqualified", "batch_sha256": batch["batch_sha256"],
        "initialization_representation_id": initialization["representation_id"], "selected_rows": counts,
        "archive_authenticity_verified": False, **FLAGS}


__all__ = ["prepare_decoder_transfer_batch", "inspect_decoder_transfer_batch", "digest", "SCHEMA"]
