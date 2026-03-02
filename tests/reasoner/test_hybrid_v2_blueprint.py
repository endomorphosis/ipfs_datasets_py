from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
    IDRegistryValidationError,
    DeonticOpV2,
    IRContractValidationError,
    clear_v2_proof_store,
    compile_ir_to_dcec,
    compile_ir_to_temporal_deontic_fol,
    explain_proof,
    find_violations,
    generate_cnl_from_ir,
    validate_ir_v2_contract,
    normalize_ir,
    parse_cnl_to_ir,
    run_v2_pipeline,
    run_v2_pipeline_with_defaults,
    check_compliance,
    configure_v2_proof_store_max_entries,
    validate_v2_canonical_id_registry,
)


def _first_norm_ref(ir) -> str:
    return next(iter(ir.norms.keys()))


def test_parse_cnl_to_ir_obligation_with_temporal() -> None:
    ir = parse_cnl_to_ir("Data controller shall report breach within 72 hours.", jurisdiction="us/federal")

    assert len(ir.norms) == 1
    norm = next(iter(ir.norms.values()))
    assert norm.op == DeonticOpV2.O
    assert norm.temporal_ref is not None


def test_parse_cnl_to_ir_rejects_multiple_activation_markers() -> None:
    try:
        parse_cnl_to_ir("Agency shall inspect records when notified if approved.")
    except ValueError as exc:
        assert "multiple_activation_markers" in str(exc)
    else:
        raise AssertionError("Expected ValueError for ambiguous activation markers")


def test_normalize_ir_maps_roles_and_duration() -> None:
    ir = parse_cnl_to_ir("Agency shall inspect records within 3 days.")
    frame = next(iter(ir.frames.values()))
    frame.roles["subject"] = frame.roles.pop("agent")

    normalized = normalize_ir(ir)
    nframe = next(iter(normalized.frames.values()))
    t = next(iter(normalized.temporals.values()))

    assert "agent" in nframe.roles
    assert "subject" not in nframe.roles
    assert t.expr.duration == "P3D"


def test_compilers_keep_deontic_wrapper_over_frame_ref() -> None:
    ir = parse_cnl_to_ir("Employer shall pay wages by 2026-12-31.")
    dcec = "\n".join(compile_ir_to_dcec(ir))
    tdfol = "\n".join(compile_ir_to_temporal_deontic_fol(ir))
    frame_ref = next(iter(ir.frames.keys()))

    assert f"O({frame_ref})" in dcec
    assert f"O({frame_ref},t)" in tdfol


def test_roundtrip_cnl_generation() -> None:
    ir = parse_cnl_to_ir("Processor may transfer data to regulator after authorization.")
    norm_ref = _first_norm_ref(ir)
    text = generate_cnl_from_ir(norm_ref, ir)

    assert "may" in text
    assert text.endswith(".")


def test_reasoner_api_produces_explainable_proof() -> None:
    ir = parse_cnl_to_ir("Controller shall file report within 2 days.")
    out = check_compliance({"ir": ir, "events": []}, {"at": "2026-03-01"})

    assert out["status"] == "non_compliant"
    assert out["proof_id"]

    explanation = explain_proof(out["proof_id"], format="nl")
    assert "Proof" in explanation["text"]
    assert explanation["steps"]


def test_proof_store_eviction_is_deterministic_and_explicit() -> None:
    previous = configure_v2_proof_store_max_entries(1)
    clear_v2_proof_store()
    try:
        out_a = check_compliance(
            {"ir": parse_cnl_to_ir("Controller shall report breach within 24 hours."), "events": []},
            {"at": "2026-03-01"},
        )
        out_b = check_compliance(
            {"ir": parse_cnl_to_ir("Vendor shall not disclose personal data."), "events": []},
            {"at": "2026-03-01"},
        )

        try:
            explain_proof(out_a["proof_id"], format="json")
        except KeyError as exc:
            assert "evicted proof_id" in str(exc)
        else:
            raise AssertionError("Expected evicted proof_id behavior")

        latest = explain_proof(out_b["proof_id"], format="json")
        assert latest["proof_id"] == out_b["proof_id"]
    finally:
        configure_v2_proof_store_max_entries(previous)
        clear_v2_proof_store()


def test_find_violations_uses_same_reasoning_contract() -> None:
    ir = parse_cnl_to_ir("Vendor shall not disclose personal data.")
    frame_ref = next(iter(ir.frames.keys()))

    out = find_violations(
        {
            "ir": ir,
            "events": [frame_ref],
            "facts": {},
        },
        ("2026-01-01", "2026-01-31"),
    )

    assert out["violations"]
    assert out["proof_id"]


def test_parse_cnl_to_ir_means_template_emits_definition_rule() -> None:
    ir = parse_cnl_to_ir("Personal data means information identifying a person.")

    assert len(ir.rules) == 1
    rule = next(iter(ir.rules.values()))
    assert rule.mode == "definition"
    assert rule.consequent.pred == "definition_of"
    assert rule.consequent.args[0] == "Personal data"


def test_parse_cnl_to_ir_includes_template_emits_member_rules() -> None:
    ir = parse_cnl_to_ir("Sensitive data includes health records, financial records, and biometrics.")

    members = sorted(r.consequent.args[1] for r in ir.rules.values() if r.consequent.pred == "includes_member")
    assert members == ["biometrics", "financial records", "health records"]


def test_validate_ir_v2_contract_accepts_parser_output_strict() -> None:
    ir = parse_cnl_to_ir("Controller shall report breach within 48 hours.")

    report = validate_ir_v2_contract(ir, strict=True)

    assert report["ok"] is True
    assert report["warnings"] == []


def test_validate_ir_v2_contract_missing_source_ref_strict_rejected() -> None:
    ir = parse_cnl_to_ir("Controller shall report breach within 48 hours.")
    norm = next(iter(ir.norms.values()))
    norm.source_ref = None

    try:
        validate_ir_v2_contract(ir, strict=True)
    except ValueError as exc:
        assert "missing_source_ref:norm" in str(exc)
        assert "V2_CONTRACT_MISSING_SOURCE_REF" in str(exc)
        assert isinstance(exc, IRContractValidationError)
        assert "V2_CONTRACT_MISSING_SOURCE_REF" in exc.error_codes
    else:
        raise AssertionError("Expected strict contract validation failure")


def test_validate_ir_v2_contract_missing_source_ref_non_strict_warns() -> None:
    ir = parse_cnl_to_ir("Controller shall report breach within 48 hours.")
    norm = next(iter(ir.norms.values()))
    norm.source_ref = None

    report = validate_ir_v2_contract(ir, strict=False)

    assert report["ok"] is True
    assert any("missing_source_ref:norm" in w for w in report["warnings"])
    assert "V2_CONTRACT_MISSING_SOURCE_REF" in report["warning_codes"]
    assert any(d["code"] == "V2_CONTRACT_MISSING_SOURCE_REF" for d in report["warning_details"])


def test_validate_v2_canonical_id_registry_accepts_parser_output() -> None:
    ir = parse_cnl_to_ir("Controller shall report breach within 48 hours.")

    report = validate_v2_canonical_id_registry(ir, strict=True)

    assert report["ok"] is True
    assert report["warnings"] == []


def test_validate_v2_canonical_id_registry_rejects_unknown_role_entity_ref() -> None:
    ir = parse_cnl_to_ir("Controller shall report breach within 48 hours.")
    frame = next(iter(ir.frames.values()))
    frame.roles["agent"] = "ent:missing"

    try:
        validate_v2_canonical_id_registry(ir, strict=True)
    except ValueError as exc:
        assert "unknown_role_entity_ref" in str(exc)
        assert "V2_IDREG_UNKNOWN_ROLE_ENTITY_REF" in str(exc)
        assert isinstance(exc, IDRegistryValidationError)
        assert "V2_IDREG_UNKNOWN_ROLE_ENTITY_REF" in exc.error_codes
    else:
        raise AssertionError("Expected ID registry validation failure")


def test_check_compliance_rejects_invalid_frame_reference() -> None:
    ir = parse_cnl_to_ir("Controller shall report breach within 48 hours.")
    frame_ref = next(iter(ir.frames.keys()))
    del ir.frames[frame_ref]

    try:
        check_compliance({"ir": ir, "events": []}, {"at": "2026-03-01"})
    except ValueError as exc:
        assert "unknown_target_frame_ref" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid contract")


def test_run_v2_pipeline_applies_hooks_and_prover() -> None:
    class _Optimizer:
        def optimize_ir(self, ir):
            return ir, {"semantic_equivalence_assertion": True, "drift_score": 0.0, "optimizer": "noop"}

    class _KG:
        def enrich_ir(self, ir):
            for frame in ir.frames.values():
                frame.attrs["kg_enriched"] = True
            return ir, {"kg": "noop-enrichment"}

    class _Prover:
        def prove(self, formulas, assumptions=None):
            return {"ok": True, "formula_count": len(formulas), "assumptions": assumptions or []}

    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        jurisdiction="us/federal",
        optimizer_hook=_Optimizer(),
        kg_hook=_KG(),
        prover_hook=_Prover(),
    )

    assert out["optimizer_report"]["applied"] is True
    assert out["kg_report"]["applied"] is True
    assert out["prover_report"]["applied"] is True
    assert out["contract_report"]["ok"] is True
    assert out["dcec"]
    assert out["tdfol"]


def test_run_v2_pipeline_rejects_optimizer_on_high_drift() -> None:
    class _BadOptimizer:
        def optimize_ir(self, ir):
            return ir, {"semantic_equivalence_assertion": False, "drift_score": 0.75, "optimizer": "bad"}

    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        optimizer_hook=_BadOptimizer(),
    )

    assert out["optimizer_report"]["applied"] is False
    assert out["optimizer_report"]["rejected"] is True
    assert "drift_threshold_exceeded" in out["optimizer_report"]["rejected_reason_codes"]
    assert "semantic_equivalence_assertion" in out["optimizer_report"]["rejected_reason_codes"]
    assert out["optimizer_report"]["failure_count"] == len(out["optimizer_report"]["rejected_reason_codes"])
    assert out["optimizer_report"]["decision_id"].startswith("opt_")



    def test_run_v2_pipeline_rejects_kg_semantic_mutation() -> None:
        class _MutatingKG:
            def enrich_ir(self, ir):
                frame = next(iter(ir.frames.values()))
                frame.predicate = "mutated_predicate"
                return ir, {"kg": "mutating", "accepted": True, "rejection_reasons": []}

        out = run_v2_pipeline(
            "Controller shall report breach within 48 hours.",
            kg_hook=_MutatingKG(),
        )

        assert out["kg_report"]["applied"] is False
        assert out["kg_report"]["rejected"] is True
        assert "frame_predicate_changed" in out["kg_report"]["rejected_reason_codes"]
        assert "frame_predicate_changed" in out["kg_report"]["invariant_failures"]


    def test_run_v2_pipeline_rejects_invalid_prover_envelope_payload() -> None:
        class _BadProver:
            def prove(self, formulas, assumptions=None):
                return {
                    "schema_version": "1.0",
                    "backend": "mock_smt",
                    "status": "ok",
                    "theorem": " and ".join(formulas),
                    "assumptions": list(assumptions or []),
                    "certificate": {
                        "certificate_id": "cert_bad",
                        "format": "smt-certificate-v1",
                        "normalized_hash": "0" * 64,
                        "payload": {
                            "backend": "mock_smt",
                            "format": "smt-certificate-v1",
                            # Intentionally omit required keys: solver, theorem_hash_hint
                        },
                    },
                }

        try:
            run_v2_pipeline(
                "Controller shall report breach within 48 hours.",
                prover_hook=_BadProver(),
            )
        except ValueError as exc:
            msg = str(exc)
            assert "invalid_prover_envelope:" in msg
            assert "prover_certificate_payload_missing_key:solver" in msg
            assert "prover_certificate_payload_missing_key:theorem_hash_hint" in msg
        else:
            raise AssertionError("Expected prover envelope validation failure")

def test_run_v2_pipeline_accepts_optimizer_on_drift_threshold_boundary() -> None:
    class _EdgeOptimizer:
        def optimize_ir(self, ir):
            return ir, {"semantic_equivalence_assertion": True, "drift_score": 0.05, "optimizer": "edge"}

    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        optimizer_hook=_EdgeOptimizer(),
        drift_threshold=0.05,
    )

    assert out["optimizer_report"]["applied"] is True
    assert out["optimizer_report"]["rejected"] is False
    assert out["optimizer_report"]["rejected_reason_codes"] == []
    assert out["optimizer_report"]["failure_count"] == 0
    assert out["optimizer_report"]["decision_id"].startswith("opt_")


def test_run_v2_pipeline_optimizer_decision_id_is_deterministic() -> None:
    class _EdgeOptimizer:
        def optimize_ir(self, ir):
            return ir, {"semantic_equivalence_assertion": True, "drift_score": 0.05, "optimizer": "edge"}

    out_a = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        optimizer_hook=_EdgeOptimizer(),
        drift_threshold=0.05,
    )
    out_b = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        optimizer_hook=_EdgeOptimizer(),
        drift_threshold=0.05,
    )

    assert out_a["optimizer_report"]["decision_id"] == out_b["optimizer_report"]["decision_id"]


def test_run_v2_pipeline_rejects_optimizer_modality_mutation() -> None:
    class _MutatingOptimizer:
        def optimize_ir(self, ir):
            norm = next(iter(ir.norms.values()))
            norm.op = DeonticOpV2.P
            return ir, {"semantic_equivalence_assertion": True, "drift_score": 0.0, "optimizer": "mutating"}

    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        optimizer_hook=_MutatingOptimizer(),
    )

    assert out["optimizer_report"]["applied"] is False
    assert out["optimizer_report"]["rejected"] is True
    assert "modality_changed" in out["optimizer_report"]["rejected_reason_codes"]
    assert "modality_changed" in out["optimizer_report"]["invariant_failures"]


def test_run_v2_pipeline_rejects_optimizer_target_frame_mutation() -> None:
    class _MutatingOptimizer:
        def optimize_ir(self, ir):
            norm = next(iter(ir.norms.values()))
            norm.target_frame_ref = "frm:mutated"
            return ir, {"semantic_equivalence_assertion": True, "drift_score": 0.0, "optimizer": "mutating"}

    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        optimizer_hook=_MutatingOptimizer(),
    )

    assert out["optimizer_report"]["applied"] is False
    assert out["optimizer_report"]["rejected"] is True
    assert "target_frame_changed" in out["optimizer_report"]["rejected_reason_codes"]
    assert "target_frame_changed" in out["optimizer_report"]["invariant_failures"]


def test_run_v2_pipeline_rejects_kg_and_preserves_ir_when_kg_not_accepted() -> None:
    class _RejectKG:
        def enrich_ir(self, ir):
            for frame in ir.frames.values():
                frame.attrs["kg_enriched"] = True
            return ir, {"accepted": False, "rejection_reasons": ["relation_growth_factor"]}

    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        kg_hook=_RejectKG(),
    )

    assert out["kg_report"]["applied"] is False
    assert out["kg_report"]["rejected"] is True
    assert "relation_growth_factor" in out["kg_report"]["rejected_reason_codes"]
    assert "kg_drift_policy_rejected" in out["kg_report"]["rejected_reason_codes"]
    assert out["kg_report"]["summary"]["entity_write_count"] == 0
    assert out["kg_report"]["summary"]["relation_write_count"] == 0
    frame = next(iter(out["ir"].frames.values()))
    assert "kg_enriched" not in frame.attrs


def test_run_v2_pipeline_with_defaults_wires_existing_modules() -> None:
    out = run_v2_pipeline_with_defaults(
        "Controller shall report breach within 48 hours.",
        jurisdiction="us/federal",
        enable_optimizer=True,
        enable_kg=True,
        enable_prover=True,
        prover_backend_id="mock_smt",
    )

    assert out["optimizer_report"]["applied"] is True
    assert out["kg_report"]["applied"] is True
    assert out["kg_report"]["summary"]["entity_link_count"] >= 0
    assert out["kg_report"]["summary"]["relation_write_count"] >= 0
    assert out["prover_report"]["applied"] is True
    assert out["prover_report"]["dcec"]["backend"] == "mock_smt"
    assert out["prover_report"]["dcec"]["schema_version"] == "1.0"
    assert out["prover_report"]["dcec"]["certificate"]["certificate_id"].startswith("cert_")
    assert len(out["prover_report"]["dcec"]["certificate"]["normalized_hash"]) == 64


def test_run_v2_pipeline_without_kg_hook_has_stable_kg_summary_shape() -> None:
    out = run_v2_pipeline(
        "Controller shall report breach within 48 hours.",
        jurisdiction="us/federal",
        kg_hook=None,
    )

    assert out["kg_report"]["applied"] is False
    assert out["kg_report"]["rejected"] is False
    assert out["kg_report"]["rejected_reason_codes"] == []
    assert out["kg_report"]["summary"] == {
        "entity_link_count": 0,
        "relation_candidate_count": 0,
        "entity_write_count": 0,
        "relation_write_count": 0,
    }
