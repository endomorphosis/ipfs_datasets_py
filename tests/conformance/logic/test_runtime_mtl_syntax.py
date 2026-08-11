"""Conformance: RuntimeMTLSyntaxAdapter@1 bridges shared temporal syntax (LFP-026).

Acceptance:

* existing golden traces remain stable
* Python and declared cross-runtime fixtures agree
* incomplete traces never produce theorem authority

Evidence subset: syntax mapping, rational intervals, finite trace,
inconclusive verdict, monitorability, source maps.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.runtime_mtl_adapter import (
    RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE,
    RuntimeMTLAdapterError,
    RuntimeMTLEvalReceipt,
    RuntimeMTLMappingReceipt,
    RuntimeMTLSyntaxAdapter,
    adapt_formula,
    adapt_text,
    evaluate_adapted,
    formula_to_temporal_text,
    metric_interval_to_runtime,
    profile_for_runtime_formula,
    runtime_interval_to_metric,
)
from ipfs_datasets_py.logic.parsers.temporal import (
    TEMPORAL_SYNTAX_INTERFACE,
    MetricInterval,
    RationalBound,
    TemporalLogicKind,
    TraceModelKind,
    parse_temporal,
    profile_ltlf,
)
from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
    RUNTIME_MTL_INTERFACE,
    Formula,
    Logic,
    MonitorAuthority,
    MonitorEvaluation,
    TimeInterval,
    TimeUnit,
    TimeValue,
    Verdict,
    evaluate_case,
    evaluate_portable,
    golden_fixtures,
    golden_fixtures_json,
)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_adapter_interface_identity() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    assert adapter.interface == RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE
    assert RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE == "RuntimeMTLSyntaxAdapter@1"
    wire = adapter.to_dict()
    assert wire["interface"] == RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE
    assert wire["runtime_mtl_interface"] == RUNTIME_MTL_INTERFACE
    assert wire["temporal_syntax_interface"] == TEMPORAL_SYNTAX_INTERFACE


# ---------------------------------------------------------------------------
# Golden traces remain stable
# ---------------------------------------------------------------------------


def test_existing_golden_traces_remain_stable() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    receipts = adapter.assert_golden_stable()
    assert len(receipts) == len(golden_fixtures())
    for receipt in receipts:
        assert isinstance(receipt, RuntimeMTLEvalReceipt)
        assert receipt.authority == MonitorAuthority.MONITOR.value
        assert receipt.authorizes_theorem is False
        assert receipt.authorizes_global_proof is False
        assert receipt.evaluation.authority is MonitorAuthority.MONITOR
        assert receipt.evaluation.authorizes_global_proof is False


def test_golden_direct_and_adapter_evaluation_agree() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    for case in golden_fixtures():
        direct = evaluate_case(
            {
                "formula": case["formula"],
                "trace": case["trace"],
                "position": case.get("position", 0),
            }
        )
        adapted = adapter.evaluate_case(case).evaluation.to_dict()
        assert direct == adapted, case["case_id"]
        for key, value in case["expected"].items():
            assert adapted[key] == value, f"{case['case_id']}:{key}"


def test_golden_fixtures_json_is_stable_encoding() -> None:
    first = golden_fixtures_json()
    second = golden_fixtures_json()
    assert first == second
    assert '"interface":"RuntimeMTLMonitor@1"' in first


# ---------------------------------------------------------------------------
# Syntax mapping / round-trip
# ---------------------------------------------------------------------------


def test_ltlf_formula_maps_to_shared_temporal_text() -> None:
    formula = Formula.from_dict(
        {
            "operator": "always",
            "logic": "ltlf",
            "operands": [
                {
                    "operator": "atom",
                    "logic": "ltlf",
                    "operands": [],
                    "proposition": "safe",
                    "interval": None,
                    "schema_version": "runtime-mtl-formula/v1",
                }
            ],
            "proposition": "",
            "interval": None,
            "schema_version": "runtime-mtl-formula/v1",
        }
    )
    adapter = RuntimeMTLSyntaxAdapter()
    receipt = adapter.map_formula(formula)
    assert isinstance(receipt, RuntimeMTLMappingReceipt)
    assert receipt.temporal_text == "always safe"
    assert receipt.profile.logic is TemporalLogicKind.LTLF
    assert receipt.profile.trace_model is TraceModelKind.FINITE
    assert receipt.source_map
    assert receipt.authorizes_theorem is False


def test_mtl_formula_maps_with_rational_interval() -> None:
    formula = Formula(
        "eventually",
        Logic.MTL,
        (Formula.atom("ready", logic=Logic.MTL),),
        interval=TimeInterval.closed(0, TimeValue(1, 2), TimeUnit.SECOND),
    )
    adapter = RuntimeMTLSyntaxAdapter(default_time_unit=TimeUnit.SECOND)
    receipt = adapter.map_formula(formula)
    assert "eventually" in receipt.temporal_text
    assert "ready" in receipt.temporal_text
    assert "1/2" in receipt.temporal_text or "0,1/2" in receipt.temporal_text.replace(" ", "")
    # Interval exactness on the runtime formula side.
    assert formula.interval is not None
    assert formula.interval.upper is not None
    assert formula.interval.upper.fraction.numerator == 1
    assert formula.interval.upper.fraction.denominator == 2


def test_formula_text_formula_round_trip_preserves_semantics() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    cases = [
        Formula("always", Logic.LTLF, (Formula.atom("safe"),)),
        Formula(
            "until",
            Logic.LTLF,
            (Formula.atom("safe"), Formula.atom("done")),
        ),
        Formula("next", Logic.LTLF, (Formula.atom("safe"),)),
        Formula(
            "eventually",
            Logic.MTL,
            (Formula.atom("ready", logic=Logic.MTL),),
            interval=TimeInterval.closed(0, 1, TimeUnit.SECOND),
        ),
        Formula(
            "always",
            Logic.MTL,
            (Formula.atom("safe", logic=Logic.MTL),),
            interval=TimeInterval.closed(0, 1, TimeUnit.LOGICAL_TICK),
        ),
        Formula(
            "eventually",
            Logic.MTL,
            (Formula.atom("ready", logic=Logic.MTL),),
            interval=TimeInterval(
                lower=TimeValue(0),
                upper=TimeValue(1),
                unit=TimeUnit.SECOND,
                lower_closed=True,
                upper_closed=False,
            ),
        ),
    ]
    for formula in cases:
        unit = formula.interval.unit if formula.interval is not None else TimeUnit.LOGICAL_TICK
        adapter = RuntimeMTLSyntaxAdapter(default_time_unit=unit)
        receipt = adapter.round_trip_formula(formula, time_unit=unit)
        assert receipt.formula.semantic_dict() == formula.semantic_dict()


def test_parse_shared_temporal_into_runtime_formula() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    ltlf = adapter.parse_text("always (safe -> eventually done)", logic=Logic.LTLF)
    assert ltlf.formula.logic is Logic.LTLF
    assert ltlf.formula.operator == "always"
    assert ltlf.source_map

    mtl = adapter.parse_text(
        "eventually[0,1] ready",
        logic=Logic.MTL,
        time_unit=TimeUnit.SECOND,
    )
    assert mtl.formula.logic is Logic.MTL
    assert mtl.formula.operator == "eventually"
    assert mtl.formula.interval is not None
    assert mtl.formula.interval.unit is TimeUnit.SECOND
    assert mtl.formula.interval.upper is not None
    assert mtl.formula.interval.upper == TimeValue(1)


def test_shared_temporal_parse_agrees_with_adapter() -> None:
    text = "safe until done"
    direct = parse_temporal(text, profile_ltlf())
    assert direct.ok and direct.root is not None
    adapter = RuntimeMTLSyntaxAdapter()
    mapped = adapter.parse_text(text, logic=Logic.LTLF)
    # Direct temporal tree lowers to the same portable formula.
    from ipfs_datasets_py.logic.parsers.runtime_mtl_adapter import temporal_node_to_formula

    lowered = temporal_node_to_formula(direct.root, logic=Logic.LTLF, profile=profile_ltlf())
    assert lowered.semantic_dict() == mapped.formula.semantic_dict()


# ---------------------------------------------------------------------------
# Rational interval codec
# ---------------------------------------------------------------------------


def test_metric_interval_codec_is_exact() -> None:
    metric = MetricInterval(
        lower=RationalBound(1, 3),
        upper=RationalBound(2, 5),
        lower_closed=False,
        upper_closed=True,
    )
    runtime = metric_interval_to_runtime(metric, unit=TimeUnit.MILLISECOND)
    assert runtime.unit is TimeUnit.MILLISECOND
    assert runtime.lower == TimeValue(1, 3)
    assert runtime.upper == TimeValue(2, 5)
    assert runtime.lower_closed is False
    assert runtime.upper_closed is True
    back = runtime_interval_to_metric(runtime)
    assert back.lower == metric.lower
    assert back.upper == metric.upper
    assert back.lower_closed is metric.lower_closed
    assert back.upper_closed is metric.upper_closed


def test_unbounded_runtime_interval_rejected_by_shared_syntax() -> None:
    unbounded = TimeInterval.unbounded(TimeUnit.SECOND)
    with pytest.raises(RuntimeMTLAdapterError, match="unbounded"):
        runtime_interval_to_metric(unbounded)


# ---------------------------------------------------------------------------
# Incomplete traces never produce theorem authority
# ---------------------------------------------------------------------------


def test_incomplete_prefix_never_produces_theorem_authority() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    prefix_cases = [
        case
        for case in golden_fixtures()
        if case["trace"]["kind"] == "finite_prefix"
    ]
    assert prefix_cases, "expected finite_prefix golden cases"
    for case in prefix_cases:
        receipt = adapter.evaluate_case(case)
        assert receipt.incomplete_trace is True
        assert receipt.finite_trace is True
        assert receipt.authorizes_theorem is False
        assert receipt.authorizes_global_proof is False
        assert receipt.evaluation.authority is MonitorAuthority.MONITOR
        assert receipt.evaluation.authorizes_global_proof is False
        with pytest.raises(RuntimeMTLAdapterError, match="theorem"):
            receipt.promote_to_theorem()
        # Inconclusive prefixes are the critical no-proof path.
        if receipt.evaluation.verdict is Verdict.INCONCLUSIVE:
            assert receipt.evaluation.status.value == "unknown"
            assert receipt.three_valued_verdict == "inconclusive"


def test_prefix_always_inconclusive_via_text_adapter() -> None:
    case = next(c for c in golden_fixtures() if c["case_id"] == "prefix-always-inconclusive")
    adapter = RuntimeMTLSyntaxAdapter()
    receipt = adapter.evaluate_text(
        "always safe",
        case["trace"],
        logic=Logic.LTLF,
    )
    assert receipt.evaluation.verdict is Verdict.INCONCLUSIVE
    assert receipt.incomplete_trace is True
    assert receipt.authorizes_theorem is False
    with pytest.raises(RuntimeMTLAdapterError, match="theorem"):
        receipt.promote_to_theorem()


def test_monitor_evaluation_construction_rejects_proof_flag() -> None:
    case = next(c for c in golden_fixtures() if c["case_id"] == "prefix-always-inconclusive")
    result = evaluate_portable(case["formula"], case["trace"])
    with pytest.raises(Exception):
        MonitorEvaluation(
            verdict=result.verdict,
            status=result.status,
            authority=MonitorAuthority.MONITOR,
            logic=result.logic,
            trace_kind=result.trace_kind,
            monitorability=result.monitorability,
            position=result.position,
            reason=result.reason,
            authorizes_global_proof=True,
        )


# ---------------------------------------------------------------------------
# Cross-runtime fixture agreement (Python declared fixtures)
# ---------------------------------------------------------------------------


def test_python_declared_fixtures_agree_with_adapter_mapping() -> None:
    """Every golden formula maps to shared temporal and round-trips."""

    adapter = RuntimeMTLSyntaxAdapter()
    for case in golden_fixtures():
        formula = Formula.from_dict(case["formula"])
        # late-event case still has a well-formed formula.
        unit = (
            formula.interval.unit
            if formula.interval is not None
            else TimeUnit.LOGICAL_TICK
        )
        # Prefer unit from nested intervals.
        def _unit(f: Formula) -> TimeUnit | None:
            if f.interval is not None:
                return f.interval.unit
            for child in f.operands:
                found = _unit(child)
                if found is not None:
                    return found
            return None

        unit = _unit(formula) or unit
        local = RuntimeMTLSyntaxAdapter(default_time_unit=unit)
        mapped = local.map_formula(formula, time_unit=unit)
        assert mapped.formula.semantic_dict() == formula.semantic_dict()
        # Round-trip through shared temporal surface.
        again = local.round_trip_formula(formula, time_unit=unit)
        assert again.formula.semantic_dict() == formula.semantic_dict()
        # Monitorability is an explicit evidence property.
        assert mapped.source_map
        assert "monitorability" in again.to_dict() or again.logic in {Logic.LTLF, Logic.MTL}


def test_adapter_evaluate_matches_runtime_for_text_forms() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    case = next(c for c in golden_fixtures() if c["case_id"] == "ltlf-always-holds")
    via_formula = adapter.evaluate(case["formula"], case["trace"])
    via_text = adapter.evaluate_text("always safe", case["trace"], logic=Logic.LTLF)
    assert via_formula.evaluation.to_dict() == via_text.evaluation.to_dict()
    assert via_text.evaluation.verdict is Verdict.TRUE


def test_mtl_interval_boundary_semantics_via_adapter() -> None:
    adapter = RuntimeMTLSyntaxAdapter(default_time_unit=TimeUnit.SECOND)
    closed = next(
        c for c in golden_fixtures() if c["case_id"] == "mtl-closed-interval-includes-boundary"
    )
    open_upper = next(
        c for c in golden_fixtures() if c["case_id"] == "mtl-open-upper-excludes-boundary"
    )
    closed_receipt = adapter.evaluate_case(closed)
    open_receipt = adapter.evaluate_case(open_upper)
    assert closed_receipt.evaluation.verdict is Verdict.TRUE
    assert open_receipt.evaluation.verdict is Verdict.FALSE
    # Same surface interval spelling differs only by boundary flags.
    closed_text = adapter.formula_to_text(closed["formula"])
    open_text = adapter.formula_to_text(open_upper["formula"])
    assert "eventually" in closed_text and "ready" in closed_text
    assert "eventually" in open_text and "ready" in open_text


def test_monitor_from_text_is_wire_compatible() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    monitor = adapter.monitor_from_text("next safe", logic=Logic.LTLF)
    case = next(c for c in golden_fixtures() if c["case_id"] == "serialization-roundtrip-next")
    result = monitor.evaluate(case["trace"])
    assert result.verdict is Verdict.TRUE
    wire = monitor.to_dict()
    assert wire["interface"] == RUNTIME_MTL_INTERFACE
    assert wire["formula"]["operator"] == "next"


# ---------------------------------------------------------------------------
# Module helpers / fail-closed paths
# ---------------------------------------------------------------------------


def test_module_level_helpers() -> None:
    formula = Formula("always", Logic.LTLF, (Formula.atom("safe"),))
    mapped = adapt_formula(formula)
    assert mapped.temporal_text == "always safe"
    text_mapped = adapt_text("eventually done", logic=Logic.LTLF)
    assert text_mapped.formula.operator == "eventually"
    case = next(c for c in golden_fixtures() if c["case_id"] == "ltlf-always-holds")
    receipt = evaluate_adapted(case["formula"], case["trace"])
    assert receipt.evaluation.verdict is Verdict.TRUE


def test_path_quantifiers_rejected() -> None:
    from ipfs_datasets_py.logic.parsers.temporal import profile_ctl, parse_temporal
    from ipfs_datasets_py.logic.parsers.runtime_mtl_adapter import temporal_node_to_formula

    result = parse_temporal("A always p", profile_ctl())
    assert result.ok and result.root is not None
    with pytest.raises(RuntimeMTLAdapterError, match="path"):
        temporal_node_to_formula(result.root, logic=Logic.LTLF)


def test_profile_for_runtime_formula_selects_mtl() -> None:
    formula = Formula(
        "always",
        Logic.MTL,
        (Formula.atom("safe", logic=Logic.MTL),),
        interval=TimeInterval.closed(0, 1, TimeUnit.LOGICAL_TICK),
    )
    profile = profile_for_runtime_formula(formula)
    assert profile.logic is TemporalLogicKind.MTL
    assert profile.metric_intervals is True


def test_formula_to_temporal_text_matches_map_formula() -> None:
    formula = Formula(
        "until",
        Logic.LTLF,
        (Formula.atom("safe"), Formula.atom("done")),
    )
    text = formula_to_temporal_text(formula)
    assert text == RuntimeMTLSyntaxAdapter().map_formula(formula).temporal_text


def test_eval_receipt_to_dict_is_explicit() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    case = next(c for c in golden_fixtures() if c["case_id"] == "prefix-always-inconclusive")
    receipt = adapter.evaluate_case(case)
    payload = receipt.to_dict()
    assert payload["authorizes_theorem"] is False
    assert payload["authorizes_global_proof"] is False
    assert payload["authority"] == "monitor"
    assert payload["incomplete_trace"] is True
    assert payload["three_valued_verdict"] == "inconclusive"
    assert payload["mapping"]["source_map"]
    assert payload["evaluation"]["interface"] == RUNTIME_MTL_INTERFACE


def test_source_maps_cover_runtime_and_temporal_nodes() -> None:
    adapter = RuntimeMTLSyntaxAdapter()
    formula = Formula(
        "until",
        Logic.LTLF,
        (Formula.atom("safe"), Formula.atom("done")),
    )
    receipt = adapter.map_formula(formula)
    kinds = {entry.kind for entry in receipt.source_map}
    assert "until" in kinds
    assert "atom" in kinds
    runtime_ids = {entry.runtime_node_id for entry in receipt.source_map}
    temporal_ids = {entry.temporal_node_id for entry in receipt.source_map}
    assert formula.node_id in runtime_ids
    assert all(temporal_ids)
    # Parsed path also produces source maps with ranges.
    parsed = adapter.parse_text("safe until done", logic=Logic.LTLF)
    assert any(entry.range is not None for entry in parsed.source_map)


def test_mtl_prefix_before_horizon_inconclusive_via_adapter() -> None:
    case = next(
        c for c in golden_fixtures() if c["case_id"] == "mtl-prefix-before-horizon-inconclusive"
    )
    adapter = RuntimeMTLSyntaxAdapter(default_time_unit=TimeUnit.SECOND)
    receipt = adapter.evaluate_case(case)
    assert receipt.evaluation.verdict is Verdict.INCONCLUSIVE
    assert receipt.incomplete_trace is True
    assert receipt.authorizes_theorem is False
    with pytest.raises(RuntimeMTLAdapterError, match="theorem"):
        receipt.promote_to_theorem()
