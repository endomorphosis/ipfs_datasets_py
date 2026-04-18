from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.bluebook_linker_fuzz_harness import (
    collect_seeded_bluebook_fuzz_candidates,
    parse_bluebook_fuzz_candidates,
    run_bluebook_linker_fuzz_harness,
    _fallback_bluebook_fuzz_candidates,
)
from ipfs_datasets_py.processors.legal_data.bluebook_citation_linker import BluebookCitationResolver


def test_parse_bluebook_fuzz_candidates_accepts_fenced_json_payload() -> None:
    raw = """
```json
[
  {
    "citation_text": "42 U.S.C. § 1983",
    "context_text": "The complaint cites 42 U.S.C. § 1983 as authority.",
    "state_code": "",
    "corpus_key_hint": "us_code",
    "citation_type_hint": "usc",
    "expected_valid": true,
    "notes": "federal civil rights"
  }
]
```
"""

    candidates = parse_bluebook_fuzz_candidates(raw)

    assert len(candidates) == 1
    assert candidates[0].citation_text == "42 U.S.C. § 1983"
    assert candidates[0].corpus_key_hint == "us_code"
    assert candidates[0].citation_type_hint == "usc"
    assert candidates[0].expected_valid is True


def test_parse_bluebook_fuzz_candidates_accepts_prior_run_candidates_payload() -> None:
    raw = json.dumps(
        {
            "summary": {"sample_count_executed": 1},
            "candidates": [
                {
                    "citation_text": "Minn. Stat. § 518.17",
                    "context_text": "The motion relies on Minn. Stat. § 518.17.",
                    "state_code": "MN",
                    "corpus_key_hint": "state_laws",
                    "citation_type_hint": "state_statute",
                    "expected_valid": True,
                }
            ],
        }
    )

    candidates = parse_bluebook_fuzz_candidates(raw)

    assert len(candidates) == 1
    assert candidates[0].citation_text == "Minn. Stat. § 518.17"
    assert candidates[0].state_code == "MN"


def test_parse_bluebook_fuzz_candidates_accepts_plain_citation_list() -> None:
    raw = json.dumps(["Minn. Stat. § 518.17", "ORS 801.545"])

    candidates = parse_bluebook_fuzz_candidates(raw)

    assert [item.citation_text for item in candidates] == ["Minn. Stat. § 518.17", "ORS 801.545"]
    assert candidates[0].render_document_text() == "The filing cites Minn. Stat. § 518.17 as supporting authority."


def test_fallback_bluebook_fuzz_candidates_cover_scraper_families() -> None:
    candidates = _fallback_bluebook_fuzz_candidates(sample_count=6)

    assert [item.corpus_key_hint for item in candidates] == [
        "state_laws",
        "caselaw_access_project",
        "cfr",
        "federal_register",
        "state_admin_rules",
        "state_court_rules",
    ]
    assert candidates[0].state_code == "MN"
    assert candidates[-1].citation_text == "Minn. R. Civ. P. 56.03"


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_labels_plain_list_failures_from_recovery(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["Minn. Stat. § 518.17"])

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. Stat. § 518.17",
                    "normalized_citation": "Minn. Stat. § 518.17",
                    "metadata": {"recovery_corpus_key": "state_laws"},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": "state_laws",
            "manifest_path": str(tmp_path / "recovery_manifest.json"),
            "scraper_patch": {
                "host": "www.revisor.mn.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
                "patch_path": str(tmp_path / "recovery.patch"),
            },
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["coverage_by_corpus"]["actionable_corpora"] == ["state_laws"]
    assert run.summary["failure_patch_clusters"][0]["corpus_key"] == "state_laws"
    backlog_cluster = run.summary["failure_patch_backlog"]["clusters"][0]
    assert backlog_cluster["sample_contexts"] == [
        {
            "citation_text": "Minn. Stat. § 518.17",
            "context_text": "",
            "state_code": None,
            "notes": None,
        }
    ]


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_falls_back_when_generation_is_not_json(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return "I can help draft citations, but here is some prose instead."

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 1,
            "unmatched_citation_count": 0,
            "citations": [{"citation_text": text, "matched": True}],
            "unresolved_citations": [],
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=2,
        corpus_keys=["state_laws"],
        state_codes=["MN"],
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["used_fallback_candidates"] is True
    assert "Unable to parse JSON payload" in run.summary["generation_parse_error"]
    assert run.raw_generation == "I can help draft citations, but here is some prose instead."
    assert [candidate.corpus_key_hint for candidate in run.candidates] == ["state_laws", "state_laws"]
    assert {candidate.state_code for candidate in run.candidates} == {"MN"}
    assert run.summary["matched_attempt_count"] == 2


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_recovers_expected_valid_extraction_misses(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "citation_text": "Okla. Stat. tit. 21 § 644",
                    "context_text": "The filing cites Okla. Stat. tit. 21 § 644.",
                    "state_code": "OK",
                    "corpus_key_hint": "state_laws",
                    "expected_valid": True,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 0,
            "matched_citation_count": 0,
            "unmatched_citation_count": 0,
            "citations": [],
            "unresolved_citations": [],
        }

    async def fake_recovery(**kwargs):
        assert kwargs["citation_text"] == "Okla. Stat. tit. 21 § 644"
        assert kwargs["corpus_key"] == "state_laws"
        assert kwargs["state_code"] == "OK"
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": kwargs["corpus_key"],
            "manifest_path": str(tmp_path / "recovery_manifest.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["unmatched_citation_count"] == 1
    assert run.summary["recovery_count"] == 1
    assert run.attempts[0].resolution["unresolved_citations"][0]["metadata"]["recovery_reason"] == (
        "expected_valid_candidate_not_extracted"
    )


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_records_prefer_hf_corpora(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["42 U.S.C. § 1983"])

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 1,
            "unmatched_citation_count": 0,
            "citations": [{"citation_text": "42 U.S.C. § 1983", "matched": True}],
            "unresolved_citations": [],
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        prefer_hf_corpora=True,
        primary_corpora_only=True,
        exact_state_partitions_only=True,
        materialize_hf_corpora=True,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["prefer_hf_corpora"] is True
    assert run.summary["primary_corpora_only"] is True
    assert run.summary["exact_state_partitions_only"] is True
    assert run.summary["materialize_hf_corpora"] is True
    assert run.summary["matched_attempt_count"] == 1


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_can_hydrate_merge_from_hf(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["Minn. Stat. § 518.17"])

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. Stat. § 518.17",
                    "normalized_citation": "Minn. Stat. § 518.17",
                    "metadata": {"recovery_corpus_key": "state_laws"},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "manifest_path": str(tmp_path / "recovery_manifest.json"),
        }

    def fake_merge(path: str, **kwargs):
        assert path == str(tmp_path / "recovery_manifest.json")
        assert kwargs == {
            "hydrate_from_hf": True,
            "hf_token": "test-token",
            "publish_merged_to_hf": False,
        }
        return {
            "status": "success",
            "existing_rows_source": "huggingface_dataset_parquet",
            "target_local_parquet_path": str(tmp_path / "STATE-MN.parquet"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_manifest_func=fake_merge,
        merge_recovered_rows=True,
        hydrate_merge_from_hf=True,
        hf_token="test-token",
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["hydrate_merge_from_hf"] is True
    assert run.summary["merged_recovery_count"] == 1
    assert run.attempts[0].merge_reports[0]["existing_rows_source"] == "huggingface_dataset_parquet"


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_can_publish_merged_parquet_to_hf(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["Minn. Stat. § 518.17"])

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. Stat. § 518.17",
                    "normalized_citation": "Minn. Stat. § 518.17",
                    "metadata": {"recovery_corpus_key": "state_laws"},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "manifest_path": str(tmp_path / "recovery_manifest.json"),
        }

    def fake_merge(path: str, **kwargs):
        assert kwargs == {
            "hydrate_from_hf": True,
            "hf_token": "test-token",
            "publish_merged_to_hf": True,
        }
        return {
            "status": "success",
            "upload_ready": True,
            "hf_dataset_id": "justicedao/ipfs_state_laws",
            "resolved_hf_parquet_path": "state_laws_parquet_cid/STATE-MN.parquet",
            "published_merged_to_hf": True,
            "publish_report": {
                "status": "success",
                "repo_id": "justicedao/ipfs_state_laws",
                "path_in_repo": "state_laws_parquet_cid/STATE-MN.parquet",
                "upload_commit": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/abc123",
            },
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_manifest_func=fake_merge,
        merge_recovered_rows=True,
        publish_merged_parquet_to_hf=True,
        hf_token="test-token",
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["hydrate_merge_from_hf"] is False
    assert run.summary["publish_merged_parquet_to_hf"] is True
    assert run.summary["merged_recovery_count"] == 1
    assert run.attempts[0].merge_reports[0]["published_merged_to_hf"] is True
    assert run.summary["recovery_merge"]["upload_ready_count"] == 1
    assert run.summary["recovery_merge"]["published_merged_count"] == 1
    assert run.summary["recovery_merge"]["publish_failure_count"] == 0
    assert run.summary["recovery_merge"]["hf_dataset_counts"] == {"justicedao/ipfs_state_laws": 1}
    assert run.summary["recovery_merge"]["resolved_hf_parquet_paths"] == [
        "state_laws_parquet_cid/STATE-MN.parquet"
    ]
    assert run.summary["recovery_merge"]["sample_upload_urls"] == [
        "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/abc123"
    ]
    matrix = run.summary["scraper_family_matrix"]
    assert matrix["published_hf_corpora"] == ["state_laws"]
    assert matrix["unpublished_hf_corpora"] == []
    matrix_row = {row["corpus_key"]: row for row in matrix["rows"]}["state_laws"]
    assert matrix_row["hf_upload_ready_count"] == 1
    assert matrix_row["hf_publish_success_count"] == 1
    assert matrix_row["hf_dataset_ids"] == ["justicedao/ipfs_state_laws"]
    assert matrix_row["hf_parquet_paths"] == ["state_laws_parquet_cid/STATE-MN.parquet"]
    assert matrix_row["hf_upload_urls"] == [
        "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/abc123"
    ]


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_classifies_hf_publish_failures(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["Minn. Stat. § 518.17"])

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. Stat. § 518.17",
                    "normalized_citation": "Minn. Stat. § 518.17",
                    "metadata": {"recovery_corpus_key": "state_laws"},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "manifest_path": str(tmp_path / "recovery_manifest.json"),
            "scraper_patch": {
                "host": "www.revisor.mn.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            },
        }

    def fake_merge(path: str, **kwargs):
        return {
            "status": "error",
            "error": "Unable to publish merged parquet to Hugging Face: 403 Forbidden",
            "upload_ready": True,
            "published_merged_to_hf": False,
            "hf_dataset_id": "justicedao/ipfs_state_laws",
            "resolved_hf_parquet_path": "state_laws_parquet_cid/STATE-MN.parquet",
            "target_local_parquet_path": str(tmp_path / "STATE-MN.parquet"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_manifest_func=fake_merge,
        merge_recovered_rows=True,
        publish_merged_parquet_to_hf=True,
        hf_token="test-token",
        corpus_keys=["state_laws"],
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["merged_recovery_count"] == 0
    assert run.summary["recovery_merge"]["upload_ready_count"] == 1
    assert run.summary["recovery_merge"]["published_merged_count"] == 0
    assert run.summary["recovery_merge"]["publish_failure_count"] == 1
    assert run.summary["recovery_merge"]["publish_error_counts"] == {
        "Unable to publish merged parquet to Hugging Face: 403 Forbidden": 1
    }
    assert run.summary["scraper_family_matrix"]["unpublished_hf_corpora"] == ["state_laws"]
    row = run.summary["scraper_family_matrix"]["rows"][0]
    assert row["hf_upload_ready_count"] == 1
    assert row["hf_publish_failure_count"] == 1
    assert row["hf_publish_success_count"] == 0
    assert row["hf_dataset_ids"] == ["justicedao/ipfs_state_laws"]
    assert row["hf_parquet_paths"] == ["state_laws_parquet_cid/STATE-MN.parquet"]
    assert run.summary["failure_patch_backlog"]["scraper_family_matrix"]["unpublished_hf_corpora"] == [
        "state_laws"
    ]


def test_collect_seeded_bluebook_fuzz_candidates_uses_grounded_rows() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key == "us_code":
                return ["memory://us_code"]
            if corpus_key == "state_laws":
                return ["memory://state_laws"]
            return []

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            if source_ref == "memory://us_code":
                return [
                    {
                        "title": "42",
                        "section": "1983",
                        "heading": "Civil action for deprivation of rights",
                        "identifier": "42 U.S.C. § 1983",
                    }
                ]
            if source_ref == "memory://state_laws":
                return [
                    {
                        "state_code": "MN",
                        "official_cite": "Minn. Stat. § 518.17",
                        "section_name": "Best interests of the child",
                    }
                ]
            return []

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["us_code", "state_laws"],
        state_codes=["MN"],
        examples_per_corpus=1,
    )

    by_corpus = {item.corpus_key_hint: item for item in seeds}
    assert by_corpus["us_code"].citation_text == "42 U.S.C. § 1983"
    assert by_corpus["us_code"].citation_type_hint == "usc"
    assert by_corpus["state_laws"].citation_text == "Minn. Stat. § 518.17"
    assert by_corpus["state_laws"].state_code == "MN"
    assert by_corpus["state_laws"].citation_type_hint == "state_statute"


def test_collect_seeded_bluebook_fuzz_candidates_uses_federal_register_citation_fields() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key == "federal_register":
                return ["memory://federal_register"]
            return []

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "identifier": "X94-90401",
                    "name": "CFR PARTS AFFECTED IN THIS ISSUE",
                },
                {
                    "identifier": "FR-2024-12345",
                    "citation_text": "89 FR 12345",
                    "normalized_citation": "89 FR 12345",
                    "name": "Dataset-backed Federal Register row",
                },
                {
                    "identifier": "CFR-40-122-41",
                    "citation_text": "40 C.F.R. § 122.41",
                    "normalized_citation": "40 C.F.R. § 122.41",
                    "name": "Dataset-backed CFR row recovered into federal register corpus",
                },
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["federal_register"],
        examples_per_corpus=2,
    )

    by_text = {seed.citation_text: seed for seed in seeds}
    assert by_text["89 FR 12345"].citation_type_hint == "federal_register"
    assert by_text["89 FR 12345"].corpus_key_hint == "federal_register"
    assert by_text["40 C.F.R. § 122.41"].citation_type_hint == "cfr"
    assert by_text["40 C.F.R. § 122.41"].corpus_key_hint == "federal_register"


def test_collect_seeded_bluebook_fuzz_candidates_finds_sparse_federal_register_rows(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    pytest.importorskip("duckdb")

    source_path = tmp_path / "federal_register.parquet"
    table = pa.table(
        {
            "identifier": ["X94-90401", None],
            "name": ["CFR PARTS AFFECTED IN THIS ISSUE", "Dataset-backed Federal Register row"],
            "citation_text": [None, "89 FR 12345"],
            "normalized_citation": [None, "89 FR 12345"],
        }
    )
    pq.write_table(table, source_path)

    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key == "federal_register":
                return [str(source_path)]
            return []

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "identifier": "X94-90401",
                    "name": "CFR PARTS AFFECTED IN THIS ISSUE",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["federal_register"],
        examples_per_corpus=1,
    )

    assert len(seeds) == 1
    assert seeds[0].citation_text == "89 FR 12345"
    assert seeds[0].citation_type_hint == "federal_register"


@pytest.mark.anyio
async def test_seed_only_fuzzer_resolves_caselaw_from_seeded_source_row_cache(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    pytest.importorskip("duckdb")

    source_path = tmp_path / "cap.parquet"
    pq.write_table(
        pa.table(
            {
                "id": ["cap-38-mich-90"],
                "citations": ["38 Mich. 90"],
                "reporter": ["Mich."],
                "first_page": ["90"],
                "name": ["John R. Long v. Robert P. Sinclair"],
                "text": ["The opinion is reported at 38 Mich. 90."],
            }
        ),
        source_path,
    )
    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        primary_corpora_only=True,
        parquet_file_overrides={"caselaw_access_project": [str(source_path)]},
    )

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        resolver=resolver,
        corpus_keys=["caselaw_access_project"],
        seed_from_corpora=True,
        seed_only=True,
        seed_examples_per_corpus=1,
        enable_recovery=False,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["sample_count_executed"] == 1
    assert run.summary["matched_attempt_count"] == 1
    assert run.summary["unmatched_citation_count"] == 0
    citation = run.attempts[0].resolution["citations"][0]
    assert citation["matched_field"] == "citations"
    assert citation["metadata"]["resolution_method"] == "seeded_source_row_cache"


def test_collect_seeded_bluebook_fuzz_candidates_balances_across_states_and_sources() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_laws":
                return []
            return [f"memory://{state_code}/part-a", f"memory://{state_code}/part-b"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            state_code = "MN" if "/MN/" in source_ref else "OR"
            prefix = "A" if source_ref.endswith("part-a") else "B"
            return [
                {
                    "state_code": state_code,
                    "official_cite": f"{state_code}-{prefix}-{index}",
                    "section_name": f"{state_code} section {index}",
                }
                for index in range(1, 5)
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_laws"],
        state_codes=["MN", "OR"],
        examples_per_corpus=4,
        sample_count=4,
        max_examples_per_state=2,
        max_examples_per_source=1,
        shuffle_seed=7,
    )

    assert len(seeds) == 4
    state_counts = {}
    note_fragments = []
    for seed in seeds:
        state_counts[seed.state_code] = state_counts.get(seed.state_code, 0) + 1
        note_fragments.append(seed.notes or "")
    assert state_counts == {"MN": 2, "OR": 2}
    assert any("source_ref=memory://MN/part-a" in note for note in note_fragments)
    assert any("source_ref=memory://MN/part-b" in note for note in note_fragments)
    assert any("source_ref=memory://OR/part-a" in note for note in note_fragments)
    assert any("source_ref=memory://OR/part-b" in note for note in note_fragments)


def test_collect_seeded_bluebook_fuzz_candidates_does_not_state_cap_non_state_corpora() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key == "us_code":
                return ["memory://us_code"]
            return []

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "title": "42",
                    "section": str(1980 + index),
                    "heading": f"Section {index}",
                }
                for index in range(10)
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["us_code"],
        examples_per_corpus=8,
        sample_count=8,
        max_examples_per_state=2,
        max_examples_per_source=8,
    )

    assert len(seeds) == 8
    assert {seed.corpus_key_hint for seed in seeds} == {"us_code"}


def test_collect_seeded_bluebook_fuzz_candidates_filters_mixed_state_rows_to_requested_state() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_laws":
                return []
            return ["memory://combined-state-shard"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {"state_code": "OR", "official_cite": "ORS 127.652", "section_name": "Oregon row"},
                {"state_code": "MN", "official_cite": "Minn. Stat. § 518.17", "section_name": "Minnesota row"},
                {"state_code": "AK", "official_cite": "Alaska Stat. § 12.55.125", "section_name": "Alaska row"},
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_laws"],
        state_codes=["MN", "AK"],
        examples_per_corpus=4,
        sample_count=4,
        max_examples_per_state=2,
        max_examples_per_source=2,
    )

    assert {seed.state_code for seed in seeds} == {"MN", "AK"}
    assert all(seed.citation_text != "ORS 127.652" for seed in seeds)


def test_collect_seeded_bluebook_fuzz_candidates_keeps_structured_and_source_backed_state_law_rows() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_laws":
                return []
            return ["memory://state-law-mixed"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "MN",
                    "name": "Chief Clerk",
                    "source_id": "urn:state:mn:statute:Minnesota Statutes § Section-15",
                    "source_url": "https://example.test/chief-clerk",
                },
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Stat. § 518.17",
                    "section_name": "Best interests",
                    "source_url": "https://example.test/518.17",
                },
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_laws"],
        state_codes=["MN"],
        examples_per_corpus=2,
        sample_count=2,
    )

    assert len(seeds) == 2
    assert {seed.citation_text for seed in seeds} == {"Minn. Stat. § 15", "Minn. Stat. § 518.17"}


def test_collect_seeded_bluebook_fuzz_candidates_synthesizes_from_state_source_id_rows() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_laws":
                return []
            return ["memory://mn-state-laws"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "MN",
                    "name": "Chief Clerk",
                    "source_id": "urn:state:mn:statute:Minnesota Statutes § Section-15",
                    "text": "Section Section-15: Chief Clerk",
                    "source_url": "https://example.test/chief-clerk",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_laws"],
        state_codes=["MN"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert len(seeds) == 1
    assert seeds[0].citation_text == "Minn. Stat. § 15"
    assert seeds[0].state_code == "MN"
    assert seeds[0].citation_type_hint == "state_statute"


def test_collect_seeded_bluebook_fuzz_candidates_synthesizes_admin_rule_sections() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_admin_rules":
                return []
            return ["memory://or-admin-rules"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "OR",
                    "identifier": "OR-ADMIN-cb01eb1cd186",
                    "source_id": "urn:state-admin:OR:OR-ADMIN-cb01eb1cd186:c1354a8d203848ec",
                    "name": "Career Education",
                    "text": "581-022-2055 Career Education Each school district shall implement plans.",
                    "source_url": "https://secure.sos.state.or.us/oard/viewSingleRule.action?ruleVrsnRsn=314719",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_admin_rules"],
        state_codes=["OR"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert len(seeds) == 1
    assert seeds[0].citation_text == "Or. Admin. Code § 581-022-2055"
    assert seeds[0].state_code == "OR"
    assert seeds[0].corpus_key_hint == "state_admin_rules"


def test_collect_seeded_bluebook_fuzz_candidates_synthesizes_admin_rule_sections_from_rule_urls() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_admin_rules":
                return []
            return ["memory://ri-admin-rules"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "RI",
                    "identifier": "RI-AGENTIC-A5",
                    "source_id": "urn:state-admin:RI:RI-AGENTIC-A5:97382a844f072226",
                    "name": "Rhode Island - Rhode Island Administrative Rules (Agentic Discovery) - A5",
                    "text": "An Official Rhode Island State Website. Contact 401-222-0000 for help.",
                    "source_url": "https://rules.sos.ri.gov/regulations/part/510-00-00-19",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_admin_rules"],
        state_codes=["RI"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert len(seeds) == 1
    assert seeds[0].citation_text == "R.I. Admin. Code § 510-00-00-19"
    assert seeds[0].state_code == "RI"
    assert seeds[0].corpus_key_hint == "state_admin_rules"


def test_collect_seeded_bluebook_fuzz_candidates_skips_admin_homepage_phone_numbers() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_admin_rules":
                return []
            return ["memory://mn-admin-homepage"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "MN",
                    "identifier": "MN-ADMIN-homepage",
                    "source_id": "urn:state-admin:MN:MN-ADMIN-homepage",
                    "name": "MN Revisor's Office",
                    "text": "Administrative rules portal. Contact 800-627-3529 for assistance.",
                    "source_url": "https://www.revisor.mn.gov",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_admin_rules"],
        state_codes=["MN"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert seeds == []


def test_collect_seeded_bluebook_fuzz_candidates_skips_synthetic_court_rule_identifiers() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_court_rules":
                return []
            return ["memory://or-court-rules"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "OR",
                    "identifier": "doc-2",
                    "source_id": "urn:state:or:statute:Clatsop County Local Rule doc-2",
                    "name": "Clatsop Rules",
                    "text": "Clatsop County Local Rule doc-2: Clatsop Rules",
                    "source_url": "https://www.courts.oregon.gov/courts/clatsop/go/Pages/rules.aspx",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_court_rules"],
        state_codes=["OR"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert seeds == []


def test_collect_seeded_bluebook_fuzz_candidates_synthesizes_state_court_rule_sections() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_court_rules":
                return []
            return ["memory://mn-court-rules"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "MN",
                    "name": "Summary Judgment",
                    "source_id": "urn:state:mn:court-rule:Rule 56.03",
                    "text": "Rule 56.03 Summary Judgment A party may move for summary judgment.",
                    "source_url": "https://www.revisor.mn.gov/court_rules/cp/id/56/",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_court_rules"],
        state_codes=["MN"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert len(seeds) == 1
    assert seeds[0].citation_text == "Minn. Court Rules § 56.03"
    assert seeds[0].state_code == "MN"
    assert seeds[0].corpus_key_hint == "state_court_rules"


def test_collect_seeded_bluebook_fuzz_candidates_prefers_court_rule_names_over_internal_sections() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_court_rules":
                return []
            return ["memory://or-court-rules"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "OR",
                    "identifier": "Section-1",
                    "source_id": "urn:state:or:court-rule:Section-1",
                    "name": "UTCR 8.120",
                    "text": "Section Section-1: UTCR 8.120",
                    "source_url": "https://www.courts.oregon.gov/rules/utcr",
                },
                {
                    "state_code": "OR",
                    "identifier": "Section-2",
                    "source_id": "urn:state:or:court-rule:Section-2",
                    "name": "\u200bLocal Rule 8.013",
                    "text": "Section Section-2: Local Rule 8.013",
                    "source_url": "https://www.courts.oregon.gov/rules/local",
                },
                {
                    "state_code": "OR",
                    "identifier": "Section-3",
                    "source_id": "urn:state:or:court-rule:Section-3",
                    "name": "UTCR 21.070(5)",
                    "text": "Section Section-3: UTCR 21.070(5)",
                    "source_url": "https://www.courts.oregon.gov/rules/utcr",
                },
                {
                    "state_code": "OR",
                    "identifier": "2025-018",
                    "source_id": "urn:state:or:court-rule:2025-018",
                    "name": "Chief Justice Order 2025-018",
                    "text": "Chief Justice Order 2025-018 adopts temporary local procedures.",
                    "source_url": "https://www.courts.oregon.gov/courts/lane/resources/Pages/Chief-Justice-Order-2025-018.aspx",
                },
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_court_rules"],
        state_codes=["OR"],
        examples_per_corpus=4,
        sample_count=4,
        shuffle_seed=0,
    )

    assert {seed.citation_text for seed in seeds} == {
        "Or. Court Rules § 8.120",
        "Or. Court Rules § 8.013",
        "Or. Court Rules § 21.070(5)",
        "Or. Court Rules § 2025-018",
    }
    assert {seed.state_code for seed in seeds} == {"OR"}
    assert {seed.corpus_key_hint for seed in seeds} == {"state_court_rules"}


def test_collect_seeded_bluebook_fuzz_candidates_does_not_seed_admin_from_implemented_statutes() -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key != "state_admin_rules":
                return []
            return ["memory://or-admin-implemented-statutes"]

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {
                    "state_code": "OR",
                    "identifier": "OR-ADMIN-cb01eb1cd186",
                    "name": "Career Education",
                    "text": "Statutory/Other Authority: ORS 326.051 Statutes/Other Implemented: ORS 329.275",
                    "source_url": "https://secure.sos.state.or.us/oard/viewSingleRule.action?ruleVrsnRsn=314719",
                }
            ]

    seeds = collect_seeded_bluebook_fuzz_candidates(
        resolver=_FakeResolver(),
        corpus_keys=["state_admin_rules"],
        state_codes=["OR"],
        examples_per_corpus=1,
        sample_count=1,
    )

    assert seeds == []


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_recovers_and_merges_unmatched(tmp_path: Path) -> None:
    raw_generation = json.dumps(
        [
            {
                "citation_text": "Minn. Stat. § 999.999",
                "context_text": "The motion relies on Minn. Stat. § 999.999.",
                "state_code": "MN",
                "corpus_key_hint": "state_laws",
                "citation_type_hint": "state_statute",
                "expected_valid": False,
                "notes": "synthetic miss to force recovery",
            }
        ]
    )

    def fake_generate(*args, **kwargs) -> str:
        return raw_generation

    def fake_resolve_document(text: str, **kwargs):
        assert "Minn. Stat. § 999.999" in text
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. Stat. § 999.999",
                    "normalized_citation": "Minn. Stat. § 999.999",
                    "corpus_key": None,
                    "metadata": {
                        "state_code": "MN",
                        "recovery_corpus_key": "state_laws",
                        "candidate_corpora": ["state_laws"],
                    },
                }
            ],
        }

    manifest_path = tmp_path / "recovery_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    candidate_metadata_path = tmp_path / "candidate_file.json"
    candidate_metadata_path.write_text(
        json.dumps(
            {
                "content_type": "text/html",
                "extraction_recipe": {"blocked_signals_detected": False},
                "candidate_validation": {
                    "citation_text": "Minn. Stat. § 999.999",
                    "confirmed": False,
                    "confidence": 0.0,
                    "matched_fragments": ["999.999"],
                    "no_result_detected": True,
                },
            }
        ),
        encoding="utf-8",
    )

    async def fake_recovery(**kwargs):
        assert kwargs["corpus_key"] == "state_laws"
        assert kwargs["state_code"] == "MN"
        return {
            "status": "tracked_and_published",
            "hf_dataset_id": "justicedao/ipfs_state_laws",
            "manifest_path": str(manifest_path),
            "citation_text": kwargs["citation_text"],
            "publish_report": {
                "repo_id": "justicedao/ipfs_state_laws",
                "upload_commit": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/tree/main/source_recovery/test",
            },
            "search_backend_status": {
                "common_crawl_domain_errors": {"www.revisor.mn.gov": "common_crawl_domain_timeout"}
            },
            "candidate_files": [
                {
                    "url": "https://www.revisor.mn.gov/statutes/cite/999.999",
                    "fetch_success": True,
                    "metadata_path": str(candidate_metadata_path),
                    "notes": "citation_anchor_not_confirmed;no_result_marker_detected",
                }
            ],
            "scraper_patch": {
                "patch_path": str(tmp_path / "recovery.patch"),
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
                "host": "www.revisor.mn.gov",
            },
        }

    def fake_merge(path: str):
        assert path == str(manifest_path)
        return {
            "status": "success",
            "target_local_parquet_path": str(tmp_path / "STATE-MN.parquet"),
            "merge_report_path": str(tmp_path / "canonical_merge_report.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        output_dir=tmp_path / "artifacts",
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_manifest_func=fake_merge,
        merge_recovered_rows=True,
    )

    assert run.summary["sample_count_executed"] == 1
    assert run.summary["matched_attempt_count"] == 0
    assert run.summary["recovery_count"] == 1
    assert run.summary["merged_recovery_count"] == 1
    assert run.attempts[0].recoveries[0]["status"] == "tracked_and_published"
    assert run.summary["recovery_publication"]["published_count"] == 1
    assert run.summary["recovery_publication"]["repo_counts"] == {"justicedao/ipfs_state_laws": 1}
    assert run.summary["recovery_publication"]["patch_path_count"] == 1
    assert run.summary["recovery_publication"]["manifest_path_count"] == 1
    assert run.summary["recovery_merge"]["status_counts"] == {"success": 1}
    assert run.summary["recovery_merge"]["success_count"] == 1
    assert run.summary["recovery_merge"]["failure_count"] == 0
    assert run.summary["recovery_merge"]["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    assert run.summary["recovery_merge"]["merge_report_paths"] == [str(tmp_path / "canonical_merge_report.json")]
    scraper_target = run.summary["scraper_coverage"]["targets"][0]
    assert scraper_target["target_file"].endswith("state_laws_scraper.py")
    assert scraper_target["merge_status_counts"] == {"success": 1}
    assert scraper_target["merge_success_count"] == 1
    assert scraper_target["merge_failure_count"] == 0
    assert scraper_target["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    assert run.summary["recovery_artifact_quality"]["candidate_file_count"] == 1
    assert run.summary["recovery_artifact_quality"]["fetch_success_count"] == 1
    assert run.summary["recovery_artifact_quality"]["citation_unconfirmed_count"] == 1
    assert run.summary["recovery_artifact_quality"]["no_result_marker_count"] == 1
    assert run.summary["recovery_artifact_quality"]["notes_counts"] == {
        "citation_anchor_not_confirmed": 1,
        "no_result_marker_detected": 1,
    }
    assert run.summary["recovery_artifact_quality"]["common_crawl_domain_error_counts"] == {
        "www.revisor.mn.gov:common_crawl_domain_timeout": 1
    }
    assert run.summary["failure_patch_clusters"][0]["patch_paths"] == [str(tmp_path / "recovery.patch")]
    assert run.attempts[0].merge_reports[0]["status"] == "success"
    assert run.output_path is not None
    assert Path(run.output_path).exists()
    persisted = json.loads(Path(run.output_path).read_text(encoding="utf-8"))
    assert persisted["summary"]["failure_patch_backlog_path"]
    assert persisted["summary"]["malformed_repairs_path"]
    assert persisted["summary"]["recovery_merge"]["success_count"] == 1
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["recovery_merge"]["success_count"] == 1
    assert backlog["recovery_artifact_quality"]["citation_unconfirmed_count"] == 1
    assert backlog["recovery_merge"]["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    persisted_backlog = json.loads(Path(run.summary["failure_patch_backlog_path"]).read_text(encoding="utf-8"))
    assert persisted_backlog["recovery_merge"]["success_count"] == 1
    assert persisted_backlog["recovery_merge"]["merge_report_paths"] == [str(tmp_path / "canonical_merge_report.json")]
    assert persisted_backlog["recovery_artifact_quality"]["no_result_marker_count"] == 1


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_summarizes_merge_failures(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["Minn. Stat. § 999.999"])

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. Stat. § 999.999",
                    "normalized_citation": "Minn. Stat. § 999.999",
                    "metadata": {"state_code": "MN", "recovery_corpus_key": "state_laws"},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "manifest_path": str(tmp_path / "recovery_manifest.json"),
            "scraper_patch": {
                "patch_path": str(tmp_path / "recovery.patch"),
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
                "host": "www.revisor.mn.gov",
            },
        }

    def fake_merge(path: str):
        return {
            "status": "failed",
            "error": "missing canonical target parquet",
            "target_local_parquet_path": str(tmp_path / "STATE-MN.parquet"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_manifest_func=fake_merge,
        merge_recovered_rows=True,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["merged_recovery_count"] == 0
    assert run.summary["recovery_merge"]["status_counts"] == {"failed": 1}
    assert run.summary["recovery_merge"]["success_count"] == 0
    assert run.summary["recovery_merge"]["failure_count"] == 1
    assert run.summary["recovery_merge"]["error_counts"] == {"missing canonical target parquet": 1}
    assert run.summary["recovery_merge"]["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    scraper_target = run.summary["scraper_coverage"]["targets"][0]
    assert scraper_target["merge_status_counts"] == {"failed": 1}
    assert scraper_target["merge_success_count"] == 0
    assert scraper_target["merge_failure_count"] == 1
    assert scraper_target["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    assert run.summary["failure_patch_backlog"]["recovery_merge"]["failure_count"] == 1
    assert run.summary["failure_patch_backlog"]["recovery_merge"]["error_counts"] == {
        "missing canonical target parquet": 1
    }


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_includes_seed_examples_in_prompt(tmp_path: Path) -> None:
    captured = {}

    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key == "us_code":
                return ["memory://us_code"]
            return []

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [{"title": "42", "section": "1983", "identifier": "42 U.S.C. § 1983"}]

    def fake_generate(prompt: str, **kwargs) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            [
                {
                    "citation_text": "42 U.S.C. § 1983",
                    "context_text": "The complaint cites 42 U.S.C. § 1983 as authority.",
                    "corpus_key_hint": "us_code",
                    "citation_type_hint": "usc",
                    "expected_valid": True,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 1,
            "unmatched_citation_count": 0,
            "citations": [{"matched": True}],
            "unresolved_citations": [],
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        resolver=_FakeResolver(),
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        enable_recovery=False,
        seed_from_corpora=True,
        seed_examples_per_corpus=1,
        corpus_keys=["us_code"],
        output_dir=tmp_path / "artifacts",
    )

    assert "Seed examples JSON" in captured["prompt"]
    assert '"citation_text": "42 U.S.C. \\u00a7 1983"' in captured["prompt"]
    assert run.summary["seeded_example_count"] == 1
    assert run.seeded_examples[0]["citation_text"] == "42 U.S.C. § 1983"


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_seed_only_emits_actionable_coverage_summary(tmp_path: Path) -> None:
    class _FakeResolver:
        def _iter_corpus_sources(self, corpus_key: str, *, state_code: str | None):
            if corpus_key == "us_code":
                return ["memory://us_code"]
            return []

        def _materialize_remote_parquet(self, source_ref: str):
            return source_ref

        def _load_local_parquet_rows(self, source_ref: str):
            return [
                {"title": "42", "section": "1983", "identifier": "42 U.S.C. § 1983"},
                {"title": "18", "section": "242", "identifier": "18 U.S.C. § 242"},
            ]

    def fake_resolve_document(text: str, **kwargs):
        matched = "42 U.S.C. § 1983" in text
        unresolved = [] if matched else [
            {
                "citation_text": "18 U.S.C. § 242",
                "normalized_citation": "18 U.S.C. § 242",
                "metadata": {
                    "recovery_corpus_key": "us_code",
                    "candidate_corpora": ["us_code"],
                },
            }
        ]
        return {
            "citation_count": 1,
            "matched_citation_count": 1 if matched else 0,
            "unmatched_citation_count": 0 if matched else 1,
            "citations": [],
            "unresolved_citations": unresolved,
        }

    async def fake_recovery(**kwargs):
        manifest_path = tmp_path / "recovery.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "manifest_path": str(manifest_path),
            "scraper_patch": {
                "host": "uscode.house.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/us_code_scraper.py",
                "patch_path": str(tmp_path / "patch.diff"),
            },
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=2,
        resolver=_FakeResolver(),
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        seed_from_corpora=True,
        seed_only=True,
        corpus_keys=["us_code"],
        min_actionable_failures=1,
        max_acceptable_failure_rate=0.20,
        output_dir=tmp_path / "artifacts",
    )

    coverage = run.summary["coverage_by_corpus"]
    assert coverage["actionable_corpora"] == ["us_code"]
    assert coverage["per_corpus"][0]["failure_count"] == 1
    assert coverage["per_corpus"][0]["actionable_failure_cluster"] is True
    patch_clusters = run.summary["failure_patch_clusters"]
    assert patch_clusters[0]["corpus_key"] == "us_code"
    assert patch_clusters[0]["host"] == "uscode.house.gov"
    assert patch_clusters[0]["failure_count"] == 1
    scraper_coverage = run.summary["scraper_coverage"]
    assert scraper_coverage["recovery_count"] == 1
    assert scraper_coverage["scraper_target_count"] == 1
    assert scraper_coverage["host_count"] == 1
    assert scraper_coverage["hosts"] == {"uscode.house.gov": 1}
    assert scraper_coverage["corpora"] == {"us_code": 1}
    assert scraper_coverage["targets"][0]["target_file"].endswith("us_code_scraper.py")
    assert scraper_coverage["targets"][0]["hosts"] == ["uscode.house.gov"]
    assert scraper_coverage["targets"][0]["corpora"] == ["us_code"]
    assert scraper_coverage["targets"][0]["citations"] == ["18 U.S.C. § 242"]
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["actionable_corpora"] == ["us_code"]
    assert backlog["cluster_count"] == 1
    assert backlog["clusters"][0]["target_file"].endswith("us_code_scraper.py")
    assert backlog["scraper_coverage"]["targets"][0]["target_file"].endswith("us_code_scraper.py")
    assert backlog["scraper_coverage"]["hosts"] == {"uscode.house.gov": 1}
    assert "malformed_repairs" in backlog
    assert run.summary["failure_patch_backlog_path"]
    assert Path(run.summary["failure_patch_backlog_path"]).exists()
    persisted_backlog = json.loads(Path(run.summary["failure_patch_backlog_path"]).read_text(encoding="utf-8"))
    assert persisted_backlog["scraper_coverage"]["scraper_target_count"] == 1
    assert persisted_backlog["scraper_coverage"]["hosts"] == {"uscode.house.gov": 1}


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_summarizes_multiple_scraper_targets(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(["Minn. Stat. § 518.17", "42 U.S.C. § 1983"])

    def fake_resolve_document(text: str, **kwargs):
        citation_text = "42 U.S.C. § 1983" if "42 U.S.C." in text else "Minn. Stat. § 518.17"
        corpus_key = "us_code" if "42 U.S.C." in citation_text else "state_laws"
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": citation_text,
                    "normalized_citation": citation_text,
                    "metadata": {"recovery_corpus_key": corpus_key, "candidate_corpora": [corpus_key]},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        corpus_key = kwargs["corpus_key"]
        is_us_code = corpus_key == "us_code"
        manifest_path = tmp_path / f"{corpus_key}.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "manifest_path": str(manifest_path),
            "scraper_patch": {
                "host": "uscode.house.gov" if is_us_code else "www.revisor.mn.gov",
                "target_file": (
                    "ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/us_code_scraper.py"
                    if is_us_code
                    else "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py"
                ),
                "patch_path": str(tmp_path / f"{corpus_key}.patch"),
            },
        }

    def fake_merge(manifest_path: str):
        if Path(manifest_path).name == "state_laws.json":
            return {
                "status": "success",
                "target_local_parquet_path": str(tmp_path / "STATE-MN.parquet"),
                "merge_report_path": str(tmp_path / "state-laws-merge-report.json"),
            }
        return {
            "status": "failed",
            "error": "missing canonical us_code target parquet",
            "target_local_parquet_path": str(tmp_path / "USC-42.parquet"),
            "merge_report_path": str(tmp_path / "us-code-merge-report.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=2,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_recovered_rows=True,
        merge_manifest_func=fake_merge,
        corpus_keys=["state_laws", "us_code", "state_admin_rules"],
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    scraper_coverage = run.summary["scraper_coverage"]
    assert scraper_coverage["recovery_count"] == 2
    assert scraper_coverage["scraper_target_count"] == 2
    assert scraper_coverage["host_count"] == 2
    assert scraper_coverage["corpora"] == {"state_laws": 1, "us_code": 1}
    targets = {Path(item["target_file"]).name: item for item in scraper_coverage["targets"]}
    assert targets["state_laws_scraper.py"]["hosts"] == ["www.revisor.mn.gov"]
    assert targets["state_laws_scraper.py"]["citations"] == ["Minn. Stat. § 518.17"]
    assert targets["state_laws_scraper.py"]["merge_status_counts"] == {"success": 1}
    assert targets["state_laws_scraper.py"]["merge_success_count"] == 1
    assert targets["state_laws_scraper.py"]["merge_failure_count"] == 0
    assert targets["state_laws_scraper.py"]["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    assert targets["us_code_scraper.py"]["hosts"] == ["uscode.house.gov"]
    assert targets["us_code_scraper.py"]["citations"] == ["42 U.S.C. § 1983"]
    assert targets["us_code_scraper.py"]["merge_status_counts"] == {"failed": 1}
    assert targets["us_code_scraper.py"]["merge_success_count"] == 0
    assert targets["us_code_scraper.py"]["merge_failure_count"] == 1
    assert targets["us_code_scraper.py"]["target_local_parquet_paths"] == [str(tmp_path / "USC-42.parquet")]
    assert run.summary["recovery_merge"]["status_counts"] == {"failed": 1, "success": 1}
    assert run.summary["recovery_merge"]["success_count"] == 1
    assert run.summary["recovery_merge"]["failure_count"] == 1
    assert run.summary["recovery_merge"]["error_counts"] == {"missing canonical us_code target parquet": 1}
    matrix = run.summary["scraper_family_matrix"]
    assert matrix["requested_corpora"] == ["state_laws", "us_code", "state_admin_rules"]
    assert matrix["covered_corpora"] == ["state_laws", "us_code"]
    assert matrix["missing_requested_corpora"] == ["state_admin_rules"]
    assert matrix["unmerged_recovery_corpora"] == ["us_code"]
    assert matrix["fully_merged_recovery_corpora"] == ["state_laws"]
    matrix_rows = {row["corpus_key"]: row for row in matrix["rows"]}
    assert matrix_rows["state_laws"]["merge_success_count"] == 1
    assert matrix_rows["state_laws"]["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN.parquet")]
    assert matrix_rows["us_code"]["merge_failure_count"] == 1
    assert matrix_rows["us_code"]["target_files"] == [
        "ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/us_code_scraper.py"
    ]
    assert matrix_rows["state_admin_rules"]["attempt_count"] == 0
    assert run.summary["failure_patch_backlog"]["scraper_coverage"]["scraper_target_count"] == 2
    assert run.summary["failure_patch_backlog"]["scraper_family_matrix"]["missing_requested_corpora"] == [
        "state_admin_rules"
    ]
    assert run.summary["failure_patch_backlog"]["scraper_coverage"]["hosts"] == {
        "uscode.house.gov": 1,
        "www.revisor.mn.gov": 1,
    }
    assert run.summary["failure_patch_backlog"]["recovery_merge"]["status_counts"] == {"failed": 1, "success": 1}
    assert run.summary["failure_patch_backlog"]["recovery_merge"]["error_counts"] == {
        "missing canonical us_code target parquet": 1
    }


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_uses_candidate_hint_for_sparse_unresolved_metadata(
    tmp_path: Path,
) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "citation_text": "Minn. R. Civ. P. 56.03",
                    "context_text": "The motion relies on Minn. R. Civ. P. 56.03.",
                    "state_code": "MN",
                    "corpus_key_hint": "state_court_rules",
                    "citation_type_hint": "state_court_rule",
                    "expected_valid": True,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. R. Civ. P. 56.03",
                    "normalized_citation": "Minn. R. Civ. P. 56.03",
                    "metadata": {},
                }
            ],
        }

    async def fake_recovery(**kwargs):
        assert kwargs["corpus_key"] == "state_court_rules"
        assert kwargs["state_code"] == "MN"
        manifest_path = tmp_path / "state_court_rules.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": kwargs["corpus_key"],
            "manifest_path": str(manifest_path),
            "scraper_patch": {
                "host": "www.revisor.mn.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_procedure_rules_scraper.py",
                "patch_path": str(tmp_path / "state_court_rules.patch"),
            },
        }

    def fake_merge(manifest_path: str):
        return {
            "status": "success",
            "target_local_parquet_path": str(tmp_path / "STATE-MN-court-rules.parquet"),
            "merge_report_path": str(tmp_path / "state-court-rules-merge-report.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_recovered_rows=True,
        merge_manifest_func=fake_merge,
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["coverage_by_corpus"]["actionable_corpora"] == ["state_court_rules"]
    assert run.summary["recovery_merge"]["success_count"] == 1
    scraper_target = run.summary["scraper_coverage"]["targets"][0]
    assert scraper_target["target_file"].endswith("state_procedure_rules_scraper.py")
    assert scraper_target["corpora"] == ["state_court_rules"]
    assert scraper_target["merge_status_counts"] == {"success": 1}
    assert scraper_target["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN-court-rules.parquet")]
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["scraper_coverage"]["corpora"] == {"state_court_rules": 1}
    assert backlog["recovery_merge"]["merge_report_paths"] == [str(tmp_path / "state-court-rules-merge-report.json")]


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_covers_federal_register_scraper_merge(
    tmp_path: Path,
) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "citation_text": "21 C.F.R. § 314.80",
                    "context_text": "The petition cites 21 C.F.R. § 314.80 for adverse event reporting.",
                    "state_code": "",
                    "corpus_key_hint": "federal_register",
                    "citation_type_hint": "cfr",
                    "expected_valid": True,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "21 C.F.R. § 314.80",
                    "normalized_citation": "21 C.F.R. § 314.80",
                    "metadata": {
                        "recovery_corpus_key": "federal_register",
                        "candidate_corpora": ["federal_register"],
                    },
                }
            ],
        }

    async def fake_recovery(**kwargs):
        assert kwargs["corpus_key"] == "federal_register"
        manifest_path = tmp_path / "federal_register.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": kwargs["corpus_key"],
            "manifest_path": str(manifest_path),
            "candidate_files": [
                {
                    "url": "https://www.ecfr.gov/current/title-21/section-314.80",
                    "fetch_success": True,
                    "validation_status": "confirmed",
                }
            ],
            "scraper_patch": {
                "host": "www.ecfr.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/federal_register_scraper.py",
                "patch_path": str(tmp_path / "federal_register.patch"),
            },
        }

    def fake_merge(manifest_path: str):
        assert Path(manifest_path).name == "federal_register.json"
        return {
            "status": "success",
            "target_local_parquet_path": str(tmp_path / "federal_register.parquet"),
            "merge_report_path": str(tmp_path / "federal-register-merge-report.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_recovered_rows=True,
        merge_manifest_func=fake_merge,
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["coverage_by_corpus"]["actionable_corpora"] == ["federal_register"]
    assert run.summary["recovery_merge"]["status_counts"] == {"success": 1}
    assert run.summary["recovery_merge"]["target_local_parquet_paths"] == [str(tmp_path / "federal_register.parquet")]
    assert run.summary["recovery_artifact_quality"]["candidate_file_count"] == 1
    scraper_target = run.summary["scraper_coverage"]["targets"][0]
    assert scraper_target["target_file"].endswith("federal_register_scraper.py")
    assert scraper_target["hosts"] == ["www.ecfr.gov"]
    assert scraper_target["corpora"] == ["federal_register"]
    assert scraper_target["citations"] == ["21 C.F.R. § 314.80"]
    assert scraper_target["merge_status_counts"] == {"success": 1}
    assert scraper_target["target_local_parquet_paths"] == [str(tmp_path / "federal_register.parquet")]
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["scraper_coverage"]["hosts"] == {"www.ecfr.gov": 1}
    assert backlog["recovery_merge"]["merge_report_paths"] == [str(tmp_path / "federal-register-merge-report.json")]


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_covers_state_admin_rules_scraper_merge(
    tmp_path: Path,
) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "citation_text": "Minn. R. 3400.0100",
                    "context_text": "The agency decision relies on Minn. R. 3400.0100.",
                    "state_code": "MN",
                    "corpus_key_hint": "state_admin_rules",
                    "citation_type_hint": "state_admin_rule",
                    "expected_valid": True,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "Minn. R. 3400.0100",
                    "normalized_citation": "Minn. R. 3400.0100",
                    "metadata": {
                        "state_code": "MN",
                        "recovery_corpus_key": "state_admin_rules",
                        "candidate_corpora": ["state_admin_rules"],
                    },
                }
            ],
        }

    async def fake_recovery(**kwargs):
        assert kwargs["corpus_key"] == "state_admin_rules"
        assert kwargs["state_code"] == "MN"
        manifest_path = tmp_path / "state_admin_rules.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": kwargs["corpus_key"],
            "manifest_path": str(manifest_path),
            "candidate_files": [
                {
                    "url": "https://www.revisor.mn.gov/rules/3400.0100/",
                    "fetch_success": True,
                    "validation_status": "confirmed",
                }
            ],
            "scraper_patch": {
                "host": "www.revisor.mn.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_admin_rules_scraper.py",
                "patch_path": str(tmp_path / "state_admin_rules.patch"),
            },
        }

    def fake_merge(manifest_path: str):
        assert Path(manifest_path).name == "state_admin_rules.json"
        return {
            "status": "success",
            "target_local_parquet_path": str(tmp_path / "STATE-MN-admin-rules.parquet"),
            "merge_report_path": str(tmp_path / "state-admin-rules-merge-report.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_recovered_rows=True,
        merge_manifest_func=fake_merge,
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["coverage_by_corpus"]["actionable_corpora"] == ["state_admin_rules"]
    assert run.summary["recovery_merge"]["status_counts"] == {"success": 1}
    assert run.summary["recovery_merge"]["target_local_parquet_paths"] == [
        str(tmp_path / "STATE-MN-admin-rules.parquet")
    ]
    assert run.summary["recovery_artifact_quality"]["candidate_file_count"] == 1
    scraper_target = run.summary["scraper_coverage"]["targets"][0]
    assert scraper_target["target_file"].endswith("state_admin_rules_scraper.py")
    assert scraper_target["hosts"] == ["www.revisor.mn.gov"]
    assert scraper_target["corpora"] == ["state_admin_rules"]
    assert scraper_target["citations"] == ["Minn. R. 3400.0100"]
    assert scraper_target["merge_status_counts"] == {"success": 1}
    assert scraper_target["target_local_parquet_paths"] == [str(tmp_path / "STATE-MN-admin-rules.parquet")]
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["scraper_coverage"]["hosts"] == {"www.revisor.mn.gov": 1}
    assert backlog["recovery_merge"]["merge_report_paths"] == [str(tmp_path / "state-admin-rules-merge-report.json")]


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_covers_caselaw_access_project_merge(
    tmp_path: Path,
) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "citation_text": "410 U.S. 113",
                    "context_text": "The complaint cites Roe v. Wade, 410 U.S. 113.",
                    "state_code": "",
                    "corpus_key_hint": "caselaw_access_project",
                    "citation_type_hint": "case",
                    "expected_valid": True,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 1,
            "matched_citation_count": 0,
            "unmatched_citation_count": 1,
            "citations": [],
            "unresolved_citations": [
                {
                    "citation_text": "410 U.S. 113",
                    "normalized_citation": "410 U.S. 113",
                    "metadata": {
                        "recovery_corpus_key": "caselaw_access_project",
                        "candidate_corpora": ["caselaw_access_project"],
                    },
                }
            ],
        }

    async def fake_recovery(**kwargs):
        assert kwargs["corpus_key"] == "caselaw_access_project"
        manifest_path = tmp_path / "caselaw_access_project.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "corpus_key": kwargs["corpus_key"],
            "manifest_path": str(manifest_path),
            "candidate_files": [
                {
                    "url": "https://www.courtlistener.com/opinion/108713/roe-v-wade/",
                    "fetch_success": True,
                    "validation_status": "confirmed",
                }
            ],
            "scraper_patch": {
                "host": "www.courtlistener.com",
                "target_file": (
                    "ipfs_datasets_py/processors/legal_scrapers/"
                    "caselaw_access_program/vector_search_integration.py"
                ),
                "patch_path": str(tmp_path / "caselaw_access_project.patch"),
            },
        }

    def fake_merge(manifest_path: str):
        assert Path(manifest_path).name == "caselaw_access_project.json"
        return {
            "status": "success",
            "target_local_parquet_path": str(tmp_path / "caselaw_access_project.parquet"),
            "merge_report_path": str(tmp_path / "caselaw-access-project-merge-report.json"),
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        recovery_func=fake_recovery,
        merge_recovered_rows=True,
        merge_manifest_func=fake_merge,
        min_actionable_failures=1,
        output_dir=tmp_path / "artifacts",
    )

    assert run.summary["coverage_by_corpus"]["actionable_corpora"] == ["caselaw_access_project"]
    assert run.summary["recovery_merge"]["status_counts"] == {"success": 1}
    assert run.summary["recovery_merge"]["target_local_parquet_paths"] == [
        str(tmp_path / "caselaw_access_project.parquet")
    ]
    assert run.summary["recovery_artifact_quality"]["candidate_file_count"] == 1
    scraper_target = run.summary["scraper_coverage"]["targets"][0]
    assert scraper_target["target_file"].endswith("caselaw_access_program/vector_search_integration.py")
    assert scraper_target["hosts"] == ["www.courtlistener.com"]
    assert scraper_target["corpora"] == ["caselaw_access_project"]
    assert scraper_target["citations"] == ["410 U.S. 113"]
    assert scraper_target["merge_status_counts"] == {"success": 1}
    assert scraper_target["target_local_parquet_paths"] == [str(tmp_path / "caselaw_access_project.parquet")]
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["scraper_coverage"]["hosts"] == {"www.courtlistener.com": 1}
    assert backlog["recovery_merge"]["merge_report_paths"] == [
        str(tmp_path / "caselaw-access-project-merge-report.json")
    ]


@pytest.mark.anyio
async def test_run_bluebook_linker_fuzz_harness_records_malformed_repairs(tmp_path: Path) -> None:
    def fake_generate(*args, **kwargs) -> str:
        return json.dumps(
            [
                {
                    "citation_text": "ORSS 801.545",
                    "context_text": "The filing relies on ORSS 801.545.",
                    "state_code": "OR",
                    "corpus_key_hint": "state_laws",
                    "citation_type_hint": "state_statute",
                    "expected_valid": False,
                }
            ]
        )

    def fake_resolve_document(text: str, **kwargs):
        return {
            "citation_count": 0,
            "matched_citation_count": 0,
            "unmatched_citation_count": 0,
            "citations": [],
            "unresolved_citations": [],
        }

    run = await run_bluebook_linker_fuzz_harness(
        sample_count=1,
        output_dir=tmp_path / "artifacts",
        llm_generate_func=fake_generate,
        resolve_document_func=fake_resolve_document,
        enable_recovery=False,
    )

    repairs = run.summary["malformed_repairs"]
    assert repairs
    assert repairs[0]["raw_citation"] == "ORSS 801.545"
    assert repairs[0]["normalized_citation"] == "ORS 801.545"
    assert run.summary["malformed_repairs_path"]
    assert Path(run.summary["malformed_repairs_path"]).exists()
