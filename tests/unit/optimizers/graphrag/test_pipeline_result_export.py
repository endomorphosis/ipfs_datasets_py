"""Tests for PipelineResult.export()."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import PipelineResult


class _Score:
    def __init__(self, overall: float = 0.5) -> None:
        self.overall = overall

    def to_dict(self):
        return {"overall": self.overall}


def _make_result() -> PipelineResult:
    return PipelineResult(
        ontology={"entities": [], "relationships": []},
        score=_Score(),
    )


def test_export_json_default():
    result = _make_result()
    payload = result.export()
    assert "ontology" in payload
    assert "entities" in payload


def test_export_json_explicit():
    result = _make_result()
    payload = result.export("json", sort_keys=True)
    assert "ontology" in payload


def test_export_yaml():
    yaml = pytest.importorskip("yaml")
    result = _make_result()
    payload = result.export("yaml")
    assert "ontology" in payload
    assert "entities" in payload
    assert yaml.safe_load(payload)["ontology"] == {"entities": [], "relationships": []}


def test_export_invalid_format():
    result = _make_result()
    with pytest.raises(ValueError):
        result.export("toml")
