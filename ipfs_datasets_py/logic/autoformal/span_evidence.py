"""Evidence rows for a small autoformal span batch.

The resume checkpoint stays a status export. These rows are a separate
parquet: source text, codec formulas, compiler output, repair capsule,
citation symbols, and the scores used to judge agreement. A row is not a
legal admit. JSONL is not written.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


EVIDENCE_SCHEMA = "uscode-autoformal-span-evidence/v1"
DEFAULT_REPOSITORY_ID = "justicedao/uscode-autoformal-span-cache"
EVIDENCE_REPO_PATH = "autoformal/uscode/span-evidence.parquet"
DATASET_ID = "justicedao/ipfs_uscode"

EVIDENCE_COLUMNS = (
    "schema_version",
    "record_kind",
    "repository_id",
    "dataset_id",
    "source_span_id",
    "legal_id",
    "source_sha256",
    "source_text",
    "status",
    "sealed",
    "admitted",
    "formalized",
    "wrote_compiler",
    "code_identity",
    "decoded_text",
    "structural",
    "formulas_json",
    "citations_json",
    "compiler_status",
    "compiler_reason",
    "compiler_fields_json",
    "decompiled",
    "rule_json",
    "repair_error",
    "repair_fix",
    "repair_diagnostic",
    "edit_paths_json",
    "symbols_json",
    "repair_json",
    "cosine_similarity",
    "embedding_cosine_similarity",
    "embedding_cosine_loss",
    "reconstruction_loss",
    "ir_compression_loss",
    "ir_compression_ratio",
    "cross_entropy_loss",
    "round_trip_cross_entropy_loss",
    "formula_cross_entropy_loss",
    "family_cross_entropy_loss",
    "view_cross_entropy_loss",
    "measurements",
    "formula_matches",
    "consensus",
    "agrees",
    "census_agree",
    "lake_ok",
    "lake_disposition",
    "train",
)


class SpanEvidenceError(ValueError):
    """The evidence export would replace the resume checkpoint or drop a column."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _strings(values: Any, *, limit: int) -> list[str]:
    found: list[str] = []
    for item in list(values or []):
        text = str(item or "").strip()
        if text and text not in found:
            found.append(text)
        if len(found) >= limit:
            break
    return found


def _disposition(formulas: Sequence[Mapping[str, Any]]) -> str:
    lakes = [str(item.get("lake") or "") for item in formulas if isinstance(item, Mapping)]
    if "duty" in lakes:
        return "duty"
    if "fixture" in lakes:
        return "fixture"
    if lakes:
        return "unrendered"
    return "none"


def _lean_source(formulas: Sequence[Mapping[str, Any]]) -> str:
    from .lake_probe import pattern_from_fixture, pattern_from_rule, render_fixture, render_norm

    parts: list[str] = []
    for formula in list(formulas)[:4]:
        if not isinstance(formula, Mapping):
            continue
        arguments = [str(part) for part in formula.get("arguments") or []]
        actor = next((part.split(":", 1)[1] for part in arguments if part.startswith("actor:")), "")
        scope = next((part.split(":", 1)[1] for part in arguments if part.startswith("scope:")), "")
        rule = {
            "action": str(formula.get("predicate") or ""),
            "actor": actor,
            "modality": str(formula.get("op") or ""),
            "object": scope,
        }
        duty = pattern_from_rule(rule)
        fixture = pattern_from_fixture(rule)
        if duty is not None:
            parts.append(render_norm(duty, suffix=str(len(parts))))
        elif fixture is not None:
            parts.append(render_fixture(fixture, suffix=str(len(parts))))
    return "\n".join(parts)


def _with_citations(formulas: list[dict[str, Any]], citations: Sequence[str]) -> list[dict[str, Any]]:
    from .repair_report import formula_evidence

    present = {str(item.get("predicate") or "") for item in formulas}
    rows = list(formulas)
    for symbol in citations:
        if symbol in present or len(rows) >= 8:
            continue
        extra = formula_evidence(
            {"formulas": [{"arguments": [], "op": "Frame", "predicate": symbol, "role": "citation"}]}
        )
        if not extra:
            continue
        rows.append(extra[0])
        present.add(symbol)
    return rows[:8]


def _auto_block(
    captured: Mapping[str, Any],
    formulas: Sequence[Mapping[str, Any]],
    decoded: str,
    structural: str,
) -> dict[str, Any]:
    return {
        "cosine_loss": captured.get("cosine_loss"),
        "cosine_similarity": captured.get("cosine_similarity"),
        "cross_entropy_loss": captured.get("cross_entropy_loss"),
        "decoded_text": decoded[:240],
        "formulas": [dict(item) for item in formulas[:8]],
        "ir_compression_loss": captured.get("ir_compression_loss"),
        "ir_compression_ratio": captured.get("ir_compression_ratio"),
        "reconstruction_loss": captured.get("reconstruction_loss"),
        "structural": structural[:180],
        "view_cross_entropy_loss": captured.get("view_cross_entropy_loss"),
    }


def _success_repair(
    captured: Mapping[str, Any],
    compiled: Mapping[str, Any],
    formulas: Sequence[Mapping[str, Any]],
    citations: Sequence[str],
    decoded: str,
    structural: str,
) -> dict[str, Any]:
    rule = compiled.get("rule") if isinstance(compiled.get("rule"), Mapping) else {}
    return {
        "admitted": False,
        "autoencoder": _auto_block(captured, formulas, decoded, structural),
        "citations": list(citations)[:8],
        "compiler": {
            "decompiled": str(compiled.get("decompiled") or "")[:240],
            "fields": _strings(compiled.get("fields"), limit=8),
            "reason": "",
            "rule": dict(rule),
            "status": str(compiled.get("compiler_status") or compiled.get("status") or ""),
        },
        "diagnostic": "",
        "edit_paths": [],
        "error": "",
        "fix": "",
        "formalized": False,
        "lake": {
            "admits": False,
            "command": "lake build Legal",
            "refuses": ["admit", "axiom", "sorry"],
        },
        "symbols": [],
        "wrote_compiler": False,
    }


def demonstration_spans() -> list[dict[str, str]]:
    """Hand-checked sentences covering a duty, a citation, a penalty, a frame, and a scrap."""

    rows = (
        ("e2e-duty-5-552", "usc:us:5:552", "Each agency shall make records available."),
        ("e2e-duty-congress", "usc:us:1:5", "Congress shall keep the record."),
        (
            "e2e-cite-42-1983",
            "usc:us:42:1983",
            "The agency shall keep the record of a claim under 42 U.S.C. § 1983 and 123 F.3d 456.",
        ),
        ("e2e-penalty-imprison", "usc:us:18:1001", "Whoever shall be imprisoned."),
        ("e2e-prohibition-theft", "usc:us:18:661", "No person shall commit theft."),
        ("e2e-title-10", "usc:us:10", "United States Code, 2024 Edition Title 10 - ARMED FORCES"),
        (
            "e2e-fine-title",
            "usc:us:18:1001",
            "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
        ),
        ("e2e-stat-scrap", "", "5, 1990, 104 Stat."),
    )
    return [{"legal_id": legal_id, "source_span_id": span_id, "text": text} for span_id, legal_id, text in rows]


def generate_span_evidence(
    spans: Sequence[Mapping[str, Any]],
    *,
    session: Any | None = None,
    capture: Callable[[str], Mapping[str, Any]] | None = None,
    compile_one: Callable[..., Mapping[str, Any]] | None = None,
    lake_check: Callable[[str], Mapping[str, Any]] | None = None,
    lake_limit: int = 4,
    lake_successes: int = 2,
    code_identity: str = "",
    dataset_id: str = DATASET_ID,
    repository_id: str = DEFAULT_REPOSITORY_ID,
) -> list[dict[str, Any]]:
    """Census each span and project one evidence row. Does not open the span cache."""

    from .repair_report import formula_evidence, repair_report
    from .span_agreement import annotate_compiled_batch, decide_span, result_alignment

    if capture is None:
        from .repair_report import codec_capture

        capture = codec_capture
    if compile_one is None:
        from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

        session = session or AutoformalSession()

        def compile_one(active: Any, text: str, span_id: str, _compile=compile_span) -> Mapping[str, Any]:
            return _compile(active, text, span_id)

    if not code_identity:
        from .span_cache import compiler_identity, compiler_path_hashes

        code_identity = compiler_identity(compiler_path_hashes(Path(__file__).resolve().parents[3]))

    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import bluebook_symbols

    prepared: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        text = str(span.get("text") or span.get("source_text") or "").strip()
        span_id = str(span.get("source_span_id") or span.get("id") or "")
        if not text or not span_id:
            continue
        legal_id = str(span.get("legal_id") or "")
        captured = dict(capture(text) or {})
        decoded = " ".join(str(captured.get("decoded_text") or text).split())
        compiled = dict(compile_one(session, decoded or text, span_id) or {})
        status = str(compiled.get("compiler_status") or compiled.get("status") or "")
        agrees = status in {"compiled", "roundtrip_ok"}
        rule = compiled.get("rule") if isinstance(compiled.get("rule"), Mapping) else {}
        fields = _strings(compiled.get("fields"), limit=8)
        reason = "" if agrees else str(compiled.get("reason") or "compiler_abstain")
        citations = _strings([*list(captured.get("citations") or []), *bluebook_symbols(text)], limit=8)
        formulas = _with_citations(formula_evidence(captured), citations)
        structural = " ".join(str(captured.get("structural") or "").split())
        enriched = {**captured, "citations": citations, "formulas": formulas}
        compiled_view = {
            "compiler_status": status,
            "decompiled": str(compiled.get("decompiled") or ""),
            "fields": fields,
            "reason": reason,
            "rule": dict(rule),
        }
        if agrees:
            repair = _success_repair(enriched, compiled_view, formulas, citations, decoded, structural)
        else:
            repair = repair_report(compiler=compiled_view, autoencoder=enriched)
            autoencoder = dict(repair.get("autoencoder") or {})
            autoencoder["formulas"] = [dict(item) for item in formulas[:8]]
            repair = {**repair, "autoencoder": autoencoder, "citations": citations[:8]}
        prepared.append(
            {
                "agrees": agrees,
                "compiled": agrees,
                "cosine_loss": captured.get("cosine_loss"),
                "cosine_similarity": captured.get("cosine_similarity"),
                "cross_entropy_loss": captured.get("cross_entropy_loss"),
                "decompiled": str(compiled.get("decompiled") or ""),
                "ir_compression_loss": captured.get("ir_compression_loss"),
                "legal_id": legal_id,
                "reason": reason,
                "reconstruction_loss": captured.get("reconstruction_loss"),
                "repair": repair,
                "rule": dict(rule),
                "source_sha256": _sha(text),
                "source_span_id": span_id,
                "text": text,
            }
        )
    annotated = annotate_compiled_batch(prepared, lake_check=lake_check, lake_limit=lake_limit)
    remaining = max(0, int(lake_successes))
    check = lake_check
    if check is None and remaining:
        from .lake_probe import lake_check as default_lake_check

        check = default_lake_check
    if check is not None and remaining:
        revised: list[dict[str, Any]] = []
        for item in annotated:
            if remaining <= 0 or item.get("agrees") is not True:
                revised.append(item)
                continue
            formulas = list(((item.get("repair") or {}).get("autoencoder") or {}).get("formulas") or [])
            source = _lean_source(formulas)
            if not source:
                revised.append(decide_span(item, lake_ok=False))
                continue
            receipt = dict(check(source) or {})
            revised.append(decide_span(item, lake_ok=receipt.get("lake_ok") is True))
            remaining -= 1
        annotated = revised
    rows = [
        _project_row(
            item,
            code_identity=code_identity,
            dataset_id=dataset_id,
            repository_id=repository_id,
        )
        for item in annotated
    ]
    _require_columns(rows)
    return rows


def _project_row(
    item: Mapping[str, Any],
    *,
    code_identity: str,
    dataset_id: str,
    repository_id: str,
) -> dict[str, Any]:
    from .span_agreement import result_alignment

    repair = dict(item.get("repair") or {})
    autoencoder = dict(repair.get("autoencoder") or {})
    compiler = dict(repair.get("compiler") or {})
    formulas = [dict(formula) for formula in autoencoder.get("formulas") or [] if isinstance(formula, Mapping)]
    citations = _strings(repair.get("citations"), limit=8)
    alignment = result_alignment(item)
    census = dict(item.get("census") or {})
    agrees = item.get("agrees") is True
    lake_ok = census.get("lake_ok")
    if lake_ok is not None:
        lake_ok = lake_ok is True
    rule = item.get("rule") if isinstance(item.get("rule"), Mapping) else {}
    fields = _strings(compiler.get("fields"), limit=8)
    return {
        "admitted": False,
        "agrees": agrees,
        "census_agree": census.get("agree") is True,
        "citations_json": _json(citations),
        "code_identity": code_identity,
        "compiler_fields_json": _json(fields),
        "compiler_reason": str(item.get("reason") or compiler.get("reason") or ""),
        "compiler_status": str(compiler.get("status") or ""),
        "consensus": str(census.get("consensus") or ""),
        "cosine_similarity": _number(alignment.get("cosine_similarity")),
        "cross_entropy_loss": _number(alignment.get("cross_entropy_loss")),
        "dataset_id": dataset_id,
        "decoded_text": str(autoencoder.get("decoded_text") or ""),
        "decompiled": str(item.get("decompiled") or ""),
        "edit_paths_json": _json(_strings(repair.get("edit_paths"), limit=8)),
        "embedding_cosine_loss": _number(autoencoder.get("cosine_loss")),
        "embedding_cosine_similarity": _number(autoencoder.get("cosine_similarity")),
        "family_cross_entropy_loss": _number(autoencoder.get("cross_entropy_loss")),
        "formalized": False,
        "formula_cross_entropy_loss": _number(alignment.get("formula_cross_entropy_loss")),
        "formula_matches": alignment.get("formula_matches") is True,
        "formulas_json": _json(formulas),
        "ir_compression_loss": _number(autoencoder.get("ir_compression_loss")),
        "ir_compression_ratio": _number(autoencoder.get("ir_compression_ratio")),
        "lake_disposition": _disposition(formulas),
        "lake_ok": lake_ok,
        "legal_id": str(item.get("legal_id") or ""),
        "measurements": int(alignment.get("measurements") or 0),
        "reconstruction_loss": _number(autoencoder.get("reconstruction_loss")),
        "record_kind": "span",
        "repair_diagnostic": str(repair.get("diagnostic") or ""),
        "repair_error": str(repair.get("error") or ""),
        "repair_fix": str(repair.get("fix") or ""),
        "repair_json": _json(repair),
        "repository_id": repository_id,
        "round_trip_cross_entropy_loss": _number(alignment.get("round_trip_cross_entropy_loss")),
        "rule_json": _json(dict(rule)),
        "schema_version": EVIDENCE_SCHEMA,
        "sealed": agrees,
        "source_sha256": str(item.get("source_sha256") or _sha(str(item.get("text") or ""))),
        "source_span_id": str(item.get("source_span_id") or ""),
        "source_text": str(item.get("text") or ""),
        "status": "sealed" if agrees else "gap",
        "structural": str(autoencoder.get("structural") or ""),
        "symbols_json": _json(_strings(repair.get("symbols"), limit=8)),
        "train": census.get("train") is True,
        "view_cross_entropy_loss": _number(autoencoder.get("view_cross_entropy_loss")),
        "wrote_compiler": False,
    }


def _require_columns(rows: Sequence[Mapping[str, Any]]) -> None:
    missing = [name for name in EVIDENCE_COLUMNS if rows and name not in rows[0]]
    if missing:
        raise SpanEvidenceError("evidence row is missing " + ", ".join(missing))


def evidence_schema():
    """Arrow schema for the evidence parquet. Null scores stay null."""

    import pyarrow as pa

    floats = {
        "cosine_similarity",
        "cross_entropy_loss",
        "embedding_cosine_loss",
        "embedding_cosine_similarity",
        "family_cross_entropy_loss",
        "formula_cross_entropy_loss",
        "ir_compression_loss",
        "ir_compression_ratio",
        "reconstruction_loss",
        "round_trip_cross_entropy_loss",
        "view_cross_entropy_loss",
    }
    bools = {
        "admitted",
        "agrees",
        "census_agree",
        "formalized",
        "formula_matches",
        "lake_ok",
        "sealed",
        "train",
        "wrote_compiler",
    }
    fields = []
    for name in EVIDENCE_COLUMNS:
        if name in floats:
            fields.append(pa.field(name, pa.float64()))
        elif name in bools:
            fields.append(pa.field(name, pa.bool_()))
        elif name == "measurements":
            fields.append(pa.field(name, pa.int32()))
        else:
            fields.append(pa.field(name, pa.string()))
    return pa.schema(fields)


def write_span_evidence_parquet(rows: Sequence[Mapping[str, Any]], path: str | Path) -> dict[str, Any]:
    """Write the evidence parquet. Does not write JSONL or the resume checkpoint."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    destination = Path(path)
    if destination.name == "resume-checkpoint.parquet":
        raise SpanEvidenceError("span evidence must not replace the resume checkpoint")
    destination.parent.mkdir(parents=True, exist_ok=True)
    projected = [dict(row) for row in rows]
    _require_columns(projected)
    table = pa.Table.from_pylist(projected, schema=evidence_schema()) if projected else pa.Table.from_pylist(
        [], schema=evidence_schema()
    )
    pq.write_table(table, destination)
    return {
        "admitted": False,
        "bytes": destination.stat().st_size,
        "formalized": False,
        "jsonl_written": False,
        "path": str(destination),
        "row_count": table.num_rows,
        "schema_version": EVIDENCE_SCHEMA,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }


def publish_span_evidence(
    path: str | Path,
    *,
    upload: bool = False,
    repository_id: str = DEFAULT_REPOSITORY_ID,
    path_in_repo: str = EVIDENCE_REPO_PATH,
    api: Any | None = None,
) -> dict[str, Any]:
    """Upload the evidence parquet. Dry-run does not contact Hugging Face."""

    source = Path(path)
    if Path(path_in_repo).name == "resume-checkpoint.parquet" or source.name == "resume-checkpoint.parquet":
        raise SpanEvidenceError("span evidence must not replace the resume checkpoint")
    receipt = {
        "admitted": False,
        "dry_run": not upload,
        "formalized": False,
        "jsonl_written": False,
        "path_in_repo": path_in_repo,
        "repository_id": repository_id,
        "uploaded": False,
    }
    if not upload:
        return receipt
    if api is None:
        from huggingface_hub import HfApi

        api = HfApi()
    api.create_repo(repository_id, repo_type="dataset", exist_ok=True)
    commit = api.upload_file(
        path_or_fileobj=str(source),
        path_in_repo=path_in_repo,
        repo_id=repository_id,
        repo_type="dataset",
        commit_message="autoformal span evidence rows",
    )
    receipt["uploaded"] = True
    receipt["dry_run"] = False
    receipt["commit"] = str(getattr(commit, "commit_url", "") or getattr(commit, "oid", "") or "")
    return receipt
