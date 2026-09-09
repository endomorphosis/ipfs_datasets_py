"""PCPR-014: stabilize semantic APIs and ContextPack contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.semantic_apis import (
    CLOSED_RELEASE_OUTCOMES,
    CONTEXT_PACK_INTERFACE,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OutcomeProbe,
    PCPR_014_GOAL_ID,
    PCPR_014_TASK_ID,
    SEMANTIC_API_NAMES,
    SemanticApiAdmissionError,
    SemanticApiCanonicalError,
    admit_semantic_request,
    current_head_runtime_probes,
    current_head_static_probes,
    pcpr_014_receipt_promotion,
    probe_semantic_runtime,
    qualify_current_head_semantic_apis,
    qualify_semantic_apis_canonical,
    semantic_api_manifest,
    semantic_api_spec,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST
from ipfs_datasets_py.proof_context.context_pack import (
    CANONICAL_INTERFACE,
    DATASETS_CONTEXT_PACK_CANONICAL,
    INTERFACE as CONTEXT_PACK_V01_INTERFACE,
    V01_MATURITY,
    admit_datasets_context_pack,
    build_context_pack,
)
from ipfs_datasets_py.proof_context.contracts import (
    OpaqueSourceRequiredError,
    StaleContextError,
    UnavailableContextError,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _cid(label: str) -> str:
    return cid_v1(label.encode("utf-8"))


def _pack_kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "PCPR-014",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surround"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "capsule_cids": (_cid("capsule"),),
    }
    fields.update(overrides)
    return fields


def test_closed_vocabularies_match_pcpr_014_requirements() -> None:
    assert PCPR_014_TASK_ID == "PCPR-014"
    assert PCPR_014_GOAL_ID == "PCPR-G220"
    assert INTERFACE == "DatasetsSemanticApiCatalog@1"
    assert CONTEXT_PACK_INTERFACE == "DatasetsContextPack@1"
    assert CANONICAL_INTERFACE == CONTEXT_PACK_INTERFACE
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith("test_pcpr_014_semantic_apis.py")
    assert SEMANTIC_API_NAMES == (
        "canonical_ir_identity",
        "source_lineage",
        "context_pack",
        "proof_obligation",
        "proof_result_validation",
        "translation_receipt",
        "interpolation",
        "cegar",
        "incremental_smt",
        "source_rights_manifest",
    )
    manifest = semantic_api_manifest()
    assert manifest["interface"] == INTERFACE
    assert manifest["v01_context_pack_maturity"] == "compatibility_only"
    assert manifest["pgir_semantic_api_maturity"] == "compatibility_only"
    with pytest.raises(KeyError, match="unknown semantic operation"):
        semantic_api_spec("promote")


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_semantic_apis()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.semantic_apis_canonical is True
    assert verdict.context_pack_canonical is True
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_014_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["semantic_apis_canonical"] is True
    assert section["context_pack_canonical"] is True
    assert section["live_solver_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_canonical_context_pack_and_catalog() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["canonical_ir_identity_profile"].present is True
    assert probes["source_lineage_schemas"].present is True
    assert probes["context_pack_canonical_interface"].present is True
    assert probes["context_pack_v01_compatibility_only"].present is True
    assert probes["proof_obligation_schema"].present is True
    assert probes["proof_result_class"].present is True
    assert probes["translation_receipt_interface"].present is True
    assert probes["interpolation_interface"].present is True
    assert probes["cegar_interface"].present is True
    assert probes["incremental_smt_interface"].present is True
    assert probes["source_rights_record"].present is True
    assert probes["manifest_advertises_context_pack"].present is True
    assert probes["catalog_closed"].present is True
    assert probes["pgir_semantic_api_not_canonical"].present is True
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["live_solver_qualification"].live is False


def test_context_pack_v1_is_canonical_and_v01_is_compatibility() -> None:
    assert DATASETS_CONTEXT_PACK_CANONICAL is True
    assert CANONICAL_INTERFACE == "DatasetsContextPack@1"
    assert CONTEXT_PACK_V01_INTERFACE == "DatasetsContextPackAuthority@0.1"
    assert V01_MATURITY == "compatibility_only"
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsContextPack@1"] == "1"
    assert versions["DatasetsContextPackAuthority@0.1"] == "0.1"
    assert versions["CanonicalIRIdentity@1"] == "1"
    assert versions["DatasetsSemanticApiCatalog@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots["datasets_context_pack"].endswith(
        "datasets-context-pack@1"
    )
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["context_pack"] == "1"


def test_v01_builder_remains_fail_closed_when_optional_cid_profile_is_present() -> None:
    try:
        from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
    except Exception:
        cid_for_bytes = None  # type: ignore[assignment]
    if cid_for_bytes is None:
        pytest.skip("software-contract CID profile is optional and unavailable")
    try:
        cid_for_bytes(b"pcpr-014")
    except ModuleNotFoundError:
        pytest.skip("multiformats is unavailable in the sealed environment")
    a = build_context_pack(**_pack_kwargs())
    b = build_context_pack(**_pack_kwargs())
    assert a.pack_cid == b.pack_cid
    with pytest.raises(StaleContextError):
        build_context_pack(**_pack_kwargs(freshness="stale"))
    with pytest.raises(UnavailableContextError):
        build_context_pack(**_pack_kwargs(unavailable=True))
    with pytest.raises(OpaqueSourceRequiredError):
        build_context_pack(**_pack_kwargs(opaque=True, source_tree_oid="deadbeef"))


def test_context_pack_v1_identity_is_deterministic_and_not_v01() -> None:
    a = admit_datasets_context_pack(_pack_kwargs())
    b = admit_datasets_context_pack(_pack_kwargs())
    assert a.pack_cid == b.pack_cid
    assert a.interface == "DatasetsContextPack@1"
    assert a.schema == "ipfs_datasets_py/datasets-context-pack@1"
    assert a.v01_maturity == "compatibility_only"
    assert a.v01_compatibility_interface == CONTEXT_PACK_V01_INTERFACE
    assert a.pack_cid.startswith("b")
    with pytest.raises(StaleContextError):
        admit_datasets_context_pack(_pack_kwargs(freshness="stale"))
    with pytest.raises(UnavailableContextError):
        admit_datasets_context_pack(_pack_kwargs(unavailable=True))
    with pytest.raises(OpaqueSourceRequiredError):
        admit_datasets_context_pack(_pack_kwargs(opaque=True, source_tree_oid="deadbeef"))


def test_freeform_and_advisory_cannot_mint_context_pack() -> None:
    with pytest.raises(SemanticApiAdmissionError, match="free-form|cannot mint"):
        admit_semantic_request(
            "context_pack",
            {**_pack_kwargs(), "backend_request": {"request_id": "forged"}},
        )
    with pytest.raises(SemanticApiAdmissionError, match="advisory"):
        admit_semantic_request("context_pack", {**_pack_kwargs(), "advisory": True})
    with pytest.raises(SemanticApiAdmissionError, match="executable"):
        admit_semantic_request("context_pack", {**_pack_kwargs(), "executable": True})


def test_canonical_ir_identity_is_deterministic() -> None:
    payload = {
        "domain": "pcpr.014.identity",
        "schema_version": "ir-claim/v1",
        "payload": {"statement": "P"},
    }
    a = admit_semantic_request("canonical_ir_identity", payload)
    b = admit_semantic_request("canonical_ir_identity", payload)
    assert a.identity_cid == b.identity_cid
    assert a.live is False
    assert a.executable is False
    with pytest.raises(SemanticApiAdmissionError, match="free-form"):
        admit_semantic_request(
            "canonical_ir_identity",
            {**payload, "extra": True},
        )


def test_proof_obligation_and_rights_fail_closed() -> None:
    obligation = admit_semantic_request(
        "proof_obligation",
        {"obligation_id": "obl:pcpr-014", "statement": "P"},
    )
    assert obligation.identity_cid
    assert obligation.executable is False
    with pytest.raises(SemanticApiAdmissionError, match="unknown"):
        admit_semantic_request(
            "proof_obligation",
            {"obligation_id": "obl:pcpr-014", "statement": "P", "proved": True},
        )
    with pytest.raises(SemanticApiAdmissionError, match="resolved"):
        admit_semantic_request(
            "source_rights_manifest",
            {
                "disposition": "admitted",
                "license_expression": "cc0-1.0",
                "source_rights_status": "unresolved",
                "transformation_rights_status": "unresolved",
                "scope": "pcpr-014",
            },
        )
    rights = admit_semantic_request(
        "source_rights_manifest",
        {
            "disposition": "quarantined",
            "license_expression": "cc0-1.0",
            "source_rights_status": "unresolved",
            "transformation_rights_status": "unresolved",
            "scope": "pcpr-014",
        },
    )
    assert rights.live is False


def test_freeform_cannot_mint_proof_result_or_translation_receipt() -> None:
    with pytest.raises(SemanticApiAdmissionError, match="ProofResult"):
        admit_semantic_request(
            "proof_result_validation",
            {"ok": True, "status": "proved"},
        )
    with pytest.raises(SemanticApiAdmissionError, match="translation"):
        admit_semantic_request("translation_receipt", {"preserved": True})
    with pytest.raises(SemanticApiAdmissionError, match="required"):
        admit_semantic_request("translation_receipt", None)


def test_executable_ops_require_bounds() -> None:
    with pytest.raises(SemanticApiAdmissionError, match="bounds"):
        admit_semantic_request("interpolation", {"theory": "QF_LIA"})
    with pytest.raises(SemanticApiAdmissionError, match="budget"):
        admit_semantic_request("cegar", {"system": "QF_LIA"})
    with pytest.raises(SemanticApiAdmissionError, match="timeout"):
        admit_semantic_request(
            "incremental_smt",
            {
                "provider": "z3",
                "provider_version": "unavailable",
                "logic": "QF_LIA",
                "translator_identity": "pcpr-014",
                "theory_fingerprint": "QF_LIA@1",
                "policy_root": "policy",
                "configuration_root": "config",
                "environment_root": "env",
            },
        )
    interpolation = admit_semantic_request(
        "interpolation",
        {
            "bounds": {
                "timeout_ms": 1000,
                "memory_limit_mib": 64,
                "max_symbols": 8,
                "max_term_nodes": 16,
                "theory": "QF_LIA",
            }
        },
    )
    assert interpolation.executable is True
    assert interpolation.live is False
    cegar = admit_semantic_request("cegar", {"budget": {"timeout_ms": 1000}})
    assert cegar.executable is True
    assert cegar.live is False
    smt = admit_semantic_request(
        "incremental_smt",
        {
            "provider": "z3",
            "provider_version": "unavailable",
            "logic": "QF_LIA",
            "translator_identity": "pcpr-014",
            "theory_fingerprint": "QF_LIA@1",
            "policy_root": "policy",
            "configuration_root": "config",
            "environment_root": "env",
            "timeout_ms": 1000,
            "memory_limit_mib": 64,
        },
    )
    assert smt.executable is True
    assert smt.live is False
    assert smt.identity_cid


def test_runtime_probes_are_measured_not_live() -> None:
    observation = probe_semantic_runtime()
    assert observation["status"] == "observed"
    assert observation["evidence_kind"] == "measured"
    assert observation["live"] is False
    assert observation["simulated_represented_as_live"] is False
    assert observation["identity_deterministic"] is True
    assert observation["context_pack_deterministic"] is True
    assert observation["freeform_pack"] is False
    assert observation["advisory_pack"] is False
    assert observation["freeform_proof"] is False
    assert observation["freeform_translation"] is False
    assert observation["interpolation_missing_bounds"] is False
    assert observation["cegar_missing_bounds"] is False
    assert observation["smt_missing_bounds"] is False
    assert observation["unresolved_admitted"] is False
    for probe in current_head_runtime_probes():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False
        if probe.probe_id in {
            "freeform_context_pack_admitted",
            "advisory_context_pack_admitted",
            "freeform_proof_result_admitted",
            "freeform_translation_receipt_admitted",
            "executable_interpolation_missing_bounds_admitted",
            "executable_cegar_missing_bounds_admitted",
            "executable_incremental_smt_missing_bounds_admitted",
            "admitted_unresolved_rights",
            "runtime_unavailable_represented_as_live",
        }:
            assert probe.present is False
        else:
            assert probe.present is True


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(SemanticApiCanonicalError, match="simulated"):
        qualify_semantic_apis_canonical(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_source_files_exist_under_datasets_root() -> None:
    assert (_PACKAGE_ROOT / "ipfs_datasets_py" / "assurance" / "semantic_apis.py").is_file()
    assert (
        _PACKAGE_ROOT / "ipfs_datasets_py" / "proof_context" / "context_pack.py"
    ).is_file()
