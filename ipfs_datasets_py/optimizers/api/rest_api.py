"""
REST API endpoints for complaint-generator optimization platform.

Provides FastAPI-based REST API for managing entities, relationships,
consensus operations, memory profiling, and comparisons.

Features:
- Full CRUD operations for entities and relationships
- Consensus mechanism REST endpoints
- Memory profiling endpoints
- Comparison operations
- OpenAPI documentation
- Error handling and validation
- CORS support
"""

from fastapi import FastAPI, HTTPException, Query, Path, Body, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import logging
from contextlib import contextmanager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EntityType(str, Enum):
    """Entity type enumeration."""
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    EVENT = "event"
    CONCEPT = "concept"
    OTHER = "other"


class RelationshipType(str, Enum):
    """Relationship type enumeration."""
    PART_OF = "part_of"
    WORKS_FOR = "works_for"
    LOCATED_IN = "located_in"
    OWNS = "owns"
    INTERACTS_WITH = "interacts_with"
    IS_CHILD_OF = "is_child_of"
    RELATED_TO = "related_to"
    MENTIONS = "mentions"
    OTHER = "other"


class EntityRequest(BaseModel):
    """Request model for entity creation/update."""
    name: str = Field(..., min_length=1, max_length=500)
    entity_type: EntityType
    description: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        use_enum_values = True


class EntityResponse(BaseModel):
    """Response model for entity."""
    id: str
    name: str
    entity_type: str
    description: Optional[str]
    confidence: float
    metadata: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    
    class Config:
        use_enum_values = True


class RelationshipRequest(BaseModel):
    """Request model for relationship creation/update."""
    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    relationship_type: RelationshipType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None
    
    @validator('source_id', 'target_id')
    def validate_ids(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('ID cannot be empty')
        return v.strip()
    
    class Config:
        use_enum_values = True


class RelationshipResponse(BaseModel):
    """Response model for relationship."""
    id: str
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float
    metadata: Optional[Dict[str, Any]]
    created_at: str
    
    class Config:
        use_enum_values = True


class AgentVoteRequest(BaseModel):
    """Request model for agent vote."""
    agent_id: str = Field(..., min_length=1)
    entities: List[EntityRequest]
    relationships: List[RelationshipRequest]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ConsensusRequest(BaseModel):
    """Request model for consensus operation."""
    votes: List[AgentVoteRequest]
    strategy: str = Field(default="majority", pattern="^(majority|unanimous|weighted|threshold|qualified_majority)$")
    threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


class ConsensusResponse(BaseModel):
    """Response model for consensus result."""
    consensus_entities: List[EntityResponse]
    consensus_relationships: List[RelationshipResponse]
    agreement_rate: float
    entropy: float
    conflicts: List[Dict[str, Any]]
    strategies_applied: List[str]
    timestamp: str


class ComparisonRequest(BaseModel):
    """Request model for comparison operation."""
    baseline_entities: List[EntityRequest]
    baseline_relationships: List[RelationshipRequest]
    optimized_entities: List[EntityRequest]
    optimized_relationships: List[RelationshipRequest]


class ComparisonResponse(BaseModel):
    """Response model for comparison result."""
    memory_saved_mb: float
    memory_saved_percent: float
    improvement_ratio: float
    entity_reduction_percent: float
    relationship_reduction_percent: float
    recommendation: str
    timestamp: str


class MemorySnapshotResponse(BaseModel):
    """Response model for memory snapshot."""
    timestamp: str
    current_memory_mb: float
    peak_memory_mb: float
    total_allocated_mb: float
    object_count: int
    gc_collections: int


class MemoryHotspotResponse(BaseModel):
    """Response model for memory hotspot."""
    object_type: str
    count: int
    total_memory_mb: float
    avg_size_kb: float
    percentage_of_total: float


class AgentProfileResponse(BaseModel):
    """Response model for agent profile."""
    agent_id: str
    reputation: float
    accuracy: float
    votes_count: int
    correct_extractions: int
    calibration: float
    last_updated: str


class ErrorResponse(BaseModel):
    """Response model for errors."""
    error: str
    detail: str
    timestamp: str
    request_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    timestamp: str
    version: str


class PaginationParams(BaseModel):
    """Pagination parameters."""
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=100)
    
    @property
    def offset(self) -> int:
        return self.skip
    
    @property
    def page_size(self) -> int:
        return self.limit


class EntityStore:
    """In-memory entity storage for API."""
    
    def __init__(self):
        self.entities: Dict[str, dict] = {}
        self._id_counter = 0
    
    def create(self, entity_data: EntityRequest) -> EntityResponse:
        """Create new entity."""
        self._id_counter += 1
        entity_id = f"entity_{self._id_counter}"
        now = datetime.utcnow().isoformat()
        
        entity = {
            'id': entity_id,
            'name': entity_data.name,
            'entity_type': entity_data.entity_type,
            'description': entity_data.description,
            'confidence': entity_data.confidence,
            'metadata': entity_data.metadata or {},
            'created_at': now,
            'updated_at': now
        }
        
        self.entities[entity_id] = entity
        return EntityResponse(**entity)
    
    def get(self, entity_id: str) -> Optional[EntityResponse]:
        """Get entity by ID."""
        if entity_id not in self.entities:
            return None
        return EntityResponse(**self.entities[entity_id])
    
    def list_entities(self, skip: int = 0, limit: int = 10) -> List[EntityResponse]:
        """List all entities with pagination."""
        entities_list = list(self.entities.values())
        return [EntityResponse(**e) for e in entities_list[skip:skip+limit]]
    
    def update(self, entity_id: str, entity_data: EntityRequest) -> Optional[EntityResponse]:
        """Update entity."""
        if entity_id not in self.entities:
            return None
        
        self.entities[entity_id].update({
            'name': entity_data.name,
            'entity_type': entity_data.entity_type,
            'description': entity_data.description,
            'confidence': entity_data.confidence,
            'metadata': entity_data.metadata or {},
            'updated_at': datetime.utcnow().isoformat()
        })
        
        return EntityResponse(**self.entities[entity_id])
    
    def delete(self, entity_id: str) -> bool:
        """Delete entity."""
        if entity_id in self.entities:
            del self.entities[entity_id]
            return True
        return False
    
    def count(self) -> int:
        """Get total entity count."""
        return len(self.entities)


class RelationshipStore:
    """In-memory relationship storage for API."""
    
    def __init__(self):
        self.relationships: Dict[str, dict] = {}
        self._id_counter = 0
    
    def create(self, rel_data: RelationshipRequest) -> RelationshipResponse:
        """Create new relationship."""
        self._id_counter += 1
        rel_id = f"rel_{self._id_counter}"
        now = datetime.utcnow().isoformat()
        
        rel = {
            'id': rel_id,
            'source_id': rel_data.source_id,
            'target_id': rel_data.target_id,
            'relationship_type': rel_data.relationship_type,
            'confidence': rel_data.confidence,
            'metadata': rel_data.metadata or {},
            'created_at': now
        }
        
        self.relationships[rel_id] = rel
        return RelationshipResponse(**rel)
    
    def get(self, rel_id: str) -> Optional[RelationshipResponse]:
        """Get relationship by ID."""
        if rel_id not in self.relationships:
            return None
        return RelationshipResponse(**self.relationships[rel_id])
    
    def list_relationships(self, skip: int = 0, limit: int = 10) -> List[RelationshipResponse]:
        """List all relationships with pagination."""
        rels_list = list(self.relationships.values())
        return [RelationshipResponse(**r) for r in rels_list[skip:skip+limit]]
    
    def delete(self, rel_id: str) -> bool:
        """Delete relationship."""
        if rel_id in self.relationships:
            del self.relationships[rel_id]
            return True
        return False
    
    def count(self) -> int:
        """Get total relationship count."""
        return len(self.relationships)


class APIServer:
    """REST API server for complaint generator."""
    
    def __init__(self, title: str = "Complaint Generator API", version: str = "1.0.0"):
        self.app = FastAPI(
            title=title,
            version=version,
            description="REST API for complaint analysis and optimization"
        )
        
        self.entity_store = EntityStore()
        self.relationship_store = RelationshipStore()
        self.version = version
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup API routes."""
        
        @self.app.get("/health", response_model=HealthResponse, tags=["Health"])
        def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "version": self.version
            }

        @self.app.get("/metrics", tags=["Metrics"])
        def metrics():
            """Prometheus scrape endpoint."""
            from ipfs_datasets_py.optimizers.common.metrics_prometheus import (
                get_global_prometheus_metrics,
            )

            metrics_collector = get_global_prometheus_metrics()
            payload = metrics_collector.collect_metrics()
            return Response(content=payload, media_type="text/plain")
        
        # Entity endpoints
        @self.app.post("/entities", response_model=EntityResponse, tags=["Entities"])
        def create_entity(entity: EntityRequest):
            """Create a new entity."""
            try:
                return self.entity_store.create(entity)
            except (AttributeError, RuntimeError, TypeError, ValueError) as e:
                logger.error(f"Error creating entity: {e}")
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/entities/{entity_id}", response_model=EntityResponse, tags=["Entities"])
        def get_entity(entity_id: str = Path(..., min_length=1)):
            """Get entity by ID."""
            entity = self.entity_store.get(entity_id)
            if not entity:
                raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
            return entity
        
        @self.app.put("/entities/{entity_id}", response_model=EntityResponse, tags=["Entities"])
        def update_entity(entity_id: str = Path(..., min_length=1), entity: EntityRequest = Body(...)):
            """Update entity."""
            updated = self.entity_store.update(entity_id, entity)
            if not updated:
                raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
            return updated
        
        @self.app.delete("/entities/{entity_id}", tags=["Entities"])
        def delete_entity(entity_id: str = Path(..., min_length=1)):
            """Delete entity."""
            if not self.entity_store.delete(entity_id):
                raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
            return {"message": f"Entity {entity_id} deleted"}
        
        @self.app.get("/entities", response_model=List[EntityResponse], tags=["Entities"])
        def list_entities(skip: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100)):
            """List all entities."""
            return self.entity_store.list_entities(skip=skip, limit=limit)
        
        # Relationship endpoints
        @self.app.post("/relationships", response_model=RelationshipResponse, tags=["Relationships"])
        def create_relationship(relationship: RelationshipRequest):
            """Create a new relationship."""
            try:
                return self.relationship_store.create(relationship)
            except (AttributeError, RuntimeError, TypeError, ValueError) as e:
                logger.error(f"Error creating relationship: {e}")
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/relationships/{rel_id}", response_model=RelationshipResponse, tags=["Relationships"])
        def get_relationship(rel_id: str = Path(..., min_length=1)):
            """Get relationship by ID."""
            rel = self.relationship_store.get(rel_id)
            if not rel:
                raise HTTPException(status_code=404, detail=f"Relationship {rel_id} not found")
            return rel
        
        @self.app.delete("/relationships/{rel_id}", tags=["Relationships"])
        def delete_relationship(rel_id: str = Path(..., min_length=1)):
            """Delete relationship."""
            if not self.relationship_store.delete(rel_id):
                raise HTTPException(status_code=404, detail=f"Relationship {rel_id} not found")
            return {"message": f"Relationship {rel_id} deleted"}
        
        @self.app.get("/relationships", response_model=List[RelationshipResponse], tags=["Relationships"])
        def list_relationships(skip: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100)):
            """List all relationships."""
            return self.relationship_store.list_relationships(skip=skip, limit=limit)
        
        # Consensus endpoint
        @self.app.post("/consensus", response_model=ConsensusResponse, tags=["Consensus"])
        def reach_consensus(request: ConsensusRequest):
            """Reach consensus from multiple agent votes."""
            try:
                # Simplified consensus: just merge all votes
                all_entities = []
                all_relationships = []
                total_confidence = 0
                agent_count = len(request.votes)
                
                for vote in request.votes:
                    for entity in vote.entities:
                        all_entities.append(EntityResponse(
                            id=f"consensus_entity_{len(all_entities)}",
                            name=entity.name,
                            entity_type=entity.entity_type,
                            description=entity.description,
                            confidence=entity.confidence,
                            metadata=entity.metadata,
                            created_at=datetime.utcnow().isoformat(),
                            updated_at=datetime.utcnow().isoformat()
                        ))
                    for rel in vote.relationships:
                        all_relationships.append(RelationshipResponse(
                            id=f"consensus_rel_{len(all_relationships)}",
                            source_id=rel.source_id,
                            target_id=rel.target_id,
                            relationship_type=rel.relationship_type,
                            confidence=rel.confidence,
                            metadata=rel.metadata,
                            created_at=datetime.utcnow().isoformat()
                        ))
                    total_confidence += vote.confidence
                
                agreement_rate = total_confidence / agent_count if agent_count > 0 else 0
                
                return {
                    "consensus_entities": all_entities[:5],  # Limit to 5 for response
                    "consensus_relationships": all_relationships[:5],
                    "agreement_rate": min(agreement_rate, 1.0),
                    "entropy": 0.5,  # Placeholder
                    "conflicts": [],
                    "strategies_applied": [request.strategy],
                    "timestamp": datetime.utcnow().isoformat()
                }
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as e:
                logger.error(f"Error reaching consensus: {e}")
                raise HTTPException(status_code=400, detail=str(e))
        
        # Comparison endpoint
        @self.app.post("/compare", response_model=ComparisonResponse, tags=["Comparison"])
        def compare_extractions(request: ComparisonRequest):
            """Compare baseline vs optimized extraction."""
            try:
                baseline_entity_count = len(request.baseline_entities)
                optimized_entity_count = len(request.optimized_entities)
                
                baseline_rel_count = len(request.baseline_relationships)
                optimized_rel_count = len(request.optimized_relationships)
                
                entity_reduction = max(0, baseline_entity_count - optimized_entity_count)
                rel_reduction = max(0, baseline_rel_count - optimized_rel_count)
                
                entity_reduction_pct = (entity_reduction / baseline_entity_count * 100) if baseline_entity_count > 0 else 0
                rel_reduction_pct = (rel_reduction / baseline_rel_count * 100) if baseline_rel_count > 0 else 0
                
                memory_saved = (entity_reduction + rel_reduction) * 0.5  # Estimate
                memory_saved_pct = 15.0  # Placeholder
                
                recommendation = f"Reduced entities by {entity_reduction_pct:.1f}%, relationships by {rel_reduction_pct:.1f}%"
                
                return {
                    "memory_saved_mb": memory_saved,
                    "memory_saved_percent": memory_saved_pct,
                    "improvement_ratio": 1.15,
                    "entity_reduction_percent": entity_reduction_pct,
                    "relationship_reduction_percent": rel_reduction_pct,
                    "recommendation": recommendation,
                    "timestamp": datetime.utcnow().isoformat()
                }
            except (AttributeError, RuntimeError, TypeError, ValueError) as e:
                logger.error(f"Error comparing extractions: {e}")
                raise HTTPException(status_code=400, detail=str(e))
        
        # Memory profiling endpoints
        @self.app.get("/memory/snapshot", response_model=MemorySnapshotResponse, tags=["Memory"])
        def get_memory_snapshot():
            """Get current memory snapshot."""
            import os
            try:
                import psutil
                process = psutil.Process(os.getpid())
                mem_info = process.memory_info()
                current_mem_mb = mem_info.rss / (1024 * 1024)
            except (ImportError, AttributeError, OSError, RuntimeError, ValueError, TypeError):
                current_mem_mb = 0.0
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "current_memory_mb": current_mem_mb,
                "peak_memory_mb": current_mem_mb,
                "total_allocated_mb": current_mem_mb,
                "object_count": self.entity_store.count() + self.relationship_store.count(),
                "gc_collections": 0
            }
        
        @self.app.get("/memory/hotspots", response_model=List[MemoryHotspotResponse], tags=["Memory"])
        def get_memory_hotspots(limit: int = Query(5, ge=1, le=20)):
            """Get memory hotspots."""
            return [
                {
                    "object_type": "EntityResponse",
                    "count": self.entity_store.count(),
                    "total_memory_mb": self.entity_store.count() * 0.001,
                    "avg_size_kb": 2.0,
                    "percentage_of_total": 50.0
                },
                {
                    "object_type": "RelationshipResponse",
                    "count": self.relationship_store.count(),
                    "total_memory_mb": self.relationship_store.count() * 0.0005,
                    "avg_size_kb": 1.5,
                    "percentage_of_total": 30.0
                }
            ][:limit]
        
        # Statistics endpoints
        @self.app.get("/stats", tags=["Statistics"])
        def get_statistics():
            """Get system statistics."""
            return {
                "total_entities": self.entity_store.count(),
                "total_relationships": self.relationship_store.count(),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def get_app(self) -> FastAPI:
        """Get FastAPI application instance."""
        return self.app
