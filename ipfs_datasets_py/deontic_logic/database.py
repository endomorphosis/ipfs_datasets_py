"""
Deontic Logic Database Management

This module provides database functionality for storing and querying deontic logic statements.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from .converter import DeonticStatement, ModalityType

class DeonticLogicDatabase:
    """Database for managing deontic logic statements and relationships"""
    
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_database()
    
    def _init_database(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deontic_statements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logic_expression TEXT NOT NULL,
                    natural_language TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    modality TEXT NOT NULL,
                    topic_id INTEGER,
                    case_id TEXT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS legal_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    case_count INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logical_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    statement_a_id INTEGER,
                    statement_b_id INTEGER,
                    relationship_type TEXT,
                    strength REAL,
                    FOREIGN KEY (statement_a_id) REFERENCES deontic_statements (id),
                    FOREIGN KEY (statement_b_id) REFERENCES deontic_statements (id)
                )
            """)
    
    def store_statement(self, statement: DeonticStatement, topic_id: Optional[int] = None, 
                       case_id: Optional[str] = None) -> int:
        """Store a deontic statement in the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO deontic_statements 
                (logic_expression, natural_language, confidence, modality, topic_id, case_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                statement.logic_expression,
                statement.natural_language,
                statement.confidence,
                statement.modality.value,
                topic_id,
                case_id
            ))
            return cursor.lastrowid
    
    def search_statements(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search statements by text content"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM deontic_statements 
                WHERE natural_language LIKE ? OR logic_expression LIKE ?
                ORDER BY confidence DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics"""
        with sqlite3.connect(self.db_path) as conn:
            total_statements = conn.execute("SELECT COUNT(*) FROM deontic_statements").fetchone()[0]
            
            modality_stats = {}
            for modality in ModalityType:
                count = conn.execute(
                    "SELECT COUNT(*) FROM deontic_statements WHERE modality = ?", 
                    (modality.value,)
                ).fetchone()[0]
                modality_stats[modality.value] = count
            
            topic_count = conn.execute("SELECT COUNT(*) FROM legal_topics").fetchone()[0]
            
            return {
                "total_statements": total_statements,
                "modality_distribution": modality_stats,
                "topic_count": topic_count,
                "last_updated": datetime.now().isoformat()
            }