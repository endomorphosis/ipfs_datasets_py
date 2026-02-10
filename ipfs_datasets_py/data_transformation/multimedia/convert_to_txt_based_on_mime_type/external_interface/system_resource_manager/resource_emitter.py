from typing import Callable, List, Any
from .resource_packet import ResourcePacket

class ResourceEmitter:
    """
    Interface for emitting resource updates and notifications.
    
    This class provides methods for broadcasting resource availability updates
    and subscribing to resource-related events.
    """

    def emit_update(self, resources: ResourcePacket) -> None:
        """
        Broadcast an update about current resource availability to the External Resource Manager.
        
        Args:
            resources: ResourcePacket containing the current resource state
        """
        pass

    def emit_warning(self, message: str) -> None:
        """
        Broadcast a warning about resource constraints or issues to the .
        
        Args:
            message: Warning message describing the resource issue
        """
        pass

    def subscribeToResourceUpdates(self, callback: Callable[[ResourcePacket], None]) -> None:
        """
        Register a callback function to be notified of resource updates.
        
        Args:
            callback: Function to call when resource updates occur,
                     accepting a ResourcePacket parameter
        """
        pass

