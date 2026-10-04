"""Fresh-campaign split and gold-free qualification boundary regressions."""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


driver = load("native_source_driver_test", "scripts/ops/autoencoder/benchmark_native_source_v3.py")
panel = driver.panel


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_development_augmentation_is_grouped_and_comparator_subset(domain):
    baseline = panel.rows(domain, "train", arm="baseline")
    augmented = panel.rows(domain, "train")
    tuning = panel.rows(domain, "validation")
    assert len(baseline) == 180 and len(augmented) == 360 and len(tuning) == 120
    assert {r["id"] for r in baseline} < {r["id"] for r in augmented}
    for key in ("id", "group_id", "source_sha256"):
        assert not {r[key] for r in augmented} & {r[key] for r in tuning}
    for rows in (augmented, tuning):
        for group in {r["group_id"] for r in rows}:
            block = [r for r in rows if r["group_id"] == group]
            assert len(block) == 24 and {r["wording_style"] for r in block} == {0, 1, 2, 3}


def test_qualification_rejects_gold_bearing_source_rows():
    with pytest.raises(ValueError, match="gold or embeddings"):
        driver.native_qualification("intent_ir", [{"id": "x", "source_text": "x", "target": {}}], {"rows": []})


@pytest.mark.parametrize("field", ["exact_target", "within_training_coverage", "target_coverage_reason", "target"])
def test_qualification_rejects_gold_evaluation_metadata(field):
    with pytest.raises(ValueError, match="evaluated predictions"):
        driver.native_qualification("intent_ir", [{"id": "x", "source_text": "x"}], {"rows": [{field: True}]})
