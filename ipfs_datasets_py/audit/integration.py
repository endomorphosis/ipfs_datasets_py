"""
Audit Logging Integration Module

This module provides integration between the audit logging system and other
IPFS Datasets components, particularly data provenance tracking. It enables
comprehensive tracking and correlation of audit events with data provenance.
"""

import json
import datetime
import logging
from typing import Dict, List, Any, Optional, Union, Set
from dataclasses import asdict

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)

# Try to import provenance module for integration
try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, ProvenanceContext,
        SourceRecord, TransformationRecord, VerificationRecord, AnnotationRecord,
        ModelTrainingRecord, ModelInferenceRecord
    )
    PROVENANCE_MODULE_AVAILABLE = True
except ImportError:
    PROVENANCE_MODULE_AVAILABLE = False


class AuditProvenanceIntegrator:
    """
    Integrates audit logging with data provenance tracking.
    
    This class provides bidirectional integration between audit logging and
    data provenance tracking systems, enabling comprehensive tracking and
    correlation of system activities.
    """
    
    def __init__(self, audit_logger=None, provenance_manager=None):
        """
        Initialize the integrator.
        
        Args:
            audit_logger: AuditLogger instance (optional, will use global instance if None)
            provenance_manager: EnhancedProvenanceManager instance (optional)
        """
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.provenance_manager = provenance_manager
        self.logger = logging.getLogger(__name__)
        
        if not PROVENANCE_MODULE_AVAILABLE:
            self.logger.warning("Data provenance module not available. Some features will be disabled.")
    
    def initialize_provenance_manager(self):
        """Initialize the provenance manager if not already done."""
        if not PROVENANCE_MODULE_AVAILABLE:
            return False
        
        if not self.provenance_manager:
            try:
                self.provenance_manager = EnhancedProvenanceManager()
                return True
            except Exception as e:
                self.logger.error(f"Error initializing provenance manager: {str(e)}")
                return False
        
        return True
    
    def audit_from_provenance_record(self, record: Any, additional_details: Dict[str, Any] = None) -> Optional[str]:
        """
        Generate an audit event from a provenance record.
        
        Args:
            record: Provenance record (SourceRecord, TransformationRecord, etc.)
            additional_details: Additional details to include in the audit event
            
        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        if not PROVENANCE_MODULE_AVAILABLE:
            return None
        
        try:
            # Determine audit category and action based on record type
            category = AuditCategory.PROVENANCE
            action = "unknown"
            resource_id = None
            resource_type = None
            details = additional_details or {}
            
            # Extract record-specific information
            if hasattr(record, "record_id"):
                details["provenance_record_id"] = record.record_id
            
            if hasattr(record, "timestamp"):
                details["provenance_timestamp"] = record.timestamp
            
            # Determine action and resource based on record type
            if isinstance(record, SourceRecord):
                action = "data_source_access"
                resource_id = record.source_id
                resource_type = "data_source"
                details["source_type"] = record.source_type
                details["source_uri"] = record.source_uri
            
            elif isinstance(record, TransformationRecord):
                action = "data_transformation"
                resource_id = record.output_id
                resource_type = "transformed_data"
                details["input_ids"] = record.input_ids
                details["transformation_type"] = record.transformation_type
            
            elif isinstance(record, VerificationRecord):
                action = "data_verification"
                resource_id = record.data_id
                resource_type = "verified_data"
                details["verification_type"] = record.verification_type
                details["result"] = record.result
            
            elif isinstance(record, AnnotationRecord):
                action = "data_annotation"
                resource_id = record.data_id
                resource_type = "annotated_data"
                details["annotation_type"] = record.annotation_type
            
            elif isinstance(record, ModelTrainingRecord):
                action = "model_training"
                resource_id = record.model_id
                resource_type = "ml_model"
                details["dataset_ids"] = record.dataset_ids
                details["parameters"] = record.parameters
            
            elif isinstance(record, ModelInferenceRecord):
                action = "model_inference"
                resource_id = record.model_id
                resource_type = "ml_model"
                details["input_id"] = record.input_id
                details["output_id"] = record.output_id
            
            # Generate the audit event
            event_id = self.audit_logger.log(
                level=AuditLevel.INFO,
                category=category,
                action=action,
                resource_id=resource_id,
                resource_type=resource_type,
                details=details
            )
            
            return event_id
        
        except Exception as e:
            self.logger.error(f"Error generating audit event from provenance record: {str(e)}")
            return None
    
    def provenance_from_audit_event(self, event: AuditEvent) -> Optional[str]:
        """
        Generate a provenance record from an audit event.
        
        Args:
            event: The audit event to convert
            
        Returns:
            str: Record ID of the generated provenance record, or None if failed
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.initialize_provenance_manager():
            return None
        
        try:
            record_id = None
            
            # Map audit category/action to provenance record type
            if event.category == AuditCategory.DATA_ACCESS and event.action in ["read", "load", "import"]:
                # Create a source record
                record_id = self.provenance_manager.record_source(
                    source_id=event.resource_id,
                    source_type=event.resource_type or "unknown",
                    source_uri=event.details.get("uri", ""),
                    metadata={
                        "audit_event_id": event.event_id,
                        "user": event.user,
                        "timestamp": event.timestamp,
                        **event.details
                    }
                )
            
            elif event.category == AuditCategory.DATA_MODIFICATION and event.action in ["transform", "process", "convert"]:
                # Create a transformation record
                input_ids = event.details.get("input_ids", [])
                if isinstance(input_ids, str):
                    input_ids = [input_ids]
                
                record_id = self.provenance_manager.record_transformation(
                    input_ids=input_ids,
                    output_id=event.resource_id,
                    transformation_type=event.details.get("transformation_type", "unknown"),
                    parameters=event.details.get("parameters", {}),
                    metadata={
                        "audit_event_id": event.event_id,
                        "user": event.user,
                        "timestamp": event.timestamp
                    }
                )
            
            elif event.category == AuditCategory.COMPLIANCE and event.action in ["verify", "validate"]:
                # Create a verification record
                record_id = self.provenance_manager.record_verification(
                    data_id=event.resource_id,
                    verification_type=event.details.get("verification_type", "unknown"),
                    result=event.details.get("result", {}),
                    metadata={
                        "audit_event_id": event.event_id,
                        "user": event.user,
                        "timestamp": event.timestamp
                    }
                )
            
            return record_id
        
        except Exception as e:
            self.logger.error(f"Error generating provenance record from audit event: {str(e)}")
            return None
    
    def link_audit_to_provenance(self, audit_event_id: str, provenance_record_id: str) -> bool:
        """
        Create a link between an audit event and a provenance record.
        
        Args:
            audit_event_id: ID of the audit event
            provenance_record_id: ID of the provenance record
            
        Returns:
            bool: Whether the linking was successful
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.initialize_provenance_manager():
            return False
        
        try:
            # Add audit event reference to provenance record
            self.provenance_manager.add_metadata_to_record(
                record_id=provenance_record_id,
                metadata={"linked_audit_event_id": audit_event_id}
            )
            
            # Log the link in audit logs
            self.audit_logger.log(
                level=AuditLevel.INFO,
                category=AuditCategory.PROVENANCE,
                action="link_audit_provenance",
                details={
                    "audit_event_id": audit_event_id,
                    "provenance_record_id": provenance_record_id
                }
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error linking audit event to provenance record: {str(e)}")
            return False
    
    def setup_audit_event_listener(self) -> bool:
        """
        Set up automatic provenance record creation from audit events.
        
        This method adds a listener to the audit logger that automatically
        creates corresponding provenance records for relevant audit events.
        
        Returns:
            bool: Whether the listener was successfully set up
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.initialize_provenance_manager():
            return False
        
        try:
            # Create a handler for the audit logger
            def audit_to_provenance_handler(event: AuditEvent):
                # Filter events that should generate provenance records
                if event.category in [AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION, 
                                      AuditCategory.COMPLIANCE]:
                    # Generate provenance record from audit event
                    record_id = self.provenance_from_audit_event(event)
                    
                    # If successful, link the audit event to the provenance record
                    if record_id:
                        self.link_audit_to_provenance(event.event_id, record_id)
            
            # Add the handler as an event listener for relevant categories
            for category in [AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION, 
                          AuditCategory.COMPLIANCE]:
                self.audit_logger.add_event_listener(audit_to_provenance_handler, category)
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error setting up audit event listener: {str(e)}")
            return False


class AuditDatasetIntegrator:
    """
    Integrates audit logging with dataset operations.
    
    This class provides utilities for tracking dataset operations
    through the audit logging system.
    """
    
    def __init__(self, audit_logger=None):
        """
        Initialize the dataset integrator.
        
        Args:
            audit_logger: AuditLogger instance (optional, will use global instance if None)
        """
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.logger = logging.getLogger(__name__)
    
    def record_dataset_load(self, dataset_name: str, dataset_id: Optional[str] = None,
                           source: Optional[str] = None, user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset loading operation in audit log.
        
        Args:
            dataset_name: Name of the dataset
            dataset_id: ID of the dataset (optional)
            source: Source of the dataset (e.g., "local", "huggingface", "ipfs")
            user: User performing the operation (optional)
            
        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_access(
                action="dataset_load",
                user=user,
                resource_id=dataset_id or dataset_name,
                resource_type="dataset",
                details={
                    "dataset_name": dataset_name,
                    "source": source or "unknown"
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset load: {str(e)}")
            return None
    
    def record_dataset_save(self, dataset_name: str, dataset_id: Optional[str] = None,
                           destination: Optional[str] = None, format: Optional[str] = None,
                           user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset saving operation in audit log.
        
        Args:
            dataset_name: Name of the dataset
            dataset_id: ID of the dataset (optional)
            destination: Destination for saving (e.g., "local", "huggingface", "ipfs")
            format: Format of the saved dataset (e.g., "parquet", "car", "arrow")
            user: User performing the operation (optional)
            
        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_modify(
                action="dataset_save",
                user=user,
                resource_id=dataset_id or dataset_name,
                resource_type="dataset",
                details={
                    "dataset_name": dataset_name,
                    "destination": destination or "unknown",
                    "format": format or "unknown"
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset save: {str(e)}")
            return None
    
    def record_dataset_transform(self, input_dataset: str, output_dataset: str,
                              transformation_type: str, parameters: Optional[Dict[str, Any]] = None,
                              user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset transformation operation in audit log.
        
        Args:
            input_dataset: Name or ID of the input dataset
            output_dataset: Name or ID of the output dataset
            transformation_type: Type of transformation applied
            parameters: Parameters of the transformation (optional)
            user: User performing the operation (optional)
            
        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_modify(
                action="dataset_transform",
                user=user,
                resource_id=output_dataset,
                resource_type="dataset",
                details={
                    "input_dataset": input_dataset,
                    "transformation_type": transformation_type,
                    "parameters": parameters or {}
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset transformation: {str(e)}")
            return None
    
    def record_dataset_query(self, dataset_name: str, query: str,
                          query_type: Optional[str] = None,
                          user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset query operation in audit log.
        
        Args:
            dataset_name: Name or ID of the dataset
            query: The query executed
            query_type: Type of query (e.g., "sql", "vector", "graph")
            user: User performing the operation (optional)
            
        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_access(
                action="dataset_query",
                user=user,
                resource_id=dataset_name,
                resource_type="dataset",
                details={
                    "query": query,
                    "query_type": query_type or "unknown"
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset query: {str(e)}")
            return None


class AuditContextManager:
    """
    Context manager for comprehensive audit logging in code blocks.
    
    This class provides a convenient way to log the beginning and end
    of operations, including timing information and exceptions.
    """
    
    def __init__(self, category: AuditCategory, action: str, resource_id: Optional[str] = None,
                 resource_type: Optional[str] = None, level: AuditLevel = AuditLevel.INFO,
                 details: Optional[Dict[str, Any]] = None, audit_logger=None):
        """
        Initialize the audit context manager.
        
        Args:
            category: Audit category
            action: Action being performed
            resource_id: ID of the resource being acted upon (optional)
            resource_type: Type of the resource being acted upon (optional)
            level: Audit level
            details: Additional details about the operation (optional)
            audit_logger: AuditLogger instance (optional, will use global instance if None)
        """
        self.category = category
        self.action = action
        self.resource_id = resource_id
        self.resource_type = resource_type
        self.level = level
        self.details = details or {}
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.start_time = None
        self.start_event_id = None
    
    def __enter__(self):
        """Begin the audited operation."""
        self.start_time = datetime.datetime.now()
        
        # Log operation start
        self.start_event_id = self.audit_logger.log(
            level=self.level,
            category=self.category,
            action=f"{self.action}_start",
            resource_id=self.resource_id,
            resource_type=self.resource_type,
            details=self.details
        )
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End the audited operation."""
        end_time = datetime.datetime.now()
        duration_ms = int((end_time - self.start_time).total_seconds() * 1000)
        
        # Add timing information to details
        details = self.details.copy()
        details["duration_ms"] = duration_ms
        details["start_event_id"] = self.start_event_id
        
        # Handle exceptions
        if exc_type is not None:
            # Log operation failure
            self.audit_logger.log(
                level=AuditLevel.ERROR,
                category=self.category,
                action=f"{self.action}_error",
                resource_id=self.resource_id,
                resource_type=self.resource_type,
                status="failure",
                details={
                    **details,
                    "error_type": exc_type.__name__,
                    "error_message": str(exc_val)
                }
            )
        else:
            # Log operation completion
            self.audit_logger.log(
                level=self.level,
                category=self.category,
                action=f"{self.action}_complete",
                resource_id=self.resource_id,
                resource_type=self.resource_type,
                status="success",
                details=details
            )
        
        # Don't suppress exceptions
        return False


def audit_function(category: AuditCategory, action: str, resource_id_arg: Optional[str] = None,
                 resource_type: Optional[str] = None, level: AuditLevel = AuditLevel.INFO,
                 details_extractor: Optional[Callable] = None):
    """
    Decorator for auditing function calls.
    
    This decorator logs the start and end of function execution,
    including timing information and exceptions.
    
    Args:
        category: Audit category
        action: Action being performed
        resource_id_arg: Name of the argument containing the resource ID (optional)
        resource_type: Type of the resource being acted upon (optional)
        level: Audit level
        details_extractor: Function to extract additional details from arguments (optional)
        
    Returns:
        Callable: Decorated function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Get audit logger
            audit_logger = AuditLogger.get_instance()
            
            # Extract resource ID from arguments if specified
            resource_id = None
            if resource_id_arg:
                if resource_id_arg in kwargs:
                    resource_id = kwargs[resource_id_arg]
                elif args and len(args) > 0:
                    # Try to get from function signature
                    import inspect
                    sig = inspect.signature(func)
                    param_names = list(sig.parameters.keys())
                    
                    for i, param_name in enumerate(param_names):
                        if param_name == resource_id_arg and i < len(args):
                            resource_id = args[i]
                            break
            
            # Extract additional details if details_extractor is provided
            details = {}
            if details_extractor:
                try:
                    details = details_extractor(*args, **kwargs) or {}
                except Exception as e:
                    logging.error(f"Error extracting audit details: {str(e)}")
            
            # Add function information to details
            details["function"] = func.__name__
            details["module"] = func.__module__
            
            # Create audit context
            with AuditContextManager(
                category=category,
                action=action,
                resource_id=resource_id,
                resource_type=resource_type,
                level=level,
                details=details,
                audit_logger=audit_logger
            ):
                # Execute the function
                return func(*args, **kwargs)
        
        return wrapper
    
    return decorator