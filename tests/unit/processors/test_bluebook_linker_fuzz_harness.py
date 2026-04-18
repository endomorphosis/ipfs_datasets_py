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
            "scraper_patch": {
                "patch_path": str(tmp_path / "recovery.patch"),
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
                "host": "www.revisor.mn.gov",
            },
        }

    def fake_merge(path: str):
        assert path == str(manifest_path)
        return {"status": "success", "target_local_parquet_path": str(tmp_path / "STATE-MN.parquet")}

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
    assert run.summary["failure_patch_clusters"][0]["patch_paths"] == [str(tmp_path / "recovery.patch")]
    assert run.attempts[0].merge_reports[0]["status"] == "success"
    assert run.output_path is not None
    assert Path(run.output_path).exists()
    persisted = json.loads(Path(run.output_path).read_text(encoding="utf-8"))
    assert persisted["summary"]["failure_patch_backlog_path"]
    assert persisted["summary"]["malformed_repairs_path"]


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
    backlog = run.summary["failure_patch_backlog"]
    assert backlog["actionable_corpora"] == ["us_code"]
    assert backlog["cluster_count"] == 1
    assert backlog["clusters"][0]["target_file"].endswith("us_code_scraper.py")
    assert "malformed_repairs" in backlog
    assert run.summary["failure_patch_backlog_path"]
    assert Path(run.summary["failure_patch_backlog_path"]).exists()


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
