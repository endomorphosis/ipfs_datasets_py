"""Independent contract tests for SPAR-008 dynamic Python frontier adapters."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "0")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "0")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.software_contracts.content import (  # noqa: E402
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (  # noqa: E402
    AnalysisConfidence,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (  # noqa: E402
    EvidenceClass,
)
from ipfs_datasets_py.semantic_refactoring.dynamic_frontier import (  # noqa: E402
    ABSENCE_DETECTABLE_KINDS,
    AUTHORITY,
    AUTHORITY_OWNER,
    DEFAULT_HERMETIC_PROFILE,
    DUCKLAKE_IS_AUTHORITY,
    DYNAMIC_PYTHON_FRONTIER_INTERFACE,
    DYNAMIC_PYTHON_FRONTIER_SCHEMA,
    FORBIDDEN_OBSERVATIONAL_FIELDS,
    FRONTIER_CAN_AUTHORIZE_COMPLETION,
    FRONTIER_CAN_AUTHORIZE_TRANSITION,
    FRONTIER_CAN_CREATE_AUTHORITY,
    FRONTIER_CID_CODEC,
    FRONTIER_CID_PROFILE,
    INVENTORY_KIND_LABELS,
    KIND_FAMILY,
    KIND_INVENTORY_LABEL,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    NETWORK_DENY,
    RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    UNKNOWN_WIDENS_FRONTIER,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    AutonomyTier,
    DynamicFinding,
    DynamicFrontierError,
    DynamicPythonFrontier,
    DynamicRiskKind,
    HermeticObservationProfile,
    HermeticRuntimeEvidenceAdapter,
    HermeticRuntimeObservation,
    ObservationStatus,
    Presence,
    analyze_source,
    autonomy_for_finding,
    decode_canonical_frontier,
    encode_canonical_frontier,
    family_for_kind,
    frontier_cid_profile,
    kind_for_inventory_label,
    lowest_autonomy,
    provider_free_exports,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "dynamic_frontier.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/dynamic_frontier.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_dynamic_frontier.py",
)
TREE_ID = "fbc6fa1ddefb2f9ecb7b5c718d618e3b60aa3051"
CAPSULE_TYPES = (
    "FunctionSemanticCapsule",
    "MethodSemanticCapsule",
    "ClassSemanticCapsule",
    "TopLevelBlockCapsule",
    "ModuleSemanticCapsule",
    "PackageSemanticCapsule",
    "CallsiteSemanticCapsule",
    "StateOwnerCapsule",
    "RegistrationCapsule",
    "ResourceLifecycleCapsule",
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _analyze(source: str, *, subject: str = "module:pkg.mod") -> DynamicPythonFrontier:
    return analyze_source(source, tree_id=TREE_ID, subject_cid=_cid(subject))


def _finding(
    kind: DynamicRiskKind = DynamicRiskKind.GETATTR_SETATTR_DELATTR,
    **overrides: Any,
) -> DynamicFinding:
    fields: dict[str, Any] = {
        "kind": kind,
        "presence": Presence.PRESENT,
        "confidence": AnalysisConfidence.EXACT,
        "evidence_class": EvidenceClass.EXACT_STATIC_FACT,
        "subject_cid": _cid("module:pkg.mod"),
        "source_cid": _cid("source:pkg.mod"),
        "tree_id": TREE_ID,
        "lineno": 1,
        "col_offset": 0,
        "name": "getattr",
        "unresolved": False,
    }
    fields.update(overrides)
    return DynamicFinding(**fields)


def _unknown(kind: DynamicRiskKind) -> DynamicFinding:
    return DynamicFinding(
        kind=kind,
        presence=Presence.UNKNOWN,
        confidence=AnalysisConfidence.CONSERVATIVE,
        evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
        subject_cid=_cid("module:pkg.mod"),
        source_cid=_cid("source:pkg.mod"),
        tree_id=TREE_ID,
        unresolved=True,
    )


def _absent(kind: DynamicRiskKind) -> DynamicFinding:
    return DynamicFinding(
        kind=kind,
        presence=Presence.ABSENT,
        confidence=AnalysisConfidence.EXACT,
        evidence_class=EvidenceClass.EXACT_STATIC_FACT,
        subject_cid=_cid("module:pkg.mod"),
        source_cid=_cid("source:pkg.mod"),
        tree_id=TREE_ID,
        unresolved=False,
    )


def _complete_findings(
    extra: tuple[DynamicFinding, ...] = (),
) -> tuple[DynamicFinding, ...]:
    present_kinds = {DynamicRiskKind(item.kind) for item in extra}
    filled: list[DynamicFinding] = list(extra)
    for kind in DynamicRiskKind:
        if kind in present_kinds:
            continue
        if kind in ABSENCE_DETECTABLE_KINDS:
            filled.append(_absent(kind))
        else:
            filled.append(_unknown(kind))
    return tuple(filled)


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-008"
    assert DYNAMIC_PYTHON_FRONTIER_INTERFACE == "DynamicPythonFrontier@1"
    assert DYNAMIC_PYTHON_FRONTIER_SCHEMA.endswith("@1")
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert FRONTIER_CAN_AUTHORIZE_COMPLETION is False
    assert FRONTIER_CAN_AUTHORIZE_TRANSITION is False
    assert FRONTIER_CAN_CREATE_AUTHORITY is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False
    assert RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT is True
    assert UNKNOWN_WIDENS_FRONTIER is True


def test_inventory_labels_cover_sealed_risk_catalog() -> None:
    catalog = json.loads(
        (INVENTORY / "dynamic_python_risk_inventory.json").read_text(encoding="utf-8")
    )
    labels = tuple(item["kind"] for item in catalog["risks"])
    assert labels == INVENTORY_KIND_LABELS
    assert tuple(KIND_INVENTORY_LABEL[kind] for kind in DynamicRiskKind) == labels
    assert set(KIND_FAMILY) == set(DynamicRiskKind)
    for label in labels:
        kind = kind_for_inventory_label(label)
        assert KIND_INVENTORY_LABEL[kind] == label
        assert family_for_kind(kind) in set(KIND_FAMILY.values())
    assert catalog["rule"] == "unknown widens the dynamic frontier and lowers autonomy"


def test_clean_module_does_not_hide_unknown_inventory_kinds() -> None:
    frontier = _analyze("VALUE = 1\n\ndef answer() -> int:\n    return VALUE\n")
    covered = {item.kind for item in frontier.findings}
    assert covered == {kind.value for kind in DynamicRiskKind}
    assert frontier.unknown_kinds
    assert AutonomyTier(frontier.autonomy_tier) in {AutonomyTier.D, AutonomyTier.E}
    present = [
        item for item in frontier.findings if item.presence == Presence.PRESENT.value
    ]
    assert present == []
    getattr_finding = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.GETATTR_SETATTR_DELATTR.value
    )
    assert getattr_finding.presence == Presence.ABSENT.value
    assert getattr_finding.evidence_class == EvidenceClass.EXACT_STATIC_FACT.value
    generated = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.GENERATED_CODE.value
    )
    assert generated.presence == Presence.UNKNOWN.value
    assert generated.unresolved is True


def test_reflection_and_dynamic_import_are_typed_present_findings() -> None:
    source = (
        "import importlib\n"
        "def load(name):\n"
        "    mod = importlib.import_module(name)\n"
        "    return getattr(mod, 'value')\n"
    )
    frontier = _analyze(source)
    kinds = {
        item.kind
        for item in frontier.findings
        if item.presence == Presence.PRESENT.value
    }
    assert DynamicRiskKind.GETATTR_SETATTR_DELATTR.value in kinds
    assert DynamicRiskKind.DYNAMIC_IMPORT.value in kinds
    getattr_finding = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.GETATTR_SETATTR_DELATTR.value
        and item.presence == Presence.PRESENT.value
    )
    assert getattr_finding.evidence_class == EvidenceClass.EXACT_STATIC_FACT.value
    assert getattr_finding.confidence == AnalysisConfidence.EXACT.value
    assert getattr_finding.autonomy_tier == AutonomyTier.D.value
    dynamic = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.DYNAMIC_IMPORT.value
        and item.presence == Presence.PRESENT.value
    )
    assert dynamic.name.endswith("import_module") or "importlib" in dynamic.name


def test_eval_and_variable_getattr_are_not_hidden() -> None:
    source = "def run(name, body):\n    obj = eval(body)\n    return getattr(obj, name)\n"
    frontier = _analyze(source)
    eval_finding = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.EVAL_EXEC_COMPILE.value
        and item.presence == Presence.PRESENT.value
    )
    getattr_finding = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.GETATTR_SETATTR_DELATTR.value
        and item.presence == Presence.PRESENT.value
    )
    assert eval_finding.name == "eval"
    assert getattr_finding.confidence == AnalysisConfidence.CONSERVATIVE.value
    assert getattr_finding.evidence_class == EvidenceClass.CONSERVATIVE_MAY_FACT.value
    assert getattr_finding.unresolved is True


def test_registration_framework_ffi_and_runtime_patterns() -> None:
    source = (
        "import ctypes\n"
        "import atexit\n"
        "import click\n"
        "from contextvars import ContextVar\n"
        "\n"
        "FLAG = ContextVar('flag')\n"
        "\n"
        "class Box(metaclass=type):\n"
        "    def __get__(self, obj, owner=None):\n"
        "        return obj\n"
        "\n"
        "@click.command()\n"
        "def build():\n"
        "    atexit.register(lambda: FLAG.get())\n"
        "    return ctypes.c_int(1)\n"
        "\n"
        "def __getattr__(name):\n"
        "    return name\n"
    )
    frontier = _analyze(source)
    present = {
        item.kind
        for item in frontier.findings
        if item.presence == Presence.PRESENT.value
    }
    assert DynamicRiskKind.NATIVE_FFI.value in present
    assert DynamicRiskKind.SIGNAL_ATEXIT.value in present
    assert DynamicRiskKind.CLI_REGISTRATION.value in present
    assert DynamicRiskKind.CONTEXT_THREAD_TASK_LOCAL.value in present
    assert DynamicRiskKind.METACLASS_DESCRIPTOR.value in present
    assert DynamicRiskKind.DECORATOR_SIDE_EFFECT.value in present
    assert DynamicRiskKind.MODULE_GETATTR_DIR.value in present
    assert DynamicRiskKind.HIGHER_ORDER.value in present
    assert DynamicRiskKind.CLOSURE_NONLOCAL.value in present


def test_hiding_an_inventory_kind_is_rejected() -> None:
    with pytest.raises(DynamicFrontierError, match="hides unknown"):
        DynamicPythonFrontier(
            tree_id=TREE_ID,
            subject_cid=_cid("module:pkg.mod"),
            source_cid=_cid("source:pkg.mod"),
            findings=(_finding(),),
        )


def test_unknown_presence_lowers_autonomy_and_opaque_is_tier_e() -> None:
    assert (
        autonomy_for_finding(
            presence=Presence.UNKNOWN.value,
            confidence=AnalysisConfidence.CONSERVATIVE.value,
            evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT.value,
        )
        == AutonomyTier.D.value
    )
    assert (
        autonomy_for_finding(
            presence=Presence.UNKNOWN.value,
            confidence=AnalysisConfidence.OPAQUE.value,
            evidence_class=EvidenceClass.UNKNOWN.value,
        )
        == AutonomyTier.E.value
    )
    opaque = DynamicFinding(
        kind=DynamicRiskKind.GENERATED_CODE,
        presence=Presence.UNKNOWN,
        confidence=AnalysisConfidence.OPAQUE,
        evidence_class=EvidenceClass.UNKNOWN,
        subject_cid=_cid("module:pkg.mod"),
        source_cid=_cid("source:pkg.mod"),
        tree_id=TREE_ID,
        unresolved=True,
    )
    frontier = DynamicPythonFrontier(
        tree_id=TREE_ID,
        subject_cid=_cid("module:pkg.mod"),
        source_cid=_cid("source:pkg.mod"),
        findings=_complete_findings((opaque,)),
    )
    assert frontier.autonomy_tier == AutonomyTier.E.value
    assert DynamicRiskKind.GENERATED_CODE.value in frontier.unknown_kinds
    assert lowest_autonomy(("A", "D")) == "D"


def test_evidence_classes_stay_separate() -> None:
    with pytest.raises(DynamicFrontierError, match="exact_static_fact"):
        _finding(
            presence=Presence.PRESENT,
            confidence=AnalysisConfidence.EXACT,
            evidence_class=EvidenceClass.RUNTIME_OBSERVATION,
        )
    with pytest.raises(DynamicFrontierError, match="runtime observation cannot be"):
        HermeticRuntimeObservation(
            finding_cid=_cid("finding"),
            profile_cid=DEFAULT_HERMETIC_PROFILE.profile_cid,
            status=ObservationStatus.OBSERVED,
            evidence_class=EvidenceClass.EXACT_STATIC_FACT,
        )
    with pytest.raises(DynamicFrontierError, match="cannot prove absence"):
        _finding(
            presence=Presence.ABSENT,
            confidence=AnalysisConfidence.CONSERVATIVE,
            evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
            unresolved=True,
        )


def test_observational_fields_are_excluded_from_identity() -> None:
    finding = _finding()
    payload = finding.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(DynamicFrontierError, match="observational"):
        DynamicFinding.from_dict(payload)
    for name in ("timestamp", "local_path", "model_output", "prompt"):
        assert name in FORBIDDEN_OBSERVATIONAL_FIELDS


def test_finding_and_frontier_cids_reverify() -> None:
    finding = _finding()
    cloned = DynamicFinding.from_dict(finding.to_dict())
    assert cloned.finding_cid == finding.finding_cid
    assert cloned.finding_cid == cid_for_structured(finding.identity_payload())
    frontier = DynamicPythonFrontier(
        tree_id=TREE_ID,
        subject_cid=_cid("module:pkg.mod"),
        source_cid=_cid("source:pkg.mod"),
        findings=_complete_findings((finding,)),
    )
    encoded = encode_canonical_frontier(frontier)
    assert encoded == frontier.canonical_bytes()
    assert decode_canonical_frontier(encoded).frontier_cid == frontier.frontier_cid
    mutated = frontier.to_dict()
    mutated["frontier_cid"] = _cid("not-the-frontier")
    with pytest.raises(DynamicFrontierError, match="does not verify"):
        DynamicPythonFrontier.from_dict(mutated)


def test_hermetic_adapter_cannot_upgrade_or_hide_unknowns() -> None:
    frontier = _analyze(
        "def load(name):\n    return getattr(__import__('pkg'), name)\n"
    )
    present = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.GETATTR_SETATTR_DELATTR.value
        and item.presence == Presence.PRESENT.value
    )
    adapter = HermeticRuntimeEvidenceAdapter()
    assert adapter.profile.network == NETWORK_DENY
    assert adapter.profile.allow_exec is False
    observed = adapter.observe(frontier, present)
    assert observed.evidence_class != EvidenceClass.EXACT_STATIC_FACT.value
    assert observed.status == ObservationStatus.UNAVAILABLE.value
    attached = adapter.attach(frontier, present)
    assert attached.unknown_kinds == frontier.unknown_kinds
    assert {item.finding_cid for item in attached.findings} == {
        item.finding_cid for item in frontier.findings
    }
    eval_frontier = _analyze("def run(body):\n    return eval(body)\n")
    eval_finding = next(
        item
        for item in eval_frontier.findings
        if item.kind == DynamicRiskKind.EVAL_EXEC_COMPILE.value
        and item.presence == Presence.PRESENT.value
    )
    blocked = adapter.observe(eval_frontier, eval_finding)
    assert blocked.status == ObservationStatus.UNSUPPORTED.value
    unknown = next(
        item
        for item in frontier.findings
        if item.presence == Presence.UNKNOWN.value
    )
    leftover = adapter.observe(frontier, unknown)
    assert leftover.status == ObservationStatus.UNAVAILABLE.value
    with pytest.raises(DynamicFrontierError, match="network=deny"):
        HermeticObservationProfile(network="allow")
    with pytest.raises(DynamicFrontierError, match="implicit install"):
        HermeticObservationProfile(implicit_install=True)
    with pytest.raises(DynamicFrontierError, match="subprocesses"):
        HermeticObservationProfile(subprocesses=1)


def test_unparseable_source_is_a_typed_terminal() -> None:
    with pytest.raises(DynamicFrontierError, match="parseable Python"):
        _analyze("def broken(\n")


def test_provider_free_exports_and_no_provider_imports() -> None:
    exports = provider_free_exports()
    assert exports == tuple(sorted(exports))
    forbidden_export_names = {
        "openai",
        "anthropic",
        "torch",
        "transformers",
        "model_output",
        "SemanticCapsuleCompiler",
        "compile_semantic_capsule",
    }
    assert forbidden_export_names.isdisjoint(set(exports))
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "openai" not in imported
    assert "anthropic" not in imported
    assert "transformers" not in imported
    assert "torch" not in imported
    text = MODULE_PATH.read_text(encoding="utf-8")
    for capsule_type in CAPSULE_TYPES:
        assert f"class {capsule_type}" not in text
    assert "does not replace" in text
    profile = frontier_cid_profile()
    assert profile["profile_id"] == PROFILE_ID == FRONTIER_CID_PROFILE
    assert profile["codec"] == STRUCTURED_CODEC == FRONTIER_CID_CODEC
    assert "DynamicPythonFrontier" in exports
    assert "analyze_source" in exports


def test_duplicate_analysis_is_deterministic() -> None:
    source = "import importlib\nx = getattr(importlib, 'import_module')\n"
    first = _analyze(source)
    second = _analyze(source)
    assert first.frontier_cid == second.frontier_cid
    assert encode_canonical_frontier(first) == encode_canonical_frontier(second)
    assert canonical_dag_json_bytes(json.loads(first.canonical_bytes().decode("utf-8"))) == (
        first.canonical_bytes()
    )


def test_relative_import_is_present_and_circular_remains_unknown_without_graph() -> None:
    frontier = _analyze("from . import sibling\n")
    relative = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.RELATIVE_CIRCULAR_IMPORT.value
    )
    assert relative.presence == Presence.PRESENT.value
    monkey = next(
        item
        for item in frontier.findings
        if item.kind == DynamicRiskKind.MONKEYPATCH.value
    )
    assert monkey.presence == Presence.UNKNOWN.value


def test_module_import_is_provider_free() -> None:
    import ipfs_datasets_py.semantic_refactoring.dynamic_frontier as frontier

    assert frontier.DynamicPythonFrontier is DynamicPythonFrontier
    assert frontier.__all__
    assert "llm" not in {name.lower() for name in frontier.__all__}
    assert "openai" not in frontier.__all__
