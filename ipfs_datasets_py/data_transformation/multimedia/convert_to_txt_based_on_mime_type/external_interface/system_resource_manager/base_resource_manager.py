from typing import Optional, Tuple, Dict, Any, TypeVar


from .resource_config import SystemResources
from .resource_packet import ResourcePacket


Injectable = TypeVar('Injectable', bound=Any)

hardware_resources = {}

class BaseResourceManager:
    """
    Base class implementing common resource management logic.
    
    This abstract base class provides the core functionality for tracking and
    managing system resources. It handles resource allocation requests, releases,
    and tracking available resources according to configured constraints.
    """
    
    def __init__(self, resources, configs):
        """
        Initialize the base resource manager with configuration.
        
        Args:
            config: ResourceConfig object containing resource limits and settings
        """
        self.configs = configs
        self.resources = resources

        self._recalculate_total_and_available_resources = self.resources['recalculate_total_and_available_resources']
        self._attempt_to_allocate_requested_resources = self.resources['attempt_to_allocate_requested_resources']
        self._release_previously_allocated_resources = self.resources['release_previously_allocated_resources']
        self._get_currently_available_resources = self.resources['get_currently_available_resources']

        self.total_resources = ResourcePacket(0, 0, 0, 0)
        self.available_resources = ResourcePacket(0, 0, 0, 0)
    
    def recalculate_total_and_available_resources(self) -> None:
        """
        Update the total and available resource calculations.
        
        This method should be called periodically to refresh the resource statistics
        based on current system state.
        """
        pass
    
    def attempt_to_allocate_requested_resources(self, request: ResourcePacket) -> Tuple[bool, Optional[ResourcePacket]]:
        """
        Attempt to allocate the requested resources.
        
        Args:
            request: ResourcePacket specifying the resources being requested
            
        Returns:
            Tuple containing:
            - Success flag (True if resources were successfully allocated)
            - ResourcePacket of actually allocated resources (may differ from request
              if partial allocation was made)
        """
        if not self._validateRequest(request):
            return False, None
        
        # Implementation would handle allocation logic
        return True, request
    
    def release_previously_allocated_resources(self, resource_packet: ResourcePacket) -> bool:
        """
        Return previously allocated resources back to the available pool.
        
        Args:
            resources: ResourcePacket specifying the resources being released
            
        Returns:
            bool: True if resources were successfully released
        """
        # Implementation would return resources to the pool
        return True
    
    def get_currently_available_resources(self) -> ResourcePacket:
        """
        Get the current available resources.
        
        Returns:
            ResourcePacket: A snapshot of currently available system resources
        """
        return self.availableResources
    
    def _validate_resource_request(self, request_packet: ResourcePacket) -> bool:
        """
        Validate if a resource request can be fulfilled.
        
        Args:
            request: ResourcePacket to validate against available resources
            
        Returns:
            bool: True if the request is valid and can be fulfilled
        """
        # Implementation would check if requested resources are available
        return True