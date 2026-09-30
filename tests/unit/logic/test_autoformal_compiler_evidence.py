"""Compiler evidence survives aggregation without becoming an admission."""

from __future__ import annotations

from ipfs_datasets_py.logic import autoformal


def test_segmented_span_retains_every_rule_and_source_clause():
    source = "The agency shall not disclose records. The officer shall retain the file for at least 20 days."
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(session, source, "segmented-evidence")

    assert result["compiler_status"] == "compiled"
    assert [rule["modality"] for rule in result["rules"]] == ["F", "O"]
    assert result["rule"] == result["rules"][0]
    assert result["compilation_complete"] is True
    assert result["admitted"] is False
    assert [component["clause_id"] for component in result["components"]] == [
        "segmented-evidence-c0", "segmented-evidence-c1",
    ]
    for component in result["components"]:
        assert source[component["source_start"]:component["source_end"]] == component["source_text"]
        assert component["rules"] == [component["compiler_rows"][0]["rule"]]
        assert component["compiler_rows"][0]["status"] == "compiled"
        assert component["roundtrip_report"]["semantic_integrity"]["full_source_equivalence_proved"] is False
        assert component["admitted"] is False
        assert all(row["admitted"] is False for row in component["rows"])
    assert result["rules"][1]["temporal_records"][0]["quantity"] == 20


def test_joined_span_retains_every_rule_and_component_identity():
    source = "The agency must retain reports; the clerk may publish notices."
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(session, source, "joined-evidence")

    assert result["compiler_status"] == "compiled"
    assert result["decompiled"] == "Agency must retain reports. Clerk may publish notices."
    assert [rule["modality"] for rule in result["rules"]] == ["O", "P"]
    assert result["rule"] == result["rules"][0]
    assert result["compilation_complete"] is True
    assert "roundtrip" not in result  # Joined spans did not previously claim a roundtrip.
    assert [component["span_id"] for component in result["components"]] == [
        "joined-evidence~0", "joined-evidence~1",
    ]
    assert [component["source_text"] for component in result["components"]] == [
        "The agency must retain reports", "the clerk may publish notices.",
    ]
    assert all(component["admitted"] is False for component in result["components"])


def test_emitted_rule_survives_decompiler_failure_and_partial_coverage(monkeypatch):
    first_rule = {"id": "rendered", "modality": "O"}
    failed_rule = {"id": "decompiler-failed", "modality": "F"}

    def emitted_rules(*_args, **_kwargs):
        return [
            {"status": "compiled", "rule": first_rule, "decompiled": "Agency must retain reports.", "reason": ""},
            {"status": "failed", "rule": failed_rule, "decompiled": "", "reason": "ValueError"},
        ]

    monkeypatch.setattr(autoformal, "_compile_text", emitted_rules)
    session = autoformal.AutoformalSession()
    monkeypatch.setattr(session, "roundtrip_clause", lambda *_args: {"evaluated": False})
    result = autoformal.compile_span(session, "The agency must retain reports.", "failed-rendering")

    assert result["rules"] == [first_rule, failed_rule]
    assert result["rule"] == first_rule
    assert result["compiler_status"] == "compiled"  # Existing any-rendered-component status.
    assert result["compilation_complete"] is False
    assert result["roundtrip"] is False
    assert [row["status"] for row in result["components"][0]["rows"]] == ["compiled", "failed"]
    assert result["admitted"] is False


def test_joined_retry_keeps_both_failed_attempts_and_successful_other_clause(monkeypatch):
    compiler = autoformal._compile_text

    def compile_with_unrepresented_clause(text, **kwargs):
        if "clerk" in text:
            reason = "unsupported:recipient" if not kwargs["allow_partial"] else "partial_still_unsupported:recipient"
            return [{"status": "abstain", "reason": reason, "rule": None, "decompiled": ""}]
        return compiler(text, **kwargs)

    monkeypatch.setattr(autoformal, "_compile_text", compile_with_unrepresented_clause)
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(
        session, "The agency must retain reports; the clerk may publish notices.", "partial-evidence",
    )

    assert result["compiler_status"] == "compiled"
    assert len(result["rules"]) == 1
    assert result["compilation_complete"] is False
    failed = result["components"][1]
    assert failed["compiler_status"] == "abstain"
    assert failed["source_text"] == "the clerk may publish notices."
    assert [attempt["span_id"] for attempt in failed["attempts"]] == [
        "partial-evidence~1", "partial-evidence~1-partial",
    ]
    assert [attempt["allow_partial"] for attempt in failed["attempts"]] == [False, True]
    assert failed["attempts"][0]["reason"] == "unsupported:recipient"
    assert failed["attempts"][1]["reason"] == "partial_still_unsupported:recipient"
    assert result["admitted"] is False


def test_fully_failed_decompilation_preserves_emitted_rules_without_success(monkeypatch):
    rule = {"id": "unrenderable", "modality": "O"}
    monkeypatch.setattr(autoformal, "_compile_text", lambda *_args, **_kwargs: [
        {"status": "failed", "rule": rule, "decompiled": "", "reason": "ValueError"},
    ])
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(session, "The agency must retain reports.", "no-rendering")

    assert result["compiler_status"] == "abstain"
    assert result["rules"] == [rule]
    assert result["components"][0]["rows"][0]["status"] == "failed"
    assert result["compilation_complete"] is False
    assert result["admitted"] is False
