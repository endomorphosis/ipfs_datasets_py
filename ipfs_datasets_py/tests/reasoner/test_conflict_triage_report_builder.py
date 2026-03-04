"""Tests for WS12-05: Conflict Triage Report Builder (JSON + Markdown)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the scripts module is importable.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "legal_data"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest

from build_hybrid_legal_conflict_triage import (
    REMEDIATION_HINTS,
    TRIAGE_REPORT_VERSION,
    build_conflict_triage_report,
    render_triage_json,
    render_triage_markdown,
)
from reasoner.hybrid_v2_blueprint import (
    AtomV2,
    CanonicalIdV2,
    ConditionNodeV2,
    DeonticOpV2,
    FrameKindV2,
    FrameV2,
    LegalIRV2,
    NormV2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(key: str) -> FrameV2:
    return FrameV2(
        id=CanonicalIdV2(namespace="frame", value=key),
        kind=FrameKindV2.ACTION,
        predicate=key,
    )


def _make_norm(key: str, op: DeonticOpV2, frame_ref: str) -> NormV2:
    return NormV2(
        id=CanonicalIdV2(namespace="norm", value=key),
        op=op,
        target_frame_ref=frame_ref,
        activation=ConditionNodeV2(op="true"),
        exceptions=[],
    )


def _conflict_ir() -> LegalIRV2:
    """Return an IR that has a modal conflict (O + F on same frame)."""
    frame_ref = "frame:submit"
    frames = {"frame:submit": _make_frame("submit")}
    norms = {
        "norm:n1": _make_norm("n1", DeonticOpV2.O, frame_ref),
        "norm:n2": _make_norm("n2", DeonticOpV2.F, frame_ref),
    }
    return LegalIRV2(jurisdiction="test", frames=frames, norms=norms)


def _empty_ir() -> LegalIRV2:
    """Return an IR with no norms (no conflicts)."""
    return LegalIRV2(jurisdiction="test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildConflictTriageReport:
    def test_required_keys_present(self):
        report = build_conflict_triage_report(_empty_ir())
        for key in ("report_id", "triage_version", "conflict_count", "conflicts", "generated_at"):
            assert key in report, f"Missing key: {key}"

    def test_triage_version(self):
        report = build_conflict_triage_report(_empty_ir())
        assert report["triage_version"] == TRIAGE_REPORT_VERSION

    def test_empty_ir_zero_conflicts(self):
        report = build_conflict_triage_report(_empty_ir())
        assert report["conflict_count"] == 0
        assert report["conflicts"] == []

    def test_conflict_ir_nonzero_count(self):
        report = build_conflict_triage_report(_conflict_ir())
        assert report["conflict_count"] > 0
        assert len(report["conflicts"]) == report["conflict_count"]

    def test_each_conflict_has_remediation_hint(self):
        report = build_conflict_triage_report(_conflict_ir())
        for c in report["conflicts"]:
            assert "remediation_hint" in c
            assert len(c["remediation_hint"]) > 0

    def test_remediation_hint_text_matches(self):
        report = build_conflict_triage_report(_conflict_ir())
        for c in report["conflicts"]:
            reason_code = c.get("reason_code", "")
            expected = REMEDIATION_HINTS.get(reason_code)
            if expected:
                assert c["remediation_hint"] == expected

    def test_deterministic_report_id(self):
        ir = _empty_ir()
        r1 = build_conflict_triage_report(ir)
        r2 = build_conflict_triage_report(ir)
        assert r1["report_id"] == r2["report_id"]

    def test_deterministic_generated_at(self):
        ir = _conflict_ir()
        r1 = build_conflict_triage_report(ir)
        r2 = build_conflict_triage_report(ir)
        assert r1["generated_at"] == r2["generated_at"]

    def test_explicit_report_id_is_preserved(self):
        report = build_conflict_triage_report(_empty_ir(), report_id="my-custom-id")
        assert report["report_id"] == "my-custom-id"

    def test_conflicts_are_sorted_deterministically(self):
        ir = _conflict_ir()
        r1 = build_conflict_triage_report(ir)
        r2 = build_conflict_triage_report(ir)
        ids1 = [(c.get("class"), c.get("norm_ids")) for c in r1["conflicts"]]
        ids2 = [(c.get("class"), c.get("norm_ids")) for c in r2["conflicts"]]
        assert ids1 == ids2


class TestRenderTriageJson:
    def test_valid_json(self):
        report = build_conflict_triage_report(_empty_ir())
        raw = render_triage_json(report)
        parsed = json.loads(raw)
        assert parsed["triage_version"] == TRIAGE_REPORT_VERSION

    def test_byte_stable(self):
        ir = _conflict_ir()
        report = build_conflict_triage_report(ir)
        j1 = render_triage_json(report)
        j2 = render_triage_json(report)
        assert j1 == j2

    def test_byte_stable_twice_from_scratch(self):
        ir = _conflict_ir()
        j1 = render_triage_json(build_conflict_triage_report(ir))
        j2 = render_triage_json(build_conflict_triage_report(ir))
        assert j1 == j2


class TestRenderTriageMarkdown:
    def test_contains_title(self):
        report = build_conflict_triage_report(_empty_ir())
        md = render_triage_markdown(report)
        assert "Conflict Triage Report" in md

    def test_contains_conflict_class(self):
        report = build_conflict_triage_report(_conflict_ir())
        md = render_triage_markdown(report)
        for c in report["conflicts"]:
            assert c["class"] in md

    def test_contains_remediation_hint_text(self):
        report = build_conflict_triage_report(_conflict_ir())
        md = render_triage_markdown(report)
        for c in report["conflicts"]:
            # At least first few words of the hint should appear.
            hint_start = c["remediation_hint"][:30]
            assert hint_start in md

    def test_byte_stable(self):
        ir = _conflict_ir()
        report = build_conflict_triage_report(ir)
        m1 = render_triage_markdown(report)
        m2 = render_triage_markdown(report)
        assert m1 == m2

    def test_byte_stable_twice_from_scratch(self):
        ir = _conflict_ir()
        m1 = render_triage_markdown(build_conflict_triage_report(ir))
        m2 = render_triage_markdown(build_conflict_triage_report(ir))
        assert m1 == m2

    def test_empty_conflicts_still_valid_markdown(self):
        report = build_conflict_triage_report(_empty_ir())
        md = render_triage_markdown(report)
        assert "Conflict Triage Report" in md
        assert "0" in md  # conflict count zero appears
