"""
MCP Tools for Deontic Logic Operations

This module provides MCP tool implementations for deontic logic conversion,
database operations, and analysis.
"""

import logging
from typing import Dict, List, Any, Optional
from ...deontic_logic import DeonticLogicConverter, DeonticLogicDatabase, DeonticLogicAnalyzer

logger = logging.getLogger(__name__)

class DeonticLogicTools:
    """MCP tools for deontic logic operations"""
    
    def __init__(self):
        self.converter = DeonticLogicConverter()
        self.database = DeonticLogicDatabase()
        self.analyzer = DeonticLogicAnalyzer(self.database)
    
    async def convert_text_to_logic(self, text: str, case_id: Optional[str] = None) -> Dict[str, Any]:
        """Convert legal text to deontic logic statements"""
        try:
            statements = self.converter.convert_text(text)
            
            # Store statements in database
            stored_statements = []
            for stmt in statements:
                stmt_id = self.database.store_statement(stmt, case_id=case_id)
                stored_statements.append({
                    'id': stmt_id,
                    'logic_expression': stmt.logic_expression,
                    'natural_language': stmt.natural_language,
                    'confidence': stmt.confidence,
                    'modality': stmt.modality.value
                })
            
            return {
                'success': True,
                'statements': stored_statements,
                'count': len(stored_statements)
            }
        except Exception as e:
            logger.error(f"Error converting text to logic: {e}")
            return {
                'success': False,
                'error': str(e),
                'statements': [],
                'count': 0
            }
    
    async def search_statements(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search deontic logic statements"""
        try:
            statements = self.database.search_statements(query, limit)
            return {
                'success': True,
                'statements': statements,
                'count': len(statements)
            }
        except Exception as e:
            logger.error(f"Error searching statements: {e}")
            return {
                'success': False,
                'error': str(e),
                'statements': [],
                'count': 0
            }
    
    async def get_database_statistics(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            stats = self.database.get_statistics()
            return {
                'success': True,
                'statistics': stats
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                'success': False,
                'error': str(e),
                'statistics': {}
            }
    
    async def detect_conflicts(self) -> Dict[str, Any]:
        """Detect logical conflicts in database"""
        try:
            conflicts = self.analyzer.detect_conflicts()
            return {
                'success': True,
                'conflicts': conflicts,
                'count': len(conflicts)
            }
        except Exception as e:
            logger.error(f"Error detecting conflicts: {e}")
            return {
                'success': False,
                'error': str(e),
                'conflicts': [],
                'count': 0
            }
    
    async def analyze_topic(self, topic_id: int) -> Dict[str, Any]:
        """Analyze a legal topic"""
        try:
            analysis = self.analyzer.analyze_topic_relationships(topic_id)
            return {
                'success': True,
                'analysis': analysis
            }
        except Exception as e:
            logger.error(f"Error analyzing topic: {e}")
            return {
                'success': False,
                'error': str(e),
                'analysis': {}
            }

# Global instance for MCP tool registration
deontic_logic_tools = DeonticLogicTools()

# MCP tool definitions
MCP_TOOLS = {
    "convert_text_to_logic": {
        "name": "convert_text_to_logic",
        "description": "Convert legal text to formal deontic logic statements",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Legal text to convert"},
                "case_id": {"type": "string", "description": "Optional case ID for reference"}
            },
            "required": ["text"]
        },
        "handler": deontic_logic_tools.convert_text_to_logic
    },
    "search_deontic_statements": {
        "name": "search_deontic_statements", 
        "description": "Search deontic logic statements in database",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Maximum results to return", "default": 10}
            },
            "required": ["query"]
        },
        "handler": deontic_logic_tools.search_statements
    },
    "get_deontic_statistics": {
        "name": "get_deontic_statistics",
        "description": "Get database statistics for deontic logic system",
        "parameters": {"type": "object", "properties": {}},
        "handler": deontic_logic_tools.get_database_statistics
    },
    "detect_logical_conflicts": {
        "name": "detect_logical_conflicts",
        "description": "Detect logical conflicts between statements",
        "parameters": {"type": "object", "properties": {}},
        "handler": deontic_logic_tools.detect_conflicts
    },
    "analyze_legal_topic": {
        "name": "analyze_legal_topic",
        "description": "Analyze relationships within a legal topic",
        "parameters": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "ID of legal topic to analyze"}
            },
            "required": ["topic_id"]
        },
        "handler": deontic_logic_tools.analyze_topic
    }
}