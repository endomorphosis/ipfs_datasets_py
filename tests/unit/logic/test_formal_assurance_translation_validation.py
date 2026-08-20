"""FACP-049: Translation receipts and deontic safety refinement.

Acceptance coverage:
- Unsupported/lossy constructs name exact loss
- Target never broadens source permission or removes prohibitions/obligations
- Proved or solver-validated rewrites are distinguished from heuristics
- Adversarial round trips have explicit dispositions
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest

TASK_ID = "FACP-049"
GOAL_ID = "FACP-G630"
BUNDLE = "facp/translation/validation"
EVIDENCE_TRANSLATION_RECEIPT = "facp/translation-receipt@1"
EVIDENCE_DEONTIC_REFINEMENT = "facp/deontic-refinement@1"
EVIDENCE_REWRITE_TRUST = "facp/rewrite-trust@1"

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
_WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
_MODULE_PATH = (
    _PACKAGE_ROOT
    / "ipfs_datasets_py"
    / "logic"
    / "translation_validation"
    / "formal_assurance.py"
)


def _load_module():
    """Load formal_assurance without executing heavy package ``__init__`` side effects."""

    pkg_name = "ipfs_datasets_py"
    logic_name = "ipfs_datasets_py.logic"
    tv_name = "ipfs_datasets_py.logic.translation_validation"
    mod_name = "ipfs_datasets_py.logic.translation_validation.formal_assurance"
    pkg_dir = _PACKAGE_ROOT / "ipfs_datasets_py"
    logic_dir = pkg_dir / "logic"
    tv_dir = logic_dir / "translation_validation"

    if pkg_name not in sys.modules or not hasattr(sys.modules[pkg_name], "__path__"):
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
        pkg.__file__ = str(pkg_dir / "__init__.py")
        sys.modules[pkg_name] = pkg
    if logic_name not in sys.modules:
        logic = types.ModuleType(logic_name)
        logic.__path__ = [str(logic_dir)]  # type: ignore[attr-defined]
        logic.__package__ = logic_name
        sys.modules[logic_name] = logic
    if tv_name not in sys.modules:
        tv = types.ModuleType(tv_name)
        tv.__path__ = [str(tv_dir)]  # type: ignore[attr-defined]
        tv.__package__ = tv_name
        sys.modules[tv_name] = tv

    if mod_name in sys.modules and hasattr(
        sys.modules[mod_name], "emit_translation_receipt"
    ):
        return sys.modules[mod_name]

    spec = importlib.util.spec_from_file_location(mod_name, _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    sys.modules[tv_name].formal_assurance = module  # type: ignore[attr-defined]
    return module


@pytest.fixture
def facp():
    return _load_module()


def _norm(facp, **overrides: Any):
    values = {
        "norm_id": "norm:default",
        "modality": facp.DeonticModality.PERMISSION,
        "action": "share-data",
        "actors": ("alice",),
        "conditions": (),
        "exceptions": (),
        "temporal_scope": "",
        "jurisdiction": "",
    }
    values.update(overrides)
    return facp.DeonticNorm(**values)


def _criteria(facp, kind: str = "none", **overrides: Any):
    values = {
        "criteria_id": "criteria:default",
        "kind": kind,
        "description": "" if kind == "none" else f"criteria for {kind}",
        "property_ids": (),
    }
    values.update(overrides)
    return facp.EqualityCriteria(**values)


# ---------------------------------------------------------------------------
# Contract surface
# ---------------------------------------------------------------------------


def test_module_exists_and_exports_contract(facp):
    assert _MODULE_PATH.is_file(), f"missing declared output: {_MODULE_PATH}"
    assert facp.TASK_ID == TASK_ID
    assert facp.GOAL_ID == GOAL_ID
    assert facp.BUNDLE == BUNDLE
    assert facp.EVIDENCE_TRANSLATION_RECEIPT == EVIDENCE_TRANSLATION_RECEIPT
    assert facp.EVIDENCE_DEONTIC_REFINEMENT == EVIDENCE_DEONTIC_REFINEMENT
    assert facp.EVIDENCE_REWRITE_TRUST == EVIDENCE_REWRITE_TRUST
    assert facp.UNSAFE_PROMOTION is False
    assert facp.CLAIM_EQUIVALENCE_WITHOUT_CRITERIA is False
    assert facp.ADMIT_HEURISTIC_INTO_PROOF_EXTRACTION is False
    assert facp.SILENT_DROP_FORBIDDEN is True
    for name in (
        "TranslationReceipt",
        "NamedLoss",
        "EqualityCriteria",
        "DeonticNorm",
        "SafetyRefinementResult",
        "TrustedRewriteRegistry",
        "RewriteRule",
        "AdversarialRoundTripResult",
        "emit_translation_receipt",
        "check_deontic_safety_refinement",
        "require_deontic_safety_refinement",
        "admit_rewrite_for_proof_extraction",
        "distinguish_rewrite_trust",
        "evaluate_adversarial_round_trip",
        "require_explicit_adversarial_dispositions",
        "loss_names_exact",
        "assert_no_permission_broadening",
        "CANONICAL_COMPILER_INTERFACE",
        "CANONICAL_DECOMPILER_INTERFACE",
        "EGRAPH_REWRITE_INTERFACE",
    ):
        assert hasattr(facp, name), name


def test_cold_import_is_pure():
    script = textwrap.dedent(
        f"""
        import os, sys, json, importlib.util, types
        package_root = {_PACKAGE_ROOT.as_posix()!r}
        module_path = {_MODULE_PATH.as_posix()!r}
        for k in (
            "IPFS_DATASETS_AUTO_INSTALL",
            "IPFS_KIT_AUTO_INSTALL_DEPS",
            "IPFS_AUTO_INSTALL",
        ):
            os.environ.pop(k, None)
        for n in list(sys.modules):
            if n == "ipfs_datasets_py" or n.startswith("ipfs_datasets_py."):
                del sys.modules[n]
        pkg = types.ModuleType("ipfs_datasets_py")
        pkg.__path__ = [package_root + "/ipfs_datasets_py"]
        sys.modules["ipfs_datasets_py"] = pkg
        logic = types.ModuleType("ipfs_datasets_py.logic")
        logic.__path__ = [package_root + "/ipfs_datasets_py/logic"]
        sys.modules["ipfs_datasets_py.logic"] = logic
        tv = types.ModuleType("ipfs_datasets_py.logic.translation_validation")
        tv.__path__ = [package_root + "/ipfs_datasets_py/logic/translation_validation"]
        sys.modules["ipfs_datasets_py.logic.translation_validation"] = tv
        spec = importlib.util.spec_from_file_location(
            "ipfs_datasets_py.logic.translation_validation.formal_assurance",
            module_path,
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        after = {{
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
            "IPFS_AUTO_INSTALL": os.environ.get("IPFS_AUTO_INSTALL"),
        }}
        print("FACP049::" + json.dumps({{
            "after": after,
            "task_id": mod.TASK_ID,
            "unsafe_promotion": mod.UNSAFE_PROMOTION,
            "admit_heuristic": mod.ADMIT_HEURISTIC_INTO_PROOF_EXTRACTION,
        }}, sort_keys=True))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_WORKSPACE_ROOT),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    line = next(
        ln for ln in completed.stdout.splitlines() if ln.startswith("FACP049::")
    )
    payload = json.loads(line[len("FACP049::") :])
    assert payload["task_id"] == TASK_ID
    assert payload["unsafe_promotion"] is False
    assert payload["admit_heuristic"] is False
    assert payload["after"]["IPFS_DATASETS_AUTO_INSTALL"] is None


# ---------------------------------------------------------------------------
# Acceptance: Unsupported/lossy constructs name exact loss
# ---------------------------------------------------------------------------


def test_named_loss_requires_exact_loss(facp):
    with pytest.raises(facp.TranslationValidationError, match="exact_loss"):
        facp.NamedLoss(
            loss_id="loss:1",
            construct_id="modality:exception",
            construct_kind="exception",
            exact_loss="",
            handling=facp.LossHandling.OMITTED,
        )


def test_lossy_receipt_requires_named_loss(facp):
    with pytest.raises(facp.TranslationValidationError, match="NamedLoss"):
        facp.emit_translation_receipt(
            source_cid="cid:source",
            target_cid="cid:target",
            compiler_cid="cid:compiler",
            source_schema="schema:legal@1",
            target_schema="schema:policy@1",
            preservation_class=facp.PreservationClass.LOSSY,
            equality_criteria=_criteria(facp, "none"),
            named_losses=(),
        )


def test_lossy_receipt_names_exact_loss(facp):
    loss = facp.NamedLoss(
        loss_id="loss:temporal",
        construct_id="construct:until",
        construct_kind="temporal_operator",
        exact_loss="dropped UNTIL temporal operator on retention window",
        handling=facp.LossHandling.OMITTED,
        source_ref_ids=("stmt:retention",),
    )
    receipt = facp.emit_translation_receipt(
        source_cid="cid:source",
        target_cid="cid:target",
        compiler_cid="cid:compiler",
        source_schema="schema:legal@1",
        target_schema="schema:smt@1",
        preservation_class=facp.PreservationClass.LOSSY,
        equality_criteria=_criteria(facp, "none"),
        named_losses=(loss,),
        assumptions=("finite-domain",),
        obligations=("obl:retain-named-loss",),
    )
    assert receipt.receipt_cid.startswith("sha256:")
    assert facp.loss_names_exact(receipt) == (
        "dropped UNTIL temporal operator on retention window",
    )
    assert loss.exact_loss in facp.loss_names_exact(receipt)
    round_trip = facp.TranslationReceipt.from_dict(receipt.to_dict())
    assert round_trip == receipt


def test_equivalence_without_criteria_is_rejected(facp):
    with pytest.raises(
        facp.TranslationValidationError, match="without criteria"
    ):
        facp.emit_translation_receipt(
            source_cid="cid:source",
            target_cid="cid:target",
            compiler_cid="cid:compiler",
            source_schema="schema:a@1",
            target_schema="schema:b@1",
            preservation_class=facp.PreservationClass.EXACT,
            equality_criteria=_criteria(facp, "none"),
        )


def test_exact_preservation_with_matching_criteria(facp):
    receipt = facp.emit_translation_receipt(
        source_cid="cid:source",
        target_cid="cid:target",
        compiler_cid="cid:compiler",
        source_schema="schema:a@1",
        target_schema="schema:b@1",
        preservation_class=facp.PreservationClass.EXACT,
        equality_criteria=_criteria(
            facp,
            "exact",
            property_ids=("prop:semantic-identity",),
        ),
    )
    assert receipt.preservation_class is facp.PreservationClass.EXACT
    assert receipt.equality_criteria.kind is facp.EqualityCriteriaKind.EXACT


# ---------------------------------------------------------------------------
# Acceptance: Target never broadens permission / removes prohibitions/obligations
# ---------------------------------------------------------------------------


def test_safe_refinement_preserves_prohibition_and_obligation(facp):
    source = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
        _norm(
            facp,
            norm_id="n:must",
            modality=facp.DeonticModality.OBLIGATION,
            action="encrypt-at-rest",
        ),
        _norm(
            facp,
            norm_id="n:may",
            modality=facp.DeonticModality.PERMISSION,
            action="read-metadata",
            conditions=("role:auditor",),
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:forbid-t",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
        _norm(
            facp,
            norm_id="n:must-t",
            modality=facp.DeonticModality.OBLIGATION,
            action="encrypt-at-rest",
        ),
        _norm(
            facp,
            norm_id="n:may-t",
            modality=facp.DeonticModality.PERMISSION,
            action="read-metadata",
            conditions=("role:auditor", "need:investigation"),
        ),
    )
    result = facp.require_deontic_safety_refinement(source, target)
    assert result.is_safe is True
    assert result.violations == ()
    assert result.result_cid.startswith("sha256:")


def test_prohibition_removed_is_unsafe(facp):
    source = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    target = ()
    result = facp.check_deontic_safety_refinement(source, target)
    assert result.is_safe is False
    assert any(
        item.kind is facp.SafetyViolationKind.PROHIBITION_REMOVED
        for item in result.violations
    )
    with pytest.raises(facp.SafetyRefinementError, match="prohibition_removed"):
        facp.require_deontic_safety_refinement(source, target)


def test_prohibition_weakened_to_permission_is_unsafe(facp):
    source = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="share-pii",
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:allow",
            modality=facp.DeonticModality.PERMISSION,
            action="share-pii",
        ),
    )
    result = facp.check_deontic_safety_refinement(source, target)
    assert result.is_safe is False
    assert any(
        item.kind
        is facp.SafetyViolationKind.PROHIBITION_WEAKENED_TO_PERMISSION
        for item in result.violations
    )


def test_obligation_removed_is_unsafe(facp):
    source = (
        _norm(
            facp,
            norm_id="n:must",
            modality=facp.DeonticModality.OBLIGATION,
            action="notify-dpo",
        ),
    )
    target = ()
    result = facp.check_deontic_safety_refinement(source, target)
    assert result.is_safe is False
    assert any(
        item.kind is facp.SafetyViolationKind.OBLIGATION_REMOVED
        for item in result.violations
    )


def test_obligation_weakened_to_permission_is_unsafe(facp):
    source = (
        _norm(
            facp,
            norm_id="n:must",
            modality=facp.DeonticModality.OBLIGATION,
            action="notify-dpo",
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:may",
            modality=facp.DeonticModality.PERMISSION,
            action="notify-dpo",
        ),
    )
    result = facp.check_deontic_safety_refinement(source, target)
    assert result.is_safe is False
    assert any(
        item.kind
        is facp.SafetyViolationKind.OBLIGATION_WEAKENED_TO_PERMISSION
        for item in result.violations
    )


def test_permission_broadened_by_new_action_is_unsafe(facp):
    source = (
        _norm(
            facp,
            norm_id="n:may-read",
            modality=facp.DeonticModality.PERMISSION,
            action="read-metadata",
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:may-read-t",
            modality=facp.DeonticModality.PERMISSION,
            action="read-metadata",
        ),
        _norm(
            facp,
            norm_id="n:may-write",
            modality=facp.DeonticModality.PERMISSION,
            action="write-metadata",
        ),
    )
    result = facp.check_deontic_safety_refinement(source, target)
    assert result.is_safe is False
    assert any(
        item.kind is facp.SafetyViolationKind.PERMISSION_BROADENED
        for item in result.violations
    )


def test_permission_condition_broadening_is_unsafe(facp):
    source = (
        _norm(
            facp,
            norm_id="n:may",
            modality=facp.DeonticModality.PERMISSION,
            action="export",
            conditions=("role:admin", "env:prod"),
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:may-t",
            modality=facp.DeonticModality.PERMISSION,
            action="export",
            conditions=("role:admin",),  # dropped env:prod guard
        ),
    )
    result = facp.check_deontic_safety_refinement(source, target)
    assert result.is_safe is False
    assert any(
        item.kind is facp.SafetyViolationKind.CONDITION_BROADENED
        for item in result.violations
    )


def test_emit_receipt_enforces_safety_by_default(facp):
    source = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:allow",
            modality=facp.DeonticModality.PERMISSION,
            action="exfiltrate",
        ),
    )
    with pytest.raises(facp.SafetyRefinementError):
        facp.emit_translation_receipt(
            source_cid="cid:source",
            target_cid="cid:target",
            compiler_cid="cid:compiler",
            source_schema="schema:legal@1",
            target_schema="schema:policy@1",
            preservation_class=facp.PreservationClass.SAFETY_REFINEMENT,
            equality_criteria=_criteria(facp, "safety_refinement"),
            source_norms=source,
            target_norms=target,
        )


def test_lossy_emit_requires_named_loss_covering_violation(facp):
    source = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    target = ()
    with pytest.raises(facp.SafetyRefinementError, match="NamedLoss"):
        facp.emit_translation_receipt(
            source_cid="cid:source",
            target_cid="cid:target",
            compiler_cid="cid:compiler",
            source_schema="schema:legal@1",
            target_schema="schema:policy@1",
            preservation_class=facp.PreservationClass.LOSSY,
            equality_criteria=_criteria(facp, "none"),
            source_norms=source,
            target_norms=target,
            named_losses=(
                facp.NamedLoss(
                    loss_id="loss:unrelated",
                    construct_id="construct:other",
                    construct_kind="predicate",
                    exact_loss="dropped unrelated predicate foo",
                    handling=facp.LossHandling.OMITTED,
                ),
            ),
        )

    receipt = facp.emit_translation_receipt(
        source_cid="cid:source",
        target_cid="cid:target",
        compiler_cid="cid:compiler",
        source_schema="schema:legal@1",
        target_schema="schema:policy@1",
        preservation_class=facp.PreservationClass.LOSSY,
        equality_criteria=_criteria(facp, "none"),
        source_norms=source,
        target_norms=target,
        named_losses=(
            facp.NamedLoss(
                loss_id="loss:forbid",
                construct_id="n:forbid",
                construct_kind="prohibition",
                exact_loss="prohibition_removed on exfiltrate (target family unsupported)",
                handling=facp.LossHandling.OMITTED,
                source_ref_ids=("n:forbid",),
            ),
        ),
        enforce_safety=True,
    )
    assert receipt.safety_refinement is not None
    assert receipt.safety_refinement.is_safe is False
    assert "prohibition_removed" in facp.loss_names_exact(receipt)[0]


def test_assert_no_permission_broadening_on_safe_receipt(facp):
    source = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:forbid-t",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    receipt = facp.emit_translation_receipt(
        source_cid="cid:source",
        target_cid="cid:target",
        compiler_cid="cid:compiler",
        source_schema="schema:legal@1",
        target_schema="schema:policy@1",
        preservation_class=facp.PreservationClass.SAFETY_REFINEMENT,
        equality_criteria=_criteria(facp, "safety_refinement"),
        source_norms=source,
        target_norms=target,
    )
    facp.assert_no_permission_broadening(receipt)


# ---------------------------------------------------------------------------
# Acceptance: Proved/solver-validated rewrites distinguished from heuristics
# ---------------------------------------------------------------------------


def test_rewrite_trust_classes_are_distinguished(facp):
    proved = facp.RewriteRule(
        rule_id="rewrite:assoc",
        trust_class=facp.RewriteTrustClass.PROVED,
        left_pattern="(and a (and b c))",
        right_pattern="(and (and a b) c)",
        proof_artifact_cid="cid:proof-assoc",
        description="associativity",
    )
    solver = facp.RewriteRule(
        rule_id="rewrite:demorgan",
        trust_class=facp.RewriteTrustClass.SOLVER_VALIDATED,
        left_pattern="(not (and a b))",
        right_pattern="(or (not a) (not b))",
        solver_validation_cid="cid:solver-demorgan",
        description="de morgan",
    )
    heuristic = facp.RewriteRule(
        rule_id="rewrite:guess",
        trust_class=facp.RewriteTrustClass.HEURISTIC,
        left_pattern="(implies a b)",
        right_pattern="(or (not a) b)",
        description="unvalidated classical rewrite",
    )
    partitioned = facp.distinguish_rewrite_trust((proved, solver, heuristic))
    assert partitioned["proved"] == (proved,)
    assert partitioned["solver_validated"] == (solver,)
    assert partitioned["heuristic"] == (heuristic,)

    registry = facp.empty_rewrite_registry("rewrite-registry:facp049")
    registry = facp.register_rewrite(registry, proved)
    registry = facp.register_rewrite(registry, solver)
    registry = facp.register_rewrite(registry, heuristic)

    assert registry.is_admitted_for_proof_extraction("rewrite:assoc") is True
    assert registry.is_admitted_for_proof_extraction("rewrite:demorgan") is True
    assert registry.is_admitted_for_proof_extraction("rewrite:guess") is False
    assert len(registry.proof_extraction_rules()) == 2
    assert len(registry.heuristic_rules()) == 1

    admitted = facp.admit_rewrite_for_proof_extraction(registry, "rewrite:assoc")
    assert admitted.trust_class is facp.RewriteTrustClass.PROVED

    with pytest.raises(facp.RewriteTrustError, match="heuristic"):
        facp.admit_rewrite_for_proof_extraction(registry, "rewrite:guess")

    assert facp.ADMIT_HEURISTIC_INTO_PROOF_EXTRACTION is False
    restored = facp.TrustedRewriteRegistry.from_dict(registry.to_dict())
    assert restored == registry


def test_proved_rewrite_requires_proof_cid(facp):
    with pytest.raises(facp.RewriteTrustError, match="proof_artifact_cid"):
        facp.RewriteRule(
            rule_id="rewrite:bad",
            trust_class=facp.RewriteTrustClass.PROVED,
            left_pattern="a",
            right_pattern="b",
        )


def test_heuristic_cannot_carry_proof_cid(facp):
    with pytest.raises(facp.RewriteTrustError, match="heuristic"):
        facp.RewriteRule(
            rule_id="rewrite:bad-h",
            trust_class=facp.RewriteTrustClass.HEURISTIC,
            left_pattern="a",
            right_pattern="b",
            proof_artifact_cid="cid:should-not-exist",
        )


def test_receipt_binds_rewrite_registry_cid(facp):
    registry = facp.register_rewrite(
        facp.empty_rewrite_registry("rewrite-registry:bind"),
        facp.RewriteRule(
            rule_id="rewrite:id",
            trust_class=facp.RewriteTrustClass.SOLVER_VALIDATED,
            left_pattern="x",
            right_pattern="x",
            solver_validation_cid="cid:solver-id",
        ),
    )
    receipt = facp.emit_translation_receipt(
        source_cid="cid:source",
        target_cid="cid:target",
        compiler_cid="cid:compiler",
        source_schema="schema:a@1",
        target_schema="schema:b@1",
        preservation_class=facp.PreservationClass.CONSERVATIVE,
        equality_criteria=_criteria(facp, "none"),
        rewrite_registry=registry,
    )
    assert receipt.rewrite_registry_cid == registry.registry_cid


# ---------------------------------------------------------------------------
# Acceptance: Adversarial round trips have explicit dispositions
# ---------------------------------------------------------------------------


def test_adversarial_round_trips_have_explicit_dispositions(facp):
    source_safe = (
        _norm(
            facp,
            norm_id="n:forbid",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    target_safe = (
        _norm(
            facp,
            norm_id="n:forbid-t",
            modality=facp.DeonticModality.PROHIBITION,
            action="exfiltrate",
        ),
    )
    loss = facp.NamedLoss(
        loss_id="loss:jurisdiction",
        construct_id="construct:jurisdiction",
        construct_kind="jurisdiction",
        exact_loss="collapsed multi-jurisdiction scope to single region EU",
        handling=facp.LossHandling.ABSTRACTED,
    )

    results = [
        facp.evaluate_adversarial_round_trip(
            case_id="case:negation",
            case_kind=facp.AdversarialCaseKind.NEGATION,
            source_norms=source_safe,
            target_norms=target_safe,
            source_cid="cid:src-neg",
            target_cid="cid:tgt-neg",
        ),
        facp.evaluate_adversarial_round_trip(
            case_id="case:exception",
            case_kind=facp.AdversarialCaseKind.EXCEPTION,
            source_norms=source_safe,
            target_norms=target_safe,
            named_losses=(loss,),
            source_cid="cid:src-ex",
            target_cid="cid:tgt-ex",
        ),
        facp.evaluate_adversarial_round_trip(
            case_id="case:temporal",
            case_kind=facp.AdversarialCaseKind.TEMPORAL_OVERLAP,
            source_norms=source_safe,
            target_norms=target_safe,
            rejected=True,
            source_cid="cid:src-time",
            target_cid="cid:tgt-time",
        ),
        facp.evaluate_adversarial_round_trip(
            case_id="case:conflict",
            case_kind=facp.AdversarialCaseKind.CONFLICT,
            source_norms=source_safe,
            target_norms=(
                _norm(
                    facp,
                    norm_id="n:allow",
                    modality=facp.DeonticModality.PERMISSION,
                    action="exfiltrate",
                ),
            ),
            source_cid="cid:src-conflict",
            target_cid="cid:tgt-conflict",
        ),
        facp.evaluate_adversarial_round_trip(
            case_id="case:jurisdiction",
            case_kind=facp.AdversarialCaseKind.JURISDICTION,
            source_norms=source_safe,
            target_norms=target_safe,
            unsupported=True,
            named_losses=(loss,),
            source_cid="cid:src-jur",
            target_cid="cid:tgt-jur",
        ),
    ]

    assert results[0].disposition is facp.RoundTripDisposition.PRESERVED
    assert results[1].disposition is facp.RoundTripDisposition.NAMED_LOSS
    assert results[1].named_loss_ids == ("loss:jurisdiction",)
    assert results[2].disposition is facp.RoundTripDisposition.REJECTED
    assert results[3].disposition is facp.RoundTripDisposition.CONFLICT_RECORDED
    assert results[4].disposition is facp.RoundTripDisposition.UNSUPPORTED

    for item in results:
        assert item.disposition in facp.RoundTripDisposition
        assert item.detail
        assert item.result_cid.startswith("sha256:")

    checked = facp.require_explicit_adversarial_dispositions(results)
    assert len(checked) == 5

    receipt = facp.emit_translation_receipt(
        source_cid="cid:source",
        target_cid="cid:target",
        compiler_cid="cid:compiler",
        source_schema="schema:legal@1",
        target_schema="schema:policy@1",
        preservation_class=facp.PreservationClass.SAFETY_REFINEMENT,
        equality_criteria=_criteria(facp, "safety_refinement"),
        source_norms=source_safe,
        target_norms=target_safe,
        adversarial_results=results,
        decompiler_cid="cid:decompiler",
        recompilation_cid="cid:recompile",
        comparison_cid="cid:compare",
    )
    assert len(receipt.adversarial_results) == 5
    kinds = {item.case_kind for item in receipt.adversarial_results}
    assert kinds == set(facp.REQUIRED_ADVERSARIAL_KINDS)


def test_missing_adversarial_kind_fails_closed(facp):
    partial = (
        facp.evaluate_adversarial_round_trip(
            case_id="case:negation",
            case_kind=facp.AdversarialCaseKind.NEGATION,
            source_norms=(),
            target_norms=(),
        ),
    )
    with pytest.raises(facp.RoundTripError, match="missing required kinds"):
        facp.require_explicit_adversarial_dispositions(partial)


def test_named_loss_disposition_requires_loss_ids(facp):
    with pytest.raises(facp.RoundTripError, match="named_loss"):
        facp.AdversarialRoundTripResult(
            case_id="case:bad",
            case_kind=facp.AdversarialCaseKind.EXCEPTION,
            disposition=facp.RoundTripDisposition.NAMED_LOSS,
            detail="missing ids",
            named_loss_ids=(),
        )


# ---------------------------------------------------------------------------
# Integration: full receipt evidence subset
# ---------------------------------------------------------------------------


def test_receipt_evidence_subset_fields(facp):
    registry = facp.register_rewrite(
        facp.empty_rewrite_registry("rewrite-registry:evidence"),
        facp.RewriteRule(
            rule_id="rewrite:proved",
            trust_class=facp.RewriteTrustClass.PROVED,
            left_pattern="p",
            right_pattern="p",
            proof_artifact_cid="cid:proof-p",
        ),
    )
    source = (
        _norm(
            facp,
            norm_id="n:must",
            modality=facp.DeonticModality.OBLIGATION,
            action="log-access",
            temporal_scope="retention:1y",
            jurisdiction="EU",
        ),
    )
    target = (
        _norm(
            facp,
            norm_id="n:must-t",
            modality=facp.DeonticModality.OBLIGATION,
            action="log-access",
            temporal_scope="retention:1y",
            jurisdiction="EU",
        ),
    )
    adversarial = [
        facp.evaluate_adversarial_round_trip(
            case_id=f"case:{kind.value}",
            case_kind=kind,
            source_norms=source,
            target_norms=target,
            source_cid="cid:src",
            target_cid="cid:tgt",
            recompilation_cid="cid:recomp",
        )
        for kind in facp.REQUIRED_ADVERSARIAL_KINDS
    ]
    receipt = facp.emit_translation_receipt(
        source_cid="cid:source-evidence",
        target_cid="cid:target-evidence",
        compiler_cid="cid:compiler-evidence",
        source_schema="schema:intent@1",
        target_schema="schema:legal@1",
        preservation_class=facp.PreservationClass.SAFETY_REFINEMENT,
        equality_criteria=_criteria(facp, "safety_refinement"),
        assumptions=("closed-world-actors",),
        obligations=("obl:preserve-log-access",),
        source_norms=source,
        target_norms=target,
        rewrite_registry=registry,
        adversarial_results=adversarial,
        decompiler_cid="cid:decompiler-evidence",
        recompilation_cid="cid:recompilation-evidence",
        comparison_cid="cid:comparison-evidence",
        metadata={"task_id": TASK_ID},
    )
    payload = receipt.to_dict()
    for key in (
        "source_cid",
        "target_cid",
        "compiler_cid",
        "source_schema",
        "target_schema",
        "preservation_class",
        "equality_criteria",
        "named_losses",
        "assumptions",
        "obligations",
        "recompilation_cid",
        "comparison_cid",
        "safety_refinement",
        "adversarial_results",
        "rewrite_registry_cid",
        "receipt_cid",
    ):
        assert key in payload, key
    assert payload["interface"] == facp.INTERFACE
    assert payload["evidence_id"] == EVIDENCE_TRANSLATION_RECEIPT
    assert payload["metadata"]["task_id"] == TASK_ID
    assert facp.TranslationReceipt.from_dict(payload) == receipt
