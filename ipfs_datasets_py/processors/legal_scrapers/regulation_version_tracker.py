"""
Historical Regulation Tracking and Version Management.

This module provides tracking and management of regulation versions over time,
including change detection, temporal queries, compliance date tracking, and
timeline visualization.

Features:
- RegulationVersionTracker for tracking changes
- Version detection and diffing
- Temporal queries (regulations as of date)
- Change notification system
- Version history storage
- Compliance date tracking
- Timeline visualization

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import RegulationVersionTracker
    
    tracker = RegulationVersionTracker()
    
    # Track regulation versions
    tracker.add_version(regulation_id, content, effective_date)
    
    # Get version at specific date
    version = tracker.get_version_at_date(regulation_id, date)
    
    # Get changes between versions
    changes = tracker.get_changes(regulation_id, from_date, to_date)
"""

import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, date
from difflib import unified_diff
import hashlib
import json

logger = logging.getLogger(__name__)


@dataclass
class RegulationVersion:
    """A specific version of a regulation."""
    regulation_id: str
    version_id: str
    content: str
    effective_date: datetime
    end_date: Optional[datetime] = None
    title: str = ""
    source_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    
    def __post_init__(self):
        """Calculate content hash if not provided."""
        if not self.content_hash and self.content:
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]


@dataclass
class RegulationChange:
    """Change between two regulation versions."""
    regulation_id: str
    from_version: str
    to_version: str
    from_date: datetime
    to_date: datetime
    change_type: str  # "added", "modified", "deleted"
    diff: str = ""
    summary: str = ""


class RegulationVersionTracker:
    """
    Track and manage regulation versions over time.
    
    Provides comprehensive version tracking:
    - Add and manage regulation versions
    - Temporal queries (get version at specific date)
    - Change detection and diffing
    - Compliance date tracking
    - Timeline visualization
    
    Example:
        >>> tracker = RegulationVersionTracker()
        >>> tracker.add_version("EPA-001", content, datetime(2020, 1, 1))
        >>> version = tracker.get_version_at_date("EPA-001", datetime(2021, 6, 1))
        >>> changes = tracker.get_changes("EPA-001", start_date, end_date)
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """Initialize version tracker.
        
        Args:
            storage_path: Optional path for persistent storage
        """
        self.storage_path = storage_path
        self.versions: Dict[str, List[RegulationVersion]] = {}
        self.compliance_dates: Dict[str, List[datetime]] = {}
        
        logger.info("RegulationVersionTracker initialized")
    
    def add_version(
        self,
        regulation_id: str,
        content: str,
        effective_date: datetime,
        title: str = "",
        source_url: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> RegulationVersion:
        """
        Add a new version of a regulation.
        
        Args:
            regulation_id: Unique regulation identifier
            content: Content of the regulation
            effective_date: Date this version became effective
            title: Title of the regulation
            source_url: Source URL
            metadata: Additional metadata
            
        Returns:
            RegulationVersion
        """
        # Generate version ID
        version_id = f"v{len(self.versions.get(regulation_id, []))  + 1}"
        
        version = RegulationVersion(
            regulation_id=regulation_id,
            version_id=version_id,
            content=content,
            effective_date=effective_date,
            title=title,
            source_url=source_url,
            metadata=metadata or {}
        )
        
        # Add to versions
        if regulation_id not in self.versions:
            self.versions[regulation_id] = []
        
        self.versions[regulation_id].append(version)
        
        # Sort versions by effective date
        self.versions[regulation_id].sort(key=lambda v: v.effective_date)
        
        # Update end dates
        self._update_end_dates(regulation_id)
        
        logger.info(f"Added version {version_id} for {regulation_id}")
        
        return version
    
    def _update_end_dates(self, regulation_id: str):
        """Update end dates for versions."""
        versions = self.versions.get(regulation_id, [])
        
        for i, version in enumerate(versions[:-1]):
            version.end_date = versions[i + 1].effective_date
        
        # Last version has no end date (current)
        if versions:
            versions[-1].end_date = None
    
    def get_version_at_date(
        self,
        regulation_id: str,
        query_date: datetime
    ) -> Optional[RegulationVersion]:
        """
        Get version of regulation at specific date.
        
        Args:
            regulation_id: Regulation identifier
            query_date: Date to query
            
        Returns:
            RegulationVersion at that date, or None
        """
        versions = self.versions.get(regulation_id, [])
        
        if not versions:
            return None
        
        # Find version effective at query_date
        for version in reversed(versions):
            if version.effective_date <= query_date:
                return version
        
        return None
    
    def get_all_versions(
        self,
        regulation_id: str
    ) -> List[RegulationVersion]:
        """Get all versions of a regulation."""
        return self.versions.get(regulation_id, [])
    
    def get_latest_version(
        self,
        regulation_id: str
    ) -> Optional[RegulationVersion]:
        """Get latest version of regulation."""
        versions = self.versions.get(regulation_id, [])
        return versions[-1] if versions else None
    
    def get_changes(
        self,
        regulation_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> List[RegulationChange]:
        """
        Get changes between versions in date range.
        
        Args:
            regulation_id: Regulation identifier
            from_date: Start date (first version if None)
            to_date: End date (latest version if None)
            
        Returns:
            List of RegulationChange objects
        """
        versions = self.versions.get(regulation_id, [])
        
        if len(versions) < 2:
            return []
        
        # Filter versions by date range
        if from_date or to_date:
            filtered_versions = []
            for v in versions:
                if from_date and v.effective_date < from_date:
                    continue
                if to_date and v.effective_date > to_date:
                    continue
                filtered_versions.append(v)
            versions = filtered_versions
        
        if len(versions) < 2:
            return []
        
        # Generate changes between consecutive versions
        changes = []
        
        for i in range(len(versions) - 1):
            from_version = versions[i]
            to_version = versions[i + 1]
            
            # Generate diff
            diff = self._generate_diff(from_version.content, to_version.content)
            
            # Detect change type
            change_type = "modified"
            if not from_version.content:
                change_type = "added"
            elif not to_version.content:
                change_type = "deleted"
            
            change = RegulationChange(
                regulation_id=regulation_id,
                from_version=from_version.version_id,
                to_version=to_version.version_id,
                from_date=from_version.effective_date,
                to_date=to_version.effective_date,
                change_type=change_type,
                diff=diff,
                summary=self._summarize_changes(diff)
            )
            
            changes.append(change)
        
        return changes
    
    def _generate_diff(self, old_content: str, new_content: str) -> str:
        """Generate unified diff between contents."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff_lines = unified_diff(
            old_lines,
            new_lines,
            fromfile="old",
            tofile="new",
            lineterm=""
        )
        
        return "".join(diff_lines)
    
    def _summarize_changes(self, diff: str) -> str:
        """Generate summary of changes from diff."""
        lines = diff.split("\n")
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        
        return f"{added} lines added, {removed} lines removed"
    
    def add_compliance_date(
        self,
        regulation_id: str,
        compliance_date: datetime,
        description: str = ""
    ):
        """
        Add compliance date for regulation.
        
        Args:
            regulation_id: Regulation identifier
            compliance_date: Date compliance is required
            description: Description of compliance requirement
        """
        if regulation_id not in self.compliance_dates:
            self.compliance_dates[regulation_id] = []
        
        self.compliance_dates[regulation_id].append({
            "date": compliance_date,
            "description": description
        })
        
        logger.info(f"Added compliance date for {regulation_id}: {compliance_date}")
    
    def get_upcoming_compliance_dates(
        self,
        days_ahead: int = 90
    ) -> List[Dict[str, Any]]:
        """
        Get upcoming compliance dates within specified days.
        
        Args:
            days_ahead: Number of days to look ahead
            
        Returns:
            List of compliance dates
        """
        from datetime import timedelta
        
        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)
        
        upcoming = []
        
        for regulation_id, dates in self.compliance_dates.items():
            for date_info in dates:
                compliance_date = date_info["date"]
                if now <= compliance_date <= cutoff:
                    upcoming.append({
                        "regulation_id": regulation_id,
                        "compliance_date": compliance_date,
                        "days_until": (compliance_date - now).days,
                        "description": date_info.get("description", "")
                    })
        
        # Sort by date
        upcoming.sort(key=lambda x: x["compliance_date"])
        
        return upcoming
    
    def generate_timeline(
        self,
        regulation_id: str,
        format: str = "text"
    ) -> str:
        """
        Generate timeline visualization for regulation.
        
        Args:
            regulation_id: Regulation identifier
            format: Output format ("text", "mermaid", "json")
            
        Returns:
            Timeline visualization
        """
        versions = self.versions.get(regulation_id, [])
        
        if not versions:
            return "No versions found"
        
        if format == "text":
            return self._generate_text_timeline(regulation_id, versions)
        elif format == "mermaid":
            return self._generate_mermaid_timeline(regulation_id, versions)
        elif format == "json":
            return self._generate_json_timeline(regulation_id, versions)
        else:
            return f"Unsupported format: {format}"
    
    def _generate_text_timeline(
        self,
        regulation_id: str,
        versions: List[RegulationVersion]
    ) -> str:
        """Generate text timeline."""
        lines = [f"Timeline for {regulation_id}:", ""]
        
        for version in versions:
            date_str = version.effective_date.strftime("%Y-%m-%d")
            lines.append(f"{date_str} - {version.version_id}")
            if version.title:
                lines.append(f"  Title: {version.title}")
            if version.content_hash:
                lines.append(f"  Hash: {version.content_hash}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _generate_mermaid_timeline(
        self,
        regulation_id: str,
        versions: List[RegulationVersion]
    ) -> str:
        """Generate Mermaid timeline."""
        lines = ["gantt"]
        lines.append(f"    title {regulation_id} Version Timeline")
        lines.append("    dateFormat YYYY-MM-DD")
        
        for version in versions:
            start = version.effective_date.strftime("%Y-%m-%d")
            end = version.end_date.strftime("%Y-%m-%d") if version.end_date else "2099-12-31"
            lines.append(f"    {version.version_id} :{start}, {end}")
        
        return "\n".join(lines)
    
    def _generate_json_timeline(
        self,
        regulation_id: str,
        versions: List[RegulationVersion]
    ) -> str:
        """Generate JSON timeline."""
        timeline = {
            "regulation_id": regulation_id,
            "versions": [
                {
                    "version_id": v.version_id,
                    "effective_date": v.effective_date.isoformat(),
                    "end_date": v.end_date.isoformat() if v.end_date else None,
                    "title": v.title,
                    "content_hash": v.content_hash
                }
                for v in versions
            ]
        }
        
        return json.dumps(timeline, indent=2)
    
    def export_history(
        self,
        regulation_id: str,
        include_content: bool = False
    ) -> Dict[str, Any]:
        """
        Export complete history of regulation.
        
        Args:
            regulation_id: Regulation identifier
            include_content: Whether to include full content
            
        Returns:
            History dictionary
        """
        versions = self.versions.get(regulation_id, [])
        changes = self.get_changes(regulation_id)
        compliance = self.compliance_dates.get(regulation_id, [])
        
        history = {
            "regulation_id": regulation_id,
            "version_count": len(versions),
            "versions": [
                {
                    "version_id": v.version_id,
                    "effective_date": v.effective_date.isoformat(),
                    "end_date": v.end_date.isoformat() if v.end_date else None,
                    "title": v.title,
                    "source_url": v.source_url,
                    "content_hash": v.content_hash,
                    "content": v.content if include_content else None
                }
                for v in versions
            ],
            "changes": [
                {
                    "from_version": c.from_version,
                    "to_version": c.to_version,
                    "from_date": c.from_date.isoformat(),
                    "to_date": c.to_date.isoformat(),
                    "change_type": c.change_type,
                    "summary": c.summary
                }
                for c in changes
            ],
            "compliance_dates": [
                {
                    "date": d["date"].isoformat(),
                    "description": d.get("description", "")
                }
                for d in compliance
            ]
        }
        
        return history
