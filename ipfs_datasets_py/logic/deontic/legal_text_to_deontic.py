"""Core conversion: legal text -> deontic logic."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from .utils.deontic_parser import (
    build_deontic_formula,
    detect_normative_conflicts,
    extract_normative_elements,
    identify_obligations,
)

logger = logging.getLogger(__name__)


async def convert_legal_text_to_deontic(
    legal_text: Union[str, Dict[str, Any]],
    jurisdiction: str = "us",
    document_type: str = "statute",
    output_format: str = "json",
    extract_obligations: bool = True,
    include_exceptions: bool = True,
) -> Dict[str, Any]:
    """Convert legal text (statutes, regs, contracts) into deontic logic."""
    try:
        # Intentionally avoid per-call logging here to keep batch pipelines quiet.

        # Treat empty/whitespace-only input as a no-op conversion.
        # This avoids noisy ERROR logs in batch/benchmark pipelines where
        # empty rows can occur.
        if legal_text is None:
            legal_text = ""

        if jurisdiction not in ["us", "eu", "uk", "international", "general"]:
            logger.warning(f"Unknown jurisdiction '{jurisdiction}', using 'general'")
            jurisdiction = "general"

        if document_type not in ["statute", "regulation", "contract", "policy", "agreement", "general"]:
            logger.warning(f"Unknown document type '{document_type}', using 'general'")
            document_type = "general"

        if isinstance(legal_text, str):
            stripped = legal_text.strip()
            if not stripped:
                return {
                    "status": "success",
                    "deontic_formulas": [],
                    "normative_structure": {"obligations": [], "permissions": [], "prohibitions": []},
                    "legal_entities": [],
                    "actions": [],
                    "temporal_constraints": [],
                    "conflicts": [],
                    "summary": {
                        "total_normative_statements": 0,
                        "successful_conversions": 0,
                        "conversion_rate": 0.0,
                        "average_confidence": 0.0,
                        "normative_distribution": {"obligations": 0, "permissions": 0, "prohibitions": 0},
                        "conflicts_detected": 0,
                        "unique_entities": 0,
                        "unique_actions": 0,
                    },
                    "metadata": {
                        "tool": "legal_text_to_deontic",
                        "version": "1.0.0",
                        "jurisdiction": jurisdiction,
                        "document_type": document_type,
                        "output_format": output_format,
                        "processing_timestamp": datetime.now().isoformat(),
                    },
                }

            sections = [stripped]
        elif isinstance(legal_text, dict):
            sections = extract_legal_text_from_dataset(legal_text)
        else:
            raise ValueError("Legal text input must be a string or dictionary")

        if not sections or all(not s.strip() for s in sections):
            return {
                "status": "success",
                "deontic_formulas": [],
                "normative_structure": {"obligations": [], "permissions": [], "prohibitions": []},
                "legal_entities": [],
                "actions": [],
                "temporal_constraints": [],
                "conflicts": [],
                "summary": {
                    "total_normative_statements": 0,
                    "successful_conversions": 0,
                    "conversion_rate": 0.0,
                    "average_confidence": 0.0,
                    "normative_distribution": {"obligations": 0, "permissions": 0, "prohibitions": 0},
                    "conflicts_detected": 0,
                    "unique_entities": 0,
                    "unique_actions": 0,
                },
                "metadata": {
                    "tool": "legal_text_to_deontic",
                    "version": "1.0.0",
                    "jurisdiction": jurisdiction,
                    "document_type": document_type,
                    "output_format": output_format,
                    "processing_timestamp": datetime.now().isoformat(),
                },
            }

        results: List[Dict[str, Any]] = []
        all_normative_elements: List[Dict[str, Any]] = []
        total_processed = 0
        successful_conversions = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue

            try:
                normative_elements = extract_normative_elements(section, document_type)
                all_normative_elements.extend(normative_elements)

                for element in normative_elements:
                    total_processed += 1
                    try:
                        deontic_formula = build_deontic_formula(element)
                        confidence = calculate_deontic_confidence(element, deontic_formula)

                        if confidence > 0.5:
                            successful_conversions += 1

                            formula_result: Dict[str, Any] = {
                                "original_text": element["text"],
                                "deontic_formula": deontic_formula,
                                "obligation_type": element["norm_type"],
                                "deontic_operator": element["deontic_operator"],
                                "subject": element.get("subject", []),
                                "action": element.get("action", []),
                                "conditions": element.get("conditions", []),
                                "temporal_constraints": element.get("temporal_constraints", []),
                                "exceptions": element.get("exceptions", []),
                                "confidence": confidence,
                                "jurisdiction": jurisdiction,
                                "document_type": document_type,
                            }

                            if output_format in ["defeasible", "all"]:
                                formula_result["defeasible_form"] = convert_to_defeasible_logic(
                                    deontic_formula, element["norm_type"], element.get("exceptions", [])
                                )

                            results.append(formula_result)

                    except Exception as exc:
                        logger.warning(f"Failed to convert normative element: {exc}")
                        continue

            except Exception as exc:
                logger.warning(f"Failed to process legal section '{section[:50]}...': {exc}")
                continue

        normative_structure = identify_obligations(all_normative_elements) if extract_obligations else {
            "obligations": [],
            "permissions": [],
            "prohibitions": [],
        }

        conflicts = detect_normative_conflicts(all_normative_elements) if len(all_normative_elements) > 1 else []

        legal_entities = extract_all_legal_entities(results)
        legal_actions = extract_all_legal_actions(results)
        temporal_constraints = extract_all_temporal_constraints(results)

        summary = {
            "total_normative_statements": total_processed,
            "successful_conversions": successful_conversions,
            "conversion_rate": successful_conversions / max(1, total_processed),
            "average_confidence": sum(r["confidence"] for r in results) / max(1, len(results)),
            "normative_distribution": {
                "obligations": sum(1 for r in results if r["obligation_type"] == "obligation"),
                "permissions": sum(1 for r in results if r["obligation_type"] == "permission"),
                "prohibitions": sum(1 for r in results if r["obligation_type"] == "prohibition"),
            },
            "conflicts_detected": len(conflicts),
            "unique_entities": len(set(legal_entities)),
            "unique_actions": len(set(legal_actions)),
        }

        if total_processed > 0:
            logger.info(
                "Successfully converted %s/%s legal statements to deontic logic",
                successful_conversions,
                total_processed,
            )

        return {
            "status": "success",
            "deontic_formulas": results,
            "normative_structure": normative_structure,
            "legal_entities": legal_entities,
            "actions": legal_actions,
            "temporal_constraints": temporal_constraints,
            "conflicts": conflicts,
            "summary": summary,
            "metadata": {
                "tool": "legal_text_to_deontic",
                "version": "1.0.0",
                "jurisdiction": jurisdiction,
                "document_type": document_type,
                "output_format": output_format,
                "processing_timestamp": datetime.now().isoformat(),
            },
        }

    except Exception as exc:
        logger.error(f"Error in convert_legal_text_to_deontic: {exc}")
        return {
            "status": "error",
            "message": str(exc),
            "deontic_formulas": [],
            "normative_structure": {"obligations": [], "permissions": [], "prohibitions": []},
            "legal_entities": [],
            "actions": [],
            "temporal_constraints": [],
            "conflicts": [],
            "summary": {
                "total_normative_statements": 0,
                "successful_conversions": 0,
                "conversion_rate": 0.0,
                "average_confidence": 0.0,
            },
        }


def extract_legal_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    texts: List[str] = []

    legal_text_fields = [
        "text",
        "legal_text",
        "statute",
        "regulation",
        "contract_text",
        "clause",
        "provision",
        "section",
        "article",
        "content",
        "body",
    ]

    for field in legal_text_fields:
        if field in dataset:
            value = dataset[field]
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                texts.extend(str(t) for t in value)

    if "data" in dataset:
        data = dataset["data"]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for field in legal_text_fields:
                        if field in item and isinstance(item[field], str):
                            texts.append(item[field])
                elif isinstance(item, str):
                    texts.append(item)

    if "sections" in dataset:
        sections = dataset["sections"]
        if isinstance(sections, list):
            texts.extend(str(s) for s in sections)

    return [t.strip() for t in texts if t and t.strip()]


def calculate_deontic_confidence(element: Dict[str, Any], deontic_formula: str) -> float:
    score = 0.0

    if element.get("deontic_operator") in ["O", "P", "F"]:
        score += 0.3

    subjects = element.get("subject", [])
    if subjects and any(s.strip() for s in subjects):
        score += 0.2

    actions = element.get("action", [])
    if actions and any(a.strip() for a in actions):
        score += 0.2

    text = element.get("text", "").lower()
    legal_indicators = [
        "shall",
        "must",
        "required",
        "obligated",
        "duty",
        "may",
        "permitted",
        "allowed",
        "entitled",
        "forbidden",
        "prohibited",
        "cannot",
        "must not",
    ]

    found_indicators = sum(1 for indicator in legal_indicators if indicator in text)
    if found_indicators > 0:
        score += min(0.15, found_indicators * 0.05)

    if element.get("temporal_constraints", []):
        score += 0.1

    if element.get("conditions", []):
        score += 0.05

    score += 0.1
    return min(1.0, score)


def convert_to_defeasible_logic(deontic_formula: str, norm_type: str, exceptions: List[str]) -> str:
    if exceptions:
        return f"{norm_type}({deontic_formula}) unless ({'; '.join(exceptions)})."
    return f"{norm_type}({deontic_formula})."


def extract_all_legal_entities(results: List[Dict[str, Any]]) -> List[str]:
    entities: List[str] = []
    for result in results:
        entities.extend([str(s) for s in result.get("subject", [])])
    return entities


def extract_all_legal_actions(results: List[Dict[str, Any]]) -> List[str]:
    actions: List[str] = []
    for result in results:
        actions.extend([str(a) for a in result.get("action", [])])
    return actions


def extract_all_temporal_constraints(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    constraints: List[Dict[str, str]] = []
    for result in results:
        constraints.extend(result.get("temporal_constraints", []))
    return constraints
