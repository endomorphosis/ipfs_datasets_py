from dataclasses import dataclass
from typing import Optional


from pydantic import BaseModel


class SystemResources(BaseModel):
    """
    Configuration settings for resource management constraints and behavior.
    
    This class defines the limits and behavior settings for the resource manager,
    including maximum allocations for various resources and policy options for
    resource management.
    """
    MAX_CPU_CORES: Optional[int] = None
    TOTAL_ALLOCATED_RAM: Optional[int] = None  # in GB
    TOTAL_ALLOCATED_VRAM: Optional[int] = None  # in GB
    TOTAL_ALLOCATED_DISK: Optional[int] = None  # in GB
    ENABLE_OVERCOMMIT: bool = False
