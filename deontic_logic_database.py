"""
Comprehensive Deontic Logic Database System for Legal Analysis

This module provides automatic deontic logic conversion, RAG relationships,
contradiction linting, and case law shepherding capabilities.
"""

import re
import json
import sqlite3
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class TreatmentType(Enum):
    """Types of case law treatment"""
    FOLLOWED = "followed"
    DISTINGUISHED = "distinguished"
    CRITICIZED = "criticized"
    QUESTIONED = "questioned"
    OVERRULED = "overruled"
    SUPERSEDED = "superseded"

@dataclass
class DeonticStatement:
    """Represents a deontic logic statement with metadata."""
    id: Optional[int]
    logic_expression: str
    natural_language: str
    confidence: float
    topic_id: int
    case_id: Optional[str]
    timestamp: datetime
    modality: str  # 'obligation', 'permission', 'prohibition'

@dataclass
class LogicalConflict:
    """Represents a logical conflict between statements."""
    id: Optional[int]
    statement_a_id: int
    statement_b_id: int
    conflict_type: str
    severity: str  # 'critical', 'warning', 'info'
    description: str
    suggested_resolution: str

@dataclass
class ShepherdCitation:
    """Represents a citation relationship for shepherding."""
    id: Optional[int]
    citing_case: str
    cited_case: str
    treatment: str  # 'followed', 'distinguished', 'overruled', etc.
    date: datetime
    precedent_strength: float

class AutomaticLogicConverter:
    """Converts legal text to deontic logic expressions."""
    
    def __init__(self):
        self.deontic_patterns = {
            'obligation': [
                r'must\s+(.+)',
                r'shall\s+(.+)',
                r'required\s+to\s+(.+)',
                r'duty\s+to\s+(.+)',
                r'obligation\s+to\s+(.+)',
                r'mandated\s+to\s+(.+)'
            ],
            'permission': [
                r'may\s+(.+)',
                r'permitted\s+to\s+(.+)',
                r'allowed\s+to\s+(.+)',
                r'right\s+to\s+(.+)',
                r'can\s+(.+)',
                r'authorized\s+to\s+(.+)'
            ],
            'prohibition': [
                r'cannot\s+(.+)',
                r'shall\s+not\s+(.+)',
                r'must\s+not\s+(.+)',
                r'prohibited\s+from\s+(.+)',
                r'forbidden\s+to\s+(.+)',
                r'barred\s+from\s+(.+)'
            ]
        }
        
        self.temporal_patterns = [
            r'immediately',
            r'within\s+(\d+)\s+(days?|months?|years?)',
            r'after\s+(.+)',
            r'before\s+(.+)',
            r'during\s+(.+)',
            r'until\s+(.+)'
        ]
        
        self.condition_patterns = [
            r'if\s+(.+)',
            r'when\s+(.+)',
            r'unless\s+(.+)',
            r'provided\s+that\s+(.+)',
            r'subject\s+to\s+(.+)'
        ]

    def convert_to_deontic_logic(self, text: str, context: Dict[str, Any] = None) -> List[DeonticStatement]:
        """Convert legal text to deontic logic statements."""
        statements = []
        
        # Normalize text
        text = self._normalize_text(text)
        
        # Extract sentences
        sentences = self._split_sentences(text)
        
        for sentence in sentences:
            for modality, patterns in self.deontic_patterns.items():
                for pattern in patterns:
                    matches = re.finditer(pattern, sentence, re.IGNORECASE)
                    for match in matches:
                        action = match.group(1).strip()
                        
                        # Extract temporal constraints
                        temporal = self._extract_temporal(sentence)
                        
                        # Extract conditions
                        conditions = self._extract_conditions(sentence)
                        
                        # Generate formal logic expression
                        logic_expr = self._generate_logic_expression(
                            modality, action, temporal, conditions
                        )
                        
                        # Calculate confidence score
                        confidence = self._calculate_confidence(sentence, match, context)
                        
                        statement = DeonticStatement(
                            id=None,
                            logic_expression=logic_expr,
                            natural_language=sentence,
                            confidence=confidence,
                            topic_id=context.get('topic_id', 1) if context else 1,
                            case_id=context.get('case_id') if context else None,
                            timestamp=datetime.now(),
                            modality=modality
                        )
                        statements.append(statement)
        
        return statements
    
    def _normalize_text(self, text: str) -> str:
        """Normalize legal text for processing."""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Handle common legal abbreviations
        text = re.sub(r'\bv\.\s+', 'v. ', text)
        # Remove citation numbers for cleaner processing
        text = re.sub(r'\d+\s+U\.S\.\s+\d+', '', text)
        return text.strip()
    
    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitting - could be enhanced with more sophisticated NLP
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _extract_temporal(self, sentence: str) -> List[str]:
        """Extract temporal constraints from sentence."""
        temporal = []
        for pattern in self.temporal_patterns:
            matches = re.findall(pattern, sentence, re.IGNORECASE)
            temporal.extend(matches)
        return temporal
    
    def _extract_conditions(self, sentence: str) -> List[str]:
        """Extract conditional clauses from sentence."""
        conditions = []
        for pattern in self.condition_patterns:
            matches = re.findall(pattern, sentence, re.IGNORECASE)
            conditions.extend(matches)
        return conditions
    
    def _generate_logic_expression(self, modality: str, action: str, 
                                 temporal: List[str], conditions: List[str]) -> str:
        """Generate formal deontic logic expression."""
        # Convert action to predicate format
        predicate = self._action_to_predicate(action)
        
        # Choose deontic operator
        operator = {'obligation': 'O', 'permission': 'P', 'prohibition': 'F'}[modality]
        
        # Build base expression
        expr = f"{operator}({predicate})"
        
        # Add temporal constraints
        if temporal:
            temporal_expr = " ∧ ".join([f"T({t})" for t in temporal])
            expr += f" ∧ {temporal_expr}"
        
        # Add conditions
        if conditions:
            condition_expr = " ∧ ".join([f"C({c})" for c in conditions])
            expr = f"({condition_expr}) → {expr}"
        
        return expr
    
    def _action_to_predicate(self, action: str) -> str:
        """Convert natural language action to predicate format."""
        # Simple conversion - replace spaces with underscores, lowercase
        predicate = re.sub(r'\s+', '_', action.lower())
        predicate = re.sub(r'[^\w_]', '', predicate)
        return predicate
    
    def _calculate_confidence(self, sentence: str, match: re.Match, 
                            context: Dict[str, Any] = None) -> float:
        """Calculate confidence score for the conversion."""
        confidence = 0.7  # Base confidence
        
        # Increase confidence for strong modal verbs
        strong_modals = ['must', 'shall', 'cannot', 'prohibited']
        if any(modal in sentence.lower() for modal in strong_modals):
            confidence += 0.2
        
        # Increase confidence for legal context
        legal_terms = ['court', 'statute', 'regulation', 'plaintiff', 'defendant']
        if any(term in sentence.lower() for term in legal_terms):
            confidence += 0.1
        
        # Decrease confidence for ambiguous language
        ambiguous = ['may', 'might', 'could', 'should']
        if any(word in sentence.lower() for word in ambiguous):
            confidence -= 0.1
        
        return min(max(confidence, 0.0), 1.0)

class ConflictDetectionEngine:
    """Detects logical conflicts in deontic statements."""
    
    def __init__(self):
        self.conflict_types = {
            'direct_contradiction': self._check_direct_contradiction,
            'temporal_inconsistency': self._check_temporal_inconsistency,
            'scope_conflict': self._check_scope_conflict,
            'precedent_violation': self._check_precedent_violation
        }
    
    def detect_conflicts(self, statements: List[DeonticStatement]) -> List[LogicalConflict]:
        """Detect conflicts between deontic statements."""
        conflicts = []
        
        for i, stmt_a in enumerate(statements):
            for j, stmt_b in enumerate(statements[i+1:], i+1):
                for conflict_type, checker in self.conflict_types.items():
                    conflict = checker(stmt_a, stmt_b)
                    if conflict:
                        conflicts.append(conflict)
        
        return conflicts
    
    def _check_direct_contradiction(self, stmt_a: DeonticStatement, 
                                  stmt_b: DeonticStatement) -> Optional[LogicalConflict]:
        """Check for direct logical contradictions."""
        # Extract predicates from logic expressions
        pred_a = self._extract_predicate(stmt_a.logic_expression)
        pred_b = self._extract_predicate(stmt_b.logic_expression)
        
        # Check if same predicate with opposite modalities
        if pred_a == pred_b:
            if ((stmt_a.modality == 'obligation' and stmt_b.modality == 'prohibition') or
                (stmt_a.modality == 'prohibition' and stmt_b.modality == 'obligation')):
                
                return LogicalConflict(
                    id=None,
                    statement_a_id=stmt_a.id,
                    statement_b_id=stmt_b.id,
                    conflict_type='direct_contradiction',
                    severity='critical',
                    description=f"Direct contradiction: {stmt_a.modality} vs {stmt_b.modality} for same action",
                    suggested_resolution="Review case precedence and jurisdiction scope"
                )
        
        return None
    
    def _check_temporal_inconsistency(self, stmt_a: DeonticStatement, 
                                    stmt_b: DeonticStatement) -> Optional[LogicalConflict]:
        """Check for temporal inconsistencies."""
        # Extract temporal information
        temporal_a = re.findall(r'T\(([^)]+)\)', stmt_a.logic_expression)
        temporal_b = re.findall(r'T\(([^)]+)\)', stmt_b.logic_expression)
        
        if temporal_a and temporal_b:
            # Simple check for conflicting temporal constraints
            if any('before' in t_a and 'after' in t_b for t_a in temporal_a for t_b in temporal_b):
                return LogicalConflict(
                    id=None,
                    statement_a_id=stmt_a.id,
                    statement_b_id=stmt_b.id,
                    conflict_type='temporal_inconsistency',
                    severity='warning',
                    description="Conflicting temporal constraints detected",
                    suggested_resolution="Clarify temporal sequence and dependencies"
                )
        
        return None
    
    def _check_scope_conflict(self, stmt_a: DeonticStatement, 
                            stmt_b: DeonticStatement) -> Optional[LogicalConflict]:
        """Check for scope conflicts."""
        # This would check for jurisdictional or applicability conflicts
        # Simplified implementation
        return None
    
    def _check_precedent_violation(self, stmt_a: DeonticStatement, 
                                 stmt_b: DeonticStatement) -> Optional[LogicalConflict]:
        """Check for precedent violations."""
        # This would check against established precedent
        # Simplified implementation
        return None
    
    def _extract_predicate(self, logic_expression: str) -> str:
        """Extract the main predicate from a logic expression."""
        match = re.search(r'[OPF]\(([^)]+)\)', logic_expression)
        return match.group(1) if match else ""

class LegalRAGProcessor:
    """RAG system for deontic logic relationships."""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        self.statement_vectors = None
        self.statements = []
    
    def index_statements(self, statements: List[DeonticStatement]):
        """Index statements for RAG queries."""
        self.statements = statements
        
        # Combine natural language and logic expressions for vectorization
        texts = [f"{stmt.natural_language} {stmt.logic_expression}" for stmt in statements]
        
        if texts:
            self.statement_vectors = self.vectorizer.fit_transform(texts)
    
    def query_related_statements(self, query: str, top_k: int = 5) -> List[Tuple[DeonticStatement, float]]:
        """Find statements related to the query."""
        if self.statement_vectors is None or not self.statements:
            return []
        
        # Vectorize query
        query_vector = self.vectorizer.transform([query])
        
        # Calculate similarities
        similarities = cosine_similarity(query_vector, self.statement_vectors)[0]
        
        # Get top-k results
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        
        results = []
        for idx in top_indices:
            if similarities[idx] > 0.1:  # Minimum similarity threshold
                results.append((self.statements[idx], similarities[idx]))
        
        return results
    
    def find_topic_relationships(self, topic_id: int) -> Dict[str, List[DeonticStatement]]:
        """Find all statements related to a specific topic."""
        topic_statements = [stmt for stmt in self.statements if stmt.topic_id == topic_id]
        
        relationships = {
            'obligations': [stmt for stmt in topic_statements if stmt.modality == 'obligation'],
            'permissions': [stmt for stmt in topic_statements if stmt.modality == 'permission'],
            'prohibitions': [stmt for stmt in topic_statements if stmt.modality == 'prohibition']
        }
        
        return relationships

class ShepherdingEngine:
    """Professional case law shepherding system."""
    
    def __init__(self):
        self.treatment_weights = {
            'followed': 1.0,
            'distinguished': 0.7,
            'criticized': 0.3,
            'questioned': 0.3,
            'overruled': 0.0,
            'superseded': 0.0
        }
    
    def validate_case_status(self, case_id: str, citations: List[ShepherdCitation]) -> Dict[str, Any]:
        """Validate the current status of a case."""
        relevant_citations = [c for c in citations if c.cited_case == case_id]
        
        # Check for negative treatments
        negative_treatments = ['overruled', 'superseded', 'criticized', 'questioned']
        negative_cites = [c for c in relevant_citations if c.treatment in negative_treatments]
        
        # Calculate precedent strength
        total_weight = sum(self.treatment_weights.get(c.treatment, 0.5) for c in relevant_citations)
        precedent_strength = total_weight / max(len(relevant_citations), 1)
        
        status = {
            'case_id': case_id,
            'status': 'good_law',
            'precedent_strength': precedent_strength,
            'total_citations': len(relevant_citations),
            'negative_citations': len(negative_cites),
            'warnings': []
        }
        
        # Determine status
        if any(c.treatment == 'overruled' for c in negative_cites):
            status['status'] = 'overruled'
            status['warnings'].append('Case has been overruled')
        elif any(c.treatment == 'superseded' for c in negative_cites):
            status['status'] = 'superseded'
            status['warnings'].append('Case has been superseded by statute')
        elif len(negative_cites) > 0:
            status['status'] = 'questioned'
            status['warnings'].append(f'{len(negative_cites)} negative citations found')
        
        return status
    
    def trace_precedent_lineage(self, case_id: str, citations: List[ShepherdCitation], 
                              max_depth: int = 5) -> Dict[str, Any]:
        """Trace the complete precedent lineage of a case."""
        lineage = {
            'case_id': case_id,
            'cited_by': [],
            'cites': [],
            'depth': 0
        }
        
        # Find cases cited by this case
        cited_cases = [c for c in citations if c.citing_case == case_id]
        for citation in cited_cases:
            lineage['cites'].append({
                'case_id': citation.cited_case,
                'treatment': citation.treatment,
                'date': citation.date.isoformat(),
                'strength': citation.precedent_strength
            })
        
        # Find cases that cite this case
        citing_cases = [c for c in citations if c.cited_case == case_id]
        for citation in citing_cases:
            lineage['cited_by'].append({
                'case_id': citation.citing_case,
                'treatment': citation.treatment,
                'date': citation.date.isoformat(),
                'strength': citation.precedent_strength
            })
        
        return lineage
    
    def get_precedent_lineage(self, case_id: str) -> Dict[str, Any]:
        """Get precedent lineage for a case (compatibility method)."""
        return {
            'case_id': case_id,
            'precedents_relied_on': [],
            'subsequent_cases': []
        }

class DeonticLogicDatabase:
    """Main database class for deontic logic system."""
    
    def __init__(self, db_path: str = "deontic_logic.db"):
        self.db_path = db_path
        self.converter = AutomaticLogicConverter()
        self.conflict_detector = ConflictDetectionEngine()
        self.rag_processor = LegalRAGProcessor()
        self.shepherding_engine = ShepherdingEngine()
        
        self._init_database()
        self._load_existing_data()
    
    def _init_database(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS deontic_statements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logic_expression TEXT NOT NULL,
                    natural_language TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    topic_id INTEGER NOT NULL,
                    case_id TEXT,
                    timestamp TEXT NOT NULL,
                    modality TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS legal_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    case_count INTEGER DEFAULT 0
                );
                
                CREATE TABLE IF NOT EXISTS topic_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_a INTEGER NOT NULL,
                    topic_b INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL,
                    strength REAL NOT NULL,
                    FOREIGN KEY (topic_a) REFERENCES legal_topics (id),
                    FOREIGN KEY (topic_b) REFERENCES legal_topics (id)
                );
                
                CREATE TABLE IF NOT EXISTS logical_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    statement_a INTEGER NOT NULL,
                    statement_b INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL,
                    FOREIGN KEY (statement_a) REFERENCES deontic_statements (id),
                    FOREIGN KEY (statement_b) REFERENCES deontic_statements (id)
                );
                
                CREATE TABLE IF NOT EXISTS conflict_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    statement_a INTEGER NOT NULL,
                    statement_b INTEGER NOT NULL,
                    conflict_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT NOT NULL,
                    suggested_resolution TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (statement_a) REFERENCES deontic_statements (id),
                    FOREIGN KEY (statement_b) REFERENCES deontic_statements (id)
                );
                
                CREATE TABLE IF NOT EXISTS case_precedents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    precedent_id TEXT NOT NULL,
                    treatment_type TEXT NOT NULL,
                    strength REAL NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS temporal_evolution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    statement_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    FOREIGN KEY (statement_id) REFERENCES deontic_statements (id)
                );
                
                CREATE TABLE IF NOT EXISTS shepard_citations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    citing_case TEXT NOT NULL,
                    cited_case TEXT NOT NULL,
                    treatment TEXT NOT NULL,
                    date TEXT NOT NULL,
                    precedent_strength REAL NOT NULL
                );
            """)
            
            # Insert default topics
            conn.execute("""
                INSERT OR IGNORE INTO legal_topics (name, description) VALUES
                ('Civil Rights', 'Constitutional and statutory civil rights'),
                ('Criminal Procedure', 'Criminal law procedures and rights'),
                ('Constitutional Law', 'Constitutional interpretation and application'),
                ('Contract Law', 'Contract formation and enforcement'),
                ('Tort Law', 'Civil wrongs and remedies'),
                ('Property Law', 'Real and personal property rights'),
                ('Administrative Law', 'Government agency authority and procedures')
            """)
    
    def _load_existing_data(self):
        """Load existing data for RAG processing."""
        statements = self.get_all_statements()
        if statements:
            self.rag_processor.index_statements(statements)
    
    def convert_document(self, text: str, case_id: str = None, topic_name: str = None) -> List[DeonticStatement]:
        """Convert a legal document to deontic logic statements."""
        # Get topic ID
        topic_id = 1  # Default
        if topic_name:
            topic_id = self._get_or_create_topic(topic_name)
        
        context = {'case_id': case_id, 'topic_id': topic_id}
        statements = self.converter.convert_to_deontic_logic(text, context)
        
        # Store statements
        for stmt in statements:
            stmt.id = self._store_statement(stmt)
        
        # Update RAG index
        self._load_existing_data()
        
        # Check for conflicts
        self._detect_and_store_conflicts(statements)
        
        return statements
    
    def _get_or_create_topic(self, topic_name: str) -> int:
        """Get or create a legal topic."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT id FROM legal_topics WHERE name = ?", (topic_name,))
            result = cursor.fetchone()
            
            if result:
                return result[0]
            else:
                cursor = conn.execute("INSERT INTO legal_topics (name) VALUES (?)", (topic_name,))
                return cursor.lastrowid
    
    def _store_statement(self, stmt: DeonticStatement) -> int:
        """Store a deontic statement in the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO deontic_statements 
                (logic_expression, natural_language, confidence, topic_id, case_id, timestamp, modality)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (stmt.logic_expression, stmt.natural_language, stmt.confidence, 
                  stmt.topic_id, stmt.case_id, stmt.timestamp.isoformat(), stmt.modality))
            return cursor.lastrowid
    
    def _detect_and_store_conflicts(self, new_statements: List[DeonticStatement]):
        """Detect and store conflicts with existing statements."""
        all_statements = self.get_all_statements()
        conflicts = self.conflict_detector.detect_conflicts(all_statements)
        
        with sqlite3.connect(self.db_path) as conn:
            for conflict in conflicts:
                conn.execute("""
                    INSERT OR IGNORE INTO conflict_analysis 
                    (statement_a, statement_b, conflict_type, severity, description, suggested_resolution)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (conflict.statement_a_id, conflict.statement_b_id, conflict.conflict_type,
                      conflict.severity, conflict.description, conflict.suggested_resolution))
    
    def get_all_statements(self) -> List[DeonticStatement]:
        """Get all deontic statements from the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, logic_expression, natural_language, confidence, 
                       topic_id, case_id, timestamp, modality
                FROM deontic_statements
            """)
            
            statements = []
            for row in cursor.fetchall():
                stmt = DeonticStatement(
                    id=row[0],
                    logic_expression=row[1],
                    natural_language=row[2],
                    confidence=row[3],
                    topic_id=row[4],
                    case_id=row[5],
                    timestamp=datetime.fromisoformat(row[6]),
                    modality=row[7]
                )
                statements.append(stmt)
            
            return statements
    
    def query_related_principles(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Query for related legal principles using RAG."""
        results = self.rag_processor.query_related_statements(query, top_k)
        
        return [{
            'statement': {
                'id': stmt.id,
                'logic_expression': stmt.logic_expression,
                'natural_language': stmt.natural_language,
                'confidence': stmt.confidence,
                'modality': stmt.modality,
                'case_id': stmt.case_id
            },
            'similarity': float(similarity)
        } for stmt, similarity in results]
    
    def lint_document(self, text: str, case_id: str = None) -> Dict[str, Any]:
        """Lint a document for logical conflicts."""
        # Convert document temporarily
        temp_statements = self.converter.convert_to_deontic_logic(text, {'case_id': case_id})
        
        # Check against existing statements
        existing_statements = self.get_all_statements()
        all_statements = existing_statements + temp_statements
        
        conflicts = self.conflict_detector.detect_conflicts(all_statements)
        
        # Filter for conflicts involving new statements
        relevant_conflicts = [
            c for c in conflicts 
            if any(stmt.natural_language == c.description for stmt in temp_statements)
        ]
        
        return {
            'conflicts_found': len(relevant_conflicts),
            'conflicts': [{
                'type': c.conflict_type,
                'severity': c.severity,
                'description': c.description,
                'resolution': c.suggested_resolution
            } for c in relevant_conflicts],
            'statements_analyzed': len(temp_statements)
        }
    
    def validate_case(self, case_id: str) -> Dict[str, Any]:
        """Validate case law status using shepherding."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT citing_case, cited_case, treatment, date, precedent_strength
                FROM shepard_citations
            """)
            
            citations = []
            for row in cursor.fetchall():
                citation = ShepherdCitation(
                    id=None,
                    citing_case=row[0],
                    cited_case=row[1],
                    treatment=row[2],
                    date=datetime.fromisoformat(row[3]),
                    precedent_strength=row[4]
                )
                citations.append(citation)
        
        return self.shepherding_engine.validate_case_status(case_id, citations)
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with sqlite3.connect(self.db_path) as conn:
            stats = {}
            
            # Count statements by modality
            cursor = conn.execute("""
                SELECT modality, COUNT(*) 
                FROM deontic_statements 
                GROUP BY modality
            """)
            stats['statements_by_modality'] = dict(cursor.fetchall())
            
            # Count conflicts by severity
            cursor = conn.execute("""
                SELECT severity, COUNT(*) 
                FROM conflict_analysis 
                WHERE resolved = FALSE
                GROUP BY severity
            """)
            stats['unresolved_conflicts'] = dict(cursor.fetchall())
            
            # Total counts
            cursor = conn.execute("SELECT COUNT(*) FROM deontic_statements")
            stats['total_statements'] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM legal_topics")
            stats['total_topics'] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM shepard_citations")
            stats['total_citations'] = cursor.fetchone()[0]
            
            return stats
    
    def add_citation(self, citing_case_id: str, cited_case_id: str, 
                    treatment: TreatmentType, quote_text: str = None):
        """Add a citation relationship between cases."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO shepard_citations 
                (citing_case, cited_case, treatment, date, precedent_strength)
                VALUES (?, ?, ?, ?, ?)
            """, (citing_case_id, cited_case_id, treatment.value, 
                  datetime.now().isoformat(), 0.8))  # Default strength
    
    def get_precedent_lineage(self, case_id: str) -> Dict[str, Any]:
        """Get the complete precedent lineage for a case."""
        with sqlite3.connect(self.db_path) as conn:
            # Get cases this case cites
            cursor = conn.execute("""
                SELECT cited_case, treatment, precedent_strength
                FROM shepard_citations
                WHERE citing_case = ?
            """, (case_id,))
            
            precedents_relied_on = []
            for row in cursor.fetchall():
                precedents_relied_on.append({
                    'case_id': row[0],
                    'treatment': row[1],
                    'strength': row[2]
                })
            
            # Get cases that cite this case
            cursor = conn.execute("""
                SELECT citing_case, treatment, precedent_strength
                FROM shepard_citations
                WHERE cited_case = ?
            """, (case_id,))
            
            subsequent_cases = []
            for row in cursor.fetchall():
                subsequent_cases.append({
                    'case_id': row[0],
                    'treatment': row[1],
                    'strength': row[2]
                })
            
            return {
                'case_id': case_id,
                'precedents_relied_on': precedents_relied_on,
                'subsequent_cases': subsequent_cases
            }

# Example usage and testing
if __name__ == "__main__":
    # Initialize database
    db = DeonticLogicDatabase()
    
    # Example legal text
    legal_text = """
    All persons born or naturalized in the United States are citizens. 
    States cannot deny any person within their jurisdiction the equal protection of the laws.
    The right of citizens to vote shall not be denied or abridged by any State on account of race.
    Schools must provide equal educational opportunities to all students.
    """
    
    # Convert document
    print("Converting legal document to deontic logic...")
    statements = db.convert_document(legal_text, case_id="test_case_001", topic_name="Civil Rights")
    
    for stmt in statements:
        print(f"Logic: {stmt.logic_expression}")
        print(f"Natural: {stmt.natural_language}")
        print(f"Confidence: {stmt.confidence:.2f}")
        print("---")
    
    # Query related principles
    print("\nQuerying related principles...")
    results = db.query_related_principles("equal protection voting rights")
    
    for result in results:
        print(f"Similarity: {result['similarity']:.2f}")
        print(f"Logic: {result['statement']['logic_expression']}")
        print("---")
    
    # Get database statistics
    print("\nDatabase Statistics:")
    stats = db.get_database_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")