"""
IPLD Logic Storage Module

This module provides IPLD storage capabilities specifically designed for deontic logic
formulas with full provenance tracking from source documents to formal logic representations.
"""

import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field, asdict
import json
import hashlib
from datetime import datetime
from pathlib import Path

from ..converters.deontic_logic_core import DeonticFormula, DeonticRuleSet
from ..converters.logic_translation_core import TranslationResult, LogicTranslationTarget

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import IPLD components
try:
    from ..data_transformation.ipld.storage import IPLDStorage
    from ..data_transformation.ipld.vector_store import IPLDVectorStore
    IPLD_AVAILABLE = True
except ImportError:
    IPLD_AVAILABLE = False
    logger.warning("IPLD components not available - using file-based storage fallback")


@dataclass
class LogicProvenanceChain:
    """Represents the complete provenance chain from source document to logic formula."""
    source_document_path: str
    source_document_cid: Optional[str] = None
    graphrag_entity_cids: List[str] = field(default_factory=list)
    knowledge_graph_cid: Optional[str] = None
    conversion_context: Dict[str, Any] = field(default_factory=dict)
    formula_cid: Optional[str] = None
    translation_cids: Dict[str, str] = field(default_factory=dict)  # target -> cid
    creation_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass 
class LogicIPLDNode:
    """IPLD node for storing logic formulas with complete metadata."""
    formula_id: str
    deontic_formula: DeonticFormula
    source_document_cid: Optional[str] = None
    source_text_excerpt: str = ""
    extraction_metadata: Dict[str, Any] = field(default_factory=dict)
    translations: Dict[str, str] = field(default_factory=dict)  # target -> translated formula
    translation_cids: Dict[str, str] = field(default_factory=dict)  # target -> IPLD CID
    provenance_chain: Optional[LogicProvenanceChain] = None
    creation_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    confidence_score: float = 1.0
    validation_results: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation for IPLD storage."""
        data = asdict(self)
        # Convert deontic formula to dict
        data["deontic_formula"] = self.deontic_formula.to_dict()
        if self.provenance_chain:
            data["provenance_chain"] = self.provenance_chain.to_dict()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LogicIPLDNode':
        """Create from dictionary representation."""
        # Reconstruct deontic formula
        formula_data = data.pop("deontic_formula")
        deontic_formula = DeonticFormula.from_dict(formula_data)
        
        # Reconstruct provenance chain if present
        provenance_data = data.pop("provenance_chain", None)
        provenance_chain = LogicProvenanceChain(**provenance_data) if provenance_data else None
        
        return cls(
            deontic_formula=deontic_formula,
            provenance_chain=provenance_chain,
            **data
        )


class LogicIPLDStorage:
    """IPLD storage manager for deontic logic formulas with provenance tracking."""
    
    def __init__(self, storage_path: str = "./ipld_logic_storage"):
        """
        Initialize IPLD logic storage.
        
        Args:
            storage_path: Path for IPLD storage (fallback when IPLD not available)
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize IPLD components if available
        if IPLD_AVAILABLE:
            try:
                self.block_manager = IPLDStorage()
                self.vector_store = IPLDVectorStore()
                self.use_ipld = True
                logger.info("IPLD logic storage initialized with full IPLD support")
            except Exception as e:
                logger.warning(f"IPLD initialization failed: {e}, using file fallback")
                self.use_ipld = False
        else:
            self.use_ipld = False
            logger.info("IPLD logic storage initialized with file-based fallback")
        
        # Storage indexes
        self.document_to_formulas: Dict[str, List[str]] = {}  # doc_cid -> formula_cids
        self.formula_nodes: Dict[str, LogicIPLDNode] = {}  # formula_cid -> node
        self.translation_index: Dict[str, Dict[str, str]] = {}  # formula_cid -> {target -> translation_cid}
    
    def store_logic_formula(self, 
                          formula: DeonticFormula,
                          source_doc_cid: Optional[str] = None,
                          extraction_metadata: Dict[str, Any] = None,
                          translations: Dict[str, str] = None) -> str:
        """
        Store a deontic logic formula in IPLD with provenance.
        
        Args:
            formula: The deontic formula to store
            source_doc_cid: CID of the source document
            extraction_metadata: Metadata about the extraction process
            translations: Translated formulas for different targets
            
        Returns:
            CID of the stored formula node
        """
        # Create logic IPLD node
        node = LogicIPLDNode(
            formula_id=formula.formula_id,
            deontic_formula=formula,
            source_document_cid=source_doc_cid,
            source_text_excerpt=formula.source_text,
            extraction_metadata=extraction_metadata or {},
            translations=translations or {},
            confidence_score=formula.confidence
        )
        
        # Store in IPLD or file system
        if self.use_ipld:
            formula_cid = self._store_in_ipld(node)
        else:
            formula_cid = self._store_in_filesystem(node)
        
        # Update indexes
        self.formula_nodes[formula_cid] = node
        
        if source_doc_cid:
            if source_doc_cid not in self.document_to_formulas:
                self.document_to_formulas[source_doc_cid] = []
            self.document_to_formulas[source_doc_cid].append(formula_cid)
        
        logger.info(f"Stored logic formula {formula.formula_id} with CID: {formula_cid}")
        return formula_cid
    
    def store_translation_result(self,
                               formula_cid: str,
                               target: LogicTranslationTarget,
                               translation_result: TranslationResult) -> str:
        """
        Store a translation result for a formula.
        
        Args:
            formula_cid: CID of the original formula
            target: Translation target (Lean, Coq, etc.)
            translation_result: Result of the translation
            
        Returns:
            CID of the stored translation
        """
        translation_data = translation_result.to_dict()
        
        if self.use_ipld:
            translation_cid = self._store_translation_in_ipld(translation_data)
        else:
            translation_cid = self._store_translation_in_filesystem(formula_cid, target.value, translation_data)
        
        # Update indexes
        if formula_cid not in self.translation_index:
            self.translation_index[formula_cid] = {}
        self.translation_index[formula_cid][target.value] = translation_cid
        
        # Update the formula node's translation data
        if formula_cid in self.formula_nodes:
            node = self.formula_nodes[formula_cid]
            node.translations[target.value] = translation_result.translated_formula
            node.translation_cids[target.value] = translation_cid
        
        logger.info(f"Stored {target.value} translation for formula {formula_cid} with CID: {translation_cid}")
        return translation_cid
    
    def store_logic_collection(self, 
                             formulas: List[DeonticFormula],
                             collection_name: str,
                             source_doc_cid: Optional[str] = None) -> str:
        """
        Store a collection of related logic formulas.
        
        Args:
            formulas: List of deontic formulas
            collection_name: Name for the collection
            source_doc_cid: CID of the source document
            
        Returns:
            CID of the collection
        """
        formula_cids = []
        
        for formula in formulas:
            formula_cid = self.store_logic_formula(
                formula=formula,
                source_doc_cid=source_doc_cid,
                extraction_metadata={"collection": collection_name}
            )
            formula_cids.append(formula_cid)
        
        # Create collection metadata
        collection_data = {
            "collection_name": collection_name,
            "formula_cids": formula_cids,
            "source_document_cid": source_doc_cid,
            "creation_timestamp": datetime.now().isoformat(),
            "formula_count": len(formulas)
        }
        
        if self.use_ipld:
            collection_cid = self._store_collection_in_ipld(collection_data)
        else:
            collection_cid = self._store_collection_in_filesystem(collection_name, collection_data)
        
        logger.info(f"Stored logic collection '{collection_name}' with {len(formulas)} formulas, CID: {collection_cid}")
        return collection_cid
    
    def retrieve_formulas_by_document(self, doc_cid: str) -> List[LogicIPLDNode]:
        """Retrieve all logic formulas derived from a specific document."""
        if doc_cid in self.document_to_formulas:
            formula_cids = self.document_to_formulas[doc_cid]
            return [self.formula_nodes[cid] for cid in formula_cids if cid in self.formula_nodes]
        return []
    
    def retrieve_formula_translations(self, formula_cid: str) -> Dict[str, str]:
        """Retrieve all translations for a specific formula."""
        if formula_cid in self.formula_nodes:
            return self.formula_nodes[formula_cid].translations
        return {}
    
    def create_provenance_chain(self,
                              source_pdf_path: str,
                              knowledge_graph_cid: str,
                              formula_cid: str,
                              graphrag_entity_cids: List[str] = None) -> LogicProvenanceChain:
        """Create a complete provenance chain for a logic formula."""
        return LogicProvenanceChain(
            source_document_path=source_pdf_path,
            graphrag_entity_cids=graphrag_entity_cids or [],
            knowledge_graph_cid=knowledge_graph_cid,
            formula_cid=formula_cid,
            conversion_context={
                "extraction_method": "graphrag_to_deontic",
                "processor_version": "2.0"
            }
        )
    
    def _store_in_ipld(self, node: LogicIPLDNode) -> str:
        """Store node in IPLD (when available)."""
        try:
            node_data = node.to_dict()
            block = self.block_manager.create_block(node_data)
            return block.cid
        except Exception as e:
            logger.error(f"IPLD storage failed: {e}, falling back to filesystem")
            return self._store_in_filesystem(node)
    
    def _store_in_filesystem(self, node: LogicIPLDNode) -> str:
        """Store node in filesystem as fallback."""
        # Generate CID-like identifier
        node_json = json.dumps(node.to_dict(), sort_keys=True)
        cid = hashlib.sha256(node_json.encode()).hexdigest()[:32]
        
        # Store as JSON file
        file_path = self.storage_path / f"formula_{cid}.json"
        with open(file_path, 'w') as f:
            json.dump(node.to_dict(), f, indent=2, default=str)
        
        return cid
    
    def _store_translation_in_ipld(self, translation_data: Dict[str, Any]) -> str:
        """Store translation in IPLD."""
        try:
            block = self.block_manager.create_block(translation_data)
            return block.cid
        except Exception as e:
            logger.error(f"IPLD translation storage failed: {e}")
            # Generate fallback CID
            data_json = json.dumps(translation_data, sort_keys=True)
            return hashlib.sha256(data_json.encode()).hexdigest()[:32]
    
    def _store_translation_in_filesystem(self, formula_cid: str, target: str, translation_data: Dict[str, Any]) -> str:
        """Store translation in filesystem."""
        # Generate CID-like identifier
        data_json = json.dumps(translation_data, sort_keys=True)
        cid = hashlib.sha256(data_json.encode()).hexdigest()[:32]
        
        # Store as JSON file
        file_path = self.storage_path / f"translation_{target}_{cid}.json"
        with open(file_path, 'w') as f:
            json.dump(translation_data, f, indent=2, default=str)
        
        return cid
    
    def _store_collection_in_ipld(self, collection_data: Dict[str, Any]) -> str:
        """Store collection in IPLD."""
        try:
            block = self.block_manager.create_block(collection_data)
            return block.cid
        except Exception as e:
            logger.error(f"IPLD collection storage failed: {e}")
            # Generate fallback CID
            data_json = json.dumps(collection_data, sort_keys=True)
            return hashlib.sha256(data_json.encode()).hexdigest()[:32]
    
    def _store_collection_in_filesystem(self, collection_name: str, collection_data: Dict[str, Any]) -> str:
        """Store collection in filesystem."""
        # Generate CID-like identifier
        data_json = json.dumps(collection_data, sort_keys=True)
        cid = hashlib.sha256(data_json.encode()).hexdigest()[:32]
        
        # Store as JSON file
        safe_name = collection_name.replace(" ", "_").replace("/", "_")
        file_path = self.storage_path / f"collection_{safe_name}_{cid}.json"
        with open(file_path, 'w') as f:
            json.dump(collection_data, f, indent=2, default=str)
        
        return cid
    
    def get_storage_statistics(self) -> Dict[str, Any]:
        """Get statistics about stored logic formulas."""
        return {
            "total_formulas": len(self.formula_nodes),
            "total_documents": len(self.document_to_formulas),
            "total_translations": sum(len(translations) for translations in self.translation_index.values()),
            "storage_backend": "IPLD" if self.use_ipld else "filesystem",
            "storage_path": str(self.storage_path)
        }


class LogicProvenanceTracker:
    """Track and verify the lineage from source document to logic formula."""
    
    def __init__(self, logic_storage: LogicIPLDStorage):
        """Initialize provenance tracker with logic storage."""
        self.logic_storage = logic_storage
        self.provenance_cache: Dict[str, LogicProvenanceChain] = {}
    
    def track_formula_creation(self,
                             formula: DeonticFormula,
                             source_pdf_path: str,
                             knowledge_graph_cid: str,
                             entity_cids: List[str] = None) -> str:
        """
        Track the creation of a formula and store complete provenance.
        
        Args:
            formula: The deontic formula
            source_pdf_path: Path to the source PDF
            knowledge_graph_cid: CID of the knowledge graph
            entity_cids: List of entity CIDs that contributed to this formula
            
        Returns:
            CID of the stored formula with provenance
        """
        # Store the formula first
        formula_cid = self.logic_storage.store_logic_formula(
            formula=formula,
            extraction_metadata={"source_method": "graphrag_conversion"}
        )
        
        # Create and store provenance chain
        provenance = self.logic_storage.create_provenance_chain(
            source_pdf_path=source_pdf_path,
            knowledge_graph_cid=knowledge_graph_cid,
            formula_cid=formula_cid,
            graphrag_entity_cids=entity_cids or []
        )
        
        # Update formula node with provenance
        if formula_cid in self.logic_storage.formula_nodes:
            self.logic_storage.formula_nodes[formula_cid].provenance_chain = provenance
        
        self.provenance_cache[formula_cid] = provenance
        
        logger.info(f"Tracked formula creation with full provenance: {formula_cid}")
        return formula_cid
    
    def verify_provenance(self, formula_cid: str) -> Dict[str, Any]:
        """
        Verify the complete lineage of a logic formula.
        
        Args:
            formula_cid: CID of the formula to verify
            
        Returns:
            Verification result with lineage information
        """
        if formula_cid not in self.logic_storage.formula_nodes:
            return {"verified": False, "error": "Formula not found"}
        
        node = self.logic_storage.formula_nodes[formula_cid]
        provenance = node.provenance_chain
        
        if not provenance:
            return {"verified": False, "error": "No provenance chain found"}
        
        verification = {
            "verified": True,
            "formula_id": node.formula_id,
            "source_document": provenance.source_document_path,
            "creation_timestamp": provenance.creation_timestamp,
            "lineage_complete": bool(provenance.knowledge_graph_cid and provenance.formula_cid),
            "entity_count": len(provenance.graphrag_entity_cids),
            "translation_count": len(node.translation_cids),
            "confidence_score": node.confidence_score
        }
        
        return verification
    
    def find_related_formulas(self, formula_cid: str) -> List[str]:
        """
        Find formulas derived from the same source or related entities.
        
        Args:
            formula_cid: CID of the reference formula
            
        Returns:
            List of related formula CIDs
        """
        if formula_cid not in self.logic_storage.formula_nodes:
            return []
        
        node = self.logic_storage.formula_nodes[formula_cid]
        provenance = node.provenance_chain
        
        if not provenance or not provenance.source_document_cid:
            return []
        
        # Find all formulas from the same document
        related_cids = self.logic_storage.document_to_formulas.get(provenance.source_document_cid, [])
        
        # Exclude the original formula
        return [cid for cid in related_cids if cid != formula_cid]
    
    def export_provenance_report(self, output_path: str = "./provenance_report.json"):
        """Export a comprehensive provenance report."""
        report = {
            "report_timestamp": datetime.now().isoformat(),
            "total_formulas": len(self.logic_storage.formula_nodes),
            "storage_statistics": self.logic_storage.get_storage_statistics(),
            "provenance_chains": []
        }
        
        for formula_cid, node in self.logic_storage.formula_nodes.items():
            if node.provenance_chain:
                verification = self.verify_provenance(formula_cid)
                report["provenance_chains"].append({
                    "formula_cid": formula_cid,
                    "verification": verification,
                    "provenance": node.provenance_chain.to_dict()
                })
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"Exported provenance report to {output_path}")
        return report


# Convenience function for easy usage
def create_logic_storage_with_provenance(storage_path: str = "./ipld_logic_storage") -> Tuple[LogicIPLDStorage, LogicProvenanceTracker]:
    """Create logic storage with provenance tracking."""
    storage = LogicIPLDStorage(storage_path)
    tracker = LogicProvenanceTracker(storage)
    return storage, tracker