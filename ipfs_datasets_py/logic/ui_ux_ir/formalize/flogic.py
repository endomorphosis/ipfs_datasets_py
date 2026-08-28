"""Structural FOL / F-logic compiler for UI/UX IR (UIFLogicCompiler@1)."""

from __future__ import annotations

from ..schema import UIIRDocument
from .contracts import (
    UIFLOGIC_VIEW_ID,
    CoverageDisposition,
    FormalFormula,
    FormalView,
    SourceMapEntry,
)
from .ontology import document_facts, ontology_symbols


UIFLOGIC_COMPILER_INTERFACE = "UIFLogicCompiler@1"


def compile_flogic(document: UIIRDocument) -> tuple[FormalView, tuple[SourceMapEntry, ...]]:
    """Compile components/roles/bindings into typed FOL/F-logic formulas."""
    symbols = list(ontology_symbols(document))
    formulas: list[FormalFormula] = []
    coverage: list[SourceMapEntry] = []
    facts = document_facts(document)

    for fact in facts:
        if fact["kind"] == "component":
            cid = fact["id"]
            role = fact["role"] or "component"
            fid = f"flogic:HasRole:{cid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="flogic",
                    text=f"HasRole({cid!r}, {role!r}).",
                    free_symbols=(f"sym:comp:{cid}", "sym:pred:HasRole"),
                    source_refs=(cid,),
                )
            )
            if fact.get("parent_id"):
                pfid = f"flogic:ChildOf:{cid}"
                formulas.append(
                    FormalFormula(
                        formula_id=pfid,
                        logic_family="flogic",
                        text=f"ChildOf({cid!r}, {fact['parent_id']!r}).",
                        free_symbols=(
                            f"sym:comp:{cid}",
                            f"sym:comp:{fact['parent_id']}",
                            "sym:pred:ChildOf",
                        ),
                        source_refs=(cid, fact["parent_id"]),
                    )
                )
            coverage.append(
                SourceMapEntry(
                    source_node_id=cid,
                    source_kind="component",
                    formula_ids=(fid,),
                    symbol_ids=(f"sym:comp:{cid}",),
                    disposition=CoverageDisposition.REPRESENTED,
                )
            )
        elif fact["kind"] == "entry_component":
            fid = f"flogic:Entry:{fact['id']}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="flogic",
                    text=f"EntryComponent({fact['id']!r}).",
                    free_symbols=(f"sym:comp:{fact['id']}", "sym:pred:EntryComponent"),
                    source_refs=(fact["id"],),
                )
            )
            coverage.append(
                SourceMapEntry(
                    source_node_id=fact["id"],
                    source_kind="entry_component",
                    formula_ids=(fid,),
                    disposition=CoverageDisposition.REPRESENTED,
                )
            )
        elif fact["kind"] == "terminal_outcome":
            fid = f"flogic:Terminal:{fact['id']}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="flogic",
                    text=f"TerminalOutcome({fact['id']!r}, {fact['outcome_kind']!r}).",
                    free_symbols=("sym:pred:TerminalOutcome",),
                    source_refs=(fact["id"],),
                )
            )
            coverage.append(
                SourceMapEntry(
                    source_node_id=fact["id"],
                    source_kind="terminal_outcome",
                    formula_ids=(fid,),
                    disposition=CoverageDisposition.REPRESENTED,
                )
            )
        elif fact["kind"] == "program_binding":
            fid = f"flogic:Bind:{fact['id']}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="flogic",
                    text=(
                        f"BindsProgram({fact['id']!r}, {fact['target_kind']!r}, "
                        f"{fact['target_ref']!r})."
                    ),
                    free_symbols=(f"sym:binding:{fact['id']}", "sym:pred:BindsProgram"),
                    source_refs=(fact["id"],),
                )
            )
            # Non-empty interface CID is interface authority elsewhere; empty is fine.
            coverage.append(
                SourceMapEntry(
                    source_node_id=fact["id"],
                    source_kind="program_binding",
                    formula_ids=(fid,),
                    symbol_ids=(f"sym:binding:{fact['id']}",),
                    disposition=CoverageDisposition.REPRESENTED,
                    note="Binding is descriptive; does not authorize execution.",
                )
            )
        elif fact["kind"] == "mcp_idl_binding":
            fid = f"flogic:McpIdl:{fact['id']}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="flogic",
                    text=f"BindsMcpIdl({fact['id']!r}, {fact['method_name']!r}).",
                    free_symbols=("sym:pred:BindsMcpIdl",),
                    source_refs=(fact["id"],),
                )
            )
            coverage.append(
                SourceMapEntry(
                    source_node_id=fact["id"],
                    source_kind="mcp_idl_binding",
                    formula_ids=(fid,),
                    disposition=CoverageDisposition.REPRESENTED,
                    note="interface_cid retained separately; never equated to ui_ir_digest.",
                )
            )

    view = FormalView(
        view_id=UIFLOGIC_VIEW_ID,
        logic_family="flogic",
        description="Structural FOL/F-logic view of components, entries, outcomes, bindings.",
        symbols=tuple(symbols),
        formulas=tuple(formulas),
        diagnostics=(
            f"interface={UIFLOGIC_COMPILER_INTERFACE}",
            "result_authority=compiler_output",
        ),
    )
    return view, tuple(coverage)


__all__ = ["UIFLOGIC_COMPILER_INTERFACE", "compile_flogic"]
