"""
Regulation Version Tracking MCP Tool.

This tool exposes the RegulationVersionTracker which provides historical
tracking of regulation versions, temporal queries, change detection, and
compliance date management.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.regulation_version_tracker
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


async def track_regulation_version(
    regulation_id: str,
    content: str,
    effective_date: str,
    title: Optional[str] = None,
    source_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Add a new version of a regulation to the tracking system.
    
    This is a thin wrapper around RegulationVersionTracker.add_version().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.regulation_version_tracker
    
    Features:
    - Track regulation versions over time
    - Automatic content hash generation
    - Change detection between versions
    - Metadata storage
    
    Args:
        regulation_id: Unique identifier for the regulation (e.g., "40-CFR-1.1", "EPA-001")
        content: Full text content of the regulation version
        effective_date: Date when version became effective (ISO format: "YYYY-MM-DD")
        title: Optional title of the regulation
        source_url: Optional URL to source document
        metadata: Optional additional metadata dictionary
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - regulation_id: The regulation identifier
        - version_id: Unique identifier for this version
        - effective_date: When version became effective
        - content_hash: Hash of the content for change detection
        - is_new_version: Whether this is a new version or duplicate
        - previous_version: Previous version info (if exists)
    
    Example:
        >>> result = await track_regulation_version(
        ...     regulation_id="40-CFR-122.1",
        ...     content="The full regulation text...",
        ...     effective_date="2024-01-15",
        ...     title="Water Pollution Standards"
        ... )
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import RegulationVersionTracker
        
        # Validate input
        if not regulation_id or not isinstance(regulation_id, str):
            return {
                "status": "error",
                "message": "regulation_id must be a non-empty string"
            }
        
        if not content or not isinstance(content, str):
            return {
                "status": "error",
                "message": "content must be a non-empty string"
            }
        
        if not effective_date:
            return {
                "status": "error",
                "message": "effective_date is required (ISO format: YYYY-MM-DD)"
            }
        
        # Parse date
        try:
            effective_dt = datetime.fromisoformat(effective_date)
        except ValueError as e:
            return {
                "status": "error",
                "message": f"Invalid date format. Use ISO format (YYYY-MM-DD): {str(e)}"
            }
        
        # Initialize tracker
        tracker = RegulationVersionTracker()
        
        # Add version
        version_result = tracker.add_version(
            regulation_id=regulation_id,
            content=content,
            effective_date=effective_dt,
            title=title or "",
            source_url=source_url or "",
            metadata=metadata or {}
        )
        
        return {
            "status": "success",
            "regulation_id": regulation_id,
            "version_id": version_result["version_id"],
            "effective_date": effective_date,
            "content_hash": version_result["content_hash"],
            "is_new_version": version_result["is_new_version"],
            "previous_version": version_result.get("previous_version"),
            "total_versions": version_result.get("total_versions", 1),
            "mcp_tool": "track_regulation_version"
        }
        
    except ImportError as e:
        logger.error(f"Import error in track_regulation_version: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in track_regulation_version MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "regulation_id": regulation_id
        }


async def get_regulation_at_date(
    regulation_id: str,
    query_date: str,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Get the version of a regulation that was effective on a specific date.
    
    This is a thin wrapper around RegulationVersionTracker.get_version_at_date().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.regulation_version_tracker
    
    Features:
    - Temporal queries (regulation as of specific date)
    - Retrieve historical versions
    - Compliance date verification
    
    Args:
        regulation_id: Unique identifier for the regulation
        query_date: Date to query (ISO format: "YYYY-MM-DD")
        include_metadata: Include full metadata in response (default: True)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - regulation_id: The regulation identifier
        - query_date: Date queried
        - version_id: Version identifier
        - effective_date: When version became effective
        - end_date: When version was superseded (if applicable)
        - title: Regulation title
        - content: Regulation content (if requested)
        - metadata: Additional metadata (if include_metadata=True)
    
    Example:
        >>> result = await get_regulation_at_date(
        ...     regulation_id="40-CFR-122.1",
        ...     query_date="2023-06-15"
        ... )
        >>> print(f"Version effective: {result['effective_date']}")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import RegulationVersionTracker
        
        if not regulation_id:
            return {
                "status": "error",
                "message": "regulation_id is required"
            }
        
        if not query_date:
            return {
                "status": "error",
                "message": "query_date is required (ISO format: YYYY-MM-DD)"
            }
        
        # Parse date
        try:
            query_dt = datetime.fromisoformat(query_date)
        except ValueError as e:
            return {
                "status": "error",
                "message": f"Invalid date format. Use ISO format (YYYY-MM-DD): {str(e)}"
            }
        
        # Initialize tracker
        tracker = RegulationVersionTracker()
        
        # Get version at date
        version = tracker.get_version_at_date(regulation_id, query_dt)
        
        if not version:
            return {
                "status": "error",
                "message": f"No version found for regulation '{regulation_id}' at date {query_date}",
                "regulation_id": regulation_id,
                "query_date": query_date
            }
        
        result = {
            "status": "success",
            "regulation_id": regulation_id,
            "query_date": query_date,
            "version_id": version.version_id,
            "effective_date": version.effective_date.isoformat(),
            "title": version.title,
            "content_hash": version.content_hash,
            "source_url": version.source_url
        }
        
        if version.end_date:
            result["end_date"] = version.end_date.isoformat()
        
        if include_metadata:
            result["content"] = version.content
            result["metadata"] = version.metadata
        
        result["mcp_tool"] = "get_regulation_at_date"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in get_regulation_at_date MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "regulation_id": regulation_id,
            "query_date": query_date
        }


async def get_regulation_changes(
    regulation_id: str,
    from_date: str,
    to_date: str,
    include_diff: bool = True,
    summary_only: bool = False
) -> Dict[str, Any]:
    """
    Get changes to a regulation between two dates.
    
    This is a thin wrapper around RegulationVersionTracker.get_changes().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.regulation_version_tracker
    
    Features:
    - Detect changes between versions
    - Generate unified diffs
    - Summarize change types
    - Timeline of changes
    
    Args:
        regulation_id: Unique identifier for the regulation
        from_date: Start date for change detection (ISO format: "YYYY-MM-DD")
        to_date: End date for change detection (ISO format: "YYYY-MM-DD")
        include_diff: Include detailed diff in response (default: True)
        summary_only: Return only change summary, not full details (default: False)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - regulation_id: The regulation identifier
        - from_date: Start date
        - to_date: End date
        - changes: List of changes between versions
        - total_changes: Number of changes detected
        - change_types: Distribution of change types (added, modified, deleted)
    
    Example:
        >>> changes = await get_regulation_changes(
        ...     regulation_id="40-CFR-122.1",
        ...     from_date="2023-01-01",
        ...     to_date="2024-01-01"
        ... )
        >>> print(f"Found {changes['total_changes']} changes")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import RegulationVersionTracker
        
        if not regulation_id:
            return {
                "status": "error",
                "message": "regulation_id is required"
            }
        
        # Parse dates
        try:
            from_dt = datetime.fromisoformat(from_date)
            to_dt = datetime.fromisoformat(to_date)
        except ValueError as e:
            return {
                "status": "error",
                "message": f"Invalid date format. Use ISO format (YYYY-MM-DD): {str(e)}"
            }
        
        if from_dt >= to_dt:
            return {
                "status": "error",
                "message": "from_date must be before to_date"
            }
        
        # Initialize tracker
        tracker = RegulationVersionTracker()
        
        # Get changes
        changes = tracker.get_changes(
            regulation_id=regulation_id,
            from_date=from_dt,
            to_date=to_dt,
            include_diff=include_diff
        )
        
        # Calculate statistics
        change_types = {}
        for change in changes:
            change_type = change.change_type
            change_types[change_type] = change_types.get(change_type, 0) + 1
        
        result = {
            "status": "success",
            "regulation_id": regulation_id,
            "from_date": from_date,
            "to_date": to_date,
            "total_changes": len(changes),
            "change_types": change_types
        }
        
        if not summary_only:
            result["changes"] = [
                {
                    "from_version": c.from_version,
                    "to_version": c.to_version,
                    "from_date": c.from_date.isoformat(),
                    "to_date": c.to_date.isoformat(),
                    "change_type": c.change_type,
                    "summary": c.summary,
                    "diff": c.diff if include_diff else None
                }
                for c in changes
            ]
        
        result["mcp_tool"] = "get_regulation_changes"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in get_regulation_changes MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "regulation_id": regulation_id
        }


async def get_regulation_timeline(
    regulation_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get complete version timeline for a regulation.
    
    Args:
        regulation_id: Unique identifier for the regulation
        start_date: Optional start date filter (ISO format: "YYYY-MM-DD")
        end_date: Optional end date filter (ISO format: "YYYY-MM-DD")
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - regulation_id: The regulation identifier
        - timeline: List of all versions with dates
        - total_versions: Total number of versions
        - first_version_date: Date of first tracked version
        - latest_version_date: Date of most recent version
        - average_update_interval: Average time between updates (in days)
    
    Example:
        >>> timeline = await get_regulation_timeline("40-CFR-122.1")
        >>> print(f"Tracked {timeline['total_versions']} versions")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import RegulationVersionTracker
        
        if not regulation_id:
            return {
                "status": "error",
                "message": "regulation_id is required"
            }
        
        # Parse optional dates
        start_dt = None
        end_dt = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
            except ValueError as e:
                return {
                    "status": "error",
                    "message": f"Invalid start_date format: {str(e)}"
                }
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
            except ValueError as e:
                return {
                    "status": "error",
                    "message": f"Invalid end_date format: {str(e)}"
                }
        
        # Initialize tracker
        tracker = RegulationVersionTracker()
        
        # Get timeline
        timeline = tracker.get_timeline(
            regulation_id=regulation_id,
            start_date=start_dt,
            end_date=end_dt
        )
        
        if not timeline:
            return {
                "status": "error",
                "message": f"No versions found for regulation '{regulation_id}'",
                "regulation_id": regulation_id
            }
        
        # Calculate statistics
        version_dates = [v["effective_date"] for v in timeline]
        first_date = min(version_dates)
        latest_date = max(version_dates)
        
        # Calculate average update interval
        if len(version_dates) > 1:
            sorted_dates = sorted(version_dates)
            intervals = [(sorted_dates[i+1] - sorted_dates[i]).days 
                        for i in range(len(sorted_dates) - 1)]
            avg_interval = sum(intervals) / len(intervals) if intervals else 0
        else:
            avg_interval = 0
        
        return {
            "status": "success",
            "regulation_id": regulation_id,
            "timeline": [
                {
                    "version_id": v["version_id"],
                    "effective_date": v["effective_date"].isoformat(),
                    "end_date": v["end_date"].isoformat() if v.get("end_date") else None,
                    "title": v.get("title", ""),
                    "content_hash": v["content_hash"]
                }
                for v in timeline
            ],
            "total_versions": len(timeline),
            "first_version_date": first_date.isoformat(),
            "latest_version_date": latest_date.isoformat(),
            "average_update_interval_days": round(avg_interval, 1),
            "mcp_tool": "get_regulation_timeline"
        }
        
    except Exception as e:
        logger.error(f"Error in get_regulation_timeline MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "regulation_id": regulation_id
        }
