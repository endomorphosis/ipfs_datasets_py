from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
    V2_QUERY_API_SCHEMA_VERSION,
    check_compliance,
    explain_proof,
    find_violations,
    parse_cnl_to_ir,
    run_v2_pipeline_with_defaults,
)


def _one_norm_ir(sentence: str):
    return parse_cnl_to_ir(sentence, jurisdiction="us/federal")


def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(value[k]) for k in sorted(value.keys())}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_shape(item) for item in value]}
    if isinstance(value, list):
        if not value:
            return {"__type__": "list", "items": "empty"}
        return {"__type__": "list", "items": _shape(value[0])}
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "none"
    return type(value).__name__


def _build_query_api_schema_snapshot():
    ir = _one_norm_ir("Controller shall report breach within 72 hours.")
    compliance = check_compliance({"ir": ir, "events": []}, {"at": "2026-03-01"})
    violations = find_violations({"ir": ir, "events": []}, ("2026-01-01", "2026-12-31"))
    explanation = explain_proof(compliance["proof_id"], format="json")
    return {
        "check_compliance": _shape(compliance),
        "find_violations": _shape(violations),
        "explain_proof": _shape(explanation),
    }


def _build_query_api_samples():
    ir = _one_norm_ir("Controller shall report breach within 72 hours.")
    compliance = check_compliance({"ir": ir, "events": []}, {"at": "2026-03-01"})
    violations = find_violations({"ir": ir, "events": []}, ("2026-01-01", "2026-12-31"))
    explanation = explain_proof(compliance["proof_id"], format="json")
    return {
        "v2_check_compliance.schema.json": compliance,
        "v2_find_violations.schema.json": violations,
        "v2_explain_proof.schema.json": explanation,
    }


def _is_valid_type(value, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "array":
        return isinstance(value, (list, tuple))
    if type_name == "object":
        return isinstance(value, dict)
    return True


def _assert_schema_required_types(sample: dict, schema: dict) -> None:
    required = list(schema.get("required") or [])
    properties = dict(schema.get("properties") or {})
    for key in required:
        assert key in sample, f"missing required key: {key}"
        declared = properties.get(key, {})
        declared_type = declared.get("type")
        if isinstance(declared_type, list):
            assert any(_is_valid_type(sample[key], t) for t in declared_type), (
                key,
                declared_type,
                type(sample[key]).__name__,
            )
        elif isinstance(declared_type, str):
            assert _is_valid_type(sample[key], declared_type), (
                key,
                declared_type,
                type(sample[key]).__name__,
            )


def test_v2_query_matrix_eight_cases() -> None:
    # Q1 compliant obligation (event happened)
    ir_q1 = _one_norm_ir("Controller shall report breach within 72 hours.")
    frame_q1 = next(iter(ir_q1.frames.keys()))
    out_q1 = check_compliance({"ir": ir_q1, "events": [frame_q1]}, {"at": "2026-03-01"})
    assert out_q1["api"] == "check_compliance"
    assert out_q1["schema_version"] == V2_QUERY_API_SCHEMA_VERSION
    assert out_q1["status"] == "compliant"

    # Q2 non-compliant obligation (event missing)
    ir_q2 = _one_norm_ir("Controller shall report breach within 72 hours.")
    out_q2 = check_compliance({"ir": ir_q2, "events": []}, {"at": "2026-03-01"})
    assert out_q2["api"] == "check_compliance"
    assert out_q2["status"] == "non_compliant"
    assert out_q2["violation_count"] == len(out_q2["violations"])
    assert all({"norm_id", "frame_id", "type"}.issubset(v.keys()) for v in out_q2["violations"])

    # Q3 prohibition violated
    ir_q3 = _one_norm_ir("Vendor shall not disclose personal data.")
    frame_q3 = next(iter(ir_q3.frames.keys()))
    out_q3 = check_compliance({"ir": ir_q3, "events": [frame_q3]}, {"at": "2026-03-01"})
    assert out_q3["status"] == "non_compliant"
    assert all({"norm_id", "frame_id", "type"}.issubset(v.keys()) for v in out_q3["violations"])

    # Q4 prohibition with exception active -> compliant
    ir_q4 = _one_norm_ir("Vendor shall not disclose personal data unless consent recorded.")
    frame_q4 = next(iter(ir_q4.frames.keys()))
    out_q4 = check_compliance(
        {
            "ir": ir_q4,
            "events": [frame_q4],
            "facts": {"unless_consent_recorded": True},
        },
        {"at": "2026-03-01"},
    )
    assert out_q4["status"] == "compliant"

    # Q5 permission only (no violation semantics)
    ir_q5 = _one_norm_ir("Agency may inspect records if complaint filed.")
    out_q5 = check_compliance(
        {
            "ir": ir_q5,
            "events": [],
            "facts": {"if_complaint_filed": True},
        },
        {"at": "2026-03-01"},
    )
    assert out_q5["status"] == "compliant"

    # Q6 find violations in range (obligation omission)
    ir_q6 = _one_norm_ir("Employer shall pay wages by 2026-12-31.")
    out_q6 = find_violations({"ir": ir_q6, "events": []}, ("2026-01-01", "2026-12-31"))
    assert out_q6["api"] == "find_violations"
    assert out_q6["schema_version"] == V2_QUERY_API_SCHEMA_VERSION
    assert out_q6["violation_count"] == len(out_q6["violations"])
    assert all({"norm_id", "frame_id", "type"}.issubset(v.keys()) for v in out_q6["violations"])
    assert len(out_q6["violations"]) >= 1

    # Q7 explain proof NL
    exp_q7 = explain_proof(out_q6["proof_id"], format="nl")
    assert exp_q7["api"] == "explain_proof"
    assert exp_q7["schema_version"] == V2_QUERY_API_SCHEMA_VERSION
    assert "Proof" in exp_q7["text"]

    # Q8 explain proof JSON
    exp_q8 = explain_proof(out_q2["proof_id"], format="json")
    assert exp_q8["api"] == "explain_proof"
    assert exp_q8["schema_version"] == V2_QUERY_API_SCHEMA_VERSION
    assert exp_q8["format"] == "json"
    assert exp_q8["steps"]


def test_v2_explain_proof_rejects_unknown_format() -> None:
    ir = _one_norm_ir("Controller shall report breach within 72 hours.")
    out = check_compliance({"ir": ir, "events": []}, {"at": "2026-03-01"})

    try:
        explain_proof(out["proof_id"], format="yaml")
    except ValueError as exc:
        assert "unsupported format" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported format")


def test_v2_query_matrix_prover_envelopes_are_normalized_and_backend_specific() -> None:
    sentence = "Controller shall report breach within 72 hours."
    out_smt = run_v2_pipeline_with_defaults(
        sentence,
        jurisdiction="us/federal",
        enable_optimizer=True,
        enable_kg=True,
        enable_prover=True,
        prover_backend_id="mock_smt",
    )
    out_fol = run_v2_pipeline_with_defaults(
        sentence,
        jurisdiction="us/federal",
        enable_optimizer=True,
        enable_kg=True,
        enable_prover=True,
        prover_backend_id="mock_fol",
    )

    smt_env = out_smt["prover_report"]["dcec"]
    fol_env = out_fol["prover_report"]["dcec"]

    assert smt_env["schema_version"] == "1.0"
    assert fol_env["schema_version"] == "1.0"
    assert smt_env["backend"] == "mock_smt"
    assert fol_env["backend"] == "mock_fol"
    assert smt_env["certificate"]["certificate_id"].startswith("cert_")
    assert fol_env["certificate"]["certificate_id"].startswith("cert_")
    assert len(smt_env["certificate"]["normalized_hash"]) == 64
    assert len(fol_env["certificate"]["normalized_hash"]) == 64
    assert smt_env["certificate"]["format"] == "smt-certificate-v1"
    assert fol_env["certificate"]["format"] == "first-order-certificate-v1"


def test_v2_query_api_schema_snapshot_lockfile() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "hybrid_v2_api_schema_snapshot.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual = _build_query_api_schema_snapshot()
    assert actual == expected, (
        "V2 query API schema snapshot drift detected.\n"
        f"Expected: {json.dumps(expected, indent=2, sort_keys=True)}\n"
        f"Actual: {json.dumps(actual, indent=2, sort_keys=True)}"
    )


def test_v2_query_api_json_schemas_match_runtime_required_keys() -> None:
    schema_dir = Path(__file__).resolve().parents[2] / "docs" / "guides" / "legal_data" / "schemas"
    samples = _build_query_api_samples()
    for schema_name, sample in samples.items():
        schema_path = schema_dir / schema_name
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        _assert_schema_required_types(sample, schema)
