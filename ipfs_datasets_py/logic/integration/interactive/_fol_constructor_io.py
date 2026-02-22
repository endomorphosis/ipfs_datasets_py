"""
FOL Constructor IO Mixin

Contains serialization, export, statistics, and private helper methods
extracted from InteractiveFOLConstructor to keep that module under 600 lines.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class FOLConstructorIOMixin:
    """
    Mixin providing IO, serialization, and session-helper methods for
    InteractiveFOLConstructor.

    Expects the host class to provide:
        - self.session_id, self.domain, self.metadata
        - self.session_statements (Dict[str, StatementRecord])
        - self.bridge (SymbolicFOLBridge)
        - self.enable_consistency_checking (bool)
        - self.analyze_logical_structure() -> Dict
        - self.validate_consistency() -> Dict
    """

    def export_session(self, format: str = "json") -> Dict[str, Any]:
        """
        Export the current session data.

        Args:
            format: Export format ("json", "fol", "prolog", "tptp")

        Returns:
            Dictionary with exported session data
        """
        export_data = {
            "session_metadata": {
                "session_id": self.session_id,
                "domain": self.domain,
                "created_at": self.metadata.created_at.isoformat(),
                "exported_at": datetime.now().isoformat(),
                "total_statements": len(self.session_statements),
                "average_confidence": self.metadata.average_confidence
            },
            "statements": [],
            "fol_formulas": [],
            "logical_analysis": {},
            "consistency_report": {},
            "errors": []
        }

        try:
            export_data["logical_analysis"] = self.analyze_logical_structure().get("analysis", {})
        except Exception as e:
            logger.warning(f"Failed to analyze logical structure during export: {e}")
            export_data["errors"].append(f"logical_analysis: {e}")

        try:
            export_data["consistency_report"] = self.validate_consistency().get("consistency_report", {})
        except Exception as e:
            logger.warning(f"Failed to validate consistency during export: {e}")
            export_data["errors"].append(f"consistency_report: {e}")

        for statement in self.session_statements.values():
            try:
                statement_data = {
                    "id": statement.id,
                    "text": statement.text,
                    "timestamp": statement.timestamp.isoformat(),
                    "confidence": statement.confidence,
                    "is_consistent": statement.is_consistent,
                    "tags": statement.tags
                }

                if statement.logical_components:
                    statement_data["logical_components"] = {
                        "quantifiers": statement.logical_components.quantifiers,
                        "predicates": statement.logical_components.predicates,
                        "entities": statement.logical_components.entities,
                        "connectives": statement.logical_components.logical_connectives
                    }

                export_data["statements"].append(statement_data)

                if statement.fol_formula:
                    fol_data = {
                        "statement_id": statement.id,
                        "original_text": statement.text,
                        "fol_formula": statement.fol_formula,
                        "format": format
                    }

                    if format != "symbolic":
                        try:
                            fol_data["exported_formula"] = self._convert_fol_format(
                                statement.fol_formula,
                                format
                            )
                        except Exception as e:
                            logger.warning(f"Failed to convert formula for statement {statement.id}: {e}")
                            export_data["errors"].append(f"fol_format {statement.id}: {e}")
                            fol_data["exported_formula"] = statement.fol_formula
                    else:
                        fol_data["exported_formula"] = statement.fol_formula

                    export_data["fol_formulas"].append(fol_data)
            except Exception as e:
                logger.warning(f"Failed to export statement {statement.id}: {e}")
                export_data["errors"].append(f"statement {statement.id}: {e}")

        return export_data

    def get_session_statistics(self) -> Dict[str, Any]:
        """Get comprehensive session statistics."""
        return {
            "session_id": self.session_id,
            "metadata": {
                "domain": self.domain,
                "created_at": self.metadata.created_at.isoformat(),
                "last_modified": self.metadata.last_modified.isoformat(),
                "total_statements": len(self.session_statements),
                "average_confidence": self.metadata.average_confidence
            },
            "logical_elements": self._count_logical_elements(),
            "bridge_statistics": self.bridge.get_statistics(),
            "session_health": self._assess_session_health()
        }

    def _update_session_metadata(self):
        """Update session metadata after changes."""
        self.metadata.last_modified = datetime.now()
        self.metadata.total_statements = len(self.session_statements)

        if self.session_statements:
            total_confidence = sum(stmt.confidence for stmt in self.session_statements.values())
            self.metadata.average_confidence = total_confidence / len(self.session_statements)

            self.metadata.consistent_statements = sum(
                1 for stmt in self.session_statements.values()
                if stmt.is_consistent is True
            )
            self.metadata.inconsistent_statements = sum(
                1 for stmt in self.session_statements.values()
                if stmt.is_consistent is False
            )

    def _check_consistency_with_existing(self, new_text: str, fol_result: Any) -> Dict[str, Any]:
        """Check consistency of new statement with existing ones."""
        consistency_result: Dict[str, Any] = {
            "consistent": True,
            "conflicts": [],
            "warnings": []
        }

        new_text_lower = new_text.lower()

        for existing_statement in self.session_statements.values():
            existing_text_lower = existing_statement.text.lower()

            if ("all" in new_text_lower and "no" in existing_text_lower) or \
               ("no" in new_text_lower and "all" in existing_text_lower):
                consistency_result["consistent"] = False
                consistency_result["conflicts"].append({
                    "type": "universal_contradiction",
                    "existing_statement": existing_statement.text,
                    "new_statement": new_text
                })

        return consistency_result

    def _check_logical_conflict(self, stmt1: Any, stmt2: Any) -> Dict[str, Any]:
        """Check for logical conflicts between two statements."""
        conflict_result: Dict[str, Any] = {
            "has_conflict": False,
            "conflict_type": None,
            "description": ""
        }

        if not stmt1.fol_formula or not stmt2.fol_formula:
            return conflict_result

        text1_lower = stmt1.text.lower()
        text2_lower = stmt2.text.lower()

        if ("all" in text1_lower and "no" in text2_lower) or \
           ("no" in text1_lower and "all" in text2_lower):
            conflict_result["has_conflict"] = True
            conflict_result["conflict_type"] = "universal_contradiction"
            conflict_result["description"] = "Universal statement contradicts negative universal"

        return conflict_result

    def _generate_consistency_recommendations(self, conflicts: List[Dict]) -> List[str]:
        """Generate recommendations for resolving consistency conflicts."""
        recommendations = []

        for conflict in conflicts:
            if conflict["conflict_type"] == "universal_contradiction":
                recommendations.append(
                    f"Review statements '{conflict['statement1']['text']}' and "
                    f"'{conflict['statement2']['text']}' for logical contradiction"
                )

        if len(conflicts) > 2:
            recommendations.append("Consider reviewing the domain assumptions and definitions")

        return recommendations

    def _generate_insights(self, analysis: Dict) -> List[str]:
        """Generate insights from logical structure analysis."""
        insights = []

        total_statements = analysis["session_overview"]["total_statements"]

        complex_ratio = analysis["complexity_analysis"]["complex_statements"] / total_statements
        if complex_ratio > 0.7:
            insights.append("Session contains many complex logical statements")
        elif complex_ratio < 0.3:
            insights.append("Session primarily contains simple logical statements")

        if analysis["consistency_analysis"]["inconsistent_statements"] > 0:
            insights.append("Some statements may be logically inconsistent")

        low_confidence = analysis["confidence_distribution"]["low_confidence"]
        if low_confidence > total_statements * 0.3:
            insights.append("Many statements have low confidence - consider rephrasing")

        quantified_ratio = analysis["complexity_analysis"]["quantified_statements"] / total_statements
        if quantified_ratio > 0.5:
            insights.append("Session heavily uses quantified statements")

        return insights

    def _convert_fol_format(self, formula: str, target_format: str) -> str:
        """Convert FOL formula to different format."""
        if target_format == "prolog":
            converted = formula.replace("∀", "forall")
            converted = converted.replace("∃", "exists")
            converted = converted.replace("→", ":-")
            converted = converted.replace("∧", ",")
            converted = converted.replace("∨", ";")
            return converted

        elif target_format == "tptp":
            converted = formula.replace("∀", "!")
            converted = converted.replace("∃", "?")
            converted = converted.replace("→", "=>")
            converted = converted.replace("∧", "&")
            converted = converted.replace("∨", "|")
            return f"fof(statement, axiom, {converted})."

        return formula

    def _count_logical_elements(self) -> Dict[str, int]:
        """Count logical elements across all statements."""
        counts = {
            "total_quantifiers": 0,
            "total_predicates": 0,
            "total_entities": 0,
            "total_connectives": 0
        }

        for statement in self.session_statements.values():
            if statement.logical_components:
                counts["total_quantifiers"] += len(statement.logical_components.quantifiers)
                counts["total_predicates"] += len(statement.logical_components.predicates)
                counts["total_entities"] += len(statement.logical_components.entities)
                counts["total_connectives"] += len(statement.logical_components.logical_connectives)

        return counts

    def _assess_session_health(self) -> Dict[str, Any]:
        """Assess the overall health of the session."""
        if not self.session_statements:
            return {"status": "empty", "score": 0}

        total_statements = len(self.session_statements)

        avg_confidence = self.metadata.average_confidence
        consistency_ratio = self.metadata.consistent_statements / total_statements

        health_score = (avg_confidence * 50) + (consistency_ratio * 50)

        health_status = "excellent" if health_score > 80 else \
                       "good" if health_score > 60 else \
                       "fair" if health_score > 40 else "poor"

        return {
            "status": health_status,
            "score": round(health_score, 2),
            "metrics": {
                "average_confidence": avg_confidence,
                "consistency_ratio": consistency_ratio,
                "total_statements": total_statements
            }
        }
