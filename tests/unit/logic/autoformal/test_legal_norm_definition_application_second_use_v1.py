"""Replay a second fictional typed occurrence through both public bridge APIs.

The original fixture owns its source, trust snapshots, signatures and clocks.
This test forwards those fixtures without replacing any product owner. Two
same-spelling occurrences in one fictional source are not two statutory sources
or independently accepted legal uses. No membership or meaning is inferred.
"""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def bridge_suite():
    spec = importlib.util.spec_from_file_location(
        "_application_second_use_genuine_bridge_fixture",
        Path(__file__).with_name("test_legal_norm_definition_application_binding_v1.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def owner(bridge_suite):
    return bridge_suite.owner.__wrapped__()


@pytest.fixture(scope="module")
def conditional(bridge_suite):
    return bridge_suite.conditional.__wrapped__()


@pytest.fixture(scope="module")
def baseline(bridge_suite, owner, conditional):
    helper = bridge_suite.helper.__wrapped__()
    return bridge_suite.baseline.__wrapped__(owner, conditional, helper)


def test_public_second_same_spelling_occurrence_replays_without_global_application(
    bridge_suite, owner, conditional, baseline, tmp_path,
):
    """Use the second exact declared link; retain the first and every rival."""
    evidence = bridge_suite.evidence
    original = {key: baseline[key] for key in ("assessment", "inputs", "request")}
    before = evidence._snapshot(original)[1]
    assessment = baseline["assessment"]
    companion = assessment["original_companion"]
    first = baseline["report"]
    first_pin = owner.norm_definition_application_binding_sha256(first)
    assert len(assessment["uses"]) == 2
    assert len(companion["links"]) == 4
    assert len(companion["definitions"]) == 2

    data = dict(baseline)
    data["request"] = bridge_suite.request_for(
        conditional, assessment, baseline["inputs"], use_index=1,
    )
    report = bridge_suite.prepare(owner, data)
    assert bridge_suite.validate(owner, data, report) == report

    selected = report["selected_binding"]
    choice = assessment["declaration_record"]["decisions"][1]
    ref = choice["selected_link_ref"]
    assert selected["use_index"] == 1
    assert selected["use"] == assessment["uses"][1]
    assert selected["choice"] == choice
    assert selected["selected_link_ref"] == ref
    assert ref["link_index"] == 2
    assert selected["selected_link"] == companion["links"][ref["link_index"]]
    assert selected["selected_link"] != first["selected_binding"]["selected_link"]
    assert selected["use"]["target"] != first["selected_binding"]["use"]["target"]
    assert selected["use"]["typed_node"]["symbol"] == "actor"
    assert first["selected_binding"]["use"]["typed_node"]["symbol"] == "actor"

    result = report["conditional_report"]
    first_result = first["conditional_report"]
    occurrence = result["occurrence_binding"]
    assert result["request"] == data["request"]
    assert result["selected_link"] == selected["selected_link"]
    assert result["request"]["alternative_id"] == selected["selected_link"]["request_link"]["alternative_id"]
    assert result["request"]["link_sha256"] == ref["sha256"]
    assert occurrence["native_predicate"]["name"] == "Approved"
    assert first_result["occurrence_binding"]["native_predicate"]["name"] == "Retain"
    assert occurrence["native_variable"]["name"] == occurrence["binding"]["name"] == "actor"
    assert occurrence["binding"] == first_result["occurrence_binding"]["binding"]
    assert occurrence["argument"]["role"] == "actor"
    assert occurrence["native_predicate"]["arguments"][occurrence["argument"]["index"]] == occurrence["native_variable"]

    assert report["original_applicability_assessment"] == assessment
    assert result["original_norm"] == first_result["original_norm"]
    assert result["original_norm"]["unchanged"] is True
    assert result["definition_alternatives"] == first_result["definition_alternatives"]
    assert len(result["definition_alternatives"]) == 2
    assert report["complete_original_populations_retained"] is True
    assert report["original_norm_and_definition_asts_unchanged"] is True
    assert report["time_context"] == first["time_context"]
    assert result["request"]["mode"] == "instance_only"
    assert result["request"]["membership_assumption"] is None
    assert result["authority"]["membership_assumption_verified"] is False
    assert result["authority"]["norm_witness_extracted"] is False
    assert all(row["kernel_checked"] is False for row in result["conditional_theorem_statements"])
    bridge_suite.assert_unapplied(report)

    # Rehashing the request cannot substitute the first occurrence's link for
    # the second declared use, even though both occurrences spell "actor".
    forged = dict(data, request=deepcopy(data["request"]))
    forged["request"]["link_sha256"] = first["selected_binding"]["selected_link_ref"]["sha256"]
    with pytest.raises(ValueError, match="conditional request differs"):
        bridge_suite.prepare(owner, forged)
    assert evidence._snapshot(original)[1] == before
    assert owner.norm_definition_application_binding_sha256(first) == first_pin

    # Preserve only already prepared fixture outputs, without another replay.
    # These four files do not contain the complete original replay-input bundle.
    (tmp_path / "second-report.json").write_bytes(bridge_suite.wire(report))
    (tmp_path / "first-report.json").write_bytes(bridge_suite.wire(first))
    (tmp_path / "second-request.json").write_bytes(bridge_suite.wire(data["request"]))
    (tmp_path / "second-instance.lean").write_text(result["lean_source"], encoding="utf-8")
