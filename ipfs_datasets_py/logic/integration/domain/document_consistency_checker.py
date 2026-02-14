"""
Document Consistency Checker

This module implements a document consistency checker that functions like a debugger
for legal documents, checking them against temporal deontic logic theorems derived
from caselaw to ensure logical consistency.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
import re

from ..converters.deontic_logic_core import (
    DeonticFormula, DeonticOperator, DeonticRuleSet, TemporalCondition,
    LegalAgent, LegalContext
)
from .deontic_logic_converter import DeonticLogicConverter, ConversionContext
from .temporal_deontic_rag_store import TemporalDeonticRAGStore, ConsistencyResult
from .proof_execution_engine import ProofExecutionEngine, ProofResult, ProofStatus
from .deontic_query_engine import DeonticQueryEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DocumentAnalysis:
    """Analysis result for a legal document."""
    document_id: str
    extracted_formulas: List[DeonticFormula] = field(default_factory=list)
    consistency_result: Optional[ConsistencyResult] = None
    proof_results: List[ProofResult] = field(default_factory=list)
    confidence_score: float = 0.0
    issues_found: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    processing_time: float = 0.0


@dataclass
class DebugReport:
    """Debug report similar to a compiler's error report."""
    document_id: str
    total_issues: int = 0
    critical_errors: int = 0
    warnings: int = 0
    suggestions: int = 0
    issues: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    fix_suggestions: List[str] = field(default_factory=list)


class DocumentConsistencyChecker:
    """
    A document consistency checker that functions like a debugger for legal documents.
    
    This class analyzes legal documents, extracts deontic logic formulas,
    and checks them against a corpus of temporal deontic logic theorems
    derived from caselaw to identify inconsistencies, conflicts, and issues.
    """
    
    def __init__(self,
                 rag_store: TemporalDeonticRAGStore,
                 logic_converter: Optional[DeonticLogicConverter] = None,
                 proof_engine: Optional[ProofExecutionEngine] = None,
                 query_engine: Optional[DeonticQueryEngine] = None):
        """
        Initialize the document consistency checker.
        
        Args:
            rag_store: The temporal deontic RAG store with theorems
            logic_converter: Converter for extracting deontic logic from text
            proof_engine: Theorem prover for formal verification
            query_engine: Query engine for deontic logic
        """
        self.rag_store = rag_store
        self.logic_converter = logic_converter
        self.proof_engine = proof_engine
        self.query_engine = query_engine or DeonticQueryEngine()
        
        # Analysis configuration
        self.enable_theorem_proving = proof_engine is not None
        self.strict_mode = False  # Whether to treat warnings as errors
        self.max_formulas_per_document = 100
        
        logger.info("Initialized DocumentConsistencyChecker")
    
    def check_document(self,
                      document_text: str,
                      document_id: str,
                      temporal_context: Optional[datetime] = None,
                      jurisdiction: Optional[str] = None,
                      legal_domain: Optional[str] = None,
                      document_metadata: Optional[Dict[str, Any]] = None) -> DocumentAnalysis:
        """
        Check a document for consistency against the theorem corpus.
        
        This is the main "debugging" function that analyzes a document like a
        compiler would analyze source code.
        
        Args:
            document_text: The text of the legal document
            document_id: Unique identifier for the document
            temporal_context: Time context for the document
            jurisdiction: Relevant jurisdiction
            legal_domain: Relevant legal domain
            document_metadata: Additional metadata about the document
            
        Returns:
            DocumentAnalysis with consistency results and issues
        """
        start_time = datetime.now()
        
        try:
            # Phase 1: Extract deontic logic formulas from document
            logger.info(f"Phase 1: Extracting deontic logic from document {document_id}")
            extracted_formulas = self._extract_deontic_formulas(
                document_text, temporal_context, jurisdiction, legal_domain, document_metadata
            )
            
            if not extracted_formulas:
                logger.warning(f"No deontic formulas extracted from document {document_id}")
                return DocumentAnalysis(
                    document_id=document_id,
                    extracted_formulas=[],
                    confidence_score=0.0,
                    issues_found=[{
                        "type": "warning",
                        "severity": "low",
                        "message": "No deontic logic formulas found in document",
                        "suggestion": "Ensure document contains legal obligations, permissions, or prohibitions"
                    }],
                    processing_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Phase 2: Check consistency against theorem corpus
            logger.info(f"Phase 2: Checking consistency for {len(extracted_formulas)} formulas")
            consistency_result = self.rag_store.check_document_consistency(
                extracted_formulas, temporal_context, jurisdiction, legal_domain
            )
            
            # Phase 3: Optional theorem proving for formal verification
            proof_results = []
            if self.enable_theorem_proving and self.proof_engine:
                logger.info("Phase 3: Running formal verification with theorem prover")
                proof_results = self._run_formal_verification(extracted_formulas)
            
            # Phase 4: Analyze results and generate issues
            issues_found = self._analyze_results(consistency_result, proof_results)
            recommendations = self._generate_recommendations(consistency_result, issues_found)
            confidence_score = self._calculate_overall_confidence(consistency_result, proof_results, issues_found)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            analysis = DocumentAnalysis(
                document_id=document_id,
                extracted_formulas=extracted_formulas,
                consistency_result=consistency_result,
                proof_results=proof_results,
                confidence_score=confidence_score,
                issues_found=issues_found,
                recommendations=recommendations,
                processing_time=processing_time
            )
            
            logger.info(f"Document analysis completed in {processing_time:.2f}s: "
                       f"{len(issues_found)} issues found, confidence: {confidence_score:.2f}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error checking document {document_id}: {e}")
            return DocumentAnalysis(
                document_id=document_id,
                confidence_score=0.0,
                issues_found=[{
                    "type": "error",
                    "severity": "critical",
                    "message": f"Failed to analyze document: {str(e)}",
                    "suggestion": "Check document format and content"
                }],
                processing_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_debug_report(self, analysis: DocumentAnalysis) -> DebugReport:
        """
        Generate a debug report similar to a compiler's error report.
        
        Args:
            analysis: The document analysis result
            
        Returns:
            DebugReport with formatted issues and suggestions
        """
        issues = analysis.issues_found
        
        # Categorize issues by severity
        critical_errors = [i for i in issues if i.get("type") == "error" or i.get("severity") == "critical"]
        warnings = [i for i in issues if i.get("type") == "warning" or i.get("severity") in ["medium", "warning"]]
        suggestions = [i for i in issues if i.get("type") == "suggestion" or i.get("severity") == "low"]
        
        # Generate summary
        summary_lines = []
        if critical_errors:
            summary_lines.append(f"❌ {len(critical_errors)} critical error(s) found")
        if warnings:
            summary_lines.append(f"⚠️  {len(warnings)} warning(s) found")
        if suggestions:
            summary_lines.append(f"💡 {len(suggestions)} suggestion(s) available")
        
        if not issues:
            summary_lines.append("✅ No consistency issues found")
        
        summary = "\n".join(summary_lines)
        
        # Generate fix suggestions
        fix_suggestions = analysis.recommendations.copy()
        
        # Add specific fixes based on consistency results
        if analysis.consistency_result and analysis.consistency_result.conflicts:
            fix_suggestions.append("Review conflicting legal provisions and resolve contradictions")
        
        if analysis.consistency_result and analysis.consistency_result.temporal_conflicts:
            fix_suggestions.append("Check temporal validity of legal provisions")
        
        return DebugReport(
            document_id=analysis.document_id,
            total_issues=len(issues),
            critical_errors=len(critical_errors),
            warnings=len(warnings),
            suggestions=len(suggestions),
            issues=issues,
            summary=summary,
            fix_suggestions=fix_suggestions
        )
    
    def batch_check_documents(self,
                            documents: List[Tuple[str, str]],  # (document_text, document_id)
                            temporal_context: Optional[datetime] = None,
                            jurisdiction: Optional[str] = None,
                            legal_domain: Optional[str] = None) -> List[DocumentAnalysis]:
        """
        Check multiple documents in batch for consistency.
        
        Args:
            documents: List of (document_text, document_id) tuples
            temporal_context: Time context for the documents
            jurisdiction: Relevant jurisdiction
            legal_domain: Relevant legal domain
            
        Returns:
            List of DocumentAnalysis results
        """
        results = []
        
        logger.info(f"Starting batch consistency check for {len(documents)} documents")
        
        for i, (document_text, document_id) in enumerate(documents):
            logger.info(f"Processing document {i+1}/{len(documents)}: {document_id}")
            
            analysis = self.check_document(
                document_text, document_id, temporal_context, jurisdiction, legal_domain
            )
            results.append(analysis)
        
        logger.info(f"Batch processing completed: {len(results)} documents analyzed")
        return results
    
    def _extract_deontic_formulas(self,
                                document_text: str,
                                temporal_context: Optional[datetime],
                                jurisdiction: Optional[str],
                                legal_domain: Optional[str],
                                document_metadata: Optional[Dict[str, Any]]) -> List[DeonticFormula]:
        """Extract deontic logic formulas from document text."""
        if self.logic_converter:
            try:
                # Use the sophisticated logic converter
                context = ConversionContext(
                    source_document_path="",
                    document_title=document_metadata.get("title", "") if document_metadata else "",
                    enable_temporal_analysis=temporal_context is not None,
                    target_jurisdiction=jurisdiction,
                    legal_domain=legal_domain
                )
                
                # For now, create a mock knowledge graph from the text
                # In a real implementation, this would use GraphRAG
                mock_kg = self._create_mock_knowledge_graph(document_text)
                
                result = self.logic_converter.convert_knowledge_graph_to_logic(mock_kg, context)
                return result.formulas if result.success else []
                
            except Exception as e:
                logger.warning(f"Logic converter failed: {e}")
                # Fall back to basic extraction
                return self._basic_formula_extraction(document_text)
        else:
            # Use basic extraction
            return self._basic_formula_extraction(document_text)
    
    def _create_mock_knowledge_graph(self, text: str):
        """Create a mock knowledge graph for testing purposes."""
        # This is a simplified mock - in practice would use GraphRAG
        class MockEntity:
            def __init__(self, entity_id: str, name: str, entity_type: str = "entity"):
                self.entity_id = entity_id
                self.name = name
                self.entity_type = entity_type
                self.properties = {"text": text[:500]}  # First 500 chars
                self.confidence = 1.0
                self.source_text = text
        
        class MockKnowledgeGraph:
            def __init__(self):
                self.entities = [MockEntity("doc_entity_1", "Document Content", "legal_document")]
                self.relationships = []
        
        return MockKnowledgeGraph()
    
    def _basic_formula_extraction(self, text: str) -> List[DeonticFormula]:
        """Basic extraction of deontic formulas using pattern matching."""
        formulas = []
        
        # Pattern matching for common legal language
        obligation_patterns = [
            r'(must|shall|required to|obligated to|duty to)\s+([^.!?]+)',
            r'(is required to|are required to)\s+([^.!?]+)',
            r'(has a duty to|have a duty to)\s+([^.!?]+)'
        ]
        
        permission_patterns = [
            r'(may|permitted to|allowed to|can)\s+([^.!?]+)',
            r'(has the right to|have the right to)\s+([^.!?]+)',
            r'(is authorized to|are authorized to)\s+([^.!?]+)'
        ]
        
        prohibition_patterns = [
            r'(must not|shall not|prohibited from|forbidden to)\s+([^.!?]+)',
            r'(cannot|may not|not allowed to)\s+([^.!?]+)',
            r'(is prohibited from|are prohibited from)\s+([^.!?]+)'
        ]
        
        # Extract obligations
        for pattern in obligation_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                proposition = match.group(2).strip()
                if len(proposition) > 5:  # Filter out very short matches
                    formula = DeonticFormula(
                        operator=DeonticOperator.OBLIGATION,
                        proposition=proposition,
                        agent=LegalAgent("unspecified", "Unspecified Party", "person"),
                        confidence=0.7,
                        source_text=match.group(0)
                    )
                    formulas.append(formula)
        
        # Extract permissions
        for pattern in permission_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                proposition = match.group(2).strip()
                if len(proposition) > 5:
                    formula = DeonticFormula(
                        operator=DeonticOperator.PERMISSION,
                        proposition=proposition,
                        agent=LegalAgent("unspecified", "Unspecified Party", "person"),
                        confidence=0.7,
                        source_text=match.group(0)
                    )
                    formulas.append(formula)
        
        # Extract prohibitions
        for pattern in prohibition_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                proposition = match.group(2).strip()
                if len(proposition) > 5:
                    formula = DeonticFormula(
                        operator=DeonticOperator.PROHIBITION,
                        proposition=proposition,
                        agent=LegalAgent("unspecified", "Unspecified Party", "person"),
                        confidence=0.7,
                        source_text=match.group(0)
                    )
                    formulas.append(formula)
        
        # Limit number of formulas to prevent overwhelming analysis
        if len(formulas) > self.max_formulas_per_document:
            formulas = formulas[:self.max_formulas_per_document]
            logger.warning(f"Limited extracted formulas to {self.max_formulas_per_document}")
        
        return formulas
    
    def _run_formal_verification(self, formulas: List[DeonticFormula]) -> List[ProofResult]:
        """Run formal verification using theorem provers."""
        if not self.proof_engine:
            return []
        
        proof_results = []
        
        for formula in formulas[:10]:  # Limit to first 10 for performance
            try:
                result = self.proof_engine.prove_deontic_formula(formula)
                proof_results.append(result)
            except Exception as e:
                logger.warning(f"Proof failed for formula: {e}")
                # Create a failure result
                proof_results.append(ProofResult(
                    prover="unknown",
                    statement=str(formula),
                    status=ProofStatus.ERROR,
                    errors=[str(e)]
                ))
        
        return proof_results
    
    def _analyze_results(self, consistency_result: ConsistencyResult, 
                        proof_results: List[ProofResult]) -> List[Dict[str, Any]]:
        """Analyze consistency and proof results to generate issues."""
        issues = []
        
        # Analyze consistency results
        if consistency_result:
            # Process logical conflicts
            for conflict in consistency_result.conflicts:
                issues.append({
                    "type": "error",
                    "severity": "critical",
                    "category": "logical_conflict",
                    "message": conflict.get("description", "Logical conflict detected"),
                    "details": {
                        "document_formula": conflict.get("document_formula"),
                        "conflicting_theorem": conflict.get("conflicting_theorem"),
                        "source_case": conflict.get("source_case")
                    },
                    "suggestion": "Review and resolve the conflicting legal provisions"
                })
            
            # Process temporal conflicts
            for temp_conflict in consistency_result.temporal_conflicts:
                issues.append({
                    "type": "warning",
                    "severity": "medium",
                    "category": "temporal_conflict",
                    "message": temp_conflict.get("description", "Temporal conflict detected"),
                    "details": temp_conflict,
                    "suggestion": "Check the temporal validity of the legal provision"
                })
            
            # Low confidence warning
            if consistency_result.confidence_score < 0.5:
                issues.append({
                    "type": "warning",
                    "severity": "medium",
                    "category": "low_confidence",
                    "message": f"Low confidence in consistency analysis ({consistency_result.confidence_score:.2f})",
                    "suggestion": "Consider additional legal review or more specific theorem matching"
                })
        
        # Analyze proof results
        for proof_result in proof_results:
            if proof_result.status == ProofStatus.ERROR:
                issues.append({
                    "type": "error",
                    "severity": "medium",
                    "category": "proof_error",
                    "message": f"Formal verification failed: {', '.join(proof_result.errors)}",
                    "details": {"statement": proof_result.statement},
                    "suggestion": "Check formula syntax and logical validity"
                })
            elif proof_result.status == ProofStatus.UNSATISFIABLE:
                issues.append({
                    "type": "error",
                    "severity": "critical",
                    "category": "logical_inconsistency",
                    "message": "Formula is logically inconsistent (unsatisfiable)",
                    "details": {"statement": proof_result.statement},
                    "suggestion": "Review the logical structure of the legal provision"
                })
        
        return issues
    
    def _generate_recommendations(self, consistency_result: ConsistencyResult, 
                                issues: List[Dict[str, Any]]) -> List[str]:
        """Generate recommendations based on analysis results."""
        recommendations = []
        
        # Category-based recommendations
        issue_categories = [issue.get("category") for issue in issues]
        
        if "logical_conflict" in issue_categories:
            recommendations.append("Resolve logical conflicts by clarifying contradictory provisions")
        
        if "temporal_conflict" in issue_categories:
            recommendations.append("Clarify temporal scope and validity periods of legal provisions")
        
        if "proof_error" in issue_categories:
            recommendations.append("Review formula extraction and ensure proper legal language structure")
        
        if "low_confidence" in issue_categories:
            recommendations.append("Consider additional legal research or expert review")
        
        # General recommendations
        if consistency_result and len(consistency_result.relevant_theorems) < 3:
            recommendations.append("Limited precedent data available - consider expanding theorem corpus")
        
        if not issues:
            recommendations.append("Document appears consistent with existing legal theorems")
        
        return recommendations
    
    def _calculate_overall_confidence(self, consistency_result: ConsistencyResult,
                                    proof_results: List[ProofResult],
                                    issues: List[Dict[str, Any]]) -> float:
        """Calculate overall confidence score for the analysis."""
        base_confidence = 1.0
        
        # Consistency result confidence
        if consistency_result:
            base_confidence *= consistency_result.confidence_score
        else:
            base_confidence *= 0.5
        
        # Proof result impact
        if proof_results:
            successful_proofs = sum(1 for r in proof_results if r.status == ProofStatus.SATISFIABLE)
            proof_ratio = successful_proofs / len(proof_results)
            base_confidence *= (0.7 + 0.3 * proof_ratio)
        
        # Issue impact
        critical_issues = sum(1 for i in issues if i.get("severity") == "critical")
        medium_issues = sum(1 for i in issues if i.get("severity") == "medium")
        
        issue_penalty = critical_issues * 0.3 + medium_issues * 0.1
        base_confidence = max(0.0, base_confidence - issue_penalty)
        
        return min(1.0, base_confidence)