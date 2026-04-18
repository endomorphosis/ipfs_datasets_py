from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.bluebook_linker_fuzz_harness import (
    collect_seeded_bluebook_fuzz_candidates,
    parse_bluebook_fuzz_candidates,
    run_bluebook_linker_fuzz_harness,
)


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
            "published_merged_to_hf": True,
            "publish_report": {
                "repo_id": "justicedao/ipfs_state_laws",
                "path_in_repo": "state_laws_parquet_cid/STATE-MN.parquet",
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
    assert run.summary["failure_patch_backlog"]["scraper_coverage"]["scraper_target_count"] == 2
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
