"""LPC-043: Intent IR adapter conformance through DomainLogicSlice@2.

Production adapter is IntentLogicSlice@2. This test does not invent a second
intent ontology.
"""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.logic.formalization.artifacts_v3 import DomainSliceStatus
from ipfs_datasets_py.logic.intent_ir.formalize.logic_slice_v2 import (
    DOMAIN_ID,
    INTENT_LOGIC_SLICE_INTERFACE,
    IntentLogicSlice,
    IntentRouteKind,
)
from ipfs_datasets_py.logic.intent_ir.formalize.typed_compiler import (
    INTENT_IR_DOMAIN_ID,
)


def _adapter_note() -> Path:
    relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "intent_uiux_adapters.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / relative


def test_intent_adapter_note_declares_required_contract_fields() -> None:
    text = _adapter_note().read_text(encoding="utf-8").lower()
    for field in (
        "source domain",
        "view",
        "family / profile",
        "property",
        "notation",
        "preserved semantics",
        "lost semantics",
        "assumptions",
        "unsupported constructs",
        "proof-safety",
        "counterexample-safety",
    ):
        assert field in text, field
    assert "no universal domain ir" in text
    assert "intentlogicslice@2" in text


def test_intent_logic_slice_emits_admitted_domain_slice() -> None:
    connector = IntentLogicSlice()
    assert connector.interface == INTENT_LOGIC_SLICE_INTERFACE
    assert connector.domain_id == DOMAIN_ID == INTENT_IR_DOMAIN_ID == "intent_ir"

    bundle = connector.connect_obligation(IntentRouteKind.INTENT)
    domain_slice = bundle.domain_slice
    domain_slice.require_admitted()
    assert domain_slice.status is DomainSliceStatus.ADMITTED
    assert domain_slice.domain == "intent_ir"
    assert domain_slice.document_id
    assert domain_slice.source_digest
    assert domain_slice.expression_id
    assert domain_slice.expression_digest
    assert domain_slice.content_digest


def test_intent_domain_stays_distinct_from_legal_and_ui_ux() -> None:
    connector = IntentLogicSlice()
    bundle = connector.connect_obligation(IntentRouteKind.GOAL)
    assert bundle.domain_slice.domain == "intent_ir"
    assert bundle.domain_slice.domain not in {
        "legal_ir",
        "security_ir",
        "ui_ux_ir",
        "universal",
    }
