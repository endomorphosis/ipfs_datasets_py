from __future__ import annotations

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
