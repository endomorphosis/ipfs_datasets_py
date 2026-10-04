"""Ground rich DCEC functional dispatch with independent complete AST parity."""
from . import native_family_lean_emitters_v5 as previous
from . import native_family_lean_emitters as base
from . import strict_dcec_functional as strict
from . import native_ui_guarded_lean as ui_guarded

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
PRODUCERS = (*previous.PRODUCERS, *strict.PRODUCERS, ui_guarded)


def emit_projection(row, *, report=None):
    if type(row) is not dict or row.get("projection_id") != "rich-intent/dcec/v1":
        try:
            return ui_guarded.emit_projection(row, report=report)
        except NotImplementedError:
            pass
        return previous.emit_projection(row, report=report)
    base.require(type(report) is dict and report.get("domain_id") == "intent_ir"
        and row.get("logic_family") == "dcec" and row.get("profile") is None
        and row.get("producer_id") == "ipfs_datasets_py.logic.intent_ir.formalize.rich_logic"
        and row.get("source_digest") == report.get("source_digest")
        and row.get("ready_for_training") is True
        and [value for value in report.get("projections", []) if value.get("projection_id") == row["projection_id"]] == [row],
        "exact_source_replayed_rich_Intent_DCEC_report_required")
    checked = strict.validate_rich_dcec_payload(row["payload"])
    renderer = base.FormulaRenderer()
    expression = renderer.formula(checked["native_ast"])
    source = "def formula_0 {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := " + expression
    return source, {"validator": "independent_complete_rich_functional_parse_and_native_DCEC_AST_parity",
        "operators": renderer.operators, "strict_functional_receipt": checked,
        "assumptions": ["Object predicates, agent interpretation and distinct modal operators are parameters.",
            "Boolean structure is preserved exactly; no deontic or cognitive axioms are asserted.",
            "This ground rich fragment introduces no clock, quantifier, observed event or event-calculus axiom."],
        "source_candidate_replay_required": True, "capability_scope": checked["scope"]}


__all__ = ["emit_projection", "PRODUCERS", "PRELUDE", "UnsupportedNativeLean"]
