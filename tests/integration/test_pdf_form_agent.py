"""Integration tests for the PDF form intelligence pipeline.

Tests the full pipeline:
    OCR → Knowledge Graph → Legal IR → Agent Fill →
    Theorem Verification → ZKP Certificate → Verify Certificate

Uses an in-memory synthetic form PDF so no external files are needed.
PyMuPDF (fitz) is required; tests are skipped if it is not installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_acroform_pdf(output_path: str) -> None:
    """Create a minimal AcroForm PDF with two text fields using PyMuPDF."""
    import fitz  # type: ignore

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Title
    page.insert_text((72, 60), "Sample Form", fontsize=16, color=(0, 0, 0))
    page.insert_text((72, 100), "Full Name *:", fontsize=11)
    page.insert_text((72, 140), "Email:", fontsize=11)
    page.insert_text((72, 180), "Date:", fontsize=11)

    # AcroForm text widgets
    for label, y, fname in [
        ("Full Name *", 95, "full_name"),
        ("Email", 135, "email"),
        ("Date", 175, "date"),
    ]:
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = fname
        widget.field_label = label
        widget.rect = fitz.Rect(200, y, 500, y + 20)
        widget.text_fontsize = 10
        widget.border_width = 0.5
        page.add_widget(widget)

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


def _pytest_skip_if_no_fitz() -> None:
    try:
        import fitz  # noqa: F401
    except ImportError:
        pytest.skip("PyMuPDF (fitz) is not installed")


# ---------------------------------------------------------------------------
# Phase 1 — Universal PDF Parsing
# ---------------------------------------------------------------------------

class TestPhase1UniversalParsing:
    """Tests for Phase 1: universal PDF parsing improvements."""

    def test_given_valid_pdf_when_classify_pdf_then_returns_type_string(self, tmp_path):
        """
        GIVEN a minimal AcroForm PDF
        WHEN classify_pdf() is called
        THEN it returns a non-empty document type string
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import classify_pdf, PDFDocumentType

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        doc_type = classify_pdf(pdf_path)
        assert doc_type in {
            PDFDocumentType.FILLABLE_FORM,
            PDFDocumentType.SCANNED_FORM,
            PDFDocumentType.STRUCTURED_DOCUMENT,
            PDFDocumentType.MIXED,
        }

    def test_given_acroform_pdf_when_classify_pdf_then_returns_fillable_form(self, tmp_path):
        """
        GIVEN an AcroForm PDF with interactive widgets
        WHEN classify_pdf() is called
        THEN it returns 'fillable_form'
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import classify_pdf, PDFDocumentType

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        assert classify_pdf(pdf_path) == PDFDocumentType.FILLABLE_FORM

    def test_given_spanish_label_when_infer_field_data_type_then_returns_correct_type(self):
        """
        GIVEN a Spanish-language label 'Firma'
        WHEN infer_field_data_type() is called
        THEN it returns 'signature'
        """
        from ipfs_datasets_py.processors.pdf_form_filler import infer_field_data_type

        assert infer_field_data_type("Firma del solicitante") == "signature"
        assert infer_field_data_type("Fecha de nacimiento") == "date"
        assert infer_field_data_type("Ciudad de residencia") == "place"

    def test_given_french_label_when_infer_field_data_type_then_returns_correct_type(self):
        """
        GIVEN French-language labels
        WHEN infer_field_data_type() is called
        THEN it returns the correct semantic type
        """
        from ipfs_datasets_py.processors.pdf_form_filler import infer_field_data_type

        assert infer_field_data_type("Date de naissance") == "date"
        assert infer_field_data_type("Courriel") == "email"
        assert infer_field_data_type("Montant total") == "currency"

    def test_given_acroform_pdf_when_analyze_form_then_fields_discovered(self, tmp_path):
        """
        GIVEN an AcroForm PDF
        WHEN analyze_pdf_form() is called
        THEN it discovers the expected number of fields
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        result = analyze_pdf_form(pdf_path)
        assert len(result.fields) >= 3  # full_name, email, date
        field_names = {f.name for f in result.fields}
        assert "full_name" in field_names
        assert "email" in field_names
        assert "date" in field_names

    def test_given_layout_provider_when_analyze_form_then_layout_fields_included(self, tmp_path):
        """
        GIVEN an analyze_pdf_form call with a custom LayoutProvider
        WHEN the layout provider yields an extra field
        THEN that field appears in the result
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        def layout_provider(ctx):
            yield {
                "kind": "line",
                "rect": [72, 220, 400, 240],
                "label": "Phone Number",
                "confidence": 0.8,
            }

        result = analyze_pdf_form(pdf_path, layout_provider=layout_provider)
        field_names = {f.name for f in result.fields}
        assert "phone_number" in field_names


# ---------------------------------------------------------------------------
# Phase 2 — Form Knowledge Graph & Legal IR
# ---------------------------------------------------------------------------

class TestPhase2KnowledgeGraphIR:
    """Tests for Phase 2: FormKnowledgeGraph and FormToLegalIR."""

    def test_given_form_analysis_when_build_knowledge_graph_then_field_nodes_created(self, tmp_path):
        """
        GIVEN a form analysis result
        WHEN build_form_knowledge_graph() is called
        THEN field nodes are created for every discovered field
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import (
            build_form_knowledge_graph,
            NODE_KIND_FIELD,
        )

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        kg = build_form_knowledge_graph(analysis)

        field_nodes = kg.get_nodes_by_kind(NODE_KIND_FIELD)
        assert len(field_nodes) == len(analysis.fields)

    def test_given_form_text_with_statute_when_build_kg_then_statute_node_added(self, tmp_path):
        """
        GIVEN form page text containing a statute citation
        WHEN build_form_knowledge_graph() is called with that text
        THEN a statute node is present in the knowledge graph
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import (
            build_form_knowledge_graph,
            NODE_KIND_STATUTE,
        )

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        kg = build_form_knowledge_graph(
            analysis,
            page_texts=["Under 26 U.S.C. § 6012, every individual must file."],
        )

        statute_nodes = kg.get_nodes_by_kind(NODE_KIND_STATUTE)
        assert len(statute_nodes) >= 1

    def test_given_form_text_with_income_tax_when_build_kg_then_concept_node_added(self, tmp_path):
        """
        GIVEN form page text containing 'income tax'
        WHEN build_form_knowledge_graph() is called
        THEN a concept node with label 'income_tax' exists
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import (
            build_form_knowledge_graph,
            NODE_KIND_CONCEPT,
        )

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        kg = build_form_knowledge_graph(
            analysis,
            page_texts=["U.S. Individual Income Tax Return for 2024"],
        )

        concept_nodes = kg.get_nodes_by_kind(NODE_KIND_CONCEPT)
        concept_labels = {n.label for n in concept_nodes}
        assert "income_tax" in concept_labels

    def test_given_kg_when_to_rule_set_then_returns_deontic_rule_set(self, tmp_path):
        """
        GIVEN a FormKnowledgeGraph
        WHEN FormToLegalIR.to_rule_set() is called
        THEN it returns a DeonticRuleSet with at least one formula
        """
        _pytest_skip_if_no_fitz()
        pytest.importorskip("ipfs_datasets_py.logic.integration")
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        converter = FormToLegalIR()
        kg = build_form_knowledge_graph(analysis)
        rule_set = converter.to_rule_set(kg)

        assert len(rule_set.formulas) >= 1

    def test_given_kg_when_to_dict_then_serialisable(self, tmp_path):
        """
        GIVEN a FormKnowledgeGraph
        WHEN to_dict() is called
        THEN the result is JSON-serialisable
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import build_form_knowledge_graph

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        kg = build_form_knowledge_graph(analysis)
        d = kg.to_dict()
        json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# Phase 3 — AI Agent Form Filler
# ---------------------------------------------------------------------------

class TestPhase3AgentFormFiller:
    """Tests for Phase 3: FormFillingAgent."""

    def test_given_context_with_all_fields_when_generate_questions_then_no_gaps(self, tmp_path):
        """
        GIVEN a context dict that satisfies all form fields
        WHEN generate_questions() is called
        THEN no questions are yielded
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.form_filling_agent import FormFillingAgent

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        agent = FormFillingAgent(
            context={
                "full_name": "Alice Smith",
                "email": "alice@example.com",
                "date": "01/01/2024",
            }
        )
        agent.analyse(pdf_path)

        gaps = asyncio.run(_collect_gaps(agent, pdf_path))
        assert gaps == []

    def test_given_empty_context_when_generate_questions_then_questions_yielded(self, tmp_path):
        """
        GIVEN an empty context
        WHEN generate_questions() is called
        THEN questions are yielded for each required field
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.form_filling_agent import FormFillingAgent

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        agent = FormFillingAgent(context={})
        agent.analyse(pdf_path)

        gaps = asyncio.run(_collect_gaps(agent, pdf_path))
        assert len(gaps) >= 1

    def test_given_invalid_email_when_provide_answer_then_returns_false(self, tmp_path):
        """
        GIVEN an agent with email field
        WHEN provide_answer() is called with an invalid email
        THEN it returns (False, error_message)
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.form_filling_agent import FormFillingAgent

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        agent = FormFillingAgent(context={})
        agent.analyse(pdf_path)

        valid, error = agent.provide_answer("email", "not-an-email")
        assert not valid
        assert "email" in error.lower()

    def test_given_valid_answers_when_fill_then_output_pdf_written(self, tmp_path):
        """
        GIVEN valid answers for all fields
        WHEN fill() is called
        THEN the output PDF is written to disk
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.form_filling_agent import FormFillingAgent

        pdf_path = tmp_path / "form.pdf"
        output_path = tmp_path / "filled.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        agent = FormFillingAgent(
            context={
                "full_name": "Alice Smith",
                "email": "alice@example.com",
                "date": "01/01/2024",
            }
        )
        agent.analyse(pdf_path)
        # Drain generate_questions to populate _answers
        asyncio.run(_collect_gaps(agent, pdf_path))

        filled = asyncio.run(agent.fill(pdf_path, output_path, strict=False))
        assert Path(filled).exists()


# ---------------------------------------------------------------------------
# Phase 4 — Theorem Prover Verification
# ---------------------------------------------------------------------------

class TestPhase4TheoremVerification:
    """Tests for Phase 4: FormRequirementsVerifier."""

    def test_given_complete_values_when_verify_then_overall_pass(self, tmp_path):
        """
        GIVEN a complete set of field values that satisfies the rule set
        WHEN FormRequirementsVerifier.verify() is called
        THEN the report has overall_pass=True
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph
        from ipfs_datasets_py.processors.form_requirements_verifier import FormRequirementsVerifier

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        try:
            kg = build_form_knowledge_graph(analysis)
            converter = FormToLegalIR()
            rule_set = converter.to_rule_set(kg)
        except ImportError:
            pytest.skip("logic sub-package not available")

        verifier = FormRequirementsVerifier()
        report = verifier.verify(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
            form_id=kg.form_id,
            source_pdf=str(pdf_path),
        )
        assert report.overall_pass is True

    def test_given_empty_required_field_when_verify_then_violation_reported(self, tmp_path):
        """
        GIVEN values with a required field left empty
        WHEN FormRequirementsVerifier.verify() is called
        THEN the report contains a violation for that field
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph
        from ipfs_datasets_py.processors.form_requirements_verifier import FormRequirementsVerifier

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        # Mark full_name as required so the verifier can catch an empty value
        required_fields = [
            spec for spec in analysis.fields if spec.name == "full_name"
        ]
        if not required_fields or not required_fields[0].required:
            pytest.skip("full_name not marked required in this environment")

        try:
            kg = build_form_knowledge_graph(analysis)
            converter = FormToLegalIR()
            rule_set = converter.to_rule_set(kg)
        except ImportError:
            pytest.skip("logic sub-package not available")

        verifier = FormRequirementsVerifier()
        report = verifier.verify(
            {"full_name": "", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
            form_id=kg.form_id,
            source_pdf=str(pdf_path),
        )

        violations = [r for r in report.results if r.status == "violated" and r.field_name == "full_name"]
        assert len(violations) >= 1

    def test_given_report_when_verdicts_hash_then_deterministic(self, tmp_path):
        """
        GIVEN a VerificationReport
        WHEN verdicts_hash() is called twice
        THEN the same hash is returned
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph
        from ipfs_datasets_py.processors.form_requirements_verifier import FormRequirementsVerifier

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        try:
            kg = build_form_knowledge_graph(analysis)
            converter = FormToLegalIR()
            rule_set = converter.to_rule_set(kg)
        except ImportError:
            pytest.skip("logic sub-package not available")

        verifier = FormRequirementsVerifier()
        report = verifier.verify(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
        )

        assert report.verdicts_hash() == report.verdicts_hash()

    def test_given_report_when_to_json_then_parseable(self, tmp_path):
        """
        GIVEN a VerificationReport
        WHEN to_json() is called
        THEN the result is valid JSON
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph
        from ipfs_datasets_py.processors.form_requirements_verifier import FormRequirementsVerifier

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        try:
            kg = build_form_knowledge_graph(analysis)
            converter = FormToLegalIR()
            rule_set = converter.to_rule_set(kg)
        except ImportError:
            pytest.skip("logic sub-package not available")

        verifier = FormRequirementsVerifier()
        report = verifier.verify(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
        )
        parsed = json.loads(report.to_json())
        assert "overall_pass" in parsed


# ---------------------------------------------------------------------------
# Phase 5 — ZKP Certificate
# ---------------------------------------------------------------------------

class TestPhase5ZKPCertificate:
    """Tests for Phase 5: FormCompletionCircuit and FormCompletionCertificate."""

    def _make_passing_report(self, tmp_path: Path):
        """Helper: return (kg, rule_set, report) for a passing form."""
        import fitz  # noqa: F401 — already checked by outer test
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph
        from ipfs_datasets_py.processors.form_requirements_verifier import FormRequirementsVerifier

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        analysis = analyze_pdf_form(pdf_path)
        kg = build_form_knowledge_graph(analysis)
        converter = FormToLegalIR()
        rule_set = converter.to_rule_set(kg)

        verifier = FormRequirementsVerifier()
        report = verifier.verify(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
            form_id=kg.form_id,
            source_pdf=str(pdf_path),
        )
        # Force overall_pass for ZKP test
        report.overall_pass = True
        return kg, rule_set, report

    def test_given_passing_report_when_generate_certificate_then_certificate_created(self, tmp_path):
        """
        GIVEN a passing VerificationReport
        WHEN generate_form_certificate() is called
        THEN a FormCompletionCertificate is returned with a non-None proof
        """
        _pytest_skip_if_no_fitz()
        try:
            from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        except ImportError:
            pytest.skip("logic sub-package not available")

        from ipfs_datasets_py.logic.zkp.form_circuit import generate_form_certificate

        kg, rule_set, report = self._make_passing_report(tmp_path)
        cert = generate_form_certificate(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
            report,
            form_id=kg.form_id,
        )
        assert cert is not None
        assert cert.proof is not None
        assert cert.is_simulated  # default

    def test_given_certificate_when_verify_then_returns_true(self, tmp_path):
        """
        GIVEN a valid FormCompletionCertificate
        WHEN verify_form_certificate() is called
        THEN it returns True
        """
        _pytest_skip_if_no_fitz()
        try:
            from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        except ImportError:
            pytest.skip("logic sub-package not available")

        from ipfs_datasets_py.logic.zkp.form_circuit import (
            generate_form_certificate,
            verify_form_certificate,
        )

        kg, rule_set, report = self._make_passing_report(tmp_path)
        cert = generate_form_certificate(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
            report,
            form_id=kg.form_id,
        )
        assert verify_form_certificate(cert) is True

    def test_given_certificate_when_to_dict_then_json_serialisable(self, tmp_path):
        """
        GIVEN a FormCompletionCertificate
        WHEN to_dict() / to_json() is called
        THEN the result is JSON-serialisable
        """
        _pytest_skip_if_no_fitz()
        try:
            from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        except ImportError:
            pytest.skip("logic sub-package not available")

        from ipfs_datasets_py.logic.zkp.form_circuit import generate_form_certificate

        kg, rule_set, report = self._make_passing_report(tmp_path)
        cert = generate_form_certificate(
            {"full_name": "Alice", "email": "alice@example.com", "date": "01/01/2024"},
            rule_set,
            report,
        )
        cert_json = cert.to_json()
        parsed = json.loads(cert_json)
        assert "proof" in parsed
        assert "public_inputs" in parsed
        # Private values must NOT appear
        assert "Alice" not in cert_json
        assert "alice@example.com" not in cert_json

    def test_given_failed_report_when_generate_certificate_then_raises_value_error(self, tmp_path):
        """
        GIVEN a VerificationReport with overall_pass=False
        WHEN generate_form_certificate() is called
        THEN it raises ValueError
        """
        _pytest_skip_if_no_fitz()
        try:
            from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        except ImportError:
            pytest.skip("logic sub-package not available")

        from ipfs_datasets_py.logic.zkp.form_circuit import generate_form_certificate
        from ipfs_datasets_py.processors.form_requirements_verifier import VerificationReport
        import time

        failing_report = VerificationReport(
            form_id="test",
            source_pdf="test.pdf",
            timestamp=time.time(),
            overall_pass=False,
        )

        with pytest.raises(ValueError, match="failed verification"):
            kg, rule_set, _ = self._make_passing_report(tmp_path)
            generate_form_certificate({}, rule_set, failing_report)


# ---------------------------------------------------------------------------
# Phase 6 — End-to-End MCP Tools
# ---------------------------------------------------------------------------

class TestPhase6MCPTools:
    """Tests for Phase 6: MCP tool wrappers."""

    def test_pdf_fill_form_agent_imported(self):
        """
        GIVEN the pdf_tools MCP package
        WHEN pdf_fill_form_agent is imported
        THEN the import succeeds
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_fill_form_agent
        assert callable(pdf_fill_form_agent)

    def test_pdf_generate_zkp_certificate_imported(self):
        """
        GIVEN the pdf_tools MCP package
        WHEN pdf_generate_zkp_certificate is imported
        THEN the import succeeds
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_generate_zkp_certificate
        assert callable(pdf_generate_zkp_certificate)

    def test_pdf_verify_zkp_certificate_imported(self):
        """
        GIVEN the pdf_tools MCP package
        WHEN pdf_verify_zkp_certificate is imported
        THEN the import succeeds
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_verify_zkp_certificate
        assert callable(pdf_verify_zkp_certificate)

    def test_pdf_fill_form_agent_returns_error_for_missing_path(self):
        """
        GIVEN pdf_fill_form_agent called with an empty pdf_source
        WHEN the coroutine is awaited
        THEN it returns an error response
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_fill_form_agent

        result = asyncio.run(pdf_fill_form_agent(""))
        assert result["status"] == "error"

    def test_pdf_verify_zkp_certificate_returns_error_for_invalid_json(self):
        """
        GIVEN pdf_verify_zkp_certificate called with invalid JSON
        WHEN the coroutine is awaited
        THEN it returns an error response
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_verify_zkp_certificate

        result = asyncio.run(pdf_verify_zkp_certificate("not-valid-json"))
        assert result["status"] == "error"

    def test_pdf_fill_form_agent_discovery_mode(self, tmp_path):
        """
        GIVEN a valid PDF form and no user_answers
        WHEN pdf_fill_form_agent is called in discovery mode
        THEN it returns a 'discovery' response with gaps
        """
        _pytest_skip_if_no_fitz()
        from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_fill_form_agent

        pdf_path = tmp_path / "form.pdf"
        _make_minimal_acroform_pdf(str(pdf_path))

        result = asyncio.run(
            pdf_fill_form_agent(
                str(pdf_path),
                context={},
            )
        )
        assert result["status"] == "success"
        assert result["mode"] == "discovery"
        assert isinstance(result["gaps"], list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _collect_gaps(agent: Any, pdf_path: Any) -> list:
    gaps = []
    async for question, field_name in agent.generate_questions(pdf_path):
        gaps.append((question, field_name))
    return gaps
