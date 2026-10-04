"""Development-only checks; never materialize the sealed test source targets."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location("convergence_benchmark_test", ROOT / "scripts/ops/autoencoder/benchmark_complete_feature_convergence.py")
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)
PANEL = BENCHMARK.load_panel()


def test_manifest_has_disjoint_compositions_and_training_known_vocabulary():
    for domain in PANEL.DOMAINS:
        rows = {split: PANEL.rows(domain, split) for split in ("train", "validation", "test")}
        assert {split: len(items) for split, items in rows.items()} == {"train": 6, "validation": 2, "test": 2}
        groups = {split: {row["group_id"] for row in items} for split, items in rows.items()}
        assert not groups["train"] & (groups["validation"] | groups["test"])
        assert not groups["validation"] & groups["test"]
        for key in ("actor", "action"):
            assert {row[key] for row in rows["validation"] + rows["test"]} <= {row[key] for row in rows["train"]}


@pytest.mark.parametrize("domain", PANEL.DOMAINS)
def test_development_native_targets_complete_and_serializable(domain):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as native
    # Development source construction exercises all constructors and the eight
    # explicit formula requirements; heldout source bodies stay unrequested.
    for row in PANEL.rows(domain, "train")[:2]:
        case = PANEL.prepare_case(row)
        report = case["report"]
        assert report["domain_id"] == domain
        assert len(case["fixture"]["formulas"]) == 8
        names = {p["projection_id"] for p in report["projections"]}
        assert len(names) == len(report["projections"])
        assert all(p["ready_for_training"] for p in report["projections"])
        lowered = native.prepare_native_family_lean(report, source_inputs=case["source_inputs"])
        assert all(p["semantic_lowering_supported"] for p in lowered["per_projection"]), lowered["per_projection"]
        assert lowered["backend_executed"] is False
        assert len(report["family_inventory"]) == 40
        assert BENCHMARK.raw(BENCHMARK.encode_source(case["source_inputs"]))
        assert case["fixture"]["source_semantics_verified"] is False
        assert case["fixture"]["qualified"] is False
        reviews = PANEL.reviews(report, row)
        assert all(item["source_digest"] == report["source_digest"] for item in reviews)
        assert not {p["logic_family"] for p in report["projections"]} & {item["family_id"] for item in reviews}


def test_non_manifest_row_rejected():
    row = {**PANEL.rows("intent_ir", "train")[0], "source_id": "unreviewed"}
    with pytest.raises(ValueError, match="exact declared"):
        PANEL.prepare_case(row)


def test_comparison_is_fixed_before_test_exposure():
    assert BENCHMARK.SETTINGS["latent_width"] == 4
    assert BENCHMARK.SETTINGS["epochs"] == 24
    assert BENCHMARK.SEEDS == (1729, 1730)
    assert BENCHMARK.STRATEGIES == ("budgeted_decoder", "complete_fixed", "complete_adaptive")


def test_native_validation_rejects_missing_projection_and_wrong_lake_library():
    cases = {"case": {"report": {"projections": [{"projection_id": "required"}]}}}
    receipt = {"library": "LegalIR", "execution": {"returncode": 0, "command": ["lake", "build", "LegalIR"]},
        "per_projection": [{"projection_id": "required", "parser_status": "passed", "lake_status": "passed"}]}
    result = {"receipt": {"all_jobs_completed": True}, "jobs": [{"job_id": "case", "receipt": {"native": receipt}}]}
    _, counts = BENCHMARK.check_native(result, cases)
    assert counts == {"actual_lake_builds": 1, "emitted_projection_checks": 1}
    receipt["per_projection"] = []
    with pytest.raises(ValueError, match="every emitted"):
        BENCHMARK.check_native(result, cases)
    receipt["per_projection"] = [{"projection_id": "required", "parser_status": "passed", "lake_status": "passed"}]
    receipt["execution"]["command"][-1] = "DifferentLibrary"
    with pytest.raises(ValueError, match="matching actual Lake"):
        BENCHMARK.check_native(result, cases)
