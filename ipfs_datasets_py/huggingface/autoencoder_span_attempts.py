"""Portable, immutable per-span attempt observations, including failed gates.

Reports are evidence transports, never authority to promote weights or execute
supervisor tasks. The owner must independently replay and qualify a remote
candidate. Existing census/goals manifests remain discoverable by SpanCacheFeed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from . import autoencoder_incremental as incremental
from .publisher import _reject_secrets
from ..logic.autoformal import span_cache_exchange as exchange

SCHEMA = "autoencoder-span-attempt/v1"
PLAN_SCHEMA = "autoencoder-span-attempt-publication/v1"
REPOSITORY = incremental.REPOSITORY
PREFIX = "autoformal/uscode/attempts"
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
GATES = incremental.GATES
DISPOSITIONS = {"qualified", "needs_repair", "training_exhausted"}


class SpanAttemptError(ValueError):
    """Conflicting, incomplete, unbounded or falsely elevated attempt evidence."""


def _json(value):
    return incremental._json(value)


def _ref(raw):
    return incremental._ref(raw)


def _read(path, bound, ref=None):
    return incremental._read(Path(path), bound, ref)


def _write(path, raw):
    incremental._write(Path(path), raw)


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise SpanAttemptError(label + " requires a bounded nonempty string")
    return value


def _reference(value, *, report=False):
    if not isinstance(value, Mapping):
        raise SpanAttemptError("portable reference required")
    ref = incremental.sparse.artifact_ref(value)
    if value.get("repository_id") != REPOSITORY or not incremental._COMMIT.fullmatch(
        str(value.get("commit_sha", ""))
    ):
        raise SpanAttemptError(
            "reference requires the authorized repository and immutable commit"
        )
    path = exchange._repo_path(value.get("path_in_repo", ""))
    if report and path != f"{PREFIX}/report-{ref['sha256']}.json":
        raise SpanAttemptError("report path is not content addressed")
    return {
        "repository_id": REPOSITORY,
        "commit_sha": value["commit_sha"],
        "path_in_repo": path,
        **ref,
    }


def _receipt(receipt, version_id, artifact):
    """Validate evidence consistency; deliberately do not replace failed gates."""
    if (
        receipt.get("schema_version") != "autoencoder-candidate-qualification/v1"
        or receipt.get("execution_mode") != "native_candidate_qualification"
        or receipt.get("candidate_version_id") != version_id
        or receipt.get("candidate_artifact") != artifact
        or receipt.get("qualification_scope")
        != "embedding_model_and_deterministic_source_compiler_pipeline"
        or receipt.get("model_emits_text_or_formulas") is not False
        or receipt.get("admitted") is not False
        or receipt.get("formalized") is not False
    ):
        raise SpanAttemptError(
            "qualification is not bound to the expected candidate and observation scope"
        )
    rows = receipt.get("rows")
    counts = [receipt.get("sample_count"), receipt.get("heldout_sample_count")]
    if (
        any(type(n) is not int or n < 0 for n in counts)
        or counts[0] < 1
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 1024
        or sum(counts) != len(rows)
    ):
        raise SpanAttemptError("complete bounded qualification rows required")
    from ..optimizers.logic_theorem_optimizer.autoencoder_candidate_qualification import (
        _is_constitution,
    )

    identities = set()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("split") not in {
            "training",
            "heldout",
        }:
            raise SpanAttemptError("invalid qualification row")
        identity = (row["split"], _text(row.get("sample_id"), "sample_id"))
        source = row.get("source")
        if (
            not isinstance(source, Mapping)
            or not isinstance(source.get("text"), str)
            or not source["text"].strip()
        ):
            raise SpanAttemptError("full source text required")
        if identity in identities or incremental._sha(
            source["text"].encode()
        ) != row.get("source_sha256"):
            raise SpanAttemptError("duplicate sample or source digest mismatch")
        identities.add(identity)
        flags = [row.get(gate, {}).get("passed") for gate in GATES[:-1]]
        if any(type(flag) is not bool for flag in flags) or row.get(
            "qualified"
        ) is not all(flags):
            raise SpanAttemptError("qualification row disagrees with gate evidence")
        if (
            row.get("admitted", False) is not False
            or row.get("formalized", False) is not False
        ):
            raise SpanAttemptError("span evidence cannot claim admission")
        if _is_constitution(source):
            if (
                any(row[gate]["passed"] for gate in GATES[1:-1])
                or '"roundtrip_ok"' in _json(row).decode()
                or row.get("compiler", {}).get("roundtrip") is True
            ):
                raise SpanAttemptError("Constitution is not formalized or roundtrip_ok")
    for split, count in zip(("training", "heldout"), counts):
        if sum(row["split"] == split for row in rows) != count:
            raise SpanAttemptError("qualification split count differs")
    gates = receipt.get("gate_results", {})
    for gate in GATES:
        if type(gates.get(gate, {}).get("passed")) is not bool:
            raise SpanAttemptError("missing unchanged qualification gate")
        if gate in receipt and receipt[gate] != gates[gate]:
            raise SpanAttemptError("duplicate qualification gate differs")
        if gate != "heldout_gate" and gates[gate]["passed"] is not all(
            row[gate]["passed"] for row in rows
        ):
            raise SpanAttemptError("qualification aggregate hides a failed row")
    if gates["heldout_gate"]["passed"] and counts[1] == 0:
        raise SpanAttemptError("heldout gate has no heldout samples")
    if receipt.get("qualified") is not all(gates[gate]["passed"] for gate in GATES):
        raise SpanAttemptError("qualified summary disagrees with unchanged gates")
    if (
        not isinstance(receipt.get("repair_todos"), list)
        or any(
            not isinstance(todo, Mapping) for todo in receipt.get("repair_todos", [])
        )
        or not receipt.get("source_sha256")
        or not receipt.get("sample_set_sha256")
    ):
        raise SpanAttemptError(
            "complete qualification provenance and repair todos required"
        )


def _validate(report):
    if report.get("schema") != SCHEMA or report.get("repository_id") != REPOSITORY:
        raise SpanAttemptError("unsupported span attempt report")
    for flag in (
        "admitted",
        "formalized",
        "promotion_performed",
        "supervisor_execution_authorized",
    ):
        if report.get(flag) is not False:
            raise SpanAttemptError(
                "attempt transport cannot authorize admission, promotion or execution"
            )
    for key in ("work_id", "span_revision", "sample_id", "candidate_version_id"):
        _text(report.get(key), key)
    if type(report.get("attempt_index")) is not int or report["attempt_index"] < 0:
        raise SpanAttemptError("attempt_index must be nonnegative")
    receipt = report["qualification"]
    if _ref(_json(receipt)) != report.get("qualification_artifact"):
        raise SpanAttemptError("qualification artifact bytes changed")
    _receipt(receipt, report["candidate_version_id"], report["candidate_artifact"])
    matches = [
        row
        for row in receipt["rows"]
        if row["sample_id"] == report["sample_id"] and row["split"] == "training"
    ]
    if len(matches) != 1:
        raise SpanAttemptError("attempt must identify exactly one training span")
    row = matches[0]
    provenance = report.get("source_provenance", {})
    source = provenance.get("source_record", {})
    if (
        source.get("record_id") != report["span_revision"]
        or source.get("sample") != row["source"]
        or source.get("text") != row["source"]["text"]
        or source.get("source_text_sha256") != row["source_sha256"]
        or report.get("source_sha256") != row["source_sha256"]
    ):
        raise SpanAttemptError("original source revision/sample binding differs")
    _text(source.get("source_span_id"), "source_span_id")
    from ..optimizers.logic_theorem_optimizer.autoencoder_candidate_qualification import (
        _is_constitution,
    )

    source_metadata = {
        **source,
        "document_id": " ".join(
            str(source.get(key, ""))
            for key in ("document_id", "legal_id", "source_span_id")
        ),
    }
    if _is_constitution(source_metadata) and (
        any(row[gate]["passed"] for gate in GATES[1:-1])
        or '"roundtrip_ok"' in _json(row).decode()
        or row.get("compiler", {}).get("roundtrip") is True
    ):
        raise SpanAttemptError(
            "Constitution source provenance cannot claim formalization"
        )
    if (
        type(provenance.get("canonical_generation")) is not int
        or provenance["canonical_generation"] < 1
    ):
        raise SpanAttemptError("assignment canonical generation required")
    _text(provenance.get("canonical_version_id"), "canonical_version_id")
    incremental.sparse.artifact_ref(provenance.get("canonical_artifact", {}))
    if report.get("repair_todos") != receipt["repair_todos"]:
        raise SpanAttemptError("original repair todos changed")
    disposition = report.get("disposition")
    if (
        disposition not in DISPOSITIONS
        or (disposition == "qualified") is not receipt["qualified"]
    ):
        raise SpanAttemptError("attempt disposition disagrees with qualification")
    weight = report.get("weight_publication")
    if weight is not None:
        if not receipt["qualified"]:
            raise SpanAttemptError("failed qualification cannot publish weights")
        reference = _reference(weight)
        if weight.get("materialized_checkpoint") != receipt.get(
            "materialized_checkpoint"
        ):
            raise SpanAttemptError(
                "weight materialized checkpoint differs from qualified evidence"
            )
        manifest = report.get("weight_manifest")
        if weight.get("kind") == "anchor":
            if (
                incremental.sparse.artifact_ref(reference)
                != receipt.get("materialized_checkpoint")
                or manifest is not None
            ):
                raise SpanAttemptError(
                    "full snapshot differs from qualified materialized checkpoint"
                )
        elif weight.get("kind", "sparse") == "sparse":
            anchor = weight.get("anchor_reference")
            if not isinstance(anchor, Mapping):
                raise SpanAttemptError(
                    "sparse weight reference requires its portable anchor"
                )
            depth = 0
            while anchor is not None:
                depth += 1
                if depth > 8:
                    raise SpanAttemptError("portable anchor chain exceeds bound")
                ancestor_ref = incremental.sparse.artifact_ref(_reference(anchor))
                materialized = incremental.sparse.artifact_ref(
                    anchor.get("materialized_checkpoint", {})
                )
                if anchor.get("kind") == "anchor":
                    if (
                        materialized != ancestor_ref
                        or anchor.get("anchor_reference") is not None
                    ):
                        raise SpanAttemptError(
                            "full anchor reference is not terminal or materialized"
                        )
                elif anchor.get("kind") != "sparse" or not isinstance(
                    anchor.get("anchor_reference"), Mapping
                ):
                    raise SpanAttemptError("sparse ancestor reference is incomplete")
                anchor = anchor.get("anchor_reference")
            if (
                not isinstance(manifest, Mapping)
                or _ref(_json(manifest)) != incremental.sparse.artifact_ref(reference)
                or manifest.get("schema") != incremental.SCHEMA
                or manifest.get("path_in_repo") != reference["path_in_repo"]
                or manifest.get("version", {}).get("version_id")
                != report["candidate_version_id"]
                or manifest.get("checkpoint_artifact") != report["candidate_artifact"]
                or manifest.get("qualification_artifact")
                != report["qualification_artifact"]
                or manifest.get("materialized_checkpoint")
                != receipt.get("materialized_checkpoint")
                or manifest.get("anchor_checkpoint")
                != (
                    weight["anchor_reference"].get("materialized_checkpoint")
                    if weight["anchor_reference"].get("kind") == "sparse"
                    else incremental.sparse.artifact_ref(weight["anchor_reference"])
                )
                or manifest.get("qualified_candidate_only") is not True
            ):
                raise SpanAttemptError(
                    "weight publication is not bound to this exact qualified attempt"
                )
        else:
            raise SpanAttemptError("unknown qualified weight kind")
    elif report.get("weight_manifest") is not None:
        raise SpanAttemptError("orphan weight manifest")
    if "exchange" in report:
        desc = report["exchange"]
        exchange_ref = incremental.sparse.artifact_ref(desc)
        path = exchange._repo_path(desc.get("path_in_repo", ""))
        if (
            not re.fullmatch(
                r"autoformal/uscode/exchanges/[A-Za-z0-9_-]+/exchange-[0-9a-f]{64}\.manifest\.json",
                path,
            )
            or desc.get("filename") != Path(path).name
            or exchange_ref["bytes"] > MAX_REPORT_BYTES
        ):
            raise SpanAttemptError("invalid bounded exchange manifest reference")
    _reject_secrets(report, label="span attempt evidence")
    return row


def _goal_rows(census, report, selected):
    from ..logic.autoformal.family_supervision import supervisor_repair_goals

    capture = {
        "census_sha256": census["census_sha256"],
        "source_text_sha256": census["source_text_sha256"],
        "qualification_artifact": report["qualification_artifact"],
        "qualification_gate_results": report["qualification"]["gate_results"],
        "repair_todos": [
            todo
            for todo in report["repair_todos"]
            if todo.get("sample_id") in (None, report["sample_id"])
        ],
        "full_qualification_location": "census.input_json.qualification_attempt.qualification",
        "full_source_provenance_location": "census.input_json.qualification_attempt.source_provenance",
        "source_provenance_sha256": incremental._sha(
            _json(report["source_provenance"])
        ),
        "source_assignment": {
            key: report["source_provenance"][key]
            for key in (
                "canonical_generation",
                "canonical_version_id",
                "canonical_artifact",
            )
        },
        "work_id": report["work_id"],
        "span_revision": report["span_revision"],
        "attempt_index": report["attempt_index"],
        "disposition": report["disposition"],
        "no_execution_authority": True,
    }
    failures = [name for name in GATES[1:-1] if not selected[name]["passed"]]
    rows = [
        {
            "text": census["source_text"],
            "source_span_id": census["source_span_id"],
            "agrees": False,
            "reason": "compiler_abstain",
            "capture": {
                **capture,
                "failed_gate": name,
                "original_gate_evidence": selected[name],
            },
        }
        for name in failures
    ]
    if (
        not report["qualification"]["gate_results"]["metric_gate"]["passed"]
        or not report["qualification"]["gate_results"]["heldout_gate"]["passed"]
        or any(
            not report["qualification"]["gate_results"][name]["passed"]
            and selected[name]["passed"]
            for name in GATES[1:-1]
        )
    ):
        rows.append(
            {
                "text": census["source_text"],
                "source_span_id": census["source_span_id"],
                "agrees": False,
                "reason": "inference_still_failing",
                "capture": {**capture, "failed_gate": "metric_or_validation"},
            }
        )
    goals = supervisor_repair_goals(
        rows,
        **{
            key: census[key]
            for key in ("release_id", "code_identity", "model_identity")
        },
    )
    pairs = [
        ("repair_packet", item["packet"], item["task"])
        for item in goals["repair_packets"]
    ]
    for item in goals["training_goals"]:
        task = {
            **item,
            **{
                key: census[key]
                for key in ("code_identity", "model_identity", "census_sha256")
            },
        }
        task["task_id"] = "AFTD-TRAIN-" + exchange._sha(
            exchange.canonical_bytes({k: v for k, v in task.items() if k != "task_id"})
        )
        pairs.append(("training_goal", task, task))
    return [
        {
            "schema_version": exchange.GOAL_EXPORT_SCHEMA,
            "record_kind": kind,
            **{
                key: census[key]
                for key in (
                    "repository_id",
                    "agent_id",
                    "source_span_id",
                    "legal_id",
                    "census_sha256",
                    "release_id",
                    "code_identity",
                    "model_identity",
                )
            },
            "task_id": task["task_id"],
            "packet_sha256": exchange._sha(exchange.canonical_bytes(packet)),
            "task_sha256": exchange._sha(exchange.canonical_bytes(task)),
            "packet_schema": packet["schema"],
            "todo_schema": task["schema"],
            "handoff_status": "dataset",
            "packet_json": exchange._json(packet),
            "task_json": exchange._json(task),
            "admitted": False,
            "formalized": False,
            "wrote_compiler": False,
            "enqueued": False,
        }
        for kind, packet, task in pairs
    ]


def stage_span_attempt(
    registry,
    candidate_version_id,
    qualification_artifact,
    destination,
    *,
    work_id,
    span_revision,
    sample_id,
    source_provenance,
    disposition,
    attempt_index,
    agent_id,
    weight_publication=None,
):
    """Stage an owner-local receipt and compatible census/goals, including failures."""
    version = registry.get_version(candidate_version_id)
    ref = incremental.sparse.artifact_ref(qualification_artifact)
    raw = _read(registry.artifact_path(ref), MAX_REPORT_BYTES, ref)
    qualification = incremental._object(raw)
    if raw != _json(qualification):
        raise SpanAttemptError(
            "qualification must preserve native canonical JSON bytes"
        )
    report = {
        "schema": SCHEMA,
        "repository_id": REPOSITORY,
        "work_id": work_id,
        "span_revision": span_revision,
        "sample_id": sample_id,
        "attempt_index": attempt_index,
        "candidate_version_id": candidate_version_id,
        "candidate_artifact": version["artifact"],
        "source_provenance": dict(source_provenance),
        "source_sha256": source_provenance.get("source_record", {}).get(
            "source_text_sha256"
        ),
        "disposition": disposition,
        "qualification_artifact": ref,
        "qualification": qualification,
        "repair_todos": qualification.get("repair_todos"),
        "weight_publication": weight_publication,
        "weight_manifest": None,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "supervisor_execution_authorized": False,
        "verification_scope": "immutable_evidence_transport_owner_must_requalify",
    }
    if weight_publication is not None:
        weight_ref = incremental.sparse.artifact_ref(_reference(weight_publication))
        if weight_publication.get("kind") == "anchor":
            registry.verify_artifact(weight_ref)
        else:
            report["weight_manifest"] = incremental._object(
                _read(
                    registry.artifact_path(weight_ref),
                    incremental.MAX_MANIFEST_BYTES,
                    weight_ref,
                )
            )
    selected = _validate(report)
    source = source_provenance["source_record"]
    item = {
        "text": source["text"],
        "source_span_id": source["source_span_id"],
        "legal_id": source.get("legal_id", ""),
        "strict_compiler_agreement": selected["semantic_gate"]["passed"],
        "compiler_result": selected.get("compiler", {}),
        "qualification_attempt": report,
        "comparison": {
            "agrees": False,
            "reason": "qualification_attempt_observation",
            "capture": {},
        },
        "comparison_provenance": {
            "qualification_artifact": ref,
            "source_sha256": selected["source_sha256"],
        },
        "metric_scope": "embedding_metrics_only_not_a_legal_ir_evaluate",
    }
    built = exchange.exchange_from_compiled(
        [item],
        agent_id=agent_id,
        repository_id=REPOSITORY,
        release_id="span-attempt-" + span_revision,
        code_identity="sha256:"
        + incremental._sha(_json(qualification["source_sha256"])),
        model_identity=candidate_version_id,
        round_index=attempt_index,
    )
    census = built["census_rows"][0]
    # Missing model text is explicit; an embedding model has no text roundtrip.
    census.update(
        reason="qualification_attempt_observation",
        agrees=None,
        cosine_similarity=selected["metric_gate"].get("embedding_cosine_similarity"),
        reconstruction_loss=selected["metric_gate"].get("reconstruction_loss"),
    )
    census["holdout_scores_json"] = exchange._json(
        {
            "cosine_similarity": census["cosine_similarity"],
            "reconstruction_loss": census["reconstruction_loss"],
            "cross_entropy_loss": None,
        }
    )
    census["census_sha256"] = exchange._row_hash(census)
    built["goal_rows"] = _goal_rows(census, report, selected)
    fingerprint = exchange._fingerprint(built["census_rows"], built["goal_rows"])
    root = Path(destination).absolute()
    staged = exchange._save_bundle(
        built,
        root / ("census-" + fingerprint + ".parquet"),
        root / ("goals-" + fingerprint + ".parquet"),
        repository_id=REPOSITORY,
        agent_id=agent_id,
    )
    manifest_path = Path(staged["manifest"]["path"])
    report["exchange"] = {
        **_ref(_read(manifest_path, MAX_REPORT_BYTES)),
        "path_in_repo": staged["manifest"]["path_in_repo"],
        "filename": manifest_path.name,
    }
    report_raw = _json(report)
    if len(report_raw) > MAX_REPORT_BYTES:
        raise SpanAttemptError("attempt report exceeds byte bound")
    report_ref = _ref(report_raw)
    report_path = root / ("report-" + report_ref["sha256"] + ".json")
    _write(report_path, report_raw)
    load_span_attempt(report_path)
    return {
        "report_path": str(report_path),
        "report_artifact": report_ref,
        "report_path_in_repo": f"{PREFIX}/{report_path.name}",
        "exchange_manifest_path": str(manifest_path),
        "census_rows": staged["census_rows"],
        "goal_rows": staged["goal_rows"],
        "uploaded": False,
        "admitted": False,
    }


def load_span_attempt(report_path):
    """Validate local report plus exact census/goals snapshots; no qualification run."""
    path = Path(report_path).absolute()
    raw = _read(path, MAX_REPORT_BYTES)
    report = incremental._object(raw)
    _validate(report)
    if raw != _json(report):
        raise SpanAttemptError("report is not canonical")
    desc = report["exchange"]
    filename = desc.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise SpanAttemptError("exchange requires a sibling filename")
    manifest_path = path.parent / filename
    manifest_raw = _read(manifest_path, MAX_REPORT_BYTES, desc)
    bundle = exchange.load_exchange_bundle(
        manifest_path, max_rows=100, max_bytes=MAX_UPLOAD_BYTES
    )
    if bundle["manifest"]["path_in_repo"] != desc["path_in_repo"]:
        raise SpanAttemptError("exchange path differs")
    if len(bundle["census_rows"]) != 1:
        raise SpanAttemptError("one span census required per attempt")
    source_report = json.loads(bundle["census_rows"][0]["input_json"])[
        "qualification_attempt"
    ]
    if source_report != {
        key: value for key, value in report.items() if key != "exchange"
    }:
        raise SpanAttemptError("census differs from complete original attempt")
    snapshots = {
        f"{PREFIX}/report-{_ref(raw)['sha256']}.json": raw,
        desc["path_in_repo"]: manifest_raw,
    }
    files = [
        {"filename": path.name, "path_in_repo": next(iter(snapshots)), **_ref(raw)},
        {
            "filename": filename,
            "path_in_repo": desc["path_in_repo"],
            **_ref(manifest_raw),
        },
    ]
    for kind in ("census", "goals"):
        descriptor = bundle["manifest"][kind]
        content = _read(bundle[kind + "_path"], MAX_UPLOAD_BYTES, descriptor)
        snapshots[descriptor["path_in_repo"]] = content
        files.append(
            {
                "filename": Path(bundle[kind + "_path"]).name,
                "path_in_repo": descriptor["path_in_repo"],
                **_ref(content),
            }
        )
    if sum(len(value) for value in snapshots.values()) > MAX_UPLOAD_BYTES:
        raise SpanAttemptError("attempt bundle exceeds upload byte bound")
    return {
        "report": report,
        "report_artifact": _ref(raw),
        "snapshots": snapshots,
        "files": files,
        "bundle": bundle,
    }


def publish_span_attempt(report_path, *, upload=False, api=None):
    """Atomically append report and compatible exchange, retrying immutable bytes."""
    loaded = load_span_attempt(report_path)
    report, snapshots = loaded["report"], loaded["snapshots"]
    result = {
        "repository_id": REPOSITORY,
        "uploaded": False,
        "dry_run": not upload,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "work_id": report["work_id"],
        "span_revision": report["span_revision"],
        "candidate_version_id": report["candidate_version_id"],
        "disposition": report["disposition"],
    }
    if not upload:
        return result
    from huggingface_hub import HfApi, CommitOperationAdd

    api = api or HfApi()
    parent = str(api.repo_info(repo_id=REPOSITORY, repo_type="dataset").sha)
    if not incremental._COMMIT.fullmatch(parent):
        raise SpanAttemptError("Hub did not return an immutable commit")

    def present_at(commit):
        present = set()
        for row in api.get_paths_info(
            REPOSITORY, list(snapshots), repo_type="dataset", revision=commit
        ):
            path = str(getattr(row, "path", "") or getattr(row, "rfilename", ""))
            if (
                path not in snapshots
                or path in present
                or not incremental._matches(row, snapshots[path])
            ):
                raise SpanAttemptError("immutable remote attempt conflicts")
            present.add(path)
        return present

    present = present_at(parent)
    operations = [
        CommitOperationAdd(path_in_repo=path, path_or_fileobj=raw)
        for path, raw in snapshots.items()
        if path not in present
    ]
    commit = parent
    if operations:
        created = api.create_commit(
            repo_id=REPOSITORY,
            repo_type="dataset",
            operations=operations,
            parent_commit=parent,
            commit_message="Append span attempt evidence and deferred repair goals",
        )
        commit = str(
            getattr(created, "oid", "")
            or (created.get("oid", "") if isinstance(created, Mapping) else "")
        )
    if not incremental._COMMIT.fullmatch(commit) or present_at(commit) != set(
        snapshots
    ):
        raise SpanAttemptError("pinned attempt publication is incomplete")
    ref = {
        "repository_id": REPOSITORY,
        "commit_sha": commit,
        "path_in_repo": loaded["files"][0]["path_in_repo"],
        **loaded["report_artifact"],
    }
    result.update(
        uploaded=True,
        dry_run=False,
        commit_sha=commit,
        report_reference=ref,
        exchange_reference={
            "repository_id": REPOSITORY,
            "commit_sha": commit,
            **{
                key: report["exchange"][key]
                for key in ("path_in_repo", "sha256", "bytes")
            },
        },
    )
    _write(
        Path(report_path).parent
        / "deliveries"
        / (_ref(_json(result))["sha256"] + ".json"),
        _json(result),
    )
    return result


def download_span_attempt_report(
    reference, destination, *, api=None, downloader=None, max_bytes=MAX_REPORT_BYTES
):
    """Fetch only a pinned report; no Parquet, checkpoints, commands or promotion."""
    ref = _reference(reference, report=True)
    if (
        type(max_bytes) is not int
        or not 1 <= max_bytes <= MAX_REPORT_BYTES
        or ref["bytes"] > max_bytes
    ):
        raise SpanAttemptError("report reference exceeds download bound")
    if downloader is None:
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url

        metadata = get_hf_file_metadata(
            hf_hub_url(
                REPOSITORY,
                ref["path_in_repo"],
                repo_type="dataset",
                revision=ref["commit_sha"],
            ),
            timeout=30,
        )
        if metadata.commit_hash != ref["commit_sha"] or metadata.size != ref["bytes"]:
            raise SpanAttemptError("report metadata differs from pinned descriptor")
        source = hf_hub_download(
            repo_id=REPOSITORY,
            repo_type="dataset",
            revision=ref["commit_sha"],
            filename=ref["path_in_repo"],
            local_dir=destination,
            etag_timeout=30,
        )
    else:
        source = downloader(
            repository_id=REPOSITORY,
            revision=ref["commit_sha"],
            filename=ref["path_in_repo"],
            directory=destination,
            max_bytes=ref["bytes"],
        )
    raw = _read(source, max_bytes, ref)
    report = incremental._object(raw)
    _validate(report)
    if "exchange" not in report:
        raise SpanAttemptError(
            "portable report is missing its compatible census exchange"
        )
    if raw != _json(report):
        raise SpanAttemptError("report is not canonical")
    path = Path(destination).absolute() / ("report-" + ref["sha256"] + ".json")
    _write(path, raw)
    return {
        "report": report,
        "report_path": str(path),
        "report_reference": ref,
        "admitted": False,
        "formalized": False,
        "owner_requalification_required": True,
    }


def enqueue_span_attempt(registry, report_path):
    loaded = load_span_attempt(report_path)
    report = loaded["report"]
    if (
        registry.get_version(report["candidate_version_id"])["artifact"]
        != report["candidate_artifact"]
    ):
        raise SpanAttemptError("owner candidate changed")
    for item in loaded["files"]:
        registry.stage_artifact(
            Path(report_path).parent / item["filename"], expected_sha256=item["sha256"]
        )
    plan = {
        "schema": PLAN_SCHEMA,
        "candidate_version_id": report["candidate_version_id"],
        "files": loaded["files"],
    }
    raw = _json(plan)
    local = Path(report_path).parent / ("publication-" + _ref(raw)["sha256"] + ".json")
    _write(local, raw)
    artifact = registry.stage_artifact(local)
    return {
        **registry.enqueue_publication(
            "span-attempt-" + artifact["sha256"],
            report["candidate_version_id"],
            artifact,
        ),
        "plan_artifact": artifact,
        "uploaded": False,
        "admitted": False,
    }


def deliver_span_attempt(
    registry,
    event_id,
    *,
    upload=False,
    worker_id="span-attempt-publisher",
    state_directory=None,
    api=None,
):
    event = registry.get_outbox_event("huggingface", event_id)
    if event["status"] == "acknowledged":
        return {**event["receipt"], "acknowledged": True, "already_delivered": True}
    if event["kind"] != "publication_requested":
        return {
            "event_id": event_id,
            "uploaded": False,
            "deferred": "different_event_kind",
        }
    ref = event["payload"]["plan_artifact"]
    plan = incremental._object(
        _read(registry.artifact_path(ref), MAX_REPORT_BYTES, ref)
    )
    if plan.get("schema") != PLAN_SCHEMA:
        return {
            "event_id": event_id,
            "uploaded": False,
            "deferred": "different_publication_schema",
        }
    if (
        plan.get("candidate_version_id") != event["payload"]["version_id"]
        or len(plan.get("files", [])) != 4
    ):
        raise SpanAttemptError("invalid attempt publication plan")
    root = (
        Path(state_directory)
        if state_directory is not None
        else Path(registry.artifact_root).parent / "hf-span-attempts"
    )
    directory = root / ref["sha256"]
    total = 0
    for item in plan["files"]:
        filename = item.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise SpanAttemptError("publication plan contains a nonlocal filename")
        total += item["bytes"]
        if total > MAX_UPLOAD_BYTES:
            raise SpanAttemptError("publication plan exceeds byte bound")
        _write(
            directory / filename,
            _read(
                registry.artifact_path(incremental.sparse.artifact_ref(item)),
                MAX_UPLOAD_BYTES,
                item,
            ),
        )
    local = directory / plan["files"][0]["filename"]
    loaded = load_span_attempt(local)
    if (
        loaded["files"] != plan["files"]
        or loaded["report"]["candidate_version_id"] != plan["candidate_version_id"]
    ):
        raise SpanAttemptError("publication plan differs from immutable report")
    if (
        registry.get_version(plan["candidate_version_id"])["artifact"]
        != loaded["report"]["candidate_artifact"]
    ):
        raise SpanAttemptError("outbox owner candidate changed")
    if not upload:
        return {
            **publish_span_attempt(local),
            "event_id": event_id,
            "acknowledged": False,
        }
    from uuid import uuid4

    attempt = "span-attempt-delivery-" + uuid4().hex
    lease = event.get("lease")
    if lease and registry._live(lease) and lease.get("worker_id") == worker_id:
        lease = registry.renew_outbox(
            attempt + "-renew", event_id, "huggingface", lease
        )["lease"]
    else:
        lease = registry.claim_outbox_event(
            attempt + "-claim", event_id, "huggingface", worker_id
        )["delivery"]["lease"]
    receipt = {
        **publish_span_attempt(local, upload=True, api=api),
        "event_id": event_id,
    }
    acknowledged = registry.ack_outbox(
        attempt + "-ack", event_id, "huggingface", receipt, lease
    )
    return {**receipt, "acknowledged": acknowledged["acknowledged"]}
