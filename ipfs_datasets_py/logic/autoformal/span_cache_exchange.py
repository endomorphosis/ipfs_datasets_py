"""Immutable census and deferred supervisor handoffs. Export is never admission."""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Mapping, Sequence
from .span_evidence import DEFAULT_REPOSITORY_ID, SpanEvidenceError
from .supervisor_queue import SCHEMA as REPAIR_SCHEMA, canonical_bytes
from .supervisor_todo import SCHEMA as TODO_SCHEMA

CENSUS_SCHEMA_V2 = "uscode-autoformal-ae-compiler-census/v2"
CENSUS_SCHEMA = "uscode-autoformal-ae-compiler-census/v3"
GOAL_EXPORT_SCHEMA = "uscode-autoformal-supervisor-goal-export/v2"
EXCHANGE_MANIFEST_SCHEMA_V2 = "uscode-autoformal-exchange-manifest/v2"
EXCHANGE_MANIFEST_SCHEMA = "uscode-autoformal-exchange-manifest/v3"
CENSUS_REPO_DIR_V2 = "autoformal/uscode/census"
CENSUS_REPO_DIR = "autoformal/uscode/census-v3"
GOALS_REPO_DIR = "autoformal/uscode/goals"
MANIFEST_REPO_DIR = "autoformal/uscode/exchanges"
_FORBIDDEN_NAMES = {"resume-checkpoint.parquet", "sealed-spans.parquet"}
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ROW_BYTES = 8 * 1024 * 1024
CENSUS_COLUMNS_V2 = (
    "schema_version",
    "record_kind",
    "repository_id",
    "agent_id",
    "source_span_id",
    "legal_id",
    "source_text",
    "source_text_sha256",
    "autoencoder_text",
    "compiler_decompiled",
    "autoencoder_compiled",
    "agrees",
    "reason",
    "compiler_roundtrip",
    "strict_compiler_agreement",
    "consensus",
    "replicated",
    "round_index",
    "selected_families_json",
    "stitch_json",
    "holdout_scores_json",
    "threshold_json",
    "below_threshold_json",
    "cosine_similarity",
    "cross_entropy_loss",
    "reconstruction_loss",
    "export_error",
    "input_json",
    "comparison_json",
    "comparison_provenance_json",
    "comparison_kind",
    "metric_scope",
    "release_id",
    "code_identity",
    "model_identity",
    "census_sha256",
    "admitted",
    "formalized",
    "wrote_compiler",
)
# Existing v2 artifacts remain immutable. New observations expose their outputs
# without requiring consumers to reverse engineer the original input envelope.
_OUTPUT_JSON_COLUMNS = (
    "autoencoder_raw_decoder_json",
    "autoencoder_safety_projected_decoder_json",
    "embedding_representation_json",
    "compiler_rules_json",
    "compiler_components_json",
    "logic_target_observation_json",
    "bridge_names_json",
    "observed_logic_families_json",
    "observed_logic_views_json",
)
CENSUS_COLUMNS = CENSUS_COLUMNS_V2 + (
    "autoencoder_output_kind",
    "autoencoder_output_status",
    "compiler_status",
    "compiler_reason",
    "compilation_complete",
    *_OUTPUT_JSON_COLUMNS,
)
_MANIFEST_CENSUS_SCHEMAS = {
    EXCHANGE_MANIFEST_SCHEMA_V2: (CENSUS_SCHEMA_V2, CENSUS_COLUMNS_V2),
    EXCHANGE_MANIFEST_SCHEMA: (CENSUS_SCHEMA, CENSUS_COLUMNS),
}
GOAL_COLUMNS = (
    "schema_version",
    "record_kind",
    "repository_id",
    "agent_id",
    "source_span_id",
    "legal_id",
    "task_id",
    "packet_sha256",
    "task_sha256",
    "census_sha256",
    "packet_schema",
    "todo_schema",
    "handoff_status",
    "packet_json",
    "task_json",
    "release_id",
    "code_identity",
    "model_identity",
    "admitted",
    "formalized",
    "wrote_compiler",
    "enqueued",
)


def _json(value):
    return canonical_bytes(value).decode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _safe_agent(value):
    return (
        "".join(c if c.isalnum() or c in "-_" else "-" for c in str(value or ""))[:48]
        or "compile-local"
    )


def _refuse(path):
    if Path(path).name in _FORBIDDEN_NAMES:
        raise SpanEvidenceError("exchange cannot replace " + Path(path).name)


def _repo_path(path):
    value = str(path)
    parsed = PurePosixPath(value)
    if (
        not value
        or parsed.is_absolute()
        or ".." in parsed.parts
        or "\\" in value
        or str(parsed) != value
    ):
        raise SpanEvidenceError(
            "exchange repository path is not a canonical relative path"
        )
    _refuse(value)
    return value


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _scores(item):
    capture = (
        item.get("autoencoder_capture")
        or item.get("codec_capture")
        or item.get("capture")
        or {}
    )
    if not isinstance(capture, Mapping):
        capture = {}
    observation = (
        capture.get("codec_observation")
        or capture.get("observation")
        or item.get("codec_observation")
        or {}
    )
    raw = observation.get("raw_losses") if isinstance(observation, Mapping) else None
    if not isinstance(raw, Mapping):
        raw = capture.get("raw_losses")
    if isinstance(raw, Mapping):
        return {
            "cosine_similarity": raw.get(
                "source_decompiled_text_embedding_cosine_similarity",
                raw.get("cosine_similarity"),
            ),
            "cross_entropy_loss": raw.get("cross_entropy_loss"),
            "reconstruction_loss": raw.get(
                "text_reconstruction_loss", raw.get("reconstruction_loss")
            ),
        }
    census = item.get("census") if isinstance(item.get("census"), Mapping) else {}
    return {
        name: item.get(name, census.get(name))
        for name in ("cosine_similarity", "cross_entropy_loss", "reconstruction_loss")
    }


def _autoencoder_text(item):
    repair = item.get("repair") if isinstance(item.get("repair"), Mapping) else {}
    autoencoder = (
        repair.get("autoencoder")
        if isinstance(repair.get("autoencoder"), Mapping)
        else {}
    )
    return str(
        item.get("autoencoder_text")
        or item.get("decoded_text")
        or autoencoder.get("decoded_text")
        or ""
    )


def _explicit_outputs(item, autoencoder_text):
    """Retain measured decoder outputs separately from source-derived targets."""
    observation = item.get("autoencoder_observation")
    observation = observation if isinstance(observation, Mapping) else item
    raw = observation.get("raw_decoder")
    projected = observation.get("safety_projected_decoder")
    representation = observation.get("embedding_representation")
    target = item.get("logic_target_observation", observation.get("logic_target_observation"))
    compiler = item.get("compiler_result")
    compiler = compiler if isinstance(compiler, Mapping) else {}
    rules = compiler.get("rules")
    if rules is None:
        rule = compiler.get("rule")
        rules = [rule] if isinstance(rule, Mapping) else []
    if not isinstance(rules, list) or any(not isinstance(rule, Mapping) for rule in rules):
        raise SpanEvidenceError("compiler rules must be a list of structured rules")
    components = compiler.get("components", [])
    if not isinstance(components, list):
        raise SpanEvidenceError("compiler components must be a list")
    for label, value in (("raw decoder", raw), ("safety projected decoder", projected),
                         ("embedding representation", representation), ("logic target", target)):
        if value is not None and not isinstance(value, Mapping):
            raise SpanEvidenceError(label + " observation must be an object or null")
    kind = "embedding_reconstruction" if raw is not None else "text" if autoencoder_text else "unavailable"
    status = str(observation.get("status") or ("observed" if kind != "unavailable" else "not_observed"))
    target = dict(target) if target is not None else None
    bridge_names = target.get("bridge_names", []) if target is not None else []
    families = target.get("observed_families", []) if target is not None else []
    views = target.get("observed_views", []) if target is not None else []
    for label, values in (("bridge names", bridge_names), ("observed logic families", families),
                          ("observed logic views", views)):
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise SpanEvidenceError(label + " must be a list of strings")
    complete = compiler.get("compilation_complete")
    if complete is not None and not isinstance(complete, bool):
        raise SpanEvidenceError("compiler completeness must be boolean or null")
    return {
        "autoencoder_output_kind": kind,
        "autoencoder_output_status": status,
        "autoencoder_raw_decoder_json": _json(raw),
        "autoencoder_safety_projected_decoder_json": _json(projected),
        "embedding_representation_json": _json(representation),
        "compiler_status": str(compiler.get("status") or compiler.get("compiler_status")
                               or ("rule_observed" if rules else "not_observed")),
        "compiler_reason": str(compiler.get("reason") or compiler.get("error_code")
                               or item.get("compiler_reason") or ""),
        "compilation_complete": complete,
        "compiler_rules_json": _json(rules),
        "compiler_components_json": _json(components),
        "logic_target_observation_json": _json(target),
        "bridge_names_json": _json(bridge_names),
        "observed_logic_families_json": _json(families),
        "observed_logic_views_json": _json(views),
    }


def _observation_evidence(row):
    """Bound goal context while retaining exact, verifiable census retrieval keys.

    Large bridge documents stay in the census. A later supervisor must verify the
    immutable exchange manifest, find this census hash, and read these columns.
    Inline context is capped independently of the original input row size.
    """
    columns = ("autoencoder_output_kind", "autoencoder_output_status", "compiler_status",
               "compiler_reason", "compilation_complete", "compiler_decompiled",
               "autoencoder_text", *_OUTPUT_JSON_COLUMNS)
    fields = {}
    remaining = 32 * 1024
    for name in columns:
        raw = row[name] if name.endswith("_json") else _json(row[name])
        encoded = raw.encode("utf-8")
        field = {"column": name, "sha256": _sha(encoded), "bytes": len(encoded)}
        if len(encoded) <= min(4096, remaining):
            field["inline"] = json.loads(raw)
            remaining -= len(encoded)
        fields[name] = field
    return {
        "schema": "uscode-autoformal-output-evidence/v1",
        "repository_id": row["repository_id"],
        "source_span_id": row["source_span_id"],
        "source_text_sha256": row["source_text_sha256"],
        "census_sha256": row["census_sha256"],
        "input_json_sha256": _sha(row["input_json"].encode("utf-8")),
        "retrieval": {
            "kind": "immutable_exchange_census",
            "manifest_directory": MANIFEST_REPO_DIR,
            "match_column": "census_sha256",
            "match_value": row["census_sha256"],
            "input_column": "input_json",
            "require_manifest_verification": True,
        },
        "outputs": fields,
        "interpretation": {
            "autoencoder_raw_decoder_json": "Measured learned decoder output; vector diagnostics are not symbolic formulas or semantic qualification.",
            "autoencoder_safety_projected_decoder_json": "Postprocessed decoder observation; target-conditioned projection is not independent learned output.",
            "logic_target_observation_json": "Source-derived bridge target, not an autoencoder-generated formal output or proof.",
            "compiler_rules_json": "Observed deterministic compiler rules; compilation and text roundtrip do not grant admission.",
            "admission": "Only the source-locked lake build <Lib> validation path can admit; metrics and this dataset are not admission.",
            "supervisor_work": "Deferred repair context for explicit later import into ipfs_accelerate_py; export executes no task. Preserve the packet acceptance and regression gates.",
        },
        "counts_as_validation": False,
        "admitted": False,
        "formalized": False,
    }


def compiled_rows_from_evidence(rows):
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise SpanEvidenceError("every evidence row must be a mapping")
        result.append(
            {
                **dict(row),
                "census": {
                    **(
                        dict(row.get("census"))
                        if isinstance(row.get("census"), Mapping)
                        else {}
                    ),
                    "train": row.get("train") is True
                    or (
                        isinstance(row.get("census"), Mapping)
                        and row["census"].get("train") is True
                    ),
                    "consensus": str(
                        row.get("consensus")
                        or (row.get("census") or {}).get("consensus")
                        or ""
                    ),
                    "agree": (
                        row.get("census_agree")
                        if "census_agree" in row
                        else (row.get("census") or {}).get("agree")
                    ),
                },
                "text": str(row.get("source_text") or row.get("text") or ""),
                "autoencoder_text": _autoencoder_text(row),
            }
        )
    return result


def _producer_identity():
    from .tree_pin import require_workspace_logic_tree

    require_workspace_logic_tree()
    import inspect
    from . import family_supervision
    from .span_cache import compiler_path_hashes

    root = Path(__file__).resolve().parents[3]
    source = Path(inspect.getfile(family_supervision)).resolve()
    return {
        "schema": "family-projection-observation/v1",
        "compiler_path_hashes": compiler_path_hashes(root),
        "family_supervision_sha256": _sha(source.read_bytes()),
    }


def _strict(item):
    for key in ("strict_compiler_agreement", "agrees"):
        if isinstance(item.get(key), bool):
            return item[key]
    return None


def _partial_compilation(compiler):
    """Distinguish incomplete emitted output from an ordinary full abstention."""
    if not isinstance(compiler, Mapping) or compiler.get("compilation_complete") is not False:
        return False
    if isinstance(compiler.get("rule"), Mapping) or any(
        isinstance(rule, Mapping) for rule in compiler.get("rules") or []
    ):
        return True
    return any(
        isinstance(component, Mapping)
        and (
            component.get("compilation_complete") is True
            or component.get("compiler_status", component.get("status"))
            in {"compiled", "roundtrip_ok", "repeal"}
        )
        for component in compiler.get("components") or []
    )


def _row_hash(row):
    return _sha(canonical_bytes({k: v for k, v in row.items() if k != "census_sha256"}))


def _fingerprint(census_rows, goal_rows):
    return _sha(
        canonical_bytes(
            {
                "census": sorted(census_rows, key=_json),
                "goals": sorted(goal_rows, key=_json),
            }
        )
    )


def exchange_from_compiled(
    rows,
    *,
    agent_id,
    repository_id=DEFAULT_REPOSITORY_ID,
    release_id="ipfs-uscode-5016b86a",
    code_identity="uscode-formal-compiler",
    model_identity="router-not-yet-called",
    round_index=0,
):
    from .family_supervision import census_autoencoder_span, supervisor_repair_goals
    from .supervisor_queue import approved_edit_scope, RepairQueueError

    if not all(
        isinstance(v, str) and v.strip()
        for v in (repository_id, release_id, code_identity, model_identity)
    ):
        raise SpanEvidenceError(
            "repository, release, code and model identities are required"
        )
    census_rows, goal_rows = [], []
    producer = _producer_identity()
    input_bytes = 0
    for item in rows:
        if not isinstance(item, Mapping):
            raise SpanEvidenceError("every census input must be a mapping")
        original_bytes = canonical_bytes(dict(item))
        input_bytes += len(original_bytes)
        original = json.loads(original_bytes)
        if len(original_bytes) > _MAX_ROW_BYTES or input_bytes > _MAX_BYTES:
            raise SpanEvidenceError("census input exceeds row byte limit")
        text, span_id = (
            item.get("text") or item.get("source_text") or "",
            item.get("source_span_id") or "",
        )
        if not isinstance(text, str) or not isinstance(span_id, str):
            raise SpanEvidenceError("source text and span identity must be strings")
        if not text.strip() or not span_id.strip():
            raise SpanEvidenceError(
                "every census input needs full source text and span identity"
            )
        ae_text, scores = _autoencoder_text(item), _scores(item)
        supplied = item.get("comparison")
        compared = (
            dict(supplied)
            if isinstance(supplied, Mapping)
            else census_autoencoder_span(
                text, span_id, ae_text, scores, round_index=round_index
            )
        )
        original_comparison = json.loads(canonical_bytes(compared))
        compared.update(
            legal_id=str(item.get("legal_id") or ""),
            text=text,
            source_span_id=span_id,
            id=span_id,
            skipped=False,
        )
        capture = dict(compared.get("capture") or {})
        original_train = (
            isinstance(item.get("census"), Mapping)
            and item["census"].get("train") is True
        )
        capture["original_training_requested"] = original_train
        strict = _strict(item)
        strict_reason = str(item.get("reason") or item.get("compiler_reason") or "")
        compiler_result = item.get("compiler_result")
        if not strict_reason and isinstance(compiler_result, Mapping):
            strict_reason = str(
                compiler_result.get("reason") or compiler_result.get("error_code") or ""
            )
        partial_compilation = _partial_compilation(compiler_result)
        missing_autoencoder_evidence = not ae_text or any(value is None for value in scores.values())
        if partial_compilation:
            # A historical per-component roundtrip can be true while another
            # component abstains. Retain that original observation and route the
            # incomplete source conversion to the existing full repair scope.
            compared.update(agrees=False, reason="strict_roundtrip_failed")
            capture["compiler_repair_trigger"] = "incomplete_component_compilation"
            capture["compiler_compilation_complete"] = False
        elif strict is False:
            reason = strict_reason or "strict_roundtrip_failed"
            try:
                approved_edit_scope(reason)
            except RepairQueueError:
                reason = "compiler_abstain"
            compared.update(agrees=False, reason=reason)
        elif missing_autoencoder_evidence:
            compared.update(agrees=False, reason="inference_still_failing")
        provenance = (
            {
                "kind": "retained_comparison",
                "binding": original.get("comparison_provenance", {}),
            }
            if isinstance(supplied, Mapping)
            else {"kind": "current_family_projection", **producer}
        )
        row = {
            "schema_version": CENSUS_SCHEMA,
            "record_kind": "span",
            "repository_id": repository_id,
            "agent_id": _safe_agent(agent_id),
            "source_span_id": span_id,
            "legal_id": str(item.get("legal_id") or ""),
            "source_text": text,
            "source_text_sha256": _sha(text.encode()),
            "autoencoder_text": ae_text,
            "compiler_decompiled": str(
                item.get("decompiled")
                or item.get("decompiled_text")
                or (
                    compiler_result.get("decompiled")
                    if isinstance(compiler_result, Mapping)
                    else ""
                )
                or ""
            ),
            "autoencoder_compiled": str(item.get("autoencoder_compiled") or ""),
            "agrees": False if compared.get("agrees") is not True else None,
            "reason": str(compared.get("reason") or ""),
            "compiler_roundtrip": strict,
            "strict_compiler_agreement": strict,
            "consensus": (
                str((item.get("census") or {}).get("consensus") or "")
                if isinstance(item.get("census"), Mapping)
                else ""
            ),
            "replicated": capture.get("replicated") is True,
            "round_index": int(round_index),
            "selected_families_json": _json(capture.get("selected_families") or []),
            "stitch_json": _json(capture.get("stitch") or {}),
            "holdout_scores_json": _json(scores),
            "threshold_json": _json(capture.get("threshold") or {}),
            "below_threshold_json": _json(capture.get("below_threshold") or []),
            "cosine_similarity": _number(scores["cosine_similarity"]),
            "cross_entropy_loss": _number(scores["cross_entropy_loss"]),
            "reconstruction_loss": _number(scores["reconstruction_loss"]),
            "export_error": "",
            "input_json": _json(original),
            "comparison_json": _json(original_comparison),
            "comparison_provenance_json": _json(provenance),
            "comparison_kind": "family_projection_not_semantic_equivalence",
            "metric_scope": str(
                item.get("metric_scope") or "observational_not_heldout"
            ),
            "release_id": str(item.get("release_id") or release_id),
            "code_identity": str(item.get("code_identity") or code_identity),
            "model_identity": str(item.get("model_identity") or model_identity),
            "admitted": False,
            "formalized": False,
            "wrote_compiler": False,
            **_explicit_outputs(item, ae_text),
        }
        row["census_sha256"] = _row_hash(row)
        census_rows.append(row)
        compared["capture"] = {
            **capture,
            "census_sha256": row["census_sha256"],
            "source_text_sha256": row["source_text_sha256"],
            "observed_strict_reason": strict_reason,
            "autoencoder_output_sha256": _sha(ae_text.encode()),
            "comparison_is_not_validation": True,
            "observation_evidence": _observation_evidence(row),
        }
        needs_goal = (
            compared.get("agrees") is not True
            or bool(capture.get("below_threshold"))
            or original_train
        )
        if not needs_goal:
            continue
        goals = supervisor_repair_goals(
            [compared],
            release_id=row["release_id"],
            code_identity=row["code_identity"],
            model_identity=row["model_identity"],
        )
        if (original_train or (partial_compilation and missing_autoencoder_evidence)) and not goals.get("training_goals"):
            deferred = supervisor_repair_goals(
                [{**compared, "reason": "inference_still_failing", "agrees": False}],
                release_id=row["release_id"],
                code_identity=row["code_identity"],
                model_identity=row["model_identity"],
            )
            goals["training_goals"] = list(deferred.get("training_goals") or [])
        produced = []
        for packed in goals.get("repair_packets") or []:
            produced.append(
                ("repair_packet", dict(packed["packet"]), dict(packed["task"]))
            )
        for packet in goals.get("training_goals") or []:
            task = {
                **dict(packet),
                "code_identity": row["code_identity"],
                "model_identity": row["model_identity"],
                "census_sha256": row["census_sha256"],
            }
            identity = _sha(
                canonical_bytes({k: v for k, v in task.items() if k != "task_id"})
            )
            task["task_id"] = "AFTD-TRAIN-" + identity
            produced.append(("training_goal", task, dict(task)))
        if not produced:
            raise SpanEvidenceError("census failure produced no portable goal")
        for kind, packet, task in produced:
            packet_raw, task_raw = canonical_bytes(packet), canonical_bytes(task)
            goal_rows.append(
                {
                    "schema_version": GOAL_EXPORT_SCHEMA,
                    "record_kind": kind,
                    "repository_id": repository_id,
                    "agent_id": _safe_agent(agent_id),
                    "source_span_id": span_id,
                    "legal_id": row["legal_id"],
                    "task_id": task["task_id"],
                    "packet_sha256": _sha(packet_raw),
                    "task_sha256": _sha(task_raw),
                    "census_sha256": row["census_sha256"],
                    "packet_schema": str(packet.get("schema") or ""),
                    "todo_schema": str(task.get("schema") or ""),
                    "handoff_status": "dataset",
                    "packet_json": packet_raw.decode(),
                    "task_json": task_raw.decode(),
                    "release_id": row["release_id"],
                    "code_identity": row["code_identity"],
                    "model_identity": row["model_identity"],
                    "admitted": False,
                    "formalized": False,
                    "wrote_compiler": False,
                    "enqueued": False,
                }
            )
    if producer != _producer_identity():
        raise SpanEvidenceError("comparison producer changed during census")
    return {
        "census_rows": census_rows,
        "goal_rows": goal_rows,
        "admitted": False,
        "formalized": False,
        "enqueued": False,
        "wrote_compiler": False,
    }


def _schema(columns):
    import pyarrow as pa

    floats = {"cosine_similarity", "cross_entropy_loss", "reconstruction_loss"}
    bools = {
        "admitted",
        "agrees",
        "compiler_roundtrip",
        "compilation_complete",
        "strict_compiler_agreement",
        "enqueued",
        "formalized",
        "replicated",
        "wrote_compiler",
    }
    return pa.schema(
        [
            pa.field(
                name,
                (
                    pa.float64()
                    if name in floats
                    else (
                        pa.bool_()
                        if name in bools
                        else pa.int32() if name == "round_index" else pa.string()
                    )
                ),
            )
            for name in columns
        ]
    )


def _immutable_write(path, payload):
    path = Path(path)
    _refuse(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.read_bytes() != payload:
            raise SpanEvidenceError(
                "immutable exchange path has conflicting bytes: " + str(path)
            )
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".exchange-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                raise SpanEvidenceError("concurrent exchange path conflict")
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def _write_table(rows, path, columns):
    import pyarrow as pa
    import pyarrow.parquet as pq

    for row in rows:
        if set(row) != set(columns):
            raise SpanEvidenceError("exchange row schema differs")
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(list(rows), schema=_schema(columns)), sink)
    raw = sink.getvalue().to_pybytes()
    if len(raw) > _MAX_BYTES:
        raise SpanEvidenceError("exchange parquet exceeds byte limit")
    _immutable_write(path, raw)
    return {
        "bytes": len(raw),
        "path": str(Path(path).resolve()),
        "filename": Path(path).name,
        "row_count": len(rows),
        "sha256": _sha(raw),
    }


def _flags(row):
    for key in ("admitted", "formalized", "wrote_compiler"):
        if row.get(key) is not False:
            raise SpanEvidenceError("exchange claims admission or a compiler write")
    if "enqueued" in row and row["enqueued"] is not False:
        raise SpanEvidenceError("exchange claims a live enqueue")


def _object(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise SpanEvidenceError("exchange JSON is invalid") from exc
    if not isinstance(value, dict) or _json(value) != raw:
        raise SpanEvidenceError("exchange JSON must be a canonical object")
    return value


def _validate_goal_rows(rows, census=None):
    from .supervisor_dispatch import TRAINING_SCHEMA
    from .supervisor_queue import EDIT_SCOPES, REGRESSION_TESTS, approved_edit_scope

    repair_packets, training_goals, identities = [], [], {}
    for row in rows:
        _flags(row)
        if (
            row.get("schema_version") != GOAL_EXPORT_SCHEMA
            or row.get("handoff_status") != "dataset"
        ):
            raise SpanEvidenceError("unsupported goal export schema or handoff state")
        packet, task = _object(row["packet_json"]), _object(row["task_json"])
        digest, task_digest = _sha(canonical_bytes(packet)), _sha(canonical_bytes(task))
        if digest != row.get("packet_sha256") or task_digest != row.get("task_sha256"):
            raise SpanEvidenceError("goal packet or task digest mismatch")
        if (
            row.get("task_id") != task.get("task_id")
            or task.get("schema") != row.get("todo_schema")
            or packet.get("schema") != row.get("packet_schema")
        ):
            raise SpanEvidenceError("goal task identity or schema differs")
        identity = str(row["task_id"])
        if identity in identities and identities[identity] != (digest, task_digest):
            raise SpanEvidenceError("goal task identity has conflicting context")
        identities[identity] = (digest, task_digest)
        if (
            task.get("source_span_id") != row.get("source_span_id")
            or not str(task.get("acceptance") or "").strip()
        ):
            raise SpanEvidenceError("goal source binding or acceptance is missing")
        for key in ("admitted", "formalized", "wrote_compiler", "enqueued"):
            if key in task and task[key] is not False:
                raise SpanEvidenceError("task claims execution or admission")
        if row["record_kind"] == "repair_packet":
            if (
                packet.get("schema") != REPAIR_SCHEMA
                or task.get("schema") != TODO_SCHEMA
            ):
                raise SpanEvidenceError("repair packet schema differs")
            if (
                packet.get("admitted") is not False
                or packet.get("formalized") is not False
            ):
                raise SpanEvidenceError("repair packet claims admission")
            source = packet.get("row") or {}
            if task["task_id"] != "AFTD-" + digest[:20]:
                raise SpanEvidenceError("repair task identity is not packet bound")
            if task.get("source_text") != source.get("text") or task.get(
                "source_span_id"
            ) != source.get("source_span_id"):
                raise SpanEvidenceError("repair task source differs from packet")
            scope = approved_edit_scope(str(source.get("reason") or ""))
            if packet.get("allowed_edit_paths") != list(
                EDIT_SCOPES[scope]
            ) or packet.get("regression_tests") != list(REGRESSION_TESTS):
                raise SpanEvidenceError(
                    "repair packet changes approved scope or regression gates"
                )
            if packet.get("preserve") != task.get("preserve") or packet.get(
                "replace"
            ) != task.get("replace"):
                raise SpanEvidenceError("repair task preserve/replace context differs")
            if any(
                packet.get(k) != row.get(k)
                for k in ("release_id", "code_identity", "model_identity")
            ):
                raise SpanEvidenceError("repair packet provenance differs")
            capture = source.get("capture") or {}
            repair_packets.append(
                {
                    "packet": packet,
                    "task": task,
                    "sha256": digest,
                    "task_sha256": task_digest,
                    "census_sha256": row["census_sha256"],
                }
            )
        elif row["record_kind"] == "training_goal":
            if (
                packet != task
                or packet.get("schema") != TRAINING_SCHEMA
                or packet.get("work_kind") != "autoencoder_training"
            ):
                raise SpanEvidenceError("training packet and task differ")
            _flags(packet)
            expected = "AFTD-TRAIN-" + _sha(
                canonical_bytes({k: v for k, v in task.items() if k != "task_id"})
            )
            if task["task_id"] != expected:
                raise SpanEvidenceError(
                    "training task identity differs from its exact context"
                )
            source = {
                "text": task.get("source_text"),
                "source_span_id": task.get("source_span_id"),
            }
            capture = task.get("capture") or {}
            if any(
                task.get(k) != row.get(k)
                for k in ("release_id", "code_identity", "model_identity")
            ):
                raise SpanEvidenceError("training provenance differs")
            training_goals.append(packet)
        else:
            raise SpanEvidenceError("unknown portable goal kind")
        if capture.get("census_sha256") != row.get("census_sha256"):
            raise SpanEvidenceError(
                "goal is not bound to its complete census observation"
            )
        if census is not None:
            evidence = census.get(row.get("census_sha256"))
            if evidence is None:
                raise SpanEvidenceError("goal references a missing census row")
            if (
                source.get("text") != evidence["source_text"]
                or source.get("source_span_id") != evidence["source_span_id"]
            ):
                raise SpanEvidenceError("goal source differs from census")
            if any(
                row.get(k) != evidence.get(k)
                for k in (
                    "repository_id",
                    "legal_id",
                    "release_id",
                    "code_identity",
                    "model_identity",
                )
            ):
                raise SpanEvidenceError("goal provenance differs from census")
            if evidence["schema_version"] == CENSUS_SCHEMA and capture.get(
                "observation_evidence"
            ) != _observation_evidence(evidence):
                raise SpanEvidenceError("goal output context differs from census")
    return {
        "repair_packets": repair_packets,
        "training_goals": training_goals,
        "admitted": False,
        "formalized": False,
        "enqueued": False,
        "wrote_compiler": False,
    }


def _positive_bound(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SpanEvidenceError(name + " must be a positive integer")
    return value


def _read_regular_snapshot(path, *, max_bytes):
    """Read a bounded regular file once; verification and decoding use these bytes."""
    import stat

    source = Path(path)
    _refuse(source)
    _positive_bound(max_bytes, "max_bytes")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if source.is_symlink():
        raise SpanEvidenceError("exchange artifact must not be a symlink")
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise SpanEvidenceError("exchange artifact cannot be opened safely") from exc
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise SpanEvidenceError("exchange artifact is not a bounded regular file")
        raw = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    stable = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if (
        len(raw) > max_bytes
        or len(raw) != before.st_size
        or stable(before) != stable(after)
    ):
        raise SpanEvidenceError(
            "exchange artifact changed while reading or exceeds its bound"
        )
    return raw


def _bounded_parquet_rows(raw, columns, *, max_rows, max_decoded_bytes):
    """Validate the footer, then decode bounded batches from the verified snapshot.

    Dictionary/RLE compression can make the footer's uncompressed size far
    smaller than the expanded Arrow table. Both the footer estimate and actual
    decoded batches are bounded; read_table is deliberately not used.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    _positive_bound(max_rows, "max_rows")
    _positive_bound(max_decoded_bytes, "max_decoded_bytes")
    try:
        parquet = pq.ParquetFile(
            pa.BufferReader(raw),
            thrift_string_size_limit=min(_MAX_BYTES, max_decoded_bytes),
            thrift_container_size_limit=1_000_000,
            pre_buffer=False,
        )
        metadata = parquet.metadata
        if metadata.num_rows > max_rows:
            raise SpanEvidenceError("exchange parquet row count exceeds bound")
        if parquet.schema_arrow != _schema(columns):
            raise SpanEvidenceError("exchange parquet schema differs")
        uncompressed = 0
        for index in range(metadata.num_row_groups):
            group = metadata.row_group(index)
            for column in range(group.num_columns):
                size = group.column(column).total_uncompressed_size
                if size < 0:
                    raise SpanEvidenceError(
                        "parquet footer has an invalid decoded size"
                    )
                uncompressed += size
        if uncompressed > max_decoded_bytes:
            raise SpanEvidenceError("parquet footer exceeds decoded byte bound")
        rows, decoded = [], 0
        for batch in parquet.iter_batches(batch_size=1, use_threads=False):
            decoded += batch.nbytes
            if decoded > max_decoded_bytes or len(rows) + batch.num_rows > max_rows:
                raise SpanEvidenceError(
                    "parquet expansion exceeds decoded byte or row bound"
                )
            rows.extend(batch.to_pylist())
        if len(rows) != metadata.num_rows:
            raise SpanEvidenceError("parquet decoded row count differs from footer")
        return rows, decoded
    except SpanEvidenceError:
        raise
    except (pa.ArrowException, OSError, ValueError) as exc:
        raise SpanEvidenceError("exchange parquet cannot be decoded safely") from exc


def load_goal_export(
    path, *, max_rows=10000, max_bytes=_MAX_BYTES, max_decoded_bytes=None
):
    """Validate a goal-only export; complete census binding requires the bundle loader."""
    _positive_bound(max_bytes, "max_bytes")
    decoded_bound = max_bytes if max_decoded_bytes is None else max_decoded_bytes
    raw = _read_regular_snapshot(path, max_bytes=max_bytes)
    rows, decoded = _bounded_parquet_rows(
        raw, GOAL_COLUMNS, max_rows=max_rows, max_decoded_bytes=decoded_bound
    )
    return {**_validate_goal_rows(rows), "goal_rows": rows, "decoded_bytes": decoded}


def _manifest_file(manifest_path, manifest, desc):
    if not isinstance(desc, Mapping):
        raise SpanEvidenceError("manifest artifact descriptor must be an object")
    filename = str(desc.get("filename") or "")
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise SpanEvidenceError("manifest filename is unsafe")
    _repo_path(filename)
    _refuse(filename)
    remote = _repo_path(desc.get("path_in_repo") or "")
    candidate = manifest_path.parent / filename
    if not candidate.exists():
        manifest_remote = PurePosixPath(_repo_path(manifest["path_in_repo"]))
        root = manifest_path
        for unused in manifest_remote.parts:
            root = root.parent
        if (root / str(manifest_remote)).resolve() != manifest_path.resolve():
            raise SpanEvidenceError("downloaded manifest layout differs")
        candidate = root / remote
    if candidate.is_symlink() or not candidate.is_file():
        raise SpanEvidenceError("manifest artifact is absent or symlinked")
    return candidate.resolve()


def load_exchange_bundle(
    manifest_path, *, max_rows=10000, max_bytes=_MAX_BYTES, max_decoded_bytes=None
):
    _positive_bound(max_rows, "max_rows")
    _positive_bound(max_bytes, "max_bytes")
    decoded_bound = max_bytes if max_decoded_bytes is None else max_decoded_bytes
    _positive_bound(decoded_bound, "max_decoded_bytes")
    path = Path(manifest_path)
    manifest_raw = _read_regular_snapshot(path, max_bytes=min(max_bytes, 1024 * 1024))
    try:
        manifest = _object(manifest_raw.decode("utf-8"))
    except UnicodeError as exc:
        raise SpanEvidenceError("manifest is not UTF-8") from exc
    census_version = _MANIFEST_CENSUS_SCHEMAS.get(manifest.get("schema"))
    if census_version is None:
        raise SpanEvidenceError("unsupported exchange manifest")
    census_schema, census_columns = census_version
    _flags(manifest)
    _repo_path(manifest.get("path_in_repo") or "")
    tables, paths, used, decoded = {}, {}, len(manifest_raw), 0
    for kind, columns in (("census", census_columns), ("goals", GOAL_COLUMNS)):
        descriptor = manifest.get(kind)
        if not isinstance(descriptor, Mapping):
            raise SpanEvidenceError("manifest is missing an artifact descriptor")
        for field in ("bytes", "row_count"):
            value = descriptor.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SpanEvidenceError(
                    "manifest artifact counts must be nonnegative integers"
                )
        if descriptor["row_count"] > max_rows or used + descriptor["bytes"] > max_bytes:
            raise SpanEvidenceError("manifest row or byte count exceeds bound")
        local = _manifest_file(path, manifest, descriptor)
        raw = _read_regular_snapshot(local, max_bytes=max(1, max_bytes - used))
        used += len(raw)
        if len(raw) != descriptor["bytes"]:
            raise SpanEvidenceError("manifest byte count or bounded size differs")
        if _sha(raw) != descriptor.get("sha256"):
            raise SpanEvidenceError("manifest artifact digest differs")
        if decoded >= decoded_bound:
            raise SpanEvidenceError("bundle exceeds total decoded byte bound")
        rows, expanded = _bounded_parquet_rows(
            raw, columns, max_rows=max_rows, max_decoded_bytes=decoded_bound - decoded
        )
        if len(rows) != descriptor["row_count"]:
            raise SpanEvidenceError("manifest row count differs")
        tables[kind] = rows
        decoded += expanded
        paths[kind] = str(local)
    census = {}
    for row in tables["census"]:
        _flags(row)
        if row["schema_version"] != census_schema or row["record_kind"] != "span":
            raise SpanEvidenceError("unsupported census row")
        if (
            row["repository_id"] != manifest["repository_id"]
            or _row_hash(row) != row["census_sha256"]
        ):
            raise SpanEvidenceError("census identity differs")
        if not isinstance(row["source_text"], str):
            raise SpanEvidenceError("census source text must be a string")
        if _sha(row["source_text"].encode()) != row["source_text_sha256"]:
            raise SpanEvidenceError("census source digest differs")
        for key in ("input_json", "comparison_json", "comparison_provenance_json"):
            if not isinstance(row[key], str) or len(row[key].encode()) > _MAX_ROW_BYTES:
                raise SpanEvidenceError(
                    "census JSON evidence exceeds its row byte bound"
                )
            _object(row[key])
        if census_schema == CENSUS_SCHEMA:
            original = _object(row["input_json"])
            expected_outputs = _explicit_outputs(original, _autoencoder_text(original))
            if any(row[key] != value for key, value in expected_outputs.items()):
                raise SpanEvidenceError("explicit output columns differ from original observation")
        census[row["census_sha256"]] = row
    verified = _validate_goal_rows(tables["goals"], census)
    fingerprint = _fingerprint(tables["census"], tables["goals"])
    if fingerprint != manifest.get("fingerprint"):
        raise SpanEvidenceError("complete bundle fingerprint differs")
    return {
        **verified,
        "manifest": manifest,
        "fingerprint": fingerprint,
        "census_rows": tables["census"],
        "goal_rows": tables["goals"],
        "census_path": paths["census"],
        "goals_path": paths["goals"],
        "decoded_bytes": decoded,
        "manifest_sha256": _sha(manifest_raw),
    }


validate_exchange_manifest = load_exchange_bundle


def _census_version_for_rows(rows):
    schemas = {row.get("schema_version") for row in rows}
    if not schemas or schemas == {CENSUS_SCHEMA}:
        return EXCHANGE_MANIFEST_SCHEMA, CENSUS_COLUMNS
    if schemas == {CENSUS_SCHEMA_V2}:
        return EXCHANGE_MANIFEST_SCHEMA_V2, CENSUS_COLUMNS_V2
    raise SpanEvidenceError("census versions must not be mixed within an immutable bundle")


def _manifest_for_pair(
    census_written,
    goals_written,
    census_rows,
    goal_rows,
    *,
    repository_id,
    agent_id,
    census_path_in_repo=None,
    goals_path_in_repo=None,
):
    fingerprint = _fingerprint(census_rows, goal_rows)
    safe = _safe_agent(agent_id)

    def content_path(requested, default, name):
        return _repo_path(
            str(PurePosixPath(_repo_path(requested)).parent / name)
            if requested
            else default + "/" + name
        )

    schema, unused_columns = _census_version_for_rows(census_rows)
    census_directory = CENSUS_REPO_DIR_V2 if schema == EXCHANGE_MANIFEST_SCHEMA_V2 else CENSUS_REPO_DIR
    census_remote = content_path(
        census_path_in_repo,
        census_directory + "/" + safe,
        "census-" + fingerprint + ".parquet",
    )
    goals_remote = content_path(
        goals_path_in_repo,
        GOALS_REPO_DIR + "/" + safe,
        "goals-" + fingerprint + ".parquet",
    )
    manifest = {
        "schema": schema,
        "repository_id": repository_id,
        "fingerprint": fingerprint,
        "path_in_repo": MANIFEST_REPO_DIR
        + "/"
        + safe
        + "/exchange-"
        + fingerprint
        + ".manifest.json",
        "admitted": False,
        "formalized": False,
        "wrote_compiler": False,
        "enqueued": False,
    }
    for name, written, remote in (
        ("census", census_written, census_remote),
        ("goals", goals_written, goals_remote),
    ):
        manifest[name] = {
            key: written[key] for key in ("filename", "bytes", "row_count", "sha256")
        }
        manifest[name]["path_in_repo"] = remote
    return manifest


def _save_bundle(
    built,
    census_path,
    goals_path,
    *,
    repository_id,
    agent_id,
    census_path_in_repo=None,
    goals_path_in_repo=None,
):
    census_rows, goals = sorted(built["census_rows"], key=_json), sorted(
        built["goal_rows"], key=_json
    )
    if (
        Path(census_path).parent.resolve() != Path(goals_path).parent.resolve()
        or Path(census_path).resolve() == Path(goals_path).resolve()
    ):
        raise SpanEvidenceError(
            "exchange files require distinct names in one directory"
        )
    _refuse(census_path)
    _refuse(goals_path)
    unused_schema, columns = _census_version_for_rows(census_rows)
    census_written = _write_table(census_rows, Path(census_path), columns)
    goals_written = _write_table(goals, Path(goals_path), GOAL_COLUMNS)
    manifest = _manifest_for_pair(
        census_written,
        goals_written,
        census_rows,
        goals,
        repository_id=repository_id,
        agent_id=agent_id,
        census_path_in_repo=census_path_in_repo,
        goals_path_in_repo=goals_path_in_repo,
    )
    manifest_path = Path(census_path).parent / (
        "exchange-" + manifest["fingerprint"] + ".manifest.json"
    )
    manifest_raw = canonical_bytes(manifest)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=".exchange-validation-", suffix=".json", dir=manifest_path.parent
    )
    candidate_path = Path(candidate_name)
    try:
        with os.fdopen(descriptor, "wb") as candidate:
            candidate.write(manifest_raw)
            candidate.flush()
            os.fsync(candidate.fileno())
        # Only validated bundles enter the outbox index. Failed validation leaves
        # immutable data files available for diagnosis without poisoning retries.
        load_exchange_bundle(candidate_path)
        _immutable_write(manifest_path, manifest_raw)
    finally:
        candidate_path.unlink(missing_ok=True)
    return {
        "admitted": False,
        "formalized": False,
        "wrote_compiler": False,
        "enqueued": False,
        "uploaded": False,
        "dry_run": True,
        "full_checkpoint_uploaded": False,
        "jsonl_written": False,
        "repository_id": repository_id,
        "fingerprint": manifest["fingerprint"],
        "census": census_written,
        "goals": goals_written,
        "manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": _sha(canonical_bytes(manifest)),
            "path_in_repo": manifest["path_in_repo"],
        },
        "census_path_in_repo": manifest["census"]["path_in_repo"],
        "goals_path_in_repo": manifest["goals"]["path_in_repo"],
        "census_rows": len(census_rows),
        "goal_rows": len(goals),
        "repair_packets": sum(r["record_kind"] == "repair_packet" for r in goals),
        "training_goals": sum(r["record_kind"] == "training_goal" for r in goals),
    }


def write_exchange_pair(
    rows,
    census_path,
    goals_path,
    *,
    agent_id="compile-local",
    release_id="ipfs-uscode-5016b86a",
    code_identity="uscode-formal-compiler",
    model_identity="router-not-yet-called",
    repository_id=DEFAULT_REPOSITORY_ID,
    round_index=0,
    census_path_in_repo=None,
    goals_path_in_repo=None,
):
    _refuse(census_path)
    _refuse(goals_path)
    built = exchange_from_compiled(
        rows,
        agent_id=agent_id,
        release_id=release_id,
        code_identity=code_identity,
        model_identity=model_identity,
        repository_id=repository_id,
        round_index=round_index,
    )
    return _save_bundle(
        built,
        census_path,
        goals_path,
        repository_id=repository_id,
        agent_id=agent_id,
        census_path_in_repo=census_path_in_repo,
        goals_path_in_repo=goals_path_in_repo,
    )


def publish_compiled_exchange(
    rows,
    destination,
    *,
    upload=False,
    agent_id="compile-local",
    release_id="ipfs-uscode-5016b86a",
    code_identity="uscode-formal-compiler",
    model_identity="router-not-yet-called",
    repository_id=DEFAULT_REPOSITORY_ID,
    round_index=0,
    api=None,
    census_path_in_repo=None,
    goals_path_in_repo=None,
):
    built = exchange_from_compiled(
        rows,
        agent_id=agent_id,
        release_id=release_id,
        code_identity=code_identity,
        model_identity=model_identity,
        repository_id=repository_id,
        round_index=round_index,
    )
    fingerprint = _fingerprint(built["census_rows"], built["goal_rows"])
    root = Path(destination)
    receipt = _save_bundle(
        built,
        root / ("census-" + fingerprint + ".parquet"),
        root / ("goals-" + fingerprint + ".parquet"),
        repository_id=repository_id,
        agent_id=agent_id,
        census_path_in_repo=census_path_in_repo,
        goals_path_in_repo=goals_path_in_repo,
    )
    if upload:
        publication = publish_exchange_manifest(
            receipt["manifest"]["path"], upload=True, api=api
        )
        receipt.update({k: v for k, v in publication.items() if k not in {"manifest"}})
    return receipt


def _publication_path(manifest_path):
    return Path(str(manifest_path) + ".publication.json")


def _valid_commit(value):
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value)
    )


def _previous_publication(manifest_path, manifest):
    path = _publication_path(manifest_path)
    if not path.exists():
        return None
    if path.is_symlink():
        raise SpanEvidenceError("publication receipt may not be a symlink")
    receipt = _object(path.read_text())
    _flags(receipt)
    if (
        receipt.get("manifest_sha256") != _sha(Path(manifest_path).read_bytes())
        or receipt.get("repository_id") != manifest["repository_id"]
        or receipt.get("fingerprint") != manifest["fingerprint"]
        or receipt.get("uploaded") is not True
        or not _valid_commit(receipt.get("commit_sha"))
        or not _valid_commit(receipt.get("parent_commit"))
    ):
        raise SpanEvidenceError("publication receipt differs from immutable manifest")
    return receipt


def pending_exchange_manifests(destination):
    root = Path(destination)
    if not root.exists():
        return []
    result = []
    for path in sorted(root.glob("exchange-*.manifest.json")):
        bundle = load_exchange_bundle(path)
        if _previous_publication(path, bundle["manifest"]) is None:
            result.append(path)
    return result


def publish_exchange_manifest(manifest_path, *, upload=False, api=None):
    bundle = load_exchange_bundle(manifest_path)
    manifest = bundle["manifest"]
    path = Path(manifest_path)
    receipt = {
        "repository_id": manifest["repository_id"],
        "fingerprint": manifest["fingerprint"],
        "manifest_sha256": _sha(path.read_bytes()),
        "manifest": {
            "path": str(path.resolve()),
            "path_in_repo": manifest["path_in_repo"],
        },
        "uploaded": False,
        "dry_run": not upload,
        "admitted": False,
        "formalized": False,
        "wrote_compiler": False,
        "enqueued": False,
    }
    previous = _previous_publication(path, manifest)
    if previous is not None:
        return {**previous, "skipped": "already_uploaded"}
    if not upload:
        return receipt
    try:
        from huggingface_hub import HfApi, CommitOperationAdd

        if api is None:
            api = HfApi()
        snapshots = {}
        for kind in ("census", "goals"):
            raw = Path(bundle[kind + "_path"]).read_bytes()
            if (
                len(raw) != manifest[kind]["bytes"]
                or _sha(raw) != manifest[kind]["sha256"]
            ):
                raise SpanEvidenceError("exchange artifact changed before upload")
            snapshots[manifest[kind]["path_in_repo"]] = raw
        manifest_raw = path.read_bytes()
        if manifest_raw != canonical_bytes(manifest):
            raise SpanEvidenceError("exchange manifest changed before upload")
        snapshots[manifest["path_in_repo"]] = manifest_raw
        head = api.repo_info(repo_id=manifest["repository_id"], repo_type="dataset")
        parent = str(head.sha)
        if not _valid_commit(parent):
            raise SpanEvidenceError("Hub returned no immutable parent commit identity")
        existing = api.get_paths_info(
            manifest["repository_id"],
            list(snapshots),
            repo_type="dataset",
            revision=parent,
        )
        present = set()
        for remote in existing:
            remote_path = str(
                getattr(remote, "path", "") or getattr(remote, "rfilename", "")
            )
            if remote_path not in snapshots:
                raise SpanEvidenceError("unexpected remote exchange artifact")
            raw = snapshots[remote_path]
            lfs = getattr(remote, "lfs", None)
            lfs_sha = (
                lfs.get("sha256")
                if isinstance(lfs, Mapping)
                else getattr(lfs, "sha256", None)
            )
            expected = (
                _sha(raw)
                if lfs_sha
                else hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest()
            )
            if (lfs_sha or getattr(remote, "blob_id", None)) != expected:
                raise SpanEvidenceError(
                    "remote immutable exchange path conflicts with retained bytes"
                )
            present.add(remote_path)
        operations = [
            CommitOperationAdd(
                path_in_repo=remote_path,
                path_or_fileobj=raw,
            )
            for remote_path, raw in snapshots.items()
            if remote_path not in present
        ]
        if operations:
            result = api.create_commit(
                repo_id=manifest["repository_id"],
                repo_type="dataset",
                operations=operations,
                parent_commit=parent,
                commit_message="Append immutable autoformal census and deferred supervisor goals",
            )
            commit = str(
                getattr(result, "oid", "")
                or (result.get("oid", "") if isinstance(result, Mapping) else "")
            )
        else:
            commit = parent
            receipt["remote_already_present"] = True
        if not _valid_commit(commit):
            raise SpanEvidenceError("Hub returned no immutable commit identity")
        receipt.update(
            uploaded=True, dry_run=False, commit_sha=commit, parent_commit=parent
        )
        _immutable_write(_publication_path(path), canonical_bytes(receipt))
    except Exception as exc:
        receipt["error"] = type(exc).__name__
    return receipt


def upload_exchange_files(
    census_path,
    goals_path,
    *,
    upload=False,
    repository_id=DEFAULT_REPOSITORY_ID,
    census_path_in_repo,
    goals_path_in_repo,
    api=None,
    manifest_path=None,
):
    import pyarrow.parquet as pq

    census_rows = pq.read_table(census_path).to_pylist()
    goals = pq.read_table(goals_path).to_pylist()
    if any(row.get("repository_id") != repository_id for row in [*census_rows, *goals]):
        raise SpanEvidenceError("exchange repository binding differs")
    agent = (
        str(census_rows[0].get("agent_id") or "compile-local")
        if census_rows
        else "compile-local"
    )
    retained_manifest = Path(census_path).parent / (
        "exchange-" + _fingerprint(census_rows, goals) + ".manifest.json"
    )
    if retained_manifest.exists():
        retained = load_exchange_bundle(retained_manifest)
        if (
            Path(retained["census_path"]).resolve() != Path(census_path).resolve()
            or Path(retained["goals_path"]).resolve() != Path(goals_path).resolve()
        ):
            raise SpanEvidenceError(
                "retained exchange manifest names different artifacts"
            )
        for kind, requested in (
            ("census", census_path_in_repo),
            ("goals", goals_path_in_repo),
        ):
            existing_path = retained["manifest"][kind]["path_in_repo"]
            intended = _repo_path(
                str(
                    PurePosixPath(_repo_path(requested)).parent
                    / PurePosixPath(existing_path).name
                )
            )
            if intended != existing_path:
                raise SpanEvidenceError(
                    "requested exchange destination differs from staged manifest"
                )
        census_path_in_repo = retained["manifest"]["census"]["path_in_repo"]
        goals_path_in_repo = retained["manifest"]["goals"]["path_in_repo"]
    receipt = _save_bundle(
        {"census_rows": census_rows, "goal_rows": goals},
        census_path,
        goals_path,
        repository_id=repository_id,
        agent_id=agent,
        census_path_in_repo=census_path_in_repo,
        goals_path_in_repo=goals_path_in_repo,
    )
    if (
        manifest_path is not None
        and Path(manifest_path).resolve() != Path(receipt["manifest"]["path"]).resolve()
    ):
        raise SpanEvidenceError("specified manifest differs from the immutable pair")
    if upload:
        receipt.update(
            publish_exchange_manifest(receipt["manifest"]["path"], upload=True, api=api)
        )
    return receipt
