"""Unit tests for the OUL-008 US Code GraphRAG reuse and scale-gap audit."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.audit_open_us_law_graphrag_reuse import (
    BM25_DOCUMENT_CEILING,
    LEGAL_TOKENIZER_ID,
    PHYSICAL_SHARD_BOUND,
    PINNED_GTE_MODEL,
    PINNED_GTE_REVISION,
    PRODUCER,
    PROGRAM_ID,
    REPAIR_AREA_IDS,
    REPORT_SCHEMA,
    REUSABLE_CONTRACT_IDS,
    SEED_ROW_COUNT,
    SHARED_TOKENIZER_ID,
    TASK_ID,
    SubstrateAuditError,
    acceptance_projection,
    build_substrate_gap_audit,
    check_committed_audit,
    check_substrate_gap_audit,
    default_report_path,
    encode_audit_report,
    expected_acceptance,
    inspect_reused_substrate,
    load_substrate_gap_audit,
    main,
    sha256_json,
    validate_substrate_gap_audit,
    write_substrate_gap_audit,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _reseal(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key != "audit_digest_sha256"}
    payload["audit_digest_sha256"] = sha256_json(body)
    return payload


def test_inspection_proves_reusable_physical_and_identity_contracts() -> None:
    inspection = inspect_reused_substrate(_repo_root())
    schema = inspection["schema_constants"]
    embeddings = inspection["embeddings_constants"]
    tokenizer = inspection["tokenizer_constants"]

    assert schema["MAX_ROWS_PER_PHYSICAL_SHARD"] == PHYSICAL_SHARD_BOUND == 4096
    assert schema["MAX_POINTERS_PER_ROW"] == 4096
    assert schema["MAX_ROUTING_ROWS_PER_INDEX"] == 4096
    assert schema["MAX_ROWS_PER_VECTOR_CENTROID"] == 8192
    assert schema["MAX_VECTOR_SHARDS_PER_CENTROID"] == 2
    assert inspection["schema_has_artifact_family"] is True
    assert inspection["function_inventory"]["build_bm25_layout"] is True
    assert inspection["function_inventory"]["page_locator_rows"] is True
    assert inspection["function_inventory"]["tokenize_legal_text"] is True
    assert inspection["virtual_term_document_edges"] is True

    assert embeddings["DEFAULT_MODEL_ID"] == PINNED_GTE_MODEL
    assert embeddings["DEFAULT_MODEL_REVISION"] == PINNED_GTE_REVISION
    assert embeddings["DEFAULT_DIMENSION"] == 384
    assert embeddings["DEFAULT_MAX_TOKENS"] == 512
    assert embeddings["DEFAULT_POOLING"] == "mean"
    assert embeddings["DEFAULT_NORMALIZATION"] == "l2"
    assert tokenizer["TOKENIZER_ID"] == LEGAL_TOKENIZER_ID


def test_inspection_records_the_eight_scale_repairs() -> None:
    inspection = inspect_reused_substrate(_repo_root())
    bm25 = inspection["bm25_constants"]
    embeddings = inspection["embeddings_constants"]

    assert embeddings["DEFAULT_BACKEND"] == "local_deterministic_projection"
    assert inspection["gte_encode_sets_max_seq_length"] is False
    assert bm25["max_documents"] == BM25_DOCUMENT_CEILING == 250_000
    assert inspection["uscode_bm25_constants"]["MAX_DOCUMENTS"] == 250_000
    assert BM25_DOCUMENT_CEILING < SEED_ROW_COUNT
    assert inspection["missing_scale_primitives"] == [
        "ipfs_datasets_py/retrieval/hf_graphrag/external_sort.py",
        "ipfs_datasets_py/retrieval/hf_graphrag/hierarchical_routes.py",
    ]
    assert inspection["locator_pages_globally_capped"] is True
    assert inspection["entry_locator_present"] is True
    assert inspection["entry_locator_page_cap"] is True
    assert inspection["query_uses_shared_tokenizer"] is True
    assert inspection["adapter_uses_legal_tokenizer"] is True
    assert bm25["DEFAULT_BM25_TOKENIZER_ID"] == SHARED_TOKENIZER_ID
    assert inspection["neighbor_scans_all_documents"] is True
    assert inspection["lineage_is_per_row"] is True
    assert inspection["lineage_schema"] is True
    assert all(
        str(task_id).startswith("USCIR-")
        for task_id in inspection["shared_task_ids"].values()
    )


def test_generated_report_proves_contracts_and_records_repairs() -> None:
    report = build_substrate_gap_audit(_repo_root())
    assert report["schema"] == REPORT_SCHEMA
    assert report["task_id"] == TASK_ID
    assert report["goal_id"] == "OUL-G010"
    assert report["program_id"] == PROGRAM_ID
    assert report["producer"] == PRODUCER
    assert report["network_required"] is False
    assert report["authorizing_for_publication"] is False
    assert acceptance_projection(report) == expected_acceptance()

    contract_ids = [item["contract_id"] for item in report["reusable_contracts"]]
    repair_ids = [item["area_id"] for item in report["required_repairs"]]
    assert contract_ids == list(REUSABLE_CONTRACT_IDS)
    assert repair_ids == list(REPAIR_AREA_IDS)
    assert all(item["reusable"] is True for item in report["reusable_contracts"])
    assert all(item["required"] is True for item in report["required_repairs"])
    assert all(item["blocking"] is True for item in report["required_repairs"])
    assert list(report["repair_areas"]) == list(REPAIR_AREA_IDS)

    for area_id in REPAIR_AREA_IDS:
        area = report["repair_areas"][area_id]
        assert area["required_repairs"]
        assert area["evidence"]
        assert area["owner_tasks"]


def test_repair_areas_name_the_acceptance_gaps() -> None:
    report = build_substrate_gap_audit(_repo_root())
    gte = report["repair_areas"]["real_gte_inference"]
    assert "sentence-transformers" in " ".join(gte["required_repairs"])
    assert gte["evidence"][0]["observed"] == "local_deterministic_projection"

    sorting = report["repair_areas"]["external_sorting"]
    assert any("external sort" in step.lower() for step in sorting["required_repairs"])

    bm25 = report["repair_areas"]["bm25_scale"]
    assert any("250,000" in step or "250000" in step for step in bm25["required_repairs"])
    assert bm25["evidence"][0]["observed"] == 250_000

    routes = report["repair_areas"]["hierarchical_routes"]
    assert any("hierarchical" in step.lower() for step in routes["required_repairs"])

    locators = report["repair_areas"]["vector_entry_locators"]
    assert any("entry_cid" in step for step in locators["required_repairs"])

    tokenizer = report["repair_areas"]["tokenizer_parity"]
    assert any("build and query" in step.lower() or "legal tokenizer" in step.lower()
               for step in tokenizer["required_repairs"])
    assert report["tokenizer"]["remote_query_uses_shared_tokenizer"] is True

    neighbors = report["repair_areas"]["postings_driven_neighbors"]
    assert any("postings" in step.lower() for step in neighbors["required_repairs"])
    assert neighbors["evidence"][0]["observed"] is True

    provenance = report["repair_areas"]["neutral_lcr_provenance"]
    joined = " ".join(provenance["required_repairs"]).lower()
    assert "source document" in joined
    assert "program-neutral" in joined or "neutral" in joined


def test_check_generated_report_passes() -> None:
    report = build_substrate_gap_audit(_repo_root())
    result = check_substrate_gap_audit(report)
    assert result["ok"] is True
    assert result["mismatches"] == []
    assert result["repair_areas"] == list(REPAIR_AREA_IDS)
    assert result["reusable_contracts"] == list(REUSABLE_CONTRACT_IDS)


def test_validate_detects_missing_repair_area() -> None:
    report = build_substrate_gap_audit(_repo_root())
    report["required_repairs"] = [
        item for item in report["required_repairs"] if item["area_id"] != "tokenizer_parity"
    ]
    del report["repair_areas"]["tokenizer_parity"]
    report["acceptance"]["required_repair_areas"] = [
        item for item in report["acceptance"]["required_repair_areas"] if item != "tokenizer_parity"
    ]
    _reseal(report)
    mismatches = validate_substrate_gap_audit(report)
    assert mismatches
    with pytest.raises(SubstrateAuditError, match="substrate gap audit check failed"):
        check_substrate_gap_audit(report)


def test_validate_detects_digest_tampering() -> None:
    report = build_substrate_gap_audit(_repo_root())
    report["audit_digest_sha256"] = "0" * 64
    mismatches = validate_substrate_gap_audit(report)
    assert any("audit_digest_sha256" in item for item in mismatches)


def test_validate_detects_unproven_reusable_contract() -> None:
    report = build_substrate_gap_audit(_repo_root())
    report["reusable_contracts"][0]["reusable"] = False
    report["acceptance"]["reusable_contracts_proven"] = False
    _reseal(report)
    mismatches = validate_substrate_gap_audit(report)
    assert any("reusable" in item for item in mismatches)


def test_committed_report_matches_live_builder() -> None:
    path = default_report_path(_repo_root())
    assert path.is_file(), f"frozen report missing: {path}"
    committed = load_substrate_gap_audit(path)
    generated = build_substrate_gap_audit(_repo_root())
    assert encode_audit_report(committed) == encode_audit_report(generated)
    check_committed_audit(path, repo_root=_repo_root())
    assert acceptance_projection(committed) == expected_acceptance()
    assert committed["schema"] == REPORT_SCHEMA
    assert committed["task_id"] == TASK_ID


def test_write_and_reload_round_trip(tmp_path: Path) -> None:
    report = build_substrate_gap_audit(_repo_root())
    out = tmp_path / "substrate_gap_audit.json"
    write_substrate_gap_audit(report, out)
    reloaded = load_substrate_gap_audit(out)
    assert acceptance_projection(reloaded) == expected_acceptance()
    check_substrate_gap_audit(reloaded)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed["corpus_scale"]["seed_row_count"] == SEED_ROW_COUNT


def test_main_check_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--check"])
    captured = capsys.readouterr()
    assert code == 0
    assert "PASSED" in captured.out
    assert "ok=True" in captured.out
    assert "real_gte_inference" in captured.out
    assert "neutral_lcr_provenance" in captured.out
    assert PINNED_GTE_REVISION not in captured.err


def test_main_without_check_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    captured = capsys.readouterr()
    assert code == 2
    assert "--check is required" in captured.err


def test_main_write_and_check_tmp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "substrate_gap_audit.json"
    write_code = main(["--write", "--report", str(out)])
    assert write_code == 0
    assert out.is_file()
    check_code = main(["--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert check_code == 0
    assert "PASSED" in captured.out


def test_main_detects_tampered_on_disk_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tampered.json"
    report = build_substrate_gap_audit(_repo_root())
    tampered = copy.deepcopy(report)
    tampered["corpus_scale"]["seed_row_count"] = 1
    _reseal(tampered)
    write_substrate_gap_audit(tampered, out)
    code = main(["--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert code == 1
    assert "FAILED" in captured.err


def test_report_is_secret_free_and_offline() -> None:
    report = build_substrate_gap_audit(_repo_root())
    encoded = encode_audit_report(report).decode("utf-8")
    assert report["network_required"] is False
    for banned in (
        "HF_TOKEN",
        "Authorization:",
        "Bearer ",
        "sk-ant-",
        "file:///home/",
        "/home/barberb",
    ):
        assert banned not in encoded
