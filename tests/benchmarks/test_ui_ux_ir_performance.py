"""UIR-080: scale / latency / resource bounds (offline, no external solvers)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ipfs_datasets_py.logic.ui_ux_ir.canonicalize import canonicalize_ui_ir
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator import (
    ActorContext,
    ActorKind,
    PolicyNorm,
    PolicyVerdict,
    RuntimeMediationContext,
    UIMediator,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    ProgramBindingTargetKind,
    ReviewStatus,
    SourceSpan,
    TerminalOutcomeKind,
    UIComponent,
    UIIRDocument,
    UISourceRef,
    UITerminalOutcome,
)

POLICY = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "benchmarks"
    / "ui_ux_ir_performance_policy.json"
)


def _doc_with_nodes(n: int) -> UIIRDocument:
    source = UISourceRef(
        ref_id="source:bench",
        source_uri="https://example.test/bench",
        source_id="bench",
        source_revision="1",
        content_sha256="c" * 64,
        container_uri="ipfs://bafybench",
        container_sha256="d" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
        span=SourceSpan(start_char=0, end_char=1),
    )
    components = tuple(
        UIComponent(
            component_id=f"component:n{i}",
            role="button" if i else "form",
            purpose=f"Node {i}",
            parent_id="" if i == 0 else "component:n0",
            source_ref_ids=(source.ref_id,),
        )
        for i in range(min(n, 200))  # keep unit suite fast; policy documents 1k/10k
    )
    return UIIRDocument(
        document_id="doc:bench",
        title="Bench",
        sources=(source,),
        components=components,
        entry_components=("component:n0",),
        terminal_outcomes=(
            UITerminalOutcome(
                outcome_id="outcome:ok",
                kind=TerminalOutcomeKind.SUCCESS,
                source_ref_ids=(source.ref_id,),
            ),
        ),
    )


def test_performance_policy_bounds_documented() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["max_nodes"] >= 1000
    assert policy["max_payload_bytes"] >= 1_000_000
    assert policy["external_solver_calls_allowed"] is False


def test_mediation_and_canonicalize_within_offline_bounds() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    doc = _doc_with_nodes(policy["soft_nodes"])
    t0 = time.perf_counter()
    blob = canonicalize_ui_ir(doc)
    canon_ms = (time.perf_counter() - t0) * 1000
    assert len(blob) < policy["max_payload_bytes"]
    assert canon_ms < policy["max_canonicalize_ms"] * 20  # CI slack

    binding = UIActionBinding(
        binding_id="binding:b",
        action_id="action:a",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafyb",
            mcp_idl_method_name="run",
        ),
        risk_class=RiskClass.LOW,
        confirmation_class=ConfirmationClass.NONE,
    )
    event = CanonicalInteractionEvent(
        event_id="e",
        kind=EventKind.ACTIVATE,
        target_component_id="c",
        timestamp_ms=1,
        provenance=EventProvenance.HUMAN,
        capability_id="cap",
        consent_ok=True,
    )
    ctx = RuntimeMediationContext(
        declaration_digest="decl",
        projection_id="proj",
        state_version=0,
        actor=ActorContext(
            actor_id="h",
            kind=ActorKind.HUMAN,
            human_consent=True,
            confirmation_granted=True,
        ),
        policy_norms=(
            PolicyNorm(norm_id="n", verdict=PolicyVerdict.ALLOW, binding_id="binding:b"),
        ),
    )
    t1 = time.perf_counter()
    for _ in range(50):
        UIMediator().mediate(binding, event, ctx)
    med_ms = ((time.perf_counter() - t1) * 1000) / 50
    assert med_ms < policy["max_mediation_ms"] * 20
