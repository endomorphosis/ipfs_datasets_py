"""MCP tool: AI-agent-driven PDF form filler.

Wraps :class:`~ipfs_datasets_py.processors.form_filling_agent.FormFillingAgent`
as an MCP-compatible async function.  The tool analyses a blank form PDF,
pre-fills fields from a provided ``context`` dict, validates every answer, and
writes the completed PDF.  Any fields the agent cannot fill from context alone
are returned in a ``gaps`` list so the caller can ask the user.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


async def pdf_fill_form_agent(
    pdf_source: Union[str, dict],
    output_path: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    user_answers: Optional[Dict[str, str]] = None,
    jurisdiction: Optional[str] = None,
    enable_ocr: bool = False,
    strict: bool = False,
) -> Dict[str, Any]:
    """Use an AI agent to fill a PDF form autonomously.

    The tool operates in two modes depending on whether ``user_answers`` is
    provided:

    **Discovery mode** (no ``user_answers``):
        Analyses the form, pre-fills as many fields as possible from
        ``context``, and returns a ``gaps`` list describing the fields the
        agent could not fill.

    **Fill mode** (``user_answers`` supplied):
        Merges ``user_answers`` into ``context``, validates every answer,
        writes the filled PDF to ``output_path``, and returns the result.

    Args:
        pdf_source: Path to the blank form PDF (string) or a dict with a
            ``"path"`` key.
        output_path: Where to write the filled PDF.  If omitted, a path is
            derived by appending ``_filled`` to the source filename.
        context: Flat dict of known values keyed by field name or semantic
            type (e.g. ``{"name": "Alice", "email": "alice@example.com"}``).
        user_answers: Answers to previously returned gaps
            (``{field_name: answer}``).
        jurisdiction: Optional jurisdiction string for deontic IR generation.
        enable_ocr: Perform OCR on scanned pages before field detection.
        strict: Raise an error if any required field is missing a valid value.

    Returns:
        Dict containing:

        * ``status``: ``"success"`` or ``"error"``
        * ``mode``: ``"discovery"`` or ``"fill"``
        * ``gaps``: list of ``{field_name, question, required}`` dicts
          (discovery mode only)
        * ``output_path``: path to the filled PDF (fill mode only)
        * ``summary``: agent fill-state summary
        * ``message``: human-readable message
    """
    try:
        # Resolve the PDF path
        if isinstance(pdf_source, dict):
            pdf_path = str(pdf_source.get("path", pdf_source.get("pdf_source", "")))
        else:
            pdf_path = str(pdf_source)

        if not pdf_path:
            return {"status": "error", "message": "pdf_source must be a file path or dict with 'path' key"}

        from ipfs_datasets_py.processors.form_filling_agent import FormFillingAgent

        ocr_provider = None
        if enable_ocr:
            try:
                from ipfs_datasets_py.processors.pdf_form_filler import build_tesseract_ocr_provider
                ocr_provider = build_tesseract_ocr_provider()
            except Exception:
                logger.warning("OCR provider unavailable; proceeding without OCR")

        # Merge context and user_answers
        merged_context: Dict[str, Any] = dict(context or {})
        if user_answers:
            merged_context.update(user_answers)

        agent = FormFillingAgent(
            context=merged_context,
            jurisdiction=jurisdiction,
            ocr_provider=ocr_provider,
        )
        agent.analyse(pdf_path)

        mode = "fill" if user_answers else "discovery"

        if mode == "discovery":
            # Collect gaps asynchronously
            gaps: List[Dict[str, Any]] = []
            async for question, field_name in agent.generate_questions(pdf_path):
                spec = agent._field_map.get(field_name)
                gaps.append(
                    {
                        "field_name": field_name,
                        "question": question,
                        "required": bool(spec.required if spec else False),
                        "data_type": spec.data_type if spec else "string",
                    }
                )
            return {
                "status": "success",
                "mode": "discovery",
                "gaps": gaps,
                "summary": agent.summary(),
                "message": (
                    f"Discovered {len(agent._field_map)} fields; "
                    f"{len(gaps)} require user input."
                ),
            }
        else:
            # Fill mode
            if output_path is None:
                src = Path(pdf_path)
                output_path = str(src.with_stem(src.stem + "_filled"))

            # Re-run discovery so answers get validated
            async for question, field_name in agent.generate_questions(pdf_path):
                pass  # all fields already answered via context

            try:
                filled_path = await agent.fill(pdf_path, output_path, strict=strict)
                return {
                    "status": "success",
                    "mode": "fill",
                    "output_path": str(filled_path),
                    "summary": agent.summary(),
                    "message": f"Form filled and written to {filled_path}",
                }
            except ValueError as exc:
                return {
                    "status": "error",
                    "mode": "fill",
                    "message": str(exc),
                    "summary": agent.summary(),
                }

    except Exception as exc:  # pragma: no cover
        logger.exception("pdf_fill_form_agent failed: %s", exc)
        return {"status": "error", "message": f"pdf_fill_form_agent error: {exc}"}


__all__ = ["pdf_fill_form_agent"]
