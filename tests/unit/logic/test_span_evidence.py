"""Evidence parquet keeps codec, compiler, citation, and score columns."""
from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.span_evidence import (
    EVIDENCE_COLUMNS,
    EVIDENCE_REPO_PATH,
    EVIDENCE_SCHEMA,
    SpanEvidenceError,
    generate_span_evidence,
    publish_span_evidence,
    write_span_evidence_parquet,
)


def _capture(text: str) -> dict:
    if "imprisoned" in text:
        return {
            "cosine_loss": 0.97,
            "cosine_similarity": 0.03,
            "decoded_text": text,
            "formulas": [{"arguments": ["scope:imprison"], "op": "O", "predicate": "imprison"}],
            "ir_compression_loss": 0.4,
            "ir_compression_ratio": 2.5,
            "reconstruction_loss": 0.0,
            "structural": "O imprison",
        }
    if "ARMED FORCES" in text:
        return {
            "cosine_similarity": 0.64,
            "decoded_text": text,
            "formulas": [
                {
                    "aliased_from": "united_states_code_edition_title_armed",
                    "arguments": [],
                    "op": "Frame",
                    "predicate": "usc:us:10",
                    "role": "frame",
                }
            ],
            "ir_compression_loss": 0.1,
            "ir_compression_ratio": 10.0,
            "reconstruction_loss": 0.0,
            "structural": "Frame usc:us:10",
        }
    if "104 Stat" in text:
        return {"decoded_text": text, "formulas": [], "reconstruction_loss": 0.0, "structural": ""}
    if "1983" in text:
        return {
            "cosine_similarity": 0.8,
            "decoded_text": text,
            "formulas": [{"arguments": ["actor:agency", "scope:record"], "op": "O", "predicate": "record"}],
            "ir_compression_loss": 0.27,
            "reconstruction_loss": 0.0,
            "structural": "O record",
        }
    if text.startswith("Congress"):
        return {
            "cosine_similarity": 0.9,
            "decoded_text": text,
            "formulas": [{"arguments": ["actor:congress", "scope:record"], "op": "O", "predicate": "record"}],
            "ir_compression_loss": 0.2,
            "reconstruction_loss": 0.0,
            "structural": "O record",
        }
    return {
        "cosine_loss": 0.1,
        "cosine_similarity": 0.9,
        "decoded_text": text,
        "formulas": [
            {
                "arguments": ["actor:agency", "scope:record_available"],
                "op": "O",
                "predicate": "record_available",
            }
        ],
        "ir_compression_loss": 0.2,
        "ir_compression_ratio": 5.0,
        "reconstruction_loss": 0.0,
        "structural": "O record_available",
    }


def _compile(session: object, text: str, span_id: str) -> dict:
    del session, span_id
    if "imprisoned" in text:
        return {
            "compiler_status": "abstain",
            "decompiled": "",
            "fields": ["penalty"],
            "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
        }
    if "ARMED FORCES" in text or "104 Stat" in text:
        return {
            "compiler_status": "abstain",
            "decompiled": "",
            "fields": ["no_parser_elements"],
            "reason": "no_parser_elements",
        }
    if "1983" in text:
        return {
            "compiler_status": "compiled",
            "decompiled": "Agency must keep the record.",
            "fields": [],
            "reason": "",
            "rule": {"action": "keep", "actor": "agency", "modality": "O", "object": "record"},
        }
    if text.startswith("Congress"):
        return {
            "compiler_status": "compiled",
            "decompiled": "Congress must keep the record.",
            "fields": [],
            "reason": "",
            "rule": {"action": "keep", "actor": "Congress", "modality": "obligation", "object": "the record"},
        }
    return {
        "compiler_status": "compiled",
        "decompiled": "Agency must make records available.",
        "fields": [],
        "reason": "",
        "rule": {"action": "make", "actor": "Agency", "modality": "obligation", "object": "records"},
    }


def _spans() -> list[dict[str, str]]:
    return [
        {"legal_id": "usc:us:5:552", "source_span_id": "e2e-duty", "text": "Each agency shall make records available."},
        {"legal_id": "usc:us:1:5", "source_span_id": "e2e-congress", "text": "Congress shall keep the record."},
        {
            "legal_id": "usc:us:42:1983",
            "source_span_id": "e2e-cite",
            "text": "The agency shall keep the record of a claim under 42 U.S.C. § 1983 and 123 F.3d 456.",
        },
        {"legal_id": "usc:us:18:1001", "source_span_id": "e2e-penalty", "text": "Whoever shall be imprisoned."},
        {
            "legal_id": "usc:us:10",
            "source_span_id": "e2e-title",
            "text": "United States Code, 2024 Edition Title 10 - ARMED FORCES",
        },
        {"legal_id": "", "source_span_id": "e2e-scrap", "text": "5, 1990, 104 Stat."},
    ]


def test_evidence_rows_fill_formulas_citations_repair_and_scores(tmp_path: Path) -> None:
    calls: list[str] = []

    def lake_check(source: str) -> dict:
        calls.append(source)
        return {"admitted": False, "formalized": False, "lake_ok": "axiom" not in source}

    rows = generate_span_evidence(
        _spans(),
        capture=_capture,
        compile_one=_compile,
        lake_check=lake_check,
        lake_limit=4,
        lake_successes=1,
        code_identity="sha256:test",
    )
    by_id = {row["source_span_id"]: row for row in rows}
    duty = by_id["e2e-duty"]
    cite = by_id["e2e-cite"]
    penalty = by_id["e2e-penalty"]
    title = by_id["e2e-title"]
    scrap = by_id["e2e-scrap"]
    congress = by_id["e2e-congress"]

    assert duty["schema_version"] == EVIDENCE_SCHEMA
    assert duty["consensus"] == "agree"
    assert duty["agrees"] is True
    assert duty["census_agree"] is True
    assert duty["sealed"] is True
    assert duty["status"] == "sealed"
    assert duty["admitted"] is False
    assert duty["formalized"] is False
    assert duty["wrote_compiler"] is False
    assert duty["lake_ok"] is True
    assert duty["lake_disposition"] == "duty"
    assert duty["repair_error"] == ""
    assert duty["cosine_similarity"] >= 0.72
    assert duty["measurements"] > 0
    assert duty["cross_entropy_loss"] is not None
    assert duty["cross_entropy_loss"] <= 2.4
    assert duty["reconstruction_loss"] == 0.0
    assert duty["ir_compression_loss"] == 0.2
    assert duty["family_cross_entropy_loss"] is None
    assert "record_available" in duty["formulas_json"]
    assert duty["decompiled"] == "Agency must make records available."
    assert congress["lake_ok"] is None
    assert congress["admitted"] is False

    citations = json.loads(cite["citations_json"])
    formulas = json.loads(cite["formulas_json"])
    predicates = {item["predicate"] for item in formulas}
    assert "usc:us:42:1983" in citations
    assert "123-f3d-456" in citations
    assert "usc:us:42:1983" in predicates
    assert "123-f3d-456" in predicates
    assert cite["consensus"] == "disagree"
    assert cite["admitted"] is False

    assert "penalty" in penalty["repair_error"].lower() or "imprison" in penalty["repair_error"].lower()
    assert "canonical_compiler.py" in penalty["repair_fix"]
    assert "canonical_compiler.py" in penalty["edit_paths_json"]
    assert penalty["symbols_json"] != "[]"
    assert penalty["consensus"] == "disagree"
    assert penalty["lake_disposition"] == "unrendered"
    assert penalty["sealed"] is False
    assert penalty["formalized"] is False

    title_formulas = json.loads(title["formulas_json"])
    assert title_formulas[0]["predicate"] == "usc:us:10"
    assert title_formulas[0]["aliased_from"] == "united_states_code_edition_title_armed"
    assert title_formulas[0]["lake"] == "fixture"
    assert title_formulas[0]["lake_code"] == 6
    assert title["lake_disposition"] == "fixture"
    assert title["ir_compression_loss"] == 0.1
    assert title["consensus"] == "disagree"

    assert scrap["consensus"] == "unscored"
    assert json.loads(scrap["formulas_json"]) == []
    assert scrap["admitted"] is False
    assert all(row["admitted"] is False and row["formalized"] is False for row in rows)
    assert calls
    assert all("axiom" not in source for source in calls)

    written = write_span_evidence_parquet(rows, tmp_path / "span-evidence.parquet")
    assert written["jsonl_written"] is False
    assert written["row_count"] == len(rows)
    assert not (tmp_path / "span-evidence.jsonl").exists()
    table = pq.read_table(tmp_path / "span-evidence.parquet")
    assert table.column_names == list(EVIDENCE_COLUMNS)
    stored = table.to_pylist()
    assert stored[0]["source_span_id"] == "e2e-duty"
    assert stored[0]["consensus"] == "agree"
    assert all(row["admitted"] is False and row["formalized"] is False for row in stored)
    assert {row["lake_ok"] for row in stored if row["source_span_id"] == "e2e-congress"} == {None}


def test_publish_refuses_the_resume_checkpoint_and_uploads_the_evidence_path(tmp_path: Path) -> None:
    path = tmp_path / "span-evidence.parquet"
    write_span_evidence_parquet([], path)
    dry = publish_span_evidence(path, upload=False)
    assert dry["uploaded"] is False
    assert dry["dry_run"] is True
    assert dry["admitted"] is False

    class Api:
        def __init__(self) -> None:
            self.kwargs: dict = {}

        def create_repo(self, *args, **kwargs) -> None:
            del args, kwargs

        def upload_file(self, **kwargs):
            self.kwargs = kwargs
            return type("Commit", (), {"commit_url": "https://example.invalid/commit/abc", "oid": "abc"})()

    api = Api()
    with pytest.raises(SpanEvidenceError):
        publish_span_evidence(
            path,
            upload=True,
            path_in_repo="autoformal/uscode/resume-checkpoint.parquet",
            api=api,
        )
    with pytest.raises(SpanEvidenceError):
        write_span_evidence_parquet([], tmp_path / "resume-checkpoint.parquet")
    receipt = publish_span_evidence(path, upload=True, api=api)
    assert receipt["uploaded"] is True
    assert receipt["formalized"] is False
    assert api.kwargs["path_in_repo"] == EVIDENCE_REPO_PATH
    assert api.kwargs["repo_id"] == "justicedao/uscode-autoformal-span-cache"
    assert api.kwargs["repo_type"] == "dataset"
    assert "token" not in api.kwargs
