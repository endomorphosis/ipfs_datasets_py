"""Evidence joins in the teacher/student smoke must not silently change inputs."""
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/validate_teacher_student_transfer.py"
    spec = importlib.util.spec_from_file_location("teacher_student_transfer_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs():
    fixture = [{"id": "x", "text": "The agency shall submit reports."}]
    text = fixture[0]["text"]
    data = {"inputs": [{"input_id": "sha256:x", "section": "x", "text": text,
        "title": "diagnostic", "citation": "authored diagnostic:x", "source": {
            "document_id": "x", "citation": "authored diagnostic:x", "source_kind": "diagnostic",
            "artifact": {"sha256": hashlib.sha256(text.encode()).hexdigest()}}}],
        "results": [{"input_id": "sha256:x", "status": "embedded"}]}
    return data, fixture


def test_valid_exact_fixture_join(runner):
    data, fixture = inputs()
    assert runner.verify_fixture_inputs(data, fixture) is None


@pytest.mark.parametrize("field", ("text", "title", "citation", "section"))
def test_reusing_embedding_for_changed_fixture_is_rejected(runner, field):
    data, fixture = inputs()
    data["inputs"][0][field] += " changed"
    with pytest.raises(RuntimeError):
        runner.verify_fixture_inputs(data, fixture)


@pytest.mark.parametrize("change", ("missing", "duplicate", "wrong_result", "not_embedded", "wrong_source"))
def test_missing_duplicate_or_misbound_embedding_rejected(runner, change):
    data, fixture = inputs()
    if change == "missing":
        data["results"] = []
    elif change == "duplicate":
        data["inputs"].append(copy.deepcopy(data["inputs"][0]))
        data["results"].append(copy.deepcopy(data["results"][0]))
        fixture.append({"id": "y", "text": fixture[0]["text"]})
    elif change == "wrong_result":
        data["results"][0]["input_id"] = "sha256:y"
    elif change == "not_embedded":
        data["results"][0]["status"] = "missing"
    else:
        data["inputs"][0]["source"]["artifact"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError):
        runner.verify_fixture_inputs(data, fixture)


@pytest.mark.parametrize("ids", ([], ["x", "x"], ["y"]))
def test_prediction_coverage_cannot_shrink_denominator(runner, ids):
    with pytest.raises(RuntimeError, match="exactly cover"):
        runner.comparison({"rows": [{"id": key} for key in ids]}, [{"id": "x", "canonical_ir": {}}])
