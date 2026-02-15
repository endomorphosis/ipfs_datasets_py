"""
Debugging Tools for Processors

Provides utilities for debugging processor behavior:
- Explain routing decisions
- Detailed diagnostics
- Processor trace logging
- Context inspection
"""

import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
import time

from .core.protocol import ProcessingContext, ProcessingResult, InputType
from .core.input_detector import InputDetector
from .core.processor_registry import get_global_registry


@dataclass
class RoutingDecision:
    """Information about a routing decision."""
    input_source: str
    input_type: InputType
    detected_format: Optional[str]
    total_processors: int
    matching_processors: List[Dict[str, Any]]
    selected_processor: Optional[str]
    selection_reason: str
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['input_type'] = self.input_type.value
        return data
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class ProcessorDebugger:
    """Debugging utilities for processors."""
    
    def __init__(self):
        """Initialize debugger."""
        self.detector = InputDetector()
        self.registry = get_global_registry()
        self.logger = logging.getLogger(__name__)
    
    async def explain_routing(self, input_source: str) -> RoutingDecision:
        """
        Explain why a particular processor was selected for an input.
        
        Args:
            input_source: Input to analyze
            
        Returns:
            RoutingDecision with detailed information
            
        Example:
            ```python
            import anyio
            from ipfs_datasets_py.processors.debug_tools import ProcessorDebugger
            
            debugger = ProcessorDebugger()
            
            async def debug():
                decision = await debugger.explain_routing("document.pdf")
                print(decision.to_json())
            
            anyio.run(debug)
            ```
        """
        # Detect input
        input_info = self.detector.detect_input(input_source)
        
        # Create context
        context = ProcessingContext(
            input_type=input_info.input_type,
            source=input_info.source,
            metadata=input_info.metadata
        )
        
        # Get total processors
        total_processors = len(self.registry._processors)
        
        # Find matching processors
        matching = await self.registry.get_processors(context)
        
        # Build matching processor info
        matching_info = []
        for proc in matching:
            entry = next((e for e in self.registry._processors if e.processor == proc), None)
            if entry:
                matching_info.append({
                    'name': entry.name,
                    'priority': entry.priority,
                    'enabled': entry.enabled,
                    'metadata': entry.metadata or {}
                })
        
        # Determine selection
        if matching_info:
            selected = matching_info[0]['name']  # Highest priority
            reason = f"Selected '{selected}' (priority {matching_info[0]['priority']}) as highest priority matching processor"
        else:
            selected = None
            reason = "No matching processors found for this input"
        
        return RoutingDecision(
            input_source=input_source,
            input_type=input_info.input_type,
            detected_format=input_info.metadata.get('format'),
            total_processors=total_processors,
            matching_processors=matching_info,
            selected_processor=selected,
            selection_reason=reason,
            timestamp=time.time()
        )
    
    def diagnose_context(self, context: ProcessingContext) -> Dict[str, Any]:
        """
        Provide detailed diagnostics for a processing context.
        
        Args:
            context: Processing context to diagnose
            
        Returns:
            Dictionary with diagnostic information
            
        Example:
            ```python
            from ipfs_datasets_py.processors.core import ProcessingContext, InputType
            from ipfs_datasets_py.processors.debug_tools import ProcessorDebugger
            
            context = ProcessingContext(
                input_type=InputType.FILE,
                source="document.pdf",
                metadata={'format': 'pdf'}
            )
            
            debugger = ProcessorDebugger()
            diagnostics = debugger.diagnose_context(context)
            print(json.dumps(diagnostics, indent=2))
            ```
        """
        return {
            'input_type': context.input_type.value,
            'source': context.source,
            'metadata': context.metadata,
            'is_url': context.is_url(),
            'is_file': context.is_file(),
            'is_folder': context.is_folder(),
            'format': context.get_format(),
            'mime_type': context.get_mime_type(),
            'helpers_available': [
                'is_url()', 'is_file()', 'is_folder()',
                'get_format()', 'get_mime_type()'
            ]
        }
    
    def diagnose_result(self, result: ProcessingResult) -> Dict[str, Any]:
        """
        Provide detailed diagnostics for a processing result.
        
        Args:
            result: Processing result to diagnose
            
        Returns:
            Dictionary with diagnostic information
        """
        kg = result.knowledge_graph or {}
        
        return {
            'success': result.success,
            'has_knowledge_graph': result.has_knowledge_graph(),
            'has_vectors': result.has_vectors(),
            'entity_count': result.get_entity_count(),
            'relationship_count': len(kg.get('relationships', [])),
            'vector_count': len(result.vectors or []),
            'error_count': len(result.errors),
            'warning_count': len(result.warnings),
            'errors': result.errors,
            'warnings': result.warnings,
            'metadata_keys': list(result.metadata.keys()) if result.metadata else []
        }
    
    def get_processor_capabilities(self, processor_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed capabilities of a specific processor.
        
        Args:
            processor_name: Name of processor
            
        Returns:
            Dictionary with capabilities or None if not found
        """
        entry = next((e for e in self.registry._processors if e.name == processor_name), None)
        
        if not entry:
            return None
        
        # Try to get capabilities from processor
        try:
            caps = entry.processor.get_capabilities()
            return {
                'name': entry.name,
                'priority': entry.priority,
                'enabled': entry.enabled,
                'capabilities': caps,
                'metadata': entry.metadata or {}
            }
        except Exception as e:
            return {
                'name': entry.name,
                'priority': entry.priority,
                'enabled': entry.enabled,
                'error': f"Failed to get capabilities: {str(e)}",
                'metadata': entry.metadata or {}
            }
    
    def trace_processing(self, enable: bool = True) -> None:
        """
        Enable or disable detailed trace logging for processing.
        
        Args:
            enable: Whether to enable trace logging
        """
        if enable:
            logging.basicConfig(
                level=logging.DEBUG,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            self.logger.info("Trace logging enabled")
        else:
            logging.basicConfig(level=logging.INFO)
            self.logger.info("Trace logging disabled")


def explain_routing(input_source: str) -> str:
    """
    Convenience function to explain routing for an input.
    
    Args:
        input_source: Input to analyze
        
    Returns:
        JSON string with routing explanation
        
    Example:
        ```python
        import anyio
        from ipfs_datasets_py.processors.debug_tools import explain_routing
        
        async def main():
            explanation = await explain_routing("document.pdf")
            print(explanation)
        
        anyio.run(main)
        ```
    """
    import anyio
    
    async def _explain():
        debugger = ProcessorDebugger()
        decision = await debugger.explain_routing(input_source)
        return decision.to_json()
    
    return anyio.run(_explain)


__all__ = [
    'ProcessorDebugger',
    'RoutingDecision',
    'explain_routing',
]
