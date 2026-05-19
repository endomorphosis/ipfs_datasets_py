from __future__ import annotations


def test_logic_manifest_covers_core_logic_families() -> None:
    from ipfs_datasets_py.logic.submodule_registry import logic_integration_manifest

    manifest = logic_integration_manifest()
    names = {entry["name"] for entry in manifest["submodules"]}

    expected = {
        "CEC",
        "TDFOL",
        "bridge",
        "common",
        "deontic",
        "external_provers",
        "flogic",
        "flogic_optimizer",
        "fol",
        "integration",
        "integrations",
        "knowledge_graphs",
        "modal",
        "observability",
        "security",
        "types",
        "zkp",
    }

    assert expected <= names
    assert manifest["submodule_count"] == len(manifest["submodules"])

    roles = manifest["roles"]
    for role in ("legal_ir", "frame_logic", "prover", "kg", "loss", "zkp"):
        assert role in roles
        assert roles[role]


def test_required_logic_submodules_import_from_registry() -> None:
    from ipfs_datasets_py.logic.submodule_registry import logic_submodule_import_report

    report = logic_submodule_import_report()
    failures = {
        name: entry
        for name, entry in report.items()
        if entry.get("ok") is False
    }

    assert failures == {}
    assert report["ErgoAI"]["skipped"] is True
    assert report["tools"]["skipped"] is True


def test_logic_namespace_and_api_expose_registry_helpers() -> None:
    import ipfs_datasets_py.logic as logic
    import ipfs_datasets_py.logic.api as api

    expected = {
        "LogicSubmoduleSpec",
        "logic_integration_manifest",
        "logic_optimizer_scope_for_component",
        "logic_optimizer_target_file_hints",
        "logic_submodule_import_report",
        "logic_submodule_names",
        "logic_submodule_spec",
        "logic_submodule_specs",
    }

    assert expected <= set(logic.__all__)
    assert expected <= set(api.__all__)
    assert logic.logic_submodule_names() == api.logic_submodule_names()


def test_optimizer_hints_include_non_modal_logic_lanes() -> None:
    from ipfs_datasets_py.logic.submodule_registry import (
        logic_optimizer_scope_for_component,
        logic_optimizer_target_file_hints,
    )

    hints = logic_optimizer_target_file_hints()

    assert "modal.frame_logic" in hints
    assert "bridge.registry" in hints
    assert "deontic.ir" in hints
    assert "TDFOL.prover" in hints
    assert "CEC.native" in hints
    assert "external_provers.router" in hints
    assert "knowledge_graphs.neo4j_compat" in hints

    assert logic_optimizer_scope_for_component("modal.compiler.registry") == "compiler_registry"
    assert logic_optimizer_scope_for_component("bridge.registry") == "bridge"
    assert logic_optimizer_scope_for_component("deontic.ir") == "deontic"
    assert logic_optimizer_scope_for_component("TDFOL.prover") == "tdfol"
    assert logic_optimizer_scope_for_component("external_provers.router") == "external_provers"


def test_modal_frame_logic_bridge_remains_neo4j_compatible() -> None:
    from ipfs_datasets_py.logic.modal import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
        modal_ir_to_neo4j_graph_data,
    )

    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(use_flogic=True)
    )
    result = codec.encode(
        "The agency shall publish notice before the permit takes effect.",
        document_id="registry-smoke",
        citation="Registry Smoke",
        source="unit_test",
    )
    graph_data = modal_ir_to_neo4j_graph_data(result.modal_ir)

    assert result.modal_ir.frame_logic.to_triples()
    assert graph_data.metadata["neo4j_compatible"] is True
    assert graph_data.node_count > 0
    assert graph_data.relationship_count > 0
