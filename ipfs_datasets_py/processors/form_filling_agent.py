"""AI-agent form filler.

:class:`FormFillingAgent` drives an autonomous multi-turn loop that:

1. Calls :func:`~ipfs_datasets_py.processors.pdf_form_filler.analyze_pdf_form`
   to discover form fields.
2. Builds a :class:`~ipfs_datasets_py.processors.pdf_form_ir.FormKnowledgeGraph`
   and converts it to a ``DeonticRuleSet`` via
   :class:`~ipfs_datasets_py.processors.pdf_form_ir.FormToLegalIR`.
3. Looks up values from a structured context dict, an optional IPFS-backed
   knowledge graph, and cross-document history.
4. Generates targeted natural-language questions for any gaps it cannot fill
   autonomously.
5. Validates each answer with type checks and constraint checks routed through
   the deontic logic layer.
6. Writes the completed form via
   :func:`~ipfs_datasets_py.processors.pdf_form_filler.fill_pdf_fields`.

Usage (async)
-------------
::

    from ipfs_datasets_py.processors.form_filling_agent import FormFillingAgent

    agent = FormFillingAgent(context={"name": "Alice", "email": "alice@example.com"})

    async for question, field_name in agent.generate_questions("blank_form.pdf"):
        answer = input(question + " ")  # replace with your UI
        agent.provide_answer(field_name, answer)

    output_path = await agent.fill("blank_form.pdf", "filled_form.pdf")

Or use :meth:`run` for a fully synchronous drive with a callback::

    agent.run("blank_form.pdf", "filled_form.pdf",
              answer_callback=lambda q, name: input(q + " "))
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

import re as _re

_DATE_PATTERNS = [
    _re.compile(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$"),
    _re.compile(r"^\d{4}[/\-]\d{2}[/\-]\d{2}$"),
]
_EMAIL_PATTERN = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_PATTERN = _re.compile(r"^[\+\d\s\-().]{7,20}$")
_SSN_PATTERN = _re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
_ZIP_PATTERN = _re.compile(r"^\d{5}(-\d{4})?$")
_STATE_ABBREVS = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}


def _validate_typed_value(value: str, data_type: str) -> Tuple[bool, str]:
    """Check *value* against *data_type* semantics.

    Returns (is_valid, error_message).
    """
    if not value:
        return True, ""  # empty is checked by required logic
    dt = data_type.lower()
    if dt == "date":
        if not any(p.match(value) for p in _DATE_PATTERNS):
            return False, f"Expected a date (MM/DD/YYYY), got: {value!r}"
    elif dt == "email":
        if not _EMAIL_PATTERN.match(value):
            return False, f"Expected an email address, got: {value!r}"
    elif dt == "phone":
        if not _PHONE_PATTERN.match(value):
            return False, f"Expected a phone number, got: {value!r}"
    elif dt == "ssn":
        if not _SSN_PATTERN.match(value):
            return False, f"Expected a Social Security Number (XXX-XX-XXXX), got: {value!r}"
    elif dt == "postal_code":
        if not _ZIP_PATTERN.match(value):
            return False, f"Expected a ZIP code (XXXXX or XXXXX-XXXX), got: {value!r}"
    elif dt == "state":
        if value.upper() not in _STATE_ABBREVS and len(value) > 20:
            return False, f"Expected a US state abbreviation or name, got: {value!r}"
    elif dt == "currency":
        cleaned = _re.sub(r"[$,\s]", "", value)
        try:
            float(cleaned)
        except ValueError:
            return False, f"Expected a numeric amount, got: {value!r}"
    elif dt == "boolean":
        if value.lower() not in {"yes", "no", "true", "false", "1", "0", "x", "✓", ""}:
            return False, f"Expected yes/no, got: {value!r}"
    return True, ""


# ---------------------------------------------------------------------------
# Field-filling answer store
# ---------------------------------------------------------------------------

@dataclass
class FilledField:
    """A field that has been answered, with validation metadata."""

    name: str
    label: str
    data_type: str
    value: str
    source: str  # "context" | "knowledge_graph" | "cross_doc" | "user"
    validated: bool = False
    validation_error: str = ""


# ---------------------------------------------------------------------------
# FormFillingAgent
# ---------------------------------------------------------------------------

class FormFillingAgent:
    """Autonomous agent that fills PDF forms.

    Parameters
    ----------
    context:
        Flat dict of known values keyed by field name or semantic type
        (e.g. ``{"name": "Alice", "email": "alice@example.com"}``).
    jurisdiction:
        Optional jurisdiction string forwarded to the legal IR converter.
    ocr_provider:
        Optional OCR callback passed through to ``analyze_pdf_form``.
    layout_provider:
        Optional layout callback passed through to ``analyze_pdf_form``.
    vlm_field_provider:
        Optional VLM callback passed through to ``analyze_pdf_form``.
    """

    def __init__(
        self,
        *,
        context: Optional[Mapping[str, Any]] = None,
        jurisdiction: Optional[str] = None,
        ocr_provider: Any = None,
        layout_provider: Any = None,
        vlm_field_provider: Any = None,
    ) -> None:
        self.context: Dict[str, Any] = dict(context or {})
        self.jurisdiction = jurisdiction
        self.ocr_provider = ocr_provider
        self.layout_provider = layout_provider
        self.vlm_field_provider = vlm_field_provider

        self._answers: Dict[str, FilledField] = {}
        self._analysis: Any = None  # FormAnalysisResult
        self._kg: Any = None        # FormKnowledgeGraph
        self._rule_set: Any = None  # DeonticRuleSet
        self._field_map: Dict[str, Any] = {}  # name → FormFieldSpec

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------

    def analyse(self, pdf_path: str | Path) -> None:
        """Parse the PDF and build the knowledge graph synchronously."""
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form
        from ipfs_datasets_py.processors.pdf_form_ir import FormToLegalIR, build_form_knowledge_graph

        kwargs: dict[str, Any] = {}
        if self.ocr_provider is not None:
            kwargs["ocr_provider"] = self.ocr_provider
        if self.layout_provider is not None:
            kwargs["layout_provider"] = self.layout_provider
        if self.vlm_field_provider is not None:
            kwargs["vlm_field_provider"] = self.vlm_field_provider

        self._analysis = analyze_pdf_form(pdf_path, **kwargs)
        self._field_map = {spec.name: spec for spec in self._analysis.fields}

        try:
            converter = FormToLegalIR(jurisdiction=self.jurisdiction)
            self._kg = build_form_knowledge_graph(self._analysis, jurisdiction=self.jurisdiction)
            self._rule_set = converter.to_rule_set(self._kg)
        except ImportError:
            logger.warning("logic sub-package not available; skipping deontic IR generation")
            self._kg = None
            self._rule_set = None

    # ------------------------------------------------------------------
    # Knowledge lookup
    # ------------------------------------------------------------------

    def _lookup_from_context(self, spec: Any) -> Optional[str]:
        """Try to satisfy a field from the provided context dict."""
        # Exact name match
        if spec.name in self.context:
            return str(self.context[spec.name])
        # Semantic type match (e.g. context["email"] satisfies data_type="email")
        if spec.data_type in self.context:
            return str(self.context[spec.data_type])
        # Label-based fuzzy key
        from ipfs_datasets_py.processors.pdf_form_filler import slugify_field_name
        slug = slugify_field_name(spec.label)
        if slug in self.context:
            return str(self.context[slug])
        return None

    def _lookup_from_knowledge_graph(self, spec: Any) -> Optional[str]:
        """Stub: look up the field value from an IPFS-backed knowledge graph.

        In a full deployment this would call the ``pdf_query_knowledge_graph``
        MCP tool.  For now returns ``None`` so the agent falls back to asking
        the user.
        """
        return None

    def _lookup_from_cross_doc(self, spec: Any) -> Optional[str]:
        """Stub: look up the field value from cross-document history."""
        return None

    def _lookup_value(self, spec: Any) -> Tuple[Optional[str], str]:
        """Return (value, source) for *spec*, checking all knowledge sources."""
        value = self._lookup_from_context(spec)
        if value is not None:
            return value, "context"
        value = self._lookup_from_knowledge_graph(spec)
        if value is not None:
            return value, "knowledge_graph"
        value = self._lookup_from_cross_doc(spec)
        if value is not None:
            return value, "cross_doc"
        return None, "user"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_answer(self, spec: Any, value: str) -> Tuple[bool, str]:
        """Validate *value* for *spec* using type checks and deontic constraints."""
        # Type / format check
        valid, error = _validate_typed_value(value, spec.data_type)
        if not valid:
            return False, error

        # Deontic constraint check (best-effort; skipped if logic unavailable)
        if self._rule_set is not None:
            try:
                valid, error = self._check_deontic_constraint(spec, value)
                if not valid:
                    return False, error
            except Exception as exc:
                logger.debug("Deontic constraint check failed (non-fatal): %s", exc)

        return True, ""

    def _check_deontic_constraint(self, spec: Any, value: str) -> Tuple[bool, str]:
        """Run a lightweight deontic consistency check for the given field value."""
        # Placeholder: a fuller implementation would invoke DeonticQueryEngine
        # to check conditional requirements and cross-field consistency.
        # For now: enforce required-field obligation.
        if spec.required and not value:
            return False, f"Field '{spec.label}' is required but has no value."
        return True, ""

    # ------------------------------------------------------------------
    # Question generation
    # ------------------------------------------------------------------

    def _generate_question(self, spec: Any) -> str:
        """Generate a natural-language question for a field the agent cannot fill."""
        hint = ""
        if spec.data_type == "date":
            hint = " (MM/DD/YYYY)"
        elif spec.data_type == "currency":
            hint = " (numeric, e.g. 1234.56)"
        elif spec.data_type == "boolean":
            hint = " (yes/no)"
        elif spec.data_type == "ssn":
            hint = " (XXX-XX-XXXX)"
        required_marker = " *" if spec.required else ""
        return f"Please enter {spec.label}{hint}{required_marker}:"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def provide_answer(self, field_name: str, value: str) -> Tuple[bool, str]:
        """Record an answer for *field_name* and validate it.

        Returns (is_valid, error_message).
        """
        spec = self._field_map.get(field_name)
        if spec is None:
            return False, f"Unknown field: {field_name!r}"
        valid, error = self._validate_answer(spec, value)
        self._answers[field_name] = FilledField(
            name=field_name,
            label=spec.label,
            data_type=spec.data_type,
            value=value,
            source="user",
            validated=valid,
            validation_error=error,
        )
        return valid, error

    async def generate_questions(
        self,
        pdf_path: str | Path,
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """Analyse *pdf_path* and yield ``(question, field_name)`` pairs for
        every field the agent cannot fill autonomously.

        Yields
        ------
        tuple[str, str]
            ``(question_text, field_name)``
        """
        if self._analysis is None:
            self.analyse(pdf_path)
        assert self._analysis is not None

        for spec in self._analysis.fields:
            # Skip if already answered
            if spec.name in self._answers:
                continue
            value, source = self._lookup_value(spec)
            if value is not None:
                valid, error = self._validate_answer(spec, value)
                self._answers[spec.name] = FilledField(
                    name=spec.name,
                    label=spec.label,
                    data_type=spec.data_type,
                    value=value,
                    source=source,
                    validated=valid,
                    validation_error=error,
                )
                if not valid:
                    # Auto-filled value failed validation — ask the user
                    yield self._generate_question(spec), spec.name
            else:
                yield self._generate_question(spec), spec.name

    async def fill(
        self,
        input_pdf: str | Path,
        output_pdf: str | Path,
        *,
        strict: bool = True,
    ) -> Path:
        """Fill *input_pdf* with all collected answers and write *output_pdf*.

        Raises
        ------
        ValueError
            If ``strict=True`` and any required field lacks a valid value.
        """
        from ipfs_datasets_py.processors.pdf_form_filler import fill_pdf_fields

        if self._analysis is None:
            self.analyse(input_pdf)

        if strict:
            missing = [
                spec.name
                for spec in (self._analysis.fields or [])
                if spec.required
                and (
                    spec.name not in self._answers
                    or not self._answers[spec.name].validated
                )
            ]
            if missing:
                raise ValueError(f"Required fields not filled or invalid: {missing}")

        values: Dict[str, Any] = {
            name: ff.value for name, ff in self._answers.items()
        }
        return fill_pdf_fields(input_pdf, output_pdf, values, strict=False)

    def run(
        self,
        input_pdf: str | Path,
        output_pdf: str | Path,
        *,
        answer_callback: Callable[[str, str], str],
        strict: bool = True,
    ) -> Path:
        """Synchronous facade: analyse the form, ask questions via *answer_callback*,
        validate answers, and write the filled PDF.

        Parameters
        ----------
        answer_callback:
            Called with ``(question, field_name)``; must return the user's
            answer string.
        """
        self.analyse(input_pdf)

        async def _async_run() -> Path:
            async for question, field_name in self.generate_questions(input_pdf):
                while True:
                    answer = answer_callback(question, field_name)
                    valid, error = self.provide_answer(field_name, answer)
                    if valid:
                        break
                    question = f"{error} — {self._generate_question(self._field_map[field_name])}"
            return await self.fill(input_pdf, output_pdf, strict=strict)

        return asyncio.run(_async_run())

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the current fill state."""
        total = len(self._field_map)
        answered = sum(1 for ff in self._answers.values() if ff.validated)
        unanswered = [
            spec.name
            for spec in (getattr(self._analysis, "fields", None) or [])
            if spec.name not in self._answers
        ]
        return {
            "total_fields": total,
            "answered_valid": answered,
            "unanswered": unanswered,
            "answers": {name: ff.value for name, ff in self._answers.items()},
        }


__all__ = [
    "FilledField",
    "FormFillingAgent",
]
