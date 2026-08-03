"""PATLAW-008: Phase 0 processor foundation end-to-end proof.

Acceptance
----------
- One canonical processor path runs
- Page/span provenance survives extraction
- Legal/form result is unknown/review rather than pass
- No confidential fixture content reaches a forbidden sink

Effects
-------
Route a synthetic confidential scanned office action through USPTO
classification and real PDF extraction into a deliberately incomplete legal
check, asserting privacy isolation the whole way.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.processors.adapters.legacy_protocol_adapter import (
    LegacyProtocolAdapter,
)
from ipfs_datasets_py.processors.adapters.pdf_adapter import PDFProcessorAdapter
from ipfs_datasets_py.processors.core.protocol import InputType, ProcessingContext
from ipfs_datasets_py.processors.core.registry import ProcessorRegistry
from ipfs_datasets_py.processors.core.universal_processor import UniversalProcessor
from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    build_artifact_manifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    SinkDecisionCode,
    UsptoPrivacyPolicy,
    deny_private_to_public_sinks,
)
from ipfs_datasets_py.processors.form_requirements_verifier import (
    STATUS_REVIEW_REQUIRED,
    STATUS_UNKNOWN,
    FormRequirementsVerifier,
)
from tests.fixtures.uspto.pdf.generators import (
    CONFIDENTIAL_CANARY,
    build_confidential_scanned_pdf,
)


# ---------------------------------------------------------------------------
# Pipeline helpers (mirrors PATLAW-007 adapter tests; no network / ML)
# ---------------------------------------------------------------------------


def _mock_ocr_engine(
    text_by_default: str = CONFIDENTIAL_CANARY,
    confidence: float = 0.9,
    available: Optional[List[str]] = None,
):
    engine = MagicMock()
    engines = list(available) if available is not None else ["mock"]
    engine.get_available_engines.return_value = engines

    def extract(image_data, strategy="quality_first", confidence_threshold=0.7):
        if not engines:
            return {
                "text": "",
                "confidence": None,
                "engine": "none",
                "status": "ocr_unavailable",
                "error": "No OCR engines available",
                "available_engines": [],
                "engines_attempted": [],
                "word_boxes": [],
            }
        status = "ok" if confidence >= confidence_threshold else "low_confidence"
        return {
            "text": text_by_default,
            "confidence": confidence,
            "engine": "mock",
            "status": status,
            "available_engines": engines,
            "engines_attempted": ["mock"],
            "word_boxes": [
                {
                    "text": text_by_default,
                    "bbox": [10, 10, 400, 40],
                    "confidence": confidence,
                }
            ],
        }

    engine.extract_with_ocr.side_effect = extract
    engine.extract_with_ocr_async = None
    return engine


class _MockKnowledgeGraph:
    def __init__(self, document_id: str = "doc-foundation-e2e"):
        self.document_id = document_id
        self.entities: list = []
        self.relationships: list = []
        self.metadata: dict = {}
        self.chunks: list = []


def _make_llm_document(summary: str = ""):
    from ipfs_datasets_py.processors.llm_optimizer import LLMDocument

    return LLMDocument(
        document_id="doc-foundation-e2e",
        title="Confidential Scanned Office Action (synthetic)",
        chunks=[],
        summary=summary or "",
        key_entities=[],
        processing_metadata={"source": "uspto_processor_foundation"},
        document_embedding=None,
    )


def _real_pipeline_processor(*, ocr_engine=None):
    """Construct specialized PDFProcessor with safe mocks (no network ML)."""
    from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import (
        PDFProcessor,
    )

    storage = MagicMock()
    _cid_counter = {"n": 0}

    def _store_json(_obj):
        _cid_counter["n"] += 1
        return f"bafy-foundation-cid-{_cid_counter['n']}"

    storage.store_json.side_effect = _store_json
    storage.store.side_effect = (
        lambda *_a, **_k: f"bafy-foundation-bytes-{_cid_counter['n']}"
    )

    async def _integrate_document(llm_document, **kwargs):
        doc_id = getattr(llm_document, "document_id", None) or "doc-foundation-e2e"
        return _MockKnowledgeGraph(document_id=doc_id)

    integrator = MagicMock()
    integrator.integrate_document = _integrate_document

    async def _optimize_for_llm(decomposed_content, metadata=None):
        return _make_llm_document()

    optimizer = MagicMock()
    optimizer.optimize_for_llm = _optimize_for_llm
    optimizer.embedding_model = "mock-embedding-model"

    processor = PDFProcessor(
        enable_monitoring=False,
        enable_audit=False,
        mock_dict={
            "storage": storage,
            "ocr_engine": ocr_engine or _mock_ocr_engine(),
            "integrator": integrator,
            "optimizer": optimizer,
            "audit_logger": None,
            "monitoring": None,
        },
    )

    async def _noop_query_interface(*_a, **_k):
        return None

    processor._setup_query_interface = _noop_query_interface  # type: ignore[method-assign]
    return processor


def _pdf_context(source: str | Path, **opts: Any) -> ProcessingContext:
    return ProcessingContext(
        input_type=InputType.FILE,
        source=str(source),
        metadata={"format": "pdf", "mime_type": "application/pdf"},
        options=dict(opts),
    )


def _content_from_core_result(result) -> Dict[str, Any]:
    """Legacy adapter places PDF content under raw_output['content']."""
    raw = result.raw_output or {}
    content = raw.get("content") if isinstance(raw, dict) else None
    if isinstance(content, dict):
        return content
    return {}


def _capture_root_and_pdf_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    names = (
        "ipfs_datasets_py.processors.adapters.pdf_adapter",
        "ipfs_datasets_py.processors.adapters.legacy_protocol_adapter",
        "ipfs_datasets_py.processors.core.universal_processor",
        "ipfs_datasets_py.processors.specialized.pdf.pdf_processor",
        "ipfs_datasets_py.processors.form_requirements_verifier",
        "ipfs_datasets_py.processors.domains.uspto.privacy",
    )
    for name in names:
        logging.getLogger(name).setLevel(logging.DEBUG)
        logging.getLogger(name).addHandler(handler)
    return stream, handler, previous_level, names


def _release_logs(stream, handler, previous_level, names):
    root = logging.getLogger()
    root.removeHandler(handler)
    root.setLevel(previous_level)
    for name in names:
        logging.getLogger(name).removeHandler(handler)
    return stream.getvalue()


def _incomplete_formula(
    *,
    formula_id: str = "oa-response-obligation",
    field: str = "response_to_rejection",
    proposition: str = "file_timely_response(response_to_rejection)",
) -> SimpleNamespace:
    """Office-action response obligation that extraction alone cannot satisfy."""
    try:
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticOperator,
        )

        op = DeonticOperator.OBLIGATION
    except Exception:
        op = SimpleNamespace(name="OBLIGATION")

    return SimpleNamespace(
        formula_id=formula_id,
        operator=op,
        proposition=proposition,
        agent="applicant",
        conditions=[],
        legal_context="office_action",
        confidence=1.0,
        source_text=proposition,
        variables={"field": field},
    )


def _rule_set(formulas: Optional[List[Any]] = None) -> SimpleNamespace:
    formulas = list(formulas or [])

    def check_consistency():
        return []

    return SimpleNamespace(
        formulas=formulas,
        rule_set_id="foundation-incomplete-oa",
        check_consistency=check_consistency,
    )


class _SinkProbe:
    """In-memory public-sink bus used only to prove denial (never accepts private)."""

    def __init__(self, policy: UsptoPrivacyPolicy) -> None:
        self.policy = policy
        self.accepted: list[dict[str, Any]] = []
        self.denied: list[dict[str, Any]] = []
        self.surfaces: list[str] = []

    def attempt(
        self,
        *,
        classification: DisclosureClassification,
        sink: PublicSink,
        content_kind: ContentKind,
        payload: Any,
    ) -> bool:
        decision = self.policy.evaluate_sink(classification, sink, content_kind)
        record = {
            "allowed": decision.allowed,
            "code": decision.code.value,
            "sink": sink.value,
            "content_kind": content_kind.value,
        }
        if not decision.allowed:
            self.denied.append(record)
            # Audit line: reason codes only — never the private payload.
            self.surfaces.append(
                json.dumps(
                    {
                        "event": "sink_denied",
                        "code": decision.code.value,
                        "sink": sink.value,
                        "content_kind": content_kind.value,
                        "classification": decision.classification.value,
                    },
                    sort_keys=True,
                )
            )
            return False
        self.accepted.append(record)
        self.surfaces.append(str(payload))
        return True


# ---------------------------------------------------------------------------
# Main Phase 0 foundation path
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUsptoProcessorFoundationEndToEnd:
    """Single cohesive path: classify → canonical route → extract → fail-closed."""

    @pytest.mark.asyncio
    async def test_confidential_scanned_office_action_foundation_path(
        self, tmp_path: Path
    ):
        # --- 1. Synthetic confidential scanned office action ---
        pdf_path = build_confidential_scanned_pdf(
            tmp_path / "confidential_office_action.pdf",
            canary=CONFIDENTIAL_CANARY,
        )
        pdf_bytes = pdf_path.read_bytes()
        digest = hashlib.sha256(pdf_bytes).hexdigest()

        policy = UsptoPrivacyPolicy()
        classification = policy.classify_before_dispatch(
            DisclosureClassification.CONFIDENTIAL_APPLICATION,
            source_classifications=(
                DisclosureClassification.CONFIDENTIAL_APPLICATION,
            ),
        )
        assert classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
        assert policy.must_quarantine(classification) is False

        manifest = build_artifact_manifest(
            artifact_id="artifact:foundation:oa:1",
            sha256=digest,
            size_bytes=len(pdf_bytes),
            classification=classification,
            media_type="application/pdf",
            private_cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            matter_id="matter:foundation:synth:1",
            encryption_namespace="private://tenant/foundation/uspto",
            labels={
                "fixture": "confidential_scanned_office_action",
                "synthetic": "true",
            },
            policy=policy,
        )
        assert (
            manifest.classification
            is DisclosureClassification.CONFIDENTIAL_APPLICATION
        )
        # Private CID must never be announceable to public sinks.
        cid_denials = manifest.private_cid_public_sink_denials(policy=policy)
        assert cid_denials
        assert all(not d["allowed"] for d in cid_denials)

        # --- 2. One canonical processor path (UniversalProcessor + adapters) ---
        pipeline = _real_pipeline_processor(
            ocr_engine=_mock_ocr_engine(text_by_default=CONFIDENTIAL_CANARY)
        )
        pdf_adapter = PDFProcessorAdapter(processor=pipeline)
        legacy_wrapper = LegacyProtocolAdapter(
            pdf_adapter, name="canonical-pdf-foundation"
        )
        registry = ProcessorRegistry()
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(
            legacy_wrapper,
            priority=100,
            name="canonical-pdf-foundation",
        )
        # Bare legacy must not register; only one adapted path is registered.
        assert len(registry) == 1

        stream, handler, prev_level, log_names = _capture_root_and_pdf_logs()
        try:
            result = await up.process(
                str(pdf_path),
                context=_pdf_context(
                    pdf_path,
                    classification=classification.value,
                    artifact_id=manifest.artifact_id,
                    matter_id=manifest.matter_id,
                ),
            )
        finally:
            log_output = _release_logs(stream, handler, prev_level, log_names)

        # Canonical routing annotations
        assert result.success is True, (
            f"canonical path must complete (success/partial); "
            f"errors={result.errors!r} metadata={result.metadata!r}"
        )
        assert result.metadata.get("routing") == "canonical_core"
        assert result.metadata.get("adapter") == "LegacyProtocolAdapter"
        assert result.metadata.get("adapter_name") == "canonical-pdf-foundation"
        assert result.metadata.get("adapted_from") == "legacy_protocol"
        assert result.metadata.get("routed_processor") in (
            "canonical-pdf-foundation",
            "PDFProcessor",
            legacy_wrapper.get_name(),
        )
        assert result.metadata.get("legacy_status") in ("success", "partial")

        # --- 3. Page/span provenance survives ---
        content = _content_from_core_result(result)
        full_text = content.get("text") or ""
        pages = content.get("pages") or []
        page_coverage = content.get("page_coverage") or []
        provenance = content.get("provenance") or {}

        assert pages, "per-page extraction with provenance required"
        assert page_coverage, "page_coverage receipts required"
        assert provenance, "document-level provenance required"

        page0 = pages[0]
        assert page0.get("page") is not None
        spans = page0.get("spans") or []
        coverage = page0.get("coverage") or {}
        assert spans or coverage, "page span or coverage provenance required"
        if spans:
            assert any(
                isinstance(s, dict) and s.get("origin") for s in spans
            ), "spans must carry origin provenance"
        if coverage:
            assert (
                coverage.get("page") is not None
                or "has_native_text" in coverage
                or "has_ocr_text" in coverage
                or "coverage" in coverage
            )

        # OCR canary proves real extraction (not placeholder)
        joined = full_text + "\n" + "\n".join(
            (p.get("text") or "") for p in pages if isinstance(p, dict)
        )
        assert CONFIDENTIAL_CANARY in joined, (
            "expected confidential fixture canary in extracted text/pages"
        )
        assert not full_text.startswith("PDF content from ")
        assert f"PDF content from {pdf_path}" not in full_text

        # --- 4. Deliberately incomplete legal check → unknown/review, not pass ---
        # Extraction alone is not a complete response package. Field values are
        # present enough to reach the prover (avoid lightweight empty→violated
        # short-circuit) but the check is still incomplete: the prover returns
        # UNSUPPORTED / timeout-class outcomes that fail closed to review.
        incomplete_values: Dict[str, Any] = {
            "application_number": "16/000,001",
            "extracted_fragment": (full_text[:80] if full_text else "fragment"),
            # Placeholder presence only — not a verified filing response.
            "response_to_rejection": "INCOMPLETE: extraction-only draft",
            "amended_claim_set": "INCOMPLETE: claims not reconstructed",
        }
        formulas = [
            _incomplete_formula(
                formula_id="oa-response",
                field="response_to_rejection",
                proposition="file_timely_response(response_to_rejection)",
            ),
            _incomplete_formula(
                formula_id="oa-claim-amendment",
                field="amended_claim_set",
                proposition="submit_amended_claims(amended_claim_set)",
            ),
        ]

        def _proof_status(name: str):
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import (
                ProofStatus,
            )

            return getattr(ProofStatus, name)

        engine = MagicMock()
        # First formula: unsupported semantics (unknown); second: prover error
        # (review_required). Both block overall_pass under fail-closed rules.
        engine.prove_deontic_formula.side_effect = [
            SimpleNamespace(
                status=_proof_status("UNSUPPORTED"),
                prover="z3",
                proof_output="",
                errors=["incomplete evidence for office-action response"],
            ),
            SimpleNamespace(
                status=_proof_status("ERROR"),
                prover="z3",
                proof_output="",
                errors=["claim reconstruction unavailable for incomplete package"],
            ),
        ]
        verifier = FormRequirementsVerifier(prover="z3", timeout=5)
        verifier._engine = engine

        report = verifier.verify(
            incomplete_values,
            _rule_set(formulas),
            form_id="office-action-response-incomplete",
        )

        assert report.overall_pass is False
        assert report.review_required is True
        statuses = {r.status for r in report.results}
        assert statuses & {STATUS_UNKNOWN, STATUS_REVIEW_REQUIRED}, (
            f"expected unknown/review outcomes, got {statuses!r}"
        )
        assert STATUS_UNKNOWN in statuses
        assert STATUS_REVIEW_REQUIRED in statuses
        assert len(report.results) == len(formulas)

        # Empty rule set from incomplete extraction must never vacuous-pass.
        with patch.object(
            FormRequirementsVerifier,
            "_get_engine",
            side_effect=ImportError("no engine for empty path"),
        ):
            empty_report = FormRequirementsVerifier().verify(
                {},
                _rule_set([]),
                form_id="empty-incomplete",
            )
        assert empty_report.overall_pass is False
        assert empty_report.review_required is True

        # --- 5. Confidential fixture content never reaches a forbidden sink ---
        probe = _SinkProbe(policy)
        private_payloads = {
            ContentKind.DOCUMENT_BYTES: pdf_bytes,
            ContentKind.EXTRACTED_TEXT: CONFIDENTIAL_CANARY,
            ContentKind.EMBEDDING: [0.11, 0.22, 0.33],
            ContentKind.CONTENT_IDENTIFIER: manifest.private_cid,
        }
        for sink in PublicSink:
            for kind, payload in private_payloads.items():
                ok = probe.attempt(
                    classification=classification,
                    sink=sink,
                    content_kind=kind,
                    payload=payload,
                )
                assert ok is False, f"must deny {kind.value} → {sink.value}"

        assert probe.accepted == []
        assert len(probe.denied) == len(PublicSink) * len(private_payloads)

        denials = deny_private_to_public_sinks(classification, policy=policy)
        assert denials
        assert all(not d.allowed for d in denials)
        assert all(
            d.code
            in (
                SinkDecisionCode.DENIED_PRIVATE,
                SinkDecisionCode.DENIED_QUARANTINE,
                SinkDecisionCode.DENIED_EXPORT_REVIEW,
                SinkDecisionCode.DENIED_CREDENTIAL,
                SinkDecisionCode.DENIED_CONTENT_KIND,
            )
            for d in denials
        )

        # assert_sink_allowed raises without embedding the canary in the error.
        with pytest.raises(PrivacyBoundaryError) as caught:
            policy.assert_sink_allowed(
                classification,
                PublicSink.REMOTE_PROMPT,
                ContentKind.EXTRACTED_TEXT,
            )
        err = caught.value
        audit = err.audit_dict()
        rendered = f"{err!s}\n{err!r}\n{json.dumps(audit)}"
        assert CONFIDENTIAL_CANARY not in rendered
        assert CONFIDENTIAL_CANARY not in json.dumps(audit)
        assert audit["sink"] == PublicSink.REMOTE_PROMPT.value

        # Log redaction strips private body; ordinary logs must not contain canary.
        redacted = policy.redact_for_logs(
            classification,
            {
                "artifact_id": manifest.artifact_id,
                "matter_id": manifest.matter_id,
                "classification": classification.value,
                "digest": digest,
                "text": CONFIDENTIAL_CANARY,
                "body": full_text,
                "cid": manifest.private_cid,
            },
        )
        redacted_blob = json.dumps(dict(redacted), default=str)
        assert CONFIDENTIAL_CANARY not in redacted_blob
        assert redacted.get("redacted") is True
        assert "text" not in redacted
        assert "body" not in redacted
        assert "cid" not in redacted

        surface = "\n".join([*probe.surfaces, log_output, redacted_blob, rendered])
        assert CONFIDENTIAL_CANARY not in surface, (
            "confidential fixture canary leaked into a forbidden sink/surface"
        )
        if manifest.private_cid:
            assert manifest.private_cid not in surface

    @pytest.mark.asyncio
    async def test_canonical_path_is_the_only_registered_route(
        self, tmp_path: Path
    ):
        """Empty registry fails closed; one adapted PDF path is the sole route."""
        empty_up = UniversalProcessor(
            registry=ProcessorRegistry(), max_retries=1, retry_delay=0
        )
        empty = await empty_up.process(
            "missing.pdf",
            context=_pdf_context("missing.pdf"),
        )
        assert empty.success is False
        assert empty.metadata.get("routing") == "empty_registry"

        pdf_path = build_confidential_scanned_pdf(
            tmp_path / "only_route.pdf",
            canary=CONFIDENTIAL_CANARY,
        )
        pipeline = _real_pipeline_processor()
        adapter = PDFProcessorAdapter(processor=pipeline)
        wrapped = LegacyProtocolAdapter(adapter, name="sole-pdf-route")
        registry = ProcessorRegistry()
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(wrapped, priority=50, name="sole-pdf-route")

        # Bare PDF adapter without LegacyProtocolAdapter must not register.
        with pytest.raises(Exception):
            up.register_processor(PDFProcessorAdapter(processor=pipeline), name="bare")

        result = await up.process(str(pdf_path), context=_pdf_context(pdf_path))
        assert result.success is True
        assert result.metadata.get("routing") == "canonical_core"
        assert result.metadata.get("adapter") == "LegacyProtocolAdapter"
        assert len(registry) == 1

        content = _content_from_core_result(result)
        assert content.get("pages") or content.get("page_coverage")
        assert content.get("provenance") is not None


@pytest.mark.integration
class TestFoundationPrivacyClassificationGate:
    """Classification gate precedes any public dispatch on foundation fixtures."""

    def test_unknown_classification_quarantines_before_sink_dispatch(self):
        policy = UsptoPrivacyPolicy()
        effective = policy.classify_before_dispatch(None)
        assert effective is DisclosureClassification.UNKNOWN
        assert policy.must_quarantine(effective) is True

        q = policy.quarantine(
            quarantine_id="q:foundation:unknown:1",
            classification=effective,
            reason_codes=("unknown_classification", "foundation_gate"),
            content_kinds=(
                ContentKind.DOCUMENT_BYTES,
                ContentKind.EXTRACTED_TEXT,
            ),
        )
        assert q.classification is DisclosureClassification.UNKNOWN

        for sink in PublicSink:
            decision = policy.evaluate_sink(
                effective, sink, ContentKind.EXTRACTED_TEXT
            )
            assert decision.allowed is False
            assert decision.quarantined is True
            assert decision.code is SinkDecisionCode.DENIED_QUARANTINE

    def test_confidential_extracted_text_denied_from_all_public_sinks(self):
        policy = UsptoPrivacyPolicy()
        denials = deny_private_to_public_sinks(
            DisclosureClassification.CONFIDENTIAL_APPLICATION,
            content_kinds=(ContentKind.EXTRACTED_TEXT,),
            policy=policy,
        )
        assert len(denials) == len(PublicSink)
        assert all(not d.allowed for d in denials)
        assert CONFIDENTIAL_CANARY not in json.dumps(
            [d.to_dict() for d in denials]
        )
