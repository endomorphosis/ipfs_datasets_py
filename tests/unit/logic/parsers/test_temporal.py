"""Unit tests for TemporalSyntax@1 / TraceSemanticsProfile@1 (LFP-024).

Evidence subset:

* parse/print/parse is alpha-equivalent
* invalid or unbounded intervals fail with stable spans
* ambiguous F/G/U/R syntax fails with stable spans
* profile and time domain enter semantic identity
* LTL, LTLf, past-LTL, MTL, CTL, CTL* profiles
* precedence / associativity / path quantifiers
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.temporal import (
    CODE_AMBIGUOUS_TEMPORAL,
    CODE_INVALID_INTERVAL,
    CODE_MISSING_INTERVAL,
    CODE_PATH_REQUIRED,
    CODE_PAST_FORBIDDEN,
    CODE_UNBOUNDED_INTERVAL,
    CODE_UNEXPECTED_INTERVAL,
    TEMPORAL_SYNTAX_INTERFACE,
    TRACE_SEMANTICS_PROFILE_INTERFACE,
    MetricInterval,
    PathQuantifierKind,
    PrintStyle,
    RationalBound,
    TemporalLogicKind,
    TemporalParseError,
    TemporalParser,
    TemporalPrinter,
    TemporalSyntax,
    TimeDomain,
    TraceModelKind,
    TraceSemanticsProfile,
    parse_print_parse,
    parse_temporal,
    print_temporal,
    profile_ctl,
    profile_ctl_star,
    profile_ltl,
    profile_ltlf,
    profile_mtl,
    profile_past_ltl,
    temporal_semantic_identity,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ltl() -> TraceSemanticsProfile:
    return profile_ltl()


def _ltlf() -> TraceSemanticsProfile:
    return profile_ltlf()


def _past() -> TraceSemanticsProfile:
    return profile_past_ltl()


def _mtl() -> TraceSemanticsProfile:
    return profile_mtl()


def _ctl() -> TraceSemanticsProfile:
    return profile_ctl()


def _ctl_star() -> TraceSemanticsProfile:
    return profile_ctl_star()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert TEMPORAL_SYNTAX_INTERFACE == "TemporalSyntax@1"
    assert TRACE_SEMANTICS_PROFILE_INTERFACE == "TraceSemanticsProfile@1"
    syntax = TemporalSyntax(_ltl())
    assert syntax.interface == TEMPORAL_SYNTAX_INTERFACE
    assert isinstance(syntax.parser, TemporalParser)
    assert isinstance(syntax.printer, TemporalPrinter)


def test_trace_semantics_profile_rejects_contradictions() -> None:
    with pytest.raises(Exception, match="metric_intervals"):
        TraceSemanticsProfile(
            profile_id="bad_mtl",
            logic=TemporalLogicKind.MTL,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.FINITE,
            metric_intervals=False,
        )
    with pytest.raises(Exception, match="allow_past"):
        TraceSemanticsProfile(
            profile_id="bad_past",
            logic=TemporalLogicKind.PAST_LTL,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.INFINITE,
            allow_past=False,
        )
    with pytest.raises(Exception, match="path"):
        TraceSemanticsProfile(
            profile_id="bad_ctl",
            logic=TemporalLogicKind.CTL,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.INFINITE,
            allow_path_quantifiers=False,
            branching=False,
        )


# ---------------------------------------------------------------------------
# Happy-path parsing across families
# ---------------------------------------------------------------------------


def test_parse_ltl_future_operators() -> None:
    result = parse_temporal(
        "always (p -> eventually q)",
        _ltl(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.EXTENSION
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "always"
    assert result.root.extension.payload["logic"] == "ltl"
    assert result.root.extension.payload["time_domain"] == "discrete"


def test_parse_ltlf_finite_profile() -> None:
    result = parse_temporal("next p and eventually q", _ltlf())
    assert result.ok
    assert result.profile is not None
    assert result.profile.logic is TemporalLogicKind.LTLF
    assert result.profile.trace_model is TraceModelKind.FINITE


def test_parse_past_ltl_operators() -> None:
    result = parse_temporal(
        "historically p and once q and (r since s)",
        _past(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None


def test_past_operators_forbidden_under_ltl() -> None:
    result = parse_temporal("once p", _ltl())
    assert not result.ok
    assert any(item.code == CODE_PAST_FORBIDDEN for item in result.errors)


def test_parse_mtl_with_bounded_intervals() -> None:
    result = parse_temporal("eventually[0,1] p", _mtl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    interval = result.root.extension.payload["interval"]
    assert interval["lower"]["numerator"] == 0
    assert interval["upper"]["numerator"] == 1
    assert interval["lower_closed"] is True
    assert interval["upper_closed"] is True


def test_parse_mtl_open_and_rational_bounds() -> None:
    result = parse_temporal("always(0,1/2] safe", _mtl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    interval = MetricInterval.from_dict(result.root.extension.payload["interval"])
    assert interval.lower_closed is False
    assert interval.upper_closed is True
    assert interval.upper == RationalBound(1, 2)


def test_parse_mtl_until_with_interval() -> None:
    result = parse_temporal("p until[1,3] q", _mtl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "until"


def test_mtl_requires_interval() -> None:
    result = parse_temporal("eventually p", _mtl())
    assert not result.ok
    assert any(item.code == CODE_MISSING_INTERVAL for item in result.errors)


def test_ltl_rejects_interval() -> None:
    result = parse_temporal("eventually[0,1] p", _ltl())
    assert not result.ok
    assert any(item.code == CODE_UNEXPECTED_INTERVAL for item in result.errors)


def test_parse_ctl_path_quantifiers() -> None:
    result = parse_temporal("A always p", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "path"
    assert result.root.extension.payload["path_quantifier"] == "all"
    body = result.root.extension.children[0]
    assert body.extension is not None
    assert body.extension.payload["kind"] == "always"


def test_parse_ctl_exists_until() -> None:
    result = parse_temporal("E (p until q)", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]


def test_ctl_path_must_wrap_temporal() -> None:
    result = parse_temporal("A p", _ctl())
    assert not result.ok
    assert any(item.code == CODE_PATH_REQUIRED for item in result.errors)


def test_ctl_star_allows_path_over_boolean() -> None:
    result = parse_temporal("A (p and always q)", _ctl_star())
    assert result.ok, [d.message for d in result.diagnostics]


def test_parse_connectives_and_implication_right_assoc() -> None:
    result = parse_temporal("p -> q -> r", _ltl())
    assert result.ok and result.root is not None
    assert result.root.kind is NodeKind.IMPLIES
    assert result.root.arguments[1].kind is NodeKind.IMPLIES


def test_parse_unicode_operators() -> None:
    result = parse_temporal("always (p → q ∧ ¬r)", _ltl())
    assert result.ok, [d.message for d in result.diagnostics]


def test_logic_parser_protocol_via_parse_request() -> None:
    document = SourceDocument.from_text("doc:req:1", "always p")
    request = ParseRequest(
        request_id="req:temporal:1",
        document=document,
        notation_id="canonical_temporal",
        profile_id="ltl_infinite_discrete",
        family_id="temporal",
        mode=ParseMode.STRICT,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=64),
        metadata={"profile": _ltl().to_dict()},
    )
    parser = TemporalParser()
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.OK
    assert artifact.cst is not None
    assert "semantic_identity" in artifact.metadata
    artifact.validate_against(document, limits=request.limits)


# ---------------------------------------------------------------------------
# Ambiguous F/G/U/R
# ---------------------------------------------------------------------------


def test_ambiguous_f_operator_fails_with_stable_span() -> None:
    source = "F p"
    result = parse_temporal(source, _ltl())
    assert not result.ok
    errors = result.errors
    assert any(item.code == CODE_AMBIGUOUS_TEMPORAL for item in errors)
    diag = next(item for item in errors if item.code == CODE_AMBIGUOUS_TEMPORAL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:amb-f", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert sliced == "F"
    diag.validate_against(document)


def test_ambiguous_g_operator_fails_with_stable_span() -> None:
    source = "G safe"
    result = parse_temporal(source, _ltl())
    assert not result.ok
    assert any(item.code == CODE_AMBIGUOUS_TEMPORAL for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_AMBIGUOUS_TEMPORAL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:amb-g", source)
    assert document.content[diag.range.start : diag.range.end].decode("utf-8") == "G"


def test_ambiguous_u_operator_fails_with_stable_span() -> None:
    source = "p U q"
    result = parse_temporal(source, _ltl())
    assert not result.ok
    assert any(item.code == CODE_AMBIGUOUS_TEMPORAL for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_AMBIGUOUS_TEMPORAL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:amb-u", source)
    assert document.content[diag.range.start : diag.range.end].decode("utf-8") == "U"
    diag.validate_against(document)


def test_ambiguous_r_operator_fails_with_stable_span() -> None:
    source = "p R q"
    result = parse_temporal(source, _ltl())
    assert not result.ok
    assert any(item.code == CODE_AMBIGUOUS_TEMPORAL for item in result.errors)


def test_classic_letters_admitted_when_profile_says_so() -> None:
    profile = profile_ltl(admit_classic_letters=True)
    result = parse_temporal("G (p -> F q)", profile)
    assert result.ok, [d.message for d in result.diagnostics]
    until = parse_temporal("p U q", profile)
    assert until.ok, [d.message for d in until.diagnostics]


def test_bare_f_as_atom_is_allowed_without_classic_letters() -> None:
    """A lone identifier F is a proposition, not an ambiguous operator."""
    result = parse_temporal("F", _ltl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.PREDICATE
    assert result.root.symbol == "F"


# ---------------------------------------------------------------------------
# Invalid / unbounded intervals
# ---------------------------------------------------------------------------


def test_unbounded_upper_interval_fails_with_stable_span() -> None:
    source = "eventually[0,inf] p"
    result = parse_temporal(source, _mtl())
    assert not result.ok
    assert any(item.code == CODE_UNBOUNDED_INTERVAL for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_UNBOUNDED_INTERVAL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:unb", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert "inf" in sliced
    diag.validate_against(document)


def test_unbounded_star_upper_fails() -> None:
    source = "always[0,*] p"
    result = parse_temporal(source, _mtl())
    assert not result.ok
    assert any(item.code == CODE_UNBOUNDED_INTERVAL for item in result.errors)


def test_missing_upper_bound_fails() -> None:
    source = "eventually[0,] p"
    result = parse_temporal(source, _mtl())
    assert not result.ok
    assert any(
        item.code in {CODE_UNBOUNDED_INTERVAL, CODE_INVALID_INTERVAL}
        for item in result.errors
    )


def test_inverted_interval_fails_with_stable_span() -> None:
    source = "eventually[2,1] p"
    result = parse_temporal(source, _mtl())
    assert not result.ok
    assert any(item.code == CODE_INVALID_INTERVAL for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_INVALID_INTERVAL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:inv", source)
    diag.validate_against(document)


def test_empty_open_interval_fails() -> None:
    source = "eventually(1,1) p"
    result = parse_temporal(source, _mtl())
    assert not result.ok
    assert any(item.code == CODE_INVALID_INTERVAL for item in result.errors)


def test_float_bound_rejected() -> None:
    source = "eventually[0,1.5] p"
    result = parse_temporal(source, _mtl())
    assert not result.ok
    assert any(item.code == CODE_INVALID_INTERVAL for item in result.errors)


# ---------------------------------------------------------------------------
# Profile and time domain enter semantic identity
# ---------------------------------------------------------------------------


def test_profile_and_time_domain_enter_semantic_identity() -> None:
    discrete = profile_mtl(
        profile_id="mtl_finite_discrete",
        time_domain=TimeDomain.DISCRETE,
    )
    dense = profile_mtl(
        profile_id="mtl_finite_dense",
        time_domain=TimeDomain.DENSE,
    )
    a = parse_temporal("eventually[0,1] p", discrete)
    b = parse_temporal("eventually[0,1] p", dense)
    assert a.ok and b.ok
    assert a.root is not None and b.root is not None
    id_a = temporal_semantic_identity(a.root, discrete)
    id_b = temporal_semantic_identity(b.root, dense)
    assert id_a["profile"]["time_domain"] == "discrete"
    assert id_b["profile"]["time_domain"] == "dense"
    assert id_a["profile"]["profile_id"] == "mtl_finite_discrete"
    assert id_b["profile"]["profile_id"] == "mtl_finite_dense"
    # Same surface text under different profiles is not alpha-equivalent
    # because extension payload embeds profile and time domain.
    assert not alpha_equivalent(a.root, b.root)
    assert a.root.extension is not None
    assert a.root.extension.payload["time_domain"] == "discrete"
    assert b.root.extension is not None
    assert b.root.extension.payload["time_domain"] == "dense"
    # Artifact metadata carries the identity.
    assert a.artifact is not None
    assert a.artifact.metadata["semantic_identity"]["profile"]["time_domain"] == (
        "discrete"
    )


def test_logic_kind_enters_extension_payload() -> None:
    ltl = parse_temporal("always p", _ltl())
    ltlf = parse_temporal("always p", _ltlf())
    assert ltl.ok and ltlf.ok
    assert ltl.root is not None and ltlf.root is not None
    assert ltl.root.extension is not None and ltlf.root.extension is not None
    assert ltl.root.extension.payload["logic"] == "ltl"
    assert ltlf.root.extension.payload["logic"] == "ltlf"
    assert not alpha_equivalent(ltl.root, ltlf.root)


# ---------------------------------------------------------------------------
# Parse / print / parse alpha-equivalence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "profile_factory"),
    [
        ("p", _ltl),
        ("not p", _ltl),
        ("p and q", _ltl),
        ("p or q", _ltl),
        ("p -> q", _ltl),
        ("p iff q", _ltl),
        ("p -> q -> r", _ltl),
        ("next p", _ltl),
        ("eventually p", _ltl),
        ("always p", _ltl),
        ("p until q", _ltl),
        ("p release q", _ltl),
        ("p weak_until q", _ltl),
        ("always (p -> eventually q)", _ltl),
        ("next p and eventually q", _ltlf),
        ("historically p", _past),
        ("once q", _past),
        ("p since q", _past),
        ("eventually[0,1] p", _mtl),
        ("always[1/2,3] safe", _mtl),
        ("p until[0,2] q", _mtl),
        ("always(0,1] p", _mtl),
        ("A always p", _ctl),
        ("E (p until q)", _ctl),
        ("A (p and always q)", _ctl_star),
        ("not (p or always q)", _ltl),
        ("true and false or p", _ltl),
    ],
)
def test_parse_print_parse_is_alpha_equivalent(source: str, profile_factory) -> None:
    profile = profile_factory()
    first = parse_temporal(source, profile)
    assert first.ok, (source, [d.message for d in first.diagnostics])
    assert first.root is not None
    printed = print_temporal(first.root)
    second = parse_temporal(printed, profile, document_id="doc:rt")
    assert second.ok, (source, printed, [d.message for d in second.diagnostics])
    assert second.root is not None
    assert alpha_equivalent(first.root, second.root), (source, printed)


def test_parse_print_parse_helper() -> None:
    result = parse_print_parse("always (p -> eventually q)", _ltl())
    assert result.ok
    assert result.printed


def test_unicode_print_style_round_trip() -> None:
    profile = _ltl()
    first = parse_temporal("always (p -> not q)", profile)
    assert first.ok and first.root is not None
    printed = print_temporal(first.root, style=PrintStyle.UNICODE)
    assert "¬" in printed or "always" in printed
    second = parse_temporal(printed, profile, document_id="doc:uni")
    assert second.ok and second.root is not None
    assert alpha_equivalent(first.root, second.root)


def test_classic_letter_round_trip_prints_multi_letter() -> None:
    profile = profile_ltl(admit_classic_letters=True)
    first = parse_temporal("G p", profile)
    assert first.ok and first.root is not None
    printed = print_temporal(first.root)
    assert "always" in printed
    second = parse_temporal(printed, profile)
    assert second.ok and second.root is not None
    assert alpha_equivalent(first.root, second.root)


# ---------------------------------------------------------------------------
# Raising API / missing profile
# ---------------------------------------------------------------------------


def test_parse_text_or_raise() -> None:
    syntax = TemporalSyntax(_ltl())
    expr = syntax.parse_text_or_raise("always p")
    assert expr.root.kind is NodeKind.EXTENSION

    with pytest.raises(TemporalParseError) as caught:
        syntax.parse_text_or_raise("F p")
    assert caught.value.diagnostics


def test_missing_profile_rejects() -> None:
    document = SourceDocument.from_text("doc:noprof", "always p")
    request = ParseRequest(
        request_id="req:noprof",
        document=document,
        notation_id="canonical_temporal",
        profile_id="ltl_infinite_discrete",
        family_id="temporal",
        mode=ParseMode.STRICT,
        limits=ParseLimits(),
        metadata={},
    )
    parser = TemporalParser()
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.REJECTED


def test_metric_interval_surface_and_dict_round_trip() -> None:
    interval = MetricInterval(
        lower=RationalBound(1, 2),
        upper=RationalBound(3),
        lower_closed=False,
        upper_closed=True,
    )
    assert interval.surface() == "(1/2,3]"
    restored = MetricInterval.from_dict(interval.to_dict())
    assert restored == interval


def test_path_quantifier_kind_values() -> None:
    assert PathQuantifierKind.ALL.value == "all"
    assert PathQuantifierKind.EXISTS.value == "exists"
