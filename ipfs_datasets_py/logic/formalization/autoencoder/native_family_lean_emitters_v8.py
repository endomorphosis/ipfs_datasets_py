"""Source-replayed explicit UI temporal and cognitive interpretation dispatch.

Existing projections retain their original native owners and source reports.
An owned malformed projection never falls back to a generic formula lowering.
"""
from . import native_family_lean_emitters_v7 as previous
from . import native_family_lean_emitters as base
from . import family_training as core
from . import native_ui_temporal_logic as temporal
from . import native_ui_dcec_logic as cognitive

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
PRODUCERS = (*previous.PRODUCERS, temporal, cognitive)
REPORT_SCHEMA = "ui-declared-logic-family-targets/v1"
_OWNERS = {
    "ui_ux_ir/declared_state_logic/TFOL/v1": temporal,
    "ui_ux_ir/declared_state_logic/TDFOL/v1": temporal,
    "ui_ux_ir/explicit_logic/bounded_dcec/v1": cognitive,
}
_SCHEMAS = {"native-ui-state-temporal-logic/v1", "native-ui-bounded-dcec/v1"}


def emit_projection(row, *, report=None):
    base.require(type(row) is dict, "native projection row required")
    owner = _OWNERS.get(row.get("projection_id"))
    if owner is not None:
        try:
            return owner.emit_projection(row, report=report)
        except NotImplementedError as error:
            raise UnsupportedNativeLean("owned UI logic projection refused by its native owner") from error
    payload = row.get("payload")
    base.require(row.get("producer_id") not in {temporal.__name__, cognitive.__name__}
        and not (type(payload) is dict and payload.get("schema") in _SCHEMAS),
        "UI logic payload or producer cannot fall back under an unknown projection ID")
    if type(report) is not dict or report.get("schema") != REPORT_SCHEMA:
        return previous.emit_projection(row, report=report)
    from . import ui_declared_logic_source as source_owner
    binding = report.get("declared_logic_source_binding")
    base.require(type(binding) is dict and set(binding) == {"source_text", "candidate"},
        "complete declared UI logic source binding required")
    source_owner.validate_family_training_report(report, source_text=binding["source_text"],
        candidate=binding["candidate"])
    base.require([item for item in report["projections"]
        if item.get("projection_id") == row.get("projection_id")] == [row],
        "exact declared UI logic projection membership required")
    original_report = report.get("base_ui_report")
    base.require(type(original_report) is dict, "complete original UI report required")
    matches = [item for item in original_report.get("projections", [])
        if item.get("projection_id") == row.get("projection_id")]
    base.require(len(matches) == 1, "one preserved original UI projection required")
    original = matches[0]
    retained = lambda value: {key: item for key, item in value.items()
                             if key not in {"source_digest", "target_sha256"}}
    base.require(core._wire(retained(row)) == core._wire(retained(original)),
        "preserved UI projection differs from original payload or metadata")
    return previous.emit_projection(original, report=original_report)


__all__ = ["emit_projection", "PRODUCERS", "PRELUDE", "UnsupportedNativeLean"]
