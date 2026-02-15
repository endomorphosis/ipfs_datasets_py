"""
Batch result module for the Omni-Converter.

This module provides the BatchResult class for tracking the results of batch processing operations.
"""
from dataclasses import dataclass, field
from datetime import datetime


from types_ import Any, Optional, ProcessingResult


@dataclass
class BatchResult:
    """
    Result of batch processing multiple files.
    
    This class represents the result of processing a batch of files, including overall
    statistics and individual file results.

    Attributes:
        total_files (int): Total number of files in the batch.
        successful_files (int): Number of files processed successfully.
        failed_files (int): Number of files that failed processing.
        results (list[ProcessingResult]): list of individual file processing results.
        statistics (dict[str, Any]): Additional statistics about the batch processing.
        start_time (datetime): Time when the batch processing started.
        end_time (datetime): Time when the batch processing ended.

    Methods:
        add_result(result): Add a processing result to the batch.
        mark_as_complete(): Mark the batch processing as complete.
        get_summary(): Get a summary dictionary of the batch processing.
        get_failed_files(): Get list of files that failed processing.
        get_successful_files(): Get list of successfully processed files.
        to_dict(): Convert to dictionary representation.
    """
    results: list[ProcessingResult] = field(default_factory=list)
    statistics: dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    total_files: int = field(init=False)
    successful_files: int = field(init=False)
    failed_files: int = field(init=False)
    
    def __post_init__(self):
        # Handle start_time if it's a timestamp
        if not isinstance(self.start_time, datetime):
            self.start_time = datetime.fromtimestamp(self.start_time)
        
        # Calculate counts
        self.total_files = len(self.results)
        self.successful_files = sum(1 for r in self.results if r.success)
        self.failed_files = sum(1 for r in self.results if not r.success)
    
    def add_result(self, result: ProcessingResult) -> None:
        """
        Add a file processing result to the batch.
        
        Args:
            result: The file processing result to add.
            
        Raises:
            ValueError: If result is None.
            AttributeError: If result is missing required attributes.
        """
        # Validate input
        if result is None:
            raise ValueError("Cannot add None result to batch")
        
        # Validate that result has required attributes
        required_attrs = ['success', 'file_path']
        for attr in required_attrs:
            if not hasattr(result, attr):
                raise AttributeError(f"ProcessingResult must have '{attr}' attribute")
        
        # Validate that result has required methods
        if not hasattr(result, 'to_dict') or not callable(getattr(result, 'to_dict')):
            raise AttributeError("ProcessingResult must have callable 'to_dict' method")
        
        self.results.append(result)
        
        # Update counts
        self.total_files += 1
        if result.success:
            self.successful_files += 1
        else:
            self.failed_files += 1
    
    def mark_as_complete(self) -> None:
        """Mark the batch processing as complete."""
        # Only set end_time if it hasn't been set already
        if self.end_time is None:
            self.end_time = datetime.now()
            
            # Update statistics only when actually completing
            self.statistics['duration_seconds'] = (self.end_time - self.start_time).total_seconds()
            self.statistics['success_rate'] = (
                (self.successful_files / self.total_files) * 100 if self.total_files > 0 else 0
            )
    
    def get_summary(self) -> dict[str, Any]:
        """
        Get a summary of the batch processing.
        
        Returns:
            A dictionary with summary information.
        """
        summary = {
            'total_files': self.total_files,
            'successful_files': self.successful_files,
            'failed_files': self.failed_files,
            'success_rate_percent': (
                (self.successful_files / self.total_files) * 100 if self.total_files > 0 else 0
            ),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'statistics': self.statistics
        }
        
        # Add duration and status based on completion state
        if self.end_time:
            summary['duration_seconds'] = (self.end_time - self.start_time).total_seconds()
            summary['duration'] = summary['duration_seconds']  # For backward compatibility
            summary['success_rate'] = summary['success_rate_percent']  # For backward compatibility
        else:
            current_time = datetime.now()
            summary['duration_seconds'] = (current_time - self.start_time).total_seconds()
            summary['duration'] = summary['duration_seconds']  # For backward compatibility
            summary['status'] = 'in_progress'
            summary['success_rate'] = summary['success_rate_percent']  # For backward compatibility
            
        return summary
    
    def get_failed_files(self) -> list[str]:
        """
        Get a list of files that failed processing.
        
        Returns:
            A list of paths to failed files.
        """
        return [r.file_path for r in self.results if not r.success]
    
    def get_successful_files(self) -> list[str]:
        """
        Get a list of files that were processed successfully.
        
        Returns:
            A list of paths to successfully processed files.
        """
        return [r.file_path for r in self.results if r.success]
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a dictionary.
        
        Returns:
            A dictionary representation of the batch result with keys:
            - total_files: Total number of files processed
            - successful_files: Number of successfully processed files
            - failed_files: Number of files that failed processing
            - results: List of individual ProcessingResult dictionaries
            - statistics: Additional batch processing statistics
            - start_time: ISO format timestamp when processing started
            - end_time: ISO format timestamp when processing ended (or None if in progress)
        """
        return {
            'total_files': self.total_files,
            'successful_files': self.successful_files,
            'failed_files': self.failed_files,
            'results': [r.to_dict() for r in self.results],
            'statistics': self.statistics,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None
        }
    
    def __str__(self) -> str:
        """
        Get a string representation of the batch result.
        
        Returns:
            A string representation of the batch result.
        """
        duration = (
            (self.end_time - self.start_time).total_seconds() 
            if self.end_time and self.start_time else None
        )
        
        success_rate = (
            f"{(self.successful_files / self.total_files) * 100:.1f}%" 
            if self.total_files > 0 else "N/A"
        )
        
        if duration is not None:
            duration_str = f"  Duration: {duration:.2f} seconds"
        else:
            duration_str = "  Status: In Progress"
        
        return (
            f"Batch Processing Result:\n"
            f"  Total Files: {self.total_files}\n"
            f"  Successful: {self.successful_files}\n"
            f"  Failed: {self.failed_files}\n"
            f"  Success Rate: {success_rate}\n"
            f"{duration_str}"
        )