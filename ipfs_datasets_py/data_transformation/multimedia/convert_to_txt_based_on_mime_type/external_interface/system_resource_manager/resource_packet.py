from dataclasses import dataclass
from typing import Optional

@dataclass
class ResourcePacket:
    """
    A unified representation of system resources that can be allocated, tracked, and released.
    
    This dataclass encapsulates the core resources managed by the system: CPU cores,
    RAM, VRAM, and disk space. It serves as the standard unit of resource allocation
    and deallocation throughout the system.
    """
    cpu_cores: int
    ram_in_mb: int
    vram_in_mb: int
    disk_space_in_gb: int

    def request(self) -> bool:
        """
        Request allocation of the resources described in this packet.
        
        Returns:
            bool: True if the allocation was successful, False otherwise.
        """
        # Implementation would request the specified resources
        pass
    
    def release(self) -> bool:
        """
        Release the resources described in this packet back to the system.
        
        Returns:
            bool: True if the deallocation was successful, False otherwise.
        """
        # Implementation would release the specified resources
        pass