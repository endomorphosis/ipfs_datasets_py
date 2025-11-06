"""
Configuration for error reporting system.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ErrorReportingConfig:
    """Configuration for automatic error reporting to GitHub issues."""
    
    # Enable/disable error reporting
    enabled: bool = field(default_factory=lambda: os.getenv('ERROR_REPORTING_ENABLED', 'true').lower() == 'true')
    
    # GitHub configuration
    github_token: Optional[str] = field(default_factory=lambda: os.getenv('GITHUB_TOKEN'))
    github_repo: str = field(default_factory=lambda: os.getenv('GITHUB_REPOSITORY', 'endomorphosis/ipfs_datasets_py'))
    
    # Rate limiting configuration
    max_issues_per_hour: int = field(default_factory=lambda: int(os.getenv('ERROR_REPORTING_MAX_PER_HOUR', '10')))
    max_issues_per_day: int = field(default_factory=lambda: int(os.getenv('ERROR_REPORTING_MAX_PER_DAY', '50')))
    
    # Deduplication configuration
    dedup_window_hours: int = field(default_factory=lambda: int(os.getenv('ERROR_REPORTING_DEDUP_HOURS', '24')))
    
    # Error context configuration
    include_stack_trace: bool = field(default_factory=lambda: os.getenv('ERROR_REPORTING_INCLUDE_STACK', 'true').lower() == 'true')
    include_environment: bool = field(default_factory=lambda: os.getenv('ERROR_REPORTING_INCLUDE_ENV', 'true').lower() == 'true')
    include_logs: bool = field(default_factory=lambda: os.getenv('ERROR_REPORTING_INCLUDE_LOGS', 'true').lower() == 'true')
    max_log_lines: int = field(default_factory=lambda: int(os.getenv('ERROR_REPORTING_MAX_LOG_LINES', '100')))
    
    # Issue labels
    default_labels: list = field(default_factory=lambda: ['bug', 'auto-generated', 'runtime-error'])
    
    # Storage for deduplication tracking
    state_file: Path = field(default_factory=lambda: Path.home() / '.ipfs_datasets' / 'error_reporting_state.json')
    
    def __post_init__(self):
        """Ensure state directory exists."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
    
    def is_valid(self) -> bool:
        """Check if configuration is valid for creating issues."""
        return self.enabled and self.github_token is not None
    
    def get_repo_owner(self) -> str:
        """Extract repository owner from github_repo."""
        return self.github_repo.split('/')[0] if '/' in self.github_repo else ''
    
    def get_repo_name(self) -> str:
        """Extract repository name from github_repo."""
        return self.github_repo.split('/')[1] if '/' in self.github_repo else self.github_repo
