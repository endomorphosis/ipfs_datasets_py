"""Bounded source nomination followed by the operation-local prepared consumer.

All selected source/catalog dispositions are frozen before numerical dispatch.
The existing prepared generator and replaying batch adapter own numerical work. This
caller supplies no source encoder, target, reference, optimizer or permission.
The complete trained checkpoint is structurally inspected before nomination,
including a population whose every context abstains. No training is performed.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-compact-prepared-source-generation/v3"
PROFILE = "full-selected-source-nomination-prepared-trained-bos-generation-384/v3"
MAX_ROWS, MAX_NEW_TOKENS = 16, 64
MAX_POPULATION_BYTES = 128 * 1024
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES, MAX_REPORT_BYTES = 192 * 1024 * 1024, 96 * 1024 * 1024
MAX_CONTEXTS_BYTES = 4 * 1024 * 1024
MAX_PREDICTIONS_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ("source", "ipfs_datasets_py.logic.autoformal.legal_compact_source_context_v1",
     "logic/autoformal/legal_compact_source_context_v1.py",
     "efaa7e3ccc73d572561569e05d02270625076ac9e5708fea2d62d60f7f294dc2"),
    ("generation", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_prepared_runtime_v3",
     "logic/formalization/autoencoder/legal_compact_content_prepared_runtime_v3.py",
     "a7d7cedfa482537ac76a9ccf9a49a79f6108e89268b02ca3b355abcfe774ec1e"),
    ("source_contract", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_source_generation_v1",
     "logic/formalization/autoencoder/legal_compact_source_generation_v1.py",
     "73729bba8ae92def8918497d72321f7aebdae4c8dfba86b9512752a0fac22464"),
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
    "BOS-only generation consumes the exact installed trained v2 current weights through the prepared v3 public runtime after pure checkpoint inspection; each nonterminal generation restores at most one private model, while historical progress remains a declaration and this caller performs no optimizer work.",
    "The existing batch adapter replays each original generation once. Original and adapter-replay numerical forwards are counted separately; replays are not extra independent predictions.",
    "decoder_declared encoder_sha256 stays null; existing batch evaluation therefore gives no source-generation comparison credit.",
    "The sixty-four-new-token cap is a separately bounded BOS engineering profile. It permits longer complete-output attempts without establishing that any formula completes or is legally correct; actual branching scores are counted from retained prefix reports.",
    "References are absent from this API. External callers can evaluate the returned full prediction/context inventories using the unchanged batch owners.",
    "Operational source/input/bound errors propagate without a successful partial report; no exceptions are converted into invented model outcomes.",
    "Source endpoint checks do not authenticate arbitrary loaded bytecode, third-party binaries, a source encoder or an operating-system sandbox.",
]


class PreparedSourceGenerationError(ValueError):
    """Whole population, input identity, source or bounded-output refusal."""


def _need(value, message):
    if not value:
        raise PreparedSourceGenerationError(message)


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
    modules, failure = {}, None
    try:
        for key, name, relative, _ in _SPECS:
            if key is not None:
                module = importlib.import_module(name)
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                      "canonical public owner origin required")
                modules[key] = module
        _need(_sources() == (root, snapshots), "owner source changed during import")
        return root, snapshots, modules
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources() == (root, snapshots), "owner source changed during import closeout")
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing trained-source owner import check also failed.")


def prepared_source_generation_sha256(report):
    """Bounded canonical report identity; this does not replay numerical work."""
    root, snapshots, modules = _owners()
    generation = modules["generation"]
    checked = generation._copy(report, MAX_REPORT_BYTES)
    _need(type(checked) is dict and checked.get("schema") == SCHEMA and checked.get("profile") == PROFILE,
          "prepared source generation report schema/profile required")
    result = generation._digest(checked, MAX_REPORT_BYTES)
    _need(_sources() == (root, snapshots), "source changed during report hashing")
    return result


def prepare_prepared_source_generation_v3(population_raw, rows, checkpoint, *,
        expected_population_sha256, expected_checkpoint_sha256, max_new_tokens):
    """Inspect trained state, nominate all contexts, then run/replay BOS generation.

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
              "prepared source profile requires max_new_tokens in 1..64")
        _hash(snapshot["expected_checkpoint_sha256"], "complete checkpoint")
        _need(type(snapshot["checkpoint"]) is dict
              and generation._digest(snapshot["checkpoint"], MAX_CHECKPOINT_BYTES) == snapshot["expected_checkpoint_sha256"],
              "complete checkpoint identity differs")
        # Reuse the original caller's exact closed whole-population and row
        # contracts. Its v1 generator is never invoked by this successor.
        source_contract = modules["source_contract"]
        _need(source_contract.MAX_ROWS == MAX_ROWS and source_contract.MAX_POPULATION_BYTES == MAX_POPULATION_BYTES,
              "original source population bounds differ")
        population = source_contract._population(snapshot["population_raw"], snapshot["expected_population_sha256"], generation)
        source_contract._rows(snapshot["rows"], population, generation)
        # This global public preflight occurs even if all rows later abstain.
        # It validates complete saved v2 state without model/Adam restoration.
        inspected = generation.inspect_compact_content_prepared_checkpoint_v3(snapshot["checkpoint"],
            expected_checkpoint_sha256=snapshot["expected_checkpoint_sha256"])
        _need(generation._digest(inspected, MAX_CHECKPOINT_BYTES) == snapshot["expected_checkpoint_sha256"],
              "public prepared checkpoint inspection changed the committed state")
        fence()
        checkpoint_preflight = {
            "checkpoint_sha256": snapshot["expected_checkpoint_sha256"],
            "checkpoint_schema": inspected["schema"], "checkpoint_profile": inspected["profile"],
            "current_weights_sha256": inspected["weights_sha256"],
            "initial_checkpoint_sha256": inspected["initial_checkpoint_sha256"],
            "initial_weights_sha256": inspected["initial_weights_sha256"],
            "parent_checkpoint_sha256": inspected["parent_checkpoint_sha256"],
            "training_progress": inspected["progress"],
            "compact_training_steps": inspected["progress"]["optimizer_steps"],
            "checkpoint_inspection_performed": True,
            "runtime_verified": False, "optimizer_constructed": False,
            "optimizer_state_restored": False,
        }
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
        pre_generation = {"checkpoint_preflight": checkpoint_preflight,
                          "population_sha256": snapshot["expected_population_sha256"],
                          "source_reports_sha256": reports_sha, "context_inventory_sha256": contexts_sha}
        frozen = {"source_reports": source_reports, "context_inventory": contexts,
                  "pre_generation": pre_generation, "checkpoint_preflight": checkpoint_preflight}
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
                "total_numerical_forward_count": 0,
                "original_branching_score_count": 0, "adapter_replay_branching_score_count": 0,
                "total_branching_score_count": 0}
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
                result = generation.generate_compact_content_prepared_v3(snapshot["checkpoint"], row["conditioning"], [1], context_raw, **options)
                fence()
                result_sha = generation.compact_content_prepared_generation_sha256(result)
                # This existing adapter performs exactly one complete replay.
                # Do not call the public prepared generation validator separately.
                adapter = generation.prepare_compact_content_prepared_batch_prediction_v3(result,
                    snapshot["checkpoint"], row["conditioning"], [1], context_raw, snapshot["population_raw"],
                    expected_generation_sha256=result_sha, expected_population_sha256=snapshot["expected_population_sha256"],
                    occurrence_id=row["id"], **options)
                fence()
                _need(generation.compact_content_prepared_generation_sha256(result) == result_sha,
                      "original generation changed across adapter replay")
                _need(adapter["generation_sha256"] == result_sha and adapter["occurrence_id"] == row["id"]
                      and adapter["population_sha256"] == snapshot["expected_population_sha256"]
                      and adapter["predictions"]["codec"] == codec and adapter["predictions"]["codec_sha256"] == codec_sha
                      and adapter["predictions"]["generation"] == generation_declaration
                      and adapter["predictions"]["rows"] == [adapter["prediction_row"]],
                      "existing batch adapter differs from original whole-population binding")
                _need(result["checkpoint_sha256"] == checkpoint_preflight["checkpoint_sha256"]
                      and result["weights_sha256"] == checkpoint_preflight["current_weights_sha256"]
                      and result["training_progress"] == checkpoint_preflight["training_progress"]
                      and result["compact_training_steps"] == checkpoint_preflight["compact_training_steps"]
                      and all(result[key] == checkpoint_preflight[key] for key in
                          ("initial_checkpoint_sha256", "initial_weights_sha256", "parent_checkpoint_sha256"))
                      and result["optimizer_constructed"] is False
                      and result["optimizer_state_restored"] is False
                      and result["training_executed"] is False and result["compact_optimizer_executed"] is False,
                      "prepared generation lineage or zero-optimizer contract differs")
                count = result["numerical_forward_count"]
                _need(type(count) is int and 0 <= count <= snapshot["max_new_tokens"],
                      "bounded original numerical-forward count required")
                branching = sum(score["numerical_forward_executed"] is True
                    and len(score["prefix_report"]["allowed_token_ids"]) > 1 for score in result["trace"])
                _need(type(branching) is int and 0 <= branching <= count,
                      "branching-score count exceeds original numerical work")
                slot.update(status="generated", reason=result["reason"], generation_sha256=result_sha,
                    generation=result, batch_adapter=adapter, original_numerical_forward_count=count,
                    adapter_replay_numerical_forward_count=count, total_numerical_forward_count=2 * count,
                    original_branching_score_count=branching, adapter_replay_branching_score_count=branching,
                    total_branching_score_count=2 * branching)
                predictions["rows"].append(adapter["prediction_row"])
            slots.append(slot)
        fence()
        counts = {"selected": len(slots), **{status: sum(row["source_context_status"] == status for row in slots)
                  for status in ("nominated", "ambiguous", "unavailable")},
                  **{key: sum(row[key] for row in slots) for key in ("original_numerical_forward_count",
                      "adapter_replay_numerical_forward_count", "total_numerical_forward_count",
                      "original_branching_score_count", "adapter_replay_branching_score_count",
                      "total_branching_score_count")}}
        result = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_selected_source_generation",
            "population": population, "population_sha256": snapshot["expected_population_sha256"],
            "checkpoint_sha256": snapshot["expected_checkpoint_sha256"],
            "checkpoint_preflight": checkpoint_preflight,
            "current_weights_sha256": checkpoint_preflight["current_weights_sha256"],
            "initial_checkpoint_sha256": checkpoint_preflight["initial_checkpoint_sha256"],
            "initial_weights_sha256": checkpoint_preflight["initial_weights_sha256"],
            "parent_checkpoint_sha256": checkpoint_preflight["parent_checkpoint_sha256"],
            "training_progress": checkpoint_preflight["training_progress"],
            "compact_training_steps": checkpoint_preflight["compact_training_steps"],
            "checkpoint_profile": checkpoint_preflight["checkpoint_profile"],
            "checkpoint_inspection_performed": True, "settings": settings,
            "settings_sha256": generation._digest(settings),
            "generation_settings_sha256": generation_declaration["settings_sha256"],
            "source_reports": source_reports, "source_reports_sha256": reports_sha,
            "context_inventory": contexts, "context_inventory_sha256": contexts_sha,
            "pre_generation_sha256": generation._digest(pre_generation),
            "predictions": predictions,
            "predictions_sha256": generation._digest(predictions, MAX_PREDICTIONS_BYTES),
            "slots": slots, "counts": counts, "model_executed": counts["total_numerical_forward_count"] > 0,
            "training_executed": False, "compact_optimizer_executed": False,
            "optimizer_constructed": False, "optimizer_state_restored": False,
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


__all__ = ["PreparedSourceGenerationError", "prepare_prepared_source_generation_v3", "prepared_source_generation_sha256"]
