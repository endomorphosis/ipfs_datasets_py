"""
Batch Processing Module for PDF Processing Pipeline

Handles large-scale PDF processing operations:
- Batch document processing with parallel execution
- Progress tracking and error handling
- Resource management and optimization
- Distributed processing coordination
- Performance monitoring and reporting
"""

import asyncio
import logging
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
import uuid
import concurrent.futures
import multiprocessing as mp
from queue import Queue
import threading

from ..ipld import IPLDStorage
from ..audit import AuditLogger
from ..monitoring import MonitoringSystem
from .pdf_processor import PDFProcessor
from .llm_optimizer import LLMOptimizer, LLMDocument
from .graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph

logger = logging.getLogger(__name__)

@dataclass
class ProcessingJob:
    """Individual processing job."""
    job_id: str
    pdf_path: str
    metadata: Dict[str, Any]
    priority: int = 5  # 1-10, higher is more priority
    created_at: str = ""
    status: str = "pending"  # pending, processing, completed, failed
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    processing_time: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

@dataclass
class BatchJobResult:
    """Result of batch processing job."""
    job_id: str
    status: str
    processing_time: float
    document_id: Optional[str] = None
    knowledge_graph_id: Optional[str] = None
    ipld_cid: Optional[str] = None
    entity_count: int = 0
    relationship_count: int = 0
    chunk_count: int = 0
    error_message: Optional[str] = None

@dataclass
class BatchStatus:
    """Overall batch processing status."""
    batch_id: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    pending_jobs: int
    processing_jobs: int
    start_time: str
    end_time: Optional[str] = None
    total_processing_time: float = 0.0
    average_job_time: float = 0.0
    throughput: float = 0.0  # documents per second
    resource_usage: Dict[str, Any] = None

class BatchProcessor:
    """
    Handles batch processing of multiple PDF documents.
    """
    
    def __init__(self,
                 max_workers: int = None,
                 max_memory_mb: int = 4096,
                 storage: Optional[IPLDStorage] = None,
                 enable_monitoring: bool = False,
                 enable_audit: bool = True):
        """
        Initialize the batch processor.
        
        Args:
            max_workers: Maximum number of worker processes
            max_memory_mb: Maximum memory usage in MB
            storage: IPLD storage instance
            enable_monitoring: Enable performance monitoring
            enable_audit: Enable audit logging
        """
        self.max_workers = max_workers or min(mp.cpu_count(), 8)
        self.max_memory_mb = max_memory_mb
        self.storage = storage or IPLDStorage()
        
        # Initialize monitoring and audit
        self.audit_logger = AuditLogger.get_instance() if enable_audit else None
        
        if enable_monitoring:
            from ..monitoring import MonitoringConfig, MetricsConfig
            config = MonitoringConfig()
            config.metrics = MetricsConfig(
                output_file="batch_processing_metrics.json",
                prometheus_export=True
            )
            self.monitoring = MonitoringSystem.initialize(config)
        else:
            self.monitoring = None
        
        # Processing components
        self.pdf_processor = PDFProcessor(storage=self.storage)
        self.llm_optimizer = LLMOptimizer()
        self.graphrag_integrator = GraphRAGIntegrator(storage=self.storage)
        
        # Job management
        self.job_queue: Queue = Queue()
        self.completed_jobs: List[BatchJobResult] = []
        self.failed_jobs: List[BatchJobResult] = []
        self.active_batches: Dict[str, BatchStatus] = {}
        
        # Worker management
        self.workers: List[threading.Thread] = []
        self.worker_pool: Optional[concurrent.futures.ProcessPoolExecutor] = None
        self.is_processing = False
        self.stop_event = threading.Event()
        
        # Performance tracking
        self.processing_stats = {
            'total_processed': 0,
            'total_failed': 0,
            'total_processing_time': 0.0,
            'peak_memory_usage': 0.0,
            'average_throughput': 0.0
        }
    
    async def process_batch(self,
                           pdf_paths: List[Union[str, Path]],
                           batch_metadata: Optional[Dict[str, Any]] = None,
                           priority: int = 5,
                           callback: Optional[Callable] = None) -> str:
        """
        Process a batch of PDF documents.
        
        Args:
            pdf_paths: List of PDF file paths to process
            batch_metadata: Metadata for the entire batch
            priority: Processing priority (1-10)
            callback: Optional callback function for progress updates
            
        Returns:
            Batch ID for tracking progress
        """
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        
        logger.info(f"Starting batch processing: {batch_id} with {len(pdf_paths)} documents")
        
        # Create batch status
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=len(pdf_paths),
            completed_jobs=0,
            failed_jobs=0,
            pending_jobs=len(pdf_paths),
            processing_jobs=0,
            start_time=datetime.utcnow().isoformat()
        )
        self.active_batches[batch_id] = batch_status
        
        # Create processing jobs
        jobs = []
        for i, pdf_path in enumerate(pdf_paths):
            job = ProcessingJob(
                job_id=f"{batch_id}_job_{i:04d}",
                pdf_path=str(pdf_path),
                metadata={
                    'batch_id': batch_id,
                    'batch_metadata': batch_metadata or {},
                    'job_index': i
                },
                priority=priority
            )
            jobs.append(job)
            self.job_queue.put(job)
        
        # Audit logging
        if self.audit_logger:
            self.audit_logger.data_access(
                "batch_processing_start",
                resource_id=batch_id,
                resource_type="pdf_batch",
                metadata={'job_count': len(jobs)}
            )
        
        # Start processing if not already running
        if not self.is_processing:
            await self._start_workers()
        
        # Monitor progress
        if callback:
            asyncio.create_task(self._monitor_batch_progress(batch_id, callback))
        
        return batch_id
    
    async def _start_workers(self):
        """Start worker threads for batch processing."""
        if self.is_processing:
            return
        
        self.is_processing = True
        self.stop_event.clear()
        
        logger.info(f"Starting {self.max_workers} worker threads")
        
        # Create worker threads
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(f"worker_{i}",),
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
        
        # Create process pool for CPU-intensive tasks
        self.worker_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=min(self.max_workers, mp.cpu_count())
        )
    
    def _worker_loop(self, worker_name: str):
        """Main worker loop for processing jobs."""
        logger.info(f"Worker {worker_name} started")
        
        while not self.stop_event.is_set():
            try:
                # Get job from queue with timeout
                job = self.job_queue.get(timeout=1.0)
                
                if job is None:  # Shutdown signal
                    break
                
                # Process job
                result = asyncio.run(self._process_single_job(job, worker_name))
                
                # Update batch status
                self._update_batch_status(job, result)
                
                # Mark queue task as done
                self.job_queue.task_done()
                
            except Queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker {worker_name} error: {e}")
                continue
        
        logger.info(f"Worker {worker_name} stopped")
    
    async def _process_single_job(self, job: ProcessingJob, worker_name: str) -> BatchJobResult:
        """Process a single PDF document job."""
        start_time = time.time()
        job.status = "processing"
        
        logger.info(f"Worker {worker_name} processing {job.job_id}: {job.pdf_path}")
        
        # Performance monitoring
        if self.monitoring:
            operation_context = self.monitoring.track_operation(
                "batch_pdf_processing",
                tags=["batch", "pdf", job.job_id]
            )
        else:
            operation_context = None
        
        try:
            with operation_context if operation_context else nullcontext():
                # Stage 1: PDF Processing
                pdf_result = await self.pdf_processor.process_pdf(
                    job.pdf_path,
                    metadata=job.metadata
                )
                
                if pdf_result.get('status') != 'success':
                    raise Exception(f"PDF processing failed: {pdf_result.get('message', 'Unknown error')}")
                
                # Stage 2: LLM Optimization
                llm_document = await self.llm_optimizer.optimize_for_llm(
                    pdf_result['decomposed_content'],
                    pdf_result['metadata']
                )
                
                # Stage 3: GraphRAG Integration
                knowledge_graph = await self.graphrag_integrator.integrate_document(llm_document)
                
                processing_time = time.time() - start_time
                
                # Create successful result
                result = BatchJobResult(
                    job_id=job.job_id,
                    status="completed",
                    processing_time=processing_time,
                    document_id=llm_document.document_id,
                    knowledge_graph_id=knowledge_graph.graph_id,
                    ipld_cid=knowledge_graph.ipld_cid,
                    entity_count=len(knowledge_graph.entities),
                    relationship_count=len(knowledge_graph.relationships),
                    chunk_count=len(knowledge_graph.chunks)
                )
                
                self.completed_jobs.append(result)
                self.processing_stats['total_processed'] += 1
                self.processing_stats['total_processing_time'] += processing_time
                
                logger.info(f"Job {job.job_id} completed in {processing_time:.2f}s")
                return result
                
        except Exception as e:
            processing_time = time.time() - start_time
            error_message = str(e)
            
            logger.error(f"Job {job.job_id} failed: {error_message}")
            
            # Create failed result
            result = BatchJobResult(
                job_id=job.job_id,
                status="failed",
                processing_time=processing_time,
                error_message=error_message
            )
            
            self.failed_jobs.append(result)
            self.processing_stats['total_failed'] += 1
            
            # Audit logging for failure
            if self.audit_logger:
                self.audit_logger.error(
                    "batch_job_failed",
                    resource_id=job.job_id,
                    resource_type="pdf_processing_job",
                    metadata={'error': error_message}
                )
            
            return result
    
    def _update_batch_status(self, job: ProcessingJob, result: BatchJobResult):
        """Update batch status based on job result."""
        batch_id = job.metadata.get('batch_id')
        if not batch_id or batch_id not in self.active_batches:
            return
        
        batch_status = self.active_batches[batch_id]
        
        if result.status == "completed":
            batch_status.completed_jobs += 1
        elif result.status == "failed":
            batch_status.failed_jobs += 1
        
        batch_status.pending_jobs = max(0, batch_status.pending_jobs - 1)
        batch_status.total_processing_time += result.processing_time
        
        # Calculate metrics
        total_finished = batch_status.completed_jobs + batch_status.failed_jobs
        if total_finished > 0:
            batch_status.average_job_time = batch_status.total_processing_time / total_finished
        
        # Check if batch is complete
        if total_finished >= batch_status.total_jobs:
            batch_status.end_time = datetime.utcnow().isoformat()
            
            # Calculate throughput
            start_dt = datetime.fromisoformat(batch_status.start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(batch_status.end_time.replace('Z', '+00:00'))
            duration = (end_dt - start_dt).total_seconds()
            
            if duration > 0:
                batch_status.throughput = batch_status.completed_jobs / duration
            
            logger.info(f"Batch {batch_id} completed: {batch_status.completed_jobs}/{batch_status.total_jobs} successful")
    
    async def _monitor_batch_progress(self, batch_id: str, callback: Callable):
        """Monitor batch progress and call callback function."""
        while batch_id in self.active_batches:
            batch_status = self.active_batches[batch_id]
            
            # Call progress callback
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(batch_status)
                else:
                    callback(batch_status)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
            
            # Check if batch is complete
            total_finished = batch_status.completed_jobs + batch_status.failed_jobs
            if total_finished >= batch_status.total_jobs:
                break
            
            # Wait before next update
            await asyncio.sleep(5.0)
    
    async def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific batch."""
        if batch_id not in self.active_batches:
            return None
        
        batch_status = self.active_batches[batch_id]
        
        # Get resource usage
        resource_usage = self._get_resource_usage()
        batch_status.resource_usage = resource_usage
        
        return asdict(batch_status)
    
    async def list_active_batches(self) -> List[Dict[str, Any]]:
        """List all active batches."""
        active_batches = []
        
        for batch_id, batch_status in self.active_batches.items():
            # Only include batches that are not complete
            total_finished = batch_status.completed_jobs + batch_status.failed_jobs
            if total_finished < batch_status.total_jobs:
                batch_dict = asdict(batch_status)
                batch_dict['resource_usage'] = self._get_resource_usage()
                active_batches.append(batch_dict)
        
        return active_batches
    
    async def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch processing job."""
        if batch_id not in self.active_batches:
            return False
        
        logger.info(f"Canceling batch {batch_id}")
        
        # Mark batch as cancelled
        batch_status = self.active_batches[batch_id]
        batch_status.end_time = datetime.utcnow().isoformat()
        
        # Remove pending jobs for this batch
        remaining_jobs = []
        cancelled_count = 0
        
        try:
            while True:
                job = self.job_queue.get_nowait()
                if job.metadata.get('batch_id') == batch_id:
                    cancelled_count += 1
                else:
                    remaining_jobs.append(job)
        except Queue.Empty:
            pass
        
        # Put back non-cancelled jobs
        for job in remaining_jobs:
            self.job_queue.put(job)
        
        logger.info(f"Cancelled {cancelled_count} pending jobs for batch {batch_id}")
        
        # Audit logging
        if self.audit_logger:
            self.audit_logger.data_access(
                "batch_processing_cancelled",
                resource_id=batch_id,
                resource_type="pdf_batch",
                metadata={'cancelled_jobs': cancelled_count}
            )
        
        return True
    
    async def stop_processing(self, timeout: float = 30.0):
        """Stop all batch processing."""
        if not self.is_processing:
            return
        
        logger.info("Stopping batch processing...")
        
        # Signal workers to stop
        self.stop_event.set()
        
        # Add None jobs to wake up workers
        for _ in range(len(self.workers)):
            self.job_queue.put(None)
        
        # Wait for workers to finish
        start_time = time.time()
        for worker in self.workers:
            remaining_time = timeout - (time.time() - start_time)
            if remaining_time > 0:
                worker.join(timeout=remaining_time)
        
        # Shutdown process pool
        if self.worker_pool:
            self.worker_pool.shutdown(wait=True, timeout=timeout)
            self.worker_pool = None
        
        self.workers.clear()
        self.is_processing = False
        
        logger.info("Batch processing stopped")
    
    def _get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage statistics."""
        import psutil
        
        process = psutil.Process()
        
        # Memory usage
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        
        # CPU usage
        cpu_percent = process.cpu_percent()
        
        # Worker thread count
        active_workers = len([w for w in self.workers if w.is_alive()])
        
        return {
            'memory_mb': memory_info.rss / 1024 / 1024,
            'memory_percent': memory_percent,
            'cpu_percent': cpu_percent,
            'active_workers': active_workers,
            'queue_size': self.job_queue.qsize(),
            'peak_memory_mb': self.processing_stats.get('peak_memory_usage', 0)
        }
    
    async def get_processing_statistics(self) -> Dict[str, Any]:
        """Get overall processing statistics."""
        total_jobs = self.processing_stats['total_processed'] + self.processing_stats['total_failed']
        
        stats = {
            'total_processed': self.processing_stats['total_processed'],
            'total_failed': self.processing_stats['total_failed'],
            'total_jobs': total_jobs,
            'success_rate': self.processing_stats['total_processed'] / total_jobs if total_jobs > 0 else 0,
            'total_processing_time': self.processing_stats['total_processing_time'],
            'average_job_time': (
                self.processing_stats['total_processing_time'] / self.processing_stats['total_processed']
                if self.processing_stats['total_processed'] > 0 else 0
            ),
            'active_batches': len(self.active_batches),
            'completed_jobs_count': len(self.completed_jobs),
            'failed_jobs_count': len(self.failed_jobs),
            'resource_usage': self._get_resource_usage()
        }
        
        return stats
    
    async def export_batch_results(self, 
                                  batch_id: str,
                                  format: str = "json",
                                  output_path: Optional[str] = None) -> str:
        """
        Export batch results to file.
        
        Args:
            batch_id: Batch ID to export
            format: Export format ('json', 'csv')
            output_path: Output file path
            
        Returns:
            Path to exported file
        """
        if batch_id not in self.active_batches:
            raise ValueError(f"Batch {batch_id} not found")
        
        batch_status = self.active_batches[batch_id]
        
        # Collect all results for this batch
        batch_results = []
        
        for result in self.completed_jobs + self.failed_jobs:
            # Check if result belongs to this batch
            for job in []:  # Would need to track jobs differently
                if job.metadata.get('batch_id') == batch_id:
                    batch_results.append(result)
                    break
        
        # Generate output path if not provided
        if not output_path:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = f"batch_results_{batch_id}_{timestamp}.{format}"
        
        output_path = Path(output_path)
        
        # Export based on format
        if format.lower() == 'json':
            export_data = {
                'batch_id': batch_id,
                'batch_status': asdict(batch_status),
                'results': [asdict(result) for result in batch_results],
                'export_timestamp': datetime.utcnow().isoformat()
            }
            
            with open(output_path, 'w') as f:
                json.dump(export_data, f, indent=2)
        
        elif format.lower() == 'csv':
            import csv
            
            with open(output_path, 'w', newline='') as f:
                if batch_results:
                    fieldnames = list(asdict(batch_results[0]).keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for result in batch_results:
                        writer.writerow(asdict(result))
        
        else:
            raise ValueError(f"Unsupported export format: {format}")
        
        logger.info(f"Batch results exported to {output_path}")
        return str(output_path)

# Utility functions for batch processing
async def process_directory_batch(directory_path: str,
                                 batch_processor: BatchProcessor,
                                 file_pattern: str = "*.pdf",
                                 max_files: Optional[int] = None) -> str:
    """
    Process all PDF files in a directory as a batch.
    
    Args:
        directory_path: Directory containing PDF files
        batch_processor: BatchProcessor instance
        file_pattern: File pattern to match
        max_files: Maximum number of files to process
        
    Returns:
        Batch ID
    """
    directory = Path(directory_path)
    
    if not directory.exists():
        raise ValueError(f"Directory does not exist: {directory_path}")
    
    # Find PDF files
    pdf_files = list(directory.glob(file_pattern))
    
    if max_files:
        pdf_files = pdf_files[:max_files]
    
    if not pdf_files:
        raise ValueError(f"No PDF files found in {directory_path}")
    
    logger.info(f"Found {len(pdf_files)} PDF files for batch processing")
    
    # Start batch processing
    batch_id = await batch_processor.process_batch(
        pdf_files,
        batch_metadata={
            'source_directory': str(directory),
            'file_pattern': file_pattern,
            'total_files_found': len(pdf_files)
        }
    )
    
    return batch_id

from contextlib import nullcontext
