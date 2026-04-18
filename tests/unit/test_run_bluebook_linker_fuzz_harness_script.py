from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "ops"
        / "legal_data"
        / "run_bluebook_linker_fuzz_harness.py"
    )
    spec = importlib.util.spec_from_file_location("run_bluebook_linker_fuzz_harness_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeFuzzRun:
    output_path = "/tmp/fuzz-run.json"
    summary = {
        "sample_count_executed": 1,
        "matched_attempt_count": 0,
        "matched_attempt_ratio": 0.0,
        "unmatched_citation_count": 1,
        "recovery_count": 1,
        "merged_recovery_count": 0,
        "coverage_by_corpus": {"actionable_corpora": ["state_laws"]},
        "scraper_family_matrix": {
            "missing_requested_corpora": ["state_admin_rules"],
            "unmerged_recovery_corpora": ["us_code"],
            "fully_merged_recovery_corpora": ["state_laws"],
            "unpublished_hf_corpora": ["us_code"],
            "published_hf_corpora": ["state_laws"],
        },
        "recovery_merge": {
            "upload_ready_count": 2,
            "published_merged_count": 1,
            "publish_failure_count": 1,
        },
        "failure_patch_clusters": [
            {
                "corpus_key": "state_laws",
                "host": "www.revisor.mn.gov",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
                "failure_count": 1,
            }
        ],
        "failure_patch_backlog_path": "/tmp/fuzz-backlog.json",
    }

    def to_dict(self):
        return {"summary": dict(self.summary), "output_path": self.output_path}


def test_run_bluebook_linker_fuzz_harness_script_maps_fast_recovery_flags(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps(["Minn. Stat. § 518.17"]), encoding="utf-8")
    captured = {}

    async def _fake_run_bluebook_linker_fuzz_harness(**kwargs):
        captured.update(kwargs)
        return _FakeFuzzRun()

    monkeypatch.delenv("LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH", raising=False)
    monkeypatch.setattr(module, "run_bluebook_linker_fuzz_harness", _fake_run_bluebook_linker_fuzz_harness)

    exit_code = module.main(
        [
            "--samples",
            "2",
            "--input-candidates",
            str(candidate_path),
            "--disable-hf-fallback",
            "--disable-exhaustive",
            "--skip-live-search",
            "--recovery-max-candidates",
            "3",
            "--recovery-archive-top-k",
            "0",
            "--min-actionable-failures",
            "1",
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--json",
        ]
    )

    assert exit_code == 0
    assert captured["sample_count"] == 2
    assert captured["allow_hf_fallback"] is False
    assert captured["exhaustive"] is False
    assert captured["recovery_max_candidates"] == 3
    assert captured["recovery_archive_top_k"] == 0
    assert captured["min_actionable_failures"] == 1
    assert captured["output_dir"] == tmp_path / "artifacts"
    assert captured["llm_generate_func"]("", provider=None, model_name=None) == '["Minn. Stat. \\u00a7 518.17"]'
    assert module.os.environ["LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH"] == "1"


def test_run_bluebook_linker_fuzz_harness_script_prints_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_script_module()

    async def _fake_run_bluebook_linker_fuzz_harness(**kwargs):
        return _FakeFuzzRun()

    monkeypatch.setattr(module, "run_bluebook_linker_fuzz_harness", _fake_run_bluebook_linker_fuzz_harness)

    exit_code = module.main(["--samples", "1", "--output-dir", str(tmp_path / "artifacts")])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Executed 1 citation cases" in output
    assert "Recoveries: 1" in output
    assert "Actionable corpora: state_laws" in output
    assert "Missing requested corpora: state_admin_rules" in output
    assert "Unmerged recovery corpora: us_code" in output
    assert "Fully merged recovery corpora: state_laws" in output
    assert "Unpublished HF corpora: us_code" in output
    assert "Published HF corpora: state_laws" in output
    assert "HF upload-ready merges: 2" in output
    assert "HF published merges: 1" in output
    assert "HF publish failures: 1" in output
    assert "Top failure cluster: state_laws @ www.revisor.mn.gov" in output
    assert "Patch backlog: /tmp/fuzz-backlog.json" in output


def test_run_bluebook_linker_fuzz_harness_script_reads_candidates_from_stdin(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    captured = {}

    async def _fake_run_bluebook_linker_fuzz_harness(**kwargs):
        captured.update(kwargs)
        return _FakeFuzzRun()

    monkeypatch.setattr(module, "run_bluebook_linker_fuzz_harness", _fake_run_bluebook_linker_fuzz_harness)
    monkeypatch.setattr(module.sys, "stdin", type("_FakeStdin", (), {"read": lambda self: '["ORS 801.545"]'})())

    exit_code = module.main(
        [
            "--samples",
            "1",
            "--input-candidates",
            "-",
            "--corpora",
            " state_laws, us_code ,,",
            "--states",
            " mn, OR ,,",
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--json",
        ]
    )

    assert exit_code == 0
    assert captured["corpus_keys"] == ["state_laws", "us_code"]
    assert captured["state_codes"] == ["mn", "OR"]
    assert captured["llm_generate_func"]("", provider=None, model_name=None) == '["ORS 801.545"]'


def test_run_bluebook_linker_fuzz_harness_script_clamps_numeric_bounds(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    captured = {}

    async def _fake_run_bluebook_linker_fuzz_harness(**kwargs):
        captured.update(kwargs)
        return _FakeFuzzRun()

    monkeypatch.setattr(module, "run_bluebook_linker_fuzz_harness", _fake_run_bluebook_linker_fuzz_harness)

    exit_code = module.main(
        [
            "--samples",
            "0",
            "--seed-examples-per-corpus",
            "0",
            "--max-seed-examples-per-state",
            "-1",
            "--max-seed-examples-per-source",
            "0",
            "--recovery-max-candidates",
            "0",
            "--recovery-archive-top-k",
            "-5",
            "--max-acceptable-failure-rate",
            "2.5",
            "--min-actionable-failures",
            "0",
            "--output-dir",
            str(tmp_path / "artifacts"),
        ]
    )

    assert exit_code == 0
    assert captured["sample_count"] == 1
    assert captured["seed_examples_per_corpus"] == 1
    assert captured["max_seed_examples_per_state"] is None
    assert captured["max_seed_examples_per_source"] is None
    assert captured["recovery_max_candidates"] == 1
    assert captured["recovery_archive_top_k"] == 0
    assert captured["max_acceptable_failure_rate"] == 1.0
    assert captured["min_actionable_failures"] == 1
