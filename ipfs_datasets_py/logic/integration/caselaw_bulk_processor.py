"""
Bulk Caselaw Processor for Temporal Deontic Logic RAG System

This module implements bulk processing of entire caselaw databases to construct
a unified temporal deontic logic system from all available legal precedents.
"""

import logging
import anyio
import json
import re
import os
from typing import Dict, List, Optional, Any, Tuple, Set, Union, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import concurrent.futures
from collections import defaultdict

from .deontic_logic_core import (
    DeonticFormula, DeonticOperator, DeonticRuleSet, TemporalCondition, 
    TemporalOperator, LegalAgent, LegalContext
)
from .temporal_deontic_rag_store import TemporalDeonticRAGStore, TheoremMetadata
from .document_consistency_checker import DocumentConsistencyChecker
from .deontic_logic_converter import DeonticLogicConverter, ConversionContext

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CaselawDocument:
    """Represents a single caselaw document for processing."""
    document_id: str
    title: str
    text: str
    date: datetime
    jurisdiction: str
    court: str
    citation: str
    legal_domains: List[str] = field(default_factory=list)
    precedent_strength: float = 1.0
    file_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessingStats:
    """Statistics for bulk processing."""
    total_documents: int = 0
    processed_documents: int = 0
    extracted_theorems: int = 0
    processing_errors: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    jurisdictions_processed: Set[str] = field(default_factory=set)
    legal_domains_processed: Set[str] = field(default_factory=set)
    temporal_range: Tuple[Optional[datetime], Optional[datetime]] = (None, None)
    
    @property
    def processing_time(self) -> timedelta:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return timedelta(0)
    
    @property
    def success_rate(self) -> float:
        if self.total_documents == 0:
            return 0.0
        return (self.processed_documents - self.processing_errors) / self.total_documents


@dataclass
class BulkProcessingConfig:
    """Configuration for bulk caselaw processing."""
    # Input configuration
    caselaw_directories: List[str] = field(default_factory=list)
    file_patterns: List[str] = field(default_factory=lambda: ["*.txt", "*.pdf", "*.json"])
    supported_formats: List[str] = field(default_factory=lambda: ["txt", "json", "xml", "pdf"])
    
    # Processing configuration
    max_concurrent_documents: int = 5
    chunk_size: int = 100
    enable_parallel_processing: bool = True
    timeout_per_document: int = 300  # seconds
    
    # Filtering configuration
    min_document_length: int = 100
    min_precedent_strength: float = 0.5
    date_range: Tuple[Optional[datetime], Optional[datetime]] = (None, None)
    jurisdictions_filter: Optional[List[str]] = None
    legal_domains_filter: Optional[List[str]] = None
    
    # Output configuration
    output_directory: str = "unified_deontic_logic_system"
    save_intermediate_results: bool = True
    create_backups: bool = True
    
    # Quality control
    enable_duplicate_detection: bool = True
    enable_consistency_validation: bool = True
    min_theorem_confidence: float = 0.7


class CaselawBulkProcessor:
    """
    Bulk processor for constructing unified deontic logic system from entire caselaw database.
    
    This class processes large volumes of caselaw documents to automatically extract
    temporal deontic logic theorems and build a comprehensive legal knowledge base.
    """
    
    def __init__(self, 
                 config: BulkProcessingConfig,
                 rag_store: Optional[TemporalDeonticRAGStore] = None,
                 logic_converter: Optional[DeonticLogicConverter] = None):
        """
        Initialize the bulk processor.
        
        Args:
            config: Configuration for bulk processing
            rag_store: Optional RAG store (will create if not provided)
            logic_converter: Optional logic converter (will create if not provided)
        """
        self.config = config
        self.rag_store = rag_store or TemporalDeonticRAGStore()
        self.logic_converter = logic_converter
        self.stats = ProcessingStats()
        
        # Document cache and processing state
        self.document_cache: Dict[str, CaselawDocument] = {}
        self.processing_queue: List[CaselawDocument] = []
        self.processed_theorems: Dict[str, TheoremMetadata] = {}
        self.error_log: List[Dict[str, Any]] = []
        
        # Create output directory
        os.makedirs(self.config.output_directory, exist_ok=True)
        
        logger.info(f"Initialized CaselawBulkProcessor with config: {len(config.caselaw_directories)} directories")
    
    async def process_caselaw_corpus(self) -> ProcessingStats:
        """
        Process the entire caselaw corpus to build unified deontic logic system.
        
        Returns:
            ProcessingStats with processing results
        """
        logger.info("Starting bulk caselaw processing for unified deontic logic system")
        self.stats.start_time = datetime.now()
        
        try:
            # Phase 1: Discovery - Find all caselaw documents
            await self._discover_caselaw_documents()
            
            # Phase 2: Preprocessing - Load and validate documents
            await self._preprocess_documents()
            
            # Phase 3: Extraction - Extract deontic logic theorems
            await self._extract_theorems_bulk()
            
            # Phase 4: Unification - Build unified system
            await self._build_unified_system()
            
            # Phase 5: Validation - Validate consistency
            if self.config.enable_consistency_validation:
                await self._validate_unified_system()
            
            # Phase 6: Export - Save results
            await self._export_unified_system()
            
            self.stats.end_time = datetime.now()
            
            logger.info(f"Bulk processing completed: {self.stats.extracted_theorems} theorems from {self.stats.processed_documents} documents")
            return self.stats
            
        except Exception as e:
            logger.error(f"Bulk processing failed: {e}")
            self.stats.end_time = datetime.now()
            raise
    
    async def _discover_caselaw_documents(self) -> None:
        """Discover all caselaw documents in configured directories."""
        logger.info("Phase 1: Discovering caselaw documents...")
        
        discovered_files = []
        
        for directory in self.config.caselaw_directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory not found: {directory}")
                continue
            
            dir_path = Path(directory)
            for pattern in self.config.file_patterns:
                files = list(dir_path.glob(f"**/{pattern}"))
                discovered_files.extend(files)
        
        # Filter by supported formats
        supported_files = [
            f for f in discovered_files 
            if f.suffix.lower()[1:] in self.config.supported_formats
        ]
        
        self.stats.total_documents = len(supported_files)
        logger.info(f"Discovered {len(supported_files)} caselaw documents")
        
        # Load document metadata
        for file_path in supported_files:
            try:
                doc = await self._load_document_metadata(file_path)
                if self._passes_filters(doc):
                    self.processing_queue.append(doc)
            except Exception as e:
                logger.warning(f"Failed to load document {file_path}: {e}")
                self.stats.processing_errors += 1
        
        logger.info(f"Queued {len(self.processing_queue)} documents for processing")
    
    async def _load_document_metadata(self, file_path: Path) -> CaselawDocument:
        """Load document metadata from file."""
        file_content = ""
        
        # Read file based on format
        if file_path.suffix.lower() == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                file_content = data.get('text', data.get('content', ''))
                
                return CaselawDocument(
                    document_id=data.get('id', file_path.stem),
                    title=data.get('title', file_path.name),
                    text=file_content,
                    date=datetime.fromisoformat(data.get('date', '2000-01-01')),
                    jurisdiction=data.get('jurisdiction', 'Unknown'),
                    court=data.get('court', 'Unknown Court'),
                    citation=data.get('citation', ''),
                    legal_domains=data.get('legal_domains', ['general']),
                    precedent_strength=data.get('precedent_strength', 1.0),
                    file_path=str(file_path),
                    metadata=data.get('metadata', {})
                )
        
        elif file_path.suffix.lower() == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
        
        # For other formats, create basic document
        doc_id = file_path.stem
        date = self._extract_date_from_filename(file_path.name) or datetime(2000, 1, 1)
        jurisdiction = self._extract_jurisdiction_from_path(str(file_path))
        
        return CaselawDocument(
            document_id=doc_id,
            title=file_path.name,
            text=file_content,
            date=date,
            jurisdiction=jurisdiction,
            court="Unknown Court",
            citation="",
            legal_domains=['general'],
            file_path=str(file_path)
        )
    
    def _passes_filters(self, doc: CaselawDocument) -> bool:
        """Check if document passes configured filters."""
        # Length filter
        if len(doc.text) < self.config.min_document_length:
            return False
        
        # Date range filter
        if self.config.date_range[0] and doc.date < self.config.date_range[0]:
            return False
        if self.config.date_range[1] and doc.date > self.config.date_range[1]:
            return False
        
        # Jurisdiction filter
        if (self.config.jurisdictions_filter and 
            doc.jurisdiction not in self.config.jurisdictions_filter):
            return False
        
        # Legal domains filter
        if (self.config.legal_domains_filter and 
            not any(domain in self.config.legal_domains_filter for domain in doc.legal_domains)):
            return False
        
        # Precedent strength filter
        if doc.precedent_strength < self.config.min_precedent_strength:
            return False
        
        return True
    
    async def _preprocess_documents(self) -> None:
        """Preprocess documents for extraction."""
        logger.info("Phase 2: Preprocessing documents...")
        
        # Sort documents by date for temporal coherence
        self.processing_queue.sort(key=lambda d: d.date)
        
        # Remove duplicates if enabled
        if self.config.enable_duplicate_detection:
            unique_docs = []
            seen_hashes = set()
            
            for doc in self.processing_queue:
                content_hash = hashlib.md5(doc.text.encode()).hexdigest()
                if content_hash not in seen_hashes:
                    unique_docs.append(doc)
                    seen_hashes.add(content_hash)
            
            removed = len(self.processing_queue) - len(unique_docs)
            if removed > 0:
                logger.info(f"Removed {removed} duplicate documents")
                self.processing_queue = unique_docs
        
        # Cache documents by ID
        for doc in self.processing_queue:
            self.document_cache[doc.document_id] = doc
        
        logger.info(f"Preprocessed {len(self.processing_queue)} documents")
    
    async def _extract_theorems_bulk(self) -> None:
        """Extract deontic logic theorems from all documents."""
        logger.info("Phase 3: Extracting deontic logic theorems...")
        
        if self.config.enable_parallel_processing:
            await self._extract_theorems_parallel()
        else:
            await self._extract_theorems_sequential()
        
        logger.info(f"Extracted {self.stats.extracted_theorems} theorems from {self.stats.processed_documents} documents")
    
    async def _extract_theorems_parallel(self) -> None:
        """Extract theorems using parallel processing."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.max_concurrent_documents) as executor:
            # Process documents in chunks
            for i in range(0, len(self.processing_queue), self.config.chunk_size):
                chunk = self.processing_queue[i:i + self.config.chunk_size]
                
                # Submit chunk for processing
                futures = [
                    executor.submit(self._process_single_document, doc)
                    for doc in chunk
                ]
                
                # Collect results
                for future in concurrent.futures.as_completed(futures, timeout=self.config.timeout_per_document):
                    try:
                        theorems = future.result()
                        if theorems:
                            for theorem in theorems:
                                self._add_theorem_to_store(theorem)
                    except Exception as e:
                        logger.error(f"Document processing failed: {e}")
                        self.stats.processing_errors += 1
                
                logger.info(f"Processed chunk {i//self.config.chunk_size + 1}/{(len(self.processing_queue) + self.config.chunk_size - 1)//self.config.chunk_size}")
    
    async def _extract_theorems_sequential(self) -> None:
        """Extract theorems using sequential processing."""
        for i, doc in enumerate(self.processing_queue):
            try:
                theorems = self._process_single_document(doc)
                if theorems:
                    for theorem in theorems:
                        self._add_theorem_to_store(theorem)
                
                if (i + 1) % 10 == 0:
                    logger.info(f"Processed {i + 1}/{len(self.processing_queue)} documents")
                    
            except Exception as e:
                logger.error(f"Failed to process document {doc.document_id}: {e}")
                self.stats.processing_errors += 1
    
    def _process_single_document(self, doc: CaselawDocument) -> List[DeonticFormula]:
        """Process a single document to extract deontic logic theorems."""
        try:
            # Use advanced logic converter if available
            if self.logic_converter:
                context = ConversionContext(
                    source_document_path=doc.file_path or "",
                    document_title=doc.title,
                    enable_temporal_analysis=True,
                    target_jurisdiction=doc.jurisdiction,
                    legal_domain=doc.legal_domains[0] if doc.legal_domains else "general"
                )
                
                # Create mock knowledge graph from document
                mock_kg = self._create_knowledge_graph_from_document(doc)
                result = self.logic_converter.convert_knowledge_graph_to_logic(mock_kg, context)
                
                if result.success:
                    self.stats.processed_documents += 1
                    return result.formulas
            
            # Fallback to pattern-based extraction
            formulas = self._extract_formulas_pattern_matching(doc)
            if formulas:
                self.stats.processed_documents += 1
            
            return formulas
            
        except Exception as e:
            logger.error(f"Error processing document {doc.document_id}: {e}")
            return []
    
    def _extract_formulas_pattern_matching(self, doc: CaselawDocument) -> List[DeonticFormula]:
        """Extract formulas using enhanced pattern matching."""
        formulas = []
        text = doc.text.lower()
        
        # Enhanced patterns for legal language
        obligation_patterns = [
            r'(must|shall|required to|obligated to|duty to|shall be required to)\s+([^.!?]+)',
            r'(is required to|are required to|has a duty to|have a duty to)\s+([^.!?]+)',
            r'(court orders?|court directs?|court requires?)\s+([^.!?]+)',
            r'(defendant must|plaintiff must|party must)\s+([^.!?]+)'
        ]
        
        permission_patterns = [
            r'(may|permitted to|allowed to|can|authorized to)\s+([^.!?]+)',
            r'(has the right to|have the right to|entitled to)\s+([^.!?]+)',
            r'(court allows?|court permits?)\s+([^.!?]+)'
        ]
        
        prohibition_patterns = [
            r'(must not|shall not|prohibited from|forbidden to|cannot)\s+([^.!?]+)',
            r'(may not|not allowed to|not permitted to)\s+([^.!?]+)',
            r'(court prohibits?|court forbids?|court bars?)\s+([^.!?]+)',
            r'(is prohibited from|are prohibited from)\s+([^.!?]+)'
        ]
        
        # Extract obligations
        for pattern in obligation_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                proposition = match.group(2).strip()
                if len(proposition) > 10 and self._is_legal_proposition(proposition):
                    agent = self._extract_agent_from_context(match.group(0), doc)
                    formula = DeonticFormula(
                        operator=DeonticOperator.OBLIGATION,
                        proposition=proposition,
                        agent=agent,
                        confidence=0.8,
                        source_text=match.group(0)
                    )
                    formulas.append(formula)
        
        # Extract permissions
        for pattern in permission_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                proposition = match.group(2).strip()
                if len(proposition) > 10 and self._is_legal_proposition(proposition):
                    agent = self._extract_agent_from_context(match.group(0), doc)
                    formula = DeonticFormula(
                        operator=DeonticOperator.PERMISSION,
                        proposition=proposition,
                        agent=agent,
                        confidence=0.8,
                        source_text=match.group(0)
                    )
                    formulas.append(formula)
        
        # Extract prohibitions
        for pattern in prohibition_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                proposition = match.group(2).strip()
                if len(proposition) > 10 and self._is_legal_proposition(proposition):
                    agent = self._extract_agent_from_context(match.group(0), doc)
                    formula = DeonticFormula(
                        operator=DeonticOperator.PROHIBITION,
                        proposition=proposition,
                        agent=agent,
                        confidence=0.8,
                        source_text=match.group(0)
                    )
                    formulas.append(formula)
        
        # Filter by confidence threshold
        return [f for f in formulas if f.confidence >= self.config.min_theorem_confidence]
    
    def _is_legal_proposition(self, proposition: str) -> bool:
        """Check if a proposition appears to be a legal statement."""
        # Filter out obviously non-legal content
        non_legal_indicators = [
            'said', 'says', 'went', 'came', 'looked', 'seemed',
            'hello', 'goodbye', 'thank', 'please', 'sorry'
        ]
        
        prop_lower = proposition.lower()
        return not any(indicator in prop_lower for indicator in non_legal_indicators)
    
    def _extract_agent_from_context(self, context: str, doc: CaselawDocument) -> LegalAgent:
        """Extract legal agent from context."""
        context_lower = context.lower()
        
        # Common legal agent patterns
        if any(word in context_lower for word in ['defendant', 'accused']):
            return LegalAgent("defendant", "Defendant", "person")
        elif any(word in context_lower for word in ['plaintiff', 'complainant']):
            return LegalAgent("plaintiff", "Plaintiff", "person")
        elif any(word in context_lower for word in ['court', 'judge']):
            return LegalAgent("court", "Court", "institution")
        elif any(word in context_lower for word in ['company', 'corporation', 'business']):
            return LegalAgent("corporation", "Corporation", "organization")
        elif any(word in context_lower for word in ['employee', 'worker']):
            return LegalAgent("employee", "Employee", "person")
        elif any(word in context_lower for word in ['employer', 'company']):
            return LegalAgent("employer", "Employer", "organization")
        else:
            return LegalAgent("party", "Legal Party", "person")
    
    def _add_theorem_to_store(self, formula: DeonticFormula) -> None:
        """Add a theorem to the RAG store."""
        # Find the source document
        source_doc = None
        for doc in self.document_cache.values():
            if formula.source_text and formula.source_text in doc.text:
                source_doc = doc
                break
        
        if not source_doc:
            # Use a default document if source not found
            source_doc = CaselawDocument(
                document_id="unknown",
                title="Unknown Case",
                text="",
                date=datetime.now(),
                jurisdiction="Unknown",
                court="Unknown Court",
                citation=""
            )
        
        # Add to RAG store with document metadata
        theorem_id = self.rag_store.add_theorem(
            formula=formula,
            temporal_scope=(source_doc.date, None),
            jurisdiction=source_doc.jurisdiction,
            legal_domain=source_doc.legal_domains[0] if source_doc.legal_domains else "general",
            source_case=f"{source_doc.title} ({source_doc.date.year})",
            precedent_strength=source_doc.precedent_strength
        )
        
        self.stats.extracted_theorems += 1
        self.stats.jurisdictions_processed.add(source_doc.jurisdiction)
        if source_doc.legal_domains:
            self.stats.legal_domains_processed.update(source_doc.legal_domains)
        
        # Update temporal range
        if self.stats.temporal_range[0] is None or source_doc.date < self.stats.temporal_range[0]:
            self.stats.temporal_range = (source_doc.date, self.stats.temporal_range[1])
        if self.stats.temporal_range[1] is None or source_doc.date > self.stats.temporal_range[1]:
            self.stats.temporal_range = (self.stats.temporal_range[0], source_doc.date)
    
    async def _build_unified_system(self) -> None:
        """Build the unified deontic logic system."""
        logger.info("Phase 4: Building unified deontic logic system...")
        
        # Create unified rule set
        all_formulas = [theorem.formula for theorem in self.rag_store.theorems.values()]
        
        unified_rule_set = DeonticRuleSet(
            name="Unified Caselaw Deontic Logic System",
            formulas=all_formulas,
            description=f"Unified system built from {len(all_formulas)} theorems across {len(self.stats.jurisdictions_processed)} jurisdictions",
            creation_date=datetime.now(),
            source_documents=list(self.document_cache.keys()),
            legal_domains=list(self.stats.legal_domains_processed),
            temporal_coverage=self.stats.temporal_range
        )
        
        # Save unified system
        if self.config.save_intermediate_results:
            output_file = os.path.join(self.config.output_directory, "unified_rule_set.json")
            with open(output_file, 'w') as f:
                json.dump(unified_rule_set.to_dict(), f, indent=2, default=str)
        
        logger.info(f"Built unified system with {len(all_formulas)} theorems")
    
    async def _validate_unified_system(self) -> None:
        """Validate the unified deontic logic system for consistency."""
        logger.info("Phase 5: Validating unified system consistency...")
        
        # Use document consistency checker to find conflicts
        checker = DocumentConsistencyChecker(rag_store=self.rag_store)
        
        # Sample documents from different jurisdictions for validation
        validation_conflicts = []
        sample_size = min(100, len(self.processing_queue))
        
        for doc in self.processing_queue[:sample_size]:
            try:
                analysis = checker.check_document(
                    document_text=doc.text[:5000],  # First 5000 chars
                    document_id=doc.document_id,
                    temporal_context=doc.date,
                    jurisdiction=doc.jurisdiction,
                    legal_domain=doc.legal_domains[0] if doc.legal_domains else "general"
                )
                
                if analysis.consistency_result and not analysis.consistency_result.is_consistent:
                    validation_conflicts.extend(analysis.consistency_result.conflicts)
            
            except Exception as e:
                logger.warning(f"Validation failed for document {doc.document_id}: {e}")
        
        logger.info(f"Validation completed: {len(validation_conflicts)} conflicts found in sample")
        
        # Save validation report
        if self.config.save_intermediate_results:
            validation_report = {
                "total_conflicts": len(validation_conflicts),
                "sample_size": sample_size,
                "conflicts": validation_conflicts[:10],  # First 10 conflicts
                "validation_date": datetime.now().isoformat()
            }
            
            output_file = os.path.join(self.config.output_directory, "validation_report.json")
            with open(output_file, 'w') as f:
                json.dump(validation_report, f, indent=2, default=str)
    
    async def _export_unified_system(self) -> None:
        """Export the unified deontic logic system."""
        logger.info("Phase 6: Exporting unified system...")
        
        # Export statistics
        stats_dict = {
            "total_documents": self.stats.total_documents,
            "processed_documents": self.stats.processed_documents,
            "extracted_theorems": self.stats.extracted_theorems,
            "processing_errors": self.stats.processing_errors,
            "success_rate": self.stats.success_rate,
            "processing_time": str(self.stats.processing_time),
            "jurisdictions_processed": list(self.stats.jurisdictions_processed),
            "legal_domains_processed": list(self.stats.legal_domains_processed),
            "temporal_range": [
                self.stats.temporal_range[0].isoformat() if self.stats.temporal_range[0] else None,
                self.stats.temporal_range[1].isoformat() if self.stats.temporal_range[1] else None
            ]
        }
        
        stats_file = os.path.join(self.config.output_directory, "processing_stats.json")
        with open(stats_file, 'w') as f:
            json.dump(stats_dict, f, indent=2)
        
        # Export RAG store
        rag_export = {
            "theorems": {
                tid: {
                    "formula": {
                        "operator": t.formula.operator.name,
                        "proposition": t.formula.proposition,
                        "agent": t.formula.agent.name if t.formula.agent else None,
                        "confidence": t.formula.confidence
                    },
                    "jurisdiction": t.jurisdiction,
                    "legal_domain": t.legal_domain,
                    "source_case": t.source_case,
                    "precedent_strength": t.precedent_strength,
                    "temporal_scope": [
                        t.temporal_scope[0].isoformat() if t.temporal_scope[0] else None,
                        t.temporal_scope[1].isoformat() if t.temporal_scope[1] else None
                    ]
                }
                for tid, t in self.rag_store.theorems.items()
            },
            "export_date": datetime.now().isoformat(),
            "total_theorems": len(self.rag_store.theorems)
        }
        
        rag_file = os.path.join(self.config.output_directory, "unified_rag_store.json")
        with open(rag_file, 'w') as f:
            json.dump(rag_export, f, indent=2)
        
        logger.info(f"Exported unified system to {self.config.output_directory}")
    
    def _extract_date_from_filename(self, filename: str) -> Optional[datetime]:
        """Extract date from filename if possible."""
        # Common date patterns in legal filenames
        date_patterns = [
            r'(\d{4})[-_](\d{1,2})[-_](\d{1,2})',  # YYYY-MM-DD
            r'(\d{1,2})[-_](\d{1,2})[-_](\d{4})',   # MM-DD-YYYY
            r'(\d{4})',                              # Just year
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, filename)
            if match:
                try:
                    if len(match.groups()) == 3:
                        if len(match.group(1)) == 4:  # YYYY-MM-DD
                            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                        else:  # MM-DD-YYYY
                            return datetime(int(match.group(3)), int(match.group(1)), int(match.group(2)))
                    elif len(match.groups()) == 1:  # Just year
                        return datetime(int(match.group(1)), 1, 1)
                except ValueError:
                    continue
        
        return None
    
    def _extract_jurisdiction_from_path(self, file_path: str) -> str:
        """Extract jurisdiction from file path."""
        path_lower = file_path.lower()
        
        # Common jurisdiction indicators
        if 'federal' in path_lower or 'supreme' in path_lower:
            return 'Federal'
        elif any(state in path_lower for state in ['california', 'texas', 'new_york', 'florida']):
            return 'State'
        elif 'international' in path_lower:
            return 'International'
        else:
            return 'Unknown'
    
    def _create_knowledge_graph_from_document(self, doc: CaselawDocument):
        """Create a mock knowledge graph from document for logic converter."""
        # This is a simplified implementation
        # In production, would use actual GraphRAG processing
        class MockEntity:
            def __init__(self, entity_id: str, name: str, entity_type: str = "legal_entity"):
                self.entity_id = entity_id
                self.name = name
                self.entity_type = entity_type
                self.properties = {"text": doc.text[:1000]}
                self.confidence = 1.0
                self.source_text = doc.text
        
        class MockKnowledgeGraph:
            def __init__(self):
                self.entities = [MockEntity(f"{doc.document_id}_entity", doc.title, "legal_document")]
                self.relationships = []
        
        return MockKnowledgeGraph()


# Factory functions for easy use
def create_bulk_processor(
    caselaw_directories: List[str],
    output_directory: str = "unified_deontic_logic_system",
    max_concurrent: int = 5,
    enable_parallel: bool = True
) -> CaselawBulkProcessor:
    """Create a bulk processor with common configuration."""
    config = BulkProcessingConfig(
        caselaw_directories=caselaw_directories,
        output_directory=output_directory,
        max_concurrent_documents=max_concurrent,
        enable_parallel_processing=enable_parallel
    )
    
    return CaselawBulkProcessor(config)


async def process_caselaw_bulk(
    caselaw_directories: List[str],
    output_directory: str = "unified_deontic_logic_system"
) -> ProcessingStats:
    """Convenience function for bulk processing."""
    processor = create_bulk_processor(caselaw_directories, output_directory)
    return await processor.process_caselaw_corpus()